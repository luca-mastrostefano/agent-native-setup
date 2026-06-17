# Docs

- `architecture/` — how the system is built and why (reflects the active RFCs).
- `rfc/` — proposals and decisions, by lifecycle state:
  - `proposed/` — drafted, under discussion
  - `active/` — accepted and in effect
  - `superseded/` — replaced by a later RFC
  - `retired/` — withdrawn, no replacement
- `improvements.md` — backlog of deferred ideas and known gaps.

The dev loop lives in [`CONTRIBUTING.md`](../CONTRIBUTING.md) at the repo root.

RFCs are named `YYYY-MM-DD-short-slug.md`. You don't move them by hand: edit the
`Status:` line and run `task rfc-sync` (also wired as a pre-commit hook) to
relocate the file to the matching folder via `git mv`, preserving history.
