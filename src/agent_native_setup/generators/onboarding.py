"""Generates ONBOARDING.md — a one-time, self-deleting first-run runbook.

`AGENTS.md` is the standing contract and auto-loads for AI assistants. The steps
here are the things you do *once* when adopting the setup (install hooks, take a
baseline, flesh out the architecture doc), so they live in a separate file the
agent deletes when done rather than re-firing in every future session.

Scaffolded whenever there's tooling to activate (quality or CI). For Claude, the
`/onboard` command in `generators/agents.py` is a zero-friction trigger for this file.
"""

from __future__ import annotations

from agent_native_setup.config import SYMLINK_CONTRACTS, WizardConfig
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


# Step/clause texts, as module constants so the flagship profile's build step can emit its
# ONBOARDING template from the SAME strings (RFC 2026-07-05 stage A) — the conditions live in
# `_steps` below and, mirrored, in the flagship's build table. Slots use str.format names.
S_READ = (
    "Read **AGENTS.md** — the contract for all work here. Everything below assumes "
    "you've read it. That plus this runbook is all you need to start — don't pre-read "
    "the whole repo; open other files only when a step calls for them."
)
PRE_HOOKS = (
    "if `pre-commit` isn't on your PATH, install it first "
    "(`pipx install pre-commit`, or `pip install pre-commit`), then "
)
PY_CLAUSE = (
    " The commit-time guard hooks run `python3` helpers, so `python3` must be on your PATH too."
)
LYCHEE_CLAUSE = (
    " The HTML link-check hook downloads its `lychee` binary on the first "
    "hook run (one-time, needs network) — expect that run to take a moment."
)
DOES_HOOKS = "installs the git hooks (lint, format, and the secret scan run before every commit)"
DOES_SETUP = "fetches dependencies (writing `package-lock.json` — commit it with the rest)"
S_TOOLCHAIN = "Set up the toolchain: {pre}run {run_phrase} — it {does}.{py_clause}{lychee_clause}"
BASELINE_TAIL = " and see what the existing code trips on"
BASELINE_SURFACE = " (see AGENTS.md's command surface; add any check your runner is missing)"
TOOLS_NOTE = (
    " {gate} runs {listed} directly, so install {it} on your PATH first — the scaffold "
    "doesn't (e.g. `pipx install {plain}`, or `uv tool install` each)."
)
S_BASELINE = "Run {gate} once to establish a clean baseline{tail}{surface}.{tools_note}"
ADOPT_FULL = (
    "Adopt the gate on the existing code (**full**): run {fmt} across the repo, "
    "commit it as one 'apply formatting' change, and add that commit's SHA to "
    "`.git-blame-ignore-revs`; then fix what's left until {gate} is green."
)
ADOPT_PROGRESSIVE = (
    "Adopt the gate on the existing code (**progressive**): don't mass-reformat "
    "— the gate only enforces files changed in a PR, so legacy code is "
    "grandfathered until it's next touched. Note what currently fails, for awareness."
)
ADOPT_NONE = (
    "Adopt the gate on the existing code (**none**): the config is scaffolded but "
    "not enforced yet — report what {gate} flags so the team can decide when "
    "to turn it on."
)
S_DOCS = (
    "Flesh out `docs/architecture/overview.md` — the tooling components are "
    "pre-filled; add the existing code's components and dependency rules."
)
PUSH_CLAUSE = ", then push — that's what triggers CI (add a git remote first if there isn't one)"
HARNESS_NOTE = (
    " An agent harness may pause for your approval on the direct-to-`main` push — "
    "that's expected for the first commit."
)
S_COMMIT = (
    "Commit the scaffold and your changes **directly to `main`** (the initial bootstrap, "
    "so no branch/PR is needed for the first commit){push_clause}.{harness_note}"
)
S_CI_GREEN = (
    "After your first push, confirm CI is green (`gh run watch`, or ask the "
    "maintainer to check the Actions tab) — local checks can't catch a missing "
    "action tag or a deprecated runner."
)
S_DEPENDABOT = (
    "Turn on Dependabot's security (vuln-fix) updates — a repo setting "
    "`dependabot.yml` can't set (on by default for public repos; manual for private). "
    "With repo admin: `gh api --method PUT repos/{{owner}}/{{repo}}/vulnerability-alerts` "
    "then `gh api --method PUT repos/{{owner}}/{{repo}}/automated-security-fixes` "
    "(idempotent — a no-op where already on), else Settings → Code security."
)
R_DELETE = "**Delete this file**"
SYMLINK_NOTE = "; {joined} {verb} to `AGENTS.md`, so edit `AGENTS.md` only — {both} update together"
R_BANNER = (
    "remove the first-run banner from `AGENTS.md` (the `agent-native-setup:first-run` "
    "block at the top{symlink_note})"
)
R_ONBOARD = "remove the `/onboard` trigger(s) ({paths})"
CLEANUP_TAIL_HTML = " and push"
CLEANUP_TAIL_PLAIN = (
    " and push — this last commit only removes setup scaffolding, so no CI watch is needed"
)
S_CLEANUP = (
    "{cleanup}, then commit{cleanup_tail} — setup is done and `AGENTS.md` carries "
    "the standing rules."
)


