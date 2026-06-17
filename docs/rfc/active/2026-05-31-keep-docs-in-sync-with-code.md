# Keep architecture docs in sync with the code that changes them

- **Status:** Active
- **Date:** 2026-05-31
- **Author:** Luca Mastrostefano

## Context

The contract's "Context" pillar rests on `docs/` and RFCs staying accurate as the
system evolves. Nothing keeps `docs/architecture/` current — it rides on the
author remembering to update prose after changing code, the exact failure mode
the project replaces with mechanical enforcement.

`rfc_needed.py` already fires on structural signals, but it enforces a *decision
record* (an RFC — "why we did this"), not the *current-state description* (the
architecture overview — "what the system is"). These are different artifacts: a
change can satisfy the RFC gate yet still leave `overview.md` stale — e.g.
implementing something an existing RFC already decided. The RFC hook even fires
*when you touch `docs/architecture/`*, which is the opposite of a reminder to
touch it.

The hard part is the one the RFC hook already faced, but sharper: staleness is
*semantic*. "This code change made the docs wrong" cannot be read off a diff. Any
mechanical trigger is a coarse proxy, and the broad proxy — "any `src/` change
without a `docs/` touch" — fires on nearly every commit (bug fixes, refactors,
tests) and trains people to rubber-stamp the waiver. The existing RFC already
rejected that breadth for exactly this reason.

So the design splits by what each layer can actually do:

- **Semantic judgment** ("are the docs now stale, and any good?") stays with
  humans and agents — the saved memory preference plus a new `code-reviewer`
  checklist line.
- **The hook** covers only the one structural signal that is both mechanically
  detectable *and* almost always doc-worthy: a new top-level component.

## Decision

Three parts; the first ships ahead of this RFC as a non-structural soft change.

**1. Soft layer (already applied).** `code-reviewer` gains a fifth check — flag
any doc under `docs/` (especially `docs/architecture/`) or RFC the change makes
stale. No enforcement; it catches staleness at *review* time by judgment, and the
saved memory preference catches it at *authoring* time.

**2. Mechanical layer.** A `commit-msg` hook `docs-sync`
(`tools/checks/docs_sync.py`), same shape and philosophy as `rfc_needed.py`.

**Trigger** (deliberately one rare, structural, almost-always-doc-worthy signal):

- a new top-level package under `src/` (a newly added `src/<pkg>/__init__.py`) —
  a component the architecture overview's Components section should name.

**Satisfied when** the same commit either:

- stages a change under `docs/architecture/`, **or**
- carries a non-empty `Docs-Not-Needed: <reason>` trailer in its message.

Otherwise the hook exits non-zero, names both escape routes, and points at
`docs/architecture/overview.md`. Like `rfc_needed.py`, it inspects
`git diff --cached`, reads the message file passed by the `commit-msg` stage, adds
**no new dependency**, and runs on `requires-python >= 3.10`. It only flags the
gap and records the call — it never writes docs.

**3. Scaffold it.** Wire the hook into the wizard so generated repos inherit both
it and the reviewer checklist line, gated on `include_docs` like the rest of the
doc machinery. Concretely this means, in `generators/quality.py`, adding
`commit-msg` to the generated `default_install_hook_types` and emitting the
`docs-sync` block, plus writing `tools/checks/docs_sync.py` (alongside
`sync_rfc_status.py` in `generators/docs.py`), and updating `CODE_REVIEWER` in
`generators/agents.py`. Note the `commit-msg` plumbing is the same piece the
`rfc_needed.py` follow-up still owes generated projects — the two should land
together so new repos get both `commit-msg` hooks at once.

## Consequences

Adding a new top-level component now forces a deliberate choice at commit time —
update the architecture overview, or state in one line why it doesn't need it —
and that choice lands in git history. The overview stops silently drifting at the
one moment it most predictably goes stale.

Coverage is intentionally partial: a doc made stale by editing *existing* code
won't trip the hook. That gap is owned by the memory preference and the reviewer
checklist line — defense in depth across author → review → commit, with the hook
as the only hard gate.

The new hook and `rfc_needed.py` both fire on a new top-level package. That is
intended — they ask different questions (record the decision vs. describe the
result) and each has its own waiver — but the double prompt is a real ergonomic
cost. If it grates in practice, fold the two into one check (see Alternatives).

Cost: an occasional `Docs-Not-Needed:` line when a new package genuinely needs no
overview entry (an internal `tools`-like helper), and one more `commit-msg` check
to install.

## Alternatives considered

- **Broad trigger** (any `src/` change without a `docs/` touch): more coverage,
  but fires on ordinary feature work, bug fixes, and tests, training contributors
  to rubber-stamp the waiver — the failure the RFC hook's own RFC avoided.
- **Fold into `rfc_needed.py`** (one hook, one waiver, both concerns): no
  duplication and no double prompt, but it conflates the two artifacts — a single
  waiver would excuse *both* the missing RFC and the stale doc, weakening each.
  Kept separate for now; revisit if the double prompt proves annoying.
- **Soft layers only** (no hook): cheapest, but leaves the one mechanically
  detectable, predictable drift point — a new component — riding on memory, which
  is precisely what the project mechanizes. The narrow hook closes it for little
  friction.
- **A bot that auto-writes the doc:** out of scope — an accurate, studyable
  overview needs the author's intent, which a hook can't supply. The hook only
  forces the decision.
