from __future__ import annotations

import heapq
import threading
import logging
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from speech_tool.asr import AsrBackend, MlxWhisperAsr, default_asr
from speech_tool.config import (
    LECTURE_CHUNK_SECONDS,
    LECTURE_POLISH_TIMEOUT_SECONDS,
    OPENCODE_MODEL,
    POLISH_PROVIDER_COOLDOWN_SECONDS,
    POLISH_PROVIDER_FAILURE_STREAK,
    POLISH_RETRY_LIMIT,
    POLISH_TIMEOUT_SECONDS,
)
from speech_tool.media import ffprobe_duration, validate_duration
from speech_tool.polish import Polisher, OpencodePolisher, default_polisher
from speech_tool.store import EventStore
from speech_tool.transcript_quality import is_noise_transcript
from speech_tool.polish_quality import polish_quality_issue

NOTE_POLISH_PRIORITY = 0
LECTURE_POLISH_PRIORITY = 1
SOFT_POLISH_FAILURES = {
    "timeout",
    "error",
    "empty",
    "quality_rejected",
    "provider_unavailable",
    "model_unavailable",
}
PROVIDER_POLISH_FAILURES = {
    "timeout",
    "error",
    "empty",
    "provider_unavailable",
    "model_unavailable",
}


class CaptureConflict(ValueError):
    pass


