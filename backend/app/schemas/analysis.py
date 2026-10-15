from __future__ import annotations

from typing import Any

from pydantic import (
    BaseModel,
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)

from app.schemas.exploration import ExplorationResult


class AppSubmission(BaseModel):
    """Optional details supplied by the submitter alongside the APK upload."""

    app_name: str | None = Field(default=None, max_length=200)
    app_description: str | None = Field(default=None, max_length=4000)
    privacy_policy: str | None = Field(default=None, max_length=1024)
    privacy_policy_kind: str | None = None
    play_store_url: str | None = Field(default=None, max_length=1024)
    # Text of an uploaded policy, kept in memory for the AI comparison only (never stored or returned).
    privacy_policy_text: str | None = Field(default=None, exclude=True)
    privacy_policy_error: str | None = Field(default=None, exclude=True)

    @field_validator("*", mode="before")
    @classmethod
    def blank_to_none(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("play_store_url")
    @classmethod
    def http_url_only(cls, value: str | None) -> str | None:
        if value and not value.lower().startswith(("http://", "https://")):
            raise ValueError("must start with http:// or https://")
        return value

    @model_validator(mode="after")
    def classify_privacy_policy(self) -> "AppSubmission":
        if not self.privacy_policy:
            self.privacy_policy_kind = None
        elif self.privacy_policy.lower().startswith(("http://", "https://")):
            self.privacy_policy_kind = "url"
        else:
            self.privacy_policy_kind = "file_path"
        return self


class ApkIdentity(BaseModel):
    file_name: str
    file_size: int
    sha256: str
    package_name: str | None = None
    version_name: str | None = None
    version_code: int | None = None


class UsesFeature(BaseModel):
    name: str | None = None
    required: bool | None = None
    gl_es_version: str | None = None


class UsesLibrary(BaseModel):
    name: str | None = None
    required: bool | None = None


class ManifestInfo(BaseModel):
    package: str | None = None
    app_label: str | None = None
    version_name: str | None = None
    version_code: int | None = None
    debuggable: bool | None = None
    allow_backup: bool | None = None
    extract_native_libs: bool | None = None
    uses_cleartext_traffic: bool | None = None
    install_location: str | None = None
    shared_user_id: str | None = None
    uses_feature: list[UsesFeature] = Field(default_factory=list)
    uses_library: list[UsesLibrary] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)


class PermissionInfo(BaseModel):
    name: str
    max_sdk_version: int | None = None
    protection_level: str | None = None
    protection_level_source: str | None = None


class MetadataItem(BaseModel):
    name: str
    value: Any = None
    value_type: str


class SdkInfo(BaseModel):
    min_sdk: int | None = None
    target_sdk: int | None = None
    max_sdk: int | None = None
    compile_sdk: int | None = None
    min_platform: str | None = None
    target_platform: str | None = None


class IntentData(BaseModel):
    scheme: str | None = None
    host: str | None = None
    port: str | None = None
    path: str | None = None
    path_prefix: str | None = None
    path_pattern: str | None = None
    mime_type: str | None = None


class IntentFilter(BaseModel):
    actions: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    data: list[IntentData] = Field(default_factory=list)


class ActivityInfo(BaseModel):
    name: str
    exported: bool | None = None
    exported_inferred: bool = False
    enabled: bool | None = True
    permission: str | None = None
    direct_boot_aware: bool | None = None
    process: str | None = None
    launch_mode: str | None = None
    theme: str | None = None
    intent_filters: list[IntentFilter] = Field(default_factory=list)


class ServiceInfo(BaseModel):
    name: str
    exported: bool | None = None
    exported_inferred: bool = False
    enabled: bool | None = True
    permission: str | None = None
    direct_boot_aware: bool | None = None
    process: str | None = None
    foreground_service_type: str | None = None
    intent_filters: list[IntentFilter] = Field(default_factory=list)


class ScreenshotInfo(BaseModel):
    file_name: str
    url: str
    original_path: str
    width: int | None = None
    height: int | None = None
    format: str | None = None
    byte_size: int | None = None


class CodeClassInfo(BaseModel):
    name: str
    dalvik_name: str
    method_count: int = 0
    is_app_code: bool = False


