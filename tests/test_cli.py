"""CLI-level behavior: Ctrl+C / Ctrl+D during the wizard exits cleanly (not a traceback)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_native_setup import cli
from agent_native_setup.config import WizardConfig
from agent_native_setup.languages import REGISTRY
from agent_native_setup.scaffold import Scaffolder


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt, EOFError])
def test_interrupt_during_prompts_exits_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupt: type[BaseException]
) -> None:
    # Force the interactive path, then have a prompt abort.
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def boom(*_a: object, **_k: object) -> object:
        raise interrupt

    monkeypatch.setattr(cli, "_interactive", boom)

    assert cli.main(["demo", "-o", str(tmp_path)]) == 130
    assert not (tmp_path / "AGENTS.md").exists()  # nothing scaffolded on cancel


def test_default_name_comes_from_cwd_when_output_is_dot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression: Path(".").name is "" — scaffolding into the cwd (the default -o)
    # without a name argument must still title the project after the directory.
    project = tmp_path / "my-project"
    project.mkdir()
    monkeypatch.chdir(project)
    assert cli.main(["-y", "--no-git"]) == 0
    agents = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert "# my-project — Agent Contract" in agents


def test_dry_run_previews_without_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # --dry-run lists what a real run would create but touches nothing (parity with
    # `update --dry-run`).
    target = tmp_path / "proj"
    rc = cli.main(["demo", "-o", str(target), "-y", "--dry-run", "--languages", "python"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "dry run" in out.lower()
    assert "would create AGENTS.md" in out
    assert "would run git init" in out  # git defaults on, but dry-run never runs it
    # Nothing was actually written — not even the manifest.
    assert not (target / "AGENTS.md").exists()
    assert not (target / ".agent-native-setup.json").exists()
    assert not (target / ".git").exists()


def test_dry_run_marks_existing_files_as_skipped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The preview must reproduce the writer's skip-existing behaviour — pretending every path
    # is new is exactly wrong for the "what will this do to my repo?" case.
    target = tmp_path / "proj"
    target.mkdir()
    (target / "README.md").write_text("my own readme\n", encoding="utf-8")  # a real run skips it
    rc = cli.main(
        ["demo", "-o", str(target), "-y", "--no-git", "--dry-run", "--languages", "python"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "would skip (exists): README.md" in out
    assert "would create README.md" not in out
    # The user's file is untouched, and nothing was written.
    assert (target / "README.md").read_text(encoding="utf-8") == "my own readme\n"
    assert not (target / ".agent-native-setup.json").exists()


def test_unknown_tool_exits_2_without_scaffolding(tmp_path: Path) -> None:
    # --languages typos are rejected; --tools typos must not silently no-op.
    rc = cli.main(["demo", "-o", str(tmp_path), "-y", "--no-git", "--tools", "cluade"])
    assert rc == 2
    assert not (tmp_path / "AGENTS.md").exists()


def test_intro_shown_at_start_of_interactive_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Interactive run: the intro prints before any prompt, even if the user cancels.
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def boom(*_a: object, **_k: object) -> object:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_interactive", boom)
    cli.main(["demo", "-o", str(tmp_path)])
    assert "scaffolds" in capsys.readouterr().out  # the "what this will do" intro


def _write_profile(root: Path, description: str) -> Path:
    import json

    (root / "templates").mkdir(parents=True)
    (root / "profile.json").write_text(
        json.dumps({"name": "acme-setup", "version": "2.3.4", "description": description}),
        encoding="utf-8",
    )
    return root


def test_intro_is_built_from_the_selected_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # --profile <x>: the "what this will do" panel pitches the selected profile — its name,
    # version, and manifest description — not the flagship bullets.
    prof = _write_profile(tmp_path / "prof", "ACME's in-house TDD contract and CI gates.")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def boom(*_a: object, **_k: object) -> object:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_interactive", boom)
    cli.main(["demo", "-o", str(tmp_path / "out"), "--profile", str(prof)])
    out = capsys.readouterr().out
    assert "acme-setup" in out
    assert "v2.3.4" in out
    assert "ACME's in-house TDD" in out
    assert "AGENTS.md" not in out  # the flagship pitch doesn't leak into a profile run


def test_intro_survives_a_profile_without_a_description(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A legacy manifest with no description still gets a sane panel: name + version, no blank
    # pitch line (validate flags the missing description; the wizard must not crash on it).
    from agent_native_setup import profiles

    prof = profiles.load(_write_profile(tmp_path / "prof", ""))
    cli._intro(prof)
    out = capsys.readouterr().out
    assert "acme-setup" in out
    assert "Non-destructive" in out


def test_intro_escapes_markup_in_a_fetched_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A profile manifest is untrusted input — Rich markup in its description must render
    # literally, not style the console (or crash on an unbalanced tag).
    from agent_native_setup import profiles

    prof = profiles.load(_write_profile(tmp_path / "prof", "[blink red]pwned[/] [unclosed"))
    cli._intro(prof)
    out = capsys.readouterr().out
    assert "[blink red]pwned" in out  # shown as text, not interpreted
    assert "[unclosed" in out


def test_intro_shows_version_in_top_right(capsys: pytest.CaptureFixture[str]) -> None:
    # The version rides on the top border, to the right of the "What this will do" heading.
    from agent_native_setup import __version__

    cli._intro()
    top = capsys.readouterr().out.splitlines()[0]  # the top border line
    assert "What this will do" in top
    assert f"v{__version__}" in top
    assert top.index("What this will do") < top.index(f"v{__version__}")  # heading left, ver right


def test_named_profile_asks_only_engine_questions_and_derives_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # RFC 2026-07-07-agents-contract §4-5: an interactive named-profile run asks only the
    # engine's own questions (name / description / git-init) — never the baseline wizard's
    # languages/parts/CI/… — and derives tool targeting from the profile's shipped contract.
    import json

    import questionary

    prof = tmp_path / "prof"
    (prof / "templates").mkdir(parents=True)
    (prof / "templates" / "AGENTS.md").write_text("contract\n", encoding="utf-8")
    (prof / "profile.json").write_text(
        json.dumps(
            {
                "name": "acme",
                "version": "1.0.0",
                "description": "d",
                "agents_contract": "AGENTS.md",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def no_baseline_wizard(*_a: object, **_k: object) -> object:
        raise AssertionError("the baseline wizard must not run for a named profile")

    monkeypatch.setattr(cli, "_interactive", no_baseline_wizard)

    asked: list[str] = []

    class _Ans:
        def __init__(self, value: object) -> None:
            self.value = value

        def unsafe_ask(self) -> object:
            return self.value

    def _text(message: str, **_k: object) -> _Ans:
        asked.append(message)
        return _Ans("myproj" if "name" in message.lower() else "a description")

    def _confirm(message: str, **_k: object) -> _Ans:
        asked.append(message)
        return _Ans(False)  # decline git init

    monkeypatch.setattr(questionary, "text", _text)
    monkeypatch.setattr(questionary, "confirm", _confirm)

    out = tmp_path / "out"
    assert cli.main(["-o", str(out), "--profile", str(prof), "--no-update-check"]) == 0
    joined = " ".join(asked)
    assert "name" in joined.lower() and "description" in joined.lower()
    # None of the baseline wizard's questions were asked.
    assert "Scaffold which parts" not in joined and "Languages" not in joined
    # Derived targeting: a declared contract targets every tool → both pointers created.
    assert (out / "CLAUDE.md").is_symlink() and (out / "GEMINI.md").is_symlink()


def test_profile_default_keeps_the_full_wizard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `--profile default` resolves to no profile (the legacy generators), whose questions the
    # full baseline wizard asks — it must NOT get the shrunken named-profile wizard.
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def no_shrunken_wizard(*_a: object, **_k: object) -> object:
        raise AssertionError("--profile default must use the full wizard, not _profile_config")

    monkeypatch.setattr(cli, "_profile_config", no_shrunken_wizard)
    used = {"full": False}

    def _full(*_a: object, **_k: object) -> WizardConfig:
        used["full"] = True
        raise KeyboardInterrupt  # bail out right after — we only assert which path ran

    monkeypatch.setattr(cli, "_interactive", _full)
    cli.main(["demo", "-o", str(tmp_path / "out"), "--profile", "default", "--no-update-check"])
    assert used["full"]  # the full wizard ran, the shrunken one never did


def test_next_steps_label_contract_optional_and_setup_important(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # With both steps shown, they're a contrasting pair: reading the contract is Optional,
    # finishing the one-time setup is the IMPORTANT must-do — and in that order.
    config = WizardConfig(project_name="demo", output_dir=tmp_path, init_git=False)
    sc = Scaffolder(config.target)
    sc.created.append("ONBOARDING.md")  # the hint keys on the runbook actually shipping
    cli._summary(config, sc)
    out = capsys.readouterr().out
    assert "⚠" in out  # the importance icon precedes IMPORTANT
    assert out.index("Optional:") < out.index("IMPORTANT:")  # contract first, setup second


def test_next_steps_lone_contract_not_mislabelled_optional(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # No quality and no CI -> only the contract step. With no contrasting must-do, it must
    # NOT be marked "Optional" (that would read as "skip the only thing to do").
    config = WizardConfig(
        project_name="demo",
        output_dir=tmp_path,
        init_git=False,
        include_quality=False,
        include_ci=False,
    )
    cli._summary(config, Scaffolder(config.target))
    out = capsys.readouterr().out
    assert "AGENTS.md" in out
    assert "Optional:" not in out
    assert "IMPORTANT:" not in out


def test_git_init_lands_on_main_regardless_of_user_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The docs, CI triggers, and onboarding all say `main`, but a user's
    # init.defaultBranch (or an old git default) can produce `master` — seen in a real
    # first run. The scaffold must pin the branch name itself.
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text("[init]\n\tdefaultBranch = master\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    target = tmp_path / "proj"
    assert cli.main(["demo", "-o", str(target), "-y", "--no-update-check"]) == 0
    branch = subprocess.run(
        ["git", "-C", str(target), "branch", "--show-current"],
        capture_output=True,
        text=True,
    )
    assert branch.stdout.strip() == "main"


def test_git_init_fallback_lands_on_main_for_old_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # git <2.28 has no `init -b`; the fallback must retarget the unborn HEAD (review of
    # the fix: `branch -m` needs git 2.30, so it failed silently on exactly the old gits).
    # Shim: a `git` that rejects `init -b` like an old git, passing everything else through.
    import shutil as _shutil

    real_git = _shutil.which("git")
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    shim = shim_dir / "git"
    shim.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "init" ] && echo "$@" | grep -q -- "-b"; then\n'
        '  echo "error: unknown switch \\`b\'" >&2; exit 129\n'
        "fi\n"
        f'exec "{real_git}" "$@"\n',
        encoding="utf-8",
    )
    shim.chmod(0o755)
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text("[init]\n\tdefaultBranch = master\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    monkeypatch.setenv("PATH", f"{shim_dir}:{__import__('os').environ['PATH']}")
    target = tmp_path / "proj"
    assert cli.main(["demo", "-o", str(target), "-y", "--no-update-check"]) == 0
    head = subprocess.run(
        ["git", "-C", str(target), "symbolic-ref", "HEAD"], capture_output=True, text=True
    )
    assert head.stdout.strip() == "refs/heads/main"


class _Ans:
    def __init__(self, value: object) -> None:
        self.value = value

    def unsafe_ask(self) -> object:
        return self.value


def _run_wizard(
    monkeypatch: pytest.MonkeyPatch,
    out_dir: Path,
    *,
    parts: list[str],
    languages: list[str],
    hooks: bool = True,
    tools: list[str] | None = None,
    confirms: list[str] | None = None,
) -> tuple[WizardConfig, str, str]:
    """Drive `_interactive` with scripted answers; return (config, console output, choice
    labels). The output is whitespace-normalized: rich hard-wraps to the console width, so a
    raw-substring assertion would break on where the line happens to fold. Pass `confirms` to
    collect every yes/no question the wizard actually asked."""
    import io

    import questionary
    from rich.console import Console

    buf = io.StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buf, no_color=True))
    titles: list[str] = []

    def _checkbox(message: str, choices: list, **_k: object) -> _Ans:
        titles.extend(c.title for c in choices)
        if "Languages" in message:
            return _Ans(list(languages))
        if "AI assistants" in message:
            return _Ans(["claude"] if tools is None else list(tools))
        return _Ans(list(parts))

    def _select(message: str, choices: list, **_k: object) -> _Ans:
        titles.extend(c.title for c in choices)
        return _Ans(choices[0].value)

    def _confirm(message: str, **_k: object) -> _Ans:
        if confirms is not None:
            confirms.append(message)
        return _Ans(hooks if "pre-commit hooks" in message else True)

    monkeypatch.setattr(questionary, "text", lambda message, **_k: _Ans("demo"))
    monkeypatch.setattr(questionary, "confirm", _confirm)
    monkeypatch.setattr(questionary, "select", _select)
    monkeypatch.setattr(questionary, "checkbox", _checkbox)

    args = cli.parse_args(["demo", "-o", str(out_dir)])
    cfg = cli._interactive(args, out_dir, list(languages), True, set(languages))
    return cfg, " ".join(buf.getvalue().split()), " ".join(titles)


def test_wizard_never_asks_about_the_first_run_banner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RFC 2026-07-09: answering "no" left a scaffolded-but-un-onboarded repo with nothing in
    AGENTS.md to say so, and bought nothing back — the banner deletes itself once ONBOARDING.md
    is done. So it ships wherever it works, and the wizard spends no question on it."""
    confirms: list[str] = []
    cfg, _out, _shown = _run_wizard(
        monkeypatch, tmp_path, parts=["quality", "ci"], languages=["python"], confirms=confirms
    )

    assert cfg.first_run_banner
    assert confirms, "harness wired wrong — the wizard asks *some* yes/no questions"
    assert not [m for m in confirms if "banner" in m.lower() or "onboard" in m.lower()]


