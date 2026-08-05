from functools import cached_property
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "LWCam Python Backend"
    app_env: str = "development"
    app_debug: bool = True
    api_prefix: str = "/api"

    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "lwcam"
    db_user: str = "postgres"
    db_password: str = "Lifewood01"

    jwt_secret: str = Field(
        min_length=32,
        default="lwcam-dev-secret-change-in-production-min-32-chars",
    )
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480
    preview_cache_dir: str = ".cache/previews"
    qc_work_dir: str = ".cache/qc_work"
    qc_audit_dir: str = ".cache/qc_audit"
    export_temp_dir: str = ""
    export_output_dir: str = ""
    export_csv_encoding: str = ""
    export_csv_line_ending: str = ""
    export_temp_retention_hours: int = Field(default=24, ge=1)

    # Upload is fail-safe: only the literal boolean/string true enables it.
    # Missing, empty, false, zero, and malformed values all keep it disabled.
    upload_enabled: bool = False
    upload_reconcile_seconds: float = Field(default=300, gt=0)
    upload_gate_retry_seconds: float = Field(default=2, gt=0)
    upload_gate_max_wait_seconds: float = Field(default=60, ge=0)
    upload_max_retries: int = Field(default=5, ge=1, le=100)
    upload_connect_timeout_seconds: float = Field(default=10, gt=0)
    upload_read_timeout_seconds: float = Field(default=300, gt=0)
    upload_stable_seconds: float = Field(default=2, ge=0)
    upload_stop_timeout_seconds: float = Field(default=10, ge=0)

    ingest_api_base_url: str = ""
    ingest_api_authorization: str = ""
    hfs_upload_url: str = ""
    hfs_username: str = ""
    hfs_password: str = ""

    ingest_db_host: str = ""
    ingest_db_port: int = Field(default=3306, ge=1, le=65535)
    ingest_db_name: str = "LWCam"
    ingest_db_user: str = ""
    ingest_db_password: str = ""

    upload_success_dir: str = ""
    upload_failed_dir: str = ""
    upload_duplicates_dir: str = ""
    upload_report_dir: str = ""

    # Bind-mount prefixes used to translate the Windows paths LWCAM stores in
    # capture_folders into container paths. Leave both empty when running
    # natively on Windows.
    capture_image_host_path: str = ""
    capture_image_container_path: str = ""

    @field_validator("upload_enabled", mode="before")
    @classmethod
    def parse_upload_enabled(cls, value: Any) -> bool:
        if value is True:
            return True
        return isinstance(value, str) and value.strip().lower() == "true"

    @cached_property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


settings = Settings()

