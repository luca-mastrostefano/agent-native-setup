# Point the agent at /security-review with a smart trigger

- **Status:** Accepted
- **Date:** 2026-06-03
- **Author:** Luca Mastrostefano

## Context

The scaffold enforces security *mechanically* — gitleaks (secrets), dependency/vuln
audits, `SECURITY.md` — but nothing prompts an agent to *reason* about security on a
change that warrants it. The generalist `code-reviewer` is tuned to the four execution
principles, not to thinking like an attacker, so logic-level flaws (authz, input
handling, deserialization) fall between the scanners and the reviewer.

We considered scaffolding a dedicated `security-reviewer` subagent (and an
`architecture-reviewer`) but rejected both. For the audience that receives `.claude/`
agents — Claude targets — Claude Code already ships a maintained `/security-review`
command, so a bespoke clone would be weaker and would rot; and a generic "review for
security" prompt tends to emit checklist noise. The gap isn't a security *lens* — it's
that nothing *routes* to the one that already exists.

## Decision

Add a line to the contract's **Feedback loops** pillar, gated on a Claude target: when a
change touches a security-sensitive surface — auth, untrusted input, secrets or crypto,
or file/network I/O — also run `/security-review` before merging, noting it complements
(doesn't replace) the mechanical scans. Add a tool-agnostic "security-reviewed if it
touches a sensitive surface" item to the PR template. Dogfood both into this repo.

A targeted trigger (not "review everything") keeps it from being busywork — the same way
the `code-reviewer` line scopes itself to "non-trivial" changes.

## Consequences

- Routes to a maintained, first-party tool instead of shipping and maintaining our own
  reviewer; activates a security lens the mechanical scans can't provide.
- One contract line (Claude-gated, so it never names a command the host lacks) plus one
  PR-checklist line. The surface-based trigger keeps it off changes that don't warrant it.
- Non-Claude targets get the generic PR item but no `/security-review` pointer (the
  command is Claude Code-specific).

## Alternatives considered

- **Scaffold a `security-reviewer` subagent:** duplicates Claude Code's maintained
  `/security-review`; a generic security prompt tends to emit checklist noise.
- **Scaffold an `architecture-reviewer` subagent:** the RFC process and the architecture
  boundary test (`tests/test_architecture.py`) already cover design review; a standing
  agent would mostly re-litigate them.
- **Mandate `/security-review` on every change:** too heavy; the surface-based trigger
  scopes it to where it pays off.
- **Leave it to the mechanical scans:** they catch known-bad deps and committed secrets,
  not logic-level security flaws.
