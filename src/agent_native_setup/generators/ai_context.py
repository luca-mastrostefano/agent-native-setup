"""Generates the canonical agent contract and per-tool entry points.

AGENTS.md is the single source of truth. CLAUDE.md and GEMINI.md symlink to it;
Cursor and Copilot files are thin pointers back to it so the contract never forks.
"""

from __future__ import annotations

from pathlib import Path

from agent_native_setup.config import SYMLINK_CONTRACTS, WizardConfig
from agent_native_setup.generators import quality
from agent_native_setup.languages import get
from agent_native_setup.scaffold import Scaffolder, render

AGENTS_MD = """\
{% if first_run_banner %}<!-- agent-native-setup:first-run — remove this block once ONBOARDING.md is done -->
> **First run — setup pending.** This repo was scaffolded by the `agent-native-setup` wizard
> (an agent-native setup); the tooling is in place but the one-time onboarding hasn't run
> yet. **Before other work, complete [`ONBOARDING.md`](./ONBOARDING.md)** — then delete
> it and remove this block.
<!-- /agent-native-setup:first-run -->

{% endif %}# {{ name }} — Agent Contract

{% if description %}{{ description }}

{% endif %}This file is the **single source of truth** for both coding agents and humans.
`CLAUDE.md`, `GEMINI.md`, `.cursor/rules/`, and `.github/copilot-instructions.md` all point here.

## Navigation

| Topic | Where |
| --- | --- |
| Project entry point | [`README.md`](./README.md) |
{% if docs %}| Architecture & decisions | `docs/architecture/` |
| Active proposals | `docs/rfc/current/` |
| How to contribute | `docs/contributing.md` |
{% endif %}{% if security %}| Security policy | [`SECURITY.md`](./SECURITY.md) |
{% endif %}

## Command surface

{% if quality_commands %}```bash
{% for label, cmd in quality_commands %}{{ cmd }}{{ "  # " + label }}
{% endfor %}```

{{ surface_note }}

{{ capture_line }}
{% else %}_No quality tooling configured yet._
{% endif %}

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

**Every change ships with the test that proves it** — pick the right level, don't
mechanically add all three:
- **Unit** — logic and edge cases (the default).
- **Integration** — when the change crosses a module, a public contract, or an external boundary.
- **Regression** — for every bug, write the failing test that reproduces it *first*, then fix.

Tests should *prove behavior*, not restate the implementation — cover the boundaries
(empty/zero/one/max), bad input, and error paths, not just the happy path. A test that
can't fail isn't worth writing.

If something genuinely can't be tested, say why rather than skipping silently.

{% if docs %}## When to write an RFC

Write an RFC in `docs/rfc/current/` before: changing architecture or a public
contract, adding a dependency or service, or anything hard to reverse. Use the
template in `docs/rfc/TEMPLATE.md`. Lifecycle: `current/ → done/ → superseded/`.{% if agents %} Before flipping one to Accepted, run the `rfc-reviewer` on the draft and resolve its findings — it checks the *decision* (simplest option, honest consequences, alternatives weighed), the way `code-reviewer` checks the diff.{% endif %}


{% endif %}## How this project stays agent-native

- **Context** — this contract, `docs/`, and RFCs keep intent discoverable. Keep it that
  way as the repo grows by scoping context down instead of letting one file sprawl: a
  directory with rules of its own can carry a local `AGENTS.md`{{ nested_symlink_note }} that
  agents follow as the nearest contract.{% if docs %} Likewise,
  give a subsystem its own `docs/architecture/<name>.md` and keep `overview.md` the index,
  so no one file becomes a monolith.{% endif %}
- **Mechanical enforcement** — linters, hooks{% if ci %}, and CI{% endif %} catch
  violations automatically. Error messages should tell you how to fix them. If a
  language in the repo isn't yet wired up for linting, formatting, and tests, add it the
  way the existing ones are (a pre-commit hook{% if ci %}, a CI step{% endif %}, and a
  command-surface entry) rather than leaving it unguarded.
- **Feedback loops** — {% if agents %}agents in `.claude/agents/`, {% endif %}tests,
  and reviews close the loop so quality compounds.{% if agents %} Before calling a
  non-trivial change done, run the `code-reviewer` (`/review`) on your diff and resolve
  its findings.{% endif %}{% if claude %} When a change touches a security-sensitive
  surface — auth, untrusted input, secrets or crypto, or file/network I/O — also run
  `/security-review` before merging; the mechanical scans catch known-bad dependencies
  and committed secrets, not logic flaws.{% endif %}{% if ci %} After changing a workflow
  in `.github/workflows/`, confirm it passed on GitHub (`gh run watch`; if `gh` isn't set
  up, ask the maintainer to check the repo's Actions tab) — local checks can't tell an
  action is missing or out of date.{% endif %} Remember that `git commit` records the
  staged index, not your working tree: re-stage any fix made after `git add` — including
  ones prompted by review — then sanity-check `git show --stat` before pushing. And make
  any long-running or backgrounded command followable — run it unbuffered (`python -u` /
  `PYTHONUNBUFFERED=1` / `stdbuf -oL`) and `tee` it to a logfile — so its progress streams
  instead of buffering silently.
"""

