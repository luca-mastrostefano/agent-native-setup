# Require an RFC — or a logged waiver — for architectural changes

- **Status:** Active
- **Date:** 2026-05-31
- **Author:** Luca Mastrostefano

## Context

`AGENTS.md` says to write an RFC before "changing architecture or a public
contract, adding a dependency or service, or anything hard to reverse." Nothing
enforces it — it rides on the author remembering. The existing `rfc-status` hook
only files an *existing* RFC into the folder matching its `Status:`; it never
notices a *missing* one. So this whole class of decision still depends on memory,
the exact thing the project replaces with mechanical enforcement.

The hard part: RFC-worthiness is partly semantic, so any diff-based trigger will
sometimes fire on a change that didn't actually need an RFC. The usual answer —
narrow the triggers to avoid false positives — also narrows coverage, missing
real architecture changes. The better answer is to make the **skip itself a
first-class, recorded decision** rather than a silent override. A false positive
then costs one justification line, not a dead hook.

## Decision

Add a **`commit-msg`** hook `rfc-needed` (`tools/checks/rfc_needed.py`) that fires
when a commit makes a structural change and is satisfied by *either* an RFC or a
logged waiver.

**Triggers** (kept to infrequent, structural signals so the prompt stays rare):

- a new distribution added to `[project.dependencies]` in `pyproject.toml`
  (new PEP 508 *name* — version bumps, re-pins, and removals do not fire);
- any change under `docs/architecture/`;
- a new top-level package under `src/` (a newly added `src/<pkg>/__init__.py`).

**Satisfied when** the same commit either:

- stages a file under `docs/rfc/proposed/` (or `active/`), **or**
- carries a non-empty `RFC-Not-Needed: <reason>` trailer in its message.

Otherwise the hook exits non-zero with a message naming both escape routes and
pointing at `docs/rfc/TEMPLATE.md`. It inspects `git diff --cached` for triggers
and reads the message file passed by the `commit-msg` stage; it parses the
dependency list directly, so it adds **no new dependency** and works on the
project's `requires-python >= 3.10`.

The hook only *flags the gap and records the call* — it never writes or moves
RFCs. Authoring stays with the contributor; `sync_rfc_status.py` keeps handling
moves. `--no-verify` remains a last resort, but the intended skip is the trailer,
because it leaves a reason in git history that review can see.

## Consequences

A structural change now forces a deliberate choice at commit time — write the
RFC, or state in one line why none is needed — and that choice lands in the
permanent record instead of an agent's working memory. Reviewers can spot a lazy
waiver in the diff. The cost: contributors write the occasional `RFC-Not-Needed:`
line for changes that genuinely don't warrant an RFC, and the check moves to the
`commit-msg` stage (added to `default_install_hook_types`).

Follow-up (not in this RFC): once proven here, the wizard should scaffold this
hook into generated projects so new repos inherit the behavior.

## Alternatives considered

- **Precision-only, plain bypass** (narrow to dependency adds, `SKIP=`/`--no-verify`):
  fewer false positives, but misses architecture changes entirely and its skips
  leave no trace. The logged-waiver approach gets broader coverage *and* an audit
  trail for the same friction.
- **Even broader triggers** (any `src/` edit, Taskfile/CI, `AGENTS.md`): would
  prompt on ordinary feature work and train people to rubber-stamp the waiver.
  Kept triggers to rare structural signals so the prompt stays meaningful.
- **Warning-only / non-blocking:** easy to ignore; adds little over the contract
  text that already exists.
- **An agent that auto-drafts the RFC:** out of scope — a meaningful RFC needs the
  author's intent, which a hook can't supply. The hook only forces the decision.
