from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class EventState(str, Enum):
    CAPTURED = "captured"
    TRANSCRIBING = "transcribing"
    TRANSCRIPTION_FAILED = "transcription_failed"
    TRANSCRIBED = "transcribed"
    POLISHING = "polishing"
    POLISHING_FAILED = "polishing_failed"
    COMPLETED = "completed"


class SpeechEvent(BaseModel):
    capture_id: Optional[str] = None
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    duration_seconds: float = 0.0
    audio_filename: str = "audio.wav"
    audio_sha256: str = ""
    asr_status: str = "pending"
    polish_status: str = "pending"
    state: EventState = EventState.CAPTURED
    asr_model: Optional[str] = None
    asr_version: Optional[str] = None
    lm_model: Optional[str] = None
    lm_version: Optional[str] = None
    last_error: Optional[str] = None
    asr_rtf: Optional[float] = None
    asr_elapsed_seconds: Optional[float] = None
    correction_count: int = 0
    transcript_revision: int = 0
    polished_revision: int = 0
    edited_revision: int = 0
    kind: str = "note"
    note_id: Optional[str] = None
    turn_index: Optional[int] = None
    session_id: Optional[str] = None
    chunk_index: Optional[int] = None

    def derived_state(self) -> EventState:
        if self.asr_status == "pending":
            return EventState.CAPTURED
        if self.asr_status == "running":
            return EventState.TRANSCRIBING
        if self.asr_status == "failed":
            return EventState.TRANSCRIPTION_FAILED
        if self.asr_status == "completed" and self.polish_status == "running":
            return EventState.TRANSCRIBED
        if self.polish_status == "failed":
            return EventState.POLISHING_FAILED
        if self.polish_status == "completed":
            return EventState.COMPLETED
        return EventState.TRANSCRIBED


class LectureSession(BaseModel):
    revision: int = 0
    expected_chunk_count: int = Field(default=0, ge=0, le=10000)
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    ended_at: Optional[str] = None
    course: str = ""
    title: str = ""
    status: str = "open"
    chunk_ids: list[str] = Field(default_factory=list)
    draft_chunk_ids: list[str] = Field(default_factory=list)


class NoteDocument(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    title: str = ""
    turn_ids: list[str] = Field(default_factory=list)
    merged_turn_ids: list[str] = Field(default_factory=list)
    final_revision: int = 0
