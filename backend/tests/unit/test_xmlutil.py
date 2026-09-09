from app.core.xmlutil import parse_bool, parse_int, resolve_component_name, typed_value


def test_parse_bool() -> None:
    assert parse_bool("true") is True
    assert parse_bool("false") is False
    assert parse_bool(None) is None


def test_parse_int_decimal_and_hex() -> None:
    assert parse_int("23") == 23
    assert parse_int("0x10") == 16
    assert parse_int("nope") is None


def test_resolve_component_name() -> None:
    assert resolve_component_name("com.example", ".MainActivity") == "com.example.MainActivity"
    assert resolve_component_name("com.example", "Other") == "com.example.Other"
    assert resolve_component_name("com.example", "com.example.MainActivity") == "com.example.MainActivity"


def test_typed_value() -> None:
    assert typed_value("true") == (True, "boolean")
    assert typed_value("42") == (42, "integer")
    assert typed_value("@string/app_name") == ("@string/app_name", "resource")
    assert typed_value("hello") == ("hello", "string")
