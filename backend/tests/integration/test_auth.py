from fastapi.testclient import TestClient

VALID_SIGNUP = {
    "full_name": "Aman Chauhan",
    "company_name": "AndroGuard Labs",
    "email": "aman@example.com",
    "password": "sup3r-secret-pass",
}


def test_signup_without_database(client: TestClient) -> None:
    response = client.post("/api/v1/auth/signup", json=VALID_SIGNUP)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"


def test_login_without_database(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "aman@example.com", "password": "sup3r-secret-pass"},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"


def test_signup_rejects_invalid_email(client: TestClient) -> None:
    response = client.post("/api/v1/auth/signup", json={**VALID_SIGNUP, "email": "not-an-email"})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert [item["field"] for item in body["error"]["details"]] == ["email"]


def test_signup_rejects_short_password(client: TestClient) -> None:
    response = client.post("/api/v1/auth/signup", json={**VALID_SIGNUP, "password": "short"})
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "password"


def test_signup_rejects_blank_full_name(client: TestClient) -> None:
    response = client.post("/api/v1/auth/signup", json={**VALID_SIGNUP, "full_name": "   "})
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "full_name"


def test_login_requires_password(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={"email": "aman@example.com"})
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "password"


def test_me_without_token_is_unauthorized(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_me_with_garbage_token_is_unauthorized(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer nonsense"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
