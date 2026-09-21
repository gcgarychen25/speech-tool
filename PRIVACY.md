# Publication boundary

This repository contains application source, synthetic tests, and generic docs.
Recordings, lecture notes, exported transcripts, personal instructions, logs,
credentials, backups, and recording-derived glossaries stay local.

The application data directory is outside the repository under the user's
Application Support directory. `docs/asr_lexicon.local.json` is an ignored local
override; the committed `docs/asr_lexicon.json` is a small generic default.
The installer carries the local override into a local runtime release when it
exists. Do not upload runtime snapshots or source backups as release assets.

## Before committing or pushing

1. Install hooks: `git config core.hooksPath .githooks` (required for every clone).
2. Configure a verified GitHub noreply author email for contribution attribution.
3. Stage exact code paths, review `git diff --cached`, and run tests.
4. Run `python3 scripts/privacy-check.py --index`, then commit meaningful work.
5. Push only to the approved remote. The pre-push hook checks every outgoing
   branch/tag's reachable commits, including file paths, text, commit messages,
   and author/committer emails. Legacy private history must never be merged in.

Ignore rules do not remove existing Git history. A sanitized root is required
when the old history contains personal content. Keep legacy history local only.
Hooks are local safeguards, not a security boundary: they can be bypassed and
are not automatically installed by cloning. The checker is heuristic and cannot
recognize every personal story or disguised secret. Human diff review remains
required; never claim zero disclosure from a passing scan.

GitHub activity reflects real commits under the account's associated identity;
there is no daily timer or manufactured contribution schedule.

Publishing source does not publish local application data. Separately, optional
AI polishing may send selected text to the configured model provider. Review
that provider's privacy policy before processing confidential material.
