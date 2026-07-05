# The engine/profile inversion: sensing moves to the engine, the default becomes a named profile

- **Status:** Proposed
- **Date:** 2026-07-05
- **Author:** Luca Mastrostefano
- [ ] Implemented

## Context

RFC 2026-07-03-ecosystem-core committed to a direction — "the default becomes one profile" —
but its path ran through stage D: **code-plugin profiles**, a one-way trust door (arbitrary
code running inside the wizard at scaffold and update time) that every prior RFC has
deliberately kept shut. The assumption was that the default *needs* generation-time code,
because it runs logic: language detection, runner detection, per-language config generation,
adoption strategies, pins.

That assumption is wrong, and seeing why makes the inversion cheap. The default's logic
splits cleanly in two:

- **Sensing** — *discovering facts about the target repo* (languages present, existing
  runner, key files, OS). This is engine work, and the engine already does it: profiles
  consume the results through the `env` namespace today.
- **Branching on facts** — *choosing what to ship given those facts*. Sandboxed Jinja over
  `env` already expresses this; it is what community profiles do now.

If the engine owns **all** sensing and the flagship setup only branches, the flagship fits in
the **existing tier-2 format** — a code-*shipping* profile (its CI workflows, hooks, and
Makefiles are code that runs in the scaffolded project, consented via the existing
`--allow-code`/trust machinery) with **zero generation-time code**. Stage D is not needed to
dethrone the default. The remaining objection — "the default as templates would be an
unmaintainable Jinja blob" — dissolves once build complexity moves to the profile's own
**release process**: author-time code generating a declarative artifact, not apply-time code.

One more problem this fixes is positioning: the name `default` quietly privileges one
opinion. It is the default *for this project's author* — not for a design team, a Go shop, or
anyone else the mission ("help the community converge on useful profiles") is for. A neutral
engine with one well-made, *named* package in the index invites peers; a privileged god-path
does not.

## Decision

**1. This project becomes the engine — a package manager for agent-native setups.** Its
surface: **sense** (fill `env`), **resolve** (path / name / index name / `git+` URL),
**compose** (overlay or standalone), **gate** (derived safety classification + content-hash
consent), **apply** (sandboxed render, path confinement, manifest provenance), **update**
(managed refresh, version/hooks/safety-flip/consent re-gates, migrations), **discover**
(community index, search, publish, index-check CI). The engine ships **no opinionated
content**: every file today's generators write moves into the flagship profile.

**2. The `env` sensor contract is the ecosystem's public API — and it survives the
inversion whole.** The engine's job is to make profiles expressive *without* letting them
run generation-time code, so the sensor set grows deliberately: existing keys
(`existing_project`, `languages`, `detected_languages`, `existing_runner`, `runner`,
`adoption`, `ai_tools`, the `has_*` toggles) plus what the inversion and community profiles
concretely need (e.g. `os`, presence of key files such as `README`/`AGENTS.md`/CI config).
The contract is **versioned and documented** (`docs/architecture/profiles.md`): keys are
add-only; renaming or removing one is a breaking engine change gated exactly like a breaking
scaffold update. In particular the **`has_*` keys do not die when the part toggles move into
the flagship's prompts (Decision 3): the engine bridges the baseline's resolved part answers
into `env.has_*` when the baseline participates, and fills them from the flag aliases (§3)
otherwise** — the layering stays "engine fills env, profiles read env"; the engine merely
gains one more source (the baseline's answers) for facts it already owned. A profile that
needs a fact the engine can't sense requests a **sensor**, not a code hook — keeping
"profiles are data at generation time" a permanent property, not a stage-D interim.

**3. The default becomes the flagship profile: named, described, tagged, listed.** A real
tier-2 profile (working name **`agent-native-baseline`** — final name open) with a
description and tags (`general`, `baseline`, `multi-language`), living under
`profiles/agent-native-baseline/` in this repo initially (fetchable via `#subdir=`, movable
to its own repo later without a format change) and **listed in the community index like any
other entry**. Its part toggles (`--no-docs`, `--no-ci`, `--no-agents`, …) were never engine
concepts — they become the profile's **`prompts`**; the existing `--no-*` flags survive as
deprecated engine aliases mapped onto `--answer` so scripts keep working. Its per-language
content matrix and toolchain pins are produced by an **author-time build step** in the
profile's own release flow (generate `templates/`, bake `pins.py` values, tag) — the
published artifact stays declarative, inspectable via `profile show`, and hash-consentable.
(One build-step consequence worth naming: CI workflows that must be *toggleable* become
`.j2` files, so their `${{ … }}` needs `{% raw %}` wrapping — the build emits that.)

**4. Composition survives with the base swapped: `extends: "default"` comes to mean "the
engine's baseline profile."** The `extends` grammar does not change (`"default" | null` —
RFC 2026-07-04-profile-extends' no-chains decision stands; the stack stays exactly two
layers). What changes is what renders the base: the **vendored** flagship applied through
the profile pipeline instead of the generators. Rules, so this is decided rather than
inherited:

