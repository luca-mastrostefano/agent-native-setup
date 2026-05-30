"""Generates GitHub Actions: a quality gate and an optional @claude responder."""

from __future__ import annotations

import textwrap

from ai_setup.config import WizardConfig
from ai_setup.languages import get
from ai_setup.scaffold import Scaffolder

QUALITY_WORKFLOW_HEAD = """\
name: quality
on:
  push:
    branches: [main]
  pull_request:

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
"""

CLAUDE_WORKFLOW = """\
name: claude
on:
  issue_comment:
    types: [created]
  pull_request_review_comment:
    types: [created]

jobs:
  claude:
    if: contains(github.event.comment.body, '@claude')
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
      id-token: write
    steps:
      - uses: actions/checkout@v4
      - uses: anthropics/claude-code-action@v1
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
"""


def generate(config: WizardConfig, sc: Scaffolder) -> None:
    if not (config.include_ci and config.use_github_actions):
        return

    langs = get(config.languages)
    steps = "".join(textwrap.indent(lang.ci_steps, "      ") for lang in langs if lang.ci_steps)
    if not steps:
        steps = '      - run: echo "no language tooling configured"\n'
    sc.write(".github/workflows/quality.yml", QUALITY_WORKFLOW_HEAD + steps)

    if "claude" in config.ai_tools:
        sc.write(".github/workflows/claude.yml", CLAUDE_WORKFLOW)
