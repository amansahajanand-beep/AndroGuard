"""Phase 12J — Spatial analyzer / gesture planner / coverage tests."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.modules.exploration.action_planner import PlannedAction, plan_actions
from app.modules.exploration.actions import SwipeAction
from app.modules.exploration.executor import ALLOWED_ACTION_KINDS, ActionExecutor
from app.modules.exploration.observation import Observation
from app.modules.exploration.prior_knowledge import ExplorationPrior
from app.modules.exploration.spatial.gesture_planner import (
    gesture_points_for_region,
    plan_gesture_actions,
)
from app.modules.exploration.spatial.gesture_verifier import (
    GestureVerifyOutcome,
    verify_gesture,
)
from app.modules.exploration.spatial.memory import RegionExplorationMemory
from app.modules.exploration.spatial.models import (
    ExplorationRegion,
    RegionType,
    ScrollOrientation,
)
from app.modules.exploration.spatial.spatial_analyzer import analyze_regions
from app.modules.exploration.ui_element import UIElement
from app.modules.exploration.verifier import VerifyOutcome, VerifyResult


def _el(**kwargs) -> UIElement:
    defaults = dict(
        text="",
        resource_id="",
        content_description="",
        class_name="android.widget.FrameLayout",
        package="com.example.app",
        bounds=(0, 0, 100, 100),
        clickable=False,
        enabled=True,
        scrollable=False,
        visible=True,
        focusable=False,
    )
    defaults.update(kwargs)
    return UIElement(**defaults)


def test_vertical_scroll_detection() -> None:
    elements = [
        _el(
            class_name="androidx.recyclerview.widget.RecyclerView",
            resource_id="com.example:id/feed",
            scrollable=True,
            bounds=(0, 200, 1080, 2000),
        )
    ]
    regions = analyze_regions(elements, screen_size=(1080, 2400))
    assert regions
    assert any(r.orientation == ScrollOrientation.VERTICAL for r in regions)
    planned = plan_gesture_actions(regions, screen_size=(1080, 2400))
    kinds = {p.kind for p in planned}
    assert "swipe_up" in kinds
    assert "swipe_down" in kinds


def test_horizontal_scrollview_detection() -> None:
    elements = [
        _el(
            class_name="android.widget.HorizontalScrollView",
            resource_id="com.example:id/carousel",
            scrollable=True,
            bounds=(40, 400, 1040, 900),
        )
    ]
    regions = analyze_regions(elements, screen_size=(1080, 2400))
    assert any(r.orientation == ScrollOrientation.HORIZONTAL for r in regions)
    planned = plan_gesture_actions(regions, screen_size=(1080, 2400))
    kinds = {p.kind for p in planned}
    assert "swipe_left" in kinds
    assert "swipe_right" in kinds
    assert "swipe_up" not in kinds


def test_inferred_horizontal_carousel_from_repeated_children() -> None:
    screen = (1080, 2400)
    cards = [
        _el(
            text=f"Card {i}",
            clickable=True,
            bounds=(40 + i * 280, 500, 40 + i * 280 + 250, 900),
        )
        for i in range(4)
    ]
    # Last card clipped at right edge.
    cards[-1] = _el(
        text="Card 3",
        clickable=True,
        bounds=(40 + 3 * 280, 500, 1080, 900),
    )
    regions = analyze_regions(cards, screen_size=screen)
    assert any(
        r.region_type == RegionType.HORIZONTAL_CAROUSEL
        or r.partially_visible_content
        for r in regions
    )
    planned = plan_gesture_actions(regions, screen_size=screen)
    assert any(p.kind == "swipe_left" for p in planned)


def test_multiple_regions_vertical_and_horizontal() -> None:
    elements = [
        _el(
            class_name="android.widget.HorizontalScrollView",
            resource_id="id/featured",
            scrollable=True,
            bounds=(0, 300, 1080, 700),
        ),
        _el(
            class_name="android.widget.HorizontalScrollView",
            resource_id="id/recommended",
            scrollable=True,
            bounds=(0, 750, 1080, 1100),
        ),
        _el(
            class_name="androidx.recyclerview.widget.RecyclerView",
            resource_id="id/feed",
            scrollable=True,
            bounds=(0, 1150, 1080, 2200),
        ),
    ]
    regions = analyze_regions(elements, screen_size=(1080, 2400))
    assert len(regions) >= 3
    planned = plan_gesture_actions(regions, screen_size=(1080, 2400))
    region_ids = {p.meta.get("region_id") for p in planned}
    assert len(region_ids) >= 2
    assert any(p.kind.startswith("swipe_left") for p in planned)
    assert any(p.kind == "swipe_up" for p in planned)


def test_region_specific_coordinates_stay_inside() -> None:
    region = ExplorationRegion(
        region_id="region_h",
        region_type=RegionType.HORIZONTAL_CAROUSEL,
        bounds=(50, 900, 1030, 1300),
        orientation=ScrollOrientation.HORIZONTAL,
        supports_left=True,
        supports_right=True,
        confidence=0.9,
    )
    start, end = gesture_points_for_region(region, "left", screen_size=(1080, 2400))
    for x, y in (start, end):
        assert 50 <= x <= 1030
        assert 900 <= y <= 1300
    assert start[0] > end[0]  # left swipe moves leftward
    assert abs(start[1] - end[1]) < 5

    vreg = ExplorationRegion(
        region_id="region_v",
        region_type=RegionType.VERTICAL_SCROLL,
        bounds=(0, 400, 1080, 2000),
        orientation=ScrollOrientation.VERTICAL,
        supports_up=True,
        supports_down=True,
        confidence=0.9,
    )
    start, end = gesture_points_for_region(vreg, "up", screen_size=(1080, 2400))
    for x, y in (start, end):
        assert 0 <= x <= 1080
        assert 400 <= y <= 2000
    assert start[1] > end[1]


def test_screen_size_independence() -> None:
    for screen in ((1080, 2400), (720, 1600)):
        region = ExplorationRegion(
            region_id="r1",
            region_type=RegionType.HORIZONTAL_SCROLL,
            bounds=(20, int(screen[1] * 0.3), screen[0] - 20, int(screen[1] * 0.5)),
            orientation=ScrollOrientation.HORIZONTAL,
            supports_left=True,
            supports_right=True,
        )
        start, end = gesture_points_for_region(region, "right", screen_size=screen)
        assert 0 < start[0] < screen[0]
        assert 0 < end[0] < screen[0]
        assert region.top <= start[1] <= region.bottom


def test_partially_visible_boosts_carousel() -> None:
    screen = (1080, 2400)
    cards = [
        _el(text="A", clickable=True, bounds=(10, 600, 300, 1000)),
        _el(text="B", clickable=True, bounds=(320, 600, 610, 1000)),
        _el(text="C", clickable=True, bounds=(630, 600, 920, 1000)),
        _el(text="D", clickable=True, bounds=(940, 600, 1080, 1000)),  # clipped
    ]
    regions = analyze_regions(cards, screen_size=screen)
    carousels = [r for r in regions if r.region_type == RegionType.HORIZONTAL_CAROUSEL]
    assert carousels
    assert any(r.partially_visible_content for r in carousels)


def test_nested_scroll_marks_child() -> None:
    elements = [
        _el(
            class_name="android.widget.ScrollView",
            scrollable=True,
            bounds=(0, 0, 1080, 2400),
            resource_id="id/root_scroll",
        ),
        _el(
            class_name="android.widget.HorizontalScrollView",
            scrollable=True,
            bounds=(40, 500, 1040, 900),
            resource_id="id/inner_carousel",
        ),
    ]
    regions = analyze_regions(elements, screen_size=(1080, 2400))
    nested = [r for r in regions if r.nested]
    assert nested
    assert any(r.orientation == ScrollOrientation.HORIZONTAL for r in nested)


def test_duplicate_gesture_prevention() -> None:
    region = ExplorationRegion(
        region_id="region_2",
        region_type=RegionType.HORIZONTAL_CAROUSEL,
        bounds=(0, 400, 1080, 800),
        orientation=ScrollOrientation.HORIZONTAL,
        supports_left=True,
        supports_right=True,
        confidence=0.9,
    )
    memory = RegionExplorationMemory()
    memory.merge_region(region)
    memory.record_gesture("region_2", "left", outcome="NO_CHANGE", no_change_limit=2)
    memory.record_gesture("region_2", "left", outcome="NO_CHANGE", no_change_limit=2)
    planned = plan_gesture_actions(
        [memory.regions["region_2"]],
        screen_size=(1080, 2400),
        memory=memory,
        no_change_limit=2,
    )
    lefts = [p for p in planned if p.kind == "swipe_left"]
    assert lefts == []


def test_boundary_after_repeated_no_change() -> None:
    before = Observation(state_id="s1", visible_text=["A", "B"], clickable_elements=[])
    after = Observation(state_id="s1", visible_text=["A", "B"], clickable_elements=[])
    result = verify_gesture(
        before=before,
        after=after,
        region_id="r1",
        direction="left",
        prior_no_change=1,
        no_change_limit=2,
    )
    assert result.outcome == GestureVerifyOutcome.BOUNDARY


def test_new_content_success() -> None:
    before = Observation(state_id="s1", visible_text=["A"], clickable_elements=[])
    after = Observation(
        state_id="s2",
        visible_text=["A", "Sponsored"],
        clickable_elements=[{"text": "Card 4", "bounds": [1, 2, 3, 4]}],
        detected_ads=[{"ad_type": "banner"}],
    )
    verify = VerifyResult(
        outcome=VerifyOutcome.STATE_CHANGED,
        before_state_id="s1",
        after_state_id="s2",
    )
    result = verify_gesture(
        before=before, after=after, verify=verify, region_id="r1", direction="left"
    )
    assert result.outcome == GestureVerifyOutcome.SUCCESS
    assert result.new_content is True


def test_ai_candidate_bound_swipe_left() -> None:
    from app.modules.ai_explorer.schema import ALLOWED_ACTIONS, AIActionDecision
    from app.modules.ai_explorer.validator import validate_and_map

    assert "swipe_left" in ALLOWED_ACTIONS
    candidates = [
        PlannedAction(
            key="swipe:left:region_1",
            action=SwipeAction(direction="left", start=(800, 600), end=(200, 600)),
            kind="swipe_left",
            priority=50,
            label="swipe left",
            meta={"region_id": "region_1"},
        )
    ]
    planned = validate_and_map(
        {
            "action": "swipe_left",
            "target": "swipe:left:region_1",
            "reason": "explore carousel",
        },
        candidates,
    )
    assert planned.kind == "swipe_left"
    import pytest

    with pytest.raises(Exception):
        AIActionDecision.model_validate(
            {"action": "adb_shell", "target": "x", "reason": "hack"}
        )


def test_executor_allows_directional_swipes() -> None:
    assert "swipe_left" in ALLOWED_ACTION_KINDS
    assert "swipe_up" in ALLOWED_ACTION_KINDS
    ui = MagicMock()
    ui.perform.return_value = MagicMock(ok=True, kind="swipe")
    ex = ActionExecutor(ui)
    planned = PlannedAction(
        key="swipe:left:r1",
        action=SwipeAction(direction="left", start=(900, 500), end=(200, 500)),
        kind="swipe_left",
        label="swipe left",
    )
    assert ex.validate(planned) is None
    result = ex.execute(planned, update_agent_state=False)
    assert result.success is True
    assert result.rejected is False


def test_action_planner_emits_horizontal_swipes() -> None:
    prior = ExplorationPrior(package_name="com.example.app")
    elements = [
        _el(
            class_name="android.widget.HorizontalScrollView",
            scrollable=True,
            bounds=(0, 400, 1080, 800),
            resource_id="id/carousel",
        ),
        _el(text="Home", clickable=True, bounds=(40, 2100, 200, 2250)),
    ]
    planned = plan_actions(elements, prior=prior, screen_size=(1080, 2400))
    kinds = {p.kind for p in planned}
    assert "swipe_left" in kinds or "swipe_right" in kinds


def test_screen_fallback_vertical_only() -> None:
    regions = analyze_regions([], screen_size=(1080, 2400))
    assert len(regions) == 1
    assert regions[0].region_type == RegionType.SCREEN_FALLBACK
    assert regions[0].supports_up and regions[0].supports_down
    assert not regions[0].supports_left


def test_navigation_graph_swipe_edge_meta() -> None:
    """Gesture candidates carry region meta for NavigationGraph edges."""
    regions = analyze_regions(
        [
            _el(
                class_name="android.widget.HorizontalScrollView",
                scrollable=True,
                bounds=(0, 400, 1080, 800),
            )
        ],
        screen_size=(1080, 2400),
    )
    planned = plan_gesture_actions(regions, screen_size=(1080, 2400))
    assert planned
    assert planned[0].meta.get("spatial") is True
    assert planned[0].meta.get("region_id")
    assert planned[0].meta.get("start")
    assert planned[0].meta.get("end")


def test_ai_context_includes_regions() -> None:
    from app.modules.ai_explorer.context import build_planning_context
    from app.modules.exploration.agent_state import AgentState

    agent = AgentState.create_initial(package_name="com.example.app", seed_goals=False)
    assert agent.region_memory is not None
    agent.region_memory.merge_region(
        ExplorationRegion(
            region_id="region_1",
            region_type=RegionType.HORIZONTAL_CAROUSEL,
            bounds=(0, 500, 1080, 950),
            orientation=ScrollOrientation.HORIZONTAL,
            supports_left=True,
            supports_right=True,
            confidence=0.91,
        )
    )
    agent.region_memory.record_gesture("region_1", "left", outcome="SUCCESS")
    ctx = build_planning_context(agent_state=agent)
    assert ctx.regions
    assert ctx.regions[0]["id"] == "region_1"
    assert ctx.regions[0]["explored"]["left"] is True
