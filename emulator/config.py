"""Emulator configuration — reads from .env in the emulator directory."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://vkus:vkus@localhost:5432/vkus"
    host: str = "0.0.0.0"
    port: int = 8001
    log_level: str = "INFO"


settings = Settings()
