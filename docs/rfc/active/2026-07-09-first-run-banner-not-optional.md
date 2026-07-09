# The first-run banner is not a question

- **Status:** Active
- **Date:** 2026-07-09
- **Author:** Luca Mastrostefano
- [x] Implemented

## Context

RFC 2026-06-03 (`first-run-banner`) introduced the self-removing `AGENTS.md` banner and
gated it behind a wizard prompt — *"Add a first-run banner to AGENTS.md so the agent
self-onboards?"*, default on. That prompt is a trap.

The banner is the only mechanism that makes the agent notice the pending setup *without
being told*. Everything else in the first-run apparatus depends on someone remembering:
`ONBOARDING.md` sits unread until a human opens it, and the `/onboard` triggers fire only
when a human types the command. Decline the banner and the wizard still ships all of it —
so the repo isn't literally half-scaffolded, but its completion now rests on the user
recalling a one-line console hint from a wizard they ran once. When that recall fails, the
project keeps the tooling and never activates it: hooks uninstalled, `ONBOARDING.md`
rotting in the tree, and the agent — the one party that reads `AGENTS.md` every session —
with nothing telling it any of that is pending.

What makes this a bad question rather than merely a risky one is that the "no" branch buys
nothing. The banner is already gated to the only situation where it does anything
(`ai_context.py`: at least one targeted AI tool — which reaches `AGENTS.md` directly, by
symlink, or via a pointer file — *and* an `ONBOARDING.md` for it to point at), and it is
transient by construction — the last step of the runbook deletes it. So "no" trades the sole memory-independent completion path for the avoidance of
a few lines of text that would have deleted themselves. No user has the context, mid-wizard,
to know that; the question reads like a reasonable minimalism toggle and isn't one.

## Decision

Drop the prompt. In the interactive wizard, inject the banner whenever it can work:

```python
first_run_banner = bool(("quality" in parts or "ci" in parts) and tools)
```

That is precisely the condition under which the question used to be *offered*, so this is
the old default with the choice removed — not a widening of when the banner appears. The
gate stays because it is load-bearing: with no AI tool targeted, no agent is pointed at
`AGENTS.md` at all and the block is inert text; without `quality`/`ci` no `ONBOARDING.md`
ships and the banner would promise a runbook that doesn't exist.

`--no-first-run-banner` survives as the scripted escape hatch. The trap is the interactive
question, where "no" looks reasonable and costs onboarding; a flag typed on purpose in a
non-interactive run is a deliberate choice by someone who read its name.

## Consequences

- The default interactive scaffold always self-onboards: the agent reads the banner on its
  first turn, so "what should I do?" is enough. Onboarding no longer depends on the user
  remembering `/onboard` or the console hint.
- One fewer question in the wizard — and the one removed is the one users were least
  equipped to answer, since its cost is invisible until weeks later.
- We give up interactive opt-out. Someone who genuinely wants an un-bannered `AGENTS.md`
  must pass `--no-first-run-banner`, or delete the delimited block afterwards (it is
  designed to be removed mechanically). This is the intended trade: the banner is cheap and
  self-erasing, so the opt-out was never worth its cost in failure modes.
- Amends the "gated by a wizard prompt" bullet of RFC 2026-06-03; the rest of that
  decision — the self-removing block, the delimiters, the suppression rules — stands.
- The `agent-native-baseline` profile still declares a `first_run_banner` prompt with its
  own `when` clause. A default run never asks it (the wizard's answers are translated onto
  the baseline's prompts via `config_to_answers`), so this change fully covers the default
  path. An explicit `--profile agent-native-baseline` run would still ask; retiring that
  prompt belongs to the profile's own repo and release, not here.

## Alternatives considered

- **Keep the question, flip the default to off.** Backwards: it makes the failure mode the
  default.
- **Keep the question, explain the cost in the `_note`.** More words to fix a question that
  shouldn't be asked. The wizard already noted what the banner does; users still had no way
  to price "no" — because "no" has no upside to weigh against.
- **Remove `--no-first-run-banner` too.** Tempting for consistency, but it deletes a public
  CLI flag (a breaking change) to close a hole nobody falls into by accident. A scripted
  run that passes the flag means it.
- **Drop the banner's gate and always inject.** Produces a block pointing at an
  `ONBOARDING.md` that was never generated, or sitting in a file no agent loads. The gate
  is what keeps the banner honest.
