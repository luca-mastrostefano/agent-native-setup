# Improvements backlog

Deferred ideas and known gaps — things not yet decided (so not an RFC) and not
current state (so not `architecture/`). Keep entries concrete; promote anything
that needs a real decision into an RFC in `docs/rfc/current/`.

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
