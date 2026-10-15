import json

from app.core.config import settings
from app.services import ai_provider
from app.services.ai_report import generate_ai_review

RESULT = {"data": {"apk": {"package_name": "com.x"}, "permissions": [{"name": "android.permission.CAMERA"}]}}


def use(monkeypatch, **values) -> None:
    defaults = {
        "ai_report_enabled": True,
        "ai_report_provider": "anthropic",
        "ai_report_api_key": None,
        "anthropic_api_key": None,
        "ai_explorer_api_key": None,
        "openai_api_key": None,
        "ai_report_model": "claude-sonnet-5-5",
        "ai_report_api_base": "https://api.anthropic.com",
        "ai_explorer_model": "nvidia/nemotron-3.5-lightning-30b-a3b",
        "ai_explorer_api_base": "https://integrate.api.nvidia.com/v1",
    }
    for key, value in {**defaults, **values}.items():
        monkeypatch.setattr(settings, key, value)


def test_anthropic_is_the_default(monkeypatch) -> None:
    use(monkeypatch, anthropic_api_key="a-key")
    assert ai_provider.provider() == "anthropic"
    assert ai_provider.api_key() == "a-key"
    assert ai_provider.api_base() == "https://api.anthropic.com"
    assert ai_provider.model() == "claude-sonnet-5-5"
    assert ai_provider.configured()


def test_nvidia_reuses_the_existing_ai_explorer_key_base_and_model(monkeypatch) -> None:
    use(monkeypatch, ai_report_provider="nvidia", ai_explorer_api_key="nvapi-abc")
    assert ai_provider.api_key() == "nvapi-abc"
    assert ai_provider.api_base() == "https://integrate.api.nvidia.com/v1"
    assert ai_provider.model() == "nvidia/nemotron-3.5-lightning-30b-a3b"
    assert ai_provider.configured()


def test_nvidia_without_any_key_is_not_configured(monkeypatch) -> None:
    use(monkeypatch, ai_report_provider="nvidia")
    assert not ai_provider.configured()


def test_an_explicit_model_and_key_win(monkeypatch) -> None:
    use(monkeypatch, ai_report_provider="nvidia", ai_report_api_key="own-key", ai_report_model="meta/llama-3.3-70b-instruct",
        ai_report_api_base="https://example.com/v1")
    assert (ai_provider.api_key(), ai_provider.model(), ai_provider.api_base()) == ("own-key", "meta/llama-3.3-70b-instruct", "https://example.com/v1")


def test_unknown_provider_falls_back_to_anthropic(monkeypatch) -> None:
    use(monkeypatch, ai_report_provider="whatever")
    assert ai_provider.provider() == "anthropic"


def test_request_is_converted_to_chat_completions_and_thinking_is_stripped(monkeypatch) -> None:
    sent = {}

    def fake_post(*, base, api_key, payload, timeout):
        sent.update(base=base, key=api_key, payload=payload)
        return '<think>I should output {"summary": "wrong"}</think>{"summary": "ok", "findings": []}'

    monkeypatch.setattr("app.modules.ai_explorer.llm._post_chat", fake_post)
    body = {"model": "m", "max_tokens": 100, "temperature": 0, "system": "SYS",
            "messages": [{"role": "user", "content": "Facts:\nperm:CAMERA: x"}]}
    text = ai_provider._openai_transport(body, api_key="nvapi-abc", api_base="https://integrate.api.nvidia.com/v1/", timeout=5)
    assert text == '{"summary": "ok", "findings": []}'
    assert sent["base"] == "https://integrate.api.nvidia.com/v1" and sent["key"] == "nvapi-abc"
    assert [m["role"] for m in sent["payload"]["messages"]] == ["system", "user"]
    assert sent["payload"]["messages"][1]["content"].startswith("Facts:")
    assert "response_format" not in sent["payload"]


def test_review_works_end_to_end_through_the_nvidia_path(monkeypatch) -> None:
    use(monkeypatch, ai_report_provider="nvidia", ai_explorer_api_key="nvapi-abc")
    seen = {}

    def fake_post(*, base, api_key, payload, timeout):
        seen["model"] = payload["model"]
        return json.dumps({"summary": "Camera access.", "findings": [{"title": "Camera", "severity": "low", "evidence_ids": ["perm:CAMERA"]}], "ad_notes": ""})

    monkeypatch.setattr("app.modules.ai_explorer.llm._post_chat", fake_post)
    review = generate_ai_review(RESULT)
    assert review["model"] == "nvidia/nemotron-3.5-lightning-30b-a3b" == seen["model"]
    assert review["findings"][0]["evidence_ids"] == ["perm:CAMERA"]


def test_nvidia_requests_switch_thinking_off(monkeypatch) -> None:
    use(monkeypatch, ai_report_provider="nvidia", ai_explorer_api_key="nvapi-abc", ai_report_disable_thinking=True)
    sent = []

    def fake_post(*, base, api_key, payload, timeout):
        sent.append(payload)
        return '{"summary": "ok"}'

    monkeypatch.setattr("app.modules.ai_explorer.llm._post_chat", fake_post)
    body = {"model": "m", "max_tokens": 100, "system": "S", "messages": [{"role": "user", "content": "u"}]}
    ai_provider._openai_transport(body, api_key="k", api_base="https://x/v1", timeout=5)
    assert sent[0]["chat_template_kwargs"] == {"enable_thinking": False}


def test_if_the_model_rejects_the_setting_it_retries_with_more_room(monkeypatch) -> None:
    use(monkeypatch, ai_report_provider="nvidia", ai_explorer_api_key="nvapi-abc", ai_report_disable_thinking=True)
    sent = []

    def fake_post(*, base, api_key, payload, timeout):
        sent.append(payload)
        if "chat_template_kwargs" in payload:
            raise RuntimeError("HTTP 400")
        return '{"summary": "ok"}'

    monkeypatch.setattr("app.modules.ai_explorer.llm._post_chat", fake_post)
    body = {"model": "m", "max_tokens": 100, "system": "S", "messages": [{"role": "user", "content": "u"}]}
    assert ai_provider._openai_transport(body, api_key="k", api_base="https://x/v1", timeout=5) == '{"summary": "ok"}'
    assert len(sent) == 2 and "chat_template_kwargs" not in sent[1] and sent[1]["max_tokens"] == 500


def test_thinking_setting_is_not_sent_to_other_providers(monkeypatch) -> None:
    use(monkeypatch, ai_report_provider="openai", openai_api_key="sk-x", ai_report_model="gpt-4o-mini")
    sent = []
    monkeypatch.setattr("app.modules.ai_explorer.llm._post_chat", lambda **kw: sent.append(kw["payload"]) or "{}")
    ai_provider._openai_transport({"model": "m", "messages": []}, api_key="k", api_base="https://x/v1", timeout=5)
    assert "chat_template_kwargs" not in sent[0]
