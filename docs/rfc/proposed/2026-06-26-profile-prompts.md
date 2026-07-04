# Profile prompts: a declarative wizard for profiles

- **Status:** Proposed
- **Date:** 2026-06-26
- **Author:** Luca Mastrostefano
- [ ] Implemented

## Context

Profiles (RFC 2026-06-23) compose a fixed setup on the default scaffold. They're **static**:
templates render against a fixed context (`project_name`/`slug`/`description`/`languages`) with
no way for a profile to ask its *own* questions. So a profile can ship "exactly our setup" but
not "our setup, **adapted**" — it can't prompt "which service tier?" and branch on the answer
the way the default wizard does (which is hand-written Python + `questionary`).

RFC 2026-06-23 §1 reserved a `config_schema` field for "the answers this profile accepts" but
left it unbuilt. This RFC realizes it as a concrete **`prompts`** contract: a profile declares
questions; the answers feed the template context and conditional file inclusion; the answers
are recorded so `update` re-renders deterministically without re-prompting.

Three constraints shape it:

1. **Declarative, not code.** The shared `contributions/` dir must stay reviewable as data
   (RFC 2026-06-23 §6), so prompts are declared in `profile.json`, never arbitrary code. The
   four base question types cover the common cases; arbitrary wizard logic stays the deferred
   code-profile path.
2. **Deterministic update.** Update must not re-prompt. Scaffold-time answers are recorded and
   replayed, so the same `(profile@version, answers)` reproduces the same output (the
   determinism contract, RFC 2026-06-23 §5).
3. **Non-interactive safe.** `-y` / CI runs can't prompt, so every prompt needs a usable
   default.

> **Implementation status.** Landed (`profiles.py` `Prompt`/`_parse_prompts`/`gather_answers`,
> the `answers` Jinja namespace + "renders-empty → skip", **conditional `when` prompts**,
> answers recorded in the manifest and replayed by `update`, and the **`--answer NAME=VALUE`**
> headless override — `parse_answer_overrides`, so an agent/CI run can answer a prompt with
> something other than its default). It stays under the still-`Proposed` scaffolding-profiles umbrella
> (RFC 2026-06-23), whose `- [ ] Implemented` tracks the whole feature; this slice is complete.

## Decision

### 1. `profile.json` gains a `prompts` array

```json
"prompts": [
  {"name": "tier",   "type": "select",   "message": "Service tier?",     "choices": ["basic", "enterprise"], "default": "basic"},
  {"name": "use_db", "type": "confirm",  "message": "Include the DB module?", "default": false},
  {"name": "engine", "type": "select",   "message": "DB engine?",        "choices": ["postgres", "mysql"], "when": "answers.use_db"},
  {"name": "svc",    "type": "text",     "message": "Service name?",      "default": "svc"}
]
```

Types map to the four `questionary` widgets the base wizard already uses: `text` (string),
`select` (one choice), `confirm` (bool), `checkbox` (list). An optional **`when`** (a Jinja
expression over the answers gathered so far plus the base context) makes a prompt
**conditional** — it's only *asked* when `when` is truthy, so a profile can branch its
questionnaire (ask `engine` only if `use_db`) the way the base wizard does. A skipped prompt
takes its default, so `answers` always has every name. Validated at **load** with clear errors:
each `name` is a unique, valid identifier (answers are read as `answers.<name>`); `type` is one
of the four; `select`/`checkbox` require non-empty `choices`; a `default` (if given) is
consistent with the type and within `choices`; a `when` (if given) compiles.

### 2. Answers feed the template context, and drive conditional file inclusion

