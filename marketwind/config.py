"""Runtime configuration loaded from the environment."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Connection settings read from env (or a local .env file)."""

    database_url: str
    redis_url: str

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
