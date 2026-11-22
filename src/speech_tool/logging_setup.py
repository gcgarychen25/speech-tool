"""Process-wide rotating, structured logging for Speech Tool.

Application logs go to ``<data-dir>/runtime/logs/`` so they can rotate
independently of launchd's stdout/stderr capture (``runtime/server.log``
and ``runtime/audio-retention.log``), which remains a backstop for
uncaught prints and third-party output.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

MAIN_LOG_NAME = "speech_tool.log"
ERROR_LOG_NAME = "speech_tool.errors.log"
RETENTION_LOG_NAME = "audio-retention.log"
RETENTION_ERROR_LOG_NAME = "audio-retention.errors.log"

MAIN_MAX_BYTES = 5 * 1024 * 1024
ERROR_MAX_BYTES = 2 * 1024 * 1024
MAIN_BACKUPS = 10
ERROR_BACKUPS = 10

_HANDLER_PREFIX = "speech_tool."
_configured_role: str | None = None

# Token-like values in log text. Patterns are applied to runtime strings only;
# this module must not contain a literal credential that publication checks flag.
_BEARER_RE = re.compile(r"(?i)(bearer\s+)\S+")
_ASSIGNED_SECRET_RE = re.compile(
    r"(?i)(authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"secret|password|passwd|token)([\"']?\s*[:=]\s*)\S+"
)
_SK_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b")
_GITHUB_TOKEN_RE = re.compile(r"\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{20,}\b")
_AWS_KEY_RE = re.compile(r"\bAKIA[A-Z0-9]{16}\b")


def redact(text: str) -> str:
    """Mask token-like values in a log string. Never returns the original secret."""
    if not text:
        return text
    out = _BEARER_RE.sub(r"\1[redacted]", text)
    out = _ASSIGNED_SECRET_RE.sub(r"\1\2[redacted]", out)
    out = _SK_RE.sub("[redacted]", out)
    out = _GITHUB_TOKEN_RE.sub("[redacted]", out)
    out = _AWS_KEY_RE.sub("[redacted]", out)
    return out


class RedactFilter(logging.Filter):
    """Redact secrets in the message, args, and cached traceback before emit."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: redact(v) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    redact(a) if isinstance(a, str) else a for a in record.args
                )
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        fields = getattr(record, "st", None)
        if isinstance(fields, dict):
            record.st = {
                k: redact(v) if isinstance(v, str) else v for k, v in fields.items()
            }
        return True


def format_kv(key: str, value: Any) -> str:
    if value is None:
        return f"{key}=-"
    if isinstance(value, bool):
        rendered = "true" if value else "false"
    elif isinstance(value, int) and not isinstance(value, bool):
        rendered = str(value)
    elif isinstance(value, float):
        rendered = f"{value:.3f}"
    else:
        rendered = str(value)
        if not rendered or any(ch.isspace() or ch in '="\\' for ch in rendered):
            rendered = json.dumps(rendered, ensure_ascii=False)
    return f"{key}={rendered}"


class StructuredFormatter(logging.Formatter):
    """One-line key=value records plus a redacted traceback on exceptions."""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        dt = datetime.fromtimestamp(record.created).astimezone()
        millis = int(record.msecs)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}" + dt.strftime("%z")

    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        parts = [
            self.formatTime(record),
            record.levelname,
            record.name,
        ]
        fields = getattr(record, "st", None)
        if isinstance(fields, dict):
            for key, value in fields.items():
                if value is None or value == "":
                    continue
                parts.append(format_kv(key, value))
        if record.message:
            parts.append(format_kv("msg", record.message))
        text = " ".join(parts)
        if record.exc_info:
            text += "\n" + redact(self.formatException(record.exc_info))
        return text


def logs_dir(root: Path | None = None) -> Path:
    from speech_tool.config import data_dir

    path = (root or data_dir()) / "runtime" / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _attach_handler(
    logger: logging.Logger, handler: logging.Handler, name: str, formatter: logging.Formatter
) -> None:
    handler.name = name
    handler.setFormatter(formatter)
    handler.addFilter(RedactFilter())
    logger.addHandler(handler)


