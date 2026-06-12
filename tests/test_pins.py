"""The pin registry: tokens resolve, typos fail loudly, nothing leaks into output."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_native_setup import cli
from agent_native_setup.config import WizardConfig
from agent_native_setup.languages import REGISTRY
from agent_native_setup.pins import PINS, sub
from agent_native_setup.scaffold import Scaffolder

_TOKEN = re.compile(rb"@[A-Z][A-Z0-9_]*@")


def test_sub_resolves_known_tokens() -> None:
    assert sub('node-version: "@NODE_VERSION@"') == f'node-version: "{PINS["NODE_VERSION"]}"'


def test_sub_unknown_token_raises() -> None:
    with pytest.raises(KeyError, match="NO_SUCH_PIN"):
        sub("rev: @NO_SUCH_PIN@")


@pytest.mark.parametrize("existing", [False, True])  # greenfield and ratchet CI variants
def test_no_unresolved_token_reaches_generated_output(tmp_path: Path, existing: bool) -> None:
    # Kitchen-sink scaffold (every language, every part): a pin token that was never
    # routed through sub() would ship verbatim in someone's repo.
    config = WizardConfig(
        project_name="demo",
        output_dir=tmp_path,
        languages=list(REGISTRY),
        init_git=False,
        existing_project=existing,
    )
    cli.build(config, Scaffolder(config.target))
    leftovers = [
        str(p.relative_to(tmp_path))
        for p in tmp_path.rglob("*")
        if p.is_file() and _TOKEN.search(p.read_bytes())
    ]
    assert leftovers == []


def test_pinned_versions_land_in_the_workflow(tmp_path: Path) -> None:
    # The wiring test: the registry values are what generated CI actually pins.
    config = WizardConfig(
        project_name="demo", output_dir=tmp_path, languages=["python", "node"], init_git=False
    )
    cli.build(config, Scaffolder(config.target))
    wf = (tmp_path / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    assert f'python-version: "{PINS["PYTHON_VERSION"]}"' in wf
    assert f'node-version: "{PINS["NODE_VERSION"]}"' in wf
