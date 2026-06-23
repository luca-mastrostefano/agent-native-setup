# agent-native-setup — Agent Contract

A wizard that scaffolds an agent-native project setup into a new repo.

**Read [`INSTRUCTION.md`](./INSTRUCTION.md) first** — the standard engineering contract (the
four execution principles, when to write an RFC, how this repo stays agent-native). This file
is the project-specific map; `CLAUDE.md` and `GEMINI.md` (symlinks) point here.

@INSTRUCTION.md

## Navigation

| Topic | Where |
| --- | --- |
| Project entry point | [`README.md`](./README.md) |
| Architecture & decisions | `docs/architecture/` |
| Proposals & decisions | `docs/rfc/` (`proposed/` → `active/`) |
| How to contribute | [`CONTRIBUTING.md`](./CONTRIBUTING.md) |
| Security policy | [`SECURITY.md`](./SECURITY.md) |

## Command surface

```bash
task install  # set up git hooks (once)
task lint  # run linters
task format  # auto-format
task typecheck  # type-check
task test  # run tests
task quality  # full local gate
task rfc-sync  # sync RFCs to their Status folder
task improvement -- "<idea>"  # log an idea in docs/improvements.md
```

Run `task --list` for the full, current set (also injected at session start via the
`.claude/settings.json` `SessionStart` hook).

**When you work out a repeatable process — a build, check, migration, or fix sequence
you'd otherwise rediscover — capture it as a `task` with a one-line `desc:`, so the next
contributor runs it deterministically instead of leaving the knowledge in a chat or a
throwaway script.**
