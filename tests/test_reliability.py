import json
import time
from types import SimpleNamespace

import pytest

from speech_tool.models import EventState
from speech_tool.pipeline import Pipeline
from speech_tool.polish import OpencodePolisher, PolishResult, _extract_opencode_text, run_opencode
from speech_tool.store import EventStore, SessionRevisionConflict
from tests.fakes import FakeAsr


def chunk(store, session, text, index):
    event = store.create_from_audio(b"audio" + bytes([index]), "a.wav", 1,
                                    kind="lecture_chunk", session_id=session.id, chunk_index=index)
    store.attach_chunk(session.id, event.id)
    store.write_raw_transcript(event.id, text)
    return event


def test_session_assembly_is_scoped_ordered_and_idempotent(tmp_path):
    store = EventStore(tmp_path)
    a, b = store.create_session(), store.create_session()
    last = chunk(store, a, "second", 1)
    first = chunk(store, a, "first", 0)
    foreign = chunk(store, b, "other course", 0)
    assert store.session_display_text(a.id) == "first\n\nsecond"
    store.patch_session(a.id, text="edited first\n\nsecond", draft_chunk_ids=[first.id, last.id], base_revision=0)
    chunk(store, a, "third", 2)
    for _ in range(3):
        assert store.session_display_text(a.id) == "edited first\n\nsecond\n\nthird"
    with pytest.raises(ValueError):
        store.patch_session(a.id, text="foreign", draft_chunk_ids=[foreign.id])
    with pytest.raises(ValueError):
        store.attach_chunk(a.id, foreign.id)
    with pytest.raises(SessionRevisionConflict):
        store.patch_session(a.id, text="stale", base_revision=0)
    assert "edited first" in store.session_display_text(a.id)
    assert list((tmp_path / "sessions" / a.id).glob("*.history.jsonl"))


def test_no_unrelated_course_memory(tmp_path):
    store = EventStore(tmp_path)
    old = store.create_session(course="Rust")
    chunk(store, old, "ownership", 0)
    current = store.create_session(course="ML")
    assert store.recent_lecture_memory("ML", current.id) == ""
    assert store.recent_lecture_memory("", current.id) == ""
    assert "ownership" in store.recent_lecture_memory("Rust", current.id)


def test_text_runner_denies_tools_and_isolates_cwd(monkeypatch):
    def run(cmd, **kw):
        assert "--dangerously-skip-permissions" not in cmd
        assert "--pure" in cmd and "speech-text" in cmd
        assert "speech-text-" in kw["cwd"]
        assert kw["env"]["XDG_DATA_HOME"].startswith(kw["cwd"])
        assert kw["env"]["XDG_STATE_HOME"].startswith(kw["cwd"])
        config = json.loads(kw["env"]["OPENCODE_CONFIG_CONTENT"])
        assert config["permission"] == {"*": "deny"}
        assert config["agent"]["speech-text"]["tools"] == {"*": False}
        return SimpleNamespace(returncode=0, stdout='{"type":"text","part":{"text":"Clean text."}}', stderr="")
    monkeypatch.setattr("speech_tool.polish.subprocess.run", run)
    assert run_opencode("clean", 3).text == "Clean text."
    assert _extract_opencode_text("saved file successfully") == ""


def test_opencode_classifies_provider_blocks(monkeypatch):
    from speech_tool.polish import _classify_opencode_failure

    version, detail = _classify_opencode_failure(
        '{"type":"error","error":{"name":"APIError","data":{"message":"OpenCode\'s free tier can only be used from within OpenCode"}}}',
        "",
    )
    assert version == "provider_unavailable"
    assert "unavailable" in detail.lower()
    version, detail = _classify_opencode_failure("", "Unknown: FileSystem.open (/tmp/opencode.log)")
    assert version == "provider_unavailable"


def test_polish_cooldown_skips_provider_calls(tmp_path):
    store = EventStore(tmp_path)
    event = store.create_from_audio(b"audio", "a.wav", 1)
    store.write_raw_transcript(event.id, "raw")
    store.update_event(event.id, lambda e: (setattr(e, "asr_status", "completed"), setattr(e, "transcript_revision", 1)))
    calls = []

    class Counting:
        def polish(self, *a, **kw):
            calls.append(1)
            return PolishResult("raw", "test", "provider_unavailable", "provider down")

    pipe = Pipeline(store, asr=FakeAsr(), polisher=Counting(), auto_start=False)
    pipe._polish_fail_streak = 3
    pipe._polish_cooldown_until = time.monotonic() + 60
    pipe._polish_provider_detail = "provider down"
    pipe._run_polish(event.id, 1)
    assert calls == []
    done = store.get(event.id)
    assert done.polish_status == "failed"
    assert done.lm_version == "provider_unavailable"
    assert "provider down" in (done.last_error or "")


def test_noise_transcript_skips_provider_and_keeps_cooldown(tmp_path):
    store = EventStore(tmp_path)
    event = store.create_from_audio(b"audio", "a.wav", 30)
    store.write_raw_transcript(event.id, "ව" * 200)
    store.update_event(event.id, lambda e: (
        setattr(e, "asr_status", "completed"),
        setattr(e, "transcript_revision", 1),
    ))
    calls = []

    class Counting:
        def polish(self, *args, **kwargs):
            calls.append(1)
            return PolishResult("spoken", "test", "provider_unavailable", "provider down")

    pipe = Pipeline(store, asr=FakeAsr(), polisher=Counting(), auto_start=False)
    pipe._polish_cooldown_until = time.monotonic() + 60
    pipe._run_polish(event.id, 1)
    assert calls == []
    done = store.get(event.id)
    assert done.polish_status == "completed"
    assert done.lm_version == "noise"
    assert done.last_error is None
    pipe.retry_polish(event.id)
    assert calls == []
    assert pipe._polish_cooldown_until > time.monotonic()


