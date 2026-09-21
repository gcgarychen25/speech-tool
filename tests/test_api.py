from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from speech_tool.app import create_app
from speech_tool.models import EventState
from speech_tool.pipeline import Pipeline
from speech_tool.polish import PassthroughPolisher
from speech_tool.store import EventStore
from tests.fakes import FakeAsr
from tests.test_store_pipeline import BlockingPolisher, wait_state


def test_api_history_copy_retry_delete(tmp_path):
    store = EventStore(tmp_path)
    pipe = Pipeline(
        store, asr=FakeAsr(), polisher=PassthroughPolisher(), auto_start=False
    )
    app = create_app(store, pipe)
    client = TestClient(app)
    wav = tmp_path / "tone.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(wav),
        ],
        check=True,
        capture_output=True,
    )
    with wav.open("rb") as f:
        res = client.post("/api/events", files={"file": ("tone.wav", f, "audio/wav")})
    assert res.status_code == 200, res.text
    event_id = res.json()["id"]
    wait_state(store, event_id, EventState.COMPLETED)
    listed = client.get("/api/events").json()
    assert listed[0]["id"] == event_id
    detail = client.get(f"/api/events/{event_id}").json()
    assert "hello world from asr" in detail["raw_transcript"]
    assert detail["polish_available"] is True
    assert detail["polish_ready"] is False
    audio = client.get(f"/api/events/{event_id}/audio")
    assert audio.status_code == 200
    assert client.post(f"/api/events/{event_id}/retry-asr").status_code == 200
    wait_state(store, event_id, EventState.COMPLETED)
    assert client.delete(f"/api/events/{event_id}").status_code == 200
    assert client.get("/api/events").json() == []


def test_append_and_edit_transcript(tmp_path):
    store = EventStore(tmp_path)
    pipe = Pipeline(
        store, asr=FakeAsr(), polisher=PassthroughPolisher(), auto_start=False
    )
    app = create_app(store, pipe)
    client = TestClient(app)
    wav = tmp_path / "tone.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(wav),
        ],
        check=True,
        capture_output=True,
    )
    with wav.open("rb") as f:
        first = client.post("/api/events", files={"file": ("tone.wav", f, "audio/wav")})
    event_id = first.json()["id"]
    wait_state(store, event_id, EventState.COMPLETED)
    initial = client.get(f"/api/events/{event_id}").json()
    edited = client.patch(
        f"/api/events/{event_id}",
        json={
            "text": "edited by user",
            "transcript_revision": initial["transcript_revision"],
        },
    )
    assert edited.status_code == 200
    with wav.open("rb") as f:
        second = client.post(
            f"/api/events?append_to={event_id}",
            files={"file": ("tone.wav", f, "audio/wav")},
        )
    assert second.status_code == 200
    wait_state(store, event_id, EventState.COMPLETED, timeout=8)
    text = store.read_polished_transcript(event_id)
    assert text.count("hello world from asr") == 2
    assert store.read_edited_transcript(event_id) == "edited by user"
    pending = client.get(f"/api/events/{event_id}").json()
    assert len(pending["pending_append_transcripts"]) == 1
    merged = client.patch(
        f"/api/events/{event_id}",
        json={
            "text": "edited by user\n\nhello world from asr",
            "transcript_revision": pending["transcript_revision"],
        },
    )
    assert merged.status_code == 200
    assert client.get(f"/api/events/{event_id}").json()[
        "pending_append_transcripts"
    ] == []
    assert store.read_polished_transcript(event_id).count("hello world from asr") == 2
    copied = client.post(
        f"/api/events/{event_id}/copy",
        json={"text": "edited by user\n\nhello world from asr"},
    )
    assert copied.status_code == 200
    assert copied.json()["changed"] is True
    log = (tmp_path / "corrections.jsonl").read_text(encoding="utf-8")
    assert "edited by user" in log
    assert "hello world from asr" in log


