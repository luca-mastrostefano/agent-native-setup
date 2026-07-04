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
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
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
CACHE_ROOT = Path.home() / ".cache" / "agent-native-setup" / "profiles"
TRUST_STORE = Path.home() / ".config" / "agent-native-setup" / "trusted.json"
# git+https:// / git+ssh:// only — never ext::/file::/transport-command URLs, which run a shell
# command at clone time (RFC 2026-07-04 §1). An enforced allowlist, not a convention.
ALLOWED_TRANSPORTS = ("https", "ssh")
# Community index (RFC 2026-07-04-community-index): a curated list of profile URLs. The canonical
# one lives in this repo; a private/team index overrides via the env var. Fetched as *data* only.
INDEX_URL = (
    "https://raw.githubusercontent.com/luca-mastrostefano/agent-native-setup/main/"
    "contributions/index.json"
)
INDEX_ENV = "AGENT_NATIVE_SETUP_INDEX_URL"
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
    # Freeform discovery tags — who/what it targets (e.g. "backend", "frontend", "design",
    # "python", "general"). Advisory metadata; carried into the community index by `publish`.
    tags: tuple[str, ...] = ()

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
                if p.is_symlink() or not p.is_file():
                    continue  # skip symlinks — a template pointing outside the profile can't ship
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
            # The derived safety tier (RFC 2026-07-03-profile-safety §4), so `update` can re-derive
            # and gate a safe → unsafe transition — new code the user hasn't consented to.
            "safety": classify_safety(self)[0],
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
        tags=tuple(_str_list("tags")),
    )


def _parse_git_url(spec: str) -> tuple[str, str, str]:
    """Parse ``git+<transport>://…[@ref][#subdir=path]`` → ``(clone_url, ref, subdir)``, enforcing
    the https/ssh transport allowlist. The ``@ref`` lives in the *path* (after the first ``/`` past
    ``://``) so it's never confused with an ssh URL's ``user@host``."""
    body = spec[len("git+") :]
    subdir = ""
    if "#subdir=" in body:
        body, subdir = body.split("#subdir=", 1)
    if "://" not in body:
        raise ProfileError(
            f"invalid git profile URL {spec!r} — expected git+https://… / git+ssh://…"
        )
    scheme = body.split("://", 1)[0]
    if scheme not in ALLOWED_TRANSPORTS:
        raise ProfileError(
            f"unsupported transport {scheme!r} in {spec!r} — only git+https:// and git+ssh:// are "
            "allowed (ext::/file:: can execute a command at clone time)"
        )
    ref = ""
    slash = body.find("/", body.index("://") + 3)
    if slash != -1 and "@" in body[slash:]:
        idx = body.rindex("@")
        body, ref = body[:idx], body[idx + 1 :]
    subdir = subdir.strip("/")
    if ref.startswith("-"):  # else git parses it as an option, not a ref (argument injection)
        raise ProfileError(f"invalid ref {ref!r} in {spec!r} — a ref can't start with '-'")
    if ".." in Path(subdir).parts:  # confine the subdir to the cache (no traversal escape)
        raise ProfileError(f"invalid subdir {subdir!r} in {spec!r} — '..' is not allowed")
    return body, ref, subdir


def _pinned(ref: str) -> bool:
    """A ref that names an immutable point (a commit sha or a version tag) → cache forever; a
    branch (``main``) is a moving target → re-fetch."""
    return bool(re.match(r"^[0-9a-f]{7,40}$", ref) or re.match(r"^v?\d", ref))


def _fetch_git(spec: str, console: Any) -> Path:
    """Clone (or reuse) a git-URL profile into the cache and return its directory. **Data-only**:
    the transport allowlist (`_parse_git_url`) + ``--no-recurse-submodules`` mean nothing runs at
    fetch time (RFC 2026-07-04 §1). A pinned ref is cached forever; a moving ref re-fetches; on a
    fetch failure an existing cache is reused with a warning."""
    clone_url, ref, subdir = _parse_git_url(spec)
    cache_dir = CACHE_ROOT / hashlib.sha256(spec.encode()).hexdigest()[:16]
    root = cache_dir / subdir if subdir else cache_dir
    if ref and _pinned(ref) and (root / PROFILE_MANIFEST).is_file():
        return root  # immutable → reuse, no network
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    staging = cache_dir.with_name(cache_dir.name + ".new")
    if staging.exists():
        shutil.rmtree(staging)
    try:
        subprocess.run(
            ["git", "clone", "--quiet", "--no-recurse-submodules", clone_url, str(staging)],
            check=True,
            capture_output=True,
            timeout=120,
        )
        if ref:
            subprocess.run(
                ["git", "-C", str(staging), "checkout", "--quiet", ref],
                check=True,
                capture_output=True,
                timeout=30,
            )
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
        staging.rename(cache_dir)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        if staging.exists():
            shutil.rmtree(staging)
        if (root / PROFILE_MANIFEST).is_file():
            console.print(f"[yellow]Couldn't fetch {spec} — using the cached copy.[/]")
        else:
            err = getattr(exc, "stderr", b"") or b""
            detail = err.decode(errors="replace").strip() if isinstance(err, bytes) else str(exc)
            raise ProfileError(f"failed to fetch profile {spec!r}: {detail[:300]}") from None
    if not (root / PROFILE_MANIFEST).is_file():
        where = f" (subdir {subdir!r})" if subdir else ""
        raise ProfileError(f"no {PROFILE_MANIFEST} in fetched profile {spec!r}{where}")
    return root


