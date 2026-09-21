# Lecture reliability and consistent controls

Approved implementation direction: the user requested best judgment, a smoother
recording experience, and a slight consistency update, not a redesign.

Alternatives considered: status-only fixes leave upload gaps unaddressed; a full
capture rewrite adds unnecessary risk. Use a bounded repair of the existing
durable journal, server acknowledgements and session health view.

1. Separate upload completeness, ASR progress and optional cleanup. Detect holes,
   duplicate indices and trailing missing chunks using a stop-time expected count.
2. Retry completed journal entries with stable capture IDs and bounded requests.
   Keep local audio until a matching server acknowledgement. Never automatically
   upload an unfinished recording or touch another tab's active capture.
3. Resume after the highest server/local index, not the number of uploaded chunks.
   Stop bookkeeping is separate from failed uploads and survives reload.
4. Reject obvious language changes and severe truncation in cleanup; use raw
   fallback and retain historical output. No promise of perfect semantic checking.
5. Preserve the current restrained layout and typography. Shared secondary-button
   treatment, accessible focus, compact health/recovery panels and clear copy.
6. Test dropped acknowledgements, persistent failures, reload/auto-retry, partial
   recordings, duplicate tabs, note editing, gaps and cleanup failures. Inspect
   desktop and narrow screenshots before publishing a content-addressed release.

No raw audio deletion, no archive-policy change, no automatic closure of old
sessions, and no fabricated replacement for missing audio. Back up the current
source and verify hashes before applying the staged patch.
