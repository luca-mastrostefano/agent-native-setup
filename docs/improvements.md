# Improvements backlog

Deferred ideas and known gaps — things not yet decided (so not an RFC) and not
current state (so not `architecture/`). Keep entries concrete; promote anything
that needs a real decision into an RFC in `docs/rfc/proposed/`.

**Start each entry with the short commit you're at (`git rev-parse --short HEAD`) and today's date, separated by ` · `, in square brackets**, so every idea is anchored to both the code it refers to and when it was raised.

`task improvement -- "<idea>"` appends a correctly-stamped entry here.

## Known gaps

- **Aggregator as an opt-in CI layer** — a `--megalinter`-style flag adding MegaLinter
  in CI, scoped to the gaps our per-language entries don't cover (non-source formats,
  copy-paste, spelling), configured to defer to our tools. Decided against by default
  (keeps the setup minimal); revisit when broad coverage is actually wanted.
- **CSS / stylelint entry** — parallel to the `html` entry for web projects; `node`
  covers JS/TS but nothing lints CSS.
- **Prettier-for-HTML formatting** — markup formatting in the `html` entry; deferred
  (overlaps the `node` entry's Prettier, lower value than the link/resource gate).
- **mypy in CI** — `mypy` runs via pre-commit and the `typecheck` target, not in the
  generated CI job (mypy in CI needs a project install). Add once the friction is worth
  it. (`tsc` is now wired into node's CI, guarded for the no-TypeScript-yet case.)
- **Tests in the existing-repo (ratchet) CI** — greenfield CI runs the suite; the
  changed-files ratchet job does not yet.
- **Dependency-scan tuning** — the scaffolded vuln scans are sensible defaults; some
  (npm audit needs a lockfile, pip-audit a resolvable env) may need per-project tuning.
- **Refresh the remaining CI action pins** — `actions/*` and `gitleaks-action@v3` are on
  Node-24, but `golangci-lint-action@v6` (bumping to v8 forces a golangci-lint **v2 config**
  migration of `GOLANGCI_CONFIG`; that migration also unlocks `GO_VERSION` ≥ 1.25 in
  `pins.py` — golangci-lint v1 tops out at Go 1.24), and the other third-party actions
  (`lychee-action`, `rustsec/audit-check`, `govulncheck-action`) should get a periodic
  Node-24 / SHA-pin audit. Dependabot's `github-actions` ecosystem will surface these.
- [b9ede32] **Automate pin freshness** — every version the wizard stamps into generated
  output now lives in `src/agent_native_setup/pins.py`, but refreshing it is still a
  manual sweep (check each upstream's releases, e.g. via the GitHub/npm APIs or
  endoflife.date). A `task`/CI check that diffs `PINS` against latest upstream releases
  would catch rot (like Node 20 going EOL) without anyone remembering to look.
- [127b11c · 2026-06-16] **Opt-in, git-gated `release` task** — scaffolded projects get a
  static `version` and no release path, so an agent improvises `git tag`/`gh release` each
  time. Offer (a prompt, default off; only when git is detected or created) a `release`
  task that cuts a tag and optionally a GitHub release (`gh release create
  --generate-notes`), degrading to tag-only without a remote/`gh`. Not a git hook — a
  deliberate, explicit task. Tier 1 (cut the tag) is language-agnostic; the bigger Tier 2
  — making the build *derive* its version from the tag (hatch-vcs for Python, `npm
  version`, tags for Go, cargo-release for Rust) to kill version-drift — is per-`Language`
  registry work, deferred. Keep it policy-light (no enforced semver/changelog). RFC-worthy.
- [127b11c · 2026-06-16] **`agent-native-setup update` command** — the provenance manifest
  (`.agent-native-setup.json`: version + resolved config + per-file fingerprint, written by
  `manifest.py`) now lands in every scaffold, but nothing consumes it yet. Build the updater:
  read the manifest, regenerate managed files from the current templates using the recorded
  config, overwrite the ones whose on-disk hash still matches the manifest (pristine), drop a
  `*.ans-new` sidecar for the ones that don't (user-edited), add newly-managed files, then
  rewrite the manifest. Additive only — never moves or deletes directories. Require a clean git
  tree so the update is a reviewable diff. **Settled-baseline problem:** the manifest captures
  the *scaffold-time* state, but onboarding then mutates recorded files as part of setup — it
  strips the first-run banner from `AGENTS.md` (transient files like ONBOARDING.md and the
  `/onboard` command are already excluded from the manifest, so they're handled), and pre-commit
  formatters (prettier/eslint/ruff) can rewrite generated files on first commit. So the baseline
  should be **re-captured once setup settles** (an end-of-onboarding `update --refresh-baseline`
  / `manifest` step), or the updater should normalize through the project's formatter and ignore
  the banner block before comparing — else those files all read as edited. **Legacy repos** get a
  partial baseline by design (only files the wizard actually wrote; a merged `AGENTS.md` always
  reads as edited until markers exist). RFC-worthy (locks the manifest format + the update policy).
- [127b11c · 2026-06-16] **Managed-block markers + a file taxonomy for updates** — whole-file
  regeneration only safely covers files the user doesn't co-own (`.claude/agents|commands/*`,
  `tools/checks/*`, editorconfig, dependabot, PR template). The mixed files — `AGENTS.md`
  (template boilerplate + the user's navigation/command surface) and `.pre-commit-config.yaml`
  (template blocks + user-added hooks) — need managed-block markers (the
  `<!-- agent-native-setup:… -->` pattern the first-run banner already uses) so the updater can
  refresh just the marked regions. Tradeoff to settle: markers in `AGENTS.md` (refresh boilerplate
  in place) vs. treating it as human-owned/advisory-only after creation. Human-owned files (README,
  docs, src, runner, pyproject/package.json) and one-time files (ONBOARDING) stay untouched. Add
  the markers to the generators sooner rather than later — retrofitting them reintroduces the
  no-provenance problem the manifest just solved.
- [000de97 · 2026-06-17] **This repo can't yet dogfood the updater** — every *generated* project
  now ships `.agent-native-setup.json`, but the scaffolder itself doesn't: it's hand-evolved, not
  wizard-generated, so a manifest's hashes would all read as "edited." When the `update` command
  lands we'll want to exercise it here too, which means deciding whether to adopt-baseline a
  manifest for this repo (record the current state as the baseline) or leave it un-managed. Tied
  to this: the manifest shipped under an `RFC-Not-Needed` waiver because it's greenfield/reversible
  (only us); lock the format with an RFC before any external user adopts it.
- [77af693 · 2026-06-22] **Scaffolding config profiles** — *promoted to RFC
  `2026-06-23-scaffolding-profiles` and largely shipped: `--profile` composition, `profile
  init`/`list`/`validate`/`save`/`add`, standalone `extends: null`, versioned update propagation
  with trust gate + version nudge, declarative `prompts`/`when`/`env` + startup contributions, the
  safety mechanism (derived classifier, sandboxed rendering, path confinement), **git-URL fetch
  on content-hash trust** (`--allow-code`, `trust`/`untrust`), and **community discovery** (a curated
  `contributions/index.json`, `profile search`/`list --community`/`publish`). Remaining:
  `profile show` and **code-plugin** profiles (the ecosystem-core stage-D one-way door) — see the
  `ecosystem-core` RFC, not here.*
- 4714a97 (2026-07-06) dry-run doesn't preview the contract fold: staging can't reproduce live target files, so a brownfield AGENTS.md shows 'would skip' though a real run folds it. Fix: stage copies of fold-relevant files (or simulate the fold read-only) so the preview matches. (review of #55)
- feat/remove-extends (2026-07-06) `profile save` sources its transient-exclusion set from the baseline pin only (RFC 2026-07-08 moved it from the vendored copy to `baseline-pin.json`) — a project scaffolded from a third-party profile that declares its own `transient` files would still capture those first-run artifacts into the snapshot. Fix: record the applied profile's `transient` list in the manifest (like `session_start`) and read it back in save. (review of B2)
- e763b77 (2026-07-07) surface profile licenses in discovery: a community profile's files land in the adopter's repo under the profile's own license, so `profile show` and the index entries should carry a `license` field (and `publish` should infer it from LICENSE) — an AGPL profile deserves informed adoption the way an unsafe one deserves consent.
- cb9611e (2026-07-09) prompt `choices` render as bare values and there's no help-text field, so a profile's whole wizard UI is the `message` string — authors cram tool links and "where to find this ID" hints into it (the engine's own `_interactive` sidesteps this with `questionary.Choice(title, value=)` labels and a dim `_note()` line, which profiles can't do). Fix: let a choice be `{"value", "label", "description"}` and give `Prompt` an optional `help` shown above the question. Public-contract change to `profile.json` → RFC first.
