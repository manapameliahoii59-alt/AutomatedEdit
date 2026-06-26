# AutomatedEdit 服务端（FastAPI + MySQL）

## 功能

- JWT 登录（无短信验证码）
- 按用户下发 DeepSeek / DashScope 秘钥
- 客户端上报使用记录
- SQLAdmin 管理后台：`/admin`（查看用户、秘钥、用量）

## 本地运行

```bash
cd server
cp .env.example .env
# 编辑 .env 填写 DATABASE_URL、JWT_SECRET、ADMIN_PASSWORD

pip install -r requirements.txt
# 宝塔 MySQL 先建库: automated_edit, utf8mb4

python scripts/create_user.py demo --deepseek-keys sk-xxx

uvicorn app.main:app --host 0.0.0.0 --port 8000
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

留空 `base_url` 时使用本地演示登录（不连服务端）。
