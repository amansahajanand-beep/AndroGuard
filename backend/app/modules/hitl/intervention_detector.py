"""Detect screens that require a human decision before exploration continues."""

from __future__ import annotations

import re
from typing import Sequence

from app.core.config import settings
from app.modules.exploration.ui_element import UIElement
from app.modules.hitl.intervention_rules import (
    ACTIVITY_HINTS,
    ALL_RULE_GROUPS,
    BLOCKING_CTA,
    DEFAULT_SYSTEM_PACKAGES,
    NORMAL_CONTENT_HINTS,
    RulePattern,
)
from app.modules.hitl.intervention_types import DetectionResult, InterventionType


def _package_of(activity: str | None, package: str | None) -> str | None:
    if package:
        return package
    if activity and "/" in activity:
        return activity.split("/", 1)[0]
    return None


def _visible_corpus(elements: Sequence[UIElement]) -> str:
    chunks: list[str] = []
    for el in elements:
        for value in (el.text, el.content_description, el.resource_id):
            if value and value.strip():
                chunks.append(value.strip())
    return "\n".join(chunks)


def _visible_labels(elements: Sequence[UIElement], *, limit: int = 40) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for el in elements:
        for value in (el.text, el.content_description):
            text = (value or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            labels.append(text)
            if len(labels) >= limit:
                return labels
    return labels


class InterventionDetector:
    """Rule-based HITL detector over UIAutomator dumps + activity/package."""

    def __init__(
        self,
        *,
        system_packages: Sequence[str] | None = None,
        target_package: str | None = None,
        enable_unknown_blocking: bool | None = None,
    ) -> None:
        configured = getattr(settings, "hitl_system_packages", None)
        if system_packages is not None:
            pkgs = list(system_packages)
        elif configured:
            pkgs = [p.strip() for p in str(configured).split(",") if p.strip()]
        else:
            pkgs = list(DEFAULT_SYSTEM_PACKAGES)
        self.system_packages = {p.lower() for p in pkgs}
        self.target_package = target_package
        if enable_unknown_blocking is None:
            enable_unknown_blocking = bool(
                getattr(settings, "hitl_unknown_blocking_enabled", True)
            )
        self.enable_unknown_blocking = enable_unknown_blocking

    def is_system_package(self, package: str | None) -> bool:
        if not package:
            return False
        lowered = package.lower()
        if lowered in self.system_packages:
            return True
        # Substring matches for OEM / AOSP forks of known system surfaces.
        markers = (
            "permissioncontroller",
            "packageinstaller",
            "systemui",
            "vpndialogs",
        )
        if any(marker in lowered for marker in markers):
            return True
        if lowered.endswith(".settings") or lowered == "com.android.settings":
            return True
        return False

    def detect(
        self,
        *,
        elements: Sequence[UIElement],
        package: str | None = None,
        activity: str | None = None,
        screenshot_path: str | None = None,
    ) -> DetectionResult:
        """Return whether the current screen requires human intervention.

        ``screenshot_path`` is accepted for API symmetry; classification is
        driven by hierarchy text + package/activity (no vision required).
        """
        _ = screenshot_path
        pkg = _package_of(activity, package)
        corpus = _visible_corpus(elements)
        labels = _visible_labels(elements)
        is_system = self.is_system_package(pkg)

        # 1) Activity / package name hints.
        activity_hit = self._match_activity(activity)
        if activity_hit is not None:
            activity_hit.is_system_ui = is_system or activity_hit.is_system_ui
            return activity_hit

        # 2) Visible-text rule groups (most specific first via ALL_RULE_GROUPS order).
        text_hit = self._match_rules(corpus, labels, is_system=is_system)
        if text_hit is not None:
            return text_hit

        # 3) System UI that still looks like a decision dialog.
        if is_system and self._looks_like_system_decision(elements, corpus):
            return DetectionResult(
                required=True,
                type=InterventionType.SYSTEM_SETTINGS,
                title="System UI decision",
                message="A system screen requires a human decision.",
                evidence=[f"system_package:{pkg}"] + labels[:8],
                confidence=0.7,
                is_system_ui=True,
                suggested_action="Complete the system prompt in the emulator",
            )

        # 4) Unknown blocking: consent-like CTAs with little other content.
        if self.enable_unknown_blocking and self._looks_unknown_blocking(
            elements, corpus, labels, package=pkg
        ):
            return DetectionResult(
                required=True,
                type=InterventionType.UNKNOWN_BLOCKING_SCREEN,
                title="Unknown blocking screen",
                message="The agent cannot safely continue; human review required.",
                evidence=labels[:10],
                confidence=0.55,
                is_system_ui=is_system,
                suggested_action="Clear the blocking screen in the emulator, then Continue",
            )

        return DetectionResult(required=False)

    def still_blocked(
        self,
        *,
        elements: Sequence[UIElement],
        package: str | None,
        activity: str | None,
        previous: DetectionResult | None = None,
        previous_fingerprint: str | None = None,
        current_fingerprint: str | None = None,
    ) -> bool:
        """True when Continue was clicked but the blocking screen remains."""
        again = self.detect(elements=elements, package=package, activity=activity)
        if again.required:
            if previous is None or again.type == previous.type:
                return True
            # Different intervention still means human work is unfinished.
            return True
        if (
            previous_fingerprint
            and current_fingerprint
            and previous_fingerprint == current_fingerprint
            and previous
            and previous.required
        ):
            return True
        return False

    # ------------------------------------------------------------------ helpers

    def _match_activity(self, activity: str | None) -> DetectionResult | None:
        if not activity:
            return None
        lowered = activity.lower()
        for itype, title, pattern in ACTIVITY_HINTS:
            if pattern.search(lowered):
                return DetectionResult(
                    required=True,
                    type=itype,
                    title=title,
                    message="Human action required",
                    evidence=[f"activity:{activity}"],
                    confidence=0.85,
                    is_system_ui=False,
                )
        return None

    def _match_rules(
        self,
        corpus: str,
        labels: list[str],
        *,
        is_system: bool,
    ) -> DetectionResult | None:
        if not corpus.strip():
            return None
        best: tuple[float, RulePattern, str] | None = None
        for group in ALL_RULE_GROUPS:
            for rule in group:
                match = rule.pattern.search(corpus)
                if not match:
                    continue
                score = rule.weight
                # Login alone on a normal content page is common ("Log in" menu).
                if rule.intervention_type is InterventionType.LOGIN:
                    if not self._login_looks_blocking(corpus, labels):
                        continue
                    score *= 0.85
                if best is None or score > best[0]:
                    best = (score, rule, match.group(0))
            if best is not None and best[0] >= 0.9:
                break
        if best is None:
            return None
        score, rule, snippet = best
        return DetectionResult(
            required=True,
            type=rule.intervention_type,
            title=rule.title,
            message="Human action required",
            evidence=[f"text:{snippet}"] + labels[:6],
            confidence=min(0.99, 0.6 + 0.2 * score),
            is_system_ui=is_system,
            suggested_action=rule.suggested_action,
        )

    def _login_looks_blocking(self, corpus: str, labels: list[str]) -> bool:
        lowered = corpus.lower()
        has_password = "password" in lowered or "username" in lowered or "email" in lowered
        has_sign_cta = any(
            re.search(r"^(log\s*in|sign\s*in|continue)$", (lab or "").strip(), re.I)
            for lab in labels
        )
        fieldish = sum(
            1
            for lab in labels
            if re.search(r"password|email|username|phone", lab, re.I)
        )
        return bool(has_password or (has_sign_cta and fieldish >= 1) or fieldish >= 2)

    def _looks_like_system_decision(
        self, elements: Sequence[UIElement], corpus: str
    ) -> bool:
        if not corpus.strip():
            return False
        has_choice = any(
            re.search(r"^(allow|deny|while using|only this time|accept|cancel|ok)$", (el.text or "").strip(), re.I)
            for el in elements
            if el.clickable and el.text
        )
        return has_choice or bool(
            re.search(r"allow|permission|default|settings", corpus, re.I)
        )

    def _looks_unknown_blocking(
        self,
        elements: Sequence[UIElement],
        corpus: str,
        labels: list[str],
        *,
        package: str | None,
    ) -> bool:
        if self.target_package and package and package != self.target_package:
            # Already left the app without a classified reason.
            if not self.is_system_package(package):
                return True
        if NORMAL_CONTENT_HINTS.search(corpus) and not BLOCKING_CTA.search(corpus):
            return False
        clickables = [el for el in elements if el.clickable and el.enabled and el.visible]
        cta_hits = [
            el
            for el in clickables
            if BLOCKING_CTA.match((el.text or el.content_description or "").strip())
        ]
        if not cta_hits:
            return False
        # Sparse screen dominated by Agree/Continue with legal-ish words nearby.
        legalish = bool(
            re.search(r"terms|privacy|policy|consent|agree|accept|continue", corpus, re.I)
        )
        return legalish and len(labels) <= 25
