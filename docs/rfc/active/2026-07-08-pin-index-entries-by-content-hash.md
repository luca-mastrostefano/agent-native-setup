# Pin community-index entries by content-hash, verified at install

- **Status:** Active
- **Date:** 2026-07-08
- **Author:** Luca Mastrostefano
- [x] Implemented

## Context

The community index (`contributions/index.json`, RFC 2026-07-04-community-index) resolves a
name to a `git+https://…@<tag>` URL. `profile add <name>` looks the name up, fetches the
listed URL, runs the derived safety classifier + consent gate, and installs. Today that proves
**liveness** — "this URL still resolves to a profile that loads and renders" — via the weekly
`index-check` and the `profile validate` load. It does **not** prove **integrity**: nothing
checks that the bytes fetched today are the bytes a maintainer vetted when the entry was
merged.

The flagship already gets that stronger guarantee. `baseline-pin.json` records the pinned
tag's `content_hash`, and `builtin_baseline_root()` refuses to scaffold if the fetched bytes
don't hash to the pin (RFC 2026-07-08-builtin-baseline-by-reference §1) — a supply-chain
tripwire. Community entries carry no such pin, so the flagship is tamper-evident and every
community profile is not. This RFC closes that asymmetry.

**Doesn't `add` already hash-pin fetched profiles?** Partly, and the gap is exactly the part
it doesn't. RFC 2026-07-04-profile-fetch §4 computes the *same* `content_hash` and records it
in `trusted.json` on consent, re-prompting if a fetched **unsafe** profile's content later
changes. But that is **trust-on-first-use**: on the *first* install-by-name there is no prior
consent to compare against, so a tag force-moved *before* you ever adopted it just prompts and
installs — there is no curator-vetted anchor. And profile-fetch §4 gives a **safe** profile no
gate at all ("untrusted + safe → no gate"), so a force-moved tag on a *safe* listing installs
**silently** today. The index hash supplies the missing anchor the TOFU store structurally
can't: a value the curator vetted at listing time, independent of whether *this* user has seen
the profile before, covering safe listings too.

The gap is narrow but real. Index entries point at immutable tags, so the *common* failure —
a dead repo, a gone tag, a broken profile — is already caught by liveness. The one thing
liveness can't catch is a **force-moved tag or a swapped release asset**: the same
`…@v0.1.1` URL resolving to *different, still-valid* bytes after listing. That is precisely a
supply-chain tamper, and RFC 2026-07-04-community-index already names its own worst case —
"a yanked/malicious listing removed upstream can linger in a cached client for up to the 24 h
TTL." A content-hash makes an install-by-name catch that drift even inside the cache window.

