# app/common/logging_cfg.py
import logging, os, sys

def configure_logging(level: str = None):
    lvl = level or os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, lvl, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
