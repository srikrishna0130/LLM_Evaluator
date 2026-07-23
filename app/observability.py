import logging
import sys

from pythonjsonlogger.json import JsonFormatter


def configure_logging(level: str, environment: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    if environment.lower() == "production":
        handler.setFormatter(
            JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s: %(message)s"
            )
        )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

