import json
import subprocess

from speech_tool.archive import archive_one, eligible, sha256


def test_verified_archive_preserves_original_and_is_idempotent(tmp_path):
    source=tmp_path/'audio.wav'
    subprocess.run(['ffmpeg','-hide_banner','-v','error','-f','lavfi','-i',
                    'sine=frequency=440:duration=1','-ar','16000',str(source)],check=True)
    before=sha256(source)
    row=archive_one(source,tmp_path/'copies','sample')
    assert row['status']=='verified'
    assert row['archive_bytes'] < row['source_bytes']
    assert row['lossy'] is False
    assert row['native_pcm_sha256']
    assert row['duration_difference_seconds'] <= .1
    assert sha256(source)==before
    assert archive_one(source,tmp_path/'copies','sample')['status']=='already_verified'


def test_failed_or_missing_transcription_not_eligible(tmp_path):
    event=tmp_path/'events'/'sample'
    event.mkdir(parents=True)
    (event/'audio.wav').write_bytes(b'not audio')
    (event/'event.json').write_text(json.dumps({'asr_status':'failed'}))
    (event/'transcript.raw.txt').write_text('some partial text')
    assert list(eligible(tmp_path))==[]