- **Composition always uses the vendored flagship** — never a fetched copy, even if the
  index has a newer one — so a composed scaffold is deterministic per engine release and
  the base adds **no consent surface** (vendored = local provenance = trusted, exactly as
  installing the tool consents to it today).
- **Two answer scopes.** The baseline's prompts (the part toggles) are asked/flag-aliased
  exactly like today's base wizard questions; an overlay profile's `answers.<name>` refers
  to **its own** prompts only, as now. No merge, no collision surface; overlays read the
  baseline's choices through `env.has_*` (Decision 2), as now.
- **Composed manifests record both layers** — the overlay block as today, plus a `base`
  record (`agent-native-baseline@<version>, vendored`) — so `update` refreshes base-owned
  files through the same profile path (§5-C).

**5. Trust: vendored in-box, identical artifact in the index.** The flagship profile is
**vendored inside the wheel** (package data), so `agent-native-setup -o .` stays offline and
zero-config: the vendored copy has local provenance — installing the tool *is* consenting to
its content, which re-grounds ecosystem-core's decision #6 on something that survives the
inversion (the artifact ships with the release, rather than being trusted for its name). The
index lists the same artifact by URL for discovery, pinning, and out-of-band updates; fetched
copies flow through the normal classifier + consent gate like any community profile. The
engine **preselects** the flagship for UX (`agent-native-setup -o .` behaves as today) —
"default" disappears as a name and a privilege, and survives only as a selection default.

**6. Two small format/engine additions the parity gate forces now.** Reviewing the
generators against the tier-2 format surfaced exactly two things templates cannot express,
both load-bearing for parity (§7):

- **`links`** — a declarative symlink list (`{"CLAUDE.md": "AGENTS.md"}`), executed by the
  engine: both ends path-confined to the project, in-project relative targets only,
  surfaced by `profile show`. This replaces the "recreate the symlink via onboarding step"
  workaround, which would otherwise be both a UX regression (the wizard creates the link
  today; an agent would have to) and a permanent parity exception. Promoted from
  "deferred" precisely because the flagship exercises it on day one.
- **`@DATE@` in template *paths*** — engine-substituted scaffold date, for the dated
  bootstrap RFC (`docs/rfc/active/<date>-adopt-agent-native-setup.md`) the default writes
  today. Dated artifact names are this ecosystem's own convention; one general token beats
  a permanent carve-out.

**7. Migration: parity-gated, engine paths preserved until proven.** The riskiest surface is
`update`: every existing project's manifest records "tool version X generated these files"
and refreshes through `cli.build`'s generators. Sequencing:

- **A. Parity harness first.** A test renders the flagship profile and the current
  generators against the same configs — **clock pinned** (the dated RFC path), across the
  full matrix (languages × tools × part toggles × existing-repo modes × composed overlay) —
  and asserts **byte-identical trees, symlinks included** (via §6 `links`). Any exception
  must be enumerated *in the harness with a reason*, not discovered later; as of this
  writing the expected exception list is **empty**. The generators remain the source of
  truth until this gate is green and stays green in CI.
- **B. Flip scaffold.** New scaffolds (plain and composed) resolve the vendored flagship
  through the one profile pipeline (`resolve → consent → gather_answers → apply`). The
  generators become dead weight but stay shipped.
- **C. Migrate update — the first externally-visible commitment.** A manifest migration
  rewrites old provenance ("engine version X") to flagship-profile provenance
  (`agent-native-baseline@Y, vendored`; composed projects gain the `base` record of §4);
  `update` re-resolves through the profile path. Old manifests keep updating throughout —
  parity (A) guarantees the vendored profile impersonates the old regenerate path. **C is
  only semi-reversible**: it mutates user manifests on their machines, an older engine
  won't read the new provenance, and undoing it would need a counter-migration that only
  reaches projects that update again. It ships with a migration entry (the existing
  machinery), a legible too-old-engine error, and only after A has soaked in CI for a
  release.
- **D. Delete the generators.** Only after A–C have shipped and a release cycle of real
  updates has passed. The point of full commitment; A–B remain cheaply reversible, C
  reversible only forward (counter-migration).

## Consequences

**Newly possible**
- **The engine is structurally neutral**: a community profile and the flagship run the same
  pipeline, same gates, same discovery. "Second-class ecosystem" ends as an architecture
  fact, not a docs claim.