def resolve(name_or_path: str, *, console: Any = None) -> Profile | None:
    """Resolve a ``--profile`` reference. ``default`` (or empty) → ``None`` (the built-in
    default, no overlay). A ``git+https://…`` / ``git+ssh://…`` URL → fetched into the cache. A path
    containing a ``profile.json`` → that profile. A bare name → the user profiles dir
    (``~/.config/agent-native-setup/profiles/<name>``). The recorded ``source`` is the reference
    verbatim, so ``update`` re-resolves (and re-fetches a URL). Raises ``ProfileError`` when it
    can't be found."""
    if name_or_path in ("", "default"):
        return None
    if name_or_path.startswith("git+"):
        return load(_fetch_git(name_or_path, console or _NullConsole()), source=name_or_path)
    candidate = Path(name_or_path).expanduser()
    if (candidate / PROFILE_MANIFEST).is_file():
        return load(candidate, source=name_or_path)
    in_user_dir = USER_PROFILE_DIR / name_or_path
    if (in_user_dir / PROFILE_MANIFEST).is_file():
        return load(in_user_dir, source=name_or_path)
    raise ProfileError(
        f"profile {name_or_path!r} not found — pass a path, a git+https://… URL, or a name "
        f"under {USER_PROFILE_DIR}"
    )


class _NullConsole:
    def print(self, *args: object, **kwargs: object) -> None: ...


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


def parse_answer_overrides(pairs: list[str], profile: Profile) -> dict[str, Any]:
    """Parse ``--answer NAME=VALUE`` pairs against the profile's prompts (RFC 2026-06-26) — the
    headless way to answer a prompt with something other than its default. Each name must match a
    prompt and each value must fit its type (select/checkbox members checked against ``choices``,
    confirm parsed as a boolean word); errors are user-facing ``ProfileError``s."""
    prompts = {p.name: p for p in profile.prompts}
    overrides: dict[str, Any] = {}
    for pair in pairs:
        name, eq, value = pair.partition("=")
        if not eq:
            raise ProfileError(f"--answer {pair!r} is not NAME=VALUE")
        p = prompts.get(name)
        if p is None:
            known = ", ".join(prompts) or "(this profile has no prompts)"
            raise ProfileError(f"--answer: no prompt named {name!r} — prompts: {known}")
        if name in overrides:  # a silent last-wins could mask a pipeline copy-paste mistake
            raise ProfileError(f"--answer {name!r} given more than once")
        if p.type == "text":
            overrides[name] = value
        elif p.type == "confirm":
            word = value.strip().lower()
            if word not in ("true", "false", "yes", "no", "1", "0"):
                raise ProfileError(f"--answer {name}: {value!r} is not a boolean (true/false)")
            overrides[name] = word in ("true", "yes", "1")
        elif p.type == "select":
            if value not in p.choices:
                raise ProfileError(
                    f"--answer {name}: {value!r} is not a choice ({', '.join(p.choices)})"
                )
            overrides[name] = value
        else:  # checkbox: comma-separated members ("" = none)
            picked = [v for v in (s.strip() for s in value.split(",")) if v]
            bad = [v for v in picked if v not in p.choices]
            if bad:
                raise ProfileError(
                    f"--answer {name}: {', '.join(bad)} not in choices ({', '.join(p.choices)})"
                )
            overrides[name] = picked
    return overrides


