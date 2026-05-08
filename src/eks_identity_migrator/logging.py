"""Logging setup. Verbosity levels: 0 silent, 1 INFO, 2 DEBUG."""

from __future__ import annotations

import logging

from rich.logging import RichHandler

_INITIALISED = False


def setup_logging(verbosity: int = 0, *, no_color: bool = False) -> None:
    global _INITIALISED
    if _INITIALISED:
        return
    level = logging.WARNING if verbosity == 0 else logging.INFO if verbosity == 1 else logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, markup=False, show_time=verbosity >= 2)],
    )
    if no_color:
        for h in logging.getLogger().handlers:
            if isinstance(h, RichHandler):
                h.console.no_color = True
    _INITIALISED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
