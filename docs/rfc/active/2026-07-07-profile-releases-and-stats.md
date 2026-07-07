# Profile releases and public stats: package-manager metadata with zero infrastructure

- **Status:** Active
- **Date:** 2026-07-07
- **Author:** Luca Mastrostefano
- [x] Implemented

## Context

The ecosystem already has the load-bearing package-manager parts: versioned artifacts
(tagged git repos), integrity (content hashes), a per-project lock (the manifest records
source + version + hash), a trust gate, discovery (the community index), and update
propagation. What it lacks is what a registry adds on top: **public metadata and
popularity signals** — which profiles are actually adopted — and a lower-friction publish
flow. The mission ("help the community converge") needs convergence *signals*: `search`
today returns entries in file order with no evidence anyone uses them.

The structural obstacle: profiles are fetched by `git clone`, and clone counts are visible
only to each repo's owner (GitHub traffic API, 14-day window). No tooling on our side can
produce public download stats from clone-as-transport. GitHub **Release assets**, by
contrast, carry public, permanent, per-version `download_count`s queryable by anyone —
and releases are also simply better package-manager semantics than moving refs: immutable,
named artifacts.

Constraints: the community-index RFC decided **zero infrastructure** (a static file in
this repo, PR-gated); the trust model requires fetches stay **data-only** and consent to
bind to **content**, not transport; `main` is ruleset-protected (no bot pushes), so CI
cannot commit stats to it.

## Decision

Two additions, both zero-infra (GitHub is the only backend), neither breaking:

**1. Release-asset transport.** `profile publish --release` packs the consented surface
(`profile.json` + `templates/`) **from the tag's committed tree** (`git archive <tag>`
semantics — never the working tree, so a dirty checkout can't ship an asset that fails its
own equivalence check) into a namespaced asset, **`agent-native-profile.tar.gz`** (a name
no unrelated repo plausibly already uses), and creates a GitHub Release on that tag.
`resolve` of a `git+https://github.com/...@<tag>` URL first tries the predictable asset
URL (`releases/download/<tag>/agent-native-profile.tar.gz`, plain HTTPS — no auth, no
git); on any failure it falls back to today's clone. Unpacked content flows through the
identical pipeline — load, validate, classify, content-hash consent — so the consent gate
is unchanged: it binds to what lands, regardless of transport. Non-GitHub hosts,
`#subdir=` monorepo profiles, and unpinned (branch/`@sha`) refs keep clone-only — the
fetch RFC's open `@sha` question is unaffected.

- **Extraction is a new untrusted-input surface**: stdlib `tarfile` with
  `filter="data"` (rejects absolute paths, traversal, symlinks/hardlinks, devices,
  permission escalation) **plus** an extracted-size cap and a member-count cap (bombs),
  with duplicate members rejected; unpacked into the cache staging dir. Ships with
  `/security-review`.
- **Security honesty — what the asset transport changes.** Release assets are *mutable
  even on an immutable tag*: anyone with release-write can silently repoint what a pinned
  URL serves, with no git history — a wider repoint surface than the tag ruleset was
  bought to prevent, and the consent gate only prompts for **unsafe**-classifying content
  (a poisoned asset swapped for a *safe*-classifying payload passes without a prompt,
  exactly as a poisoned tag would today via clone). Mitigation, not elimination:
  `check_index` fetches every **listed** entry through **both transports** (forcing each
  path explicitly) and fails on hash mismatch with a distinct diagnosis ("asset ≠ tag:
  possible poisoning — delist and notify the author" vs ordinary rot). Detection window:
  up to the weekly cron plus the 24h client cache; the on-PR trigger only fires for this
  repo's own changes. Hand-shared URLs that are not in the index get **no** equivalence
  check, ever — their protection remains the consent gate alone, as with clone today.

**2. A stats sidecar, precomputed by CI, served like the index.** A weekly workflow
(`index-stats`) queries the public GitHub API for each index entry — stars, and the
summed `download_count` of `agent-native-profile.tar.gz` assets **across all releases**
(the ordering metric, defined) — and force-pushes a single `contributions/stats.json` to
a dedicated **`stats` branch**. Verified mechanics, stated so the implementer isn't
discovering them: the branch ruleset targets only `main` and `v*` tags, so a CI-owned
`stats` branch is writable; the workflow needs `permissions: contents: write` (the
index-check workflow deliberately sets `read`); schedule-only + workflow_dispatch means
no fork-PR token exposure; the authenticated `GITHUB_TOKEN` budget (1,000 req/h) covers
~400 entries at ~2 calls each. The raw URL is fetched by the engine exactly like the
index: bounded, daily-cached, silent-on-failure, advisory-only. `profile search` /
`list --community` / `show` display what's available (`⭐ 12 · ⬇ 340`) and `search`
orders hits by that summed download count when stats are present; entries without
releases simply show stars. A listing's stats grant no trust — display data only,
escaped like every other remote field.

## Consequences

- Per-profile, per-version download counts become **public data** — no telemetry, no
  server, no privacy surface. The engine never phones home; the counting happens on
  GitHub's side when the asset is downloaded.
- **The metric is partially self-inflated and age-biased**: `check_index` itself downloads
  every listed asset weekly, so counts accrue ~1+/week per entry regardless of adoption,
  and cumulative totals favor older listings. Accepted — it's a popularity *signal*, not
  a measurement, and it's the cheapest honest one available.
- **One sticky commitment**: the asset name and predictable URL scheme become a
  compatibility contract with every deployed client once shipped (like the fetch RFC's
  hash format); everything else here — the stats branch, the workflow, the display — is
  cheaply reversible, and clone fallback is permanent.
- Asset fetch is faster than clone (one small HTTPS GET) and works without git installed —
  but only for pinned GitHub tags; the clone path remains fully supported, so authors who
  never run `publish --release` lose nothing except stats.
- **Downloads ≠ usage.** Release counts measure fetches (CI re-fetches inflate them;
  cache hits deflate them). Real active-usage measurement would require the engine to
  report in — rejected below; we accept the cruder public metric.
- The `stats` branch is CI-owned and force-pushed: history-free by design, and a
  compromised workflow could write misleading stats (display-only; never trust-bearing).
  The weekly cadence bounds API usage regardless of index size; clients still make exactly
  one cached fetch.
- `check_index` gains network weight (each entry fetched twice where assets exist) — it
  already runs weekly/on-PR only.
- Two more moving parts in `publish` (tarball + `gh release create`) — it degrades
  gracefully to today's print-the-entry behavior without `--release` or without `gh`.

## Alternatives considered

- **Opt-in engine telemetry (PostHog-style or a counter endpoint).** The only way to
  measure *usage* rather than downloads. Rejected: the tool that gates profiles on
  "will this run code on your machine?" must not quietly report from your machine; and it
  breaks the zero-infra decision. Revisitable as explicit opt-in if the community ever
  needs it.
- **Client-side live API stats** (each `search` queries GitHub per entry). Zero new
  pieces, but N entries × unauthenticated rate limits (60/h) breaks past ~25 entries and
  makes `search` slow. Rejected; the CI-precomputed sidecar costs one fetch.
- **Owner-only traffic API.** Clone counts exist but are private to each profile's owner
  and 14-day-windowed — useless for a public signal. Rejected.
- **Commit stats.json to `main` via PRs.** Weekly bot PRs through the required checks are
  noise, and auto-merge machinery is more infra than a data branch. Rejected.
- **Status quo (no stats).** Keeps `search` evidence-free file-order; the convergence
  loop stays blind. Rejected — this is the cheapest honest signal available.
