# publish enforces the release invariants

- **Status:** Proposed
- **Date:** 2026-07-09
- **Author:** Luca Mastrostefano (drafted with Claude)
- [ ] Implemented

## Context

A profile release is defined by two things an adopter can see: the tag in its listing URL
(`…@v0.2.0`) and the `content_hash` of `profile.json` + `templates/`. The meta contract
scaffolded into every profile repo (`_SKELETON_AGENTS`, `profiles.py:1179`) spends its
"Verify, ship, and maintain" section teaching the author to keep those two honest, and it
says the quiet part out loud twice:

> `publish` hashes your *working tree*, so a stray untracked/ignored file poisons the
> emitted `content_hash`

> Nothing enforces this for you: `publish` never checks that you bumped.

Both are true, and both are load-bearing invariants left to human memory. The result is two
defects that publish is standing right next to and declines to catch:

**1. The tag is never checked against `profile.json`'s `version`.** `_publish` reads the tag
with `git describe --tags --exact-match` (`profiles.py:2501`) and splices it into the
listing URL (`:2074-2075`). Nothing strips the `v` and compares it to `prof.version`. This
is not cosmetic. `update` decides whether to pause on a breaking change by comparing the
version recorded in the adopter's `.agent-native-setup.json` against the version in the
newly fetched `profile.json` (`update.py:421-428` → `versioning.decide`), and it never
consults `content_hash` at all. An author who tags `v0.2.0` but forgets to bump
`profile.json` ships a release that records `0.1.0` on every adopter's machine, exactly as
the previous release did — so `versioning.decide` returns `NOOP`, the gate never fires, and
the new bytes apply anyway (they are hash-verified, and the hash is correct). A breaking
release passes through the major-version gate from RFC `2026-06-22-version-driven-updates`
in total silence. `content_hash` does not rescue this: it covers `profile.json`'s raw
bytes, so it *does* change, and publish cheerfully re-pins the index entry to the new hash.
The gate is defeated precisely because everything else looks correct.

**2. Publish hashes a different tree than it releases.** `content_hash(prof)` reads from
`profile.root` — the working tree (`profiles.py:2094` → `:1764` → `template_files()`,
`:198`, which `rglob`s every regular file on disk with zero git awareness).
`_release_steps` packs the asset with `git archive <tag>` — the committed tree
(`profiles.py:2422`), which drops untracked and ignored files. Nothing inside publish checks
the two agree, so a stray `.DS_Store`, `__pycache__/`, or `.claude/settings.local.json`
under `templates/` — the meta contract's own examples, at `profiles.py:1232-1233` — emits an
entry whose hash describes bytes no adopter will ever receive. It is caught eventually, by
`_asset_equivalence` in `tools/checks/check_index.py:26-58` when the listing PR hits CI — a
failure that surfaces in someone else's repo, one round-trip and one confused author later.

Constraints: the printed index entry is publish's contract and its fallback, and every tail
step degrades to it (RFC `2026-07-07-publish-opens-the-index-pr`). Publish must stay
scriptable — non-interactive runs never prompt. And the checks below must not fire on the
`--url` override path, where there may be no local git tag to compare against at all.

## Decision

Turn the two invariants the contract *documents* into invariants publish *enforces*. Both
are checks, not machinery; both are reversible by deleting them.

**1. Refuse a tag that disagrees with `profile.json`.** After `_git_tag` resolves a tag,
compare it to `prof.version` (accepting both `v0.2.0` and `0.2.0`). On mismatch, abort with
a message naming both values and the two ways out (`git tag -d` and re-tag, or bump
`profile.json`). This is an **error, not a warning** — a warning is what the meta contract
already is, and the failure mode it guards is silent and unrecoverable once adopters have
pinned. Skipped when `--url` is passed or no tag exists (today's untagged warning still
applies).

**2. Refuse a dirty release surface.** Before hashing, run

```bash
git status --porcelain --ignored -- profile.json templates/
```

and abort if it reports anything. **`--ignored` is the load-bearing flag**: plain
`--porcelain` lists untracked files (`??`) but hides gitignored ones by design, and the
ignored half is the more common poisoning vector — precisely the `.DS_Store` /
`__pycache__` / `settings.local.json` cases the contract warns about. A check without it
would enforce the smaller half of the invariant while appearing to enforce all of it. The
message names the offending paths and distinguishes the two classes, because the remedies
differ: commit or delete an untracked file; move an ignored one out of `templates/`
entirely, since `git archive` will drop it from the asset no matter what `.gitignore` says.
Skipped when `--url` is passed.

Both checks run **before** the entry is printed — they are preconditions for a *correct*
entry, so unlike the release and index-PR steps they must not degrade to printing one. A
poisoned entry is worse than no entry.

