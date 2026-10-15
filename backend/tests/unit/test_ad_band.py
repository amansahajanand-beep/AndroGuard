from app.modules.exploration.action_planner import _ad_text_regions, _is_banner_ad_slot, plan_actions
from app.modules.exploration.ui_element import UIElement

W, H = 1080, 2400
PKG = "com.albums.photoeditor.photogallery"


def el(text="", desc="", bounds=(0, 0, 0, 0), clickable=True, rid="", cls="android.view.View"):
    return UIElement(text=text, content_description=desc, bounds=bounds, clickable=clickable, resource_id=rid,
                     class_name=cls, package=PKG, enabled=True, visible=True)


def photos_with_banner():
    """The stuck screen: bottom navigation above a 'Test Ad' banner whose headline is a narrow node."""
    return [
        el(bounds=(0, 0, W, H), clickable=False, cls="android.widget.FrameLayout"),
        el(desc="Search", bounds=(900, 100, 1000, 200)),
        el(text="Photos", bounds=(0, 2000, 270, 2150)),
        el(text="Albums", bounds=(270, 2000, 540, 2150)),
        el(text="Stories", bounds=(540, 2000, 810, 2150)),
        el(text="More", bounds=(810, 2000, 1080, 2150)),
        # Ad band, bottom 7% of the screen.
        el(text="Test Ad", clickable=False, bounds=(470, 2235, 620, 2285)),
        el(text="Find University Courses + Career Tests", rid="asoch-id-442hwvi8qeh7", bounds=(210, 2290, 770, 2360)),
        el(text="Open", bounds=(780, 2290, 1050, 2370), cls="android.widget.Button"),
    ]


def test_headline_and_open_button_inside_the_ad_band_are_ads() -> None:
    elements = photos_with_banner()
    regions = _ad_text_regions(elements)
    headline = elements[7]
    open_btn = elements[8]
    assert _is_banner_ad_slot(headline, screen_size=(W, H), ad_regions=regions)
    assert _is_banner_ad_slot(open_btn, screen_size=(W, H), ad_regions=regions)


def test_bottom_navigation_above_the_ad_is_not_an_ad() -> None:
    elements = photos_with_banner()
    regions = _ad_text_regions(elements)
    for nav in elements[2:6]:
        assert not _is_banner_ad_slot(nav, screen_size=(W, H), ad_regions=regions)


def test_planner_picks_real_navigation_never_the_ad_headline() -> None:
    planned = plan_actions(photos_with_banner(), screen_size=(W, H), activity=f"{PKG}/.LauncherHomeActivity")
    labels = [p.label for p in planned if p.kind == "tap"]
    assert not any("University" in label or label == "Open" for label in labels)
    assert any(label in ("Albums", "Stories", "More", "Search") for label in labels)


def test_no_ad_copy_means_no_extra_regions() -> None:
    plain = [el(text="Albums", bounds=(270, 2000, 540, 2150))]
    assert _ad_text_regions(plain) == []
