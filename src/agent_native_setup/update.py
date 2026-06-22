"""The `update` engine: refresh a scaffolded project to the running version.

The hard policy — *what may be overwritten* — lives here, on top of the provenance the
manifest records (per-file fingerprints + the seed set). The model is **classify, don't
merge** (RFC 2026-06-20):

- compare each file's on-disk fingerprint to what the manifest recorded at scaffold time;
- **refresh** only files that are still pristine *and* managed;
- **never touch** seed files (user-owned once written) — not even to refresh;
- **report** anything the user edited as a conflict for them (or their agent) to reconcile;
- **remove** managed files we no longer generate, but only while pristine.

This module is the deterministic core: `classify` is pure given the filesystem, `apply`
copies the decided changes from an already-regenerated tree, and `render_report` describes
them. Orchestration (git preconditions, regeneration, migrations) lives in the CLI.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_native_setup import manifest, migrations
from agent_native_setup.config import AI_TOOLS, WizardConfig
from agent_native_setup.scaffold import Scaffolder


def fingerprint(path: Path) -> str | None:
    """The manifest-format fingerprint of a path: ``symlink:<target>`` for a link,
    ``sha256:<hex>`` for a file, ``None`` if it doesn't exist. Mirrors ``Scaffolder``."""
    if path.is_symlink():  # check before is_file (which follows the link)
        return "symlink:" + os.readlink(path)
    if path.is_file():
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    return None


@dataclass
class Conflict:
    """A file `update` refuses to touch, with why — surfaced for the user to reconcile."""

    rel: str
    reason: str


@dataclass
class Plan:
    """What an update would do. ``creates``/``refreshes``/``removes`` are auto-applied;
    ``conflicts`` are left as-is and reported."""

    creates: list[str] = field(default_factory=list)
    refreshes: list[str] = field(default_factory=list)
    removes: list[str] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)

    @property
    def is_noop(self) -> bool:
        return not (self.creates or self.refreshes or self.removes or self.conflicts)

    @property
    def touched(self) -> int:
        return len(self.creates) + len(self.refreshes) + len(self.removes)


def classify(
    old_manifest: dict, new_recorded: dict[str, str], new_seed: set[str], target: Path
) -> Plan:
    """Decide, per file, what the update does — comparing the freshly regenerated set
    (``new_recorded`` fingerprints + ``new_seed``) against what's on disk and what the old
    manifest recorded.

    Refresh requires the on-disk file to still match the *old* manifest (pristine since the
    last scaffold); anything else managed-and-changed is a conflict we won't clobber.
    """
    old_files: dict[str, str] = old_manifest.get("files", {})
    old_seed: set[str] = set(old_manifest.get("seed", []))
    plan = Plan()

    for rel, new_fp in sorted(new_recorded.items()):
        if rel in new_seed:
            # Seed: user-owned once written — the updater never creates, refreshes, or
            # removes it. (We deliberately don't even create a "new" seed file: a
            # date-stamped path like the bootstrap RFC differs every run, so creating it
            # would duplicate the one already on disk under a fresh date.)
            continue
        disk = fingerprint(target / rel)
        if disk is None:
            plan.creates.append(rel)
        elif disk == new_fp:
            continue  # already current
        elif rel in old_files and disk == old_files[rel]:
            plan.refreshes.append(rel)  # pristine since scaffold → safe to update
        elif rel in old_files:
            plan.conflicts.append(Conflict(rel, "edited since scaffold"))
        else:
            plan.conflicts.append(Conflict(rel, "already present, not from this scaffold"))

    for rel, old_fp in sorted(old_files.items()):
        if rel in new_recorded:
            continue  # still generated — handled above
        disk = fingerprint(target / rel)
        if disk is None or rel in old_seed:
            continue  # already gone, or user-owned: leave it
        if disk == old_fp:
            plan.removes.append(rel)  # pristine orphan → safe to remove
        else:
            plan.conflicts.append(Conflict(rel, "no longer generated; edited since scaffold"))

    return plan


