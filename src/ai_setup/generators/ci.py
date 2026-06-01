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

# Existing-repo variant: PR-only, with full history and a resolved diff base so the
# per-language steps can lint just the changed files (legacy code is grandfathered).
QUALITY_WORKFLOW_HEAD_RATCHET = """\
name: quality
on:
  pull_request:

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Resolve diff base
        run: echo "DIFF_BASE=${{ github.event.pull_request.base.sha }}" >> "$GITHUB_ENV"
"""

# Secrets + dependency scanning, in its own job. Non-blocking on an existing repo so
# pre-existing vulns/secrets are reported, not used to wall off the first PR.
CHECKS_JOB_HEAD = """\
  checks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
"""
CHECKS_JOB_HEAD_NONBLOCKING = """\
  checks:
    runs-on: ubuntu-latest
    continue-on-error: true  # existing repo: report vulns/secrets, don't block
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
"""
GITLEAKS_CI_STEP = "- uses: gitleaks/gitleaks-action@v2\n"

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


def _checks_job(config: WizardConfig, langs: list) -> str:
    """The security `checks` job: per-language vuln scans + gitleaks secrets scan."""
    blocks = [lang.ci_security_steps for lang in langs if lang.ci_security_steps]
    blocks.append(GITLEAKS_CI_STEP)
    head = CHECKS_JOB_HEAD_NONBLOCKING if config.existing_project else CHECKS_JOB_HEAD
    return head + "".join(textwrap.indent(b, "      ") for b in blocks)


def generate(config: WizardConfig, sc: Scaffolder) -> None:
    if not (config.include_ci and config.use_github_actions):
        return

    langs = get(config.languages)
    if config.existing_project:
        head = QUALITY_WORKFLOW_HEAD_RATCHET
        blocks = [lang.ci_ratchet_steps or lang.ci_steps for lang in langs]
    else:
        head = QUALITY_WORKFLOW_HEAD
        blocks = [lang.ci_steps for lang in langs]
    steps = "".join(textwrap.indent(b, "      ") for b in blocks if b)
    if not steps:
        steps = '      - run: echo "no language tooling configured"\n'
    checks = _checks_job(config, langs) if config.include_security else ""
    sc.write(".github/workflows/quality.yml", head + steps + checks)

    if "claude" in config.ai_tools:
        sc.write(".github/workflows/claude.yml", CLAUDE_WORKFLOW)
