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
    # Keep a copy on disk so a run can be diagnosed after the console is gone.
    try:
        if not settings.log_to_file:
            raise RuntimeError("file logging disabled")
        from logging.handlers import RotatingFileHandler

        settings.temp_root.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            settings.temp_root / "backend.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )
        logging.getLogger().addHandler(file_handler)
    except Exception:
        pass
    logging.getLogger("androguard").setLevel(logging.ERROR)
    logging.getLogger("PIL").setLevel(logging.WARNING)
    try:
        from loguru import logger as loguru_logger

        loguru_logger.disable("androguard")
    except Exception:
        pass
