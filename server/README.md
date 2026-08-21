# AutomatedEdit 服务端（FastAPI + MySQL）

## 功能

- JWT 登录（易投账号密码经 iocpx 第三方校验，首次登录自动注册本地用户）
- 管理后台可控制用户**是否允许使用桌面端**（`允许使用桌面端` 开关），并查看用户**易投账号与明文密码**（用户每次登录成功后自动更新）
- 按用户下发策划 LLM / DashScope 秘钥（官方 DeepSeek、OpenCode Go 或小米 MiMo）
- 客户端上报使用记录，并汇总为**每日活动**（登录/关闭时间、下载剧目、剪辑剧目）
- 按用户保存客户端配置（下载集数、自动解压/识别/剪辑等），支持命名空间扩展
- 自建管理后台：`/admin`（用户、每日活动、用量、策划任务）

## 本地运行

```bash
cd server
cp .env.example .env
# 编辑 .env：本地测试可连远程库
# DATABASE_URL=mysql+pymysql://用户:密码@129.204.86.63:3306/automated_edit?charset=utf8mb4

pip install -r requirements.txt
# 宝塔 MySQL 先建库: automated_edit, utf8mb4

python scripts/create_user.py demo --deepseek-keys sk-xxx

uvicorn app.main:app --host 0.0.0.0 --port 8000

# 若 venv 在项目里
source venv/bin/activate

# 若在 server 上一级


# 服务端项目路径/www/wwwroot/automated-edit-api
# 服务端管理后台http://129.204.86.63:7172/admin
# 服务端地址129.204.86.63
source ../venv/bin/activate

# 宝塔「Python 项目管理器」创建的，可能是
source /www/server/pyporject_evn/项目名_venv/bin/activate
```

- API 文档: http://127.0.0.1:8000/docs
- 管理后台: http://127.0.0.1:8000/admin （`.env` 里 ADMIN_USERNAME / ADMIN_PASSWORD）

## 宝塔部署要点

1. MySQL 建库 + 用户权限
2. 上传 `server/` 目录，配置 `.env`
3. Supervisor 启动（**保持单 worker**，策划任务虽已落库，执行线程仍绑定进程）:
   `uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1`
4. Nginx 反代 `api.你的域名.com` → `8000`，配置 SSL；建议用 `/health` 做上游探活（会检查数据库）

## 客户端配置

在桌面端 `config.json` 中设置：

```json
{
  "API": {
    "base_url": "https://api.你的域名.com"
  }
}
```

留空 `base_url` 时默认连接 `http://129.204.86.63:7172`；登录须经服务端校验易投账号密码。

## 每日策划/剪辑限额

在管理后台 **用户** 页编辑用户，可设置：

| 字段 | 说明 |
|------|------|
| 每日策划上限 | 每天可策划的不同剧目数，默认 **30**，`0` = 不限制 |
| 每日剪辑上限 | 每天可剪辑的不同剧目数，默认 **30**，`0` = 不限制 |

同一剧目重复策划/剪辑不计入限额。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/client/quota/today` | 查询今日配额与使用情况 |
| POST | `/api/client/quota/check` | 预检是否允许策划/剪辑某剧目 |
| POST | `/api/client/usage` | 上报 `plan_drama` / `clip_drama` 时服务端强制校验 |

`POST /api/client/quota/check` 请求体示例：

```json
{ "action": "plan", "drama_name": "某剧名" }
```

## 服务端代理策划

策划逻辑与 API 密钥**仅存在于服务端**。在管理后台 **用户** 编辑页为每位用户选择 **策划模型**（官方 DeepSeek、OpenCode Go 或小米 MiMo），并填写对应 **策划 API Keys**（逗号分隔）。未配置用户 Key 时可选用 `.env` 中的 `DEEPSEEK_API_KEYS` 作为全局兜底。

在 **用户** 页可设置 **使用期限**（`valid_until`）：留空表示永久有效；到期后桌面端登录与 API 均返回 **「无效」**。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/client/plan/jobs` | 创建策划任务（校验每日策划配额） |
| GET | `/api/client/plan/jobs/{job_id}` | 查询进度 |
| GET | `/api/client/plan/jobs/{job_id}/result` | 任务完成后获取密文结果 |

