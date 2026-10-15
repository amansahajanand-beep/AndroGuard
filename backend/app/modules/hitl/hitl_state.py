"""Snapshot of exploration progress taken when HITL pauses the agent."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ExplorationCheckpoint:
    """Frozen explorer position so Continue resumes the same in-memory run.

    The worker thread stays alive and holds the emulator lock; this checkpoint is
    also exposed on the job record for the frontend / debugging.
    """

    job_id: str
    intervention_id: str
    current_state_id: str | None = None
    parent_state_id: str | None = None
    current_activity: str | None = None
    current_package: str | None = None
    depth: int = 0
    actions_performed: int = 0
    screenshots_captured: int = 0
    unique_states: int = 0
    visited_states: list[str] = field(default_factory=list)
    visited_actions: dict[str, list[str]] = field(default_factory=dict)
    navigation_graph: dict[str, Any] = field(default_factory=dict)
    activity_trail: list[str] = field(default_factory=list)
    blocked_fingerprint: str | None = None
    blocked_visible_text: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExplorationCheckpoint":
        created = data.get("created_at")
        if isinstance(created, str):
            try:
                created_at = datetime.fromisoformat(created)
            except ValueError:
                created_at = _now()
        elif isinstance(created, datetime):
            created_at = created
        else:
            created_at = _now()
        return cls(
            job_id=str(data.get("job_id") or ""),
            intervention_id=str(data.get("intervention_id") or ""),
            current_state_id=data.get("current_state_id"),
            parent_state_id=data.get("parent_state_id"),
            current_activity=data.get("current_activity"),
            current_package=data.get("current_package"),
            depth=int(data.get("depth") or 0),
            actions_performed=int(data.get("actions_performed") or 0),
            screenshots_captured=int(data.get("screenshots_captured") or 0),
            unique_states=int(data.get("unique_states") or 0),
            visited_states=list(data.get("visited_states") or []),
            visited_actions={
                str(k): list(v) for k, v in (data.get("visited_actions") or {}).items()
            },
            navigation_graph=dict(data.get("navigation_graph") or {}),
            activity_trail=list(data.get("activity_trail") or []),
            blocked_fingerprint=data.get("blocked_fingerprint"),
            blocked_visible_text=list(data.get("blocked_visible_text") or []),
            created_at=created_at,
        )