def apply(plan: Plan, new_recorded: dict[str, str], source: Path, target: Path) -> None:
    """Carry out ``plan``: copy created/refreshed files from the regenerated ``source`` tree
    into ``target``, recreate symlinks from their recorded target, and delete removals.
    Conflicts are deliberately left untouched."""
    for rel in plan.creates + plan.refreshes:
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        fp = new_recorded[rel]
        if dest.is_symlink():  # never write or unlink *through* an existing link
            dest.unlink()
        if fp.startswith("symlink:"):
            if dest.exists():
                dest.unlink()
            dest.symlink_to(fp.split(":", 1)[1])
        else:
            dest.write_bytes((source / rel).read_bytes())
    for rel in plan.removes:
        path = target / rel
        if path.is_symlink() or path.exists():
            path.unlink()
        _prune_empty_parents(path.parent, target)


def _prune_empty_parents(start: Path, stop: Path) -> None:
    """Remove now-empty directories from ``start`` up to (not including) ``stop``."""
    parent = start
    while parent != stop and parent.is_dir():
        try:
            parent.rmdir()  # only succeeds while empty
        except OSError:
            break
        parent = parent.parent


def render_report(plan: Plan, from_version: str, to_version: str) -> str:
    """The ``UPDATING.md`` runbook: what was applied, and the conflicts left to reconcile."""
    lines = [
        "# Updating this project's agent-native setup",
        "",
        f"`agent-native-setup` refreshed the generated setup from **{from_version}** to "
        f"**{to_version}**.",
        "",
    ]
    if plan.conflicts:
        lines += [
            "## Reconcile these",
            "",
            "These files changed in the new version, but you've edited them — so they were "
            "**left as-is**. Compare each against the new version and fold in what you want "
            "(your coding agent can do this for you):",
            "",
        ]
        lines += [f"- `{c.rel}` — {c.reason}" for c in plan.conflicts]
        lines.append("")
    else:
        lines += ["No conflicts — nothing of yours needed reconciling.", ""]

    applied = [
        ("Added", plan.creates),
        ("Refreshed", plan.refreshes),
        ("Removed", plan.removes),
    ]
    lines += ["## Applied automatically", ""]
    if plan.touched:
        for label, rels in applied:
            for rel in rels:
                lines.append(f"- {label}: `{rel}`")
    else:
        lines.append("- Nothing — every managed file was already current.")
    lines += [
        "",
        "Review the diff (`git diff`) before committing. When you've reconciled the "
        "conflicts above, delete this file.",
        "",
    ]
    return "\n".join(lines)


# --- orchestration (preconditions, regeneration, manifest rewrite) ----------------------

REPORT_PATH = "UPDATING.md"


