# Profile safety: derived classification, sandboxed rendering, path confinement, update re-gate

- **Status:** Active
- **Date:** 2026-07-03
- **Author:** Luca Mastrostefano
- [x] Implemented

> **Status note:** the content-based core **landed** — `profiles.classify_safety` (derived tier,
> allowlist + fail-closed), **sandboxed rendering** (`SandboxedEnvironment` — the base scaffold
> renders clean under it), **path confinement** in `apply` (refuses an output escaping the target),
> the recorded manifest `safety` tier, the **safe → unsafe update re-gate**, and the `validate`/
> `save` wiring. The consent gate + trust model deferred to the fetch RFC (§5) landed there
> (RFC 2026-07-04-profile-fetch, Active) — this slice is complete.

## Context

RFC 2026-07-03-ecosystem-core set the *direction* — allow code-carrying profiles, gated by a
**tool-derived** (never author-declared) safe/unsafe classification and an explicit `--allow-code`
consent — and deferred the **mechanism** to this RFC. It is the precondition for the last stage-A
piece, **git-URL / registry fetch**: you cannot responsibly consume a profile you didn't write
without (a) knowing whether it runs code and (b) not being silently owned by a template.

Two of the mechanism's parts are also **holes today**, independent of fetch:
- Templates render through a plain Jinja `Environment` (`scaffold.py`), so a hostile `.j2` can
  reach Python via attribute access and execute at scaffold time.
- The overlay writer (`Scaffolder.overlay`) does `path = self.target / rel` with **no traversal or
  symlink-escape guard** — a profile output path of `../../.ssh/authorized_keys` would escape the
  target.

So even before fetch exists, a profile shared by a colleague or copied from anywhere can path-
traverse or Jinja-escape. This RFC pins the classifier *and* closes those two holes, so the "safe"
tier is actually safe and fetch has a foundation to build on.

## Decision

**1. A derived classifier.** `profiles.classify_safety(profile) -> (tier, reasons)` where `tier`
is `"safe"` or `"unsafe"` and `reasons` is the concrete list of what made it unsafe. It inspects
*content*, never a declared field:
- **`session_start`** present → unsafe (**persistent** — runs every session; the loudest tier per
  ecosystem-core §5a).
- **`onboarding`** present → unsafe (agent-executed steps — `ln -s`, or worse).
- a **template output path** (after `.j2`-strip) that is an **execution sink** *or is not
  provably inert* → unsafe. Per ecosystem-core §4 the rule is **allowlist + fail-closed**, realized
  as: a known-**inert** set (Markdown/text/data docs, `.claude/agents|commands/*.md`, `.gitignore`,
  `.editorconfig`, `LICENSE`, and the like) is safe; a known-**sink** set (`.git/hooks/*`,
  `.github/workflows/*`, other CI, `Makefile`/`Taskfile`/`justfile`, `pyproject.toml`/
  `package.json`, `conftest.py`/`sitecustomize.py`, `.claude/settings.json`, `.vscode/*`,
  `setup.cfg`/`tox.ini`, `.gitattributes`, `.envrc`, the pre-commit config) is unsafe; **anything
  unrecognized defaults to unsafe.** (Future code/plugin entrypoints — not built — are unsafe by
  the same rule.)

**2. Path confinement — a hard refusal, for *every* profile (safe or unsafe).** Before applying
any profile, reject an output path that escapes the target: `..` traversal, an absolute path, or a
path that resolves (via an existing symlink) outside the target root. This is **not a tier** — a
profile that tries to write outside the project is malicious/broken and is refused outright, with
the offending path named. Independent of the safe/unsafe split.

