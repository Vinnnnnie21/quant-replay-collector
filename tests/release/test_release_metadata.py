from __future__ import annotations

from pathlib import Path

import quant_collector_app

from quant_collector_app.app_config import APP_VERSION
from quant_collector_app.version import __version__ as canonical_version
from scripts.clean_release import DEFAULT_OUTPUT, RELEASE_VERSION
from project_paths import APP_DIR, REPO_ROOT


def test_release_metadata_uses_one_version():
    assert canonical_version == "1.6.0"
    assert APP_VERSION == canonical_version
    assert quant_collector_app.__version__ == APP_VERSION
    assert RELEASE_VERSION == f"v{APP_VERSION}"
    assert DEFAULT_OUTPUT.name == f"QuantReplayCollector-v{APP_VERSION}-Clean"
    assert f"## v{APP_VERSION} -" in Path("CHANGELOG.md").read_text(encoding="utf-8")


def test_current_application_and_release_scripts_contain_no_prerelease_version():
    paths = [
        *APP_DIR.rglob("*.py"),
        *APP_DIR.rglob("*.bat"),
        *(REPO_ROOT / "scripts").glob("*.py"),
        *(REPO_ROOT / "scripts").glob("*.ps1"),
        REPO_ROOT / "run_app.py",
        REPO_ROOT / "run_app.pyw",
    ]
    offenders = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in paths
        if "1.6.0-rc" in path.read_text(encoding="utf-8", errors="ignore")
    ]

    assert offenders == []


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


def test_dependency_lock_header_names_the_current_release():
    lock_text = Path("requirements-lock.txt").read_text(encoding="utf-8")

    assert f"Quant Replay Collector v{canonical_version}." in lock_text
    assert "v1.5.2" not in lock_text


def test_current_release_guide_uses_formal_v160_commands():
    current_section = Path("docs/release.md").read_text(encoding="utf-8").split(
        "## v1.5.0 Release Notes",
        maxsplit=1,
    )[0]

    assert "QuantReplayCollector-v1.6.0-Clean" in current_section
    assert "qrc-v160-native-validation" in current_section
    assert "QuantReplayCollector-v1.5.1-Clean" not in current_section
    assert "qrc-rc2-native-validation" not in current_section


def test_entry_behavior_model_runtime_is_locked_for_windows_python_313():
    locked = Path("requirements-lock.txt").read_text(encoding="utf-8")
    app_requirements = Path("quant_collector_app/requirements.txt").read_text(
        encoding="utf-8"
    )
    health_source = Path("quant_collector_app/app_health.py").read_text(
        encoding="utf-8"
    )

    assert "scikit-learn==1.9.0" in locked
    assert "scipy==1.18.0" in locked
    assert "joblib==1.5.3" in locked
    assert "narwhals==2.24.0" in locked
    assert "threadpoolctl==3.6.0" in locked
    assert "scikit-learn==1.9.0" in app_requirements
    assert '"sklearn"' in health_source
