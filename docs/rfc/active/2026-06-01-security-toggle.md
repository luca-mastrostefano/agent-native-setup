# A `--no-security` toggle for the security gate

- **Status:** Active
- **Date:** 2026-06-01
- **Author:** Luca Mastrostefano

## Context

`2026-06-01-harden-generated-ci.md` added secrets + dependency scanning, folded into
the coarse `include_quality` / `include_ci` switches. Some projects want the rest of
the quality gate but not the security scanning — e.g. `gitleaks-action` needs a
license on private org repos, or a team runs security tooling elsewhere. Today there
is no way to opt out of *just* security without dropping all of quality or all of CI.

## Decision

Add one boolean, `include_security` (default **true**), exposed as `--no-security`
and an interactive confirm. When off, the wizard omits:

- the **gitleaks pre-commit hook**, and
- the **`checks` CI job** (per-language vuln scan + gitleaks).

It does **not** affect tests-in-CI — those stay under `include_ci`. The toggle is
security-specific.

One flag, not three: no separate secrets / vuln / per-language sub-flags. That keeps
the coarse, low-config CLI surface the project favors (`AGENTS.md`: "no configurability
that wasn't requested").

## Consequences

- Teams can keep linting/formatting/tests/CI while opting out of security scanning.
- Default-on means new projects still get security by default; opting out is explicit
  and recorded in the run.
- Minor: one more flag and one more line in the interactive "scaffold which parts" flow.

## Alternatives considered

- **Per-check flags (secrets vs deps vs ...):** rejected — the configurability sprawl
  the project deliberately avoids.
- **Fold security into `include_quality` only:** rejected — security spans both
  pre-commit and CI, so a dedicated boolean is clearer than coupling it to one switch.
