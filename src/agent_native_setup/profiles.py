"""Scaffolding profiles (RFC 2026-06-23): compose a team's files on the default setup.

A profile is a directory with a ``profile.json`` and a ``templates/`` tree. ``extends: default``
means the wizard generates its normal output, then the profile's template files are overlaid on
top, superseding any base file at the same path. ``extends: null`` is **standalone** — the
default generators are skipped and the profile provides everything from scratch (its own
``AGENTS.md``, etc.). Each profile file is **managed** — refreshed by ``update`` when the profile
ships a new ``version`` — unless listed in the profile's ``seed`` set (written once, then the
user's).

Templates ending in ``.j2`` are rendered with Jinja against the project context (the ``.j2``
is stripped from the output path); every other file ships verbatim — so a profile can carry
files that contain ``{{ ... }}`` literally (e.g. a GitHub Actions ``${{ ... }}`` expression)
without Jinja mangling them.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_native_setup.config import WizardConfig
from agent_native_setup.scaffold import (
    Scaffolder,
    compile_expr,
    eval_expr,
    render,
    render_strict,
)

PROFILE_MANIFEST = "profile.json"
TEMPLATES_DIR = "templates"
USER_PROFILE_DIR = Path.home() / ".config" / "agent-native-setup" / "profiles"
EXTENDS_VALUES = ("default", None)  # "default" composes on the base; null = standalone
PROMPT_TYPES = ("text", "select", "confirm", "checkbox")


class ProfileError(Exception):
    """A profile that can't be loaded or is invalid. The message is user-facing."""


@dataclass(frozen=True)
class Prompt:
    """A question a profile asks at scaffold time (RFC 2026-06-26). The answer is exposed to
    templates as ``answers.<name>``."""

    name: str
    type: str  # one of PROMPT_TYPES
    message: str
    choices: tuple[str, ...] = ()
    default: object = None
    # A Jinja expression (over earlier answers + the base context); the prompt is only *asked*
    # when it's truthy. A skipped prompt takes its default. None = always ask.
    when: str | None = None

    @property
    def effective_default(self) -> object:
        """The non-interactive answer (`-y`/CI): the declared default, else a per-type default."""
        if self.default is not None:
            return self.default
        return {
            "text": "",
            "confirm": False,
            "checkbox": [],
            "select": self.choices[0] if self.choices else "",
        }[self.type]


@dataclass(frozen=True)
class Profile:
    name: str
    version: str
    extends: str | None  # "default" (compose on base) | None (standalone, from scratch)
    description: str
    root: Path  # the profile directory
    source: str  # the reference it was resolved from — recorded in the project manifest
    # Output paths the profile ships as **seed** (write-once, never refreshed). Everything else
    # under templates/ is **managed** — refreshed on update when the profile ships a new version.
    seed: frozenset[str] = frozenset()
    # One-time setup steps folded into ONBOARDING.md (the agent runs them once, on first
    # session) and shell commands appended to the .claude SessionStart hooks (run every session).
    onboarding: tuple[str, ...] = ()
    session_start: tuple[str, ...] = ()
    # Questions the profile asks at scaffold; answers feed templates as ``answers.<name>``.
    prompts: tuple[Prompt, ...] = ()

    @property
    def standalone(self) -> bool:
        """A standalone profile (``extends: null``) skips the default generators entirely."""
        return self.extends is None

    def template_files(self) -> list[tuple[str, Path]]:
        """``(output_rel, source_path)`` for each file under ``templates/``, with a trailing
        ``.j2`` stripped from the output path. Sorted, so application is deterministic."""
        base = self.root / TEMPLATES_DIR
        files: list[tuple[str, Path]] = []
        if base.is_dir():
            for p in sorted(base.rglob("*")):
                if p.is_file():
                    rel = p.relative_to(base).as_posix()
                    files.append((rel[:-3] if rel.endswith(".j2") else rel, p))
        return files

    def manifest_block(self) -> dict[str, object]:
        """The provenance block recorded in the project's ``.agent-native-setup.json``."""
        block: dict[str, object] = {
            "name": self.name,
            "version": self.version,
            "extends": self.extends,
            "source": self.source,
        }
        # Recorded so a degraded update (profile gone) can keep the SessionStart hooks instead
        # of regenerating settings.json without them. Onboarding is one-time/transient, so it
        # needs no recording.
        if self.session_start:
            block["session_start"] = list(self.session_start)
        return block


