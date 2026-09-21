# Speech Tool V1 — Success Criteria

## Objective

Build a **macOS-first, local-first personal speech ingestion tool**.

The system should let the user quickly capture speech on a Mac, convert it to text with **local ASR**, optionally clean the transcript with an **LM polishing step**, and persist the complete history reliably for later access and reprocessing.

The implementation approach is intentionally unspecified. Optimize for the success criteria below rather than for any particular architecture or technology.

---

## Core User Experience

The intended flow is:

**Capture speech → persist raw audio → local ASR → persist raw transcript → LM polish → persist polished transcript → access persistent history**

The tool should feel fast and reliable enough to become a default speech-input utility in daily use on macOS.

---

## V1 Scope

V1 is intentionally **Mac-only**.

The goal is to first prove that the core speech ingestion pipeline is useful, reliable, and fast enough for daily use before adding cross-device or iOS support.

V1 should not spend engineering effort on:

- iPhone / iOS capture
- cross-device synchronization
- iOS local ASR
- mobile-specific UI
- cloud ASR
- device-to-device coordination

However, the persisted data model should avoid unnecessary assumptions that would make future multi-device support difficult.

---

## V1 Success Criteria

### 1. Low-friction speech capture on macOS

The user must be able to start and stop a recording quickly from a Mac.

Requirements:

- Starting a recording should take only a few seconds.
- The interaction should require minimal friction.
- Recordings from a few seconds up to **10 minutes** must be supported.
- The recording must be safely persisted before downstream processing begins.
- If ASR or LM processing later fails, the original recording must remain available.
- Application restart or processing failure must not silently destroy a completed recording.

The exact interaction model is not prescribed. A global shortcut, menu-bar interaction, small native window, localhost web UI, or another low-friction interface is acceptable.

The success criterion is the user experience, not a particular UI technology.

---

### 2. Local ASR

Speech-to-text inference must run locally on the Mac rather than requiring a cloud ASR service.

Requirements:

- Successfully transcribe recordings up to **10 minutes**.
- Support:
  - Chinese
  - English
  - Chinese-English code switching
- Preserve technical terminology reasonably well.
- A failed transcription must be retryable.
- Previously recorded audio must be re-transcribable later.
- The ASR model or implementation must be replaceable without invalidating historical recordings.

Accuracy does not need to be perfect, but the output should be good enough that an LM cleanup step can reliably produce usable text.

---

### 3. Reasonable transcription latency

The system should feel responsive enough for normal daily use on the target Mac.

Target maximum post-recording ASR latency:

| Audio length | Target |
|---|---:|
| < 30 seconds | < 3 seconds |
| 30 sec – 2 min | < 10 seconds |
| 2 – 5 min | < 30 seconds |
| 5 – 10 min | < 60 seconds |

A useful aggregate target is:

**Real-Time Factor (RTF) ≤ 0.2**

Faster performance is welcome but is not required for V1.

The latency target should be evaluated on the actual target machine.

---

### 4. Durable persistence

Every recording must become a persistent speech event.

At minimum, each event must preserve:

- stable event ID
- creation timestamp
- recording duration
- raw audio
- raw ASR transcript
- polished transcript
- ASR status
- polishing status
- ASR model/version metadata
- LM/model metadata when available

The following must remain distinct:

1. raw audio
2. raw ASR transcript
3. polished transcript

A derived artifact must never overwrite its source.

The key invariant is:

> **Derived data may be regenerated. Source data must never be silently destroyed.**

The storage design should make it possible to re-run ASR or LM polishing later without losing previous source material.

---

### 5. LM polishing

After ASR completes, the transcript should optionally pass through an LM-based cleanup step.

For V1, this step only needs to:

- fix obvious ASR mistakes
- restore punctuation
- add reasonable paragraph breaks
- preserve the speaker's original meaning
- preserve Chinese-English code switching where appropriate
- preserve technical terminology
- avoid summarization
- avoid adding information that was not spoken

The V1 implementation may use a non-interactive coding/LM CLI such as OpenCode rather than a dedicated model-provider API.

