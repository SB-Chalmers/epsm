# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Package-local standard-library logging helpers; no output on import."""

from __future__ import annotations

import inspect
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from time import monotonic
from uuid import uuid4

_context = ContextVar(__name__ + ".context", default=None)


def current_context():
    """Copy identifiers for an explicit package or thread boundary."""
    return dict(_context.get() or {})


class _ContextLogger(logging.LoggerAdapter):
    """Enrich local module events without configuring handlers or levels."""

    def process(self, message, kwargs):
        """Merge active operation identifiers with explicit fields on this record."""
        extra = dict(kwargs.get("extra") or {})
        extra["epsm_context"] = {**current_context(), **extra.get("epsm_context", {})}
        kwargs["extra"] = extra
        return message, kwargs


def context_logger(name):
    """Get a module logger enriched with this package's operation identifiers."""
    return _ContextLogger(logging.getLogger(name), {})


def bind_context(**identifiers):
    """Add known identifiers to the current operation without changing inputs."""
    context = _context.get()
    if context is not None:
        context.update(identifiers)


def call_with_context(function, *args, log_context=None, **kwargs):
    """Pass context only to an explicitly supported public keyword.

    Signature inspection preserves older collaborator versions. A TypeError
    inside the collaborator is never interpreted as an unsupported keyword.
    """
    parameters = inspect.signature(function).parameters
    if "log_context" in parameters:
        kwargs.setdefault(
            "log_context", current_context() if log_context is None else log_context
        )
    return function(*args, **kwargs)


