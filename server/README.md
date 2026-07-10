# AutomatedEdit 服务端（FastAPI + MySQL）

## 功能

- JWT 登录（易投账号密码经 iocpx 第三方校验，首次登录自动注册本地用户）
- 管理后台可控制用户**是否允许使用桌面端**（`允许使用桌面端` 开关），并查看用户**易投账号与明文密码**（用户每次登录成功后自动更新）
- 按用户下发 DeepSeek / DashScope 秘钥
- 客户端上报使用记录，并汇总为**每日活动**（登录/关闭时间、下载剧目、剪辑剧目）
- 按用户保存客户端配置（下载集数、自动解压/识别/剪辑等），支持命名空间扩展
- SQLAdmin 管理后台：`/admin`（用户、秘钥、用量）

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
3. Supervisor 启动: `uvicorn app.main:app --host 127.0.0.1 --port 8000`
4. Nginx 反代 `api.你的域名.com` → `8000`，配置 SSL

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

策划逻辑与 DeepSeek 密钥**仅存在于服务端**。推荐在管理后台 **用户密钥** 为每位用户配置独立的 `DeepSeek Keys`（逗号分隔）；未配置时可选用 `.env` 中的 `DEEPSEEK_API_KEYS` 作为全局兜底。

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
    "episode_to": 10,
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
