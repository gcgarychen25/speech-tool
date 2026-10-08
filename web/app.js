const NOTE_MAX = 600;
const LECTURE_CHUNK = 60;
const LECTURE_MAX = 7200;
const el = (id) => document.getElementById(id);
const historyEl = el("history");
const noteWorkspace = el("noteWorkspace");
const lectureWorkspace = el("lectureWorkspace");
const noteModeBtn = el("modeNote");
const lectureModeBtn = el("modeLecture");
const newBtn = el("newItem");
const recordBtn = el("record");
const discardBtn = el("discard");
const copyNoteBtn = el("copyNote");
const timerEl = el("timer");
const statusEl = el("status");
const courseEl = el("course");
const listenerNotes = el("listenerNotes");
const lectureDraft = el("lectureDraft");
const lecturePolished = el("lecturePolished");
const stampBtn = el("stamp");
const draftQuestionBtn = el("draftQuestion");
const copyQuestionBtn = el("copyQuestion");
const questionOut = el("questionOut");
const questionRefine = el("questionRefine");
const noteFinal = el("noteFinal");
const clearNoteBtn = el("clearNoteFinal");
const finalState = el("finalState");
const roundsTitle = el("roundsTitle");
const roundsList = el("roundsList");
const roundInspector = el("roundInspector");
const inspectorTitle = el("inspectorTitle");
const inspectorMeta = el("inspectorMeta");
const inspectorPolished = el("inspectorPolished");
const copyInspectorPolished = el("copyInspectorPolished");
const retryInspectorPolish = el("retryInspectorPolish");
const retryLecturePolish = el("retryLecturePolish");

const state = {
  mode: localStorage.getItem("speech-mode") || "note",
  selectedKind: "note",
  selectedId: null,
  bootNewLecture: false,
  note: null,
  session: null,
  history: [],
  roundNodes: new Map(),
  turnSaves: new Map(),
  expandedRoundId: null,
  pinnedRoundId: null,
  finalRevision: 0,
  finalBaseText: "",
  finalApplied: "",
  finalDirty: false,
  finalTimer: null,
  finalChain: Promise.resolve(),
  finalPending: 0,
  syncing: false,
  lastStatus: "",
  questionUncached: false,

  recording: false,
  recordingMode: null,
  recorder: null,
  media: null,
  blobs: [],
  startedAt: 0,
  chunkStartedAt: 0,
  tick: null,
  discard: false,
  rotating: false,
  createdNoteForRecording: false,

  liveSessionId: null,
  chunkIndex: 0,
  uploads: [],
  captureReady: null,
  mergedChunks: new Set(),
  lectureDirty: false,
  notesDirty: false,
  lectureApplied: "",
  notesApplied: "",
  lectureSaveTimer: null,
  notesSaveTimer: null,
  sessionSaveChain: Promise.resolve(),
  sessionSavePending: 0,
  sessionRevision: 0,
  recordingOffset: 0,
  releaseCaptureLock: null,
  captureLockReason: "",
  autoStopped: false,
  stopEndPending: 0,
  captureReadyState: "pending",
  noteTakePending: 0,
};

function fmt(value) {
  const seconds = Math.max(0, Number(value) || 0);
  const minutes = Math.floor(seconds / 60).toString().padStart(2, "0");
  const remainder = Math.floor(seconds % 60).toString().padStart(2, "0");
  return `${minutes}:${remainder}`;
}
function setStatus(text, noticePriority = -1) {
  const next = text || "";
  // Side actions stay in the capture notice so the live recording line remains.
  if (state.recording && !recordingStatusIsLive(next)) {
    if (next) showCaptureNotice(next, noticePriority);
    holdRecordingStatus();
    return;
  }
  // A note take has no browser journal. Keep the saving line until the server accepts it.
  if (state.noteTakePending && next !== NOTE_TAKE_SAVING_STATUS) {
    if (next) showCaptureNotice(next, noticePriority);
    holdNoteTakeStatus();
    return;
  }
  if (next === state.lastStatus) return;
  statusEl.textContent = next;
  state.lastStatus = next;
}
function holdNoteTakeStatus() {
  if (!state.noteTakePending || state.lastStatus === NOTE_TAKE_SAVING_STATUS) return;
  statusEl.textContent = NOTE_TAKE_SAVING_STATUS;
  state.lastStatus = NOTE_TAKE_SAVING_STATUS;
}
const HISTORY_REFRESH_NOTICE = "History could not refresh. Recording continues.";
const NOTES_UNSAVED_NOTICE = "Your lecture notes are still unsaved. Recording continues.";
const NOTE_UNSAVED_NOTICE = "This note is still unsaved. Recording continues.";
const POLISH_UNSAVED_NOTICE = "This polish edit is still unsaved. Recording continues.";
const QUESTION_UNSAVED_NOTICE = "Question saved in this browser; server save is still pending.";
const QUESTION_TAB_ONLY_NOTICE = "This question is only in this tab until it saves. Keep this tab open.";
const DRAFT_STORAGE_FULL_NOTICE = "Local draft storage is full. Keep this tab open until saved.";
const NOTE_TAKE_SAVING_STATUS = "Saving this note take. Keep this tab open until it is stored.";
const HISTORY_DURING_NOTE_SAVE = "History could not refresh. This note take is still saving. Keep this tab open.";
function safeClientDetail(error) {
  const text = String(error?.message || "Request failed").replace(/\s+/g, " ").trim();
  if (!text || text.length > 180 || /[\\/]/.test(text)) return "Request failed";
  return text;
}
function liveCaptureStatus() {
  if (state.recordingMode === "note") {
    return state.note ? `Recording round ${(state.note.turn_count || 0) + 1}` : "Recording note";
  }
  return `Recording lecture · part ${(state.chunkIndex || 0) + 1}`;
}
function lectureSetupHoldStatus() {
  const recorder = state.recorder;
  const held = recorder?.backupDurable
    ? "This part stays on this device."
    : recorder?.backupEverDurable
      ? "An earlier backup of this part stays on this device. The latest backup did not save. Keep this tab open."
      : "This part is only in this tab until the browser backup succeeds. Keep this tab open.";
  return `Recording lecture · part ${state.chunkIndex + 1}. The lecture is not ready yet. ${held}`;
}
function refreshLectureSetupHold() {
  if (!state.recording || state.recordingMode !== "lecture" || state.captureReadyState !== "failed") return;
  setStatus(lectureSetupHoldStatus());
}
function recordingStatusIsLive(text) {
  return text.startsWith("Recording lecture")
    || text.startsWith("Recording note")
    || text.startsWith("Recording round");
}
function holdRecordingStatus() {
  if (!state.recording) return;
  if (!recordingStatusIsLive(state.lastStatus || "")) setStatus(liveCaptureStatus());
}
function showCaptureNotice(text, priority = 0) {
  const notice = el("captureNotice");
  const current = notice.textContent || "";
  const currentPriority = Number(notice.dataset.priority || 0);
  if (!current || priority >= currentPriority) {
    notice.textContent = text;
    notice.dataset.priority = String(priority);
  }
}
function clearCaptureNotice(text) {
  const notice = el("captureNotice");
  if ((notice.textContent || "") !== text) return;
  notice.textContent = "";
  delete notice.dataset.priority;
}
function clearLiveCaptureNotices() {
  const notice = el("captureNotice");
  const current = notice.textContent || "";
  if (current === HISTORY_REFRESH_NOTICE || current.includes("Recording continues")) {
    notice.textContent = "";
    delete notice.dataset.priority;
  }
}
function fit(textarea, maxRatio = 0.32) {
  textarea.style.height = "auto";
  textarea.style.height = Math.min(Math.max(textarea.scrollHeight, 76), innerHeight * maxRatio) + "px";
}
function assignValue(textarea, next, follow = false) {
  if (textarea.value === next) return false;
  const nearBottom = textarea.scrollHeight - textarea.scrollTop - textarea.clientHeight < 48;
  textarea.value = next;
  if (follow || nearBottom) textarea.scrollTop = textarea.scrollHeight;
  return true;
}
async function api(url, options) {
  const response = await fetch(url, { ...options, signal: options?.signal || AbortSignal.timeout(30000) });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(
      typeof body.detail === "string"
        ? body.detail
        : body.detail?.message || `Request failed (${response.status})`,
    );
    error.status = response.status;
    error.detail = body.detail;
    throw error;
  }
  return body;
}
function turnStatus(turn) {
  if (turn.asr_status === "failed") return "transcription failed";
  if (turn.asr_status !== "completed") return "transcribing";
  if (turn.lm_version === "quality_rejected") return "transcript saved · original kept";
  if (turn.polish_status === "failed") {
    return turn.lm_version === "provider_unavailable" || turn.lm_version === "model_unavailable"
      ? "transcript saved · cleanup unavailable"
      : "transcript saved · cleanup needs retry";
  }
  if (["pending", "running"].includes(turn.polish_status)) return "transcript saved · cleaning up";
  if (turn.lm_version === "provider_unavailable" || turn.lm_version === "model_unavailable") {
    return "transcript saved · cleanup unavailable";
  }
  if (["timeout", "error", "empty"].includes(turn.lm_version)) return "transcript saved · cleanup needs retry";
  return "ready";
}
function polishRetryVisible(detail) {
  return detail.polish_status === "failed"
    || ["timeout", "error", "empty", "provider_unavailable", "model_unavailable", "quality_rejected"].includes(detail.lm_version);
}
function cleanupBreakdown(detail) {
  const cleanup = detail.cleanup_failed_chunks || 0;
  const guard = detail.cleanup_guard_chunks || 0;
  const providerFailed = detail.cleanup_provider_failed_chunks || 0;
  const cooldown = Math.max(0, Number(detail.cleanup_cooldown_seconds) || 0);
  const providerDown = detail.cleanup_provider_available === false || cooldown > 0;
  const guardOnly = cleanup > 0 && guard === cleanup && providerFailed === 0;
  return {
    cleanup, guard, providerFailed, cooldown, providerDown, guardOnly,
    providerPause: providerDown && cleanup > 0 && !guardOnly,
  };
}
function cleanupListStatus(kind) {
  if (kind.providerPause) return "transcript saved · cleanup unavailable";
  if (kind.guardOnly) return "transcript saved · original kept";
  return "transcript saved · cleanup unfinished";
}
function itemStatus(item) {
  if (item.kind === 'session') {
    if (item.missing_chunk_indices?.length) {
      const gaps = item.missing_chunk_indices.length;
      return gaps === 1 ? "1 audio gap · review" : `${gaps} audio gaps · review`;
    }
    if (item.asr_failed_chunks) return 'audio saved · transcription needs retry';
    if (item.transcription_pending_chunks) return 'audio saved · transcribing';
    if (item.empty_transcript_chunks) {
      const silent = item.empty_transcript_chunks;
      return silent === 1 ? "1 part has no detected speech" : `${silent} parts have no detected speech`;
    }
    if (item.duplicate_chunk_indices?.length) return 'duplicate part numbers · review';
    if (item.cleanup_failed_chunks) return cleanupListStatus(cleanupBreakdown(item));
    if (item.cleanup_pending_chunks) return 'transcript saved · cleaning up';
    if (item.chunk_count) return 'transcript saved';
    return item.status === 'open' ? 'open' : 'ended';
  }
  if (item.state === "empty") return "empty";
  if (item.state === "polishing_failed") {
    return cleanupListStatus(cleanupBreakdown({
      cleanup_failed_chunks: item.cleanup_failed_turns,
      cleanup_guard_chunks: item.cleanup_guard_turns,
      cleanup_provider_failed_chunks: item.cleanup_provider_failed_turns,
      cleanup_cooldown_seconds: item.cleanup_cooldown_seconds,
      cleanup_provider_available: item.cleanup_provider_available,
    }));
  }
  if ((item.state || "").includes("fail")) return "transcription needs retry";
  if (item.state === "transcribing") return "transcribing";
  if (item.status === "open") return "open";
  if (item.polish_status === "failed") return "transcript saved · cleanup unfinished";
  if (item.state === "polishing") return "transcript saved · cleaning up";
  if (["pending", "running"].includes(item.polish_status)) {
    return "transcript saved · cleaning up";
  }
  if (item.polish_skipped) return "transcript saved · cleanup unfinished";
  return "ready";
}
function historyMetaIsSerious(item, status) {
  if (item.kind === "session") {
    return Boolean(
      item.asr_failed_chunks
      || item.missing_chunk_indices?.length
      || item.duplicate_chunk_indices?.length
    );
  }
  // Notes: only ASR/transcription failures are urgent; polish failures are optional.
  return Boolean(
    item.state === "transcription_failed"
    || status.includes("transcription needs retry")
    || status.includes("transcription failed")
  );
}
function rebaseNote(baseText, current, next) {
  if (current === baseText) return next;
  if (!current.startsWith(baseText)) return null;
  const suffix = current.slice(baseText.length);
  if (!baseText && next.trim() && suffix.trim()) {
    return `${next.replace(/\s+$/, "")}\n\n${suffix.replace(/^\s+/, "")}`;
  }
  return next.replace(/\s+$/, "") + suffix;
}
function preserveCursor(textarea, next) {
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  textarea.value = next;
  if (document.activeElement === textarea) {
    const max = next.length;
    textarea.setSelectionRange(Math.min(start, max), Math.min(end, max));
  }
}