def operation(event, *, level=logging.INFO, traceback=False):
    """Trace a public operation, preserving results, exceptions and signatures.

    ``log_context`` is an optional keyword-only mapping of scalar identifiers.
    Identifiers never enter physical models or scientific calculation options.
    Generator context is restored between yields so consumers remain isolated.
    """

    def decorate(function):
        """Wrap one operation without changing its public calculation contract."""
        signature = inspect.signature(function)
        logger = logging.getLogger(function.__module__)

        def begin(args, kwargs, supplied):
            """Build an isolated operation context from explicit scalar identifiers."""
            parent = current_context() if supplied is None else dict(supplied)
            if any(
                not isinstance(key, str)
                or not isinstance(value, (str, int, bool, type(None)))
                for key, value in parent.items()
            ):
                raise TypeError("log_context must contain scalar identifiers")
            context = dict(parent)
            if parent.get("operation_id"):
                context["parent_operation_id"] = parent["operation_id"]
            context["operation_id"] = uuid4().hex
            bound = signature.bind(*args, **kwargs)
            for key in ("building_id", "run_id", "study_id", "evaluation_id"):
                if key in bound.arguments and isinstance(
                    bound.arguments[key], (str, int)
                ):
                    context[key] = bound.arguments[key]
            for key in ("building", "spec", "self"):
                value = bound.arguments.get(key)
                identifier = getattr(value, "identifier", None)
                if isinstance(identifier, str):
                    context.setdefault("building_id", identifier)
            if event == "study.protocol.save" and "self" in bound.arguments:
                context.setdefault("study_id", bound.arguments["self"].id)
            selected = {}
            for key in (
                "category",
                "construction_year",
                "archetype_id",
                "state",
                "renovation_state",
                "year",
                "station_id",
                "batch_size",
                "workers",
            ):
                value = bound.arguments.get(key)
                if isinstance(value, (str, int, bool)):
                    selected[key] = value
            for key in ("path", "directory", "output"):
                value = bound.arguments.get(key)
                if isinstance(value, (str, Path)):
                    selected[key] = str(value)
            config = bound.arguments.get("config")
            if config is not None and event == "weather.compile":
                for key in ("year", "station_id", "weather_policy"):
                    value = getattr(config, key, None)
                    if isinstance(value, (str, int, bool)):
                        selected[key] = value
            return context, selected

        def emit(context, suffix, started, *, selected=None, error=None):
            """Emit one lifecycle event with bounded timing and error metadata."""
            details = dict(selected or {})
            if started is not None:
                details["duration_s"] = monotonic() - started
            if error is not None:
                details.update(
                    code=getattr(error, "code", event + ".failed"),
                    error_type=type(error).__name__,
                )
            logger.log(
                logging.ERROR if error is not None else level,
                "%s %s",
                event.replace(".", " "),
                suffix,
                extra={
                    "epsm_event": event + "." + suffix,
                    "epsm_context": context,
                    "epsm_details": details,
                },
                exc_info=traceback and error is not None,
            )

        def summary(result):
            """Describe bounded output identities and counts without storing records."""
            details = {}
            if isinstance(result, Path):
                details["path"] = str(result)
            for name in ("run_id", "dataset_id", "source_version", "rows"):
                value = getattr(result, name, None)
                if isinstance(value, (str, int)):
                    details[name] = value
            if isinstance(result, (list, tuple)):
                details["item_count"] = len(result)
            if isinstance(result, tuple) and result and isinstance(result[0], dict):
                for name, label in (
                    ("Zone", "zone_count"),
                    ("BuildingSurface:Detailed", "surface_count"),
                ):
                    if name in result[0]:
                        details[label] = len(result[0][name])
            return details

        @wraps(function)
        def wrapped(*args, log_context=None, **kwargs):
            """Execute a synchronous operation and always restore the caller context."""
            context, selected = begin(args, kwargs, log_context)
            token = _context.set(context)
            started = monotonic()
            emit(context, "started", None, selected=selected)
            try:
                result = function(*args, **kwargs)
            except Exception as error:
                emit(context, "failed", started, selected=selected, error=error)
                raise
            except BaseException:
                emit(context, "cancelled", started, selected=selected)
                raise
            else:
                selected.update(summary(result))
                emit(context, "completed", started, selected=selected)
                return result
            finally:
                _context.reset(token)

        @wraps(function)
        def generated(*args, log_context=None, **kwargs):
            """Advance a lazy operation and restore context before yielding each item."""
            context, selected = begin(args, kwargs, log_context)
            started = monotonic()
            emit(context, "started", None, selected=selected)
            iterator = function(*args, **kwargs)
            try:
                while True:
                    token = _context.set(context)
                    try:
                        item = next(iterator)
                    except StopIteration:
                        emit(context, "completed", started, selected=selected)
                        return
                    finally:
                        _context.reset(token)
                    yield item
            except Exception as error:
                emit(context, "failed", started, selected=selected, error=error)
                raise
            except BaseException:
                emit(context, "cancelled", started, selected=selected)
                raise
            finally:
                iterator.close()

        result = generated if inspect.isgeneratorfunction(function) else wrapped
        parameters = list(signature.parameters.values())
        index = next(
            (i for i, p in enumerate(parameters) if p.kind == p.VAR_KEYWORD),
            len(parameters),
        )
        parameters.insert(
            index,
            inspect.Parameter(
                "log_context", inspect.Parameter.KEYWORD_ONLY, default=None
            ),
        )
        result.__signature__ = signature.replace(parameters=parameters)
        return result

    return decorate


@contextmanager
def configure_cli(level, namespace):
    """Temporarily configure a CLI entrypoint, restoring an embedding host."""
    threshold = logging.CRITICAL + 1 if level == "OFF" else getattr(logging, level)
    logger = logging.getLogger(namespace)
    original = logger.handlers[:], logger.level, logger.propagate
    if any(not isinstance(handler, logging.NullHandler) for handler in logger.handlers):
        raise ValueError(f"Unmanaged log handler on {namespace}")
    handler = logging.StreamHandler() if level != "OFF" else logging.NullHandler()
    handler.setLevel(threshold)
    handler.setFormatter(logging.Formatter("%(levelname)-7s %(name)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(threshold)
    logger.propagate = False
    try:
        yield
    finally:
        logger.removeHandler(handler)
        handler.close()
        logger.handlers, logger.level, logger.propagate = original