def gather_answers(
    profile: Profile,
    config: WizardConfig,
    *,
    interactive: bool,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve the profile's prompt answers: ask interactively, else use defaults. A prompt with
    a ``when`` is only asked when that expression (over the answers gathered so far + the base
    context) is truthy; a skipped prompt takes its default, so ``answers`` always has every name.
    ``overrides`` (from ``--answer``) win unconditionally — an overridden prompt is never asked,
    and its answer feeds later ``when`` expressions."""
    overrides = overrides or {}
    if not profile.prompts or not interactive:
        return {**default_answers(profile), **overrides}
    import questionary

    answers: dict[str, Any] = {}
    for p in profile.prompts:
        d = p.effective_default
        if p.name in overrides:
            answers[p.name] = overrides[p.name]
            continue
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
    target_root = sc.target.resolve()
    owned: list[str] = []
    for out_rel, src in profile.template_files():
        # Path confinement (RFC 2026-07-03-profile-safety §2): refuse an output that escapes the
        # project before writing. `out_rel` comes from `relative_to(templates/)` so it can't itself
        # be absolute or contain `..`; the real vector this catches is a **symlink parent already in
        # the target** that redirects the write outside (resolve() follows it). Defensive against
        # the others too.
        dest = (sc.target / out_rel).resolve()
        if dest != target_root and target_root not in dest.parents:
            raise ProfileError(f"profile output path escapes the project: {out_rel!r}")
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
  base setup, or `null` to be standalone / from scratch), description, optional `tags` (freeform
  discovery keywords — who/what it targets, e.g. `backend` / `frontend` / `design` / `general`),
  an optional `seed` list, and optional `onboarding` / `session_start` lists (below).
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
runs (`-y`) use each prompt's `default` unless overridden headlessly with
`--answer name=value`; the answers are recorded and replayed on `update` (never re-asked).

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
        "tags": [],
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
    tier, reasons = classify_safety(prof)
    console.print(
        f"[green]✓ {prof.name} {prof.version} valid[/] — extends={prof.extends!r}, "
        f"{len(files)} file(s), {len(prof.prompts)} prompt(s), safety: [bold]{tier}[/]."
    )
    if reasons:
        console.print(
            f"  [dim]{tier} because:[/] {'; '.join(reasons[:4])}"
            + (" …" if len(reasons) > 4 else "")
        )
    return 0


# Files a saved profile captures only when user-*added* under these prefixes — dirs the scaffold
# owns exclusively, so a new file there is house content, not the project's own source.
_SETUP_ADD_DIRS = (".claude/", "tools/checks/")
# Date-stamped, regenerated fresh per project → non-deterministic; never a real delta.
_BOOTSTRAP_RFC = re.compile(r"docs/rfc/.+-adopt-agent-native-setup\.md$")
# Writing any of these is code-by-proxy (RFC 2026-07-03-ecosystem-core §4) → the profile is
# "unsafe" (see classify_safety). Not exhaustive by design — the classifier fails closed, so any
# path that's neither a known sink nor known-inert is treated as unsafe anyway.
_SINK_PREFIXES = (".git/hooks/", ".github/workflows/", ".claude/settings.json", ".vscode/")
_SINK_NAMES = (
    "Makefile",
    "Taskfile.yml",
    "taskfile.yml",
    "justfile",
    ".pre-commit-config.yaml",
    ".envrc",
    "pyproject.toml",
    "package.json",
    "conftest.py",
    "sitecustomize.py",
    "setup.cfg",
    "tox.ini",
    ".gitattributes",
)
# Provably-inert output paths — the only ones that let a profile earn a `safe` verdict. Kept
# minimal; the set grows to earn more profiles `safe` (RFC 2026-07-03-profile-safety §1, Open Qs).
_INERT_SUFFIXES = (".md", ".txt", ".rst")
_INERT_NAMES = (".gitignore", ".editorconfig", "LICENSE", "LICENSE.md", "NOTICE")


def _is_sink(out_rel: str) -> bool:
    return out_rel.startswith(_SINK_PREFIXES) or out_rel.rsplit("/", 1)[-1] in _SINK_NAMES


def _is_inert(out_rel: str) -> bool:
    return out_rel.endswith(_INERT_SUFFIXES) or out_rel.rsplit("/", 1)[-1] in _INERT_NAMES


def classify_safety(profile: Profile) -> tuple[str, list[str]]:
    """Derive a profile's safety tier from its *content* (RFC 2026-07-03-profile-safety §1) — never
    a declared field. ``"unsafe"`` when it carries code: ``session_start`` hooks (every session),
    agent-executed ``onboarding`` steps, or a template that writes an execution sink or a
    not-provably-inert path (allowlist + fail-closed: unknown ⇒ unsafe). Returns ``(tier, reasons)``
    with the concrete reasons, so consent (once fetch gates on it) can be informed."""
    reasons: list[str] = []
    if profile.session_start:
        reasons.append(f"{len(profile.session_start)} session_start hook(s) run every session")
    if profile.onboarding:
        reasons.append(f"{len(profile.onboarding)} onboarding step(s) are agent-executed")
    for out_rel, _ in profile.template_files():
        if _is_sink(out_rel):
            reasons.append(f"writes an execution sink: {out_rel}")
        elif not _is_inert(out_rel):
            reasons.append(f"writes a not-provably-inert file: {out_rel}")
    return ("unsafe" if reasons else "safe", reasons)


# --- fetch trust: content-hash pre-trust + consent (RFC 2026-07-04) --------------------------


def content_hash(profile: Profile) -> str:
    """A stable hash over **exactly `profile.json` + every file under `templates/`** — the surface
    that gets applied and copied — so consent binds to precisely what lands, version-independent of
    any tag (RFC 2026-07-04 §4)."""
    entries = [("profile.json", (profile.root / PROFILE_MANIFEST).read_bytes())]
    entries += [(out_rel, src.read_bytes()) for out_rel, src in profile.template_files()]
    h = hashlib.sha256()
    for rel, data in sorted(entries):
        h.update(rel.encode() + b"\0" + hashlib.sha256(data).hexdigest().encode() + b"\n")
    return h.hexdigest()


def is_untrusted_source(source: str) -> bool:
    """A fetched (URL) profile is untrusted provenance; a local path / ``~/.config`` name is
    trusted (you have it / authored it) — provenance is the source scheme (RFC 2026-07-04 §3)."""
    return source.startswith("git+")


def _load_trust() -> dict[str, str]:
    try:
        data = json.loads(TRUST_STORE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_trust(store: dict[str, str]) -> None:
    TRUST_STORE.parent.mkdir(parents=True, exist_ok=True)
    TRUST_STORE.write_text(json.dumps(store, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def consent(profile: Profile, *, allow_code: bool, interactive: bool, console: Any) -> bool:
    """Gate a **fetched, code-carrying** profile (RFC 2026-07-04 §4). Returns True to proceed.
    A trusted-provenance (local) or `safe` profile passes freely; an `unsafe` fetched profile whose
    content hash isn't already trusted needs consent (`--allow-code` or an interactive yes), which
    is then recorded **per artifact** so a re-fetch of the same content doesn't re-ask."""
    if not is_untrusted_source(profile.source):
        return True  # local / authored → trusted
    tier, reasons = classify_safety(profile)
    if tier == "safe":
        return True  # provably can't run code (sandboxed, confined, no hooks/sinks)
    h = content_hash(profile)
    if h in _load_trust():
        return True  # this exact artifact was consented before
    console.print(
        f":warning:  [yellow]{profile.name!r} is a fetched, code-carrying (unsafe) profile[/] — "
        "it will run code on your machine:"
    )
    for r in reasons:
        console.print(f"  [yellow]•[/] {r}")
    if allow_code or (interactive and _confirm_trust(profile.name)):
        store = _load_trust()
        store[h] = profile.name
        _save_trust(store)
        return True
    if interactive:
        console.print("[yellow]Declined[/] — not applied.")
    else:
        console.print(
            "[red]Refused[/] — a fetched code-carrying profile needs [bold]--allow-code[/] "
            "(or run interactively to confirm)."
        )
    return False


def _confirm_trust(name: str) -> bool:
    import questionary

    return bool(questionary.confirm(f"Trust {name!r} and run its code?", default=False).ask())


# --- community index: discovery (RFC 2026-07-04-community-index) ------------------------------

_INDEX_CACHE_TTL = 24 * 60 * 60  # a listing is a moving target — refresh at most daily
_INDEX_FAILURE_TTL = 60 * 60  # cache a failure briefly so we don't re-pay the timeout each run


def _index_cache_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return Path(base) / "agent-native-setup" / "community-index.json"


def _fetch_index(now: float) -> list[dict]:
    """The community index entries, served from a <24h cache when possible. Read-only, **data
    only** (never clones/applies), and **silent on any failure** → ``[]`` (like `update --check`).
    Entries are validated for shape only; a listing grants no trust — the URL still goes through the
    fetch allowlist + consent gate at `add` time."""
    url = os.environ.get(INDEX_ENV) or INDEX_URL
    path = _index_cache_path()
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.get("url") == url:  # a changed index URL invalidates the cache
            ttl = _INDEX_CACHE_TTL if cached.get("entries") else _INDEX_FAILURE_TTL
            if now - cached.get("checked_at", 0) < ttl:
                return cached.get("entries") or []
    except (OSError, ValueError):
        pass
    entries: list[dict] | None = None
    try:
        if url.startswith(("https://", "http://")):  # http(s) only — never file:// etc.
            import urllib.request

            with urllib.request.urlopen(url, timeout=2.0) as resp:
                data = json.loads(resp.read(1_000_000))  # cap the body — a larger index is hostile
            raw = data.get("profiles") if isinstance(data, dict) else None
            if isinstance(raw, list):
                entries = [e for e in raw if isinstance(e, dict) and e.get("name") and e.get("url")]
    except Exception:  # network / parse failure — advisory only, never raise
        entries = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"checked_at": now, "url": url, "entries": entries}), encoding="utf-8"
        )
    except OSError:
        pass
    return entries or []


