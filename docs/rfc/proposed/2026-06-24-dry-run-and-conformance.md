# Scaffold `--dry-run` and a conformance (drift) check

- **Status:** Proposed
- **Date:** 2026-06-24
- **Author:** Luca Mastrostefano
- [ ] Implemented

## Context

The scaffold-then-`update` loop has two ergonomic gaps in *today's* engine — independent of
the proposed profiles work (RFC 2026-06-23), though both generalize to it once the wizard is
formally the `default` profile:

1. **No scaffold preview.** `update` has `--dry-run`; the scaffolder doesn't. A user
   evaluating what the wizard will lay down has to run it for real — non-destructive, but it
   still writes files and may `git init`.
2. **No "have I drifted?" answer.** Keeping a fleet of repos consistent needs a way to ask
   *"does this project still match its scaffolded setup?"* The update engine already computes
   it (regenerate at the current version, then `classify` surfaces every managed file edited
   away from the scaffold), but `update --dry-run` on an up-to-date project **mislabels** the
   result: it prints *"N file(s) you've edited changed upstream"* when nothing changed
   upstream — the user drifted.

These are the immediately-buildable subset of a broader profile-experience review; the
profiles-native refinements (init / save-as-lifecycle / trust-pinning / N-layer) live with
RFC 2026-06-23, gated on that engine.

## Decision

### 1. Scaffold `--dry-run`

A `--dry-run` flag on the scaffold flow renders the full set of files a run would create
(and which it would **skip** because they already exist), writes nothing to the target, and
skips `git init`. The implementation reuses the proven `update` regeneration path in two
passes: (1) build the resolved config into a throwaway temp dir
(`dataclasses.replace(config, output_dir=tmp, init_git=False)`) to discover the file set,
then (2) stage an empty placeholder for each discovered path that already exists in the
target and build again, so `Scaffolder.write`'s **own** preserve/force/skip logic produces
the create-vs-skip split. This matters: the skip-existing and `--force`-overwrite behaviour
lives in the writer, *outside* the generators — so previewing against an existing repo has to
replay the writer, not just the generators, to match a real run. No new `Scaffolder` mode and
no reimplementation of that policy. Parity with `update --dry-run`.

### 2. Conformance: reframe same-version conflicts as local drift

When `update` runs with no version change (`decide == NOOP`), classify's conflicts are
**local drift**, not upstream changes. `_print_plan` (and the `UPDATING.md` reconcile intro)
say so: *"N managed file(s) have drifted from the scaffold (edited since)"* instead of
*"changed upstream."* No engine change — the conflict is already computed; only the framing
was wrong. This makes `update --dry-run` double as an are-we-conformant check, and the
wording generalizes verbatim to "drifted from profile X" once the owning layer is the
baseline.

We deliberately do **not** add a separate `--drift` / `profile status` command: drift *is*
the `update --dry-run` plan at the same version, so reframing that output covers it without
surface bloat. (Revisit only if conformance needs a machine-readable exit code for a CI gate.)

## Consequences

- Scaffold gains preview parity with update; a user (or agent) can see the tree before
  committing to it.
- Conformance is answered by reusing the update engine for ~free, giving the
  fleet-consistency goal a real check — the deepest of the broader review's items, since it's
  *why* a team standardizes on a setup.
- The drift reframe is behaviour-preserving except for wording; the only risk is the message
  itself, covered by tests.
- `--dry-run` builds into a temp dir, so it inherits the same determinism assumption the
  updater already relies on (the generators are pure functions of the config).

## Alternatives considered

- **A dedicated `update --drift` / `profile status` command.** Rejected as surface bloat:
  same-version `update --dry-run` already *is* the check; a second command would duplicate it.
- **Make scaffold `--dry-run` a non-writing `Scaffolder` mode** (a flag threaded through
  `write`). Rejected: build-into-temp reuses the existing path with zero new branching in the
  writer, and matches how `update` already regenerates.
- **Put drift in the SessionStart `--check` nudge.** Rejected: regenerating the whole tree is
  too heavy for every session start (`check()` is kept sub-1.5s and silent-on-error); drift is
  an explicit, on-demand `--dry-run`.
