import json
import os
import re
import threading
import time

from app.common.ffmpeg_paths import ensure_ffmpeg_on_path, resolve_ffmpeg
from app.common.my_logger import my_logger as logger
from app.data.models.drama_project import DramaProject

MODEL_ID = "iic/SenseVoiceSmall"
VAD_MODEL = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
MAX_SEGMENT_GAP_MS = 1000


def _safe_print(text: str, flush: bool = True):
    try:
        print(text, flush=flush)
    except Exception:
        pass


def _episode_sort_key(filename: str) -> tuple:
    """按集数数字排序：1.mp4、2.mp4…10.mp4，避免字典序把 10 排到 2 前面。"""
    stem = os.path.splitext(filename)[0]
    m = re.match(r"^(\d+)", stem)
    if m:
        return (0, int(m.group(1)), filename.lower())
    m = re.search(r"第\s*(\d+)\s*集", stem)
    if m:
        return (0, int(m.group(1)), filename.lower())
    m = re.search(r"(\d+)", stem)
    if m:
        return (1, int(m.group(1)), filename.lower())
    return (2, 0, filename.lower())


def _split_words_to_sentences(
    words: list[str],
    timestamps: list[list[int]],
    filename: str,
    max_gap_ms: int = MAX_SEGMENT_GAP_MS,
) -> list[dict]:
    """将 SenseVoice 逐字/词 CTC 时间戳聚合成与剪辑工程兼容的自然台词大句。"""
    from funasr.utils.postprocess_utils import rich_transcription_postprocess

    sentences = []
    curr_chars: list[str] = []
    curr_start: int | None = None
    curr_end: int | None = None

    end_puncs = set("。！？!?；;\n")
    all_puncs = set("。！？!?；;，,、 ")

    for w, ts in zip(words, timestamps):
        w_clean = rich_transcription_postprocess(w).strip()
        if not w_clean:
            continue

        s_ms, e_ms = ts[0], ts[1]

        # 停顿切分判断（静音间隔超过 max_gap_ms 自动切句）
        if curr_end is not None and (s_ms - curr_end) > max_gap_ms:
            if curr_chars:
                text = "".join(curr_chars).strip()
                if any(c not in all_puncs for c in text):
                    sentences.append({
                        "start": round(curr_start / 1000.0, 3),
                        "end": round(curr_end / 1000.0, 3),
                        "text": text,
                        "source_file": filename,
                    })
                curr_chars = []
                curr_start = None
                curr_end = None

        if curr_start is None:
            curr_start = s_ms
        curr_end = e_ms
        curr_chars.append(w_clean)

        # 句末标点切分
        if any(c in end_puncs for c in w_clean):
            text = "".join(curr_chars).strip()
            if any(c not in all_puncs for c in text):
                sentences.append({
                    "start": round(curr_start / 1000.0, 3),
                    "end": round(curr_end / 1000.0, 3),
                    "text": text,
                    "source_file": filename,
                })
            curr_chars = []
            curr_start = None
            curr_end = None

    if curr_chars:
        text = "".join(curr_chars).strip()
        if any(c not in all_puncs for c in text):
            sentences.append({
                "start": round(curr_start / 1000.0, 3),
                "end": round(curr_end / 1000.0, 3),
                "text": text,
                "source_file": filename,
            })

    return sentences