def test_silent_transcript_skips_provider_during_cooldown(tmp_path):
    store = EventStore(tmp_path)
    event = store.create_from_audio(b"audio", "a.wav", 1)
    store.write_raw_transcript(event.id, "   ")
    store.update_event(event.id, lambda e: (
        setattr(e, "asr_status", "completed"),
        setattr(e, "transcript_revision", 1),
    ))
    calls = []

    class Counting:
        def polish(self, *args, **kwargs):
            calls.append(1)
            return PolishResult("spoken", "test", "provider_unavailable", "provider down")

    pipe = Pipeline(store, asr=FakeAsr(), polisher=Counting(), auto_start=False)
    pipe._polish_cooldown_until = time.monotonic() + 60
    pipe._polish_provider_detail = "provider down"
    pipe._run_polish(event.id, 1)
    assert calls == []
    done = store.get(event.id)
    assert done.polish_status == "completed"
    assert done.lm_version == "no_speech"
    assert done.polished_revision == 1
    assert done.last_error is None


def _completed_note_turn(store, note, raw, index, duration):
    event = store.create_from_audio(
        b"audio" + bytes([index]),
        "turn.webm",
        duration,
        kind="note_turn",
        note_id=note.id,
        turn_index=index,
    )
    store.attach_turn(note.id, event.id)
    store.write_raw_transcript(event.id, raw)
    store.update_event(event.id, lambda item: (
        setattr(item, "asr_status", "completed"),
        setattr(item, "transcript_revision", 1),
        setattr(item, "polish_status", "completed"),
        setattr(item, "polished_revision", 1),
    ))
    return event


def test_note_open_and_restart_leave_noise_and_silence_out_of_the_draft(tmp_path):
    store = EventStore(tmp_path)
    speech = "A synthetic sentence about buffers and queues."
    noise = "ව" * 200
    note = store.create_note("Synthetic note")
    spoken = _completed_note_turn(store, note, speech, 0, 5)
    noisy = _completed_note_turn(store, note, noise, 1, 30)
    silent = _completed_note_turn(store, note, "   ", 2, 4)
    assert store.read_note_final(note.id)[0] == ""

    pipe = Pipeline(store, asr=FakeAsr(), polisher=SimpleNamespace(polish=lambda *a, **k: None), auto_start=False)
    pipe.recover_and_resume()
    restarted, _revision = store.read_note_final(note.id)
    assert restarted == speech
    saved = store.get_note(note.id)
    assert spoken.id in saved.merged_turn_ids
    assert noisy.id not in saved.merged_turn_ids
    assert silent.id not in saved.merged_turn_ids
    assert noise in store.read_raw_transcript(noisy.id)
    pipe.recover_and_resume()
    assert store.read_note_final(note.id)[0] == speech

    # A note that has no draft file yet is filled from rounds the same way.
    legacy = store.create_note("Legacy note")
    legacy_spoken = _completed_note_turn(store, legacy, speech, 0, 5)
    legacy_noise = _completed_note_turn(store, legacy, noise, 1, 30)
    _completed_note_turn(store, legacy, "   ", 2, 4)
    store.note_final_path(legacy.id).unlink()
    opened, _revision = store.read_note_final(legacy.id)
    assert opened == speech
    saved = store.get_note(legacy.id)
    assert legacy_spoken.id in saved.merged_turn_ids
    assert legacy_noise.id not in saved.merged_turn_ids
    assert noise in store.read_raw_transcript(legacy_noise.id)


def test_empty_input_never_calls_model(monkeypatch):
    monkeypatch.setattr("speech_tool.polish.run_opencode", lambda *a: pytest.fail("model called"))
    assert OpencodePolisher().polish("  ").version == "no_speech"


def test_timeout_is_failure_without_fake_polished_file(tmp_path):
    store = EventStore(tmp_path)
    event = store.create_from_audio(b"audio", "a.wav", 1)
    store.write_raw_transcript(event.id, "raw")
    store.update_event(event.id, lambda e: (setattr(e, "asr_status", "completed"), setattr(e, "transcript_revision", 1)))
    polisher = SimpleNamespace(polish=lambda *a, **kw: PolishResult("raw", "test", "timeout"))
    pipe = Pipeline(store, asr=FakeAsr(), polisher=polisher, auto_start=False)
    pipe._run_polish(event.id, 1)
    assert store.get(event.id).state == EventState.POLISHING_FAILED
    assert store.read_raw_transcript(event.id) == "raw"
    assert not store.read_polished_transcript(event.id)


def test_capture_retry_is_idempotent(tmp_path, monkeypatch):
    store = EventStore(tmp_path)
    session = store.create_session()
    pipe = Pipeline(store, asr=FakeAsr(), auto_start=False)
    monkeypatch.setattr("speech_tool.pipeline.ffprobe_duration", lambda _: 1)
    monkeypatch.setattr(pipe, "enqueue_asr", lambda _: None)
    args = dict(audio_bytes=b"bytes", filename="a.webm", tmp_path=tmp_path / "a.webm", session_id=session.id, chunk_index=0, capture_id="capture-1")
    one = pipe.ingest_audio(**args)
    assert pipe.ingest_audio(**args) == one
    assert store.get_session(session.id).chunk_ids == [one]
    with pytest.raises(ValueError):
        pipe.ingest_audio(**{**args, "audio_bytes": b"different"})
