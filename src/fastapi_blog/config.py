from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).parent / ".env",
        env_file_encoding="utf-8",
    )

    secret_key: SecretStr
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 10000

    max_upload_size_bytes: int = 5 * 1024 * 1024

    post_per_page: int = 100


settings = Settings()  # type: ignore[call-arg] # Loaded from .env file
