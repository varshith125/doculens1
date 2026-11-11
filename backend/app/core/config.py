from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_env_file = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DOCULENS_",
        env_file=(".env", _env_file),
        extra="ignore",
    )

    allowed_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    cookie_secure: bool = False
    require_https: bool = False
    retention_seconds: int = Field(default=60, ge=30, le=3600)
    max_upload_mb: int = Field(default=12, ge=1, le=12)
    max_active_scans: int = Field(default=8, ge=1, le=32)
    workers: int = Field(default=1, ge=1, le=4)
    max_storage_mb: int = Field(default=160, ge=24, le=1024)
    ocr_models_dir: str = ""
    ocr_medium_det_path: str = ""
    ocr_medium_rec_path: str = ""
    ocr_fast_text: bool = True
    # Inference threads per OCR model; 0 sizes it from this machine's processor.
    ocr_threads: int = Field(default=0, ge=0, le=64)
    arabic_model_path: str = ""
    arabic_dictionary_path: str = ""
    semantic_models_dir: str = str(Path(__file__).resolve().parents[3] / "models" / "semantic")

    # Reread the MRZ band with local contrast when its checksum is not valid.
    enable_multivariant_voting: bool = True

    # Tesseract OCR backup engine (fallback tier 3). The binary and tessdata are
    # discovered at runtime; these only override that discovery.
    enable_tesseract_backup: bool = True
    tesseract_cmd: str = ""
    tessdata_dir: str = ""
    tesseract_language: str = "eng"
    tesseract_timeout_seconds: float = Field(default=5.0, gt=0, le=60)


@lru_cache
def get_settings() -> Settings:
    return Settings()
