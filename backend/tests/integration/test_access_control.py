import pytest
from fastapi.testclient import TestClient

from tests.conftest import USER_A, USER_B
from app.jobs.models import JobRecord
from app.jobs.store import get_job_store

JOB_ID = "11111111-1111-4111-8111-111111111111"

PROTECTED = [
    ("get", "/api/v1/analyses"),
    ("get", "/api/v1/analysis/" + JOB_ID),
    ("get", "/api/v1/analyze-apk/" + JOB_ID),
    ("post", "/api/v1/analyze-apk/" + JOB_ID + "/cancel"),
    ("post", "/api/v1/analyze-apk"),
    ("post", "/api/v1/analyze"),
    ("get", "/api/v1/workers/health"),
    ("get", "/api/v1/files/" + JOB_ID + "/a.png"),
    ("get", "/api/v1/analyze-apk/" + JOB_ID + "/ui"),
    ("get", "/api/v1/analyze-apk/" + JOB_ID + "/intervention/x/screenshot"),
    ("post", "/api/v1/analyze-apk/" + JOB_ID + "/intervention/x/continue"),
]


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_protected_routes_require_a_token(anon_client: TestClient, method: str, path: str) -> None:
    response = getattr(anon_client, method)(path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_health_stays_public(anon_client: TestClient) -> None:
    assert anon_client.get("/api/v1/health").status_code == 200


def test_job_is_only_visible_to_its_owner(client: TestClient, as_user) -> None:
    get_job_store().create(JobRecord(id=JOB_ID, user_id=USER_A.id, file_name="a.apk"))

    assert client.get(f"/api/v1/analyze-apk/{JOB_ID}").status_code == 200

    as_user(USER_B)
    assert client.get(f"/api/v1/analyze-apk/{JOB_ID}").status_code == 404
    assert client.post(f"/api/v1/analyze-apk/{JOB_ID}/cancel").status_code == 404
    assert client.get(f"/api/v1/analyze-apk/{JOB_ID}/ui").status_code == 404
    assert client.get(f"/api/v1/files/{JOB_ID}/a.png").status_code == 404


def test_job_without_owner_is_hidden_from_everyone(client: TestClient) -> None:
    get_job_store().create(JobRecord(id="22222222-2222-4222-8222-222222222222", user_id=None))
    assert client.get("/api/v1/analyze-apk/22222222-2222-4222-8222-222222222222").status_code == 404