**Why a hash is a real control here, not a checksum against corruption.** The bytes live in
the third party's repo; the hash lives in *our* curated `index.json`, fetched at runtime from
`main`'s raw file (`profiles.py` `INDEX_URL`). Different trust domains: an author who
force-moves their tag cannot also rewrite the hash the curator committed. That separation is
the whole reason this is worth doing — a hash shipped *alongside* the bytes (e.g. in the
profile's own `profile.json`) would be rewritten by the same attacker and catch only accidental
corruption.

**This does not reintroduce "declared, not derived."** RFC 2026-07-04-community-index §3
rejected an author-declared `safety` field because a bad author can lie about it and it can't
be checked. A `content_hash` is different in kind: it is **objectively verifiable** — you
re-fetch and re-hash. The safe/unsafe tier stays **derived** at fetch by `classify_safety`,
and the consent gate stays the only place *execution* trust is granted. The hash adds
*integrity* (are these the vetted bytes?), orthogonal to *safety* (may these bytes run?). Both
gates apply.

## Decision

**Add a required `content_hash` to every index entry and verify the fetched bytes against it
when installing a profile by its index name. A mismatch is a hard, legible refusal.**

### 1. `content_hash` in the entry schema — required

Each `contributions/index.json` entry gains `content_hash`: the SHA-256 produced by the
existing `profiles.content_hash()` (over `profile.json` + `templates/`) — the *same* function
and algorithm the baseline pin uses. No new hashing primitive.

It is **required, not optional**. Optional-and-verify-if-present is a non-guarantee: an
attacker adding a malicious entry would simply omit the field to skip the check. A uniform
invariant is enforced by the well-formedness test and by `check_index`. The three current
entries are backfilled in this change (`agent-native-baseline@v0.2.0` already has its hash —
it equals the baseline pin's `c668be8…`).

A stable hash only exists for a **pinned** ref, so requiring `content_hash` makes a pinned
`@<tag>` de facto required for every listing. This resolves RFC 2026-07-04-community-index's
open question ("a recommended `@ref` remains open") in the direction its own §5 already leans
("unpinned/broken URLs are the main failure mode"): `check_index` rejects an entry whose URL
is not pinned, with a message pointing at the fix.

### 2. Verify at install-by-name — the security win

When `profile add <name>` / `show <name>` resolves a bare name **through the index**
(`_resolve_ref` → index lookup), thread the entry's `content_hash` to the install site and,
after `_fetch_git`, compute `content_hash(fetched)` and compare. This mirrors the baseline
gate (`builtin_baseline_root`), extended from the one flagship to every listed profile.

**Scope: install-by-name only.** Installing by a raw `git+…` URL (`profile add
git+https://…@tag`) carries no declared hash and is **not** verified — that is the correct
boundary, not a gap: pasting a raw URL is opting out of the curated index and into trusting
that URL yourself, exactly as today. The guarantee is precise: *adopting a profile by the name
the index vouches for verifies the bytes the index vouched for.*

### 3. Federated indexes: verify-if-present, required-in-canonical

The install site (§2) verifies **when the resolved entry declares a `content_hash`**, and
falls back to today's liveness + consent behavior when it doesn't. That is not the
"verify-if-present is a non-guarantee" §1 rejects — the two live in different trust models.
For the **canonical** index, `check_index` + the well-formedness test make the field *always
present*, so an attacker cannot omit it to dodge the check (§1). For a **federated** index
(`AGENT_NATIVE_SETUP_INDEX_URL`, RFC 2026-07-04-community-index §4), the operator *is* the
trust root — you already trust them to list any URL under any name — so verify-if-present is
the correct semantics: an operator who wants the tamper-evidence includes hashes (and can
enforce their own required-ness by running the standalone `check_index` against their JSON in
their own CI); one who omits them has chosen liveness-only for their own list, as they choose
everything else about it. Refusing hash-less federated entries outright would instead be a
silent, breaking behavior change to a documented feature. The install site therefore keys on
the field's presence, not on which index served it.

### 4. A mismatch is a hard refusal, with a raw-URL escape hatch

On mismatch, `add` fails with a `ProfileError` naming the drift and the escape:

> the bytes at `<url>` no longer match the hash vetted in the community index — the tag was
> moved or its content changed since it was listed. Refusing. To install these bytes anyway,
> adopt them by raw URL: `profile add <url>`.

Hard-fail, not warn-and-proceed: a warning that the user clicks past defeats the purpose, and
the raw-URL path already gives a deliberate, visible override for "I know the tag moved and
want the new bytes." That escape is **not** a security bypass of execution trust — a raw
`git+` URL still hits the derived-classifier + consent gate (RFC 2026-07-03-profile-safety); it
only opts out of *integrity* vetting, which is the layer the user is explicitly overriding.

### 5. `check_index` asserts declared == fetched (weekly + on PR)

`check_index` already resolves (and thus fetches) every entry; it hashes only *some* today —
inside `_asset_equivalence`, and only for GitHub asset-bearing entries, to compare the asset
and clone transports, never against a declared value. Add a per-entry step that computes
`content_hash(load(resolved.root))` — the `load` already happens — and asserts it equals
`entry.content_hash`, for **every** entry regardless of transport or asset. This keeps the
declared hashes honest without an adopter having to install: a force-moved tag fails CI
weekly, and on a `contributions/**` PR the check validates that the hash the author wrote
matches the pinned tag they listed. The mismatch message prints the correct hash so a stale
entry is a copy-paste fix.

### 6. `profile publish` emits `content_hash`

`profile publish` already prints the ready-to-PR entry; it now computes and includes
`content_hash` (it already loads the profile to validate it). Hand-computing a hash is exactly
the kind of error the RFC 2026-07-04-community-index §5 publish step exists to prevent, so the
machine emits it.

## Consequences

**Newly possible**
- **Install-by-name is tamper-evident.** A force-moved tag or swapped asset is caught at the
  moment of adoption — the point where it would otherwise inject unexpected bytes into a user's
  repo — and again weekly in CI.
- **Narrows the community-index cache window.** RFC 2026-07-04-community-index accepts that a
  yanked/repointed listing can linger up to the 24 h index-cache TTL; for the *repointed-tag*
  case the install-time hash check catches it regardless of cache age.
- **Closes the flagship/community asymmetry** and resolves the "recommended `@ref`" open
  question (pinned refs now required).

**Harder / costs**
- **Every entry carries a hash that must be right.** For an immutable tag the hash is stable —
  a legitimate new release is a *new tag*, hence a new entry/PR, so the hash is naturally fresh
  at PR time. The one maintenance case is an author *re-cutting the same tag*, which is exactly
  the event we want to surface. `publish` emits the value and `check_index` prints the correct
  one on drift, so the toil is bounded to a copy-paste.
- **A required field is a well-formedness constraint.** New listings without a valid
  `content_hash` fail CI; the three existing entries are backfilled here.
- **Trust is relocated, not removed.** The guarantee rests on the index itself being fetched
  over a trusted channel (`raw.githubusercontent.com` on `main` + the repo's branch
  protection). Whoever can tamper with the index fetch can rewrite both URL and hash. "Do you
  trust the curator's index" is a far better anchor than "has no upstream tag ever moved," but
  it is trust-anchoring, not trust-elimination, and the docs must say so.

- **Tightens the `content_hash` compatibility contract.** The primitive is already load-bearing
  for `trusted.json` consent (RFC 2026-07-04-profile-fetch Reversibility: changing how it's
  computed mass-invalidates stored consent); binding the index schema to it too means a future
  change to the hash format would invalidate stored consents *and* every index entry at once.
  This feature is cheaply reversible in isolation (below), but it raises the cost of ever
  touching the shared definition.

**What we give up**
- Nothing that works today. Raw-URL installs are unchanged; the check is additive on the
  name path. Reversible: drop the field + the two checks and installs fall back to liveness.

## Alternatives considered

- **MD5.** Rejected. MD5 is collision-broken; a checksum whose job is to defend against a
  *malicious* byte swap must be collision-resistant, or an attacker crafts a colliding profile.
  The repo already standardizes on SHA-256 (`content_hash`, cache keys) — reuse it, don't add a
  weaker second algorithm.
- **Ship the hash alongside the bytes** (e.g. in the profile's own `profile.json`). Rejected:
  same trust domain as the bytes, so a tag-mover rewrites it too — it degrades to a
  corruption checksum, not a tamper control. The hash must live curator-side in the index.
- **Optional / verify-if-present.** Rejected: an attacker omits the field to skip the check,
  so the guarantee must be uniform. At three entries, backfill is trivial.
- **Warn-and-confirm on mismatch** instead of hard-fail. Rejected: a click-through warning
  weakens the guarantee to a nag, and the raw-URL escape already covers the deliberate "I want
  the moved bytes" case without a new consent-flow branch.
- **CI-only, no install-time check.** Rejected: it protects only people who read CI. The point
  is protecting the adopter at consumption; install-time is where the bytes actually land.
- **Skip-unchanged / "diff-only" to save fetches.** Rejected — and it does not do what it
  sounds like. Rot is *remote*; to know whether a tag drifted from the stored hash you must
  fetch and hash it, so a stored hash saves no network work. Its value is integrity, not fewer
  fetches; framing it as an optimization is a category error.

## RFC bookkeeping (on acceptance)

- **2026-07-04-community-index** — amends §3 (clarify integrity ≠ safety: the index still
  grants no *execution* trust; a verifiable hash is not a declared-safety tier), extends §6
  (name → URL now also carries the expected hash), and **resolves** its open question by
  requiring a pinned `@<tag>`.
- **2026-07-08-builtin-baseline-by-reference / 2026-07-03-profile-safety** — note the baseline
  hash gate is now the special case of a general per-entry integrity check; the consent gate
  remains the execution-trust boundary, unchanged.
- **`docs/architecture/profiles.md`** — update the Resolution / community-index section: name
  installs now verify the entry's `content_hash`; add the `content_hash` field to the entry
  schema description.
