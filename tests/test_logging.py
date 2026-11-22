import io
import logging
import sys
from pathlib import Path

from speech_tool.logging_setup import (
    ERROR_LOG_NAME,
    MAIN_BACKUPS,
    MAIN_LOG_NAME,
    MAIN_MAX_BYTES,
    StructuredFormatter,
    configure_logging,
    detect_release_info,
    log_event,
    log_startup,
    redact,
)


def test_redact_masks_token_like_values():
    bearer = "Bearer " + "Z" * 24
    assigned = "api_key=" + "Y" * 20
    sk = "sk-" + "x" * 24
    github = "ghp_" + "a" * 36
    aws = "AKIA" + "A" * 16
    blob = f"{bearer} {assigned} prefix {sk} {github} {aws} ok"
    cleaned = redact(blob)
    assert "Z" * 24 not in cleaned
    assert "Y" * 20 not in cleaned
    assert sk not in cleaned
    assert github not in cleaned
    assert aws not in cleaned
    assert "[redacted]" in cleaned
    assert "ok" in cleaned
    assert redact("") == ""


def test_formatter_is_key_value_and_includes_extras():
    record = logging.LogRecord(
        name="speech_tool.pipeline",
        level=logging.INFO,
        pathname="pipeline.py",
        lineno=1,
        msg="polish completed",
        args=(),
        exc_info=None,
    )
    record.st = {
        "stage": "polish",
        "event_id": "evt-1",
        "session_id": "sid-1",
        "model": "example-model",
        "elapsed_s": 1.5,
        "result": "ok",
    }
    line = StructuredFormatter().format(record)
    assert " INFO speech_tool.pipeline " in line
    assert "stage=polish" in line
    assert "event_id=evt-1" in line
    assert "session_id=sid-1" in line
    assert "model=example-model" in line
    assert "elapsed_s=1.500" in line
    assert "result=ok" in line
    assert 'msg="polish completed"' in line
    assert "T" in line.split()[0]


def test_configure_logging_writes_rotating_and_error_files(tmp_path, capsys):
    log_dir = tmp_path / "logs"
    configure_logging(role="server", log_dir=log_dir, stream=True, force=True)
    logger = logging.getLogger("speech_tool.tests")
    log_event(logger, logging.INFO, "hello info", stage="server", result="ok")
    log_event(logger, logging.ERROR, "hello error", stage="server", error="boom")
    # Handlers flush on emit for FileHandler by default? RotatingFileHandler may buffer.
    for handler in logging.getLogger().handlers:
        name = getattr(handler, "name", None) or ""
        if name.startswith("speech_tool."):
            handler.flush()
    main = (log_dir / MAIN_LOG_NAME).read_text(encoding="utf-8")
    errors = (log_dir / ERROR_LOG_NAME).read_text(encoding="utf-8")
    assert "msg=" in main and "hello info" in main
    assert "stage=server" in main
    assert "hello error" in main
    assert "hello error" in errors
    assert "hello info" not in errors
    assert MAIN_MAX_BYTES == 5 * 1024 * 1024
    assert MAIN_BACKUPS == 10
    captured = capsys.readouterr()
    # stderr handler is WARNING+, so INFO must not leak there
    assert "hello info" not in captured.err
    assert "hello error" in captured.err


def test_startup_line_has_release_and_models_but_no_secrets(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    monkeypatch.setenv("SPEECH_TOOL_OPENCODE_MODEL", "opencode-go/example-flash")
    monkeypatch.setenv("SPEECH_TOOL_ASR_MODEL", "Qwen/Qwen3-ASR-0.6B")
    configure_logging(role="server", log_dir=log_dir, stream=False, force=True)
    log_startup(role="server", log_dir=log_dir)
    for handler in logging.getLogger().handlers:
        name = getattr(handler, "name", None) or ""
        if name.startswith("speech_tool."):
            handler.flush()
    text = (log_dir / MAIN_LOG_NAME).read_text(encoding="utf-8")
    assert "service starting" in text
    assert "stage=server" in text
    assert "release=" in text
    assert "git_commit=" in text
    assert "python=" in text
    assert "opencode_model=opencode-go/example-flash" in text
    assert "asr_model=" in text
    secret = "sk-" + "x" * 24
    assert secret not in text
    info = detect_release_info()
    assert "release_id" in info
    assert "git_commit" in info


def test_exception_log_includes_traceback(tmp_path):
    log_dir = tmp_path / "logs"
    configure_logging(role="server", log_dir=log_dir, stream=False, force=True)
    logger = logging.getLogger("speech_tool.tests")
    try:
        raise RuntimeError("injected failure")
    except RuntimeError:
        log_event(
            logger,
            logging.ERROR,
            "asr failed",
            stage="asr",
            event_id="evt-2",
            exc_info=True,
        )
    for handler in logging.getLogger().handlers:
        name = getattr(handler, "name", None) or ""
        if name.startswith("speech_tool."):
            handler.flush()
    text = (log_dir / MAIN_LOG_NAME).read_text(encoding="utf-8")
    errors = (log_dir / ERROR_LOG_NAME).read_text(encoding="utf-8")
    assert "asr failed" in text
    assert "Traceback (most recent call last)" in text
    assert "RuntimeError: injected failure" in text
    assert "Traceback (most recent call last)" in errors
