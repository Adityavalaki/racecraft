# ROLLBACK
Last known good commit: fd0513a (GitHub `main` before 2026-10-27's merge; PR #4). Its web
app did not build (`App.tsx`, see the merge commit), so for a working app go back to
177e8e5 (2026-10-20). The 2026-10-27 merge brings in `audit-fixes` and `free-plan`.
To undo it: `git revert -m 1 <merge sha>` (keeps history; never force-push `main`).

## Undoing a change
- Code: the audit fixes are on branch `audit-fixes`, one commit per finding. `git revert <sha>`
  undoes one; `git checkout main` drops them all.
- Data changes: none. No fix rewrites the lake, the predictions or the WebView profile.
  The deleted `legacy/` code is in git history: `git checkout 177e8e5 -- legacy`.
- Feature flag to switch off without a deploy: none.
- Re-check afterwards: `.venv\Scripts\python -m pytest -m "not network"` and `cd web; npx vitest run`.
