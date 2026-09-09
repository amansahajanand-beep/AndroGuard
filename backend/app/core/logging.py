import logging
import sys

from app.core.config import settings


def setup_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
        force=True,
    )
    logging.getLogger("androguard").setLevel(logging.ERROR)
    logging.getLogger("PIL").setLevel(logging.WARNING)
    try:
        from loguru import logger as loguru_logger

        loguru_logger.disable("androguard")
    except Exception:
        pass
