from __future__ import annotations

import hashlib
import json
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4
from functools import wraps

from speech_tool.config import events_dir, notes_dir, sessions_dir
from speech_tool.corrections import build_correction
from speech_tool.lexicon import course_key
from speech_tool.transcript_quality import is_noise_transcript
from speech_tool.models import EventState, LectureSession, NoteDocument, SpeechEvent

RAW_TRANSCRIPT = "transcript.raw.txt"
POLISHED_TRANSCRIPT = "transcript.polished.txt"
EDITED_TRANSCRIPT = "transcript.edited.txt"
ASR_EDITED_TRANSCRIPT = "transcript.asr.edited.txt"
POLISHED_EDITED_TRANSCRIPT = "transcript.polished.edited.txt"
QUESTIONS_JSONL = "questions.jsonl"
LISTENER_NOTES = "listener_notes.txt"
CORRECTIONS_JSONL = "corrections.jsonl"
EVENT_JSON = "event.json"
NOTE_JSON = "note.json"
NOTE_FINAL = "note.final.edited.txt"


class NoteRevisionConflict(RuntimeError):
    def __init__(self, text: str, revision: int):
        super().__init__("Note changed while editing")
        self.text = text
        self.revision = revision


class SessionRevisionConflict(RuntimeError):
    pass


def session_locked(method):
    @wraps(method)
    def run(self, *args, **kwargs):
        with self._meta_lock:
            return method(self, *args, **kwargs)
    return run