function applyMode() {
  const noteMode = state.mode === "note";
  noteModeBtn.classList.toggle("on", noteMode);
  lectureModeBtn.classList.toggle("on", !noteMode);
  noteWorkspace.style.display = noteMode ? "block" : "none";
  lectureWorkspace.style.display = noteMode ? "none" : "flex";
  copyNoteBtn.textContent = noteMode ? "Copy note" : "Copy lecture";
  copyNoteBtn.disabled = noteMode ? !noteFinal.value : !lectureDraft.value;
  clearNoteBtn.disabled = !noteFinal.value;
  localStorage.setItem("speech-mode", state.mode);
}
function syncNoteActions() {
  const hasText = Boolean(noteFinal.value);
  if (state.mode === "note") copyNoteBtn.disabled = !hasText;
  clearNoteBtn.disabled = !hasText;
}

function turnSaveState(turnId, branch, initial = "") {
  const key = `${turnId}:${branch}`;
  if (!state.turnSaves.has(key)) {
    state.turnSaves.set(key, {
      key, turnId, branch, applied: initial || "", dirty: false,
      timer: null, chain: Promise.resolve(), pending: 0,
    });
  }
  return state.turnSaves.get(key);
}
async function saveTurn(save, textarea) {
  clearTimeout(save.timer);
  if (!save.dirty) return save.chain;
  const text = textarea.value;
  save.applied = text;
  save.dirty = false;
  save.pending += 1;
  const run = async () => {
    try {
      await api(`/api/events/${save.turnId}/drafts/${save.branch}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      clearCaptureNotice(POLISH_UNSAVED_NOTICE);
    } catch (error) {
      save.dirty = true;
      if (state.recording) showCaptureNotice(POLISH_UNSAVED_NOTICE, 1);
      else setStatus(error.message);
    } finally {
      save.pending -= 1;
    }
  };
  save.chain = save.chain.then(run, run);
  await save.chain;
}
async function flushTurnSaves() {
  if (!state.expandedRoundId) return;
  await saveTurn(turnSaveState(state.expandedRoundId, "polished"), inspectorPolished);
}
async function saveFinal(force = false) {
  clearTimeout(state.finalTimer);
  if (!state.note || (!state.finalDirty && !force)) return state.finalChain;
  const id = state.note.id;
  const payload = {
    base_revision: state.finalRevision,
    base_text: state.finalBaseText,
    text: noteFinal.value,
  };
  state.finalDirty = false;
  state.finalPending += 1;
  finalState.textContent = "Saving";
  const run = async () => {
    try {
      let result = await api(`/api/notes/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      applyFinalResult(id, result.final_text, result.final_revision);
      clearCaptureNotice(NOTE_UNSAVED_NOTICE);
    } catch (error) {
      if (error.status === 409 && error.detail?.final_text != null) {
        const merged = rebaseNote(payload.base_text, error.detail.final_text, payload.text);
        state.finalRevision = error.detail.final_revision;
        state.finalBaseText = error.detail.final_text;
        if (merged != null) {
          if (noteFinal.value === payload.text) preserveCursor(noteFinal, merged);
          try {
            const result = await api(`/api/notes/${id}`, {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                base_revision: error.detail.final_revision,
                base_text: error.detail.final_text,
                text: merged,
              }),
            });
            applyFinalResult(id, result.final_text, result.final_revision);
            clearCaptureNotice(NOTE_UNSAVED_NOTICE);
            return;
          } catch (retryError) {
            error = retryError;
          }
        }
      }
      state.finalDirty = true;
      finalState.textContent = "Unsaved";
      if (state.recording) showCaptureNotice(NOTE_UNSAVED_NOTICE, 1);
      else setStatus(error.message);
    } finally {
      state.finalPending -= 1;
    }
  };
  state.finalChain = state.finalChain.then(run, run);
  await state.finalChain;
}
async function flushFinalSave() {
  await saveFinal();
}
function applyFinalResult(noteId, text, revision) {
  if (state.selectedId !== noteId || state.selectedKind !== "note") return;
  state.finalRevision = revision;
  state.finalBaseText = text;
  state.finalApplied = text;
  if (document.activeElement === noteFinal || state.finalDirty) {
    if (text.startsWith(noteFinal.value) && text !== noteFinal.value) {
      preserveCursor(noteFinal, text);
      state.finalDirty = false;
    } else {
      state.finalDirty = noteFinal.value !== text;
    }
  } else if (noteFinal.value !== text) {
    noteFinal.value = text;
    fit(noteFinal, 0.55);
  }
  finalState.textContent = state.finalDirty ? "Unsaved" : "Saved";
  syncNoteActions();
}
function applyFinalFromServer(text, revision) {
  const next = text || "";
  if (state.finalDirty || state.finalPending) {
    if (state.finalDirty) saveFinal();
    return;
  }
  if (document.activeElement === noteFinal) {
    if (next.startsWith(noteFinal.value) && next !== noteFinal.value) {
      preserveCursor(noteFinal, next);
      fit(noteFinal, 0.55);
    }
  } else if (noteFinal.value !== next) {
    noteFinal.value = next;
    fit(noteFinal, 0.55);
  }
  state.finalRevision = revision;
  state.finalBaseText = next;
  state.finalApplied = next;
  finalState.textContent = "Saved";
  syncNoteActions();
}

function latestTurn(note) {
  const turns = note?.turns || [];
  return turns[turns.length - 1] || null;
}
function inspectedTurnId(note) {
  if (state.pinnedRoundId && note.turns.some((turn) => turn.id === state.pinnedRoundId)) {
    return state.pinnedRoundId;
  }
  state.pinnedRoundId = null;
  return latestTurn(note)?.id || null;
}
function scrollRoundsToLatest() {
  roundsList.scrollTop = roundsList.scrollHeight;
}
function renderRounds(note) {
  const turns = note.turns || [];
  roundsTitle.textContent = `Rounds${turns.length ? ` (${turns.length})` : ""}`;
  const ids = new Set(turns.map((turn) => turn.id));
  for (const [id, node] of state.roundNodes) {
    if (!ids.has(id)) {
      node.button.remove();
      state.roundNodes.delete(id);
    }
  }
  if (!turns.length) {
    roundsList.innerHTML = '<p class="empty">No rounds yet.</p>';
    state.roundNodes.clear();
    roundInspector.classList.remove("on");
    return;
  }
  roundsList.querySelector(".empty")?.remove();
  const activeId = inspectedTurnId(note);
  turns.forEach((turn, index) => {
    let node = state.roundNodes.get(turn.id);
    if (!node) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "round-row";
      button.innerHTML = `
        <span class="round-number"></span>
        <span class="round-preview"></span>
        <span class="round-status"></span>`;
      button.addEventListener("click", () => selectRound(turn.id));
      node = {
        button,
        number: button.querySelector(".round-number"),
        preview: button.querySelector(".round-preview"),
        status: button.querySelector(".round-status"),
      };
      state.roundNodes.set(turn.id, node);
    }
    const before = roundsList.children[index];
    if (before !== node.button) roundsList.insertBefore(node.button, before || null);
    node.number.textContent = `Round ${turn.turn_index + 1}`;
    node.preview.textContent = turn.preview || (turn.asr_status === "completed" ? "" : "Transcribing…");
    node.status.textContent = `${fmt(turn.duration_seconds)} · ${turnStatus(turn)}`;
    node.button.classList.toggle("active", activeId === turn.id);
  });
  if (!state.pinnedRoundId) scrollRoundsToLatest();
}
function updateInspectorFields(detail, isLatest) {
  const polishSave = turnSaveState(detail.id, "polished", detail.polished_draft || "");
  inspectorTitle.textContent = isLatest
    ? `Latest polish · Round ${detail.turn_index + 1}`
    : `Round ${detail.turn_index + 1} polish`;
  inspectorMeta.textContent = `${fmt(detail.duration_seconds)} · ${turnStatus(detail)}${noteCleanupPause(detail)}`;
  inspectorPolished.disabled = detail.polished_draft == null;
  inspectorPolished.placeholder = detail.asr_status !== "completed"
    ? "Waiting for ASR…"
    : (["pending", "running"].includes(detail.polish_status) ? "Polishing…"
      : polishRetryVisible(detail) && !detail.polished_draft
        ? "Original transcript kept. Cleanup did not replace it."
        : "No transcript yet");
  if (!polishSave.dirty && !polishSave.pending && document.activeElement !== inspectorPolished) {
    const value = detail.polished_draft || "";
    if (inspectorPolished.value !== value) {
      inspectorPolished.value = value;
      polishSave.applied = value;
      fit(inspectorPolished, 0.22);
    }
  }
  copyInspectorPolished.disabled = !inspectorPolished.value;
  retryInspectorPolish.hidden = !polishRetryVisible(detail);
}
function noteCleanupPause(detail) {
  const note = state.note || {};
  const cooldown = Math.max(0, Number(note.cleanup_cooldown_seconds) || 0);
  const providerDown = note.cleanup_provider_available === false || cooldown > 0;
  const providerFailure = ["timeout", "error", "empty", "provider_unavailable", "model_unavailable"].includes(detail.lm_version);
  const keptOriginal = detail.lm_version === "quality_rejected";
  if (!providerDown || (!providerFailure && !keptOriginal && detail.polish_status !== "failed")) return "";
  return ` · paused for ${cleanupPausePhrase(cooldown)} · Retry polish tries again now`;
}
async function showRoundPolish(turnId) {
  if (!state.note || !turnId) return;
  const keepFinalFocus = document.activeElement === noteFinal;
  if (state.expandedRoundId && state.expandedRoundId !== turnId) {
    await flushTurnSaves();
  }
  state.expandedRoundId = turnId;
  roundInspector.classList.add("on");
  renderRounds(state.note);
  const detail = await api(`/api/notes/${state.note.id}/turns/${turnId}`);
  if (state.expandedRoundId !== turnId) return;
  updateInspectorFields(detail, latestTurn(state.note)?.id === turnId);
  if (keepFinalFocus) noteFinal.focus({ preventScroll: true });
}
async function selectRound(turnId) {
  if (!state.note) return;
  const latestId = latestTurn(state.note)?.id;
  state.pinnedRoundId = turnId === latestId ? null : turnId;
  await showRoundPolish(turnId);
}
async function refreshInspector() {
  if (!state.note) return;
  const turnId = inspectedTurnId(state.note);
  if (!turnId) {
    roundInspector.classList.remove("on");
    return;
  }
  if (state.expandedRoundId !== turnId) {
    await showRoundPolish(turnId);
    return;
  }
  const detail = await api(`/api/notes/${state.note.id}/turns/${turnId}`);
  if (inspectedTurnId(state.note) !== detail.id) return;
  updateInspectorFields(detail, latestTurn(state.note)?.id === detail.id);
}