README_MD = """\
# {{ name }}

{% if description %}{{ description }}

{% endif %}## Getting started

This repository follows an agent-native setup. **Start with
[`AGENTS.md`](./AGENTS.md)** — the single source of truth for conventions, the
command surface, and the four execution principles.

{% if show_quickstart %}Requires [`pre-commit`](https://pre-commit.com){% if runner == "task" %} and [`task`](https://taskfile.dev){% endif %}{% if surface_tools %}; the command surface also calls {{ surface_tools }} directly, so put {{ surface_pron }} on your PATH (pipx/uv/pip){% endif %}{% if needs_lychee %}. The HTML link-check hook downloads its [`lychee`](https://lychee.cli.rs) binary on the first hook run (one-time, needs network){% endif %}.

```bash
{{ runner }} install   # set up git hooks (once)
{{ runner }} quality   # run the full local gate
```
{% endif %}"""

CURSOR_RULE = """\
---
description: Project agent contract (canonical rules live in AGENTS.md)
alwaysApply: true
---

Read and follow `AGENTS.md` at the repo root — it is the single source of truth
for conventions, the command surface, and the four execution principles.
Do not duplicate rules here; edit `AGENTS.md` instead.
"""

COPILOT_MD = """\
# Copilot instructions

The canonical contract for this repository is **`AGENTS.md`** at the root.
Follow it: the four execution principles (think before coding, simplicity first,
surgical changes, goal-driven execution) and the documented command surface.
"""


def _live_text(path: Path) -> str:
    """Return the stripped content of a real (non-symlink) file, else ``""``."""
    if path.is_symlink() or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _nested_symlink_note(symlinks: list[str]) -> str:
    """The 'symlink beside a nested AGENTS.md' aside, for the targeted symlink tools.

    Empty when no symlink tool is targeted (e.g. Cursor/Copilot only) — they read a
    nested AGENTS.md directly, so the note doesn't apply.
    """
    if not symlinks:
        return ""
    joined = "/".join(f"`{name}`" for name in symlinks)
    if len(symlinks) == 1:
        tool = "Claude" if symlinks[0] == "CLAUDE.md" else "Gemini"
        loads = f"{tool} loads {joined}"
    else:
        loads = "those tools load their own file"
    return f" (with a {joined} symlink beside it, like the root — {loads}, not `AGENTS.md`)"


