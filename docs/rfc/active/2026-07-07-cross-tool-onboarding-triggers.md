# Cross-tool onboarding triggers: /onboard for every targeted assistant

- **Status:** Active
- **Date:** 2026-07-07
- **Author:** Luca Mastrostefano
- [x] Implemented

## Context

The first-run apparatus is one transient runbook (`ONBOARDING.md`) plus its triggers. The
runbook itself is tool-agnostic markdown, but today only Claude Code gets a zero-friction
trigger (`.claude/commands/onboard.md` → `/onboard`); Cursor, Copilot, and Gemini users
rely on the AGENTS.md first-run banner and the post-scaffold console hint. Worse, a
project scaffolded from a **profile** (the flip made every scaffold one) other than paths
that run the agents generator gets *no* trigger at all — `tolaria-setup` ships a 7-step
`ONBOARDING.md` with nothing pointing at it but the console text.

Meanwhile every targeted tool now has a project-scoped, version-controllable command
convention (each verified against its current docs, 2026-07-07):

| Tool | File | Format |
| --- | --- | --- |
| Claude Code | `.claude/commands/onboard.md` | markdown |
| Gemini CLI | `.gemini/commands/onboard.toml` | TOML (`prompt`, `description`) |
| Cursor | `.cursor/commands/onboard.md` | markdown (filename = command) |
| Copilot / VS Code | `.github/prompts/onboard.prompt.md` | markdown + YAML frontmatter |

The user requirement this closes: onboarding must be easy to run from **whichever**
assistant the adopter uses, and once run it must be gone for **every** future agent, not
just the one that ran it.

## Decision

**Whenever `ONBOARDING.md` ships, ship a `/onboard` trigger for every targeted tool, all
`transient`, and make the runbook's cleanup step delete all of them.**

Concretely:

1. **One owner, one uniform gate.** The onboarding generator (`generators/onboarding.py`)
   emits every trigger — including Claude's, which moves out of the agents generator. The
   gate becomes uniform: **runbook ⇒ triggers**, derived from `config.ai_tools` (claude →
   `.claude/commands/`, gemini → `.gemini/commands/`, cursor → `.cursor/commands/`,
   copilot → `.github/prompts/`). This is a deliberate behavioral change for one cell:
   today Claude's trigger also required `include_agents` — under the uniform rule a
   `--no-agents` + Claude scaffold *gains* `/onboard` (the other tools never had an
   `include_agents` analog, and a runbook without its trigger is the gap this RFC
   exists to close). Byte content of Claude's command text is unchanged; the parity
   harness updates both sides together.
2. **Same prompt, four containers.** One shared trigger text ("read `ONBOARDING.md`, work
   through its steps now, delete the onboarding apparatus when done"), wrapped per tool's
   format (markdown / TOML / prompt-frontmatter). No per-tool behavioral differences.
3. **All transient.** Written but never recorded in the manifest — `update` can never
   resurrect a trigger after onboarding removed it (the existing `transient` semantics,
   RFC 2026-07-05 §6).
4. **Cleanup enumerates what was actually written.** The runbook's final step lists the
   trigger files (plus `ONBOARDING.md` itself and the banner, as today), derived from the
   generator's own write results — not re-derived from config — so a pre-existing user
   file at a trigger path (skipped by the preserve rule) is never listed for deletion.
   Whichever brand finishes onboarding removes the apparatus for all brands in one commit.
5. **Profile-owned paths win.** If the applied profile itself ships a file at a trigger
   path (e.g. its own `.gemini/commands/onboard.toml`), the engine skips its trigger for
   that tool — otherwise the profile's *managed* copy would overwrite the engine's
   transient one, get recorded, and be resurrected by `update` after onboarding deleted
   it (the exact bug `transient` prevents). A profile that wants self-deleting triggers
   declares them in its own `transient` list.
6. **The console summary points at onboarding whenever the runbook shipped** — including
   profile scaffolds, which today print no pointer at all (`_summary` gates on
   quality/ci). One tool-agnostic line: type `/onboard` in your assistant, or open
   `ONBOARDING.md`.
7. **Both flows.** The base scaffold and profile scaffolds (`onboarding.generate(base=False)`)
   get identical trigger behavior — closing the standalone-profile gap.
8. **Flagship parity.** The baseline profile's templates gain the three new conditional
   trigger templates + updated cleanup text via `build.py`; whole-tree parity stays the
   gate; ships as baseline v0.2.0 (pre-1.0 minor: new shipped files).

## Consequences

- Cursor/Copilot/Gemini users get the same "type /onboard" first-run experience Claude
  users have; the console summary can say one thing for everyone.
- Profile-scaffolded projects (tolaria-setup, future community profiles with `onboarding`
  steps) finally get discoverable onboarding.
- Three more transient files in a default scaffold (only for targeted tools); inert for
  tools not installed, and gone after first run.
- The agents generator no longer writes `/onboard`. For Claude the bytes are identical in
  every cell except `--no-agents` + quality/ci, which now gains the trigger (owned above).
- `build.py`'s hand-mirrored Jinja surface grows by three trigger conditionals plus the
  cleanup enumeration — the drift-prone seam. The whole-tree parity gate remains the
  mechanism that keeps the mirror honest; "one owner" holds for the *generator* path, not
  for the mirror.
- Baseline v0.2.0 is a pre-1.0 minor: every existing scaffold's next `update` gates as
  breaking (one confirmation / `--yes`) — the cost of new shipped files under the
  versioning contract.
- `--tools` with an empty list means a runbook with zero triggers (the summary line still
  points at the file); conversely the flag defaults to *all four* tools, so a standalone
  profile scaffold ships four small trigger files unless the adopter narrows `--tools` —
  accepted, they're transient and inert where the tool isn't installed.
- Triggers being transient, updates never create them retroactively (accepted: the new
  experience is for new scaffolds).
- **§4 holds on the generator path only.** The flagship's templates re-derive the cleanup
  enumeration from `answers.tools` (a template cannot see write results), so on the default
  scaffold path a pre-existing user file at a trigger path is correctly *preserved* but
  still *listed* in the runbook's cleanup line — the same pre-existing limitation the
  parity harness documents for generation-time I/O. Accepted for now; the failure mode is
  one wrong line in a transient runbook the agent reads while looking at the tree.

## Alternatives considered

- **Banner-only for non-Claude tools (status quo).** Works only where the banner ships
  (baseline with agents+tools on); profiles get nothing. Rejected — the gap is real
  (tolaria-setup) and the per-tool cost is one small transient file.
- **Extend the AGENTS.md first-run banner to profile scaffolds instead.** One existing
  mechanism, auto-loaded by all four tools. Rejected for two reasons: a banner is ambient
  context, not a typed command (the requirement is "easy to *run*"), and a profile owns
  its `AGENTS.md` — the engine injecting a banner into a profile-shipped contract crosses
  the ownership line the fold/seed rules draw everywhere else.
- **A shell script (`./onboard.sh`)** as the universal trigger. Tool-agnostic but not
  agent-native — it's the human who runs scripts; the point is the *assistant* discovering
  a first-class command. Rejected.
- **Symlinking one command file across tools.** The four formats differ (TOML vs
  frontmatter markdown); a link can't bridge formats. Rejected.
- **Registering triggers as recorded (managed) files.** `update` would resurrect them
  after deletion — exactly the resurrection bug `transient` exists to prevent. Rejected.
