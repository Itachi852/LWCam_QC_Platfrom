from functools import cached_property

from pydantic import Field
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

    jwt_secret: str = Field(min_length=32, default="lwcam-dev-secret-change-in-production-min-32-chars")
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

    # Bind-mount prefixes used to translate the Windows paths LWCAM stores in
    # capture_folders into container paths. Leave both empty when running
    # natively on Windows.
    capture_image_host_path: str = ""
    capture_image_container_path: str = ""

    @cached_property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


settings = Settings()

