"""Command-line entry point: flags, interactive prompts, orchestration."""

from __future__ import annotations

import argparse
import dataclasses
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from agent_native_setup import __version__, manifest, profiles, update, update_check
from agent_native_setup.config import AI_TOOLS, WizardConfig
from agent_native_setup.generators import agents, ai_context, ci, docs, onboarding, quality
from agent_native_setup.languages import REGISTRY, detect_languages, detect_runner
from agent_native_setup.scaffold import Scaffolder

console = Console()
LANG_KEYS = list(REGISTRY)
_MULTISELECT_HINT = "(↑/↓ move · space to select · enter to confirm)"


def _csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="agent-native-setup", description="Scaffold an agent-native project setup."
    )
    p.add_argument("name", nargs="?", help="project name")
    p.add_argument("-o", "--output", default=".", help="target directory (default: cwd)")
    p.add_argument("--description", default="")
    p.add_argument(
        "--profile",
        default=None,
        help="compose a profile on the default setup: a path to a profile dir, or a name in "
        "~/.config/agent-native-setup/profiles (see `agent-native-setup profile --help`)",
    )
    p.add_argument("--languages", type=_csv, default=None, help=f"comma-sep: {','.join(LANG_KEYS)}")
    p.add_argument("--tools", type=_csv, default=None, help=f"comma-sep: {','.join(AI_TOOLS)}")
    p.add_argument("--no-agents", dest="agents", action="store_false")
    p.add_argument("--no-docs", dest="docs", action="store_false")
    p.add_argument("--no-quality", dest="quality", action="store_false")
    p.add_argument("--no-ci", dest="ci", action="store_false")
    p.add_argument("--no-security", dest="security", action="store_false")
    p.add_argument(
        "--runner",
        choices=["make", "task"],
        default="make",
        help="runner for a fresh repo (default: make; an existing one is auto-detected)",
    )
    p.add_argument(
        "--adopt",
        choices=["progressive", "full", "none"],
        default="progressive",
        help="how the gate applies to an EXISTING repo's code (default: progressive)",
    )
    p.add_argument("--no-github-actions", dest="github_actions", action="store_false")
    p.add_argument("--no-hooks", dest="hooks", action="store_false")
    p.add_argument("--no-first-run-banner", dest="first_run_banner", action="store_false")
    p.add_argument("--no-git", dest="git", action="store_false")
    p.add_argument("-y", "--yes", action="store_true", help="non-interactive; use flags/defaults")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="show what would be created, write nothing (parity with `update --dry-run`)",
    )
    p.add_argument("--force", action="store_true", help="overwrite existing files")
    p.add_argument(
        "--no-update-check",
        dest="update_check",
        action="store_false",
        help="don't check GitHub for a newer release at the end of a run",
    )
    p.set_defaults(
        agents=True,
        docs=True,
        quality=True,
        ci=True,
        security=True,
        github_actions=True,
        hooks=True,
        first_run_banner=True,
        git=True,
        update_check=True,
    )
    return p.parse_args(argv)


