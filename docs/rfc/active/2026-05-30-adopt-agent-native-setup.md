# Adopt the agent-native project setup

- **Status:** Active
- **Date:** 2026-05-30
- **Author:** agent-native-setup team

## Context

Starting a new project, we want coding agents and humans working from the same
contract from day one, with conventions enforced mechanically rather than by
memory.

## Decision

Adopt this scaffold: a canonical `AGENTS.md` (with per-tool pointers), a docs +
RFC structure, linters and pre-commit hooks, CI on every push, and the four execution principles as the standard
for every change.

## Consequences

Contributors have one place to look for conventions. Drift is caught by tooling.
The cost is keeping `AGENTS.md` and the docs current as the project evolves.
