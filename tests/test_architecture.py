"""Structural guardrail for the dependency rules in docs/architecture/overview.md.

List the import prefixes each package under ``src/`` must NOT depend on; this
test fails if one does. Start empty and add boundaries as the design stabilizes.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"

# package path (relative to src/) -> import prefixes it may not use.
# e.g. "billing": ("ui", "experiments") forbids src/billing/** importing those.
FORBIDDEN_IMPORTS: dict[str, tuple[str, ...]] = {
    # Generators render output; they must not reach back into the CLI orchestrator.
    "agent_native_setup/generators": ("agent_native_setup.cli",),
}


def _imported_modules(source: str) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_module_boundaries() -> None:
    offenders: dict[str, set[str]] = {}
    for package, forbidden in FORBIDDEN_IMPORTS.items():
        for module_file in (SRC_DIR / package).rglob("*.py"):
            bad = {
                m
                for m in _imported_modules(module_file.read_text(encoding="utf-8"))
                if m.startswith(forbidden)
            }
            if bad:
                offenders[str(module_file)] = bad
    assert not offenders, f"module boundary violated: {offenders}"
