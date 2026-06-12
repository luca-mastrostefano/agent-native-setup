"""Auto-format a just-edited file (a Claude Code PostToolUse hook helper).

Reads the hook event JSON from stdin, pulls the edited file's path, and runs
the project's formatter for that file type, so an agent's edit never reaches
the format gate unformatted. Best-effort by design: any miss (no formatter on
PATH, unknown extension, missing file, bad JSON) exits 0 silently — pre-commit
remains the enforcer; this hook only saves the round-trip.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

# file extension -> formatter argv (the file's path is appended)
FORMATTERS: dict[str, list[str]] = {
    ".py": ["ruff", "format"],
}


def format_command(path_str: str) -> list[str] | None:
    """The formatter invocation for ``path_str``, or None when nothing applies."""
    path = Path(path_str)
    cmd = FORMATTERS.get(path.suffix)
    if not cmd or not path.is_file() or shutil.which(cmd[0]) is None:
        return None
    return [*cmd, path_str]


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(event, dict):
        return 0
    tool_input = event.get("tool_input") or {}
    cmd = format_command(str(tool_input.get("file_path") or ""))
    if cmd:
        subprocess.run(cmd, capture_output=True, check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
