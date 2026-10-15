"""In-process store for HITL intervention records."""

from __future__ import annotations

import threading
from typing import Any

from app.modules.hitl.hitl_state import ExplorationCheckpoint
from app.modules.hitl.intervention_types import Intervention, InterventionStatus


class InterventionStore:
    """Thread-safe memory store keyed by intervention id and job id.

    Jobs already have their own store; this keeps live Intervention objects and
    checkpoints without inventing a second database abstraction.
    """

    def __init__(self) -> None:
        self._by_id: dict[str, Intervention] = {}
        self._by_job: dict[str, list[str]] = {}
        self._checkpoints: dict[str, ExplorationCheckpoint] = {}
        self._lock = threading.RLock()

    def save(self, intervention: Intervention) -> Intervention:
        with self._lock:
            self._by_id[intervention.intervention_id] = intervention
            bucket = self._by_job.setdefault(intervention.job_id, [])
            if intervention.intervention_id not in bucket:
                bucket.append(intervention.intervention_id)
            return intervention

    def get(self, intervention_id: str) -> Intervention | None:
        with self._lock:
            return self._by_id.get(intervention_id)

    def get_active_for_job(self, job_id: str) -> Intervention | None:
        with self._lock:
            for iid in reversed(self._by_job.get(job_id, [])):
                item = self._by_id.get(iid)
                if item and item.status is InterventionStatus.WAITING:
                    return item
            return None

    def list_for_job(self, job_id: str) -> list[Intervention]:
        with self._lock:
            return [
                self._by_id[iid]
                for iid in self._by_job.get(job_id, [])
                if iid in self._by_id
            ]

    def update(self, intervention_id: str, **changes: Any) -> Intervention | None:
        with self._lock:
            item = self._by_id.get(intervention_id)
            if item is None:
                return None
            for key, value in changes.items():
                if hasattr(item, key):
                    setattr(item, key, value)
            return item

    def save_checkpoint(self, checkpoint: ExplorationCheckpoint) -> None:
        with self._lock:
            self._checkpoints[checkpoint.intervention_id] = checkpoint

    def get_checkpoint(self, intervention_id: str) -> ExplorationCheckpoint | None:
        with self._lock:
            return self._checkpoints.get(intervention_id)

    def clear_job(self, job_id: str) -> None:
        with self._lock:
            ids = self._by_job.pop(job_id, [])
            for iid in ids:
                self._by_id.pop(iid, None)
                self._checkpoints.pop(iid, None)


_STORE = InterventionStore()


def get_intervention_store() -> InterventionStore:
    return _STORE