# One prompt, four containers (RFC 2026-07-07-cross-tool-onboarding-triggers): every
# targeted tool gets a /onboard trigger for the same runbook, each in its tool's own
# project-scoped command format. All transient — written, never recorded, deleted by the
# runbook's own cleanup step, so no future agent of any brand re-runs onboarding.
_ONBOARD_DESCRIPTION = "Walk through first-run setup (ONBOARDING.md), then delete it"
_ONBOARD_BODY = """\
Read `ONBOARDING.md` at the repo root and work through its steps. Per its note on
working concurrently: kick the slow one-time installs off in the background up
front, and fan out genuinely independent work to subagents (e.g. drafting the
architecture doc while wiring an uncovered language) — but keep the
baseline → commit → push → CI chain serial, and keep a single mutually-dependent
change (like one language's lint/format/CI wiring) with one author so it can't
drift. Stop to confirm with me on anything needing a human decision (adding
secrets, repo-wide reformatting). When every step passes, delete `ONBOARDING.md`.
"""
ONBOARD_COMMAND_CURSOR = _ONBOARD_BODY  # Cursor: plain markdown, filename = command
# Claude and Copilot both take frontmatter markdown — one container, two paths.
ONBOARD_COMMAND_CLAUDE = f"""\
---
description: {_ONBOARD_DESCRIPTION}
---

{_ONBOARD_BODY}"""
ONBOARD_COMMAND_COPILOT = f"""\
---
description: {_ONBOARD_DESCRIPTION}
---

{_ONBOARD_BODY}"""
ONBOARD_COMMAND_GEMINI = f'''\
description = "{_ONBOARD_DESCRIPTION}"
prompt = """
{_ONBOARD_BODY}"""
'''
# (tool, output path, content) — order fixes the cleanup enumeration order.
ONBOARD_TRIGGERS = (
    ("claude", ".claude/commands/onboard.md", ONBOARD_COMMAND_CLAUDE),
    ("cursor", ".cursor/commands/onboard.md", ONBOARD_COMMAND_CURSOR),
    ("copilot", ".github/prompts/onboard.prompt.md", ONBOARD_COMMAND_COPILOT),
    ("gemini", ".gemini/commands/onboard.toml", ONBOARD_COMMAND_GEMINI),
)


def _write_triggers(
    config: WizardConfig, sc: Scaffolder, profile_paths: frozenset[str]
) -> list[str]:
    """Write a /onboard trigger per targeted tool; return the paths **actually written** —
    the cleanup step enumerates exactly these. A profile-owned path wins (the profile's
    managed copy must not be shadowed by a transient the manifest can't see), and a
    pre-existing user file is preserved, so neither is ever listed for deletion."""
    written: list[str] = []
    for tool, rel, content in ONBOARD_TRIGGERS:
        if tool not in config.ai_tools or rel in profile_paths:
            continue
        if (sc.target / rel).exists() and not sc.force:
            continue  # the user's own file — preserved, not ours to remove
        sc.write(rel, content, transient=True)
        written.append(rel)
    return written


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
        return ADOPT_FULL.format(gate=gate, fmt=fmt)
    if config.adoption == "progressive":
        return ADOPT_PROGRESSIVE
    return ADOPT_NONE.format(gate=gate)


