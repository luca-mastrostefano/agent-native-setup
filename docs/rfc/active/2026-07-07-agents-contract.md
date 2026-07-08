# agents_contract: engine-executed multi-tool compatibility, profile-owned questions

- **Status:** Active
- **Date:** 2026-07-07
- **Author:** Luca Mastrostefano
- [x] Implemented

## Context

A profile that works with every AI assistant today must hand-roll the pattern the
flagship uses: one canonical contract file (`AGENTS.md`), per-tool pointers (`CLAUDE.md`
and `GEMINI.md` symlinks via `links`, each gated by a `when` over its own tools prompt),
and the knowledge of **which file each assistant actually reads**. Three problems:

1. **Authors will forget.** The tool-file matrix (Claude reads `CLAUDE.md`, Gemini reads
   `GEMINI.md`, Cursor and Copilot read `AGENTS.md` natively) is ecosystem trivia, not
   anything a profile author thinks about while packaging *their* setup. A profile that
   ships only `AGENTS.md` silently works for some assistants and not others, and nobody
   finds out until an adopter on the wrong tool does.
2. **The safety classifier punishes doing it right.** `classify_safety` is fail-closed on
   `links` — *any* entry makes a fetched profile classify `unsafe` and demand consent.
   The most idiomatic compatibility pattern (a `CLAUDE.md → AGENTS.md` symlink) costs the
   author adoption friction. The good citizen pays; the author who forgot doesn't.
3. **The engine's wizard makes a promise it can't keep.** On a named-profile run the
   engine still asks its full baseline wizard first — including "AI assistants to target
   (each gets a config pointing at AGENTS.md)" — but for a standalone profile nearly every
   answer is discarded (the legacy generators are skipped), the profile cannot even *see*
   the tools answer (`env` never echoes a choice), and the engine cannot make an arbitrary
   profile support Cursor. The question implies engine-guaranteed compatibility that does
   not exist.

The constraint from RFC 2026-07-05 stands: the engine ships **zero generation-time
content** — profiles are the complete setup, and any fix must not reopen composition
through the back door. The distinction that threads the needle: *what the contract says*
is content (profile-owned); *which filename each tool reads it from* is a fact about the
tool ecosystem that changes on the tools' schedule, not any profile's — engine-shaped
knowledge, best updated in one place by engine releases rather than rotting inside every
published profile.

## Decision

**A profile declares its canonical contract file; the engine executes the tool-pointer
matrix. The engine wizard shrinks to the questions the engine actually owns; everything
else is the profile's prompts.**

### 1. The `agents_contract` field

`profile.json` gains one optional string field:

```json
{ "agents_contract": "AGENTS.md" }
```

— a project-relative, confined path that must equal one of the profile's shipped template
output paths (`load` rejects anything else: a contract the profile doesn't ship has
nothing to point at). It declares "this file is my agent contract; make every assistant
find it."

### 2. Engine pointer matrix

When `agents_contract` is declared, `apply` creates per-tool pointers from an
engine-owned matrix — each a symlink targeting the contract path directly:

| Pointer | For | Created when |
| --- | --- | --- |
| `AGENTS.md` | Cursor, Copilot, every AGENTS.md-native tool | contract isn't itself `AGENTS.md` |
| `CLAUDE.md` | Claude Code | always |
| `GEMINI.md` | Gemini CLI | always |

Skip rules, in order: a pointer path the profile ships a file at is skipped (profile-owned
wins — the same rule the onboarding triggers use); a pointer path the profile declares its
own `links` entry for is skipped (author override, keeping its `when`); the contract path
itself is never pointed at itself.

Pointers are created **unconditionally — no question asked**. A repository is
multi-contributor: which assistant is in play is a property of whoever ever opens the
repo, not of the person running the wizard. The cost is at most three inert symlinks.

The pointers run through the existing `links` machinery: same path confinement, same
`symlink:<target>` manifest provenance, same `show` visibility, and — **at scaffold time**
— the same contract fold (a pre-existing real file at a pointer path or at the contract
path is preserved beneath the marker, never clobbered). Pointers are created at the repo
root regardless of where the contract lives (`agents_contract: "docs/AGENTS.md"` ⇒ a
root-level `AGENTS.md → docs/AGENTS.md`); a contract that *is* a pointer name works by
the same rules (`agents_contract: "CLAUDE.md"` ⇒ `AGENTS.md → CLAUDE.md`,
`GEMINI.md → CLAUDE.md`, and no self-pointer).