def _parse_prompts(data: dict, manifest_path: Path) -> tuple[Prompt, ...]:
    """Validate and build the profile's ``prompts`` (RFC 2026-06-26), with user-facing errors."""
    raw = data.get("prompts", [])
    if not isinstance(raw, list):
        raise ProfileError(f"{manifest_path}: 'prompts' must be a list")
    prompts: list[Prompt] = []
    seen: set[str] = set()
    for i, p in enumerate(raw):
        at = f"{manifest_path}: prompts[{i}]"
        if not isinstance(p, dict):
            raise ProfileError(f"{at} must be an object")
        name, ptype = p.get("name"), p.get("type")
        if not isinstance(name, str) or not name.isidentifier():
            raise ProfileError(
                f"{at} 'name' must be a valid identifier (it becomes answers.<name>)"
            )
        if name in seen:
            raise ProfileError(f"{at} duplicate name {name!r}")
        seen.add(name)
        if ptype not in PROMPT_TYPES:
            raise ProfileError(f"{at} 'type' must be one of {', '.join(PROMPT_TYPES)}")
        if not isinstance(p.get("message"), str) or not p["message"]:
            raise ProfileError(f"{at} 'message' is required")
        choices = p.get("choices", [])
        choices_ok = (
            isinstance(choices, list) and choices and all(isinstance(c, str) for c in choices)
        )
        if ptype in ("select", "checkbox") and not choices_ok:
            raise ProfileError(f"{at} ({ptype}) needs a non-empty 'choices' list of strings")
        default = p.get("default")
        if default is not None and not _default_ok(ptype, default, choices):
            raise ProfileError(f"{at} 'default' is not valid for a {ptype} prompt")
        when = p.get("when")
        if when is not None:
            if not isinstance(when, str):
                raise ProfileError(f"{at} 'when' must be a string (a Jinja expression)")
            try:
                compile_expr(when)  # fail at load on a bad expression, not mid-prompt
            except Exception as exc:
                raise ProfileError(f"{at} 'when' is not a valid expression: {exc}") from None
        prompts.append(Prompt(name, ptype, p["message"], tuple(choices), default, when))
    return tuple(prompts)


def _default_ok(ptype: str, default: object, choices: list) -> bool:
    if ptype == "text":
        return isinstance(default, str)
    if ptype == "confirm":
        return isinstance(default, bool)
    if ptype == "select":
        return default in choices
    return isinstance(default, list) and all(d in choices for d in default)  # checkbox


def load(path: Path, *, source: str | None = None) -> Profile:
    """Load and validate the profile at ``path``. ``source`` is the reference the user gave
    (recorded for provenance); defaults to the resolved path."""
    path = path.expanduser().resolve()
    manifest_path = path / PROFILE_MANIFEST
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ProfileError(f"no {PROFILE_MANIFEST} in {path}") from None
    except (OSError, ValueError) as exc:
        raise ProfileError(f"can't read {manifest_path}: {exc}") from None
    name, version = data.get("name"), data.get("version")
    if not name or not version:
        raise ProfileError(f"{manifest_path}: both 'name' and 'version' are required")
    if "extends" not in data:
        raise ProfileError(
            f"{manifest_path}: 'extends' is required — \"default\" (compose on the default setup) "
            "or null (standalone, from scratch)"
        )
    extends = data["extends"]  # explicit: "default" composes; null = standalone
    if extends not in EXTENDS_VALUES:
        raise ProfileError(
            f'{manifest_path}: extends={extends!r} is invalid — use "default" or null'
        )

    def _str_list(key: str) -> list[str]:
        value = data.get(key, [])
        if not isinstance(value, list) or not all(isinstance(s, str) for s in value):
            raise ProfileError(f"{manifest_path}: {key!r} must be a list of strings")
        return value

    return Profile(
        name=str(name),
        version=str(version),
        extends=extends,
        description=str(data.get("description", "")),
        root=path,
        source=source if source is not None else str(path),
        seed=frozenset(_str_list("seed")),
        onboarding=tuple(_str_list("onboarding")),
        session_start=tuple(_str_list("session_start")),
        prompts=_parse_prompts(data, manifest_path),
    )


