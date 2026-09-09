from app.storage.s3 import object_key, public_url


def test_object_key() -> None:
    assert object_key("job-1", "icon.png") == "job-1/icon.png"


def test_public_url(monkeypatch) -> None:
    from app.core import config

    monkeypatch.setattr(
        config.settings,
        "s3_public_base_url",
        "https://example.supabase.co/storage/v1/object/public",
    )
    monkeypatch.setattr(config.settings, "s3_bucket", "apk-screenshots")
    url = public_url("abc", "ic_launcher.webp")
    assert url == "https://example.supabase.co/storage/v1/object/public/apk-screenshots/abc/ic_launcher.webp"
