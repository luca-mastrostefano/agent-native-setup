# An `update` command: refresh a scaffolded project to a newer version

- **Status:** Proposed
- **Date:** 2026-06-20
- **Author:** Luca Mastrostefano
- [ ] Implemented

## Context

The wizard scaffolds once and walks away. When we ship a fix — a CI permission, a
security default, a sharper review rule, a new guardrail — every already-scaffolded
project stays frozen at the version that generated it. The update-check nudge
(RFC 2026-06-04) tells a user a newer release *exists*, but there is no way to **apply**
it to a repo that's already set up. Re-running the wizard doesn't help: it's
non-destructive, so it skips every existing file and changes nothing.

The provenance manifest (`.agent-native-setup.json`) was built as the foundation for
exactly this, and its own docstring defers the policy: *"This file only records
provenance; the policy for what's safe to overwrite belongs to the (not-yet-built)
updater."* It records the three things an updater needs: the **resolved config** (frozen
languages/runner/adoption/toggles — so we regenerate with the same choices, not by
re-detecting), a **per-file fingerprint** (`sha256:…` for files, `symlink:…` for links),
and the **version** that generated the tree.

Three things make this hard, and the design has to answer each:

1. **Drift across many versions.** A repo might be ten releases behind. We can't ask the
   user to apply updates one release at a time.
2. **Structural moves of user-populated directories.** This isn't hypothetical: RFC
   2026-06-17 renamed `current/ → active/`, `done/`/`superseded/` and added `retired/`.
   A downstream repo that had accumulated its *own* RFCs under `current/` needs those
   files **moved**, not just the empty scaffold refreshed. The tool only knows about
   files *it* generated, so regenerating alone would strand the user's RFCs in a folder
   the new layout no longer uses.
3. **Files that are seed-once vs tool-managed.** `README.md` and `docs/architecture/overview.md`
   are seeded then owned by the user — refreshing them is wrong even when untouched.
   Standard instructions (the four principles, RFC rules) are the opposite: the
   highest-value thing to push on update. Today both live such that the contract file is
   simultaneously *most valuable to update* and *most likely to be edited* — a permanent
   conflict.

## Decision

