from app.modules.permissions.aosp import aosp_protection_level


def test_known_dangerous_and_normal() -> None:
    assert aosp_protection_level("android.permission.CAMERA") == "dangerous"
    assert aosp_protection_level("android.permission.INTERNET") == "normal"


def test_unknown_permission_is_none() -> None:
    assert aosp_protection_level("com.example.UNKNOWN") is None
