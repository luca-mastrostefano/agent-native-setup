# The engine/profile inversion: sensing moves to the engine, one project = one profile

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

And once the default is a normal profile, a second simplification follows.
`extends: "default"` — the compose mechanism — exists only because the default used to be
unforkable engine code; overlaying was the *only* way to build on it. RFC
2026-07-04-profile-extends already decided that building on a **profile** is git's job
(fork, `upstream` remote, merge), not an in-tool mechanism. With the default now a profile,
that decision covers it too: **`extends` has no remaining reason to exist.** One project =
one profile; extension = fork the profile's repo, whoever authored it.

One more problem this fixes is positioning: the name `default` quietly privileges one
opinion. It is the default *for this project's author* — not for a design team, a Go shop, or
anyone else the mission ("help the community converge on useful profiles") is for. A neutral
engine with one well-made, *named* package in the index invites peers; a privileged god-path
does not.

## Decision

**1. This project becomes the engine — a package manager for agent-native setups.** Its
surface: **sense** (fill `env`), **prompt** (a profile's declarative wizard), **resolve**
(path / name / index name / `git+` URL), **gate** (derived safety classification +
content-hash consent), **apply** (sandboxed render, path confinement, `links`, manifest
provenance), **update** (managed refresh, version/hooks/safety-flip/consent re-gates,
migrations), **discover** (community index, search, publish, index-check CI). The engine
ships **no opinionated content**: every file today's generators write moves into the
flagship profile.

**2. `env` is the ecosystem's public API, and it carries *sensed facts only*.** The
fact/choice split becomes strict: **`env` = what the engine observed about the repo**
(`existing_project`, `detected_languages`, `existing_runner`, `os`, presence of key files
such as `README`/`AGENTS.md`/CI config, …); **`answers` = what the user chose** (a profile's
prompts). The contract is versioned and documented (`docs/architecture/profiles.md`); keys
are add-only from this RFC onward; renaming or removing one is a breaking engine change
gated like a breaking scaffold update. **The existing choice-echo keys (`env.has_docs`,
`has_ci`, …, and `env.languages`/`runner`/`adoption`/`ai_tools` insofar as they echo flags
rather than detection) are removed** — they existed so an overlay could read the base's
choices, and with composition gone (Decision 4) they have no reader. This is a breaking
format change made deliberately *now*, while the ecosystem is experimental, has one seed
index entry, and no known external profiles. A profile that needs a fact the engine can't
sense requests a **sensor**, not a code hook — keeping "profiles are data at generation
time" a permanent property, not a stage-D interim. Two rules complete the contract:
**sensing happens at scaffold time and is recorded in the manifest; `update` replays the
recorded observation, never re-senses** — the determinism rule the prompts RFC already set
("re-render against the *same* environment"), without which the regenerate→byte-identical
classification (and §7's parity argument) breaks the first time a repo's detected languages
drift. And the **top-level `languages` context key goes with the echoes** (it mirrors the
chosen — not detected — languages): profiles read `env.detected_languages` (fact) or ask
their own prompt (choice); `example-team` is updated in the same change.

**3. The default becomes the flagship profile: named, described, tagged, listed.** A real
tier-2 profile (working name **`agent-native-baseline`** — final name open) with a
description and tags (`general`, `baseline`, `multi-language`), living under
`profiles/agent-native-baseline/` in this repo **only during extraction (stage A)** and
moving to **its own repo at stage B** — from the moment it is live and forkable, it is a
normal profile repo, and the index entry points there — and **listed in the community index
like any other entry**. Its part toggles (`--no-docs`, `--no-ci`, `--no-agents`, …) were never engine
concepts — they become the profile's **`prompts`** (its templates branch on its *own*
`answers.include_docs`, not on env echoes) — and so do the other choice flags:
`--languages`, `--tools`, `--runner`, `--adopt`. **All of them survive as deprecated engine
aliases mapped onto `--answer`** so existing scripts keep working unchanged. Its per-language
content matrix and toolchain pins are produced by an **author-time build step** in the
profile's own release flow (generate `templates/`, bake `pins.py` values, tag) — the
published artifact stays declarative, inspectable via `profile show`, and hash-consentable.
(One build-step consequence worth naming: CI workflows that must be *toggleable* become
`.j2` files, so their `${{ … }}` needs `{% raw %}` wrapping — the build emits that.)

**4. The format drops `extends`. One project = one profile; extension is a fork.** Every
profile ships its complete setup (what `extends: null` means today); the compose path,
overlay writer, and the two-layer answer/trust/update machinery are removed rather than
generalized. To build "the baseline plus our house files," a team forks the flagship's repo
and adds templates (adding static files to a fork is trivial; the matrix build only matters
if they edit the matrix), taking upstream improvements via `git merge` — exactly the
extension model RFC 2026-07-04-profile-extends already chose for every other profile, now
applied uniformly because the baseline no longer needs a special case. Consequences owned
here rather than inherited:

- **`profile save` changes meaning**: it produces a **standalone snapshot** — the flagship
  rendered for that project's configuration plus the project's delta, baked into one
  complete profile. It loses cross-stack generality (the snapshot is pinned to the
  project's languages/choices); acceptable, because a team's stack is fixed and a general
  profile is what forking the flagship is for.
- **Previously-composed projects degrade defined-ly**: at migration (§7-C) a manifest with
  an overlay block keeps all its files, base-owned provenance moves to the flagship, and
  overlay-owned files become **frozen** (kept, never refreshed, warned once) — the existing
  degraded-profile behavior. The known population of such projects outside this repo's own
  tests and examples is zero; the `example-team` profile is re-authored standalone in the
  same change.
- **RFC bookkeeping**: on acceptance, pointer notes go to *four* documents — profile-extends
  (its "the stack stays `[default, profile]`" phrasing becomes "the stack is one profile";
  its git-native decision is extended, not changed), the scaffolding-profiles umbrella's
  composition sections, **profile-save** (whose decision "extract an `extends: default`
  delta" is redefined by the snapshot model above), and **profile-prompts** (home of the
  removed env echo keys and of the recorded-env determinism rule Decision 2 carries
  forward).

**5. Trust: vendored in-box, identical artifact in the index.** The flagship profile is
**vendored inside the wheel** (package data), so `agent-native-setup -o .` stays offline and
zero-config: the vendored copy has local provenance — installing the tool *is* consenting to
its content, which re-grounds ecosystem-core's decision #6 on something that survives the
inversion (the artifact ships with the release, rather than being trusted for its name).
Once the flagship lives in its own repo (stage B), vendoring becomes a **release-time step**:
the engine's release pins `agent-native-baseline@<tag>`, embeds that artifact in the wheel,
and records its content hash — same trust grounding, now with an explicit, verifiable pin. The
index lists the same artifact by URL for discovery, pinning, and out-of-band updates; fetched
copies flow through the normal classifier + consent gate like any community profile. The
engine **preselects** the flagship for UX (`agent-native-setup -o .` behaves as today) —
"default" disappears as a name and a privilege, and survives only as a selection default.

**6. Two small format/engine additions the parity gate forces now.** Reviewing the
generators against the tier-2 format surfaced exactly two things templates cannot express,
both load-bearing for parity (§7):

- **`links`** — a declarative symlink list (`{"CLAUDE.md": "AGENTS.md"}`), executed by the
  engine: both ends path-confined to the project, in-project relative targets only,
  surfaced by `profile show`. A link may carry a `when` (a Jinja expression, mirroring
  a prompt's) — discovered necessary immediately: the tool symlinks ship per selected
  tool. This replaces the "recreate the symlink via onboarding step"
  workaround, which would otherwise be both a UX regression (the wizard creates the link
  today; an agent would have to) and a permanent parity exception.
- **`@DATE@` in template *paths*** — engine-substituted scaffold date, for the dated
  bootstrap RFC (`docs/rfc/active/<date>-adopt-agent-native-setup.md`) the default writes
  today. Dated artifact names are this ecosystem's own convention; one general token beats
  a permanent carve-out.

**7. Migration: parity-gated, engine paths preserved until proven.** The riskiest surface is
`update`: every existing project's manifest records "tool version X generated these files"
and refreshes through `cli.build`'s generators. Sequencing:

- **A. Parity harness first.** A test renders the flagship profile and the current
  generators against the same configs — **clock pinned** (the dated RFC path), across the
  full matrix (languages × tools × part toggles × existing-repo modes) — and asserts
  **byte-identical trees, symlinks included** (via §6 `links`). Any exception must be
  enumerated *in the harness with a reason*, not discovered later; as of this writing the
  expected exception list is **empty**. The generators remain the source of truth until
  this gate is green and stays green in CI.
- **B. Flip scaffold; remove `extends`; rework `save`.** New scaffolds resolve the vendored
  flagship through the one profile pipeline (`resolve → consent → gather_answers → apply`);
  the compose path and the `extends` field go in the same release (`profile validate`
  rejects the field with a message pointing at the fork recipe) — which forces `profile
  save`'s snapshot rework into **this same release**, since today's `save` emits
  `extends: "default"` and must never produce output its own validator rejects. **The
  flagship also moves to its own repo in this release** (the engine embeds it hash-pinned at
  release time — Decision 5), so it is cleanly forkable from the moment anyone scaffolds
  from it; parity CI switches from same-repo to pinned-tag comparison, cheap now that the
  flagship is parity-stable rather than under extraction. The generators become dead weight
  but stay shipped.
- **C. Migrate update — the first externally-visible commitment.** A manifest migration
  rewrites old provenance ("engine version X") to flagship-profile provenance
  (`agent-native-baseline@Y, vendored`) — whose real substance is a **config→answers
  translation table**: every recorded config key (`include_docs/ci/agents/quality/security`,
  `languages`, `runner`, `adoption`, `ai_tools`) maps to a flagship answer, and the recorded
  env snapshot is carried over for replay (Decision 2), so re-rendering stays byte-faithful
  to what was scaffolded. Previously-composed manifests degrade per Decision 4. `update` re-resolves through the profile path. Old manifests keep updating
  throughout — parity (A) guarantees the vendored profile impersonates the old regenerate
  path. **C is only semi-reversible**: it mutates user manifests on their machines, an
  older engine won't read the new provenance, and undoing it would need a counter-migration
  that only reaches projects that update again. It ships with a migration entry (the
  existing machinery), a legible too-old-engine error, and only after A has soaked in CI
  for a release.
- **D. Delete the generators.** Only after A–C have shipped and a release cycle of real
  updates has passed. The point of full commitment; A–B remain cheaply reversible, C
  reversible only forward (counter-migration).

## Consequences

**Newly possible**
- **The engine is structurally neutral**: a community profile and the flagship run the same
  pipeline, same gates, same discovery. "Second-class ecosystem" ends as an architecture
  fact, not a docs claim.
- **The whole system gets simpler**: no compose path, no overlay writer, no two-layer
  update/trust/answer machinery, no base/child version axes — one project, one profile, one
  update stream. The engine model becomes exactly a package manager's.
- The flagship gains what every profile has: `profile show` inspectability, index discovery,
  its own version stream — with an honest asterisk: **content-release decoupling is partial.**
  Index-fetched adopters can pick up a flagship fix without an engine release; the vendored
  copy (the `-o .` default and every migrated project) still rides engine releases. The
  escape hatch (point `--profile` at the index URL) exists but is opt-in.
- Community profiles get a growing, documented sensor API instead of waiting on a code-plugin
  trust model that was never going to be cheap to open.

**Harder / costs**
- **Thin-overlay authoring goes away.** Today a team can share a 3-file `extends: default`
  delta; tomorrow the equivalent is a fork of the flagship (heavier: a whole repo, upstream
  merges) or a `save` snapshot (lighter, but stack-pinned). This is the real price of
  uniformity, paid deliberately: the overlay model would otherwise force the engine to keep
  two-layer trust/update/answer semantics forever for one special-cased base.
- **The migration is the project's largest change** — every generator, its tests, the
  compose machinery, and the update path move, gain a shim, or are removed. The parity
  harness bounds the risk but is itself real work (it already surfaced the dated RFC path
  and the symlink — §6).
- **`env` becomes a public contract** with breaking-change discipline: adding sensors is an
  engine release; changing one is an ecosystem break. The one deliberate break (dropping
  the choice-echo keys) happens *in* this RFC, while it is provably cheap.
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
- **Composition (`extends`), entirely.** Anyone who wanted overlays gets forks. If real
  demand for in-tool thin overlays emerges later, it can return as its own RFC against a
  then-neutral engine — nothing in this design forecloses it; we just refuse to carry its
  machinery speculatively.
- **Ecosystem-core's §7 staged plan (and only that, plus the §6 re-grounding).** Its
  stages A/B land here in stronger form; C's "module registry" becomes the flagship's
  author-time build; D's code plugins are not needed and stay out of scope. Ecosystem-core's
  §§1–5 — the derived classifier, allowlist + fail-closed, lifecycle re-gates,
  persistent-vs-one-shot consent principle — are **not** superseded: they are decided
  foundation, already realized by the Active safety and fetch RFCs. On acceptance,
  2026-07-03-ecosystem-core moves to `superseded/` with a note saying exactly this.

## Alternatives considered

- **Keep `extends: "default"` as a thin-overlay mechanism** (the pre-review shape of this
  RFC). Rejected: it special-cases one base forever and drags permanent machinery behind it
  — two answer scopes, base+overlay manifests, an env bridge echoing one profile's choices
  to another, two update streams — all to avoid a fork. It also contradicts the
  profile-extends decision the moment the base is a normal profile: we would be telling the
  community "extension is git-native" while keeping a private overlay lane for ourselves.
  The ecosystem's youth makes this the last cheap moment to remove it.
- **Stage-D code plugins** (ecosystem-core's original path): make profiles capable of
  generation-time code, then rewrite the default as plugin #1. Rejected: it opens the
  arbitrary-code trust door for *everyone* to solve a problem only *our* profile had — and
  the env-detachment insight shows even our profile doesn't have it.
- **Status quo** (default stays privileged generator code). Rejected: the default remains
  the capable one and every community profile remains structurally second-class — the
  opposite of the mission.
- **Partial extraction** (static files into a profile, dynamic parts stay generators).
  Rejected: one setup split across two mechanisms with two update paths — worse cohesion
  than either endpoint.
- **Flagship in its own repo from day one (stage A).** Rejected for the extraction window
  only: during A the flagship is being *derived from* the generators, and every parity fix
  touches a generator and a template together — cross-repo, that is two PRs and a pin bump
  per iteration. The split lands at **B** instead (§7-B), the first moment the flagship is
  live, adoptable, and therefore worth forking; the monorepo-fork awkwardness the
  profile-extends RFC warned about is confined to A, when the extender population is zero.
- **Flagship in this repo until D** (the pre-amendment plan). Rejected once the constraint
  was challenged: it kept the day-one extension norm pointed at a monorepo `#subdir=` for
  two whole stages after adoption began, for no gain beyond deferring the release-time
  pin-and-embed step.
- **Onboarding-step symlinks instead of `links`.** Rejected by the parity gate itself: it
  bakes a permanent parity exception *and* a UX regression into the migration's
  load-bearing safety argument.

## Open questions

- **The flagship's name** — `agent-native-baseline` is the working proposal; needs a decision
  before B (it appears in manifests, the index, and docs).
- **`env` versioning shape** — a single `env.contract_version` key vs. documenting sensor
  availability per engine version. Decide during A.
- **Flag-alias sunset** — how long the deprecated `--no-*` aliases live after D, and what a
  baseline-specific flag means when `--profile` selects a different profile (proposal:
  warn-and-ignore, revisit at D).
- **Classifier treatment of `links`** — a link is not inert (it redirects reads/writes);
  proposal: any `links` entry ⇒ not `safe` (fail-closed), revisit if it proves too blunt.
- **`save` snapshot mechanics** — how a snapshot pins the flagship version it embedded, so
  a saved profile can still say what it was derived from (provenance in its README vs. a
  manifest field). Must be decided by **B** (save's rework ships there — §7-B).
