#!/usr/bin/env python3
"""Verify Speech Tool V1 against docs/speech_tool_v1_success_criteria.md."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from speech_tool.asr import FailingAsr, MlxWhisperAsr
from speech_tool.models import EventState
from speech_tool.pipeline import Pipeline
from speech_tool.polish import FailingPolisher, OpencodePolisher, PassthroughPolisher
from speech_tool.store import EventStore, sha256_file
from tests.fakes import FakeAsr


def say_to_wav(text: str, dest: Path, voice: str) -> Path:
    aiff = dest.with_suffix(".aiff")
    subprocess.run(["say", "-v", voice, "-o", str(aiff), text], check=True)
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(aiff), "-ar", "16000", "-ac", "1", str(dest)],
        check=True,
        capture_output=True,
    )
    aiff.unlink(missing_ok=True)
    return dest


def wait_state(store, event_id, state, timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        event = store.get(event_id)
        if event.state == state:
            return event
        time.sleep(0.2)
    raise AssertionError(f"timeout waiting {state}: {store.get(event_id)}")


def ingest_file(pipe: Pipeline, wav: Path) -> str:
    return pipe.ingest_audio(wav.read_bytes(), wav.name, wav)


def main() -> int:
    report = []
    tmp = Path(tempfile.mkdtemp(prefix="speech-tool-verify-"))
    store = EventStore(tmp)

    event = store.create_from_audio(b"raw-audio-bytes", "clip.wav", 1.0)
    digest = event.audio_sha256
    fail_pipe = Pipeline(
        store, asr=FailingAsr(), polisher=PassthroughPolisher(), auto_start=False
    )
    fail_pipe.enqueue_asr(event.id)
    failed = wait_state(store, event.id, EventState.TRANSCRIPTION_FAILED, 5)
    assert sha256_file(store.audio_path(failed)) == digest
    report.append({"id": "asr_failure_keeps_audio", "ok": True})

    store2 = EventStore(tmp / "p2")
    e2 = store2.create_from_audio(b"raw-audio-bytes-2", "clip.wav", 1.0)
    p2 = Pipeline(
        store2, asr=FakeAsr(), polisher=FailingPolisher(), auto_start=False
    )
    p2.enqueue_asr(e2.id)
    wait_state(store2, e2.id, EventState.POLISHING_FAILED, 5)
    assert store2.read_raw_transcript(e2.id)
    assert store2.read_polished_transcript(e2.id) is None
    report.append({"id": "polish_failure_keeps_raw", "ok": True})

    e2.asr_status = "running"
    store2.save(e2)
    store2.interrupt_inflight()
    assert store2.get(e2.id).asr_status == "pending"
    report.append({"id": "interrupt_recoverable", "ok": True})

    live = os.environ.get("SPEECH_TOOL_LIVE_ASR", "1") == "1"
    if live:
        asr = MlxWhisperAsr()
        asr.warmup()
        work = tmp / "live"
        work.mkdir()
        en = say_to_wav(
            "This is a local speech tool using Whisper for automatic speech recognition.",
            work / "en.wav",
            "Samantha",
        )
        zh = say_to_wav(
            "这是一个本地语音工具，用来做中文语音识别测试。",
            work / "zh.wav",
            "Tingting",
        )
        mixed = say_to_wav(
            "我们用 Whisper 做 ASR，然后用 language model 做 polish。",
            work / "mix.wav",
            "Tingting",
        )
        live_store = EventStore(work / "events_root")
        polish_name = os.environ.get("SPEECH_TOOL_VERIFY_POLISHER", "passthrough")
        polisher = (
            OpencodePolisher() if polish_name == "opencode" else PassthroughPolisher()
        )
        pipe = Pipeline(live_store, asr=asr, polisher=polisher, auto_start=False)
        live_results = {}
        for label, wav in [("en", en), ("zh", zh), ("mix", mixed)]:
            eid = ingest_file(pipe, wav)
            ev = wait_state(live_store, eid, EventState.COMPLETED, 300)
            text = live_store.read_raw_transcript(eid) or ""
            live_results[label] = {
                "text": text,
                "rtf": ev.asr_rtf,
                "elapsed": ev.asr_elapsed_seconds,
                "duration": ev.duration_seconds,
            }
            report.append(
                {
                    "id": f"live_asr_{label}",
                    "ok": bool(text.strip()),
                    "text": text,
                    "rtf": ev.asr_rtf,
                    "elapsed": ev.asr_elapsed_seconds,
                    "duration": ev.duration_seconds,
                }
            )
        en_ev = live_results["en"]
        latency_ok = (en_ev["elapsed"] or 99) < 3 or (en_ev["rtf"] or 99) <= 0.2
        report.append({"id": "latency_short_clip", "ok": bool(latency_ok), **en_ev})
        report.append({"id": "polisher_used", "ok": True, "polisher": polish_name})

        # Duration support: build a ~35s clip and check RTF still meets the 30s bucket.
        long_wav = work / "long.wav"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-stream_loop",
                "7",
                "-i",
                str(en),
                "-t",
                "32",
                "-ar",
                "16000",
                str(long_wav),
            ],
            check=True,
            capture_output=True,
        )
        eid = ingest_file(pipe, long_wav)
        ev = wait_state(live_store, eid, EventState.COMPLETED, 300)
        long_ok = (ev.asr_elapsed_seconds or 99) < 10 or (ev.asr_rtf or 99) <= 0.2
        report.append(
            {
                "id": "latency_30s_clip",
                "ok": bool(long_ok),
                "elapsed": ev.asr_elapsed_seconds,
                "rtf": ev.asr_rtf,
                "duration": ev.duration_seconds,
            }
        )

    print(json.dumps({"report": report, "tmp": str(tmp)}, indent=2, ensure_ascii=False))
    failed = [r for r in report if not r.get("ok")]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
