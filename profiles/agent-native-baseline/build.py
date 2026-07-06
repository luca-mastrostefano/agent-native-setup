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
from agent_native_setup.generators import (  # noqa: E402
    agents,
    ai_context,
    ci,
    docs,
    onboarding,
    quality,
)
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
    # agents.generate: the transient /onboard command (matches onboarding.generate's gate)
    (
        ".claude/commands/onboard.md",
        f"{_CLAUDE} and (answers.include_quality or answers.include_ci)",
        agents.ONBOARD_COMMAND,
    ),
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


def _jexpr(const: str, **slots: str) -> str:
    """A Jinja concatenation expression rendering `const` with each {slot} replaced by the
    given Jinja variable/expression — so step texts stay THE generator's constants."""
    import re

    parts = re.split(r"(\{\w+\})", const)
    out = []
    for part in parts:
        m = re.fullmatch(r"\{(\w+)\}", part)
        if m:
            out.append(slots[m.group(1)])
        elif part:
            out.append(_j(part))
    return "(" + " ~ ".join(out) + ")"


def _onboarding_prelude() -> list[str]:
    """The ONBOARDING.md runbook re-expressed over answers/env: texts are onboarding.py's own
    constants; the conditions mirror `_steps` (checked by the parity matrix, cell by cell)."""
    ob = onboarding
    setup_langs = [k for k, lang in REGISTRY.items() if lang.setup_command]
    has_setup = "(" + " or ".join(f'"{k}" in answers.languages' for k in setup_langs) + ")"
    banner_both = ob.SYMLINK_NOTE.format(
        joined="`CLAUDE.md` and `GEMINI.md`", verb="symlink", both="all"
    )
    banner_cl = ob.SYMLINK_NOTE.format(joined="`CLAUDE.md`", verb="symlinks", both="both")
    banner_gm = ob.SYMLINK_NOTE.format(joined="`GEMINI.md`", verb="symlinks", both="both")
    L = []
    A = L.append
    A(
        '{% set gate = "your full check gate" if env.existing_runner else '
        '("`task quality`" if answers.runner == "task" else "`make quality`") %}'
    )
    A(
        '{% set fmt = "your formatter" if env.existing_runner else '
        '("`task format`" if answers.runner == "task" else "`make format`") %}'
    )
    A("{% set has_setup = " + has_setup + " %}")
    A("{% set has_ci = answers.include_ci and answers.github_actions %}")
    A("{% set pre = " + _j(ob.PRE_HOOKS) + ' if answers.hooks else "" %}')
    A(
        "{% set py_clause = "
        + _j(ob.PY_CLAUSE)
        + ' if (answers.hooks and answers.include_docs) else "" %}'
    )
    A(
        "{% set lychee_clause = "
        + _j(ob.LYCHEE_CLAUSE)
        + ' if (answers.hooks and "html" in answers.languages) else "" %}'
    )
    A(
        "{% set does = [("
        + _j(ob.DOES_HOOKS)
        + ' if answers.hooks else ""), ('
        + _j(ob.DOES_SETUP)
        + ' if has_setup else "")] | select | join(" and ") %}'
    )
    A(
        '{% set run_phrase = ([("`pre-commit install`" if answers.hooks else ""), '
        '("`npm install`" if has_setup else "")] | select | join(" and ")) '
        "if env.existing_runner else "
        '("`" ~ answers.runner ~ " " ~ ("bootstrap" if has_setup else "install") ~ "`") %}'
    )
    A(
        "{% set s_toolchain = "
        + _jexpr(
            ob.S_TOOLCHAIN,
            pre="pre",
            run_phrase="run_phrase",
            does="does",
            py_clause="py_clause",
            lychee_clause="lychee_clause",
        )
        + ' if (answers.hooks or has_setup) else "" %}'
    )
    A("{% set tail = " + _j(ob.BASELINE_TAIL) + ' if env.existing_project else "" %}')
    A("{% set surface = " + _j(ob.BASELINE_SURFACE) + ' if env.existing_runner else "" %}')
    A('{% set _ships = answers.include_docs and "python" not in answers.languages %}')
    A(
        '{% set listed = "`ruff`, `mypy`, and `pytest`" if "python" in answers.languages '
        'else ("`ruff`" if _ships else "") %}'
    )
    A('{% set it = "it" if ("python" not in answers.languages and _ships) else "them" %}')
    A(
        "{% set tools_note = "
        + _jexpr(ob.TOOLS_NOTE, gate="gate", listed="listed", it="it")
        + ' if listed else "" %}'
    )
    A(
        "{% set s_baseline = "
        + _jexpr(
            ob.S_BASELINE, gate="gate", tail="tail", surface="surface", tools_note="tools_note"
        )
        + ' if answers.include_quality else "" %}'
    )
    A(
        "{% set s_adopt = ("
        + _jexpr(ob.ADOPT_FULL, gate="gate", fmt="fmt")
        + ' if answers.adopt == "full" else ('
        + _j(ob.ADOPT_PROGRESSIVE)
        + ' if answers.adopt == "progressive" else '
        + _jexpr(ob.ADOPT_NONE, gate="gate")
        + ')) if (answers.include_quality and env.existing_project) else "" %}'
    )
    A("{% set s_docs = " + _j(ob.S_DOCS) + ' if answers.include_docs else "" %}')
    A("{% set ci_clause = " + _j(ob.CI_CLAUSE) + ' if has_ci else "" %}')
    A("{% set s_uncovered = " + _jexpr(ob.S_UNCOVERED, ci_clause="ci_clause") + " %}")
    A("{% set push_clause = " + _j(ob.PUSH_CLAUSE) + ' if has_ci else "" %}')
    A("{% set harness_note = " + _j(ob.HARNESS_NOTE) + ' if has_ci else "" %}')
    A(
        "{% set s_commit = "
        + _jexpr(ob.S_COMMIT, push_clause="push_clause", harness_note="harness_note")
        + " %}"
    )
    A("{% set s_ci = " + _j(ob.S_CI_GREEN) + ' if has_ci else "" %}')
    A("{% set s_dep = " + _j(ob.S_DEPENDABOT.format()) + ' if has_ci else "" %}')
    A(
        "{% set _note = "
        + _j(banner_both)
        + ' if ("claude" in answers.tools and "gemini" in answers.tools) else ('
        + _j(banner_cl)
        + ' if "claude" in answers.tools else ('
        + _j(banner_gm)
        + ' if "gemini" in answers.tools else "")) %}'
    )
    A(
        "{% set r_banner = "
        + _jexpr(ob.R_BANNER, symlink_note="_note")
        + ' if (answers.first_run_banner and answers.tools) else "" %}'
    )
    A(
        "{% set r_onboard = "
        + _j(ob.R_ONBOARD)
        + ' if (answers.include_agents and "claude" in answers.tools) else "" %}'
    )
    A("{% set _r = [" + _j(ob.R_DELETE) + ", r_banner, r_onboard] | select | list %}")
    A(
        "{% set cleanup = _r[0] if _r | length == 1 else "
        '((_r[0] ~ " and " ~ _r[1]) if _r | length == 2 else '
        '((_r[:-1] | join(", ")) ~ ", and " ~ _r[-1])) %}'
    )
    A(
        '{% set cleanup_tail = "" if not has_ci else ('
        + _j(ob.CLEANUP_TAIL_HTML)
        + ' if "html" in answers.languages else '
        + _j(ob.CLEANUP_TAIL_PLAIN)
        + ") %}"
    )
    A(
        "{% set s_cleanup = "
        + _jexpr(ob.S_CLEANUP, cleanup="cleanup", cleanup_tail="cleanup_tail")
        + " %}"
    )
    A(
        "{% set _steps = [" + _j(ob.S_READ) + ", s_toolchain, s_baseline, s_adopt, s_docs, "
        "s_uncovered, s_commit, s_ci, s_dep, s_cleanup] | select | list %}"
    )
    return L