function renderNote(note, seedFinal = false) {
  state.note = note;
  if (seedFinal) {
    state.finalDirty = false;
    noteFinal.value = note.final_text || "";
    state.finalRevision = note.final_revision || 0;
    state.finalBaseText = noteFinal.value;
    state.finalApplied = noteFinal.value;
    finalState.textContent = "Saved";
    fit(noteFinal, 0.55);
    syncNoteActions();
  } else {
    applyFinalFromServer(note.final_text || "", note.final_revision || 0);
  }
  renderRounds(note);
}

function visibleHistory() {
  const kind = state.mode === "note" ? "note" : "session";
  return state.history.filter((item) => item.kind === kind);
}
function renderHistory() {
  const visible = visibleHistory();
  historyEl.replaceChildren();
  if (!visible.length) {
    historyEl.innerHTML = state.mode === "note"
      ? '<p class="empty">No notes yet.</p>'
      : '<p class="empty">No lectures yet.</p>';
    return;
  }
  for (const item of visible) {
    const button = document.createElement("button");
    button.className = "hist";
    button.classList.toggle(
      "active",
      state.selectedKind === item.kind && state.selectedId === item.id,
    );
    const title = item.kind === "note"
      ? item.title
      : `${item.course ? `${item.course} · ` : "Lecture · "}${item.title || ""}`;
    const count = item.kind === "note"
      ? `${item.turn_count} turn${item.turn_count === 1 ? "" : "s"}`
      : `${item.chunk_count} part${item.chunk_count === 1 ? "" : "s"}`;
    button.innerHTML = `<span class="when"></span><span class="meta"></span>`;
    button.querySelector(".when").textContent = title;
    const meta = button.querySelector(".meta");
    const status = itemStatus(item);
    meta.textContent = `${fmt(item.duration_seconds)} · ${count} · ${status}`;
    if (historyMetaIsSerious(item, status)) meta.classList.add("fail");
    const del = document.createElement("button");
    del.type = "button";
    del.className = "hist-del";
    del.title = "Delete";
    del.textContent = "×";
    del.onclick = (event) => {
      event.stopPropagation();
      deleteHistoryItem(item.kind, item.id);
    };
    button.appendChild(del);
    button.onclick = () => selectItem(item.kind, item.id);
    historyEl.appendChild(button);
  }
}
async function selectItem(kind, id) {
  if (state.recording) return;
  await flushFinalSave();
  await flushTurnSaves();
  await flushSessionSave();
  state.selectedKind = kind;
  state.selectedId = id;
  state.mode = kind === "note" ? "note" : "lecture";
  state.expandedRoundId = null;
  state.pinnedRoundId = null;
  roundInspector.classList.remove("on");
  if (kind === "note") {
    renderNote(await api(`/api/notes/${id}`), true);
    await refreshInspector();
  } else {
    renderSession(await api(`/api/sessions/${id}`), true);
  }
  applyMode();
  renderHistory();
}
async function switchMode(mode) {
  if (state.recording || state.mode === mode) return;
  try {
    await flushFinalSave();
    await flushTurnSaves();
    await flushSessionSave();
  } catch (error) {
    setStatus(error.message);
  }
  const kind = mode === "note" ? "note" : "session";
  state.mode = mode;
  if (state.selectedKind === kind && state.selectedId) {
    applyMode();
    renderHistory();
    return;
  }
  const recent = state.history.find((item) => item.kind === kind);
  if (recent) {
    await selectItem(kind, recent.id);
    return;
  }
  state.selectedKind = kind;
  state.selectedId = null;
  if (kind === "note") {
    resetNoteEditor();
  } else {
    state.session = null;
    listenerNotes.value = "";
    lectureDraft.value = "";
    lecturePolished.value = "";
    resetQuestionFields();
  }
  applyMode();
  renderHistory();
}
function resetQuestionFields() {
  stopQuestionWaiting();
  el("questionSuggestion").hidden = true;
  questionStatus("Uses your question first, or the selected note. Only transcribed audio is available.");
  questionOut.value = "";
  questionRefine.value = "";
  copyQuestionBtn.disabled = true;
}
function resetNoteEditor() {
  state.note = null;
  state.roundNodes.clear();
  state.expandedRoundId = null;
  state.pinnedRoundId = null;
  state.finalRevision = 0;
  state.finalBaseText = "";
  state.finalApplied = "";
  state.finalDirty = false;
  noteFinal.value = "";
  finalState.textContent = "Saved";
  roundsList.innerHTML = '<p class="empty">No rounds yet.</p>';
  roundsTitle.textContent = "Rounds";
  roundInspector.classList.remove("on");
  inspectorPolished.value = "";
  copyNoteBtn.disabled = true;
  clearNoteBtn.disabled = true;
}
async function createAndSelectNote() {
  const note = await api("/api/notes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: "" }),
  });
  state.selectedKind = "note";
  state.selectedId = note.id;
  state.mode = "note";
  state.expandedRoundId = null;
  state.pinnedRoundId = null;
  roundInspector.classList.remove("on");
  renderNote(note, true);
  applyMode();
  await sync();
  return note;
}

