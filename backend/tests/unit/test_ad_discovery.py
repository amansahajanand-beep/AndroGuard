"""Unit tests for Phase 5 advertisement placement discovery."""

from __future__ import annotations

from app.modules.exploration.ad_discovery import (
    AdDiscoveryLimits,
    AdPlacementCatalog,
    AdPlacementDetector,
    AdPlacementFingerprint,
    uniqueness_key_for,
)
from app.modules.exploration.ui_element import UIElement


def _el(**kwargs) -> UIElement:
    defaults = dict(
        text="",
        resource_id="",
        content_description="",
        class_name="android.widget.FrameLayout",
        package="com.example.app",
        bounds=(0, 0, 100, 80),
        clickable=False,
        enabled=True,
        scrollable=False,
        visible=True,
    )
    defaults.update(kwargs)
    return UIElement(**defaults)


def test_detect_bottom_banner_relative_bbox():
    detector = AdPlacementDetector(bbox_quantize=0.05)
    elements = [
        _el(
            class_name="com.google.android.gms.ads.AdView",
            resource_id="com.example:id/banner_ad",
            bounds=(0, 1968, 1080, 2400),
        )
    ]
    found = detector.detect(
        elements,
        screen_width=1080,
        screen_height=2400,
        page="Home",
        trigger_action="entry",
    )
    assert len(found) == 1
    fp = found[0]
    assert fp.ad_detected is True
    assert fp.ad_type == "banner"
    assert fp.position == "bottom"
    assert fp.relative_bbox[0] == 0.0
    assert fp.relative_bbox[2] == 1.0
    assert abs(fp.relative_bbox[1] - 0.82) < 0.02
    assert abs(fp.relative_bbox[3] - 0.18) < 0.02


def test_same_placement_different_content_dedupes():
    limits = AdDiscoveryLimits(target_ad_variations_per_page=5, max_ad_variations_per_page=10)
    catalog = AdPlacementCatalog(limits)
    base = AdPlacementFingerprint(
        page="Home",
        ad_detected=True,
        ad_type="banner",
        position="bottom",
        relative_bbox=(0.0, 0.82, 1.0, 0.18),
        trigger_action="entry",
        visual_state_id="state-a",
        screenshot_path="/tmp/a.png",
    )
    other = AdPlacementFingerprint(
        page="Home",
        ad_detected=True,
        ad_type="banner",
        position="bottom",
        relative_bbox=(0.0, 0.83, 1.0, 0.17),  # tiny creative/layout jitter
        trigger_action="entry",
        visual_state_id="state-b",
        screenshot_path="/tmp/b.png",
    )
    new1, _ = catalog.observe(base)
    new2, rec = catalog.observe(other)
    assert new1 is True
    assert new2 is False
    assert rec.seen_count == 2
    assert catalog.count_for_page("Home") == 1


def test_top_vs_bottom_banner_are_distinct():
    catalog = AdPlacementCatalog(AdDiscoveryLimits())
    bottom = AdPlacementFingerprint(
        page="Home",
        ad_detected=True,
        ad_type="banner",
        position="bottom",
        relative_bbox=(0.0, 0.82, 1.0, 0.18),
        trigger_action="entry",
    )
    top = AdPlacementFingerprint(
        page="Home",
        ad_detected=True,
        ad_type="banner",
        position="top",
        relative_bbox=(0.0, 0.0, 1.0, 0.12),
        trigger_action="entry",
    )
    assert uniqueness_key_for(bottom) != uniqueness_key_for(top)
    assert catalog.observe(bottom)[0] is True
    assert catalog.observe(top)[0] is True
    assert catalog.count_for_page("Home") == 2


def test_scroll_trigger_creates_distinct_native_key():
    a = AdPlacementFingerprint(
        page="Home",
        ad_detected=True,
        ad_type="native",
        position="middle",
        relative_bbox=(0.05, 0.40, 0.90, 0.25),
        trigger_action="entry",
    )
    b = AdPlacementFingerprint(
        page="Home",
        ad_detected=True,
        ad_type="native",
        position="middle",
        relative_bbox=(0.05, 0.40, 0.90, 0.25),
        trigger_action="swipe_down",
    )
    assert uniqueness_key_for(a) != uniqueness_key_for(b)


