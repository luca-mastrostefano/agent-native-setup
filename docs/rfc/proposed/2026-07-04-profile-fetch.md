# Profile fetch: consume a profile from a git URL, on per-artifact content-hash trust

- **Status:** Proposed
- **Date:** 2026-07-04
- **Author:** Luca Mastrostefano
- [ ] Implemented

> **Status note:** the core **landed** — `git+https://`/`git+ssh://` fetch (enforced transport
> allowlist, `--no-recurse-submodules`, cached, pinned-ref reuse, offline fallback), `content_hash`
> over exactly `profile.json` + `templates/`, the `trusted.json` store, the provenance-aware
> `consent` gate (fetched + unsafe + untrusted → `--allow-code`; safe/local pass freely; recorded
> per artifact), `profile add`/`untrust`/`trust --list`, the `--allow-code` scaffold flag, and the
> update re-fetch/re-gate. Deferred (Open questions): a registry/index, `@sha` verification. Kept
> `Proposed` under the parent profiles RFC's umbrella.

## Context

The local profile system is complete and hardened — author (`init`/`validate`/`save`), compose or
standalone, prompts/`when`/`env`, versioned updates, and the safety foundation (derived classifier,
sandboxed rendering, path confinement). The **last stage-A gap** (RFC 2026-07-03-ecosystem-core) is
**distribution**: today `--profile` takes only a local path or a `~/.config` name, so there is no
way to consume a profile someone else *published*. Without that, the ecosystem can't exist — you
can author and share by hand, but not *install*.

`profile-safety` deferred the **trust model** to exactly here, because trust only becomes a real
question once a profile's bytes come from somewhere you didn't write. It also made this tractable:
the classifier lets **safe** (declarative, sandboxed, confined) profiles flow freely, so only
**unsafe** ones ever need consent. This RFC adds git-URL fetch and answers the three questions
`profile-safety` §5 left open: the trust model, the consent granularity, and install-time trust. It
also **realizes** RFC 2026-06-23 §7's deferred `url`/`git+https://` fetch and its "team pre-trust by
content hash" sketch, and makes that RFC's earlier `update_source` idea obsolete — the recorded
`source` is the single re-resolution pointer (the shipped code already works this way).

## Decision

**1. Fetch from a git URL.** `--profile git+https://github.com/team/profile.git` (and `git+ssh://`)
resolves by **cloning into a cache** and loading the profile from the checkout. Optional
`@<ref>` pins a tag/branch/commit (`…profile.git@v1.2.0`); optional `#subdir=<path>` selects a
profile inside a monorepo. `profiles.resolve()` gains **`git+` scheme dispatch** (today it handles
a local path / `~/.config` name) — the one integration point, which `update` re-fetches through
since the recorded `source` is the URL.

The fetch is **data-only, but only because it's constrained** — not by trusting `git clone` in
general (which can execute at clone time):
- **Transport allowlist.** Only `git+https://` / `git+ssh://` are accepted; `ext::`, `file::`, and
  transport-command URLs (they run a shell command *at clone time*) are **rejected**, never passed
  through to `git`. "https/ssh only" is an enforced allowlist, not a convention.
- **No submodule recursion.** Clone with `--no-recurse-submodules` — a `.gitmodules` `ext::` URL is
  a known RCE vector (CVE-2019-1387 & family).

With those, a clone transfers data and installs no hooks (client hooks live in `.git/hooks`, not
the tree), so **nothing runs at fetch time**; all code risk is in *applying* the profile, which the
safety controls govern.

**2. Cache + offline.** Clones live under `~/.cache/agent-native-setup/profiles/<url-hash>/`
(pinned refs are immutable, cached forever; a moving ref re-fetches). `update` re-fetches; offline
falls back to the cache with a warning rather than failing.

**3. Provenance is the source scheme.** A **URL** is *untrusted* (bytes from the network you may
not have read); a **local path**, a `~/.config` name, and the in-box `default` are *trusted* (you
have them locally / authored / they shipped with the tool). This is durable — the scheme is
recorded in `source` and survives into `update`.

**4. The trust model: per-artifact content-hash pre-trust** — the crux `profile-safety` deferred.
Consent is granted to *a specific artifact*, not a path or a moving target:
- A profile's **content hash** = a sha256 over its sorted `(path, sha256(bytes))` list of
  **exactly `profile.json` + every file under `templates/`** — which is *exactly the surface that
  gets applied and copied*, so consent binds to precisely what can affect the consumer. That set is
  the whole applied surface: `apply` renders only `templates/` and reads `session_start`/
  `onboarding` from `profile.json`; **`profile add` copies only that same set** (never the rest of
  the checkout — a repo's top-level `Taskfile`, docs, or a tree-shipped `.git/hooks/` are neither
  hashed, classified, nor installed), and symlinks are skipped everywhere (`template_files`, copy).
  It's version-independent of any tag. Caveat: the hash is byte-exact, so a checkout under
  `core.autocrlf` can normalize line endings and re-prompt on another machine — that errs toward
  *friction* (re-consent), never toward a silent bypass, which is the safe direction.
- **Untrusted (fetched) + `unsafe`** → **gate**: show the classifier's reasons (the sinks, the
  `session_start` commands separated as *persistent*, the onboarding steps as *one-shot* — per
  ecosystem-core §5a), require consent, then **record the content hash** in a user trust store
  (`~/.config/agent-native-setup/trusted.json`). Consent = `--allow-code` (or an interactive
  `yes`); a non-tty run without it refuses with the reasons.
- **Re-fetch of the same content** → the hash is in the store → **no prompt**. **Changed content**
  (a new version, or a moving ref that advanced) → a new hash → **re-prompt**, showing the new
  reasons — so a "moving target" can never silently swap in unreviewed code.
