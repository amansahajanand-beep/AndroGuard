from app.modules.components.exported import resolve_exported


def test_explicit_exported_wins() -> None:
    exported, inferred, warning = resolve_exported(False, True, 35)
    assert exported is False
    assert inferred is False
    assert warning is None


def test_missing_exported_target_31_with_filters() -> None:
    exported, inferred, warning = resolve_exported(None, True, 31)
    assert exported is None
    assert inferred is False
    assert warning is not None


def test_legacy_default_with_filters() -> None:
    exported, inferred, warning = resolve_exported(None, True, 28)
    assert exported is True
    assert inferred is True
    assert warning is None


def test_legacy_default_without_filters() -> None:
    exported, inferred, warning = resolve_exported(None, False, 28)
    assert exported is False
    assert inferred is True
    assert warning is None
