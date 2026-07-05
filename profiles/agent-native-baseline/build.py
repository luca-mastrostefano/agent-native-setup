"""Author-time build step for the flagship profile (RFC 2026-07-05 §3).

Stage A: the generators are still the source of truth, so every ported template is
derived FROM them — verbatim constants raw-wrapped (PORTS), and rendering templates
re-emitted with a {% set %} prelude mapping their variables onto answers/env, baking
generator-computed values from the real functions' own output (_rendered_ports). Run
this after changing a generator; the parity harness (tests/test_flagship_parity.py)
catches drift in either direction. Post-stage-D this script becomes the profile's own
release tool (language matrix -> templates, pin baking).

Conditional inclusion pattern: a file only shipped for some answers is wrapped as
`{% if <cond> %}{% raw %}...content...{% endraw %}{% endif %}` — rendering empty (and
therefore skipped) when the condition is false, byte-exact when true. Conditions are
baked from the generators' own gating (build-time knowledge, like pins): change a
generator's gate, re-run this, and the harness proves the translation.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_native_setup.config import WizardConfig  # noqa: E402
from agent_native_setup.generators import agents, ai_context, ci, docs, quality  # noqa: E402
from agent_native_setup.generators.ai_context import _nested_symlink_note  # noqa: E402
from agent_native_setup.generators.docs import _arch_tooling  # noqa: E402
from agent_native_setup.languages import REGISTRY  # noqa: E402

PROFILE_ROOT = Path(__file__).resolve().parent
TEMPLATES = PROFILE_ROOT / "templates"
BUILT_MANIFEST = PROFILE_ROOT / ".built-manifest.json"  # meta — outside templates/, never ships

# Gate shorthands — the flagship's prompt names (answers.*) + sensed facts (env.*).
_DOCS = "answers.include_docs"
_CLAUDE = 'answers.include_agents and "claude" in answers.tools'
_QUALITY = "answers.include_quality"
_GHA = "answers.include_ci and answers.github_actions"
_PY_DOCS = f'{_DOCS} and "python" in answers.languages'
# docs.py ships the RFC dependency gate for languages that declare a Dependabot ecosystem —
# derived from the registry at build time, so adding a language can't silently diverge.
_DEP_LANGS = (
    "("
    + " or ".join(
        f'"{key}" in answers.languages'
        for key, lang in REGISTRY.items()
        if lang.dependabot_ecosystem
    )
    + ")"
)

# (output path, gate expression or None, constant) — grows as files port over.
PORTS: list[tuple[str, str | None, str]] = [
    # docs.generate (gated on include_docs in cli.build)
    ("docs/README.md", _DOCS, docs.DOCS_README),
    ("docs/rfc/TEMPLATE.md", _DOCS, docs.RFC_TEMPLATE),
    ("tools/checks/sync_rfc_status.py", _DOCS, docs.SYNC_RFC_STATUS),
    ("tools/checks/test_sync_rfc_status.py", _DOCS, docs.TEST_SYNC_RFC_STATUS),
    ("tools/checks/rfc_needed.py", f"{_DOCS} and {_DEP_LANGS}", docs.RFC_NEEDED),
    ("tools/checks/test_rfc_needed.py", f"{_DOCS} and {_DEP_LANGS}", docs.TEST_RFC_NEEDED),
    ("tools/checks/docs_sync.py", _PY_DOCS, docs.DOCS_SYNC),
    ("tools/checks/test_docs_sync.py", _PY_DOCS, docs.TEST_DOCS_SYNC),
    ("tools/checks/tests_needed.py", _PY_DOCS, docs.TESTS_NEEDED),
    ("tools/checks/test_tests_needed.py", _PY_DOCS, docs.TEST_TESTS_NEEDED),
    # agents.generate (include_agents; early-returns without the claude tool)
    (".claude/README.md", _CLAUDE, agents.AGENTS_README),
    (".claude/agents/planner.md", _CLAUDE, agents.PLANNER),
    (".claude/commands/review.md", _CLAUDE, agents.REVIEW_COMMAND),
    (".claude/commands/update-agent-scaffolding.md", _CLAUDE, agents.UPDATE_COMMAND),
    (".claude/agents/rfc-reviewer.md", f"{_CLAUDE} and {_DOCS}", agents.RFC_REVIEWER),
    (".claude/commands/rfc.md", f"{_CLAUDE} and {_DOCS}", agents.RFC_COMMAND),
    # ai_context (always runs; per-tool pointer files)
    (".cursor/rules/agent-contract.mdc", '"cursor" in answers.tools', ai_context.CURSOR_RULE),
    (".github/copilot-instructions.md", '"copilot" in answers.tools', ai_context.COPILOT_MD),
    # ci.generate (include_ci and use_github_actions)
    (".github/PULL_REQUEST_TEMPLATE.md", _GHA, ci.PULL_REQUEST_TEMPLATE),
    # quality.generate (include_quality)
    (".editorconfig", _QUALITY, quality.EDITORCONFIG),
    (".gitattributes", _QUALITY, quality.GITATTRIBUTES),
    ("SECURITY.md", f"{_QUALITY} and answers.include_security", quality.SECURITY_MD),
    (".git-blame-ignore-revs", f"{_QUALITY} and env.existing_project", quality.BLAME_IGNORE_REVS),
]


def _j(value: str) -> str:
    """A Jinja string literal for `value` (json escaping is compatible for our content)."""
    import json

    return json.dumps(value)


def _cfg(**kw: object) -> WizardConfig:
    return WizardConfig(project_name="x", output_dir=Path("."), languages=[], **kw)


def _rendered_ports() -> list[tuple[str, str | None, str, list[str]]]:
    """(path, gate, constant, prelude-set-lines) for generator templates that RENDER: the
    prelude maps each template variable onto answers/env (and bakes generator-computed
    values as Jinja conditionals over the same facts the Python computed them from)."""
    note_both = _nested_symlink_note(["CLAUDE.md", "GEMINI.md"])
    note_cl = _nested_symlink_note(["CLAUDE.md"])
    note_gm = _nested_symlink_note(["GEMINI.md"])
    nested = (
        "{% set nested_symlink_note = "
        + f'{_j(note_both)} if ("claude" in answers.tools and "gemini" in answers.tools) '
        + f'else ({_j(note_cl)} if "claude" in answers.tools '
        + f'else ({_j(note_gm)} if "gemini" in answers.tools else "")) %}}'
    )
    # _arch_tooling's bullet variants, sliced from the real function's output per config.
    base3 = _arch_tooling(_cfg(include_quality=False, include_ci=False))
    q_gha = _arch_tooling(_cfg(include_security=False)).split("\n")[3]
    q_only = _arch_tooling(_cfg(include_ci=False)).split("\n")[3]
    ci_sec = _arch_tooling(_cfg()).split("\n")[4]
    ci_plain = _arch_tooling(_cfg(include_security=False)).split("\n")[4]
    # Slice sanity: every variant must still be a single bullet line at the expected index —
    # a reordered or multi-line bullet would otherwise mis-slice silently for any variant the
    # parity matrix doesn't exercise.
    assert all(v.startswith("- **") for v in (q_gha, q_only, ci_sec, ci_plain)), (
        "arch-tooling bullets moved — fix the slice indices in _rendered_ports"
    )
    tooling = [
        "{% set _gha = answers.include_ci and answers.github_actions %}",
        "{% set tooling = " + _j(base3) + " %}",
        '{% if answers.include_quality %}{% set tooling = tooling + "\\n" + ('
        + _j(q_gha)
        + " if _gha else "
        + _j(q_only)
        + ") %}{% endif %}",
        '{% if _gha %}{% set tooling = tooling + "\\n" + ('
        + _j(ci_sec)
        + " if answers.include_security else "
        + _j(ci_plain)
        + ") %}{% endif %}",
    ]
    return [
        (
            "INSTRUCTION.md",
            None,
            ai_context.INSTRUCTION_MD,
            [
                "{% set docs = answers.include_docs %}",
                "{% set agents = answers.include_agents %}",
                '{% set claude = "claude" in answers.tools %}',
                "{% set ci = answers.include_ci and answers.github_actions %}",
                nested,
            ],
        ),
        (
            "CONTRIBUTING.md",
            _DOCS,
            docs.CONTRIBUTING,
            ["{% set existing_project = env.existing_project %}"],
        ),
        ("docs/architecture/overview.md", _DOCS, docs.ARCH_OVERVIEW, tooling),
        (
            ".claude/agents/code-reviewer.md",
            _CLAUDE,
            agents.CODE_REVIEWER,
            ["{% set include_docs = answers.include_docs %}"],
        ),
    ]


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--out", default=str(TEMPLATES), help="output dir (tests build into a scratch dir)"
    )
    args = ap.parse_args(argv)
    out_root = Path(args.out)
    in_place = out_root == TEMPLATES

    if in_place and BUILT_MANIFEST.is_file():  # remove renamed/dropped outputs — no orphans
        for rel in json.loads(BUILT_MANIFEST.read_text(encoding="utf-8")):
            (TEMPLATES / rel).unlink(missing_ok=True)

    built: list[str] = []
    for out_rel, cond, content in PORTS:
        if "{% endraw %}" in content:  # would terminate our wrapper early — needs hand-porting
            raise SystemExit(f"{out_rel}: content contains endraw; port by hand")
        if cond is None:
            rel = out_rel
            body = content
        else:
            rel = out_rel + ".j2"
            body = "{% if " + cond + " %}{% raw %}" + content + "{% endraw %}{% endif %}"
        path = out_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        built.append(rel)
        print(f"built {rel}")
    for out_rel, cond, content, prelude in _rendered_ports():
        # A rendering template: prelude {% set %} lines map its variables onto answers/env;
        # trim_blocks consumes the newline after each block tag, so the body stays byte-exact.
        parts = []
        if cond is not None:
            parts.append("{% if " + cond + " %}\n")
        parts += [line + "\n" for line in prelude]
        parts.append(content)
        if cond is not None:
            parts.append("{% endif %}")
        rel = out_rel + ".j2"
        path = out_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(parts), encoding="utf-8")
        built.append(rel)
        print(f"built {rel} (rendered)")
    if in_place:
        BUILT_MANIFEST.write_text(json.dumps(sorted(built), indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