- **Untrusted + `safe`** → **no gate**. A safe profile provably can't run code (no hooks/sinks,
  rendered sandboxed, paths confined), so gating it would be pure friction. This is sound **because
  the applied/copied surface is exactly `templates/` + the declarative `session_start`/`onboarding`
  and nothing else in the fetched tree is executed or installed** (§1 copy invariant); and because
  the classifier fails closed, a coverage miss errs toward false-*unsafe* (friction), never
  false-*safe* (bypass). *This is the payoff of the safety classifier*: the everyday fetch — a
  declarative profile — is frictionless.
- **Trusted sources** (local path / `~/.config` / `default`) → no gate, as today.

**5. `profile add` installs with one-time consent.** `agent-native-setup profile add <url> [name]`
fetches, classifies, gates once (recording the hash), and copies the profile into
`~/.config/agent-native-setup/profiles/<name>` — thereafter a *trusted local* profile used by name.
This is the npm-install model: consent at install, then use freely. Direct `--profile <url>` also
works (ephemeral cache fetch, inline consent). One flag, `--allow-code`, covers both persistent and
one-shot code for v1; the disclosure still separates them so consent is informed.

**5a. Consent is revocable in v1.** A consent store that can only be written to isn't honest, so
`profile trust --list` (show what's consented) and `profile untrust <hash|name>` (revoke) ship
**with** the store, not as a later refinement — a mistaken rubber-stamp must have a supported undo.

**6. Composes with the update re-gate.** On `update`, re-resolve → re-fetch → re-classify →
re-check the hash. A fetched profile whose new content is unsafe-and-not-yet-trusted **re-gates**
(generalizing the safe→unsafe gate from `profile-safety` §4). A pinned `@sha` never changes, so it
never re-gates; a moving ref re-gates whenever its content changes to something unconsented.

## Consequences

**Newly possible**
- **The ecosystem becomes real**: publish a profile on any git host (no central registry, no infra
  to run), and anyone consumes it with `profile add <url>`.
- **Safe profiles are frictionless; unsafe ones gate once per version.** The classifier does the
  work the whole safety arc was building toward.
- **Consent is durable and honest** — tied to the exact artifact, so a review means something and a
  content change re-asks.

**Harder / costs**
- **A supply-chain surface**: you now run *applied* code from fetched profiles (only after consent,
  and only if unsafe; safe ones are sandboxed data). The consent gate + content-hash are the
  mitigation, not a guarantee against a user who rubber-stamps.
- **Trust-store state** (`trusted.json`) is user-level state to manage — hence `trust --list` /
  `untrust` ship in v1 (§5a).
- **Unpinned refs are a moving target**: reproducibility needs `@<tag/sha>`; the version-nudge and
  re-gate soften the unpinned case but don't remove it.

**What we give up**
- Nothing that works today — `--profile <local>` and `<name>` are unchanged; URL support and the
  gate are additive.
- **Content-hash pre-trust does *not* close the clone-then-point path** — and this RFC says so
  plainly, *overriding* `profile-safety` §5, which had framed content-hash as the thing that would
  close that "loophole." It doesn't: it closes the **fetch-by-URL** channel (where bytes arrive
  un-inspected), and `git clone <url> && --profile ./dir` is accepted as **equivalent to running
  any repo you deliberately cloned** — you already ran `git clone` and could `cat` it; the user is
  the trust anchor for local code (ecosystem-core §6). So the gate lives on the URL path, not the
  local path, on purpose.

**Reversibility.** `--profile <local>`/`<name>` support is additive. The genuine one-way-ish
commitments: `trusted.json` becomes **persistent user-level state**, and the **content-hash
definition becomes a compatibility contract** — changing how the hash is computed later invalidates
every stored consent (mass re-prompting). This is the concrete step that opens *fetched-code
consumption*, the one-way door ecosystem-core §7 flagged as stage D; the hash format is the part
that's expensive to reverse, so pin it deliberately.

## Alternatives considered

- **A central registry / package index** (name → url, hosted). Rejected for now: git URLs need
  zero infrastructure and no gatekeeper; a curated index can layer on top later (Open questions).
- **Trust-on-first-use without content-hash** (trust the *source*, run whatever it later serves).
  Rejected: a moving ref would silently run unreviewed code on the next fetch — the exact failure
  the content-hash prevents.
- **Signing / PKI** (verify a publisher key). Heavier than content-hash pre-trust and needs a key
  ecosystem; content-hash gives artifact integrity + informed consent without it. Deferrable if a
  real publisher-identity need emerges.
- **Gate every fetched profile regardless of tier.** Rejected: a `safe` profile can't run code, so
  gating it is pure friction — and the classifier exists precisely so we don't have to.
- **Fetch by running an installer the profile ships.** Rejected outright: that's arbitrary remote
  code execution at *fetch* time, before any classification. Fetch stays data-only (`git clone`).

## Open questions (for implementation)

- The exact **URL grammar** (`@ref`, `#subdir=`), and private-repo **auth** (lean on git's own
  credential handling rather than reinventing it).
- The `trusted.json` **on-disk format** (the `trust --list` / `untrust` commands themselves are v1,
  §5a) — pin the hash definition carefully, since it's a compatibility contract (Reversibility).
- **Consent granularity**: one `--allow-code`, or a distinct `--allow-hooks` for persistent
  `session_start` (ecosystem-core §5a decided the *principle*; v1 uses one flag with separated
  disclosure — revisit if the distinction proves worth a second flag).
- Whether a **pinned `@sha`** should be verified against the fetched commit (cheap integrity check).
- A future **registry/index** layered over URL fetch (discovery, curation, `profile search`).