async function flushSessionSave() {
  clearTimeout(state.lectureSaveTimer);
  clearTimeout(state.notesSaveTimer);
  if (state.selectedKind !== "session" || !state.selectedId) return state.sessionSaveChain;
  const saveDraft = state.lectureDirty;
  const saveNotes = state.notesDirty;
  if (!saveDraft && !saveNotes) return state.sessionSaveChain;
  const id = state.selectedId;
  const draft = lectureDraft.value;
  const notes = listenerNotes.value;
  const chunkIds = [...state.mergedChunks];
  let baseRevision = state.sessionRevision;
  state.sessionSavePending++;
  state.lectureDirty = false;
  state.notesDirty = false;
  state.lectureApplied = draft;
  state.notesApplied = notes;
  const run = async () => {
    try {
      if (state.selectedId === id) baseRevision = state.sessionRevision;
      const saved = await api(`/api/sessions/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          base_revision: baseRevision,
          text: saveDraft ? draft : undefined,
          listener_notes: saveNotes ? notes : undefined,
          draft_chunk_ids: chunkIds,
        }),
      });
      if (state.selectedId === id) state.sessionRevision = saved.revision;
      const key = `speech-draft-${id}`;
      const cached = JSON.parse(localStorage.getItem(key) || "null");
      if (cached?.text === draft && cached?.notes === notes) localStorage.removeItem(key);
      clearCaptureNotice(NOTES_UNSAVED_NOTICE);
    } catch (error) {
      if (state.selectedId === id) {
        state.lectureDirty ||= saveDraft;
        state.notesDirty ||= saveNotes;
        if (state.recording) showCaptureNotice(NOTES_UNSAVED_NOTICE, 1);
        else setStatus(error.message);
      }
      throw error;
    } finally {
      state.sessionSavePending--;
    }
  };
  state.sessionSaveChain = state.sessionSaveChain.then(run, run);
  await state.sessionSaveChain;
}
async function mergeSessionChunks(detail) {
  // Backend assembles session text. Never append into shared browser state.
  if (detail.id !== state.selectedId || state.lectureDirty || state.sessionSavePending) return;
  const top = lectureDraft.scrollTop;
  const start = lectureDraft.selectionStart;
  const end = lectureDraft.selectionEnd;
  const next = detail.display_text ?? detail.raw_transcript ?? "";
  if (lectureDraft.value !== next) {
    lectureDraft.value = next;
    lectureDraft.setSelectionRange(start, end);
    lectureDraft.scrollTop = top;
  }
  state.lectureApplied = next;
  state.mergedChunks = new Set(detail.draft_chunk_ids || []);
}
async function renderSession(detail, seed = false) {
  if (state.selectedKind !== "session" || detail.id !== state.selectedId) return;
  if (state.session?.id === detail.id && (detail.revision || 0) < state.sessionRevision) return;
  seed ||= state.session?.id !== detail.id;
  const workspaceTop = lectureWorkspace.scrollTop;
  state.session = detail;
  if (seed) {
    courseEl.value = detail.course || "";
    listenerNotes.value = detail.listener_notes || "";
    lectureDraft.value = detail.display_text ?? detail.raw_transcript ?? "";
    questionOut.value = localStorage.getItem(`speech-question-${detail.id}`) ?? detail.latest_question ?? "";
    stopQuestionWaiting();
    showQuestionSuggestion(detail.latest_question_suggestion);
    questionStatus("Uses your question first, or the selected note. Only transcribed audio is available.");
    copyQuestionBtn.disabled = !questionOut.value;
    state.notesApplied = listenerNotes.value;
    state.lectureApplied = lectureDraft.value;
    state.notesDirty = false;
    state.lectureDirty = false;
    state.sessionRevision = detail.revision || 0;
    state.mergedChunks = new Set(detail.draft_chunk_ids || []);
    if (!state.mergedChunks.size) {
      for (const chunk of detail.chunks || []) {
        if (chunk.raw_transcript) state.mergedChunks.add(chunk.id);
      }
    }
  }
  if (!state.lectureDirty && !state.notesDirty && !state.sessionSavePending) {
    state.sessionRevision = detail.revision || 0;
    if (listenerNotes.value !== (detail.listener_notes || "")) listenerNotes.value = detail.listener_notes || "";
    state.notesApplied = listenerNotes.value;
  }
  if (seed) {
    const cached = JSON.parse(localStorage.getItem(`speech-draft-${detail.id}`) || "null");
    if (cached) {
      lectureDraft.value = cached.text;
      listenerNotes.value = cached.notes;
      state.lectureDirty = cached.text !== state.lectureApplied;
      state.notesDirty = cached.notes !== state.notesApplied;
      state.sessionRevision = cached.revision;
      setStatus("Recovered local edits. Copy them before resolving any save conflict.", 1);
    }
  }
  assignValue(lecturePolished, detail.polished_transcript || "");
  renderLectureHealth(detail);
  if (retryLecturePolish) {
    retryLecturePolish.hidden = !detail.polish_skipped;
  }
  copyNoteBtn.disabled = !lectureDraft.value;
  await mergeSessionChunks(detail);
  copyNoteBtn.disabled = !lectureDraft.value;
  lectureWorkspace.scrollTop = workspaceTop;
}

async function sync() {
  if (state.syncing) return;
  state.syncing = true;
  try {
    const [notes, sessions] = await Promise.all([
      api("/api/notes"),
      api("/api/sessions"),
    ]);
    state.history = [
      ...notes.map((item) => ({ ...item, kind: "note" })),
      ...sessions.map((item) => ({ ...item, kind: "session" })),
    ].sort((a, b) => (a.updated_at || a.created_at) < (b.updated_at || b.created_at) ? 1 : -1);
    renderHistory();
    // Hotkey / ?record=1 starts a new lecture; do not seed the previous session
    // into Course (that was overwriting Calendar autofill).
    if (!state.selectedId && !state.recording && !state.bootNewLecture) {
      const wanted = state.mode === "note" ? "note" : "session";
      const recent = state.history.find((item) => item.kind === wanted);
      if (recent) {
        state.selectedKind = wanted;
        state.selectedId = recent.id;
      }
    }
    if (state.selectedId) {
      if (state.selectedKind === "note") {
        renderNote(await api(`/api/notes/${state.selectedId}`));
        await refreshInspector();
      } else {
        await renderSession(await api(`/api/sessions/${state.selectedId}`));
      }
      renderHistory();
    }
    clearCaptureNotice(HISTORY_REFRESH_NOTICE);
    clearCaptureNotice(HISTORY_DURING_NOTE_SAVE);
  } catch (error) {
    if (state.recording) {
      holdRecordingStatus();
      showCaptureNotice(HISTORY_REFRESH_NOTICE, 0);
    } else if (state.noteTakePending) {
      holdNoteTakeStatus();
      showCaptureNotice(HISTORY_DURING_NOTE_SAVE, 0);
    } else {
      setStatus(error.message);
    }
  } finally {
    state.syncing = false;
  }
}
function hasPending() {
  return state.history.some((item) =>
    item.transcription_pending_chunks
    || item.cleanup_pending_chunks
    || ["transcribing", "polishing", "captured", "transcribed", "open"].includes(item.state));
}

function recordingUI(on) {
  state.recording = on;
  recordBtn.classList.toggle("live", on);
  recordBtn.setAttribute("aria-label", on ? "Stop" : "Record");
  discardBtn.disabled = !on;
  newBtn.disabled = on;
  noteModeBtn.disabled = on;
  lectureModeBtn.disabled = on;
}
function armRecorder() {
  state.blobs = [];
  state.recorder = new MediaRecorder(state.media);
  const recorder = state.recorder;
  const parts = state.blobs;
  recorder.captureId = crypto.randomUUID();
  recorder.backupChain = Promise.resolve();
  recorder.ondataavailable = (event) => {
    if (!event.data.size) return;
    parts.push(event.data);
    if (state.recordingMode !== "lecture") return;
    const row = { id: recorder.captureId, blob: new Blob(parts, { type: recorder.mimeType }),
      sessionId: state.liveSessionId, index: state.chunkIndex,
      complete: recorder.state === "inactive", createdAt: Date.now() };
    recorder.backupChain = recorder.backupChain.then(() => SpeechRecovery.put(row)).then(() => {
      recorder.backupDurable = true;
      recorder.backupEverDurable = true;
      const notice = el("captureNotice").textContent || "";
      if (notice.startsWith("Audio backup failed")) clearLiveCaptureNotices();
      if (state.recorder === recorder) refreshLectureSetupHold();
    }).catch((error) => {
      recorder.backupDurable = false;
      holdRecordingStatus();
      const earlier = recorder.backupEverDurable
        ? " An earlier backup of this part stays on this device."
        : "";
      // Higher than lecture-setup notices so a failed backup is not replaced.
      showCaptureNotice(`Audio backup failed: ${safeClientDetail(error)}. Keep this tab open.${earlier} Recording continues.`, 3);
      if (state.recorder === recorder) refreshLectureSetupHold();
    });
  };
  state.recorder.onstop = onRecorderStop;
  state.recorder.start(5000);
  state.chunkStartedAt = Date.now();
}
function isFreshLecture(item) {
  if (!item || item.kind !== "session") return false;
  if (item.status === "open") return Date.now() - Date.parse(item.created_at) < LECTURE_MAX * 1000;
  const stamp = item.ended_at || item.updated_at || item.created_at;
  if (!stamp) return false;
  return Date.now() - Date.parse(stamp) < 30 * 60 * 1000;
}
function lectureSessionTitle() {
  return new Date().toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
async function applyCalendarSuggestion(options = {}) {
  const force = Boolean(options.force);
  const fromQuery = typeof options.courseHint === "string" ? options.courseHint.trim() : "";
  if (fromQuery && (force || !courseEl.value.trim())) {
    courseEl.value = fromQuery;
  }
  if (courseEl.value.trim() && !force) return null;
  try {
    const hint = await api("/api/calendar/suggest", { signal: AbortSignal.timeout(9000) });
    if (hint?.course && (force || !courseEl.value.trim())) {
      courseEl.value = hint.course;
      const courseLine = `Course from Calendar · ${hint.course}`;
      if (state.recording) showCaptureNotice(courseLine, 0);
      else setStatus(courseLine);
    } else if (hint && hint.authorized === false && hint.detail === "calendar_access_denied") {
      const denied = "Calendar access denied. Enable Speech Tool under System Settings → Privacy & Security → Calendars.";
      if (state.recording) showCaptureNotice(denied, 1);
      else setStatus(denied);
    } else if (hint && hint.detail === "calendar_helper_missing") {
      const missing = "Calendar helper not installed. Re-run install-desktop.py --install after building calendar-current.";
      if (state.recording) showCaptureNotice(missing, 1);
      else setStatus(missing);
    }
    return hint;
  } catch (_) {
    return null;
  }
}
async function prepareRecordingTarget(options = {}) {
  const forceNew = Boolean(options.forceNew);
  await flushFinalSave();
  await flushTurnSaves();
  await flushSessionSave();
  state.createdNoteForRecording = false;
  if (state.recordingMode === "note") {
    if (state.selectedKind !== "note" || !state.selectedId) {
      await createAndSelectNote();
      state.createdNoteForRecording = true;
    }
    return;
  }
  const existing = !forceNew && state.selectedKind === "session" && state.selectedId
    ? state.history.find((item) => item.kind === "session" && item.id === state.selectedId)
    : null;
  if (existing && isFreshLecture(existing)) {
    await api(`/api/sessions/${existing.id}/reopen`, { method: "POST" });
    state.liveSessionId = existing.id;
    state.uploads = [];
    const detail = await api(`/api/sessions/${existing.id}`);
    const localRows = await SpeechRecovery.list();
    state.chunkIndex = Math.max(detail.next_chunk_index ?? Math.max(0, ...(detail.chunks || []).map(c => (c.chunk_index ?? -1) + 1)),
      ...localRows.filter(row => row.sessionId === existing.id && row.id !== state.recorder?.captureId).map(row => (row.index ?? -1) + 1));
    state.recordingOffset = detail.duration_seconds || 0;
    state.bootNewLecture = false;
    await renderSession(detail, true);
  } else {
    await applyCalendarSuggestion({
      courseHint: options.courseHint,
      // New lecture from Control-Option-L must keep Calendar, not the prior session's course.
      force: Boolean(forceNew),
    });
    const session = await api("/api/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        course: courseEl.value || "",
        title: lectureSessionTitle(),
      }),
    });
    state.selectedKind = "session";
    state.selectedId = session.id;
    state.liveSessionId = session.id;
    state.chunkIndex = 0;
    state.recordingOffset = 0;
    state.uploads = [];
    state.bootNewLecture = false;
    await renderSession(session, true);
  }
  await sync();
}
async function startRecording(options = {}) {
  if (state.recording || state.starting) return;
  state.starting = true;
  const source = el('audioSource').value;
  el('captureNotice').textContent = '';
  delete el('captureNotice').dataset.priority;
  el('audioSource').disabled = true;
  recordBtn.disabled = true;
  // Start the picker on this click, before awaiting the cross-tab lock.
  const openCapture = () => SpeechCapture.open(source, () => {
    if (state.recording) stopRecording();
    el('captureNotice').textContent = 'Meeting sharing ended. Recording stopped; saved audio will continue processing.';
  }, levels => {
    el('micLevel').value = levels.microphone || 0;
    el('meetingLevel').value = levels.meeting || 0;
  });
  const capturePromise = source === 'meeting' ? openCapture() : null;
  capturePromise?.catch(() => {});
  if (!await claimCapture()) {
    capturePromise?.then(c => c.close()).catch(() => {});
    state.starting = false;
    el('audioSource').disabled = false;
    recordBtn.disabled = false;
    setStatus(captureBlockedMessage(false));
    return;
  }
  if (options.forceLecture) {
    state.mode = "lecture";
    applyMode();
  }
  try {
    state.capture = await (capturePromise || openCapture());
    state.media = state.capture.stream;
  } catch (error) {
    state.releaseCaptureLock?.();
    state.starting = false;
    el('audioSource').disabled = false;
    recordBtn.disabled = false;
    el('captureNotice').textContent = error.message;
    setStatus(error.message);
    return;
  }
  state.starting = false;
  recordBtn.disabled = false;
  el('audioMeters').hidden = false;
  el('meetingMeterLabel').hidden = source !== 'meeting';
  state.recordingMode = options.forceLecture ? "lecture" : state.mode;
  state.discard = false;
  state.rotating = false;
  state.autoStopped = false;
  state.captureReadyState = "pending";
  armRecorder();
  state.startedAt = Date.now();
  recordingUI(true);
  state.tick = setInterval(() => {
    const elapsed = (Date.now() - state.startedAt) / 1000;
    timerEl.textContent = fmt(elapsed + state.recordingOffset);
    if (state.recordingMode === "note" && elapsed >= NOTE_MAX) stopRecording();
    if (state.recordingMode === "lecture" && elapsed >= LECTURE_MAX) {
      state.autoStopped = true;
      stopRecording();
      return;
    }
    if (state.recordingMode === "lecture" && !state.rotating &&
        (Date.now() - state.chunkStartedAt) / 1000 >= LECTURE_CHUNK) {
      state.rotating = true;
      state.recorder.stop();
    }
  }, 200);
  setStatus(state.recordingMode === "note" ? "Recording note" : "Recording lecture");
  state.captureReady = prepareRecordingTarget({
    forceNew: Boolean(options.forceNew),
    courseHint: options.courseHint,
  }).then(
    (value) => {
      state.captureReadyState = "ok";
      return value;
    },
    (error) => {
      state.captureReadyState = "failed";
      throw error;
    },
  );
  try {
    await state.captureReady;
    setStatus(state.recordingMode === "note"
      ? `Recording round ${(state.note?.turn_count || 0) + 1}`
      : `Recording lecture · part ${state.chunkIndex + 1}`);
    const notice = el("captureNotice").textContent || "";
    if (notice.startsWith("Lecture setup failed") || notice.startsWith("Note setup failed")) {
      clearLiveCaptureNotices();
    }
  } catch (error) {
    if (state.recording && state.recordingMode === "lecture") {
      setStatus(lectureSetupHoldStatus());
      const notice = el("captureNotice").textContent || "";
      if (!notice.startsWith("Audio backup failed")) {
        showCaptureNotice(`Lecture setup failed: ${safeClientDetail(error)}. Recording continues.`, 2);
      }
    } else if (state.recording) {
      setStatus("Recording note. This take is not saved if you stop now.");
      showCaptureNotice(`Note setup failed: ${safeClientDetail(error)}. Recording continues.`, 2);
    } else {
      setStatus(error.message);
    }
  }
}
function finishRecording(discard) {
  if (!state.recording) return;
  state.discard = discard;
  recordingUI(false);
  clearInterval(state.tick);
  if (state.recorder?.state !== "inactive") state.recorder.stop();
  state.media?.getTracks().forEach((track) => track.stop());
  state.capture?.close();
  state.capture = null;
  el('audioSource').disabled = false;
  el('audioMeters').hidden = true;
  clearLiveCaptureNotices();
}
const stopRecording = () => finishRecording(false);
const discardRecording = () => finishRecording(true);
async function saveNoteTurn(blob) {
  if (state.captureReady) await state.captureReady;
  const form = new FormData();
  form.append("file", blob, "recording.webm");
  setStatus(NOTE_TAKE_SAVING_STATUS);
  const turn = await api(`/api/notes/${state.selectedId}/turns`, {
    method: "POST",
    body: form,
  });
  state.releaseNoteTakeHold?.();
  const summary = {
    ...turn,
    asr_draft: null,
    polished_draft: null,
    raw_transcript: null,
    polished_transcript: null,
    preview: turn.preview || "",
  };
  state.note.turns = [...(state.note.turns || []), summary];
  state.note.turn_count = state.note.turns.length;
  state.pinnedRoundId = null;
  renderRounds(state.note);
  setStatus(`Round ${turn.turn_index + 1} · transcribing`);
  await sync();
}
async function uploadLectureChunk(blob, sessionId, index, captureId) {
  const form = new FormData();
  form.append("file", blob, `chunk-${index + 1}.webm`);
  return api(`/api/events?session_id=${encodeURIComponent(sessionId)}&chunk_index=${index}&capture_id=${captureId}`, {
    method: "POST",
    body: form,
  });
}
const uploadingCaptures = new Map();
const blockedCaptures = new Set();
const unjournaledCaptures = [];
let recoveryBusy = false;
async function listRecoverableCaptures() {
  const stored = await SpeechRecovery.list().catch(() => []);
  const memoryIds = new Set(unjournaledCaptures.map((row) => row.id));
  return stored.filter((row) => !memoryIds.has(row.id)).concat(unjournaledCaptures);
}
async function putCaptureRow(row) {
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      await SpeechRecovery.put(row);
      row.memoryOnly = false;
      const index = unjournaledCaptures.findIndex((item) => item.id === row.id);
      if (index >= 0) unjournaledCaptures.splice(index, 1);
      return true;
    } catch (_) { /* Retry once, then keep the part in this tab. */ }
  }
  row.memoryOnly = true;
  if (!unjournaledCaptures.some((item) => item.id === row.id)) unjournaledCaptures.push(row);
  return false;
}
async function sendCapture(row) {
  if (uploadingCaptures.has(row.id)) return uploadingCaptures.get(row.id);
  const work = (async () => {
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const saved = await uploadLectureChunk(row.blob, row.sessionId, row.index, row.id);
        if (!saved.id || saved.capture_id !== row.id || saved.session_id !== row.sessionId || saved.chunk_index !== row.index) {
          throw new Error('Server acknowledgement did not match this recording; local audio retained');
        }
        await SpeechRecovery.remove(row.id);
        const held = unjournaledCaptures.findIndex((item) => item.id === row.id);
        if (held >= 0) unjournaledCaptures.splice(held, 1);
        blockedCaptures.delete(row.id);
        return saved;
      } catch (error) {
        if (error.status >= 400 && error.status < 500 && ![408, 429].includes(error.status)) {
          blockedCaptures.add(row.id);
          throw error;
        }
        if (attempt === 2 || !navigator.onLine) throw error;
        await new Promise(resolve => setTimeout(resolve, [750, 2000][attempt]));
      }
    }
  })();
  uploadingCaptures.set(row.id, work);
  refreshRecoveryStatus();
  try { return await work; }
  finally { uploadingCaptures.delete(row.id); await refreshRecoveryStatus(); }
}
function uploadingRecoveryDetail() {
  const ids = [...uploadingCaptures.keys()];
  const count = ids.length;
  const memory = ids.filter((id) => unjournaledCaptures.some((row) => row.id === id)).length;
  const noun = `recording part${count === 1 ? "" : "s"}`;
  if (!memory) {
    return count === 1
      ? "Uploading 1 recording part · the copy in this browser stays until the server confirms it."
      : `Uploading ${count} recording parts · the copies in this browser stay until the server confirms them.`;
  }
  if (memory === count) {
    const be = count === 1 ? "it is" : "they are";
    const pronoun = count === 1 ? "it" : "them";
    return `Uploading ${count} ${noun} · ${be} only in this tab until the server confirms ${pronoun}. Keep this tab open.`;
  }
  const durable = count - memory;
  const memBe = memory === 1 ? "is" : "are";
  const pronoun = memory === 1 ? "it" : "them";
  const durableBit = durable === 1
    ? "The other copy stays in this browser until the server confirms it."
    : `The other ${durable} copies stay in this browser until the server confirms them.`;
  return `Uploading ${count} ${noun} · ${memory} ${memBe} only in this tab until the server confirms ${pronoun}. ${durableBit} Keep this tab open.`;
}
async function refreshRecoveryStatus() {
  try {
    const rows = (await listRecoverableCaptures()).filter(row => !(state.recording && row.id === state.recorder?.captureId));
    const panel = el('recoveryPanel');
    panel.hidden = !rows.length && !recoveryBusy;
    el('recoverAudio').hidden = !rows.length;
    el('recoverAudio').disabled = recoveryBusy || state.recording;
    el('recoverAudio').textContent = recoveryBusy ? 'Recovering…' : 'Recover audio';
    el('recoveryStatus').textContent = recoveryBusy ? 'Restoring saved audio to its original lecture…'
      : uploadingCaptures.size ? uploadingRecoveryDetail()
      : recoveryQueueDetail(rows);
  } catch (error) {
    el('recoveryPanel').hidden = false;
    el('recoveryStatus').textContent = 'Browser audio backup is unavailable. Keep this tab open until uploads finish.';
  }
}
function publicCleanupDetail(detail) {
  const text = String(detail || "").replace(/\s+/g, " ").trim();
  if (!text.startsWith("AI cleanup") || text.length > 180 || /[\\/]/.test(text)) return "";
  return text.replace(/[.]+$/, "");
}
function cleanupPausePhrase(seconds) {
  const remaining = Math.max(0, Number(seconds) || 0);
  if (remaining >= 90) return `about ${Math.ceil(remaining / 60)} min`;
  if (remaining > 0) return `${remaining}s`;
  return "a short time";
}
function recoveryQueueDetail(rows) {
  const partialLoose = rows.filter((row) => !row.complete && !row.sessionId);
  const partialHeld = rows.filter((row) => !row.complete && row.sessionId);
  const unassigned = rows.filter((row) => row.complete && !row.sessionId);
  const blocked = rows.filter((row) => row.complete && row.sessionId && blockedCaptures.has(row.id));
  const waiting = rows.filter((row) => row.complete && row.sessionId && !blockedCaptures.has(row.id));
  const memoryOnly = rows.filter((row) => row.memoryOnly);
  const durableCount = rows.length - memoryOnly.length;
  const bits = [];
  if (durableCount || !memoryOnly.length) {
    bits.push(`${durableCount} recording part${durableCount === 1 ? "" : "s"} saved in this browser`);
  }
  if (memoryOnly.length) {
    const count = memoryOnly.length;
    bits.push(`${count} part${count === 1 ? " is" : "s are"} only in this tab. Keep this tab open; closing it drops ${count === 1 ? "that part" : "those parts"}`);
  }
  if (partialHeld.length) {
    const count = partialHeld.length;
    bits.push(`${count} interrupted part${count === 1 ? "" : "s"} need review. Recover audio uploads ${count === 1 ? "it" : "them"} after you stop`);
  }
  if (partialLoose.length) {
    const count = partialLoose.length;
    bits.push(`${count} interrupted part${count === 1 ? "" : "s"} never joined a lecture. Recover audio downloads ${count === 1 ? "it" : "them"} after you stop`);
  }
  if (unassigned.length) {
    bits.push(`${unassigned.length} part${unassigned.length === 1 ? "" : "s"} could not join a lecture. Use Recover audio after stopping to download ${unassigned.length === 1 ? "it" : "them"}`);
  }
  if (blocked.length) {
    bits.push(`${blocked.length} part${blocked.length === 1 ? " was" : "s were"} rejected by the server and will not retry until you use Recover audio`);
  }
  if (waiting.length) {
    bits.push(state.recording
      ? "Completed parts retry automatically after recording stops"
      : "Completed parts retry automatically");
  }
  return `${bits.join(". ")}.`;
}
function renderLectureHealth(detail) {
  const missing = detail.missing_chunk_indices || [];
  const failed = detail.asr_failed_chunks || 0;
  const duplicate = detail.duplicate_chunk_indices || [];
  const kind = cleanupBreakdown(detail);
  const { cleanup, guard, providerFailed, cooldown, providerDown, guardOnly, providerPause } = kind;
  // Red/attention only for capture/ASR problems or paused provider; optional unfinished cleanup stays calm.
  el('lectureHealth').dataset.attention = Boolean(missing.length || failed || duplicate.length || detail.empty_transcript_chunks || providerPause);
  // Capture and transcription come before optional cleanup, so a later part
  // still transcribing is not described as a saved transcript.
  el('lectureHealthTitle').textContent = !detail.chunk_count ? 'Ready to record'
    : missing.length ? 'Some audio has not reached this lecture'
    : failed ? 'Audio saved · transcription needs retry'
    : detail.transcription_pending_chunks ? 'Audio saved · transcribing'
    : detail.empty_transcript_chunks === 1 ? 'Audio saved · 1 part has no detected speech'
    : detail.empty_transcript_chunks ? `Audio saved · ${detail.empty_transcript_chunks} parts have no detected speech`
    : duplicate.length ? 'Duplicate part numbers need review'
    : providerPause ? 'Transcript saved · AI cleanup unavailable'
    : guardOnly ? 'Transcript saved · original kept'
    : cleanup ? 'Transcript saved · AI cleanup unfinished'
    : detail.cleanup_pending_chunks ? 'Transcript saved · cleaning up'
    : 'Transcript saved';
  const parts = [`${detail.chunk_count || 0} parts uploaded`, `${detail.transcribed_chunks ?? detail.chunk_count ?? 0} transcribed`];
  if (detail.transcription_pending_chunks) {
    const pendingAsr = detail.transcription_pending_chunks;
    parts.push(`${pendingAsr} part${pendingAsr === 1 ? '' : 's'} still transcribing`);
  }
  if (failed) parts.push(`${failed} part${failed === 1 ? '' : 's'} need transcription retry`);
  if (detail.empty_transcript_chunks) {
    const silent = detail.empty_transcript_chunks;
    const noun = silent === 1 ? "part" : "parts";
    parts.push(`${silent} ${noun} finished without transcript text. Check your audio source; a missing speaker signal cannot be restored by text cleanup`);
  }
  if (missing.length) parts.push(`Missing part${missing.length === 1 ? '' : 's'}: ${missing.slice(0, 8).map(i => i + 1).join(', ')}${missing.length > 8 ? '…' : ''}. Check Recover audio in the original browser`);
  if (duplicate.length) parts.push('Duplicate part numbers need review');
  if (providerPause) {
    const safeDetail = publicCleanupDetail(detail.cleanup_provider_detail);
    parts.push(`AI cleanup is paused for ${cleanupPausePhrase(cooldown)} after repeated provider failures. Original transcript remains. Retry cleanup tries again now`);
    if (safeDetail) parts.push(safeDetail);
  } else if (providerFailed) {
    parts.push(`${providerFailed} cleanup result${providerFailed === 1 ? '' : 's'} need retry; original transcript remains available`);
  } else if (cleanup && !guard) {
    parts.push(`${cleanup} cleanup result${cleanup === 1 ? '' : 's'} need retry; original transcript remains available`);
  } else if (detail.cleanup_pending_chunks) {
    parts.push('Optional cleanup is still processing');
  }
  if (guard) parts.push(`${guard} cleanup result${guard === 1 ? '' : 's'} kept the original after a language or length check`);
  if (!providerPause && providerDown && guardOnly) {
    parts.push(`Automatic cleanup is paused for ${cleanupPausePhrase(cooldown)}. Retry cleanup tries again now`);
  }
  if (detail.status === 'open' && !state.recording) parts.push('Session not marked ended');
  if (detail.chunk_count && !detail.completeness_known && !missing.length) parts.push('No internal gaps detected; recording-end completeness not verified');
  el('lectureHealthDetail').textContent = parts.join(' · ');
  el('retryTranscription').hidden = !failed;
  el('retryCleanup').hidden = !cleanup;
  el('copyTranscriptPath').hidden = !(detail.chunk_count > 0);
  el('cleanupSummary').textContent = providerPause
    ? `Cleanup is paused for ${cleanupPausePhrase(cooldown)} after repeated provider failures. Original transcript text stays available. Retry cleanup tries again now. Your notes are unchanged.`
    : guardOnly
      ? `Original transcript kept where cleanup changed the language or removed too much.${providerDown ? ` Automatic cleanup is paused for ${cleanupPausePhrase(cooldown)}.` : ''} Your saved notes are unchanged.`
      : cleanup ? 'Uses original text where cleanup failed or changed the language. Your saved notes are unchanged.'
      : 'Optional cleanup. Original text is used for parts still processing.';
}
function rememberStoppedLecture(sessionId, expected) {
  localStorage.setItem(`speech-stop-${sessionId}`, JSON.stringify({expected_chunk_count: expected}));
}
function lectureEndPendingStatus(base, pending) {
  if (!pending) return base;
  const which = pending === 1 ? "A lecture is" : "Lectures are";
  return `${base} ${which} not marked ended yet; that retry continues automatically.`;
}
function liveUploadFailureStatus(error) {
  const prefix = `Recording lecture · part ${state.chunkIndex + 1}.`;
  if (!error.localAudioRetained) return `${prefix} ${safeClientDetail(error)}`;
  const blocked = Boolean(error.uploadBlocked);
  if (error.memoryOnly) {
    return blocked
      ? `${prefix} Earlier part is only in this tab and will not retry until you use Recover audio. Keep this tab open.`
      : `${prefix} Earlier part is only in this tab. It retries automatically after you stop. Keep this tab open.`;
  }
  return blocked
    ? `${prefix} Earlier part stays on this device and will not retry until you use Recover audio.`
    : `${prefix} Earlier part stays on this device. It retries automatically after you stop.`;
}
function rejectedUploadStopStatus(captureId) {
  const tabOnly = unjournaledCaptures.some((item) => item.id === captureId);
  const where = tabOnly
    ? "This part is only in this tab and will not retry until you use Recover audio. Keep this tab open."
    : "This part stays on this device and will not retry until you use Recover audio.";
  const pending = state.stopEndPending;
  const ending = !pending ? ""
    : pending === 1
      ? " The lecture is not marked ended yet; that end request retries automatically."
      : " Lectures are not marked ended yet; those end requests retry automatically.";
  return `Recording stopped. ${where}${ending}`;
}
async function finishStoppedLectures() {
  let pending = 0;
  for (const key of Object.keys(localStorage).filter(key => key.startsWith('speech-stop-'))) {
    const sid = key.slice('speech-stop-'.length);
    if (state.recording && sid === state.liveSessionId) continue;
    const body = localStorage.getItem(key);
    if (!body) continue;
    try {
      await api(`/api/sessions/${sid}/end`, {method:'POST', headers:{'Content-Type':'application/json'}, body, signal:AbortSignal.timeout(5000)});
      if (localStorage.getItem(key) === body) localStorage.removeItem(key);
    } catch (error) {
      if (error.status === 404 && localStorage.getItem(key) === body) {
        localStorage.removeItem(key);
        continue;
      }
      pending += 1;
    }
  }
  return pending;
}
function continueLectureCapture() {
  state.rotating = false;
  state.chunkIndex += 1;
  armRecorder();
  return `Recording lecture · part ${state.chunkIndex + 1}`;
}
async function saveLectureChunk(blob, captureId) {
  const continuing = state.recording;
  // Arm the next minute before awaiting session setup once that setup has
  // already settled. A rejected session must not leave the timer running
  // with the microphone stopped. While setup is still pending, wait so the
  // server-assigned part number is not guessed.
  let armedNext = false;
  if (continuing && state.captureReadyState !== "pending") {
    setStatus(continueLectureCapture());
    armedNext = true;
  }
  if (state.captureReady) {
    try {
      await state.captureReady;
    } catch (_) {
      // Keep the finished part in the local journal below.
    }
  }
  if (continuing && state.recording && !armedNext) {
    setStatus(continueLectureCapture());
    armedNext = true;
  }
  const sessionId = state.liveSessionId;
  const index = armedNext ? state.chunkIndex - 1 : state.chunkIndex++;
  const row = {
    id: captureId,
    blob,
    sessionId: sessionId || "",
    index,
    complete: true,
    createdAt: Date.now(),
  };
  const journaled = await putCaptureRow(row);
  if (!sessionId) {
    await refreshRecoveryStatus();
    if (state.recording) {
      setStatus(journaled
        ? `Recording lecture · part ${state.chunkIndex + 1}. Earlier part stays on this device. It never joined a lecture. Recover audio downloads it after you stop.`
        : `Recording lecture · part ${state.chunkIndex + 1}. Earlier part is only in this tab and never joined a lecture. Recover audio downloads it after you stop. Keep this tab open.`);
      return;
    }
    const failure = new Error("Lecture session is not ready");
    failure.memoryOnly = !journaled;
    failure.unassigned = true;
    throw failure;
  }
  if (!state.recording) rememberStoppedLecture(sessionId, state.chunkIndex);
  if (!journaled) await refreshRecoveryStatus();
  const upload = sendCapture(row);
  // Observe rejection immediately, even while the next recorder is running.
  upload.catch(() => {});
  state.uploads.push(upload);
  if (state.recording) {
    try {
      await upload;
    } catch (error) {
      error.localAudioRetained = true;
      error.memoryOnly = unjournaledCaptures.some((item) => item.id === captureId);
      error.uploadBlocked = blockedCaptures.has(captureId);
      throw error;
    }
    await sync();
    return;
  }
  // Ending capture does not wait behind network retries. The journal and
  // stop marker survive reload; completeness is tracked independently.
  // A failed end request must not look like the audio itself was lost.
  let unmarked = 0;
  try { unmarked = await finishStoppedLectures(); }
  finally { state.liveSessionId = null; }
  state.stopEndPending = unmarked;
  const stoppedLine = lectureEndPendingStatus(
    'Recording stopped · audio uploads and transcript processing continue in the background.',
    unmarked,
  );
  upload.then(() => sync()).catch(() => {
    refreshRecoveryStatus();
    // A rejected part does not keep uploading. Leave a newer status alone.
    if (state.recording || !blockedCaptures.has(captureId) || state.lastStatus !== stoppedLine) return;
    setStatus(rejectedUploadStopStatus(captureId));
  });
  setStatus(stoppedLine);
  await sync();
}
async function handleDiscard() {
  if (state.captureReady) {
    try { await state.captureReady; } catch (_) {}
  }
  let statusText = "Discarded";
  if (state.recordingMode === "note") {
    const keptRounds = Boolean(state.note?.turn_count);
    if (state.createdNoteForRecording && !keptRounds) {
      await api(`/api/notes/${state.selectedId}`, { method: "DELETE" });
      state.selectedId = null;
      resetNoteEditor();
      await sync();
    } else if (keptRounds) {
      statusText = "This take was discarded. Earlier rounds stay in the note.";
    }
  } else if (state.liveSessionId) {
    if (!state.chunkIndex) {
      await api(`/api/sessions/${state.liveSessionId}`, { method: "DELETE" });
    } else {
      statusText = "In-progress part discarded. Earlier parts of this lecture stay saved.";
      await Promise.allSettled(state.uploads);
      try {
        await api(`/api/sessions/${state.liveSessionId}/end`, { method: "POST" });
      } catch (error) {
        if (error.status !== 404) {
          rememberStoppedLecture(state.liveSessionId, state.chunkIndex);
          statusText = lectureEndPendingStatus(statusText, 1);
        }
      }
    }
    state.liveSessionId = null;
    await sync();
  }
  setStatus(statusText);
}
async function onRecorderStop() {
  const recorder = state.recorder;
  const finalStop = !state.recording;
  const blob = new Blob(state.blobs, {
    type: state.recorder?.mimeType || "audio/webm",
  });
  // Note audio is not in the browser journal. Warn until this stop attempt finishes.
  const noteNeedsHold = finalStop && !state.discard && state.recordingMode === "note" && blob.size > 0;
  if (noteNeedsHold) {
    state.noteTakePending += 1;
    state.releaseNoteTakeHold = () => {
      state.noteTakePending = Math.max(0, state.noteTakePending - 1);
      state.releaseNoteTakeHold = null;
    };
  }
  let failure = null;
  try {
    await recorder.backupChain;
    if (state.discard) await handleDiscard();
    else if (state.recordingMode === "note") await saveNoteTurn(blob);
    else await saveLectureChunk(blob, recorder.captureId);
    if (state.discard && state.recordingMode === "lecture") {
      await SpeechRecovery.remove(recorder.captureId);
      const held = unjournaledCaptures.findIndex((item) => item.id === recorder.captureId);
      if (held >= 0) unjournaledCaptures.splice(held, 1);
    }
  } catch (error) {
    failure = error;
  } finally {
    state.releaseNoteTakeHold?.();
    clearCaptureNotice(HISTORY_DURING_NOTE_SAVE);
    if (finalStop) state.releaseCaptureLock?.();
  }
  if (failure) {
    const error = failure;
    const stillRecording = state.recording && state.recordingMode === "lecture";
    const recovery = stillRecording
      ? liveUploadFailureStatus(error)
      : state.recordingMode === "lecture"
      ? (error.unassigned
        ? (error.memoryOnly
          ? "Lecture session is not ready. This part never joined a lecture and is only in this tab. Recover audio downloads it before this tab closes."
          : "Lecture session is not ready. This part never joined a lecture and stays in this browser. Recover audio downloads it; do not clear browser storage.")
        : error.memoryOnly
        ? `${safeClientDetail(error)} This part is only in this tab. Use Recover audio before closing it.`
        : `${safeClientDetail(error)} · Use Recover audio; do not clear browser storage.`)
      : `${safeClientDetail(error)} · This note take was not saved. Record it again; Recover audio only keeps lecture parts.`;
    setStatus(recovery);
    await refreshRecoveryStatus();
    return;
  }
  if (state.autoStopped) {
    setStatus(lectureEndPendingStatus(
      "Stopped after 2 hours. Audio uploads and transcript processing continue in the background.",
      state.stopEndPending,
    ));
  }
}

noteFinal.addEventListener("input", () => {
  state.finalDirty = noteFinal.value !== state.finalApplied;
  finalState.textContent = state.finalDirty ? "Unsaved" : "Saved";
  syncNoteActions();
  fit(noteFinal, 0.55);
  clearTimeout(state.finalTimer);
  state.finalTimer = setTimeout(() => saveFinal(), 450);
});
async function clearContinuousNote() {
  if (!noteFinal.value) return;
  clearTimeout(state.finalTimer);
  noteFinal.value = "";
  fit(noteFinal, 0.55);
  syncNoteActions();
  if (!state.note) {
    state.finalDirty = false;
    finalState.textContent = "Saved";
    return;
  }
  state.finalDirty = true;
  await saveFinal(true);
  if (!noteFinal.value) setStatus("Cleared");
}
clearNoteBtn.addEventListener("click", () => {
  clearContinuousNote();
});
inspectorPolished.addEventListener("input", () => {
  if (!state.expandedRoundId) return;
  const save = turnSaveState(state.expandedRoundId, "polished");
  save.dirty = inspectorPolished.value !== save.applied;
  copyInspectorPolished.disabled = !inspectorPolished.value;
  fit(inspectorPolished, 0.22);
  clearTimeout(save.timer);
  save.timer = setTimeout(() => saveTurn(save, inspectorPolished), 450);
});
copyInspectorPolished.addEventListener("click", async () => {
  if (!inspectorPolished.value || !state.expandedRoundId) return;
  await navigator.clipboard.writeText(inspectorPolished.value);
  try {
    await api(`/api/events/${state.expandedRoundId}/copy`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: inspectorPolished.value }),
    });
  } catch (error) {
    setStatus(error.message);
    return;
  }
  setStatus("Copied polished draft");
});
retryInspectorPolish.addEventListener("click", async () => {
  if (!state.expandedRoundId) return;
  retryInspectorPolish.disabled = true;
  try {
    await api(`/api/events/${state.expandedRoundId}/retry-polish`, { method: "POST" });
    setStatus("Retrying polish");
    await refreshInspector();
    await sync();
  } catch (error) {
    setStatus(error.message);
  } finally {
    retryInspectorPolish.disabled = false;
  }
});
retryLecturePolish.addEventListener("click", async () => {
  if (state.selectedKind !== "session" || !state.selectedId) return;
  retryLecturePolish.disabled = true;
  try {
    await api(`/api/sessions/${state.selectedId}/retry-polish`, { method: "POST" });
    setStatus("Retrying lecture polish");
    await sync();
  } catch (error) {
    setStatus(error.message);
  } finally {
    retryLecturePolish.disabled = false;
  }
});
async function deleteHistoryItem(kind, id) {
  if (state.recording) return;
  const path = kind === "note" ? `/api/notes/${id}` : `/api/sessions/${id}`;
  await api(path, { method: "DELETE" });
  if (state.selectedId === id) {
    state.selectedId = null;
    state.note = null;
    state.session = null;
    if (kind === "note") resetNoteEditor();
    else {
      listenerNotes.value = "";
      lectureDraft.value = "";
      lecturePolished.value = "";
      resetQuestionFields();
    }
  }
  await sync();
}
listenerNotes.addEventListener("input", () => {
  state.notesDirty = listenerNotes.value !== state.notesApplied;
  clearTimeout(state.notesSaveTimer);
  cacheLectureDraft();
  state.notesSaveTimer = setTimeout(() => flushSessionSave().catch(() => {}), 400);
});
lectureDraft.addEventListener("input", () => {
  state.lectureDirty = lectureDraft.value !== state.lectureApplied;
  copyNoteBtn.disabled = !lectureDraft.value;
  clearTimeout(state.lectureSaveTimer);
  cacheLectureDraft();
  state.lectureSaveTimer = setTimeout(() => flushSessionSave().catch(() => {}), 500);
});
courseEl.addEventListener("change", async () => {
  if (state.selectedKind !== "session" || !state.selectedId) return;
  await flushSessionSave();
  const detail = await api(`/api/sessions/${state.selectedId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ course: courseEl.value }),
  });
  if (detail.id === state.selectedId) state.sessionRevision = detail.revision;
});
stampBtn.addEventListener("click", () => {
  const parts = timerEl.textContent.split(":");
  const seconds = state.recording
    ? state.recordingOffset + (Date.now() - state.startedAt) / 1000
    : Number(parts[0]) * 60 + Number(parts[1]);
  const start = listenerNotes.selectionStart;
  const prefix = start > 0 && listenerNotes.value[start - 1] !== "\n" ? "\n" : "";
  listenerNotes.setRangeText(`${prefix}[${fmt(seconds)}] `, start, listenerNotes.selectionEnd, "end");
  state.notesDirty = true;
  cacheLectureDraft();
  state.notesSaveTimer = setTimeout(() => flushSessionSave().catch(() => {}), 300);
  listenerNotes.focus();
});
let questionRequest = null;
function questionStatus(message, kind = "idle") {
  el("questionStatus").textContent = message;
  el("questionStatus").dataset.state = kind;
}
function showQuestionSuggestion(result) {
  el("suggestionLabel").textContent = result?.mode === "explore" ? "Exploration / clarification — review before asking" : "Suggested wording";
  el("suggestedQuestion").textContent = result?.question || "";
  el("questionSuggestion").hidden = !result?.question;
}
function stopQuestionWaiting() {
  if (!questionRequest) return;
  const request = questionRequest;
  questionRequest = null;
  request.controller.abort();
  clearInterval(request.ticker);
  clearTimeout(request.timeout);
  draftQuestionBtn.disabled = false;
  draftQuestionBtn.textContent = el("questionMode").value === "explore" ? "Explore question" : "Polish wording";
  draftQuestionBtn.setAttribute("aria-busy", "false");
  el("stopQuestion").hidden = true;
}
function selectedQuestionNote() {
  const selected = listenerNotes.value.slice(listenerNotes.selectionStart, listenerNotes.selectionEnd).trim();
  const cursor = listenerNotes.selectionStart;
  const start = listenerNotes.value.lastIndexOf("\n", cursor - 1) + 1;
  const end = listenerNotes.value.indexOf("\n", cursor);
  return selected || listenerNotes.value.slice(start, end < 0 ? undefined : end).trim();
}
el("useSelectedNote").onclick = () => {
  const note = selectedQuestionNote();
  if (!note) { questionStatus("Select a thought in your notes first."); return; }
  // Seeding is explicit; retain a generated candidate separately.
  questionOut.value = note;
  questionOut.dispatchEvent(new Event("input"));
  questionOut.focus();
  questionStatus("Selected note copied into your question. Edit it or press ⌘Enter.");
};
el("stopQuestion").onclick = () => {
  stopQuestionWaiting();
  questionStatus("Stopped waiting. Your question is unchanged. The server may still finish; reopen this lecture to recover its suggestion.");
};
el("useQuestion").onclick = () => {
  questionOut.value = el("suggestedQuestion").textContent;
  questionOut.dispatchEvent(new Event("input"));
  questionOut.focus();
  questionStatus("Suggestion applied. You can edit it or refine it again.");
};
el("copySuggestion").onclick = async () => {
  try {
    await navigator.clipboard.writeText(el("suggestedQuestion").textContent);
    questionStatus("Copied suggestion.");
  } catch (_) { questionStatus("Clipboard unavailable. Select the suggestion and copy it manually.", "error"); }
};
questionOut.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && !event.isComposing) {
    event.preventDefault(); draftClassQuestion();
  }
});
el("questionMode").onchange = () => {
  if (!questionRequest) draftQuestionBtn.textContent = el("questionMode").value === "explore" ? "Explore question" : "Polish wording";
};
async function draftClassQuestion(noteThought = "") {
  if (draftQuestionBtn.disabled) return;
  if (state.selectedKind !== "session" || !state.selectedId) {
    questionStatus("Start or open a lecture first.", "error");
    return;
  }
  const id = state.selectedId;
  const confusion = noteThought || questionOut.value.trim() || selectedQuestionNote();
  if (!confusion) { questionStatus("Type a question or select a thought from your notes first.", "error"); questionOut.focus(); return; }
  const lectureExcerpt = lectureDraft.value.slice(lectureDraft.selectionStart, lectureDraft.selectionEnd);
  const oldQuestion = questionOut.value;
  const refinement = questionRefine.value;
  draftQuestionBtn.disabled = true;
  draftQuestionBtn.textContent = "Drafting…";
  draftQuestionBtn.setAttribute("aria-busy", "true");
  el("stopQuestion").hidden = false;
  const request = { controller: new AbortController(), started: Date.now(), timedOut: false };
  questionRequest = request;
  const updateProgress = () => {
    if (state.selectedId !== id || state.selectedKind !== "session") { stopQuestionWaiting(); return; }
    const seconds = Math.floor((Date.now() - request.started) / 1000);
    questionStatus(`${seconds < 8 ? "Drafting from your question" : "Still waiting for AI"} · ${seconds}s. You can keep taking notes.`, "loading");
  };
  updateProgress();
  request.ticker = setInterval(updateProgress, 1000);
  request.timeout = setTimeout(() => { request.timedOut = true; request.controller.abort(); }, 30000);
  try {
    const result = await api(`/api/sessions/${id}/questions`, {
      signal: request.controller.signal,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        confusion,
        lecture_excerpt: el("questionContext").checked ? lectureExcerpt : "",
        refine: refinement,
        prior_question: noteThought ? "" : oldQuestion,
        preserve_draft: true,
        mode: el("questionMode").value,
        use_context: el("questionContext").checked,
      }),
    });
    if (questionRequest !== request || state.selectedId !== id || state.selectedKind !== "session") return;
    if (!result.question?.trim()) throw new Error("AI returned an empty suggestion. Please retry.");
    showQuestionSuggestion(result);
    const changed = questionOut.value !== oldQuestion;
    questionStatus(result.model === "passthrough" ? "Basic wording only: AI refinement is disabled." :
      changed ? "Suggestion ready for your earlier draft. Your newer wording is unchanged." :
      result.question.trim() === confusion ? "AI kept your wording unchanged. Add a specific refinement instruction to try again." :
      `Ready · ${result.context_source || "transcribed lecture context"}. Review below, then use or copy it.`);
  } catch (error) {
    if (questionRequest !== request || state.selectedId !== id) return;
    questionStatus(request.timedOut ? "No response after 30 seconds. Your question is safe. Retry when ready; the server may still finish." : `${error.message}. Your question is unchanged. Retry when ready.`, "error");
  } finally {
    if (questionRequest === request) {
      const failed = el("questionStatus").dataset.state === "error";
      stopQuestionWaiting();
      if (failed) draftQuestionBtn.textContent = "Retry question";
    }
  }
}
draftQuestionBtn.addEventListener("click", () => {
  draftClassQuestion();
});
copyQuestionBtn.addEventListener("click", async () => {
  if (!questionOut.value) return;
  await navigator.clipboard.writeText(questionOut.value);
  setStatus("Copied question");
});
questionRefine.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || event.isComposing) return;
  event.preventDefault();
  draftClassQuestion();
});
copyNoteBtn.addEventListener("click", async () => {
  if (state.mode === "note") {
    await flushFinalSave();
    if (!state.selectedId) return;
    const result = await api(`/api/notes/${state.selectedId}/copy`, { method: "POST" });
    await navigator.clipboard.writeText(result.text);
  } else {
    await flushSessionSave();
    if (!lectureDraft.value) return;
    await navigator.clipboard.writeText(lectureDraft.value);
    await api(`/api/sessions/${state.selectedId}/copy`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: lectureDraft.value }),
    });
  }
  setStatus("Copied");
});
newBtn.addEventListener("click", async () => {
  if (state.recording) return;
  if (state.mode === "note") {
    await flushFinalSave();
    await flushTurnSaves();
    await createAndSelectNote();
  } else {
    await flushSessionSave();
    state.selectedId = null;
    state.session = null;
    listenerNotes.value = "";
    lectureDraft.value = "";
    lecturePolished.value = "";
    resetQuestionFields();
    timerEl.textContent = "00:00";
    setStatus("");
    renderHistory();
  }
});
noteModeBtn.onclick = () => switchMode("note");
lectureModeBtn.onclick = () => switchMode("lecture");
recordBtn.onclick = () => state.recording ? stopRecording() : startRecording();
discardBtn.onclick = discardRecording;
document.addEventListener("keydown", (event) => {
  if (event.code !== "Space" || ["TEXTAREA", "INPUT"].includes(event.target.tagName)) return;
  event.preventDefault();
  state.recording ? stopRecording() : startRecording();
});

