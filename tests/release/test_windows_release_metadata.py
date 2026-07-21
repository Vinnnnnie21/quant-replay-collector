from __future__ import annotations

from pathlib import Path

from project_paths import APP_DIR, REPO_ROOT


def test_windows_release_metadata_is_derived_from_canonical_version(tmp_path):
    from quant_collector_app.release_metadata import (
        WINDOWS_FILE_VERSION,
        WINDOWS_PACKAGE_BASENAME,
    )
    from scripts.write_windows_version_info import write_windows_build_metadata

    version_file = tmp_path / "qrc-version-info.txt"
    batch_file = tmp_path / "qrc-release-env.bat"
    write_windows_build_metadata(version_file=version_file, batch_file=batch_file)

    assert WINDOWS_FILE_VERSION == "1.6.0.0"
    assert WINDOWS_PACKAGE_BASENAME == "QRC-v1.6.0-Windows-x64"
    version_text = version_file.read_text(encoding="utf-8")
    batch_text = batch_file.read_text(encoding="utf-8")
    assert "filevers=(1, 6, 0, 0)" in version_text
    assert "prodvers=(1, 6, 0, 0)" in version_text
    assert "FileVersion', '1.6.0.0'" in version_text
    assert "ProductVersion', '1.6.0'" in version_text
    assert 'QRC_PACKAGE_NAME=QRC-v1.6.0-Windows-x64' in batch_text


def test_windows_build_uses_generated_version_resource():
    source = (APP_DIR / "build_windows.bat").read_text(encoding="utf-8")

    assert "write_windows_version_info.py" in source
    assert "--version-file" in source
    assert "qrc-release-env.bat" in source
    assert "QRC_PACKAGE_NAME" in source
    assert "1.6.0-rc" not in source
    assert "scripts/write_windows_version_info.py" in (
        REPO_ROOT / "scripts" / "clean_release.py"
    ).read_text(encoding="utf-8")


def test_windows_build_prefers_the_locked_repository_runtime():
    source = (APP_DIR / "build_windows.bat").read_text(encoding="utf-8")

    venv_check = source.index('if exist "..\\.venv\\Scripts\\python.exe"')
    launcher_fallback = source.index("where py")
    assert venv_check < launcher_fallback
    assert 'set "PYTHON_CMD=..\\.venv\\Scripts\\python.exe"' in source
    assert "-r ..\\requirements-lock.txt" in source
    assert "-r requirements.txt" not in source
    isolation = source.index('set "PYTHONNOUSERSITE=1"')
    isolated_user_base = source.index('set "PYTHONUSERBASE=%CD%\\build\\isolated-python-user"')
    pyinstaller = source.index("-m PyInstaller")
    assert isolation < pyinstaller
    assert isolated_user_base < pyinstaller


def test_windows_build_excludes_dependency_test_and_sample_datasets():
    source = (APP_DIR / "build_windows.bat").read_text(encoding="utf-8")

    for module in ("pytest", "pyarrow.tests", "sklearn.datasets"):
        assert f"--exclude-module={module}" in source