def _print_index_entries(entries: list[dict], console: Any) -> None:
    from rich.markup import escape  # entry fields are attacker-controlled remote data — never let

    for e in entries:  # them inject console markup (a forged "verified" line, hidden text, …)
        name, url = escape(str(e["name"])), escape(str(e["url"]))
        desc = escape(str(e.get("description", "")))
        console.print(f"  [bold]{name}[/]{' — ' + desc if desc else ''}")
        console.print(f"    [dim]{url}[/]")
    console.print(
        "\n[dim]A listing isn't vetting — `profile add <name>` (or `show <name>` to inspect "
        "first) classifies it, and an unsafe (code-carrying) profile asks for consent.[/]"
    )


def _index_url_for(name: str) -> str | None:
    """Exact-name lookup in the community index — the ``add <name>`` fallback. Data-only."""
    import time

    for e in _fetch_index(time.time()):
        if e["name"] == name:
            return str(e["url"])
    return None


def _resolve_ref(ref: str, console: Any) -> Profile | None:
    """``resolve``, falling back to an exact-name community-index lookup for a bare name
    (RFC 2026-07-04-community-index §6) — so ``add``/``show`` work straight off a ``search`` hit
    without copy-pasting the URL. Locals always win (the fallback only runs when ``resolve``
    finds nothing); the resolved URL goes through the identical transport allowlist and consent
    gate as a hand-typed one, and the printed line keeps the redirection visible."""
    try:
        return resolve(ref, console=console)
    except ProfileError:
        # Only a bare name consults the index — never a URL or anything path-shaped.
        if ref.startswith("git+") or "/" in ref or "\\" in ref:
            raise
        url = _index_url_for(ref)
        if url is None:
            raise
        from rich.markup import escape  # the URL is attacker-controlled index data

        console.print(f"[dim]{escape(ref)} → community index → {escape(url)}[/]")
        return resolve(url, console=console)