**Update semantics.** Expansion happens at load time from the *current* engine's matrix,
and `update` re-resolves and re-applies — so an engine release that grows the matrix
retrofits projects scaffolded from a contract-declaring profile on their next
(non-degraded) update, with no profile release and no author action. This is a deliberate,
named exception to the replay-never-re-sense rule (RFC 2026-07-05 §2): `env` and
`answers` replay from the manifest because they record *observations and choices*; the
matrix is engine knowledge, and replaying a stale matrix would defeat the retrofit that
justifies the mechanic. At update a grown pointer lands only where the path is **free**;
an occupied path is reported through the standard update conflict handling and left
untouched — never folded, never clobbered (the fold is a scaffold-time affordance,
consented by running the wizard; `update` silently rewriting a hand-written `CLAUDE.md`
into a fold would not be). The matrix is thereby a public contract with the same add-only discipline as
`env`: adding a pointer is an engine release; renaming or removing one is a breaking
change, gated like a breaking scaffold update.

### 3. Safety: expanded pointers are not author links

The links⇒unsafe rule stays fail-closed for author-declared `links` (arbitrary link
names, arbitrary targets). Engine-expanded pointers are excluded from it: their shape is
fixed (known names, target = the validated shipped contract path, both ends confined), so
they are provably inert — a profile whose only "link" is `agents_contract` can still earn
`safe`. Consent still binds to the declaration: `agents_contract` lives in `profile.json`,
which the content hash covers, so changing it re-asks like any other change. The inverse
is new and stated plainly: **matrix growth changes the applied bytes with no hash change
and no re-consent** — this is the first place where a profile's declared content doesn't
fully determine what lands on disk. Future engine-expanded pointers ride *engine* trust,
not profile trust; that is acceptable precisely because their shape is fixed and inert
(a symlink with an engine-known name to the already-consented contract path), and it is
the trade that buys the retrofit.

### 4. The engine wizard shrinks to engine-owned questions

On an interactive **named-profile** run the engine asks only what it owns: project name,
description (the base rendering context every profile receives), and `git init` when the
target isn't already a repo — then hands off to the profile's own `prompts`
(`gather_answers`). The languages / AI-assistants / parts / CI / hooks / security /
runner / adoption / banner questions are baseline *content* and stop being asked: today
their answers are silently discarded on these runs, which is strictly worse than not
asking. **Baseline runs are unchanged** — the full wizard still runs and translates onto
the flagship's prompts (`config_to_answers`), preserving the stage-A byte-parity gate.
The deprecated wizard flags stay parsed as `--answer` aliases exactly as documented.

### 5. Tool targeting is derived, not asked

The dropped "AI assistants" answer fed exactly two engine mechanics on standalone runs:
which `/onboard` triggers to write, and whether to write the `.claude` hooks file. Both
now derive from what the profile actually declares and ships:

- a tool is targeted iff the profile ships anything under its config surface (`.claude/`,
  `.cursor/`, `.gemini/`; Copilot: `.github/prompts/` or `.github/copilot-instructions.md`)
  — measured over template output paths, `links`, and `empty_files`;
- `agents_contract` declared ⇒ **all** known tools targeted (the contract is
  tool-universal by construction);
- `session_start` declared ⇒ Claude targeted: the hooks are defined as Claude-targeting,
  so declaring them *is* the opt-in. The "this profile defines session_start hooks but
  the project targets no Claude config" warning goes away — the condition can no longer
  arise.

### 6. Authoring levers: compatibility as the default path

- `profile init`'s skeleton pre-fills `agents_contract: "AGENTS.md"` alongside a
  `templates/AGENTS.md` stub — a new author *deletes* compatibility consciously instead
  of forgetting to add it.
- `profile save` recognizes the pattern (snapshot symlinks named `AGENTS.md`/`CLAUDE.md`/
  `GEMINI.md` all resolving to one shipped file) and emits `agents_contract` instead of
  raw `links` — a project scaffolded from the flagship saves into a profile that stays
  `safe` and inherits future matrix growth.
- `profile validate` prints an advisory (not an error) when a profile ships `AGENTS.md`
  but declares neither `agents_contract` nor a link to it: one line makes it work
  everywhere.

The flagship itself can adopt `agents_contract` in its own repo (dropping its two
conditional `links` entries and its `tools`-gated pointer logic) — a follow-up release
there, out of scope here.

## Consequences

