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
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_native_setup import manifest, migrations, versioning
from agent_native_setup.config import AI_TOOLS, WizardConfig
from agent_native_setup.migrations import Migration
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


def render_report(
    plan: Plan,
    from_version: str,
    to_version: str,
    agent_steps: Sequence[Migration] = (),
    *,
    version_changed: bool = True,
) -> str:
    """The ``UPDATING.md`` runbook: what was applied, the conflicts left to reconcile, and —
    for a breaking-boundary update — the ordered migration steps for the agent/user to do."""
    lines = [
        "# Updating this project's agent-native setup",
        "",
        f"`agent-native-setup` refreshed the generated setup from **{from_version}** to "
        f"**{to_version}**.",
        "",
    ]
    if agent_steps:
        lines += [
            "## Migration steps",
            "",
            "This update crosses a breaking version boundary. Do these **in order** — they "
            "transform files you own, which the tool won't touch automatically:",
            "",
        ]
        for m in agent_steps:
            lines += [f"### {m.version} — {m.describe}", "", m.instructions.strip(), ""]
    if plan.conflicts:
        intro = (
            "These files changed in the new version, but you've edited them — so they were "
            "**left as-is**. Compare each against the new version and fold in what you want "
            "(your coding agent can do this for you):"
            if version_changed
            else "These managed files have **drifted** from the scaffold (you edited them since) "
            "— so they were **left as-is**. Reconcile them against the generated baseline if you "
            "want them back in sync:"
        )
        lines += ["## Reconcile these", "", intro, ""]
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


def _restore_profile_overlay(old: dict, sc: Scaffolder, target: Path) -> None:
    """Re-assert the profile's overlaid files (RFC 2026-06-23, Phase 1) into the regenerated
    set *before* classify. Phase 1 doesn't re-run the profile on update, so without this the
    base regeneration would either drop a profile's new file from provenance or — worse —
    *refresh the base content back over a file the profile overrode* (classify would see the
    on-disk override as a pristine-since-scaffold managed file). Marking each profile-owned
    path seed with its recorded fingerprint makes classify's seed short-circuit preserve it.

    Scoped to exactly the paths the manifest records as profile-owned — never the broader
    `seed` set, so a renamed default seed file (e.g. the date-stamped bootstrap RFC) is left
    to classify, not wrongly carried."""
    profile = old.get("profile") or {}
    owned = profile.get("files", []) if isinstance(profile, dict) else []
    old_files: dict[str, str] = old.get("files", {})
    for rel in owned:
        if rel in old_files and (target / rel).exists():
            sc.recorded[rel] = old_files[rel]
            sc.seed.add(rel)


