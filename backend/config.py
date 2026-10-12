from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    bot_token: str = ""
    admin_username: str = "ownerparadoxy"
    app_url: str = "https://sellstarsss.bothost.tech"
    database_url: str = "postgresql+asyncpg://stars:change-me@db:5432/stars_shop"
    master_key: str = ""
    admin_session_secret: str = ""
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

settings = Settings()
