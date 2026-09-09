from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from app.core.config import settings
from app.core.xmlutil import parse_int

logger = logging.getLogger(__name__)

_PACKAGE_NAME = re.compile(r"package:\s*name='([^']+)'")
_VERSION_CODE = re.compile(r"versionCode='([^']*)'")
_VERSION_NAME = re.compile(r"versionName='([^']*)'")
_COMPILE_SDK = re.compile(r"compileSdkVersion='([^']*)'")
_SDK_VERSION = re.compile(r"^sdkVersion:'([^']+)'", re.MULTILINE)
_TARGET_SDK = re.compile(r"^targetSdkVersion:'([^']+)'", re.MULTILINE)
_LABEL = re.compile(r"^application-label:'(.*)'$", re.MULTILINE)
_PERMISSION = re.compile(
    r"^uses-permission(?:-sdk-\d+)?: name='([^']+)'(?: maxSdkVersion='([^']+)')?",
    re.MULTILINE,
)


@lru_cache(maxsize=1)
def find_aapt() -> str | None:
    configured = (settings.aapt_path or "").strip()
    if configured:
        path = Path(configured)
        if path.is_file():
            return str(path)
    for name in ("aapt", "aapt.exe"):
        found = shutil.which(name)
        if found:
            return found
    home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if not home:
        return None
    tools = Path(home) / "build-tools"
    if not tools.is_dir():
        return None
    for version_dir in sorted(tools.iterdir(), reverse=True):
        for exe in ("aapt.exe", "aapt"):
            candidate = version_dir / exe
            if candidate.is_file():
                return str(candidate)
    return None


def aapt_available() -> bool:
    return find_aapt() is not None


def parse_badging(output: str) -> dict:
    package = _first(_PACKAGE_NAME, output)
    version_code = parse_int(_first(_VERSION_CODE, output))
    version_name = _first(_VERSION_NAME, output)
    compile_sdk = parse_int(_first(_COMPILE_SDK, output))
    min_sdk = parse_int(_first(_SDK_VERSION, output))
    target_sdk = parse_int(_first(_TARGET_SDK, output))
    label = _first(_LABEL, output)
    permissions: list[dict] = []
    seen: set[str] = set()
    for match in _PERMISSION.finditer(output):
        name = match.group(1)
        if not name or name in seen:
            continue
        seen.add(name)
        permissions.append({"name": name, "max_sdk_version": parse_int(match.group(2))})
    return {
        "package": package,
        "version_code": version_code,
        "version_name": version_name,
        "compile_sdk": compile_sdk,
        "min_sdk": min_sdk,
        "target_sdk": target_sdk,
        "app_label": label,
        "permissions": permissions,
        "raw": False,
    }


def dump_badging(apk_path: Path) -> dict | None:
    binary = find_aapt()
    if binary is None:
        return None
    try:
        completed = subprocess.run(
            [binary, "dump", "badging", str(apk_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("aapt dump badging failed: %s", type(exc).__name__)
        return None
    if completed.returncode != 0:
        logger.warning("aapt dump badging exited %s", completed.returncode)
        return None
    parsed = parse_badging(completed.stdout or "")
    parsed["raw"] = True
    return parsed


def prefer(aapt_value, other_value, field: str, warnings: list[str]):
    if aapt_value is not None and other_value is not None and str(aapt_value) != str(other_value):
        warnings.append(
            f"{field} mismatch: aapt={aapt_value} androguard={other_value}; using aapt."
        )
    if aapt_value is not None:
        return aapt_value
    return other_value


def _first(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    value = match.group(1)
    return value if value != "" else None
