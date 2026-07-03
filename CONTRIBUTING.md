# Contributing

## Dev loop

1. Read `AGENTS.md` (the project map) and the `INSTRUCTION.md` it points to — the
   contract and the four execution principles.
2. For anything architectural or hard to reverse, write an RFC first
   (`docs/rfc/proposed/`, from `docs/rfc/TEMPLATE.md`).
3. Make the change. Keep it surgical.
4. Run the quality gate before committing (see the command surface in `AGENTS.md`).

## Definition of done

- The change traces directly to the task — no drive-by edits.
- It's verified by a test or an explicit check.
- Linters and hooks pass.

## Contributing a profile

Profiles let a team or the community ship their own agent-native setup. To author one — or
contribute an example — see [`examples/profiles/README.md`](./examples/profiles/README.md).
Every example must pass `agent-native-setup profile validate` (CI enforces it).
