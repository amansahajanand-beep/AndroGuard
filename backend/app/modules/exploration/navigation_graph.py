"""In-memory navigation graph for deterministic UI exploration.

Tracks:

* ``visited_states`` — unique visual states retained so far
* ``visited_actions`` — action keys already tried from each state
* ``navigation_graph`` — directed edges (from → to via action)
* ``current_state`` / ``parent_state`` — where the explorer is now

Example tree shape (labels only)::

    Home
     ├── Settings
     ├── Profile
     └── Games
           ├── Game 1
           └── Game 2
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.modules.exploration.state_detector import ScreenStateRecord


@dataclass
class NavEdge:
    """One performed transition between visual states."""

    from_state_id: str
    to_state_id: str
    action_kind: str
    action_key: str
    succeeded: bool = True
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_state_id": self.from_state_id,
            "to_state_id": self.to_state_id,
            "action_kind": self.action_kind,
            "action_key": self.action_key,
            "succeeded": self.succeeded,
            "meta": dict(self.meta),
        }


@dataclass
class PageBudget:
    """Per-page unique-child accounting (TARGET / MAX states per page)."""

    unique_child_states: set[str] = field(default_factory=set)
    actions_tried: int = 0


class NavigationGraph:
    """Directed graph of discovered UI states plus DFS backtrack helpers."""

    def __init__(self) -> None:
        self.visited_states: dict[str, ScreenStateRecord] = {}
        # state_id -> set of action keys already executed from that state
        self.visited_actions: dict[str, set[str]] = {}
        self.edges: list[NavEdge] = []
        self.parent_of: dict[str, str | None] = {}
        self.children_of: dict[str, list[str]] = {}
        self.current_state_id: str | None = None
        self.page_budgets: dict[str, PageBudget] = {}
        self.labels: dict[str, str] = {}

    @property
    def current_state(self) -> ScreenStateRecord | None:
        if not self.current_state_id:
            return None
        return self.visited_states.get(self.current_state_id)

    @property
    def parent_state_id(self) -> str | None:
        if not self.current_state_id:
            return None
        return self.parent_of.get(self.current_state_id)

    @property
    def parent_state(self) -> ScreenStateRecord | None:
        parent_id = self.parent_state_id
        if not parent_id:
            return None
        return self.visited_states.get(parent_id)

    def add_state(
        self,
        record: ScreenStateRecord,
        *,
        parent_id: str | None = None,
        label: str | None = None,
    ) -> None:
        sid = record.state_id
        is_new = sid not in self.visited_states
        self.visited_states[sid] = record
        self.visited_actions.setdefault(sid, set())
        self.page_budgets.setdefault(sid, PageBudget())
        self.labels[sid] = label or record.label or record.activity or sid
        if is_new:
            self.parent_of.setdefault(sid, parent_id)
            if parent_id:
                self.children_of.setdefault(parent_id, [])
                if sid not in self.children_of[parent_id]:
                    self.children_of[parent_id].append(sid)
                self.page_budgets.setdefault(parent_id, PageBudget()).unique_child_states.add(sid)
        self.current_state_id = sid

    def mark_action(self, state_id: str, action_key: str) -> None:
        self.visited_actions.setdefault(state_id, set()).add(action_key)
        self.page_budgets.setdefault(state_id, PageBudget()).actions_tried += 1

    def action_seen(self, state_id: str, action_key: str) -> bool:
        return action_key in self.visited_actions.get(state_id, set())

    def connect(
        self,
        *,
        from_state_id: str,
        to_state_id: str,
        action_kind: str,
        action_key: str,
        succeeded: bool = True,
        meta: dict[str, Any] | None = None,
    ) -> NavEdge:
        edge = NavEdge(
            from_state_id=from_state_id,
            to_state_id=to_state_id,
            action_kind=action_kind,
            action_key=action_key,
            succeeded=succeeded,
            meta=meta or {},
        )
        self.edges.append(edge)
        return edge

    def unique_child_count(self, state_id: str) -> int:
        return len(self.page_budgets.get(state_id, PageBudget()).unique_child_states)

    def set_current(self, state_id: str) -> None:
        if state_id not in self.visited_states:
            raise KeyError(f"Unknown state {state_id}")
        self.current_state_id = state_id

    def backtrack_parent(self) -> str | None:
        """Move current pointer to the parent state (does not press Back itself)."""
        parent = self.parent_state_id
        if parent:
            self.current_state_id = parent
        return parent

    def depth_of(self, state_id: str | None = None) -> int:
        sid = state_id if state_id is not None else self.current_state_id
        depth = 0
        seen: set[str] = set()
        while sid and sid not in seen:
            seen.add(sid)
            parent = self.parent_of.get(sid)
            if not parent:
                break
            depth += 1
            sid = parent
        return depth

    def max_depth(self) -> int:
        if not self.visited_states:
            return 0
        return max(self.depth_of(sid) for sid in self.visited_states)

    def tree(self) -> dict[str, Any]:
        """Nested dict suitable for JSON / ASCII rendering."""
        roots = [sid for sid, parent in self.parent_of.items() if parent is None]
        if not roots and self.visited_states:
            roots = [next(iter(self.visited_states))]

        def node(sid: str) -> dict[str, Any]:
            return {
                "state_id": sid,
                "label": self.labels.get(sid, sid),
                "activity": (
                    self.visited_states[sid].visual.activity
                    if sid in self.visited_states
                    else None
                ),
                "children": [node(child) for child in self.children_of.get(sid, [])],
            }

        return {"roots": [node(r) for r in roots], "edge_count": len(self.edges)}

    def ascii_tree(self) -> str:
        lines: list[str] = []

        def walk(sid: str, prefix: str, is_last: bool) -> None:
            connector = "└── " if is_last else "├── "
            label = self.labels.get(sid, sid)
            lines.append(f"{prefix}{connector}{label} ({sid})")
            children = self.children_of.get(sid, [])
            extension = "    " if is_last else "│   "
            for index, child in enumerate(children):
                walk(child, prefix + extension, index == len(children) - 1)

        roots = [sid for sid, parent in self.parent_of.items() if parent is None]
        if not roots and self.visited_states:
            roots = [next(iter(self.visited_states))]
        for index, root in enumerate(roots):
            label = self.labels.get(root, root)
            lines.append(f"{label} ({root})")
            children = self.children_of.get(root, [])
            for child_index, child in enumerate(children):
                walk(child, "", child_index == len(children) - 1)
        return "\n".join(lines) if lines else "(empty)"

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_state_id": self.current_state_id,
            "parent_state_id": self.parent_state_id,
            "visited_states": list(self.visited_states.keys()),
            "visited_actions": {k: sorted(v) for k, v in self.visited_actions.items()},
            "edges": [edge.to_dict() for edge in self.edges],
            "parent_of": dict(self.parent_of),
            "tree": self.tree(),
            "ascii_tree": self.ascii_tree(),
            "max_depth": self.max_depth(),
        }
