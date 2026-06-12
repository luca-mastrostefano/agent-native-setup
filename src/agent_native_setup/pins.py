"""Single registry of every version the wizard pins into generated output.

Pins rot as upstreams move releases forward — refresh them together here instead
of hunting string literals across the generators. Templates reference a pin as an
``@KEY@`` token and pass through :func:`sub`, which resolves it at import time
(no f-string/Jinja brace-escaping against the YAML/JSON/shell braces templates
are full of). A typo'd token fails loudly the moment the module imports.

The ``@vN`` GitHub Action majors (``actions/checkout@v6`` …) are deliberately
NOT here: the scaffolded Dependabot config keeps those fresh in generated repos.
"""

from __future__ import annotations

import re

PINS = {
    # Toolchains installed by the CI setup-* actions.
    # Node: the active LTS line. Go: the newest line golangci-lint v1 supports —
    # the golangci-lint-action v6 -> v8 migration (docs/improvements.md) unlocks 1.25+.
    "PYTHON_VERSION": "3.13",
    "NODE_VERSION": "24",
    "GO_VERSION": "1.24",
    # pre-commit hook revs (refresh: `pre-commit autoupdate`, or each repo's releases).
    "PRE_COMMIT_HOOKS_REV": "v6.0.0",
    "GITLEAKS_REV": "v8.30.1",
    "ACTIONLINT_PY_REV": "v1.7.12.24",
    "RUFF_PRE_COMMIT_REV": "v0.15.17",
    "MIRRORS_MYPY_REV": "v2.1.0",
    "HTML_HOOKS_NODEJS_REV": "v1.1.2",
    # lychee >= 0.16 hooks are `language: script` and self-install the binary via
    # cargo-binstall on first run; the rev MUST be a `lychee-v*` release tag
    # (the hook script exits 100 on a bare `vX.Y.Z` tag).
    "LYCHEE_HOOK_REV": "lychee-v0.24.2",
    # npm dev-toolchain ranges written into the generated package.json. eslint 10
    # and typescript 6.0 sit inside typescript-eslint's peer ranges
    # (eslint ^8.57||^9||^10, typescript >=4.8.4 <6.1.0 — checked 2026-06).
    "ESLINT_RANGE": "^10.4.1",
    "PRETTIER_RANGE": "^3.8.4",
    "TYPESCRIPT_RANGE": "^6.0.3",
    "TYPESCRIPT_ESLINT_RANGE": "^8.61.0",
    "HTMLHINT_VERSION": "1.9.2",
    # Third-party actions pinned to an exact release (not a floating major).
    "PIP_AUDIT_ACTION_REV": "v1.1.0",
}

_TOKEN_RE = re.compile(r"@([A-Z][A-Z0-9_]*)@")


def sub(template: str) -> str:
    """Resolve ``@KEY@`` pin tokens in a template string."""

    def _resolve(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in PINS:
            raise KeyError(f"unknown pin token @{key}@ — add it to pins.PINS")
        return PINS[key]

    return _TOKEN_RE.sub(_resolve, template)
