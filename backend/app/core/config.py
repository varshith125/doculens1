from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCULENS_", env_file=".env", extra="ignore")

    allowed_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    cookie_secure: bool = False
    retention_seconds: int = Field(default=900, ge=30, le=3600)
    max_upload_mb: int = Field(default=12, ge=1, le=12)
    max_active_scans: int = Field(default=8, ge=1, le=32)
    workers: int = Field(default=1, ge=1, le=4)
    max_storage_mb: int = Field(default=160, ge=24, le=1024)
    arabic_model_path: str = ""
    arabic_dictionary_path: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
