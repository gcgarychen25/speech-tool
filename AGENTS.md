# Speech Tool contributor rules

- Preserve raw audio and transcripts. Use synthetic data in tests and examples.
- Keep personal instructions, transcripts, logs, credentials, backups, and local
  glossary overrides out of Git. See PRIVACY.md before staging files.
- After meaningful requested changes, run relevant tests, inspect the staged diff,
  run `python3 scripts/privacy-check.py --index`, and make a focused commit.
- Push verified commits to the explicitly configured owner-approved GitHub
  remote. If no remote is configured or checks fail, report the blocker; do not
  guess a destination, bypass hooks, or force-push.
- Commit and push real work, not empty/backdated commits for contribution counts.
- Do not stage unrelated work. Never use `git add .` or `git add -A`.
- Local deployment is separate from a commit or push. Never restart during a
  recording. Do not claim tested source is deployed until runtime verification.
- Install repository hooks with `git config core.hooksPath .githooks`.
- Use a GitHub noreply commit email; do not commit personal email addresses.