def _agents_prelude() -> list[str]:
    """AGENTS.md's context re-expressed over answers/env — texts are ai_context's own
    constants; per-language command data is baked from the REGISTRY at build time; the
    label-major, cross-language cmd dedupe mirrors generate() via a namespace loop."""
    import json as _json

    ac = ai_context
    # Per (label, language): the registry's raw quality commands, in registry field order.
    by_label: dict[str, dict[str, list[str]]] = {}
    for label in ("lint", "format", "typecheck", "test"):
        by_label[label] = {
            key: [cmd for lbl, cmd in lang.quality_commands if lbl == label]
            for key, lang in REGISTRY.items()
            if any(lbl == label for lbl, _ in lang.quality_commands)
        }
    has_tc = (
        "("
        + (" or ".join(f'"{k}" in answers.languages' for k in by_label["typecheck"]) or "false")
        + ")"
    )
    has_test = (
        "("
        + (" or ".join(f'"{k}" in answers.languages' for k in by_label["test"]) or "false")
        + ")"
    )
    surface_task = ac.SURFACE_NOTE_EXISTING.format(runner_name="Task", discover="task --list")
    surface_make = ac.SURFACE_NOTE_EXISTING.format(
        runner_name="Make", discover="grep -E '^[A-Za-z0-9_.-]+:.*## ' Makefile"
    )
    L = []
    A = L.append
    A("{% set name = project_name %}")
    A("{% set docs = answers.include_docs %}")
    A('{% set claude = "claude" in answers.tools %}')
    A("{% set security = answers.include_security %}")
    A(
        "{% set first_run_banner = answers.first_run_banner and answers.tools "
        "and (answers.include_quality or answers.include_ci) %}"
    )
    A("{% set _verb = answers.runner %}")
    A("{% set ns = namespace(qc=[], seen=[]) %}")
    # existing-runner branch: raw per-language commands, label-major, deduped by cmd
    A("{% if answers.include_quality and env.existing_runner %}")
    A(
        "{% if answers.hooks %}"
        '{% set ns.qc = ns.qc + [("set up git hooks (once)", "pre-commit install")] %}'
        "{% endif %}"
    )
    for label in ("lint", "format", "typecheck", "test"):
        A("{% set _by_lang = " + _json.dumps(by_label[label]) + " %}")
        A(
            "{% for _l in answers.languages %}{% for _c in _by_lang.get(_l, []) %}"
            "{% if _c not in ns.seen %}{% set ns.seen = ns.seen + [_c] %}"
            '{% set ns.qc = ns.qc + [("' + label + '", _c)] %}'
            "{% endif %}{% endfor %}{% endfor %}"
        )
    A(
        "{% set surface_note = "
        + _j(surface_task)
        + ' if answers.runner == "task" else '
        + _j(surface_make)
        + " %}"
    )
    # generated-runner branch: our own targets
    A("{% elif answers.include_quality %}")
    A(
        "{% if answers.hooks %}"
        '{% set ns.qc = ns.qc + [("set up git hooks (once)", _verb ~ " install")] %}'
        "{% endif %}"
    )
    A(
        '{% set ns.qc = ns.qc + [("run linters", _verb ~ " lint"), '
        '("auto-format", _verb ~ " format")] %}'
    )
    A(
        "{% if " + has_tc + ' %}{% set ns.qc = ns.qc + [("type-check", _verb ~ " typecheck")] %}'
        "{% endif %}"
    )
    A(
        "{% if " + has_test + ' %}{% set ns.qc = ns.qc + [("run tests", _verb ~ " test")] %}'
        "{% endif %}"
    )
    A('{% set ns.qc = ns.qc + [("full local gate", _verb ~ " quality")] %}')
    A(
        "{% if answers.include_docs %}{% set ns.qc = ns.qc + ["
        '("sync RFCs to their Status folder", _verb ~ " rfc-sync"), '
        '("log an idea in docs/improvements.md", '
        + _j(quality.IMPROVEMENT_USAGE["make"])
        + ' if _verb == "make" else '
        + _j(quality.IMPROVEMENT_USAGE["task"])
        + ")] %}{% endif %}"
    )
    A(
        "{% set surface_note = "
        + _j(ac.SURFACE_NOTE_TASK)
        + ' if _verb == "task" else '
        + _j(ac.SURFACE_NOTE_MAKE)
        + " %}"
    )
    A('{% else %}{% set surface_note = "" %}{% endif %}')
    A("{% set quality_commands = ns.qc %}")
    A('{% set _target_word = "`task`" if answers.runner == "task" else "`make` target" %}')
    A("{% set capture_line = " + _jexpr(ac.CAPTURE_LINE, target_word="_target_word") + " %}")
    return L


