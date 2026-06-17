# A delta-scoped cohesion/coupling lens for the code-reviewer

- **Status:** Active
- **Date:** 2026-06-04
- **Author:** Luca Mastrostefano

## Context

The `code-reviewer` flags over-abstraction (Simplicity) and drive-by refactors (Surgical),
but nothing asks whether a change harms **cohesion or coupling** — piling a new, unrelated
responsibility onto a module, or reaching across a boundary. Adding that lens naively
("this file is too big, split it") would be noisy and, worse, push drive-by refactors of
**legacy** code — violating Surgical Changes and exactly the failure the maintainer flagged.

## Decision

Add one lens to the reviewer, scoped to the **delta** — mirroring how the gate grandfathers
legacy by checking only changed files: does *this change* add a new unrelated responsibility
to a module, or a new cross-boundary dependency? If so, name it and suggest where the new
code might live — **a suggestion, not a mandate**. It must **never flag a file's
pre-existing size or push a refactor of code the change didn't introduce**. The reviewer
keeps its "prefer a few high-confidence findings" restraint.

This complements the mechanical `FORBIDDEN_IMPORTS` boundary test (`tests/test_architecture.py`):
the test enforces *import* rules deterministically; the lens catches the design-level
cohesion a test can't — on the delta only. Dogfood into this repo's `code-reviewer`.

## Consequences

- The reviewer can catch a change that quietly turns a focused module into a grab-bag, or
  introduces coupling — without becoming a legacy-refactor nag.
- One lens, legacy-safe by construction: it can only fire on what the PR introduced.

## Alternatives considered

- **A blanket "file too big → split it" check:** noisy on legacy, pushes drive-by
  refactors, conflicts with Surgical Changes / Simplicity First. Rejected — it's the very
  failure mode this lens is designed to avoid.
- **Leave it to the architecture boundary test:** mechanical and right for *import* rules,
  but it can't judge cohesion or whether a change adds an unrelated responsibility.
- **Add it to the four principles in the contract:** over-weights a review concern; the
  reviewer is the narrower, correct home (like the docs-in-sync lens).
