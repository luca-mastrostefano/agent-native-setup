# Harden the generated quality gate: secrets + dependency scanning, tests in CI

- **Status:** Active
- **Date:** 2026-06-01
- **Author:** Luca Mastrostefano

## Context

The generated quality setup lints and formats, but has two gaps versus what a real
project wants:

- **No security signal** — nothing scans for committed secrets or vulnerable
  dependencies. None of the `Language` entries cover it.
- **CI doesn't run the tests** — the generated `quality.yml` runs linters only, even
  though this repo's own CI runs `pytest` (commit `0f5ddda`). Generated projects
  under-check relative to what we practice.

Same constraint as the legacy-aware work: an existing repo must not get a red gate
on day one for *pre-existing* vulns or secrets.

## Decision

1. **Secrets scanning (gitleaks), language-agnostic.** A gitleaks pre-commit hook
   (`gitleaks v8.24.2`) plus a gitleaks CI step. Catches committed credentials
   regardless of stack.
2. **Per-language dependency/vuln scanning** via each tool's self-setup mechanism —
   new `Language.ci_security_steps`: `pypa/gh-action-pip-audit` (python),
   `npm audit --audit-level=high` (node), `golang/govulncheck-action` (go),
   `rustsec/audit-check@v2` (rust).
3. **A dedicated `checks` CI job** runs the per-language security steps + gitleaks.
   On an **existing** repo the job is `continue-on-error: true` — findings are
   reported, not blocking, so legacy vulns/secrets don't wall off the first PR
   (consistent with the changed-files ratchet). Greenfield: blocking.
4. **Tests in greenfield CI.** Each language's `ci_steps` now runs its test command
   (python installs the package + `pytest`; `npm test --if-present`; `go test ./...`;
   `cargo test`), matching this repo's own CI. The changed-files ratchet job stays
   lint-only (tests there are backlogged in `docs/improvements.md`).

Pins refreshed in the same pass (`ruff-pre-commit`, `mirrors-mypy`,
`pre-commit-hooks`) since they were well behind.

## Consequences

- New projects get secrets + dependency scanning and a test gate out of the box;
  existing repos get them as reports, not blockers, until cleaned up.
- `gitleaks-action` is free for public repos; private org repos need a
  `GITLEAKS_LICENSE` secret (documented in generated CI by the action's own error).
- The vuln scanners are sensible defaults; some need per-project tuning (npm audit
  wants a lockfile, pip-audit a resolvable env) — logged in `docs/improvements.md`.
- More CI minutes per run — acceptable for the signal.

## Alternatives considered

- **Vuln scans in pre-commit:** rejected — they need network and are slow; pre-commit
  stays fast/offline. CI is the right home.
- **Block on existing-repo findings:** rejected — reintroduces the day-one blast;
  report-not-block matches the legacy-aware design.
- **A combined aggregator (MegaLinter) for security too:** deferred (see
  `docs/improvements.md`) — heavier and broader than the targeted signal wanted now.
