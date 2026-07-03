# Invert to an ecosystem core: the default becomes one profile, safety gates code

- **Status:** Proposed
- **Date:** 2026-07-03
- **Author:** Luca Mastrostefano
- [ ] Implemented

## Context

Today the tool has one privileged generator — the default scaffold — written as Python
(`cli.build` + the `generators/`). Profiles (RFC 2026-06-23) are a **declarative layer on
top**: templates, prompts, `env`, declarative startup. That split makes the default the
*heart* of the project, and not by choice: the default is the only thing that runs **logic**
(language detection, pins, the adoption CI variant, embedded check scripts), while a profile
is **data**. Whoever can run logic is the capable one, so the default is the center of gravity
and community profiles are permanently secondary — "skins on our engine," not peers.

We want to **invert** that: make the community-authored profile *ecosystem* the core, and the
default merely the official, in-box starter. Be precise about where we actually are: the
**composition and update *engine* is landed** — profiles compose or stand alone and carry
versioned updates (with a trust gate on new `session_start` commands, a version nudge, and
`profile validate`) — but the **ecosystem half is entirely unbuilt.** The authoring and
distribution pieces this direction rests on (`profile save`, git-URL/package fetch, a
registry/`contributions/`) are exactly the ones RFC 2026-06-23's status note still lists as *not
yet* shipped. So this RFC commits to a *direction* whose stage-A prerequisites do not exist yet;
that commitment is cheap and reversible (see §7-A), but it is a commitment on top of an unbuilt
distribution story, not a description of something already working.

Two things are missing, then: (a) that authoring/distribution layer, and (b) a way for a
community profile to be *as capable as the default* — which means running code — **without
exposing every user to arbitrary code by default.**

That last clause is the whole problem. Capability requires code; code requires trust. Resolve
the trust question and the code/data asymmetry that makes the default the heart dissolves. This
RFC records the decision to invert, the trust model that makes it safe, and the staged path.

## Decision

**1. Commit to the inversion as the north star.** The product is a *package manager and
composition engine for agent-native setups*. The default is the official profile that ships in
the box — a trusted-by-default participant in the same pipeline as every community profile, not
a privileged code path. "The tool" is the resolver/composer/updater/distributor; "the value" is
the catalog.

**2. Allow code-carrying profiles, gated by explicit consent.** This settles the fork between
*declarative-only* (safe, but the default stays the permanent heart) and *code profiles* (real
peers, but they run code). We take the second, with the burden placed on an informed, explicit
user opt-in — a `--allow-code` modifier — rather than on a fragile sandbox for untrusted code.
This matches ecosystem norms (npm install scripts, VS Code extensions, Terraform providers).
This **revises RFC 2026-06-23 §6**, which scoped the community `contributions/` dir to
declarative-only and treated code profiles as a separately-installed opt-in *not accepted into
that dir*. Here code profiles are a first-class, consent-gated path; that RFC's §6/§7 trust
sketch is superseded by the model below.

**3. Safety is *derived by the tool*, never *declared by the author*** — the load-bearing rule.
A `"safe": true` field is worthless against a malicious author. The tool classifies a profile
from what it actually contains, records the classification in the manifest, and demands the
modifier when it detects code. Two tiers:

- **safe** — writes files only, rendered in a **sandboxed** Jinja environment, output paths
  **confined** to the target (no `../` traversal, no symlink escape), and **not** into an
  *execution sink*. Installs and updates by default.
- **unsafe** — ships plugin/entrypoint code, **or** shell/session hooks (`session_start`,
  onboarding steps run by an agent), **or** writes into an execution sink. Requires
  `--allow-code`.

**4. "No code" is subtler than "no plugin" — two things we already ship count as code.** The
classifier must treat as unsafe:
- **Shell/session hooks.** `session_start` runs every session; onboarding steps are executed by
  an agent. This is exactly why the shipped `session_start` trust gate exists — it generalizes
  into this tier.
