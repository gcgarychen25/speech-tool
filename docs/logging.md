# Logging

Speech Tool writes application logs under the data directory:

```
~/Library/Application Support/SpeechTool/runtime/logs/
```

| File | What it contains | Rotation |
| --- | --- | --- |
| `speech_tool.log` | Server, ASR, polish, and question events at INFO and above | 5 MiB, 10 backups (`speech_tool.log.1`, …) |
| `speech_tool.errors.log` | ERROR and above only, including tracebacks | 2 MiB, 10 backups |
| `audio-retention.log` | Hourly retention job: one summary per run, plus removals and failures | 5 MiB, 10 backups |
| `audio-retention.errors.log` | Retention errors with tracebacks | 2 MiB, 10 backups |

launchd still captures process stdout/stderr in the unrotated backstop files `runtime/server.log` and `runtime/audio-retention.log`. Those should stay small: the app sends only WARNING+ to stderr, and retention no longer prints a line per already-archived event. Prefer the rotating files in `runtime/logs/` for daily review.

## Line format

One record per line, local time with offset, then level, logger, key=value fields, and `msg=`:

```
2026-11-22T12:00:00.123-0500 INFO speech_tool.pipeline stage=polish event_id=… session_id=… model=… elapsed_s=6.210 result=ok msg="polish completed"
```

Useful keys: `stage` (`server`, `asr`, `polish`, `retention`, `question`), `event_id`, `session_id`, `model`, `elapsed_s`, `rtf`, `result`, `error`, `release`, `git_commit`. Exceptions add a redacted traceback on the following lines. Token-like values (Bearer tokens, `api_key=` / `token=` assignments, `sk-…`, GitHub PATs) are masked as `[redacted]`.

On startup the server (and the retention job) emit a `service starting` line with the release hash, git commit when known, Python version, and model settings. It does not record credentials.

A `RELEASE.json` file in a published snapshot (written by `scripts/install-desktop.py`) supplies the release hash and git commit for that line.

## Grep examples

```bash
LOG=~/Library/Application\ Support/SpeechTool/runtime/logs

# Everything from today
rg '2026-11-22' "$LOG/speech_tool.log"

# Failed or rejected polish attempts
rg 'stage=polish' "$LOG/speech_tool.log" | rg 'result=(error|timeout|provider_unavailable|model_unavailable|empty|quality_rejected)'

# ASR failures
rg 'stage=asr' "$LOG/speech_tool.errors.log"

# Startup / which release and model are running
rg 'msg="service starting"' "$LOG/speech_tool.log"

# Retention summaries and deletions
rg 'stage=retention' "$LOG/audio-retention.log"
```

After a logging or other approved code change, publish a new local snapshot with `scripts/install-desktop.py --install --replace-service` only when nothing is recording. The installer keeps existing `SPEECH_TOOL_*` environment variables on the service and points `PYTHONPATH` at the new snapshot.