def run(target: Path, *, dry_run: bool, console: Any, assume_yes: bool = False) -> int:
    """Refresh ``target`` to this version. Returns a process exit code."""
    old = _load_manifest(target)
    if old is None:
        console.print(
            "[red]No .agent-native-setup.json found[/] — this project predates provenance "
            "tracking (or wasn't scaffolded by agent-native-setup). Re-run the scaffolder "
            "(non-destructive) to record a manifest, then `update` will work."
        )
        return 2

    from_version = str(old.get("version") or "0.0.0")
    to_version = str(manifest.__version__)
    decision = versioning.decide(from_version, to_version)
    if decision == versioning.DOWNGRADE:
        console.print(
            f"[red]Your installed tool ({to_version}) is older than this project's "
            f"scaffolding ({from_version})[/] — upgrade the tool, then run update."
        )
        return 2
    # agent/manual steps for the breaking boundaries crossed; their presence also gates,
    # so a mistagged step still gets a confirmation rather than auto-applying.
    agent_steps = migrations.steps_in_span(from_version, to_version)
    gated = decision == versioning.GATED or bool(agent_steps)
    # No version change → any conflicts are *local drift* (the user edited a managed file),
    # not upstream changes. This is the conformance-check case (RFC 2026-06-24): `update
    # --dry-run` on an up-to-date project, reframed so the report doesn't cry "changed upstream".
    version_changed = decision != versioning.NOOP

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
        if (
            gated
            and (
                gate_rc := _confirm_gate(
                    console, from_version, to_version, agent_steps, assume_yes=assume_yes
                )
            )
            is not None
        ):
            return gate_rc

    # Structural moves of user content run first (so regeneration lands on the new layout);
    # a dry run previews them without mutating anything.
    moves = migrations.apply_all(target, apply=not dry_run)
    for action in moves:
        console.print(f"  [magenta]~[/] {'would move' if dry_run else 'moved'} {action}")

    with tempfile.TemporaryDirectory() as tmp:
        sc = _regenerate(_config_from_manifest(old, Path(tmp)), Path(tmp))
        # build() writes the manifest *last* via sc.write, which adds it to `recorded`.
        # The updater owns the manifest itself (rewritten below), so drop it from the set
        # it classifies and re-records — exactly as a fresh scaffold excludes it.
        sc.recorded.pop(manifest.MANIFEST_PATH, None)
        sc.seed.discard(manifest.MANIFEST_PATH)
        # Re-assert profile overlays as seed before classifying, so the base never refreshes
        # over them and their provenance survives (Phase 1 doesn't re-run the profile).
        _restore_profile_overlay(old, sc, target)
        plan = classify(old, sc.recorded, sc.seed, target)
        if dry_run:
            _print_plan(
                console,
                plan,
                dry_run=True,
                agent_steps=agent_steps,
                version_changed=version_changed,
            )
            return 0
        apply(plan, sc.recorded, Path(tmp), target)
        # UPDATING.md is the *actionable* runbook — written only when there's something for
        # the user to do (conflicts to reconcile, or migration steps). A clean autopilot
        # refresh leaves no runbook to delete; the `git diff` is the record.
        if plan.conflicts or agent_steps:
            (target / REPORT_PATH).write_text(
                render_report(
                    plan, from_version, to_version, agent_steps, version_changed=version_changed
                ),
                encoding="utf-8",
            )
        # Written last, so an interrupt before here leaves `installed` unchanged (re-runnable).
        new_manifest = manifest.build(
            _config_from_manifest(old, target), sc, profile=old.get("profile")
        )
        (target / manifest.MANIFEST_PATH).write_text(
            json.dumps(new_manifest, indent=2) + "\n", encoding="utf-8"
        )
    _print_plan(
        console, plan, dry_run=False, agent_steps=agent_steps, version_changed=version_changed
    )
    return 0


def _confirm_gate(
    console: Any, from_v: str, to_v: str, agent_steps: list[Migration], *, assume_yes: bool
) -> int | None:
    """Confirm a breaking-boundary update. Returns ``None`` to proceed, or an exit code to
    stop with (0 = user declined, 2 = needs --yes in a non-interactive run)."""
    detail = f" with {len(agent_steps)} migration step(s) to apply" if agent_steps else ""
    if assume_yes:
        return None
    if not sys.stdin.isatty():
        console.print(
            f"[red]Breaking update {from_v} → {to_v}{detail}[/] needs confirmation. Preview "
            "with [bold]--dry-run[/], then re-run with [bold]--yes[/] to proceed."
        )
        return 2
    import questionary

    if questionary.confirm(
        f"Breaking update ({from_v} → {to_v}){detail} — proceed?", default=False
    ).ask():
        return None
    console.print("[yellow]Aborted[/] — no changes made.")
    return 0


