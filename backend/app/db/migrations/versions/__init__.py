"""Ordered migration registry."""

from __future__ import annotations

from app.db.migrations.versions import v001_phase11_screenshot_persistence as v001

MIGRATIONS = [
    (v001.VERSION, v001.upgrade),
]
