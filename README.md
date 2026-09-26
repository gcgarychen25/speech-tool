# Speech Tool

## Contributing and privacy

Read [PRIVACY.md](PRIVACY.md) before publishing changes. Install the commit/push
guards with `git config core.hooksPath .githooks`. Use synthetic test data and a
GitHub noreply commit email. Commit verified meaningful changes and push only to
the approved remote; personal data and local runtime snapshots stay off GitHub.
Personal glossary corrections belong in ignored `docs/asr_lexicon.local.json`.

macOS-first local speech ingestion: capture, persist raw audio, local ASR, LM polish, durable history.

Open **Speech Tool** from Spotlight, or press **Control-Option-L** to open a new lecture and start recording. Cursor and a terminal are not required. Chrome must have microphone permission once.

## Daily use

### September 10: notes-first and meaning-preserving questions

Lecture notes have a larger, resizable editor; the raw and AI-cleaned transcript
panes are collapsed until needed. Command-Enter in the notes asks about the
selected thought/current line without replacing your notes or existing question.
Command-Enter in the question composer uses that question instead.

**Polish wording only** is the default: preserve subject, scope and uncertainty.
**Explore my question** is explicit and may return a clarification if intent is
unclear. **Use lecture context** is opt-in and defaults off. Context must not
redirect a question to another topic; previous-course memory is not included.
Suggestions still require explicit application. AI adherence is not guaranteed;
compare the original with the suggestion before using it.

### Audio reference copies (non-destructive, opt-in)

`python -m speech_tool.archive --root STORE --destination ARCHIVE` is a dry run.
Add `--apply` for verified lossless FLAC copies of WAV files, or `--apply --watch` to process
future transcribed files automatically. It skips failed/untranscribed files,
checks full decoding and duration, writes source/archive hashes and retains every
original. Already-compressed WebM is retained unchanged. Native decoded PCM must
match exactly for lossless copies. `--lossy` explicitly enables experimental
Opus32 copies; a real sample showed substantial ASR differences, so these must
not replace originals. `--event-id ID` and `--limit N` bound a test batch. Interrupted lock or
uncommitted output is left for inspection, never overwritten automatically.

This is **not enabled as a background service**: lossy copies need quality review
and add disk usage while originals remain. There is no delete/replace switch.
Actual space reclamation requires an approved retention policy. Do not treat
decoded-duration agreement as proof of speech clarity or transcription accuracy.

The installed app lives in `~/Applications/Speech Tool.app`. It starts the user-scoped background service when needed:

```bash
open -a "Speech Tool"
```

`com.speechtool.server` starts at login and restarts after exit. Runtime dependencies and a versioned application snapshot live under `~/Library/Application Support/SpeechTool/runtime/`, not the cloud-evictable Desktop virtual environment. HTTP starts before Whisper warmup; recording does not wait for polishing. The service uses `--no-replace` and never kills another listener on port 8787.

```bash
curl -sf http://127.0.0.1:8787/api/health
```

Default ASR is `mlx-community/whisper-small-mlx`. Optional:

```bash
export SPEECH_TOOL_ASR_MODEL=mlx-community/whisper-tiny-mlx   # faster, worse quality
export SPEECH_TOOL_OPENCODE_MODEL=opencode/mimo-v2.6-flash-free
```

Default cleanup uses OpenCode. Free-tier models may refuse non-interactive CLI
calls; when that happens the UI keeps the raw transcript and reports cleanup as
paused, including about how long automatic retries wait. **Retry cleanup** tries
again immediately. A question-helper outage is reported separately and leaves
the question box unchanged. Override the model or provider credentials locally
if cleanup must stay enabled.

## Late-to-lecture

Global hotkey: **Control-Option-L**. The server is started automatically when necessary. Chrome should already have microphone permission for `127.0.0.1`. An existing recording in another tab is protected, not closed.

Equivalent commands:

```bash
./scripts/start-lecture.sh
# or
open "http://127.0.0.1:8787/?mode=lecture&record=1"
```

That opens a new Chrome tab in Lecture mode and starts a new session immediately. Recording is on when Lecture is selected, the button is a red rounded square, and the timer is ticking. Discard a test take. A lecture left running auto-stops after **2 hours**. Saved audio keeps uploading and transcribing in the background. Record/Stop stay visible at the bottom; scroll the lecture pane, not the whole page.

In Lecture, type directly into **Your question · ask in class** and press **Command-Enter** or **Draft question**. This text is always the primary input. If it is empty, the selected note or cursor line supplies the thought. **Use selected note** explicitly copies a different note into the question box. **Command-Shift-Q** adds a note timestamp.

Progress and elapsed waiting time appear beside the question, independently of recording status. The server allows 20 seconds for AI; the browser stops waiting after 30 seconds and offers retry. **Stop waiting** stops the browser request, not an already-running server computation. A completed suggestion remains in the lecture's question history and can be recovered by reopening the lecture.

Suggestions appear separately; **Use this wording** applies one to your editable, saved question, and **Copy suggestion** copies it directly. Newer edits are never overwritten by an arriving suggestion. Add an optional refinement instruction to iterate. Selected lecture text takes precedence; otherwise keyword-matched excerpts from this lecture are used, falling back to its latest two transcribed chunks. Untranscribed speech is unavailable. Question generation uses its own text-only OpenCode prompt, not the transcript-polish queue. It targets the missing relationship or mechanism without inventing a more sophisticated concern. AI quality still needs classroom feedback.

Question start/completion/failure, request reference, model and elapsed time are written to `runtime/server.log`; raw question text is not added to those diagnostic lines. The original thought, generated suggestion and source IDs remain in `questions.jsonl`.

New lecture audio is submitted every minute, with best-effort browser backups every five seconds. If an upload fails or the tab is interrupted, reopen the tool and use **Recover audio**. Completed parts retry on their own after recording stops. A part the server rejected stays in this browser until you use **Recover audio**. Do not clear site data before recovering. The most recent unflushed audio can still be lost during an OS/browser crash; note-mode audio does not yet use this journal.

After approved code changes, publish a new local snapshot with `scripts/install-desktop.py --install --replace-service` using the dedicated runtime Python. This restarts only this tool's service and backs up its previous service configuration. Do not update during a recording.

Legacy hotkey setup (the desktop installer relocates an existing helper into the local runtime):

```bash
./scripts/install-lecture-hotkey.sh
```

Unload it:

```bash
launchctl bootout "gui/$(id -u)/com.speechtool.lecture-hotkey"
```

## Tests

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 "$HOME/Library/Application Support/SpeechTool/runtime/venv/bin/python" -m pytest -q -p no:capture -p no:cacheprovider
SPEECH_TOOL_VERIFY_POLISHER=passthrough python tests/verify_success_criteria.py
```

The 7-day / 40-recording field test in the success criteria is manual.

## Data

Under `~/Library/Application Support/SpeechTool/`:

- `events/<id>/` — `audio.*` (never overwritten), `transcript.raw.txt`, `transcript.polished.txt`, `event.json`
- `notes/<id>/` — `note.json`, `note.final.edited.txt` (canonical draft; Clear empties this only)
- `sessions/<id>/` — lecture chunks, `listener_notes.txt`, `questions.jsonl`