def _search(args: argparse.Namespace, console: Any) -> int:
    import time

    entries = _fetch_index(time.time())
    if not entries:
        console.print("[yellow]Couldn't reach the community index[/] (offline, or it's empty).")
        return 0
    q = args.query.lower()
    hits = [
        e
        for e in entries
        if q in e["name"].lower()
        or q in e.get("description", "").lower()
        or q in " ".join(e.get("tags", [])).lower()
    ]
    if not hits:
        console.print(f"[yellow]No community profiles match {args.query!r}.[/]")
        return 0
    console.print(f"[cyan]Community profiles matching {args.query!r}:[/]")
    _print_index_entries(hits, console)
    return 0


def _publish(args: argparse.Namespace, console: Any) -> int:
    """Validate a profile and print its shareable URL + a ready-to-PR index entry — the tail of the
    author flow (RFC 2026-07-04-community-index §5). Does not push or open a PR."""
    root = Path(args.path).expanduser().resolve()
    if _validate(argparse.Namespace(path=str(root)), console) != 0:
        return 1
    prof = load(root)
    url = args.url or _infer_git_url(root)
    tag = _git_tag(root)
    if url and tag:
        url = f"{url}@{tag}"
    elif url:
        console.print(
            "[yellow]No tag on the current commit[/] — tag a version "
            "([bold]git tag v1.0.0[/]) and append [bold]@v1.0.0[/] to the URL for a reproducible "
            "listing."
        )
    url = url or "git+https://<your-repo>.git@v1.0.0"
    entry = {
        "name": prof.name,
        "url": url,
        "description": prof.description,
        "author": "TODO: your name/handle",
        "tags": list(prof.tags),  # carried from the profile's own tags
    }
    console.print(f"\n[green]Shareable URL:[/] [bold]--profile {url}[/]")
    console.print("[green]Add this entry[/] to a PR against `contributions/index.json`:")
    console.print(json.dumps(entry, indent=2))
    return 0


