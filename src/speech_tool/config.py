from __future__ import annotations

import os
from pathlib import Path


APP_NAME = "SpeechTool"
NOTE_MAX_SECONDS = 600
LECTURE_CHUNK_SECONDS = 300
LECTURE_MAX_SECONDS = int(os.environ.get("SPEECH_TOOL_LECTURE_MAX", "7200"))
MAX_DURATION_SECONDS = NOTE_MAX_SECONDS
DEFAULT_PORT = 8787
DEFAULT_ASR_MODEL = os.environ.get(
    "SPEECH_TOOL_ASR_MODEL", "mlx-community/whisper-small-mlx"
)
DEFAULT_POLISHER = os.environ.get("SPEECH_TOOL_POLISHER", "opencode")
OPENCODE_BIN = os.environ.get("SPEECH_TOOL_OPENCODE_BIN", "opencode")
OPENCODE_MODEL = os.environ.get(
    "SPEECH_TOOL_OPENCODE_MODEL", "opencode/mimo-v2.5-free"
)
POLISH_TIMEOUT_SECONDS = float(os.environ.get("SPEECH_TOOL_POLISH_TIMEOUT", "20"))
LECTURE_POLISH_TIMEOUT_SECONDS = float(
    os.environ.get("SPEECH_TOOL_LECTURE_POLISH_TIMEOUT", "120")
)
POLISH_RETRY_LIMIT = int(os.environ.get("SPEECH_TOOL_POLISH_RETRY", "1"))
QUESTION_TIMEOUT_SECONDS = float(os.environ.get("SPEECH_TOOL_QUESTION_TIMEOUT", "20"))
DEFAULT_BROWSER = os.environ.get("SPEECH_TOOL_BROWSER", "Google Chrome")


def data_dir() -> Path:
    override = os.environ.get("SPEECH_TOOL_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / "Library" / "Application Support" / APP_NAME


def events_dir(root: Path | None = None) -> Path:
    path = (root or data_dir()) / "events"
    path.mkdir(parents=True, exist_ok=True)
    return path


def sessions_dir(root: Path | None = None) -> Path:
    path = (root or data_dir()) / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def notes_dir(root: Path | None = None) -> Path:
    path = (root or data_dir()) / "notes"
    path.mkdir(parents=True, exist_ok=True)
    return path
