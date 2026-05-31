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
from ai_setup.languages import REGISTRY, detect_languages
from ai_setup.scaffold import Scaffolder

console = Console()
LANG_KEYS = list(REGISTRY)


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
    p.add_argument("--no-github-actions", dest="github_actions", action="store_false")
    p.add_argument("--no-hooks", dest="hooks", action="store_false")
    p.add_argument("--no-git", dest="git", action="store_false")
    p.add_argument("-y", "--yes", action="store_true", help="non-interactive; use flags/defaults")
    p.add_argument("--force", action="store_true", help="overwrite existing files")
    p.set_defaults(
        agents=True, docs=True, quality=True, ci=True, github_actions=True, hooks=True, git=True
    )
    return p.parse_args(argv)


def _interactive(args: argparse.Namespace, out: Path, detected: list[str] | None) -> WizardConfig:
    import questionary

    name = args.name or questionary.text("Project name:", default=out.name).ask()
    description = args.description or questionary.text("One-line description:").ask()
    languages = (
        args.languages
        if args.languages is not None
        else questionary.checkbox(
            "Languages (linters scaffolded only for these):",
            choices=[
                questionary.Choice(REGISTRY[k].label, value=k, checked=k in (detected or []))
                for k in LANG_KEYS
            ],
        ).ask()
    )
    tools = (
        args.tools
        if args.tools is not None
        else questionary.checkbox(
            "AI assistants to target:",
            choices=[questionary.Choice(t, value=t, checked=True) for t in AI_TOOLS],
        ).ask()
    )
    parts = questionary.checkbox(
        "Scaffold which parts?",
        choices=[
            questionary.Choice("Agents & commands", value="agents", checked=args.agents),
            questionary.Choice("Docs & RFCs", value="docs", checked=args.docs),
            questionary.Choice("Linters & quality", value="quality", checked=args.quality),
            questionary.Choice("CI (GitHub Actions)", value="ci", checked=args.ci),
        ],
    ).ask()
    use_ga = (
        "ci" in parts and questionary.confirm("Add GitHub Actions workflows?", default=True).ask()
    )
    hooks = (
        "quality" in parts and questionary.confirm("Install pre-commit hooks?", default=True).ask()
    )
    init_git = questionary.confirm("Run `git init`?", default=True).ask()

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
        steps.append("Run [bold]task install[/] to enable pre-commit hooks.")
    if config.include_ci and config.use_github_actions and "claude" in config.ai_tools:
        steps.append("Add an [bold]ANTHROPIC_API_KEY[/] secret to enable the @claude workflow.")
    console.print("\n[bold]Next steps:[/]")
    for s in steps:
        console.print(f"  • {s}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    out = Path(args.output).expanduser()

    # When languages aren't given, detect them from an existing project's files.
    detected = detect_languages(out) if args.languages is None else None
    if detected:
        console.print(f"[cyan]Detected language(s):[/] {', '.join(detected)}")

    interactive = not args.yes and sys.stdin.isatty()
    config = _interactive(args, out, detected) if interactive else _from_flags(args, out, detected)

    unknown = set(config.languages) - set(LANG_KEYS)
    if unknown:
        console.print(
            f"[red]Unknown language(s): {', '.join(sorted(unknown))}[/]. "
            f"Choose from: {', '.join(LANG_KEYS)}"
        )
        return 2

    sc = Scaffolder(config.target, force=args.force)
    try:
        build(config, sc)
    except KeyboardInterrupt:
        removed = sc.rollback()
        console.print(f"\n[yellow]Interrupted — rolled back {removed} newly created item(s).[/]")
        return 130
    _summary(config, sc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