class Pipeline:
    def __init__(
        self,
        store: EventStore,
        asr: AsrBackend | None = None,
        polisher: Polisher | None = None,
        auto_start: bool = True,
    ):
        self.store = store
        self.asr = asr or default_asr()
        self.polisher = polisher or default_polisher()
        self._lock = threading.Lock()
        self._commit_lock = threading.Lock()
        self._asr_busy: set[str] = set()
        self._polish_busy: set[str] = set()
        self._asr_queues: dict[str, deque] = defaultdict(deque)
        self._polish_queues: dict[str, deque] = defaultdict(deque)
        self._polish_heap: list[tuple[int, int, str]] = []
        self._polish_seq = 0
        self._polish_running = False
        self._polish_priority: dict[str, int] = {}
        self._asr_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="asr")
        self._polish_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="polish")
        self._polish_fail_streak = 0
        self._polish_cooldown_until = 0.0
        self._polish_provider_detail: str | None = None
        if auto_start:
            self.recover_and_resume()

    def polish_provider_status(self) -> dict:
        remaining = max(0.0, self._polish_cooldown_until - time.monotonic())
        return {
            "available": remaining <= 0,
            "cooldown_remaining_seconds": int(remaining),
            "consecutive_failures": self._polish_fail_streak,
            "last_detail": self._polish_provider_detail,
            "model": OPENCODE_MODEL,
        }

    def clear_polish_cooldown(self) -> None:
        self._polish_fail_streak = 0
        self._polish_cooldown_until = 0.0

    def _note_polish_outcome(self, version: str | None, detail: str | None) -> None:
        if version in PROVIDER_POLISH_FAILURES:
            self._polish_fail_streak += 1
            self._polish_provider_detail = detail or (
                f"AI cleanup failed ({version}); raw transcript preserved"
            )
            if self._polish_fail_streak >= max(POLISH_PROVIDER_FAILURE_STREAK, 1):
                self._polish_cooldown_until = (
                    time.monotonic() + max(POLISH_PROVIDER_COOLDOWN_SECONDS, 0)
                )
            return
        if version and version not in SOFT_POLISH_FAILURES:
            self.clear_polish_cooldown()
            self._polish_provider_detail = None

    def ingest_audio(
        self,
        audio_bytes: bytes,
        filename: str,
        tmp_path,
        append_to: str | None = None,
        note_id: str | None = None,
        session_id: str | None = None,
        chunk_index: int | None = None,
        capture_id: str | None = None,
    ) -> str:
        duration = ffprobe_duration(tmp_path)
        if note_id:
            note = self.store.get_note(note_id)
            validate_duration(duration)
            event = self.store.create_from_audio(
                audio_bytes,
                filename,
                duration,
                kind="note_turn",
                note_id=note_id,
                turn_index=len(note.turn_ids),
            )
            self.store.attach_turn(note_id, event.id)
            self.enqueue_asr(event.id)
            return event.id
        if session_id:
            with self.store._meta_lock:
                self.store.get_session(session_id)
                if capture_id:
                    import hashlib
                    for existing in self.store.list_events():
                        if existing.capture_id == capture_id:
                            if existing.session_id != session_id or existing.audio_sha256 != hashlib.sha256(audio_bytes).hexdigest():
                                raise CaptureConflict("Capture ID already used for different audio")
                            if existing.chunk_index != chunk_index:
                                raise CaptureConflict("Capture ID already used for another chunk index")
                            self.store.attach_chunk(session_id, existing.id)
                            return existing.id
                validate_duration(duration, LECTURE_CHUNK_SECONDS)
                if chunk_index is not None:
                    if not 0 <= chunk_index < 10000:
                        raise ValueError('Invalid lecture chunk index')
                    if any(e.chunk_index == chunk_index for e in self.store.session_chunks(session_id)):
                        raise CaptureConflict('Chunk index already stored; local audio retained for review')
                event = self.store.create_from_audio(
                    audio_bytes, filename, duration, kind="lecture_chunk",
                    session_id=session_id, chunk_index=chunk_index, capture_id=capture_id,
                )
                self.store.attach_chunk(session_id, event.id)
            self.enqueue_asr(event.id)
            return event.id
        validate_duration(duration)
        if append_to:
            existing = self.store.get(append_to)
            if existing.kind != "note":
                raise RuntimeError("Can only append onto a note")
            path = self.store.add_segment(append_to, audio_bytes, filename)
            self._submit_asr(
                append_to, lambda: self._run_append(append_to, path, duration)
            )
            return append_to
        event = self.store.create_from_audio(audio_bytes, filename, duration)
        self.enqueue_asr(event.id)
        return event.id

    def recover_and_resume(self) -> None:
        self.store.interrupt_inflight()
        self._catch_up_note_appends()
        for event_id, kind in self.store.pending_work():
            if kind == "asr":
                self.enqueue_asr(event_id)
            else:
                self.enqueue_polish(event_id)

    def _catch_up_note_appends(self) -> None:
        for event in self.store.list_events():
            if not event.note_id or event.asr_status != "completed":
                continue
            raw = self.store.read_raw_transcript(event.id)
            if raw:
                self.store.append_turn_to_note(event.note_id, event.id, raw)

    def enqueue_asr(self, event_id: str, force: bool = False) -> None:
        self._submit_asr(event_id, lambda: self._run_asr(event_id, force=force))

    def enqueue_polish(self, event_id: str, revision: int | None = None) -> None:
        target = (
            self.store.get(event_id).transcript_revision
            if revision is None
            else revision
        )
        self._submit_polish(event_id, lambda: self._run_polish(event_id, target))

    def _update_event(self, event_id: str, **values):
        def update(event):
            for name, value in values.items():
                setattr(event, name, value)

        return self.store.update_event(event_id, update)

    def retranscribe(self, event_id: str) -> None:
        self._update_event(
            event_id,
            asr_status="pending",
            polish_status="pending",
            last_error=None,
        )
        self.enqueue_asr(event_id, force=True)

    def retry_asr(self, event_id: str) -> None:
        self._update_event(event_id, asr_status="pending", last_error=None)
        self.enqueue_asr(event_id)

    def retry_polish(self, event_id: str) -> None:
        event = self.store.get(event_id)
        if not self.store.read_raw_transcript(event_id):
            raise RuntimeError("Raw transcript missing; run ASR first")
        self.clear_polish_cooldown()
        self._update_event(event_id, polish_status="pending", last_error=None)
        self.enqueue_polish(event_id)

    def warmup_asr(self) -> None:
        warmup = getattr(self.asr, "warmup", None)
        if callable(warmup):
            warmup()

    def _submit_asr(self, event_id: str, fn: Callable[[], None]) -> None:
        self._submit(event_id, fn, self._asr_queues, self._asr_busy, self._asr_pool)

    def _submit_polish(self, event_id: str, fn: Callable[[], None]) -> None:
        event = self.store.get(event_id)
        priority = (
            LECTURE_POLISH_PRIORITY
            if event.kind == "lecture_chunk"
            else NOTE_POLISH_PRIORITY
        )
        with self._lock:
            self._polish_queues[event_id].append(fn)
            current = self._polish_priority.get(event_id)
            if current is None or priority < current:
                self._polish_priority[event_id] = priority
            if event_id in self._polish_busy:
                return
            self._polish_busy.add(event_id)
            heapq.heappush(
                self._polish_heap,
                (self._polish_priority[event_id], self._polish_seq, event_id),
            )
            self._polish_seq += 1
            if not self._polish_running:
                self._polish_running = True
                self._polish_pool.submit(self._polish_loop)

    def _polish_loop(self) -> None:
        while True:
            with self._lock:
                if not self._polish_heap:
                    self._polish_running = False
                    return
                _priority, _seq, event_id = heapq.heappop(self._polish_heap)
                queue = self._polish_queues[event_id]
                if not queue:
                    self._polish_busy.discard(event_id)
                    self._polish_priority.pop(event_id, None)
                    continue
                fn = queue.popleft()
            try:
                fn()
            finally:
                with self._lock:
                    if self._polish_queues[event_id]:
                        heapq.heappush(
                            self._polish_heap,
                            (
                                self._polish_priority.get(
                                    event_id, LECTURE_POLISH_PRIORITY
                                ),
                                self._polish_seq,
                                event_id,
                            ),
                        )
                        self._polish_seq += 1
                    else:
                        self._polish_busy.discard(event_id)
                        self._polish_priority.pop(event_id, None)

    def _submit(
        self,
        event_id: str,
        fn: Callable[[], None],
        queues: dict,
        busy: set[str],
        pool: ThreadPoolExecutor,
    ) -> None:
        with self._lock:
            queues[event_id].append(fn)
            if event_id in busy:
                return
            busy.add(event_id)
        pool.submit(lambda: self._drain(event_id, queues, busy))

    def _drain(self, event_id: str, queues: dict, busy: set[str]) -> None:
        while True:
            with self._lock:
                queue = queues[event_id]
                if not queue:
                    busy.discard(event_id)
                    return
                fn = queue.popleft()
            fn()

    def _run_append(self, event_id: str, audio_path, duration: float) -> None:
        self._update_event(
            event_id,
            asr_status="running",
            polish_status="pending",
            last_error=None,
        )
        try:
            asr = self.asr.transcribe(audio_path, kind="note_turn")
            with self._commit_lock:
                self.store.append_raw_transcript(event_id, asr.text)
                def complete(event):
                    event.asr_status = "completed"
                    event.asr_model = asr.model
                    event.asr_version = asr.version
                    event.asr_elapsed_seconds = asr.elapsed_seconds
                    event.asr_rtf = asr.rtf
                    event.duration_seconds = (
                        event.duration_seconds or 0
                    ) + duration
                    event.transcript_revision += 1
                    event.polish_status = "pending"
                    event.last_error = None

                event = self.store.update_event(event_id, complete)
                self.store.write_segment_transcript(
                    audio_path,
                    asr.text,
                    event.transcript_revision,
                )
                revision = event.transcript_revision
            self.enqueue_polish(event_id, revision)
        except Exception as exc:
            self._update_event(
                event_id,
                asr_status="failed",
                last_error=str(exc),
            )

    def _run_asr(self, event_id: str, force: bool = False) -> None:
        event = self.store.get(event_id)
        if event.asr_status == "completed" and not force:
            if event.note_id:
                raw = self.store.read_raw_transcript(event_id)
                if raw and not is_noise_transcript(raw, event.duration_seconds or 0):
                    self.store.append_turn_to_note(event.note_id, event.id, raw)
            if event.polish_status == "pending":
                self.enqueue_polish(event_id)
            return
        self._update_event(event_id, asr_status="running", last_error=None)
        try:
            audio = self.store.audio_path(event)
            course_args = {"course": self.store.get_session(event.session_id).course} if event.session_id and isinstance(self.asr, MlxWhisperAsr) else {}
            result = self.asr.transcribe(audio, kind=event.kind, **course_args)
            with self._commit_lock:
                self.store.write_raw_transcript(event_id, result.text)
                def complete(event):
                    event.asr_status = "completed"
                    event.asr_model = result.model
                    event.asr_version = result.version
                    event.asr_elapsed_seconds = result.elapsed_seconds
                    event.asr_rtf = result.rtf
                    event.transcript_revision += 1
                    event.polish_status = "pending"
                    event.last_error = None

                event = self.store.update_event(event_id, complete)
                revision = event.transcript_revision
                if event.note_id and not is_noise_transcript(
                    result.text, event.duration_seconds or 0
                ):
                    self.store.append_turn_to_note(
                        event.note_id,
                        event.id,
                        result.text,
                    )
        except Exception as exc:
            self._update_event(
                event_id,
                asr_status="failed",
                last_error=str(exc),
            )
            return
        self.enqueue_polish(event_id, revision)

    def _run_polish(self, event_id: str, revision: int) -> None:
        with self._commit_lock:
            event = self.store.get(event_id)
            if event.transcript_revision != revision:
                return
            raw = self.store.read_raw_transcript(event_id)
            if raw is None:
                return
            timeout = (
                LECTURE_POLISH_TIMEOUT_SECONDS
                if event.kind == "lecture_chunk"
                else POLISH_TIMEOUT_SECONDS
            )
            self._update_event(
                event_id,
                polish_status="running",
                last_error=None,
            )
        if time.monotonic() < self._polish_cooldown_until:
            detail = self._polish_provider_detail or (
                "AI cleanup paused after repeated provider failures; raw transcript preserved"
            )
            logging.getLogger(__name__).warning(
                "polish event=%s skipped cooldown remaining=%.0fs",
                event_id,
                self._polish_cooldown_until - time.monotonic(),
            )
            with self._commit_lock:
                event = self.store.get(event_id)
                if event.transcript_revision != revision:
                    return
                self._update_event(
                    event_id,
                    polish_status="failed",
                    lm_version="provider_unavailable",
                    last_error=detail,
                )
            return
        result = None
        last_error = None
        attempts = 1 + max(POLISH_RETRY_LIMIT, 0)
        for attempt in range(attempts):
            started = time.monotonic()
            try:
                course_args = {"course": self.store.get_session(event.session_id).course} if event.session_id and isinstance(self.polisher, OpencodePolisher) else {}
                result = self.polisher.polish(raw, timeout=timeout, **course_args)
                last_error = None
                issue = polish_quality_issue(raw, result.text) if result.version not in SOFT_POLISH_FAILURES else None
                if issue:
                    result.version = 'quality_rejected'
                    last_error = ValueError(issue)
                if result.version not in SOFT_POLISH_FAILURES:
                    break
            except Exception as exc:
                last_error = exc
                result = None
                if attempt == attempts - 1:
                    break
            finally:
                logging.getLogger(__name__).log(
                    logging.WARNING if last_error or (result and result.version in SOFT_POLISH_FAILURES) else logging.INFO,
                    'polish event=%s attempt=%d elapsed=%.2fs result=%s',
                    event_id, attempt + 1, time.monotonic() - started,
                    result.version if result else 'exception',
                )
        detail = None
        if result is not None:
            detail = getattr(result, "detail", None)
            self._note_polish_outcome(result.version, detail)
        elif last_error is not None:
            self._note_polish_outcome("error", str(last_error))
        with self._commit_lock:
            event = self.store.get(event_id)
            if event.transcript_revision != revision:
                return
            if result is None or result.version in SOFT_POLISH_FAILURES:
                message = (
                    str(last_error)
                    if last_error
                    else detail
                    or f"Polish {result.version if result else 'failed'}; raw transcript preserved"
                )
                self._update_event(
                    event_id,
                    polish_status="failed",
                    lm_version=result.version if result else "error",
                    last_error=message,
                )
                return
            self.store.write_polished_transcript(event_id, result.text)
            self._update_event(
                event_id,
                polish_status="completed",
                polished_revision=revision,
                lm_model=result.model,
                lm_version=result.version,
                last_error=None,
            )
