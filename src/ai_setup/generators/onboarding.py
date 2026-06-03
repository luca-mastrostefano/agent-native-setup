"""Generates ONBOARDING.md — a one-time, self-deleting first-run runbook.

`AGENTS.md` is the standing contract and auto-loads for AI assistants. The steps
here are the things you do *once* when adopting the setup (install hooks, take a
baseline, flesh out the architecture doc), so they live in a separate file the
agent deletes when done rather than re-firing in every future session.

Scaffolded whenever there's tooling to activate (quality or CI). For Claude, the
`/onboard` command in `generators/agents.py` is a zero-friction trigger for this file.
"""

from __future__ import annotations

from ai_setup.config import WizardConfig
from ai_setup.scaffold import Scaffolder

HEADER = """\
# First-run setup — {name}

This repo was scaffolded by the `ai-setup` wizard — an AI-native setup. The
tooling is in place but hasn't been activated yet; the steps below are the
one-time bootstrap. If you're an AI assistant starting here for the first time,
do them now. The standing rules live in `AGENTS.md`; this file is only the
bootstrap, so **delete it once every step is done.**

"""


def _gate_and_format(config: WizardConfig) -> tuple[str, str]:
    """(full-gate phrase, formatter phrase) for the runbook.

    With a generated runner we own the `quality`/`format` targets and name them
    directly. When deferring to a *detected* runner we don't own its targets, so
    we point at AGENTS.md's command surface instead of a target that may not exist
    (the same hedge `ai_context` and the install step already make).
    """
    if config.existing_runner:
        return ("your full check gate", "your formatter")
    r = config.runner
    return (f"`{r} quality`", f"`{r} format`")


def _adoption_step(config: WizardConfig, gate: str, fmt: str) -> str:
    if config.adoption == "full":
        return (
            f"Adopt the gate on the existing code (**full**): run {fmt} across the repo, "
            "commit it as one 'apply formatting' change, and add that commit's SHA to "
            f"`.git-blame-ignore-revs`; then fix what's left until {gate} is green."
        )
    if config.adoption == "progressive":
        return (
            "Adopt the gate on the existing code (**progressive**): don't mass-reformat "
            "— the gate only enforces files changed in a PR, so legacy code is "
            "grandfathered until it's next touched. Note what currently fails, for awareness."
        )
    return (
        "Adopt the gate on the existing code (**none**): the config is scaffolded but "
        f"not enforced yet — report what {gate} flags so the team can decide when "
        "to turn it on."
    )


def _steps(config: WizardConfig) -> list[str]:
    r = config.runner
    install_cmd = "pre-commit install" if config.existing_runner else f"{r} install"
    has_ci = config.include_ci and config.use_github_actions
    gate, fmt = _gate_and_format(config)

    steps = [
        "Read **AGENTS.md** — the contract for all work here. Everything below assumes "
        "you've read it.",
    ]
    if config.git_hooks:
        # The RFC/docs hooks shell out to `python tools/checks/*.py`, so a non-Python
        # project still needs `python` on PATH for them to run.
        py_clause = (
            " (the RFC/docs hooks run `python` helpers, so `python` must be on your PATH too)"
            if config.include_docs
            else ""
        )
        # lychee's hook is language: system — it needs the binary already installed, or
        # the first commit that touches a checked file fails.
        lychee_clause = (
            " The HTML link-check hook needs `lychee` on your PATH too "
            "(`brew install lychee` or `cargo install lychee`)."
            if "html" in config.languages
            else ""
        )
        steps.append(
            "Install the git hooks: if `pre-commit` isn't on your PATH, `pipx install "
            f"pre-commit` first, then run `{install_cmd}` so lint, format, and the secret "
            f"scan run before every commit{py_clause}.{lychee_clause}"
        )
    if config.include_quality:
        tail = " and see what the existing code trips on" if config.existing_project else ""
        surface = (
            " (see AGENTS.md's command surface; add any check your runner is missing)"
            if config.existing_runner
            else ""
        )
        steps.append(f"Run {gate} once to establish a clean baseline{tail}{surface}.")
        if config.existing_project:
            steps.append(_adoption_step(config, gate, fmt))
    if config.include_docs:
        steps.append(
            "Flesh out `docs/architecture/overview.md` — it ships as a stub. Replace it "
            "with a real map of this codebase's components so future agents have context."
        )
    ci_clause = ", a CI step," if has_ci else ""
    steps.append(
        "Wire up any uncovered language: if the repo uses a language not yet set up for "
        f"lint/format/test, add it the way the existing ones are (a pre-commit hook{ci_clause} "
        "and a command-surface entry), per the contract."
    )
    push_clause = (
        ", then push — that's what triggers CI (add a git remote first if there isn't one)"
        if has_ci
        else ""
    )
    steps.append(f"Commit the scaffold and your changes{push_clause}.")
    if has_ci:
        steps.append(
            "After your first push, confirm CI is green (`gh run watch`, or ask the "
            "maintainer to check the Actions tab) — local checks can't catch a missing "
            "action tag or a deprecated runner."
        )
        if "claude" in config.ai_tools:
            steps.append(
                "Enable the @claude workflow: add an `ANTHROPIC_API_KEY` secret "
                "(Settings → Secrets and variables → Actions). This one's on you, not the agent."
            )
    # The first-run apparatus self-deletes: name every artifact that was actually
    # scaffolded so the agent clears all of them in one final commit, leaving only
    # the standing contract behind.
    removals = ["**Delete this file**"]
    if config.first_run_banner and config.ai_tools:  # the banner was injected
        removals.append(
            "remove the first-run banner from `AGENTS.md` (the `ai-setup:first-run` "
            "block at the top)"
        )
    if config.include_agents and "claude" in config.ai_tools:  # the /onboard command exists
        removals.append("remove the `/onboard` command (`.claude/commands/onboard.md`)")
    if len(removals) == 1:
        cleanup = removals[0]
    elif len(removals) == 2:
        cleanup = f"{removals[0]} and {removals[1]}"
    else:
        cleanup = ", ".join(removals[:-1]) + ", and " + removals[-1]
    steps.append(
        f"{cleanup}, then commit — setup is done and `AGENTS.md` carries the standing rules."
    )
    return steps


def generate(config: WizardConfig, sc: Scaffolder) -> None:
    # Only meaningful when there's tooling to activate; a bare contract needs no runbook.
    if not (config.include_quality or config.include_ci):
        return
    body = HEADER.format(name=config.project_name)
    body += "\n".join(f"{i}. {step}" for i, step in enumerate(_steps(config), 1)) + "\n"
    sc.write("ONBOARDING.md", body)