def test_max_ad_variations_per_page_cap():
    limits = AdDiscoveryLimits(target_ad_variations_per_page=2, max_ad_variations_per_page=2)
    catalog = AdPlacementCatalog(limits)
    for index in range(5):
        fp = AdPlacementFingerprint(
            page="Home",
            ad_detected=True,
            ad_type="banner",
            position="bottom" if index % 2 == 0 else "top",
            relative_bbox=(0.0, 0.1 * index, 1.0, 0.1),
            trigger_action=f"tap:{index}",
        )
        # Force unique keys via different quantized tops + action buckets.
        catalog.observe(fp)
    assert catalog.count_for_page("Home") <= 2


def test_detect_interstitial_fullscreen():
    detector = AdPlacementDetector()
    elements = [
        _el(
            class_name="android.webkit.WebView",
            resource_id="com.example:id/interstitial_ad",
            bounds=(0, 0, 1080, 2400),
        )
    ]
    found = detector.detect(
        elements,
        screen_width=1080,
        screen_height=2400,
        page="Home",
        trigger_action="tap",
    )
    assert found
    assert found[0].ad_type in {"interstitial", "unknown"}
    assert found[0].position == "fullscreen"


def test_gate_activity_yields_no_placements():
    detector = AdPlacementDetector()
    elements = [
        _el(
            class_name="android.widget.FrameLayout",
            bounds=(0, 0, 1080, 2400),
        ),
        _el(
            class_name="android.widget.Button",
            text="Set As Default",
            clickable=True,
            bounds=(80, 1800, 1000, 1950),
        ),
    ]
    found = detector.detect(
        elements,
        screen_width=1080,
        screen_height=2400,
        page="DefaultApp",
        activity="com.reader.alldocviewer.pdfeditor.launcher.activity.DefaultAppActivity",
        trigger_action="entry",
    )
    assert found == []


def test_bare_fullscreen_frame_is_not_an_ad():
    detector = AdPlacementDetector()
    elements = [
        _el(
            class_name="android.widget.FrameLayout",
            bounds=(0, 0, 1080, 2400),
        ),
        _el(
            class_name="android.view.View",
            bounds=(0, 2060, 1080, 2200),
        ),
    ]
    found = detector.detect(
        elements,
        screen_width=1080,
        screen_height=2400,
        page="Home",
        activity="com.example.app.MainActivity",
        trigger_action="entry",
    )
    assert found == []


def test_target_requires_strong_evidence():
    from app.modules.exploration.ad_discovery import is_strong_ad_evidence

    limits = AdDiscoveryLimits(target_ad_variations_per_page=2, max_ad_variations_per_page=10)
    catalog = AdPlacementCatalog(limits)
    weak = AdPlacementFingerprint(
        page="Home",
        ad_detected=True,
        ad_type="banner",
        position="bottom",
        relative_bbox=(0.0, 0.82, 1.0, 0.18),
        trigger_action="entry",
        evidence=("geometry:banner_band",),
    )
    strong = AdPlacementFingerprint(
        page="Home",
        ad_detected=True,
        ad_type="banner",
        position="top",
        relative_bbox=(0.0, 0.0, 1.0, 0.12),
        trigger_action="entry",
        evidence=("class:com.google.android.gms.ads.AdView",),
    )
    catalog.observe(weak)
    catalog.observe(strong)
    assert is_strong_ad_evidence(strong.evidence)
    assert not is_strong_ad_evidence(weak.evidence)
    assert catalog.count_for_page("Home") == 2
    assert catalog.strong_count_for_page("Home") == 1
    assert catalog.has_reached_target("Home") is False


