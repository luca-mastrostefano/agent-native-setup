# example-team — a reference profile

A tiny `extends: default` profile that demonstrates the main authoring features in one place.
It composes on the default scaffold and adds:

| File | Shows |
| --- | --- |
| `profile.json` → `prompts` | a `select` question (`tier`) asked at scaffold, replayed on update |
| `templates/docs/conventions.md.j2` | a `.j2` template reading `project_name`, `answers.tier`, `env.existing_project`, `languages` |
| `templates/docs/team-notes.md` (`seed`) | a **write-once** file — never overwritten by an update |
| `templates/.claude/agents/example-reviewer.md` | a house `.claude/` agent added on top of the base library (managed — refreshed on update) |
| `profile.json` → `onboarding` / `session_start` | a one-time onboarding step and an every-session reminder |

This file and the layout notes are **meta** — only what's under `templates/` ships into a
scaffolded project.

## Try it

```bash
agent-native-setup demo -o /tmp/demo --profile ./examples/profiles/example-team -y
```

`docs/conventions.md` in the result renders with the project name and your chosen tier.
