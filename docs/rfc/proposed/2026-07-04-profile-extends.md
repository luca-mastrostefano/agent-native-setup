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
three house files" must copy it. The obvious feature — `extends: git+<url>`, a profile composing
on a fetched base, chains resolved recursively with per-layer trust gates — was designed far
enough to cost it out. This RFC records why we are **not** building it.

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

Why git wins over an in-tool `extends: <url>`:

- **Git's merge is strictly better than ours could be.** An overlay mechanism composes
  whole-file, overlay-wins. Git merges *within* files, three-way, with conflict markers and the
  entire tooling ecosystem around them. For "take the base's improvements into my edited copy" —
  the actual job — we would be re-implementing a worse `git merge` and asking users to learn it.
- **"Forking severs updates" is false with a remote.** `git fetch upstream && git merge` *is* the
  update stream, at the layer where a human should be: the extender reviews base changes before
  releasing them to their own consumers. That review-in-the-middle is curation, not friction —
  chains would pipe unreviewed base changes past the extender straight into consumers, gated only
  by a consent hash the consumer can't meaningfully evaluate.
- **It matches ecosystem norms.** A consumer's profile updates when *that profile's maintainer*
  releases — exactly how package managers work. Nobody expects transitive auto-updates that
  bypass their direct dependency's release.
- **The delta stays visible** — `git diff upstream/main` is the "what did we change on the base"
  view, better than reading an overlay directory against a mental model of the base.
- **What we don't build**: chain resolution (network-dependent, breaks anywhere → breaks
  everything), cycle/depth guards, per-layer consent, degraded-update handling for unreachable
  bases, and merge-semantics documentation. Single-layer profiles keep the existing trust model
  untouched — one artifact, one hash, one gate.

The consumer side is unaffected and already solved: projects scaffolded from the fork get its
releases through the existing `update` (managed files, conflict classify, version gates,
re-consent on content change).

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
  see "review-in-the-middle" above.

## Alternatives considered

- **`extends: git+<url>` with recursive chains** (visited-set cycle guard, depth cap, per-layer
  content-hash consent, flatten-at-resolve composition). Fully designed, then rejected: every
  hard part — merging, update streams, delta visibility — is something git already does better,
  and the parts git doesn't do (per-layer trust, degraded resolution) exist only *because* the
  design created them. The feature would be our largest mechanism serving our thinnest need.
- **One-hop-only extends** (a base must extend `default`/`null`). Same costs minus recursion;
  same inferiority to `git merge` on the core job.
- **`profile init --from <url>`** (a command wrapping the clone-and-rename recipe). Deferred, not
  rejected: it's two git commands today; add the sugar if the recipe proves to be a stumbling
  block in practice.
- **Extend by index name** (`extends: "python-backend"`). Rejected outright: it would make
  profile identity depend on which index resolves it (the index URL is env-overridable), turning
  discovery metadata into a resolution authority.
