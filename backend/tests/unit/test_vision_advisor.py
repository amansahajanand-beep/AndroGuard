from io import BytesIO

from PIL import Image

from app.core.config import settings
from app.modules.ai_explorer.vision_advisor import choose_with_vision, parse_choice


def png_bytes() -> bytes:
    out = BytesIO()
    Image.new("RGB", (1080, 2400), "white").save(out, format="PNG")
    return out.getvalue()


CANDIDATES = [("English", [80, 740, 1000, 860]), ("Next", [300, 1900, 780, 2040]), ("Install", [700, 2100, 1040, 2220])]


def test_parse_valid_choice_and_ads() -> None:
    result = parse_choice('{"screen_kind":"language","choice":1,"ad_candidates":[3],"reason":"pick language"}', 3)
    assert result and result.choice_index == 1 and result.ad_indexes == [3]


def test_choice_flagged_as_ad_is_dropped() -> None:
    result = parse_choice('{"choice":3,"ad_candidates":[3]}', 3)
    assert result and result.choice_index is None and result.ad_indexes == [3]


def test_out_of_range_and_garbage_are_ignored() -> None:
    assert parse_choice("no json here", 3) is None
    result = parse_choice('{"choice":9,"ad_candidates":[0, 7, "x"]}', 3)
    assert result and result.choice_index is None and result.ad_indexes == []


def test_extracts_json_from_prose() -> None:
    result = parse_choice('Sure! {"choice": 2, "ad_candidates": []} done', 3)
    assert result and result.choice_index == 2


def test_no_key_means_no_call(monkeypatch) -> None:
    monkeypatch.setattr(settings, "vision_planner_api_key", None)
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    called = []
    assert choose_with_vision(png_bytes(), CANDIDATES, transport=lambda *a, **k: called.append(1) or "") is None
    assert not called


def test_request_carries_image_and_numbered_candidates(monkeypatch) -> None:
    monkeypatch.setattr(settings, "vision_planner_api_key", "test-key")
    seen = {}

    def fake(body, **kwargs):
        seen["body"] = body
        seen["key"] = kwargs["api_key"]
        return '{"screen_kind":"language select","choice":1,"ad_candidates":[3],"reason":"x"}'

    result = choose_with_vision(png_bytes(), CANDIDATES, transport=fake)
    assert result and result.choice_index == 1 and result.ad_indexes == [3]
    content = seen["body"]["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[0]["source"]["media_type"] == "image/jpeg"
    assert '3. "Install"' in content[1]["text"]
    assert seen["key"] == "test-key"


def test_transport_failure_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(settings, "vision_planner_api_key", "k")

    def boom(*a, **k):
        raise OSError("network down")

    assert choose_with_vision(png_bytes(), CANDIDATES, transport=boom) is None