def _infer_git_url(path: Path) -> str | None:
    """Best-effort ``git+https://…`` from the profile dir's ``origin`` remote (https or ssh)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    remote = out.stdout.strip()
    if remote.startswith("https://"):
        return "git+" + remote
    m = re.match(r"git@([^:]+):(.+)", remote)  # git@host:owner/repo(.git) → git+ssh://…
    return f"git+ssh://git@{m.group(1)}/{m.group(2)}" if m else None


def _git_tag(path: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "describe", "--tags", "--exact-match"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else None
    except (OSError, subprocess.SubprocessError):
        return None


def _parameterize(
    content: bytes, name: str, slug: str, rel: str, subs: list[tuple[str, str, int]]
) -> tuple[str | None, str]:
    """Return ``(text_or_None, template_name)``. Word-boundary-substitutes the project name/slug
    with ``{{ project_name }}`` / ``{{ slug }}`` (never a substring), recording each in ``subs``.
    A parameterized file gets a ``.j2`` suffix; a binary/undecodable file ships verbatim."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return None, rel  # binary → verbatim, no rendering
    tokens = [(name, "{{ project_name }}")]
    if slug and slug != name:  # if slug == name we can't tell which token a match wants → use name
        tokens.append((slug, "{{ slug }}"))
    total = 0
    for needle, token in tokens:
        if not needle:
            continue
        pat = re.compile(r"\b" + re.escape(needle) + r"\b")
        n = len(pat.findall(text))
        if n:
            text = pat.sub(token, text)
            subs.append((rel, token, n))
            total += n
    return text, (rel + ".j2" if total else rel)


def _save(args: argparse.Namespace, console: Any) -> int:
    """Extract an ``extends: default`` profile from a scaffolded project's *delta* from the default
    (RFC 2026-07-03-profile-save). Read-only on the source; writes a review-ready draft."""
    from agent_native_setup import manifest as manifest_mod
    from agent_native_setup import update

    project = Path(args.project).expanduser().resolve()
    old = update._load_manifest(project)
    if old is None:
        console.print(
            f"[red]No {manifest_mod.MANIFEST_PATH} in {project}[/] — `profile save` needs a "
            "project that agent-native-setup scaffolded."
        )
        return 2
    out = Path(args.output).expanduser().resolve() / args.name
    if out.exists():
        console.print(f"[red]{out} already exists[/] — choose another name or location.")
        return 2

    files: dict[str, str] = old.get("files", {})
    seed_set = set(old.get("seed", []))
    captured: dict[str, tuple[bytes, bool]] = {}  # rel -> (content, is_seed)
    onboarding_steps: list[str] = []
    excluded: list[str] = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        config = update._config_from_manifest(old, tmp_path)
        update._regenerate(config, tmp_path)  # the default baseline the project was born from

        for rel in sorted(files):
            if rel == manifest_mod.MANIFEST_PATH:
                continue
            if _BOOTSTRAP_RFC.search(rel):  # non-deterministic → not a real delta
                excluded.append(rel)
                continue
            pf = project / rel
            if pf.is_symlink():  # templates can't carry a symlink → recreate it via onboarding
                target = os.readlink(pf)
                onboarding_steps.append(f"Recreate the `{rel}` symlink: `ln -s {target} {rel}`")
                continue
            if not pf.is_file():
                continue  # user deleted it — nothing to capture
            content = pf.read_bytes()
            base = tmp_path / rel
            if base.is_file() and base.read_bytes() == content:
                continue  # pristine → the default provides it; the profile extends it
            captured[rel] = (content, rel in seed_set)  # edited → the user's version

        # User-added files, only where the scaffold owns the directory (else it's their source).
        transient = {"ONBOARDING.md", ".claude/commands/onboard.md"}  # one-time, self-deleting
        added_elsewhere: list[str] = []
        for pf in sorted(project.rglob("*")):
            if not pf.is_file() or pf.is_symlink():
                continue
            rel = pf.relative_to(project).as_posix()
            if rel in files or rel == manifest_mod.MANIFEST_PATH or rel.startswith(".git/"):
                continue
            if rel in transient:
                continue  # never capture the transient first-run apparatus
            if any(rel.startswith(d) for d in _SETUP_ADD_DIRS):
                captured[rel] = (pf.read_bytes(), False)  # house content → managed
            else:
                added_elsewhere.append(rel)

    # Write the profile: render captured files into templates/, parameterizing name/slug.
    (out / TEMPLATES_DIR).mkdir(parents=True)
    subs: list[tuple[str, str, int]] = []
    seed_list: list[str] = []
    for rel, (content, is_seed) in sorted(captured.items()):
        text, tmpl_name = _parameterize(content, config.project_name, config.slug, rel, subs)
        dst = out / TEMPLATES_DIR / tmpl_name
        dst.parent.mkdir(parents=True, exist_ok=True)
        if text is None:
            dst.write_bytes(content)
        else:
            dst.write_text(text, encoding="utf-8")
        if is_seed:
            seed_list.append(rel)

    pj = {
        "name": args.name,
        "version": "0.1.0",
        "extends": "default",
        "description": f"TODO: describe this profile (saved from {project.name}).",
        "tags": [],
        "seed": sorted(seed_list),
        "onboarding": onboarding_steps,
        "session_start": [],
        "prompts": [],
    }
    (out / PROFILE_MANIFEST).write_text(json.dumps(pj, indent=2) + "\n", encoding="utf-8")
    (out / "README.md").write_text(
        _SKELETON_README.format(
            name=args.name,
            source_hint=f"./{args.name}",
            intro="A profile composed on the built-in `default` setup (`extends: default`).",
            result="they get the normal scaffold **plus** every file under `templates/`.",
        ),
        encoding="utf-8",
    )
    (out / "AGENTS.md").write_text(_SKELETON_AGENTS.format(name=args.name), encoding="utf-8")

    console.print(f"[green]Saved profile[/] {out} — {len(captured)} file(s) from the delta.")
    if seed_list:
        console.print(f"  [dim]seed (write-once):[/] {', '.join(seed_list)}")
    for rel, token, n in subs:
        console.print(f"  [cyan]param[/] {rel}: {n} -> {token}")
    for step in onboarding_steps:
        console.print(f"  [magenta]onboarding[/] {step}")
    if added_elsewhere:
        console.print(
            f"  [yellow]not captured[/] ({len(added_elsewhere)} added file(s) outside setup dirs — "
            "review and copy any house content into templates/ by hand): "
            + ", ".join(added_elsewhere[:8])
            + (" …" if len(added_elsewhere) > 8 else "")
        )
    if excluded:
        console.print(f"  [dim]skipped (regenerated per project):[/] {', '.join(excluded)}")
    tier, _ = classify_safety(load(out))  # the real classifier on the written draft
    console.print(f"  [yellow]safety:[/] {tier}. Review, then run [bold]profile validate {out}[/].")
    return 0


