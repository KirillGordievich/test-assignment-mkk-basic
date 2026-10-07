import logging

from app.config import settings


def setup_logging() -> None:
    logging.basicConfig(
        level=settings.app.log_level.upper(),
        format="%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
