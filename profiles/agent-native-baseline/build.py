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


def _formatters_by_lang() -> dict[str, list[list[object]]]:
    return {
        k: [[ext, list(lang.format_file_cmd)] for ext in lang.detect_exts]
        for k, lang in REGISTRY.items()
        if lang.format_file_cmd
    }


def _fmt_langs_expr() -> str:
    return "(" + " or ".join(f'"{k}" in answers.languages' for k in _formatters_by_lang()) + ")"


# format-on-edit: formatter-capable language AND quality AND docs, inside the claude gate
# (agents.generate early-returns without the claude tool).
_FMT_HOOK = f"{_CLAUDE} and {_QUALITY} and {_DOCS} and " + _fmt_langs_expr()
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
    # agents.generate: format-on-edit's verbatim test (same gate as the helper)
    (
        "tools/checks/test_format_on_edit.py",
        _FMT_HOOK,
        agents.TEST_FORMAT_ON_EDIT,
    ),
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


def _step_list(block: str) -> list[str]:
    """Split an (already 6-space-indented) CI block into step chunks, mirroring
    ci._dedupe_steps' boundary rule, so Jinja can dedupe at the same granularity."""
    chunks: list[list[str]] = []
    for line in block.splitlines(keepends=True):
        if line.startswith("      - ") or not chunks:
            chunks.append([])
        chunks[-1].append(line)
    return ["".join(c) for c in chunks]


def _settings_port() -> list[tuple[str, str | None, str, list[str]]]:
    """.claude/settings.json, mirroring agents.generate: permission allowlist + SessionStart
    hooks (three list-command variants baked from the real builder) + the format-on-edit
    PostToolUse; serialized with the engine's to_json (byte-equal to json.dumps(indent=2))."""
    from types import SimpleNamespace

    def _cmd(runner: str, existing: bool) -> str:
        return agents._session_list_command(
            SimpleNamespace(runner=runner, existing_runner=existing)
        )

    prelude = [
        "{% set _q = answers.include_quality %}",
        '{% set _allow = ([("Bash(" ~ answers.runner ~ ":*)") '
        'if (_q and not env.existing_runner) else ""] | select | list) '
        '+ (["Bash(pre-commit:*)"] if (_q and answers.hooks) else []) '
        '+ ["Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)"] %}',
        "{% set _list_cmd = "
        + _j(_cmd("task", False))
        + ' if answers.runner == "task" else ('
        + _j(_cmd("make", True))
        + " if env.existing_runner else "
        + _j(_cmd("make", False))
        + ") %}",
        '{% set _sess = ([{"type": "command", "command": _list_cmd}] '
        "if (_q or env.existing_runner) else []) "
        '+ [{"type": "command", "command": ' + _j(agents.UPDATE_CHECK_COMMAND) + "}] %}",
        "{% if " + _FMT_HOOK + " %}"
        '{% set _hooks = {"SessionStart": [{"hooks": _sess}], "PostToolUse": [{"matcher": '
        '"Edit|Write", "hooks": [{"type": "command", '
        '"command": "python tools/checks/format_on_edit.py"}]}]} %}'
        '{% else %}{% set _hooks = {"SessionStart": [{"hooks": _sess}]} %}{% endif %}',
        '{% set _settings = {"permissions": {"allow": _allow}, "hooks": _hooks} %}',
    ]
    return [(".claude/settings.json", _CLAUDE, "{{ _settings | to_json }}\n", prelude)]