def configure_logging(
    *,
    role: str = "server",
    log_dir: Path | None = None,
    stream: bool = True,
    force: bool = False,
) -> Path:
    """Install rotating handlers on the root logger. Idempotent per role.

    ``log_dir`` is for tests; production uses ``<data-dir>/runtime/logs``.
    """
    global _configured_role
    directory = Path(log_dir) if log_dir is not None else logs_dir()
    directory.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    if _configured_role == role and not force:
        return directory
    for handler in list(root.handlers):
        if handler.name and handler.name.startswith(_HANDLER_PREFIX):
            root.removeHandler(handler)
            handler.close()

    formatter = StructuredFormatter()
    main_name = RETENTION_LOG_NAME if role == "retention" else MAIN_LOG_NAME
    error_name = RETENTION_ERROR_LOG_NAME if role == "retention" else ERROR_LOG_NAME

    main = logging.handlers.RotatingFileHandler(
        directory / main_name,
        maxBytes=MAIN_MAX_BYTES,
        backupCount=MAIN_BACKUPS,
        encoding="utf-8",
    )
    main.setLevel(logging.INFO)
    _attach_handler(root, main, _HANDLER_PREFIX + "main", formatter)

    errors = logging.handlers.RotatingFileHandler(
        directory / error_name,
        maxBytes=ERROR_MAX_BYTES,
        backupCount=ERROR_BACKUPS,
        encoding="utf-8",
    )
    errors.setLevel(logging.ERROR)
    _attach_handler(root, errors, _HANDLER_PREFIX + "errors", formatter)

    if stream:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setLevel(logging.WARNING)
        _attach_handler(root, stream_handler, _HANDLER_PREFIX + "stderr", formatter)

    root.setLevel(logging.INFO)
    # Token-adjacent HTTP client chatter (OAuth URLs, etc.) does not belong at INFO.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    _configured_role = role
    return directory


def log_event(
    logger: logging.Logger,
    level: int,
    msg: str,
    *args: Any,
    exc_info: Any = None,
    **fields: Any,
) -> None:
    """Log ``msg`` with structured key=value fields (stage, event_id, ...)."""
    st = {key: value for key, value in fields.items() if value is not None}
    logger.log(level, msg, *args, exc_info=exc_info, extra={"st": st})


def detect_release_info() -> dict[str, str]:
    """Best-effort release hash and git commit. Never includes secrets or home paths."""
    info: dict[str, str] = {}
    candidates: list[Path] = []

    def consider_src(src: Path) -> None:
        if src.name != "src":
            return
        release = src.parent
        if release.parent.name == "releases":
            info.setdefault("release_id", release.name)
            candidates.append(release / "RELEASE.json")

    for part in os.environ.get("PYTHONPATH", "").split(os.pathsep):
        if part:
            consider_src(Path(part))
    consider_src(Path(__file__).resolve().parent.parent)
    consider_src(Path.cwd() / "src")
    candidates.append(Path.cwd() / "RELEASE.json")

    for path in candidates:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            continue
        if not isinstance(data, dict):
            continue
        for key in ("release_id", "git_commit", "installed_at", "version"):
            value = data.get(key)
            if isinstance(value, str) and value and key not in info:
                info[key] = value
        break

    if "git_commit" not in info:
        commit = _git_commit()
        if commit:
            info["git_commit"] = commit
    info.setdefault("release_id", "dev")
    info.setdefault("git_commit", "unknown")
    return info


def _git_commit() -> str | None:
    starts = [
        Path.cwd(),
        Path(__file__).resolve().parent.parent.parent,
    ]
    seen: set[Path] = set()
    for start in starts:
        if start in seen or not start.exists():
            continue
        seen.add(start)
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=start,
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            sha = result.stdout.strip()
            if re.fullmatch(r"[0-9a-f]{7,40}", sha):
                return sha
    return None


def log_startup(role: str = "server", log_dir: Path | None = None) -> None:
    """Emit one startup record with release, models, and Python version. No secrets."""
    from speech_tool import config

    info = detect_release_info()
    directory = log_dir or logs_dir()
    logger = logging.getLogger("speech_tool")
    log_event(
        logger,
        logging.INFO,
        "service starting",
        stage="server" if role == "server" else "retention",
        release=info.get("release_id"),
        git_commit=info.get("git_commit"),
        python=sys.version.split()[0],
        asr_backend=os.environ.get("SPEECH_TOOL_ASR_BACKEND"),
        asr_model=os.environ.get(
            "SPEECH_TOOL_ASR_MODEL", getattr(config, "DEFAULT_ASR_MODEL", None)
        ),
        asr_dtype=os.environ.get(
            "SPEECH_TOOL_ASR_DTYPE", getattr(config, "DEFAULT_ASR_DTYPE", None)
        ),
        polisher=os.environ.get(
            "SPEECH_TOOL_POLISHER", getattr(config, "DEFAULT_POLISHER", None)
        ),
        opencode_model=os.environ.get(
            "SPEECH_TOOL_OPENCODE_MODEL", getattr(config, "OPENCODE_MODEL", None)
        ),
        polish_timeout_s=getattr(config, "POLISH_TIMEOUT_SECONDS", None),
        lecture_polish_timeout_s=getattr(config, "LECTURE_POLISH_TIMEOUT_SECONDS", None),
        log_dir=str(directory),
        role=role,
        version=info.get("version", "0.1.0"),
    )


__all__ = [
    "MAIN_BACKUPS",
    "MAIN_MAX_BYTES",
    "ERROR_BACKUPS",
    "ERROR_MAX_BYTES",
    "MAIN_LOG_NAME",
    "ERROR_LOG_NAME",
    "RETENTION_LOG_NAME",
    "configure_logging",
    "detect_release_info",
    "format_kv",
    "log_event",
    "log_startup",
    "logs_dir",
    "redact",
]
