# agent-native-baseline — the flagship profile (stage-A extraction)

This is the default scaffold **being extracted** into a normal profile
(RFC 2026-07-05-engine-and-flagship-profile). Until the parity gate is green the
**generators remain the source of truth** — nothing resolves this profile in a real
scaffold yet; it exists so `tests/test_flagship_parity.py` can grow file-by-file
byte-parity against the generators.

- `profile.json` — the flagship's identity + the part toggles as prompts
  (the `--no-*`/choice flags become `--answer` aliases at stage B).
- `templates/` — ported output files. **Do not edit the built ones by hand**: files
  emitted by `build.py` carry a header comment in the build table; re-run
  `python profiles/agent-native-baseline/build.py` after changing a generator constant.
- `build.py` — the author-time build step (RFC §3). During stage A it derives
  templates from the generators' own constants, so ported files cannot drift from
  the source of truth they mirror. Post-D it becomes the profile's own release tool.

Parity status lives in the harness: `PORTED` in `tests/test_flagship_parity.py` is
the set of outputs asserted byte-identical across the config matrix; coverage is
reported on every run. The `.gitkeep`s ship via the `empty_files` field (a template
rendering empty means "skip", so intentional emptiness is declared, not templated). (`docs/improvements.md`
ported once `env.is_git` landed.) Decided (RFC §7-A):
force means force — under `--force` a profile seed file overwrites; the generators'
`preserve` semantics are not carried over, an accepted change landing at stage B.
