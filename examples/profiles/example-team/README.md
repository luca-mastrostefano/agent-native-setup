# example-team — a reference profile

A tiny profile that demonstrates the main authoring features in one place:

| File | Shows |
| --- | --- |
| `profile.json` → `prompts` | a `select` question (`tier`) asked at scaffold, replayed on update |
| `templates/docs/conventions.md.j2` | a `.j2` template reading `project_name`, `answers.tier`, and the `env` facts (`env.existing_project`, `env.detected_languages`) |
| `templates/docs/team-notes.md` (`seed`) | a **write-once** file — never overwritten by an update |
| `profile.json` → `onboarding` / `session_start` | a one-time onboarding step and an every-session reminder |

It is deliberately *not* a complete setup — a scaffolded project gets exactly these files, no
`AGENTS.md` or quality gate. A real team profile starts by **forking the flagship
`agent-native-baseline` repo** (the complete setup) and adding house files like these; this
example only exercises the format.

This file and the layout notes are **meta** — only what's under `templates/` ships into a
scaffolded project.

## Try it

```bash
agent-native-setup demo -o /tmp/demo --profile ./examples/profiles/example-team -y
```

`docs/conventions.md` in the result renders with the project name and your chosen tier.
