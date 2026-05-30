"""Registry mapping languages to their linters, hooks, CI steps and configs.

Adding a language = adding one ``Language`` entry here. Generators stay generic.
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path

PYPROJECT_TOML = """\
[project]
name = "{{ slug }}"
version = "0.1.0"
requires-python = ">=3.10"

# Ruff: linter + formatter for Python. https://docs.astral.sh/ruff/
[tool.ruff]
line-length = 100
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "I", "W", "B", "RUF"]

# Mypy: static type checking. https://mypy.readthedocs.io/
[tool.mypy]
python_version = "3.10"
warn_redundant_casts = true
warn_unused_ignores = true

# Pytest. https://docs.pytest.org/
[tool.pytest.ini_options]
testpaths = ["tests"]
"""

ARCH_TEST = '''\
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
FORBIDDEN_IMPORTS: dict[str, tuple[str, ...]] = {}


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
'''

ESLINT_CONFIG = """\
// Flat config. Requires: npm i -D eslint typescript-eslint
import tseslint from "typescript-eslint";

export default tseslint.config(
  ...tseslint.configs.recommended,
  { ignores: ["dist/", "node_modules/", "**/*.gen.*"] },
);
"""

PRETTIER_CONFIG = """\
{
  "printWidth": 100,
  "tabWidth": 2,
  "singleQuote": false,
  "trailingComma": "all"
}
"""

GOLANGCI_CONFIG = """\
# golangci-lint config. https://golangci-lint.run/
linters:
  enable:
    - gofmt
    - govet
    - staticcheck
    - errcheck
    - ineffassign
"""

RUSTFMT_CONFIG = """\
max_width = 100
edition = "2021"
"""


@dataclass
class Language:
    key: str
    label: str
    # path -> file contents, relative to the generated project root
    config_files: dict[str, str] = field(default_factory=dict)
    # YAML `repos:` entries (no leading indent), added to .pre-commit-config.yaml
    pre_commit_block: str = ""
    # YAML `steps:` entries (no leading indent), added to the CI quality job
    ci_steps: str = ""
    gitignore: list[str] = field(default_factory=list)
    # (label, shell command) pairs surfaced in the task runner / README
    quality_commands: list[tuple[str, str]] = field(default_factory=list)
    # Auto-detection signals for existing projects:
    detect_files: list[str] = field(default_factory=list)  # root markers (globs ok)
    detect_exts: list[str] = field(default_factory=list)  # source file extensions


REGISTRY: dict[str, Language] = {
    "python": Language(
        key="python",
        label="Python",
        config_files={
            "pyproject.toml": PYPROJECT_TOML,
            "tests/test_architecture.py": ARCH_TEST,
        },
        pre_commit_block="""\
- repo: https://github.com/astral-sh/ruff-pre-commit
  rev: v0.6.9
  hooks:
    - id: ruff
      args: [--fix]
    - id: ruff-format
- repo: https://github.com/pre-commit/mirrors-mypy
  rev: v1.13.0
  hooks:
    - id: mypy
""",
        ci_steps="""\
- uses: actions/setup-python@v5
  with:
    python-version: "3.12"
- run: pipx install ruff
- run: ruff check .
- run: ruff format --check .
""",
        gitignore=[
            "__pycache__/",
            "*.py[cod]",
            ".venv/",
            ".ruff_cache/",
            ".mypy_cache/",
            ".pytest_cache/",
        ],
        quality_commands=[
            ("lint", "ruff check ."),
            ("format", "ruff format ."),
            ("typecheck", "mypy ."),
            ("test", "pytest"),
        ],
        detect_files=["pyproject.toml", "setup.py", "setup.cfg", "requirements*.txt", "Pipfile"],
        detect_exts=[".py"],
    ),
    "node": Language(
        key="node",
        label="JavaScript / TypeScript",
        config_files={
            "eslint.config.mjs": ESLINT_CONFIG,
            ".prettierrc.json": PRETTIER_CONFIG,
        },
        pre_commit_block="""\
