"""Provenance manifest written into every scaffolded project.

Records what generated the project — the scaffolder version, the resolved config,
and a fingerprint of each file the wizard wrote — so a future ``update`` command
can tell a pristine generated file (safe to refresh) from one the user has edited,
without re-detecting or guessing. This file only *records* provenance; the policy
for what's safe to overwrite belongs to the (not-yet-built) updater.

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
    }


def write(config: WizardConfig, sc: Scaffolder) -> None:
    """Write the provenance manifest. Call last, after every file is scaffolded."""
    sc.write(MANIFEST_PATH, json.dumps(build(config, sc), indent=2) + "\n")
