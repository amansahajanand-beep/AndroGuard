from types import SimpleNamespace

from app.modules.exploration.explorer import ExplorationEngine


def engine(states: int, actions: int, last_new: int):
    eng = ExplorationEngine.__new__(ExplorationEngine)
    eng.hitl_manager = None
    eng.detector = SimpleNamespace(states=[object()] * states)
    eng.limits = SimpleNamespace(max_unique_states=50, max_actions=400, max_time_seconds=600)
    eng._hitl_paused_seconds = 0.0
    eng._last_new_state_action = last_new
    session = SimpleNamespace(actions_performed=actions, hit_state_limit=False, hit_action_limit=False, hit_timeout=False)
    return eng, session


def test_stops_after_a_long_run_with_no_new_screens() -> None:
    import time

    eng, session = engine(states=6, actions=60, last_new=20)
    assert eng._stop_reason(session, time.perf_counter()) == "exploration_exhausted"


def test_keeps_going_while_screens_are_still_being_found() -> None:
    import time

    eng, session = engine(states=6, actions=60, last_new=45)
    assert eng._stop_reason(session, time.perf_counter()) is None


def test_does_not_stop_early_with_almost_no_screens() -> None:
    import time

    eng, session = engine(states=2, actions=60, last_new=0)
    assert eng._stop_reason(session, time.perf_counter()) is None
