import json
import os
import re
import time

from app.common.ffmpeg_paths import ensure_ffmpeg_on_path, resolve_ffmpeg
from app.common.my_logger import my_logger as logger
from app.data.models.drama_project import DramaProject

MODEL_ID = "iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
VAD_MODEL = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
PUNC_MODEL = "iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch"
BEAM_SIZE = 15


class TranscriptionService:
    _model = None

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
                ("视频识别", MODEL_ID),
                ("VAD 静音检测", VAD_MODEL),
                ("标点恢复", PUNC_MODEL),
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
        if cls._model is not None:
            return
        ensure_ffmpeg_on_path()
        import torch
        from funasr import AutoModel
        cls._torch = torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"🚀 正在初始化 ff 引擎 (device={device}, beam={BEAM_SIZE})")
        cls._model = AutoModel(
            model=MODEL_ID,
            device=device,
            vad_model=VAD_MODEL,
            punc_model=PUNC_MODEL,
            disable_update=True,
        )

    @classmethod
    def transcribe(cls, project: DramaProject) -> str:
        cls.init_model()
        torch = cls._torch

        project_path = project.folder_path
        valid_exts = (".mp4", ".mov", ".mkv", ".avi")
        raw_files = sorted(
            [f for f in os.listdir(project_path) if f.lower().endswith(valid_exts)],
            key=lambda s: [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)],
        )
        if not raw_files:
            raise FileNotFoundError(f"项目 {project.name} 中没有找到视频文件")

        global_script = []
        start_time = time.time()
        file_errors: list[str] = []

        for file in raw_files:
            file_path = os.path.join(project_path, file)
            print(f"   🎧 正在识别: {file} ...")
            try:
                res = cls._model.generate(
                    input=file_path,
                    batch_size_s=300,
                    beam_size=BEAM_SIZE,
                    sentence_timestamp=True,
                )
                if not res:
                    file_errors.append(f"{file}: 引擎返回空结果")
                    continue
                data = res[0]
                got_text = False
                if "sentence_info" in data:
                    for info in data["sentence_info"]:
                        text = info["text"].replace(" ", "")
                        if text:
                            got_text = True
                            global_script.append({
                                "start": round(info["start"] / 1000.0, 3),
                                "end": round(info["end"] / 1000.0, 3),
                                "text": text,
                                "source_file": file,
                            })
                # 无分句时间戳时，尽量回退到整段文本，避免整剧判空
                if not got_text:
                    plain = str(data.get("text") or "").replace(" ", "").strip()
                    if plain:
                        global_script.append({
                            "start": 0.0,
                            "end": 0.0,
                            "text": plain,
                            "source_file": file,
                        })
                    else:
                        file_errors.append(f"{file}: 无可用文本")
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception as e:
                msg = f"{file}: {e}"
                file_errors.append(msg)
                print(f"   ❌ 识别报错 {file}: {e}")
                logger.warning("识别报错 {}: {}", file, e)

        if not global_script:
            detail = "；".join(file_errors[:5]) if file_errors else "未知原因"
            if len(file_errors) > 5:
                detail += f"…（共 {len(file_errors)} 集失败）"
            raise RuntimeError(
                f"项目 {project.name} 未识别到任何内容（{detail}）"
            )

        from app.common.crypto import write_encrypted_json
        from app.common.drama_artifact_paths import finalize_written_artifact, prepare_write_path

        output_path = prepare_write_path(project_path, script=True)
        write_encrypted_json(output_path, {"steps": global_script, "project_name": project.name})
        finalize_written_artifact(output_path)

        cost = time.time() - start_time
        print(f"✅ 《{project.name}》识别完成, 耗时 {cost:.1f}s")
        return output_path