applyMode();
const bootParams = new URLSearchParams(location.search);
const autoRecord = bootParams.get("record") === "1";
const autoLecture = autoRecord
  || bootParams.get("mode") === "lecture"
  || bootParams.get("lecture") === "1";
const bootCourse = (bootParams.get("course") || "").trim();
if (autoLecture) {
  state.mode = "lecture";
  applyMode();
}
if (autoRecord) state.bootNewLecture = true;
if (bootCourse) courseEl.value = bootCourse;
if (autoLecture || autoRecord) {
  history.replaceState({}, "", location.pathname);
}
el('audioSource').value = localStorage.getItem('speech-audio-source') === 'meeting' ? 'meeting' : 'microphone';
function showCaptureHint() {
  const meeting = el('audioSource').value === 'meeting';
  el('captureHint').textContent = meeting
    ? 'Click Record, choose the meeting tab, and enable Share tab audio. Only audio is recorded. Watch both meters to confirm the sources.'
    : 'Records your microphone, not direct laptop audio. For online meetings select Meeting audio + microphone.';
}
el('audioSource').onchange = () => {localStorage.setItem('speech-audio-source', el('audioSource').value); showCaptureHint();};
showCaptureHint();
sync().then(async () => {
  if (autoLecture && !courseEl.value.trim()) {
    await applyCalendarSuggestion({ courseHint: bootCourse });
  }
  if (!autoRecord) return;
  if (el('audioSource').value === 'meeting') {
    setStatus('Ready for your meeting. Click Record to authorize meeting audio sharing.');
  } else startRecording({ forceLecture: true, forceNew: true, courseHint: bootCourse || courseEl.value });
});
setInterval(() => {
  if (hasPending() || state.recording) sync();
}, 500);
const channel = new BroadcastChannel("speech-tool");
const boot = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
channel.onmessage = () => {}; // Never close a tab holding recordings or edits.
channel.postMessage({ type: "takeover", boot });

