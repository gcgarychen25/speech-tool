import time

from fastapi.testclient import TestClient
import pytest
from pathlib import Path

from speech_tool.app import create_app
from speech_tool.pipeline import Pipeline
from speech_tool.polish import PassthroughPolisher, PolishResult
from speech_tool.polish_quality import polish_quality_issue
from speech_tool.store import EventStore
from tests.fakes import FakeAsr


def setup(tmp_path):
    store = EventStore(tmp_path)
    pipe = Pipeline(store, asr=FakeAsr(), polisher=PassthroughPolisher(), auto_start=False)
    return store, pipe, TestClient(create_app(store, pipe))


def add_chunk(store, session, index, raw='This is the original lecture transcript.'):
    event = store.create_from_audio(b'audio', 'audio.webm', 5, kind='lecture_chunk', session_id=session.id, chunk_index=index)
    store.attach_chunk(session.id, event.id)
    store.write_raw_transcript(event.id, raw)
    store.update_event(event.id, lambda e: (setattr(e, 'asr_status', 'completed'), setattr(e, 'transcript_revision', 1)))
    return event


def test_health_exposes_polish_provider(tmp_path):
    store, pipe, client = setup(tmp_path)
    pipe._polish_fail_streak = 2
    pipe._polish_provider_detail = "provider down"
    result = client.get('/api/health').json()
    assert result['ok'] is True
    assert result['polish']['consecutive_failures'] == 2
    assert result['polish']['available'] is True
    assert 'model' in result['polish']


def test_empty_completed_audio_is_not_pending_transcription(tmp_path):
    store, pipe, client = setup(tmp_path)
    session = store.create_session()
    add_chunk(store, session, 0, '')
    result = client.get(f'/api/sessions/{session.id}').json()
    assert result['empty_transcript_chunks'] == 1
    assert result['transcription_pending_chunks'] == 0
    assert result['transcribed_chunks'] == 0


def test_gap_trailing_gap_next_index_and_saved_raw(tmp_path):
    store, pipe, client = setup(tmp_path)
    session = store.create_session()
    first = add_chunk(store, session, 0)
    third = add_chunk(store, session, 2)
    store.update_event(third.id, lambda e: (setattr(e, 'polish_status', 'failed'), setattr(e, 'lm_version', 'timeout')))
    result = client.get(f'/api/sessions/{session.id}').json()
    assert result['transcribed_chunks'] == 2
    assert result['cleanup_failed_chunks'] == 1
    assert result['cleanup_provider_failed_chunks'] == 1
    assert result['cleanup_guard_chunks'] == 0
    assert result['missing_chunk_indices'] == [1]
    assert result['next_chunk_index'] == 3
    assert not result['completeness_known']
    assert 'original lecture' in result['display_text']
    result = client.post(f'/api/sessions/{session.id}/end', json={'expected_chunk_count': 4}).json()
    assert result['status'] == 'ended'
    assert result['missing_chunk_indices'] == [1, 3]
    assert result['next_chunk_index'] == 4
    assert result['completeness_known']
    add_chunk(store, session, 1)
    add_chunk(store, session, 3)
    assert client.get(f'/api/sessions/{session.id}').json()['missing_chunk_indices'] == []


def test_upload_error_hides_filesystem_path(tmp_path, monkeypatch):
    from speech_tool.media import MediaError

    store, _pipe, client = setup(tmp_path)
    session = store.create_session()

    def unreadable(_path):
        raise MediaError("unreadable /tmp/speech-tool-test/clip.webm")

    monkeypatch.setattr("speech_tool.pipeline.ffprobe_duration", unreadable)
    hidden = client.post(
        f"/api/events?session_id={session.id}&chunk_index=0&capture_id=capture-path",
        files={"file": ("a.webm", b"audio", "audio/webm")},
    )
    assert hidden.status_code == 400
    assert "/" not in hidden.json()["detail"]
    assert hidden.json()["detail"] == "Audio could not be stored; original upload retained in browser"

    def readable_failure(_path):
        raise MediaError("No decodable audio packets; original upload retained in browser")

    monkeypatch.setattr("speech_tool.pipeline.ffprobe_duration", readable_failure)
    shown = client.post(
        f"/api/events?session_id={session.id}&chunk_index=1&capture_id=capture-clean",
        files={"file": ("b.webm", b"audio", "audio/webm")},
    )
    assert shown.status_code == 400
    assert shown.json()["detail"] == "No decodable audio packets; original upload retained in browser"


