"""Provenance manifest written into every scaffolded project.

Records what generated the project — the scaffolder version, the resolved config,
a fingerprint of each file the wizard wrote, and which of those files are *seed*
(user-owned once written) versus managed (refreshable) — so a future ``update``
command can tell a pristine generated file (safe to refresh) from one the user has
edited or owns, without re-detecting or guessing.

A leaf: imports only the package version, ``config``, and ``scaffold``.
"""

from __future__ import annotations

import json

from agent_native_setup import __version__
from agent_native_setup.config import WizardConfig
from agent_native_setup.scaffold import Scaffolder

# Committed with the repo (provenance travels with it), so deliberately not gitignored.
MANIFEST_PATH = ".agent-native-setup.json"


def _config_snapshot(config: WizardConfig) -> dict[str, object]:
    """The config fields a future update needs to regenerate the same files."""
    return {
        "project_name": config.project_name,
        "description": config.description,
        "languages": list(config.languages),
        "ai_tools": list(config.ai_tools),
        "runner": config.runner,
        "adoption": config.adoption,
        # Frozen so `update` regenerates the same variants (changed-files-only CI, the
        # adoption section, deferring to an existing runner) instead of re-detecting.
        "existing_project": config.existing_project,
        "existing_runner": config.existing_runner,
        "include_agents": config.include_agents,
        "include_docs": config.include_docs,
        "include_quality": config.include_quality,
        "include_ci": config.include_ci,
        "include_security": config.include_security,
        "use_github_actions": config.use_github_actions,
        "git_hooks": config.git_hooks,
        "first_run_banner": config.first_run_banner,
    }


def build(config: WizardConfig, sc: Scaffolder) -> dict[str, object]:
    """The manifest document for what this run scaffolded."""
    return {
        "scaffolder": "agent-native-setup",
        "version": __version__,
        "config": _config_snapshot(config),
        # Sorted for a stable, diff-friendly file. Excludes the manifest itself: it's
        # built from sc.recorded *before* the manifest is written.
        "files": dict(sorted(sc.recorded.items())),
        # The subset of `files` the user owns once seeded (README, the architecture
        # overview, the bootstrap RFC, …). `update` never refreshes these; everything
        # else in `files` is "managed" and refreshed when still pristine. Additive: an
        # older manifest without this key means "treat every file as managed."
        "seed": sorted(sc.seed),
    }


def write(config: WizardConfig, sc: Scaffolder) -> None:
    """Write the provenance manifest. Call last, after every file is scaffolded."""
    sc.write(MANIFEST_PATH, json.dumps(build(config, sc), indent=2) + "\n")
