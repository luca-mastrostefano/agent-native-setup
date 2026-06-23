# Rework the RFC lifecycle: proposed → active → (superseded | retired)

- **Status:** Active
- **Date:** 2026-06-17
- **Author:** agent-native-setup team
- [x] Implemented

## Context

The current lifecycle — Proposed/Accepted/Done/Superseded over `current/ → done/ →
superseded/` — conflates two unrelated axes: a decision's **validity** (is it in
effect?) and its **implementation status** (is it built?). "Accepted" vs "Done" is
the latter, which doesn't belong in an RFC lifecycle.

The evidence is in the repo: **all 34 prior RFCs are `Accepted` in `current/`, and
`done/` is empty** — the Accepted/Done distinction (the implementation-status axis) has
never once been used. (`superseded/` is empty too, but that reflects the project's youth
— no decision has been replaced yet — not over-specification.) Two further gaps:

- `superseded` needs a replacement RFC to point at, so a decision **withdrawn without a
  replacement** has no honest terminal state today: you'd misuse `superseded` with no
  link, or leave a dead decision marked active. No RFC has hit this yet, so `retired` is
  a deliberate bet that completing the validity state-machine now is cheaper than hitting
  the gap later — not a response to observed pain.
- Nothing connects an RFC's state to whether `docs/architecture/` is current, so the
  architecture docs have no derivable source of truth.

## Decision

**1. Four states, each its own folder.** `proposed → active → (superseded | retired)`:

| State | Meaning | Folder |
| --- | --- | --- |
| **proposed** | drafted, under discussion, not yet binding | `docs/rfc/proposed/` |
| **active** | accepted and in effect — governs the system now | `docs/rfc/active/` |
| **superseded** | replaced by a specific later RFC (link it) | `docs/rfc/superseded/` |
| **retired** | withdrawn/obsolete, no replacement (say why) | `docs/rfc/retired/` |

`active` replaces both `Accepted` and `Done`: a decision is active whether or not it's
been built. Folders mirror the state names exactly (no more `current/`/`done/`).

**2. Architecture reflects the active RFCs.** `docs/architecture/` is the readable
synthesis of the currently-active **architectural** decisions: nothing in
`architecture/` without an active RFC behind it, and superseding or retiring an
architectural RFC is the cue to update it. This is scoped to *architectural* RFCs —
process/convention RFCs (testing expectations, followable processes, review lenses)
reflect into the contract (`INSTRUCTION.md` for the standard parts, `AGENTS.md`) /
`CONTRIBUTING.md` instead. Kept as a **guideline**, not a
mechanical 1:1: there is no new "kind" field and no gate demanding an architecture edit
per RFC — the scoping is by judgment, because most RFCs' kind is obvious and a wrong
gate is worse than none.

**3. Implementation status is a checkbox, not a state.** The RFC template carries a
`- [ ] Implemented` line in its header; `active` means "decision in effect" regardless
of build status, so the lifecycle stops tracking work that issues/PRs already track.

## Consequences

The steady state is simpler (one `active/` folder is where decisions live), reversal
becomes first-class (`retired`), and `architecture/` gains a source of truth. The
migration touches the meta-process, so it lands behind this RFC:

- Restamp the 34 prior `Accepted` RFCs → `Active` and move them to `active/`.
- `docs/rfc/TEMPLATE.md` — Status line becomes `Proposed | Active | Superseded |
  Retired`; add the `- [ ] Implemented` checkbox.
- `sync_rfc_status.py` — `STATUS_FOLDER` and `LIFECYCLE_FOLDERS` for the four folders.
- `rfc_needed.py` — its "an RFC is staged" check currently looks for
  `docs/rfc/current/`; a new RFC is `proposed`, so the check must accept
  `docs/rfc/proposed/` (and `active/`), or it stops recognizing accompanying RFCs.
- `docs/README.md`, the contract's lifecycle line (`current/ → done/ → superseded/`),
  the `rfc-reviewer` agent's "no conflict with done/superseded" criterion, and the
  still-active `rfc-reviewer` RFC's Decision text, which bakes in the old vocabulary.

Cost: a one-time migration and everyone learning four states — but they map to how
people already think ("is this decision live?") better than the old four did. This RFC
is itself cheap to reverse (rename the folders back, restamp), but it redefines a
process every contributor and the commit-msg gate rely on, so it gets an RFC — and is the
first decision authored under the new model (the 34 prior RFCs migrate into it). Its
header already uses the new `- [ ] Implemented` checkbox and a `Proposed` state valid
under both the old and new template, pre-adopting the format intentionally before the
template change lands.

## Alternatives considered

- **Keep the current model** — rejected: the unused `done/`/`superseded/` folders after
  34 RFCs show it's over-specified, and it has neither a `retired` state nor any
  architecture linkage.
- **Add a `kind: architectural | process` field** to scope the architecture principle
  mechanically — rejected as over-engineering: prose scoping plus the supersede/retire
  cue is enough, and a per-RFC architecture gate would misfire on process RFCs.
- **Keep `Done` as a state** — rejected: implementation status isn't decision validity;
  the `- [ ] Implemented` checkbox captures it without a lifecycle state.
- **Track decision validity in issues instead of the lifecycle** — rejected: issues
  track work; the RFC lifecycle is the right home for standing decisions.