`.env` 示例：

```env
DEEPSEEK_API_URL=https://api.deepseek.com/chat/completions
DEEPSEEK_MODEL=deepseek-v4-flash
# OpenCode Go（用户选 Go 通道时使用）
OPENCODE_GO_API_URL=https://opencode.ai/zen/go/v1/chat/completions
OPENCODE_GO_MODEL=deepseek-v4-flash
# 小米 MiMo（用户选 MiMo 通道时使用）
XIAOMI_MIMO_API_URL=https://api.xiaomimimo.com/v1/chat/completions
XIAOMI_MIMO_MODEL=mimo-v2.5
# 可选全局兜底（优先使用用户密钥表中的配置）
# DEEPSEEK_API_KEYS=sk-xxx
```

## 用户配置 API

需携带登录后的 `Authorization: Bearer <token>`。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/client/settings` | 获取当前用户全部配置 |
| PATCH | `/api/client/settings` | 部分更新（按命名空间深度合并） |

配置按**命名空间**分组存储，便于后续扩展。当前内置 `video_download`：

```json
{
  "video_download": {
    "episode_from": 1,
    "episode_to": 15,
    "download_dir": "",
    "auto_unzip": true,
    "auto_transcribe": true,
    "auto_import_clip": true,
    "auto_start_after_add": true
  }
}
```

PATCH 示例（仅更新部分字段，其余保持不变）：

```json
{
  "video_download": {
    "episode_from": 2,
    "episode_to": 8,
    "auto_unzip": false
  }
}
```

可在顶层增加新的命名空间（如 `clip_edit`），服务端会原样保存并在 GET 时返回。

## 桌面端更新

客户端登录后会自动检查更新；也可在「设置 → 检查更新」手动检查。接口**无需登录**：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/client/version` | 返回最新版本、最低支持版本、安装包下载链接、更新说明 |
| GET | `/release/<文件名>` | 下载 `release/` 目录下的安装包 |

### 推荐：与打包产物同目录

本地打包后，`release/` 里会有安装包；再生成同目录的 `version.json`：

```bash
iscc scripts/pack_installer.iss
uv run python scripts/write_release_version.py --changelog "修复若干问题"
```

生成示例：

```
release/
  剪辑助手-v0.0.2-installer.exe
  version.json
```

`version.json` 示例：

```json
{
  "latest": "0.0.2",
  "min_supported": "0.0.1",
  "installer": "剪辑助手-v0.0.2-installer.exe",
  "changelog": "修复若干问题"
}
```

发版到服务器：把整个 `release/` 上传到 API 项目下（例如 `/www/wwwroot/automated-edit-api/release/`），或设置：

```env
CLIENT_RELEASES_DIR=/www/wwwroot/automated-edit-api/release
```

一般**无需重启** API（每次请求会重新读 `version.json`）。  
下载地址：`{PUBLIC_BASE_URL或请求域名}/release/<installer>`。若反代后链接不对：

```env
PUBLIC_BASE_URL=https://你的对外域名
```

### 回退：`.env` 配置

没有 `release/version.json` 时，仍可用：

```env
CLIENT_LATEST_VERSION=0.0.2
CLIENT_MIN_SUPPORTED_VERSION=0.0.1
CLIENT_DOWNLOAD_URL=https://你的域名/release/MyApp-v0.0.2-installer.exe
CLIENT_CHANGELOG=修复若干问题；优化下载体验
```

- 客户端确认更新后会**应用内下载**安装包并打开安装程序
- 客户端 `app/common/config.py` 的 `VERSION` 与 `scripts/pack_installer.iss` 的 `MyAppVersion` 需与发布版本一致