def _list(args: argparse.Namespace, console: Any) -> int:
    if getattr(args, "community", False):
        import time

        entries = _fetch_index(time.time())
        if not entries:
            console.print("[yellow]Couldn't reach the community index[/] (offline, or it's empty).")
            return 0
        console.print("[cyan]Community profiles[/] (from the index):")
        _print_index_entries(entries, console)
        return 0
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
    from rich.markup import escape  # an installed-from-URL profile's fields are remote data

    console.print(f"[cyan]Profiles in[/] {USER_PROFILE_DIR}:")
    for d in found:
        try:
            p = load(d, source=d.name)
            tier = classify_safety(p)[0]
            desc = escape(p.description) or "(no description)"
            console.print(f"  [bold]{escape(p.name)}[/] {escape(p.version)} · {tier} — {desc}")
        except ProfileError as exc:
            console.print(f"  [red]{escape(d.name)}[/] — invalid: {exc}")
    return 0


def _show(args: argparse.Namespace, console: Any) -> int:
    """Inspect a profile — a path, a ``~/.config`` name, an index name, or a ``git+…`` URL —
    **without applying it**: its files, prompts, startup, and derived safety tier. Read-only
    (fetches a URL into the cache but runs no code and asks for no consent), so you can see exactly
    what a community profile *would* do before you `add` it. Fields are escaped — a fetched
    profile's are untrusted data."""
    from rich.markup import escape

    try:
        prof = _resolve_ref(args.ref, console)
    except ProfileError as exc:
        console.print(f"[red]{exc}[/]")
        return 2
    if prof is None:
        console.print("[cyan]default[/] — the built-in setup (no profile overlay).")
        return 0
    tier, reasons = classify_safety(prof)
    kind = "standalone" if prof.standalone else "extends default"
    desc = escape(prof.description) or "(no description)"
    console.print(f"[cyan]{escape(prof.name)}[/] {escape(prof.version)} — {desc}")
    console.print(f"  {kind}  ·  safety: [bold]{tier}[/]")
    if prof.tags:
        console.print(f"  tags: {escape(', '.join(prof.tags))}")
    for r in reasons:
        console.print(f"    [yellow]•[/] {escape(r)}")
    files = [rel for rel, _ in prof.template_files()]
    console.print(f"  files ({len(files)}): {escape(', '.join(files)) or '(none)'}")
    if prof.prompts:
        console.print(f"  prompts: {escape(', '.join(p.name for p in prof.prompts))}")
    if prof.onboarding:
        console.print(f"  onboarding: {len(prof.onboarding)} step(s)")
    if prof.session_start:
        console.print("  session_start (runs every session):")
        for cmd in prof.session_start:
            console.print(f"    [yellow]$[/] {escape(cmd)}")
    return 0


