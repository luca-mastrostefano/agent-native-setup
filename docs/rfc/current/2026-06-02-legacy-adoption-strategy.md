# A single "legacy adoption strategy" choice for existing repos

- **Status:** Accepted
- **Date:** 2026-06-02
- **Author:** Luca Mastrostefano

## Context

We grandfather existing code in several places — the ratchet CI gate, non-blocking
security `checks`, security-only Dependabot — each auto-defaulted to "progressive."
But an existing repo isn't always a large legacy codebase: it may be **small or new**,
where applying the full gate immediately is the better call; and some teams just want
the config scaffolded without enforcing it yet. Silently defaulting to progressive is
wrong for those cases, and the legacy knobs are scattered and should move together.

## Decision

When scaffolding into a repo with pre-existing source (`existing_project`), **ask one
question — the adoption strategy** — and let the answer drive every legacy knob
coherently. The prompt highlights "progressive" as recommended, but we do **not**
silently default; the user chooses.

| Knob | **progressive** (recommended) | **full** | **none** |
| --- | --- | --- | --- |
| CI quality job | ratchet — changed files only, blocking | whole repo, blocking | whole repo, non-blocking (`continue-on-error`) |
| CI security `checks` job | non-blocking | blocking | non-blocking |
| Dependabot | security-only | full version updates | security-only |
| `.git-blame-ignore-revs` + sweep guidance | format as you touch | next-steps prompt the one-time sweep | optional |

- **progressive** — only new/changed code is enforced; existing code grandfathered.
  Best for a mature legacy repo.
- **full** — enforce on the whole repo now, like a fresh project. Best for a small or
  new repo; next-steps prompt the one-time formatter sweep.
- **none** — scaffold all the config, but CI is informational (never red); turn
  enforcement on when ready.

Interactive + existing repo → ask. Non-interactive → `--adopt {progressive,full,none}`
(default `progressive`). A **fresh** repo is always "full" (greenfield) and is not
asked. This replaces the scattered `existing_project` branches in `ci.py`,
`quality.py`, and `_dependabot` with one `adoption` value.

## Consequences

- One coherent choice instead of silent per-process defaults: small/new existing repos
  can opt into full standards, mature ones stay grandfathered, and "not ready to
  enforce yet" is supported.
- One new prompt (only when an existing repo is detected) plus one flag.
- A little more branching in the generators (three modes instead of two).

## Alternatives considered

- **Keep auto-progressive, no prompt:** simplest, but wrong for the small/new existing
  repo — the case that motivated this.
- **A prompt per process:** sprawl; one strategy keeps the knobs consistent.
- **Drop `none`, offer only progressive/full:** simpler, but "scaffold without
  enforcing yet" is a real adoption stance worth supporting.