function cacheLectureDraft() {
  if (!state.selectedId) return;
  try {
    localStorage.setItem(`speech-draft-${state.selectedId}`, JSON.stringify({
      text: lectureDraft.value, notes: listenerNotes.value, revision: state.sessionRevision,
    }));
    clearCaptureNotice(DRAFT_STORAGE_FULL_NOTICE);
  } catch (_) { setStatus(DRAFT_STORAGE_FULL_NOTICE, 2); }
}
function pageLeaveNeedsWarning() {
  if (state.recording || state.noteTakePending || state.sessionSavePending || state.lectureDirty || state.notesDirty) return true;
  if (state.finalDirty || state.finalPending || state.questionUncached || unjournaledCaptures.length) return true;
  for (const save of state.turnSaves.values()) {
    if (save.dirty || save.pending) return true;
  }
  return false;
}
window.addEventListener("beforeunload", (event) => {
  if (pageLeaveNeedsWarning()) {
    event.preventDefault(); event.returnValue = "";
  }
});
listenerNotes.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && !event.isComposing) {
    event.preventDefault(); draftClassQuestion(selectedQuestionNote());
  }
});
document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.shiftKey && event.key.toLowerCase() === "q" && state.mode === "lecture") {
    event.preventDefault(); stampBtn.click();
  }
});
const questionTimers = new Map();
questionOut.addEventListener("input", () => {
  copyQuestionBtn.disabled = !questionOut.value.trim();
  const id = state.selectedId, text = questionOut.value;
  if (!id || state.selectedKind !== "session") return;
  try {
    localStorage.setItem(`speech-question-${id}`, text);
    state.questionUncached = false;
    clearCaptureNotice(QUESTION_TAB_ONLY_NOTICE);
    if (!state.recording && state.lastStatus === QUESTION_TAB_ONLY_NOTICE) setStatus("");
  } catch (_) {
    state.questionUncached = true;
    if (state.recording) showCaptureNotice(QUESTION_TAB_ONLY_NOTICE, 2);
    else setStatus(QUESTION_TAB_ONLY_NOTICE, 2);
  }
  clearTimeout(questionTimers.get(id));
  questionTimers.set(id, setTimeout(async () => {
    try {
      await api(`/api/sessions/${id}/questions/edit`, {method: "POST",
        headers: {"Content-Type": "application/json"}, body: JSON.stringify({text})});
      if (questionOut.value === text) {
        state.questionUncached = false;
        clearCaptureNotice(QUESTION_TAB_ONLY_NOTICE);
        if (!state.recording && state.lastStatus === QUESTION_TAB_ONLY_NOTICE) setStatus("");
      }
      if (localStorage.getItem(`speech-question-${id}`) === text) {
        localStorage.removeItem(`speech-question-${id}`);
        clearCaptureNotice(QUESTION_UNSAVED_NOTICE);
      }
    } catch (_) {
      if (state.questionUncached) {
        if (state.recording) showCaptureNotice(QUESTION_TAB_ONLY_NOTICE, 2);
        else setStatus(QUESTION_TAB_ONLY_NOTICE, 2);
      } else if (state.recording) showCaptureNotice(QUESTION_UNSAVED_NOTICE, 1);
      else setStatus(QUESTION_UNSAVED_NOTICE);
    }
  }, 400));
});

