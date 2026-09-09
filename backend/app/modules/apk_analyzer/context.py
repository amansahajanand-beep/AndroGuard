from __future__ import annotations

import logging
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element

from app.core.errors import AppError
from app.modules.apk_analyzer.aapt import dump_badging

logger = logging.getLogger(__name__)


@dataclass
class ApkContext:
    path: Path
    file_name: str
    file_size: int
    sha256: str
    job_id: str
    apk: Any
    manifest_xml: Element
    zip_names: list[str]
    aapt: dict | None = None
    warnings: list[str] = field(default_factory=list)


def _load_apk_class():
    try:
        from androguard.core.apk import APK

        return APK
    except ImportError:  # pragma: no cover
        from androguard.core.bytecodes.apk import APK

        return APK


def _validate_zip(path: Path) -> list[str]:
    if path.stat().st_size < 4:
        raise AppError("INVALID_FILE", "The uploaded file is empty.")
    header = path.read_bytes()[:4]
    if header[:2] != b"PK":
        raise AppError("INVALID_APK", "The uploaded file is not a valid Android APK.")
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
    except AppError:
        raise
    except zipfile.BadZipFile as exc:
        raise AppError("CORRUPT_APK", "The uploaded APK appears to be corrupted.") from exc
    except Exception as exc:
        raise AppError("CORRUPT_APK", "The uploaded APK could not be read as a ZIP archive.") from exc

    lowered = {name.lower() for name in names}
    if "bundleconfig.pb" in lowered or "base/manifest/androidmanifest.xml" in lowered:
        raise AppError(
            "UNSUPPORTED_APK",
            "Android App Bundles (.aab) and split packages are not supported.",
        )
    if "AndroidManifest.xml" not in names:
        raise AppError("INVALID_APK", "The uploaded file is not a valid Android APK.")
    return names


def open_apk(
    path: Path,
    *,
    file_name: str,
    file_size: int,
    sha256: str,
    job_id: str,
) -> ApkContext:
    zip_names = _validate_zip(path)
    apk_cls = _load_apk_class()
    try:
        apk = apk_cls(str(path))
    except AppError:
        raise
    except Exception as exc:
        logger.warning("Androguard failed to parse APK: %s", type(exc).__name__)
        raise AppError("CORRUPT_APK", "The APK could not be parsed.") from exc

    try:
        manifest_xml = apk.get_android_manifest_xml()
    except Exception as exc:
        raise AppError("MANIFEST_INVALID", "The Android manifest could not be parsed.") from exc

    if manifest_xml is None:
        raise AppError("MANIFEST_INVALID", "The Android manifest could not be parsed.")

    aapt = dump_badging(path)
    warnings: list[str] = []
    if aapt is None:
        warnings.append("aapt is unavailable; using Androguard-only metadata.")

    return ApkContext(
        path=path,
        file_name=file_name,
        file_size=file_size,
        sha256=sha256,
        job_id=job_id,
        apk=apk,
        manifest_xml=manifest_xml,
        zip_names=zip_names,
        aapt=aapt,
        warnings=warnings,
    )