@pytest.mark.parametrize(
    ("parts", "tools", "expected"),
    [
        # The banner points at ONBOARDING.md, which ships for either half of the toolchain.
        (["quality", "ci"], ["claude"], True),
        (["quality"], ["claude"], True),
        (["ci"], ["claude"], True),
        # No quality/CI ⇒ no ONBOARDING.md to point at, so the banner would dangle.
        (["agents", "docs"], ["claude"], False),
        # No AI assistant ⇒ no agent is pointed at AGENTS.md, so the banner is inert text.
        (["quality", "ci"], [], False),
    ],
)
def test_first_run_banner_ships_exactly_where_it_can_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    parts: list[str],
    tools: list[str],
    expected: bool,
) -> None:
    """Always-on is gated, not unconditional: the banner needs an AI tool to read AGENTS.md
    *and* an ONBOARDING.md for it to point at. Outside that, injecting it would leave a
    block promising a runbook that never shipped."""
    cfg, _out, _shown = _run_wizard(
        monkeypatch, tmp_path, parts=parts, languages=["python"], tools=tools
    )

    assert cfg.first_run_banner is expected


def test_wizard_names_and_links_the_tools_it_signs_you_up_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A question the user can't answer informed is one they answer by mashing enter: every
    external tool the wizard pulls in is named *and* linked, and the part labels say what lands."""
    cfg, out, shown = _run_wizard(
        monkeypatch, tmp_path, parts=["quality", "ci"], languages=["python"]
    )

    assert "https://pre-commit.com" in out  # they must install it before the hooks run
    assert "https://gitleaks.io" in out  # nobody knows what "secret scanning" means concretely
    assert "https://taskfile.dev" in shown  # the runner choice that costs an install says so
    assert "code-reviewer" in shown and "docs/architecture" in shown
    assert cfg.include_ci and cfg.include_quality


@pytest.mark.parametrize(
    ("parts", "hooks", "languages", "expected"),
    [
        # Both halves land: say where each one runs, and name only the picked language's audit.
        (
            ["quality", "ci"],
            True,
            ["python"],
            "in the pre-commit hook and CI. Dependency audit: pip-audit, in CI.",
        ),
        # Multi-language: every selected audit is named.
        (
            ["quality", "ci"],
            True,
            ["python", "go"],
            "Dependency audit: pip-audit, govulncheck, in CI.",
        ),
        # No CI → the audit half of "security scanning" silently does nothing. Admit it.
        (
            ["quality"],
            True,
            ["python"],
            "in the pre-commit hook. Dependency audit (pip-audit) is CI-only, which you declined.",
        ),
        # No quality → no pre-commit config exists, so don't claim gitleaks runs in a hook.
        (["ci"], True, ["python"], "gitleaks (https://gitleaks.io), in CI."),
        # Hooks declined and no CI → gitleaks has nowhere to run at all.
        (["quality"], False, ["python"], "neither of which you're scaffolding."),
        # A language with no audit tool (or none picked) must not name one.
        (
            ["quality", "ci"],
            True,
            ["html"],
            "Dependency audit: none — no selected language has one.",
        ),
    ],
)
def test_wizard_security_note_tracks_what_was_actually_selected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    parts: list[str],
    hooks: bool,
    languages: list[str],
    expected: str,
) -> None:
    """The security question spans two gates (hook + CI) and every language's audit tool. Its
    explainer must describe the run the user is actually configuring — a static sentence would
    claim gitleaks runs in CI while the same note says CI was declined."""
    _, out, _ = _run_wizard(monkeypatch, tmp_path, parts=parts, languages=languages, hooks=hooks)
    assert expected in out
    # Never name an audit tool for a language they didn't choose.
    for absent in {"pip-audit", "npm audit", "govulncheck", "cargo-audit"} - {
        REGISTRY[k].audit_tool for k in languages
    }:
        assert absent not in out


@pytest.mark.parametrize(
    "languages",
    [
        # An audit tool exists, so the clobbered value is truthy and `ai_tools` silently becomes
        # ["pip-audit"] — a name that isn't an AI tool at all.
        ["python"],
        # No audit tool, so the clobbered value is empty: the user's "claude" is dropped outright
        # and the first-run-banner question is never even asked.
        ["html"],
    ],
)
def test_wizard_keeps_the_ai_tools_when_the_security_note_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, languages: list[str]
) -> None:
    """The security note derives the per-language audit tools; that list must not overwrite the
    AI assistants the user picked. Both feed `WizardConfig`, and only "quality"/"ci" runs reach
    the note — which is the common path, so a clobber here mis-scaffolds every such project."""
    cfg, _, _ = _run_wizard(monkeypatch, tmp_path, parts=["quality", "ci"], languages=languages)
    assert cfg.ai_tools == ["claude"]