class CodeMethodInfo(BaseModel):
    class_name: str
    name: str
    descriptor: str | None = None
    api_labels: list[str] = Field(default_factory=list)


class ApiCallInfo(BaseModel):
    api: str
    api_label: str
    category: str
    api_class: str | None = None
    api_method: str | None = None
    risk_category: str | None = None
    caller_class: str | None = None
    caller_method: str | None = None
    caller_descriptor: str | None = None
    confidence: str | None = None
    evidence: str | None = None


class MappedApiCall(BaseModel):
    """Confirmed class → method → sensitive API mapping for audit/LLM consumers."""

    class_name: str
    method_name: str
    method_signature: str | None = None
    api_class: str
    api_method: str
    api: str
    risk_category: str
    category: str | None = None
    evidence: str
    confidence: str = "HIGH"
    is_app_code: bool = False


class NetworkStringInfo(BaseModel):
    value: str
    kind: str
    caller_class: str | None = None
    caller_method: str | None = None


class SdkUsageInfo(BaseModel):
    name: str
    package_prefix: str
    class_count: int = 0
    sample_classes: list[str] = Field(default_factory=list)


class CodeFinding(BaseModel):
    id: str
    category: str
    title: str
    detail: str
    evidence: list[str] = Field(default_factory=list)


class CodeAnalysisSummary(BaseModel):
    dex_files: int = 0
    class_count: int = 0
    method_count: int = 0
    xref_built: bool = False
    truncated: bool = False


class CodeAnalysis(BaseModel):
    summary: CodeAnalysisSummary = Field(default_factory=CodeAnalysisSummary)
    classes: list[CodeClassInfo] = Field(default_factory=list)
    methods: list[CodeMethodInfo] = Field(default_factory=list)
    api_calls: list[MappedApiCall] = Field(default_factory=list)
    sensitive_api_calls: list[ApiCallInfo] = Field(default_factory=list)
    network_calls: list[ApiCallInfo] = Field(default_factory=list)
    webview_usage: list[ApiCallInfo] = Field(default_factory=list)
    file_storage_operations: list[ApiCallInfo] = Field(default_factory=list)
    telephony_calls: list[ApiCallInfo] = Field(default_factory=list)
    data_access_indicators: list[ApiCallInfo] = Field(default_factory=list)
    dynamic_code_loading: list[ApiCallInfo] = Field(default_factory=list)
    third_party_sdk_usage: list[SdkUsageInfo] = Field(default_factory=list)
    network_strings: list[NetworkStringInfo] = Field(default_factory=list)
    code_findings: list[CodeFinding] = Field(default_factory=list)


class AnalysisMeta(BaseModel):
    id: str | None = None
    status: str
    analyzed_at: str
    analyzer_version: str
    duration_ms: int
    warnings: list[str] = Field(default_factory=list)
    persisted: bool = False


class AnalysisData(BaseModel):
    ai_review: dict | None = None
    ai_policy_analysis: dict | None = None
    apk: ApkIdentity
    submission: AppSubmission = Field(default_factory=AppSubmission)
    manifest: ManifestInfo
    permissions: list[PermissionInfo] = Field(default_factory=list)
    metadata: list[MetadataItem] = Field(default_factory=list)
    sdk: SdkInfo
    activities: list[ActivityInfo] = Field(default_factory=list)
    services: list[ServiceInfo] = Field(default_factory=list)
    # Static raster assets pulled out of the APK archive (not emulator captures).
    screenshots: list[ScreenshotInfo] = Field(default_factory=list)
    code_analysis: CodeAnalysis = Field(default_factory=CodeAnalysis)
    analysis: AnalysisMeta
    # Dynamic emulator exploration. Absent entirely on the synchronous /analyze path,
    # so existing response payloads stay unchanged.
    exploration: ExplorationResult | None = None

    @model_serializer(mode="wrap")
    def _omit_absent_exploration(self, handler: SerializerFunctionWrapHandler) -> Any:
        data = handler(self)
        if isinstance(data, dict) and data.get("exploration") is None:
            data.pop("exploration", None)
        return data


class AnalysisResponse(BaseModel):
    schema_version: str
    status: str
    data: AnalysisData