Answers are exposed under an **`answers`** namespace in the Jinja context, so a `.j2` template
reads `{{ answers.svc }}`, `{% if answers.use_db %}…{% endif %}`, `{% if 'metrics' in
answers.extras %}…`. Namespacing (rather than top-level) means a prompt name can never shadow a
base context key (`profiles._context`'s keys) or a Jinja global — so the only name check needed
is uniqueness + valid identifier, with no brittle reserved-word list to maintain.

The detected/resolved **environment** is exposed under a parallel **`env`** namespace, so a
profile can adapt to the actual repo without code: `env.existing_project` (brownfield repo with
source?), `env.detected_languages` (auto-detected from marker files) and `env.languages` (the
selected set), `env.existing_runner` / `env.runner`, `env.adoption`, `env.ai_tools`, and the
`env.has_quality` / `has_ci` / `has_docs` / `has_agents` / `has_security` toggles. These are
facts the base wizard already computes; they're recorded in the manifest config snapshot, so an
`update` re-renders against the **same** environment (deterministic, no re-detection). Both
`answers` and `env` are usable in templates *and* in a prompt's `when`.

**Conditional whole-file inclusion** reuses Jinja with one rule: **a `.j2` template whose
rendered output is empty after `.strip()` is not written** (and not recorded). So a file wrapped
in `{% if answers.use_db %}…{% endif %}` ships only when `use_db` is true. Two clarifications:
- If the skipped path is a **new** file, nothing lands there.
- If it's an **override** of a base file at the same path, skipping leaves the **base's** version
  in place — the profile simply declines to supersede it (not an empty file).

Verbatim (non-`.j2`) files always ship — an author who wants a literal empty file ships it
verbatim.

### 3. Prompting: interactive at scaffold, recorded for update

- **Scaffold, interactive:** after resolving the profile, run each prompt via `questionary`, in
  order — a prompt with a `when` that evaluates falsy (against the answers gathered so far) is
  skipped and takes its default. So `when` only changes *which questions appear*.
- **Scaffold, non-interactive (`-y` / no TTY):** use each prompt's `default` (unless overridden
  with `--answer name=value` — validated against the prompt's type), or a type default
  (`""` / `false` / first choice / `[]`). `when` is moot here — nothing is asked.
- **Recorded:** the resolved answers are stored in the manifest's `profile` block
  (`"answers": {…}`), beside the version and owned files.
- **Update:** the engine reads the recorded answers and re-renders with them — **never
  re-prompting**. A prompt a bumped profile *added* (no recorded answer) falls back to its
  `default`; a *removed* prompt's stale answer is ignored. Same `(version, answers)` → same
  output, so the conditional file set is deterministic.

### 4. Owned-files accuracy — at scaffold *and* update

Because conditional inclusion makes the owned set depend on the answers, the manifest must
record the files the profile **actually wrote** (from `apply`'s result), not every template.
Scaffold already does this (`cli.build` records `apply`'s return). The **update path is the one
that must change**: today it rebuilds the block's `files` from `template_files()` (every
template, in `update._reresolve_profile`) and persists *that* — which conditional inclusion
would make wrong (claiming a skipped file). The engine instead takes the owned set from the
**re-application against the recorded answers**: `build` returns the accurate block (real files
+ the answers it used), and the update persists *that*, not a pre-render guess. With the set
accurate, `classify` handles a changed answer correctly — a newly-included file is a `create`,
a newly-excluded pristine one a removed orphan.

## Consequences

- Profiles gain "a wizard" — **declaratively, without code** — closing the biggest
  expressiveness gap with the default system, while staying reviewable data fit for the
  `contributions/` dir.
- It is **less powerful than the default's hand-written wizard**: four declared question types,
  declarative conditions, no cross-question logic beyond what Jinja expresses. Arbitrary wizard
  logic remains the deferred code-profile path — an honest, named ceiling.
- The manifest's `profile` block grows an `answers` map — a new recorded contract, and (like the
  rest of the block) a **manifest-schema commitment**: once profiles in the wild record it, the
  shape is a one-way door.
- **Conditional inclusion makes removal a function of a profile's evolution.** A managed profile
  file that renders empty after a version bump (a changed template, or a default-flipping new
  prompt) is **dropped** on update — an orphan-remove if the user left it pristine, a surfaced
  conflict if they edited it (never silently lost). That's the honest cost of "renders-empty →
  skip": a file can disappear from a re-render the user didn't directly trigger, but only when
  they hadn't touched it.
- "Renders-empty → skip" is a small implicit rule, scoped to `.j2` files and pinned to
  `.strip()`. The owned-files-accuracy change (§4) is a strict improvement at scaffold and a
  real fix on update.
- New validation surface (names, types, choices, defaults) — caught at load with clear errors,
  before a bad profile reaches a consumer. `profile init` ships an empty `prompts: []`.

## Alternatives considered

- **Per-file `when` conditions in `profile.json`.** A parallel map of path→expression for
  inclusion. Rejected: a second mini-language beside Jinja that duplicates what `{% if %}`
  already says; "renders-empty → skip" reuses the templating the profile already has.
- **Top-level answers (`{{ tier }}`).** Cleaner templates, but a prompt name can shadow a base
  context key (and `_context`'s keys evolve) or a Jinja global, needing a brittle, drifting
  reserved-word check. Rejected for the `answers` namespace — collision-proof for a touch of
  verbosity, with only a uniqueness/identifier check needed.
- **Re-prompt on update.** Simplest, but breaks determinism and nags the user on every refresh.
  Rejected: record answers, replay them.
- **Code profiles (a Python wizard).** Full power, matches the default. Rejected for this slice:
  arbitrary execution can't live in the shared dir; it's the separately-deferred plugin path.
- **More question types (path, password, validation regexes).** Rejected for now as scope: the
  four base types cover the common cases; add types when a real profile needs one.
