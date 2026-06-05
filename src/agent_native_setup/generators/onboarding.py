"""Generates ONBOARDING.md — a one-time, self-deleting first-run runbook.

`AGENTS.md` is the standing contract and auto-loads for AI assistants. The steps
here are the things you do *once* when adopting the setup (install hooks, take a
baseline, flesh out the architecture doc), so they live in a separate file the
agent deletes when done rather than re-firing in every future session.

Scaffolded whenever there's tooling to activate (quality or CI). For Claude, the
`/onboard` command in `generators/agents.py` is a zero-friction trigger for this file.
"""

from __future__ import annotations

from agent_native_setup.config import WizardConfig
from agent_native_setup.languages import get
from agent_native_setup.scaffold import Scaffolder

HEADER = """\
# First-run setup — {name}

This repo was scaffolded by the `agent-native-setup` wizard — an agent-native setup. The
tooling is in place but hasn't been activated yet; the steps below are the
one-time bootstrap. If you're an AI assistant starting here for the first time,
do them now. The standing rules live in `AGENTS.md`; this file is only the
bootstrap, so **delete it once every step is done.**

> **Work the independent parts concurrently.** The big costs here are one-time —
> building hook environments, installing deps, waiting on CI. If your assistant
> can, start those installs in the background up front and run independent steps in
> parallel; but keep the baseline → commit → push → CI chain in order, and pause
> for the human-gated calls (adding secrets, repo-wide reformatting).

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
    has_ci = config.include_ci and config.use_github_actions
    has_setup = any(lang.setup_command for lang in get(config.languages))  # e.g. npm install
    gate, fmt = _gate_and_format(config)

    steps = [
        "Read **AGENTS.md** — the contract for all work here. Everything below assumes "
        "you've read it. That plus this runbook is all you need to start — don't pre-read "
        "the whole repo; open other files only when a step calls for them.",
    ]
    # Git hooks are optional (--no-hooks); the setup step is still worth showing when
    # there are deps to fetch (e.g. node's npm install / lockfile).
    if config.git_hooks or has_setup:
        # The pipx prereq + the hook-specific notes only apply to the hooks, which exist
        # only with git_hooks. (lychee's hook is language: system; the RFC/docs hooks run
        # `python tools/checks/*.py`.)
        if config.git_hooks:
            pre = (
                "if `pre-commit` isn't on your PATH, install it first "
                "(`pipx install pre-commit`, or `pip install pre-commit`), then "
            )
            py_clause = (
                " The RFC/docs hooks run `python` helpers, so `python` must be on your PATH too."
                if config.include_docs
                else ""
            )
            lychee_clause = (
                " The HTML link-check hook needs `lychee` on your PATH too "
                "(`brew install lychee` or `cargo install lychee`)."
                if "html" in config.languages
                else ""
            )
        else:
            pre = py_clause = lychee_clause = ""
        does = []
        if config.git_hooks:
            does.append(
                "installs the git hooks (lint, format, and the secret scan run before every commit)"
            )
        if has_setup:
            does.append(
                "fetches dependencies (writing `package-lock.json` — commit it with the rest)"
            )
        if config.existing_runner:
            # We don't own a runner here, so spell out the deterministic commands.
            cmds = (["`pre-commit install`"] if config.git_hooks else []) + (
                ["`npm install`"] if has_setup else []
            )
            run_phrase = " and ".join(cmds)
        else:
            # `bootstrap` does hooks + dep install in one step; `install` is hooks-only.
            run_phrase = f"`{r} {'bootstrap' if has_setup else 'install'}`"
        steps.append(
            f"Set up the toolchain: {pre}run {run_phrase} — it "
            f"{' and '.join(does)}.{py_clause}{lychee_clause}"
        )
    if config.include_quality:
        tail = " and see what the existing code trips on" if config.existing_project else ""
        surface = (
            " (see AGENTS.md's command surface; add any check your runner is missing)"
            if config.existing_runner
            else ""
        )
        # The command surface calls these Python tools directly (not via npm or the managed
        # pre-commit hooks), so they must be on PATH for the gate to run — the scaffold
        # doesn't install them.
        py_tools = [f"`{t}`" for t in config.python_surface_tools]
        if py_tools:
            listed = (
                py_tools[0]
                if len(py_tools) == 1
                else ", ".join(py_tools[:-1]) + ", and " + py_tools[-1]
            )
            it = "it" if len(py_tools) == 1 else "them"
            tools_note = (
                f" {gate} runs {listed} directly, so install {it} on your PATH first "
                "(e.g. `pipx install`, `uv tool install`, or pip in a venv) — the scaffold doesn't."
            )
        else:
            tools_note = ""
        steps.append(f"Run {gate} once to establish a clean baseline{tail}{surface}.{tools_note}")
        if config.existing_project:
            steps.append(_adoption_step(config, gate, fmt))
    if config.include_docs:
        steps.append(
            "Flesh out `docs/architecture/overview.md` — the tooling components are "
            "pre-filled; add the product components and dependency rules as they land. "
            "If there's no product code yet, leave those sections as TODOs and move on."
        )
    ci_clause = ", a CI step," if has_ci else ""
    steps.append(
        "Wire up any uncovered language: if the repo uses a language not yet set up for "
        f"lint/format/test, add it the way the existing ones are (a pre-commit hook{ci_clause} "
        "and a command-surface entry), per the contract — including a real test where there's "
        "logic to cover, and a note on why if something genuinely can't be tested. If a "
        "test hook shells out to git, keep the existing hooks' `env -u GIT_DIR …` prefix so "
        "it runs against a temp repo, not this one."
    )
    push_clause = (
        ", then push — that's what triggers CI (add a git remote first if there isn't one)"
        if has_ci
        else ""
    )
    # The push targets `main` directly; an agent harness (e.g. Claude Code) may classify
    # that as needing approval, so flag it as expected rather than a setup error.
    harness_note = (
        " An agent harness may pause for your approval on the direct-to-`main` push — "
        "that's expected for the first commit."
        if has_ci
        else ""
    )
    steps.append(
        "Commit the scaffold and your changes **directly to `main`** (the initial bootstrap, "
        f"so no branch/PR is needed for the first commit){push_clause}.{harness_note}"
    )
    if has_ci:
        steps.append(
            "After your first push, confirm CI is green (`gh run watch`, or ask the "
            "maintainer to check the Actions tab) — local checks can't catch a missing "
            "action tag or a deprecated runner."
        )
        steps.append(
            "Turn on Dependabot's security (vuln-fix) updates — a repo setting "
            "`dependabot.yml` can't set (on by default for public repos; manual for private). "
            "With repo admin: `gh api --method PUT repos/{owner}/{repo}/vulnerability-alerts` "
            "then `gh api --method PUT repos/{owner}/{repo}/automated-security-fixes` "
            "(idempotent — a no-op where already on), else Settings → Code security."
        )
    # The first-run apparatus self-deletes: name every artifact that was actually
    # scaffolded so the agent clears all of them in one final commit, leaving only
    # the standing contract behind.
    removals = ["**Delete this file**"]
    if config.first_run_banner and config.ai_tools:  # the banner was injected
        # CLAUDE.md is a symlink to AGENTS.md (claude targets), so editing AGENTS.md updates
        # both — flag it here, in the transient runbook, so the agent doesn't try to handle
        # CLAUDE.md separately. Deliberately kept out of the permanent contract.
        symlink_note = (
            "; `CLAUDE.md` symlinks to `AGENTS.md`, so edit `AGENTS.md` only — both update together"
            if "claude" in config.ai_tools
            else ""
        )
        removals.append(
            "remove the first-run banner from `AGENTS.md` (the `agent-native-setup:first-run` "
            f"block at the top{symlink_note})"
        )
    if config.include_agents and "claude" in config.ai_tools:  # the /onboard command exists
        removals.append("remove the `/onboard` command (`.claude/commands/onboard.md`)")
    if len(removals) == 1:
        cleanup = removals[0]
    elif len(removals) == 2:
        cleanup = f"{removals[0]} and {removals[1]}"
    else:
        cleanup = ", ".join(removals[:-1]) + ", and " + removals[-1]
    # The cleanup commit only removes setup scaffolding, so skip the second `gh run watch`
    # (the one watch stays on step 8's first push). Exception: with the HTML link-check
    # (lychee) in CI, this commit edits link-checked docs, so don't claim the watch is
    # unnecessary there.
    if not has_ci:
        cleanup_tail = ""
    elif "html" in config.languages:
        cleanup_tail = " and push"
    else:
        cleanup_tail = (
            " and push — this last commit only removes setup scaffolding, so no CI watch is needed"
        )
    steps.append(
        f"{cleanup}, then commit{cleanup_tail} — setup is done and `AGENTS.md` carries "
        "the standing rules."
    )
    return steps


def generate(config: WizardConfig, sc: Scaffolder) -> None:
    # Only meaningful when there's tooling to activate; a bare contract needs no runbook.
    if not (config.include_quality or config.include_ci):
        return
    body = HEADER.format(name=config.project_name)
    body += "\n".join(f"{i}. {step}" for i, step in enumerate(_steps(config), 1)) + "\n"
    sc.write("ONBOARDING.md", body)
