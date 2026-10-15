from __future__ import annotations

import logging

from app.core.config import settings
from app.db.repository import persist_analysis, persist_screenshots
from app.db.session import engine
from app.schemas.analysis import AnalysisResponse
from app.storage.images import read_local_screenshots
from app.storage.local import LocalTempStorage
from app.storage.s3 import upload_screenshots

logger = logging.getLogger(__name__)


def publish_static_artifacts(
    job_id: str,
    result: AnalysisResponse,
    storage: LocalTempStorage,
) -> dict[str, bytes]:
    """Upload extracted APK image assets to S3 and persist the analysis.

    Both are best effort: a failure appends a warning to the result instead of
    failing the analysis. Extracted from the /analyze handler so the synchronous
    endpoint and the async job pipeline behave identically.

    Returns the asset bytes that were read from local storage.
    """
    blobs = read_local_screenshots(
        job_id,
        [item.file_name for item in result.data.screenshots],
        storage,
    )
    if settings.s3_enabled and blobs:
        try:
            formats = {item.file_name: item.format for item in result.data.screenshots}
            urls = upload_screenshots(job_id, blobs, formats)
            for item in result.data.screenshots:
                if item.file_name in urls:
                    item.url = urls[item.file_name]
        except Exception:
            logger.exception("Could not upload screenshots for %s to S3", job_id)
            result.data.analysis.warnings.append(
                "Analysis completed but screenshots were not uploaded to S3."
            )
    if engine is not None:
        try:
            persist_analysis(job_id, result)
            persist_screenshots(job_id, result.data.screenshots, blobs)
            result.data.analysis.persisted = True
        except Exception:
            logger.exception("Could not save analysis %s to PostgreSQL", job_id)
            result.data.analysis.warnings.append(
                "Analysis completed but was not saved to the database."
            )
    return blobs