def test_capture_ack_retries_and_index_conflicts(tmp_path, monkeypatch):
    store, pipe, client = setup(tmp_path)
    session = store.create_session()
    monkeypatch.setattr('speech_tool.pipeline.ffprobe_duration', lambda _: 1)
    monkeypatch.setattr(pipe, 'enqueue_asr', lambda _: None)
    url = f'/api/events?session_id={session.id}&chunk_index=0&capture_id=capture-one'
    one = client.post(url, files={'file': ('a.webm', b'audio', 'audio/webm')})
    assert one.status_code == 200
    assert one.json()['capture_id'] == 'capture-one'
    two = client.post(url, files={'file': ('a.webm', b'audio', 'audio/webm')})
    assert two.json()['id'] == one.json()['id']
    conflict = client.post(url.replace('capture-one', 'capture-two'), files={'file': ('a.webm', b'other', 'audio/webm')})
    assert conflict.status_code == 409
    assert len(store.get_session(session.id).chunk_ids) == 1
    assert client.post(f'/api/sessions/{session.id}/end', json={'expected_chunk_count': -1}).status_code == 422


def test_language_guard_historical_fallback_and_targeted_retry(tmp_path, monkeypatch):
    store, pipe, client = setup(tmp_path)
    session = store.create_session()
    raw = 'Rust handles virtual tables differently. A reference to a trait object includes a data pointer and a virtual table pointer. '
    event = add_chunk(store, session, 0, raw)
    translated = '这是一段中文翻译，它改变了讲课使用的语言。虚表包含函数指针，数据指针指向对象本身。'
    store.write_polished_transcript(event.id, translated)
    store.update_event(event.id, lambda e: (setattr(e, 'polish_status', 'completed'), setattr(e, 'polished_revision', 1)))
    result = client.get(f'/api/sessions/{session.id}').json()
    assert result['cleanup_failed_chunks'] == 1
    assert result['cleanup_guard_chunks'] == 1
    assert result['cleanup_provider_failed_chunks'] == 0
    assert result['polished_transcript'] == raw.strip()
    assert store.read_polished_transcript(event.id) == translated
    called = []
    monkeypatch.setattr(pipe, 'retry_polish', called.append)
    client.post(f'/api/sessions/{session.id}/retry-polish')
    assert called == [event.id]
    store.write_polished_transcript(event.id, raw)
    assert translated in store.polished_transcript_path(event.id).with_name('transcript.polished.txt.history.jsonl').read_text()


def test_new_bad_cleanup_not_published(tmp_path):
    store, pipe, client = setup(tmp_path)
    event = add_chunk(store, store.create_session(), 0, 'This English lecture explains virtual tables and dynamic dispatch in the Rust programming language.')
    class Translator:
        def polish(self, *args, **kwargs):
            return PolishResult('这段讲义解释了虚函数表以及动态分派在程序设计语言中的作用。', 'fake', 'test')
    pipe.polisher = Translator()
    pipe._run_polish(event.id, 1)
    assert store.get(event.id).lm_version == 'quality_rejected'
    view = client.get(f'/api/sessions/{event.session_id}').json()
    assert view['cleanup_guard_chunks'] == 1
    assert view['cleanup_provider_failed_chunks'] == 0
    assert not store.read_polished_transcript(event.id)
    assert store.read_raw_transcript(event.id)


def test_guard_preserves_code_switching_and_normal_cleanup():
    raw = 'Today we discuss Rust references and the distinction between dynamic dispatch and static dispatch.'
    assert polish_quality_issue(raw, raw) is None
    mixed = '今天我们学习 Rust 的 dynamic dispatch，它与 static dispatch 有什么区别，应该如何选择？'
    assert polish_quality_issue(mixed, mixed) is None
    assert polish_quality_issue(raw * 4, 'Summary.')


def test_provider_pause_is_visible_without_raw_text(tmp_path):
    store, pipe, client = setup(tmp_path)
    session = store.create_session()
    event = add_chunk(store, session, 0)
    store.update_event(event.id, lambda e: (
        setattr(e, 'polish_status', 'failed'),
        setattr(e, 'lm_version', 'provider_unavailable'),
    ))
    pipe._polish_cooldown_until = time.monotonic() + 125
    pipe._polish_provider_detail = (
        "AI cleanup is unavailable from the provider right now; raw transcript preserved"
    )
    result = client.get(f'/api/sessions/{session.id}').json()
    assert result['cleanup_provider_available'] is False
    assert result['cleanup_failed_chunks'] == 1
    assert result['cleanup_provider_failed_chunks'] == 1
    assert result['cleanup_guard_chunks'] == 0
    assert result['cleanup_cooldown_seconds'] >= 120
    assert result['cleanup_provider_detail'].startswith('AI cleanup')
    assert 'original lecture' not in (result['cleanup_provider_detail'] or '')
    note = client.post('/api/notes', json={'title': 'synthetic note'}).json()
    assert note['cleanup_provider_available'] is False
    assert note['cleanup_cooldown_seconds'] >= 120
    assert note['state'] == 'empty'


