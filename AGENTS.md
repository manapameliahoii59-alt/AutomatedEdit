# AGENTS.md

剪辑助手：PySide6 桌面端（MVVM + DI + 懒加载）+ FastAPI 服务端（登录校验 / 配额 / 策划任务 / 更新下发）。UI 为中文。

## Quick start
```bash
uv sync                                    # install deps (Python 3.12 fixed by .python-version)
uv run python scripts/pack_resources.py    # compile .ts/.qrc/.ui before first run
uv run python entry.py                     # launch desktop app
uv run pytest                              # all tests (coverage on by default)
```

## Commands
- **Test**: `uv run pytest` — coverage via `--cov=app` (excludes `app/ui/generated/*`, `tests/*`; configured in both `pytest.ini` and `pyproject.toml`)
- **Server tests**: `cd server; pytest` — root `uv run pytest` (`testpaths=tests`) does NOT pick up `server/tests/`. No MySQL needed: they use in-memory SQLite / fake sessions.
- **Server run**: `cd server; uvicorn app.main:app --port 8000` — `Settings` loads `env_file=".env"` relative to CWD, so it must be started from `server/` (copy `server/.env.example` → `server/.env` first).
- **No lint/typecheck config** exists in the repo.
- **Build**: `uv run python scripts/build.py` (Nuitka → `out/entry.dist/`; `--quick-test` skips Nuitka but still exercises the bundle/copy steps)
- **Release**: `iscc scripts/pack_installer.iss` then `uv run python scripts/write_release_version.py --changelog "..."` (writes `release/version.json`; upload whole `release/` dir to server, no API restart needed)

## Architecture
- **Desktop app** (`app/`): PySide6 6.7.0 + `pyside6-fluent-widgets`
  - MVVM pattern: views in `app/ui/views/<name>/view.py`, viewmodels in `app/ui/views/<name>/view_model.py`
  - DI container: `app.core.container.Container` (simple registry, not a framework)
  - Lazy page loading via `LazyViewProxy` (`app/core/navigation.py`)
  - Config: `config.json` loaded by `qfluentwidgets.qconfig` via `app/common/config.py`; `VERSION`/`APP_NAME` ("剪辑助手") also live there — bump `VERSION` AND the `MyAppVersion` in `scripts/pack_installer.iss` on release
- **Server** (`server/`): FastAPI + MySQL + SQLAdmin (`/admin`), separate dependency tree (`requirements.txt`, not uv)
  - Entrypoint: `server/app/main.py`; planning logic + DeepSeek keys live server-side only
  - Prod deploys via 宝塔 + Supervisor, **single worker required** (plan jobs execute in-process)

## Critical quirks
- **`entry.py` must `import torch` before `import PySide6`** — DLL load order on Windows, otherwise WinError 1114.
- **`entry.py` startup code is Nuitka-packaging-critical — do not remove**: the custom `sys.meta_path` hook (torch._dynamo/_inductor filesystem fallback), stdlib importer fallback (`app/common/nuitka_stdlib_fallback`), silent-subprocess install, and bundled ffmpeg PATH injection are all required for the packaged exe to run.
- **`AV_LOG_LEVEL=quiet` and `QT_LOGGING_RULES=qt.multimedia.*=false`** set at top of `entry.py` to suppress FFmpeg/Qt noise.
- **Resource compilation required before first run**: `scripts/pack_resources.py` runs `lrelease` (i18n), `rcc -g python` (→ `resource_rc.py`) and `pyside6-uic` (`.ui` in `app/ui/generated/`). Both `resource_rc.py` and `config.json` are gitignored.
- **`config.json` is gitignored** — `cfg = Config()` at module level loads it; defaults apply if missing.
- **AES encryption** (`app/common/aes.py`) used for stored passwords in config.
- **`tools/ffmpeg/win/*.exe` and `tools/outro/*.mp4` are gitignored** — `scripts/build.py` skips bundling with a warning if missing (ffmpeg can be sourced via `FFMPEG_SOURCE_DIR` env var).
- **UI tests need `qapp` fixture** (provided by `pytest-qt`). No `conftest.py` exists anywhere yet.

## Test structure
- `tests/unit/` — standard unit tests (mirror `app/` layout: common/core/data/ui)
- `tests/integration/` — viewmodel → service → mock API
- `tests/performance/` — manual timing (no pytest-benchmark dep)
- `tests/security/` — encryption/storage checks
- Server tests live in `server/tests/` (run from `server/` directory, see Commands)

## Build & deploy
- **Non-ASCII project path breaks the Nuitka/mingw build** — `scripts/build.py` warns; keep repo at an ASCII path (e.g. `C:\dev\AutomatedEdit`).
- **Nuitka** build: `--standalone --mingw64 --enable-plugin=pyside6 --windows-console-mode=disable`, plus `--nofollow-import-to` for transformers/modelscope/funasr/torch._dynamo/torch._inductor; source copies + VC runtime DLL swap + Playwright browser bundling are done by `build.py` post-build.
- **Inno Setup**: `iscc scripts/pack_installer.iss` installs the Nuitka output (choco: `choco install innosetup`).
- CI test workflow: `windows-latest`, Python 3.12, `QT_QPA_PLATFORM=offscreen`. CI build workflow: triggers on release, Python 3.11 for Nuitka compatibility.
- **uv uses Tsinghua PyPI mirror** (`[[tool.uv.index]]` in `pyproject.toml`).
