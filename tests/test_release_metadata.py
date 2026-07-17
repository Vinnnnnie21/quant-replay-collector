from __future__ import annotations

from pathlib import Path

import quant_collector_app

from quant_collector_app.app_config import APP_VERSION
from scripts.clean_release import DEFAULT_OUTPUT, RELEASE_VERSION


def test_release_metadata_uses_one_version():
    assert APP_VERSION == "1.5.2"
    assert quant_collector_app.__version__ == APP_VERSION
    assert RELEASE_VERSION == f"v{APP_VERSION}"
    assert DEFAULT_OUTPUT.name == f"QuantReplayCollector-v{APP_VERSION}-Clean"
    assert f"## v{APP_VERSION} -" in Path("CHANGELOG.md").read_text(encoding="utf-8")


def test_supported_ci_runtime_and_default_install_are_locked():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    root_requirements = Path("requirements.txt").read_text(encoding="utf-8")
    locked_lines = [
        line.strip()
        for line in Path("requirements-lock.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert 'python-version: "3.13"' in workflow
    assert "-r requirements-lock.txt" in root_requirements
    assert locked_lines
    assert all("==" in line for line in locked_lines)
