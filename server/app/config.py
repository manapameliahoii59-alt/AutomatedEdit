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

    # 桌面端更新（GET /api/client/version）
    client_latest_version: str = "0.0.1"
    client_min_supported_version: str = "0.0.1"
    client_download_url: str = ""
    client_changelog: str = ""


settings = Settings()
