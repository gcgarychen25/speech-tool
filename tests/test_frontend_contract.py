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
    assert "cannot coordinate the microphone" in javascript
    assert "Audio did not start" in (ROOT / "web" / "capture.js").read_text(encoding="utf-8")
    assert "Copy note" in html
    assert ">Clear</button>" in html
    assert "clearContinuousNote" in javascript
    assert "Lecture" in html
    start = javascript.split("async function startRecording", 1)[1]
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
    assert "overflow: hidden" in html
    assert "position: sticky" in html
