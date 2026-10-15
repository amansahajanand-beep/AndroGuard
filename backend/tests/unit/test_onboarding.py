from app.modules.exploration.onboarding import looks_like_language_screen, plan_language_actions
from app.modules.exploration.ui_element import UIElement

SIZE = (1080, 2400)


def el(text="", rid="", bounds=(0, 0, 0, 0), clickable=True, cls="android.widget.TextView", pkg="com.app"):
    return UIElement(text=text, resource_id=rid, bounds=bounds, clickable=clickable, class_name=cls, package=pkg)


def language_screen():
    return [
        el("Hindi", bounds=(80, 600, 1000, 720)),
        el("English", bounds=(80, 740, 1000, 860)),
        el("Español", bounds=(80, 880, 1000, 1000)),
        el("Français", bounds=(80, 1020, 1000, 1140)),
        el("Next", rid="com.app:id/btn_next", bounds=(300, 1900, 780, 2040)),
        # A native ad card on the same screen that must never be tapped.
        el("Install", rid="com.app:id/ad_call_to_action", bounds=(700, 2100, 1040, 2220)),
    ]


def test_language_list_is_detected() -> None:
    assert looks_like_language_screen(language_screen())
    assert not looks_like_language_screen([el("Start workout"), el("Settings")])


def test_activity_name_plus_two_languages_counts() -> None:
    elements = [el("English", bounds=(0, 0, 100, 50)), el("Hindi", bounds=(0, 60, 100, 110))]
    assert looks_like_language_screen(elements, activity="com.app/.LanguageSelectActivity")


def test_english_is_chosen_first_then_confirm_never_the_ad() -> None:
    planned = plan_language_actions(language_screen(), screen_size=SIZE)
    assert planned[0].label.lower().startswith("english")
    assert planned[0].meta["tag"] == "language_select"
    labels = [p.label.lower() for p in planned]
    assert "next" in labels
    assert not any("install" in label for label in labels)


def test_already_tapped_keys_are_skipped_so_it_does_not_loop() -> None:
    first = plan_language_actions(language_screen(), screen_size=SIZE)
    skip = {item.key for item in first}
    assert plan_language_actions(language_screen(), screen_size=SIZE, skip_keys=skip) == []


def test_falls_back_to_first_row_when_english_is_absent() -> None:
    elements = [
        el("Hindi", bounds=(80, 600, 1000, 720)),
        el("Español", bounds=(80, 740, 1000, 860)),
        el("Français", bounds=(80, 880, 1000, 1000)),
    ]
    planned = plan_language_actions(elements, screen_size=SIZE)
    assert planned[0].label == "Hindi"
