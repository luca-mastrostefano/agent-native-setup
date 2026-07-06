"""Stage-A parity gate (RFC 2026-07-05 §7-A) — COMPLETE: the flagship profile reproduces
the generators' output byte-for-byte, whole-tree, across every matrix cell. The generators
remain the source of truth until stage B; ``build.py`` derives the templates from them, so
drift in either direction fails here.

Known out-of-scope behavior (RFC §7-A enumeration): the **AGENTS.md brownfield fold** —
both trees build into empty dirs, so the generators' merge of a pre-existing
AGENTS.md/CLAUDE.md (ai_context.generate) has no counterpart here. Decided to stay an
engine mechanic; it lands at stage B when the flagship becomes the scaffold, with its own
tests there.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest

from agent_native_setup import cli, profiles
from agent_native_setup.cli import config_to_answers
from agent_native_setup.config import WizardConfig
from agent_native_setup.generators import docs as docs_gen
from agent_native_setup.scaffold import Scaffolder

FLAGSHIP = Path(__file__).resolve().parent.parent / "profiles" / "agent-native-baseline"

# Paths the two trees legitimately never compare (provenance differs by design).
EXCLUDED = {".agent-native-setup.json"}

PINNED_DAY = "2026-01-01"


def _matrix() -> list[tuple[str, dict]]:
    """Config cells: languages x tools x part toggles x runner/adopt. Grows with coverage."""
    return [
        (
            "full",
            dict(
                languages=["python", "node"],
                ai_tools=["claude", "cursor", "copilot", "gemini"],
            ),
        ),
        (
            "lean",
            dict(
                languages=[],
                ai_tools=["claude"],
                include_docs=False,
                include_quality=False,
                include_ci=False,
                include_security=False,
            ),
        ),
        (
            "taskful",
            dict(
                languages=["python"], ai_tools=["claude", "gemini"], runner="task", adoption="full"
            ),
        ),
        (
            "brownfield",
            dict(languages=["node"], ai_tools=["claude", "copilot"], existing_project=True),
        ),
        (
            "no-agents",
            dict(languages=["go"], ai_tools=["cursor"], include_agents=False),
        ),
        # Discriminator cells: each flips ONE conjunct of a compound gate that every other
        # cell leaves co-varying, so a wrong gate translation cannot pass the matrix.
        (
            "bare-tools",  # claude present but agents off; ci on but GHA off; quality on but
            # security off; docs on but no dependabot language (html)
            dict(
                languages=["html"],
                ai_tools=["claude"],
                include_agents=False,
                include_security=False,
                use_github_actions=False,
            ),
        ),
        (
            "legacy-no-quality",  # existing repo but quality off -> no blame-ignore-revs
            dict(languages=["python"], existing_project=True, include_quality=False),
        ),
        (
            "gemini-only",  # the gemini-only nested-symlink-note variant
            dict(languages=["python"], ai_tools=["gemini"]),
        ),
        (
            "open-ci",  # gha on with security off -> the plain CI tooling bullet
            dict(languages=["node"], include_security=False),
        ),
        (
            "no-surface-tools",  # quality on, docs off, non-python -> quickstart with no
            # python surface tools (README's empty surface_tools branch)
            dict(languages=["node"], include_docs=False),
        ),
        (
            "deferred-runner",  # an existing runner -> no quickstart despite quality on
            dict(languages=["python"], existing_runner=True),
        ),
        (
            "none-adopt",  # adoption=none + hooks off (runbook variants)
            dict(
                languages=["node"],
                existing_project=True,
                adoption="none",
                git_hooks=False,
            ),
        ),
        (
            "html-hooks",  # lychee clause + the html cleanup tail
            dict(languages=["html", "python"], ai_tools=["claude"]),
        ),
        # The real-world default path: the CLI defaults first_run_banner=True but the
        # dataclass defaults False, so without these cells the banner-removal step, all
        # three symlink-note variants, the 3-way cleanup join, and ADOPT_FULL's rendered
        # slots would be unfalsified (review of #49).
        (
            "banner-full-adopt",  # banner on + adoption=full actually rendered
            dict(
                languages=["python"],
                ai_tools=["claude", "gemini"],
                first_run_banner=True,
                existing_project=True,
                adoption="full",
            ),
        ),
        (
            "banner-runner",  # banner on + existing runner -> two-command run_phrase join
            dict(
                languages=["node"], ai_tools=["claude"], first_run_banner=True, existing_runner=True
            ),
        ),
        (
            "git-on",  # env.is_git true both sides (improvements.md's git-stamp variant)
            dict(languages=["python"], init_git=True, is_git=True),
        ),
        (
            "rusty",  # rust's config files + cargo ecosystem
            dict(languages=["rust"], ai_tools=["gemini"]),
        ),
        (
            "rusty-legacy",  # the cargo sec-variant dependabot entry (review of #53)
            dict(languages=["rust", "go"], existing_project=True),
        ),
        (
            "legacy-two-langs",  # existing runner + two languages in NON-registry order:
            # AGENTS.md's raw-command surface, label-major in SELECTED-language order (the
            # cross-language dedupe itself is latent — no two registry languages share a
            # command today, mirroring generate()'s equally never-firing seen set)
            dict(languages=["node", "python"], existing_runner=True, ai_tools=["claude"]),
        ),
        # Mutation-proven gaps from the #52 review: each cell fails a template mutation the
        # rest of the matrix rides through.
        (
            "legacy-taskful",  # task-flavored SURFACE_NOTE_EXISTING + hooks-off in that branch
            dict(languages=["python"], existing_runner=True, runner="task", git_hooks=False),
        ),
        (
            "banner-inert",  # banner requested but quality+ci off -> banner must NOT render
            dict(
                languages=["python"],
                ai_tools=["claude"],
                first_run_banner=True,
                include_quality=False,
                include_ci=False,
            ),
        ),
        (
            "banner-no-tools",  # banner requested but no tools targeted -> must NOT render
            dict(languages=["python"], ai_tools=[], first_run_banner=True),
        ),
    ]


def _config(target: Path, **over: object) -> WizardConfig:
    base: dict = dict(
        project_name="demo",
        output_dir=target,
        description="a demo",
        languages=["python"],
        init_git=False,
    )
    base.update(over)
    return WizardConfig(**base)


def _tree(root: Path) -> dict[str, object]:
    """rel -> bytes for files, ('link', target) for symlinks."""
    out: dict[str, object] = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if rel in EXCLUDED or rel.startswith(".git/"):
            continue
        if p.is_symlink():
            out[rel] = ("link", str(p.readlink()))
        elif p.is_file():
            out[rel] = p.read_bytes()
    return out


def _pin_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Day(datetime.date):
        @classmethod
        def today(cls) -> "datetime.date":
            return datetime.date.fromisoformat(PINNED_DAY)

    monkeypatch.setattr(docs_gen, "date", _Day)


@pytest.mark.parametrize(("cell", "over"), _matrix())
def test_flagship_matches_generators_on_ported_files(
    cell: str, over: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin_clock(monkeypatch)
    gen_dir, flag_dir = tmp_path / "gen", tmp_path / "flag"
    gen_sc = Scaffolder(gen_dir)
    cli.build(_config(gen_dir, **over), gen_sc, None)

    flagship = profiles.load(FLAGSHIP)
    config = _config(flag_dir, **over)
    flag_sc = Scaffolder(flag_dir)
    cli.build(
        config,
        flag_sc,
        flagship,
        answers=config_to_answers(config),
        profile_date=PINNED_DAY,
    )

    # Seed-set parity (review of #53): a preserve/seed-class file whose protection status
    # differs is invisible to tree comparison but makes update clobber a user's file later.
    # Transient files must never be seeded on EITHER side (excluding one would hide
    # exactly the one-sided regression this check exists for — review of #54).
    assert "ONBOARDING.md" not in gen_sc.seed | flag_sc.seed
    gen_seed = {r for r in gen_sc.seed if r not in EXCLUDED}
    flag_seed = {r for r in flag_sc.seed if r not in EXCLUDED}
    assert gen_seed == flag_seed, f"[{cell}] seed sets differ: {gen_seed ^ flag_seed}"

    # Whole-tree equality (stage A complete): every path, byte for byte, both directions.
    gen_tree, flag_tree = _tree(gen_dir), _tree(flag_dir)
    assert set(gen_tree) == set(flag_tree), (
        f"[{cell}] tree mismatch: only-generators={sorted(set(gen_tree) - set(flag_tree))} "
        f"only-flagship={sorted(set(flag_tree) - set(gen_tree))}"
    )
    for rel in sorted(gen_tree):
        assert gen_tree[rel] == flag_tree[rel], f"[{cell}] {rel}: bytes differ"
    print(f"[parity:{cell}] whole tree identical: {len(gen_tree)} paths")


def test_flagship_profile_loads_and_validates() -> None:
    import argparse

    prof = profiles.load(FLAGSHIP)
    assert prof.name == "agent-native-baseline"

    class _Console:
        text = ""

        def print(self, *a: object, **_k: object) -> None:
            self.text += " ".join(str(x) for x in a) + "\n"

    assert profiles._validate(argparse.Namespace(path=str(FLAGSHIP)), _Console()) == 0


def test_built_templates_are_current(tmp_path: Path) -> None:
    """`build.py` output is committed — a generator-constant change without a rebuild fails
    here with the exact command to run. Builds into a scratch dir: the working tree is never
    mutated, so the failure signal is repeatable and parallel-safe."""
    import subprocess
    import sys

    out = tmp_path / "templates"
    proc = subprocess.run(
        [sys.executable, str(FLAGSHIP / "build.py"), "--out", str(out)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"build.py failed:\n{proc.stderr}"
    fresh = {p.relative_to(out).as_posix(): p.read_bytes() for p in out.rglob("*") if p.is_file()}
    committed_root = FLAGSHIP / "templates"
    committed = {
        p.relative_to(committed_root).as_posix(): p.read_bytes()
        for p in committed_root.rglob("*")
        if p.is_file()
    }
    # Every built file must exist, byte-identical, in the committed tree (hand-written .j2
    # templates may exist beyond the built set; orphans of RENAMED build outputs are caught
    # because build.py owns every path it ever emitted via the committed build manifest).
    for rel, content in fresh.items():
        assert rel in committed, f"built template {rel} is not committed — run build.py"
        assert committed[rel] == content, (
            f"{rel} is stale — run: python profiles/agent-native-baseline/build.py"
        )
    built_list = json.loads((FLAGSHIP / ".built-manifest.json").read_text(encoding="utf-8"))
    assert sorted(fresh) == sorted(built_list), (
        "build manifest out of date — run: python profiles/agent-native-baseline/build.py"
    )
    for rel in built_list:
        assert rel in fresh, f"orphaned built template {rel} — removed from PORTS but committed"