def generate(config: WizardConfig, sc: Scaffolder) -> None:
    # The Taskfile is the canonical command surface; point the contract at it.
    langs = get(config.languages)

    def _has(label: str) -> bool:
        return any(lbl == label for lang in langs for lbl, _ in lang.quality_commands)

    quality_commands: list[tuple[str, str]] = []
    surface_note = ""
    if config.include_quality and config.existing_runner:
        # Their runner is the source of truth — show the raw checks to ensure exist.
        if config.git_hooks:
            quality_commands.append(("set up git hooks (once)", "pre-commit install"))
        seen: set[str] = set()
        for label in ("lint", "format", "typecheck", "test"):
            for lang in langs:
                for lbl, cmd in lang.quality_commands:
                    if lbl == label and cmd not in seen:
                        seen.add(cmd)
                        quality_commands.append((label, cmd))
        runner_name = "Task" if config.runner == "task" else "Make"
        discover = (
            "task --list"
            if config.runner == "task"
            else "grep -E '^[A-Za-z0-9_.-]+:.*## ' Makefile"
        )
        surface_note = (
            f"This repo already uses **{runner_name}** — its targets are the source of "
            f"truth. Run `{discover}` to see them; the commands above are the standard "
            f"checks this setup expects, so add any that aren't already targets."
        )
    elif config.include_quality:
        verb = config.runner  # "make" (default) or "task"
        if config.git_hooks:
            quality_commands.append(("set up git hooks (once)", f"{verb} install"))
        quality_commands.append(("run linters", f"{verb} lint"))
        quality_commands.append(("auto-format", f"{verb} format"))
        if _has("typecheck"):
            quality_commands.append(("type-check", f"{verb} typecheck"))
        if _has("test"):
            quality_commands.append(("run tests", f"{verb} test"))
        quality_commands.append(("full local gate", f"{verb} quality"))
        if config.include_docs:
            quality_commands.append(("sync RFCs to their Status folder", f"{verb} rfc-sync"))
            quality_commands.append(
                ("log an idea in docs/improvements.md", quality.IMPROVEMENT_USAGE[verb])
            )
        surface_note = (
            "Run `task --list` for the full, current set."
            if verb == "task"
            else "Run `make help` for the full, current set."
        )

    target_word = "`task`" if config.runner == "task" else "`make` target"
    capture_line = (
        "**When you work out a repeatable process — a build, check, migration, or fix "
        f"sequence you'd otherwise rediscover — capture it as a {target_word} with a "
        "one-line description, so the next contributor runs it deterministically instead "
        "of leaving the knowledge in a chat or a throwaway script.**"
    )
    # Tools whose context file is a symlink to AGENTS.md (CLAUDE.md, GEMINI.md), in
    # registry order — drives the nested-contract note and the fold/symlink below.
    symlinks = [name for tool, name in SYMLINK_CONTRACTS.items() if tool in config.ai_tools]
    rendered = render(
        AGENTS_MD,
        name=config.project_name,
        description=config.description,
        docs=config.include_docs,
        agents=config.include_agents,
        # `/security-review` is a Claude Code built-in, so point at it only for Claude
        # targets — independent of whether we scaffold our own `.claude/` agents.
        claude="claude" in config.ai_tools,
        nested_symlink_note=_nested_symlink_note(symlinks),
        ci=config.include_ci and config.use_github_actions,
        security=config.include_security,
        # Banner only helps when a targeted tool auto-loads AGENTS.md AND there's an
        # ONBOARDING.md to point at; otherwise it's inert text.
        first_run_banner=(
            config.first_run_banner
            and bool(config.ai_tools)
            and (config.include_quality or config.include_ci)
        ),
        quality_commands=quality_commands,
        surface_note=surface_note,
        capture_line=capture_line if quality_commands else "",
    )

    # Never clobber a pre-existing contract. Fold any non-empty AGENTS.md — and the real
    # CLAUDE.md/GEMINI.md we're about to replace with symlinks — below ours.
    agents_path = config.target / "AGENTS.md"
    sources = [agents_path] + [config.target / name for name in symlinks]
    preserved = [(p.name, text) for p in sources if (text := _live_text(p))]
    if preserved:
        agents_existed = agents_path.is_file()
        blocks = [rendered.rstrip()]
        for label, text in preserved:
            blocks.append(f"---\n\n<!-- Preserved from your original {label} -->\n\n{text}")
        merged = "\n\n".join(blocks) + "\n"
        agents_path.parent.mkdir(parents=True, exist_ok=True)
        agents_path.write_text(merged, encoding="utf-8")
        names = ", ".join(label for label, _ in preserved)
        sc.created.append(f"AGENTS.md (merged existing {names})")
        sc.track_new(agents_path, existed=agents_existed)
        sc.record("AGENTS.md", merged)  # this path bypasses sc.write; fingerprint it too
    else:
        sc.write("AGENTS.md", rendered)

    # README is the human entry point the contract links to; never clobber an
    # existing one, even with --force.
    # Python tools the command surface calls directly (see config.python_surface_tools) —
    # declared as prerequisites so `make quality` doesn't fail on a clean machine.
    py_surface = [f"`{t}`" for t in config.python_surface_tools]
    if len(py_surface) <= 1:
        surface_tools = py_surface[0] if py_surface else ""
    else:
        surface_tools = ", ".join(py_surface[:-1]) + ", and " + py_surface[-1]
    sc.render_write(
        "README.md",
        README_MD,
        preserve=True,
        name=config.project_name,
        description=config.description,
        show_quickstart=config.include_quality and not config.existing_runner,
        runner=config.runner,
        needs_lychee=config.git_hooks and "html" in config.languages,
        surface_tools=surface_tools,
        surface_pron="it" if len(py_surface) == 1 else "them",
    )

    for name in symlinks:
        # A real CLAUDE.md/GEMINI.md (if any) is now folded into AGENTS.md; drop it so
        # the symlink can take its place.
        if any(label == name for label, _ in preserved):
            (config.target / name).unlink()
        sc.symlink(name, "AGENTS.md")
    if "cursor" in config.ai_tools:
        sc.write(".cursor/rules/agent-contract.mdc", CURSOR_RULE)
    if "copilot" in config.ai_tools:
        sc.write(".github/copilot-instructions.md", COPILOT_MD)
