import json
import subprocess
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from speech_tool.app import create_app
from speech_tool.store import EventStore
from speech_tool.retention import retain_event, archive_reference, GRACE_SECONDS
from speech_tool.archive import sha256
from speech_tool.pipeline import Pipeline
from speech_tool.polish import PassthroughPolisher
from tests.fakes import FakeAsr


def prepared(tmp_path):
    wav = tmp_path / 'fixture.wav'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                    'sine=frequency=440:duration=1', '-ar', '16000', str(wav)], check=True)
    store = EventStore(tmp_path / 'store')
    event = store.create_from_audio(wav.read_bytes(), 'audio.wav', 1)
    store.write_raw_transcript(event.id, 'A completed transcript.')
    store.update_event(event.id, lambda e: setattr(e, 'asr_status', 'completed'))
    return store, store.get(event.id)


def test_grace_then_archive_playback_and_transcript_writes(tmp_path):
    store, event = prepared(tmp_path)
    original = store.audio_path(event)
    root = store.root
    row = retain_event(root, original.parent, now=1000)
    assert row['status'] == 'grace_period_original_retained'
    assert row['delete_not_before'] == 1000 + GRACE_SECONDS
    assert original.exists()
    retain_event(root, original.parent, now=999 + GRACE_SECONDS)
    assert original.exists()
    assert retain_event(root, original.parent, now=1000 + GRACE_SECONDS)['status'] == 'playback_service_not_verified_original_retained'
    row = retain_event(root, original.parent, now=1000 + GRACE_SECONDS, allow_removal=True)
    assert row['status'] == 'original_removed_lossless_copy_verified'
    assert not original.exists()
    archived = store.audio_path(event)
    assert archived.suffix == '.flac'
    assert store.get(event.id).audio_sha256 == event.audio_sha256
    client = TestClient(create_app(store, Pipeline(store, asr=FakeAsr(), polisher=PassthroughPolisher(), auto_start=False)))
    response = client.get(f'/api/events/{event.id}/audio')
    assert response.status_code == 200
    assert response.content == archived.read_bytes()
    assert 'flac' in response.headers['content-disposition']
    class ArchiveAsr(FakeAsr):
        def transcribe(self, audio_path, **kwargs):
            assert audio_path == archived
            # Exercise the actual decoder used by local transcription.
            from speech_tool.media import ensure_wav_16k
            decoded = tmp_path / 'retranscribed.wav'
            ensure_wav_16k(audio_path, decoded)
            assert decoded.stat().st_size > 0
            return super().transcribe(audio_path, **kwargs)
    pipe = Pipeline(store, asr=ArchiveAsr(), polisher=PassthroughPolisher(), auto_start=False)
    pipe._run_asr(event.id, force=True)
    assert store.get(event.id).asr_status == 'completed', store.get(event.id).last_error
    assert store.read_raw_transcript(event.id) == 'hello world from asr'
    store.write_raw_transcript(event.id, 'Retranscribed from archive.')
    store.write_polished_transcript(event.id, 'Still editable.')


def test_corrupt_archive_never_deletes_original(tmp_path):
    store, event = prepared(tmp_path)
    original = store.audio_path(event)
    retain_event(store.root, original.parent, now=1000)
    archived = archive_reference(store.root, event.id, event.audio_sha256)
    archived.write_bytes(b'corrupt')
    with pytest.raises(ValueError):
        retain_event(store.root, original.parent, now=1000 + GRACE_SECONDS)
    assert sha256(original) == event.audio_sha256


def test_failed_retranscription_and_webm_remain(tmp_path):
    store, event = prepared(tmp_path)
    original = store.audio_path(event)
    retain_event(store.root, original.parent, now=1000)
    store.update_event(event.id, lambda e: setattr(e, 'asr_status', 'failed'))
    row = retain_event(store.root, original.parent, now=1000 + GRACE_SECONDS)
    assert row['status'] == 'transcription_not_complete'
    assert original.exists()
    webm = store.create_from_audio(b'webm bytes', 'audio.webm', 1)
    assert retain_event(store.root, store.audio_path(webm).parent, now=1e10)['status'] == 'compressed_or_noncanonical_retained'
    assert store.audio_path(webm).read_bytes() == b'webm bytes'


def test_corrupt_receipt_and_source_protected(tmp_path):
    store, event = prepared(tmp_path)
    original = store.audio_path(event)
    retain_event(store.root, original.parent, now=1000)
    archived = archive_reference(store.root, event.id, event.audio_sha256)
    receipt = archived.parent / 'retention.json'
    data = json.loads(receipt.read_text())
    data['delete_not_before'] = 1001
    receipt.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        retain_event(store.root, original.parent, now=2000)
    assert original.exists()


def test_real_clock_grace_starts_after_encoding(tmp_path, monkeypatch):
    store, event = prepared(tmp_path)
    moments = iter([1000, 2000])
    monkeypatch.setattr('speech_tool.retention.time', SimpleNamespace(time=lambda: next(moments)))
    row = retain_event(store.root, store.audio_path(event).parent)
    assert row['delete_not_before'] == 2000 + GRACE_SECONDS