- The flagship gains what every profile has: `profile show` inspectability, index discovery,
  its own version stream — with an honest asterisk: **content-release decoupling is partial.**
  Index-fetched adopters can pick up a flagship fix without an engine release; the vendored
  copy (the `-o .` default and every migrated project) still rides engine releases. The
  escape hatch (point `--profile` at the index URL) exists but is opt-in.
- Community profiles get a growing, documented sensor API instead of waiting on a code-plugin
  trust model that was never going to be cheap to open.

**Harder / costs**
- **The migration is the project's largest change** — every generator, its tests, and the
  update path move or gain a compatibility shim. The parity harness bounds the risk but is
  itself real work, and byte-parity across the config matrix will surface every hidden
  generator behavior (it already surfaced two: the dated RFC path and the symlink — §6).
- **`env` becomes a public contract** with breaking-change discipline: adding sensors is an
  engine release; changing one is an ecosystem break. The engine inherits a stewardship
  burden it didn't have when `env` served one in-house consumer — including keeping the
  `has_*` bridge (Decision 2) semantically stable while its source changes.
- **The flagship needs its own build/release tooling** (matrix → templates, pin baking,
  `{% raw %}` emission, tagging) — new machinery, though it runs at author time where a bug
  is a bad release, not a compromised user machine.
- **Interactive UX must not regress**: part toggles as prompts must feel like today's wizard
  (same questions, same defaults), and the `--no-*` flag aliases must keep scripts working.
- **Two format additions** (`links`, `@DATE@` paths) — small and general, but format surface
  is forever; both are pulled in only because the flagship exercises them on day one.

**What we give up**
- Generation-time flexibility for our own content: the flagship can only use facts every
  profile can use. Deliberately — it forces sensors to be general instead of private, and
  it's the property that keeps the trust story simple forever.
- **Ecosystem-core's §7 staged plan (and only that, plus the §6 re-grounding).** Its
  stages A/B land here in stronger form; C's "module registry" becomes the flagship's
  author-time build; D's code plugins are not needed and stay out of scope (a future need
  for generation-time code gets its own RFC against a then-neutral engine). Ecosystem-core's
  §§1–5 — the derived classifier, allowlist + fail-closed, lifecycle re-gates,
  persistent-vs-one-shot consent principle — are **not** superseded: they are decided
  foundation, already realized by the Active safety and fetch RFCs. On acceptance,
  2026-07-03-ecosystem-core moves to `superseded/` with a note saying exactly this, so the
  trust decisions keep a clear home in the trail.

## Alternatives considered

- **Stage-D code plugins** (ecosystem-core's original path): make profiles capable of
  generation-time code, then rewrite the default as plugin #1. Rejected: it opens the
  arbitrary-code trust door for *everyone* to solve a problem only *our* profile had — and
  the env-detachment insight shows even our profile doesn't have it.
- **Status quo** (default stays privileged generator code). Rejected: the default remains
  the capable one and every community profile remains structurally second-class — the
  opposite of the mission. It also keeps content fixes coupled to engine releases for
  everyone, not just vendored-path users.
- **Partial extraction** (static files into a profile, dynamic parts stay generators).
  Rejected: one setup split across two mechanisms with two update paths — worse cohesion
  than either endpoint.
- **Compose against a *fetched* flagship** (newest index version as base). Rejected:
  non-deterministic scaffolds per network state, and it would add a consent surface to
  every composed run. Vendored-only composition keeps base identity pinned to the engine
  release.
- **Flagship in its own repo from day one.** Deferred, not rejected: `#subdir=` fetch makes
  the in-repo start free and keeps the parity harness trivially in one CI; moving out later
  is a URL change. Starting separate would complicate vendoring and parity for no near-term
  gain.
- **Onboarding-step symlinks instead of `links`** (the pre-review draft's v1 plan).
  Rejected by the parity gate itself: it bakes a permanent parity exception *and* a UX
  regression into the migration's load-bearing safety argument. A confined, declarative
  `links` field is less total machinery than a permanent documented divergence.

## Open questions

- **The flagship's name** — `agent-native-baseline` is the working proposal; needs a decision
  before B (it appears in manifests, the index, and docs).
- **`env` versioning shape** — a single `env.contract_version` key vs. documenting sensor
  availability per engine version. Decide during A.
- **Flag-alias sunset** — how long the deprecated `--no-*` aliases live after D, and whether
  `--profile <other> --no-docs` (a baseline toggle aimed at a non-baseline profile) warns or
  errors. Proposal: warn-and-ignore, revisit at D.
- **Classifier treatment of `links`** — a link is not inert (it redirects reads/writes);
  proposal: any `links` entry ⇒ not `safe` (fail-closed), revisit if it proves too blunt
  for legitimate declarative profiles.
