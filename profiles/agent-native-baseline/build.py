"""Author-time build step for the flagship profile (RFC 2026-07-05 §3).

Stage A: the generators are still the source of truth, so ported *verbatim* files are
derived FROM their constants — run this after changing one, and the parity harness
(`tests/test_flagship_parity.py`) will catch any drift either way. Hand-written `.j2`
templates (config-dependent content) live directly under `templates/` and are not
touched here. Post-stage-D this script becomes the profile's own release tool
(language matrix -> templates, pin baking).

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

from agent_native_setup.generators import agents, ai_context, ci, docs, quality  # noqa: E402

TEMPLATES = Path(__file__).resolve().parent / "templates"

# Gate shorthands — the flagship's prompt names (answers.*) + sensed facts (env.*).
_DOCS = "answers.include_docs"
_CLAUDE = 'answers.include_agents and "claude" in answers.tools'
_QUALITY = "answers.include_quality"
_GHA = "answers.include_ci and answers.github_actions"
_PY_DOCS = f'{_DOCS} and "python" in answers.languages'
# docs.py ships the RFC dependency gate for languages that declare a Dependabot ecosystem
# (python/node/go/rust today — baked, like pins; html has none).
_DEP_LANGS = (
    '("python" in answers.languages or "node" in answers.languages '
    'or "go" in answers.languages or "rust" in answers.languages)'
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


def main() -> int:
    for out_rel, cond, content in PORTS:
        if "{% endraw %}" in content:  # would terminate our wrapper early — needs hand-porting
            raise SystemExit(f"{out_rel}: content contains endraw; port by hand")
        if cond is None:
            path = TEMPLATES / out_rel
            body = content
        else:
            path = TEMPLATES / (out_rel + ".j2")
            body = "{% if " + cond + " %}{% raw %}" + content + "{% endraw %}{% endif %}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        print(f"built {path.relative_to(TEMPLATES.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
