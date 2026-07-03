# Example profiles — and how to author your own

A **profile** lets a team or the community ship their own agent-native setup *on top of* the
default (`extends: "default"`) or *from scratch* (`extends: null`). This directory holds small,
runnable examples you can copy and learn from.

## What's here

- [`example-team/`](./example-team/) — a tiny `extends: default` profile demonstrating a prompt,
  the `env` namespace, a write-once `seed` file, a house `.claude/` agent, and startup hooks.

Try one against a throwaway target:

```bash
agent-native-setup demo -o /tmp/demo --profile ./examples/profiles/example-team -y
```

## Author your own

1. **Scaffold the skeleton:** `agent-native-setup profile init my-team` (add `--standalone` for a
   from-scratch profile). It writes `profile.json`, an empty `templates/`, a `README.md`, and an
   `AGENTS.md` — the last is a contract that lets an assistant help you build the profile.
2. **Add your files under `templates/`.** A file at `templates/foo/bar.md` lands at `foo/bar.md`
   in every scaffolded project. Use `.j2` for anything project-specific (rendered with
   `project_name` / `slug` / `description` / `languages`, your `answers.<name>`, and the
   `env.<name>` namespace). List write-once files under `seed` in `profile.json`. Keep scratch
   and notes **outside** `templates/` — only `templates/` ships.
3. **Validate:** `agent-native-setup profile validate ./my-team`, and fix every finding. It loads
   the profile, strict-renders every template (catching typos), and checks `seed` entries.

See any profile's generated `AGENTS.md` for the full authoring contract, and the
[main README's Profiles section](../../README.md#profiles-experimental) for the field reference.

**Already have a customized project?** `agent-native-setup profile save <project> <name>` extracts
an `extends: default` profile from that project's *delta* from the default (the files you changed
or added), read-only on the source — a shortcut to a review-ready draft.

## Contributing a profile here

Open a PR adding `examples/profiles/<name>/`. Keep it **small and declarative** — a focused
demonstration, not a kitchen sink. Every example must pass `profile validate` (CI enforces it via
`tests/test_example_profiles.py`).
