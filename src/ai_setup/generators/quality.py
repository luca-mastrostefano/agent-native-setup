"""Generates linter configs, pre-commit hooks, .gitignore and a Taskfile."""

from __future__ import annotations

import textwrap

from ai_setup.config import WizardConfig
from ai_setup.languages import Language, get
from ai_setup.scaffold import Scaffolder

BASE_HOOKS = """\
- repo: https://github.com/pre-commit/pre-commit-hooks
  rev: v5.0.0
  hooks:
    - id: trailing-whitespace
    - id: end-of-file-fixer
    - id: check-yaml
    - id: check-toml
    - id: check-merge-conflict
    - id: check-added-large-files
      args: [--maxkb=4096]
"""

# Secrets scanning, language-agnostic — runs on every commit.
GITLEAKS_HOOK = """\
- repo: https://github.com/gitleaks/gitleaks
  rev: v8.24.2
  hooks:
    - id: gitleaks
"""

# Lints the generated workflows; only added when GitHub Actions are scaffolded. Runs
# only on .github/workflows/ changes. actionlint-py self-installs via pre-commit's
# Python backend (no Go/Docker).
ACTIONLINT_HOOK = """\
- repo: https://github.com/Mateusz-Grzelinski/actionlint-py
  rev: v1.7.12.24
  hooks:
    - id: actionlint
      files: ^\\.github/workflows/
"""

# Mechanical enforcement: a changed RFC's Status drives which folder it lives in.
RFC_STATUS_HOOK = """\
- repo: local
  hooks:
    - id: rfc-status
      name: rfc status -> folder sync
      entry: python tools/checks/sync_rfc_status.py
      language: system
      pass_filenames: false
      files: ^docs/rfc/.*\\.md$
"""

# commit-msg gates for RFC + architecture-doc discipline. Triggers key on the
# pyproject/src layout, so these ship only for Python projects (see docs.generate).
COMMIT_MSG_HOOKS = """\
- repo: local
  hooks:
    - id: rfc-needed
      name: RFC needed for structural changes
      entry: python tools/checks/rfc_needed.py
      language: system
      stages: [commit-msg]
    - id: docs-sync
      name: architecture docs for new components
      entry: python tools/checks/docs_sync.py
      language: system
      stages: [commit-msg]
"""

BASE_GITIGNORE = [".DS_Store", ".env", ".env.local", "*.log"]

# Scaffolded only for existing repos: lets a one-time formatter sweep stay out of
# `git blame`. See the "Adopting on an existing codebase" section in contributing.md.
BLAME_IGNORE_REVS = """\
# Commits git blame (and GitHub's blame view) should skip — for bulk, no-logic
# changes like a one-time formatter sweep across pre-existing code:
#
#   1. run your formatter across the repo (see the command surface)
#   2. git commit -am "style: apply formatters across the codebase"
#   3. add the resulting commit SHA on its own line below
#   4. git config blame.ignoreRevsFile .git-blame-ignore-revs   (once, locally)
"""

# Editor-agnostic formatting baseline (applies before linters even run).
EDITORCONFIG = """\
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space
indent_size = 4

[*.{yml,yaml,json,md,js,jsx,ts,tsx,html,css}]
indent_size = 2

[Makefile]
indent_style = tab
"""

# Normalize line endings in the repo (native on checkout) — avoids Windows CRLF churn.
GITATTRIBUTES = "* text=auto\n"

SECURITY_MD = """\
# Security Policy

## Reporting a vulnerability

Report security issues privately to the maintainers rather than opening a public
issue, and allow time for a fix before any disclosure.

## Automated scanning

This repository scans for committed secrets with gitleaks (pre-commit and CI) and
audits dependencies for known vulnerabilities in CI.
"""


def _test_hook(lang: Language) -> str:
    """A pre-push hook that runs a language's full test suite."""
    cmd = next((c for lbl, c in lang.quality_commands if lbl == "test"), None)
    if not cmd:
        return ""
    return f"""\
- repo: local
  hooks:
    - id: {lang.key}-tests
      name: {lang.label} tests (pre-push)
      entry: {cmd}
      language: system
      pass_filenames: false
      always_run: true
      stages: [pre-push]
"""


def _pre_commit_config(config: WizardConfig, langs: list[Language]) -> str:
    # The RFC/docs commit-msg gates only make sense with docs and a Python layout.
    commit_msg = config.include_docs and any(lang.key == "python" for lang in langs)
    blocks = [BASE_HOOKS] + ([GITLEAKS_HOOK] if config.include_security else [])
    if config.include_ci and config.use_github_actions:
        blocks.append(ACTIONLINT_HOOK)  # lint the workflows we generate
    blocks += [lang.pre_commit_block for lang in langs if lang.pre_commit_block]
    if config.include_docs:
        blocks.append(RFC_STATUS_HOOK)
    if commit_msg:
        blocks.append(COMMIT_MSG_HOOKS)
    blocks += [h for h in (_test_hook(lang) for lang in langs) if h]
    indented = "".join(textwrap.indent(b, "  ") for b in blocks)
    stages = ["pre-commit", "commit-msg", "pre-push"] if commit_msg else ["pre-commit", "pre-push"]
    return f"default_install_hook_types: [{', '.join(stages)}]\n\nrepos:\n{indented}"