- **Writes to an execution sink** (code-by-proxy): a profile with zero plugin code can still own
  you by writing a file that something later *executes*. The invariant the safe tier must
  guarantee is therefore an **allowlist**, not a blocklist: *every output path is provably
  inert.* A blocklist of known sinks is the wrong shape — any sink not on it renders a
  code-carrying profile "safe" — and the list is unavoidably incomplete. Known sinks already
  include `.git/hooks/*`, `.claude/settings.json` SessionStart hooks, `.github/workflows/*` (and
  other CI), a `Makefile`/`Taskfile`/`justfile` you'll invoke, `pyproject.toml`/`package.json`
  build/lifecycle hooks, `.envrc` (direnv), the pre-commit config, `conftest.py` /
  `sitecustomize.py` (imported by the test runner / Python startup), `.vscode/tasks.json` and
  `.vscode/settings.json` (`python.defaultInterpreterPath` → arbitrary binary), `setup.cfg` /
  `tox.ini` entry points, and a `.gitattributes` filter driver — and that enumeration is
  *illustrative, not exhaustive*. Because it can't be exhaustive, the classifier's rule is
  **conservative-by-default: a write whose execution semantics aren't understood is treated as
  unsafe, not safe.** The stage-C/D RFC pins the mechanism (a positive "known-inert" set,
  extension/location heuristics), but the *shape* — allowlist + fail-closed — is decided here.

Also required for the safe tier to be *real*: render with `SandboxedEnvironment` (else a hostile
template can call Python) and confine output paths (else the writer's `path = self.target / rel`
has no traversal or symlink-escape guard). **Both landed** in RFC 2026-07-03-profile-safety.

**5. The gate holds across the lifecycle, not just install.** A profile installed *safe* whose
v2 adds a hook, a plugin, or a sink write must **re-require `--allow-code` on update** (or block),
so the boundary can't leak over time. This generalizes the existing new-`session_start` trust
gate. Consent is informed: as the shipped gate already does, show the *actual* code/hooks/sinks
that triggered the prompt, not just a count — the user approves what they can see.

**5a. Persistent execution is consented to distinctly from one-shot code — it must not ride in on
a one-shot approval.** A scaffold- or update-time code action runs *once* and its result is
visible in the `git diff` the user reviews. A `session_start`/hook, by contrast, runs *every
session, unattended, forever* — the diff can't reassure you about what it will do next month. So
these are not one risk: the consent prompt separates and labels them (as the shipped gate already
does, showing each command), a persistent-hook approval is re-confirmed on any update that
changes it, and — critically — persistent execution can never be granted implicitly by an
approval given for one-shot code. The exact modifier granularity (one `--allow-code` vs. a
distinct `--allow-hooks`) is a stage-C/D detail; the *principle* — that unattended, persistent
code demands its own explicit, re-confirmable consent — is decided here.