def _interactive(
    args: argparse.Namespace,
    out: Path,
    detected: list[str] | None,
    prompt_runner: bool,
    in_target: set[str],
) -> WizardConfig:
    import questionary

    name = (
        args.name
        or questionary.text(
            "Project name (titles AGENTS.md/README; used as the package name):",
            default=out.name,
        ).unsafe_ask()
    )
    description = (
        args.description
        or questionary.text(
            "One-line description (shown in the README and AGENTS.md header):"
        ).unsafe_ask()
    )
    languages = (
        args.languages
        if args.languages is not None
        else questionary.checkbox(
            "Languages (linters scaffolded only for these):",
            instruction=_MULTISELECT_HINT,
            choices=[
                questionary.Choice(REGISTRY[k].label, value=k, checked=k in (detected or []))
                for k in LANG_KEYS
            ],
        ).unsafe_ask()
    )
    if args.languages is None:  # echo the result — questionary's "done" hides what was picked
        if languages:
            console.print(f"[cyan]Languages:[/] {', '.join(languages)}")
        else:
            console.print(
                ":warning:  [bold yellow]No language selected[/] — linters/tests won't "
                "be scaffolded."
            )
    tools = (
        args.tools
        if args.tools is not None
        else questionary.checkbox(
            "AI assistants to target (each gets a config pointing at AGENTS.md):",
            instruction=_MULTISELECT_HINT,
            choices=[questionary.Choice(t, value=t, checked=True) for t in AI_TOOLS],
        ).unsafe_ask()
    )
    if args.tools is None:
        console.print(f"[cyan]AI assistants:[/] {', '.join(tools) if tools else 'none'}")
    parts = questionary.checkbox(
        "Scaffold which parts?",
        instruction=_MULTISELECT_HINT,
        choices=[
            questionary.Choice("Agents & commands", value="agents", checked=args.agents),
            questionary.Choice("Docs & RFCs", value="docs", checked=args.docs),
            questionary.Choice("Linters & quality", value="quality", checked=args.quality),
            questionary.Choice("CI (GitHub Actions)", value="ci", checked=args.ci),
        ],
    ).unsafe_ask()
    console.print(
        f"[cyan]Scaffolding:[/] {', '.join(parts) if parts else 'nothing beyond the contract'}"
    )
    use_ga = (
        "ci" in parts
        and questionary.confirm(
            "Add GitHub Actions workflows? (CI quality + security gate on push/PR)",
            default=True,
        ).unsafe_ask()
    )
    hooks = (
        "quality" in parts
        and questionary.confirm(
            "Install pre-commit hooks? (run linters/format/secret-scan before each commit)",
            default=True,
        ).unsafe_ask()
    )
    security = ("quality" in parts or "ci" in parts) and questionary.confirm(
        "Add security scanning (secrets + dependency audit)?", default=True
    ).unsafe_ask()
    runner = args.runner
    if prompt_runner and "quality" in parts:
        runner = questionary.select(
            "Task runner for the command surface (none detected):",
            choices=[
                questionary.Choice("Make  [no extra dependencies]", value="make"),
                questionary.Choice(
                    "Task  [not detected - needs install: taskfile.dev]", value="task"
                ),
            ],
        ).unsafe_ask()
    adoption = args.adopt
    if bool(set(languages or []) & in_target) and ("quality" in parts or "ci" in parts):
        adoption = questionary.select(
            "Existing code detected — how should the quality gate apply to it?",
            choices=[
                questionary.Choice(
                    "Progressively — only files changed in a PR (recommended, mature repo)",
                    value="progressive",
                ),
                questionary.Choice(
                    "Fully — enforce on the whole repo now (good for a small/new repo)",
                    value="full",
                ),
                questionary.Choice(
                    "None — scaffold the config but don't enforce on existing code yet",
                    value="none",
                ),
            ],
        ).unsafe_ask()
    first_run_banner = False
    if ("quality" in parts or "ci" in parts) and tools:
        first_run_banner = questionary.confirm(
            "Add a first-run banner to AGENTS.md so the agent self-onboards? "
            "(auto-removed once onboarding is done)",
            default=True,
        ).unsafe_ask()
    if (out / ".git").exists():
        console.print("[cyan]Already a git repository[/] — skipping git init.")
        init_git = False
    else:
        init_git = questionary.confirm(
            "Run `git init`? (initialize a git repository here)", default=True
        ).unsafe_ask()

    return WizardConfig(
        project_name=name,
        description=description,
        output_dir=out,
        languages=languages or [],
        ai_tools=tools or [],
        include_agents="agents" in parts,
        include_docs="docs" in parts,
        include_quality="quality" in parts,
        include_ci="ci" in parts,
        include_security=bool(security),
        runner=runner or "make",
        adoption=adoption or "progressive",
        use_github_actions=bool(use_ga),
        git_hooks=bool(hooks),
        first_run_banner=bool(first_run_banner),
        init_git=bool(init_git),
    )


def _from_flags(args: argparse.Namespace, out: Path, detected: list[str] | None) -> WizardConfig:
    return WizardConfig(
        project_name=args.name or out.name,
        description=args.description,
        output_dir=out,
        languages=args.languages if args.languages is not None else (detected or []),
        ai_tools=args.tools if args.tools is not None else list(AI_TOOLS),
        include_agents=args.agents,
        include_docs=args.docs,
        include_quality=args.quality,
        include_ci=args.ci,
        include_security=args.security,
        runner=args.runner,
        adoption=args.adopt,
        use_github_actions=args.github_actions,
        git_hooks=args.hooks,
        first_run_banner=args.first_run_banner,
        init_git=args.git,
    )


