from app.core.config import Settings
from app.services import mailer


def test_smtp_user_is_accepted_as_an_alias_for_smtp_username(monkeypatch) -> None:
    monkeypatch.delenv("SMTP_USERNAME", raising=False)
    monkeypatch.setenv("SMTP_USER", "key-123")
    assert Settings(_env_file=None).smtp_username == "key-123"


def test_smtp_username_still_works(monkeypatch) -> None:
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.setenv("SMTP_USERNAME", "key-456")
    assert Settings(_env_file=None).smtp_username == "key-456"


def test_send_email_logs_in_when_a_username_is_configured(monkeypatch) -> None:
    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=0):
            calls.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            calls.append(("starttls",))

        def login(self, user, password):
            calls.append(("login", user, password))

        def send_message(self, msg):
            calls.append(("send", msg["To"]))

    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    for key, value in {"smtp_host": "smtp.example.com", "smtp_port": 587, "smtp_from": "App <a@example.com>",
                       "smtp_username": "key", "smtp_password": "secret", "smtp_use_ssl": False, "smtp_use_tls": True}.items():
        monkeypatch.setattr(mailer.settings, key, value)
    assert mailer.send_email("u@example.com", "Subject", "body") is True
    assert ("starttls",) in calls and ("login", "key", "secret") in calls and ("send", "u@example.com") in calls