The meta contract at `profiles.py:1273` recommends the same check in prose, and recommends
it with the same blind spot (`git status --porcelain templates/`, no `--ignored`). Fixing
the engine without fixing the sentence that taught the gap would leave authors a documented
command that disagrees with the one publish runs, so the implementation updates both.

## Consequences

- The two silent failure modes become loud, local, and pre-emptive. The `update` gate stops
  depending on the author having remembered to bump.
- **Publish gains the ability to fail on a correct-looking repo.** An author who habitually
  tags `release-0.2.0`, or who has a `.DS_Store` under `templates/`, now hits a wall where
  they previously sailed through. That is the point, but it is a real behavior change for
  anyone mid-flight, and the error messages carry the whole burden of not being infuriating:
  each names the offending value and the exact command that resolves it.
- **The ignored-file refusal will fire on repos that publish fine today** — anyone on macOS
  with a `.DS_Store` under `templates/` is currently shipping a poisoned `content_hash` and
  does not know it, because `check_index` only runs against the *index* repo. Their next
  publish stops working. This is the change landing correctly, but it is the single most
  likely source of "you broke publish" reports, and it lands on people who did nothing new.
- `check_index`'s `_asset_equivalence` becomes a backstop rather than the first line of
  defense. It stays — it also catches a force-moved tag after the fact, which no local check
  can.
- We give up the ability to publish a listing for a working tree that isn't committed. That
  was never a coherent thing to do; the release asset never contained it.
- Both checks are pure refusals with no external effects, so this RFC opens no one-way door:
  reverting is deleting two guards. The one irreversible step in the neighborhood —
  creating the author's public repo — is deliberately left out (see below).

## Alternatives considered

- **Also absorb `gh repo create` behind a `--create-repo` flag.** The last manual step of the
  ship sequence, and the original motivation for looking here. Rejected on this repo's own
  precedent: RFC `2026-07-07-publish-opens-the-index-pr` weighed exactly this and recorded
  that printing a copy-pasteable command *"works for the repo-create step"* — the index PR
  got machinery only because *"there is no honest one-liner"* for it. Repo creation has an
  honest one-liner, and the meta contract already prints it. Absorbing it would also bundle
  the one outward-facing, irreversible action in the area (a public repo appears under the
  author's account) with two trivially reversible guards, letting the one-way door ride in
  on their coattails. If it is ever worth doing, it earns its own RFC and its own consent
  design.
- **Scaffold a `publish-profile` skill into every profile repo at `init`/`save`.** Give the
  profile-authoring agent an invocable procedure for the hard steps. Rejected. The procedure
  *already ships* — `_SKELETON_AGENTS` writes all six steps into the profile's root
  `AGENTS.md`, the nearest contract that agent reads (`profiles.py:1266-1292`) — and
  `.agents/skills/extract-profile/SKILL.md` phase 5 states them a second time. A scaffolded
  skill would be the third copy, and copies of this particular procedure rot: the publish
  protocol is central and versioned, having changed twice in two weeks (`content_hash`
  pinning, RFC `2026-07-08`; the auto-opened index PR, RFC `2026-07-07`), with RFC
  `2026-07-09-profile-license-metadata` proposing another field. The CLI resolves at
  `@latest`; a markdown procedure frozen into a profile repo at `init` time does not.
  Enforcement in the engine is the version of this idea that cannot drift — an agent that
  reads a stale procedure gets it wrong; an agent that runs a current `publish` gets told.
  If a skill still earns its place afterward, it should be *one* skill in this repo that
  `extract-profile` delegates to and the meta contract links, taking the copies from two to
  one rather than two to three. That is a separate, smaller change.
- **Warn instead of abort.** This is the status quo dressed up: the meta contract is already
  a warning, in prose, at the exact moment the author is reading about the invariant, and it
  did not hold. A defeated update gate is not recoverable after adopters have pinned.
- **Derive the tag from `profile.json` and tag automatically.** Deletes the mismatch by
  construction. Passed: tagging is the author's assertion that a commit *is* the release, and
  a `publish` that silently creates tags makes a rerun after a failed release step ambiguous
  (does it retag? move it?). Refusing a wrong tag keeps the assertion where it belongs and
  stays idempotent.
- **Hash the tagged tree instead of the working tree.** Makes defect 2 impossible rather than
  detected, and is arguably the more principled fix — it is what `git archive` already does
  for the asset. Passed for now because it silently publishes bytes the author may not have
  looked at, and because it would mask the `.DS_Store`-in-`templates/` mistake rather than
  teach it. The refusal surfaces the divergence instead of resolving it in the author's
  absence. Worth revisiting once the refusal proves noisy in practice.
- **A `task publish-profile` recipe.** The Taskfile is maintainer-side plumbing for this
  repo's index and releases; profile authors work in *their* repo, which has no Taskfile of
  ours. Wrong surface.
