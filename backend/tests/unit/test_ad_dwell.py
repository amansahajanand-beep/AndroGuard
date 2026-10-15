from types import SimpleNamespace

from app.modules.exploration.ad_dwell import dwell_observe, frame_publish_records
from app.modules.exploration.ui_element import UIElement

TARGET = "com.fitpal.tracker"
ACT = f"{TARGET}/.HomeActivity"
SIZE = (1080, 2400)


def fp(position, ad_type="banner", bbox=(0.0, 0.85, 1.0, 0.1)):
    return SimpleNamespace(ad_type=ad_type, position=position, relative_bbox=bbox, evidence=("id:ad",))


class Clock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


def run(frames_by_tick, *, activities=None, seconds=6.0, max_frames=4, start_activity=ACT):
    clock = Clock()
    tick = {"i": 0}
    captured = []

    def current():
        return min(int(clock.t / 1.5), len(frames_by_tick) - 1)

    def dump():
        i = current()
        act = activities[i] if activities else ACT
        return ([UIElement(text="x", bounds=(0, 0, 10, 10))], SIZE, act)

    def detect(elements, size, act):
        return frames_by_tick[current()]

    def capture():
        shot = SimpleNamespace(state_id=f"shot-{len(captured)}", activity=ACT)
        captured.append(shot)
        return shot

    out = dwell_observe(
        state_id="s1", page="HomeActivity", activity=start_activity, target_package=TARGET,
        dump=dump, package=lambda: TARGET, detect=detect, capture=capture,
        seconds=seconds, interval=1.5, max_frames=max_frames,
        sleep=clock.sleep, clock=clock.now,
    )
    return out, captured


def test_bottom_banner_then_top_banner_is_recorded_as_a_position_change() -> None:
    bottom = [fp("bottom")]
    top = [fp("top", bbox=(0.0, 0.02, 1.0, 0.1))]
    out, captured = run([bottom, bottom, top, top])
    assert out.timeline.positions_seen == ["bottom", "top"]
    assert out.timeline.to_dict()["position_changed"] is True
    assert len(out.timeline.sightings) == 2
    assert out.timeline.sightings[0].frame_id == "s1"  # first frame is the state's own screenshot
    assert len(captured) == 1  # only the layout change needed a new frame


def test_unchanged_layout_captures_nothing_extra() -> None:
    bottom = [fp("bottom")]
    out, captured = run([bottom] * 5)
    assert len(out.timeline.sightings) == 1 and not captured


def test_no_ads_yields_empty_timeline() -> None:
    out, _ = run([[]] * 4)
    assert out.timeline.sightings == []


def test_frame_cap_is_respected() -> None:
    frames = [[fp("bottom")], [fp("top", bbox=(0, 0.02, 1, 0.1))], [fp("middle", ad_type="native", bbox=(0.1, 0.4, 0.8, 0.3))], [fp("bottom", bbox=(0, 0.7, 1, 0.1))]]
    out, captured = run(frames, max_frames=1)
    assert len(captured) == 1
    assert len(out.timeline.sightings) == 4


def test_stops_when_screen_changes() -> None:
    out, _ = run([[fp("bottom")], [fp("bottom")]], activities=[ACT, f"{TARGET}/.Other"])
    assert out.timeline.stopped_reason == "navigated"


def test_fullscreen_ad_activity_is_recorded_and_stops_dwell() -> None:
    ad_act = f"{TARGET}/com.google.android.gms.ads.AdActivity"
    out, captured = run([[], []], activities=[ad_act, ad_act], start_activity=ad_act)
    assert out.timeline.stopped_reason == "ad_screen"
    assert out.timeline.sightings and out.timeline.sightings[0].is_fullscreen
    assert out.timeline.sightings[0].position == "fullscreen"
    assert len(captured) == 1  # the ad screen itself was captured


def test_frames_wrapped_for_upload_carry_position() -> None:
    bottom = [fp("bottom")]
    top = [fp("top", bbox=(0, 0.02, 1, 0.1))]
    out, _ = run([bottom, top, top])
    records = frame_publish_records(out.frames, {"s1": out.timeline})
    assert records and records[0].ad_placement.candidate_regions[0]["position"] == "top"