def test_plan_actions_prefers_set_as_default():
    from app.modules.exploration.action_planner import plan_actions

    elements = [
        _el(
            class_name="android.widget.TextView",
            text="Terms of Service",
            clickable=True,
            bounds=(100, 2200, 400, 2300),
        ),
        _el(
            class_name="android.widget.Button",
            text="Get Started",
            clickable=True,
            bounds=(80, 1800, 1000, 1950),
        ),
    ]
    planned = plan_actions(elements, screen_size=(1080, 2400), include_menu=False)
    taps = [p for p in planned if p.kind == "tap"]
    assert taps
    assert taps[0].meta.get("is_onboarding_cta") is True
    assert "Get Started" in (taps[0].label or taps[0].meta.get("text") or "")


def test_plan_actions_prefers_cancel_on_default_home_dialog() -> None:
    from app.modules.exploration.action_planner import (
        looks_like_default_home_gate,
        plan_actions,
    )

    elements = [
        _el(text="Set # Phone Cleaner as your default home app?", clickable=False),
        _el(text="# Alarm Clock", bounds=(40, 600, 900, 700), clickable=True),
        _el(
            text="Cancel",
            bounds=(400, 1600, 600, 1700),
            class_name="android.widget.Button",
            clickable=True,
        ),
        _el(
            text="Set as default",
            bounds=(620, 1600, 980, 1700),
            class_name="android.widget.Button",
            clickable=True,
            enabled=False,
        ),
    ]
    assert looks_like_default_home_gate(elements) is True
    planned = plan_actions(elements, screen_size=(1080, 2400), include_menu=False)
    taps = [p for p in planned if p.kind == "tap"]
    assert taps
    assert taps[0].label == "Cancel"


def test_plan_actions_avoids_set_as_default_home_hijack():
    from app.modules.exploration.action_planner import plan_actions

    elements = [
        _el(
            class_name="android.widget.Button",
            text="Set As Default",
            resource_id="com.example:id/btnSetDefault",
            clickable=True,
            bounds=(80, 1800, 1000, 1950),
        ),
        _el(
            class_name="android.widget.Button",
            text="Files",
            clickable=True,
            bounds=(100, 800, 400, 900),
        ),
    ]
    planned = plan_actions(elements, screen_size=(1080, 2400), include_menu=False)
    taps = [p for p in planned if p.kind == "tap"]
    assert taps
    assert "Files" in (taps[0].label or taps[0].meta.get("text") or "")
    assert taps[0].meta.get("is_home_hijack_cta") is not True


def test_catalog_merge_across_runs():
    a = AdPlacementCatalog(AdDiscoveryLimits())
    b = AdPlacementCatalog(AdDiscoveryLimits())
    fp1 = AdPlacementFingerprint(
        page="Home",
        ad_detected=True,
        ad_type="banner",
        position="bottom",
        relative_bbox=(0.0, 0.82, 1.0, 0.18),
        trigger_action="entry",
        run_index=0,
    )
    fp2 = AdPlacementFingerprint(
        page="Home",
        ad_detected=True,
        ad_type="interstitial",
        position="fullscreen",
        relative_bbox=(0.0, 0.0, 1.0, 1.0),
        trigger_action="tap",
        run_index=1,
    )
    a.observe(fp1)
    b.observe(fp2)
    added = a.merge(b)
    assert added == 1
    assert a.count_for_page("Home") == 2


def test_fingerprint_schema_mapping_includes_relative_bbox():
    from app.modules.exploration.ad_explorer import fingerprint_to_schema_ad

    fp = AdPlacementFingerprint(
        page="Home",
        ad_detected=True,
        ad_type="banner",
        position="bottom",
        relative_bbox=(0.0, 0.82, 1.0, 0.18),
        uniqueness_key="abc",
        trigger_action="entry",
        evidence=("class:AdView",),
    )
    mapped = fingerprint_to_schema_ad(fp)
    assert mapped.page == "Home"
    assert mapped.relative_bbox == [0.0, 0.82, 1.0, 0.18]
    assert mapped.position == "bottom"
    assert mapped.ad_type == "banner"
