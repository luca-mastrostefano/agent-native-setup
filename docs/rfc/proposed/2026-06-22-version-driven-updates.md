# Version-driven updates: a semver difficulty contract + a major-version gate

- **Status:** Proposed
- **Date:** 2026-06-22
- **Author:** Luca Mastrostefano
- [ ] Implemented

## Context

RFC 2026-06-20 shipped the `update` engine: regenerate from the saved config, classify each
generated file against the manifest's fingerprints (create / refresh-when-pristine /
conflict-when-edited / remove-orphan), never touch *seed* (user-owned) files, replay
idempotent structural migrations, lean on git for undo. It works, but it has **no notion of
versions** — and that leaves three real gaps for a tool whose whole value is shipping
improvements to already-scaffolded repos over months.

1. **It can't tell a safe refresh from a breaking change.** Every on-disk divergence is a
   flat "conflict." There's no declared signal that "1.3 → 1.6 is rubber-stamp-safe" while
   "1.x → 2.0 restructures your contract and needs you in the loop." The user (or their
   agent) has to reverse-engineer the risk from a diff every single time.

2. **Some changes can't be expressed as content at all.** Regeneration produces the latest
   content of files the wizard *generates*. It cannot transform a file the **user owns**
   (split their `AGENTS.md`), nor move content the user accumulated (their RFCs, when a
   folder layout changes). Today those land as bare "conflicts" with no guidance.

3. **The skipped-versions trap.** A user many releases behind needs the migration
   instructions for **every** version boundary they cross, *in order* — not just the latest
   release's. A 1.2 → 3.0 jump where `UPDATING.md` carries only the 3.0 steps is not merely
   incomplete: the 3.0 migration may assume the 2.0 layout, so applying it against a 1.2-era
   tree produces garbage or fails.

The lived question this RFC answers is **"how does a user keep their scaffolding fresh from
time to time?"** Two facts frame it:

- **There are two versions in play.** The *tool* (the CLI, installed globally via
  `uv tool install`) and the *scaffolding* (the generated files in the repo, whose version
  is recorded in `.agent-native-setup.json`). The newer templates live in the upgraded tool,
  not the repo — so **every update is two steps**: `uv tool upgrade agent-native-setup`, then
  `agent-native-setup update` (or the `/update` skill).
- **Distribution is HEAD-install today, and this is a hard gating dependency — not a cost.**
  RFC 2026-06-04 adopted `hatch-vcs` (tag-derived versions), but there is no release cadence,
  so `__version__` resolves to `"0.0.0"` (raw checkout) or a dev string (`2.1.0.dev4+gsha`),
  and the manifest records that verbatim. **Until deliberate `patch`/`minor`/`major` release
  tags exist, the model below does not function as designed:** every project reads
  `installed = 0.0.0`, the whole migration registry falls in-span, and `update` degrades to
  *today's* behavior — surface everything, gate nothing, no autopilot. So **shipping tagged
  releases is a precondition of this RFC, not a downstream consequence of it.** Everything
  past this point assumes that precondition is met; the "unknown version" edge case
  (below) is what we do in the meantime, and it is the steady state until tags land.

## Decision

A version-driven model layered on the existing engine. The engine stays the spine; versions
add the missing intent.

### 1. Semver is a difficulty contract

The version bump *declares* how hard the update is to apply to an existing project:

| Bump | Meaning for an existing project | How `update` treats it |
| --- | --- | --- |
| **patch** | a fix; pure content refresh | auto-applied |
| **minor** | compatible feature; content refresh **+ auto, idempotent structural moves** (deterministic, no judgment) | auto-applied |
| **major** | a change that needs **user confirmation** and possibly **agent-assisted** migration of user-owned content or layout | gated (below) |

The obligation that makes this work: **any change that needs an agent or the user to migrate
an existing project MUST ship as a major.** That turns "is this safe to auto-apply?" from a
per-run inference into a declared property. Crucially, the declaration is *verified, not
trusted blindly* — see §8.

### 2. An update has two independent halves