def resolve(name_or_path: str) -> Profile | None:
    """Resolve a ``--profile`` reference. ``default`` (or empty) → ``None`` (the built-in
    default, no overlay). A path containing a ``profile.json`` → that profile. A bare name →
    the user profiles dir (``~/.config/agent-native-setup/profiles/<name>``). Raises
    ``ProfileError`` with a clear message when it can't be found."""
    if name_or_path in ("", "default"):
        return None
    candidate = Path(name_or_path).expanduser()
    if (candidate / PROFILE_MANIFEST).is_file():
        return load(candidate, source=name_or_path)
    in_user_dir = USER_PROFILE_DIR / name_or_path
    if (in_user_dir / PROFILE_MANIFEST).is_file():
        return load(in_user_dir, source=name_or_path)
    raise ProfileError(
        f"profile {name_or_path!r} not found — pass a path to a profile directory, or place it "
        f"under {USER_PROFILE_DIR}"
    )


def _context(config: WizardConfig, answers: dict[str, Any]) -> dict[str, Any]:
    """The variables a ``.j2`` profile template (and a prompt's ``when``) can reference. Prompt
    answers live under ``answers.<name>`` and detected/resolved environment facts under
    ``env.<name>`` — both namespaced so they can never shadow a base key."""
    return {
        "project_name": config.project_name,
        "slug": config.slug,
        "description": config.description,
        "languages": list(config.languages),
        "answers": dict(answers),
        "env": {
            "existing_project": config.existing_project,  # brownfield repo with source?
            "languages": list(config.languages),  # the selected languages
            "detected_languages": list(config.detected_languages),  # what's actually in the repo
            "existing_runner": config.existing_runner,
            "runner": config.runner,
            "adoption": config.adoption,
            "ai_tools": list(config.ai_tools),
            "has_quality": config.include_quality,
            "has_ci": config.include_ci,
            "has_docs": config.include_docs,
            "has_agents": config.include_agents,
            "has_security": config.include_security,
        },
    }


def default_answers(profile: Profile) -> dict[str, Any]:
    """The answers used non-interactively (`-y`/CI) or as the baseline an update replays from —
    each prompt's declared (or type) default."""
    return {p.name: p.effective_default for p in profile.prompts}


def gather_answers(profile: Profile, config: WizardConfig, *, interactive: bool) -> dict[str, Any]:
    """Resolve the profile's prompt answers: ask interactively, else use defaults. A prompt with
    a ``when`` is only asked when that expression (over the answers gathered so far + the base
    context) is truthy; a skipped prompt takes its default, so ``answers`` always has every name."""
    if not profile.prompts or not interactive:
        return default_answers(profile)
    import questionary

    answers: dict[str, Any] = {}
    for p in profile.prompts:
        d = p.effective_default
        if p.when is not None and not eval_expr(p.when, **_context(config, answers)):
            answers[p.name] = d  # condition false → don't ask, use the default
            continue
        if p.type == "text":
            answers[p.name] = questionary.text(p.message, default=str(d)).unsafe_ask()
        elif p.type == "confirm":
            answers[p.name] = questionary.confirm(p.message, default=bool(d)).unsafe_ask()
        elif p.type == "select":
            answers[p.name] = questionary.select(
                p.message, choices=list(p.choices), default=d if d in p.choices else None
            ).unsafe_ask()
        else:  # checkbox
            checked = set(d if isinstance(d, list) else [])
            answers[p.name] = questionary.checkbox(
                p.message,
                choices=[questionary.Choice(c, checked=c in checked) for c in p.choices],
            ).unsafe_ask()
    return answers


