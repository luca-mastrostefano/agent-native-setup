# Profile-contributed Claude settings

- **Status:** Active
- **Date:** 2026-07-09
- **Author:** Luca Mastrostefano
- [x] Implemented

## Context

A profile that ships agent tooling usually has to *enable* it too. The canonical case:
`tolaria-setup` ships a `.mcp.json` registering the CodeScene MCP server, but a registration
is not an authorization — Claude Code won't use the server until it's listed in
`enabledMcpjsonServers`, and its `mcp__codescene__*` tools need a `permissions.allow` entry.

Today a profile has no supported way to contribute those two keys:

- **Shipping `templates/.claude/settings.json` doesn't work.** The engine generates that file
  itself, carrying the update-check nudge plus the profile's own guarded `session_start`
  commands (`generators/agents.py`, the settings writer). A profile-shipped
  `settings.json` is an overlay that **supersedes** it ("single-owner"), so declaring
  `session_start` *and* shipping `settings.json` silently drops the SessionStart hooks. The
  only way out is for the profile to hand-copy the engine's hook machinery (the
  `UPDATE_CHECK_COMMAND` string, the `{ …; } || true` guard wrapping) into a static file,
  where it drifts on the next engine release.

- **So authors reach for `.claude/settings.local.json` instead.** `tolaria-setup` does exactly
  this, and had to add a `!templates/.claude/settings.local.json` negation to its own
  `.gitignore` to keep the file tracked. But `settings.local.json` is Claude Code's
  **per-user, git-ignored** file. Shipping it tracked means (a) the adopter commits a file
  that is by convention personal, and (b) every approval Claude Code later writes into that
  same file — the adopter's *own* choices — gets committed too. `profile validate` now flags
  this (the `⚠ ships '.claude/settings.local.json'` lint), but the lint has no correct
  alternative to point at.

Both symptoms are the same missing capability: **a profile can declare hooks, but not the
permissions and MCP enablement those hooks and tools require.**

There is a security dimension. Pre-approving `Bash(…)` patterns or an MCP server grants
authority on the adopter's machine. Today that authority is smuggled in as opaque file
content, and the consent prompt (RFC 2026-07-04 §4) shows only "writes a not-provably-inert
file". Whatever we add should make the grant *legible* at consent time.

## Decision

Add an optional **`claude_settings`** object to `profile.json` that the engine **merges into
the `.claude/settings.json` it generates**, rather than having the profile replace that file.

```json
{
  "claude_settings": {
    "permissions": { "allow": ["mcp__codescene__*", "Bash(git status:*)"], "deny": [] },
    "enabledMcpjsonServers": ["codescene"]
  }
}
```

Rules, chosen to be the smallest thing that solves the problem:

1. **Key allowlist.** Only `permissions` (`allow`/`deny`, lists of strings) and
   `enabledMcpjsonServers` (list of strings) are accepted. Anything else — including an
   unknown key *inside* `claude_settings` — is a load-time `ProfileError`. A profile must not
   be able to reach arbitrary settings keys, notably not `hooks` or `env`.
2. **`claude_settings` triggers the write, and targets Claude.** Today `.claude/settings.json`
   is written only when `session_start` is non-empty *and* Claude is a derived target
   (`cli.py` → the settings writer). That gate is wrong for this feature: a
   profile whose whole point is "enable the MCP server I ship" has no hooks, so its
   contribution would be silently dropped, and `derive_tools` wouldn't even target Claude for
   it. Therefore:
   - `derive_tools` treats a declared `claude_settings` as targeting `claude` (joining
     `session_start`, a `.claude/` file, and `agents_contract` in `_TOOL_SURFACES` logic).
   - The settings write is triggered by **`session_start` *or* `claude_settings`** being
     non-empty. The generator takes both and is no longer named for hooks alone.
3. **The engine owns `hooks`.** The generated `hooks.SessionStart` (update-check + guarded
   `session_start` commands) is written as today; the profile's contributed keys are overlaid
   *beside* it, never over it. A profile cannot drop the update nudge or its own guard. With
   `claude_settings` and no `session_start`, the file is written with the update-check hook
   only.
4. **A shipped `templates/.claude/settings.json` still supersedes** (unchanged, single-owner) —
   this stays backwards-compatible. But `profile validate` warns when a profile ships that file
   *and* declares `session_start` (that combination silently loses the hooks) or *and* declares
   `claude_settings` (the overlay wins; the contribution is dead config).
