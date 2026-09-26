from __future__ import annotations

from pathlib import Path
import logging
import time
from typing import Optional, Literal
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from speech_tool.pipeline import Pipeline, CaptureConflict
from speech_tool.polish_quality import polish_quality_issue
from speech_tool.store import EventStore, NoteRevisionConflict, SessionRevisionConflict
from speech_tool.transcript_quality import is_noise_transcript

STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "web"


class TextUpdate(BaseModel):
    text: str
    transcript_revision: Optional[int] = None


class CopyPayload(BaseModel):
    text: str


class NoteCreate(BaseModel):
    title: str = ""


class NoteFinalUpdate(BaseModel):
    base_revision: int
    base_text: str
    text: str


class TurnDraftUpdate(BaseModel):
    text: str


class SessionCreate(BaseModel):
    course: str = ""
    title: str = ""


class SessionEnd(BaseModel):
    expected_chunk_count: int = Field(ge=0, le=10000)


class SessionPatch(BaseModel):
    base_revision: Optional[int] = None
    text: Optional[str] = None
    listener_notes: Optional[str] = None
    course: Optional[str] = None
    title: Optional[str] = None
    draft_chunk_ids: Optional[list[str]] = None


class QuestionRequest(BaseModel):
    mode: Literal["polish", "explore"] = "polish"
    use_context: bool = False
    preserve_draft: bool = False
    anchor_chunk_id: Optional[str] = None
    lecture_excerpt: str = ""
    confusion: str = ""
    refine: str = ""
    prior_question: str = ""


class SessionChunkView(BaseModel):
    id: str
    chunk_index: Optional[int]
    asr_status: str
    polish_status: str
    lm_version: Optional[str] = None
    duration_seconds: float = 0.0
    skip_merge: bool = False
    raw_transcript: Optional[str] = None
    cleanup_issue: Optional[str] = None


class NoteTurnView(BaseModel):
    id: str
    created_at: str
    turn_index: int
    duration_seconds: float
    state: str
    asr_status: str
    polish_status: str
    last_error: Optional[str]
    transcript_revision: int
    polished_revision: int
    polish_available: bool
    lm_version: Optional[str] = None
    preview: str = ""
    raw_transcript: Optional[str] = None
    polished_transcript: Optional[str] = None
    asr_draft: Optional[str] = None
    polished_draft: Optional[str] = None


class NoteView(BaseModel):
    id: str
    created_at: str
    updated_at: str
    title: str
    turn_count: int
    duration_seconds: float
    state: str
    final_text: Optional[str] = None
    final_revision: int = 0
    cleanup_provider_available: bool = True
    turns: list[NoteTurnView] = Field(default_factory=list)


class SessionView(BaseModel):
    revision: int = 0
    id: str
    created_at: str
    ended_at: Optional[str]
    course: str
    title: str
    status: str
    chunk_count: int
    duration_seconds: float
    state: str
    polish_status: str
    polish_available: bool = False
    polish_ready: bool = False
    polish_skipped: bool = False
    cleanup_provider_available: bool = True
    cleanup_cooldown_seconds: int = 0
    cleanup_provider_detail: Optional[str] = None
    display_text: Optional[str] = None
    raw_transcript: Optional[str] = None
    polished_transcript: Optional[str] = None
    listener_notes: Optional[str] = None
    latest_question: Optional[str] = None
    latest_question_suggestion: Optional[dict] = None
    chunks: list[SessionChunkView] = Field(default_factory=list)
    draft_chunk_ids: list[str] = Field(default_factory=list)
    last_error: Optional[str] = None
    transcribed_chunks: int = 0
    empty_transcript_chunks: int = 0
    transcription_pending_chunks: int = 0
    asr_failed_chunks: int = 0
    cleanup_failed_chunks: int = 0
    cleanup_pending_chunks: int = 0
    missing_chunk_indices: list[int] = Field(default_factory=list)
    duplicate_chunk_indices: list[int] = Field(default_factory=list)
    next_chunk_index: int = 0
    expected_chunk_count: int = 0
    completeness_known: bool = False


