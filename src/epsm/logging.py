# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Explicit application-owned console and JSONL logging for EPSM packages.

Calling setup changes only the listed package hierarchies. Imports perform no
configuration or file I/O. ``reset_logging`` restores host-managed propagation.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path

_ROOTS = (
    "epsm",
    "epsm_core",
    "epsm_data",
    "epsm_db",
    "sweden_ubem",
    "epsm_rc",
    "epsm_lca",
    "smhi2epw",
    "epsm_studies",
)
_lock = threading.RLock()
_saved = {}
_handlers = []


def _redact(value):
    """Remove credential-bearing URLs and common secret assignments from text."""
    value = re.sub(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s\"'<>]+", "[redacted-url]", value)
    return re.sub(
        r"(?i)\b(password|token|secret|api_key|authorization)\s*[=:]\s*[^\s,;]+",
        r"\1=[redacted]",
        value,
    )


def _clean(value):
    if isinstance(value, str):
        return _redact(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("Log field names must be strings")
            result[key] = (
                "[redacted]"
                if re.search(
                    r"(?i)(password|token|secret|api_key|authorization|database_url)",
                    key,
                )
                else _clean(item)
            )
        return result
    raise TypeError(f"Unsupported log field type: {type(value).__name__}")


class JsonFormatter(logging.Formatter):
    """Serialize handbook schema version 1 without arbitrary object coercion."""

    def format(self, record):
        result = {
            "schema_version": 1,
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "epsm_event", "python.log"),
            "message": _redact(record.getMessage()),
        }
        for source, target in (
            ("epsm_context", "context"),
            ("epsm_details", "details"),
        ):
            value = getattr(record, source, None)
            if value is not None:
                result[target] = _clean(value)
        if record.exc_info:
            result["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": _redact(str(record.exc_info[1])),
                "traceback": _redact(
                    "".join(traceback.format_exception(*record.exc_info))
                ),
            }
        return json.dumps(result, ensure_ascii=False, allow_nan=False)


class ConsoleFormatter(logging.Formatter):
    """Show the active module, identifiers and elapsed duration on one line."""

    def format(self, record):
        context = getattr(record, "epsm_context", None) or {}
        ids = " ".join(
            f"{key}={str(context[key])[:8] if key == 'operation_id' else context[key]}"
            for key in (
                "study_id",
                "building_id",
                "evaluation_id",
                "run_id",
                "operation_id",
            )
            if key in context
        )
        duration = (getattr(record, "epsm_details", None) or {}).get("duration_s")
        suffix = f" ({duration:.3f} s)" if isinstance(duration, (int, float)) else ""
        message = f"{record.levelname:<7} {record.name}"
        if ids:
            message += f" [{ids}]"
        message += f" {record.getMessage()}{suffix}"
        if record.exc_info:
            message += (
                "\n" + "".join(traceback.format_exception(*record.exc_info)).rstrip()
            )
        return _redact(message)


def _level(value):
    if isinstance(value, str):
        if value.upper() == "OFF":
            return logging.CRITICAL + 1
        value = logging.getLevelName(value.upper())
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("Use DEBUG, INFO, WARNING, ERROR, CRITICAL or OFF")
    return value


class _ConsoleLevels(logging.Filter):
    def __init__(self, default, overrides):
        super().__init__()
        self.default = default
        self.overrides = sorted(overrides.items(), key=lambda pair: -len(pair[0]))

    def filter(self, record):
        for name, threshold in self.overrides:
            if record.name == name or record.name.startswith(name + "."):
                return record.levelno >= threshold
        return record.levelno >= self.default


def _included(name):
    return any(name == root or name.startswith(root + ".") for root in _ROOTS)


def configure_logging(
    *,
    console_level="INFO",
    directory=None,
    file_level="DEBUG",
    package_levels=None,
    enabled=True,
):
    """Choose EPSM output; create ``directory/logs/study.jsonl`` only if supplied.

    Console overrides use package/module names; ``epsm_db`` also covers the
    legacy ``sweden_ubem`` namespace. ``enabled=False`` silences both outputs;
    console OFF retains a configured file. Existing foreign handlers cause a
    ValueError before settings change. Reconfiguration closes displaced files.
    """
    console_threshold, file_threshold = _level(console_level), _level(file_level)
    if not isinstance(enabled, bool):
        raise TypeError("enabled must be a boolean")
    overrides = {}
    for name, level in (package_levels or {}).items():
        if not _included(name):
            raise ValueError(f"Logger outside managed packages: {name}")
        overrides[name] = _level(level)
        if name == "epsm_db" or name.startswith("epsm_db."):
            overrides[name.replace("epsm_db", "sweden_ubem", 1)] = _level(level)
    with _lock:
        conflicts = []
        for name, candidate in logging.Logger.manager.loggerDict.copy().items():
            if _included(name) and isinstance(candidate, logging.Logger):
                if any(
                    h not in _handlers and not isinstance(h, logging.NullHandler)
                    for h in candidate.handlers
                ):
                    conflicts.append(name)
        if conflicts:
            raise ValueError(
                "Unmanaged log handlers conflict: " + ", ".join(sorted(conflicts))
            )
        prepared = []
        try:
            if enabled and console_threshold <= logging.CRITICAL:
                handler = logging.StreamHandler()
                handler.setFormatter(ConsoleFormatter())
                handler.addFilter(_ConsoleLevels(console_threshold, overrides))
                prepared.append(handler)
            if enabled and directory is not None and file_threshold <= logging.CRITICAL:
                path = Path(directory) / "logs" / "study.jsonl"
                path.parent.mkdir(parents=True, exist_ok=True)
                handler = logging.FileHandler(path, encoding="utf-8")
                handler.setLevel(file_threshold)
                handler.setFormatter(JsonFormatter())
                prepared.append(handler)
            if not prepared:
                prepared.append(logging.NullHandler())
        except BaseException:
            for handler in prepared:
                handler.close()
            raise
        for name in _ROOTS:
            logger = logging.getLogger(name)
            _saved.setdefault(name, (logger.level, logger.propagate, logger.disabled))
            for handler in _handlers:
                logger.removeHandler(handler)
            logger.setLevel(logging.DEBUG)
            logger.propagate = False
            logger.disabled = False
            for handler in prepared:
                logger.addHandler(handler)
        for handler in _handlers:
            handler.close()
        _handlers[:] = prepared


def reset_logging():
    """Close owned output and restore the host settings saved on first setup."""
    with _lock:
        for name, (level, propagate, disabled) in _saved.items():
            logger = logging.getLogger(name)
            for handler in _handlers:
                logger.removeHandler(handler)
            logger.setLevel(level)
            logger.propagate, logger.disabled = propagate, disabled
        for handler in _handlers:
            handler.close()
        _handlers.clear()
        _saved.clear()