Ship two surfaces: `agent-native-setup update` (the deterministic **engine**) and a
`/update` **skill** in the generated `.claude/` (the **agent choreography** that runs the
engine and reconciles what it can't). Four coupled decisions.

> **Implementation status (2026-06-20).** The engine (§1, §3, §4) shipped: `classify`/`apply`,
> the manifest `seed` policy, the structural migration list, the git preconditions, and the
> CLI subcommand. It landed against the **decoupled fallback** (see Alternatives) — `AGENTS.md`
> ships as a whole-file `seed`, so the contract is never clobbered, but the **`INSTRUCTION.md`
> split in §2 is deferred**: standard-instruction improvements don't yet propagate on update,
> and the "single source of truth" / RFC 2026-06-17 edits in Consequences land with that
> follow-up. The `/update` skill is also pending. `- [ ] Implemented` stays unchecked until both land.

### 1. Classify, don't merge

For each file the *new* wizard would generate, compare the on-disk sha256 to the
manifest's recorded fingerprint:

| On disk | vs manifest | State | Action |
| --- | --- | --- | --- |
| missing | — | **new this version** | write it |
| exists | sha **==** recorded | **pristine** | overwrite with new content (if `managed`) |
| exists | sha **!=** recorded | **user-edited** | **conflict** — never clobber; report it |
| in old manifest, no longer generated | pristine | **orphan** | remove |

We deliberately do **not** do a three-way merge. A true merge needs the *base* content
(which we'd have to store or re-run old templates to reconstruct) plus a merge engine and
conflict markers — the weight that makes `cruft`/`copier` heavy. Because the wizard
generates **whole files** (it never owns fragments inside a user's file), classification
covers the real cases. For an edited file the honest answer is non-destructive: *"upstream
changed this and so did you — here's the new version, reconcile it,"* and reconciliation
is handed to the coding agent via the `/update` skill, which is the agent-native move and
the reason this can be simpler than a deterministic merger.

### 2. Managed vs seed ownership — made physical by splitting the contract

The manifest gains a per-file **policy**: `managed` (refresh when pristine) or `seed`
(write once, never refresh). The `seed` set is the existing `preserve=True` call sites
(today `README.md` and `.gitignore`) **plus** files we seed without `preserve` but still
shouldn't refresh — `docs/architecture/overview.md` and accumulated RFCs. So `policy` is
**derived from `preserve` and widened by an explicit seed list in one place** (not a second
hand-maintained mirror of ownership): a generator that writes with `preserve=True` is `seed`
by construction; the short extra list names the seed-but-not-preserved files. Everything
else — agents, slash commands, linter/CI configs, the enforcement checks — is `managed`.

A `seed` file **short-circuits classification**: never refreshed, and an edit to it is *not*
a reported conflict (it's the user's file to own). The one already-tested edge: a `preserve`
file that **pre-existed** the original scaffold is never fingerprinted
(`test_skipped_file_is_not_recorded`), so the manifest has *no baseline* for it. A generated
path with no recorded fingerprint is treated as user-owned — left untouched, not resurrected.

The contract file is the hard case, and we resolve it structurally. **Split `AGENTS.md`:**

- **`INSTRUCTION.md`** — the standard operating contract: the four execution principles,
  think-before-coding, the RFC rules, the "how this stays agent-native" guidance. `managed`,
  and in practice almost always pristine — users rarely edit boilerplate method. This is
  where update value concentrates: improve the standard guidance once and every repo gets
  it on `update`.
- **`AGENTS.md`** — thin and user-owned (`seed`): the project description, the navigation
  table, the live command surface, plus whatever the user adds. Its first line points at
  `INSTRUCTION.md` (a prose "read this first," and an `@INSTRUCTION.md` import line that
  Claude honors directly). The `CLAUDE.md`/`GEMINI.md` symlinks and the Cursor/Copilot
  configs keep pointing at `AGENTS.md` — the pointer web is unchanged; `AGENTS.md` just
  sheds its boilerplate body into `INSTRUCTION.md` and forwards to it.

  One existing path needs care: when scaffolding onto a repo that *already* has an
  `AGENTS.md`, the generator folds the user's prior contract in and fingerprints the merged
  bytes (it bypasses the normal `write`). After the split, that folded `AGENTS.md` is still
  `seed` (correct — it holds the user's content), `INSTRUCTION.md` is written alongside as a
  fresh `managed` file, and the `@INSTRUCTION.md` forward line must be injected at the top of
  the merge so it survives — the fold-in is the messiest path the split touches, so the
  implementation covers it explicitly.

If a user *does* edit `INSTRUCTION.md`, the fingerprint catches it and it becomes a
reported conflict like any other — the split is an optimization for the common case, not a
correctness assumption.

### 3. Regenerate-and-reconcile, plus a thin ordered migration list

Generated files are handled by **regenerate-and-reconcile**: regenerate the whole tree
from the saved config with the new templates, then classify (§1). A *generated* file that
moved is free — its old path is a pristine orphan (removed), its new path is missing
(written).

But moves of **user-populated** directories (Context §2) can't be inferred from the
manifest. So the updater runs a small, **ordered, version-keyed migration list first**,
before regenerating:

```
MIGRATIONS = [
  Migration("0.5.0", "RFC lifecycle: current/→active/, done/+superseded/, add retired/",
            apply=lambda tree: move_dir(tree, "docs/rfc/current", "docs/rfc/active")),
  ...
]
```

The updater reads the manifest version `V_old` and applies every migration newer than
`V_old`, in order — so a ten-releases-behind repo replays the structural changes in
sequence (answering the drift problem). The vocabulary is **deliberately tiny**: file/dir
move and rename, nothing else. Each migration is **idempotent** (safe if partially applied
or re-run) and ships with a test. We explicitly **exclude content-rewriting** migrations
(transforming text *inside* a user's file) — that's a merge problem in disguise; if a
future change needs it, that's a separate decision, not this engine.

Order of operations:

1. **Preconditions** — clean git working tree (or `--dry-run`); a manifest present (else
   degraded mode, below).
2. **Migrate** — replay ordered migrations to move user content into the new layout.
3. **Regenerate** — render the new templates from the saved config into an in-memory set
   of `(path, content, policy)`.
4. **Classify** — new / pristine-refresh / conflict / orphan (§1), honoring `seed` vs
   `managed`.
5. **Apply** — write new + refresh pristine-managed; skip conflicts; remove pristine
   orphans.
6. **Report** — write `UPDATING.md` (the conflict list + what changed), rewrite the
   manifest (new version, new fingerprints, policies).

The user then reviews `git diff`; the `/update` skill walks the agent through the
`UPDATING.md` conflicts and deletes it when done (the `ONBOARDING.md` pattern).

### 4. Git is the undo and the review surface — when there is a git repo

When the target is a git repo, `update` requires a **clean working tree** (or a branch).
Then `git diff` *is* the review surface, `git checkout .` *is* the undo, and a conflict is
simply a file the tool refused to touch. `--dry-run` prints the classification plan before
writing.

But git is **optional** in this tool — `init_git` is user-declinable, `git init` is
best-effort, and a repo may have none. So `update` can't assume `.git` exists. The rule:

- **No `.git`** → refuse by default with a clear message (`update needs a git repo or
  --dry-run to stay reversible; run git init or use --dry-run`). `--dry-run` always works
  without git (it writes nothing). We do **not** silently fall back to mutating an
  unversioned tree.
- **`.git` present, dirty tree** → refuse and ask the user to commit/stash first, so the
  diff `update` produces is unambiguously *its* diff.

We add no bespoke rollback engine for `update`: the scaffold path's `rollback()` exists
because it runs on a possibly-fresh dir mid-build, whereas `update` runs against an
existing tree where git (or `--dry-run`) is the safer, reviewable undo.

**Degraded mode.** A repo scaffolded before the manifest existed (or with an unreadable
manifest) has no provenance: only **add missing files, never overwrite**, and report
everything else. Old manifest *schemas* (missing the new `policy` field, missing config
keys) fill from defaults — the updater tolerates its own format evolving.

## Consequences

- Fixes propagate. The tool's reason to exist — shipping CI/security/review improvements —
  finally reaches already-scaffolded repos, which is most of its value over a one-shot
  generator.
- The contract split makes the highest-value payload (standard instructions) cleanly
  refreshable, at the cost of two files where there was one. It nicks the "single source of
  truth" principle — but `AGENTS.md` stays the one file every tool points at; it just
  delegates the method to `INSTRUCTION.md`. The risk is an agent reading `AGENTS.md` and
  not following the pointer; the `@INSTRUCTION.md` import and a prominent first line
  mitigate it, and the existing model already relies on agents following pointers (the nav
  table, the docs). Because it redefines a live convention, this RFC must edit the text that
  asserts it: the `AGENTS.md`/`CLAUDE.md` "single source of truth" line and the
  reflect-into-`AGENTS.md` guidance in RFC 2026-06-17 (which now means `INSTRUCTION.md` for
  the standard parts). Those edits land behind this RFC, listed here so the change isn't
  silent.
- `update` is only as reversible as the repo lets it be: in a git repo it's `git diff` +
  `git checkout`; with no `.git` it refuses unless `--dry-run` (§4). So a non-git scaffolded
  repo can preview but not apply an update until it runs `git init` — an accepted limitation,
  surfaced rather than worked around with a fragile bespoke undo.
- We take on a **migration ledger**: every structural move of user-populated layout now
  needs an idempotent, tested migration, maintained forever. This is real ongoing cost, but
  it's bounded (move/rename only) and pays for the one thing regeneration can't do.
- `update` is only as safe as the clean-tree precondition and the fingerprints. The known
  wrinkle: the tool's own **pre-commit format hooks may reformat a generated file on first
  commit**, so a "pristine" file can read as edited at update time. We hash exact bytes; the
  mitigation is that such files fall into the conflict bucket where the only diff is
  whitespace — trivial for `git diff`/the agent to wave through — and we surface, not
  silently skip, so the user always sees them. (Alternative: normalize before hashing —
  rejected as a footgun that hides real edits.)
- New languages/toggles are **not** retro-added on update — the saved config is the frozen
  set the user opted into; `update` refreshes what was chosen, it doesn't expand scope. A
  separate `--reconfigure` is out of scope here.

## Alternatives considered

- **Three-way merge (`cruft`/`copier` model).** Store or reconstruct base content and merge
  the wizard's diff onto the user's edits. Rejected: needs base content + a merge engine +
  conflict markers, and the agent reconciles edited files better than a textual merger
  anyway. Whole-file generation makes classify-and-report sufficient.
- **Pure regenerate-and-reconcile, no migrations.** Simplest, but the RFC-rename case proves
  it strands user-populated directories. Rejected as incorrect for the demonstrated need.
- **A full migration framework (every change is a forward migration, Rails-style).**
  Rejected as over-engineering: regeneration already handles generated files; migrations
  are needed *only* for structural moves of user content, so the list stays tiny instead of
  growing one entry per release.
- **Keep one `AGENTS.md`, treat it as `seed`.** No contract split — accept that
  standard-instruction improvements never propagate on update. Simpler, and a valid way to
  **decouple**: land the engine first against today's single file, add the split later.
  Rejected as the default because it forfeits the update's highest-value payload — but it's
  the clean fallback if we'd rather ship the engine before touching the contract.
- **Auto-apply / no review step.** Rejected: silently overwriting in a user's repo is
  exactly the surprise the tool's non-destructive promise rules out. Clean-tree + `git diff`
  + `--dry-run` keeps every change reviewable.
- **A `/update` skill with no CLI engine** (agent does the whole update). Rejected: the new
  templates live in the *upgraded Python package*, not in the user's repo — the agent has no
  source to regenerate from. The engine must be the CLI; the skill is choreography on top.