class EventStore:
    def __init__(self, root: Path):
        self.root = root
        self.events_path = events_dir(root)
        self.sessions_path = sessions_dir(root)
        self.notes_path = notes_dir(root)
        self._meta_lock = threading.RLock()

    def _dir(self, event_id: str) -> Path:
        return self.events_path / event_id

    def create_from_audio(
        self,
        audio_bytes: bytes,
        filename: str,
        duration_seconds: float,
        kind: str = "note",
        note_id: str | None = None,
        turn_index: int | None = None,
        session_id: str | None = None,
        chunk_index: int | None = None,
        capture_id: str | None = None,
    ) -> SpeechEvent:
        event = SpeechEvent(
            capture_id=capture_id,
            duration_seconds=duration_seconds,
            kind=kind,
            note_id=note_id,
            turn_index=turn_index,
            session_id=session_id,
            chunk_index=chunk_index,
        )
        dest = self._dir(event.id)
        dest.mkdir(parents=True, exist_ok=False)
        suffix = Path(filename).suffix.lower() or ".webm"
        audio_filename = f"audio{suffix}"
        audio_path = dest / audio_filename
        audio_path.write_bytes(audio_bytes)
        event.audio_filename = audio_filename
        event.audio_sha256 = sha256_file(audio_path)
        event.asr_status = "pending"
        event.polish_status = "pending"
        event.state = EventState.CAPTURED
        self._write_event(event)
        return event

    def get(self, event_id: str) -> SpeechEvent:
        with self._meta_lock:
            path = self._dir(event_id) / EVENT_JSON
            if not path.exists():
                raise FileNotFoundError(event_id)
            data = json.loads(path.read_text(encoding="utf-8"))
            return SpeechEvent.model_validate(data)

    def save(self, event: SpeechEvent) -> None:
        with self._meta_lock:
            existing = self._dir(event.id) / event.audio_filename
            if existing.exists():
                current = sha256_file(existing)
                if event.audio_sha256 and current != event.audio_sha256:
                    raise RuntimeError("Refusing to save event: raw audio hash changed")
                event.audio_sha256 = current
            event.state = event.derived_state()
            self._write_event(event)

    def update_event(
        self,
        event_id: str,
        update: Callable[[SpeechEvent], None],
    ) -> SpeechEvent:
        with self._meta_lock:
            event = self.get(event_id)
            update(event)
            self.save(event)
            return event

    def list_events(self) -> list[SpeechEvent]:
        events: list[SpeechEvent] = []
        for child in self.events_path.iterdir():
            meta = child / EVENT_JSON
            if meta.exists():
                events.append(
                    SpeechEvent.model_validate(
                        json.loads(meta.read_text(encoding="utf-8"))
                    )
                )
        events.sort(key=lambda e: e.created_at, reverse=True)
        return events

    def _note_dir(self, note_id: str) -> Path:
        return self.notes_path / note_id

    def create_note(self, title: str = "") -> NoteDocument:
        note = NoteDocument(title=title.strip())
        if not note.title:
            note.title = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
        dest = self._note_dir(note.id)
        dest.mkdir(parents=True, exist_ok=False)
        self._write_note(note)
        self._write_note_final(note.id, "")
        return note

    def get_note(self, note_id: str) -> NoteDocument:
        with self._meta_lock:
            path = self._note_dir(note_id) / NOTE_JSON
            if not path.exists():
                raise FileNotFoundError(note_id)
            return NoteDocument.model_validate(
                json.loads(path.read_text(encoding="utf-8"))
            )

    def save_note(self, note: NoteDocument) -> None:
        with self._meta_lock:
            note.updated_at = datetime.now(timezone.utc).isoformat()
            self._write_note(note)

    def note_final_path(self, note_id: str) -> Path:
        return self._note_dir(note_id) / NOTE_FINAL

    def _write_note_final(self, note_id: str, text: str) -> None:
        path = self.note_final_path(note_id)
        tmp = path.with_suffix(".txt.tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)

    def _seed_note_final(self, note: NoteDocument) -> tuple[NoteDocument, str]:
        path = self.note_final_path(note.id)
        if path.exists():
            return note, path.read_text(encoding="utf-8")
        parts: list[str] = []
        merged: list[str] = []
        for event_id in note.turn_ids:
            text = self.read_asr_draft(event_id)
            if text.strip():
                parts.append(text.strip())
                merged.append(event_id)
        text = "\n\n".join(parts)
        self._write_note_final(note.id, text)
        note.merged_turn_ids = merged
        if text:
            note.final_revision += 1
        self.save_note(note)
        return note, text

    def read_note_final(self, note_id: str) -> tuple[str, int]:
        with self._meta_lock:
            note = self.get_note(note_id)
            note, text = self._seed_note_final(note)
            return text, note.final_revision

    def append_turn_to_note(
        self,
        note_id: str,
        event_id: str,
        text: str,
    ) -> tuple[str, int]:
        with self._meta_lock:
            note = self.get_note(note_id)
            note, current = self._seed_note_final(note)
            if event_id in note.merged_turn_ids:
                return current, note.final_revision
            chunk = text.strip()
            merged = (
                f"{current.rstrip()}\n\n{chunk}".strip()
                if current.strip() and chunk
                else (current or chunk)
            )
            self._write_note_final(note_id, merged)
            note.merged_turn_ids.append(event_id)
            note.final_revision += 1
            self.save_note(note)
            return merged, note.final_revision

    def update_note_final(
        self,
        note_id: str,
        base_revision: int,
        base_text: str,
        text: str,
    ) -> tuple[str, int]:
        with self._meta_lock:
            note = self.get_note(note_id)
            note, current = self._seed_note_final(note)
            if note.final_revision == base_revision and current == base_text:
                updated = text
            elif current.startswith(base_text):
                suffix = current[len(base_text) :]
                if not base_text and text.strip() and suffix.strip():
                    updated = f"{text.rstrip()}\n\n{suffix.lstrip()}"
                else:
                    updated = text.rstrip() + suffix
            else:
                raise NoteRevisionConflict(current, note.final_revision)
            if updated != current:
                self._write_note_final(note_id, updated)
                note.final_revision += 1
                self.save_note(note)
            return updated, note.final_revision

    def attach_turn(self, note_id: str, event_id: str) -> NoteDocument:
        with self._meta_lock:
            note = self.get_note(note_id)
            if event_id not in note.turn_ids:
                note.turn_ids.append(event_id)
            turn_index = note.turn_ids.index(event_id)
            self.update_event(
                event_id,
                lambda event: self._mark_note_turn(
                    event,
                    note_id,
                    turn_index,
                ),
            )
            self.save_note(note)
            return note

    @staticmethod
    def _mark_note_turn(
        event: SpeechEvent,
        note_id: str,
        turn_index: int,
    ) -> None:
        event.kind = "note_turn"
        event.note_id = note_id
        event.turn_index = turn_index

    def _ensure_legacy_notes(self) -> None:
        with self._meta_lock:
            for event in self.list_events():
                if event.kind not in {"note", "note_turn"}:
                    continue
                note_id = event.note_id or event.id
                note_path = self._note_dir(note_id) / NOTE_JSON
                if not note_path.exists():
                    self._note_dir(note_id).mkdir(parents=True, exist_ok=True)
                    title = datetime.fromisoformat(event.created_at).astimezone().strftime(
                        "%Y-%m-%d %H:%M"
                    )
                    self._write_note(
                        NoteDocument(
                            id=note_id,
                            created_at=event.created_at,
                            updated_at=event.created_at,
                            title=title,
                            turn_ids=[event.id],
                        )
                    )
                note = self.get_note(note_id)
                if event.id not in note.turn_ids:
                    note.turn_ids.append(event.id)
                    self.save_note(note)
                turn_index = note.turn_ids.index(event.id)
                if (
                    event.note_id != note_id
                    or event.turn_index != turn_index
                    or event.kind != "note_turn"
                ):
                    self.update_event(
                        event.id,
                        lambda current, nid=note_id, idx=turn_index: (
                            self._mark_note_turn(current, nid, idx)
                        ),
                    )

    def list_notes(self) -> list[NoteDocument]:
        self._ensure_legacy_notes()
        notes: list[NoteDocument] = []
        for child in self.notes_path.iterdir():
            meta = child / NOTE_JSON
            if meta.exists():
                notes.append(
                    NoteDocument.model_validate(
                        json.loads(meta.read_text(encoding="utf-8"))
                    )
                )
        notes.sort(key=lambda note: note.updated_at, reverse=True)
        return notes

    def delete_note(self, note_id: str) -> None:
        note = self.get_note(note_id)
        for event_id in note.turn_ids:
            if self._dir(event_id).exists():
                self.delete(event_id)
        shutil.rmtree(self._note_dir(note_id))

    def _write_note(self, note: NoteDocument) -> None:
        path = self._note_dir(note.id) / NOTE_JSON
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(note.model_dump(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(path)

    def audio_path(self, event: SpeechEvent) -> Path:
        original = self._dir(event.id) / event.audio_filename
        if original.exists():
            return original
        from .retention import archive_reference
        return archive_reference(self.root, event.id, event.audio_sha256)

    def raw_transcript_path(self, event_id: str) -> Path:
        return self._dir(event_id) / RAW_TRANSCRIPT

    def polished_transcript_path(self, event_id: str) -> Path:
        return self._dir(event_id) / POLISHED_TRANSCRIPT

    def write_raw_transcript(self, event_id: str, text: str) -> None:
        self._assert_audio_intact(event_id)
        self.raw_transcript_path(event_id).write_text(text, encoding="utf-8")

    @session_locked
    def write_polished_transcript(self, event_id: str, text: str) -> None:
        self._assert_audio_intact(event_id)
        self._versioned_text(self.polished_transcript_path(event_id), text)

    def edited_transcript_path(self, event_id: str) -> Path:
        return self._dir(event_id) / EDITED_TRANSCRIPT

    def write_edited_transcript(
        self,
        event_id: str,
        text: str,
        transcript_revision: int | None = None,
    ) -> None:
        self._assert_audio_intact(event_id)
        self.edited_transcript_path(event_id).write_text(text, encoding="utf-8")
        if transcript_revision is not None:
            self.update_event(
                event_id,
                lambda event: setattr(
                    event,
                    "edited_revision",
                    transcript_revision,
                ),
            )

    def read_edited_transcript(self, event_id: str) -> str | None:
        path = self.edited_transcript_path(event_id)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def asr_edited_transcript_path(self, event_id: str) -> Path:
        return self._dir(event_id) / ASR_EDITED_TRANSCRIPT

    def polished_edited_transcript_path(self, event_id: str) -> Path:
        return self._dir(event_id) / POLISHED_EDITED_TRANSCRIPT

    def read_asr_draft(self, event_id: str) -> str:
        path = self.asr_edited_transcript_path(event_id)
        if path.exists():
            return path.read_text(encoding="utf-8")
        legacy = self.read_edited_transcript(event_id)
        if legacy is not None:
            return legacy
        return self.read_raw_transcript(event_id) or ""

    def read_polished_draft(self, event_id: str) -> str | None:
        path = self.polished_edited_transcript_path(event_id)
        if path.exists():
            return path.read_text(encoding="utf-8")
        return self.current_polished_transcript(event_id)

    def write_turn_draft(self, event_id: str, branch: str, text: str) -> None:
        self._assert_audio_intact(event_id)
        if branch == "asr":
            path = self.asr_edited_transcript_path(event_id)
        elif branch == "polished":
            path = self.polished_edited_transcript_path(event_id)
        else:
            raise ValueError(f"Unknown draft branch: {branch}")
        path.write_text(text, encoding="utf-8")
        event = self.get(event_id)
        if event.note_id:
            self.save_note(self.get_note(event.note_id))

    def preferred_turn_text(self, event_id: str) -> tuple[str, str]:
        polished = self.read_polished_draft(event_id)
        if polished is not None:
            return "polished", polished
        return "asr", self.read_asr_draft(event_id)

    def display_text(self, event_id: str) -> str:
        edited = self.read_edited_transcript(event_id)
        if edited is not None:
            return edited.strip()
        return (self.read_raw_transcript(event_id) or "").strip()

    def current_polished_transcript(self, event_id: str) -> str | None:
        event = self.get(event_id)
        polished = self.read_polished_transcript(event_id)
        if not polished:
            return None
        if event.transcript_revision == event.polished_revision:
            return polished
        return None

    def record_copy_correction(self, event_id: str, copied: str) -> dict:
        self._assert_audio_intact(event_id)
        polished = (
            self.current_polished_transcript(event_id)
            or self.read_raw_transcript(event_id)
            or ""
        )
        copied_text = copied
        event = self.get(event_id)
        self.write_edited_transcript(
            event_id,
            copied_text,
            transcript_revision=event.transcript_revision,
        )
        correction = build_correction(polished, copied_text)
        payload = {
            "id": str(uuid4()),
            "event_id": event_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "changed": correction.changed,
            "polished": correction.polished,
            "copied": correction.copied,
            "unified_diff": correction.unified_diff,
            "replacements": correction.replacements,
        }
        if correction.changed:
            line = json.dumps(payload, ensure_ascii=False)
            event_log = self._dir(event_id) / CORRECTIONS_JSONL
            with event_log.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            global_log = self.root / CORRECTIONS_JSONL
            global_log.parent.mkdir(parents=True, exist_ok=True)
            with global_log.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            self.update_event(
                event_id,
                lambda event: setattr(
                    event,
                    "correction_count",
                    (event.correction_count or 0) + 1,
                ),
            )
        return payload

    def record_note_copy(self, note_id: str) -> dict:
        note = self.get_note(note_id)
        copied, revision = self.read_note_final(note_id)
        baseline_parts: list[str] = []
        for event_id in note.turn_ids:
            baseline = (
                self.current_polished_transcript(event_id)
                or self.read_raw_transcript(event_id)
                or ""
            )
            if baseline.strip():
                baseline_parts.append(baseline.strip())
        correction = build_correction("\n\n".join(baseline_parts), copied)
        payload = {
            "id": str(uuid4()),
            "note_id": note_id,
            "final_revision": revision,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "changed": correction.changed,
            "polished": correction.polished,
            "copied": correction.copied,
            "unified_diff": correction.unified_diff,
            "replacements": correction.replacements,
        }
        if correction.changed:
            line = json.dumps(payload, ensure_ascii=False)
            with (self._note_dir(note_id) / CORRECTIONS_JSONL).open(
                "a", encoding="utf-8"
            ) as handle:
                handle.write(line + "\n")
            with (self.root / CORRECTIONS_JSONL).open(
                "a", encoding="utf-8"
            ) as handle:
                handle.write(line + "\n")
        return {
            "note_id": note_id,
            "text": copied,
            "final_revision": revision,
            "turn_count": len(note.turn_ids),
            "correction": payload,
        }

    def _append_correction(self, event_id: str, payload: dict) -> None:
        line = json.dumps(payload, ensure_ascii=False)
        with (self._dir(event_id) / CORRECTIONS_JSONL).open(
            "a", encoding="utf-8"
        ) as handle:
            handle.write(line + "\n")
        global_log = self.root / CORRECTIONS_JSONL
        global_log.parent.mkdir(parents=True, exist_ok=True)
        with global_log.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        self.update_event(
            event_id,
            lambda event: setattr(
                event,
                "correction_count",
                (event.correction_count or 0) + 1,
            ),
        )

    def append_raw_transcript(self, event_id: str, raw_chunk: str) -> str:
        self._assert_audio_intact(event_id)
        raw = (self.read_raw_transcript(event_id) or "").rstrip()
        chunk = raw_chunk.strip()
        merged = f"{raw}\n\n{chunk}".strip() if raw and chunk else (raw or chunk)
        self.raw_transcript_path(event_id).write_text(merged, encoding="utf-8")
        return merged

    def add_segment(self, event_id: str, audio_bytes: bytes, filename: str) -> Path:
        dest = self._dir(event_id) / "segments"
        dest.mkdir(parents=True, exist_ok=True)
        suffix = Path(filename).suffix.lower() or ".webm"
        n = len(list(dest.glob("seg-*"))) + 1
        path = dest / f"seg-{n:03d}{suffix}"
        path.write_bytes(audio_bytes)
        return path

    def write_segment_transcript(
        self,
        audio_path: Path,
        text: str,
        transcript_revision: int,
    ) -> Path:
        path = audio_path.with_suffix(".raw.json")
        path.write_text(
            json.dumps(
                {
                    "transcript_revision": transcript_revision,
                    "text": text.strip(),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path

    def pending_segment_transcripts(self, event_id: str) -> list[dict]:
        event = self.get(event_id)
        if self.read_edited_transcript(event_id) is None:
            return []
        segments = self._dir(event_id) / "segments"
        if not segments.exists():
            return []
        pending = []
        for path in sorted(segments.glob("seg-*.raw.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if int(payload.get("transcript_revision") or 0) > event.edited_revision:
                pending.append(payload)
        return pending

    def read_raw_transcript(self, event_id: str) -> str | None:
        path = self.raw_transcript_path(event_id)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def read_polished_transcript(self, event_id: str) -> str | None:
        path = self.polished_transcript_path(event_id)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def delete(self, event_id: str) -> None:
        shutil.rmtree(self._dir(event_id))

    def interrupt_inflight(self) -> list[SpeechEvent]:
        recovered = []
        for event in self.list_events():
            changed = False
            if event.asr_status == "running":
                event.asr_status = "pending"
                event.last_error = "Interrupted while transcribing; queued for retry"
                changed = True
            if event.polish_status == "running":
                event.polish_status = "pending"
                event.last_error = "Interrupted while polishing; queued for retry"
                changed = True
            if changed:
                self.save(event)
                recovered.append(event)
        return recovered

    def pending_work(self) -> list[tuple[str, str]]:
        jobs: list[tuple[str, str]] = []
        for event in self.list_events():
            if event.asr_status == "pending":
                jobs.append((event.id, "asr"))
            elif event.asr_status == "completed" and event.polish_status == "pending":
                jobs.append((event.id, "polish"))
        return jobs

    def _assert_audio_intact(self, event_id: str) -> None:
        event = self.get(event_id)
        path = self.audio_path(event)
        if not path.exists():
            raise RuntimeError("Raw audio missing")
        digest = sha256_file(path)
        if path.suffix.lower() == '.flac' and path != self._dir(event.id) / event.audio_filename:
            # audio_path verified the lossless archive against its manifest;
            # original byte hash remains immutable provenance, not a FLAC hash.
            return
        if event.audio_sha256 and digest != event.audio_sha256:
            raise RuntimeError("Raw audio was modified")

    def _write_event(self, event: SpeechEvent) -> None:
        path = self._dir(event.id) / EVENT_JSON
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(event.model_dump(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(path)

    def _session_dir(self, session_id: str) -> Path:
        return self.sessions_path / session_id

    def create_session(self, course: str = "", title: str = "") -> LectureSession:
        session = LectureSession(course=course.strip(), title=title.strip())
        if not session.title:
            session.title = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
        dest = self._session_dir(session.id)
        dest.mkdir(parents=True, exist_ok=False)
        self._write_session(session)
        return session

    def get_session(self, session_id: str) -> LectureSession:
        path = self._session_dir(session_id) / "session.json"
        if not path.exists():
            raise FileNotFoundError(session_id)
        return LectureSession.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def save_session(self, session: LectureSession) -> None:
        self._write_session(session)

    def list_sessions(self) -> list[LectureSession]:
        items: list[LectureSession] = []
        for child in self.sessions_path.iterdir():
            meta = child / "session.json"
            if meta.exists():
                items.append(
                    LectureSession.model_validate(
                        json.loads(meta.read_text(encoding="utf-8"))
                    )
                )
        items.sort(key=lambda s: s.created_at, reverse=True)
        return items

    def attach_chunk(self, session_id: str, event_id: str) -> LectureSession:
        with self._meta_lock:
            if self.get(event_id).session_id != session_id:
                raise ValueError("Chunk belongs to a different session")
            session = self.get_session(session_id)
            if event_id not in session.chunk_ids:
                session.chunk_ids.append(event_id)
            self._write_session(session)
            return session

    @session_locked
    def end_session(self, session_id: str, expected_chunk_count: int | None = None) -> LectureSession:
        session = self.get_session(session_id)
        if expected_chunk_count is not None:
            if not 0 <= expected_chunk_count <= 10000:
                raise ValueError('Invalid expected chunk count')
            session.expected_chunk_count = max(session.expected_chunk_count, expected_chunk_count)
        session.status = "ended"
        session.ended_at = datetime.now(timezone.utc).isoformat()
        self._write_session(session)
        # Derived full ASR file for Finder / editors; chunk files remain source of truth.
        self.materialize_session_raw_transcript(session_id)
        return session

    def session_raw_transcript_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / RAW_TRANSCRIPT

    def materialize_session_raw_transcript(self, session_id: str) -> dict:
        """Write the assembled ASR lecture text to one session-level file.

        Chunk ``events/<id>/transcript.raw.txt`` files remain the durable source
        of truth. This file is a convenience snapshot for opening or copying a
        path after class; it is regenerated on demand and when a session ends.
        """
        self.get_session(session_id)
        text = self.session_raw_text(session_id, skip_noise=True)
        path = self.session_raw_transcript_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".txt.tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
        return {
            "path": str(path.resolve()),
            "bytes": len(text.encode("utf-8")),
            "ready": bool(text.strip()),
            "kind": "asr",
        }

    @session_locked
    def reopen_session(self, session_id: str) -> LectureSession:
        session = self.get_session(session_id)
        session.status = "open"
        session.ended_at = None
        self._write_session(session)
        return session

    def delete_session(self, session_id: str) -> None:
        self.get_session(session_id)
        shutil.rmtree(self._session_dir(session_id))

    def session_display_text(self, session_id: str) -> str:
        session = self.get_session(session_id)
        edited = self._session_dir(session_id) / EDITED_TRANSCRIPT
        if edited.exists():
            text = edited.read_text(encoding="utf-8")
            # Legacy edits with no provenance cannot safely be auto-appended.
            merged = set(session.draft_chunk_ids or session.chunk_ids)
            extra = [self.read_raw_transcript(e.id).strip()
                     for e in self.session_chunks(session_id)
                     if e.id not in merged and self.read_raw_transcript(e.id)]
            return "\n\n".join([text, *extra]).strip()
        return self.session_raw_text(session.id, skip_noise=True)

    def session_chunks(self, session_id: str) -> list[SpeechEvent]:
        session = self.get_session(session_id)
        events = [self.get(i) for i in dict.fromkeys(session.chunk_ids)]
        if any(e.session_id != session_id for e in events):
            raise ValueError("Session contains a foreign chunk")
        return sorted(events, key=lambda e: (e.chunk_index if e.chunk_index is not None else 10**9, e.created_at, e.id))

    def patch_session(self, session_id: str, *, text=None, listener_notes=None,
                      course=None, title=None, draft_chunk_ids=None, base_revision=None):
        with self._meta_lock:
            session = self.get_session(session_id)
            if base_revision is not None and session.revision != base_revision:
                raise SessionRevisionConflict("Lecture changed in another tab. Your local draft is retained; reload after copying it.")
            if draft_chunk_ids is not None and not set(draft_chunk_ids).issubset(session.chunk_ids):
                raise ValueError("Draft includes chunks from another session")
            if text is not None:
                self.write_session_edited(session_id, text, draft_chunk_ids)
            if listener_notes is not None:
                self.write_listener_notes(session_id, listener_notes)
            session = self.update_session_meta(session_id, course, title)
            session.revision += 1
            self._write_session(session)
            return session

    def _versioned_text(self, path: Path, text: str) -> None:
        previous = path.read_text(encoding="utf-8") if path.exists() else ""
        if previous == text:
            return
        # Persist both sides before publishing. Never destroy an earlier edit.
        with path.with_name(path.name + ".history.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(),
                                     "before": previous, "after": text}, ensure_ascii=False) + "\n")
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)

    def session_raw_text(self, session_id: str, skip_noise: bool = False) -> str:
        session = self.get_session(session_id)
        parts = []
        for event in self.session_chunks(session_id):
            event_id = event.id
            text = self.read_raw_transcript(event_id) or ""
            if not text.strip():
                continue
            if skip_noise and is_noise_transcript(text, event.duration_seconds or 0):
                continue
            parts.append(text.strip())
        return "\n\n".join(parts).strip()

    def session_polished_text(self, session_id: str) -> str:
        from speech_tool.polish_quality import polish_quality_issue
        session = self.get_session(session_id)
        parts = []
        for event in self.session_chunks(session_id):
            event_id = event.id
            raw = self.read_raw_transcript(event_id) or ''
            cleaned = self.current_polished_transcript(event_id) or ''
            # Keep suspect historical output on disk; do not present it as
            # trustworthy cleanup. Raw text remains usable without a model call.
            text = raw if polish_quality_issue(raw, cleaned) else (cleaned or raw)
            if text.strip():
                parts.append(text.strip())
        return "\n\n".join(parts).strip()

    @session_locked
    def write_session_edited(
        self,
        session_id: str,
        text: str,
        draft_chunk_ids: list[str] | None = None,
    ) -> None:
        session = self.get_session(session_id)
        path = self._session_dir(session_id) / EDITED_TRANSCRIPT
        if draft_chunk_ids is not None and not set(draft_chunk_ids).issubset(session.chunk_ids):
            raise ValueError("Draft includes chunks from another session")
        self._versioned_text(path, text)
        if draft_chunk_ids is not None:
            session.draft_chunk_ids = list(dict.fromkeys(draft_chunk_ids))
            self._write_session(session)

    def listener_notes_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / LISTENER_NOTES

    def read_listener_notes(self, session_id: str) -> str:
        path = self.listener_notes_path(session_id)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    @session_locked
    def write_listener_notes(self, session_id: str, text: str) -> None:
        self.get_session(session_id)
        self._versioned_text(self.listener_notes_path(session_id), text)

    def questions_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / QUESTIONS_JSONL

    @session_locked
    def append_question(self, session_id: str, payload: dict) -> dict:
        self.get_session(session_id)
        line = json.dumps(payload, ensure_ascii=False)
        with self.questions_path(session_id).open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return payload

    def latest_question_suggestion(self, session_id: str) -> dict | None:
        path = self.questions_path(session_id)
        if path.exists():
            for line in reversed(path.read_text(encoding="utf-8").splitlines()):
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("model") and row.get("question"):
                    return row
        return None

    def latest_question(self, session_id: str) -> str:
        path = self.questions_path(session_id)
        if not path.exists():
            return ""
        last = ""
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("display", True):
                last = (row.get("question") or "").strip()
        return last

    def recent_lecture_memory(
        self,
        course: str,
        exclude_id: str,
        limit: int = 2,
    ) -> str:
        sessions = [item for item in self.list_sessions() if item.id != exclude_id]
        wanted = course_key(course)
        if not wanted:
            return ""
        sessions = [item for item in sessions if course_key(item.course or "") == wanted]
        parts: list[str] = []
        for item in sessions[:limit]:
            text = self.session_raw_text(item.id, skip_noise=True)[-800:]
            if text.strip():
                title = item.title or item.id[:8]
                parts.append(f"[{title}] {text.strip()}")
        return "\n\n".join(parts)

    @session_locked
    def update_session_meta(
        self, session_id: str, course: str | None = None, title: str | None = None
    ) -> LectureSession:
        session = self.get_session(session_id)
        if course is not None:
            session.course = course.strip()
        if title is not None:
            session.title = title.strip()
        self._write_session(session)
        return session

    def record_session_copy(self, session_id: str, copied: str) -> dict:
        polished = self.session_polished_text(session_id)
        self.write_session_edited(session_id, copied)
        correction = build_correction(polished, copied)
        payload = {
            "id": str(uuid4()),
            "session_id": session_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "changed": correction.changed,
            "polished": correction.polished,
            "copied": correction.copied,
            "unified_diff": correction.unified_diff,
            "replacements": correction.replacements,
        }
        if correction.changed:
            line = json.dumps(payload, ensure_ascii=False)
            with (self._session_dir(session_id) / CORRECTIONS_JSONL).open(
                "a", encoding="utf-8"
            ) as handle:
                handle.write(line + "\n")
            with (self.root / CORRECTIONS_JSONL).open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        return payload

    def _write_session(self, session: LectureSession) -> None:
        path = self._session_dir(session.id) / "session.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(session.model_dump(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(path)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
