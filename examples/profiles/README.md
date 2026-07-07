# Example profiles — and how to author your own

A **profile** is a packaged, versioned, **complete** project setup a team or the community
ships — the built-in scaffold is itself the flagship `agent-native-baseline` profile. This
directory holds small, runnable examples you can copy and learn from.

## What's here

- [`example-team/`](./example-team/) — a tiny profile demonstrating a prompt, the `env`
  namespace, a write-once `seed` file, and startup hooks (deliberately not a complete setup —
  a real team profile starts by forking the flagship repo).

Try one against a throwaway target:

```bash
agent-native-setup demo -o /tmp/demo --profile ./examples/profiles/example-team -y
```

## Author your own

1. **Scaffold the skeleton:** `agent-native-setup profile init my-team` — or, to build on the
   baseline ("that plus our house files"), **fork the flagship repo** instead. `init` writes `profile.json`, an empty `templates/`, a `README.md`, and an
   `AGENTS.md` — the last is a contract that lets an assistant help you build the profile.
2. **Add your files under `templates/`.** A file at `templates/foo/bar.md` lands at `foo/bar.md`
   in every scaffolded project. Use `.j2` for anything project-specific (rendered with
   `project_name` / `slug` / `description`, your `answers.<name>`, and the sensed-facts
   `env.<name>` namespace). List write-once files under `seed` in `profile.json`. Keep scratch
   and notes **outside** `templates/` — only `templates/` ships.
3. **Validate:** `agent-native-setup profile validate ./my-team`, and fix every finding. It loads
   the profile, strict-renders every template (catching typos), and checks `seed` entries.

See any profile's generated `AGENTS.md` for the full authoring contract, and the
[main README's Profiles section](../../README.md#profiles--the-community-loop) for the field reference.

**Extracting from an existing repo** (one that wasn't scaffolded by this tool) is often the
fastest way to a profile — point any coding agent at the [`extract-profile`
skill](../../.agents/skills/extract-profile/SKILL.md). You don't need this repo cloned. Two
steps, from your own project's root:

```bash
# 1. download the skill into your repo (Codex auto-discovers this location):
curl -fsSL --create-dirs -o .agents/skills/extract-profile/SKILL.md \
  https://raw.githubusercontent.com/luca-mastrostefano/agent-native-setup/main/.agents/skills/extract-profile/SKILL.md
```

```text
2. then paste this into your agent's chat:

   Follow .agents/skills/extract-profile/SKILL.md to extract an
   agent-native-setup profile from this repo.
```

The skill codifies the proven procedure: inventory and classify the repo's agent surface,
gate on license, parameterize identity and instance-bound values, prove fidelity with a
byte-diff, and ship (tag, `publish --release`, and the offered community-index PR). Claude
Code, Cursor, Copilot, and Gemini also get a `/extract-profile` trigger when a project is
scaffolded from this repo.

**Already have a customized project?** `agent-native-setup profile save <project> <name>`
snapshots that project's complete setup (your edits included) as a standalone profile,
read-only on the source — a shortcut to a review-ready draft.

## Contributing a profile here

Open a PR adding `examples/profiles/<name>/`. Keep it **small and declarative** — a focused
demonstration, not a kitchen sink. Every example must pass `profile validate` (CI enforces it via
`tests/test_example_profiles.py`).
