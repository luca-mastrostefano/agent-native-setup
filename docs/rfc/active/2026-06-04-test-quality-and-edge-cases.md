# Push test quality and edge cases, not just test presence

- **Status:** Active
- **Date:** 2026-06-04
- **Author:** Luca Mastrostefano

## Context

The `testing-expectation` RFC made "every change ships with the test that proves it" a
first-class rule and named edge cases under Unit. But it's brief: it names edge cases in
three words and never guards against the common agent failure modes — tautological /
coverage-theater tests, tests that restate the implementation, and happy-path-only tests
that skip boundaries, bad input, and error paths. The `code-reviewer`'s principle-4 lens
only asks "is it verified by a test?" — presence, not quality.

## Decision

Two small additions, kept consistent with Simplicity First (*fewer, more meaningful*
tests, not more tests):

1. **Contract, principle 4** — add a line: tests should prove behavior, not restate the
   implementation; cover the boundaries (empty/zero/one/max), bad input, and error paths,
   not just the happy path; a test that can't fail isn't worth writing.
2. **`code-reviewer`** — expand the principle-4 lens to flag tautological / happy-path-only
   tests and name the missing edge case, while keeping its "prefer a few high-confidence
   findings" restraint so it doesn't nag.

Dogfood both into this repo.

## Consequences

- The agent is steered toward tests that exercise real behavior and edges, and the
  reviewer catches coverage theater — closing the gap between "has a test" and "has a
  good test".
- A few contract lines; no change to the testing *levels* guidance, so it doesn't reopen
  the "mandate all three" over-prescription the prior RFC rejected.

## Alternatives considered

- **Leave it** (status quo): edge cases are named but weakly, and nothing catches
  low-value tests.
- **Mandate coverage thresholds or property-based tests:** heavier and easy to game;
  guidance plus a review lens targets *meaning*, not a number.
