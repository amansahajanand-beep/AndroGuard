from types import SimpleNamespace

from app.modules.exploration.actions import BackAction, CoordinateTapAction, TapAction
from app.modules.exploration.ad_escape import escape_ad, has_countdown, is_ad_screen
from app.modules.exploration.ui_element import UIElement

TARGET = "com.fitpal.tracker"
AD_ACTIVITY = f"{TARGET}/com.google.android.gms.ads.AdActivity"
HOME_ACTIVITY = f"{TARGET}/.HomeActivity"
SIZE = (1080, 2400)


def el(**kw) -> UIElement:
    return UIElement(**{"clickable": True, "enabled": True, "visible": True, **kw})


CLOSE = el(content_description="Close ad", bounds=(900, 80, 1020, 200), class_name="android.widget.ImageButton")
CONTENT = [el(text="Start workout", bounds=(100, 800, 980, 1000))]


class FakeUi:
    def __init__(self, screens, on_back=None, on_tap=None):
        self.screens = list(screens)  # successive (elements, activity); advance on actions
        self.actions = []
        self.on_back = on_back
        self.on_tap = on_tap

    def perform(self, action):
        self.actions.append(action)
        if isinstance(action, BackAction) and self.on_back:
            self.on_back(self)
        if isinstance(action, (TapAction, CoordinateTapAction)) and self.on_tap:
            self.on_tap(self)

    def advance(self):
        if len(self.screens) > 1:
            self.screens.pop(0)

    @property
    def current(self):
        return self.screens[0]


def run(ui, *, recover=lambda: True, countdown=8.0, sleeps=None):
    from app.modules.ai_explorer.assist import plan_ad_dismiss_actions

    return escape_ad(
        ui=ui,
        dump=lambda: (ui.current[0], SIZE, ui.current[1]),
        package=lambda: ui.current[1].split("/")[0],
        is_foreground=lambda: ui.current[1].split("/")[0] == TARGET,
        target_package=TARGET,
        dismiss_candidates=plan_ad_dismiss_actions,
        recover=recover,
        settle=lambda: None,
        sleep=(sleeps.append if sleeps is not None else (lambda _s: None)),
        countdown_wait_seconds=countdown,
    )


def test_in_package_ad_activity_is_an_ad() -> None:
    assert is_ad_screen([], activity=AD_ACTIVITY, package=TARGET, target_package=TARGET, screen_size=SIZE)
    assert not is_ad_screen(CONTENT, activity=HOME_ACTIVITY, package=TARGET, target_package=TARGET, screen_size=SIZE)


def test_no_ad_means_no_action() -> None:
    ui = FakeUi([(CONTENT, HOME_ACTIVITY)])
    result = run(ui)
    assert not result.ad_seen and not ui.actions


def test_taps_close_control_and_returns_to_app() -> None:
    ui = FakeUi([([CLOSE], AD_ACTIVITY), (CONTENT, HOME_ACTIVITY)], on_tap=lambda u: u.advance())
    result = run(ui)
    assert result.ad_seen and result.escaped
    assert isinstance(ui.actions[0], TapAction)


def test_waits_for_countdown_then_closes() -> None:
    countdown = el(text="Skip in 3", clickable=False, bounds=(900, 80, 1020, 200))
    ui = FakeUi(
        [([countdown], AD_ACTIVITY), ([countdown], AD_ACTIVITY), ([CLOSE], AD_ACTIVITY), (CONTENT, HOME_ACTIVITY)],
        on_tap=lambda u: u.advance(),
    )
    sleeps: list[float] = []

    def advance_on_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        ui.advance()

    from app.modules.ai_explorer.assist import plan_ad_dismiss_actions

    result = escape_ad(
        ui=ui,
        dump=lambda: (ui.current[0], SIZE, ui.current[1]),
        package=lambda: ui.current[1].split("/")[0],
        is_foreground=lambda: ui.current[1].split("/")[0] == TARGET,
        target_package=TARGET,
        dismiss_candidates=plan_ad_dismiss_actions,
        recover=lambda: True,
        settle=lambda: None,
        sleep=advance_on_sleep,
    )
    assert "wait_countdown" in result.steps and result.escaped
    assert has_countdown([countdown])


def test_unlabeled_x_uses_corner_tap_then_back() -> None:
    ui = FakeUi(
        [([], AD_ACTIVITY), (CONTENT, HOME_ACTIVITY)],
        on_tap=lambda u: u.advance(),
    )
    result = run(ui)
    assert result.escaped
    assert isinstance(ui.actions[0], CoordinateTapAction)


def test_back_used_when_corner_does_nothing() -> None:
    ui = FakeUi([([], AD_ACTIVITY), (CONTENT, HOME_ACTIVITY)], on_back=lambda u: u.advance())
    result = run(ui)
    assert result.escaped
    assert any(isinstance(a, BackAction) for a in ui.actions)


def test_stuck_ad_falls_back_to_recovery() -> None:
    ui = FakeUi([([], AD_ACTIVITY)])
    called = []
    result = run(ui, recover=lambda: called.append(1) or True)
    assert called and result.escaped and "recover" in result.steps


def test_ad_that_opened_browser_is_recovered() -> None:
    ui = FakeUi([([], "com.android.chrome/.Main")])
    called = []
    result = run(ui, recover=lambda: called.append(1) or True)
    assert result.ad_seen and "left_app" in result.steps and called


def test_webview_page_with_corner_icon_is_not_an_ad() -> None:
    page = [
        el(content_description="More options", bounds=(940, 60, 1060, 200)),
        el(text="Privacy", clickable=False, bounds=(100, 300, 900, 400)),
        el(class_name="android.webkit.WebView", bounds=(0, 300, 1080, 2300), text="privacy"),
    ]
    assert not is_ad_screen(page, activity=f"{TARGET}/.WebActivity", package=TARGET, target_package=TARGET, screen_size=SIZE)


def test_layout_detection_still_works_with_ad_sdk_evidence() -> None:
    page = [
        el(content_description="Close", bounds=(940, 60, 1060, 200)),
        el(class_name="com.google.android.gms.ads.AdView", package="com.google.android.gms.ads", bounds=(0, 300, 1080, 2300)),
    ]
    assert is_ad_screen(page, activity=f"{TARGET}/.MainActivity", package=TARGET, target_package=TARGET, screen_size=SIZE)