def test_lecture_session_api(tmp_path):
    store = EventStore(tmp_path)
    pipe = Pipeline(
        store, asr=FakeAsr(), polisher=PassthroughPolisher(), auto_start=False
    )
    app = create_app(store, pipe)
    client = TestClient(app)
    wav = tmp_path / "tone.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(wav),
        ],
        check=True,
        capture_output=True,
    )
    session = client.post("/api/sessions", json={"course": "RL"}).json()
    with wav.open("rb") as f:
        first = client.post(
            f"/api/events?session_id={session['id']}&chunk_index=0",
            files={"file": ("tone.wav", f, "audio/wav")},
        )
    with wav.open("rb") as f:
        second = client.post(
            f"/api/events?session_id={session['id']}&chunk_index=1",
            files={"file": ("tone.wav", f, "audio/wav")},
        )
    assert first.status_code == 200
    assert second.status_code == 200
    wait_state(store, first.json()["id"], EventState.COMPLETED)
    wait_state(store, second.json()["id"], EventState.COMPLETED)
    assert client.get("/api/events").json() == []
    listed = client.get("/api/sessions").json()
    assert listed[0]["chunk_count"] == 2
    assert listed[0]["course"] == "RL"
    detail = client.get(f"/api/sessions/{session['id']}").json()
    assert detail["display_text"].count("hello world from asr") == 2
    assert detail["polish_available"] is True
    patched = client.patch(
        f"/api/sessions/{session['id']}",
        json={"listener_notes": "[01:20] ask about mixing time"},
    )
    assert patched.status_code == 200
    again = client.get(f"/api/sessions/{session['id']}").json()
    assert again["listener_notes"] == "[01:20] ask about mixing time"
    assert "mixing" not in again["display_text"]
    drafted = client.post(
        f"/api/sessions/{session['id']}/questions",
        json={"confusion": "why align broadcasting from the right"},
    )
    assert drafted.status_code == 200
    assert "align broadcasting from the right" in drafted.json()["question"]
    with_question = client.get(f"/api/sessions/{session['id']}").json()
    assert with_question["latest_question"] == drafted.json()["question"]
    assert "align broadcasting" not in with_question["display_text"]
    refined = client.post(
        f"/api/sessions/{session['id']}/questions",
        json={
            "confusion": "why align broadcasting from the right",
            "prior_question": drafted.json()["question"],
            "refine": "one sentence",
        },
    )
    assert refined.status_code == 200
    assert "one sentence" in refined.json()["question"]
    empty = client.post("/api/sessions", json={"course": "RL"}).json()
    missing = client.post(
        f"/api/sessions/{empty['id']}/questions",
        json={"confusion": ""},
    )
    assert missing.status_code == 400
    client.post(f"/api/sessions/{session['id']}/end")
    assert client.get(f"/api/sessions/{session['id']}").json()["status"] == "ended"


def test_note_document_multi_turn_drafts_and_copy(tmp_path):
    store = EventStore(tmp_path)
    pipe = Pipeline(
        store, asr=FakeAsr(), polisher=PassthroughPolisher(), auto_start=False
    )
    client = TestClient(create_app(store, pipe))
    wav = tmp_path / "tone.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(wav),
        ],
        check=True,
        capture_output=True,
    )
    note = client.post("/api/notes", json={"title": "Working note"}).json()
    turn_ids = []
    for _ in range(2):
        with wav.open("rb") as handle:
            response = client.post(
                f"/api/notes/{note['id']}/turns",
                files={"file": ("tone.wav", handle, "audio/wav")},
            )
        assert response.status_code == 200
        turn_ids.append(response.json()["id"])
    for turn_id in turn_ids:
        wait_state(store, turn_id, EventState.COMPLETED)

    detail = client.get(f"/api/notes/{note['id']}").json()
    assert [turn["turn_index"] for turn in detail["turns"]] == [0, 1]
    assert detail["final_text"] == (
        "hello world from asr\n\nhello world from asr"
    )
    assert all(turn["asr_draft"] is None for turn in detail["turns"])
    first_detail = client.get(
        f"/api/notes/{note['id']}/turns/{turn_ids[0]}"
    ).json()
    assert first_detail["asr_draft"] == "hello world from asr"
    assert first_detail["polished_draft"] == "hello world from asr"
    assert all("hello world from asr" in (turn["preview"] or "") for turn in detail["turns"])

    asr_edit = client.patch(
        f"/api/events/{turn_ids[0]}/drafts/asr",
        json={"text": "edited ASR one"},
    )
    polish_edit = client.patch(
        f"/api/events/{turn_ids[0]}/drafts/polished",
        json={"text": "edited polish one"},
    )
    assert asr_edit.status_code == 200
    assert polish_edit.status_code == 200
    assert store.read_raw_transcript(turn_ids[0]) == "hello world from asr"
    assert store.read_polished_transcript(turn_ids[0]) == "hello world from asr"
    assert client.get(f"/api/notes/{note['id']}").json()["final_text"] == (
        "hello world from asr\n\nhello world from asr"
    )

    current = client.get(f"/api/notes/{note['id']}").json()
    final_update = client.patch(
        f"/api/notes/{note['id']}",
        json={
            "base_revision": current["final_revision"],
            "base_text": current["final_text"],
            "text": "canonical edited note",
        },
    )
    assert final_update.status_code == 200
    copied = client.post(f"/api/notes/{note['id']}/copy")
    assert copied.status_code == 200
    assert copied.json()["text"] == "canonical edited note"

    cleared = client.patch(
        f"/api/notes/{note['id']}",
        json={
            "base_revision": final_update.json()["final_revision"],
            "base_text": final_update.json()["final_text"],
            "text": "",
        },
    )
    assert cleared.status_code == 200
    assert cleared.json()["final_text"] == ""
    after_clear = client.get(f"/api/notes/{note['id']}").json()
    assert after_clear["final_text"] == ""
    assert after_clear["turn_count"] == len(turn_ids)
    assert store.read_raw_transcript(turn_ids[0]) == "hello world from asr"
    assert store.read_polished_transcript(turn_ids[0]) == "hello world from asr"


