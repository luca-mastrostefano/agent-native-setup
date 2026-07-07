# publish opens the index PR

- **Status:** Active
- **Date:** 2026-07-07
- **Author:** Luca Mastrostefano (drafted with Claude)
- [x] Implemented

## Context

`profile publish --release` ends with homework: an entry containing
`"author": "TODO: your name/handle"`, an instruction to hand-edit
`contributions/index.json` in *another* repo, and no command to run. The first real
dogfood run (a user publishing a profile extracted by the extract-profile skill) ended
with "I'm a bit lost, isn't there a suggested command? Can't it create the PR
automatically?". A package manager's publish step should finish the job.

Two smaller defects surfaced in the same run:

- `_infer_git_url` emits `git+ssh://` when `origin` is an SSH remote. A *public listing*
  URL must be fetchable by anyone; `git+https://` is the universal read-only transport
  (and the convention of every existing index entry). SSH is right for the author's
  push, wrong for the adopters' fetch.
- The `author` field is a TODO even though `gh` (already required for `--release`) knows
  who the user is.

Constraints: the index stays PR-gated on a protected branch and human-reviewed — the
trust model (RFC 2026-07-04-community-index) must not change. The index file is
hand-formatted (2-space indent, single-line tag arrays); a mechanical edit must not
reformat the whole file, or every listing PR becomes an unreviewable diff. A private
index (`AGENT_NATIVE_SETUP_INDEX_URL`) may not live on GitHub at all.

## Decision

This RFC **amends RFC 2026-07-04-community-index §5**, which decided publish "does not
push or open a PR (that stays the author's deliberate act)". The deliberate act moves
into an explicit interactive confirm; the dogfood run showed that stopping short of the
PR doesn't protect the author's agency, it just strands them. The active RFC carries an
amendment banner.

Three changes to `_publish`, in increasing order of machinery:

1. **Normalize the listing URL to https for github.com remotes.** `git@github.com:o/r`
   → `git+https://github.com/o/r.git`. Non-GitHub ssh remotes keep today's URL — we
   can't assume an https mirror exists — but publish now prints a warning that a
   `git+ssh://` listing is adopter-hostile (anyone without ssh access to that host
   can't fetch it), instead of leaving `check-index` to discover the rot later.
2. **Autofill `author`**: `gh api user` login, falling back to `git config user.name`,
   falling back to today's TODO. Best-effort, never fails publish.
3. **Offer to open the listing PR** after the release step — and on any tagged publish,
   with or without `--release`: a listing is valid without an asset (clone fallback), so
   the offer shouldn't be gated on one. Interactive confirm (default yes). Mechanics —
   git-native, clone-based:
   - Derive `owner/repo`, branch, and file path from the *effective* index URL (env
     override respected) when it is a `raw.githubusercontent.com` URL; otherwise skip
     silently (private/non-GitHub index → printed entry, as today).
   - Shallow-clone the index repo (via `gh repo clone`, so auth follows gh), splice the
     entry **textually** right after the `"profiles": [` line, rendered in the file's
     house style — then `json.loads` the result and check name/URL uniqueness locally
     before pushing. Splice anchor missing or result unparsable → degrade.
   - **Re-publish of a listed name** (version bump): only when the repo part of the URL
     (everything before `@ref`) is **unchanged** — then replace the old entry's `url`
     string in place (URLs are unique), leaving description/tags to the human; the PR
     body notes they may have drifted. If the repo part differs, the auto-PR is
     **refused** with a loud message: repointing a listed name to a different repo is
     the hijack shape (a routine-looking "bump" PR that steals an established name),
     and precisely because this RFC makes bump PRs frequent and rubber-stampable, an
     owner change must arrive as a hand-written PR that says what it is.
   - Push a branch; if push is refused (no write access), `gh repo fork --clone=false`,
     push to the fork, and open the PR cross-fork (`--head login:branch`). Then
     `gh pr create --repo <index-repo>`.
   - **Every failure degrades to today's behavior**: the entry is always printed
     *before* any of this runs (same ordering rule as the release step), so the worst
     case is exactly the status quo plus a one-line reason.
   - Non-interactive stdin (CI) never asks and never attempts — publish stays
     scriptable and side-effect-predictable.

The index's trust model is untouched: automation *authors* the PR; a human still
reviews it, CI (`check-index`) still fetches and validates the listing, and the
protected branch still refuses direct pushes.

## Consequences

- `publish --release` becomes the complete author flow: validate → release asset →
  listing PR, one command and one confirm from extracted-profile to community-listed.
- New failure surface (clone, fork, push, PR) — all soft; the printed entry remains the
  contract and the fallback.
- `gh` graduates from "needed for --release" to "the auth for the whole publish tail";
  without it, publish still works as today.
- A textual splice is coupled to the index file's shape (`"profiles": [` anchor). The
  local parse-and-validate step is the real safety net (anchor drift degrades legibly,
  never a broken PR); the committed-index test gains an assertion pinning the anchor so
  a reformat of the file fails CI before it can strand publishers.
- **The review queue is what scales with this feature.** Lowering a listing to one
  confirm grows the curation burden the community-index RFC named as its main ongoing
  cost — more PRs, and more of them looking routine. The owner-change refusal above
  exists to keep "routine-looking" honest.
- Maintainers get the same flow as contributors (direct branch vs fork) with no special
  casing beyond "try push, fork on refusal"; the direct-push path leaves a branch on
  the canonical repo to delete after merge (squash-merge with branch deletion is the
  house habit, so in practice this is absorbed by the merge).

## Alternatives considered

- **Print one copy-pasteable command instead of automating.** Works for the repo-create
  step (shipped in the extract-profile skill), but there is no honest one-liner for
  "insert this JSON object into a file in a repo you may not have write access to" —
  any such command would smuggle in the same machinery, minus the error handling.
- **GitHub contents-API flow (no clone).** Fewer files on disk, but more choreography
  (blob encode, ref create, fork sync) and it abandons git primitives; the clone is a
  few KB. We prefer git-native mechanics.
- **Canonicalize the index format and rewrite structurally.** The hand-formatted-file
  constraint is self-imposed — we own `index.json` and could reformat it once to
  `json.dumps(indent=2)` and then parse → modify → serialize, which is robust against
  any anchor drift. Passed because the house style (single-line tag arrays) keeps each
  entry a compact reviewable block — the property listing PRs live on — and the splice's
  parse-and-validate degrade plus the new anchor-pinning test bound the fragility to "a
  legible skip", which is cheaper than giving up the review ergonomics.
- **Auto-merge for maintainers / direct commit.** Rejected: the human review gate on
  the index is the trust model, not a formality — nobody bypasses it, including us.
- **Regenerate the whole entry on re-publish.** Would silently overwrite curated
  description/tag edits made in review; the url-only bump keeps the human in charge of
  prose.
- **A `--pr/--no-pr` flag.** The interactive confirm already covers intent, and
  non-interactive runs never attempt the PR; a flag is speculative surface.
