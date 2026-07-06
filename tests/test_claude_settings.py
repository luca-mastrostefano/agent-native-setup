"""Generated .claude/settings.json: permission allowlist + the format-on-edit hook."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from agent_native_setup import cli
from agent_native_setup.config import WizardConfig
from agent_native_setup.scaffold import Scaffolder

READONLY_GIT = ["Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)"]


def _settings(tmp_path: Path, **overrides: object) -> dict:
    config = WizardConfig(project_name="demo", output_dir=tmp_path, init_git=False, **overrides)
    cli.build(config, Scaffolder(config.target))
    return json.loads((tmp_path / ".claude/settings.json").read_text(encoding="utf-8"))


# --- permission allowlist -------------------------------------------------------


def test_allowlist_preapproves_the_contracts_own_commands(tmp_path: Path) -> None:
    allow = _settings(tmp_path, languages=["python"])["permissions"]["allow"]
    assert "Bash(make:*)" in allow  # the default runner is the command surface
    assert "Bash(pre-commit:*)" in allow
    assert all(rule in allow for rule in READONLY_GIT)
    assert not any("git push" in r or "git commit" in r for r in allow)  # never write git


def test_allowlist_uses_the_chosen_runner(tmp_path: Path) -> None:
    allow = _settings(tmp_path, languages=["python"], runner="task")["permissions"]["allow"]
    assert "Bash(task:*)" in allow
    assert "Bash(make:*)" not in allow


def test_allowlist_without_quality_keeps_only_readonly_git(tmp_path: Path) -> None:
    allow = _settings(tmp_path, include_quality=False, include_ci=False)["permissions"]["allow"]
    assert allow == READONLY_GIT


def test_allowlist_never_preapproves_an_existing_unknown_runner(tmp_path: Path) -> None:
    # The wizard didn't author a pre-existing runner's targets (`make deploy`?
    # `task release`?) — those must keep prompting; only known-benign rules remain.
    config = {"languages": ["python"], "existing_runner": True}
    allow = _settings(tmp_path, **config)["permissions"]["allow"]
    assert "Bash(make:*)" not in allow and "Bash(task:*)" not in allow
    assert "Bash(pre-commit:*)" in allow  # the hooks are still ours


# --- SessionStart update check --------------------------------------------------


def _session_commands(settings: dict) -> list[str]:
    return [h["command"] for h in settings["hooks"]["SessionStart"][0]["hooks"]]


def test_session_start_nudges_about_updates(tmp_path: Path) -> None:
    cmds = _session_commands(_settings(tmp_path, languages=["python"]))
    assert any("update --check" in c for c in cmds)
    # Guarded: silent if the CLI isn't installed, never fails the session.
    check = next(c for c in cmds if "update --check" in c)
    assert "command -v agent-native-setup" in check and "|| true" in check


def test_update_check_hook_present_even_without_quality_tooling(tmp_path: Path) -> None:
    # The update nudge is useful for any scaffolded project, so it ships even when there's
    # no command surface to list.
    settings = _settings(tmp_path, languages=["python"], include_quality=False, include_ci=False)
    assert any("update --check" in c for c in _session_commands(settings))


def test_update_skill_is_scaffolded(tmp_path: Path) -> None:
    # The /update-agent-scaffolding slash command choreographs the whole flow: preview,
    # confirm a breaking update, then reconcile UPDATING.md.
    _settings(tmp_path, languages=["python"])
    cmd = (tmp_path / ".claude/commands/update-agent-scaffolding.md").read_text(encoding="utf-8")
    assert "agent-native-setup update" in cmd
    assert "--dry-run" in cmd and "--yes" in cmd  # preview, then confirm a breaking update
    assert "UPDATING.md" in cmd  # reconcile the runbook


# --- format-on-edit hook --------------------------------------------------------


def test_format_hook_wired_and_helper_shipped(tmp_path: Path) -> None:
    settings = _settings(tmp_path, languages=["python", "node"])
    post = settings["hooks"]["PostToolUse"]
    assert post[0]["matcher"] == "Edit|Write"
    assert post[0]["hooks"][0]["command"] == "python3 tools/checks/format_on_edit.py"
    body = (tmp_path / "tools/checks/format_on_edit.py").read_text(encoding="utf-8")
    assert '".py": ["ruff", "format"]' in body
    assert '".ts": ["npx", "prettier", "--write"]' in body
    assert (tmp_path / "tools/checks/test_format_on_edit.py").exists()


def test_format_hook_formats_an_edited_file_end_to_end(tmp_path: Path) -> None:
    # Feed the shipped helper a real PostToolUse-style event and watch it format.
    _settings(tmp_path, languages=["python"])
    messy = tmp_path / "src" / "app.py"
    messy.parent.mkdir(parents=True)
    messy.write_text("x=1\n")
    event = json.dumps({"tool_input": {"file_path": str(messy)}})
    subprocess.run(
        [sys.executable, "tools/checks/format_on_edit.py"],
        cwd=tmp_path,
        input=event,
        text=True,
        check=True,
        capture_output=True,
    )
    assert messy.read_text() == "x = 1\n"


def test_no_format_hook_without_a_formatter_language(tmp_path: Path) -> None:
    settings = _settings(tmp_path, languages=["html"])  # html ships no formatter
    assert "PostToolUse" not in settings.get("hooks", {})
    assert not (tmp_path / "tools/checks/format_on_edit.py").exists()


def test_no_format_hook_without_docs(tmp_path: Path) -> None:
    # The docs machinery's guards (scoped ruff + the unittest runner) are what keep
    # the shipped helper linted and tested; without docs it must not ship unguarded.
    settings = _settings(tmp_path, languages=["python"], include_docs=False)
    assert "PostToolUse" not in settings.get("hooks", {})
    assert not (tmp_path / "tools/checks/format_on_edit.py").exists()