class EventView(BaseModel):
    id: str
    capture_id: Optional[str] = None
    created_at: str
    duration_seconds: float
    state: str
    asr_status: str
    polish_status: str
    asr_model: Optional[str]
    asr_version: Optional[str]
    lm_model: Optional[str]
    lm_version: Optional[str]
    last_error: Optional[str]
    asr_rtf: Optional[float]
    display_text: Optional[str] = None
    raw_transcript: Optional[str] = None
    polished_transcript: Optional[str] = None
    pending_append_transcripts: list[dict] = Field(default_factory=list)
    transcript_revision: int = 0
    polished_revision: int = 0
    edited_revision: int = 0
    polish_available: bool = False
    polish_ready: bool = False
    kind: str = "note"
    note_id: Optional[str] = None
    turn_index: Optional[int] = None
    session_id: Optional[str] = None
    chunk_index: Optional[int] = None


def create_app(store: EventStore, pipeline: Pipeline | None = None) -> FastAPI:
    pipe = pipeline or Pipeline(store)
    app = FastAPI(title="Speech Tool")
    if STATIC_DIR.exists():
        app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")

    def view(event_id: str, include_text: bool = False) -> EventView:
        event = store.get(event_id)
        raw = store.read_raw_transcript(event.id)
        polished = store.read_polished_transcript(event.id)
        display = store.display_text(event.id)
        current_polished = store.current_polished_transcript(event.id)
        polish_available = bool(
            event.asr_status == "completed"
            and event.polish_status == "completed"
            and event.lm_version not in {
                "timeout",
                "error",
                "empty",
                "provider_unavailable",
                "model_unavailable",
            }
            and current_polished
        )
        polish_ready = bool(
            polish_available
            and (raw or "").strip() != current_polished.strip()
        )
        return EventView(
            id=event.id,
            capture_id=event.capture_id,
            created_at=event.created_at,
            duration_seconds=event.duration_seconds,
            state=event.state.value,
            asr_status=event.asr_status,
            polish_status=event.polish_status,
            asr_model=event.asr_model,
            asr_version=event.asr_version,
            lm_model=event.lm_model,
            lm_version=event.lm_version,
            last_error=event.last_error,
            asr_rtf=event.asr_rtf,
            display_text=display,
            raw_transcript=raw if include_text else None,
            polished_transcript=polished if include_text else None,
            pending_append_transcripts=(
                store.pending_segment_transcripts(event.id) if include_text else []
            ),
            transcript_revision=event.transcript_revision,
            polished_revision=event.polished_revision,
            edited_revision=event.edited_revision,
            polish_available=polish_available,
            polish_ready=polish_ready,
            kind=event.kind,
            note_id=event.note_id,
            turn_index=event.turn_index,
            session_id=event.session_id,
            chunk_index=event.chunk_index,
        )

    def turn_view(event_id: str, include_text: bool = False) -> NoteTurnView:
        event = store.get(event_id)
        raw = store.read_raw_transcript(event_id)
        polished = store.current_polished_transcript(event_id)
        polish_available = bool(
            event.polish_status == "completed"
            and event.lm_version
            not in {
                "timeout",
                "error",
                "empty",
                "provider_unavailable",
                "model_unavailable",
            }
            and polished is not None
        )
        return NoteTurnView(
            id=event.id,
            created_at=event.created_at,
            turn_index=event.turn_index or 0,
            duration_seconds=event.duration_seconds,
            state=event.state.value,
            asr_status=event.asr_status,
            polish_status=event.polish_status,
            last_error=event.last_error,
            transcript_revision=event.transcript_revision,
            polished_revision=event.polished_revision,
            polish_available=polish_available,
            lm_version=event.lm_version,
            preview=(raw or "").strip().replace("\n", " ")[:120],
            raw_transcript=raw if include_text else None,
            polished_transcript=polished if include_text else None,
            asr_draft=store.read_asr_draft(event_id) if include_text else None,
            polished_draft=(
                store.read_polished_draft(event_id) if include_text else None
            ),
        )

    def note_view(note_id: str, include_turns: bool = False) -> NoteView:
        note = store.get_note(note_id)
        turns = [store.get(event_id) for event_id in note.turn_ids]
        duration = sum(event.duration_seconds or 0 for event in turns)
        if not turns:
            note_state = "empty"
        elif any(event.asr_status == "failed" for event in turns):
            note_state = "transcription_failed"
        elif any(event.asr_status != "completed" for event in turns):
            note_state = "transcribing"
        elif any(
            event.polish_status in {"pending", "running"} for event in turns
        ):
            note_state = "polishing"
        elif any(event.polish_status == "failed" for event in turns):
            note_state = "polishing_failed"
        else:
            note_state = "completed"
        final_text = None
        final_revision = note.final_revision
        if include_turns:
            final_text, final_revision = store.read_note_final(note_id)
        provider = pipe.polish_provider_status()
        return NoteView(
            id=note.id,
            created_at=note.created_at,
            updated_at=note.updated_at,
            title=note.title,
            turn_count=len(note.turn_ids),
            duration_seconds=duration,
            state=note_state,
            final_text=final_text,
            final_revision=final_revision,
            cleanup_provider_available=bool(provider.get("available", True)),
            turns=(
                [turn_view(event.id, include_text=False) for event in turns]
                if include_turns
                else []
            ),
        )

    def session_view(session_id: str, include_text: bool = False) -> SessionView:
        session = store.get_session(session_id)
        chunks = []
        chunk_views: list[SessionChunkView] = []
        duration = 0.0
        last_error = None
        worst = "completed"
        rank = {
            "transcription_failed": 4,
            "polishing_failed": 3,
            "transcribing": 2,
            "polishing": 2,
            "captured": 2,
            "transcribed": 1,
            "completed": 0,
        }
        worst_n = 0
        transcribed = asr_failed = cleanup_failed = cleanup_pending = 0
        empty_transcript = transcription_pending = 0
        indices = []
        for event_id in session.chunk_ids:
            event = store.get(event_id)
            chunks.append(event)
            raw = store.read_raw_transcript(event.id) or ''
            cleaned = store.current_polished_transcript(event.id) or ''
            issue = polish_quality_issue(raw, cleaned) if cleaned else None
            transcribed += int(event.asr_status == 'completed' and bool(raw.strip()))
            empty_transcript += int(event.asr_status == 'completed' and not raw.strip())
            transcription_pending += int(event.asr_status in {'pending', 'running'})
            asr_failed += int(event.asr_status == 'failed')
            cleanup_failed += int(event.polish_status == 'failed' or bool(issue))
            cleanup_pending += int(event.asr_status == 'completed' and event.polish_status in {'pending', 'running'})
            if event.chunk_index is not None and 0 <= event.chunk_index < 10000:
                indices.append(event.chunk_index)
            if include_text:
                chunk_views.append(
                    SessionChunkView(
                        id=event.id,
                        chunk_index=event.chunk_index,
                        asr_status=event.asr_status,
                        polish_status=event.polish_status,
                        lm_version=event.lm_version,
                        duration_seconds=event.duration_seconds or 0,
                        skip_merge=is_noise_transcript(
                            raw or "", event.duration_seconds or 0
                        ),
                        raw_transcript=raw,
                        cleanup_issue=issue,
                    )
                )
            duration += event.duration_seconds or 0
            state = event.state.value
            n = rank.get(state, 1)
            if n > worst_n:
                worst_n = n
                worst = state
            if event.last_error:
                last_error = event.last_error
        if not chunks:
            worst = session.status if session.status == "open" else "completed"
        if not chunks:
            polish_status = "pending"
        elif cleanup_failed:
            polish_status = "failed"
        elif all(
            e.polish_status == "completed"
            and e.polished_revision == e.transcript_revision
            for e in chunks
        ):
            polish_status = "completed"
        elif any(e.polish_status == "running" for e in chunks):
            polish_status = "running"
        else:
            polish_status = "pending"
        raw_text = store.session_raw_text(session_id)
        polished_text = store.session_polished_text(session_id)
        polish_available = bool(
            polish_status == "completed"
            and polished_text
            and all(
                e.lm_version
                not in {
                    "timeout",
                    "error",
                    "empty",
                    "provider_unavailable",
                    "model_unavailable",
                }
                for e in chunks
            )
        )
        polish_ready = bool(
            polish_available and polished_text.strip() != raw_text.strip()
        )
        provider = pipe.polish_provider_status()
        next_index = max(indices, default=-1) + 1
        expected = max(session.expected_chunk_count, next_index)
        present = set(indices)
        return SessionView(
            revision=session.revision,
            id=session.id,
            created_at=session.created_at,
            ended_at=session.ended_at,
            course=session.course,
            title=session.title,
            status=session.status,
            chunk_count=len(session.chunk_ids),
            duration_seconds=duration,
            state=worst,
            polish_status=polish_status,
            polish_available=polish_available,
            polish_ready=polish_ready,
            polish_skipped=bool(cleanup_failed),
            cleanup_provider_available=bool(provider.get("available", True)),
            cleanup_cooldown_seconds=int(provider.get("cooldown_remaining_seconds") or 0),
            cleanup_provider_detail=provider.get("last_detail"),
            transcribed_chunks=transcribed,
            empty_transcript_chunks=empty_transcript,
            transcription_pending_chunks=transcription_pending,
            asr_failed_chunks=asr_failed,
            cleanup_failed_chunks=cleanup_failed,
            cleanup_pending_chunks=cleanup_pending,
            missing_chunk_indices=[i for i in range(expected) if i not in present],
            duplicate_chunk_indices=sorted(i for i in present if indices.count(i) > 1),
            next_chunk_index=max(next_index, session.expected_chunk_count),
            expected_chunk_count=expected,
            completeness_known=bool(session.expected_chunk_count and len(indices) == len(chunks)),
            display_text=store.session_display_text(session_id) if include_text else None,
            raw_transcript=raw_text if include_text else None,
            polished_transcript=polished_text if include_text else None,
            listener_notes=store.read_listener_notes(session_id) if include_text else None,
            latest_question=store.latest_question(session_id) if include_text else None,
            latest_question_suggestion=store.latest_question_suggestion(session_id) if include_text else None,
            chunks=chunk_views,
            draft_chunk_ids=[e.id for e in store.session_chunks(session_id) if store.read_raw_transcript(e.id)],
            last_error=last_error,
        )

    @app.get("/", response_class=HTMLResponse)
    def index():
        html = STATIC_DIR / "index.html"
        return HTMLResponse(
            html.read_text(encoding="utf-8"),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/health")
    def health():
        polish = pipe.polish_provider_status()
        return {
            "ok": True,
            "app": "speech-tool",
            "protocol": 2,
            "audio_archive_protocol": 1,
            "polish": polish,
        }

    @app.get("/api/notes")
    def list_notes():
        return [note_view(note.id) for note in store.list_notes()]

    @app.post("/api/notes")
    def create_note(body: NoteCreate):
        note = store.create_note(body.title)
        return note_view(note.id, include_turns=True)

    @app.get("/api/notes/{note_id}")
    def get_note(note_id: str):
        try:
            return note_view(note_id, include_turns=True)
        except FileNotFoundError:
            raise HTTPException(404, "Note not found")

    @app.patch("/api/notes/{note_id}")
    def update_note_final(note_id: str, body: NoteFinalUpdate):
        try:
            text, revision = store.update_note_final(
                note_id,
                body.base_revision,
                body.base_text,
                body.text,
            )
            return {"id": note_id, "final_text": text, "final_revision": revision}
        except FileNotFoundError:
            raise HTTPException(404, "Note not found")
        except NoteRevisionConflict as exc:
            raise HTTPException(
                409,
                {
                    "message": str(exc),
                    "final_text": exc.text,
                    "final_revision": exc.revision,
                },
            )

    @app.post("/api/notes/{note_id}/turns")
    async def create_note_turn(note_id: str, file: UploadFile = File(...)):
        payload = await file.read()
        tmp = store.events_path / "_incoming"
        tmp.mkdir(exist_ok=True)
        incoming = tmp / f"{uuid4()}-{file.filename or 'audio.webm'}"
        incoming.write_bytes(payload)
        try:
            event_id = pipe.ingest_audio(
                payload,
                file.filename or "audio.webm",
                incoming,
                note_id=note_id,
            )
            return turn_view(event_id, include_text=True)
        except FileNotFoundError:
            raise HTTPException(404, "Note not found")
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            incoming.unlink(missing_ok=True)

    @app.get("/api/notes/{note_id}/turns/{event_id}")
    def get_note_turn(note_id: str, event_id: str):
        try:
            note = store.get_note(note_id)
            if event_id not in note.turn_ids:
                raise FileNotFoundError(event_id)
            return turn_view(event_id, include_text=True)
        except FileNotFoundError:
            raise HTTPException(404, "Turn not found")

    @app.patch("/api/events/{event_id}/drafts/{branch}")
    def update_turn_draft(
        event_id: str,
        branch: str,
        body: TurnDraftUpdate,
    ):
        try:
            store.write_turn_draft(event_id, branch, body.text)
            return turn_view(event_id, include_text=True)
        except FileNotFoundError:
            raise HTTPException(404, "Turn not found")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/notes/{note_id}/copy")
    def copy_note(note_id: str):
        try:
            return store.record_note_copy(note_id)
        except FileNotFoundError:
            raise HTTPException(404, "Note not found")

    @app.delete("/api/notes/{note_id}")
    def delete_note(note_id: str):
        try:
            store.delete_note(note_id)
        except FileNotFoundError:
            raise HTTPException(404, "Note not found")
        return {"ok": True}

    @app.get("/api/events")
    def list_events():
        return [
            view(e.id)
            for e in store.list_events()
            if e.kind in {"note", "note_turn"}
        ]

    @app.get("/api/sessions")
    def list_sessions():
        return [session_view(s.id) for s in store.list_sessions()]

    @app.post("/api/sessions")
    def create_session(body: SessionCreate):
        session = store.create_session(course=body.course, title=body.title)
        return session_view(session.id)

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str):
        try:
            return session_view(session_id, include_text=True)
        except FileNotFoundError:
            raise HTTPException(404, "Session not found")

    @app.patch("/api/sessions/{session_id}")
    def update_session_text(session_id: str, body: SessionPatch):
        try:
            store.patch_session(session_id, **body.model_dump())
            return session_view(session_id, include_text=True)
        except SessionRevisionConflict as exc:
            raise HTTPException(409, str(exc))
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except FileNotFoundError:
            raise HTTPException(404, "Session not found")

    @app.post("/api/sessions/{session_id}/copy")
    def copy_session(session_id: str, body: CopyPayload):
        try:
            return store.record_session_copy(session_id, body.text)
        except FileNotFoundError:
            raise HTTPException(404, "Session not found")

    @app.post("/api/sessions/{session_id}/end")
    def end_session(session_id: str, body: SessionEnd | None = None):
        try:
            store.end_session(session_id, body.expected_chunk_count if body else None)
            return session_view(session_id)
        except FileNotFoundError:
            raise HTTPException(404, "Session not found")

    @app.post("/api/sessions/{session_id}/reopen")
    def reopen_session(session_id: str):
        try:
            store.reopen_session(session_id)
            return session_view(session_id, include_text=True)
        except FileNotFoundError:
            raise HTTPException(404, "Session not found")

    @app.post("/api/sessions/{session_id}/retry-polish")
    def retry_session_polish(session_id: str):
        try:
            session = store.get_session(session_id)
        except FileNotFoundError:
            raise HTTPException(404, "Session not found")
        for event_id in session.chunk_ids:
            event = store.get(event_id)
            suspect = polish_quality_issue(store.read_raw_transcript(event_id) or '', store.current_polished_transcript(event_id) or '')
            if event.polish_status not in {'pending', 'running'} and (suspect or event.polish_status == 'failed'):
                try:
                    pipe.retry_polish(event_id)
                except Exception:
                    continue
        return session_view(session_id, include_text=True)

    @app.post('/api/sessions/{session_id}/retry-transcription')
    def retry_session_transcription(session_id: str):
        try:
            session = store.get_session(session_id)
        except FileNotFoundError:
            raise HTTPException(404, 'Session not found')
        for event_id in session.chunk_ids:
            if store.get(event_id).asr_status == 'failed':
                pipe.retry_asr(event_id)
        return session_view(session_id, include_text=True)

    @app.post("/api/sessions/{session_id}/questions")
    def draft_session_question(session_id: str, body: QuestionRequest):
        from datetime import datetime, timezone

        from speech_tool.question import draft_question, relevant_context_indices

        try:
            session = store.get_session(session_id)
        except FileNotFoundError:
            raise HTTPException(404, "Session not found")
        source_chunks = store.session_chunks(session_id)
        confusion = body.confusion.strip() or store.read_listener_notes(session_id)
        context_source = "Selected lecture anchor"
        if body.anchor_chunk_id:
            ids = [e.id for e in source_chunks]
            if body.anchor_chunk_id not in ids:
                raise HTTPException(400, "Question anchor belongs to another lecture")
            source_chunks = source_chunks[max(0, ids.index(body.anchor_chunk_id) - 1):ids.index(body.anchor_chunk_id) + 1]
        else:
            indices, context_source = relevant_context_indices(
                [store.read_raw_transcript(e.id) or "" for e in source_chunks], confusion)
            source_chunks = [source_chunks[i] for i in indices]
        lecture = "\n\n".join(store.read_raw_transcript(e.id) or "" for e in source_chunks)
        if body.lecture_excerpt.strip():
            lecture = body.lecture_excerpt[:6000]
            source_chunks = []  # Editable selected text has no exact raw-event attribution.
            context_source = "Selected lecture text"
        previous_saved_question = store.latest_question(session_id)
        if not body.use_context:
            lecture, source_chunks, context_source = "", [], "Your question only"
        request_id = str(uuid4())
        started = time.monotonic()
        logger = logging.getLogger("speech_tool.questions")
        logger.warning("question started request=%s session=%s", request_id, session_id)
        try:
            result = draft_question(
                confusion=confusion,
                lecture=lecture,
                memory="",
                prior_question=body.prior_question,
                refine=body.refine,
                polisher=pipe.polisher,
                mode=body.mode,
            )
        except ValueError as exc:
            logger.warning("question invalid request=%s", request_id)
            raise HTTPException(400, str(exc))
        except Exception:
            logger.warning("question failed request=%s elapsed=%.2f", request_id, time.monotonic() - started)
            raise HTTPException(502, f"Question generation failed (reference {request_id})")
        if result.version in {
            "timeout",
            "error",
            "empty",
            "provider_unavailable",
            "model_unavailable",
        } or not result.text.strip():
            logger.warning("question %s request=%s elapsed=%.2f model=%s", result.version, request_id, time.monotonic() - started, result.model)
            provider_down = result.version in {"provider_unavailable", "model_unavailable"}
            raise HTTPException(
                504 if result.version == "timeout" else 502,
                (
                    "Question helper is unavailable right now"
                    if provider_down
                    else (
                        "AI took too long"
                        if result.version == "timeout"
                        else "AI did not return a usable question"
                    )
                )
                + f" (reference {request_id})",
            )
        logger.warning("question ready request=%s elapsed=%.2f model=%s", request_id, time.monotonic() - started, result.model)
        return store.append_question(
            session_id,
            {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "session_id": session_id,
                "source_event_ids": [e.id for e in source_chunks],
                "lecture_excerpt": body.lecture_excerpt,
                "confusion": confusion,
                "refine": body.refine,
                "question": result.text,
                "model": result.model,
                "version": result.version,
                "context_source": context_source,
                "mode": body.mode,
                "request_id": request_id,
                "elapsed_seconds": round(time.monotonic() - started, 2),
                "display": not body.preserve_draft and store.latest_question(session_id) == previous_saved_question,
            },
        )

    @app.post("/api/sessions/{session_id}/questions/edit")
    def save_question_edit(session_id: str, body: CopyPayload):
        from datetime import datetime, timezone
        try:
            return store.append_question(session_id, {"question": body.text, "source": "user_edit",
                "created_at": datetime.now(timezone.utc).isoformat(), "session_id": session_id})
        except FileNotFoundError:
            raise HTTPException(404, "Session not found")

    @app.delete("/api/sessions/{session_id}")
    def delete_session(session_id: str):
        try:
            store.delete_session(session_id)
        except FileNotFoundError:
            raise HTTPException(404, "Session not found")
        return {"ok": True}

    @app.get("/api/events/{event_id}")
    def get_event(event_id: str):
        try:
            return view(event_id, include_text=True)
        except FileNotFoundError:
            raise HTTPException(404, "Event not found")

    @app.get("/api/events/{event_id}/audio")
    def get_audio(event_id: str):
        try:
            event = store.get(event_id)
        except FileNotFoundError:
            raise HTTPException(404, "Event not found")
        try:
            path = store.audio_path(event)
        except (ValueError, OSError):
            raise HTTPException(503, "Audio reference is missing or failed integrity verification")
        return FileResponse(path, filename=path.name)

    @app.post("/api/events")
    async def create_event(
        file: UploadFile = File(...),
        append_to: Optional[str] = None,
        note_id: Optional[str] = None,
        session_id: Optional[str] = None,
        chunk_index: Optional[int] = None,
        capture_id: Optional[str] = None,
    ):
        payload = await file.read()
        tmp = store.events_path / "_incoming"
        tmp.mkdir(exist_ok=True)
        incoming = tmp / f"{uuid4()}-{file.filename or 'audio.webm'}"
        incoming.write_bytes(payload)
        try:
            event_id = pipe.ingest_audio(
                payload,
                file.filename or "audio.webm",
                incoming,
                append_to=append_to,
                note_id=note_id,
                session_id=session_id,
                chunk_index=chunk_index,
                capture_id=capture_id,
            )
        except CaptureConflict as exc:
            incoming.unlink(missing_ok=True)
            raise HTTPException(409, str(exc)) from exc
        except Exception as exc:
            incoming.unlink(missing_ok=True)
            raise HTTPException(400, str(exc)) from exc
        incoming.unlink(missing_ok=True)
        return view(event_id)

    @app.patch("/api/events/{event_id}")
    def update_text(event_id: str, body: TextUpdate):
        try:
            store.write_edited_transcript(
                event_id,
                body.text,
                transcript_revision=body.transcript_revision,
            )
            return view(event_id, include_text=True)
        except FileNotFoundError:
            raise HTTPException(404, "Event not found")
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/events/{event_id}/copy")
    def copy_event(event_id: str, body: CopyPayload):
        try:
            return store.record_copy_correction(event_id, body.text)
        except FileNotFoundError:
            raise HTTPException(404, "Event not found")
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/events/{event_id}/retry-asr")
    def retry_asr(event_id: str):
        try:
            pipe.retry_asr(event_id)
            return view(event_id)
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/events/{event_id}/retranscribe")
    def retranscribe(event_id: str):
        try:
            pipe.retranscribe(event_id)
            return view(event_id)
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/events/{event_id}/retry-polish")
    def retry_polish(event_id: str):
        try:
            pipe.retry_polish(event_id)
            return view(event_id)
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.delete("/api/events/{event_id}")
    def delete_event(event_id: str):
        try:
            store.delete(event_id)
        except FileNotFoundError:
            raise HTTPException(404, "Event not found")
        return {"ok": True}

    app.state.store = store
    app.state.pipeline = pipe
    return app
