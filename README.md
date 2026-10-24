# `stats` branch — data only, do not edit by hand

Auto-generated **daily** by `.github/workflows/index-stats.yml` on `main`.
Holds public per-profile metrics (stars, forks, release-asset downloads) in
`contributions/stats.json`, fetched client-side by the website and by
`profile search`/`list`.

This branch is **force-pushed** on every run (`git checkout --orphan stats`),
so it has no durable history and **PRs against it will be overwritten**.
Rationale: `docs/rfc/proposed/2026-07-07-profile-releases-and-stats.md` on `main`.
