# Add an `html` language entry: markup linting + offline link/resource checking

- **Status:** Active
- **Date:** 2026-06-01
- **Author:** Luca Mastrostefano

## Context

The wizard scaffolds per-language tooling through the `Language` registry
(`python`/`node`/`go`/`rust`); HTML is not covered. A common and costly failure —
especially with AI agents — is restructuring a page (moving CSS/JS/images) without
updating the `<link href>`/`<script src>`/`<img src>` that point at them, leaving
dangling resource references. Markup linters do **not** catch this.

Two categories of tool, doing different jobs:

- **Markup linters** (HTMLHint, html-validate, W3C vnu) check well-formedness and
  quality, but never whether a referenced file exists.
- **Link/resource checkers** (lychee, htmltest, html-proofer) resolve `href`/`src`
  and `#fragments` against the filesystem — this is the part that catches the bug.

A hard distribution constraint shapes the choice: the wizard ships only *config*,
so any tool must install itself with no manual "download a binary onto PATH" step.
pre-commit has **no built-in prebuilt-binary fetcher** (open upstream request
[#1453]), so the only self-installing routes are: a language backend pre-commit
bootstraps (node/python/ruby), a Docker image, or a tool whose own hook downloads
its binary.

## Decision

Add an `html` `Language` entry providing **HTMLHint** (markup) + **lychee**
(link/resource), both self-installing, plus a CI step.

- **HTMLHint** via the `Lucas-C/pre-commit-hooks-nodejs` hook (`id: htmlhint`).
  pre-commit's node backend fetches Node *and* htmlhint into an isolated env — no
  system Node, no manual setup. Ship a minimal `.htmlhintrc`.
- **lychee** via the official `lycheeverse/lychee` pre-commit hook (`id: lychee`),
  run with `--offline` so it only verifies that local files and `#fragments`
  exist. Its wrapper script downloads the prebuilt binary on first run
  (`cargo-binstall` — prebuilt, not compiled; no Rust toolchain, no Docker), then
  caches it. This is the gate that catches moved-resource bugs.
- **CI**: add `lycheeverse/lychee-action` (zero-install) plus an htmlhint step to
  the entry's `ci_steps`. CI is the reliable backstop — local hooks can be skipped
  with `--no-verify`, but CI always runs, which matters most for agent changes. The
  entry also defines `ci_ratchet_steps` (changed-files-only htmlhint + lychee) so it
  honors the legacy-aware setup from `2026-06-01-legacy-aware-quality-setup.md`.
- Detect on `.html`/`.htm`; `quality_commands` lint = `npx htmlhint .`. Name the
  entry `html` (file-type scoped; `node` already covers JS/TS).

External-repo hooks pinned to release tags, exactly like the `python` entry's
ruff/mypy hooks.

## Consequences

- A new web project gets markup linting plus a hard gate on dead resource paths
  with **no manual tool installation** — `task install` (pre-commit install) stays
  the only setup step, same as every other language.
- First run of the lychee hook needs network + curl/bash to fetch its binary
  (cached afterward). Restrictive proxies or Windows-without-curl hit friction; the
  `lychee-docker` and `lychee-system` hook variants are documented fallbacks.
- `--offline` means broken *external* URLs are not checked by default. Intentional:
  it keeps the gate fast, deterministic, and network-independent in CI. A project
  can drop `--offline` later if it wants external checking.
- No conflict with the `node` entry: node's Prettier hook is scoped to
  js/ts/json/css/md and does not touch `.html`, so selecting both entries is safe.
  We deliberately do **not** add Prettier-for-HTML — markup formatting wasn't asked
  for and is lower value than the broken-path gate.

## Alternatives considered

- **htmltest instead of lychee:** purpose-built for built static-site output and
  excellent, but has no maintained pre-commit hook → `language: system` (manual
  install) or Docker, i.e. exactly the manual setup we're avoiding. lychee's
  self-downloading hook is the easier distribution story.
- **html-proofer:** the most thorough, but Ruby; pre-commit's ruby backend can
  provision it, though that often compiles Ruby (slow, fragile). Heavier than the
  problem needs.
- **Link check in CI only (no local hook):** zero local deps, but loses the fast
  local feedback loop. Since the lychee hook self-installs, the local cost is low,
  so we keep both and let CI remain the hard backstop.
- **Force Docker for the link checker locally:** most reproducible, but Docker is a
  heavy dependency to require of every contributor. Kept as a documented fallback,
  not the default.
- **Prettier-for-HTML formatting:** deferred — not requested, overlaps with the
  `node` entry, and markup formatting is lower value than the resource-path gate.

[#1453]: https://github.com/pre-commit/pre-commit/issues/1453
