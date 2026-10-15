"""A numbered fact sheet built from an audit's JSON.

Every AI statement must cite fact ids from this sheet, so anything the model claims can be
checked against the data the analysis actually found. Facts are plain, short and factual:
nothing here is interpreted. Ids are stable (``perm:READ_CONTACTS``, ``sdk:google-admob``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_AD_SDK_HINTS = (
    "admob", "ads", "applovin", "unity", "ironsource", "mintegral", "vungle",
    "chartboost", "audience", "inmobi", "pangle", "adcolony",
)


@dataclass(frozen=True)
class Fact:
    id: str
    text: str


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:48] or "unknown"


def _short_permission(name: str) -> str:
    return name.rsplit(".", 1)[-1]


def build_facts(result: dict[str, Any]) -> list[Fact]:
    data = result.get("data") or {}
    code = data.get("code_analysis") or {}
    exploration = data.get("exploration") or {}
    submission = data.get("submission") or {}
    facts: list[Fact] = []

    def add(fact_id: str, text: str) -> None:
        if all(f.id != fact_id for f in facts):
            facts.append(Fact(fact_id, text))

    apk = data.get("apk") or {}
    if apk.get("package_name"):
        add("app:package", f"Package name is {apk['package_name']}.")
    if (data.get("sdk") or {}).get("target_sdk") is not None:
        add("app:target_sdk", f"Target SDK is {data['sdk']['target_sdk']}.")
    if submission.get("app_description"):
        add("app:description", f"Submitted description: {str(submission['app_description'])[:300]}")

    for item in (data.get("permissions") or [])[:80]:
        name = item.get("name") if isinstance(item, dict) else str(item)
        if name:
            add(f"perm:{_short_permission(str(name))}", f"The manifest declares permission {name}.")

    for item in (code.get("third_party_sdk_usage") or [])[:40]:
        name = str(item.get("name") if isinstance(item, dict) else item or "")
        if not name:
            continue
        kind = "an advertising SDK" if any(h in name.lower() for h in _AD_SDK_HINTS) else "a third-party SDK"
        add(f"sdk:{_slug(name)}", f"The code uses {name}, {kind}.")

    for key, label in (
        ("network_calls", "network calls"),
        ("dynamic_code_loading", "dynamic code loading sites"),
        ("data_access_indicators", "data access indicators (contacts, storage, accounts and similar)"),
        ("telephony_calls", "telephony API calls"),
    ):
        count = len(code.get(key) or [])
        if count:
            add(f"code:{key}", f"The code contains {count} {label}.")

    exported = (data.get("components") or {}).get("exported") or []
    if exported:
        add("components:exported", f"{len(exported)} components are exported to other apps.")

    policy = submission.get("privacy_policy")
    add(
        "policy:provided",
        "A privacy policy was provided with the submission." if policy else "No privacy policy was provided with the submission.",
    )

    if exploration.get("status"):
        add("explore:status", f"Emulator exploration status: {exploration['status']}; {len(exploration.get('states') or [])} screens visited.")
    for index, entry in enumerate((exploration.get("ad_timeline") or [])[:20]):
        screen = entry.get("page") or entry.get("activity") or "a screen"
        types = sorted({s.get("ad_type") for s in entry.get("sightings") or [] if s.get("ad_type")})
        positions = ", ".join(entry.get("positions_seen") or [])
        moved = " The ad position changed while the screen was open." if entry.get("position_changed") else ""
        add(f"ad:{index + 1}", f"Ads seen on {screen}: {', '.join(types) or 'unknown type'} at {positions or 'unknown position'}.{moved}")
    return facts


def render_facts(facts: list[Fact]) -> str:
    return "\n".join(f"{f.id}: {f.text}" for f in facts)


def fact_ids(facts: list[Fact]) -> set[str]:
    return {f.id for f in facts}