**6. The default is classified `unsafe`, trusted-by-default because it ships in-box.** It runs
code, so honesty demands the `unsafe` label; it's exempt from the prompt only because it's a
pinned, reviewed part of the tool itself. A nice side effect: this *pressures the ecosystem
toward safe/declarative profiles*, with code as the clearly-marked escape hatch. Caveat the
inversion creates for itself: today "in-box" is unambiguous (the default *is* the tool, so
upgrading the tool *is* consenting to the default's code). After stage D the default becomes a
fetched, versioned `default` plugin like any other, and "in-box" gets fuzzy — so the exemption
must be re-grounded on something that survives the inversion (e.g. the default profile being
signed/pinned by the tool's own release, not merely named `default`). Naming this now so #6
isn't quietly undermined by #7-D.

**7. Sequencing — cheapest and most reversible first.** Each stage shifts the center of gravity
further; we do not build the deep end first.

- **A. Reframe + distribution.** `profile save`, git-URL/package fetch, a registry/index,
  `profile search`/`show`/`add`. The product identity flips to "package manager for agent-native
  setups; ships with one good default." No capability change, fully reversible.
- **B. No privileged path (dogfood).** Route the default through the same resolve → compose →
  apply → update pipeline community profiles use; treat it as "our profile." A forcing function:
  once our own default is *just our profile*, the ecosystem is structurally the core.
- **C. Module registry.** Decompose the default into registered, individually
  selectable/replaceable modules — extend the existing `Language`-registry pattern to agents,
  the quality gate, docs/RFC conventions, and security. Core = composition engine + registry;
  default = a curated bundle of modules.
- **D. Code/plugin profiles.** A plugin API behind the safe/unsafe gate; extract the default's
  generators into the `default` plugin so the engine has no privileged path. Full inversion.

Build the **safety model (points 3–6) as the precondition to C/D** — you cannot safely allow
code without it. A and B are declarative distribution and don't need it. **C and D each get their
own detailed RFC before implementation;** this RFC commits to the direction, the fork's answer,
and the trust foundation.

## Consequences

**Newly possible / easier**
- Teams and the community ship *full* setups, not skins; the tool's value compounds with the
  catalog instead of being capped by our one opinion. The default stops being the bottleneck.
- Capable community profiles (code) without exposing everyone — the safe tier is the default
  experience, code is opt-in and visible.
- A dogfood-forced architecture (stage B): no back door means our default can't quietly stay
  special.

**Harder / what we take on**
- **A supply-chain surface.** We now distribute and (for `unsafe` profiles) run community
  artifacts. That is a security posture the project doesn't have today.
- **The classifier must be correct.** A misclassification — code that reads as safe — is silent
  arbitrary execution. This is the single most safety-critical component; it needs adversarial
  tests and a conservative default (unknown ⇒ unsafe).
- **`--allow-code` fatigue.** Habitual approval is the known failure mode of consent gates.
  Mitigate by showing exactly what triggered it (the shipped-gate pattern), and by making the safe tier
  genuinely capable so most profiles never need the modifier.
- **Registry governance** (curation, provenance, yanking a bad version) becomes an ongoing
  responsibility once distribution exists.

**What we give up**
- The simplicity of "one trusted generator." The tool becomes a platform, with a platform's
  governance and security obligations.

**Reversibility.** A and B are reversible. C is cheap to reverse *only while the registry stays
internal* — once it becomes the public extension surface that third-party modules target, it
approaches a one-way door, so keep it internal until D actually opens it. D — running untrusted
code — is the hard one-way commitment on the security surface, which is *why* it is gated behind
the derived classifier, explicit consent, and building the safety model first.

## Alternatives considered

- **Declarative-only, never allow code.** Safe and simple, but it cannot achieve the inversion:
  the default stays the permanent heart and community profiles are capped at configuration.
  Rejected as the north star — but *retained as the `safe` tier*, so the everyday experience is
  exactly this, with code as the escape hatch.
- **Author-declared safety (a `"safe": true` field).** Rejected outright: worthless against a
  malicious author. Safety must be tool-derived (point 3).
- **A full sandbox for untrusted code (run everyone's code locked-down, no consent needed).** A
  much larger and leakier engineering surface, and it still can't safely grant the filesystem and
  generator access a real profile needs. The consent model is simpler and matches ecosystem norms;
  the *user*, not a fragile sandbox, is the trust anchor for code.
- **Keep the default privileged, just add distribution.** That is stage A in isolation — valuable,
  but it leaves the asymmetry intact. It's a subset of this plan, not an alternative to it.

## Open questions (for the stage-C/D follow-up RFCs)

- The exact "known-inert" allowlist and sink heuristics, and how the classifier stays current as
  new sinks appear (the *shape* — allowlist + fail-closed — is decided in §4; the mechanism is not).
- The modifier granularity for §5a's decided principle: one `--allow-code` covering both one-shot
  and persistent code, or a distinct `--allow-hooks` for persistent execution.
- The plugin API surface and its isolation model (process boundary? capability limits?).
- Registry shape: a reviewed `contributions/` in-repo vs. a git-URL/package index vs. both.