def _runner_ports() -> list[tuple[str, str | None, str, list[str]]]:
    """Makefile/Taskfile, mirroring quality._makefile/_taskfile call-for-call: by-label
    command lists precomputed like AGENTS.md's, then the same sequential assembly."""
    import json as _json

    labels = ("lint", "format", "format-check", "typecheck", "test")
    by_label = {
        label: {
            k: [cmd for lbl, cmd in lang.quality_commands if lbl == label]
            for k, lang in REGISTRY.items()
            if any(lbl == label for lbl, _ in lang.quality_commands)
        }
        for label in labels
    }
    setup_by_lang = {k: lang.setup_command for k, lang in REGISTRY.items() if lang.setup_command}

    def common() -> list[str]:
        L = [
            '{% set _ships = answers.include_docs and "python" not in answers.languages %}',
            "{% set ns = namespace(o=[], gd=[], ph=[]) %}",
        ]
        for label in labels:
            var = label.replace("-", "_")
            L.append("{% set _m = " + _json.dumps(by_label[label]) + " %}")
            L.append(
                "{% set ns.c_" + var + " = [] %}"
                "{% for _l in answers.languages %}{% for _c in _m.get(_l, []) %}"
                "{% set ns.c_" + var + " = ns.c_" + var + " + [_c] %}{% endfor %}{% endfor %}"
            )
            if label in quality._TOOLS_RUFF_CMDS:
                L.append(
                    "{% if _ships %}{% set ns.c_"
                    + var
                    + " = ns.c_"
                    + var
                    + " + ["
                    + _j(quality._TOOLS_RUFF_CMDS[label])
                    + "] %}{% endif %}"
                )
            if label == "test":
                L.append(
                    "{% if answers.include_docs %}{% set ns.c_test = ns.c_test + ["
                    + _j(quality.TOOLS_TESTS_CMD)
                    + "] %}{% endif %}"
                )
        L.append("{% set _setup_m = " + _json.dumps(setup_by_lang) + " %}")
        L.append(
            "{% set ns.setup = [] %}{% for _l in answers.languages %}"
            "{% if _l in _setup_m %}{% set ns.setup = ns.setup + [_setup_m[_l]] %}{% endif %}"
            "{% endfor %}"
        )
        return L

    def t_task(name: str, desc: str, cmds: str, deps: str | None = None) -> str:
        # quality._taskfile.task():
        # ["  name:", "    desc: ...", ("    deps: [..]"), "    cmds:", "      - c"...]
        lines = f'["  {name}:", "    desc: " ~ {desc}]'
        if deps:
            lines += f' + (["    deps: [" ~ ({deps} | join(", ")) ~ "]"])'
        out = f'{{% set ns.o = ns.o + {lines} + ["    cmds:"] %}}'
        out += "{% for _c in " + cmds + ' %}{% set ns.o = ns.o + ["      - " ~ _c] %}{% endfor %}'
        return out

    def t_target(name: str, desc: str, cmds: str, deps: str | None = None) -> str:
        # quality._makefile.target(): ["name: deps ## desc"] + ["\tc"...] + [""]
        head = (
            f'{{% set ns.o = ns.o + ["{name}:" ~ ((" " ~ ({deps})) if ({deps}) else "") '
            f'~ " ## " ~ {desc}] %}}'
            if deps
            else f'{{% set ns.o = ns.o + ["{name}: ## " ~ {desc}] %}}'
        )
        return (
            head
            + "{% for _c in "
            + cmds
            + ' %}{% set ns.o = ns.o + ["\t" ~ _c] %}{% endfor %}'
            + '{% set ns.o = ns.o + [""] %}'
        )

    boot_desc = (
        '("first-run setup: git hooks + fetch deps" if answers.hooks '
        'else "first-run setup: fetch deps")'
    )
    imp_desc_task = _j(
        "append a commit+date-stamped idea to docs/improvements.md "
        f"({quality.IMPROVEMENT_USAGE['task']})"
    )
    imp_desc_make = _j(
        "append a commit+date-stamped idea to docs/improvements.md "
        f"({quality.IMPROVEMENT_USAGE['make']})"
    )

    # ---- Taskfile ----
    tf = common()
    tf.append("{% set ns.o = ns.o + [" + _j('version: "3"') + ', "", "tasks:"] %}')
    tf.append(
        "{% if answers.hooks %}"
        + t_task("install", _j("install git hooks"), '["pre-commit install"]')
        + "{% endif %}"
    )
    tf.append(
        "{% if ns.setup %}"
        + t_task("bootstrap", boot_desc, "ns.setup", '(["install"] if answers.hooks else false)')
        + "{% endif %}"
    )
    tf.append(t_task("lint", _j("run linters"), '(ns.c_lint or ["true"])'))
    tf.append(t_task("format", _j("auto-format"), '(ns.c_format or ["true"])'))
    tf.append('{% set ns.gd = ["lint"] %}')
    tf.append(
        "{% if ns.c_format_check %}"
        + t_task("format-check", _j("check formatting (read-only)"), "ns.c_format_check")
        + '{% set ns.gd = ns.gd + ["format-check"] %}{% endif %}'
    )
    tf.append(
        "{% if ns.c_typecheck %}"
        + t_task("typecheck", _j("type-check"), "ns.c_typecheck")
        + '{% set ns.gd = ns.gd + ["typecheck"] %}{% endif %}'
    )
    tf.append(
        "{% if ns.c_test %}"
        + t_task("test", _j("run tests"), "ns.c_test")
        + '{% set ns.gd = ns.gd + ["test"] %}{% endif %}'
    )
    tf.append(
        t_task("quality", _j("full local gate"), '["echo \\"quality gate passed\\""]', "ns.gd")
    )
    tf.append(
        "{% if answers.include_docs %}"
        + t_task(
            "rfc-sync",
            _j("move RFCs into the folder matching their Status"),
            '["python tools/checks/sync_rfc_status.py"]',
        )
        + t_task("improvement", imp_desc_task, "[" + _j(quality._IMPROVEMENT_CMD_TASK) + "]")
        + "{% endif %}"
    )

    # ---- Makefile ----
    mk = common()
    mk.append(
        '{% set ns.ph = ["help"] + (["install"] if answers.hooks else []) '
        '+ (["bootstrap"] if ns.setup else []) + ["lint", "format"] %}'
    )
    mk.append('{% if ns.c_format_check %}{% set ns.ph = ns.ph + ["format-check"] %}{% endif %}')
    mk.append('{% if ns.c_typecheck %}{% set ns.ph = ns.ph + ["typecheck"] %}{% endif %}')
    mk.append('{% if ns.c_test %}{% set ns.ph = ns.ph + ["test"] %}{% endif %}')
    mk.append(
        '{% set ns.ph = ns.ph + ["quality"] %}'
        '{% if answers.include_docs %}{% set ns.ph = ns.ph + ["rfc-sync", "improvement"] %}'
        "{% endif %}"
    )
    mk.append('{% set ns.o = ns.o + [".PHONY: " ~ (ns.ph | join(" ")), ""] %}')
    mk.append(
        "{% set ns.o = ns.o + ["
        + _j("help: ## Show available targets")
        + ", "
        + _j("\t@grep -E '^[a-zA-Z0-9_.-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /  /'")
        + ', ""] %}'
    )
    mk.append(
        "{% if answers.hooks %}"
        + t_target("install", _j("set up git hooks (once)"), '["pre-commit install"]')
        + "{% endif %}"
    )
    mk.append(
        "{% if ns.setup %}"
        + t_target("bootstrap", boot_desc, "ns.setup", '("install" if answers.hooks else "")')
        + "{% endif %}"
    )
    mk.append(t_target("lint", _j("run linters"), '(ns.c_lint or ["true"])'))
    mk.append(t_target("format", _j("auto-format"), '(ns.c_format or ["true"])'))
    mk.append('{% set ns.gd = ["lint"] %}')
    mk.append(
        "{% if ns.c_format_check %}"
        + t_target("format-check", _j("check formatting (read-only)"), "ns.c_format_check")
        + '{% set ns.gd = ns.gd + ["format-check"] %}{% endif %}'
    )
    mk.append(
        "{% if ns.c_typecheck %}"
        + t_target("typecheck", _j("type-check"), "ns.c_typecheck")
        + '{% set ns.gd = ns.gd + ["typecheck"] %}{% endif %}'
    )
    mk.append(
        "{% if ns.c_test %}"
        + t_target("test", _j("run tests"), "ns.c_test")
        + '{% set ns.gd = ns.gd + ["test"] %}{% endif %}'
    )
    mk.append(t_target("quality", _j("full local gate"), "[]", '(ns.gd | join(" "))'))
    mk.append(
        "{% if answers.include_docs %}"
        + t_target(
            "rfc-sync",
            _j("move RFCs into the folder matching their Status"),
            '["python tools/checks/sync_rfc_status.py"]',
        )
        + t_target("improvement", imp_desc_make, "[" + _j(quality._IMPROVEMENT_CMD_MAKE) + "]")
        + "{% endif %}"
    )

    gate_common = f"{_QUALITY} and not env.existing_runner"
    return [
        (
            "Taskfile.yml",
            f'{gate_common} and answers.runner == "task"',
            '{{ (ns.o | join("\n")) ~ "\n" }}',
            tf,
        ),
        (
            "Makefile",
            f'{gate_common} and answers.runner == "make"',
            '{{ ((ns.o | join("\n")) | trim) ~ "\n" }}',
            mk,
        ),
    ]


