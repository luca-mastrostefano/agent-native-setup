# A release-time version guard, tied to the migration registry

- **Status:** Active
- **Date:** 2026-06-23
- **Author:** Luca Mastrostefano
- [x] Implemented

## Context

The update model (RFC 2026-06-22) made the **release version a contract**: the bump *declares*
update difficulty, and the `--check` nudge + the changelog speak in its terms ("compatible
update" vs "major (breaking) update; review before applying"). The risk being mechanized here
is a **dishonest label** — an **under-bump** that ships a migration-bearing (breaking) change
as a compatible one.

What this is **not**: it is not "silent downstream breakage." The engine already self-heals
the dangerous part — `run()` computes `gated = decision == GATED or bool(agent_steps)`
(`update.py:310`), so a project that crosses *any* `agent`/`manual` migration is gated and
shown the migration steps **even if the version label says compatible**. So a mistagged
migration still applies safely downstream; what a mislabel corrupts is the **label's
honesty** — the `--check` nudge undersells the change, and the semver contract that the whole
model leans on stops meaning what it says. This guard keeps the *declaration* truthful at the
one moment it's chosen; it does not (and need not) re-police safety the engine already
enforces.

Three facts make this worth mechanizing:

- This project is **hatch-vcs / tag-derived** and releases often (v0.1 → v0.6 already), with
  the tag cut by `task release VERSION=X.Y.Z` — frequently by a coding agent. The bump is a
  judgment call made repeatedly, which is exactly where a guard pays off. (There's no version
  *file* to check per-commit; the bump *is* the tag, so enforcement belongs at release time,
  once per tag, not at commit time.)
- The project's identity is **mechanical-enforcement-over-memory** — it already gates RFCs,
  tests, and docs at commit time. The version, the one thing the whole update feature depends
  on, is currently unguarded. That's the inconsistency this closes.
- The **only mechanizable definition of "breaking" in this project** is *"ships an `agent`/
  `manual` migration"* — and that's already encoded, with a version, in `migrations.py`
  (`steps_in_span`, the `0.6.0` split). So the migration registry is the source of truth to
  check the release version against; we don't need to infer breaking-ness from commit prose.

## Decision

A small, tested guard wired into `task release VERSION=X.Y.Z`, run **before**
`gh release create`. `VERSION` is the **human-supplied input** the maintainer chose — the tag
doesn't exist yet (the task is about to create it; hatch-vcs only derives the package version
*from* the tag afterward) — which is precisely why it needs checking. It reuses
`versioning.breaking_series` — the same function the update gate keys on — so the release
boundary and the update boundary **cannot drift apart**.

`latest_tag` is read from **`gh release list` / `git fetch --tags` first**, not bare local
`git tag` — a stale clone must not weaken the forward-only check. Then, given `latest_tag` and
`VERSION`:

1. **Block a non-forward release** — `VERSION` must be strictly greater than `latest_tag`.
2. **Block an under-bump** — if any `agent`/`manual` migration is *activated by this release*
   (its version is in the half-open interval `(latest_tag, VERSION]`) but
   `breaking_series(VERSION) == breaking_series(latest_tag)`, refuse: a migration is this
   project's definition of breaking, so the bump must cross a breaking-series boundary (pre-1.0
   a minor, 1.0+ a major). The error names the offending migration and the version it implies.
   *The interval is half-open at the top deliberately:* the registry is append-only and may
   already hold an entry staged for a **future** version (`> VERSION`); such an entry isn't
   "activated" by this release and is correctly ignored. The check is on the **boundary**, not
   on `Migration.version == VERSION` exactly — so a deliberate over-bump (release a
   `0.6.0`-tagged migration as `0.7.0`) still passes, which is the intended latitude.
3. **Warn (not block) on a breaking bump with no activated migration** — usually fine (a
   breaking change that needs no migration, or a deliberate over-bump), occasionally a
   *forgotten* migration. A warning makes the human look without crying wolf.
