"""Suggest lecture course/title from the local macOS Calendar (EventKit).

No Google OAuth. Event titles stay on-device; this module never writes calendar
payloads into the git workspace.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
HELPER_NAMES = ("calendar-current",)


def _candidate_helpers() -> list[Path]:
    env = os.environ.get("SPEECH_TOOL_CALENDAR_HELPER", "").strip()
    if env:
        # Explicit override (tests / custom install): do not fall through.
        return [Path(env)]
    runtime = Path.home() / "Library" / "Application Support" / "SpeechTool" / "runtime" / "bin"
    return [runtime / "calendar-current", ROOT / "scripts" / "calendar-current"]


def helper_path() -> Path | None:
    for path in _candidate_helpers():
        if path.is_file() and os.access(path, os.X_OK):
            return path
    return None


def _lecture_stamp(now: datetime | None = None) -> str:
    stamp = now or datetime.now().astimezone()
    return stamp.strftime("%b %-d, %I:%M %p").replace(" 0", " ").lstrip()


def empty_suggestion(*, detail: str, authorized: bool = False) -> dict[str, Any]:
    return {
        "ok": False,
        "authorized": authorized,
        "course": None,
        "title": _lecture_stamp(),
        "event_title": None,
        "events": [],
        "detail": detail,
        "source": "local_calendar",
    }


def suggest_from_calendar(
    *,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
    timeout: float = 8.0,
) -> dict[str, Any]:
    """Return a course/title suggestion from the overlapping Calendar event."""
    run = runner or subprocess.run
    helper = helper_path()
    if helper is None:
        return empty_suggestion(detail="calendar_helper_missing")
    try:
        completed = run(
            [str(helper)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return empty_suggestion(detail="calendar_helper_timeout")
    except OSError as exc:
        return empty_suggestion(detail=f"calendar_helper_os_error:{exc}")
    raw = (completed.stdout or "").strip()
    if completed.returncode != 0 and not raw:
        err = (completed.stderr or "").strip()[:200]
        return empty_suggestion(detail=err or f"calendar_helper_exit_{completed.returncode}")
    try:
        payload = json.loads(raw.splitlines()[-1])
    except json.JSONDecodeError:
        return empty_suggestion(detail="calendar_helper_bad_json")
    if not isinstance(payload, dict):
        return empty_suggestion(detail="calendar_helper_bad_payload")
    course = payload.get("course") or payload.get("event_title")
    if isinstance(course, str):
        course = course.strip() or None
    else:
        course = None
    title = payload.get("title")
    if not isinstance(title, str) or not title.strip():
        title = _lecture_stamp()
    events = payload.get("events") if isinstance(payload.get("events"), list) else []
    authorized = bool(payload.get("authorized"))
    ok = bool(payload.get("ok")) and authorized
    detail = payload.get("detail")
    if ok and course is None and detail is None:
        detail = "no_overlapping_event"
    return {
        "ok": bool(ok and course),
        "authorized": authorized,
        "course": course,
        "title": title.strip(),
        "event_title": course,
        "events": events,
        "detail": detail,
        "source": "local_calendar",
    }


def which_helper() -> str | None:
    path = helper_path()
    return str(path) if path else None


def helper_present() -> bool:
    return helper_path() is not None


def ensure_runtime_helper_copied() -> Path | None:
    """Best-effort copy used by install-desktop; safe no-op if missing."""
    src = ROOT / "scripts" / "calendar-current"
    if not src.is_file():
        return None
    dest_dir = Path.home() / "Library" / "Application Support" / "SpeechTool" / "runtime" / "bin"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "calendar-current"
    shutil.copy2(src, dest)
    dest.chmod(0o755)
    return dest
