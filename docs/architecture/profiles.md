# Profiles

A **profile** is a packaged, versioned setup a team or community ships on top of (or instead
of) the default scaffold. This is the subsystem map for `src/agent_native_setup/profiles.py`
and its integration points; [`overview.md`](./overview.md) is the repo-wide index. The RFC
trail: 2026-06-23-scaffolding-profiles (umbrella), 2026-06-26-profile-prompts,
2026-07-03-profile-safety / -profile-save / -ecosystem-core, 2026-07-04-profile-fetch /
-community-index / -profile-extends.

## Format

A profile is a directory:

```
my-profile/
  profile.json   # name, version (own semver), extends, description, tags, seed,
                 # prompts, onboarding, session_start
  templates/     # the files it ships; paths relative to the project root
  README.md, AGENTS.md, …   # meta — never ships; only profile.json + templates/ do
```

`extends: "default"` composes: the wizard generates its normal output, then each template file
overlays it (same path supersedes). `extends: null` is **standalone**: the default generators
are skipped and the profile provides everything. Templates ending in `.j2` are rendered
(Jinja, `.j2` stripped; one that renders empty is skipped — conditional inclusion); everything
else ships verbatim, so literal `${{ … }}` is safe. Each shipped file is **managed**
(refreshed by `update`) unless listed in `seed` (written once, then the user's).

Two path-level affordances (RFC 2026-07-05 §6): **`links`** — an object of
`"link": "target"` pairs (or `{"target": …, "when": …}` — the `when` mirrors a prompt's, so a
per-tool link ships only when relevant; both ends project-relative, traversal-free,
re-confined at apply) the
engine creates as symlinks, recorded as `symlink:<target>` provenance like the base's own
links, shown by `show`, and classified fail-closed (any link ⇒ not `safe`); **`transient`** —
output paths written but never recorded (self-deleting first-run files: a manifest that
listed one would let `update` resurrect it after onboarding removed it); **`empty_files`**
— declared conditionally-shipped empty files (`{"docs/rfc/active/.gitkeep":
"answers.include_docs"}`; a template rendering empty means *skip*, so intentional
emptiness is declared — paths confined, classified like any output, `when` like links');
and **`@DATE@`**
in a template *path*, substituted with the scaffold date — recorded in the manifest
(`profile.date`) and **replayed on update**, so a dated path never drifts or duplicates under
a refresh.

## Resolution (`resolve`)

`--profile` / `profile add` / `profile show` accept, in this order of precedence:

1. `default` / empty → `None` (no overlay) — and with **no `--profile` at all, the engine
   scaffolds the vendored flagship** (`builtin:agent-native-baseline`, trusted like any
   local artifact, wheel-embedded; the wizard's flags/questions translate onto its prompts);
2. a `git+https://…` / `git+ssh://…` URL (optionally `@ref`, `#subdir=dir`) → fetched into
   `~/.cache/agent-native-setup/profiles/` (pinned refs cached forever, branches re-fetched,
   stale cache reused on fetch failure with a warning);
3. a path containing `profile.json`;
4. a bare name under `~/.config/agent-native-setup/profiles/`;
5. (`add`/`show` only) a bare name that matches nothing local → exact-name lookup in the
   community index; the `name → community index → <url>` redirection is printed, and only
   `git+` entries are accepted (a path-shaped entry would masquerade as trusted-local). A
   broken local profile reports its own error — it is never shadowed by an index listing.

The reference is recorded verbatim as the manifest `source`, so `update` re-resolves (and
re-fetches) the same way later.

## Rendering context

`.j2` templates and prompt `when` expressions see `project_name` / `slug` / `description` /
`languages`, the prompt answers under **`answers.<name>`**, and detected/resolved facts under
**`env.<name>`** (`existing_project`, `languages`, `detected_languages`, `existing_runner`,
`runner`, `adoption`, `ai_tools`, the `has_quality`/`has_ci`/… toggles, and the sensed facts
`is_git` (is/will be a git repo), `os` (`darwin`/`linux`/`windows`, `""` = other/unsensed),
`has_readme` / `has_agents_md` / `has_ci_config` (a `README.md` / `AGENTS.md` /
`.github/workflows/` directory present before scaffolding), and `date` (the scaffold date —
the same stamp `@DATE@` paths use, replayed on update) — sensed once at
scaffold, recorded in the manifest snapshot, and **replayed by `update`, never re-sensed**,
per RFC 2026-07-05 §2) — both
namespaced so they can never shadow a base key. Templates also get a `to_json` filter
(byte-equal to `json.dumps(indent=2)` — unlike `tojson`, no HTML escaping). The env contract is **add-only**: renaming or
removing a key is a breaking engine change, gated like a breaking scaffold update. All rendering goes through Jinja's
`SandboxedEnvironment` (`scaffold.py`): profile templates are untrusted input.

## Prompts

`prompts` is a declarative mini-wizard: `text` / `select` / `confirm` / `checkbox`, each with a
`message`, optional `choices`/`default`, and an optional `when` (a Jinja expression over
earlier answers + the base context — a false `when` skips the question and takes the default).
Answers land in `answers.<name>`, are recorded in the project manifest, and are **replayed on
update, never re-asked**. Non-interactive runs (`-y`/CI) take each prompt's declared (or
per-type) default; the repeatable **`--answer NAME=VALUE`** flag answers any prompt headlessly
(type-validated; an overridden prompt is never asked and feeds later `when`s; a duplicate
`--answer` for one prompt is an error).

## Startup contributions

- `onboarding` — markdown steps folded into the project's one-time, self-deleting
  `ONBOARDING.md` (use for what templates can't express, e.g. recreating a symlink).
- `session_start` — shell commands appended to the `.claude` SessionStart hooks, run every
  session, each wrapped so a failure can't disrupt the session.

For `extends: default` they merge into the base's onboarding/hooks; standalone profiles get a
profile-only `ONBOARDING.md` and a minimal hooks `settings.json`. Hooks are recorded in the
manifest so a *degraded* update (profile unresolvable) keeps them.

## The contract fold (engine mechanic)

When a profile ships a file **and** declares links pointing at it (the AGENTS.md pattern), a
pre-existing real file at the target or at a link path is **folded** beneath the rendered
content — preserved verbatim under a `Preserved from your original <name>` marker, seeded as
the user's to reconcile, with the link then taking the file's place. Never clobbered, never
left to block the scaffold (RFC 2026-07-05, decided 2026-07-06).

## Safety and trust

Four independent layers (RFCs 2026-07-03-profile-safety, 2026-07-04-profile-fetch):

1. **Sandboxed rendering** — a hostile template can't reach Python.
2. **Path confinement** — `apply` refuses any output path that escapes the project (including
   via a pre-existing symlinked parent).
3. **Derived classification** — `classify_safety` computes `safe`/`unsafe` from *content*,
   never a declared field: `session_start` hooks, agent-executed `onboarding` steps, or a
   template writing an execution sink (`.github/workflows/`, `Makefile`, `pyproject.toml`, …)
   or any not-provably-inert path (allowlist + fail-closed: unknown ⇒ unsafe).
4. **Consent, bound to the artifact** — provenance is the source scheme: local/`~/.config`
   profiles are trusted; a **fetched** (`git+`) profile that classifies unsafe needs consent
   (`--allow-code` or an interactive yes), recorded per **content hash** (over `profile.json` +
   `templates/`) in `~/.config/agent-native-setup/trusted.json` — the same bytes never re-ask,
   any change re-asks. `profile trust --list` / `untrust` manage the store.

`update` re-gates: a breaking version bump pauses; *new* `session_start` commands are listed
and confirmed even on a non-breaking bump; a **safe → unsafe flip** gates; a re-fetched profile
re-passes consent on its new hash.

## Discovery (community index)

`contributions/index.json` is a curated, PR-gated list of `{name, url, description, author,
tags}` entries — a phone book, not a registry: profiles live in their own repos and a listing
grants no trust (RFC 2026-07-04-community-index). `profile search <query>` and
`list --community` read it via a bounded, daily-cached, silent-on-failure HTTP GET
(`AGENT_NATIVE_SETUP_INDEX_URL` points a team at a private index). `profile publish` prints a
profile's shareable URL (pinned `@<tag>` when the commit is tagged — else it nudges you to
tag) + ready-to-PR entry. Freeform `tags` on the profile are the
single source of truth, carried into the entry by `publish`. The `index-check` workflow
(weekly, on `contributions/` PRs, on demand; `task check-index` locally) fetches and validates
every listing so rot fails CI instead of the next adopter.

## Extension is git-native

There is deliberately no `extends: <url>` chain mechanism (RFC 2026-07-04-profile-extends):
to build on a community profile, fork its repo, keep `upstream` as a remote, and
`git fetch upstream && git merge` to take base improvements — reviewed, then released to your
own consumers through the normal version bump. Git's three-way merge handles shared-file
changes an overlay never could, and the extender stays the review point.

## Authoring journey

`profile init <name>` (`--standalone`) scaffolds the skeleton plus a field-reference README
and a meta `AGENTS.md` so an assistant can help build it; `profile save <project> <name>`
extracts a profile from a scaffolded project's *delta* against the regenerated default
(parameterizing name/slug, preserving `seed`, turning symlinks into onboarding steps);
`profile validate` loads it and strict-renders every template (undefined variable = error);
`profile publish` validates and prints the shareable URL + index entry. Fields are escaped
wherever fetched profiles are displayed (`show`/`list`/index output) — remote metadata is
untrusted display data.

## Integration points

| Where | What |
| --- | --- |
| `cli.build` | resolves the profile, gates consent, gathers answers, applies the overlay, records the manifest `profile` block (name/version/extends/source/safety/files/answers/hooks). |
| `scaffold.Scaffolder` | `overlay` (child-last write), sandboxed Jinja envs. |
| `update.py` | re-resolves from the recorded `source`, re-applies (managed refresh / conflict), version + new-hooks + safety-flip + re-consent gates, degraded mode (frozen files, kept hooks), `--check` staleness nudge. |
| `tools/checks/check_index.py` | the index-rot CI check (`.github/workflows/index-check.yml`). |