def test_edit_first_turn_while_second_turn_processes(tmp_path):
    store = EventStore(tmp_path)
    polisher = BlockingPolisher()
    pipe = Pipeline(store, asr=FakeAsr(), polisher=polisher, auto_start=False)
    client = TestClient(create_app(store, pipe))
    wav = tmp_path / "tone.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(wav),
        ],
        check=True,
        capture_output=True,
    )
    note = client.post("/api/notes", json={"title": "Live note"}).json()
    with wav.open("rb") as handle:
        first = client.post(
            f"/api/notes/{note['id']}/turns",
            files={"file": ("tone.wav", handle, "audio/wav")},
        ).json()
    wait_state(store, first["id"], EventState.TRANSCRIBED)
    assert polisher.started.wait(timeout=2)
    assert client.patch(
        f"/api/events/{first['id']}/drafts/asr",
        json={"text": "turn one edited during recording"},
    ).status_code == 200

    with wav.open("rb") as handle:
        second = client.post(
            f"/api/notes/{note['id']}/turns",
            files={"file": ("tone.wav", handle, "audio/wav")},
        ).json()
    wait_state(store, second["id"], EventState.TRANSCRIBED)
    assert client.patch(
        f"/api/events/{first['id']}/drafts/asr",
        json={"text": "turn one final edit"},
    ).status_code == 200
    polisher.release.set()
    wait_state(store, first["id"], EventState.COMPLETED)
    wait_state(store, second["id"], EventState.COMPLETED)

    detail = client.get(f"/api/notes/{note['id']}").json()
    first_detail = client.get(
        f"/api/notes/{note['id']}/turns/{first['id']}"
    ).json()
    second_detail = client.get(
        f"/api/notes/{note['id']}/turns/{second['id']}"
    ).json()
    assert first_detail["asr_draft"] == "turn one final edit"
    assert second_detail["asr_draft"] == "hello world from asr"
    assert second_detail["polished_draft"].startswith("latest:")
    assert detail["final_text"] == (
        "hello world from asr\n\nhello world from asr"
    )


def test_canonical_note_update_rebases_concurrent_asr_append(tmp_path):
    store = EventStore(tmp_path)
    pipe = Pipeline(
        store, asr=FakeAsr(), polisher=PassthroughPolisher(), auto_start=False
    )
    client = TestClient(create_app(store, pipe))
    note = client.post("/api/notes", json={"title": "Concurrent"}).json()
    base_text = note["final_text"] or ""
    base_revision = note["final_revision"]
    wav = tmp_path / "tone.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(wav),
        ],
        check=True,
        capture_output=True,
    )
    with wav.open("rb") as handle:
        turn = client.post(
            f"/api/notes/{note['id']}/turns",
            files={"file": ("tone.wav", handle, "audio/wav")},
        ).json()
    wait_state(store, turn["id"], EventState.COMPLETED)

    rebased = client.patch(
        f"/api/notes/{note['id']}",
        json={
            "base_revision": base_revision,
            "base_text": base_text,
            "text": "typed while ASR was running",
        },
    )
    assert rebased.status_code == 200
    assert rebased.json()["final_text"] == (
        "typed while ASR was running\n\nhello world from asr"
    )

    stale = client.patch(
        f"/api/notes/{note['id']}",
        json={
            "base_revision": base_revision,
            "base_text": "unrelated stale base",
            "text": "must not overwrite",
        },
    )
    assert stale.status_code == 409
    assert "hello world from asr" in stale.json()["detail"]["final_text"]


def test_hundred_round_note_stays_lazy(tmp_path):
    store = EventStore(tmp_path)
    pipe = Pipeline(
        store, asr=FakeAsr(), polisher=PassthroughPolisher(), auto_start=False
    )
    client = TestClient(create_app(store, pipe))
    note = store.create_note("Century")
    for index in range(100):
        turn = store.create_from_audio(
            b"audio",
            f"round-{index}.wav",
            1.0,
            kind="note_turn",
            note_id=note.id,
            turn_index=index,
        )
        store.attach_turn(note.id, turn.id)
        store.write_raw_transcript(turn.id, f"round {index} asr")
        store.append_turn_to_note(note.id, turn.id, f"round {index} asr")
    detail = client.get(f"/api/notes/{note.id}").json()
    assert detail["turn_count"] == 100
    assert len(detail["turns"]) == 100
    assert all(turn["asr_draft"] is None for turn in detail["turns"])
    assert all(turn["polished_draft"] is None for turn in detail["turns"])
    assert detail["final_text"].startswith("round 0 asr")
    assert detail["final_text"].endswith("round 99 asr")
    inspected = client.get(
        f"/api/notes/{note.id}/turns/{detail['turns'][41]['id']}"
    ).json()
    assert inspected["asr_draft"] == "round 41 asr"
    html = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(
        encoding="utf-8"
    )
    assert html.count('id="noteFinal"') == 1
    assert html.count('id="inspectorAsr"') == 0
    assert html.count('id="inspectorPolished"') == 1