def _steps(config: WizardConfig, profile_steps: tuple[str, ...], triggers: list[str]) -> list[str]:
    r = config.runner
    has_ci = config.include_ci and config.use_github_actions
    has_setup = any(lang.setup_command for lang in get(config.languages))  # e.g. npm install
    gate, fmt = _gate_and_format(config)

    steps = [S_READ]
    # Git hooks are optional (--no-hooks); the setup step is still worth showing when
    # there are deps to fetch (e.g. node's npm install / lockfile).
    if config.git_hooks or has_setup:
        # The pipx prereq + the hook-specific notes only apply to the hooks, which exist
        # only with git_hooks. (The RFC/docs hooks run `python3 tools/checks/*.py`.)
        if config.git_hooks:
            pre = PRE_HOOKS
            py_clause = PY_CLAUSE if config.include_docs else ""
            lychee_clause = LYCHEE_CLAUSE if "html" in config.languages else ""
        else:
            pre = py_clause = lychee_clause = ""
        does = []
        if config.git_hooks:
            does.append(DOES_HOOKS)
        if has_setup:
            does.append(DOES_SETUP)
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
            S_TOOLCHAIN.format(
                pre=pre,
                run_phrase=run_phrase,
                does=" and ".join(does),
                py_clause=py_clause,
                lychee_clause=lychee_clause,
            )
        )
    if config.include_quality:
        tail = BASELINE_TAIL if config.existing_project else ""
        surface = BASELINE_SURFACE if config.existing_runner else ""
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
            plain = " ".join(config.python_surface_tools)
            tools_note = TOOLS_NOTE.format(gate=gate, listed=listed, it=it, plain=plain)
        else:
            tools_note = ""
        steps.append(
            S_BASELINE.format(gate=gate, tail=tail, surface=surface, tools_note=tools_note)
        )
        if config.existing_project:
            steps.append(_adoption_step(config, gate, fmt))
    if config.include_docs and config.existing_project:
        steps.append(S_DOCS)  # greenfield has nothing to describe yet — the doc says so itself
    # A profile's own setup steps extend the default flow here: after the base toolchain/baseline
    # is up, but *before* the bootstrap commit — so team setup runs as part of the initial setup
    # and lands in the first commit, not as a trailing afterthought.
    steps += list(profile_steps)
    push_clause = PUSH_CLAUSE if has_ci else ""
    # The push targets `main` directly; an agent harness (e.g. Claude Code) may classify
    # that as needing approval, so flag it as expected rather than a setup error.
    harness_note = HARNESS_NOTE if has_ci else ""
    steps.append(S_COMMIT.format(push_clause=push_clause, harness_note=harness_note))
    if has_ci:
        steps.append(S_CI_GREEN)
        steps.append(S_DEPENDABOT.format())
    # The first-run apparatus self-deletes: name every artifact that was actually
    # scaffolded so the agent clears all of them in one final commit, leaving only
    # the standing contract behind.
    removals = [R_DELETE]
    if config.first_run_banner and config.ai_tools:  # the banner was injected
        # CLAUDE.md/GEMINI.md symlink to AGENTS.md, so editing AGENTS.md updates them too —
        # flag it here, in the transient runbook, so the agent doesn't try to handle those
        # separately. Deliberately kept out of the permanent contract.
        links = [name for tool, name in SYMLINK_CONTRACTS.items() if tool in config.ai_tools]
        if links:
            symlink_note = SYMLINK_NOTE.format(
                joined=" and ".join(f"`{name}`" for name in links),
                verb="symlinks" if len(links) == 1 else "symlink",
                both="both" if len(links) == 1 else "all",
            )
        else:
            symlink_note = ""
        removals.append(R_BANNER.format(symlink_note=symlink_note))
    if triggers:  # every /onboard trigger actually written — all brands, one cleanup
        removals.append(R_ONBOARD.format(paths=", ".join(f"`{p}`" for p in triggers)))
    if len(removals) == 1:
        cleanup = removals[0]
    elif len(removals) == 2:
        cleanup = f"{removals[0]} and {removals[1]}"
    else:
        cleanup = ", ".join(removals[:-1]) + ", and " + removals[-1]
    # The cleanup commit only removes setup scaffolding, so skip the second `gh run watch`
    # (the one watch stays on the first push above). Exception: with the HTML link-check
    # (lychee) in CI, this commit edits link-checked docs, so don't claim the watch is
    # unnecessary there.
    if not has_ci:
        cleanup_tail = ""
    elif "html" in config.languages:
        cleanup_tail = CLEANUP_TAIL_HTML
    else:
        cleanup_tail = CLEANUP_TAIL_PLAIN
    steps.append(S_CLEANUP.format(cleanup=cleanup, cleanup_tail=cleanup_tail))
    return steps


def generate(
    config: WizardConfig,
    sc: Scaffolder,
    profile_steps: tuple[str, ...] = (),
    *,
    base: bool | None = None,
    profile_paths: frozenset[str] = frozenset(),
) -> None:
    # Meaningful when there's tooling to activate, or a profile contributed setup steps; a
    # bare contract with nothing to do needs no runbook. ``base`` overrides the default-flow
    # detection: a standalone profile passes ``base=False`` so its steps stand alone (the
    # default's toolchain/baseline steps would reference tooling it never scaffolded).
    has_base = (config.include_quality or config.include_ci) if base is None else base
    if not has_base and not profile_steps:
        return
    # Runbook ⇒ triggers, one per targeted tool (RFC 2026-07-07): written first, so the
    # cleanup step can enumerate exactly what landed. ``profile_paths`` are the applied
    # profile's own outputs — a profile-owned path wins and gets no engine trigger.
    triggers = _write_triggers(config, sc, profile_paths)
    if has_base:
        # The profile's steps extend the default flow (slotted before the bootstrap commit).
        steps = _steps(config, profile_steps, triggers)
    else:
        # No default tooling to activate (a `--no-quality --no-ci` base, or a standalone profile
        # that doesn't extend the default): the profile's steps *are* the onboarding, then self-delete.
        cleanup = "**Delete this file**"
        if triggers:
            cleanup += " and " + R_ONBOARD.format(paths=", ".join(f"`{p}`" for p in triggers))
        steps = [*profile_steps, f"{cleanup} — onboarding is done."]
    body = HEADER.format(name=config.project_name)
    body += "\n".join(f"{i}. {step}" for i, step in enumerate(steps, 1)) + "\n"
    sc.write("ONBOARDING.md", body, transient=True)  # self-deletes during onboarding
