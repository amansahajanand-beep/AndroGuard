"""Rule patterns that classify screens requiring human intervention."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.modules.hitl.intervention_types import InterventionType


@dataclass(frozen=True)
class RulePattern:
    intervention_type: InterventionType
    title: str
    pattern: re.Pattern[str]
    weight: float = 1.0
    suggested_action: str | None = None


def _rx(*parts: str) -> re.Pattern[str]:
    return re.compile("|".join(parts), re.IGNORECASE)


# Default system / OEM packages that often host decision dialogs.
DEFAULT_SYSTEM_PACKAGES: tuple[str, ...] = (
    "com.android.settings",
    "com.android.permissioncontroller",
    "com.google.android.permissioncontroller",
    "com.google.android.packageinstaller",
    "com.android.packageinstaller",
    "com.google.android.settings",
    "com.android.systemui",
    "com.google.android.gms",
    "com.android.vpndialogs",
    "com.android.certinstaller",
    "com.samsung.android.packageinstaller",
    "com.miui.securitycenter",
    "com.huawei.systemmanager",
)

TERMS_PATTERNS: tuple[RulePattern, ...] = (
    RulePattern(
        InterventionType.TERMS_CONSENT,
        "Accept Terms",
        _rx(
            r"terms\s*(and|&)\s*conditions",
            r"terms\s*of\s*(service|use)",
            r"\bi\s*agree\b",
            r"accept\s*terms",
            r"agree\s*(and|&)\s*continue",
            r"legal\s*agreement",
            r"end\s*user\s*license",
            r"\beula\b",
        ),
        suggested_action="Review terms, then Agree / Accept in the emulator",
    ),
)

PRIVACY_PATTERNS: tuple[RulePattern, ...] = (
    RulePattern(
        InterventionType.PRIVACY_CONSENT,
        "Agree to Privacy Policy",
        _rx(
            r"privacy\s*policy",
            r"privacy\s*notice",
            r"agree\s*to\s*privacy",
            r"data\s*protection",
            r"gdpr",
            r"consent\s*to\s*(data|privacy)",
            r"personal\s*data",
        ),
        suggested_action="Review privacy policy, then Agree / Continue in the emulator",
    ),
)

PERMISSION_PATTERNS: tuple[RulePattern, ...] = (
    RulePattern(
        InterventionType.PERMISSION,
        "Android Permission",
        _rx(
            r"allow\s+\w+\s+to\s+",
            r"while\s+using\s+the\s+app",
            r"only\s+this\s+time",
            r"don'?t\s+allow",
            r"allow\s+notifications?",
            r"allow\s+camera",
            r"allow\s+microphone",
            r"allow\s+location",
            r"allow\s+photos?",
            r"allow\s+media",
            r"allow\s+storage",
            r"allow\s+contacts?",
            r"allow\s+phone",
            r"access\s+(this\s+)?device'?s?\s+location",
            r"permission\s*required",
            r"wants\s+to\s+send\s+you\s+notifications",
        ),
        suggested_action="Allow or Deny the permission in the emulator",
    ),
)

DEFAULT_APP_PATTERNS: tuple[RulePattern, ...] = (
    RulePattern(
        InterventionType.DEFAULT_APP,
        "Set as default app",
        _rx(
            r"set\s+as\s+default",
            r"make\s+default",
            r"set\s+as\s+default\s+(browser|launcher|app|phone|sms|home)",
            r"choose\s+default\s+app",
            r"default\s+application",
            r"always\s+use\s+this\s+app",
            r"use\s+as\s+default",
            r"select\s+a\s+home\s+app",
        ),
        suggested_action="Choose the default app (or cancel) in the emulator",
    ),
)

SYSTEM_SETTINGS_PATTERNS: tuple[RulePattern, ...] = (
    RulePattern(
        InterventionType.SYSTEM_SETTINGS,
        "System settings decision",
        _rx(
            r"allow\s+from\s+this\s+source",
            r"install\s+unknown\s+apps",
            r"change\s+system\s+settings",
            r"accessibility",
            r"display\s+over\s+other\s+apps",
            r"appear\s+on\s+top",
            r"battery\s+optimization",
            r"notification\s+access",
            r"vpn\s+(connection|confirmation|permission)",
            r"device\s+administrator",
            r"modify\s+system\s+settings",
            r"usage\s+access",
            r"all\s+files\s+access",
        ),
        suggested_action="Complete the system settings change in the emulator",
    ),
)

LOGIN_PATTERNS: tuple[RulePattern, ...] = (
    RulePattern(
        InterventionType.LOGIN,
        "Sign in required",
        _rx(
            r"\blog\s*in\b",
            r"\bsign\s*in\b",
            r"username",
            r"password",
            r"email\s*address",
            r"create\s*account",
            r"forgot\s*password",
        ),
        weight=0.9,
        suggested_action="Sign in (or skip) in the emulator",
    ),
)

OTP_PATTERNS: tuple[RulePattern, ...] = (
    RulePattern(
        InterventionType.OTP,
        "Verification code required",
        _rx(
            r"\botp\b",
            r"one[\s-]*time\s*(pass)?(code|word|password)",
            r"verification\s*code",
            r"enter\s*(the\s*)?code",
            r"sms\s*code",
            r"6[\s-]*digit",
        ),
        suggested_action="Enter the verification code in the emulator",
    ),
)

CAPTCHA_PATTERNS: tuple[RulePattern, ...] = (
    RulePattern(
        InterventionType.CAPTCHA,
        "Human verification (CAPTCHA)",
        _rx(
            r"captcha",
            r"recaptcha",
            r"verify\s+you\s+are\s+(a\s+)?human",
            r"i'?m\s+not\s+a\s+robot",
            r"human\s+verification",
            r"select\s+all\s+images",
        ),
        suggested_action="Complete the CAPTCHA in the emulator",
    ),
)

VERIFICATION_PATTERNS: tuple[RulePattern, ...] = (
    RulePattern(
        InterventionType.VERIFICATION,
        "Account / device verification",
        _rx(
            r"account\s+verification",
            r"verify\s+(your\s+)?(email|phone|account|device)",
            r"google\s+account",
            r"device\s+verification",
            r"security\s+confirmation",
            r"confirm\s+(it'?s|it\s+is)\s+you",
            r"two[\s-]*factor",
            r"\b2fa\b",
        ),
        suggested_action="Complete verification in the emulator (type/confirm as asked)",
    ),
)

CREATE_CONTENT_PATTERNS: tuple[RulePattern, ...] = (
    RulePattern(
        InterventionType.CREATE_CONTENT,
        "Create or set up something",
        _rx(
            r"create\s+(new\s+)?(alarm|event|timer|task|note|account|profile|reminder)",
            r"add\s+(new\s+)?(alarm|event|timer|task|note|reminder|item)",
            r"set\s+(up|an?\s+alarm|a\s+timer|a\s+reminder)",
            r"new\s+(alarm|event|timer|task|note|reminder)",
            r"enter\s+(a\s+)?(name|title|label)",
            r"give\s+it\s+a\s+name",
            r"what\s+should\s+we\s+call",
        ),
        weight=1.05,
        suggested_action="Create/setup in the emulator: type name, select options, then Save/Create",
    ),
)

SELECTION_PATTERNS: tuple[RulePattern, ...] = (
    RulePattern(
        InterventionType.SELECTION,
        "Select an option",
        _rx(
            r"select\s+(a|an|your|the)\s+\w+",
            r"choose\s+(a|an|your|the)\s+\w+",
            r"pick\s+(a|an|your|the)\s+\w+",
            r"please\s+select",
            r"select\s+language",
            r"choose\s+language",
            r"select\s+country",
            r"choose\s+from\s+the\s+list",
        ),
        suggested_action="Select the required option in the emulator, then Continue",
    ),
)

FORM_INPUT_PATTERNS: tuple[RulePattern, ...] = (
    RulePattern(
        InterventionType.FORM_INPUT,
        "Type required information",
        _rx(
            r"enter\s+(your\s+)?(name|email|phone|title|message|details)",
            r"type\s+(your\s+)?(name|email|phone|title)",
            r"fill\s+(in|out)\s+(the\s+)?(form|fields|details)",
            r"required\s+field",
            r"this\s+field\s+is\s+required",
        ),
        suggested_action="Tap fields and type with the emulator keyboard, then Save/Next",
    ),
)

ALL_RULE_GROUPS: tuple[tuple[RulePattern, ...], ...] = (
    CAPTCHA_PATTERNS,
    OTP_PATTERNS,
    VERIFICATION_PATTERNS,
    PERMISSION_PATTERNS,
    DEFAULT_APP_PATTERNS,
    SYSTEM_SETTINGS_PATTERNS,
    CREATE_CONTENT_PATTERNS,
    SELECTION_PATTERNS,
    FORM_INPUT_PATTERNS,
    TERMS_PATTERNS,
    PRIVACY_PATTERNS,
    LOGIN_PATTERNS,
)

# Activity / package name hints (checked independently of visible text).
ACTIVITY_HINTS: tuple[tuple[InterventionType, str, re.Pattern[str]], ...] = (
    (InterventionType.TERMS_CONSENT, "Accept Terms", _rx(r"terms", r"eula", r"licenseagreement")),
    (InterventionType.PRIVACY_CONSENT, "Agree to Privacy Policy", _rx(r"privacy", r"gdpr", r"consent")),
    (InterventionType.DEFAULT_APP, "Set as default app", _rx(r"defaultapp", r"default_app", r"role\.request")),
    (InterventionType.PERMISSION, "Android Permission", _rx(r"permission", r"grantpermissions")),
    (InterventionType.LOGIN, "Sign in required", _rx(r"login", r"signin", r"sign_in", r"auth")),
    (InterventionType.CAPTCHA, "Human verification (CAPTCHA)", _rx(r"captcha")),
)

# Phrases that look like a blocking CTA without a more specific match.
BLOCKING_CTA = _rx(
    r"^(agree|accept|continue|allow|deny|confirm|submit|verify|next)$",
)

# Screens that are clearly non-blocking content (suppress unknown_blocking).
NORMAL_CONTENT_HINTS = _rx(
    r"\b(home|settings|profile|games?|alarm|timer|clock|inbox|feed|search|"
    r"library|gallery|camera\s*roll|playlist|dashboard|menu)\b",
)
