"""Configuration model for the scaffolding wizard."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

AI_TOOLS = ("claude", "cursor", "copilot")
SCAFFOLD_PARTS = ("ai_context", "agents", "docs", "quality", "ci")


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "project"


@dataclass
class WizardConfig:
    """Everything the generators need to produce a project."""

    project_name: str
    description: str = ""
    output_dir: Path = field(default_factory=Path.cwd)
    languages: list[str] = field(default_factory=list)
    ai_tools: list[str] = field(default_factory=lambda: list(AI_TOOLS))
    include_agents: bool = True
    include_docs: bool = True
    include_quality: bool = True
    include_ci: bool = True
    include_security: bool = True  # secrets (gitleaks) + dependency/vuln scanning
    use_github_actions: bool = True
    git_hooks: bool = True
    init_git: bool = True
    # True when scaffolding into a repo that already has source for the selected
    # languages; flips the quality gate to changed-files-only (legacy grandfathering).
    existing_project: bool = False
    # Task runner the command surface speaks: "make" (zero-install default) | "task".
    runner: str = "make"
    # True when the target already had a Taskfile/Makefile: defer to it, don't
    # generate our own Taskfile and don't touch theirs.
    existing_runner: bool = False

    @property
    def slug(self) -> str:
        return slugify(self.project_name)

    @property
    def target(self) -> Path:
        return self.output_dir.resolve()
