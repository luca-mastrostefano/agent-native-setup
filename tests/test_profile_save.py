"""profile save (RFC 2026-07-03, redefined by RFC 2026-07-05 §4): snapshot a scaffolded
project's **complete** setup as a standalone profile — the setup as rendered for that project
plus the project's own edits, symlinks as `links`, the dated bootstrap RFC via `@DATE@`."""

from __future__ import annotations

import argparse
import json
from datetime import date
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


def test_save_snapshots_the_complete_setup(tmp_path: Path) -> None:
    proj = _scaffold(tmp_path / "proj")
    inst = proj / "INSTRUCTION.md"
    inst.write_text(inst.read_text(encoding="utf-8") + "\n## House rule\nx\n", encoding="utf-8")
    assert _save(proj, "house", tmp_path / "out") == 0

    prof = profiles.load(tmp_path / "out" / "house")
    shipped = [rel for rel, _ in prof.template_files()]
    # The snapshot is the WHOLE setup, edits included — not a delta from anything.
    assert "INSTRUCTION.md" in shipped and "AGENTS.md" in shipped
    assert any("code-reviewer" in s for s in shipped)  # pristine files ship too
    body = (tmp_path / "out/house/templates/INSTRUCTION.md").read_text(encoding="utf-8")
    assert "## House rule" in body  # the user's edit is part of the snapshot
    # Provenance: the snapshot says what it was derived from.
    assert "agent-native-baseline" in prof.description
    assert "agent-native-baseline" in (tmp_path / "out/house/README.md").read_text(encoding="utf-8")


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
    )  # a seed file
    assert _save(proj, "house", tmp_path / "out") == 0

    pj = json.loads((tmp_path / "out/house/profile.json").read_text(encoding="utf-8"))
    assert "README.md" in pj["seed"]  # an edited seed file stays write-once in the profile


def test_save_collapses_tool_pointers_into_agents_contract(tmp_path: Path) -> None:
    proj = _scaffold(tmp_path / "proj")
    assert _save(proj, "house", tmp_path / "out") == 0

    pj = json.loads((tmp_path / "out/house/profile.json").read_text(encoding="utf-8"))
    # The CLAUDE.md/GEMINI.md → AGENTS.md pointer symlinks collapse to one engine-owned
    # agents_contract (RFC 2026-07-07-agents-contract §6) — not raw links, so the snapshot
    # inherits future matrix growth instead of pinning the pointer set.
    assert pj["agents_contract"] == "AGENTS.md"
    assert "CLAUDE.md" not in pj.get("links", {}) and "GEMINI.md" not in pj.get("links", {})
    assert pj.get("onboarding", []) == []
    # Round-trips: loading the saved profile re-expands the pointers.
    prof = profiles.load(tmp_path / "out/house")
    assert prof.contract_pointers() == (("CLAUDE.md", "AGENTS.md"), ("GEMINI.md", "AGENTS.md"))


def test_save_captures_the_bootstrap_rfc_through_date_token(tmp_path: Path) -> None:
    proj = _scaffold(tmp_path / "proj")
    assert _save(proj, "house", tmp_path / "out") == 0

    prof = profiles.load(tmp_path / "out/house")
    shipped = [rel for rel, _ in prof.template_files()]
    dated = "docs/rfc/active/@DATE@-adopt-agent-native-setup.md"
    assert dated in shipped  # re-parameterized, so a new scaffold re-stamps it
    assert dated in prof.seed  # and it stays write-once
    tmpl = (tmp_path / f"out/house/templates/{dated}.j2").read_text(encoding="utf-8")
    stamp = f"{date.today():%Y-%m-%d}"
    assert "{{ env.date }}" in tmpl and stamp not in tmpl  # the body re-stamps with the path


def test_save_skips_binary_files_and_its_output_still_validates(tmp_path: Path) -> None:
    proj = _scaffold(tmp_path / "proj")
    (proj / ".claude" / "logo.png").write_bytes(b"\x89PNG\x00\xff\xfe")  # binary house file
    console = _Console()
    args = argparse.Namespace(project=str(proj), name="house", output=str(tmp_path / "out"))
    assert profiles._save(args, console) == 0

    shipped = [rel for rel, _ in profiles.load(tmp_path / "out/house").template_files()]
    # Profiles ship text only (apply reads UTF-8) — a captured binary would produce a draft
    # that crashes the consumer's scaffold. Skipped and reported instead (review of B2).
    assert not any("logo.png" in s for s in shipped)
    assert "binary" in console.text and "logo.png" in console.text
    # save must never produce output its own validator rejects.
    assert cli.main(["profile", "validate", str(tmp_path / "out/house")]) == 0


def test_save_falls_back_to_onboarding_for_an_unconfinable_symlink(tmp_path: Path) -> None:
    proj = _scaffold(tmp_path / "proj")
    (proj / "CLAUDE.md").unlink()
    (proj / "CLAUDE.md").symlink_to("/etc/hosts")  # absolute target — can't ship as a link
    assert _save(proj, "house", tmp_path / "out") == 0

    pj = json.loads((tmp_path / "out/house/profile.json").read_text(encoding="utf-8"))
    assert "CLAUDE.md" not in pj.get("links", {})  # never a confinement-violating links entry
    assert any("ln -s /etc/hosts CLAUDE.md" in s for s in pj["onboarding"])  # the fallback


def test_save_warns_when_onboarding_is_incomplete(tmp_path: Path) -> None:
    # A pre-onboarding AGENTS.md bakes in the first-run banner while the snapshot ships no
    # ONBOARDING.md — an inconsistency the author must see (review of B2).
    proj = _scaffold(tmp_path / "proj")
    console = _Console()
    args = argparse.Namespace(project=str(proj), name="early", output=str(tmp_path / "out1"))
    assert profiles._save(args, console) == 0
    assert "onboarding incomplete" in console.text  # ONBOARDING.md still on disk

    # onboarding done — the whole transient apparatus self-deleted (runbook + every trigger)
    from agent_native_setup import profiles as _p

    for rel in _p.load(_p.builtin_baseline_root()).transient:
        (proj / rel).unlink(missing_ok=True)
    console2 = _Console()
    args2 = argparse.Namespace(project=str(proj), name="late", output=str(tmp_path / "out2"))
    assert profiles._save(args2, console2) == 0
    assert "onboarding incomplete" not in console2.text


def test_save_excludes_user_source_and_reports_it(tmp_path: Path) -> None:
    proj = _scaffold(tmp_path / "proj")
    (proj / "src").mkdir()
    (proj / "src/app.py").write_text("print('hi')\n", encoding="utf-8")  # the user's own code
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
            "--no-git",
            "--no-update-check",
            "--profile",
            str(tmp_path / "out/house"),
        ]
    )
    assert rc == 0
    # The snapshot IS the setup — no generator base beneath it.
    assert "House rule" in (new / "INSTRUCTION.md").read_text(encoding="utf-8")
    assert "For neptune." in (new / ".claude/agents/house.md").read_text(
        encoding="utf-8"
    )  # re-parameterized
    assert (new / "AGENTS.md").is_file() and (new / "CLAUDE.md").is_symlink()  # links recreated
    stamp = f"{date.today():%Y-%m-%d}"
    boot = new / f"docs/rfc/active/{stamp}-adopt-agent-native-setup.md"
    assert boot.is_file() and stamp in boot.read_text(encoding="utf-8")  # re-stamped