def build(
    config: WizardConfig,
    sc: Scaffolder,
    profile: profiles.Profile | None = None,
    *,
    session_start: tuple[str, ...] | None = None,
    answers: dict[str, object] | None = None,
) -> dict[str, object] | None:
    """Scaffold ``config`` (plus ``profile``'s overlay) into ``sc``'s target and write the
    manifest. Returns the recorded ``profile`` block (or ``None``) — its `files`/`answers`
    reflect what was *actually* applied, which `update` persists instead of re-guessing."""
    config.target.mkdir(parents=True, exist_ok=True)
    # Profile-contributed startup: SessionStart hook commands (every session) and one-time
    # onboarding steps, injected into the base generators so they merge in (not clobber). The
    # `session_start` override lets a degraded update keep the recorded hooks when the profile
    # object is gone.
    hooks = (
        session_start if session_start is not None else (profile.session_start if profile else ())
    )
    onboarding_steps = profile.onboarding if profile else ()
    ai_context.generate(config, sc)
    if config.include_agents:
        agents.generate(config, sc, session_start=hooks)
    if config.include_docs:
        docs.generate(config, sc)
    if config.include_quality:
        quality.generate(config, sc)
    if config.include_ci:
        ci.generate(config, sc)
    onboarding.generate(config, sc, profile_steps=onboarding_steps)
    # A profile composes on top: its files overlay the default output (managed by default,
    # seed when listed), before git/manifest so they're committed and recorded as provenance.
    # The recorded block carries the exact paths the profile owns + the answers it rendered
    # against, so `update` re-applies them deterministically without re-prompting.
    profile_block = None
    if profile is not None:
        resolved = answers if answers is not None else profiles.default_answers(profile)
        profile_block = {
            **profile.manifest_block(),
            "files": profiles.apply(profile, config, sc, resolved),
        }
        if resolved:
            profile_block["answers"] = resolved
    git_dir = config.target / ".git"
    if config.init_git and not git_dir.exists():
        try:
            subprocess.run(["git", "init", "-q"], cwd=config.target, check=True)
            sc.created.append(".git/ (initialized)")
            sc.track_new(git_dir, existed=False)
        except (OSError, subprocess.CalledProcessError):
            pass
    # Last: record provenance for everything written above, so a future `update` can
    # refresh pristine generated files without touching the user's edits.
    manifest.write(config, sc, profile=profile_block)
    return profile_block


def _summary(config: WizardConfig, sc: Scaffolder) -> None:
    console.print(Panel.fit(f"[bold]{config.project_name}[/] scaffolded", style="green"))
    for rel in sorted(sc.created):
        console.print(f"  [green]+[/] {rel}")
    if sc.skipped:
        console.print(
            f"\n[yellow]Skipped {len(sc.skipped)} existing file(s)[/] (use --force to overwrite)"
        )
    contract = "Read [bold]AGENTS.md[/] — the contract for all contributors."
    onboard: str | None = None
    if config.include_quality or config.include_ci:
        # ONBOARDING.md owns the one-time setup; tell the user the concrete first action
        # (the agent can't speak first — it waits for input), not "it self-onboards".
        banner_on = config.first_run_banner and bool(config.ai_tools)
        if config.include_agents and "claude" in config.ai_tools:
            tail = (
                " (or just ask it what to do — AGENTS.md flags the pending setup)"
                if banner_on
                else " (walks through ONBOARDING.md)"
            )
            onboard = f"Finish setup: in Claude Code, type [bold]/onboard[/] at the prompt{tail}."
        else:
            tail = " — it'll also see the first-run note in AGENTS.md" if banner_on else ""
            onboard = (
                "Finish setup: open [bold]ONBOARDING.md[/] and follow it, or ask your "
                f"AI assistant to{tail}."
            )
    # The one-time setup is the must-do; reading the contract is recommended-not-required.
    # Label them as a contrasting pair only when both show, so a lone contract step (no
    # quality/CI) isn't mislabelled "Optional".
    if onboard:
        steps = [f"[dim]Optional:[/] {contract}", f"⚠️  [bold]IMPORTANT:[/] {onboard}"]
    else:
        steps = [contract]
    # A bordered panel (matching the intro) so the call to action isn't mistaken for
    # trailing log output and scrolled past.
    console.print()
    console.print(
        Panel.fit(
            "\n".join(f"• {s}" for s in steps),
            title="Next steps",
            title_align="left",
            border_style="cyan",
        )
    )


