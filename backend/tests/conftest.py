import os
from pathlib import Path

os.environ["DATABASE_URL"] = ""
# Tests must not depend on (or spend) the developer's real AI keys / provider from .env.
for _name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AI_EXPLORER_API_KEY", "AI_REPORT_API_KEY", "VISION_PLANNER_API_KEY"):
    os.environ[_name] = ""
os.environ["AI_REPORT_PROVIDER"] = "anthropic"
os.environ["AI_REPORT_ENABLED"] = "false"
os.environ["VISION_PLANNER_ENABLED"] = "false"
os.environ["LOG_TO_FILE"] = "false"  # keep test output out of tmp/backend.log
os.environ["UIAUTOMATOR2_ENABLED"] = "false"  # tests never talk to a real device
os.environ["S3_ACCESS_KEY"] = ""
os.environ["S3_SECRET_KEY"] = ""

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_current_user_header_or_query
from app.main import app
from app.schemas.auth import UserProfile

USER_A = UserProfile(id="00000000-0000-0000-0000-00000000000a", full_name="User A", company_name="A Co", email="a@example.com")
USER_B = UserProfile(id="00000000-0000-0000-0000-00000000000b", full_name="User B", company_name="B Co", email="b@example.com")


@pytest.fixture
def anon_client() -> TestClient:
    """No credentials: every protected route must answer 401."""
    app.dependency_overrides.clear()
    return TestClient(app)


@pytest.fixture
def client():
    """Authenticated as USER_A (auth itself is covered by test_auth / test_access_control)."""
    app.dependency_overrides[get_current_user] = lambda: USER_A
    app.dependency_overrides[get_current_user_header_or_query] = lambda: USER_A
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def as_user():
    """Switch the authenticated identity mid-test."""

    def _switch(user: UserProfile) -> None:
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_current_user_header_or_query] = lambda: user

    yield _switch
    app.dependency_overrides.clear()


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"
