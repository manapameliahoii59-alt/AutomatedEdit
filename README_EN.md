<h1 align="center">
  Clip Assistant · AutomatedEdit
</h1>

<div align="center">

[中文](./README.md) | **English**

[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue?color=#4ec820)]()
[![PySide6 6.7.0](https://img.shields.io/badge/PySide6-6.7.0-green?color=#4ec820)]()
[![FastAPI](https://img.shields.io/badge/FastAPI-Server-009688?color=#4ec820)]()
[![GPLv3](https://img.shields.io/badge/License-GPLv3-blue?color=#4ec820)](LICENSE)
[![Platform Windows](https://img.shields.io/badge/Platform-Windows-blue?color=#4ec820)]()

</div>

A desktop automation tool for short-drama creators. It runs the whole
**download → AI planning → speech recognition → rendering → batch masking**
pipeline in one place, backed by a FastAPI server for login verification,
daily quota, planning jobs and update delivery.

## ✨ Key Features

- 📥 **Video Download**: batch download from the Changdu platform, with anti-crawl fingerprint spoofing, cookie encoding fixes and auto-unzip
- ✂️ **Automated Editing**: import a drama and run the full "plan → transcribe → render" flow in one click, with auto-retry and dynamic queuing
- 🤖 **AI Planning**: auto-generate clip plans per episode across DeepSeek / Qwen / Xiaomi MiMo / Zhipu GLM channels (proxied by the server; keys never reach the client)
- 🎙 **Speech Recognition**: local FunASR transcription to drive subtitle and cut points
- 🎬 **Hardware-Accelerated Rendering**: auto-detects and uses NVIDIA NVENC / AMD AMF / Intel QSV, with CPU software encoding fallback
- ⚡ **Render Engine v3**: three-stage chunked stream reuse + baked overlay text to speed up batch rendering
- 🩹 **Batch Masking**: three-stage masking (with history) for multi-episode videos
- 🎨 **Modern UI**: Fluent Design via qfluentwidgets, with light/dark themes
- 🏗 **MVVM + dependency injection + lazy loading**, fully separating logic from UI

## 🧩 Architecture

| Component | Stack | Notes |
|-----------|-------|-------|
| Desktop `app/` | PySide6 6.7.0 + pyside6-fluent-widgets | MVVM, DI container, `LazyViewProxy` lazy loading |
| Server `server/` | FastAPI + MySQL + SQLAdmin | Login / daily quota / planning jobs / update delivery, admin at `/admin` |

See [server/README.md](./server/README.md) for server APIs and deployment.

## 🖼 Screenshots

| Login | Main (Light) | Main (Dark) |
|-------|--------------|-------------|
| <img src="screen_shot/login.png" width="300"> | <img src="screen_shot/main_window.png" width="300"> | <img src="screen_shot/main_dark.png" width="300"> |

## 🚀 Quick Start

### Requirements

1. Python **3.12** (pinned by `.python-version`)
2. [uv](https://docs.astral.sh/uv/) for dependencies and virtual environments
3. [FFmpeg](https://ffmpeg.org/) for rendering/transcoding (a bundled copy lives in `tools/ffmpeg/`)
4. Optional: NVIDIA / AMD / Intel GPU to enable hardware acceleration

### Run the Desktop App

```bash
# Clone the repository
git clone https://github.com/manapameliahoii59-alt/AutomatedEdit.git
cd AutomatedEdit

# Install dependencies
uv sync

# Compile resources (.ts/.qrc/.ui, required before first run)
uv run python scripts/pack_resources.py

# Launch
uv run python entry.py
```

> Server address resolution: the source/dev build defaults to local
> `http://127.0.0.1:8000`; the packaged build defaults to the production server.
> Override via `API.base_url` in `config.json` or the `AE_API_BASE_URL` env var.

### Run the Server

The server has its own dependency tree and must be started from `server/`
(otherwise `.env` is not found):

```bash
cd server
cp .env.example .env      # configure database and keys
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

See [server/README.md](./server/README.md) for details.

## 🛠 Development Workflow

### UI Design

1. Open/create `.ui` files under `app/ui/generated/` with Qt Designer
2. Add or modify widgets
3. Save and recompile resources: `uv run python scripts/pack_resources.py`

### Business Logic (MVVM)

1. **View**: `app/ui/views/<name>/view.py`, subclassing `QWidget` and the UI class — wiring only
2. **ViewModel**: `view_model.py` in the same folder, subclassing `app.core.view_model.ViewModel`, using `Signal` to notify the View
3. **Register navigation**: use `LazyViewProxy` in `app/ui/views/main_window/view.py` for on-demand loading

## 🧪 Tests

```bash
# Desktop tests (coverage on by default)
uv run pytest

# Server tests (run from server/)
cd server; pytest
```

Layout: `tests/unit/`, `tests/integration/`, `tests/performance/`, `tests/security/`; server tests live in `server/tests/`.

## 📦 Packaging

The build script uses **Nuitka** + **Inno Setup**:

```bash
# Full build (Nuitka compile, slow)
uv run python scripts/build.py

# Build and produce the installer (writes version info)
uv run python scripts/build.py --installer

# Fast daily packaging: reuse the compiled base, sync app/ only (seconds)
uv run python scripts/build.py --app-only --fast-pack
```

Manual Inno Setup: `iscc scripts/pack_installer.iss`.

> ⚠️ Non-ASCII paths break the Nuitka/mingw build — keep the repo at an ASCII path.

## 🛠 Project Structure

```
├── app/                    # Desktop core
│   ├── common/             # Utilities (Config, Logger, AES, ...)
│   ├── core/               # Core infra (DI Container, Navigation/LazyViewProxy)
│   ├── data/               # Data layer (API, Models, Services)
│   └── ui/                 # UI layer
│       ├── components/     # Custom components
│       ├── generated/      # Generated Python from .ui files
│       └── views/          # MVVM pages
├── server/                 # FastAPI server (separate dependency tree)
├── resource/               # Resources (i18n, images, qss)
├── scripts/                # Build & utility scripts
│   ├── build.py            # Nuitka build script
│   ├── pack_installer.iss  # Inno Setup config
│   └── pack_resources.py   # Resource compilation
├── tools/                  # Bundled ffmpeg / fonts / outro assets
├── tests/                  # Test suite
├── entry.py                # Entry point
├── pyproject.toml          # Project config & dependencies
└── README.md
```

## ⚠️ Notes

> The code is mainly AI-assisted. Use it for learning/reference and test thoroughly before production use.

## 🙏 Special Thanks

- **[PyQt-Fluent-Widgets / qfluentwidgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets)** — the high-quality Fluent Design component library by zhiyiYo.