async function claimCapture() {
  state.captureLockReason = "";
  if (!navigator.locks) {
    state.captureLockReason = "unsupported";
    return false;
  }
  return new Promise((resolve) => navigator.locks.request("speech-microphone", { ifAvailable: true }, async (lock) => {
    if (!lock) {
      state.captureLockReason = "busy";
      resolve(false);
      return;
    }
    await new Promise((release) => { state.releaseCaptureLock = release; resolve(true); });
    state.releaseCaptureLock = null;
  }));
}
function captureBlockedMessage(forRecovery) {
  if (state.captureLockReason === "unsupported") {
    return "This browser cannot coordinate the microphone across tabs. Use Chrome, then try again.";
  }
  return forRecovery
    ? "Stop the recording in the other tab first."
    : "Recording is already active in another Speech Tool tab. Return to that tab.";
}
function downloadedStaySentence(downloaded, downloadedMemory) {
  const durable = downloaded - downloadedMemory;
  if (downloadedMemory && !durable) {
    const be = downloaded === 1 ? "It is" : "They are";
    const again = downloaded === 1 ? "it" : "them";
    const kept = downloaded === 1 ? "the download is the copy to keep" : "the downloads are the copies to keep";
    return `${be} only in this tab until this tab closes; ${kept}, and this tab can download ${again} again.`;
  }
  if (!downloadedMemory) {
    return downloaded === 1
      ? "It stays in this browser; Recover audio can download it again."
      : "They stay in this browser; Recover audio can download them again.";
  }
  const durableBit = durable === 1 ? "1 stays in this browser" : `${durable} stay in this browser`;
  const memoryBit = downloadedMemory === 1
    ? "1 is only in this tab until this tab closes; the download is the copy to keep"
    : `${downloadedMemory} are only in this tab until this tab closes; the downloads are the copies to keep`;
  return `${durableBit}. ${memoryBit}.`;
}
function downloadedRecoverySuffix(downloaded, downloadedMemory) {
  if (!downloaded) return "";
  const noun = `recording part${downloaded === 1 ? "" : "s"}`;
  return ` Downloaded ${downloaded} ${noun} that never joined a lecture. ${downloadedStaySentence(downloaded, downloadedMemory)}`;
}
async function recoverSavedAudio(manual = false) {
  if (recoveryBusy) return;
  if (state.recording) { setStatus("Stop recording before recovering audio."); return; }
  if (manual && !await claimCapture()) { setStatus(captureBlockedMessage(true)); return; }
  recoveryBusy = true;
  let recovered = 0, failed = 0, downloaded = 0, downloadedMemory = 0;
  try {
    await refreshRecoveryStatus();
    const rows = await listRecoverableCaptures();
    for (const row of rows) {
      if (!manual && (!row.complete || blockedCaptures.has(row.id))) continue;
      if (!row.sessionId) {
        if (!manual) continue;
        const link = document.createElement("a");
        link.href = URL.createObjectURL(row.blob); link.download = `recovered-${row.id}.webm`; link.click();
        setTimeout(() => URL.revokeObjectURL(link.href), 1000);
        downloaded += 1;
        if (row.memoryOnly) downloadedMemory += 1;
        continue;
      }
      try {
        await sendCapture(row);
        recovered++;
      } catch (error) {
        failed++;
        const retained = row.memoryOnly
          ? "This part is only in this tab."
          : "Local audio retained.";
        if (manual) setStatus(`Recovery needs attention: ${safeClientDetail(error)}. ${retained}`);
      }
    }
    let endPending = 0;
    if (manual) endPending = await finishStoppedLectures();
    else if (!state.recording && navigator.locks) {
      endPending = await navigator.locks.request('speech-microphone', {ifAvailable:true}, async lock => (
        lock ? finishStoppedLectures() : 0
      )) || 0;
    }
    const downloadedClause = downloadedRecoverySuffix(downloaded, downloadedMemory);
    if (recovered) {
      setStatus(lectureEndPendingStatus(
        `${recovered} recording part${recovered === 1 ? '' : 's'} recovered to the original lecture${failed ? ` · ${failed} still need attention` : ''}.${downloadedClause}`,
        endPending,
      ));
    } else if (downloaded) {
      setStatus(lectureEndPendingStatus(
        `${downloadedRecoverySuffix(downloaded, downloadedMemory).trim()}${failed ? ` ${failed} still need attention.` : ""}`,
        endPending,
      ));
    } else if (manual && endPending && !failed) {
      setStatus(lectureEndPendingStatus("Saved audio stays on the server.", endPending));
    }
    await sync();
  } catch (error) { setStatus(`Recovery pending: ${error.message}. Local audio retained.`); }
  finally { recoveryBusy = false; if (manual) state.releaseCaptureLock?.(); await refreshRecoveryStatus(); }
}
el('recoverAudio').onclick = () => recoverSavedAudio(true);
el('retryCleanup').onclick = () => retryLecturePolish.click();
el('retryTranscription').onclick = async () => {
  if (state.selectedKind !== 'session' || !state.selectedId) return;
  el('retryTranscription').disabled = true;
  try {
    await api(`/api/sessions/${state.selectedId}/retry-transcription`, {method:'POST'});
    await sync();
  } catch (error) { setStatus(error.message); }
  finally { el('retryTranscription').disabled = false; }
};
el('copyTranscriptPath').onclick = async () => {
  if (state.selectedKind !== 'session' || !state.selectedId) return;
  const btn = el('copyTranscriptPath');
  btn.disabled = true;
  try {
    const result = await api(`/api/sessions/${state.selectedId}/transcript-path`, { method: 'POST' });
    await navigator.clipboard.writeText(result.path);
    setStatus(result.ready
      ? `Transcript path copied · ${result.path}`
      : `Path copied · file is empty until ASR finishes · ${result.path}`);
  } catch (error) { setStatus(error.message); }
  finally { btn.disabled = false; }
};
async function automaticRecovery() {
  await refreshRecoveryStatus();
  if (!state.recording && !recoveryBusy && navigator.onLine) {
    const rows = await listRecoverableCaptures();
    if (rows.some(row => row.complete && row.sessionId && !blockedCaptures.has(row.id)) || Object.keys(localStorage).some(k => k.startsWith('speech-stop-'))) {
      if (navigator.locks) await navigator.locks.request('speech-upload-recovery', {ifAvailable:true}, async lock => {
        if (lock) await recoverSavedAudio(false);
      });
    }
  }
}
window.addEventListener('online', () => automaticRecovery().catch(() => {}));
setTimeout(() => automaticRecovery().catch(() => {}), 1500);
setInterval(() => automaticRecovery().catch(() => {}), 15000);
