# AGENTS.md

## Quick start
```bash
uv sync                                    # install deps
uv run python scripts/pack_resources.py    # compile .ts/.qrc/.ui before first run
uv run python entry.py                     # launch desktop app
uv run pytest                              # all tests (coverage on by default)
```

## Commands
- **Test**: `uv run pytest` — coverage via `--cov=app` (excludes `app/ui/generated/*`, `tests/*`)
- **No lint/typecheck config** exists in the repo.
- **Build**: `uv run python scripts/build.py` (Nuitka → `out/entry.dist/`)
- **Server** (separate project in `server/`): `pip install -r requirements.txt && uvicorn app.main:app`

## Architecture
- **Desktop app** (`app/`): PySide6 6.7.0 + `pyside6-fluent-widgets`
  - MVVM pattern: views in `app/ui/views/<name>/view.py`, viewmodels in `app/ui/views/<name>/view_model.py`
  - DI container: `app.core.container.Container` (simple registry, not a framework)
  - Lazy page loading via `LazyViewProxy` (`app/core/navigation.py`)
  - Config: `config.json` loaded by `qfluentwidgets.qconfig` via `app/common/config.py`
- **Server** (`server/`): FastAPI + MySQL + SQLAdmin, separate dependency tree (`requirements.txt`, not uv)
  - Entrypoint: `server/app/main.py`
  - Config: `.env` (pydantic-settings)

## Critical quirks
- **`entry.py` must `import torch` before `import PySide6`** — DLL load order on Windows, otherwise WinError 1114.
- **`AV_LOG_LEVEL=quiet` and `QT_LOGGING_RULES=qt.multimedia.*=false`** set at top of `entry.py` to suppress FFmpeg/Qt noise.
- **Resource compilation required before first run**: `scripts/pack_resources.py` calls `pyside6-rcc` (QRC) and `pyside6-uic` (`.ui` files in `app/ui/generated/`). Output lands in `resource_rc.py` and `app/ui/generated/ui_*.py`.
- **`config.json` is gitignored** — `cfg = Config()` at module level loads it; defaults apply if missing.
- **AES encryption** (`app/common/aes.py`) used for stored passwords in config.
- **UI tests need `qapp` fixture** (provided by `pytest-qt`). No `conftest.py` at test roots yet.

## Test structure
- `tests/unit/` — standard unit tests
- `tests/integration/` — viewmodel → service → mock API
- `tests/performance/` — manual timing (no pytest-benchmark dep)
- `tests/security/` — encryption/storage checks
- Server tests live in `server/tests/` (run from `server/` directory)

## Build & deploy
- **Nuitka** build: `--standalone --mingw64 --enable-plugin=pyside6 --windows-console-mode=disable`
- **Inno Setup**: `iscc scripts/pack_installer.iss` installs the Nuitka output
- CI test workflow: `windows-latest`, Python 3.12, `QT_QPA_PLATFORM=offscreen`
- CI build workflow: triggers on release, Python 3.11 for Nuitka compatibility
