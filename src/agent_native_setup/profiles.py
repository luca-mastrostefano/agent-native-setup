"""Scaffolding profiles (RFC 2026-06-23): compose a team's files on the default setup.

A profile is a directory with a ``profile.json`` and a ``templates/`` tree. ``extends: default``
means the wizard generates its normal output, then the profile's template files are overlaid on
top, superseding any base file at the same path. Each profile file is **managed** — refreshed by
``update`` when the profile ships a new ``version`` — unless listed in the profile's ``seed`` set
(written once, then the user's). Standalone (``extends: null``) is still Phase 2.

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
from agent_native_setup.scaffold import Scaffolder, render

PROFILE_MANIFEST = "profile.json"
TEMPLATES_DIR = "templates"
USER_PROFILE_DIR = Path.home() / ".config" / "agent-native-setup" / "profiles"
SUPPORTED_EXTENDS = ("default",)


class ProfileError(Exception):
    """A profile that can't be loaded or is invalid. The message is user-facing."""


@dataclass(frozen=True)
class Profile:
    name: str
    version: str
    extends: str
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
    extends = data.get("extends")  # absent/null = standalone (Phase 2), not coerced to default
    if not name or not version:
        raise ProfileError(f"{manifest_path}: both 'name' and 'version' are required")
    if extends not in SUPPORTED_EXTENDS:
        raise ProfileError(
            f"{manifest_path}: extends={extends!r} isn't supported yet — set extends to one of "
            f"{', '.join(SUPPORTED_EXTENDS)} (standalone / extends:null is Phase 2)"
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


def _context(config: WizardConfig) -> dict[str, Any]:
    """The variables a ``.j2`` profile template can reference."""
    return {
        "project_name": config.project_name,
        "slug": config.slug,
        "description": config.description,
        "languages": list(config.languages),
    }


def apply(profile: Profile, config: WizardConfig, sc: Scaffolder) -> list[str]:
    """Overlay ``profile``'s templates onto an already-generated scaffold. Files are **managed**
    (refreshed on update when the profile ships a new version) unless listed in the profile's
    ``seed`` set, which are written once. ``.j2`` files are rendered against the project context;
    others ship verbatim. A file at the same path as a base file supersedes it.

    Returns the sorted list of paths the profile actually owns (those it wrote — a path where a
    user's own file pre-existed is skipped and not claimed), so the project manifest records them
    and ``update`` re-applies the profile to refresh them."""
    ctx = _context(config)
    owned: list[str] = []
    for out_rel, src in profile.template_files():
        raw = src.read_text(encoding="utf-8")
        content = render(raw, **ctx) if src.name.endswith(".j2") else raw
        if sc.overlay(out_rel, content, seed=out_rel in profile.seed):
            owned.append(out_rel)
    return sorted(owned)


# --- authoring CLI: `agent-native-setup profile <init|list>` ----------------------------

_SKELETON_README = """\
# {name} — agent-native-setup profile

A profile composed on the built-in `default` setup (`extends: default`). When someone runs

```bash
agent-native-setup my-app -o ./my-app --profile {source_hint}
```

they get the normal scaffold **plus** every file under `templates/`.

## Layout

- `profile.json` — name, version (your own semver), `extends`, description, an optional
  `seed` list, and optional `onboarding` / `session_start` lists (below).
- `templates/` — the files this profile ships. Paths are relative to the project root, so
  `templates/.claude/agents/foo.md` lands at `.claude/agents/foo.md`. A file ending in
  `.j2` is rendered (Jinja) with `project_name`, `slug`, `description`, `languages` and the
  `.j2` stripped; anything else is copied verbatim (so files containing `{{{{ ... }}}}`,
  like GitHub Actions `${{{{ ... }}}}`, are safe).

## Startup instructions

- `onboarding` — a list of markdown steps folded into the project's `ONBOARDING.md`, which an
  agent runs **once** on first session (then it self-deletes). Use it for one-time setup
  ("run `task team-setup`", "request access to X").
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


def _init(args: argparse.Namespace, console: Any) -> int:
    root = Path(args.output).expanduser().resolve() / args.name
    if root.exists():
        console.print(f"[red]{root} already exists[/] — choose another name or location.")
        return 2
    (root / TEMPLATES_DIR).mkdir(parents=True)
    (root / TEMPLATES_DIR / ".gitkeep").write_text("", encoding="utf-8")
    manifest = {
        "name": args.name,
        "version": "0.1.0",
        "extends": "default",
        "description": "TODO: one line describing this profile",
        "seed": [],
        "onboarding": [],
        "session_start": [],
    }
    (root / PROFILE_MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (root / "README.md").write_text(
        _SKELETON_README.format(name=args.name, source_hint=f"./{args.name}"), encoding="utf-8"
    )
    console.print(f"[green]Created profile[/] {root}")
    console.print(
        f"  Add files under [bold]{args.name}/templates/[/], then scaffold with "
        f"[bold]--profile {root}[/]."
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
    sub.add_parser("list", help="list profiles in the user profiles dir")
    args = p.parse_args(argv)
    if args.cmd == "init":
        return _init(args, console)
    return _list(console)
