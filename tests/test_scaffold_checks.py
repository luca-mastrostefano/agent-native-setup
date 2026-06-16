"""The wizard scaffolds the RFC/docs commit-msg gates — for Python projects only."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from agent_native_setup import cli
from agent_native_setup.config import WizardConfig
from agent_native_setup.generators import agents, docs
from agent_native_setup.scaffold import Scaffolder, render

REPO_ROOT = Path(__file__).resolve().parents[1]


def _build(tmp_path: Path, **overrides: object) -> Path:
    config = WizardConfig(project_name="demo", output_dir=tmp_path, init_git=False, **overrides)
    cli.build(config, Scaffolder(config.target))
    return tmp_path


def test_python_project_scaffolds_commit_msg_gates(tmp_path: Path) -> None:
    root = _build(tmp_path, languages=["python"])
    assert (root / "tools/checks/rfc_needed.py").exists()
    assert (root / "tools/checks/docs_sync.py").exists()
    assert (root / "tools/checks/tests_needed.py").exists()
    cfg = (root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "commit-msg" in cfg.splitlines()[0]  # in default_install_hook_types
    assert "id: rfc-needed" in cfg
    assert "id: docs-sync" in cfg
    assert "id: tests-needed" in cfg


def test_manifest_language_ships_rfc_gate_but_not_layout_gates(tmp_path: Path) -> None:
    # go has a dependency manifest (go.mod), so the RFC gate ships; the src/+tests/
    # layout gates (docs-sync, tests-needed) stay Python-only.
    root = _build(tmp_path, languages=["go"])
    assert (root / "tools/checks/rfc_needed.py").exists()
    assert not (root / "tools/checks/docs_sync.py").exists()
    assert not (root / "tools/checks/tests_needed.py").exists()
    cfg = (root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "commit-msg" in cfg.splitlines()[0]
    assert "id: rfc-needed" in cfg
    assert "docs-sync" not in cfg and "tests-needed" not in cfg


def test_no_manifest_language_omits_commit_msg_gates(tmp_path: Path) -> None:
    # html declares no dependency manifest, so no commit-msg gate ships at all.
    root = _build(tmp_path, languages=["html"])
    assert not (root / "tools/checks/rfc_needed.py").exists()
    cfg = (root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "commit-msg" not in cfg


def test_no_docs_omits_commit_msg_gates(tmp_path: Path) -> None:
    root = _build(tmp_path, languages=["python"], include_docs=False)
    assert not (root / "tools/checks/rfc_needed.py").exists()
    cfg = (root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "commit-msg" not in cfg


def test_code_reviewer_has_docs_check_with_docs(tmp_path: Path) -> None:
    root = _build(tmp_path, languages=["python"])
    assert "Docs in sync" in (root / ".claude/agents/code-reviewer.md").read_text(encoding="utf-8")


def test_code_reviewer_checks_test_quality(tmp_path: Path) -> None:
    # The goal-driven lens checks test quality, not just presence.
    body = (_build(tmp_path, languages=["python"]) / ".claude/agents/code-reviewer.md").read_text(
        encoding="utf-8"
    )
    assert "happy-path-only" in body
    assert "missing edge case" in body


def test_code_reviewer_cohesion_lens_is_delta_scoped(tmp_path: Path) -> None:
    # Cohesion/coupling lens, but only on the change — it must never nag about legacy size.
    body = (_build(tmp_path, languages=["python"]) / ".claude/agents/code-reviewer.md").read_text(
        encoding="utf-8"
    )
    assert "Cohesion & coupling" in body
    assert "of *this change* only" in body
    assert "pre-existing size" in body  # legacy is explicitly grandfathered


def test_code_reviewer_omits_docs_check_without_docs(tmp_path: Path) -> None:
    root = _build(tmp_path, languages=["python"], include_docs=False)
    body = (root / ".claude/agents/code-reviewer.md").read_text(encoding="utf-8")
    assert "Docs in sync" not in body
    assert "4. Goal-driven" in body  # the other checks survive


def test_rfc_reviewer_ships_with_docs_and_is_wired_into_the_rfc_command(tmp_path: Path) -> None:
    # The RFC review pass: an agent judging decision quality, invoked by /rfc before
    # the draft is shown. Ships with docs (RFCs only exist then).
    root = _build(tmp_path, languages=["python"])
    agent = (root / ".claude/agents/rfc-reviewer.md").read_text(encoding="utf-8")
    assert "name: rfc-reviewer" in agent
    assert "Simplest viable option" in agent  # the decision-quality lens, not code
    rfc_cmd = (root / ".claude/commands/rfc.md").read_text(encoding="utf-8")
    assert "rfc-reviewer" in rfc_cmd  # the /rfc flow runs the review before showing


def test_rfc_reviewer_omitted_without_docs(tmp_path: Path) -> None:
    # No docs -> no RFCs -> neither the agent nor the /rfc command ships.
    root = _build(tmp_path, languages=["python"], include_docs=False)
    assert not (root / ".claude/agents/rfc-reviewer.md").exists()
    assert not (root / ".claude/commands/rfc.md").exists()


def test_contract_points_at_rfc_reviewer_with_agents_and_docs(tmp_path: Path) -> None:
    # The "When to write an RFC" section names the agent (gated on agents, like the
    # code-reviewer line); a no-agents project states the rule without the agent.
    with_agents = (_build(tmp_path / "a", languages=["python"]) / "AGENTS.md").read_text(
        encoding="utf-8"
    )
    assert "When to write an RFC" in with_agents
    assert "rfc-reviewer" in with_agents
    no_agents = (
        _build(tmp_path / "n", languages=["python"], include_agents=False) / "AGENTS.md"
    ).read_text(encoding="utf-8")
    assert "When to write an RFC" in no_agents  # the rule still stands
    assert "rfc-reviewer" not in no_agents  # but no agent to point at


def test_non_python_project_guards_shipped_python_with_ruff(tmp_path: Path) -> None:
    # docs ship tools/checks/*.py even for a node project; guard them with ruff at all
    # three layers (pre-commit, command surface, CI) so they don't ship unlinted.
    root = _build(tmp_path, languages=["node"])
    pc = (root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    mk = (root / "Makefile").read_text(encoding="utf-8")
    wf = (root / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    assert "ruff-check" in pc and "^tools/.*\\.py$" in pc  # scoped pre-commit hook
    assert "ruff check tools/" in mk and "ruff format --check tools/" in mk  # local gate
    assert "ruff check tools/" in wf  # CI matches local
    gi = (root / ".gitignore").read_text(encoding="utf-8")
    assert "__pycache__/" in gi  # unittest drops bytecode under tools/checks/
    assert ".ruff_cache/" in gi  # the tools/ ruff hook drops a cache at the repo root


def test_python_project_does_not_double_guard(tmp_path: Path) -> None:
    # When Python IS selected its own ruff covers tools/; don't add the scoped guard.
    mk = (_build(tmp_path, languages=["python"]) / "Makefile").read_text(encoding="utf-8")
    assert "ruff check ." in mk
    assert "ruff check tools/" not in mk


def test_architecture_overview_preseeds_tooling(tmp_path: Path) -> None:
    # The wizard knows the components it built; seed them instead of a bare TODO.
    body = (_build(tmp_path, languages=["node"]) / "docs/architecture/overview.md").read_text(
        encoding="utf-8"
    )
    assert "Tooling & process" in body
    assert "`AGENTS.md`" in body and "`tools/checks/`" in body
    assert "CI" in body  # ci is on by default
    assert "TODO" in body  # product components still left to the team


def test_ruff_precommit_uses_current_id(tmp_path: Path) -> None:
    # ruff-pre-commit renamed `ruff` -> `ruff-check`; `ruff` is a legacy alias.
    pc = (_build(tmp_path, languages=["python"]) / ".pre-commit-config.yaml").read_text(
        encoding="utf-8"
    )
    assert "id: ruff-check" in pc
    assert "id: ruff\n" not in pc  # no bare legacy alias


def test_embedded_scripts_match_repo_files() -> None:
    """The wizard ships exactly the scripts this repo dogfoods and tests."""
    assert docs.RFC_NEEDED == (REPO_ROOT / "tools/checks/rfc_needed.py").read_text(encoding="utf-8")
    assert docs.DOCS_SYNC == (REPO_ROOT / "tools/checks/docs_sync.py").read_text(encoding="utf-8")
    assert docs.TESTS_NEEDED == (REPO_ROOT / "tools/checks/tests_needed.py").read_text(
        encoding="utf-8"
    )
    rendered = render(agents.FORMAT_ON_EDIT, formatters=[(".py", ["ruff", "format"])])
    assert rendered == (REPO_ROOT / "tools/checks/format_on_edit.py").read_text(encoding="utf-8")
    # sync_rfc_status's test is dogfooded byte-for-byte (this repo runs it via discover).
    # The commit-gate helper tests (rfc_needed/docs_sync/tests_needed) aren't kept
    # in-repo — they'd share a basename with this repo's existing tests/ suites — so
    # they're verified end-to-end by test_shipped_tests_pass_against_shipped_helpers.
    assert docs.TEST_SYNC_RFC_STATUS == (
        REPO_ROOT / "tools/checks/test_sync_rfc_status.py"
    ).read_text(encoding="utf-8")
    assert agents.TEST_FORMAT_ON_EDIT == (
        REPO_ROOT / "tools/checks/test_format_on_edit.py"
    ).read_text(encoding="utf-8")


def test_ships_tests_for_the_helpers_it_ships(tmp_path: Path) -> None:
    # node project: sync_rfc_status, the RFC gate (package.json manifest), and the
    # format-on-edit helper ship — with their tests; the layout gates don't.
    node = _build(tmp_path / "node", languages=["node"])
    assert (node / "tools/checks/test_sync_rfc_status.py").exists()
    assert (node / "tools/checks/test_rfc_needed.py").exists()
    assert (node / "tools/checks/test_format_on_edit.py").exists()
    assert not (node / "tools/checks/test_docs_sync.py").exists()
    assert not (node / "tools/checks/test_tests_needed.py").exists()
    # Python project: the layout gates ship too, so do their tests.
    py = _build(tmp_path / "py", languages=["python"])
    assert (py / "tools/checks/test_sync_rfc_status.py").exists()
    assert (py / "tools/checks/test_rfc_needed.py").exists()
    assert (py / "tools/checks/test_docs_sync.py").exists()
    assert (py / "tools/checks/test_tests_needed.py").exists()


def test_no_docs_omits_the_helper_tests(tmp_path: Path) -> None:
    root = _build(tmp_path, languages=["python"], include_docs=False)
    assert not (root / "tools/checks/test_sync_rfc_status.py").exists()


def test_tools_tests_runner_wired_at_all_three_layers(tmp_path: Path) -> None:
    # Even a non-Python project gets the runner — it needs only `python`, not pytest.
    root = _build(tmp_path, languages=["node"])
    runner = "python -m unittest discover -s tools/checks"
    assert runner in (root / "Makefile").read_text(encoding="utf-8")  # command surface
    pc = (root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "id: tools-checks-tests" in pc and runner in pc  # pre-push hook
    wf = (root / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    assert runner in wf  # CI


def test_pre_push_test_hooks_scrub_git_env(tmp_path: Path) -> None:
    # git exports GIT_DIR into every hook; a test that `git init`s a temp dir would otherwise
    # operate on the real repo. The pre-push *test* hooks scrub it; the git-aware rfc-status
    # hook (which should see the real repo) does not.
    pc = (_build(tmp_path, languages=["python"]) / ".pre-commit-config.yaml").read_text(
        encoding="utf-8"
    )
    scrub = "env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE "
    assert f"entry: {scrub}pytest" in pc  # python test hook
    assert f"entry: {scrub}python -m unittest discover -s tools/checks" in pc  # tools tests
    assert "entry: python tools/checks/sync_rfc_status.py" in pc  # git-aware hook NOT scrubbed


def test_tools_tests_runner_omitted_without_docs(tmp_path: Path) -> None:
    root = _build(tmp_path, languages=["node"], include_docs=False)
    runner = "python -m unittest discover -s tools/checks"
    assert runner not in (root / "Makefile").read_text(encoding="utf-8")
    assert runner not in (root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert runner not in (root / ".github/workflows/quality.yml").read_text(encoding="utf-8")


def test_shipped_tests_pass_against_shipped_helpers(tmp_path: Path) -> None:
    # End to end: the scaffolded tests must pass against the scaffolded helpers, run the
    # way a generated project runs them (python -m unittest discover, no pytest).
    for langs in (["node"], ["python"]):
        root = _build(tmp_path / langs[0], languages=langs)
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tools/checks"],
            cwd=root,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"{langs}: {result.stderr}"


def test_sync_rfc_status_stays_under_default_line_length(tmp_path: Path) -> None:
    # sync_rfc_status.py ships even for non-Python projects, where no line-length=100
    # config is present — keep it <=88 cols so a default ruff/flake8 won't flag it.
    root = _build(tmp_path, languages=["node"])  # node project: no Python tooling shipped
    body = (root / "tools/checks/sync_rfc_status.py").read_text(encoding="utf-8")
    too_long = [line for line in body.splitlines() if len(line) > 88]
    assert not too_long, f"lines over 88 cols: {too_long}"
