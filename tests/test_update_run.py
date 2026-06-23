"""End-to-end `update` orchestration: scaffold an 'older version' into a clean git repo,
simulate drift, run the update, and assert each file lands in the right state.

Regeneration uses the current code, so 'older version' drift is faked by editing on-disk
files and the manifest fingerprints the updater compares against.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from agent_native_setup import cli, manifest, migrations, update
from agent_native_setup.config import WizardConfig
from agent_native_setup.manifest import MANIFEST_PATH
from agent_native_setup.migrations import Migration
from agent_native_setup.scaffold import Scaffolder


class _Console:
    """Collects printed output so tests can assert on it without rich rendering."""

    def __init__(self) -> None:
        self.text = ""

    def print(self, *args: object, **_kw: object) -> None:
        self.text += " ".join(str(a) for a in args) + "\n"


def _sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _git(target: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-C",
            str(target),
            "-c",
            "user.email=t@e",
            "-c",
            "user.name=t",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        check=True,
        capture_output=True,
    )


def _scaffold(target: Path) -> dict:
    config = WizardConfig(
        project_name="demo", output_dir=target, languages=["python"], init_git=False
    )
    cli.build(config, Scaffolder(target))
    return json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))


def _commit_clean_baseline(target: Path) -> None:
    _git(target, "init", "-q")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "baseline", "--no-verify")


def test_update_refreshes_conflicts_recreates_removes_and_respects_seed(tmp_path: Path) -> None:
    target = tmp_path / "proj"
    target.mkdir()
    manifest = _scaffold(target)

    refreshed = ".claude/agents/code-reviewer.md"  # managed, pristine-but-stale → refresh
    conflicted = "tools/checks/sync_rfc_status.py"  # managed, user-edited → conflict
    recreated = ".editorconfig"  # managed, deleted by user → recreate
    orphan = "tools/checks/legacy_helper.py"  # managed, no longer generated → remove
    seed = "AGENTS.md"  # user-owned contract → never touched

    real_reviewer = (target / refreshed).read_text(encoding="utf-8")

    # Drift the tree to look like an older scaffold, and the manifest to match it.
    (target / refreshed).write_text("STALE\n", encoding="utf-8")
    manifest["files"][refreshed] = _sha("STALE\n")  # still "pristine since scaffold"
    (target / conflicted).write_text("# my own edits\n", encoding="utf-8")  # fp left as-is
    (target / recreated).unlink()
    (target / orphan).write_text("legacy\n", encoding="utf-8")
    manifest["files"][orphan] = _sha("legacy\n")  # pristine orphan
    (target / seed).write_text("# my own contract\n", encoding="utf-8")
    manifest["version"] = "0.0.1"
    (target / MANIFEST_PATH).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    _commit_clean_baseline(target)

    console = _Console()
    # 0.0.1 → tool version crosses a breaking boundary; confirm it so we test the content engine.
    assert update.run(target, dry_run=False, console=console, assume_yes=True) == 0

    # Pristine-but-stale managed file refreshed back to the current template.
    assert (target / refreshed).read_text(encoding="utf-8") == real_reviewer
    # User-edited managed file left alone and surfaced as a conflict.
    assert (target / conflicted).read_text(encoding="utf-8") == "# my own edits\n"
    # Deleted managed file (a guardrail) restored.
    assert (target / recreated).exists()
    # Pristine orphan removed.
    assert not (target / orphan).exists()
    # Seed file (the contract) untouched, even though it diverged from the template.
    assert (target / seed).read_text(encoding="utf-8") == "# my own contract\n"

    report = (target / update.REPORT_PATH).read_text(encoding="utf-8")
    assert conflicted in report
    assert "0.0.1" in report  # from_version

    new_manifest = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    assert new_manifest["version"] != "0.0.1"  # stamped to the running version
    assert orphan not in new_manifest["files"]  # no longer generated → dropped from manifest


def test_update_does_not_duplicate_the_dated_bootstrap_rfc(tmp_path: Path) -> None:
    # Regression: the bootstrap RFC's filename carries the scaffold date. Regeneration uses
    # *today's* date, so its path differs from the one on disk — update must not create a
    # second copy under today's date.
    target = tmp_path / "proj"
    target.mkdir()
    manifest = _scaffold(target)

    rfc_dir = target / "docs/rfc/active"
    [boot] = list(rfc_dir.glob("*-adopt-agent-native-setup.md"))
    new_rel = "docs/rfc/active/" + boot.name
    old_rel = "docs/rfc/active/2026-01-01-adopt-agent-native-setup.md"
    # Re-date the on-disk RFC and the manifest entry as if scaffolded back in January.
    (target / old_rel).write_text(boot.read_text(encoding="utf-8"), encoding="utf-8")
    boot.unlink()
    manifest["files"][old_rel] = manifest["files"].pop(new_rel)
    manifest["seed"] = [old_rel if s == new_rel else s for s in manifest["seed"]]
    (target / MANIFEST_PATH).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    _commit_clean_baseline(target)

    assert update.run(target, dry_run=False, console=_Console()) == 0
    boots = sorted(p.name for p in rfc_dir.glob("*-adopt-agent-native-setup.md"))
    assert boots == ["2026-01-01-adopt-agent-native-setup.md"]  # exactly one, not duplicated


def test_update_never_treats_the_manifest_as_a_conflict_or_lists_itself(tmp_path: Path) -> None:
    # Regression: build() writes the manifest via sc.write, which adds it to `recorded`.
    # If not excluded, the updater flags `.agent-native-setup.json` as a conflict ("not from
    # this scaffold") and lists it in the rewritten manifest's own files.
    target = tmp_path / "proj"
    target.mkdir()
    _scaffold(target)
    _commit_clean_baseline(target)

    console = _Console()
    assert update.run(target, dry_run=False, console=console) == 0
    assert MANIFEST_PATH not in console.text  # not surfaced as a conflict

    new_manifest = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    assert MANIFEST_PATH not in new_manifest["files"]
    assert MANIFEST_PATH not in new_manifest["seed"]


def _set_version(target: Path, version: str) -> None:
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    m["version"] = version
    (target / MANIFEST_PATH).write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")


def test_breaking_update_without_confirmation_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 0.4 → 0.5 crosses a 0.x breaking boundary. Non-interactive + no --yes → refuse and
    # mutate nothing (the gate is checked before any migration or content write).
    monkeypatch.setattr(manifest, "__version__", "0.5.0")
    target = tmp_path / "proj"
    target.mkdir()
    _scaffold(target)
    _set_version(target, "0.4.0")
    stale = target / ".claude/agents/code-reviewer.md"
    stale.write_text("STALE\n", encoding="utf-8")
    _commit_clean_baseline(target)

    console = _Console()
    assert update.run(target, dry_run=False, console=console, assume_yes=False) == 2
    assert "needs confirmation" in console.text
    assert stale.read_text(encoding="utf-8") == "STALE\n"  # untouched
    assert not (target / update.REPORT_PATH).exists()


def test_breaking_update_with_yes_proceeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(manifest, "__version__", "0.5.0")
    target = tmp_path / "proj"
    target.mkdir()
    m = _scaffold(target)
    stale = ".claude/agents/code-reviewer.md"
    real = (target / stale).read_text(encoding="utf-8")
    (target / stale).write_text("STALE\n", encoding="utf-8")
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    m["version"] = "0.4.0"
    m["files"][stale] = _sha("STALE\n")
    (target / MANIFEST_PATH).write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")
    _commit_clean_baseline(target)

    assert update.run(target, dry_run=False, console=_Console(), assume_yes=True) == 0
    assert (target / stale).read_text(encoding="utf-8") == real  # refreshed once confirmed


def test_downgrade_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Installed tool older than the project's scaffolding → refuse before touching anything.
    monkeypatch.setattr(manifest, "__version__", "0.4.0")
    target = tmp_path / "proj"
    target.mkdir()
    _scaffold(target)
    _set_version(target, "0.6.0")
    console = _Console()
    assert update.run(target, dry_run=False, console=console, assume_yes=True) == 2
    assert "older than" in console.text


def test_breaking_boundary_with_no_steps_still_requires_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Crossing a breaking series with ZERO migration steps must still pause — a major is the
    # user's signal to look, even when the change is mechanically safe (RFC §3 edge case).
    monkeypatch.setattr(manifest, "__version__", "0.5.0")
    monkeypatch.setattr(migrations, "MIGRATIONS", [])  # no agent/manual steps in the span
    target = tmp_path / "proj"
    target.mkdir()
    _scaffold(target)
    _set_version(target, "0.4.0")
    stale = target / ".claude/agents/code-reviewer.md"
    stale.write_text("STALE\n", encoding="utf-8")
    _commit_clean_baseline(target)

    console = _Console()
    assert update.run(target, dry_run=False, console=console, assume_yes=False) == 2
    assert "needs confirmation" in console.text
    assert stale.read_text(encoding="utf-8") == "STALE\n"  # untouched


def test_check_is_silent_for_an_unknown_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A raw-checkout scaffold records 0.0.0; we can't meaningfully assess staleness, so the
    # nudge stays quiet rather than crying "breaking update" on every session.
    target = tmp_path / "proj"
    target.mkdir()
    _scaffold(target)
    _set_version(target, "0.0.0")
    _patch_latest(monkeypatch, "v0.5.0")
    console = _Console()
    update.check(target, console)
    assert console.text == ""


def test_check_never_raises_on_a_fetch_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The cache refresh can fail (offline, GitHub hiccup); from a SessionStart hook the check
    # must swallow it and return 0, never propagate.
    from agent_native_setup import update_check

    def boom(now: float) -> str:
        raise RuntimeError("network down")

    monkeypatch.setattr(update_check, "_latest_with_cache", boom)
    target = tmp_path / "proj"
    target.mkdir()
    _scaffold(target)
    _set_version(target, "0.1.0")
    console = _Console()
    assert update.check(target, console) == 0
    assert console.text == ""


def test_breaking_runbook_lists_ordered_agent_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(manifest, "__version__", "0.5.0")
    monkeypatch.setattr(
        migrations,
        "MIGRATIONS",
        [Migration("0.5.0", "agent", "split the contract", instructions="Move X into Y.")],
    )
    target = tmp_path / "proj"
    target.mkdir()
    _scaffold(target)
    _set_version(target, "0.4.0")
    _commit_clean_baseline(target)

    assert update.run(target, dry_run=False, console=_Console(), assume_yes=True) == 0
    report = (target / update.REPORT_PATH).read_text(encoding="utf-8")
    assert "## Migration steps" in report
    assert "### 0.5.0 — split the contract" in report
    assert "Move X into Y." in report


def _patch_latest(monkeypatch: pytest.MonkeyPatch, tag: str | None) -> None:
    from agent_native_setup import update_check

    monkeypatch.setattr(update_check, "_latest_with_cache", lambda now: tag)


def test_check_nudges_for_a_compatible_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "proj"
    target.mkdir()
    _scaffold(target)
    _set_version(target, "0.1.0")
    _patch_latest(monkeypatch, "v0.1.5")  # same 0.1 series, newer
    console = _Console()
    update.check(target, console)
    assert "compatible update" in console.text and "0.1.5" in console.text


def test_check_warns_for_a_breaking_update(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "proj"
    target.mkdir()
    _scaffold(target)
    _set_version(target, "0.4.0")
    _patch_latest(monkeypatch, "v0.5.0")  # 0.4 → 0.5 crosses a 0.x boundary
    console = _Console()
    update.check(target, console)
    assert "breaking" in console.text


def test_check_is_silent_when_current_or_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "proj"
    target.mkdir()
    _scaffold(target)
    _set_version(target, "0.5.0")
    _patch_latest(monkeypatch, "v0.5.0")  # same version → nothing to say
    console = _Console()
    update.check(target, console)
    assert console.text == ""
    _patch_latest(monkeypatch, None)  # offline / no release info → silent
    update.check(target, console)
    assert console.text == ""


def test_check_is_silent_without_a_manifest(tmp_path: Path) -> None:
    console = _Console()
    assert update.check(tmp_path, console) == 0
    assert console.text == ""


def test_update_performs_the_real_contract_split(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # End-to-end dogfood of the first real agent migration: a pre-split project (no
    # INSTRUCTION.md, recorded at 0.5.1) updated to 0.6.0 crosses the split boundary —
    # INSTRUCTION.md is created as a managed file, and the agent step lands in UPDATING.md.
    monkeypatch.setattr(manifest, "__version__", "0.6.0")
    target = tmp_path / "proj"
    target.mkdir()
    _scaffold(target)
    # Simulate a project scaffolded before the split: drop INSTRUCTION.md from disk + manifest.
    (target / "INSTRUCTION.md").unlink()
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    m["files"].pop("INSTRUCTION.md", None)
    m["seed"] = [s for s in m["seed"] if s != "INSTRUCTION.md"]
    m["version"] = "0.5.1"
    (target / MANIFEST_PATH).write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")
    _commit_clean_baseline(target)

    assert update.run(target, dry_run=False, console=_Console(), assume_yes=True) == 0
    # INSTRUCTION.md created as a managed file (missing → create).
    assert (
        (target / "INSTRUCTION.md").read_text(encoding="utf-8").startswith("# Engineering contract")
    )
    new_m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    assert "INSTRUCTION.md" in new_m["files"] and "INSTRUCTION.md" not in new_m["seed"]
    # The agent migration's reconciliation steps are in the runbook.
    report = (target / update.REPORT_PATH).read_text(encoding="utf-8")
    assert "### 0.6.0 — split AGENTS.md" in report
    assert "Reconcile your `AGENTS.md`" in report


def test_update_refuses_without_a_manifest(tmp_path: Path) -> None:
    console = _Console()
    rc = update.run(tmp_path, dry_run=False, console=console)
    assert rc == 2
    assert "No .agent-native-setup.json" in console.text


def test_update_refuses_a_dirty_or_nongit_tree(tmp_path: Path) -> None:
    target = tmp_path / "proj"
    target.mkdir()
    _scaffold(target)  # has a manifest, but no git repo
    console = _Console()
    rc = update.run(target, dry_run=False, console=console)
    assert rc == 2
    assert "git repo" in console.text


def test_update_refuses_a_scaffolded_subdir_of_another_repo(tmp_path: Path) -> None:
    # Regression (git-undo guarantee): a project scaffolded into a subdir of some parent
    # repo, with no .git of its own, must be refused — not silently updated against the
    # parent repo, whose `git diff`/`git checkout` would span unrelated files.
    _git(tmp_path, "init", "-q")  # parent repo at tmp_path
    sub = tmp_path / "packages" / "proj"
    sub.mkdir(parents=True)
    _scaffold(sub)
    console = _Console()
    assert update.run(sub, dry_run=False, console=console) == 2
    assert "git repo" in console.text


def test_dry_run_previews_migration_moves_without_performing_them(tmp_path: Path) -> None:
    # Regression: the moves are exactly what a cautious user runs --dry-run to preview.
    target = tmp_path / "proj"
    target.mkdir()
    _scaffold(target)
    legacy = target / "docs/rfc/current/2025-old-decision.md"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("an old RFC the user wrote under the previous layout\n", encoding="utf-8")

    console = _Console()
    assert update.run(target, dry_run=True, console=console) == 0
    assert "docs/rfc/current/2025-old-decision.md → docs/rfc/active/" in console.text
    assert legacy.exists()  # previewed, not actually moved
    assert not (target / "docs/rfc/active/2025-old-decision.md").exists()


def test_dry_run_writes_nothing_and_reports(tmp_path: Path) -> None:
    target = tmp_path / "proj"
    target.mkdir()
    manifest = _scaffold(target)
    stale = ".claude/agents/code-reviewer.md"
    (target / stale).write_text("STALE\n", encoding="utf-8")
    manifest["files"][stale] = _sha("STALE\n")
    (target / MANIFEST_PATH).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    # No git repo at all — dry-run must still work (it writes nothing).

    console = _Console()
    assert update.run(target, dry_run=True, console=console) == 0
    assert (target / stale).read_text(encoding="utf-8") == "STALE\n"  # unchanged
    assert not (target / update.REPORT_PATH).exists()  # no UPDATING.md written
    assert stale in console.text  # but the plan is reported