def _matrix_ports() -> list[tuple[str, str | None, str, list[str]]]:
    """The registry-driven config files: per-language configs verbatim-rendered, plus
    .gitignore and dependabot.yml assembled in the prelude from the SAME sources the
    generators compose them from (constants + a build-time call of ci._dependabot)."""
    import json as _json
    from types import SimpleNamespace

    ports: list[tuple[str, str | None, str, list[str]]] = []
    # Per-language config files (quality.generate): rendered with slug/name.
    for key, lang in REGISTRY.items():
        for path, content in lang.config_files.items():
            ports.append(
                (
                    path,
                    f'{_QUALITY} and "{key}" in answers.languages',
                    content,
                    ["{% set name = project_name %}"],
                )
            )
    # .gitignore (quality.generate): base + per-language lines in SELECTED order + extras.
    gi_by_lang = {k: list(lang.gitignore) for k, lang in REGISTRY.items() if lang.gitignore}
    gitignore_prelude = [
        "{% set ns = namespace(g=" + _json.dumps(quality.BASE_GITIGNORE) + ") %}",
        "{% set _gi = " + _json.dumps(gi_by_lang) + " %}",
        "{% for _l in answers.languages %}{% set ns.g = ns.g + _gi.get(_l, []) %}{% endfor %}",
        '{% if answers.include_docs and "python" not in answers.languages %}'
        "{% set ns.g = ns.g + " + _json.dumps(quality.TOOLS_PY_GITIGNORE) + " %}{% endif %}",
        '{% if "claude" in answers.tools %}{% set ns.g = ns.g + ['
        + _j(quality.CLAUDE_LOCAL_SETTINGS_LINE)
        + "] %}{% endif %}",
    ]
    ports.append((".gitignore", _QUALITY, '{{ ns.g | join("\n") }}\n', gitignore_prelude))
    # dependabot.yml (ci.generate): entries derived by CALLING ci._dependabot at build time —
    # the actions entry and each ecosystem's entry, in both security_only variants.
    base_plain = ci._dependabot([], False)
    base_sec = ci._dependabot([], True)
    prefix_plain = "version: 2\nupdates:\n"
    sec_header = base_sec[: base_sec.index("version: 2")]
    actions_plain = base_plain[len(prefix_plain) :]
    actions_sec = base_sec[len(sec_header) + len(prefix_plain) :]
    # Slicing self-check: a shape change in _dependabot must fail HERE, not as opaque
    # byte diffs across matrix cells.
    assert prefix_plain + actions_plain == base_plain
    assert sec_header + prefix_plain + actions_sec == base_sec
    eco_by_lang: dict[str, list[str]] = {}
    for key, lang in REGISTRY.items():
        if not lang.dependabot_ecosystem:
            continue
        fake = SimpleNamespace(dependabot_ecosystem=lang.dependabot_ecosystem)
        plain_full = ci._dependabot([fake], False)
        sec_full = ci._dependabot([fake], True)
        entry_plain = plain_full[len(prefix_plain) + len(actions_plain) :]
        entry_sec = sec_full[len(sec_header) + len(prefix_plain) + len(actions_sec) :]
        assert prefix_plain + actions_plain + entry_plain == plain_full
        assert sec_header + prefix_plain + actions_sec + entry_sec == sec_full
        # (_dependabot's cross-language ecosystem dedupe is latent — no two registry
        # languages share an ecosystem — mirroring the other latent dedupes noted in the matrix.)
        eco_by_lang[key] = [entry_plain, entry_sec]
    dep_prelude = [
        '{% set _sec = env.existing_project and answers.adopt != "full" %}',
        "{% set _i = 1 if _sec else 0 %}",
        "{% set _eco = " + _json.dumps(eco_by_lang) + " %}",
        "{% set ns = namespace(d=[]) %}",
        "{% for _l in answers.languages %}"
        "{% if _l in _eco %}{% set ns.d = ns.d + [_eco[_l][_i]] %}{% endif %}"
        "{% endfor %}",
        "{% set _head = ("
        + _j(sec_header)
        + ' if _sec else "") ~ '
        + _j(prefix_plain)
        + " ~ ("
        + _j(actions_sec)
        + " if _sec else "
        + _j(actions_plain)
        + ") %}",
    ]
    ports.append(
        (
            ".github/dependabot.yml",
            _GHA,
            '{{ _head ~ (ns.d | join("")) }}',
            dep_prelude,
        )
    )
    return ports


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
            "docs/improvements.md",
            _DOCS,
            docs.IMPROVEMENTS,
            [
                "{% set git = env.is_git %}",
                # Total over today's runner set {make, task} (cli --runner choices); a third
                # runner would silently take the task branch — revisit with the runner set.
                "{% set improvement_cmd = ("
                + _j(quality.IMPROVEMENT_USAGE["make"])
                + ' if answers.runner == "make" else '
                + _j(quality.IMPROVEMENT_USAGE["task"])
                + ') if (answers.include_quality and not env.existing_runner) else "" %}',
            ],
        ),
        (
            ".claude/agents/code-reviewer.md",
            _CLAUDE,
            agents.CODE_REVIEWER,
            ["{% set include_docs = answers.include_docs %}"],
        ),
        ("AGENTS.md", None, ai_context.AGENTS_MD, _agents_prelude()),
        (
            "ONBOARDING.md",
            "answers.include_quality or answers.include_ci",
            onboarding.HEADER.replace("{name}", "{{ project_name }}")
            + "{% for step in _steps %}{{ loop.index }}. {{ step }}\n{% endfor %}",
            _onboarding_prelude(),
        ),
        (
            "README.md",
            None,
            ai_context.README_MD,
            [
                "{% set name = project_name %}",
                "{% set show_quickstart = answers.include_quality and not env.existing_runner %}",
                "{% set runner = answers.runner %}",
                '{% set needs_lychee = answers.hooks and "html" in answers.languages %}',
                # config.python_surface_tools, baked: python -> ruff/mypy/pytest;
                # ships_tools_python (docs without python) -> ruff alone; else none.
                '{% set _ships = answers.include_docs and "python" not in answers.languages %}',
                '{% set surface_tools = "`ruff`, `mypy`, and `pytest`" '
                'if "python" in answers.languages else ("`ruff`" if _ships else "") %}',
                '{% set surface_pron = "it" '
                'if ("python" not in answers.languages and _ships) else "them" %}',
            ],
        ),
    ]


def _check_flagship_invariants() -> None:
    """ONBOARDING.md ships as a ported template with no profile-steps slot — if the flagship
    ever declares its own `onboarding` steps, they would be silently superseded (review of
    #49). Fail the build instead."""
    import json

    manifest = json.loads((PROFILE_ROOT / "profile.json").read_text(encoding="utf-8"))
    assert not manifest.get("onboarding"), (
        "flagship onboarding steps would be dropped by the ported ONBOARDING.md template — "
        "give the template a profile-steps slot before declaring any"
    )


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--out", default=str(TEMPLATES), help="output dir (tests build into a scratch dir)"
    )
    args = ap.parse_args(argv)
    _check_flagship_invariants()
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
    for out_rel, cond, content, prelude in _rendered_ports() + _matrix_ports():
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