def _dry_run(
    config: WizardConfig,
    *,
    force: bool,
    profile: profiles.Profile | None = None,
    answers: dict[str, object] | None = None,
) -> None:
    """Preview a scaffold without writing. Builds into throwaway dirs so the real generators
    (and a composed profile, if any) decide the file set *and* the real ``Scaffolder`` decides
    create-vs-skip against what the target already contains — so the preview matches a real run
    (including the files it would skip), instead of pretending every path is new."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # Pass 1: discover every path a run would write (empty dir → `recorded` holds them all,
        # keyed by clean rel path for files and symlinks alike).
        scout = Scaffolder((root / "scout").resolve())
        build(
            dataclasses.replace(config, output_dir=root / "scout", init_git=False),
            scout,
            profile,
            answers=answers,
        )
        # Pass 2: stage a placeholder for each discovered path that already exists in the real
        # target, then let `Scaffolder.write`'s own preserve/force/skip logic split the result —
        # no reimplementation of that policy, so the preview can't drift from the real writer.
        stage = root / "stage"
        for rel in scout.recorded:
            if (config.target / rel).exists() or (config.target / rel).is_symlink():
                placeholder = stage / rel
                placeholder.parent.mkdir(parents=True, exist_ok=True)
                placeholder.write_text("", encoding="utf-8")
        sc = Scaffolder(stage.resolve(), force=force)
        build(
            dataclasses.replace(config, output_dir=stage, init_git=False),
            sc,
            profile,
            answers=answers,
        )
    console.print(
        Panel.fit(
            f"[bold]{config.project_name}[/] — dry run [dim](nothing written)[/]", style="yellow"
        )
    )
    for rel in sorted(sc.created):
        console.print(f"  [green]+[/] would create {rel}")
    for rel in sorted(sc.skipped):
        console.print(f"  [dim]=[/] would skip (exists): {rel}")
    # Best-effort: a real run *attempts* git init but tolerates failure; the preview says it
    # would try, not that it's guaranteed.
    if config.init_git and not (config.target / ".git").exists():
        console.print("  [green]+[/] would run git init")
    tail = f"{len(sc.created)} file(s) would be created"
    if sc.skipped:
        tail += f", {len(sc.skipped)} skipped (already present)"
    console.print(f"\n[dim]{tail} in[/] {config.target}")


def _intro() -> None:
    body = (
        "[bold]agent-native-setup[/] scaffolds an [bold]agent-native[/] project setup:\n"
        "  • a canonical [bold]AGENTS.md[/] contract for coding agents and humans\n"
        "  • docs + RFCs and a [bold].claude/[/] agents & commands library\n"
        "  • linters, pre-commit hooks, secret + dependency scanning, and CI\n\n"
        "[dim]Non-destructive — existing files are never overwritten. "
        "A few quick questions follow; press Ctrl+C to cancel.[/]"
    )
    # Rich panels allow only one title, so span it: the heading on the left and the
    # version on the right, sized to the panel's fit width (6 = the "╭─ " + " ─╮" border
    # decoration). On a terminal too narrow to fit both, fall back to the plain heading.
    label, ver = "What this will do", f"v{__version__}"
    width = console.measure(Panel.fit(body)).maximum
    gap = width - len(label) - len(ver) - 6
    if gap >= 2:
        console.print(
            Panel(
                body,
                title=f"{label}{' ' * gap}{ver}",
                title_align="left",
                width=width,
                border_style="cyan",
            )
        )
    else:  # terminal too narrow to span both — show the heading alone
        console.print(Panel.fit(body, title=label, border_style="cyan"))


def main(argv: list[str] | None = None) -> int:
    raw = sys.argv[1:] if argv is None else argv
    # `update` and `profile` are subcommands on top of the (default) scaffold flow; everything
    # else parses as before, so the scaffold CLI is untouched.
    if raw and raw[0] == "update":
        return update.run_cli(raw[1:], console)
    if raw and raw[0] == "profile":
        return profiles.run_cli(raw[1:], console)
    args = parse_args(raw)
    # resolve() so the default project name works for `-o .` (Path(".").name is "").
    out = Path(args.output).expanduser().resolve()
    interactive = not args.yes and sys.stdin.isatty()
    if interactive:
        _intro()

    # Source already in the target — drives language auto-select and legacy handling.
    in_target = set(detect_languages(out))
    detected = sorted(in_target) if args.languages is None else None
    if detected:
        console.print(f"[cyan]Detected language(s):[/] {', '.join(detected)}")

    # Respect an existing runner; for a fresh repo the prompt/flag chooses (default Make).
    runner_detected, existing_runner = detect_runner(out)

    try:
        config = (
            _interactive(args, out, detected, not existing_runner, in_target)
            if interactive
            else _from_flags(args, out, detected)
        )
    except (KeyboardInterrupt, EOFError):
        console.print("\n[yellow]Cancelled.[/]")
        return 130

    unknown = set(config.languages) - set(LANG_KEYS)
    if unknown:
        console.print(
            f"[red]Unknown language(s): {', '.join(sorted(unknown))}[/]. "
            f"Choose from: {', '.join(LANG_KEYS)}"
        )
        return 2
    unknown_tools = set(config.ai_tools) - set(AI_TOOLS)
    if unknown_tools:
        console.print(
            f"[red]Unknown AI tool(s): {', '.join(sorted(unknown_tools))}[/]. "
            f"Choose from: {', '.join(AI_TOOLS)}"
        )
        return 2

    config.existing_runner = existing_runner
    if existing_runner:
        config.runner = runner_detected  # defer to what's already there
        console.print(
            f"[cyan]Detected task runner:[/] {runner_detected} — deferring to it "
            "(no runner file generated)."
        )

    # Scaffolding over existing source for a selected language → grandfather it.
    config.existing_project = bool(set(config.languages) & in_target)
    if config.existing_project and config.include_quality:
        console.print(
            f"[yellow]Existing code detected[/] — adoption strategy: [bold]{config.adoption}[/]. "
            "See CONTRIBUTING.md."
        )

    try:
        profile = profiles.resolve(args.profile) if args.profile else None
    except profiles.ProfileError as exc:
        console.print(f"[red]{exc}[/]")
        return 2
    answers: dict[str, object] | None = None
    if profile is not None:
        console.print(f"[cyan]Profile:[/] {profile.name} {profile.version} (composed on default).")
        # SessionStart hooks live in .claude/settings.json, which is only generated for Claude.
        # Warn rather than silently drop a profile's hooks when there's nowhere to put them.
        if profile.session_start and not (config.include_agents and "claude" in config.ai_tools):
            console.print(
                ":warning:  [yellow]This profile defines session_start hooks, but the project "
                "has no Claude `.claude/` config[/] — those hooks won't be applied."
            )
        try:
            answers = profiles.gather_answers(profile, config, interactive=interactive)
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Cancelled.[/]")
            return 130

    if args.dry_run:
        _dry_run(config, force=args.force, profile=profile, answers=answers)
        return 0

    sc = Scaffolder(config.target, force=args.force)
    try:
        build(config, sc, profile, answers=answers)
    except (KeyboardInterrupt, EOFError):
        console.print("\n[yellow]Cancelled.[/]")
        if rolled_back := sc.rollback():
            console.print(f"[yellow]Rolled back {rolled_back} created or overwritten item(s).[/]")
        return 130
    _summary(config, sc)
    # Advisory, interactive-only: never in scripted/CI runs, and never blocks or fails.
    if (
        interactive
        and args.update_check
        and not os.environ.get("CI")
        and not os.environ.get("AGENT_NATIVE_SETUP_NO_UPDATE_CHECK")
    ):
        update_check.maybe_notify(console)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