def _taskfile(config: WizardConfig, langs: list[Language], hooks: bool) -> str:
    def cmds_for(label: str) -> list[str]:
        return [cmd for lang in langs for lbl, cmd in lang.quality_commands if lbl == label]

    def task(name: str, desc: str, cmds: list[str], deps: list[str] | None = None) -> list[str]:
        out = [f"  {name}:", f"    desc: {desc}"]
        if deps:
            out.append(f"    deps: [{', '.join(deps)}]")
        out.append("    cmds:")
        out += [f"      - {c}" for c in cmds]
        return out

    typecheck = cmds_for("typecheck")
    test = cmds_for("test")

    lines = ['version: "3"', "", "tasks:"]
    if hooks:
        lines += task("install", "install git hooks", ["pre-commit install"])
    lines += task("lint", "run linters", cmds_for("lint") or ["true"])
    lines += task("format", "auto-format", cmds_for("format") or ["true"])
    gate_deps = ["lint"]
    if typecheck:
        lines += task("typecheck", "type-check", typecheck)
        gate_deps.append("typecheck")
    if test:
        lines += task("test", "run tests", test)
        gate_deps.append("test")
    lines += task("quality", "full local gate", ['echo "quality gate passed"'], deps=gate_deps)
    if config.include_docs:
        lines += task(
            "rfc-sync",
            "move RFCs into the folder matching their Status",
            ["python tools/checks/sync_rfc_status.py"],
        )
    return "\n".join(lines) + "\n"


def _makefile(config: WizardConfig, langs: list[Language], hooks: bool) -> str:
    """A self-documenting Makefile (`make help`) — the zero-install default runner."""

    def cmds_for(label: str) -> list[str]:
        return [cmd for lang in langs for lbl, cmd in lang.quality_commands if lbl == label]

    def target(name: str, desc: str, cmds: list[str], deps: str = "") -> list[str]:
        head = f"{name}:{' ' + deps if deps else ''} ## {desc}"
        return [head] + [f"\t{c}" for c in cmds] + [""]

    typecheck = cmds_for("typecheck")
    test = cmds_for("test")
    phony = ["help"] + (["install"] if hooks else []) + ["lint", "format"]
    if typecheck:
        phony.append("typecheck")
    if test:
        phony.append("test")
    phony.append("quality")
    if config.include_docs:
        phony.append("rfc-sync")

    out = [f".PHONY: {' '.join(phony)}", ""]
    out += [
        "help: ## Show available targets",
        "\t@grep -E '^[a-zA-Z0-9_.-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /  /'",
        "",
    ]
    if hooks:
        out += target("install", "set up git hooks (once)", ["pre-commit install"])
    out += target("lint", "run linters", cmds_for("lint") or ["true"])
    out += target("format", "auto-format", cmds_for("format") or ["true"])
    gate_deps = ["lint"]
    if typecheck:
        out += target("typecheck", "type-check", typecheck)
        gate_deps.append("typecheck")
    if test:
        out += target("test", "run tests", test)
        gate_deps.append("test")
    out += target("quality", "full local gate", [], deps=" ".join(gate_deps))
    if config.include_docs:
        out += target(
            "rfc-sync",
            "move RFCs into the folder matching their Status",
            ["python tools/checks/sync_rfc_status.py"],
        )
    return "\n".join(out).rstrip() + "\n"


def generate(config: WizardConfig, sc: Scaffolder) -> None:
    langs = get(config.languages)

    for lang in langs:
        for path, content in lang.config_files.items():
            sc.render_write(path, content, slug=config.slug, name=config.project_name)

    if config.git_hooks:
        sc.write(".pre-commit-config.yaml", _pre_commit_config(config, langs))

    gitignore = BASE_GITIGNORE + [line for lang in langs for line in lang.gitignore]
    sc.write(".gitignore", "\n".join(gitignore) + "\n")
    sc.write(".editorconfig", EDITORCONFIG)
    sc.write(".gitattributes", GITATTRIBUTES)
    if config.include_security:
        sc.write("SECURITY.md", SECURITY_MD)

    # Defer to an existing Taskfile/Makefile rather than imposing (or clobbering) one.
    if not config.existing_runner:
        if config.runner == "task":
            sc.write("Taskfile.yml", _taskfile(config, langs, config.git_hooks))
        else:
            sc.write("Makefile", _makefile(config, langs, config.git_hooks))

    if config.existing_project:
        sc.write(".git-blame-ignore-revs", BLAME_IGNORE_REVS)
