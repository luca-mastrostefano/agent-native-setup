# Docs

- `architecture/` — how the system is built and why.
- `rfc/` — proposals and decisions, by lifecycle stage:
  - `current/` — under discussion or in progress
  - `done/` — accepted and shipped
  - `superseded/` — replaced by a later RFC
- `improvements.md` — backlog of deferred ideas and known gaps.
- `contributing.md` — the dev loop.

RFCs are named `YYYY-MM-DD-short-slug.md`. You don't move them by hand: edit the
`Status:` line and run `task rfc-sync` (also wired as a pre-commit hook) to
relocate the file to the matching folder via `git mv`, preserving history.
