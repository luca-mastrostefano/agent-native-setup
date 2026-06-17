# Real versions + an end-of-run "update available" nudge

- **Status:** Active
- **Date:** 2026-06-04
- **Author:** Luca Mastrostefano

## Context

`agent-native-setup` is installed from git (`uv tool install git+…`) and upgraded by hand
(`uv tool upgrade`). There's no package-manager update channel, so users don't learn that a
newer version — with fixes like the gitleaks CI permission — exists unless they think to
upgrade. In one recent hour we hit this twice: fixes shipped, and the only way to get them
was a manual upgrade nobody was prompted to run.

Two things block a meaningful "update available" check today:

1. **No comparable version.** `version` is a static `0.1.0` in both `pyproject.toml` and
   `__init__.py`, and everyone installs from `main`'s HEAD. A running copy can't tell
   whether it's current — `0.1.0` never moves and the tool doesn't know its own commit.
2. **No release cadence.** There are no tags, so "latest" has no definition to compare to.

## Decision

Two coupled parts.

### 1. Real, tag-derived versions

Adopt `hatch-vcs`: derive the version from the latest git tag (`[tool.hatch.version] source
= "vcs"`), dropping the static `version` in `pyproject.toml` and `__init__.__version__` —
the tag becomes the single source of truth. A build at tag `v0.2.0` is `0.2.0`; a build N
commits past it is `0.2.0.devN+g<sha>`. Cut a release with `task release VERSION=X.Y.Z`
when a meaningful batch lands — it runs `gh release create`, which makes the tag *and* the
GitHub release the check reads (the check uses the Releases API, so a bare tag isn't enough).

### 2. An end-of-run, best-effort update nudge

After a **successful** scaffold (never before — it must not block or delay the real work),
the CLI checks GitHub for the latest release tag and, if the installed version is behind,
prints one dismissible line:

    A newer agent-native-setup (v0.3.0) is available — run `uv tool upgrade agent-native-setup`.

Guardrails so it stays unobtrusive and safe:

- **Offline / any error → skip silently.** ~1.5 s timeout on a stdlib `urllib` call to the
  GitHub releases API (unauthenticated; no token, no PII sent).
- **Cached.** Store the last-check time + latest-seen version under the user cache dir;
  check at most once / 24 h — not a network call every run, and never trips the 60/h
  unauthenticated rate limit.
- **Quiet in the wrong contexts.** Skip when non-interactive (`--yes` / no TTY) or under
  CI, and honor `--no-update-check` and `AGENT_NATIVE_SETUP_NO_UPDATE_CHECK=1`.
- **Never fails the run.** A failed or skipped check is a silent no-op.

Comparison uses `packaging.version` (a tiny, ubiquitous **new runtime dep** — adding it is
the reason this is an RFC). Dev versions compare correctly (`0.3.0.dev2` > the `0.2.0`
release, < `0.3.0`), so a bleeding-edge HEAD install is never nagged.

## Consequences

- Users — and the agents driving them — learn about fixes without remembering to upgrade.
  Highest-value outcome, given the tool ships CI/security fixes that silently affect every
  repo it generates.
- Tagged releases give a real version to cite and a natural changelog boundary — good
  hygiene independent of the nudge.
- Costs: one runtime dep (`packaging`), one build dep (`hatch-vcs`), a small cached network
  call, and a release (tag) step. This is **polish, not core function** — worth it only if
  distribution quality matters to you; otherwise it cuts against Simplicity First, and the
  manual `uv tool upgrade` is fine.

## Alternatives considered

- **Manual version bumps instead of `hatch-vcs`:** bump `version` in two files + tag each
  release. Simpler tooling, but two-place edits drift; tag-derived is one source.
- **Compare commit SHAs instead of tags** (embed the build commit, diff against `main`'s
  latest): matches today's HEAD-tracking usage and needs no release discipline, but it's
  hackier (a build hook to embed the SHA) and would nag on every `main` commit, not on
  releases.
- **No check; rely on manual `uv tool upgrade`** (status quo): zero moving parts, but the
  user never learns an upgrade is worth running.
- **Telemetry / auto-update:** out of scope and intrusive. A read-only check that only ever
  prints a hint is the least-surprising option.

## Resolved

- **Ship both parts together** (this change), rather than tags-first then the nudge.
- **Interactive only** — the nudge is skipped under `--yes`, a non-TTY, or CI (and via
  `--no-update-check` / `AGENT_NATIVE_SETUP_NO_UPDATE_CHECK`), so scripted and CI output
  stays clean.