5. **Contributing settings makes a profile `unsafe`**, with reasons naming what is granted
   (e.g. `pre-approves 2 permission(s): mcp__codescene__*, Bash(git status:*)`; `enables 1 MCP
   server: codescene`). Pre-approval is authority, so it must be visible where authority is
   reviewed. Scope honestly: `consent()` only gates **fetched** (`git+…`) profiles, so this
   surfaces the grant at install time for those; a local/`~/.config` profile is trusted by
   provenance and shows it only via `profile validate` / `classify_safety`. For the canonical
   `tolaria-setup` case the profile is *already* `unsafe` (it ships `session_start` and a
   `.mcp.json`), so the new thing here is the **reason line**, not a new gate.
6. **Merge, don't concatenate.** `permissions.allow` from the profile is written as-is. The
   engine contributes no permissions of its own on the profile path today (only the non-profile
   `generate()` emits them, which profiles never reach), so there is nothing to union with; if
   that changes, the union is the engine's list plus the profile's, deduped and order-stable.
7. **Replay on update.** `claude_settings` is recorded in the project manifest's profile block,
   and the degraded-update path (profile gone) regenerates `settings.json` from the recorded
   value — which requires decoupling that write from "`hooks` is non-empty" too, exactly as in
   rule 2. Otherwise a hookless profile's permissions vanish on the very update this protects.
8. **Typos must not be silent.** `load()` reads only known keys, so a misspelled
   `claud_settings` would grant nothing with no error — the same invisible under-delivery this
   RFC exists to remove. `profile validate` therefore warns (advisory, exit code unchanged) on
   any unrecognized **top-level** `profile.json` key. This is deliberately a lint, not a load
   error: rejecting unknown keys outright would break forward-compatibility for profiles
   written against a newer engine.

Why this over the alternatives: it is additive (no existing profile changes behavior), it
keeps the engine the single owner of the file it generates, and it gives the
`settings.local.json` lint a correct destination to recommend.

## Consequences

**Easier.** A profile can ship an MCP server *and* have it work, in the supported way: one
declarative object, no hand-copied hook machinery, nothing tracked that shouldn't be. The
`⚠ ships settings.local.json` lint gains an actionable fix ("move these to
`claude_settings`"), and `tolaria-setup` can drop its `.gitignore` negation and its tracked
`settings.local.json`.

**Newly possible.** For a *fetched* profile, consent can name the concrete authority being
granted instead of a generic "unsafe". A hookless profile that only registers and enables an
MCP server becomes expressible at all — today it silently no-ops.

**Harder / given up.**
- A profile still cannot set arbitrary Claude settings. Deliberate: the allowlist is the point.
  Growing it is an add-only engine change, like `env` and `AGENT_POINTERS`.
- The settings write is no longer gated on `hooks` alone (rule 2), on both the scaffold and the
  degraded-update path. That is a behavior change to a code path `session_start`-only profiles
  already use, so it needs regression tests proving those profiles produce a byte-identical
  `settings.json`.
- `derive_tools` gains a fourth way to target `claude` (rule 2), widening the RFC
  2026-07-07-agents-contract surface it was meant to keep narrow.
- Profiles that ship a whole `settings.json` keep working but stay on the footgun path. We warn
  rather than break them; a future RFC may deprecate the overlay for that one path.
- One more field on the public `profile.json` contract, and one more thing `update` must replay.
- An engine that predates this field ignores `claude_settings` — verified: `load()` reads only
  known keys and rejects only `extends`, so there is no unknown-key error. A profile using it
  degrades to "MCP registered but not enabled" on old engines rather than failing loudly.
  Acceptable, and exactly today's behavior for those users. The flip side is rule 8's typo lint.
- The consent prompt's header reads "it will run code on your machine", but a
  `permissions.allow` entry *removes a future guardrail* rather than running code. The reason
  line will sit slightly oddly under that header until the wording is revisited separately.

## Alternatives considered

- **Let a shipped `settings.json` merge with the generated one.** Rejected: merging two opaque
  JSON files has no obvious precedence rule for `hooks`, and it would let a profile clobber the
  update nudge and its own guard by accident. The single-owner rule is what makes the generated
  file predictable; `claude_settings` gives the profile a seat at the table without taking the
  table.
- **Teach the engine to leave `settings.local.json` alone and just gitignore it.** This is what
  `tolaria-setup` effectively does. Rejected: it still ships a per-user file as project content,
  and Claude Code will keep appending the adopter's own approvals to it. Ignoring the file makes
  the leak quieter, not absent, and the shared pre-approval stops reaching teammates at all.
- **A `permissions` top-level field instead of a nested `claude_settings`.** Rejected: the keys
  are Claude-specific and the profile contract is meant to stay tool-neutral where it can.
  Namespacing under `claude_settings` leaves room for a `cursor_settings` sibling without a
  second migration.
- **Do nothing; document the `settings.local.json` pattern.** Rejected: it is the pattern the
  new lint exists to discourage, and it makes the adopter's personal approvals a committed
  artifact. We would be blessing a leak.
