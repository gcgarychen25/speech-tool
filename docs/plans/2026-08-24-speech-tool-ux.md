# Speech Tool UX iteration — 24 Aug 2026

Ingestion layer: capture feels instant, state is honest, artifacts stay split so later agents can iterate without a UI rewrite.

## Product rules that were leaking into the UI

- ASR is the source of truth. Polish is optional and async. Timeout must not look like a hang or a success.
- Note Record appends; `+ New` starts another note. Lecture Record was always creating a new session. It now appends to the selected session (`+ New` is the boundary).
- Perception vs rules: Whisper + Mimo stay replaceable. Course jargon lives in `docs/asr_lexicon.json` and is injected into ASR `initial_prompt` and the polish prompt. Copy from the inspector writes `corrections.jsonl`.

## What this pass changes

1. Lecture polish 120s + one retry; notes 20s; notes jump the polish queue.
2. Continue a selected lecture; retry skipped polish from the inspector or lecture pane.
3. History delete; skip mic-left-on / repetition-loop chunks from the lecture draft (raw files stay).
4. Keep ASR on whisper-small; keep polish on mimo-v2.5-free.

## Later, not now

- Native menu-bar extra. Until then, `scripts/start-lecture.sh` / `?mode=lecture&record=1` is the late-to-hall path.
- Switching default ASR to large-v3-turbo. Bake-off 2026-08-24: turbo was slower on short notes (~3x) and worse on jargon. Keep whisper-small.
