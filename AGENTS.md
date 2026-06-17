# agent-native-setup — Agent Contract

A wizard that scaffolds an agent-native project setup into a new repo.

This file is the **single source of truth** for both coding agents and humans.
`CLAUDE.md`, `GEMINI.md`, `.cursor/rules/`, and `.github/copilot-instructions.md` all point here.

## Navigation

| Topic | Where |
| --- | --- |
| Project entry point | [`README.md`](./README.md) |
| Architecture & decisions | `docs/architecture/` |
| Proposals & decisions | `docs/rfc/` (`proposed/` → `active/`) |
| How to contribute | `docs/contributing.md` |
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

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

**Every change ships with the test that proves it** — pick the right level, don't
mechanically add all three:
- **Unit** — logic and edge cases (the default).
- **Integration** — when the change crosses a module, a public contract, or an external boundary.
- **Regression** — for every bug, write the failing test that reproduces it *first*, then fix.

Tests should *prove behavior*, not restate the implementation — cover the boundaries
(empty/zero/one/max), bad input, and error paths, not just the happy path. A test that
can't fail isn't worth writing.

If something genuinely can't be tested, say why rather than skipping silently.

## When to write an RFC

Write an RFC in `docs/rfc/proposed/` before: changing architecture or a public
contract, adding a dependency or service, or anything hard to reverse. Use the
template in `docs/rfc/TEMPLATE.md`. Lifecycle: `proposed/ → active/ → (superseded/ |
retired/)`; `docs/architecture/` reflects the active RFCs.
Before flipping one to Active, run the `rfc-reviewer` on the draft and resolve
its findings — it checks the *decision* (simplest option, honest consequences,
alternatives weighed), the way `code-reviewer` checks the diff.

## How this project stays agent-native

- **Context** — this contract, `docs/`, and RFCs keep intent discoverable. Keep it that
  way as the repo grows by scoping context down instead of letting one file sprawl: a
  directory with rules of its own can carry a local `AGENTS.md` (with a `CLAUDE.md`/`GEMINI.md`
  symlink beside it, like the root — those tools load their own file, not `AGENTS.md`) that
  agents follow as the nearest contract. Likewise, give a subsystem its own `docs/architecture/<name>.md`
  and keep `overview.md` the index, so no one file becomes a monolith.
- **Mechanical enforcement** — linters, hooks, and CI catch
  violations automatically. Error messages should tell you how to fix them. If a
  language in the repo isn't yet wired up for linting, formatting, and tests, add it the
  way the existing ones are (a pre-commit hook, a CI step, and a command-surface entry)
  rather than leaving it unguarded.
- **Feedback loops** — agents in `.claude/agents/`, tests,
  and reviews close the loop so quality compounds. Before calling a non-trivial change
  done, run the `code-reviewer` (`/review`) on your diff and resolve its findings. When a
  change touches a security-sensitive surface — auth, untrusted input, secrets or crypto,
  or file/network I/O — also run `/security-review` before merging; the mechanical scans
  catch known-bad dependencies and committed secrets, not logic flaws. After
  changing a workflow in
  `.github/workflows/`, confirm it passed on GitHub (`gh run watch`; if `gh` isn't set
  up, ask the maintainer to check the repo's Actions tab) — local checks can't tell an
  action is missing or out of date. Remember that `git commit` records the staged index,
  not your working tree: re-stage any fix made after `git add` — including ones prompted
  by review — then sanity-check `git show --stat` before pushing. And make any
  long-running or backgrounded command followable — run it unbuffered (`python -u` /
  `PYTHONUNBUFFERED=1` / `stdbuf -oL`) and `tee` it to a logfile — so its progress streams
  instead of buffering silently.