def apply(
    profile: Profile, config: WizardConfig, sc: Scaffolder, answers: dict[str, Any]
) -> list[str]:
    """Overlay ``profile``'s templates onto an already-generated scaffold. Files are **managed**
    (refreshed on update when the profile ships a new version) unless listed in the profile's
    ``seed`` set, which are written once. ``.j2`` files are rendered against the project context
    plus ``answers`` (and a ``.j2`` that renders empty is skipped — conditional inclusion);
    others ship verbatim. A file at the same path as a base file supersedes it.

    Returns the sorted list of paths the profile actually owns (those it wrote — a path where a
    user's own file pre-existed, or a ``.j2`` that rendered empty, is not claimed), so the
    project manifest records exactly them and ``update`` re-applies the profile to refresh them."""
    ctx = _context(config, answers)
    owned: list[str] = []
    for out_rel, src in profile.template_files():
        raw = src.read_text(encoding="utf-8")
        if src.name.endswith(".j2"):
            content = render(raw, **ctx)
            if not content.strip():
                continue  # conditional include: a .j2 that renders empty is not shipped
        else:
            content = raw
        if sc.overlay(out_rel, content, seed=out_rel in profile.seed):
            owned.append(out_rel)
    return sorted(owned)


# --- authoring CLI: `agent-native-setup profile <init|list>` ----------------------------

_SKELETON_README = """\
# {name} — agent-native-setup profile

{intro} When someone runs

```bash
agent-native-setup my-app -o ./my-app --profile {source_hint}
```

{result}

## Layout

- `profile.json` — name, version (your own semver), `extends` (`"default"` to compose on the
  base setup, or `null` to be standalone / from scratch), description, an optional `seed` list,
  and optional `onboarding` / `session_start` lists (below).
- `templates/` — the files this profile ships. Paths are relative to the project root, so
  `templates/.claude/agents/foo.md` lands at `.claude/agents/foo.md`. A file ending in
  `.j2` is rendered (Jinja) with `project_name`, `slug`, `description`, `languages`, the
  `answers.<name>` from your prompts, and an `env.<name>` namespace of detected facts
  (`env.existing_project`, `env.detected_languages`, `env.runner`, `env.has_ci`, …) — and the
  `.j2` stripped; anything else is copied verbatim (so files containing `{{{{ ... }}}}`,
  like GitHub Actions `${{{{ ... }}}}`, are safe).

## Prompts (a mini wizard)

`prompts` is a list of questions asked at scaffold time. Each is `{{"name", "type", "message",
"choices", "default"}}` where `type` is `text` / `select` / `confirm` / `checkbox` (`choices`
for select/checkbox). Answers are exposed to `.j2` templates under
`answers.<name>` — e.g. `{{{{ answers.tier }}}}`, `{{% if answers.use_db %}}…{{% endif %}}`. A
`.j2` that renders **empty** is not shipped, so wrap a whole file in `{{% if … %}}` for
conditional inclusion. A prompt may also carry a `when` (a Jinja expression over earlier
answers) so it's only asked when relevant — e.g. `"when": "answers.use_db"`. Non-interactive
runs (`-y`) use each prompt's `default`; the answers are recorded and replayed on `update`
(never re-asked).

## Startup instructions

- `onboarding` — a list of markdown steps folded into the project's `ONBOARDING.md`, which an
  agent runs **once** on first session (then it self-deletes). Use it for one-time setup
  ("run `task team-setup`", "request access to X") and for things a template can't express —
  e.g. "recreate the `CLAUDE.md` symlink: `ln -s AGENTS.md CLAUDE.md`".
- `session_start` — a list of shell commands appended to the `.claude` **SessionStart** hooks,
  run at the start of **every** session (e.g. `echo` a reminder into the agent's context). Each
  is wrapped so a failing command can't disrupt the session.

## Updating

Bump `version` when you change templates and your users run `agent-native-setup update`: every
file is **managed** (refreshed when they haven't edited it; reported as a conflict if they
have). List paths under `seed` for files you want shipped **once** and never refreshed (a
starter README, say). A breaking bump (major, or the minor pre-1.0) makes `update` pause for
confirmation. For `update` to pull your changes, the profile must still be resolvable then
(same path, or in `~/.config/agent-native-setup/profiles/`).

Add your files under `templates/`, then point `--profile` at this directory.
"""

