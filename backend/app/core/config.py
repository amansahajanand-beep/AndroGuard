from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )

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

    # --- Object storage (Supabase S3-compatible or AWS). Never log these values. ---
    # Canonical fields stay s3_*; AWS_* / S3_* env aliases are accepted.
    s3_endpoint_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("s3_endpoint_url", "S3_ENDPOINT_URL"),
    )
    s3_region: str = Field(
        default="ap-south-1",
        validation_alias=AliasChoices("s3_region", "S3_REGION", "AWS_REGION"),
    )
    s3_bucket: str = Field(
        default="apk-screenshots",
        validation_alias=AliasChoices("s3_bucket", "S3_BUCKET"),
    )
    s3_access_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "s3_access_key", "S3_ACCESS_KEY", "AWS_ACCESS_KEY_ID"
        ),
    )
    s3_secret_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "s3_secret_key", "S3_SECRET_KEY", "AWS_SECRET_ACCESS_KEY"
        ),
    )
    s3_public_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("s3_public_base_url", "S3_PUBLIC_BASE_URL"),
    )
    # Phase 8 root prefix: apps/{app_id}/runs/{run_id}/...
    s3_prefix: str = Field(
        default="apps",
        validation_alias=AliasChoices("s3_prefix", "S3_PREFIX"),
    )
    s3_upload_timeout_seconds: float = 30.0
    s3_upload_retries: int = 3
    s3_upload_retry_backoff_seconds: float = 0.75
    s3_cleanup_local_after_upload: bool = False
    s3_verify_uploads: bool = True

    # --- Async job queue (optional; falls back to Postgres, then in-memory) ---
    redis_url: str | None = None
    job_poll_interval_seconds: float = 1.0
    job_retention_seconds: int = 24 * 3600
    job_max_workers: int = 2
    job_timeout_seconds: int = 1800

    # --- Dynamic exploration on an Android emulator (opt-in) ---
    # Disabled by default so the existing synchronous /analyze path is untouched.
    exploration_enabled: bool = False
    # Tool discovery. Env names map case-insensitively, so ANDROID_SDK_ROOT,
    # ADB_PATH, EMULATOR_PATH and AVD_NAME all bind here. No path is hardcoded.
    android_sdk_root: str | None = None
    adb_path: str = "adb"
    emulator_path: str | None = None
    avd_name: str | None = None
    emulator_serial: str | None = None
    emulator_headless: bool = False
    emulator_cold_boot: bool = False
    emulator_wipe_data: bool = False
    emulator_gpu_mode: str = "auto"
    emulator_extra_args: str = ""
    emulator_stop_when_done: bool = True
    emulator_boot_timeout_seconds: int = 240
    adb_command_timeout_seconds: int = 60
    apk_install_timeout_seconds: int = 300
    exploration_timeout_seconds: int = 300
    exploration_max_states: int = 25
    exploration_max_actions: int = 200
    exploration_action_delay_ms: int = 900
    exploration_screenshot_format: str = "png"
    exploration_s3_prefix: str = "exploration"
    exploration_keep_apk: bool = True
    ad_detection_vision_enabled: bool = False
    # Phase 3: screenshot / visual-state similarity (0.0-1.0). Higher = stricter uniqueness.
    exploration_state_similarity_threshold: float = 0.92
    exploration_hash_size: int = 16
    # Fraction of screen height ignored at top/bottom when hashing (status bar / nav chrome).
    exploration_hash_crop_top: float = 0.04
    exploration_hash_crop_bottom: float = 0.03
    # Phase 4: deterministic exploration limits (unique states, not blind screenshots).
    # TARGET_STATES_PER_PAGE / MAX_STATES_PER_PAGE / MAX_EXPLORATION_DEPTH
    exploration_target_states_per_page: int = 5
    exploration_max_states_per_page: int = 10
    exploration_max_depth: int = 20
    exploration_stabilize_ms: int = 500
    exploration_splash_wait_seconds: float = 3.0
    # How long to poll a non-interactive splash / loading screen before giving up.
    exploration_splash_max_wait_seconds: float = 45.0
    # Max repeated splash waits (each wait is splash_wait_seconds) inside the poll loop.
    exploration_splash_max_polls: int = 15
    # Phase 5: unique advertisement placement variations (not blind screenshot quotas).
    # TARGET_AD_VARIATIONS_PER_PAGE / MAX_AD_VARIATIONS_PER_PAGE / MAX_EXPLORATION_RUNS
    exploration_target_ad_variations_per_page: int = 5
    exploration_max_ad_variations_per_page: int = 10
    exploration_max_runs: int = 5
    exploration_ad_bbox_quantize: float = 0.05
    # Phase 6: screenshot advertisement detection (vision providers; no emulator control).
    ad_detection_enabled: bool = True
    ad_detection_provider: str = "heuristic"  # heuristic|openai|gemini|claude|local|object_detection
    ad_detection_min_confidence: float = 0.45
    ad_detection_timeout_seconds: float = 60.0
    # Shared / provider-specific API keys (optional).
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    anthropic_api_key: str | None = None
    ad_detection_openai_api_key: str | None = None
    ad_detection_gemini_api_key: str | None = None
    ad_detection_anthropic_api_key: str | None = None
    ad_detection_openai_model: str = "gpt-4o-mini"
    ad_detection_openai_api_base: str = "https://api.openai.com/v1"
    ad_detection_gemini_model: str = "gemini-1.5-flash"
    ad_detection_claude_model: str = "claude-3-5-sonnet-latest"
    ad_detection_anthropic_api_base: str = "https://api.anthropic.com"
    ad_detection_local_model_path: str | None = None
    ad_detection_local_fallback_heuristic: bool = True
    ad_detection_od_model_path: str | None = None

    # --- Phase 7: Human-in-the-Loop (HITL) ---
    hitl_enabled: bool = True
    hitl_timeout_seconds: int = 1800
    # Comma-separated Android / OEM packages treated as system UI.
    hitl_system_packages: str = (
        "com.android.settings,com.android.permissioncontroller,"
        "com.google.android.permissioncontroller,com.google.android.packageinstaller,"
        "com.android.packageinstaller,com.google.android.settings,com.android.systemui,"
        "com.android.vpndialogs,com.google.android.gms"
    )
    hitl_unknown_blocking_enabled: bool = True

    # --- Phase 10: AI / LangGraph decision layer (optional) ---
    # Prefer deterministic rules; AI only chooses among allow-listed actions.
    # Default provider: NVIDIA OpenAI-compatible endpoint (Nemotron).
    ai_explorer_enabled: bool = False
    ai_explorer_api_key: str | None = None  # NVIDIA nvapi-... key (or OPENAI_API_KEY fallback)
    ai_explorer_api_base: str = "https://integrate.api.nvidia.com/v1"
    ai_explorer_model: str = "nvidia/nemotron-3.5-lightning-30b-a3b"
    ai_explorer_timeout_seconds: float = 60.0
    ai_explorer_min_candidates: int = 3
    # Some OpenAI-compatible hosts (incl. NVIDIA) reject response_format=json_object.
    ai_explorer_json_response_format: bool = False

    @property
    def exploration_ready(self) -> bool:
        """True when dynamic exploration is switched on and has an ADB binary configured."""
        return bool(self.exploration_enabled and (self.adb_path or "").strip())

    @property
    def redis_enabled(self) -> bool:
        return bool((self.redis_url or "").strip())

    @property
    def s3_enabled(self) -> bool:
        """True when bucket + credentials are set (endpoint optional for AWS)."""
        return bool(
            (self.s3_access_key or "").strip()
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
