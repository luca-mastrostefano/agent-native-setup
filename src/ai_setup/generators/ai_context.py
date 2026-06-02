"""Generates the canonical agent contract and per-tool entry points.

AGENTS.md is the single source of truth. CLAUDE.md symlinks to it; Cursor and
Copilot files are thin pointers back to it so the contract never forks.
"""

from __future__ import annotations

from pathlib import Path

from ai_setup.config import WizardConfig
from ai_setup.languages import get
from ai_setup.scaffold import Scaffolder, render

AGENTS_MD = """\
# {{ name }} — Agent Contract

{% if description %}{{ description }}

{% endif %}This file is the **single source of truth** for both human and AI contributors.
`CLAUDE.md`, `.cursor/rules/`, and `.github/copilot-instructions.md` all point here.

## Navigation

| Topic | Where |
| --- | --- |
| Project entry point | [`README.md`](./README.md) |
{% if docs %}| Architecture & decisions | `docs/architecture/` |
| Active proposals | `docs/rfc/current/` |
| How to contribute | `docs/contributing.md` |
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

{% if docs %}## When to write an RFC

Write an RFC in `docs/rfc/current/` before: changing architecture or a public
contract, adding a dependency or service, or anything hard to reverse. Use the
template in `docs/rfc/TEMPLATE.md`. Lifecycle: `current/ → done/ → superseded/`.

{% endif %}## How this project stays AI-native

- **Context** — this contract, `docs/`, and RFCs keep intent discoverable.
- **Mechanical enforcement** — linters, hooks{% if ci %}, and CI{% endif %} catch
  violations automatically. Error messages should tell you how to fix them.
- **Feedback loops** — {% if agents %}agents in `.claude/agents/`, {% endif %}tests,
  and reviews close the loop so quality compounds.
"""

README_MD = """\
# {{ name }}

{% if description %}{{ description }}

{% endif %}## Getting started

This repository follows an AI-native setup. **Start with
[`AGENTS.md`](./AGENTS.md)** — the single source of truth for conventions, the
command surface, and the four execution principles.

{% if show_quickstart %}Requires [`pre-commit`](https://pre-commit.com){% if runner == "task" %} and [`task`](https://taskfile.dev){% endif %}.

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
    rendered = render(
        AGENTS_MD,
        name=config.project_name,
        description=config.description,
        docs=config.include_docs,
        agents=config.include_agents,
        ci=config.include_ci and config.use_github_actions,
        quality_commands=quality_commands,
        surface_note=surface_note,
        capture_line=capture_line if quality_commands else "",
    )

    # Never clobber a pre-existing contract. Fold any non-empty AGENTS.md — and
    # the real CLAUDE.md we're about to replace with a symlink — below ours.
    agents_path = config.target / "AGENTS.md"
    claude_path = config.target / "CLAUDE.md"
    claude_targeted = "claude" in config.ai_tools
    sources = [agents_path] + ([claude_path] if claude_targeted else [])
    preserved = [(p.name, text) for p in sources if (text := _live_text(p))]
    if preserved:
        agents_existed = agents_path.is_file()
        blocks = [rendered.rstrip()]
        for label, text in preserved:
            blocks.append(f"---\n\n<!-- Preserved from your original {label} -->\n\n{text}")
        agents_path.parent.mkdir(parents=True, exist_ok=True)
        agents_path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
        names = ", ".join(label for label, _ in preserved)
        sc.created.append(f"AGENTS.md (merged existing {names})")
        sc.track_new(agents_path, existed=agents_existed)
    else:
        sc.write("AGENTS.md", rendered)

    # README is the human entry point the contract links to; never clobber an
    # existing one, even with --force.
    sc.render_write(
        "README.md",
        README_MD,
        preserve=True,
        name=config.project_name,
        description=config.description,
        show_quickstart=config.include_quality and not config.existing_runner,
        runner=config.runner,
    )

    if claude_targeted:
        # The real CLAUDE.md (if any) is now folded into AGENTS.md; drop it so the
        # symlink can take its place.
        if any(label == "CLAUDE.md" for label, _ in preserved):
            claude_path.unlink()
        sc.symlink("CLAUDE.md", "AGENTS.md")
    if "cursor" in config.ai_tools:
        sc.write(".cursor/rules/agent-contract.mdc", CURSOR_RULE)
    if "copilot" in config.ai_tools:
        sc.write(".github/copilot-instructions.md", COPILOT_MD)
