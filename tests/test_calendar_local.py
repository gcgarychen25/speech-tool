from pathlib import Path
import json
import subprocess

from fastapi.testclient import TestClient

from speech_tool.app import create_app
from speech_tool.calendar_local import suggest_from_calendar
from speech_tool.pipeline import Pipeline
from speech_tool.polish import PassthroughPolisher
from speech_tool.store import EventStore
from tests.fakes import FakeAsr


def test_suggest_from_calendar_uses_helper_json(monkeypatch, tmp_path):
    helper = tmp_path / "calendar-current"
    helper.write_text("#!/bin/sh\ncat <<'EOF'\n{\"ok\":true,\"authorized\":true,\"course\":\"RL Meeting\",\"title\":\"Sep 29, 7:00 PM\",\"event_title\":\"RL Meeting\",\"events\":[]}\nEOF\n")
    helper.chmod(0o755)
    monkeypatch.setenv("SPEECH_TOOL_CALENDAR_HELPER", str(helper))
    result = suggest_from_calendar()
    assert result["ok"] is True
    assert result["course"] == "RL Meeting"
    assert result["source"] == "local_calendar"


def test_suggest_from_calendar_missing_helper(monkeypatch):
    monkeypatch.setenv("SPEECH_TOOL_CALENDAR_HELPER", "/tmp/speech-tool-missing-calendar-helper")
    result = suggest_from_calendar()
    assert result["ok"] is False
    assert result["detail"] == "calendar_helper_missing"


def test_calendar_suggest_api(monkeypatch, tmp_path):
    helper = tmp_path / "calendar-current"
    helper.write_text("#!/bin/sh\necho '{\"ok\":true,\"authorized\":true,\"course\":\"System Programming\",\"title\":\"Sep 29, 3:09 PM\",\"events\":[]}'\n")
    helper.chmod(0o755)
    monkeypatch.setenv("SPEECH_TOOL_CALENDAR_HELPER", str(helper))
    store = EventStore(tmp_path / "data")
    pipe = Pipeline(store, asr=FakeAsr(), polisher=PassthroughPolisher(), auto_start=False)
    client = TestClient(create_app(store, pipe))
    health = client.get("/api/health").json()
    assert health["calendar_helper"] is True
    suggest = client.get("/api/calendar/suggest").json()
    assert suggest["course"] == "System Programming"


def test_frontend_calendar_autofill_contract():
    root = Path(__file__).resolve().parents[1]
    html = (root / "web" / "index.html").read_text(encoding="utf-8")
    javascript = (root / "web" / "app.js").read_text(encoding="utf-8")
    start = (root / "scripts" / "start-lecture.sh").read_text(encoding="utf-8")
    assert "applyCalendarSuggestion" in javascript
    assert "/api/calendar/suggest" in javascript
    assert "bootCourse" in javascript
    assert "bootNewLecture" in javascript
    assert "force: Boolean(forceNew)" in javascript
    assert "historyMetaIsSerious" in javascript
    assert "cleanup unfinished" in javascript
    assert "cleanup needs review" not in javascript
    assert "calendar-current" in start
    assert "course=" in start
    assert "app.js?v=33" in html
