# Extending community profiles is git-native (no `extends: <url>` chains)

- **Status:** Proposed
- **Date:** 2026-07-04
- **Author:** Luca Mastrostefano
- [ ] Implemented

## Context

The mission is a community that **converges** on good scaffolding: profiles that are adopted,
searched, and **extended**. Adoption and discovery work end-to-end (fetch RFC 2026-07-04,
community-index RFC 2026-07-04). Extension has no *tool* support: `extends` accepts only
`"default"` or `null`, so a team that wants "the community `python-backend` profile plus our
three house files" must copy it. RFC 2026-06-23-scaffolding-profiles anticipated exactly this
under "Deferred experience refinements" (**N-layer composition** — `extends: <another-profile>`,
build when demand appears). The feature was designed far enough to cost it out — recursive
resolution, cycle/depth guards, per-layer trust, flatten-at-resolve composition. This RFC
records why we are **not** building it, and retires that deferred item.

## Decision

**Extension is git-native: fork the base profile's repo, keep `upstream` as a remote, edit, tag,
publish.** The profile format does not change (`extends` stays `"default" | null`); we ship a
documented recipe, not machinery:

```bash
git clone https://github.com/acme/python-backend-profile.git my-profile
cd my-profile && git remote rename origin upstream
# edit templates/, bump name/version in profile.json, git tag v0.1.0, push to your own repo
# later, to take the base's improvements — reviewed, then released to your consumers:
git fetch upstream && git merge upstream/main   # then bump version + tag
```

Why the fork wins over an in-tool `extends: <url>`:

- **The real trade is auto-flow vs. review-in-the-middle — and review wins.** Chains give
  consumers un-overridden base files *automatically*, with no extender action; the fork requires
  the extender to `git fetch upstream && git merge` and cut a release. That manual step is the
  point: the extender reviews base changes before releasing them to their own consumers, instead
  of base changes piping past them gated only by a consent hash the end consumer can't
  meaningfully evaluate. "Forking severs updates" is false with a remote — the update stream
  survives, relocated to the layer where a human should be.
- **When base and extender touch the same file, git resolves it; an overlay can't.** Chain
  composition is whole-file overlay-wins (the model `extends: default` ships): once the extender
  overrides a file, base improvements to that file stop reaching anyone downstream, silently.
  Git's three-way merge combines both edits (or surfaces a conflict to resolve once). For the
  files the extender *doesn't* touch, the two models tie — so the mechanism only differs where
  the overlay is worse.
- **It's vendoring, a norm people know.** A fork with an `upstream` remote is exactly the
  vendored-dependency workflow: you own your copy, you pull upstream deliberately, your
  consumers get *your* releases. (It is *not* the npm transitive-range model — package managers
  do float transitive deps without the middle package releasing — and we choose vendoring
  deliberately, for the review property above.)
- **The delta stays visible** — `git diff upstream/main` is the "what did we change on the base"
  view, better than reading an overlay directory against a mental model of the base.
- **What we don't build**: chain resolution (network-dependent, breaks anywhere → breaks
  everything), cycle/depth guards, per-layer consent, degraded-update handling for unreachable
  bases, and merge-semantics documentation. Single-layer profiles keep the existing trust model
  untouched — one artifact, one hash, one gate.

The consumer side is unaffected and already solved: projects scaffolded from the fork get its
releases through the existing `update` (managed files, conflict classify, version gates,
re-consent on content change).

This supersedes the parent RFC's deferred **N-layer composition** item, and with it the
instruction to keep the manifest's layer stack "designed for N": with extension permanently
git-native, the stack is `[default, profile]` forever and that forward-compatibility guidance
has no remaining customer.

## Consequences

**Easier**
- Zero new code or format surface; the trust model stays single-layer (the entire fetch/consent
  RFC applies unchanged).
- Extenders use tools they already know; the recipe is four git commands.

**Harder / costs**
- **Taking base updates is a manual, per-fork act.** An extender who never runs
  `git fetch upstream` drifts silently — there is no in-tool "your base has moved" nudge. Accepted:
  that nudge is `git fetch`; re-implementing it inside the wizard is the machinery this RFC
  declines. If real forks rot in practice, a `profile show`-style staleness hint can be revisited.
- **A fork carries the whole base** (all files, not just the delta). The delta view is
  `git diff upstream/main`, which requires keeping the remote — the recipe's one habit to learn.
- **`#subdir=` profiles fork awkwardly** (you clone the monorepo). Accepted: standalone profile
  repos are already the documented publishing shape; subdir profiles are the convenience case.

**What we give up**
- Automatic transitive updates (base → overlay-consumers with no extender action). Deliberately:
  see review-in-the-middle above.

**Reversibility**
- Nearly free to reverse: no format change, no recorded state, no shipped mechanism. If demand
  proves out an in-tool composition later, `extends: git+<url>` can be added without breaking
  any fork made under this recipe (a fork is just a profile). This RFC is a recorded rejection
  to prevent re-litigation, not a one-way door.

## Alternatives considered

- **`extends: git+<url>` with recursive chains** (visited-set cycle guard, depth cap, per-layer
  content-hash consent, flatten-at-resolve composition). Fully designed, then rejected: on
  shared-file changes its overlay model silently blocks base improvements where git would merge
  them, it moves base-change review from the extender to a consent hash at the consumer, and the
  parts git doesn't do (per-layer trust, degraded resolution for unreachable bases) exist only
  *because* the design created them. The feature would be our largest mechanism serving our
  thinnest need.
- **One-hop-only extends** (a base must extend `default`/`null`). Same costs minus recursion;
  same losses on the core job.
- **`extends: <local name>`** (compose on a profile already installed via `profile add` —
  resolves locally, so no network-dependent chains, no per-layer consent at scaffold, no index
  authority). The cheapest in-tool option, but it still needs the N-layer manifest/refresh
  machinery and still composes whole-file overlay-wins — and it makes a project's meaning depend
  on what happens to be installed on the machine (the same profile name can resolve to different
  content per user, and `update` can't re-fetch the base for anyone else). Loses to the fork on
  both review-in-the-middle and reproducibility.
- **`profile init --from <url>`** (a command wrapping the clone-and-rename recipe). Deferred, not
  rejected: it's two git commands today; add the sugar if the recipe proves to be a stumbling
  block in practice.
- **Extend by index name** (`extends: "python-backend"`). Rejected outright: it would make
  profile identity depend on which index resolves it (the index URL is env-overridable), turning
  discovery metadata into a resolution authority.
