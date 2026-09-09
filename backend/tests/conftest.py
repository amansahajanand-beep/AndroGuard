import os
from pathlib import Path

os.environ["DATABASE_URL"] = ""
os.environ["S3_ACCESS_KEY"] = ""
os.environ["S3_SECRET_KEY"] = ""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"
