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

permissions:
  contents: read

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

permissions:
  contents: read

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


PULL_REQUEST_TEMPLATE = """\
## What & why

<!-- What does this change, and why? Link the RFC if one applies. -->

## Checklist

- [ ] Traces directly to the task — no drive-by changes (see `AGENTS.md`)
- [ ] Verified by a test or an explicit check
- [ ] Ran the quality gate locally
- [ ] Docs/RFCs updated if behavior or architecture changed
"""


def _dependabot(langs: list, security_only: bool) -> str:
    """Dependabot config: GitHub Actions plus each selected language's ecosystem.

    When security-only, routine version updates are disabled
    (``open-pull-requests-limit: 0``) so Dependabot doesn't open a wave of bump PRs for
    already-outdated deps; security updates still apply once enabled in repo settings.
    """
    ecosystems = ["github-actions"]
    for lang in langs:
        if lang.dependabot_ecosystem and lang.dependabot_ecosystem not in ecosystems:
            ecosystems.append(lang.dependabot_ecosystem)
    limit = "    open-pull-requests-limit: 0\n" if security_only else ""
    updates = "".join(
        f'  - package-ecosystem: "{eco}"\n'
        '    directory: "/"\n'
        "    schedule:\n"
        '      interval: "weekly"\n'
        f"{limit}"
        "    groups:\n"
        "      dependencies:\n"
        '        patterns: ["*"]\n'
        for eco in ecosystems
    )
    header = (
        "# Existing repo: routine version updates are off (open-pull-requests-limit: 0)\n"
        "# so Dependabot won't bulk-bump already-outdated deps. Security updates still\n"
        "# apply once enabled in Settings > Code security. Remove the limit for routine\n"
        "# version-update PRs.\n"
        if security_only
        else ""
    )
    return f"{header}version: 2\nupdates:\n{updates}"


def _checks_job(langs: list, blocking: bool) -> str:
    """The security `checks` job: per-language vuln scans + gitleaks secrets scan."""
    blocks = [lang.ci_security_steps for lang in langs if lang.ci_security_steps]
    blocks.append(GITLEAKS_CI_STEP)
    head = CHECKS_JOB_HEAD if blocking else CHECKS_JOB_HEAD_NONBLOCKING
    return head + "".join(textwrap.indent(b, "      ") for b in blocks)


def generate(config: WizardConfig, sc: Scaffolder) -> None:
    if not (config.include_ci and config.use_github_actions):
        return

    langs = get(config.languages)
    # A fresh repo is enforced fully (greenfield); an existing one follows its adoption.
    effective = config.adoption if config.existing_project else "full"
    if effective == "progressive":
        head = QUALITY_WORKFLOW_HEAD_RATCHET
        blocks = [lang.ci_ratchet_steps or lang.ci_steps for lang in langs]
    else:
        head = QUALITY_WORKFLOW_HEAD
        blocks = [lang.ci_steps for lang in langs]
        if effective == "none":  # informational gate — runs the full checks but never fails
            head = head.replace(
                "  quality:\n    runs-on: ubuntu-latest\n",
                "  quality:\n    runs-on: ubuntu-latest\n"
                "    continue-on-error: true  # adoption=none: informational, never blocks\n",
            )
    steps = "".join(textwrap.indent(b, "      ") for b in blocks if b)
    if not steps:
        steps = '      - run: echo "no language tooling configured"\n'
    checks = _checks_job(langs, blocking=effective == "full") if config.include_security else ""
    sc.write(".github/workflows/quality.yml", head + steps + checks)

    sc.write(".github/dependabot.yml", _dependabot(langs, security_only=effective != "full"))
    sc.write(".github/PULL_REQUEST_TEMPLATE.md", PULL_REQUEST_TEMPLATE)

    if "claude" in config.ai_tools:
        sc.write(".github/workflows/claude.yml", CLAUDE_WORKFLOW)