- repo: local
  hooks:
    - id: prettier
      name: prettier
      entry: npx prettier --write
      language: system
      files: \\.(js|jsx|ts|tsx|json|css|md)$
    - id: eslint
      name: eslint
      entry: npx eslint --fix
      language: system
      files: \\.(js|jsx|ts|tsx)$
""",
        ci_steps="""\
- uses: actions/setup-node@v4
  with:
    node-version: "20"
- run: npm ci || npm install
- run: npx prettier --check .
- run: npx eslint .
""",
        gitignore=["node_modules/", "dist/", ".next/", "*.tsbuildinfo"],
        quality_commands=[
            ("lint", "npx eslint ."),
            ("format", "npx prettier --check ."),
            ("typecheck", "npx tsc --noEmit"),
            ("test", "npm test --if-present"),
        ],
        detect_files=["package.json", "tsconfig.json"],
        detect_exts=[".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"],
    ),
    "go": Language(
        key="go",
        label="Go",
        config_files={".golangci.yml": GOLANGCI_CONFIG},
        pre_commit_block="""\
- repo: local
  hooks:
    - id: gofmt
      name: gofmt
      entry: gofmt -w
      language: system
      files: \\.go$
    - id: golangci-lint
      name: golangci-lint
      entry: golangci-lint run
      language: system
      pass_filenames: false
      types: [go]
""",
        ci_steps="""\
- uses: actions/setup-go@v5
  with:
    go-version: "1.22"
- uses: golangci/golangci-lint-action@v6
- run: test -z "$(gofmt -l .)"
""",
        gitignore=["bin/", "*.test", "vendor/"],
        quality_commands=[
            ("lint", "golangci-lint run"),
            ("format", "gofmt -w ."),
            ("typecheck", "go vet ./..."),
            ("test", "go test ./..."),
        ],
        detect_files=["go.mod"],
        detect_exts=[".go"],
    ),
    "rust": Language(
        key="rust",
        label="Rust",
        config_files={"rustfmt.toml": RUSTFMT_CONFIG},
        pre_commit_block="""\
- repo: local
  hooks:
    - id: cargo-fmt
      name: cargo fmt
      entry: cargo fmt --
      language: system
      files: \\.rs$
    - id: clippy
      name: cargo clippy
      entry: cargo clippy -- -D warnings
      language: system
      pass_filenames: false
      types: [rust]
""",
        ci_steps="""\
- uses: dtolnay/rust-toolchain@stable
  with:
    components: clippy, rustfmt
- run: cargo fmt --check
- run: cargo clippy -- -D warnings
""",
        gitignore=["target/", "Cargo.lock"],
        quality_commands=[
            ("lint", "cargo clippy"),
            ("format", "cargo fmt"),
            ("typecheck", "cargo check"),
            ("test", "cargo test"),
        ],
        detect_files=["Cargo.toml"],
        detect_exts=[".rs"],
    ),
}

# Directories never worth scanning when detecting languages on an existing project.
IGNORE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "target",
    "dist",
    "build",
    "vendor",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".next",
    ".idea",
    ".tox",
}


def get(keys: list[str]) -> list[Language]:
    return [REGISTRY[k] for k in keys if k in REGISTRY]


def detect_languages(root: Path) -> list[str]:
    """Return registry keys whose marker files or source extensions appear under ``root``.

    Used to auto-select linters when scaffolding into an existing project.
    """
    root = Path(root)
    if not root.is_dir():
        return []
    try:
        root_names = [p.name for p in root.iterdir()]
    except OSError:
        return []

    exts: set[str] = set()
    seen = 0
    for _dir, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")]
        for filename in filenames:
            exts.add(Path(filename).suffix)
        seen += len(filenames)
        if seen >= 20000:  # bound the walk on huge repos
            break

    detected = []
    for key, lang in REGISTRY.items():
        file_hit = any(fnmatch.fnmatch(n, pat) for n in root_names for pat in lang.detect_files)
        if file_hit or any(e in exts for e in lang.detect_exts):
            detected.append(key)
    return detected
