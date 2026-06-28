"""Generates Claude Code subagents and slash commands.

Ships a small, opinionated set wired to the four execution principles rather
than a sprawling catalogue — add more as real workflows emerge.
"""

from __future__ import annotations

import json

from agent_native_setup.config import WizardConfig
from agent_native_setup.languages import get
from agent_native_setup.scaffold import Scaffolder

# Make has no built-in target lister; grep self-documenting `## ` targets, else names.
_MAKE_LIST_GREP = (
    "grep -E '^[A-Za-z0-9_.-]+:.*## ' Makefile | sed -E 's/:.*## /  /' "
    "|| grep -E '^[A-Za-z0-9_.-]+:' Makefile | cut -d: -f1 | sort -u"
)

# No-binary fallback: pull task names (and their desc: lines, indented) straight from
# the Taskfile, so the agent still gets the command surface when go-task isn't installed.
# First-match-only loop, not `cat` over all spellings: on a case-insensitive filesystem
# (macOS, Windows) Taskfile.yml and taskfile.yml are the same file and would list twice.
# The trailing pipeline exits 0 either way, so the hook never reports failure.
_TASKFILE_LIST_SED = (
    "for f in Taskfile.yml taskfile.yml Taskfile.yaml taskfile.yaml; do "
    'if [ -f "$f" ]; then cat "$f"; break; fi; done '
    "| sed -n -E 's/^  ([A-Za-z0-9_.-]+):$/\\1/p; s/^    desc: */  /p'"
)


# SessionStart staleness nudge: only if the CLI is on PATH, and silent on any failure, so a
# missing tool or an offline machine never disrupts the session.
UPDATE_CHECK_COMMAND = (
    "command -v agent-native-setup >/dev/null 2>&1 && "
    "agent-native-setup update --check 2>/dev/null || true"
)


def _guarded(command: str) -> str:
    """Wrap a profile-contributed SessionStart command so a failure can't disrupt the session —
    matching how the built-in hooks stay tolerant (always exit 0). The `{ …; }` group makes the
    `|| true` apply to the whole command (sequences, `&&`, pipes), not just its last part."""
    return f"{{ {command.strip()} ; }} || true"


def write_session_start_settings(sc: Scaffolder, session_start: tuple[str, ...]) -> None:
    """Write a minimal ``.claude/settings.json`` carrying only a standalone profile's guarded
    SessionStart hooks. A standalone profile (``extends: null``) skips the full `generate` above,
    so it owns its own permissions/agents — this just gives its every-session commands a home. If
    the profile also ships its own ``settings.json`` template, that overlay supersedes this."""
    guarded = [{"type": "command", "command": _guarded(c)} for c in session_start if c.strip()]
    if not guarded:
        return
    settings = {"hooks": {"SessionStart": [{"hooks": guarded}]}}
    sc.write(".claude/settings.json", json.dumps(settings, indent=2) + "\n")


def _session_list_command(config: WizardConfig) -> str:
    """Command the SessionStart hook runs to inject the live command surface.

    Guards on the runner being installed so a missing tool prints a hint, not an error.
    """
    if config.runner == "task":
        return (
            "command -v task >/dev/null 2>&1 && task --list || { "
            "echo 'task not found (install go-task: https://taskfile.dev) "
            "- targets from the Taskfile:'; "
            f"{_TASKFILE_LIST_SED}; }}"
        )
    if config.existing_runner:  # unknown Makefile — grep targets (no make binary needed)
        return _MAKE_LIST_GREP
    # our generated Makefile is self-documenting via a `help` target
    return "command -v make >/dev/null 2>&1 && make help || echo 'make not found on PATH'"


