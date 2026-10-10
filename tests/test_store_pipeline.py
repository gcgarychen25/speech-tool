from __future__ import annotations

import time
import threading

from speech_tool.asr import FailingAsr
from speech_tool.models import EventState
from speech_tool.pipeline import Pipeline
from speech_tool.polish import FailingPolisher, PassthroughPolisher, PolishResult, Polisher
from speech_tool.store import EventStore, sha256_file
from tests.fakes import FakeAsr


class CountingPolisher(Polisher):
    def __init__(self):
        self.n = 0

    def polish(self, raw_text: str, timeout: float | None = None) -> PolishResult:
        self.n += 1
        return PolishResult(text=raw_text.upper(), model="count", version="1")


def wait_state(store: EventStore, event_id: str, state: EventState, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        event = store.get(event_id)
        if event.state == state:
            return event
        time.sleep(0.05)
    raise AssertionError(
        f"timed out waiting for {state}, got {store.get(event_id).state}"
    )


def test_persist_before_processing_and_separate_artifacts(tmp_path):
    store = EventStore(tmp_path)
    audio = b"RIFF" + b"\x00" * 64
    event = store.create_from_audio(audio, "clip.wav", 1.2)
    audio_hash = event.audio_sha256
    assert store.audio_path(event).exists()
    store.write_raw_transcript(event.id, "raw")
    store.write_polished_transcript(event.id, "polished")
    assert store.audio_path(event).read_bytes() == audio
    assert sha256_file(store.audio_path(event)) == audio_hash
    assert store.read_raw_transcript(event.id) == "raw"
    assert store.read_polished_transcript(event.id) == "polished"
    assert store.read_raw_transcript(event.id) != store.read_polished_transcript(
        event.id
    )


def test_asr_failure_keeps_audio(tmp_path):
    store = EventStore(tmp_path)
    event = store.create_from_audio(b"audio-bytes", "clip.wav", 1.0)
    pipe = Pipeline(
        store, asr=FailingAsr(), polisher=PassthroughPolisher(), auto_start=False
    )
    pipe.enqueue_asr(event.id)
    failed = wait_state(store, event.id, EventState.TRANSCRIPTION_FAILED)
    assert store.audio_path(failed).exists()
    assert store.read_raw_transcript(event.id) is None
    pipe.retry_asr(event.id)
    wait_state(store, event.id, EventState.TRANSCRIPTION_FAILED)


def test_polish_failure_keeps_raw(tmp_path):
    store = EventStore(tmp_path)
    event = store.create_from_audio(b"audio-bytes", "clip.wav", 1.0)
    pipe = Pipeline(
        store, asr=FakeAsr(), polisher=FailingPolisher(), auto_start=False
    )
    pipe.enqueue_asr(event.id)
    failed = wait_state(store, event.id, EventState.POLISHING_FAILED)
    assert store.read_raw_transcript(event.id) == "hello world from asr"
    assert store.read_polished_transcript(event.id) is None
    assert store.audio_path(failed).exists()
    pipe.polisher = PassthroughPolisher()
    pipe.retry_polish(event.id)
    done = wait_state(store, event.id, EventState.COMPLETED)
    assert store.read_polished_transcript(done.id) == "hello world from asr"


def test_restart_recovers_inflight(tmp_path):
    store = EventStore(tmp_path)
    event = store.create_from_audio(b"audio-bytes", "clip.wav", 1.0)
    event.asr_status = "running"
    store.save(event)
    recovered = store.interrupt_inflight()
    assert recovered[0].asr_status == "pending"
    pipe = Pipeline(
        store, asr=FakeAsr(), polisher=PassthroughPolisher(), auto_start=True
    )
    done = wait_state(store, event.id, EventState.COMPLETED)
    assert done.asr_status == "completed"


def test_retranscribe_does_not_destroy_audio(tmp_path):
    store = EventStore(tmp_path)
    event = store.create_from_audio(b"keep-me", "clip.wav", 1.0)
    digest = event.audio_sha256
    pipe = Pipeline(
        store, asr=FakeAsr(), polisher=CountingPolisher(), auto_start=False
    )
    pipe.enqueue_asr(event.id)
    wait_state(store, event.id, EventState.COMPLETED)
    pipe.retranscribe(event.id)
    wait_state(store, event.id, EventState.COMPLETED)
    assert sha256_file(store.audio_path(store.get(event.id))) == digest
    assert store.read_raw_transcript(event.id)


class SlowPolisher(Polisher):
    def polish(self, raw_text: str, timeout: float | None = None) -> PolishResult:
        time.sleep(1.2)
        return PolishResult(text=raw_text.upper(), model="slow", version="1")


def test_asr_finishes_without_waiting_for_polish(tmp_path):
    store = EventStore(tmp_path)
    event = store.create_from_audio(b"audio-bytes", "clip.wav", 1.0)
    pipe = Pipeline(
        store, asr=FakeAsr(), polisher=SlowPolisher(), auto_start=False
    )
    started = time.time()
    pipe.enqueue_asr(event.id)
    ready = wait_state(store, event.id, EventState.TRANSCRIBED, timeout=1)
    assert time.time() - started < 0.8
    assert store.read_raw_transcript(ready.id) == "hello world from asr"
    wait_state(store, event.id, EventState.COMPLETED, timeout=3)


class BlockingPolisher(Polisher):
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def polish(self, raw_text: str, timeout: float | None = None) -> PolishResult:
        self.calls += 1
        if self.calls == 1:
            self.started.set()
            self.release.wait(timeout=3)
            return PolishResult(text="stale polish", model="blocking", version="1")
        return PolishResult(text=f"latest: {raw_text}", model="blocking", version="1")


def test_stale_polish_cannot_overwrite_appended_transcript(tmp_path):
    store = EventStore(tmp_path)
    event = store.create_from_audio(b"audio-bytes", "clip.wav", 1.0)
    polisher = BlockingPolisher()
    pipe = Pipeline(store, asr=FakeAsr(), polisher=polisher, auto_start=False)
    pipe.enqueue_asr(event.id)
    assert polisher.started.wait(timeout=2)

    segment = store.add_segment(event.id, b"more-audio", "more.wav")
    pipe._run_append(event.id, segment, 1.0)
    polisher.release.set()

    done = wait_state(store, event.id, EventState.COMPLETED, timeout=5)
    assert done.transcript_revision == 2
    assert done.polished_revision == 2
    assert store.read_polished_transcript(event.id).startswith("latest:")
    assert store.read_polished_transcript(event.id) != "stale polish"


def test_append_preserves_user_draft_until_ui_merges_chunk(tmp_path):
    store = EventStore(tmp_path)
    event = store.create_from_audio(b"audio-bytes", "clip.wav", 1.0)
    pipe = Pipeline(
        store, asr=FakeAsr(), polisher=PassthroughPolisher(), auto_start=False
    )
    pipe.enqueue_asr(event.id)
    wait_state(store, event.id, EventState.COMPLETED)
    revision = store.get(event.id).transcript_revision
    store.write_edited_transcript(
        event.id, "my corrected draft", transcript_revision=revision
    )

    segment = store.add_segment(event.id, b"more-audio", "more.wav")
    pipe._run_append(event.id, segment, 1.0)

    assert store.read_edited_transcript(event.id) == "my corrected draft"
    pending = store.pending_segment_transcripts(event.id)
    assert len(pending) == 1
    assert pending[0]["text"] == "hello world from asr"
    latest = store.get(event.id)
    assert pending[0]["transcript_revision"] == latest.transcript_revision

    store.write_edited_transcript(
        event.id,
        "my corrected draft\n\nhello world from asr",
        transcript_revision=latest.transcript_revision,
    )
    assert store.pending_segment_transcripts(event.id) == []


def test_display_text_never_auto_applies_polish(tmp_path):
    store = EventStore(tmp_path)
    event = store.create_from_audio(b"audio-bytes", "clip.wav", 1.0)
    store.write_raw_transcript(event.id, "raw draft")
    store.write_polished_transcript(event.id, "polished proposal")
    assert store.display_text(event.id) == "raw draft"


def test_legacy_note_migrates_to_single_turn_document(tmp_path):
    store = EventStore(tmp_path)
    event = store.create_from_audio(b"legacy", "legacy.wav", 1.0)
    notes = store.list_notes()
    assert len(notes) == 1
    assert notes[0].id == event.id
    assert notes[0].turn_ids == [event.id]
    migrated = store.get(event.id)
    assert migrated.kind == "note_turn"
    assert migrated.note_id == notes[0].id
    assert migrated.turn_index == 0


def test_note_turn_drafts_do_not_overwrite_baselines(tmp_path):
    store = EventStore(tmp_path)
    note = store.create_note("Working note")
    turn = store.create_from_audio(
        b"audio",
        "turn.wav",
        1.0,
        kind="note_turn",
        note_id=note.id,
        turn_index=0,
    )
    store.attach_turn(note.id, turn.id)
    store.write_raw_transcript(turn.id, "raw baseline")
    store.write_polished_transcript(turn.id, "polished baseline")
    store.write_turn_draft(turn.id, "asr", "edited ASR")
    store.write_turn_draft(turn.id, "polished", "edited polish")

    assert store.read_raw_transcript(turn.id) == "raw baseline"
    assert store.read_polished_transcript(turn.id) == "polished baseline"
    assert store.read_asr_draft(turn.id) == "edited ASR"
    assert store.read_polished_draft(turn.id) == "edited polish"
    assert store.preferred_turn_text(turn.id) == ("polished", "edited polish")

    raw_only = store.create_from_audio(
        b"audio-2",
        "turn-2.wav",
        1.0,
        kind="note_turn",
        note_id=note.id,
        turn_index=1,
    )
    store.attach_turn(note.id, raw_only.id)
    store.write_raw_transcript(raw_only.id, "second raw")
    store.write_turn_draft(raw_only.id, "asr", "second ASR edit")
    assert store.preferred_turn_text(raw_only.id) == ("asr", "second ASR edit")


def test_note_final_append_is_idempotent_and_preserves_concurrent_edit(tmp_path):
    store = EventStore(tmp_path)
    note = store.create_note("Continuous")
    turn = store.create_from_audio(
        b"audio",
        "turn.wav",
        1.0,
        kind="note_turn",
        note_id=note.id,
        turn_index=0,
    )
    store.attach_turn(note.id, turn.id)
    base_text, base_revision = store.read_note_final(note.id)
    assert base_text == ""

    appended, append_revision = store.append_turn_to_note(
        note.id, turn.id, "first ASR"
    )
    assert appended == "first ASR"
    same, same_revision = store.append_turn_to_note(
        note.id, turn.id, "first ASR"
    )
    assert same == appended
    assert same_revision == append_revision

    merged, merged_revision = store.update_note_final(
        note.id,
        base_revision,
        base_text,
        "user typed while recording",
    )
    assert merged == "user typed while recording\n\nfirst ASR"
    assert merged_revision > append_revision


def test_clear_note_final_keeps_rounds_and_later_asr(tmp_path):
    store = EventStore(tmp_path)
    note = store.create_note("Clear me")
    first = store.create_from_audio(
        b"audio",
        "turn.wav",
        1.0,
        kind="note_turn",
        note_id=note.id,
        turn_index=0,
    )
    store.attach_turn(note.id, first.id)
    store.write_raw_transcript(first.id, "raw baseline")
    store.write_polished_transcript(first.id, "polished baseline")
    store.append_turn_to_note(note.id, first.id, "old canonical")
    text, revision = store.read_note_final(note.id)
    cleared, _ = store.update_note_final(note.id, revision, text, "")
    assert cleared == ""
    assert store.get_note(note.id).turn_ids == [first.id]
    assert store.read_raw_transcript(first.id) == "raw baseline"
    assert store.read_polished_transcript(first.id) == "polished baseline"

    later = store.create_from_audio(
        b"audio-2",
        "turn-2.wav",
        1.0,
        kind="note_turn",
        note_id=note.id,
        turn_index=1,
    )
    store.attach_turn(note.id, later.id)
    appended, _ = store.append_turn_to_note(note.id, later.id, "after clear")
    assert appended == "after clear"
    assert store.get_note(note.id).turn_ids == [first.id, later.id]


def test_clear_note_final_keeps_concurrent_asr_append(tmp_path):
    store = EventStore(tmp_path)
    note = store.create_note("Clear race")
    turn = store.create_from_audio(
        b"audio",
        "turn.wav",
        1.0,
        kind="note_turn",
        note_id=note.id,
        turn_index=0,
    )
    store.attach_turn(note.id, turn.id)
    text, revision = store.read_note_final(note.id)
    store.append_turn_to_note(note.id, turn.id, "new ASR")
    merged, _ = store.update_note_final(note.id, revision, text, "")
    assert merged.strip() == "new ASR"


def test_legacy_note_final_seeds_from_existing_user_draft(tmp_path):
    store = EventStore(tmp_path)
    event = store.create_from_audio(b"legacy", "legacy.wav", 1.0)
    store.write_raw_transcript(event.id, "legacy raw")
    store.write_edited_transcript(event.id, "legacy user edit")
    note = store.list_notes()[0]
    text, revision = store.read_note_final(note.id)
    assert text == "legacy user edit"
    assert revision == 1
    assert note.id == event.id


def test_note_copy_uses_canonical_draft(tmp_path):
    store = EventStore(tmp_path)
    note = store.create_note("Copy")
    turn = store.create_from_audio(
        b"audio",
        "turn.wav",
        1.0,
        kind="note_turn",
        note_id=note.id,
        turn_index=0,
    )
    store.attach_turn(note.id, turn.id)
    store.write_raw_transcript(turn.id, "raw")
    store.write_polished_transcript(turn.id, "polished")
    store.write_turn_draft(turn.id, "polished", "polished draft")
    store.append_turn_to_note(note.id, turn.id, "raw")
    text, revision = store.read_note_final(note.id)
    store.update_note_final(note.id, revision, text, "canonical user text")
    copied = store.record_note_copy(note.id)
    assert copied["text"] == "canonical user text"


def test_completed_asr_appends_to_note_on_resume(tmp_path):
    store = EventStore(tmp_path)
    note = store.create_note("Resume")
    turn = store.create_from_audio(
        b"audio",
        "turn.wav",
        1.0,
        kind="note_turn",
        note_id=note.id,
        turn_index=0,
    )
    store.attach_turn(note.id, turn.id)
    store.write_raw_transcript(turn.id, "recovered asr")
    store.update_event(
        turn.id,
        lambda event: (
            setattr(event, "asr_status", "completed"),
            setattr(event, "polish_status", "pending"),
        ),
    )
    text, _ = store.read_note_final(note.id)
    assert text == ""
    Pipeline(store, asr=FakeAsr(), polisher=PassthroughPolisher(), auto_start=True)
    wait_state(store, turn.id, EventState.COMPLETED)
    final, _ = store.read_note_final(note.id)
    assert final == "recovered asr"
    assert store.read_raw_transcript(turn.id) == "recovered asr"


def test_history_order_and_delete(tmp_path):
    store = EventStore(tmp_path)
    a = store.create_from_audio(b"a", "a.wav", 1.0)
    time.sleep(0.01)
    b = store.create_from_audio(b"b", "b.wav", 2.0)
    ids = [e.id for e in store.list_events()]
    assert ids[0] == b.id
    store.delete(a.id)
    assert [e.id for e in store.list_events()] == [b.id]


def test_lecture_session_concat(tmp_path):
    store = EventStore(tmp_path)
    session = store.create_session(course="RL", title="")
    a = store.create_from_audio(
        b"a", "a.wav", 1.0, kind="lecture_chunk", session_id=session.id, chunk_index=0
    )
    b = store.create_from_audio(
        b"b", "b.wav", 1.0, kind="lecture_chunk", session_id=session.id, chunk_index=1
    )
    store.attach_chunk(session.id, a.id)
    store.attach_chunk(session.id, b.id)
    store.write_raw_transcript(a.id, "chunk one")
    store.write_polished_transcript(a.id, "chunk one")
    store.write_raw_transcript(b.id, "chunk two")
    store.write_polished_transcript(b.id, "chunk two")
    assert "chunk one" in store.session_display_text(session.id)
    assert "chunk two" in store.session_display_text(session.id)
    listed = store.list_sessions()
    assert listed[0].id == session.id
    assert listed[0].course == "RL"


def test_listener_notes_stay_off_transcript(tmp_path):
    store = EventStore(tmp_path)
    session = store.create_session(course="RL")
    a = store.create_from_audio(
        b"a", "a.wav", 1.0, kind="lecture_chunk", session_id=session.id, chunk_index=0
    )
    store.attach_chunk(session.id, a.id)
    store.write_raw_transcript(a.id, "lecture words")
    store.write_polished_transcript(a.id, "lecture words")
    store.write_listener_notes(session.id, "[03:12] why does this bound hold?")
    assert store.session_display_text(session.id) == "lecture words"
    assert "bound" in store.read_listener_notes(session.id)


def test_question_drafts_stay_off_transcript_and_use_recent_memory(tmp_path):
    store = EventStore(tmp_path)
    earlier = store.create_session(course="RL", title="yesterday")
    a = store.create_from_audio(
        b"a", "a.wav", 1.0, kind="lecture_chunk", session_id=earlier.id, chunk_index=0
    )
    store.attach_chunk(earlier.id, a.id)
    store.write_raw_transcript(a.id, "mixing time on the chain")
    current = store.create_session(course="RL", title="today")
    b = store.create_from_audio(
        b"b", "b.wav", 1.0, kind="lecture_chunk", session_id=current.id, chunk_index=0
    )
    store.attach_chunk(current.id, b.id)
    store.write_raw_transcript(b.id, "broadcasting aligns from the right")
    store.append_question(
        current.id,
        {"question": "Why does broadcasting align from the right?", "confusion": "shapes"},
    )
    assert store.latest_question(current.id).startswith("Why does broadcasting")
    assert "broadcasting" in store.session_display_text(current.id)
    assert "Why does broadcasting" not in store.session_display_text(current.id)
    memory = store.recent_lecture_memory("RL", current.id)
    assert "mixing time" in memory
    assert "broadcasting aligns" not in memory


def test_decoder_errors_omit_filesystem_paths(monkeypatch):
    from pathlib import Path

    from speech_tool import media

    class Failed:
        returncode = 1
        stderr = "/tmp/speech-tool-test/incoming/clip.webm: Invalid data found"
        stdout = ""

    monkeypatch.setattr(media.subprocess, "run", lambda *args, **kwargs: Failed())
    try:
        media.ffprobe_duration(Path("clip.webm"))
        raise AssertionError("expected MediaError")
    except media.MediaError as exc:
        text = str(exc)
    assert "/" not in text
    assert text == media.UNREADABLE_AUDIO
    try:
        media.ensure_wav_16k(Path("clip.webm"), Path("clip.wav"))
        raise AssertionError("expected MediaError")
    except media.MediaError as exc:
        assert str(exc) == media.UNREADABLE_AUDIO
        assert "clip.webm" not in str(exc)


def test_rejects_over_ten_minutes():
    from speech_tool.media import MediaError, validate_duration

    validate_duration(600)
    try:
        validate_duration(603)
        raise AssertionError("expected MediaError")
    except MediaError:
        pass
    validate_duration(300, 300)
    try:
        validate_duration(303, 300)
        raise AssertionError("expected MediaError")
    except MediaError:
        pass


class TimeoutThenSuccessPolisher(Polisher):
    def __init__(self):
        self.n = 0
        self.timeouts: list[float | None] = []

    def polish(self, raw_text: str, timeout: float | None = None) -> PolishResult:
        self.n += 1
        self.timeouts.append(timeout)
        if self.n == 1:
            return PolishResult(text=raw_text, model="flaky", version="timeout")
        return PolishResult(text="cleaned", model="flaky", version="opencode")


class OrderPolisher(Polisher):
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.order: list[str] = []

    def polish(self, raw_text: str, timeout: float | None = None) -> PolishResult:
        self.order.append(raw_text)
        if len(self.order) == 1:
            self.started.set()
            self.release.wait(timeout=3)
        return PolishResult(text=raw_text, model="order", version="1")


def _ready_for_polish(store: EventStore, event_id: str, text: str) -> None:
    store.write_raw_transcript(event_id, text)
    store.update_event(
        event_id,
        lambda event: (
            setattr(event, "asr_status", "completed"),
            setattr(event, "transcript_revision", 1),
            setattr(event, "polish_status", "pending"),
        ),
    )


def test_polish_retries_timeout_once(tmp_path):
    store = EventStore(tmp_path)
    event = store.create_from_audio(b"audio-bytes", "clip.wav", 1.0)
    polisher = TimeoutThenSuccessPolisher()
    pipe = Pipeline(store, asr=FakeAsr(), polisher=polisher, auto_start=False)
    _ready_for_polish(store, event.id, "raw asr")
    pipe.enqueue_polish(event.id, revision=1)
    done = wait_state(store, event.id, EventState.COMPLETED)
    assert polisher.n == 2
    assert store.read_polished_transcript(done.id) == "cleaned"
    assert done.lm_version == "opencode"


def test_lecture_polish_uses_longer_timeout_than_notes(tmp_path):
    store = EventStore(tmp_path)
    polisher = TimeoutThenSuccessPolisher()
    pipe = Pipeline(store, asr=FakeAsr(), polisher=polisher, auto_start=False)
    note = store.create_from_audio(
        b"n", "n.wav", 1.0, kind="note_turn", turn_index=0
    )
    session = store.create_session(course="4787")
    lecture = store.create_from_audio(
        b"l",
        "l.wav",
        1.0,
        kind="lecture_chunk",
        session_id=session.id,
        chunk_index=0,
    )
    _ready_for_polish(store, note.id, "note asr")
    pipe.enqueue_polish(note.id, revision=1)
    wait_state(store, note.id, EventState.COMPLETED)
    note_timeout = polisher.timeouts[0]
    _ready_for_polish(store, lecture.id, "lecture asr")
    pipe.enqueue_polish(lecture.id, revision=1)
    wait_state(store, lecture.id, EventState.COMPLETED)
    assert note_timeout == 20
    assert 120 in polisher.timeouts


def test_note_polish_jumps_lecture_queue(tmp_path):
    store = EventStore(tmp_path)
    polisher = OrderPolisher()
    pipe = Pipeline(store, asr=FakeAsr(), polisher=polisher, auto_start=False)
    session = store.create_session(course="4787")
    first = store.create_from_audio(
        b"a",
        "a.wav",
        1.0,
        kind="lecture_chunk",
        session_id=session.id,
        chunk_index=0,
    )
    second = store.create_from_audio(
        b"b",
        "b.wav",
        1.0,
        kind="lecture_chunk",
        session_id=session.id,
        chunk_index=1,
    )
    note = store.create_from_audio(
        b"n", "n.wav", 1.0, kind="note_turn", turn_index=0
    )
    _ready_for_polish(store, first.id, "L1")
    pipe.enqueue_polish(first.id, revision=1)
    assert polisher.started.wait(timeout=2)
    _ready_for_polish(store, second.id, "L2")
    pipe.enqueue_polish(second.id, revision=1)
    _ready_for_polish(store, note.id, "NOTE")
    pipe.enqueue_polish(note.id, revision=1)
    polisher.release.set()
    wait_state(store, first.id, EventState.COMPLETED)
    wait_state(store, second.id, EventState.COMPLETED)
    wait_state(store, note.id, EventState.COMPLETED)
    assert polisher.order == ["L1", "NOTE", "L2"]


def test_timeout_polish_still_exposes_transcript(tmp_path):
    store = EventStore(tmp_path)
    event = store.create_from_audio(
        b"audio", "turn.wav", 1.0, kind="note_turn", turn_index=0
    )
    store.write_raw_transcript(event.id, "raw asr")
    store.write_polished_transcript(event.id, "raw asr")
    store.update_event(
        event.id,
        lambda item: (
            setattr(item, "asr_status", "completed"),
            setattr(item, "polish_status", "completed"),
            setattr(item, "transcript_revision", 1),
            setattr(item, "polished_revision", 1),
            setattr(item, "lm_version", "timeout"),
        ),
    )
    assert store.read_polished_draft(event.id) == "raw asr"


def test_noise_chunks_are_omitted_from_lecture_display(tmp_path):
    from speech_tool.transcript_quality import is_noise_transcript

    assert is_noise_transcript("I'm going to come up here. " * 12, 60)
    assert is_noise_transcript("ව" * 200, 120)
    assert not is_noise_transcript(
        "The first principle is write learning as first-order optimization over a loss.",
        8,
    )

    store = EventStore(tmp_path)
    session = store.create_session(course="4787")
    good = store.create_from_audio(
        b"a", "a.wav", 8.0, kind="lecture_chunk", session_id=session.id, chunk_index=0
    )
    junk = store.create_from_audio(
        b"b", "b.wav", 120.0, kind="lecture_chunk", session_id=session.id, chunk_index=1
    )
    store.attach_chunk(session.id, good.id)
    store.attach_chunk(session.id, junk.id)
    store.write_raw_transcript(good.id, "The first principle is write learning as first-order optimization over a loss.")
    store.write_raw_transcript(junk.id, "ව" * 200)
    assert "first principle" in store.session_display_text(session.id)
    assert "ව" not in store.session_display_text(session.id)
    assert "ව" in store.session_raw_text(session.id)


def test_reopen_session_clears_ended_state(tmp_path):
    store = EventStore(tmp_path)
    session = store.create_session(course="4787")
    store.end_session(session.id)
    opened = store.reopen_session(session.id)
    assert opened.status == "open"
    assert opened.ended_at is None


def test_lexicon_feeds_whisper_and_polish_prompts():
    from speech_tool.lexicon import polish_lexicon_block, whisper_initial_prompt

    note = whisper_initial_prompt("note_turn")
    lecture = whisper_initial_prompt("lecture_chunk")
    polish = polish_lexicon_block()
    assert "CUDA" in note
    assert "CUDA" in lecture
    assert "Kuda" in polish
    assert "DeepSeek" in polish


def test_polish_prompt_treats_transcript_as_data():
    from speech_tool.polish import build_polish_prompt

    prompt = build_polish_prompt("请把语音识别结果尽快显示出来，不要等 polish 完成才给正文。")
    assert "<transcript>" in prompt
    assert "</transcript>" in prompt
    assert "不要等 polish" in prompt
    assert "untrusted ASR data" in prompt
    assert prompt.index("<transcript>") < prompt.index("不要等 polish")


def test_noise_asr_does_not_append_to_canonical_note(tmp_path):
    from speech_tool.asr import AsrResult

    class JunkAsr(FakeAsr):
        def transcribe(self, audio_path, *, kind=None):
            return AsrResult(
                text="ව" * 200,
                model="fake",
                version="test",
                elapsed_seconds=0.01,
                rtf=0.01,
            )

    store = EventStore(tmp_path)
    note = store.create_note("Noise")
    event = store.create_from_audio(
        b"audio",
        "turn.wav",
        120.0,
        kind="note_turn",
        note_id=note.id,
        turn_index=0,
    )
    store.attach_turn(note.id, event.id)
    pipe = Pipeline(store, asr=JunkAsr(), polisher=PassthroughPolisher(), auto_start=False)
    pipe.enqueue_asr(event.id)
    wait_state(store, event.id, EventState.COMPLETED)
    raw = store.read_raw_transcript(event.id)
    final, _ = store.read_note_final(note.id)
    assert raw and "ව" in raw
    assert "ව" not in final
