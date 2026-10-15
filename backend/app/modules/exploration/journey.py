"""Domain-agnostic journey executor — enforce the per-upload nav map like a human.

Works for ANY APK: filters allow-listed candidates by active goal *kind*
(onboarding / create / home / sidebar / destination / settings / ad_trigger),
never by hardcoded product domains (alarm/shop/game/…).

Section labels come from THIS app's live drawer/bottom-nav and activity tokens.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

from app.modules.exploration.action_planner import PlannedAction, back_action
from app.modules.exploration.prior_knowledge import ExplorationPrior
from app.modules.exploration.ui_element import UIElement

ScreenRole = Literal[
    "dialog",
    "form",
    "drawer_open",
    "settings",
    "onboarding",
    "home",
    "unknown",
]

_SECTION_NOISE = {
    "add",
    "create",
    "new",
    "save",
    "done",
    "ok",
    "cancel",
    "delete",
    "edit",
    "more",
    "options",
    "search",
    "close",
    "back",
    "ad",
    "ads",
    "click",
    "install",
    "test",
}
_SECTION_SLUG_RX = re.compile(r"[^\w]+", re.UNICODE)


def _slug(text: str) -> str:
    """Stable id slug; keeps letters/digits from any language (not ASCII-only)."""
    raw = (text or "").strip().lower()
    parts: list[str] = []
    for ch in raw:
        if ch.isalnum():
            parts.append(ch)
        elif parts and parts[-1] != "_":
            parts.append("_")
    s = "".join(parts).strip("_")
    return s[:32] or "section"

# Journey kinds that count toward "visit every page" coverage.
_COVERAGE_KINDS = frozenset(
    {
        "onboarding",
        "create",
        "home",
        "sidebar",
        "destination",
        "feature",
        "settings",
    }
)


@dataclass
class JourneyState:
    """Mutable progress for the current exploration session."""

    step_attempts: dict[str, int] = field(default_factory=dict)
    max_attempts_per_step: int = 8
    drawer_opened: bool = False
    sections_expanded: bool = False
    min_section_visits: int = 2
    section_visits: int = 0


def classify_screen(
    elements: Sequence[UIElement],
    *,
    activity: str | None = None,
    screen_size: tuple[int, int] | None = None,
) -> ScreenRole:
    """Coarse screen role from hierarchy (domain-agnostic)."""
    act = (activity or "").lower()
    texts = [
        (el.text or el.content_description or "").strip().lower()
        for el in elements
        if (el.text or el.content_description)
    ]
    blob = " ".join(texts[:40])
    rids = " ".join((el.resource_id or "").lower() for el in elements[:60])

    if any(
        t in {"cancel", "delete", "ok", "allow", "deny", "while using the app"}
        for t in texts
    ) and sum(1 for el in elements if el.clickable) <= 8:
        if any(t in {"cancel", "delete", "discard", "remove"} for t in texts):
            return "dialog"
        if any("permission" in (el.package or "").lower() for el in elements):
            return "dialog"

    if "drawer" in rids or "nav_view" in rids or "navigationview" in rids:
        # Bottom-nav ids like nav_home must not count as an open drawer.
        if not any(
            token in rids
            for token in ("bottomnav", "bottom_nav", "tab_layout", "tablayout")
        ):
            return "drawer_open"
    if screen_size:
        width = screen_size[0] or 0
        height = screen_size[1] or 0
        # Ignore bottom chrome — Home/Clock/Timer tabs look "left-labeled" otherwise.
        left_labeled = [
            el
            for el in elements
            if el.clickable
            and el.visible
            and (el.text or "").strip()
            and el.right <= width * 0.55
            and el.left <= width * 0.35
            and (height <= 0 or el.bottom < height * 0.82)
        ]
        if len(left_labeled) >= 3 and width > 0:
            return "drawer_open"

    if any(token in act for token in ("setting", "preference", "option")):
        return "settings"
    if "setting" in blob or "preference" in blob:
        if any("setting" in t for t in texts[:12]):
            return "settings"

    edit_count = sum(
        1
        for el in elements
        if "edittext" in (el.class_name or "").lower()
        or "textinput" in (el.class_name or "").lower()
    )
    if edit_count >= 1:
        return "form"

    if any(
        token in act or token in blob
        for token in ("onboard", "welcome", "intro", "consent", "gdpr")
    ):
        return "onboarding"

    if "home" in blob or "main" in act or "launcher" in act:
        return "home"
    return "unknown"


def _meta_flag(item: PlannedAction, key: str) -> bool:
    return bool((item.meta or {}).get(key))


def _label_blob(item: PlannedAction) -> str:
    meta = item.meta or {}
    return " ".join(
        str(x)
        for x in (
            item.label,
            meta.get("text"),
            meta.get("content_description"),
            meta.get("resource_id"),
        )
        if x
    ).lower()


def _always_keep(item: PlannedAction) -> bool:
    if item.kind in {"wait", "back", "relaunch", "open_menu"}:
        return True
    # Swipes must survive journey filters — otherwise we stay on one screen forever
    # while higher-priority taps keep winning.
    if item.kind in {"swipe_up", "swipe_down", "swipe_left", "swipe_right", "swipe"}:
        return True
    if _meta_flag(item, "is_close"):
        return True
    if _meta_flag(item, "is_cancel_dialog"):
        return True
    if item.kind == "tap" and "permission" in _label_blob(item):
        return True
    pkg = str((item.meta or {}).get("package") or "").lower()
    if "permissioncontroller" in pkg:
        return True
    return False


def maybe_skip_stale_onboarding(
    prior: ExplorationPrior,
    *,
    elements: Sequence[UIElement],
    role: ScreenRole,
    activity: str | None = None,
) -> str | None:
    """Skip onboarding when the UI is clearly past gates (home / main chrome)."""
    active = prior.active_goal() if prior else None
    if not active or str(active.get("kind") or "") != "onboarding":
        return None
    if role not in {"home", "drawer_open", "settings", "form", "unknown"}:
        return None
    act = (activity or "").lower()
    if any(token in act for token in ("onboard", "welcome", "intro", "consent", "gdpr")):
        return None
    # Still on a real gate CTA → do not skip.
    from app.modules.exploration.action_planner import _is_onboarding_cta

    if any(_is_onboarding_cta(el) for el in elements):
        return None
    # Main launcher / bottom-nav / FAB chrome ⇒ past onboarding.
    rids = " ".join((el.resource_id or "").lower() for el in elements[:80])
    looks_main = any(
        token in rids
        for token in (
            "fab",
            "bottomnav",
            "bottom_nav",
            "nav_home",
            "nav_settings",
            "addalarm",
            "drawer",
        )
    ) or role in {"home", "drawer_open", "settings"}
    if not looks_main and role == "unknown":
        return None
    gid = str(active.get("id") or "")
    if not gid:
        return None
    prior.skip_goal(gid, reason="past_onboarding_ui")
    return gid


def _matches_labels(item: PlannedAction, labels: Sequence[str]) -> bool:
    hay = _label_blob(item)
    if not hay:
        return False
    for label in labels:
        token = (label or "").strip().lower()
        if len(token) >= 2 and token in hay:
            return True
    return False


def _is_drawer_row_candidate(
    item: PlannedAction, *, screen_size: tuple[int, int] | None
) -> bool:
    if item.kind != "tap":
        return False
    if _meta_flag(item, "is_overflow") or _meta_flag(item, "is_destructive_confirm"):
        return False
    if _meta_flag(item, "is_ad_cta") or _meta_flag(item, "is_banner_ad"):
        return False
    meta = item.meta or {}
    bounds = meta.get("bounds") or []
    text = (meta.get("text") or item.label or "").strip()
    if not text or len(text) > 40:
        return False
    if screen_size and len(bounds) == 4:
        width = screen_size[0] or 0
        if width > 0 and int(bounds[2]) > width * 0.62:
            # Full-width rows OK in open drawer panels; keep if left-anchored.
            if int(bounds[0]) > width * 0.4:
                return False
    return True


def filter_candidates_for_step(
    candidates: Sequence[PlannedAction],
    *,
    prior: ExplorationPrior,
    elements: Sequence[UIElement],
    screen_size: tuple[int, int] | None = None,
    activity: str | None = None,
    journey: JourneyState | None = None,
) -> list[PlannedAction]:
    """Keep allow-listed actions that advance the active nav-map step."""
    active = prior.active_goal() if prior else None
    if not active:
        return list(candidates)

    kind = str(active.get("kind") or "destination")
    labels = [str(x) for x in (active.get("ui_labels") or []) if x]
    role = classify_screen(elements, activity=activity, screen_size=screen_size)
    if journey is not None and role == "drawer_open":
        journey.drawer_opened = True

    kept: list[PlannedAction] = []
    # Labels for sections not yet visited — always allow these taps (full crawl).
    uncovered_labels: list[str] = []
    for goal in uncovered_coverage_goals(prior):
        if str(goal.get("kind") or "") not in {"destination", "feature", "settings", "home"}:
            continue
        for lab in goal.get("ui_labels") or []:
            token = str(lab or "").strip().lower()
            if len(token) >= 2:
                uncovered_labels.append(token)

    for item in candidates:
        if _always_keep(item):
            # open_menu only helpful for sidebar (or recovery).
            if item.kind == "open_menu" and kind not in {"sidebar", "home", "settings"}:
                if kind == "create" and role not in {"form", "dialog"}:
                    continue
            kept.append(item)
            continue

        if _meta_flag(item, "is_overflow") or _meta_flag(item, "is_destructive_confirm"):
            continue
        if _meta_flag(item, "is_ad_cta"):
            continue

        # Prefer visiting remaining checklist pages even if active step differs.
        if uncovered_labels and item.kind == "tap" and _matches_labels(item, uncovered_labels):
            kept.append(item)
            continue

        if kind == "onboarding":
            if _meta_flag(item, "is_onboarding_cta") or item.kind == "type_text":
                kept.append(item)
            elif _matches_labels(
                item, ["continue", "next", "agree", "allow", "skip", "get started"]
            ):
                kept.append(item)
        elif kind == "create":
            if role == "form" or role == "dialog":
                if (
                    item.kind == "type_text"
                    or _meta_flag(item, "is_primary_submit")
                    or _meta_flag(item, "is_cancel_dialog")
                    or _matches_labels(item, ["save", "done", "create", "ok", "add"])
                ):
                    kept.append(item)
            elif (
                _meta_flag(item, "is_create_explore")
                or _matches_labels(item, labels or ["add", "create", "new", "fab"])
                or item.kind == "type_text"
                or _meta_flag(item, "is_primary_submit")
            ):
                kept.append(item)
        elif kind == "home":
            if _matches_labels(item, labels or ["home", "main"]) or (
                "home" in _label_blob(item)
            ):
                kept.append(item)
            elif item.kind == "back":
                kept.append(item)
        elif kind == "sidebar":
            if journey and journey.drawer_opened or role == "drawer_open":
                if _is_drawer_row_candidate(item, screen_size=screen_size):
                    kept.append(item)
                elif _matches_labels(item, labels):
                    kept.append(item)
            elif _meta_flag(item, "is_drawer") or item.kind == "open_menu":
                kept.append(item)
        elif kind in {"destination", "feature"}:
            if _matches_labels(item, labels) or (
                labels and any(lab.lower() in _label_blob(item) for lab in labels if len(lab) >= 3)
            ):
                kept.append(item)
            # Bottom-nav / labeled section taps matching goal title tokens.
            title = str(active.get("title") or "")
            title_tokens = [t for t in re.split(r"\W+", title.lower()) if len(t) >= 3]
            if title_tokens and _matches_labels(item, title_tokens):
                kept.append(item)
        elif kind == "settings":
            if _matches_labels(item, labels or ["settings", "preference", "options"]):
                kept.append(item)
            elif "setting" in _label_blob(item) or "preference" in _label_blob(item):
                kept.append(item)
        elif kind == "ad_trigger":
            if _meta_flag(item, "ad_trigger") or _matches_labels(
                item, labels or ["watch", "reward", "video", "earn"]
            ):
                kept.append(item)
        else:
            kept.append(item)

    # De-dupe preserving order.
    seen: set[str] = set()
    ordered: list[PlannedAction] = []
    for item in kept:
        if item.key in seen:
            continue
        seen.add(item.key)
        ordered.append(item)

    # If filter emptied the list, fall back to non-overflow candidates.
    if not ordered:
        ordered = [
            c
            for c in candidates
            if not _meta_flag(c, "is_overflow")
            and not _meta_flag(c, "is_destructive_confirm")
            and not _meta_flag(c, "is_ad_cta")
        ] or list(candidates)
    return ordered


def note_step_attempt(prior: ExplorationPrior, journey: JourneyState) -> str | None:
    """If active goal already exceeded budget, skip it. Does not increment."""
    active = prior.active_goal()
    if not active:
        return None
    gid = str(active.get("id") or "")
    if not gid:
        return None
    if journey.step_attempts.get(gid, 0) < journey.max_attempts_per_step:
        return None
    prior.skip_goal(gid, reason="step_budget_exhausted")
    return gid


def record_step_action(prior: ExplorationPrior, journey: JourneyState) -> None:
    """Count one executed action against the active journey step."""
    active = prior.active_goal()
    if not active:
        return
    gid = str(active.get("id") or "")
    if not gid:
        return
    journey.step_attempts[gid] = journey.step_attempts.get(gid, 0) + 1
    kind = str(active.get("kind") or "")
    if kind in {"destination", "feature"} and gid.startswith("section_"):
        journey.section_visits += 1


def recover_action_for_stuck_step(
    *,
    role: ScreenRole,
    candidates: Sequence[PlannedAction],
) -> PlannedAction | None:
    """Prefer Cancel when a step is stuck on a dialog.

    Do NOT unconditionally press Back — from the app root that exits to the
    system Home launcher and triggers a relaunch loop.
    """
    for item in candidates:
        if _meta_flag(item, "is_cancel_dialog"):
            return item
    if role == "dialog":
        for item in candidates:
            label = (item.label or "").lower()
            if item.kind == "back" or label == "cancel":
                return item
        return back_action()
    # Non-dialog stuck step: let the planner pick another candidate (menu, etc.).
    return None


def discover_section_labels(
    elements: Sequence[UIElement],
    *,
    screen_size: tuple[int, int] | None = None,
) -> list[str]:
    """Collect unique section names from bottom nav / drawer rows (this app only)."""
    width = (screen_size[0] if screen_size else 0) or 0
    height = (screen_size[1] if screen_size else 0) or 0
    found: list[str] = []
    seen: set[str] = set()

    for el in elements:
        if not el.clickable or not el.visible or not el.enabled:
            continue
        text = (el.text or el.content_description or "").strip()
        if not text or len(text) > 28:
            continue
        key = text.lower()
        if key in _SECTION_NOISE or key in seen:
            continue
        if key in {"home", "settings", "setting"}:
            # Home/settings already have dedicated goals.
            continue
        rid = (el.resource_id or "").lower()
        cls = (el.class_name or "").lower()
        near_bottom = height > 0 and el.top >= height * 0.78
        bottom_nav = near_bottom or "bottom" in rid or "tab" in rid or "navigation" in rid
        left_drawer = width > 0 and el.left <= width * 0.45 and el.right <= width * 0.7
        if bottom_nav or left_drawer or "nav" in rid or "menu" in cls:
            seen.add(key)
            found.append(text)
        if len(found) >= 12:
            break
    return found


def expand_section_goals(
    prior: ExplorationPrior,
    elements: Sequence[UIElement],
    *,
    screen_size: tuple[int, int] | None = None,
    journey: JourneyState | None = None,
    incremental: bool = False,
) -> list[str]:
    """Append destination goals for live sections; return newly added goal ids.

    When ``incremental`` is True (full-coverage mode), keep discovering new
    bottom-nav / drawer labels across the run instead of locking after first hit.
    """
    if journey and journey.sections_expanded and not incremental:
        return []
    labels = discover_section_labels(elements, screen_size=screen_size)
    if not labels:
        return []

    existing = {str(g.get("id")) for g in prior.goals if g.get("id")}
    # Insert after sidebar in nav_path order.
    max_order = 0
    for step in prior.nav_path:
        max_order = max(max_order, int(step.get("order") or 0))
    sidebar_order = next(
        (
            int(s.get("order") or 0)
            for s in prior.nav_path
            if s.get("goal_id") == "sidebar_menu"
        ),
        None,
    )
    insert_at = (sidebar_order + 1) if sidebar_order is not None else max_order + 1

    added: list[str] = []
    new_steps: list[dict[str, Any]] = []
    for label in labels:
        gid = f"section_{_slug(label)}"
        if gid in existing:
            continue
        goal = {
            "id": gid,
            "kind": "destination",
            "title": f"Visit section: {label}",
            "activity_hints": [],
            "ui_labels": [label.lower(), label],
            "expected_ad_types": [],
            "priority": 60,
            "step_order": 45,
            "why": f"Live UI section '{label}' discovered on this app",
            "covered": False,
        }
        prior.goals.append(goal)
        existing.add(gid)
        added.append(gid)
        new_steps.append(
            {
                "goal_id": gid,
                "order": insert_at + len(new_steps),
                "summary": f"Open {label}",
            }
        )

    if new_steps:
        # Shift later nav_path orders and splice section steps after sidebar.
        shifted: list[dict[str, Any]] = []
        for step in sorted(prior.nav_path, key=lambda s: int(s.get("order") or 0)):
            order = int(step.get("order") or 0)
            if order >= insert_at:
                step = dict(step)
                step["order"] = order + len(new_steps)
            shifted.append(step)
        prior.nav_path = sorted(
            shifted + new_steps, key=lambda s: int(s.get("order") or 0)
        )
        # Refresh blueprint snapshot if present.
        if prior.blueprint is not None:
            prior.blueprint = dict(prior.blueprint)
            prior.blueprint["goals"] = list(prior.goals)
            prior.blueprint["nav_path"] = list(prior.nav_path)

    if journey is not None and added and not incremental:
        journey.sections_expanded = True
    elif journey is not None and added and incremental:
        # Mark that we have seen chrome at least once; still allow more labels later.
        journey.sections_expanded = False
    return added


def uncovered_coverage_goals(prior: ExplorationPrior) -> list[dict[str, Any]]:
    """Nav-map goals still needed for full app-page coverage (excludes ad_trigger)."""
    covered = set(prior.covered_goal_evidence or {})
    out: list[dict[str, Any]] = []
    for goal in prior.goals or []:
        gid = str(goal.get("id") or "")
        kind = str(goal.get("kind") or "")
        if not gid or gid in covered:
            continue
        if kind not in _COVERAGE_KINDS:
            continue
        out.append(goal)
    return out


def has_coverage_checklist(prior: ExplorationPrior) -> bool:
    """True when the prior defines at least one page-coverage goal."""
    for goal in prior.goals or []:
        if str(goal.get("kind") or "") in _COVERAGE_KINDS and goal.get("id"):
            return True
    return False


def is_coverage_complete(prior: ExplorationPrior) -> bool:
    """True when a checklist exists and every coverage goal is covered/skipped."""
    if not has_coverage_checklist(prior):
        return False
    return not uncovered_coverage_goals(prior)


def prefer_coverage_actions(
    candidates: Sequence[PlannedAction],
    *,
    prior: ExplorationPrior,
) -> list[PlannedAction]:
    """Put taps that advance uncovered section/home/settings goals first."""
    uncovered = uncovered_coverage_goals(prior)
    if not uncovered or not candidates:
        return list(candidates)

    labels: list[str] = []
    for goal in uncovered:
        for lab in goal.get("ui_labels") or []:
            token = str(lab or "").strip().lower()
            if len(token) >= 2:
                labels.append(token)
        title = str(goal.get("title") or "")
        for token in re.split(r"\W+", title.lower()):
            if len(token) >= 3 and token not in {"visit", "section", "open"}:
                labels.append(token)
    if not labels:
        return list(candidates)

    matching: list[PlannedAction] = []
    rest: list[PlannedAction] = []
    for item in candidates:
        if item.kind in {"swipe_up", "swipe_down", "swipe", "open_menu", "back", "wait"}:
            rest.append(item)
            continue
        if _matches_labels(item, labels):
            matching.append(item)
        else:
            rest.append(item)
    return matching + rest
