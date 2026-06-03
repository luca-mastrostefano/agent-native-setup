"""Runner detection, the Make-by-default generated runner, and the SessionStart hook."""

from __future__ import annotations

import json
from pathlib import Path

from ai_setup import cli
from ai_setup.config import WizardConfig
from ai_setup.languages import detect_runner
from ai_setup.scaffold import Scaffolder


def _build(tmp_path: Path, **overrides: object) -> Path:
    config = WizardConfig(project_name="demo", output_dir=tmp_path, init_git=False, **overrides)
    cli.build(config, Scaffolder(config.target))
    return tmp_path


def _hook_cmd(root: Path) -> str:
    settings = json.loads((root / ".claude/settings.json").read_text(encoding="utf-8"))
    return settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]


# --- detection ----------------------------------------------------------------


def test_detect_runner_taskfile(tmp_path: Path) -> None:
    (tmp_path / "Taskfile.yml").write_text("version: '3'\n")
    assert detect_runner(tmp_path) == ("task", True)


def test_detect_runner_makefile(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text("lint:\n\truff check .\n")
    assert detect_runner(tmp_path) == ("make", True)


def test_detect_runner_none_defaults_make(tmp_path: Path) -> None:
    assert detect_runner(tmp_path) == ("make", False)


# --- fresh project: Make by default -------------------------------------------


def test_fresh_generates_self_documenting_makefile(tmp_path: Path) -> None:
    root = _build(tmp_path, languages=["python"])  # runner defaults to "make"
    assert not (root / "Taskfile.yml").exists()
    mk = (root / "Makefile").read_text(encoding="utf-8")
    assert "help: ## Show available targets" in mk
    assert "lint: ## run linters" in mk
    assert "ruff check ." in mk
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert "make lint" in agents
    assert "Run `make help`" in agents
    assert "capture it as a `make` target" in agents


def test_cli_default_is_make(tmp_path: Path) -> None:
    cli.main(["demo", "-o", str(tmp_path), "--languages", "python", "--yes", "--no-git"])
    assert (tmp_path / "Makefile").exists()
    assert not (tmp_path / "Taskfile.yml").exists()


def test_quality_gate_runs_format_in_check_mode(tmp_path: Path) -> None:
    # The gate must include a read-only format check so `quality` mirrors CI without
    # the gate rewriting files. Holds for both runners.
    mk = (_build(tmp_path / "m", languages=["python"]) / "Makefile").read_text(encoding="utf-8")
    assert "quality: lint format-check" in mk
    assert "format-check: ## check formatting (read-only)\n\truff format --check ." in mk
    tf = (_build(tmp_path / "t", languages=["python"], runner="task") / "Taskfile.yml").read_text(
        encoding="utf-8"
    )
    assert "format-check" in tf and "deps: [lint, format-check" in tf


# --- --runner task opt-in -----------------------------------------------------


def test_runner_task_optin_generates_taskfile(tmp_path: Path) -> None:
    root = _build(tmp_path, languages=["python"], runner="task")
    assert (root / "Taskfile.yml").exists()
    assert not (root / "Makefile").exists()
    assert "task lint" in (root / "AGENTS.md").read_text(encoding="utf-8")


def test_cli_runner_flag_task(tmp_path: Path) -> None:
    args = ["demo", "-o", str(tmp_path), "--languages", "python", "--yes", "--no-git"]
    cli.main([*args, "--runner", "task"])
    assert (tmp_path / "Taskfile.yml").exists()
    assert not (tmp_path / "Makefile").exists()


# --- defer to an existing runner ----------------------------------------------


def test_existing_make_is_deferred_to(tmp_path: Path) -> None:
    root = _build(tmp_path, languages=["python"], runner="make", existing_runner=True)
    assert not (root / "Makefile").exists()  # we did not write our own
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert "already uses **Make**" in agents
    assert "ruff check ." in agents  # raw command, not `make lint`
    assert "capture it as a `make` target" in agents


def test_existing_taskfile_is_deferred_to(tmp_path: Path) -> None:
    (tmp_path / "Taskfile.yml").write_text("version: '3'\ntasks:\n  custom:\n    cmds: [echo hi]\n")
    cli.main(["demo", "-o", str(tmp_path), "--languages", "python", "--yes", "--no-git"])
    assert "custom" in (tmp_path / "Taskfile.yml").read_text(encoding="utf-8")  # untouched
    assert not (tmp_path / "Makefile").exists()  # no competing runner added
    assert "task --list" in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")


# --- SessionStart hook (runner-aware, guarded) --------------------------------


def test_hook_make_default_uses_make_help(tmp_path: Path) -> None:
    cmd = _hook_cmd(_build(tmp_path, languages=["python"]))
    assert "make help" in cmd
    assert "command -v make" in cmd  # guarded


def test_hook_task_uses_task_list(tmp_path: Path) -> None:
    cmd = _hook_cmd(_build(tmp_path, languages=["python"], runner="task"))
    assert "task --list" in cmd
    assert "command -v task" in cmd  # guarded


def test_hook_existing_make_greps_targets(tmp_path: Path) -> None:
    cmd = _hook_cmd(_build(tmp_path, languages=["python"], runner="make", existing_runner=True))
    assert "Makefile" in cmd and "## " in cmd