**Easier / newly possible**
- Multi-assistant compatibility becomes the path of least resistance: one declared field,
  and the ecosystem-trivia matrix lives in exactly one place. New assistants retrofit to
  projects scaffolded from contract-declaring profiles via engine release + `update`,
  with zero author involvement.
- The safety verdict stops penalizing the idiomatic pattern — compatibility no longer
  costs consent friction.
- The named-profile UX becomes honest and short: three engine questions, then the
  profile's own wizard. The engine never again asks a question whose answer it discards
  or implies a guarantee it can't keep.

**Harder / costs**
- The engine gains one content-adjacent mechanic. It is deliberately minimal — it authors
  no bytes, only executes a declaration through the existing links machinery — but it is
  a real exception to "the engine only applies what profiles declare," justified because
  the knowledge is tool-ecosystem-shaped, not setup-shaped.
- The pointer matrix becomes a compatibility surface the engine must maintain add-only,
  like `env`.
- Projects scaffolded from a contract-declaring profile get `CLAUDE.md`/`GEMINI.md`
  symlinks even if no contributor ever uses those tools — accepted: they are inert,
  self-explanatory, and the multi-contributor argument dominates.
- Derived tool targeting is a behavior change for standalone runs: a profile shipping no
  tool surface and no contract gets **no** `/onboard` triggers (today `-y` defaulted to
  all four). This is the correct reading — the runbook hint still prints — but it is a
  change adopters can observe. It also removes the adopter's only lever over triggers on
  these runs: `--tools` (a deprecated baseline alias) no longer narrows or zeroes them,
  interactively or under `-y`. Accepted without a replacement lever — the triggers are
  transient and self-deleting, and a per-adopter toggle for a repo-scoped, self-removing
  file is machinery without a constituency.

## Reversibility

`agents_contract` is permanent format surface and the pointer names are a public
contract: once a release ships them, profiles in the wild declare the field and projects
carry engine-provenance pointers, so removal or renaming is an ecosystem break, not a
revert. The wizard shrink and derived targeting are engine-internal and cheaply
reversible until the flagship (or any published profile) starts relying on the derived
rules. This asymmetry is why the change is RFC-gated.

## RFC bookkeeping (on acceptance)

- **2026-07-07-cross-tool-onboarding-triggers** — pointer note: the targeting gate for
  standalone-profile runs changes from `config.ai_tools` to the derived rules in §5, and
  its accepted "adopter can narrow triggers via `--tools`" consequence is withdrawn for
  those runs.
- **2026-07-05-engine-and-flagship-profile** — pointer notes: this RFC is the recorded
  revisit of its open question on the fail-closed links rule ("revisit if it proves too
  blunt" — resolved by carving out the engine-expanded shape, not by softening author
  links), and §2 here is a named exception to both the zero-generation-content principle
  and the §2 replay rule.
- **`docs/architecture/profiles.md`** — document the field, the matrix, the update
  exception, and the derived targeting alongside the existing `links` section.

## Alternatives considered

- **Enforce compatibility for every profile (keep the engine question, inject pointers
  unconditionally).** The engine can't know an arbitrary profile's contract file — some
  ship none — so it would inject mystery files or guess. Composition through the back
  door, one release after `extends` was removed. Rejected.
- **Docs and convention only (recipe + skeleton, no field).** Doesn't fix the
  links⇒unsafe penalty, leaves the matrix to rot inside every published profile, and
  "authors will forget" is the motivating problem — a convention is exactly what gets
  forgotten. Rejected.
- **Teach the classifier the idiomatic shape, no new field.** The minimal fix for the
  safety penalty alone: author-declared `links` whose names are the known pointers and
  whose target is a shipped inert file stop tripping the unsafe rule, plus the `validate`
  advisory from §6. No format surface, no matrix, no update retrofit. Rejected as
  dominated: it solves problem 2 only — authors still hand-roll (and forget) the
  pattern, the tool-file matrix still rots in every published profile, and a new
  assistant still requires every author to release. The classifier carve-out it needs is
  the same one §3 makes anyway.
- **Gate pointers on an engine question ("which assistants?").** Re-adds a question the
  answer to which is person-scoped while the artifact is repo-scoped, and contradicts the
  minimum-question principle this RFC exists to serve. Rejected.
- **Sense installed tools on the scaffolding machine.** Wrong machine — collaborators
  differ, CI scaffolds have no tools installed. Rejected.
- **Keep the full engine wizard on named-profile runs.** The status quo: ~10 questions
  whose answers are discarded, plus the false-promise assistants question. Rejected as
  strictly worse than asking nothing.
