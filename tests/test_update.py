"""Unit tests for the `update` engine core (classify / apply / render_report).

These drive the policy with synthetic manifests and on-disk files — no real generation —
so each classification branch is pinned independently of the generators.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from agent_native_setup.update import Conflict, Plan, apply, classify, fingerprint, render_report


def _sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _manifest(files: dict[str, str], seed: list[str] | None = None) -> dict:
    return {"files": files, "seed": seed or []}


# --- classify: managed files ------------------------------------------------------------


def test_new_managed_file_is_created(tmp_path: Path) -> None:
    plan = classify(_manifest({}), {"a.txt": _sha("new")}, set(), tmp_path)
    assert plan.creates == ["a.txt"]
    assert plan.refreshes == plan.removes == [] and plan.conflicts == []


def test_pristine_managed_file_is_refreshed(tmp_path: Path) -> None:
    _write(tmp_path / "a.txt", "old")  # on disk still matches the old manifest
    old = _manifest({"a.txt": _sha("old")})
    plan = classify(old, {"a.txt": _sha("new")}, set(), tmp_path)
    assert plan.refreshes == ["a.txt"]
    assert plan.creates == [] and plan.conflicts == []


def test_already_current_file_is_a_noop(tmp_path: Path) -> None:
    _write(tmp_path / "a.txt", "same")
    old = _manifest({"a.txt": _sha("old")})
    plan = classify(old, {"a.txt": _sha("same")}, set(), tmp_path)
    assert plan.is_noop


def test_edited_managed_file_is_a_conflict(tmp_path: Path) -> None:
    _write(tmp_path / "a.txt", "user edited this")  # diverged from the old fingerprint
    old = _manifest({"a.txt": _sha("old")})
    plan = classify(old, {"a.txt": _sha("new")}, set(), tmp_path)
    assert plan.refreshes == []
    assert plan.conflicts == [Conflict("a.txt", "edited since scaffold")]


def test_file_present_but_not_from_this_scaffold_is_a_conflict(tmp_path: Path) -> None:
    # The new version introduces a path the user already happens to have — no baseline to
    # prove it's ours, so we never clobber it.
    _write(tmp_path / "a.txt", "user's own file")
    plan = classify(_manifest({}), {"a.txt": _sha("new")}, set(), tmp_path)
    assert plan.conflicts == [Conflict("a.txt", "already present, not from this scaffold")]


# --- classify: seed files (user-owned once written) -------------------------------------


def test_seed_file_on_disk_is_left_untouched(tmp_path: Path) -> None:
    _write(tmp_path / "README.md", "user readme, much changed")
    old = _manifest({"README.md": _sha("seeded")}, seed=["README.md"])
    plan = classify(old, {"README.md": _sha("new seeded")}, {"README.md"}, tmp_path)
    assert plan.is_noop  # never refreshed, never reported


def test_seed_files_are_never_created_by_update(tmp_path: Path) -> None:
    # Even a seed path absent on disk and unknown to the old manifest is NOT created: a
    # date-stamped seed (the bootstrap RFC) differs every run, so creating it would
    # duplicate the existing one under a fresh date. The original scaffold seeds; update
    # never does.
    plan = classify(_manifest({}), {"NOTES.md": _sha("seed")}, {"NOTES.md"}, tmp_path)
    assert plan.is_noop


def test_deleted_seed_file_is_not_resurrected(tmp_path: Path) -> None:
    # Known seed (in old manifest) the user deleted: respect the deletion.
    old = _manifest({"NOTES.md": _sha("seed")}, seed=["NOTES.md"])
    plan = classify(old, {"NOTES.md": _sha("seed")}, {"NOTES.md"}, tmp_path)
    assert plan.is_noop


# --- classify: orphans (generated before, not now) --------------------------------------


def test_pristine_orphan_is_removed(tmp_path: Path) -> None:
    _write(tmp_path / "gone.txt", "v1 content")
    old = _manifest({"gone.txt": _sha("v1 content")})
    plan = classify(old, {}, set(), tmp_path)  # new version no longer generates it
    assert plan.removes == ["gone.txt"]


def test_edited_orphan_is_a_conflict_not_removed(tmp_path: Path) -> None:
    _write(tmp_path / "gone.txt", "user changed it")
    old = _manifest({"gone.txt": _sha("v1 content")})
    plan = classify(old, {}, set(), tmp_path)
    assert plan.removes == []
    assert plan.conflicts == [Conflict("gone.txt", "no longer generated; edited since scaffold")]


def test_seed_orphan_is_left_alone(tmp_path: Path) -> None:
    _write(tmp_path / "overview.md", "user's architecture")
    old = _manifest({"overview.md": _sha("seeded")}, seed=["overview.md"])
    plan = classify(old, {}, set(), tmp_path)
    assert plan.is_noop


def test_already_deleted_orphan_does_nothing(tmp_path: Path) -> None:
    old = _manifest({"gone.txt": _sha("v1")})  # nothing on disk
    plan = classify(old, {}, set(), tmp_path)
    assert plan.is_noop


# --- classify: symlinks -----------------------------------------------------------------


def test_symlink_with_changed_target_is_refreshed(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").symlink_to("AGENTS.md")
    old = _manifest({"CLAUDE.md": "symlink:AGENTS.md"})
    plan = classify(old, {"CLAUDE.md": "symlink:INSTRUCTION.md"}, set(), tmp_path)
    assert plan.refreshes == ["CLAUDE.md"]


def test_fingerprint_distinguishes_symlink_from_file(tmp_path: Path) -> None:
    _write(tmp_path / "real.md", "hi")
    (tmp_path / "link.md").symlink_to("real.md")
    assert fingerprint(tmp_path / "real.md") == _sha("hi")
    assert fingerprint(tmp_path / "link.md") == "symlink:real.md"
    assert fingerprint(tmp_path / "missing.md") is None


# --- apply ------------------------------------------------------------------------------


def test_apply_creates_and_refreshes_from_source(tmp_path: Path) -> None:
    source, target = tmp_path / "src", tmp_path / "tgt"
    _write(source / "new.txt", "fresh content")
    _write(source / "upd.txt", "updated content")
    _write(target / "upd.txt", "stale")
    plan = Plan(creates=["new.txt"], refreshes=["upd.txt"])
    recorded = {"new.txt": _sha("fresh content"), "upd.txt": _sha("updated content")}
    apply(plan, recorded, source, target)
    assert (target / "new.txt").read_text() == "fresh content"
    assert (target / "upd.txt").read_text() == "updated content"


def test_apply_creates_a_symlink_from_its_recorded_target(tmp_path: Path) -> None:
    source, target = tmp_path / "src", tmp_path / "tgt"
    target.mkdir(parents=True)
    plan = Plan(creates=["CLAUDE.md"])
    apply(plan, {"CLAUDE.md": "symlink:AGENTS.md"}, source, target)
    link = target / "CLAUDE.md"
    assert link.is_symlink() and link.readlink() == Path("AGENTS.md")


def test_apply_removes_and_prunes_empty_dirs(tmp_path: Path) -> None:
    target = tmp_path / "tgt"
    _write(target / "docs" / "old.md", "x")
    apply(Plan(removes=["docs/old.md"]), {}, tmp_path / "src", target)
    assert not (target / "docs" / "old.md").exists()
    assert not (target / "docs").exists()  # emptied dir pruned


def test_apply_leaves_conflicts_untouched(tmp_path: Path) -> None:
    source, target = tmp_path / "src", tmp_path / "tgt"
    _write(target / "mine.txt", "my edits")
    apply(Plan(conflicts=[Conflict("mine.txt", "edited since scaffold")]), {}, source, target)
    assert (target / "mine.txt").read_text() == "my edits"


# --- render_report ----------------------------------------------------------------------


def test_report_lists_conflicts_and_applied_changes() -> None:
    plan = Plan(
        creates=["new.md"],
        refreshes=["tools/checks/x.py"],
        removes=["docs/old.md"],
        conflicts=[Conflict("AGENTS.md", "edited since scaffold")],
    )
    report = render_report(plan, "0.2.0", "0.5.0")
    assert "0.2.0" in report and "0.5.0" in report
    assert "AGENTS.md" in report and "edited since scaffold" in report
    assert "`new.md`" in report and "`tools/checks/x.py`" in report and "`docs/old.md`" in report


def test_report_states_when_there_are_no_conflicts() -> None:
    report = render_report(Plan(refreshes=["a.py"]), "0.2.0", "0.3.0")
    assert "No conflicts" in report
