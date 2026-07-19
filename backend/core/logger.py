"""
Logging configuration for UBQN.

Replaces print() with structured Python logging.
Usage:
    from src.backend.core.logger import get_logger
    logger = get_logger(__name__)
    logger.info("cam1: OK (tcp|h264|hw)")
"""

from __future__ import annotations

import logging
import sys

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_CONFIGURED = False


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logger. Call once at program start."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Get a named logger. Auto-configures logging if not yet done."""
    setup_logging()
    return logging.getLogger(name)
