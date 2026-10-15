"""Golden cases for the AI privacy-policy check.

Each case is a small audit JSON plus a privacy policy, with the answer a careful reviewer would
give. ``offline_reply`` is a canned model reply used to test the validators without a model; it
deliberately includes invented quotes and fact ids that must be dropped.

Add a case whenever the report gets something wrong on a real app: copy the relevant fields of
the audit JSON and the policy, then write down what the right answer is.
"""

from __future__ import annotations

from typing import Any

POLICY_LOCATION_ONLY = (
    "FitPal Privacy Policy. We collect your approximate location to show nearby workouts. "
    "We do not sell your personal information to third parties. "
    "You can delete your account at any time from the settings screen, and we then delete your data within 30 days. "
    "We use industry standard security to protect your data."
)

POLICY_DISCLOSES_ALL = (
    "FitPal Privacy Policy. We collect your approximate location to show nearby workouts. "
    "With your permission we read your contacts so you can invite friends to workouts. "
    "We use Google AdMob to show advertising, which may use your advertising ID. "
    "We use analytics to improve the app. We do not sell your personal information. "
    "You can delete your account at any time and we delete your data within 30 days."
)

POLICY_NO_ADS = (
    "FitPal Privacy Policy. FitPal is an ad-free app and never shows advertising. "
    "We collect your approximate location to show nearby workouts. "
    "We do not share your data with advertising networks. You can delete your account at any time."
)


def audit(permissions: list[str], sdks: list[str]) -> dict[str, Any]:
    return {
        "data": {
            "apk": {"package_name": "com.fitpal.tracker", "version_name": "3.2.1"},
            "sdk": {"target_sdk": 34},
            "submission": {"app_name": "FitPal", "app_description": "Workout tracker", "privacy_policy": "https://fitpal.example/privacy"},
            "permissions": [{"name": f"android.permission.{name}"} for name in permissions],
            "code_analysis": {"third_party_sdk_usage": [{"name": name} for name in sdks], "network_calls": [1, 2]},
        }
    }


CASES: list[dict[str, Any]] = [
    {
        "name": "contacts_not_disclosed",
        "result": audit(["ACCESS_COARSE_LOCATION", "READ_CONTACTS"], []),
        "policy": POLICY_LOCATION_ONLY,
        "expect": {"issues": [{"evidence_any": ["perm:READ_CONTACTS"], "types": ["undisclosed_data_use", "vague_or_missing"]}]},
        "offline_reply": {
            "summary": "Contacts access is not mentioned in the policy.",
            "claims": [
                {"topic": "location", "statement": "Collects approximate location", "quote": "We collect your approximate location to show nearby workouts"},
                {"topic": "ads", "statement": "Invented claim", "quote": "We share your contacts with partners for marketing"},
            ],
            "issues": [
                {"type": "undisclosed_data_use", "severity": "high", "title": "Contacts access not disclosed", "evidence_ids": ["perm:READ_CONTACTS"], "claim_topics": [], "recommended_fix": "Disclose contacts use."},
                {"type": "undisclosed_data_use", "severity": "high", "title": "Microphone not disclosed", "evidence_ids": ["perm:RECORD_AUDIO"], "claim_topics": [], "recommended_fix": "x"},
            ],
        },
        "offline_expect": {"issues": 1, "claims": 1, "min_dropped": 2},
    },
    {
        "name": "fully_disclosed",
        "result": audit(["ACCESS_COARSE_LOCATION", "READ_CONTACTS"], ["Google AdMob"]),
        "policy": POLICY_DISCLOSES_ALL,
        "expect": {"issues": []},
        "offline_reply": {
            "summary": "The policy covers the data the app uses.",
            "claims": [
                {"topic": "contacts", "statement": "Reads contacts to invite friends", "quote": "With your permission we read your contacts so you can invite friends to workouts"},
                {"topic": "ads", "statement": "Uses AdMob", "quote": "We use Google AdMob to show advertising"},
            ],
            "issues": [],
        },
        "offline_expect": {"issues": 0, "claims": 2, "min_dropped": 0},
    },
    {
        "name": "policy_says_no_ads_but_app_has_ads",
        "result": audit(["ACCESS_COARSE_LOCATION"], ["Google AdMob"]),
        "policy": POLICY_NO_ADS,
        "expect": {"issues": [{"evidence_any": ["sdk:google-admob"], "types": ["contradiction"]}]},
        "offline_reply": {
            "summary": "The policy says the app is ad-free but it contains an ad SDK.",
            "claims": [{"topic": "ads", "statement": "Says the app is ad-free", "quote": "FitPal is an ad-free app and never shows advertising"}],
            "issues": [
                {"type": "contradiction", "severity": "high", "title": "Policy says ad-free but AdMob is present", "evidence_ids": ["sdk:google-admob"], "claim_topics": ["ads"], "recommended_fix": "Update the policy."},
                {"type": "contradiction", "severity": "medium", "title": "Contradiction on a topic never claimed", "evidence_ids": ["sdk:google-admob"], "claim_topics": ["children"], "recommended_fix": "x"},
            ],
        },
        "offline_expect": {"issues": 1, "claims": 1, "min_dropped": 1},
    },
    {
        "name": "location_only_app_is_clean",
        "result": audit(["ACCESS_COARSE_LOCATION"], []),
        "policy": POLICY_LOCATION_ONLY,
        "expect": {"issues": []},
        "offline_reply": {"summary": "No mismatch.", "claims": [], "issues": []},
        "offline_expect": {"issues": 0, "claims": 0, "min_dropped": 0},
    },
]