# PostToolUse helper: format the file the agent just edited, so an edit never reaches
# the format gate unformatted. Lives in tools/checks/ so the docs machinery's guards
# (the scoped ruff hook and the unittest pre-push/CI runner, where hooks/CI are on)
# cover it — which is why it ships only with include_docs (see generate()). Kept
# <=88 cols / default-ruff-format stable like the other shipped helpers.
FORMAT_ON_EDIT = '''"""Auto-format a just-edited file (a Claude Code PostToolUse hook helper).

Reads the hook event JSON from stdin, pulls the edited file's path, and runs
the project's formatter for that file type, so an agent's edit never reaches
the format gate unformatted. Best-effort by design: any miss (no formatter on
PATH, unknown extension, missing file, bad JSON) exits 0 silently — pre-commit
remains the enforcer; this hook only saves the round-trip.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

# file extension -> formatter argv (the file's path is appended)
FORMATTERS: dict[str, list[str]] = {
{% for ext, cmd in formatters %}    "{{ ext }}": {{ cmd | tojson }},
{% endfor %}}


def format_command(path_str: str) -> list[str] | None:
    """The formatter invocation for ``path_str``, or None when nothing applies."""
    path = Path(path_str)
    cmd = FORMATTERS.get(path.suffix)
    if not cmd or not path.is_file() or shutil.which(cmd[0]) is None:
        return None
    return [*cmd, path_str]


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(event, dict):
        return 0
    tool_input = event.get("tool_input") or {}
    cmd = format_command(str(tool_input.get("file_path") or ""))
    if cmd:
        subprocess.run(cmd, capture_output=True, check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

TEST_FORMAT_ON_EDIT = '''"""Tests for the format-on-edit hook helper (stdlib unittest)."""

import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_HELPER = Path(__file__).resolve().parent / "format_on_edit.py"
_spec = importlib.util.spec_from_file_location("format_on_edit", _HELPER)
assert _spec and _spec.loader
format_on_edit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(format_on_edit)

EXT, CMD = sorted(format_on_edit.FORMATTERS.items())[0]


class FormatCommand(unittest.TestCase):
    def test_known_extension_gets_formatter_plus_path(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=EXT) as f:
            with mock.patch.object(format_on_edit.shutil, "which", lambda _: "/bin/x"):
                cmd = format_on_edit.format_command(f.name)
        self.assertEqual(cmd, [*CMD, f.name])

    def test_unknown_extension_is_skipped(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".nope") as f:
            self.assertIsNone(format_on_edit.format_command(f.name))

    def test_missing_file_is_skipped(self) -> None:
        self.assertIsNone(format_on_edit.format_command("no/such/file" + EXT))

    def test_missing_formatter_binary_is_skipped(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=EXT) as f:
            with mock.patch.object(format_on_edit.shutil, "which", lambda _: None):
                self.assertIsNone(format_on_edit.format_command(f.name))


class Main(unittest.TestCase):
    def test_bad_json_on_stdin_still_exits_zero(self) -> None:
        with mock.patch.object(format_on_edit.sys, "stdin", io.StringIO("{nope")):
            self.assertEqual(format_on_edit.main(), 0)

    def test_event_without_file_path_exits_zero(self) -> None:
        with mock.patch.object(format_on_edit.sys, "stdin", io.StringIO("{}")):
            self.assertEqual(format_on_edit.main(), 0)


if __name__ == "__main__":
    unittest.main()