class TranscriptionService:
    _model = None
    _torch = None
    # FunASR/GPU 不宜并行；批量识别也走同一把锁，避免日志与推理交错
    _lock = threading.RLock()

    @classmethod
    def check_environment(cls) -> list[str]:
        try:
            import torch  # noqa: F401
        except (ImportError, OSError) as e:
            raise ImportError(f"识别模块tt加载失败：{e}，请检查环境配置")

        try:
            import funasr  # noqa: F401
        except (ImportError, OSError) as e:
            raise ImportError(f"识别模块ff加载失败：{e}，请检查环境配置")

        warnings = []
        if not torch.cuda.is_available():
            warnings.append("未检测到 CUDA GPU，将使用 CPU 进行识别（速度较慢）")

        # FunASR 解码 MP4 依赖 PATH 上的 ffmpeg
        ensure_ffmpeg_on_path()
        try:
            resolve_ffmpeg()
        except FileNotFoundError as e:
            raise ImportError(str(e)) from e

        try:
            # ModelScope 实际缓存：~/.cache/modelscope/hub/models/<model_id>
            cache_dir = os.path.join(
                os.path.expanduser("~"), ".cache", "modelscope", "hub", "models"
            )
            for label, model_id in [
                ("SenseVoice 语音识别", MODEL_ID),
                ("VAD 静音检测", VAD_MODEL),
            ]:
                model_path = os.path.join(cache_dir, model_id)
                if not os.path.isdir(model_path):
                    warnings.append(
                        f"{label} 模型未缓存（首次使用需联网自动下载，耗时较长）"
                    )
        except Exception:
            warnings.append("无法检查模型缓存状态，首次使用可能需要联网下载")

        return warnings

    @classmethod
    def init_model(cls):
        with cls._lock:
            if cls._model is not None:
                return
            ensure_ffmpeg_on_path()
            import torch
            from funasr import AutoModel
            cls._torch = torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            _safe_print(f"正在初始化 SenseVoice-Small 识别引擎 (device={device})")
            cls._model = AutoModel(
                model=MODEL_ID,
                device=device,
                vad_model=VAD_MODEL,
                vad_kwargs={"max_single_segment_time": 30000},
                disable_update=True,
            )

    @classmethod
    def transcribe(cls, project: DramaProject) -> str:
        with cls._lock:
            return cls._transcribe_locked(project)

    @classmethod
    def _transcribe_locked(cls, project: DramaProject) -> str:
        cls.init_model()
        torch = cls._torch

        project_path = project.folder_path
        valid_exts = (".mp4", ".mov", ".mkv", ".avi")
        raw_files = sorted(
            [f for f in os.listdir(project_path) if f.lower().endswith(valid_exts)],
            key=_episode_sort_key,
        )
        if not raw_files:
            raise FileNotFoundError(f"项目 {project.name} 中没有找到视频文件")

        global_script = []
        start_time = time.time()
        file_errors: list[str] = []
        total_files = len(raw_files)
        _safe_print(f"开始识别《{project.name}》（共 {total_files} 集，引擎: SenseVoice-Small）", flush=True)
        _safe_print(f"   识别顺序: {' → '.join(raw_files)}", flush=True)

        for index, file in enumerate(raw_files, 1):
            file_path = os.path.join(project_path, file)
            _safe_print(f"   《{project.name}》识别 {index}/{total_files}: {file} ...", flush=True)
            try:
                res = cls._model.generate(
                    input=file_path,
                    cache={},
                    language="zh",
                    use_itn=True,
                    batch_size_s=60,
                    merge_vad=True,
                    merge_length_s=15,
                    output_timestamp=True,
                )
                if not res:
                    file_errors.append(f"{file}: 引擎返回空结果")
                    continue
                data = res[0]
                got_text = False
                timestamps = data.get("timestamp", [])
                words = data.get("words", [])
                if timestamps and words:
                    sentences = _split_words_to_sentences(words, timestamps, file)
                    if sentences:
                        got_text = True
                        global_script.extend(sentences)

                # 无分句时间戳时，尽量回退到整段文本，避免整剧判空
                if not got_text:
                    from funasr.utils.postprocess_utils import rich_transcription_postprocess
                    raw_text = data.get("text") or ""
                    plain = rich_transcription_postprocess(str(raw_text)).replace(" ", "").strip()
                    if plain:
                        global_script.append({
                            "start": 0.0,
                            "end": 0.0,
                            "text": plain,
                            "source_file": file,
                        })
                    else:
                        file_errors.append(f"{file}: 无可用文本")

                if torch and torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception as e:
                msg = f"{file}: {e}"
                file_errors.append(msg)
                _safe_print(f"   《{project.name}》识别报错 {file}: {e}", flush=True)
                logger.warning("识别报错 《{}》 {}: {}", project.name, file, e)

        if not global_script:
            detail = "；".join(file_errors[:5]) if file_errors else "未知原因"
            if len(file_errors) > 5:
                detail += f"…（共 {len(file_errors)} 集失败）"
            raise RuntimeError(f"项目 {project.name} 未识别到任何内容（{detail}）")

        from app.common.crypto import write_encrypted_json
        from app.common.drama_artifact_paths import finalize_written_artifact, prepare_write_path

        output_path = prepare_write_path(project_path, script=True)
        write_encrypted_json(output_path, {"steps": global_script, "project_name": project.name})
        finalize_written_artifact(output_path)

        cost = time.time() - start_time
        _safe_print(f"《{project.name}》识别完成（SenseVoice-Small）, 耗时 {cost:.1f}s", flush=True)
        return output_path
