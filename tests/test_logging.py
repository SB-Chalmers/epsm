# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Observable logging controls, file records and host application isolation."""

import json
import logging

import pytest

from epsm.logging import configure_logging, reset_logging


@pytest.fixture(autouse=True)
def restore_logging():
    yield
    reset_logging()


def emit(level=logging.INFO, message="Prepared building", **fields):
    logging.getLogger("epsm_core.geometry").log(
        level,
        message,
        extra={
            "epsm_event": "geometry.prepared",
            "epsm_context": {"building_id": "B42"},
            "epsm_details": {"duration_s": 0.25},
            **fields,
        },
    )


def records(path):
    return [
        json.loads(line)
        for line in (path / "logs/study.jsonl").read_text().splitlines()
    ]


def test_info_console_debug_file_and_context(tmp_path, capsys):
    configure_logging(directory=tmp_path)
    emit(logging.DEBUG, "Converted surfaces")
    emit()
    console = capsys.readouterr().err
    assert "Converted surfaces" not in console
    assert all(
        part in console for part in ("INFO", "epsm_core.geometry", "B42", "0.25")
    )
    lines = records(tmp_path)
    assert [line["level"] for line in lines] == ["DEBUG", "INFO"]
    assert lines[0]["schema_version"] == 1
    assert lines[0]["timestamp"].endswith("Z")
    assert lines[0]["context"]["building_id"] == "B42"


def test_reconfigure_levels_destinations_and_off(tmp_path, capsys):
    configure_logging(directory=tmp_path / "first")
    configure_logging(directory=tmp_path / "second", console_level="WARNING")
    emit()
    assert not capsys.readouterr().err
    assert len(records(tmp_path / "second")) == 1
    assert records(tmp_path / "first") == []
    configure_logging(enabled=False)
    emit(logging.ERROR)
    assert not capsys.readouterr().err
    assert len(records(tmp_path / "second")) == 1


def test_console_off_keeps_file_and_package_override(tmp_path, capsys):
    configure_logging(console_level="OFF", directory=tmp_path)
    emit()
    assert not capsys.readouterr().err
    assert len(records(tmp_path)) == 1
    configure_logging(console_level="WARNING", package_levels={"epsm_core": "DEBUG"})
    emit(logging.DEBUG)
    assert "Prepared building" in capsys.readouterr().err


def test_reset_preserves_host_and_restores_settings(caplog):
    logger = logging.getLogger("epsm_core")
    original = logger.level, logger.propagate, logger.disabled
    configure_logging()
    reset_logging()
    assert (logger.level, logger.propagate, logger.disabled) == original
    with caplog.at_level(logging.INFO):
        emit()
        logging.getLogger("unrelated").info("host message")
    assert "Prepared building" in caplog.text and "host message" in caplog.text


def test_conflict_and_bad_configuration_leave_previous_setup(tmp_path, capsys):
    configure_logging(directory=tmp_path)
    with pytest.raises(ValueError):
        configure_logging(console_level="NOT_A_LEVEL")
    with pytest.raises((TypeError, ValueError)):
        configure_logging(package_levels={"epsm_workflows": "DEBUG"})
    target = logging.getLogger("epsm_rc.nested")
    handler = logging.StreamHandler()
    target.addHandler(handler)
    try:
        with pytest.raises(ValueError, match="epsm_rc.nested"):
            configure_logging()
    finally:
        target.removeHandler(handler)
        handler.close()
    emit()
    assert len(records(tmp_path)) == 1
    assert "Prepared building" in capsys.readouterr().err


def test_third_party_fields_and_exception_redaction(tmp_path):
    configure_logging(directory=tmp_path, console_level="OFF")
    logging.getLogger("epsm_core.vendor").warning("vendor event")
    try:
        raise ValueError(
            "postgresql://owner:secret@localhost/db?token=sentinel_credential"
        )
    except ValueError:
        logging.getLogger("epsm").exception("Calculation failed")
    lines = records(tmp_path)
    assert lines[0]["event"] == "python.log"
    assert lines[1]["exception"]["type"] == "ValueError"
    text = (tmp_path / "logs/study.jsonl").read_text()
    assert "secret" not in text and "sentinel_credential" not in text


@pytest.mark.parametrize("value", [float("nan"), float("inf"), object()])
def test_json_formatter_rejects_unsupported_details(value):
    from epsm.logging import JsonFormatter

    record = logging.LogRecord("epsm", logging.INFO, __file__, 1, "event", (), None)
    record.epsm_details = {"value": value}
    with pytest.raises((TypeError, ValueError)):
        JsonFormatter().format(record)


def test_invalid_file_does_not_replace_working_setup(tmp_path, capsys):
    configure_logging()
    bad = tmp_path / "file"
    bad.write_text("not a directory")
    with pytest.raises(OSError):
        configure_logging(directory=bad)
    emit()
    assert "Prepared building" in capsys.readouterr().err


def test_database_alias_and_console_off_override(capsys):
    configure_logging(console_level="WARNING", package_levels={"epsm_db": "DEBUG"})
    logging.getLogger("sweden_ubem.stock").debug("Hydrated database page")
    assert "Hydrated database page" in capsys.readouterr().err
    configure_logging(console_level="OFF", package_levels={"epsm_db": "DEBUG"})
    logging.getLogger("sweden_ubem.stock").debug("Must stay quiet")
    assert not capsys.readouterr().err