_SKELETON_AGENTS = """\
# Building the {name} profile — agent contract

You're helping build an **agent-native-setup profile** in this directory. A profile is just two
things: `profile.json` (its config) and `templates/` (the files it ships into scaffolded
projects). **Everything else here — including this file — is ignored by the profile**; it's
scratch/harness for building it, so keep your notes, specs, and working files at the root, not
under `templates/`. See [`README.md`](./README.md) for the full field reference.

## Rules

- **Deliverables go in `templates/`.** A file at `templates/foo/bar.md` lands at `foo/bar.md` in
  every project scaffolded from this profile. Your own scratch stays **outside** `templates/` so
  it never ships.
- **Use `.j2` for anything project-specific.** A file ending in `.j2` is rendered (Jinja) with
  `project_name` / `slug` / `description` / `languages`, the profile's `answers.<name>`, and an
  `env.<name>` namespace (detected facts) — then the `.j2` is stripped. Everything else ships
  verbatim (so a literal `${{{{ ... }}}}` is safe).
- **Mark write-once files as `seed`** in `profile.json` (a starter README, say): seed files are
  shipped once and never overwritten by an update. Everything else under `templates/` is
  *managed* — refreshed when the profile ships a new `version`.
- **`extends`**: `"default"` composes on the built-in setup; `null` is standalone (from scratch —
  then ship the project's own `AGENTS.md` under `templates/AGENTS.md`, distinct from *this* file).
- **Before calling it done, run `agent-native-setup profile validate .`** and fix every finding —
  it loads the profile, strict-renders every template (catching typos), and checks `seed` entries.
"""


