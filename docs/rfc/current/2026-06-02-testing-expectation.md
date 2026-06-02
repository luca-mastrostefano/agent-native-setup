# Make testing an explicit expectation in the contract

- **Status:** Accepted
- **Date:** 2026-06-02
- **Author:** Luca Mastrostefano

## Context

The generated `AGENTS.md` (principle 4, Goal-Driven Execution) already implies testing
— "write tests for invalid inputs," "write a test that reproduces the bug," "tests pass
before and after a refactor" — and the `code-reviewer` agent + tests-in-CI enforce
"verified by a test." But it reads as *examples* rather than a first-class rule,
"regression" is never named, and there's no guidance on *which level* to test at. The
result is easy to under-test — or, just as bad, to mechanically over-test.

## Decision

Add a short, explicit expectation to principle 4: **every change ships with the test
that proves it, at the right level** —

- **Unit** — logic and edge cases (the default).
- **Integration** — when the change crosses a module, a public contract, or an external
  boundary.
- **Regression** — for every bug, the failing reproduction written *first*, then the fix.

Framed as "pick the right level, don't mechanically add all three," and requiring the
author to say *why* when something genuinely can't be tested. Dogfood the same wording
into this repo's own `AGENTS.md`.

## Consequences

- Testing becomes a first-class, unmissable expectation with level guidance, instead of
  buried examples — while explicitly avoiding the over-prescription (mandating all three
  on every change) that would be noise and cut against Simplicity First.
- The contract grows by a few lines.

## Alternatives considered

- **Leave it implicit** (the principle-4 examples): the discipline exists but is easy to
  miss and silent on level.
- **Mandate unit + integration + regression for every change:** over-prescriptive and
  noisy — wrong for changes that don't warrant all three.