'''

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
4. Goal-driven — is the change verified by a test that *proves* it? Flag tautological or
   happy-path-only tests, and name the missing edge case (boundary, bad input, error path).
5. Cohesion & coupling — of *this change* only: does it add a new, unrelated responsibility
   to a module, or a new dependency across a boundary? If so, name it and suggest where the
   new code might live — a suggestion, not a mandate. Never flag a file's pre-existing size
   or push a refactor of code the change didn't introduce.
{% if include_docs %}
6. Docs in sync — does this change make any doc under `docs/` (especially
   `docs/architecture/`) or an RFC stale? If so, flag the specific file.
{% endif %}
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

RFC_REVIEWER = """\
---
name: rfc-reviewer
description: Reviews an RFC draft for decision quality before it's accepted. Use on a new or changed RFC.
tools: Read, Grep, Glob
---

You review RFCs for this project — the *decision*, not the code. Read the RFC (and
any it supersedes) and judge it against:

1. Problem stated — is the Context a real problem with its constraints, not an
   assumed solution? Flag a Context that just restates the Decision.
2. Simplest viable option — does the Decision pick the minimum that solves the
   problem, with an honest "why it wins"? Flag speculative scope or gold-plating.
3. Alternatives genuinely weighed — are the rejected options real and fairly
   described, not strawmen? Name an obvious missing one (including "do nothing").
4. Honest consequences — do they state the costs, what gets harder, and what's
   given up — not only the upside? Flag a section that only sells.
5. Reversibility — is the "hard to reverse" framing accurate? A cheap-to-reverse
   change may not need an RFC at all; a one-way door must say so.
6. No conflict — does it contradict or silently overlap an existing active,
   superseded, or retired RFC? If it supersedes one, does it say so?

Report findings ordered by severity, citing the section. Prefer a few
high-confidence issues over a long list, and scale to the RFC — a one-line decision
gets one-line scrutiny. If it's sound, say so plainly; don't manufacture objections.
"""

RFC_COMMAND = """\
---
description: Scaffold a new RFC in docs/rfc/proposed/
---

Create a new RFC for: $ARGUMENTS

1. Pick a short kebab-case slug and today's date.
2. Copy `docs/rfc/TEMPLATE.md` to `docs/rfc/proposed/<YYYY-MM-DD>-<slug>.md`.
3. Fill in Context, Decision, and Consequences. Leave status as `Proposed`.
4. Run the `rfc-reviewer` subagent on the draft and resolve its findings.
5. Show me the reviewed draft before considering it done.
"""

REVIEW_COMMAND = """\
---
description: Review the current changes with the code-reviewer subagent
---

Run the `code-reviewer` subagent on the current uncommitted changes and
summarize its findings. Focus on correctness and the four execution principles.
"""

UPDATE_COMMAND = """\
---
description: Update this project's agent-native setup to the latest release
---

Refresh the scaffolding this project was generated from, then reconcile anything
that needs judgment. The engine is non-destructive — it never overwrites files
you've edited; it reports them for you to fold in.

1. Make sure the tree is clean (`git status`); commit or stash first — `update`
   refuses a dirty tree so its diff is unambiguously its own (and `git restore .`
   is the undo).
2. Upgrade the tool so it has the new templates:
   `uv tool upgrade agent-native-setup` (or `pipx upgrade agent-native-setup`).
3. Preview: `agent-native-setup update --dry-run`. It prints what it would
   refresh/add/remove, any conflicts, and — for a **breaking (major) update** —
   the migration steps.
4. If it's a breaking update, summarize the changes and migration steps for me and
   **get my confirmation** before proceeding. Apply with
   `agent-native-setup update --yes`; otherwise just `agent-native-setup update`.
5. If it wrote `UPDATING.md`, work through it: do the **migration steps in order**
   (they transform files you own — e.g. splitting the contract — and must preserve
   my edits), then reconcile each conflict (fold the new version into my edited
   file). Delete `UPDATING.md` when everything's done.
6. Show me `git diff` for review. Don't commit or push without me.
"""

ONBOARD_COMMAND = """\
---
description: Walk through first-run setup (ONBOARDING.md), then delete it
---

Read `ONBOARDING.md` at the repo root and work through its steps. Per its note on
working concurrently: kick the slow one-time installs off in the background up
front, and fan out genuinely independent work to subagents (e.g. drafting the
architecture doc while wiring an uncovered language) — but keep the
baseline → commit → push → CI chain serial, and keep a single mutually-dependent
change (like one language's lint/format/CI wiring) with one author so it can't
drift. Stop to confirm with me on anything needing a human decision (adding
secrets, repo-wide reformatting). When every step passes, delete `ONBOARDING.md`.
"""


def _file_formatters(config: WizardConfig) -> list[tuple[str, list[str]]]:
    """(extension, formatter argv) pairs for the selected languages, sorted."""
    pairs = [
        (ext, lang.format_file_cmd)
        for lang in get(config.languages)
        if lang.format_file_cmd
        for ext in lang.detect_exts
    ]
    return sorted(pairs)


def _permission_allow(config: WizardConfig) -> list[str]:
    """Pre-approve what the contract itself tells the agent to run.

    Only the runner the wizard authored is blanket-approved — its targets are known
    benign (lint/format/test/...). A pre-existing runner's targets are unknown
    (`make deploy`? `task release`?), so those still prompt. `pre-commit` includes
    `uninstall`/`autoupdate`; accepted — any effect lands in the reviewable diff.
    """
    rules = []
    if config.include_quality and not config.existing_runner:
        rules.append(f"Bash({config.runner}:*)")  # the command surface we generated
    if config.include_quality and config.git_hooks:
        rules.append("Bash(pre-commit:*)")
    rules += ["Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)"]
    return rules


def generate(config: WizardConfig, sc: Scaffolder, session_start: tuple[str, ...] = ()) -> None:
    if "claude" not in config.ai_tools:
        return
    sc.write(".claude/README.md", AGENTS_README)
    sc.render_write(
        ".claude/agents/code-reviewer.md", CODE_REVIEWER, include_docs=config.include_docs
    )
    sc.write(".claude/agents/planner.md", PLANNER)
    sc.write(".claude/commands/review.md", REVIEW_COMMAND)
    sc.write(".claude/commands/update-agent-scaffolding.md", UPDATE_COMMAND)
    if config.include_docs:
        sc.write(".claude/agents/rfc-reviewer.md", RFC_REVIEWER)
        sc.write(".claude/commands/rfc.md", RFC_COMMAND)
    # Matches when generators/onboarding.py writes ONBOARDING.md, so the command
    # never points at a file that wasn't scaffolded.
    if config.include_quality or config.include_ci:
        sc.write(
            ".claude/commands/onboard.md", ONBOARD_COMMAND, transient=True
        )  # removed post-onboarding

    # Format-on-edit needs a formatter-capable language, the quality tooling it feeds,
    # and docs — the docs machinery's guards (scoped ruff + the unittest runner) are
    # what keep the shipped helper linted and tested.
    formatters = _file_formatters(config)
    format_hook = bool(formatters) and config.include_quality and config.include_docs
    if format_hook:
        sc.render_write("tools/checks/format_on_edit.py", FORMAT_ON_EDIT, formatters=formatters)
        sc.write("tools/checks/test_format_on_edit.py", TEST_FORMAT_ON_EDIT)

    settings: dict[str, object] = {"permissions": {"allow": _permission_allow(config)}}
    hooks: dict[str, object] = {}
    # SessionStart hooks: inject the live command surface, and nudge if the scaffolding is
    # behind a newer release. The update check is tolerant — silent if the tool isn't on
    # PATH or the check errors — so it never disrupts a session.
    session_hooks: list[dict[str, str]] = []
    if config.include_quality or config.existing_runner:
        session_hooks.append({"type": "command", "command": _session_list_command(config)})
    session_hooks.append({"type": "command", "command": UPDATE_CHECK_COMMAND})
    # Profile-contributed startup commands run every session, after the built-in ones. Guarded
    # so a failing profile command can't disrupt the session (the base hooks are tolerant too).
    session_hooks += [
        {"type": "command", "command": _guarded(cmd)} for cmd in session_start if cmd.strip()
    ]
    hooks["SessionStart"] = [{"hooks": session_hooks}]
    if format_hook:
        hooks["PostToolUse"] = [
            {
                "matcher": "Edit|Write",
                "hooks": [{"type": "command", "command": "python tools/checks/format_on_edit.py"}],
            }
        ]
    if hooks:
        settings["hooks"] = hooks
    sc.write(".claude/settings.json", json.dumps(settings, indent=2) + "\n")
