# agent-native-baseline — the flagship profile (stage-A extraction)

This is the default scaffold, extracted into a normal profile
(RFC 2026-07-05-engine-and-flagship-profile). **Stage A is complete**: the parity gate
(`tests/test_flagship_parity.py`) asserts whole-tree, byte-for-byte equality with the
generators across the full config matrix. The generators remain the source of truth until
stage B — nothing resolves this profile in a real scaffold yet; `build.py` derives every
template from them.

- `profile.json` — the flagship's identity + the part toggles as prompts
  (the `--no-*`/choice flags become `--answer` aliases at stage B).
- `templates/` — ported output files. **Do not edit the built ones by hand**: files
  emitted by `build.py` carry a header comment in the build table; re-run
  `python profiles/agent-native-baseline/build.py` after changing a generator constant.
- `build.py` — the author-time build step (RFC §3). During stage A it derives
  templates from the generators' own constants, so ported files cannot drift from
  the source of truth they mirror. Post-D it becomes the profile's own release tool.

Parity is whole-tree: every path the generators produce, byte-identical, in every
matrix cell (the `.gitkeep`s ship via `empty_files`; the dated adopt-RFC via `@DATE@`;
the first-run pair via `transient`). (`docs/improvements.md`
ported once `env.is_git` landed.) Decided (RFC §7-A):
force means force — under `--force` a profile seed file overwrites; the generators'
`preserve` semantics are not carried over, an accepted change landing at stage B.
