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
    assert "The empty lecture could not be deleted." in javascript
    assert "This part is still in this browser and can still upload." in javascript
    assert "The new note could not be deleted." in javascript
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
    assert 'const HISTORY_REFRESH_IDLE = "History could not refresh."' in javascript
    assert 'const NOTES_UNSAVED_IDLE = "Your lecture notes are still unsaved."' in javascript
    assert 'const NOTE_UNSAVED_IDLE = "This note is still unsaved."' in javascript
    assert 'const POLISH_UNSAVED_IDLE = "This polish edit is still unsaved."' in javascript
    assert "idleUnsavedStatus" in javascript
    assert "safeStatusDetail" in javascript
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
    assert "recorderStopsPending" in leave
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
    assert "captureFailureReason(error)" in recover
    assert "safeClientDetail(error)" not in recover
    assert "error.message" not in recover
    attention = javascript.split("function recoveryAttentionStatus", 1)[1].split("function ", 1)[0]
    assert "Recovery needs attention." in attention
    assert "Recovery needs attention: ${reason}." in attention
    assert "Try Recover audio again before closing this tab." in recover
    assert "failedMemory" in recover
    assert "recoveryAttentionStatus" in recover
    assert "These parts are only in this tab." in javascript
    assert "1 is only in this tab" in javascript
    assert '${tabBit}; ${browserBit}' in javascript
    assert "saved audio will continue processing" not in javascript
    assert "Meeting sharing ended. Recording stopped." in javascript
    assert "this part may still be only in this tab." in javascript
    assert "stopRecorderSoon" in javascript
    assert "recorder.pendingStop" in javascript
    backup = javascript.split("recorder.ondataavailable", 1)[1].split("state.recorder.onstop", 1)[0]
    assert "backupDurable = true" in backup
    assert "backupDurable = false" in backup
    assert "clearAudioBackupNotice()" in backup
    assert "audioBackupFailureNotice(error, recorder.backupEverDurable)" in backup
    assert ", 3);" in backup
    backup_notice = javascript.split("function audioBackupFailureNotice", 1)[1].split("function ", 1)[0]
    assert 'state.recording ? " Recording continues." : ""' in backup_notice
    assert "Keep this tab open." in backup_notice
    assert "This take is not saved if you stop now" in javascript
    assert "Saving this note take. Keep this tab open until it is stored." in javascript
    assert "History could not refresh. This note take is still saving. Keep this tab open." in javascript
    note_save = javascript.split("async function saveNoteTurn", 1)[1].split("async function ", 1)[0]
    assert note_save.index("releaseNoteTakeHold") < note_save.index("· transcribing")
    recorder_stop = javascript.split("async function onRecorderStop", 1)[1].split("async function ", 1)[0]
    assert recorder_stop.index("noteTakePending") < recorder_stop.index("await recorder.backupChain")
    assert recorder_stop.index("await recorder.backupChain") < recorder_stop.index("backupEverDurable = Boolean")
    assert recorder_stop.index("backupEverDurable = Boolean") < recorder_stop.index("forgetDiscardedLecturePart")
    assert recorder_stop.index("forgetDiscardedLecturePart") < recorder_stop.index("handleDiscard")
    assert "droppedLecturePart || !backupEverDurable" in recorder_stop
    assert "!droppedLecturePart && backupEverDurable" in recorder_stop
    assert recorder_stop.index("releaseNoteTakeHold") < recorder_stop.index("stoppedNoteTakeStatus")
    discard_failure = recorder_stop.split("if (failure)", 1)[1]
    assert discard_failure.index("state.discard") < discard_failure.index("stoppedLecturePartStatus")
    assert "discardFailureStatus" in discard_failure
    forget = javascript.split("async function forgetDiscardedLecturePart", 1)[1].split("async function ", 1)[0]
    assert "SpeechRecovery.remove" in forget
    assert "unjournaledCaptures" in forget
    discard_status = javascript.split("function discardFailureStatus", 1)[1].split("async function ", 1)[0]
    assert "safeStatusDetail" in discard_status
    assert "Recover audio" not in discard_status
    assert "The empty lecture could not be deleted." in discard_status
    assert "!droppedLecturePart && backupEverDurable" in discard_status
    assert discard_status.index("backupEverDurable") < discard_status.index("can still upload")
    assert "can still upload" in discard_status
    assert "stoppedLecturePartStatus(error)" in recorder_stop
    assert "stoppedNoteTakeStatus(error)" in recorder_stop
    assert "error.message} · This note take was not saved" not in recorder_stop
    reason = javascript.split("function captureFailureReason", 1)[1].split("function ", 1)[0]
    assert "safeClientDetail(error)" in reason
    assert "The audio could not be read" in reason
    assert "The server did not confirm this recording" in reason
    assert "The audio could not be stored" in reason
    assert "This recording conflicts with one already stored" in reason
    assert "retained in browser" in reason
    assert "could not be stored" not in reason.split("The audio could not be stored", 1)[-1]
    stopped_part = javascript.split("function stoppedLecturePartStatus", 1)[1].split("function ", 1)[0]
    assert "This part is only in this tab. Use Recover audio before closing it." in stopped_part
    assert "This part stays in this browser. Use Recover audio; do not clear browser storage." in stopped_part
    assert "safeClientDetail(error)" not in stopped_part
    stopped_note = javascript.split("function stoppedNoteTakeStatus", 1)[1].split("function ", 1)[0]
    assert "This note take was not saved. Record it again; Recover audio only keeps lecture parts." in stopped_note
    assert "retained in browser" not in stopped_note
    assert "safeClientDetail(error)} This part is only in this tab" not in javascript
    assert "liveUploadFailureStatus" in recorder_stop
    live_fail = javascript.split("function liveUploadFailureStatus", 1)[1].split("function ", 1)[0]
    assert "captureFailureReason(error)" in live_fail
    assert "safeClientDetail(error)" not in live_fail
    assert "Recording continues." in live_fail
    assert "Earlier part is only in this tab and will not retry until you use Recover audio." in live_fail
    assert "Earlier part stays on this device. It retries automatically after you stop." in live_fail
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
    setup_show = javascript.split("function showSetupFailureNotice", 1)[1].split("function ", 1)[0]
    assert 'notice.startsWith("Audio backup failed")' in setup_show
    late_setup = setup_fail.split("await state.captureReady;", 1)[1]
    assert "setStatus(error.message)" not in late_setup
    assert 'showSetupFailureNotice("Lecture", error)' in late_setup
    assert 'showSetupFailureNotice("Note", error)' in late_setup
    assert "!state.discard" in late_setup
    assert "clearLiveCaptureNotices()" not in late_setup
    sync_fn = javascript.split("async function sync()", 1)[1].split("function hasPending", 1)[0]
    assert "holdRecordingStatus()" in sync_fn
    assert "error.message" not in sync_fn
    assert "HISTORY_REFRESH_IDLE" in sync_fn
    assert "state.lastStatus !== HISTORY_REFRESH_IDLE" in sync_fn
    assert "state.lastStatus === HISTORY_REFRESH_IDLE" in sync_fn
    stopped_notices = javascript.split("function clearLiveCaptureNotices", 1)[1].split("function fit", 1)[0]
    assert "HISTORY_REFRESH_IDLE" in stopped_notices
    assert "NOTES_UNSAVED_IDLE" in stopped_notices
    assert "NOTE_UNSAVED_IDLE" in stopped_notices
    assert "POLISH_UNSAVED_IDLE" in stopped_notices
    assert 'current.startsWith("Audio backup failed")' in stopped_notices
    assert 'current.startsWith("Lecture setup failed")' in stopped_notices
    assert 'current.startsWith("Note setup failed")' in stopped_notices
    assert "state.discard" in stopped_notices
    assert "Recording continues\\.$" in stopped_notices
    assert 'current.includes("Recording continues")' in stopped_notices
    setup_notice = javascript.split("function setupFailureNotice", 1)[1].split("function ", 1)[0]
    assert 'state.recording ? " Recording continues." : ""' in setup_notice
    assert "safeClientDetail(error)" in setup_notice
    save_turn = javascript.split("async function saveTurn", 1)[1].split("async function ", 1)[0]
    assert "POLISH_UNSAVED_IDLE" in save_turn
    assert "error.message" not in save_turn
    save_final = javascript.split("async function saveFinal", 1)[1].split("async function flushFinalSave", 1)[0]
    assert "NOTE_UNSAVED_IDLE" in save_final
    assert "error.message" not in save_final
    save_session = javascript.split("async function flushSessionSave", 1)[1].split("async function mergeSessionChunks", 1)[0]
    assert "NOTES_UNSAVED_IDLE" in save_session
    assert "error.message" not in save_session
    switch_mode = javascript.split("async function switchMode", 1)[1].split("function resetQuestionFields", 1)[0]
    assert "NOTES_UNSAVED_IDLE" in switch_mode
    assert "error.message" not in switch_mode
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
