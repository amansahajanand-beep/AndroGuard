from __future__ import annotations

import shutil
from pathlib import Path

from app.core.config import settings


class LocalTempStorage:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or settings.jobs_dir
        self.root.mkdir(parents=True, exist_ok=True)

    def job_dir(self, job_id: str) -> Path:
        path = self.root / job_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def apk_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "input.apk"

    def screenshots_dir(self, job_id: str) -> Path:
        path = self.job_dir(job_id) / "screenshots"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def screenshot_path(self, job_id: str, filename: str) -> Path:
        return self.screenshots_dir(job_id) / filename

    def delete_apk(self, job_id: str) -> None:
        path = self.apk_path(job_id)
        path.unlink(missing_ok=True)

    def delete_job(self, job_id: str) -> None:
        shutil.rmtree(self.job_dir(job_id), ignore_errors=True)
