from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "AndroGuard APK Analyzer"
    analyzer_version: str = "1.0.0"
    schema_version: str = "1.0.0"
    max_apk_size_mb: int = 80
    analysis_timeout_seconds: int = 90
    max_screenshots: int = 40
    max_image_bytes: int = 8 * 1024 * 1024
    dex_analysis_enabled: bool = True
    max_code_classes: int = 200
    max_code_methods: int = 300
    max_code_findings: int = 200
    job_ttl_seconds: int = 3600
    temp_root: Path = Path("./tmp")
    log_level: str = "INFO"
    database_url: str | None = None
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24
    aapt_path: str | None = None
    s3_endpoint_url: str | None = None
    s3_region: str = "ap-south-1"
    s3_bucket: str = "apk-screenshots"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_public_base_url: str | None = None

    # --- Async job queue (optional; falls back to Postgres, then in-memory) ---
    redis_url: str | None = None
    job_poll_interval_seconds: float = 1.0
    job_retention_seconds: int = 24 * 3600

    # --- Dynamic exploration on an Android emulator (opt-in) ---
    # Disabled by default so the existing synchronous /analyze path is untouched.
    exploration_enabled: bool = False
    adb_path: str = "adb"
    emulator_serial: str | None = None
    emulator_boot_timeout_seconds: int = 240
    exploration_timeout_seconds: int = 600
    exploration_max_states: int = 25
    exploration_max_actions: int = 60
    exploration_action_delay_ms: int = 900
    exploration_screenshot_format: str = "png"
    exploration_s3_prefix: str = "exploration"
    exploration_keep_apk: bool = True
    ad_detection_vision_enabled: bool = False

    @property
    def exploration_ready(self) -> bool:
        """True when dynamic exploration is switched on and has an ADB binary configured."""
        return bool(self.exploration_enabled and (self.adb_path or "").strip())

    @property
    def redis_enabled(self) -> bool:
        return bool((self.redis_url or "").strip())

    @property
    def s3_enabled(self) -> bool:
        return bool(
            (self.s3_endpoint_url or "").strip()
            and (self.s3_access_key or "").strip()
            and (self.s3_secret_key or "").strip()
            and (self.s3_bucket or "").strip()
        )

    @property
    def max_apk_size_bytes(self) -> int:
        return self.max_apk_size_mb * 1024 * 1024

    @property
    def jobs_dir(self) -> Path:
        return self.temp_root / "jobs"


settings = Settings()