def _note_turn(store, note, raw, **updates):
    event = store.create_from_audio(
        b'audio', 'turn.webm', 5, kind='note_turn', note_id=note.id, turn_index=len(note.turn_ids),
    )
    store.attach_turn(note.id, event.id)
    store.write_raw_transcript(event.id, raw)
    store.update_event(event.id, lambda e: (
        setattr(e, 'asr_status', 'completed'),
        setattr(e, 'transcript_revision', 1),
    ))
    if updates:
        store.update_event(event.id, lambda e: [setattr(e, key, value) for key, value in updates.items()])
    return event


def test_note_history_labels_original_kept_separately_from_provider_failure(tmp_path):
    store, pipe, client = setup(tmp_path)
    raw = 'This English note explains virtual tables and dynamic dispatch in the Rust programming language.'
    kept = store.create_note('Kept original')
    event = _note_turn(store, kept, raw, polish_status='failed', lm_version='quality_rejected')
    listed = client.get('/api/notes').json()
    match = next(item for item in listed if item['id'] == kept.id)
    assert match['state'] == 'polishing_failed'
    assert match['cleanup_failed_turns'] == 1
    assert match['cleanup_guard_turns'] == 1
    assert match['cleanup_provider_failed_turns'] == 0
    assert not store.read_polished_transcript(event.id)

    provider = store.create_note('Provider down')
    _note_turn(store, provider, raw, polish_status='failed', lm_version='provider_unavailable')
    pipe._polish_cooldown_until = time.monotonic() + 90
    view = client.get(f'/api/notes/{provider.id}').json()
    assert view['cleanup_guard_turns'] == 0
    assert view['cleanup_provider_failed_turns'] == 1
    assert view['cleanup_provider_available'] is False
    assert view['cleanup_cooldown_seconds'] >= 60

    historical = store.create_note('Historical translation')
    translated = '这是一段中文翻译，它改变了笔记使用的语言。虚表包含函数指针，数据指针指向对象本身。'
    old = _note_turn(store, historical, raw, polish_status='completed', polished_revision=1, lm_version='test')
    store.write_polished_transcript(old.id, translated)
    view = client.get(f'/api/notes/{historical.id}').json()
    assert view['state'] == 'polishing_failed'
    assert view['cleanup_guard_turns'] == 1
    assert view['cleanup_provider_failed_turns'] == 0


def test_retry_transcription_only_failed(tmp_path, monkeypatch):
    store, pipe, client = setup(tmp_path)
    session = store.create_session()
    good = add_chunk(store, session, 0)
    failed = add_chunk(store, session, 1)
    store.update_event(failed.id, lambda e: setattr(e, 'asr_status', 'failed'))
    called = []
    monkeypatch.setattr(pipe, 'retry_asr', called.append)
    assert client.post(f'/api/sessions/{session.id}/retry-transcription').status_code == 200
    assert called == [failed.id]


def test_transcript_path_materializes_full_asr_file(tmp_path):
    store, pipe, client = setup(tmp_path)
    session = store.create_session()
    add_chunk(store, session, 0, 'First lecture part.')
    add_chunk(store, session, 1, 'Second lecture part.')
    result = client.post(f'/api/sessions/{session.id}/transcript-path').json()
    path = Path(result['path'])
    assert result['kind'] == 'asr'
    assert result['ready'] is True
    assert path.name == 'transcript.raw.txt'
    assert path.parent.name == session.id
    assert path.read_text(encoding='utf-8') == 'First lecture part.\n\nSecond lecture part.'
    ended = client.post(f'/api/sessions/{session.id}/end').json()
    assert ended['status'] == 'ended'
    assert path.exists()


def test_transcript_path_empty_until_asr(tmp_path):
    store, pipe, client = setup(tmp_path)
    session = store.create_session()
    result = client.post(f'/api/sessions/{session.id}/transcript-path').json()
    assert result['ready'] is False
    assert Path(result['path']).read_text(encoding='utf-8') == ''
    assert client.post('/api/sessions/missing/transcript-path').status_code == 404
