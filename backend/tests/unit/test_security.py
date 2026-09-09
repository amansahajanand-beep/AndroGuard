from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_hash_is_not_the_plaintext() -> None:
    hashed = hash_password("sup3r-secret")
    assert hashed != "sup3r-secret"
    assert hashed.startswith("$2b$")


def test_verify_accepts_correct_password() -> None:
    assert verify_password("sup3r-secret", hash_password("sup3r-secret")) is True


def test_verify_rejects_wrong_password() -> None:
    assert verify_password("wrong-password", hash_password("sup3r-secret")) is False


def test_verify_rejects_malformed_hash() -> None:
    assert verify_password("sup3r-secret", "not-a-bcrypt-hash") is False


def test_same_password_hashes_differently() -> None:
    assert hash_password("sup3r-secret") != hash_password("sup3r-secret")


def test_token_round_trip_carries_subject() -> None:
    token, expires_in = create_access_token("user-123")
    assert expires_in > 0
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "user-123"


def test_tampered_token_is_rejected() -> None:
    token, _ = create_access_token("user-123")
    assert decode_access_token(token + "x") is None
