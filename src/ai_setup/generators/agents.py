"""Generates Claude Code subagents and slash commands.

Ships a small, opinionated set wired to the four execution principles rather
than a sprawling catalogue — add more as real workflows emerge.
"""

from __future__ import annotations

from ai_setup.config import WizardConfig
from ai_setup.scaffold import Scaffolder

AGENTS_README = """\
# Agents & commands

- `agents/` — Claude Code subagents (focused, tool-scoped personas).
- `commands/` — slash commands for repeatable workflows.

Keep each agent narrow. The shared contract lives in the root `AGENTS.md`.
"""

CODE_REVIEWER = """\
---
name: code-reviewer
description: Reviews the diff against the four execution principles. Use after changing code.
tools: Read, Grep, Glob, Bash
---

You review changes for this project. Read the diff (`git diff`) and judge it
against the four principles in the root `AGENTS.md`:

1. Think before coding — are assumptions sound and stated?
2. Simplicity first — is this the minimum code? Flag speculative abstractions.
3. Surgical changes — does every changed line trace to the task? Flag drive-by
   refactors and reformatting.
4. Goal-driven — is the change verified by a test or check?

Report findings ordered by severity. Be specific: cite `file:line`. Prefer a
few high-confidence issues over a long list. If it's clean, say so plainly.
"""

PLANNER = """\
---
name: planner
description: Turns a vague task into a verifiable, step-by-step plan before any code is written.
tools: Read, Grep, Glob
---

You turn tasks into plans. For the given task:

- Restate the goal and list explicit assumptions. Flag anything ambiguous.
- Produce numbered steps, each with a concrete verification check
  ("verify: <test/command/observation>").
- Call out the simplest viable approach and any tradeoffs.
- Do not write implementation code — output only the plan.
"""

RFC_COMMAND = """\
---
description: Scaffold a new RFC in docs/rfc/current/
---

Create a new RFC for: $ARGUMENTS

1. Pick a short kebab-case slug and today's date.
2. Copy `docs/rfc/TEMPLATE.md` to `docs/rfc/current/<YYYY-MM-DD>-<slug>.md`.
3. Fill in Context, Decision, and Consequences. Leave status as `Proposed`.
4. Show me the draft before considering it done.
"""

REVIEW_COMMAND = """\
---
description: Review the current changes with the code-reviewer subagent
---

Run the `code-reviewer` subagent on the current uncommitted changes and
summarize its findings. Focus on correctness and the four execution principles.
"""


def generate(config: WizardConfig, sc: Scaffolder) -> None:
    if "claude" not in config.ai_tools:
        return
    sc.write(".claude/README.md", AGENTS_README)
    sc.write(".claude/agents/code-reviewer.md", CODE_REVIEWER)
    sc.write(".claude/agents/planner.md", PLANNER)
    sc.write(".claude/commands/review.md", REVIEW_COMMAND)
    if config.include_docs:
        sc.write(".claude/commands/rfc.md", RFC_COMMAND)
