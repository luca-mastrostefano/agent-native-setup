"""Secrets + dependency scanning and tests in the generated CI."""

from __future__ import annotations

from pathlib import Path

from agent_native_setup import cli
from agent_native_setup.config import WizardConfig
from agent_native_setup.scaffold import Scaffolder


def _build(tmp_path: Path, **overrides: object) -> Path:
    config = WizardConfig(project_name="demo", output_dir=tmp_path, init_git=False, **overrides)
    cli.build(config, Scaffolder(config.target))
    return tmp_path


def _wf(root: Path) -> str:
    return (root / ".github/workflows/quality.yml").read_text(encoding="utf-8")


def test_gitleaks_in_pre_commit(tmp_path: Path) -> None:
    _build(tmp_path, languages=["python"])
    assert "gitleaks" in (tmp_path / ".pre-commit-config.yaml").read_text(encoding="utf-8")


def test_checks_job_has_secrets_and_vuln_scan(tmp_path: Path) -> None:
    wf = _wf(_build(tmp_path, languages=["python"]))
    assert "checks:" in wf
    assert "gitleaks/gitleaks-action@v3" in wf  # v3 = node24 (v2 was deprecated node20)
    assert "pip-audit" in wf


def test_gitleaks_passes_github_token(tmp_path: Path) -> None:
    # gitleaks-action requires GITHUB_TOKEN to scan ANY pull_request; without it every
    # PR's checks job is red while main stays green. (Not Dependabot-specific.)
    wf = _wf(_build(tmp_path, languages=["python"]))
    assert "GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in wf
    assert "dependabot[bot]" not in wf  # the earlier actor-skip was the wrong fix


def test_checks_job_grants_gitleaks_pr_read_and_stays_readonly(tmp_path: Path) -> None:
    # gitleaks-action calls the PR API (list commits) on every pull_request, so the checks
    # job needs pull-requests:read or it 403s on the first PR. We keep CI read-only
    # (least-privilege) by disabling PR comments rather than granting pull-requests:write.
    wf = _wf(_build(tmp_path, languages=["python"]))
    assert "pull-requests: read" in wf
    assert 'GITLEAKS_ENABLE_COMMENTS: "false"' in wf
    assert "pull-requests: write" not in wf  # no CI write permission anywhere


def test_tests_run_in_greenfield_ci(tmp_path: Path) -> None:
    wf = _wf(_build(tmp_path, languages=["python"]))
    assert "pytest" in wf
    assert "pip install -e ." in wf


def test_checks_job_non_blocking_for_existing(tmp_path: Path) -> None:
    wf = _wf(_build(tmp_path, languages=["python"], existing_project=True))
    assert "checks:" in wf
    assert "continue-on-error: true" in wf  # the checks job doesn't block legacy


def test_go_security_uses_govulncheck_and_tests(tmp_path: Path) -> None:
    wf = _wf(_build(tmp_path, languages=["go"]))
    assert "golang/govulncheck-action" in wf
    assert "go test ./..." in wf


def test_no_security_drops_gitleaks_and_checks_job(tmp_path: Path) -> None:
    root = _build(tmp_path, languages=["python"], include_security=False)
    pc = (root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "gitleaks" not in pc
    wf = _wf(root)
    assert "checks:" not in wf
    assert "gitleaks" not in wf
    assert "pip-audit" not in wf
    assert "pytest" in wf  # the toggle is security-specific; tests still run


def test_no_security_flag_via_cli(tmp_path: Path) -> None:
    args = [
        "demo",
        "-o",
        str(tmp_path),
        "--languages",
        "python",
        "--yes",
        "--no-git",
        "--no-security",
    ]
    cli.main(args)
    wf = (tmp_path / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    assert "gitleaks" not in wf
    assert "checks:" not in wf