**3. Sandboxed rendering — for *every* profile.** Render `.j2` templates through Jinja's
`SandboxedEnvironment` (and validation's strict env likewise), so a hostile template can't call
Python via attribute/method access. Hardening of the existing render path; applies regardless of
tier.

**4. Record the derived tier; re-derive on update.** At scaffold, store the classifier's tier in
the manifest's profile block. On `update`, re-resolve the profile, re-derive the tier, and treat a
**safe → unsafe** transition (or new unsafe content) as a **confirmation gate** — reusing the
existing `_confirm_gate` (interactive confirm; `--yes` consents; a non-tty run without it is
blocked). This is content-based — it needs no provenance — and generalizes today's
new-`session_start` gate into "this update introduces code you haven't consented to."

**5. The scaffold-time consent gate — and the trust model it needs — are deferred to the fetch
RFC.** A gate that fires *before applying an untrusted profile* only has teeth once untrusted
sources exist, which is fetch. And the load-bearing question — *what counts as trusted?* — must be
answered where provenance is real. Keying trust on how a `--profile` reference is *spelled* (local
path = trusted, URL = untrusted) is a **loophole**: `git clone <evil> && agent-native-setup
--profile ./evil` reads as a local path and would be "trusted", re-opening exactly the
copied-from-anywhere threat this RFC's Context names. So the durable model — most likely
**per-artifact consent by content hash** (trust a specific artifact, not a path or a moving
target), matching the pre-trust principle sketched in RFC 2026-06-23 — is decided in the fetch RFC,
alongside the provenance it governs. **This RFC ships no provenance/consent gate.**

What lands now is **content-based and needs no provenance**: the classifier (§1), path confinement
+ sandboxed rendering (§2-3, the live holes), the recorded tier + the **update re-gate** (§4), and
the `validate`/`save` disclosure (§6). The gate for *first use of an untrusted profile* arrives
with fetch, on the trust model decided there.

**6. Wire the surface to the real classifier.** `profile validate` reports the derived tier;
`profile save` replaces its current heuristic disclosure (a hand-kept sink list) with a
`classify_safety` call — one source of truth. The `default` scaffold classifies `unsafe` (it
writes CI, ships hooks) — the honest tier; that's disclosure only for now (no scaffold gate), and
it keeps pressure toward safe/declarative profiles. The classifier **ships functional even with a
minimal inert set**: everything unrecognized is `unsafe`, so it produces a correct (if
conservative) verdict from day one, and the inert set grows to earn more profiles a `safe` verdict.

**Scope.** Builds: the classifier, path confinement, sandboxed rendering, the manifest tier +
content-based update re-gate, and the `validate`/`save` wiring. Defers: the **scaffold-time consent
gate + its trust model** (to the fetch RFC — §5); git-URL/registry **fetch** itself (its own RFC —
this unblocks it); **code/plugin** entrypoints (no code-profiles exist yet — "unsafe" today means
hooks + sinks, not arbitrary plugins); and any **OS-level sandbox** for execution (ecosystem-core
chose the *consent* model — the user, not a leaky sandbox, is the trust anchor for code; the Jinja
sandbox here is only to stop render-time escape, not to contain approved hooks).

## Consequences

**Newly safe / possible**
- **The "safe" tier becomes real today**: sandboxed rendering and path confinement close actual
  escape holes that exist right now for any shared/local profile, fetch or not.
- **Fetch is unblocked**: the classifier + hardening it needs are met, so a later fetch RFC can add
  the consent gate on a real trust model rather than inventing the whole safety story at once.
- **One source of truth** for "is this code-carrying": `save`, `validate`, and update all call the
  same derived classifier — they can't drift.

**Harder / costs**
- **The classifier must be correct**, and fail-closed (unknown ⇒ unsafe) is the safety-critical
  default — it needs adversarial tests (a template that writes a sink under a `.j2`, a traversal
  path, a Jinja escape attempt).
- **Sandboxing may reject a template that used a now-blocked Jinja feature.** The base scaffold and
  the example profile must render clean under `SandboxedEnvironment`; a real regression risk to
  test up front.
- **Maintaining the inert/sink sets** is ongoing (new sinks appear); fail-closed limits the blast
  radius of a miss (an unrecognized path is unsafe, not silently safe).

**What we give up**
- **Rendering permissiveness.** `SandboxedEnvironment` and path confinement are *behavior-narrowing*,
  not purely additive: a template that renders today under the plain `Environment`, or writes a path
  we now confine, may be **refused** tomorrow. We accept that — the base scaffold and example
  profile must be verified clean under the sandbox up front — because the alternative is a render
  path that can execute arbitrary Python.
- The content-based update re-gate adds one confirmation to an update that newly introduces
  hooks/sinks — intended friction, but friction.

## Alternatives considered

- **Author-declared safety** (`"safe": true`). Rejected in ecosystem-core and here: worthless
  against a malicious author. The classifier derives the tier.
- **Ship a provenance-based consent gate now** (local path/`~/.config` = trusted, URL = gated).
  Rejected: it keys trust on how a reference is *spelled*, so `git clone <evil> && --profile ./evil`
  reads as "trusted" — a loophole that leaves today's real channel (cloned/copied dirs) ungated
  while protecting only the channel that doesn't exist yet (fetch). Deferring the gate to the fetch
  RFC, where the durable model is **per-artifact consent by content hash**, is both safer and
  simpler than baking in a provenance model this early.
- **Gate every unsafe profile on every use, regardless of anything.** Rejected: a consent prompt on
  each use of a profile you authored locally is daily friction; the durable answer (content-hash
  pre-trust: consent once per artifact, remember it) belongs with fetch, not here.
- **A pure allowlist (only pre-approved inert paths ship; everything else refused).** Too
  restrictive — it would refuse a profile shipping a novel-but-harmless file. The chosen hybrid
  (known-inert safe, known-sink unsafe, unknown ⇒ unsafe *tier*, not refusal) fails closed on the
  *tier* without blocking legitimate content.
- **An OS-level sandbox for approved hooks.** Rejected per ecosystem-core: a real sandbox is large
  and leaky, and consent is the chosen trust model. The Jinja sandbox here is scoped to render-time
  escape only, not to contain code the user approved.
- **Defer everything until fetch is built.** Rejected: the sandbox + path-confinement holes are
  exploitable *now* by any shared profile, and fetch cannot be built safely without the classifier
  — so the foundation must come first.

## Open questions (for implementation)

- The exact **known-inert** set and how it grows without re-touching code each time (a data table?
  extension + directory heuristics?). Ships functional with a minimal set (unknown ⇒ unsafe).
- Whether path confinement should **hard-refuse** an escaping output path (abort the whole
  scaffold) or **skip** it with a loud warning. Refusal is safer against a malicious profile;
  skip is friendlier to a merely-buggy one. Leaning refusal.

Deferred to the **fetch RFC** (where provenance is real): the trusted/untrusted model
(content-hash pre-trust vs. source scheme), the `--allow-code` / `--allow-hooks` consent
granularity (ecosystem-core §5a decided the *principle*; the CLI shape is open), and whether a
`~/.config`-installed profile is trusted at install-time.
