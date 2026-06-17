# Cancel superseded PR CI runs (workflow concurrency)

- **Status:** Active
- **Date:** 2026-06-06
- **Author:** Luca Mastrostefano

## Context

The generated quality workflow has no `concurrency` control, so pushing several commits to
a PR in quick succession leaves every superseded run going — wasted CI minutes and slower
feedback. (First of the git/GitHub-integration improvements; the settings-based ones —
branch protection, auto-delete-merged-branches — come later as onboarding steps, since they
need a remote and admin.)

## Decision

Add a workflow-level `concurrency` block to both the greenfield and ratchet quality
workflows:

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.head_ref || github.run_id }}
  cancel-in-progress: true
```

`github.head_ref` is set only for `pull_request` events, so superseded **PR** runs share a
group and the older one is cancelled; a `push`/`main` run falls back to the unique
`github.run_id`, so it is **never** cancelled — every `main` commit still gets verified.
Pure file change, no new permissions or settings. Dogfooded into this repo's workflow.

## Consequences

- Rapid PR pushes no longer pile up redundant runs — faster feedback, fewer CI minutes.
- `main` history stays fully checked (push runs aren't cancelled).
- Zero new permissions or settings.

## Alternatives considered

- **Group by `github.ref` for everything:** simpler, but would also cancel in-progress
  `main` runs, leaving some `main` commits unverified.
- **No concurrency control (status quo):** wastes minutes on superseded PR runs.
