from app.modules.exploration.action_planner import default_home_pitch_visible, has_real_app_ui
from app.modules.exploration.ui_element import UIElement

PKG = "com.albums.photoeditor.photogallery"


def el(text="", desc="", bounds=(0, 0, 100, 100), clickable=True, pkg=PKG):
    return UIElement(text=text, content_description=desc, bounds=bounds, clickable=clickable, package=pkg)


def photos_home():
    """The real Photos screen from the stuck run: search, overflow, bottom navigation."""
    return [
        el(desc="Search", bounds=(900, 100, 1000, 200)),
        el(desc="More options", bounds=(1000, 100, 1080, 200)),
        el(text="Photos", bounds=(0, 2200, 270, 2400)),
        el(text="Albums", bounds=(270, 2200, 540, 2400)),
        el(text="Stories", bounds=(540, 2200, 810, 2400)),
        el(text="More", bounds=(810, 2200, 1080, 2400)),
        el(text="There's nothing to show", clickable=False),
    ]


def test_photos_home_is_real_app_ui_and_not_a_default_pitch() -> None:
    elements = photos_home()
    assert has_real_app_ui(elements, target_package=PKG)
    assert not default_home_pitch_visible(elements)


def test_set_as_default_prompt_is_detected_by_text() -> None:
    prompt = [el(text="Set as default", bounds=(100, 1500, 900, 1650)), el(text="Cancel", bounds=(100, 1700, 900, 1800))]
    assert default_home_pitch_visible(prompt)


def test_dialog_sentence_is_detected() -> None:
    assert default_home_pitch_visible([el(text="Set Photos as your default home app", clickable=False)])


def test_nearly_empty_shell_is_not_real_ui() -> None:
    shell = [el(text="Welcome", clickable=False), el(text="Continue")]
    assert not has_real_app_ui(shell, target_package=PKG)


def test_other_package_controls_do_not_count_as_app_ui() -> None:
    system = [el(text=t, pkg="com.android.settings") for t in ("A", "B", "C", "D")]
    assert not has_real_app_ui(system, target_package=PKG)