These are computed and reasoned about separately, because they have different version
behavior:

- **Content of generated files** — a **one-shot** fingerprint diff between the user's tree
  and the *latest* templates (the regenerate-and-classify engine, already built). It is
  version-independent: it collapses any amount of drift (1.2 → 3.0) in a single pass, and it
  must **not** be enumerated per version (no "1.3 refreshed X, 1.4 refreshed X again" noise).
- **Migration steps** — the ordered, per-version transforms of **user-owned** content/layout
  that regeneration cannot compute. These are the part that **replays across the span**.

This split is the resolution of every "incremental vs one-shot" tension in the discussion:
*content folds to latest in one shot; breaking-step instructions replay in sequence.*

### 3. The major-version gate

Let `installed` = the manifest's version, `latest` = the running tool's version (compared
with `packaging.Version`).

- **`latest <= installed`** → nothing to do (and if strictly less, **refuse**: "your installed
  tool is older than this project's scaffolding — upgrade the tool").
- **Same major** (`installed.major == latest.major`) → **autopilot.** Apply the content diff
  and any auto structural moves in the span; the only review is the standard `git diff`. No
  extra confirmation — the contract promised nothing breaking happened.
- **`latest.major > installed.major`** → **gated.** Run the `auto` structural migrations
  (idempotent), then **pause before any content is written**: assemble the ordered span of
  `agent`/`manual` steps into the runbook (§5) and **require explicit confirmation**. On
  confirm, the agent/user works the ordered instruction sections, and *then* content
  regenerates **to latest in one pass** and classifies (§2). Content is **never** applied
  boundary-by-boundary — that is the one-shot diff §2 describes; only the migration
  *instructions* are span-ordered. For a **multi-major** span (1.2 → 3.0), the runbook's
  instruction sections cover every boundary, ascending (2.0 then 3.0), because each agent step
  assumes the prior one ran; the v1 flow confirms **once** for the whole span (per-boundary
  confirmation is the stepped upgrade, §5).

A major boundary **always** pauses for confirmation, even if its steps happen to be
mechanically safe — crossing a major is the user's signal to look.

### 4. The migration registry (append-only) — revising 2026-06-20's version-blind model

> **This revises, not extends, RFC 2026-06-20 §3.** That RFC deliberately chose *version-blind,
> attempt-all* migrations ("robust even when versions aren't reliably tagged"), and the shipped
> `migrations.py` keys each entry by a free-text slug (`since="rfc-lifecycle-rework"`), not a
> comparable semver. This RFC keeps that robustness for the deterministic moves but adds a
> real semver to the entries that need a *gate* and a *span*. The reconciliation below is the
> point — it is not purely additive, and the re-keying is a named cost (§Consequences).

A single append-only list, retained forever, is the "incremental changelog." Each entry
declares:

- **version** — a real semver (`packaging.Version`-comparable), the release it shipped in;
- **kind** — `auto` (a deterministic move/rename the tool performs), `agent` (needs a coding
  agent to read the user's content and transform it), or `manual` (a human step);
- a **machine-applicable function** (for `auto`) **and/or** a **natural-language instruction
  block** (for `agent`/`manual`).

The two kinds are handled differently, which is how this stays compatible with the built
engine:

- **`auto` steps keep the shipped idempotent attempt-all behavior** — they guard on the old
  layout and no-op otherwise, so they run on every update regardless of version, and getting
  their version slightly wrong can't hurt. Their version is informational/ordering only. This
  is exactly `migrations.py` today, plus a semver alongside the slug.
- **`agent`/`manual` steps are version-keyed and span-selected**: emit every such step with
  `installed < step.version <= latest`, ascending, into the runbook (§5). This is the *only*
  place span selection is load-bearing — assembling the ordered instruction sections for the
  boundaries actually crossed (the skipped-versions fix). By the §1 contract, `auto` steps
  may ship at a minor; `agent`/`manual` steps only at a major.

(Until real tags exist, `installed = 0.0.0` makes span selection trivially return *everything*
— so the version-keying earns its keep only once the Context's release-tagging precondition is
met. Until then `auto` attempt-all already does the right thing, and the agent-step span is
simply "all of them.")

### 5. `UPDATING.md` is an ordered runbook

It carries the two halves explicitly, so a skipped-versions user gets everything in order:

```
## Reconcile these          ← one-shot content conflicts (edited managed files), to latest
- AGENTS.md — edited since scaffold
- …

## Migration steps          ← the ordered span (installed, latest]
### 2.0.0 — split AGENTS.md → INSTRUCTION.md
  <instructions for the agent>
### 3.0.0 — relocate the docs/rfc layout
  <instructions>
```

**v1 ships the aggregated runbook**: all ordered sections in one file, the agent works
through them top-to-bottom, confirm once for the whole major span. The **stepped** variant
(pause-confirm-migrate at each boundary individually) is noted as the upgrade — it is safer
for "each migration assumes the prior ran," but chattier, and needs no new data (same ordered
span), so it can land later without rework.

### 6. Discovery — the start-of-session check

A user won't update what they don't know is stale. The end-of-run nudge (RFC 2026-06-04) only
fires on a fresh scaffold; extend it to **existing** repos via the generated
`.claude/settings.json` `SessionStart` hook, which already injects the command surface. Add a
read-only `agent-native-setup update --check` that prints one cached line (reusing the
update-check cache + TTL) and nothing when current:

- same major behind → `scaffolding 1.3.0 · latest 1.6.0 — compatible update, run /update`
- a major behind → a louder `scaffolding 1.6.0 · latest 2.0.0 — major (breaking) update; review before applying`

So minor updates become a casual `/update`; majors announce themselves.

### 7. The `INSTRUCTION.md` split, now motivated

RFC 2026-06-20 deferred splitting the contract into a managed `INSTRUCTION.md` (standard
rules, refreshable) + a seed `AGENTS.md` (the user's). Under this model it becomes the
**first dogfooded `agent` major migration**: a 2.0 step that reads the user's `AGENTS.md`,
lifts the standard sections into `INSTRUCTION.md`, leaves their additions behind, and adds the
`@INSTRUCTION.md` pointer. Its payoff is structural: *after* the split, improvements to the
standard instructions are plain content refreshes (the managed `INSTRUCTION.md`) — converting
the scariest content-migration (transforming a user-owned file) into free regeneration
forever after. The split is the proof that the `agent`-kind migration pulls its weight.

### 8. Defense in depth: the version declares, the fingerprints verify

Semver is a human promise, and humans mislabel. The per-file fingerprints are the backstop
that keeps a mistake from becoming data loss:

- A change wrongly tagged **minor** that would **clobber a file the user edited** is still
  caught — the fingerprint diverges, so it's a conflict, not an overwrite. The version label
  can't override the evidence on disk.
- What the backstop *cannot* catch is a **semantic** break in a file the user never touched
  (pristine → refreshed to something that breaks their build). Nothing on disk flags it.

So semver discipline is **load-bearing, not decorative**, and the fingerprint check is a
safety net under it — not a substitute. We state this plainly rather than pretend the version
is infallible.

## User stories

**A. Compatible update (1.3.0 → 1.6.0).** Session opens; the hook prints "compatible update,
run /update." The user runs `uv tool upgrade` then `agent-native-setup update`. Same major →
autopilot: a clean tree is required, content refreshes (a sharper `code-reviewer` prompt, a
fixed CI permission, a new guardrail script), pristine orphans are removed, seed files
untouched, zero migration steps. Output is one reviewable `git diff`; the user commits.
Their whole role: review and commit.

**B. Major update (1.6.0 → 2.0.0).** The hook flags a breaking update. After upgrading the
tool, `update` applies the safe content, then **stops** at the 2.0 boundary: "2.0.0 splits
your AGENTS.md — run it with your agent (/update), or apply UPDATING.md by hand." Via the
skill, the agent reads the declared instructions, performs the split on the user's actual
content, confirms before writing, narrates the result. Still one `git diff`; `git checkout .`
is the undo.

**C. Long-dormant, multi-major skip (1.2.0 → 3.0.0).** The span crosses two majors, so the
gate fires. `auto` moves run, then `update` pauses: `UPDATING.md`'s migration section lists
the `agent`/`manual` steps for **both** boundaries — `### 2.0.0` then `### 3.0.0`, ascending —
the case that motivated §5. The user confirms once; the agent works the sections
top-to-bottom (2.0 before 3.0, since 3.0 assumes the 2.0 layout); *then* content regenerates
to 3.0 in a single pass. Content is not applied per boundary — only the breaking-step
instructions are sequenced. Neither boundary's instructions are silently skipped.

**D. A customization meets an upstream change (any bump).** The user had edited a *managed*
file (customized `code-reviewer.md`). Even in a compatible update, the fingerprint catches the
divergence → it's not clobbered, it's a conflict in `UPDATING.md`. `/update` drives the agent
to reconcile: "upstream sharpened this prompt; you added a rule; here's the merge." Agent help
on conflict is **opportunistic** and independent of the major/minor gate.

## Edge cases

- **Downgrade** (`latest < installed`): refuse with "upgrade the tool" — never regenerate
  older templates over newer scaffolding.
- **No / pre-version manifest** (degraded): RFC 2026-06-20 already refuses a missing manifest.
  A manifest with an **unparseable or absent version** is treated as `0.0.0` → the whole
  registry is in-span, so **all** migration instructions are surfaced conservatively and the
  user/agent reconciles; nothing auto-applies across an unknown boundary without confirmation.
- **Dev / HEAD builds** (`2.1.0.dev4+gsha`): compared by `packaging.Version`, which orders dev
  builds correctly (`< 2.1.0`, `> 2.0.0`). The major is the release major, so a dev build of
  the same major as `latest` is autopilot; a bleeding-edge HEAD past `latest` is "nothing to
  do," never nagged.
- **Major bump with no migration steps** (e.g. a tool was removed): still gated — a major
  always confirms — but the runbook's migration section just states what changed.
- **Interrupted migration** — and the recovery is genuinely harder for `agent` steps than for
  `auto` ones, so we don't pretend otherwise. The manifest version is bumped **only after the
  user confirms the migration succeeded** (the agent's result is reviewed, not auto-trusted),
  so `installed` is unchanged on interrupt. For `auto`/content failures, recovery is clean:
  they're idempotent, so re-running finishes the job, and `git restore .` reverts tracked
  files. For an `agent` step the guarantee is weaker: it's *not* idempotent, and
  `git restore .` does **not** remove new **untracked** files — a half-done split that already
  wrote a new `INSTRUCTION.md` leaves it behind. So the recovery contract for `agent` steps
  is the explicit pair **`git restore . && git clean -fd`** (clean removes the untracked
  artifacts), returning to the pre-update commit; re-run from there. The `/update` skill must
  state this, and an `agent` migration should be authored to be safely abandonable (write its
  new files only once, near the end), since a generic mid-flight abort is the residual risk
  this design carries rather than eliminates.
- **Agent unavailable** for a major (plain CLI, no Claude): the breaking steps are **not**
  auto-applied; `UPDATING.md` carries human-readable instructions to do by hand or hand to an
  agent later. `update` exits having applied only the safe part.
- **A migration target the user also edited**: migrations (which transform user content) run
  **before** the content classify, so the `agent` step operates on the user's real file; the
  agent is explicitly responsible for preserving their edits while transforming structure
  (that's why it's `agent`-kind, not `auto`).
- **Registry growth**: append-only, but each entry is a small move + optional instruction
  block, bounded by the count of **breaking changes**, not releases — most releases add no
  entry. The maintenance cost is real but proportional to genuine structural change.
- **Idempotent re-run / already current**: `auto` steps no-op on the new layout; an
  already-current tree classifies to nothing. `update` is safe to run repeatedly.

## Consequences

- Updating becomes a routine the SessionStart check surfaces, minor updates are one-command
  autopilot, and breaking changes are gated, explained, confirmed, and agent-assisted rather
  than a wall of unexplained conflicts. This is the payoff that makes a long-lived scaffolded
  repo actually track the tool's improvements.
- We take on **release discipline** — deliberate patch/minor/major tagging and an actual
  cadence — as a hard requirement, not a nicety. Mislabeling has real consequences (§8). This
  is the biggest new cost and it is process, not code.
- The migration registry must be maintained forever and tested for **ordered composition**
  across spans (does 1.x→2.0→3.0 compose?). Bounded, but a standing burden.
- This **revises RFC 2026-06-20 §3's deliberately version-blind migration model** (§4): the
  shipped `Migration.since` slug must gain a real semver, and `agent`/`manual` steps gain
  span selection. `auto` steps keep their attempt-all behavior, so it's a superset, not a
  teardown — but it is a change to a live decision, recorded here so the two RFCs don't read
  as contradictory.
- `INSTRUCTION.md` (§7) lands as the first major migration, which means editing the "single
  source of truth" line in the contract and the reflect-into-`AGENTS.md` guidance of RFC
  2026-06-17 — those edits ride with the 2.0 step, as RFC 2026-06-20 already flagged.
- The version comparison adds no new dependency (`packaging` arrived with RFC 2026-06-04).
- We give up the simplicity of a version-blind engine: there is now a gate, a registry, a
  span calculation, and a confirmation flow. Justified only because the alternative — every
  breaking change arriving as an unexplained conflict — scales worse as the tool matures.

## Alternatives considered

- **Pure migration chain** (every change ships an incremental script; replay the whole chain).
  Rejected: for the common case (a managed file's content changed) regeneration already
  produces the new content, so a per-release script just re-encodes the template — redundant
  authoring plus a forever-compose test burden. Worse with HEAD-installs, where chain
  boundaries are fuzzy. We keep regeneration for content and reserve scripts/instructions for
  what genuinely needs them (structural + breaking).
- **Runtime inference only** (today's engine, no versions): every divergence is a flat
  conflict with no autopilot/gate distinction and no guidance for breaking changes. It's the
  thing this RFC fixes.
- **Always route updates through the agent** (no auto path): heavyweight and slow for a
  trivial patch; burns judgment on rubber-stamp diffs. The gate exists precisely to reserve
  the agent for majors.
- **Stepped runbook in v1** (pause-confirm at every boundary): safer but chattier, and needs
  the same ordered-span data as the aggregated runbook — so we ship aggregated first and can
  add stepping without rework.
- **Telemetry / silent auto-update**: out of scope and intrusive; a read-only check plus an
  explicit, reviewable `update` is the least-surprising design.

## Resolved

Calls made for this proposal (open to challenge in review):

- **Gate on the major boundary**, full stop — the clean tripwire. `auto` structural moves may
  ship in a minor; anything needing judgment forces a major.
- **Aggregated runbook for v1**: one confirmation for the whole major span, the agent works
  the ordered instruction sections in one pass. Per-boundary (stepped) confirmation is the
  later, rework-free upgrade.
- **Agent-or-manual fallback**: a major never auto-applies its breaking steps; without an
  agent, `UPDATING.md` instructions stand in.
- **Manifest version bumped only after the user confirms success**, so interrupts leave
  `installed` unchanged — cleanly re-runnable for `auto`/content, with the `agent`-step
  `git restore . && git clean -fd` caveat spelled out in the interrupted-migration edge case.
- **Downgrade refused**; unknown/missing version treated conservatively (everything in-span,
  nothing auto across an unknown boundary).
- **Content is never enumerated per version** — one diff to latest; only migration steps are
  version-sequenced.

## Open questions

- **Where the `agent` instruction blocks live**: inline in the migration registry, or in the
  `/update` skill text, or both (registry for the canonical steps, skill for how to drive
  them). Leaning: canonical steps in the registry, choreography in the skill.
- **How `--check` learns `latest`** for the SessionStart line without a network call every
  session — reuse the 24h update-check cache, but confirm that's fresh enough to be useful
  without being noisy.