def _load_manifest(target: Path) -> dict | None:
    try:
        return json.loads((target / manifest.MANIFEST_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _git_state(target: Path) -> tuple[bool, bool]:
    """``(target_is_repo_root, is_clean_worktree)``. Returns ``(False, False)`` unless the
    target is *itself* a git worktree root — a scaffolded subdir of some parent repo is
    refused, so the diff-review surface and `git checkout` undo cover exactly this project
    and nothing else."""
    try:
        top = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
        )
    except OSError:
        return False, False
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != target.resolve():
        return False, False
    status = subprocess.run(
        ["git", "-C", str(target), "status", "--porcelain"], capture_output=True, text=True
    )
    return True, status.returncode == 0 and not status.stdout.strip()


def _config_from_manifest(old: dict, output_dir: Path) -> WizardConfig:
    """Rebuild the WizardConfig the project was scaffolded with, tolerating older manifests
    that predate some keys (they fall back to the dataclass defaults)."""
    cfg: dict[str, Any] = old.get("config", {})

    def get(key: str, default: Any) -> Any:
        return cfg.get(key, default)

    return WizardConfig(
        project_name=get("project_name", output_dir.name),
        description=get("description", ""),
        output_dir=output_dir,
        languages=list(get("languages", [])),
        ai_tools=list(get("ai_tools", list(AI_TOOLS))),
        include_agents=get("include_agents", True),
        include_docs=get("include_docs", True),
        include_quality=get("include_quality", True),
        include_ci=get("include_ci", True),
        include_security=get("include_security", True),
        use_github_actions=get("use_github_actions", True),
        git_hooks=get("git_hooks", True),
        first_run_banner=get("first_run_banner", False),
        runner=get("runner", "make"),
        adoption=get("adoption", "progressive"),
        existing_project=get("existing_project", False),
        existing_runner=get("existing_runner", False),
        init_git=False,  # never touch git in the throwaway regeneration tree
    )


def _regenerate(config: WizardConfig, into: Path) -> Scaffolder:
    """Render the current version's full scaffold into ``into`` and return the Scaffolder
    (its ``recorded`` fingerprints + ``seed`` set describe the new generation)."""
    from agent_native_setup import cli  # lazy: cli imports this module

    sc = Scaffolder(into)
    cli.build(config, sc)
    return sc


def run(target: Path, *, dry_run: bool, console: Any) -> int:
    """Refresh ``target`` to this version. Returns a process exit code."""
    old = _load_manifest(target)
    if old is None:
        console.print(
            "[red]No .agent-native-setup.json found[/] — this project predates provenance "
            "tracking (or wasn't scaffolded by agent-native-setup). Re-run the scaffolder "
            "(non-destructive) to record a manifest, then `update` will work."
        )
        return 2

    if not dry_run:
        is_repo, clean = _git_state(target)
        if not is_repo:
            console.print(
                "[red]update needs a git repo[/] so changes stay reviewable and reversible. "
                "Run `git init` and commit first, or preview with [bold]--dry-run[/]."
            )
            return 2
        if not clean:
            console.print(
                "[red]Working tree isn't clean[/] — commit or stash first so the update's "
                "diff is unambiguously its own. (Or preview with [bold]--dry-run[/].)"
            )
            return 2

    # Structural moves of user content run first (so regeneration lands on the new layout);
    # a dry run previews them without mutating anything.
    moves = migrations.apply_all(target, apply=not dry_run)
    for action in moves:
        console.print(f"  [magenta]~[/] {'would move' if dry_run else 'moved'} {action}")

    from_version = str(old.get("version") or "0.0.0")
    with tempfile.TemporaryDirectory() as tmp:
        sc = _regenerate(_config_from_manifest(old, Path(tmp)), Path(tmp))
        # build() writes the manifest *last* via sc.write, which adds it to `recorded`.
        # The updater owns the manifest itself (rewritten below), so drop it from the set
        # it classifies and re-records — exactly as a fresh scaffold excludes it.
        sc.recorded.pop(manifest.MANIFEST_PATH, None)
        sc.seed.discard(manifest.MANIFEST_PATH)
        plan = classify(old, sc.recorded, sc.seed, target)
        if dry_run:
            _print_plan(console, plan, dry_run=True)
            return 0
        apply(plan, sc.recorded, Path(tmp), target)
        to_version = str(manifest.__version__)
        (target / REPORT_PATH).write_text(
            render_report(plan, from_version, to_version), encoding="utf-8"
        )
        new_manifest = manifest.build(_config_from_manifest(old, target), sc)
        (target / manifest.MANIFEST_PATH).write_text(
            json.dumps(new_manifest, indent=2) + "\n", encoding="utf-8"
        )
    _print_plan(console, plan, dry_run=False)
    return 0


def _print_plan(console: Any, plan: Plan, *, dry_run: bool) -> None:
    verb = "Would" if dry_run else "Did"
    if plan.is_noop:
        console.print("[green]Already up to date[/] — nothing to change.")
        return
    for label, rels in (("create", plan.creates), ("refresh", plan.refreshes)):
        for rel in rels:
            console.print(f"  [green]+[/] {verb.lower()} {label}: {rel}")
    for rel in plan.removes:
        console.print(f"  [red]-[/] {verb.lower()} remove: {rel}")
    if plan.conflicts:
        console.print(
            f"\n[yellow]{len(plan.conflicts)} file(s) you've edited changed upstream[/] — "
            + ("see the plan above" if dry_run else f"left as-is; see [bold]{REPORT_PATH}[/]")
            + " to reconcile:"
        )
        for c in plan.conflicts:
            console.print(f"  [yellow]![/] {c.rel} — {c.reason}")
    if not dry_run:
        console.print("\n[dim]Review [/][bold]git diff[/][dim] before committing.[/]")


def run_cli(argv: list[str], console: Any) -> int:
    p = argparse.ArgumentParser(
        prog="agent-native-setup update",
        description="Refresh a scaffolded project to this version of the setup.",
    )
    p.add_argument("-o", "--output", default=".", help="project directory (default: cwd)")
    p.add_argument("--dry-run", action="store_true", help="show what would change, write nothing")
    args = p.parse_args(argv)
    return run(Path(args.output).expanduser().resolve(), dry_run=args.dry_run, console=console)
