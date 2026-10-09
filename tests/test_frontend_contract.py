from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_note_ui_is_continuous_editor_with_collapsed_rounds():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

    assert 'id="noteFinal"' in html
    assert 'id="clearNoteFinal"' in html
    assert 'id="roundsList"' in html
    assert 'id="roundInspector"' in html
    assert 'id="inspectorAsr"' not in html
    assert html.count('id="inspectorPolished"') == 1
    assert "max-height: calc(36px * 3)" in html
    assert 'id="turns"' not in html
    assert "Apply polish" not in html
    assert "incomingPane" not in html
    assert javascript.count("createElement(\"textarea\")") == 0
    assert "inspectorAsr" not in javascript
    assert "/api/notes/${state.selectedId}/turns" in javascript
    assert "/api/notes/${state.note.id}/turns/${turnId}" in javascript
    assert "flushFinalSave()" in javascript
    assert "flushTurnSaves()" in javascript
    assert "pinnedRoundId" in javascript
    assert "visibleHistory" in javascript
    assert "cleanup unavailable" in javascript or "AI cleanup unavailable" in javascript
    assert "cleanup_provider_available" in javascript
    assert "cleanup_cooldown_seconds" in javascript
    assert "cleanup_guard_chunks" in javascript
    assert "cleanup_provider_failed_chunks" in javascript
    assert "transcript saved · original kept" in javascript
    assert "language or length check" in javascript
    assert "In-progress part discarded. Earlier parts of this lecture stay saved." in javascript
    assert "Earlier rounds stay in the note." in javascript
    assert "Original transcript kept. Cleanup did not replace it." in javascript
    assert "cleanup_failed_turns" in javascript
    assert "cleanup_guard_turns" in javascript
    assert "Recover audio only keeps lecture parts." in javascript
    pending = javascript.split("function hasPending()", 1)[1].split("function ", 1)[0]
    assert "transcription_pending_chunks" in pending
    assert "cleanup_pending_chunks" in pending
    assert '"captured"' in pending
    assert '"transcribed"' in pending
    pause = javascript.split("function noteCleanupPause", 1)[1].split("function ", 1)[0]
    assert "quality_rejected" in pause
    assert "provider_unavailable" in pause
    assert "quality_rejected" in javascript
    assert "Completed parts retry automatically" in javascript
    assert "will not retry until you use Recover audio" in javascript
    assert "not marked ended yet" in javascript
    end_status = javascript.split("function lectureEndPendingStatus", 1)[1].split("function ", 1)[0]
    assert "that end request retries automatically" in end_status
    assert "those end requests retry automatically" in end_status
    assert "that retry continues automatically" not in javascript
    assert "still transcribing" in javascript
    assert "need transcription retry" in javascript
    session_status = javascript.split("if (item.kind === 'session')", 1)[1].split("if (item.state === \"empty\")", 1)[0]
    assert session_status.index("transcription_pending_chunks") < session_status.index("cleanup_failed_chunks")
    assert session_status.index("empty_transcript_chunks") < session_status.index("cleanup_failed_chunks")
    assert "duplicate part numbers · review" in session_status
    health_title = javascript.split("lectureHealthTitle').textContent", 1)[1].split("const parts", 1)[0]
    assert health_title.index("transcription_pending_chunks") < health_title.index("providerPause")
    assert health_title.index("empty_transcript_chunks") < health_title.index("AI cleanup unfinished")
    assert "Duplicate part numbers need review" in health_title
    assert health_title.index("AI cleanup unfinished") < health_title.index("cleanup_pending_chunks")
    assert "Transcript saved · cleaning up" in health_title
    turn = javascript.split("function turnStatus", 1)[1].split("function ", 1)[0]
    assert "polish skipped" not in turn
    assert "transcript saved · cleaning up" in turn
    assert "transcript saved · cleanup needs retry" in turn
    chunk = javascript.split("async function saveLectureChunk", 1)[1].split("async function ", 1)[0]
    assert chunk.index("continueLectureCapture") < chunk.index("await state.captureReady")
    assert "Earlier part stays on this device" in chunk
    assert "Recover audio downloads it after you stop" in chunk
    assert "failure.unassigned = true" in chunk
    assert "localAudioRetained" in chunk
    assert "uploadBlocked" in chunk
    assert "retries automatically after you stop" in javascript
    assert "will not retry until you use Recover audio" in javascript
    assert "rejectedUploadStopStatus" in chunk
    assert "state.lastStatus !== stoppedLine" in chunk
    assert "could not join a lecture" in javascript
    assert "never joined a lecture" in javascript
    assert "Recover audio uploads" in javascript
    assert "Recover audio downloads" in javascript
    assert "It stays" in javascript
    assert "Recording lecture · part" in javascript
    assert "History could not refresh. Recording continues." in javascript
    assert "holdRecordingStatus" in javascript
    status_fn = javascript.split("function setStatus", 1)[1].split("function safeClientDetail", 1)[0]
    assert "recordingStatusIsLive" in status_fn
    assert "showCaptureNotice" in status_fn
    assert "noteTakePending" in status_fn
    assert "holdNoteTakeStatus" in status_fn
    assert "Local draft storage is full. Keep this tab open until saved." in javascript
    assert "only in this tab" in javascript
    assert "unjournaledCaptures" in javascript
    assert "putCaptureRow" in javascript
    assert "The lecture is not ready yet" in javascript
    assert "backupDurable" in javascript
    assert "backupEverDurable" in javascript
    assert "only in this tab until the browser backup succeeds" in javascript
    assert "An earlier backup of this part stays on this device." in javascript
    hold = javascript.split("function lectureSetupHoldStatus", 1)[1].split("function ", 1)[0]
    assert "This part stays on this device." in hold
    assert "recorder?.backupDurable" in hold
    assert "recorder?.backupEverDurable" in hold
    assert "pageLeaveNeedsWarning" in javascript
    leave = javascript.split("function pageLeaveNeedsWarning", 1)[1].split("function ", 1)[0]
    assert "finalDirty" in leave
    assert "finalPending" in leave
    assert "unjournaledCaptures" in leave
    assert "questionUncached" in leave
    assert "turnSaves" in leave
    assert "noteTakePending" in leave
    assert "only in this tab until the server confirms" in javascript
    assert "the copy in this browser stays until the server confirms it" in javascript
    assert "the copies in this browser stay until the server confirms them" in javascript
    assert "The other copy stays in this browser until the server confirms it." in javascript
    assert "audio gaps" in javascript
    assert "1 part has no detected speech" in javascript
    assert "the downloads are the copies to keep" in javascript
    assert "Recover audio downloads it before this tab closes." in javascript
    assert "This question is only in this tab until it saves." in javascript
    assert "This part is only in this tab." in javascript
    assert "This part stays in this browser." in javascript
    assert "Local audio retained." not in javascript
    recover = javascript.split("async function recoverSavedAudio", 1)[1].split("el('recoverAudio')", 1)[0]
    assert "safeClientDetail(error)" in recover
    assert "error.message" not in recover
    assert "Try Recover audio again before closing this tab." in recover
    backup = javascript.split("recorder.ondataavailable", 1)[1].split("state.recorder.onstop", 1)[0]
    assert "backupDurable = true" in backup
    assert "backupDurable = false" in backup
    assert ", 3);" in backup
    assert "This take is not saved if you stop now" in javascript
    assert "Saving this note take. Keep this tab open until it is stored." in javascript
    assert "History could not refresh. This note take is still saving. Keep this tab open." in javascript
    note_save = javascript.split("async function saveNoteTurn", 1)[1].split("async function ", 1)[0]
    assert note_save.index("releaseNoteTakeHold") < note_save.index("· transcribing")
    recorder_stop = javascript.split("async function onRecorderStop", 1)[1].split("async function ", 1)[0]
    assert recorder_stop.index("noteTakePending") < recorder_stop.index("await recorder.backupChain")
    assert recorder_stop.index("releaseNoteTakeHold") < recorder_stop.index("This note take was not saved")
    assert "safeClientDetail(error)} · This note take was not saved" in recorder_stop
    assert "error.message} · This note take was not saved" not in recorder_stop
    assert "liveUploadFailureStatus" in recorder_stop
    assert "Recording lecture · chunk" not in javascript
    assert "transcript saved · cleaning up" in javascript
    assert "return item.status === 'open' ? 'open' : 'ended'" in javascript
    endLoop = javascript.split("async function finishStoppedLectures", 1)[1].split("async function ", 1)[0]
    assert "error.status === 404" in endLoop
    assert "pending += 1" in endLoop
    stop = javascript.split("async function saveLectureChunk", 1)[1].split("async function ", 1)[0]
    assert "state.stopEndPending" in stop
    assert "lectureEndPendingStatus" in stop
    assert "cannot coordinate the microphone" in javascript
    assert "Audio did not start" in (ROOT / "web" / "capture.js").read_text(encoding="utf-8")
    assert "Copy note" in html
    assert ">Clear</button>" in html
    assert "clearContinuousNote" in javascript
    assert "Lecture" in html
    start = javascript.split("async function startRecording", 1)[1]
    setup_fail = start.split("function finishRecording", 1)[0]
    assert "lectureSetupHoldStatus()" in setup_fail
    assert 'notice.startsWith("Audio backup failed")' in setup_fail
    assert "holdRecordingStatus()" in javascript.split("async function sync()", 1)[1].split("function hasPending", 1)[0]
    assert start.index("SpeechCapture.open") < start.index("prepareRecordingTarget")
    assert "forceNew" in javascript
    assert "isFreshLecture" in javascript
    assert 'bootParams.get("record")' in javascript
    assert "LECTURE_MAX" in javascript
    assert "Stopped after 2 hours" in javascript
    assert 'id="draftQuestion"' in html
    assert 'id="questionOut"' in html
    assert "/api/sessions/${id}/questions" in javascript
    assert "window.close()" not in javascript
    assert "base_revision: baseRevision" in javascript
    assert "recorder.start(5000)" in javascript
    assert "speech-microphone" in javascript
    assert "SpeechRecovery.remove" in javascript
    assert 'id="copyTranscriptPath"' in html
    assert "/api/sessions/${state.selectedId}/transcript-path" in javascript
    assert "overflow: hidden" in html
    assert "position: sticky" in html
