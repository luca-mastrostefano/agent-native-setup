# Scaffold an engineering baseline: editorconfig, gitattributes, Dependabot, least-privilege CI, PR template, SECURITY.md

- **Status:** Accepted
- **Date:** 2026-06-02
- **Author:** Luca Mastrostefano

## Context

The wizard scaffolds linters, hooks, CI, and security scanning, but omits several
near-universal, low-cost hygiene files most production repos carry. Each maps to one
of the three pillars. The bar (per `AGENTS.md`'s "small, opinionated set"): cheap,
language-agnostic where possible, and clearly earning its place. Opinionated or
team/type-dependent practices — conventional-commit enforcement, changelog/release
automation, LICENSE choice, CODEOWNERS, coverage thresholds, action SHA-pinning —
are explicitly deferred to `docs/improvements.md`, not defaulted.

## Decision

Add six files, each hung off the appropriate existing toggle, and dogfood them into
this repo.

1. **`.editorconfig`** — with the quality setup, alongside `.gitignore` (universal).
   `root = true`; utf-8, LF, final newline, trim trailing whitespace; indent defaults
   (4 for Python, 2 for YAML/JSON/MD/web, tab for Makefile).
2. **`.gitattributes`** — alongside `.gitignore`. `* text=auto` for line-ending
   normalization (removes the Windows CRLF churn we kept flagging).
3. **`.github/dependabot.yml`** — when CI + GitHub Actions. One ecosystem per selected
   language (`pip`/`npm`/`gomod`/`cargo`) plus `github-actions`, weekly, grouped.
   Keeps deps + Actions fresh (addresses the pin-staleness we hit) and complements the
   vuln scanning. (Dependabot can't update `.pre-commit-config` hooks — backlogged.)
   **Legacy-aware:** for an existing repo, routine version updates are disabled
   (`open-pull-requests-limit: 0`, security-only) so Dependabot doesn't flood a stale
   project with bump PRs on day one — same grandfathering as the CI ratchet; a fresh
   repo gets full version updates, and a comment explains how to opt up.
4. **Least-privilege CI permissions** — add `permissions: { contents: read }` to the
   generated `quality.yml`. (`claude.yml` keeps the write scope it needs.)
5. **`.github/PULL_REQUEST_TEMPLATE.md`** — when CI + GitHub Actions. A short checklist:
   links the RFC, ran the quality gate, change is surgical/traces to the task, verified
   by a test.
6. **`SECURITY.md`** — when security scanning is on. How to report a vulnerability, plus
   a note on the scanning the repo runs.

## Consequences

- New projects carry the hygiene baseline out of the box; all six are cheap and mostly
  language-agnostic.
- Dependabot keeps dependencies and Actions current and complements the vuln scan; it
  can open PR noise — weekly cadence + grouping mitigate.
- `permissions: contents: read` is least-privilege by default; a future workflow that
  needs more must opt in explicitly.
- More generated files means more surface — kept to six that earn their place; Tier-2
  practices stay in `docs/improvements.md`.

## Alternatives considered

- **Default the Tier-2 set too** (commit-message enforcement, changelog automation,
  LICENSE, CODEOWNERS, coverage): rejected — opinionated or team/type-dependent, and
  sprawl. Left opt-in / backlogged.
- **SHA-pin GitHub Actions** for supply-chain safety: real upside, but pins go stale and
  add maintenance; Dependabot-on-actions gets most of the benefit with less friction.
- **`pre-commit.ci`** for hook auto-updates: out of scope (a hosted service); a
  scheduled `pre-commit autoupdate` job could come later.