The polishing component should remain replaceable so that a future implementation can use another CLI, model provider, or local model.

A polishing failure must not affect the saved audio or raw transcript.

---

### 6. Persistent history

The user must be able to access previously captured speech events on the Mac.

The history must allow the user to:

- view events in reverse chronological order
- see when each event was created
- see recording duration
- replay raw audio
- view raw transcript
- view polished transcript
- copy transcript text
- delete an event
- see failed or pending ASR states
- see failed or pending polishing states
- retry failed ASR
- retry failed polishing
- re-transcribe historical audio

V1 does **not** need advanced organization, search, or categorization.

---

### 7. Reliability and failure recovery

The system must be designed so that failures after recording do not cause data loss.

The following cases must be recoverable:

- ASR process failure
- LM polishing failure
- application restart
- device restart
- interruption after audio capture but before processing completes
- temporary loss of network connectivity during an LM polishing step

Once a recording has been completed, the raw audio should be safely persisted before downstream processing begins.

The system should expose enough state to distinguish between:

- captured
- pending transcription
- transcription failed
- transcribed
- polishing pending
- polishing failed
- completed

Equivalent state modeling is acceptable.

---

## Explicit Non-Goals for V1

Do **not** expand V1 into a cross-device product or personal memory system.

The following are outside scope:

- iPhone / iOS support
- cross-device synchronization
- iOS local ASR
- cloud ASR
- memory extraction
- long-term memory consolidation
- semantic search
- embeddings
- vector databases
- knowledge graphs
- topic clustering
- automatic project classification
- automatic tagging
- summaries
- personalized reasoning
- user modeling
- context retrieval for agents
- automatic injection into ChatGPT, Codex, Cursor, or other tools
- complex model routing
- advanced prompt orchestration

These may be added only after the Mac workflow is proven reliable and useful in daily use.

---

## Definition of Done

V1 is complete when all of the following are true.

### Functional

- Recording works reliably on macOS.
- Starting and stopping a recording is low-friction.
- Recordings up to 10 minutes are supported.
- Local ASR works for Chinese, English, and mixed Chinese-English speech.
- LM polishing works.
- Raw audio, raw transcript, and polished transcript are stored separately.
- History persists across application restarts.
- Failed ASR can be retried.
- Failed polishing can be retried.
- Historical audio can be re-transcribed.

### Reliability

During testing:

- no completed raw recording is lost
- ASR failure does not lose the recording
- LM failure does not lose the raw transcript
- application restart does not lose persisted events
- interrupted processing can resume or be retried

### Real-world validation

Use the tool for at least **7 consecutive days**.

During that period, create at least:

- 40 total recordings
- 3 recordings longer than 5 minutes
- 1 recording close to 10 minutes
- Chinese-only recordings
- English-only recordings
- Chinese-English mixed recordings

Also deliberately test:

- one ASR failure
- one LM polishing failure
- one processing interruption
- one application restart during or after processing

At the end of the test:

- every completed raw recording still exists
- every recording can eventually obtain a transcript
- failed processing can be retried successfully
- the tool is convenient enough to be used voluntarily as a normal Mac speech-input workflow

---

## Product Principle

V1 is successful if it becomes a reliable personal **speech ingestion layer for macOS**.

It does not need to understand, organize, summarize, synchronize, or remember the user's life yet.

For V1, the priority order is:

**Capture → Persist → Transcribe → Polish → History**

Everything else comes later.

---

## Deferred Direction

Future versions may extend the system in this order:

### V1.5 — Device-independent context store

Keep the speech-event schema and storage boundaries clean enough that another capture device can be added without redesigning the entire data model.

### V2 — iPhone capture and cross-device access

Add iPhone as another capture interface.

iPhone local ASR is **not** required by default. A future mobile client may capture and upload audio while transcription happens elsewhere under the user's control.

### V3 — Context retrieval and memory

Only after the ingestion layer is proven useful should the system consider:

- search
- context selection
- export / injection into other tools
- memory extraction
- consolidation
- long-term personalized context