4. **An explicit, logged override** — a release is a deliberate act and the human may, rarely,
   know better (e.g. a breaking change with no expressible migration). `RELEASE_FORCE=1` (or a
   `--force` flag) bypasses the block, printing what it overrode — an escape hatch, not a wall.

It ships the project's way: a **tested** check (a script with a unittest, like the other
shipped guards), wired as a `release`-task precondition. It lives in *this* repo's own tooling
and reads `agent_native_setup.{versioning,migrations}` — it is **not** generated into
downstream projects (they have no migration registry; this guards releasing *the tool*).

**Honest scope.** The guard enforces **label honesty** for the one case where "breaking" is
machine-knowable — a migration-bearing change must carry a breaking bump. It deliberately does
*not* try to keep downstream *safe* (the engine's `bool(agent_steps)` already does that, per
Context), and it **cannot** catch a *semantic* break in a pristine generated file that needs
no migration (the §8 residual): there's no machine signal for it, and Conventional Commits
wouldn't surface it either. That case stays human judgment; the step-3 warning is the only
nudge we can honestly offer. So this guards the *declaration*, not the *outcome* — a smaller,
honest win, not a safety net.

## Consequences

- The version label stays **honest by construction**: a migration-bearing release can't ship
  as compatible, so the `--check` nudge and the changelog mean what they say — and the semver
  contract the whole update model leans on stays trustworthy. Caught deterministically at
  release, the moment most likely to be fumbled by an agent cutting a tag.
- Small cost: a tested script + one task line, run once per release. No new dependency, and
  **no new boundary logic** — it reuses `breaking_series`, so the release guard and the update
  gate stay definitionally in lockstep.
- It does **not** remove human judgment for the residual (a no-migration semantic break), and
  the override keeps the guard from blocking a maintainer who genuinely knows better — at the
  cost that the override can be misused (logged, so at least it's visible).
- One more shipped check to keep green, but it's pinned to the registry the gate already
  requires to be honest, so it can't rot independently.

## Alternatives considered

- **Conventional Commits + an auto-derived bump** (`fix:`→patch, `feat:`→minor, `feat!:`→
  major): rejected. "Breaking" here is *migration-presence*, not commit-type — this would add
  process while missing the cases that matter and giving false confidence. (A typed-commit
  lint could be a separate nicety, but it's not the load-bearing piece.)
- **Full semantic-release / auto-computed version**: rejected — removes human judgment exactly
  where this project needs it (the "is this breaking for the update model" call), and adds a
  heavy toolchain for a tag-derived project.
- **Require `Migration.version == VERSION` exactly** (stricter than the boundary check):
  rejected — it forbids a legitimate over-bump (deciding at release that a `0.6.0`-tagged
  migration should actually ship as `0.7.0`). The boundary check is the real invariant; exact
  equality would block honest latitude for no safety gain.
- **Commit-msg-time enforcement** (like the RFC/test gates): rejected — hatch-vcs is
  tag-derived, so there's no per-commit version to check; the bump is a once-per-release act.
- **Documentation only**: rejected — the project's whole ethos is mechanical enforcement; a
  prose "remember to bump right" for the update feature's load-bearing invariant is the gap
  this closes.

## Resolved

- **Block under-bump + non-forward; warn the reverse** (breaking bump, no migration). The
  asymmetry matches the harm: an under-bump is an unambiguous false label (a migration *is*
  breaking), worth a block; an over-bump just gates a downstream user needlessly, worth a warn.
- **Provide an explicit, logged override** rather than a hard wall — a release is deliberate,
  and the residual (§ Honest scope) sometimes legitimately needs it.
- **Lives in this repo's tooling, not the generated output** — it guards releasing the tool.

## Open questions

- **Should a breaking bump with no migration eventually be a soft *block* with a waiver**
  (like the commit-msg gates' `RFC-Not-Needed:` trailer), rather than a warning? Leaning warn
  for now — most breaking-but-no-migration releases are legitimate, and a waiver adds ceremony
  for the rarer case. Revisit if a forgotten migration ever slips through.
