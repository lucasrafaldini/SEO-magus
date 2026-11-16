"""
Logging for SEO-Magus.

Every module logs through `get_logger(__name__)`, which maps the module path to
the "seo_magus" logger hierarchy (src.engines.link_graph -> seo_magus.engines.link_graph),
so all project logs can be filtered or silenced with one logger name.

Library code never configures handlers; entry points (the CLI) call
`configure_logging()`. Levels used across the project:

  DEBUG    every decision: classifier calls, per-pair gate outcomes, anchor choices, iterations
  INFO     workflow milestones: config loaded, run started/finished, counts, files written
  WARNING  degraded operation: API fallback to simulation, networkx fallback, taxonomy issues
  ERROR    failures that abort a step

The level can also be set with the SEO_MAGUS_LOG_LEVEL environment variable.
"""

import logging
import os
import sys
from pathlib import Path
from typing import Optional, Union

ROOT_LOGGER_NAME = "seo_magus"
LOG_LEVEL_ENV = "SEO_MAGUS_LOG_LEVEL"
DEFAULT_LEVEL = "WARNING"
LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
DATE_FORMAT = "%H:%M:%S"

logging.getLogger(ROOT_LOGGER_NAME).addHandler(logging.NullHandler())

_HANDLER_MARK = "_seo_magus_handler"


def get_logger(module_name: str) -> logging.Logger:
    """Project logger for a module (pass __name__)."""
    if module_name.startswith("src."):
        module_name = module_name[len("src."):]
    elif module_name == "__main__":
        module_name = "cli"
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{module_name}")


def resolve_level(level: Optional[Union[str, int]] = None) -> int:
    """Explicit level > SEO_MAGUS_LOG_LEVEL > WARNING. Accepts names or numbers."""
    if level is None:
        level = os.environ.get(LOG_LEVEL_ENV) or DEFAULT_LEVEL
    if isinstance(level, int):
        return level
    value = logging.getLevelName(str(level).strip().upper())
    if not isinstance(value, int):
        raise ValueError(f"Unknown log level {level!r}; use DEBUG, INFO, WARNING or ERROR")
    return value


def configure_logging(
    level: Optional[Union[str, int]] = None,
    log_file: Optional[Union[str, Path]] = None,
    stream=None,
) -> logging.Logger:
    """
    Send project logs (and Python warnings) to stderr and optionally a file.
    Safe to call repeatedly: handlers installed by a previous call are replaced.
    """
    root = logging.getLogger(ROOT_LOGGER_NAME)
    root.setLevel(resolve_level(level))
    for handler in [h for h in root.handlers if getattr(h, _HANDLER_MARK, False)]:
        root.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    handlers = [logging.StreamHandler(stream or sys.stderr)]
    if log_file is not None:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    for handler in handlers:
        handler.setFormatter(formatter)
        setattr(handler, _HANDLER_MARK, True)
        root.addHandler(handler)

    # warnings.warn(...) (TaxonomyWarning, ConvergenceWarning, ...) -> the same log stream
    logging.captureWarnings(True)
    warnings_logger = logging.getLogger("py.warnings")
    for handler in [h for h in warnings_logger.handlers if getattr(h, _HANDLER_MARK, False)]:
        warnings_logger.removeHandler(handler)
    for handler in handlers:
        warnings_logger.addHandler(handler)
    warnings_logger.propagate = False
    return root
