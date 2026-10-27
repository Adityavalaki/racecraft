# ROLLBACK
Last known good commit: 177e8e5 (2026-10-20), on `main`, before the audit fixes.

## Undoing a change
- Code: the audit fixes are on branch `audit-fixes`, one commit per finding. `git revert <sha>`
  undoes one; `git checkout main` drops them all.
- Data changes: none. No fix rewrites the lake, the predictions or the WebView profile.
  The deleted `legacy/` code is in git history: `git checkout 177e8e5 -- legacy`.
- Feature flag to switch off without a deploy: none.
- Re-check afterwards: `.venv\Scripts\python -m pytest -m "not network"` and `cd web; npx vitest run`.