def _ci_ports() -> list[tuple[str, str | None, str, list[str]]]:
    """quality.yml + .pre-commit-config.yaml, assembled from the SAME constants and registry
    blocks the generators compose them from (indentation and step-splitting done at build)."""
    import json as _json
    import textwrap

    # -- quality.yml -----------------------------------------------------------------
    head_full = ci.QUALITY_WORKFLOW_HEAD
    head_ratchet = ci.QUALITY_WORKFLOW_HEAD_RATCHET
    head_none = head_full.replace(
        "  quality:\n    runs-on: ubuntu-latest\n",
        "  quality:\n    runs-on: ubuntu-latest\n"
        "    continue-on-error: true  # adoption=none: informational, never blocks\n",
    )
    assert head_none != head_full  # the replace anchor must keep matching ci.generate's
    steps_by_lang: dict[str, list[list[str]]] = {}
    sec_by_lang: dict[str, list[str]] = {}
    for key, lang in REGISTRY.items():
        plain = _step_list(textwrap.indent(lang.ci_steps, "      ")) if lang.ci_steps else []
        ratchet_src = lang.ci_ratchet_steps or lang.ci_steps
        ratchet = _step_list(textwrap.indent(ratchet_src, "      ")) if ratchet_src else []
        steps_by_lang[key] = [plain, ratchet]  # [full/none variant, ratchet variant]
        if lang.ci_security_steps:
            sec_by_lang[key] = _step_list(textwrap.indent(lang.ci_security_steps, "      "))
    tools_ruff = _step_list(textwrap.indent(ci.TOOLS_RUFF_CI, "      "))
    tools_tests = _step_list(textwrap.indent(ci.TOOLS_TESTS_CI, "      "))
    gitleaks = _step_list(textwrap.indent(ci.GITLEAKS_CI_STEP, "      "))
    no_tooling = '      - run: echo "no language tooling configured"\n'
    qy = [
        '{% set _eff = answers.adopt if env.existing_project else "full" %}',
        '{% set _ri = 1 if _eff == "progressive" else 0 %}',
        "{% set _steps_by = " + _json.dumps(steps_by_lang) + " %}",
        "{% set ns = namespace(st=[], seen=[], seen2=[], sec=[]) %}",
        "{% for _l in answers.languages %}{% for _s in _steps_by.get(_l, [[], []])[_ri] %}"
        "{% if (_s | trim) and (_s | trim) not in ns.seen %}"
        "{% set ns.seen = ns.seen + [_s | trim] %}{% set ns.st = ns.st + [_s] %}"
        "{% elif not (_s | trim) %}{% set ns.st = ns.st + [_s] %}{% endif %}"
        "{% endfor %}{% endfor %}",
        '{% if answers.include_docs and "python" not in answers.languages %}'
        "{% for _s in " + _json.dumps(tools_ruff) + " %}"
        "{% if (_s | trim) not in ns.seen %}{% set ns.seen = ns.seen + [_s | trim] %}"
        "{% set ns.st = ns.st + [_s] %}{% endif %}{% endfor %}{% endif %}",
        "{% if answers.include_docs %}{% for _s in " + _json.dumps(tools_tests) + " %}"
        "{% if (_s | trim) not in ns.seen %}{% set ns.seen = ns.seen + [_s | trim] %}"
        "{% set ns.st = ns.st + [_s] %}{% endif %}{% endfor %}{% endif %}",
        '{% set _steps = (ns.st | join("")) if ns.st else ' + _j(no_tooling) + " %}",
        "{% set _head = "
        + _j(head_ratchet)
        + ' if _eff == "progressive" else ('
        + _j(head_none)
        + ' if _eff == "none" else '
        + _j(head_full)
        + ") %}",
        "{% set _sec_by = " + _json.dumps(sec_by_lang) + " %}",
        # the checks job dedupes with a FRESH seen set (ci._checks_job calls _dedupe_steps
        # independently of the quality job's) — ns.seen2, never ns.seen
        "{% if answers.include_security %}"
        "{% set ns.seen2 = [] %}"
        "{% for _l in answers.languages %}{% for _s in _sec_by.get(_l, []) %}"
        "{% if (_s | trim) not in ns.seen2 %}{% set ns.seen2 = ns.seen2 + [_s | trim] %}"
        "{% set ns.sec = ns.sec + [_s] %}{% endif %}{% endfor %}{% endfor %}"
        "{% for _s in " + _json.dumps(gitleaks) + " %}"
        "{% if (_s | trim) not in ns.seen2 %}{% set ns.seen2 = ns.seen2 + [_s | trim] %}"
        "{% set ns.sec = ns.sec + [_s] %}{% endif %}{% endfor %}"
        "{% set _checks = ("
        + _j(ci.CHECKS_JOB_HEAD)
        + ' if _eff == "full" else '
        + _j(ci.CHECKS_JOB_HEAD_NONBLOCKING)
        + ') ~ (ns.sec | join("")) %}'
        '{% else %}{% set _checks = "" %}{% endif %}',
    ]
    ports = [
        (
            ".github/workflows/quality.yml",
            _GHA,
            "{{ _head ~ _steps ~ _checks }}",
            qy,
        )
    ]
    # -- .pre-commit-config.yaml -------------------------------------------------------
    import textwrap as _tw

    def ind(block: str) -> str:
        return _tw.indent(block, "  ")

    pc_by_lang = {
        k: ind(lang.pre_commit_block) for k, lang in REGISTRY.items() if lang.pre_commit_block
    }
    test_by_lang = {}
    for k, lang in REGISTRY.items():
        th = quality._test_hook(lang)
        if th:
            test_by_lang[k] = ind(th)
    _DEP = (
        "("
        + " or ".join(
            f'"{k}" in answers.languages' for k, lg in REGISTRY.items() if lg.dependabot_ecosystem
        )
        + ")"
    )
    pc = [
        "{% set _rfc_gate = answers.include_docs and " + _DEP + " %}",
        '{% set _py_gates = answers.include_docs and "python" in answers.languages %}',
        "{% set ns = namespace(b=[" + _j(ind(quality.BASE_HOOKS)) + "]) %}",
        "{% if answers.include_security %}{% set ns.b = ns.b + ["
        + _j(ind(quality.GITLEAKS_HOOK))
        + "] %}{% endif %}",
        "{% if answers.include_ci and answers.github_actions %}{% set ns.b = ns.b + ["
        + _j(ind(quality.ACTIONLINT_HOOK))
        + "] %}{% endif %}",
        "{% set _pc = " + _json.dumps(pc_by_lang) + " %}",
        "{% for _l in answers.languages %}{% if _l in _pc %}"
        "{% set ns.b = ns.b + [_pc[_l]] %}{% endif %}{% endfor %}",
        '{% if answers.include_docs and "python" not in answers.languages %}'
        "{% set ns.b = ns.b + [" + _j(ind(quality.TOOLS_RUFF_HOOK)) + "] %}{% endif %}",
        "{% if answers.include_docs %}{% set ns.b = ns.b + ["
        + _j(ind(quality.RFC_STATUS_HOOK))
        + "] %}{% endif %}",
        "{% if _rfc_gate %}{% set ns.b = ns.b + ["
        + _j(ind(quality.RFC_NEEDED_HOOK))
        + "] %}{% endif %}",
        "{% if _py_gates %}{% set ns.b = ns.b + ["
        + _j(ind(quality.PY_LAYOUT_COMMIT_HOOKS))
        + "] %}{% endif %}",
        "{% set _th = " + _json.dumps(test_by_lang) + " %}",
        "{% for _l in answers.languages %}{% if _l in _th %}"
        "{% set ns.b = ns.b + [_th[_l]] %}{% endif %}{% endfor %}",
        "{% if answers.include_docs %}{% set ns.b = ns.b + ["
        + _j(ind(quality.TOOLS_TESTS_HOOK))
        + "] %}{% endif %}",
        '{% set _stages = "pre-commit, commit-msg, pre-push" '
        'if (_rfc_gate or _py_gates) else "pre-commit, pre-push" %}',
    ]
    ports.append(
        (
            ".pre-commit-config.yaml",
            f"{_QUALITY} and answers.hooks",
            'default_install_hook_types: [{{ _stages }}]\n\nrepos:\n{{ ns.b | join("") }}',
            pc,
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
            "docs/rfc/active/@DATE@-adopt-agent-native-setup.md",
            _DOCS,
            docs.FIRST_RFC,
            [
                "{% set today = env.date %}",
                "{% set name = project_name %}",
                '{% set _ex = [("linters and pre-commit hooks" if answers.include_quality '
                'else ""), ("CI on every push" if (answers.include_ci and '
                'answers.github_actions) else "")] | select | list %}',
                '{% set extras = ((_ex | join(", ")) ~ ", ") if _ex else "" %}',
            ],
        ),
        (
            "tools/checks/format_on_edit.py",
            _FMT_HOOK,
            agents.FORMAT_ON_EDIT,
            [
                "{% set _fmt = " + __import__("json").dumps(_formatters_by_lang()) + " %}",
                "{% set ns = namespace(f=[]) %}",
                "{% for _l in answers.languages %}{% for _p in _fmt.get(_l, []) %}"
                "{% set ns.f = ns.f + [_p] %}{% endfor %}{% endfor %}",
                "{% set formatters = ns.f | sort %}",
            ],
        ),
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
    for out_rel, cond, content, prelude in (
        _rendered_ports() + _matrix_ports() + _ci_ports() + _runner_ports() + _settings_port()
    ):
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
