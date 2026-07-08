# Builtin baseline by reference: fetch the pinned flagship, don't vendor it

- **Status:** Active
- **Date:** 2026-07-08
- **Author:** Luca Mastrostefano
- [x] Implemented

## Context

The engine ships a **vendored copy** of the flagship profile — `profiles/agent-native-baseline/`
(profile.json + templates), baked into the wheel as `_baseline`, hash-pinned via
`profiles/baseline-pin.json` (tag + content hash). `resolve("builtin:agent-native-baseline")`
loads it from disk with zero network, and RFC 2026-07-05 (Decision 5) chose this for offline,
reproducible, supply-chain-safe default scaffolding.

Two costs have proven real:

1. **The baseline lives in two places.** Its own repo (`agent-native-baseline`, the source of
   truth, tagged and index-listed) and a vendored copy here. Every baseline release needs a
   re-vendor + pin bump in the engine, and the copy can drift (caught by CI, but it's ceremony).
   The engine — meant to be content-neutral after the RFC 2026-07-05 flip — still carries the
   flagship's bytes.
2. **Content-release decoupling is only partial.** A baseline fix reaches index-fetched adopters
   immediately, but the *default* scaffold (`-o .`, no `--profile`) rides the vendored copy and
   so waits for an engine release.

The offline guarantee that justified vendoring does not earn its keep here: **this tool always
drives a coding agent, so it is effectively never run air-gapped.** Trading a rare-to-nonexistent
offline default for a single source of truth is a deliberate, accepted call (maintainer decision,
2026-07-08). This RFC reverses Decision 5 of RFC 2026-07-05.

The constraints that must survive the change: the default run stays **consent-free** (it must not
hit the fetched-`unsafe`-profile gate every time — the baseline ships execution sinks, so it
classifies `unsafe`); output stays **reproducible per engine release** (a given engine version
scaffolds the same baseline, not whatever the repo serves today); and the **test suite stays
hermetic** (it must not depend on live network to scaffold the default).

## Decision

**Resolve `builtin:agent-native-baseline` by fetching its hardcoded, pinned git URL and verifying
the bytes against `baseline-pin.json`'s content hash — then trusting it as builtin. Remove the
vendored files from the repo and the wheel.**

### 1. `builtin_baseline_root()` fetches + verifies

`baseline-pin.json` stays, minus the files it used to point beside: `{name, repo, url
(git+https://…@<tag>), tag, content_hash}`. `builtin_baseline_root()`:

1. reads the pin;
2. calls the existing `_fetch_git(pin.url)` — which already does asset-first for pinned GitHub
   tags, clone fallback, **caches pinned refs forever**, and reuses a stale cache on fetch failure;
3. `load`s the fetched dir and computes `content_hash`;
4. **verifies it equals `pin.content_hash`** — a mismatch is a loud `ProfileError` (the pin is the
   supply-chain trust root; the engine only trusts bytes it was released against), never a silent
   fallthrough;
5. returns the cache path.

`resolve` is otherwise unchanged: it still passes `source="builtin:agent-native-baseline"`, so
`is_untrusted_source` returns False and the default run is **consent-free** — but now that verdict
rests on the hash check in step 4, not on the bytes being local. The pinned tag is immutable by the
baseline repo's ruleset, so the fetched bytes can't be repointed under a released engine.

**Step 4 gates every resolution — a fail-closed property, not an assertion.** The hash check lives
in `builtin_baseline_root()` and runs after *every* `_fetch_git` return: the network fetch, the
"reuse pinned cache, no network" hit, and the stale-cache-on-failure path alike. So even cached or
stale bytes are re-verified on each call — no path reaches "trusted builtin" without matching the
pin. And because `_fetch_git`'s cache key is `sha256(spec)[:16]` over the *full* URL including
`@<tag>`, a **bumped pin resolves to a different cache dir**: an old tag's stale cache can never be
served under a new pin. The consent-free guarantee is therefore demonstrably anchored to the hash,
cache hits included.

### 2. Pinned, not floating

The URL pins `@<tag>` (bumping the baseline = a one-line `baseline-pin.json` edit: new tag + new
hash — still an engine change, but a trivial one, no re-vendor). Floating `@latest`/`@main` is
rejected: it can't be hash-pre-verified, so it would force either a consent prompt on every default
run or blanket-trusting whatever the repo serves — losing exactly the reproducibility and
consent-free trust this section preserves.

### 3. Offline is out of scope, softened by the cache

The **first `builtin:` resolution on a cold cache** needs network; a fetch failure there is a clear
error ("couldn't fetch the builtin baseline — network/GitHub required for the first run"). This is
*not* only the first scaffold — `builtin:agent-native-baseline` is re-resolved by several call
sites, each of which now needs a warm cache on a cold machine:

- **scaffold** (`cli.main` resolving the default);
- **`update`** — a default-scaffolded project records `source="builtin:agent-native-baseline"`;
  `update`'s re-resolve (`update.py` `_reresolve_profile`) and the background staleness nudge
  (`_notify_if_outdated`) both re-resolve it, so updating a long-ago scaffold on a *different* cold
  machine now fetches;
- **`profile save`** — see §4 (mitigated).

Because pinned refs cache forever, **every subsequent run is offline-capable from the cache**, and a
later transient failure reuses the stale cache with a warning (existing `_fetch_git` behavior). So
the regression is bounded to the *first* `builtin:` touch on a machine — but that first touch may be
an `update` or a staleness check, not necessarily the initial scaffold. Each of these paths must
surface the same legible error, not a stack trace.

### 4. Remove the vendored files; keep a dev/test fixture out of the wheel

Delete `profiles/agent-native-baseline/**` from the shipped package and drop its `_baseline`
force-include from the build; the wheel instead force-includes `profiles/baseline-pin.json` (the pin
the engine reads at runtime). The **shipped wheel carries no baseline bytes**, only the pin — the
objective.

**`profile save` must not gain a network dependency.** It currently reads the baseline's `transient`
set (`load(builtin_baseline_root()).transient`) only to exclude the first-run apparatus from a
snapshot — a project-local, offline-feeling operation. Fetching the whole baseline just for that
list is wrong. Resolution: **bake the transient list into `baseline-pin.json`** (a handful of static
paths — `ONBOARDING.md` + the `/onboard` triggers) and have `profile save` read it from the pin, so
snapshotting never touches the network. The pin is regenerated at baseline-release time anyway, so
the list stays in sync mechanically.

**Test hermeticity — a test-only stub, not a shipped override.** The suite must scaffold the default
offline while faithfully recording `source="builtin:agent-native-baseline"`. An env-var path
override can't do this: pointing resolution at a local dir would record *that path* as `source`,
breaking every default-scaffold test that asserts the `builtin:` provenance. So instead a
`tests/conftest.py` autouse fixture **monkeypatches `builtin_baseline_root` to return a checked-in
fixture** (`tests/fixtures/agent-native-baseline`, byte-identical to the pinned release, a dev
artifact never packaged). This keeps `resolve`'s `builtin:` source intact, needs no network, and
ships nothing. Tests marked `real_baseline_fetch` opt out to exercise the true fetch+verify path.
`check_baseline_pin.py` verifies the fixture hashes to the pin (offline) and the live tag hashes to
the pin (online), so the fixture can't drift — the same guarantee the vendored copy had, minus the
shipped bytes.

A configurable production override (e.g. an `AGENT_NATIVE_SETUP_BUILTIN_SOURCE` for exact mirrors)
is **deliberately not built** (Simplicity First): the only concrete need is hermetic tests, met by
the stub above, and a team wanting a *different* default already has `--profile <their-url>`. A
hash-checked `git+` mirror override can be added later if a real consumer appears — its absence
avoids a shipped, security-sensitive env var no one is using yet.

### 5. Verification workflow re-grounds on the pin

The `index-check` workflow already fetches the baseline through both transports and fails on hash
mismatch (the poisoning tripwire). With no vendored copy to diff, the engine-side checks re-ground
on the pin. Concrete touch-points, all currently anchored on the vendored tree:

- **`tools/checks/check_baseline_pin.py`** hashes `profiles/agent-native-baseline` unconditionally
  (before its online branch), so removing the files breaks both its offline and online modes. It
  becomes "`baseline-pin.json.content_hash` equals the live tag's fetched hash" — the same
  guarantee, minus the local bytes. Its unit tests (`tools/checks/test_check_baseline_pin.py`)
  move with it.
- **`tests/test_flagship_parity.py`** asserts against the vendored copy; the whole-tree parity
  harness (generators vs. vendored output, RFC 2026-07-05 stage A) loses its vendored operand. It
  re-points at the checked-in fixture / pinned fetch, or — since parity is stage-A/stage-D
  transitional scaffolding for the generators being deleted — is retired with them. Decided in
  implementation; listed here as a known touch-point.

## Consequences

**Easier / newly possible**
- **One source of truth.** The baseline lives only in its own repo; releasing it is a pin bump, not
  a re-vendor. The engine carries no flagship bytes — content-neutral in fact.
- **Simpler release step:** update two fields in `baseline-pin.json`; no file copy, no `_baseline`
  packaging.
- **Smaller wheel.**
- Private deployments wanting a *different* default point `--profile` at their own URL (already
  supported) — no engine patch or re-vendor needed.
- **No new shipped attack surface.** The env-var override the earlier draft proposed is not built;
  hermetic tests use a test-only monkeypatch stub instead, so a released wheel gains no
  environment-controlled, hash-exempt, consent-free code path.

**Harder / costs**
- **The cold-cache first run needs network** and fails without it. Accepted: the tool always drives
  an agent, so offline-first-run is out of scope. Documented, with a legible error.
- **Reproducibility is now network-conditioned.** A released engine scaffolds the pinned tag *when
  reachable and hash-matching*; it can no longer guarantee byte-identical output from a cold cache
  offline. The immutable tag + hash keeps it reproducible when online; a deleted/unreachable tag
  fails loudly rather than drifting.
- **First-run latency:** one clone/asset fetch (then cached).
- **Test hermeticity rests on a conftest stub + fixture** rather than the vendored copy being
  always present. A test-only baseline copy remains in `tests/fixtures/` (out of the wheel), and it
  carries a **sync ceremony**: on a baseline release the fixture must be re-synced to the new pinned
  tag — `check_baseline_pin.py` fails if it drifts. This is the same re-vendor ceremony as before,
  moved from the shipped wheel to a dev fixture (the point: it no longer ships).
- **Trust hinges entirely on the hash check.** If it is ever weakened, a repointed tag could feed
  unexpected bytes into a consent-free run. The check is the security boundary and must fail closed —
  and it runs on every resolution, cache hits included (§1).

## Alternatives considered

- **Keep vendoring (status quo, RFC 2026-07-05 Decision 5).** Offline, reproducible, fast — but the
  duplicated copy and partial decoupling are the friction this RFC exists to remove, and the offline
  benefit doesn't apply to an always-online tool. Rejected per the maintainer call.
- **Vendor-as-fallback (fetch when online, fall back to a bundled copy).** Keeps offline *and*
  picks up fixes — but it *keeps the vendored bytes in the wheel*, which is precisely what we're
  removing, and adds fetch-vs-fallback branching. Rejected: it optimizes for the offline case we've
  chosen to drop.
- **Floating `@latest`.** Maximal decoupling, but forfeits hash pre-verification → consent prompt or
  blanket trust on every default run, and non-reproducible output. Rejected (see §2).
- **Delete the pin, trust any bytes at the URL.** Removes the supply-chain anchor and the
  consent-free guarantee. Rejected.

## Reversibility

Re-vendoring is straightforward (restore the files + `_baseline` packaging + the old
`builtin_baseline_root`), and `baseline-pin.json` already carries everything needed to reproduce
the vendored copy from the tag. The one-way-ish part is the **cache/trust semantics** users will
have relied on (a warmed cache, the override env var); reverting is safe but the offline-first-run
guarantee, once dropped and documented, is a support-expectations change more than a code one. Low
reversal cost overall — this is far cheaper to undo than the RFC 2026-07-05 flip it amends.

## RFC bookkeeping (on acceptance)

- **2026-07-05-engine-and-flagship-profile** — amends its **Decision 5** (vendored, wheel-embedded
  flagship): the default is now fetched-by-pin, not vendored. Its stage-A whole-tree parity harness
  loses the vendored operand (§5 here).
- **2026-07-04-profile-fetch / 2026-07-03-profile-safety** — the `builtin:` scheme stays
  trusted/consent-free, now gated on the `baseline-pin.json` hash rather than local provenance;
  note the hash as the trust anchor.
- **`docs/architecture/profiles.md`** and **`overview.md`** — update the Resolution section and the
  index row (builtin now fetches the pinned URL, verifies the hash, caches); drop the "vendored copy
  embedded in the wheel" description and re-point the moved README link.
- **`.github/workflows/quality.yml`** — the wheel-contents assertion flips from "embeds
  `_baseline/`" to "ships `baseline-pin.json` and **no** baseline bytes".
- **`CONTRIBUTING.md`** — the rebuild-templates command path moves to the fixture.
- **`tools/checks/check_baseline_pin.py`** (+ its tests) and **`tests/test_flagship_parity.py`** —
  re-ground on the fixture/pin (§5).
