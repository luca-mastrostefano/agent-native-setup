# Improvements backlog

Deferred ideas and known gaps — things not yet decided (so not an RFC) and not
current state (so not `architecture/`). Keep entries concrete; promote anything
that needs a real decision into an RFC in `docs/rfc/current/`.

## Known gaps

- **Aggregator as an opt-in CI layer** — a `--megalinter`-style flag adding MegaLinter
  in CI, scoped to the gaps our per-language entries don't cover (non-source formats,
  copy-paste, spelling), configured to defer to our tools. Decided against by default
  (keeps the setup minimal); revisit when broad coverage is actually wanted.
- **CSS / stylelint entry** — parallel to the `html` entry for web projects; `node`
  covers JS/TS but nothing lints CSS.
- **Prettier-for-HTML formatting** — markup formatting in the `html` entry; deferred
  (overlaps the `node` entry's Prettier, lower value than the link/resource gate).
- **lychee on Windows / locked-down networks** — the `html` link check self-downloads
  its binary via curl on first run; document the `lychee-docker` / `lychee-system`
  hook fallbacks for environments without curl.
- **Type-checking in CI** — `mypy`/`tsc` run via pre-commit and `task typecheck`, not
  in the generated CI job (mypy in CI needs a project install). Add once the friction
  is worth it.
- **Tests in the existing-repo (ratchet) CI** — greenfield CI runs the suite; the
  changed-files ratchet job does not yet.
- **Dependency-scan tuning** — the scaffolded vuln scans are sensible defaults; some
  (npm audit needs a lockfile, pip-audit a resolvable env) may need per-project tuning.
- **Refresh the remaining CI action pins** — `actions/*` are on the Node-24 majors, but
  `golangci-lint-action@v6` (bumping to v8 forces a golangci-lint **v2 config** migration
  of `GOLANGCI_CONFIG`), and the third-party actions (`gitleaks-action`, `lychee-action`,
  `rustsec/audit-check`, `claude-code-action`, `govulncheck-action`) should get a periodic
  Node-24 / SHA-pin audit. Dependabot's `github-actions` ecosystem will surface these.
