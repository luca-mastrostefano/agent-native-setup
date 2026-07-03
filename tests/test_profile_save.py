"""profile save (RFC 2026-07-03): extract a reusable `extends: default` profile from a scaffolded
project's *delta* from the default — not a frozen snapshot of the whole scaffold."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_native_setup import cli, profiles


class _Console:
    def __init__(self) -> None:
        self.text = ""

    def print(self, *args: object, **_kw: object) -> None:
        self.text += " ".join(str(a) for a in args) + "\n"


def _scaffold(target: Path, name: str = "acme-svc") -> Path:
    rc = cli.main(
        [
            name,
            "-o",
            str(target),
            "-y",
            "--languages",
            "python",
            "--no-git",
            "--no-update-check",
            "--no-hooks",
        ]
    )
    assert rc == 0
    return target


def _save(project: Path, name: str, out_parent: Path) -> int:
    return cli.main(["profile", "save", str(project), name, "-o", str(out_parent)])


def test_save_requires_a_scaffolded_project(tmp_path: Path) -> None:
    (tmp_path / "plain").mkdir()  # no manifest
    assert cli.main(["profile", "save", str(tmp_path / "plain"), "p", "-o", str(tmp_path)]) == 2


def test_save_captures_only_the_delta(tmp_path: Path) -> None:
    proj = _scaffold(tmp_path / "proj")
    inst = proj / "INSTRUCTION.md"
    inst.write_text(inst.read_text(encoding="utf-8") + "\n## House rule\nx\n", encoding="utf-8")
    assert _save(proj, "house", tmp_path / "out") == 0

    shipped = [rel for rel, _ in profiles.load(tmp_path / "out" / "house").template_files()]
    assert "INSTRUCTION.md" in shipped  # the edited file is captured
    assert "AGENTS.md" not in shipped  # pristine → the default provides it, not the profile
    assert not any("code-reviewer" in s for s in shipped)  # pristine default agent → excluded


def test_save_parameterizes_the_project_name(tmp_path: Path) -> None:
    proj = _scaffold(tmp_path / "proj", name="acme-svc")
    (proj / ".claude/agents/house.md").write_text(
        "---\nname: house\ndescription: reviewer for acme-svc\n---\nCheck acme-svc rules.\n",
        encoding="utf-8",
    )
    assert _save(proj, "house", tmp_path / "out") == 0

    agent = (tmp_path / "out/house/templates/.claude/agents/house.md.j2").read_text(
        encoding="utf-8"
    )
    assert "{{ project_name }}" in agent and "acme-svc" not in agent


def test_save_preserves_seed_status(tmp_path: Path) -> None:
    proj = _scaffold(tmp_path / "proj")
    (proj / "README.md").write_text(
        "# acme-svc\n\ncustom readme\n", encoding="utf-8"
    )  # a default seed
    assert _save(proj, "house", tmp_path / "out") == 0

    pj = json.loads((tmp_path / "out/house/profile.json").read_text(encoding="utf-8"))
    assert "README.md" in pj["seed"]  # an edited seed file stays write-once in the profile


def test_save_turns_symlinks_into_onboarding_steps(tmp_path: Path) -> None:
    proj = _scaffold(tmp_path / "proj")
    (proj / "INSTRUCTION.md").write_text("house\n", encoding="utf-8")  # ensure a real delta
    assert _save(proj, "house", tmp_path / "out") == 0

    pj = json.loads((tmp_path / "out/house/profile.json").read_text(encoding="utf-8"))
    assert any("ln -s AGENTS.md CLAUDE.md" in s for s in pj["onboarding"])


def test_save_excludes_user_source_and_reports_it(tmp_path: Path) -> None:
    proj = _scaffold(tmp_path / "proj")
    (proj / "src").mkdir()
    (proj / "src/app.py").write_text("print('hi')\n", encoding="utf-8")  # the user's own code
    (proj / "INSTRUCTION.md").write_text("house\n", encoding="utf-8")
    console = _Console()
    args = argparse.Namespace(project=str(proj), name="house", output=str(tmp_path / "out"))
    assert profiles._save(args, console) == 0

    shipped = [rel for rel, _ in profiles.load(tmp_path / "out/house").template_files()]
    assert not any("app.py" in s for s in shipped)  # source not swept into the profile
    assert "src/app.py" in console.text and "not captured" in console.text  # but reported


def test_save_round_trips_into_a_new_project(tmp_path: Path) -> None:
    proj = _scaffold(tmp_path / "proj", name="acme-svc")
    inst = proj / "INSTRUCTION.md"
    inst.write_text(
        inst.read_text(encoding="utf-8") + "\n## House rule\ntag oncall\n", encoding="utf-8"
    )
    (proj / ".claude/agents/house.md").write_text(
        "---\nname: house\ndescription: d\n---\nFor acme-svc.\n", encoding="utf-8"
    )
    assert _save(proj, "house", tmp_path / "out") == 0
    assert cli.main(["profile", "validate", str(tmp_path / "out/house")]) == 0

    new = tmp_path / "new"
    rc = cli.main(
        [
            "neptune",
            "-o",
            str(new),
            "-y",
            "--languages",
            "python",
            "--no-git",
            "--no-update-check",
            "--no-hooks",
            "--profile",
            str(tmp_path / "out/house"),
        ]
    )
    assert rc == 0
    assert "House rule" in (new / "INSTRUCTION.md").read_text(encoding="utf-8")  # delta propagated
    assert "For neptune." in (new / ".claude/agents/house.md").read_text(
        encoding="utf-8"
    )  # re-parameterized
