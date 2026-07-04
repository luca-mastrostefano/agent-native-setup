# Community profile index: zero-infra discovery via a curated, PR-gated list

- **Status:** Proposed
- **Date:** 2026-07-04
- **Author:** Luca Mastrostefano
- [ ] Implemented

## Context

The profile ecosystem can now **author** (`init`/`save`/`validate`), **publish** (`git push`),
**trust** (content-hash consent), and **consume by URL** (`fetch`/`add`). But it cannot
**discover**: there is no way to *find* a profile you weren't handed the URL for. The community
loop — build → publish → **discover** → adopt → update — breaks at that one link, so today
"community" means trading URLs in a chat, not an ecosystem. RFC 2026-07-04-profile-fetch deferred "a
registry/index" to its own RFC; this is it, in the lightest form that fits this project's
no-infrastructure ethos and closes the loop.

## Decision

**1. A committed index — `contributions/index.json`.** A curated JSON list of entries
`{name, url, description, author, tags?}`, checked into this repo. Community members **PR an entry**;
curation is the repo's *existing* code-review gate — zero servers, zero accounts. **Profiles live in
their own repos** (the index holds `git+https://…` URLs, not the profiles themselves), so each keeps
its own release cadence and `update` stream; the index is only a phone book.

**2. `profile search <query>` and `profile list --community`.** Fetch the index with a bounded,
daily-cached HTTP GET from the canonical raw URL (silent on failure, exactly like `update --check`),
filter by name/description/tags, and print `name — description` + the URL. **Read-only; nothing
runs** — fetching JSON is data, and `search` never clones or applies anything. **An index URL is
not privileged**: an entry's `url` flows through the *identical* transport allowlist and
content-hash consent gate as a hand-typed `--profile` URL (fetch RFC §1/§4). So an `ext::sh -c …`
smuggled into an index `url` is rejected the same way, and a poisoned index gains an attacker
nothing they couldn't get by DMing you the URL directly — it can only lie in *prose*, not run code.

**3. The index grants no trust; classification stays derived.** An index entry is *discovery
metadata*, not a safety claim. There is deliberately **no author-declared `safety` field** — that
would reintroduce the "declared, not derived" anti-pattern RFC 2026-07-03-profile-safety §3
rejected. The authoritative safe/unsafe tier is computed **at fetch** by `classify_safety`, and the
consent gate at `add`/`--profile` is the only place trust is granted. `search` output says as much
("run `profile add` — an unsafe profile will ask for consent").

**4. Federation via an env override.** The index URL defaults to the canonical repo raw URL;
`AGENT_NATIVE_SETUP_INDEX_URL` points `search`/`list --community` at a **private/team index**
instead — a company curates its own list (a JSON in their own repo) with no fork and no infra.

**5. `profile publish` — a guided publish step.** The tail of the author flow (`save` → `validate`
→ **`publish`**): it validates the profile, prints its shareable `git+https://…@<tag>` URL (nudging
the author to tag a version), and emits the ready-to-PR `index.json` entry. It does **not** push or
open a PR (that stays the author's deliberate act). It earns its place beyond documentation because
it *encodes the correct shape* a human gets wrong by hand — a pinned `@<tag>` URL and a
schema-valid entry — and **unpinned/broken URLs are the main failure mode of the curation burden**,
so producing reproducible listings directly serves the index's maintainability.

**6. Adopt by name — `add <name>` / `show <name>` fall back to the index.** When a ref is a bare
name that resolves to nothing local (locals always win), `add`/`show` look it up in the index by
exact name and proceed with the listed URL — the npm-install model, collapsing the
`search` → copy URL → `add` journey to two short commands. This gives the index one new
authority: it resolves a *name* to a URL. Two constraints make the exposure unchanged in kind
(a poisoned index could equally have listed the URL under an enticing name to copy by hand):
the listed URL must itself be `git+` — a path-shaped entry is **refused**, because it would
resolve as a trusted-local profile and skip the consent gate (provenance is keyed on the
scheme) — and the `git+` URL then flows through the identical transport allowlist and consent
gate as a typed one. A broken *local* profile is never shadowed: it reports its own error.
The printed `name → community index → <url>` line keeps the redirection visible, and anything
URL- or path-shaped never consults the index.

## Consequences

**Newly possible**
- **The community loop closes**: `search` → `add` lets a stranger find and adopt a profile, which
  is the whole point of "community-driven." Everything else we built becomes usable by people you
  can't DM.
- **Zero infrastructure**: a JSON file + PRs. Curation is the repo's own review, which the project
  already trusts for correctness.
- **Federation for free**: teams run a private index by pointing the env var at their own JSON.

**Harder / costs**
- **Curation is a real, ongoing burden** — every listing is a PR the maintainers review. Bounded,
  but it grows with the list, and quality/spam control becomes a governance question at scale.
- **The index is a moving target** (cached, silent-on-fail) — `search` can be stale or unreachable;
  it degrades to "couldn't reach the index," never an error. Staleness here is slightly
  higher-stakes than a missed upgrade nudge: a **yanked/malicious listing removed upstream can
  linger in a cached client for up to the 24 h TTL**. The consent gate still fires on any fetch, so
  the exposure is bounded, but "a yank takes up to a day to reach a cached client" is real.
- **Discovery ≠ endorsement — and we accept the tension honestly.** Being listed is not a safety
  guarantee; the derived classifier + consent gate remain the only trust boundary. But PR-curation
  into *this repo's* index inevitably reads as *some* vetting ("trust-by-listing"), and the
  `description`/`tags` a user scans at `search` time are attacker-controlled prose with no tier
  attached (the tier is only knowable after a fetch). We accept that: the listing confers a trust
  halo the classifier can't revoke, so the output must repeat that the *classifier*, not the
  listing, is the boundary — and reviewers must treat a merge as "plausibly useful," not "vetted safe."

**What we give up**
- Nothing that works today — `search`/`list --community`/`publish` are additive and read-only.
  Reversible: the index is a file; the commands are new.

## Alternatives considered

- **A hosted registry / package index** (servers, accounts, upload API, moderation tooling).
  Rejected for now: it needs infrastructure and governance this project deliberately avoids, and the
  in-repo index can grow into one if demand proves it out.
- **Commit the actual profile *directories* under `contributions/`** (not just URLs). Rejected as
  the default: it couples every profile's lifecycle and updates to *this* repo and bloats it —
  profiles want their own repos. (An entry may still point at an in-repo `#subdir=` profile; that's
  how the example seeds the index without external hosting.)
- **An author-declared `safety` field in the index.** Rejected: worthless against a bad author and
  contradicts derived-not-declared. The tier is shown from the *derived* classifier once fetched.
- **No index — keep sharing URLs.** That is the status-quo gap this RFC exists to close.

## Open questions (for implementation)

- **`tags` — decided:** freeform discovery keywords live on the **profile itself** (`profile.json`
  `tags`), are shown by `show`, matched by `search`, and carried into the index entry by `publish`
  (single source of truth). **CI check — decided:** `index-check` (weekly + on `contributions/`
  PRs + on demand) fetches every listed URL and runs the `profile validate` load +
  strict-render, so rot fails CI instead of the next adopter. A recommended `@ref` remains open
  (`publish` already nudges toward a pinned tag).
- **Multiple** indexes (a config *list* of URLs) vs. the single env override — start with one, revisit.
- **Ranking** as the list grows (exact/substring only for v1; relevance later).
