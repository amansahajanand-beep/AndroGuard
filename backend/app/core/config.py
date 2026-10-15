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

    # --- Password reset email (SMTP). Never log these values. ---
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = Field(default=None, validation_alias=AliasChoices("smtp_username", "smtp_user"))
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_use_tls: bool = True  # STARTTLS on 587; set SMTP_USE_SSL for implicit TLS on 465
    smtp_use_ssl: bool = False
    frontend_base_url: str = "http://localhost:5173"
    password_reset_expire_minutes: int = 30

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
    # Phase 12I — worker / emulator isolation (safe defaults: 1 concurrent job).
    exploration_worker_concurrency: int = 1
    exploration_emulator_serials: str = ""  # comma-separated; empty = single auto device
    exploration_job_max_attempts: int = 2
    exploration_cleanup_timeout_seconds: float = 60.0
    exploration_worker_heartbeat_seconds: float = 10.0
    exploration_worker_stale_timeout_seconds: float = 120.0

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
    # Phase 12G: first_match | discover_all (default preserves multi-placement behavior).
    exploration_ad_discovery_mode: str = "discover_all"
    # Phase 12H: bounded settle when waiting for delayed runtime ads (seconds).
    exploration_ad_discovery_settle_seconds: float = 1.0
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
    ad_detection_claude_model: str = "claude-sonnet-5-5"
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
    # Minimum AI confidence to accept a selection (else deterministic fallback).
    ai_explorer_min_confidence: float = 0.70
    # Some OpenAI-compatible hosts (incl. NVIDIA) reject response_format=json_object.
    ai_explorer_json_response_format: bool = False
    # When enabled, auto-clear permissions/default/consent/forms/ads before HITL.
    # Deterministic taps work even without AI_EXPLORER_ENABLED; LLM ranks when on.
    # Stay on each new screen and record how its ads appear / move over time.
    ad_dwell_enabled: bool = True
    ad_dwell_seconds: float = 6.0
    ad_dwell_interval_seconds: float = 1.5
    ad_dwell_max_frames: int = 4  # extra screenshots per screen (taken only when the ad layout changes)
    ad_dwell_budget_seconds: float = 150.0  # total dwell time per run
    # What to do on "Set as default / Home app" screens: dismiss (never become Home) or grant.
    default_app_policy: str = "dismiss"
    # Vision-guided tap choice (Claude looks at the screenshot like a first-time user). Off by default:
    # it makes one model call per decision step, capped by vision_planner_max_calls per run.
    vision_planner_enabled: bool = False
    vision_planner_api_key: str | None = None  # falls back to ANTHROPIC_API_KEY
    vision_planner_model: str = "claude-haiku-5-5"
    vision_planner_api_base: str = "https://api.anthropic.com"
    vision_planner_timeout_seconds: float = 20.0
    vision_planner_max_calls: int = 40
    vision_planner_min_candidates: int = 2
    # AI-written review (summary + per-risk explanations) stored under data.ai_review.
    # Uses only the audit's own evidence; rule-based verdicts are never changed.
    ai_report_enabled: bool = False
    ai_report_disable_thinking: bool = True  # NVIDIA reasoning models: skip the hidden thinking (it can use every token)
    ai_report_provider: str = "anthropic"  # anthropic | nvidia | openai (the last two are OpenAI-compatible)
    ai_report_api_key: str | None = None  # falls back to ANTHROPIC_API_KEY
    ai_report_model: str = "claude-sonnet-5-5"
    ai_report_api_base: str = "https://api.anthropic.com"
    ai_report_timeout_seconds: float = 90.0
    ai_policy_max_chars: int = 24000  # privacy policy characters sent to the model
    # Read the UI tree through uiautomator2 first (works on animated screens where
    # `uiautomator dump` fails with "could not get idle state"); adb dump stays as fallback.
    uiautomator2_enabled: bool = True
    # End the run when this many actions in a row reveal no new screen (the app is explored).
    exploration_stall_actions: int = 30
    # Swipes allowed per screen before the agent must tap something (swipes that change nothing loop forever).
    exploration_max_swipes_per_state: int = 2
    log_to_file: bool = True  # also write logs to tmp/backend.log
    ad_escape_enabled: bool = True  # verified close/wait/back/relaunch when an ad is on screen
    ai_assist_gates_enabled: bool = True
    ai_assist_max_steps: int = 6
    # When AI explorer is on, optionally LLM-refine the static exploration blueprint.
    ai_exploration_plan_enabled: bool = True
    # Max actions on one nav-map step before skip + recover (any APK).
    exploration_journey_step_budget: int = 8
    # Visit every discovered home/sidebar/section/settings goal before stopping.
    exploration_full_coverage_enabled: bool = True
    # Soft floor applied when full coverage is on (env can still set higher).
    exploration_full_coverage_min_states: int = 50
    exploration_full_coverage_min_actions: int = 400
    exploration_full_coverage_min_timeout_seconds: int = 600
    exploration_full_coverage_min_states_per_page: int = 12
    exploration_full_coverage_step_budget: int = 12

    # --- Phase 12J: human-like gesture / spatial exploration ---
    exploration_gesture_max_per_region: int = 4
    exploration_gesture_no_change_limit: int = 2
    exploration_gesture_distance_ratio: float = 0.7
    exploration_gesture_edge_margin: float = 0.15

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