def _init(args: argparse.Namespace, console: Any) -> int:
    root = Path(args.output).expanduser().resolve() / args.name
    if root.exists():
        console.print(f"[red]{root} already exists[/] — choose another name or location.")
        return 2
    (root / TEMPLATES_DIR).mkdir(parents=True)
    (root / TEMPLATES_DIR / ".gitkeep").write_text("", encoding="utf-8")
    standalone = args.standalone
    manifest = {
        "name": args.name,
        "version": "0.1.0",
        "extends": None if standalone else "default",
        "description": "TODO: one line describing this profile",
        "seed": [],
        "onboarding": [],
        "session_start": [],
        "prompts": [],
    }
    (root / PROFILE_MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if standalone:
        intro = "A **standalone** profile (`extends: null`) — it replaces the default setup."
        result = (
            "they get **only** the files under `templates/` (no default scaffold), so ship "
            "your own `AGENTS.md`, etc."
        )
    else:
        intro = "A profile composed on the built-in `default` setup (`extends: default`)."
        result = "they get the normal scaffold **plus** every file under `templates/`."
    (root / "README.md").write_text(
        _SKELETON_README.format(
            name=args.name, source_hint=f"./{args.name}", intro=intro, result=result
        ),
        encoding="utf-8",
    )
    # An agent contract for *building* the profile: it lives at the profile root (not under
    # templates/), so it's meta — never shipped — and lets an assistant help author the profile.
    (root / "AGENTS.md").write_text(_SKELETON_AGENTS.format(name=args.name), encoding="utf-8")
    console.print(f"[green]Created {'standalone ' if standalone else ''}profile[/] {root}")
    console.print(
        f"  Add files under [bold]{args.name}/templates/[/], validate with "
        f"[bold]profile validate {root}[/], then scaffold with [bold]--profile {root}[/]."
    )
    console.print("  [dim]AGENTS.md guides an assistant building it; README.md has the details.[/]")
    return 0


def _validate(args: argparse.Namespace, console: Any) -> int:
    """Author-side check: the profile loads (schema/prompts/when), every ``.j2`` template renders,
    and each ``seed`` entry names a file the profile actually ships — so a broken profile is caught
    here, not when a consumer scaffolds with it. Rendering is *strict* (the validation context has
    the same keys as a real scaffold, so an undefined variable can only be a typo that scaffolding
    would silently leave blank) — catching both Jinja syntax errors and undefined-name typos."""
    root = Path(args.path).expanduser().resolve()
    try:
        prof = load(root)
    except ProfileError as exc:
        console.print(f"[red]✗ invalid:[/] {exc}")
        return 1
    errors: list[str] = []
    ctx = _context(
        WizardConfig(project_name="example", output_dir=root, languages=[]),
        default_answers(prof),
    )
    files = prof.template_files()
    for out_rel, src in files:
        if src.suffix == ".j2":
            try:
                render_strict(src.read_text(encoding="utf-8"), **ctx)
            except Exception as exc:  # Jinja syntax error or undefined variable — name the template
                errors.append(f"template {out_rel}: {exc}")
    outputs = {out_rel for out_rel, _ in files}
    for s in sorted(prof.seed):
        if s not in outputs:
            errors.append(f"seed entry {s!r} doesn't match any file under templates/")
    if errors:
        for e in errors:
            console.print(f"[red]✗[/] {e}")
        return 1
    console.print(
        f"[green]✓ {prof.name} {prof.version} valid[/] — extends={prof.extends!r}, "
        f"{len(files)} file(s), {len(prof.prompts)} prompt(s)."
    )
    return 0


def _list(console: Any) -> int:
    found = (
        sorted(p.parent for p in USER_PROFILE_DIR.glob(f"*/{PROFILE_MANIFEST}"))
        if USER_PROFILE_DIR.is_dir()
        else []
    )
    if not found:
        console.print(
            f"[yellow]No profiles in[/] {USER_PROFILE_DIR}. Create one with "
            "[bold]agent-native-setup profile init <name>[/], or pass a path to [bold]--profile[/]."
        )
        return 0
    console.print(f"[cyan]Profiles in[/] {USER_PROFILE_DIR}:")
    for d in found:
        try:
            p = load(d, source=d.name)
            console.print(
                f"  [bold]{p.name}[/] {p.version} — {p.description or '(no description)'}"
            )
        except ProfileError as exc:
            console.print(f"  [red]{d.name}[/] — invalid: {exc}")
    return 0


def run_cli(argv: list[str], console: Any) -> int:
    p = argparse.ArgumentParser(prog="agent-native-setup profile", description="Author profiles.")
    sub = p.add_subparsers(dest="cmd", required=True)
    init = sub.add_parser("init", help="scaffold a new profile skeleton")
    init.add_argument("name", help="profile name (also the directory name)")
    init.add_argument("-o", "--output", default=".", help="parent directory (default: cwd)")
    init.add_argument(
        "--standalone",
        action="store_true",
        help="extends: null — start from scratch instead of composing on the default",
    )
    sub.add_parser("list", help="list profiles in the user profiles dir")
    val = sub.add_parser("validate", help="check a profile loads and its templates render")
    val.add_argument("path", help="path to the profile directory")
    args = p.parse_args(argv)
    if args.cmd == "init":
        return _init(args, console)
    if args.cmd == "validate":
        return _validate(args, console)
    return _list(console)
