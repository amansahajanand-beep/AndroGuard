from app.core.config import settings
from app.modules.exploration.action_planner import PlannedAction, apply_swipe_budget


def planned(kind: str, key: str) -> PlannedAction:
    return PlannedAction(key=key, action=None, kind=kind, priority=80, label=key)


MIXED = [planned("swipe_left", "s1"), planned("tap", "albums"), planned("swipe_right", "s2"), planned("tap", "stories")]


def test_swipes_remain_while_budget_is_unspent() -> None:
    assert len(apply_swipe_budget(MIXED, swipes_done=1, budget=2)) == 4


def test_swipes_are_dropped_once_the_budget_is_spent() -> None:
    kept = apply_swipe_budget(MIXED, swipes_done=2, budget=2)
    assert [c.key for c in kept] == ["albums", "stories"]


def test_swipes_are_kept_when_nothing_else_is_left() -> None:
    only_swipes = [planned("swipe_left", "s1"), planned("swipe_up", "s2")]
    assert apply_swipe_budget(only_swipes, swipes_done=5, budget=2) == only_swipes


def test_zero_budget_disables_the_limit() -> None:
    assert len(apply_swipe_budget(MIXED, swipes_done=99, budget=0)) == 4


def test_default_budget_is_small() -> None:
    assert settings.exploration_max_swipes_per_state == 2
