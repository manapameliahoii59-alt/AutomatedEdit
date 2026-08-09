from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "mysql+pymysql://root:password@127.0.0.1:3306/automated_edit?charset=utf8mb4"
    jwt_secret: str = "dev-secret-change-in-production"
    jwt_expire_minutes: int = 60 * 24 * 7
    admin_username: str = "admin"
    admin_password: str = "admin123"
    iocpx_base_url: str = "https://api.iocpx.com"

    deepseek_api_url: str = "https://api.deepseek.com/chat/completions"
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_api_keys: str = ""

    # OpenCode Go（Zen）策划通道默认端点
    opencode_go_api_url: str = "https://opencode.ai/zen/go/v1/chat/completions"
    opencode_go_model: str = "deepseek-v4-flash"

    # 对外访问根地址（反代后建议配置，用于拼安装包下载链接）
    # 例：https://api.example.com
    public_base_url: str = ""
    # 安装包目录（默认自动：仓库根 release/ 或 server/release/）
    client_releases_dir: str = ""

    # 桌面端更新回退配置（优先读 release/version.json）
    client_latest_version: str = "0.0.1"
    client_min_supported_version: str = "0.0.1"
    client_download_url: str = ""
    client_changelog: str = ""


settings = Settings()
