"""Command-line entry point: flags, interactive prompts, orchestration."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from ai_setup.config import AI_TOOLS, WizardConfig
from ai_setup.generators import agents, ai_context, ci, docs, quality
from ai_setup.languages import REGISTRY, detect_languages, detect_runner
from ai_setup.scaffold import Scaffolder

console = Console()
LANG_KEYS = list(REGISTRY)
_MULTISELECT_HINT = "(↑/↓ move · space to select · enter to confirm)"


def _csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="ai-setup", description="Scaffold an AI-native project setup.")
    p.add_argument("name", nargs="?", help="project name")
    p.add_argument("-o", "--output", default=".", help="target directory (default: cwd)")
    p.add_argument("--description", default="")
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
    p.add_argument("--no-git", dest="git", action="store_false")
    p.add_argument("-y", "--yes", action="store_true", help="non-interactive; use flags/defaults")
    p.add_argument("--force", action="store_true", help="overwrite existing files")
    p.set_defaults(
        agents=True,
        docs=True,
        quality=True,
        ci=True,
        security=True,
        github_actions=True,
        hooks=True,
        git=True,
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
            console.print("[yellow]No language selected[/] — linters/tests won't be scaffolded.")
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
        init_git=args.git,
    )


def build(config: WizardConfig, sc: Scaffolder) -> Scaffolder:
    config.target.mkdir(parents=True, exist_ok=True)
    ai_context.generate(config, sc)
    if config.include_agents:
        agents.generate(config, sc)
    if config.include_docs:
        docs.generate(config, sc)
    if config.include_quality:
        quality.generate(config, sc)
    if config.include_ci:
        ci.generate(config, sc)
    git_dir = config.target / ".git"
    if config.init_git and not git_dir.exists():
        try:
            subprocess.run(["git", "init", "-q"], cwd=config.target, check=True)
            sc.created.append(".git/ (initialized)")
            sc.track_new(git_dir, existed=False)
        except (OSError, subprocess.CalledProcessError):
            pass
    return sc


def _summary(config: WizardConfig, sc: Scaffolder) -> None:
    console.print(Panel.fit(f"[bold]{config.project_name}[/] scaffolded", style="green"))
    for rel in sorted(sc.created):
        console.print(f"  [green]+[/] {rel}")
    if sc.skipped:
        console.print(
            f"\n[yellow]Skipped {len(sc.skipped)} existing file(s)[/] (use --force to overwrite)"
        )
    steps = ["Read [bold]AGENTS.md[/] — the contract for all contributors."]
    if config.git_hooks:
        install_cmd = "pre-commit install" if config.existing_runner else f"{config.runner} install"
        steps.append(
            f"Install [bold]pre-commit[/] (e.g. [bold]pipx install pre-commit[/]), then run "
            f"[bold]{install_cmd}[/] to enable the git hooks."
        )
    if config.include_ci and config.use_github_actions and "claude" in config.ai_tools:
        steps.append("Add an [bold]ANTHROPIC_API_KEY[/] secret to enable the @claude workflow.")
    console.print("\n[bold]Next steps:[/]")
    for s in steps:
        console.print(f"  • {s}")


def _intro() -> None:
    console.print(
        Panel.fit(
            "[bold]ai-setup[/] scaffolds an [bold]AI-native[/] project setup:\n"
            "  • a canonical [bold]AGENTS.md[/] contract for human + AI contributors\n"
            "  • docs + RFCs and a [bold].claude/[/] agents & commands library\n"
            "  • linters, pre-commit hooks, secret + dependency scanning, and CI\n\n"
            "[dim]Non-destructive — existing files are never overwritten. "
            "A few quick questions follow; press Ctrl+C to cancel.[/]",
            title="What this will do",
            border_style="cyan",
        )
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    out = Path(args.output).expanduser()
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
            "See docs/contributing.md."
        )

    sc = Scaffolder(config.target, force=args.force)
    try:
        build(config, sc)
    except (KeyboardInterrupt, EOFError):
        console.print("\n[yellow]Cancelled.[/]")
        if removed := sc.rollback():
            console.print(f"[yellow]Rolled back {removed} newly created item(s).[/]")
        return 130
    _summary(config, sc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
