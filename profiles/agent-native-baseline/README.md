# agent-native-baseline — the vendored flagship copy

**Canonical home: <https://github.com/luca-mastrostefano/agent-native-baseline>** (stage B3,
RFC 2026-07-05 §5). This directory is the engine's **pin-verified vendored copy** of that
repo's tagged release — the artifact the wheel embeds (`pyproject.toml` force-include) and
`builtin:agent-native-baseline` resolves to, so scaffolding stays offline and the trust
grounding is "installing the tool is consenting to exactly this reviewed artifact."

The pin lives in [`../baseline-pin.json`](../baseline-pin.json) (tag + content hash over
`profile.json` + `templates/`). Three checks keep it honest:

- `tests/test_flagship_parity.py::test_vendored_flagship_matches_its_pin` — offline, every
  test run: this copy hashes to the pin.
- `tools/checks/check_baseline_pin.py` (`task check-baseline`, run by the `index-check`
  workflow) — network: the pinned tag still resolves to the same artifact.
- `tests/test_flagship_parity.py` whole-tree parity — this copy is byte-identical to the
  generators across the config matrix (until stage D deletes them).

## Changing the flagship

Until stage D the templates are **derived**: `build.py` (kept here — it imports the
engine's generators, so it runs from this repo; it moves to the profile repo at D) emits
them from the generators' own constants. The release loop is:

1. change the generator constant → `python profiles/agent-native-baseline/build.py`;
2. copy the result to the profile repo, bump `profile.json`'s `version`, tag `vX.Y.Z`;
3. in the same engine PR: sync this vendored copy and update `../baseline-pin.json`
   (`profiles.content_hash` of the loaded profile) — the offline pin test forces this.

**Do not edit built templates by hand** — parity and the pin will both catch the drift.
Decided history (RFC §7-A): force means force — under `--force` a profile seed file
overwrites; the generators' `preserve` semantics were deliberately not carried over.
