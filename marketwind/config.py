"""Runtime configuration loaded from the environment."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Connection settings read from env (or a local .env file)."""

    database_url: str
    redis_url: str
    bocha_api_key: str | None = None
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    llm_model: str = "deepseek-v4-pro"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
