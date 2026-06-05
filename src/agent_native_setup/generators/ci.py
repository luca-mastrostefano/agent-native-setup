"""Generates GitHub Actions: the quality gate, a dependency/secret scan, and the PR template."""

from __future__ import annotations

import textwrap

from agent_native_setup.config import WizardConfig
from agent_native_setup.languages import get
from agent_native_setup.scaffold import Scaffolder

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
      - uses: actions/checkout@v6
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
      - uses: actions/checkout@v6
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
    permissions:
      contents: read
      pull-requests: read  # gitleaks-action lists PR commits via the API; 403s without it
    steps:
      - uses: actions/checkout@v6
        with:
          fetch-depth: 0
"""
CHECKS_JOB_HEAD_NONBLOCKING = """\
  checks:
    runs-on: ubuntu-latest
    continue-on-error: true  # existing repo: report vulns/secrets, don't block
    permissions:
      contents: read
      pull-requests: read  # gitleaks-action lists PR commits via the API; 403s without it
    steps:
      - uses: actions/checkout@v6
        with:
          fetch-depth: 0
"""
GITLEAKS_CI_STEP = (
    # v3 runs on node24 (v2 was the deprecated node20). On a pull_request, gitleaks-action
    # calls the PR API to list commits — that needs pull-requests:read on the job (see the
    # checks-job head) — and by default posts findings as PR comments, which would need
    # pull-requests:write. We keep CI read-only and disable comments, so a leak still fails
    # the job and shows in the run log without granting write. GITHUB_TOKEN authenticates
    # the read call; without it every PR's checks job 403s while `main` stays green.
    "- uses: gitleaks/gitleaks-action@v3\n"
    "  env:\n"
    "    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}\n"
    '    GITLEAKS_ENABLE_COMMENTS: "false"\n'
)

# Guards the Python helpers shipped under tools/ when Python isn't a selected language,
# matching the tools/ ruff in the command surface + pre-commit (no local-vs-CI drift).
TOOLS_RUFF_CI = """\
- uses: actions/setup-python@v6
  with:
    python-version: "3.12"
- run: pipx install ruff
- run: ruff check tools/
- run: ruff format --check tools/
"""

# Runs the stdlib-unittest tests shipped beside the tools/checks helpers. The setup-python
# step is identical to the ruff guard's / Python's, so _dedupe_steps collapses it; only
# the unittest run is added. Whenever helpers ship (include_docs), any language.
TOOLS_TESTS_CI = """\
- uses: actions/setup-python@v6
  with:
    python-version: "3.12"
- run: python -m unittest discover -s tools/checks
"""

PULL_REQUEST_TEMPLATE = """\
## What & why

<!-- What does this change, and why? Link the RFC if one applies. -->

## Checklist

- [ ] Traces directly to the task — no drive-by changes (see `AGENTS.md`)
- [ ] Verified by a test or an explicit check
- [ ] Ran the quality gate locally
- [ ] Security-reviewed if it touches auth, untrusted input, secrets, or network I/O
- [ ] Docs/RFCs updated if behavior or architecture changed
"""


def _dedupe_steps(steps: str) -> str:
    """Drop exact-duplicate steps so a shared toolchain (e.g. Node for node+html) is set up once."""
    blocks: list[list[str]] = []
    for line in steps.splitlines(keepends=True):
        if line.startswith("      - ") or not blocks:
            blocks.append([])
        blocks[-1].append(line)
    seen: set[str] = set()
    kept: list[str] = []
    for block in blocks:
        text = "".join(block)
        key = text.strip()
        if key and key in seen:
            continue
        seen.add(key)
        kept.append(text)
    return "".join(kept)


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
        "# so Dependabot won't bulk-bump already-outdated deps. Security (vuln-fix) updates\n"
        "# are on by default for public repos, and a Settings > Code security toggle for\n"
        "# private ones. Remove the limit for routine version-update PRs.\n"
        if security_only
        else ""
    )
    return f"{header}version: 2\nupdates:\n{updates}"


def _checks_job(langs: list, blocking: bool) -> str:
    """The security `checks` job: per-language vuln scans + gitleaks secrets scan."""
    blocks = [lang.ci_security_steps for lang in langs if lang.ci_security_steps]
    blocks.append(GITLEAKS_CI_STEP)
    head = CHECKS_JOB_HEAD if blocking else CHECKS_JOB_HEAD_NONBLOCKING
    return head + _dedupe_steps("".join(textwrap.indent(b, "      ") for b in blocks))


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
    if config.ships_tools_python:  # guard the shipped tools/checks/*.py in CI too
        blocks.append(TOOLS_RUFF_CI)
    if config.include_docs:  # run the shipped tools/checks tests in CI
        blocks.append(TOOLS_TESTS_CI)
    steps = _dedupe_steps("".join(textwrap.indent(b, "      ") for b in blocks if b))
    if not steps:
        steps = '      - run: echo "no language tooling configured"\n'
    checks = _checks_job(langs, blocking=effective == "full") if config.include_security else ""
    sc.write(".github/workflows/quality.yml", head + steps + checks)

    sc.write(".github/dependabot.yml", _dependabot(langs, security_only=effective != "full"))
    sc.write(".github/PULL_REQUEST_TEMPLATE.md", PULL_REQUEST_TEMPLATE)
