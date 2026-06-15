import json
import os
import re
import time

from app.data.models.drama_project import DramaProject

MODEL_ID = "iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
VAD_MODEL = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
PUNC_MODEL = "iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch"
BEAM_SIZE = 25


class TranscriptionService:
    _model = None

    @classmethod
    def init_model(cls):
        if cls._model is not None:
            return
        import torch
        from funasr import AutoModel
        cls._torch = torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"🚀 正在初始化 FunASR 引擎 (device={device}, beam={BEAM_SIZE})")
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
                    continue
                data = res[0]
                if "sentence_info" in data:
                    for info in data["sentence_info"]:
                        text = info["text"].replace(" ", "")
                        if text:
                            global_script.append({
                                "start": round(info["start"] / 1000.0, 3),
                                "end": round(info["end"] / 1000.0, 3),
                                "text": text,
                                "source_file": file,
                            })
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception as e:
                print(f"   ❌ 识别报错 {file}: {e}")

        if not global_script:
            raise RuntimeError(f"项目 {project.name} 未识别到任何台词")

        output_path = os.path.join(project_path, "full_script_data.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({"steps": global_script, "project_name": project.name}, f, ensure_ascii=False, indent=2)

        cost = time.time() - start_time
        print(f"✅ 《{project.name}》听写完成: {len(global_script)} 句, 耗时 {cost:.1f}s")
        return output_path