def _print_plan(
    console: Any,
    plan: Plan,
    *,
    dry_run: bool,
    agent_steps: Sequence[Migration] = (),
    version_changed: bool = True,
) -> None:
    verb = "Would" if dry_run else "Did"
    if plan.is_noop and not agent_steps:
        msg = "nothing to change" if version_changed else "no drift from the scaffold"
        console.print(f"[green]Already up to date[/] — {msg}.")
        return
    for label, rels in (("create", plan.creates), ("refresh", plan.refreshes)):
        for rel in rels:
            console.print(f"  [green]+[/] {verb.lower()} {label}: {rel}")
    for rel in plan.removes:
        console.print(f"  [red]-[/] {verb.lower()} remove: {rel}")
    if plan.conflicts:
        # No version change → these are the user's own drift, not upstream changes.
        if version_changed:
            head = f"{len(plan.conflicts)} file(s) you've edited changed upstream"
            tail = (
                "see the plan above" if dry_run else f"left as-is; see [bold]{REPORT_PATH}[/]"
            ) + (" to reconcile:")
        else:
            head = f"{len(plan.conflicts)} managed file(s) have drifted from the scaffold"
            tail = "edited since — [bold]git diff[/] shows your changes:"
        console.print(f"\n[yellow]{head}[/] — {tail}")
        for c in plan.conflicts:
            console.print(f"  [yellow]![/] {c.rel} — {c.reason}")
    if agent_steps:
        console.print(
            f"\n[magenta]{len(agent_steps)} migration step(s)[/] cross a version boundary — "
            + ("previewed below" if dry_run else f"do them via [bold]{REPORT_PATH}[/]")
            + ":"
        )
        for m in agent_steps:
            console.print(f"  [magenta]→[/] {m.version}: {m.describe}")
    if not dry_run:
        console.print("\n[dim]Review [/][bold]git diff[/][dim] before committing.[/]")


def check(target: Path, console: Any) -> int:
    """Print a one-line staleness nudge (or nothing), comparing the project's scaffolding
    version to the latest release. Read-only and **silent on any error** — it runs from a
    SessionStart hook, so it must never fail a session. It reads the daily-cached latest
    release, refreshing it with one bounded (<=1.5s) network call when the cache is stale;
    that refresh is shared with the end-of-run nudge, so in steady state it's a cache hit."""
    try:
        old = _load_manifest(target)
        if old is None:
            return 0  # not a scaffolded project (or pre-manifest) — nothing to say
        installed = str(old.get("version") or "0.0.0")
        if versioning.parse(installed) == versioning.parse("0.0.0"):
            return 0  # no usable scaffolding version (raw-checkout dev) — don't cry wolf
        from agent_native_setup import update_check

        latest = update_check._latest_with_cache(time.time())
        if not latest:
            return 0  # offline / no release info
        latest_v = latest.lstrip("v")
        decision = versioning.decide(installed, latest_v)
        head = (
            f"[dim]agent-native-setup:[/] scaffolding [bold]{installed}[/] · "
            f"latest [bold]{latest_v}[/] — "
        )
        if decision == versioning.AUTOPILOT:
            console.print(f"{head}compatible update, run [bold]/update-agent-scaffolding[/].")
        elif decision == versioning.GATED:
            console.print(
                f"{head}[yellow]major (breaking) update[/]; review before applying "
                "([bold]/update-agent-scaffolding[/])."
            )
        # NOOP (current) / DOWNGRADE (ahead of latest) → say nothing
    except Exception:  # advisory only — never disrupt a session
        pass
    return 0


def run_cli(argv: list[str], console: Any) -> int:
    p = argparse.ArgumentParser(
        prog="agent-native-setup update",
        description="Refresh a scaffolded project to this version of the setup.",
    )
    p.add_argument("-o", "--output", default=".", help="project directory (default: cwd)")
    p.add_argument("--dry-run", action="store_true", help="show what would change, write nothing")
    p.add_argument(
        "-y", "--yes", action="store_true", help="confirm a breaking (major-boundary) update"
    )
    p.add_argument("--check", action="store_true", help="print a one-line staleness nudge and exit")
    args = p.parse_args(argv)
    target = Path(args.output).expanduser().resolve()
    if args.check:
        return check(target, console)
    return run(target, dry_run=args.dry_run, console=console, assume_yes=args.yes)
