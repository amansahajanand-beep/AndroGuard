from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.core.errors import AppError
from app.modules.activities import extract_activities
from app.modules.apk_analyzer import open_apk
from app.modules.dex import extract_code_analysis
from app.modules.dex.extract import empty_code_analysis
from app.modules.manifest import extract_manifest
from app.modules.metadata import extract_metadata
from app.modules.permissions import extract_permissions
from app.modules.screenshots import extract_screenshots
from app.modules.sdk import extract_sdk
from app.modules.services import extract_services
from app.schemas.analysis import AnalysisData, AnalysisResponse, AppSubmission
from app.storage.local import LocalTempStorage

logger = logging.getLogger(__name__)


def analyze_apk(
    path: Path,
    *,
    file_name: str,
    file_size: int,
    sha256: str,
    job_id: str,
    storage: LocalTempStorage,
    submission: AppSubmission | None = None,
) -> AnalysisResponse:
    started = time.perf_counter()
    ctx = open_apk(
        path,
        file_name=file_name,
        file_size=file_size,
        sha256=sha256,
        job_id=job_id,
    )
    try:
        manifest = extract_manifest(ctx)
        sdk = extract_sdk(ctx)
        permissions = extract_permissions(ctx)
        metadata = extract_metadata(ctx)
        activities = extract_activities(ctx, sdk.get("target_sdk"))
        services = extract_services(ctx, sdk.get("target_sdk"))
        screenshots = extract_screenshots(ctx, storage)
        try:
            code_analysis = extract_code_analysis(
                ctx,
                permission_names=[item.get("name") for item in permissions if item.get("name")],
            )
        except Exception:
            logger.exception("DEX code analysis failed for job %s", job_id)
            ctx.warnings.append("DEX code analysis failed; code_analysis is empty.")
            code_analysis = empty_code_analysis()
    except AppError:
        raise
    except Exception as exc:
        logger.exception("Analyzer failed for job %s", job_id)
        raise AppError(
            "ANALYZER_ERROR",
            "An internal analyzer error occurred.",
            http_status=500,
        ) from exc

    duration_ms = int((time.perf_counter() - started) * 1000)
    analyzed_at = datetime.now(timezone.utc).isoformat()
    data = AnalysisData.model_validate(
        {
            "apk": {
                "file_name": file_name,
                "file_size": file_size,
                "sha256": sha256,
                "package_name": manifest.get("package"),
                "version_name": manifest.get("version_name"),
                "version_code": manifest.get("version_code"),
            },
            "submission": (submission or AppSubmission()).model_dump(),
            "manifest": manifest,
            "permissions": permissions,
            "metadata": metadata,
            "sdk": sdk,
            "activities": activities,
            "services": services,
            "screenshots": screenshots,
            "code_analysis": code_analysis,
            "analysis": {
                "id": job_id,
                "status": "completed",
                "analyzed_at": analyzed_at,
                "analyzer_version": settings.analyzer_version,
                "duration_ms": duration_ms,
                "warnings": ctx.warnings,
                "persisted": False,
            },
        }
    )
    return AnalysisResponse(
        schema_version=settings.schema_version,
        status="completed",
        data=data,
    )