def _add(args: argparse.Namespace, console: Any) -> int:
    """Fetch (or resolve) a profile, gate its code once, and install it into the user profiles dir
    as a trusted local profile — the npm-install model (RFC 2026-07-04 §5). Copies **only**
    `profile.json` + `templates/` (the classified/hashed surface); skips symlinks."""
    import sys

    try:
        prof = _resolve_ref(args.url, console)
    except ProfileError as exc:
        console.print(f"[red]{exc}[/]")
        return 2
    if prof is None:
        console.print("[red]'default' is built in — nothing to add.[/]")
        return 2
    if not consent(
        prof, allow_code=args.allow_code, interactive=sys.stdin.isatty(), console=console
    ):
        return 1
    dest = USER_PROFILE_DIR / (args.name or prof.name)
    if dest.exists():
        console.print(f"[red]{dest} already exists[/] — choose another name, or remove it first.")
        return 2
    src_templates = prof.root / TEMPLATES_DIR
    (dest / TEMPLATES_DIR).mkdir(parents=True)
    shutil.copy2(prof.root / PROFILE_MANIFEST, dest / PROFILE_MANIFEST)
    for pth in src_templates.rglob("*"):
        if pth.is_symlink() or not pth.is_file():
            continue  # only regular files under templates/ — no symlinks, no rest-of-checkout
        out = dest / TEMPLATES_DIR / pth.relative_to(src_templates)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pth, out)
    console.print(
        f"[green]Added[/] {dest.name} → {dest}. Use it with [bold]--profile {dest.name}[/]."
    )
    return 0


def _untrust(args: argparse.Namespace, console: Any) -> int:
    store = _load_trust()
    matches = [h for h, n in store.items() if args.ref in (h, n) or h.startswith(args.ref)]
    if not matches:
        console.print(f"[yellow]No trusted profile matching {args.ref!r}.[/]")
        return 1
    for h in matches:
        del store[h]
    _save_trust(store)
    console.print(f"[green]Revoked[/] {len(matches)} trusted entry(ies).")
    return 0


def _trust_list(console: Any) -> int:
    store = _load_trust()
    if not store:
        console.print("[yellow]No trusted (consented) fetched profiles.[/]")
        return 0
    console.print("[cyan]Trusted fetched profiles (content hash):[/]")
    for h, n in sorted(store.items(), key=lambda kv: (kv[1], kv[0])):
        console.print(f"  [bold]{n}[/] {h[:12]}")
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
    lst = sub.add_parser("list", help="list profiles (yours, or --community from the index)")
    lst.add_argument("--community", action="store_true", help="list the community index instead")
    val = sub.add_parser("validate", help="check a profile loads and its templates render")
    val.add_argument("path", help="path to the profile directory")
    show = sub.add_parser("show", help="inspect a profile (files/prompts/safety) without applying")
    show.add_argument("ref", help="a path, a ~/.config name, an index name, or a git+https://… URL")
    save = sub.add_parser("save", help="extract a profile from a scaffolded project's delta")
    save.add_argument("project", help="path to a project agent-native-setup scaffolded")
    save.add_argument("name", help="profile name (also the directory name)")
    save.add_argument("-o", "--output", default=".", help="parent directory (default: cwd)")
    add = sub.add_parser("add", help="fetch/install a profile (git+URL or path) into the user dir")
    add.add_argument(
        "url", help="a git+https://… / git+ssh://… URL, a path, or a name (local or in the index)"
    )
    add.add_argument("name", nargs="?", help="install name (default: the profile's own name)")
    add.add_argument(
        "--allow-code", action="store_true", help="consent to a fetched code-carrying profile"
    )
    search = sub.add_parser("search", help="find community profiles in the index")
    search.add_argument("query", help="match against name / description / tags")
    pub = sub.add_parser("publish", help="validate + print a profile's shareable URL and entry")
    pub.add_argument("path", help="path to the profile directory")
    pub.add_argument("--url", help="the git+https://… URL it's published at (else inferred)")
    untrust = sub.add_parser("untrust", help="revoke consent for a fetched profile")
    untrust.add_argument("ref", help="a trusted content hash (or prefix) or profile name")
    trust = sub.add_parser("trust", help="manage consent for fetched profiles")
    trust.add_argument("--list", action="store_true", help="list trusted (consented) profiles")
    args = p.parse_args(argv)
    if args.cmd == "init":
        return _init(args, console)
    if args.cmd == "validate":
        return _validate(args, console)
    if args.cmd == "show":
        return _show(args, console)
    if args.cmd == "save":
        return _save(args, console)
    if args.cmd == "add":
        return _add(args, console)
    if args.cmd == "search":
        return _search(args, console)
    if args.cmd == "publish":
        return _publish(args, console)
    if args.cmd == "untrust":
        return _untrust(args, console)
    if args.cmd == "trust":
        return _trust_list(console)
    return _list(args, console)
