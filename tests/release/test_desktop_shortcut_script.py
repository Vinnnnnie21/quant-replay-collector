from __future__ import annotations

import shutil
import subprocess
import hashlib
import json
from pathlib import Path

import pytest

from quant_collector_app.app_config import APP_VERSION
from project_paths import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts" / "create_desktop_shortcut.ps1"


def _write_manifest(target: Path, *, version: str = APP_VERSION) -> Path:
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    path = target.parent / "release-manifest.json"
    path.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "application_version": version,
                "database_schema_version": 19,
                "package_format": "onedir",
                "entrypoint": target.name,
                "entrypoint_sha256": digest,
                "native_launch_verified": True,
            }
        ),
        encoding="utf-8",
    )
    return path


def _powershell() -> str:
    executable = shutil.which("powershell.exe") or shutil.which("powershell")
    if not executable:
        pytest.skip("Windows PowerShell is unavailable")
    return executable


def _dry_run(
    *, target: Path, desktop: Path, icon: Path | None, shortcut_name: str | None = None
) -> subprocess.CompletedProcess[str]:
    command = [
        _powershell(),
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SCRIPT),
        "-TargetPath",
        str(target),
        "-DesktopPath",
        str(desktop),
        "-DryRun",
    ]
    if icon is not None:
        command.extend(["-IconPath", str(icon)])
    if shortcut_name is not None:
        command.extend(["-ShortcutName", shortcut_name])
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_shortcut_script_is_parameterized_and_has_no_developer_user_path():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "TargetPath" in source
    assert "DesktopPath" in source
    assert "IconPath" in source
    assert "ShortcutName" in source
    assert "DryRun" in source
    assert "ManifestPath" in source
    assert "ExpectedVersion" in source
    assert "C:\\Users\\32499" not in source
    assert "GetFolderPath" in source


def test_shortcut_script_builds_a_temporary_link_before_atomic_replace():
    source = SCRIPT.read_text(encoding="utf-8")

    create_index = source.index("CreateShortcut($temporaryShortcut)")
    save_index = source.index("$shortcut.Save()")
    replace_index = source.index("Move-Item -LiteralPath $temporaryShortcut")

    assert create_index < save_index < replace_index
    assert "CreateShortcut($shortcutPath)" not in source
    assert "Test-Path -LiteralPath $temporaryShortcut" in source


def test_windows_build_produces_qrc_exe_and_uses_icon_only_when_available():
    source = (REPO_ROOT / "quant_collector_app" / "build_windows.bat").read_text(
        encoding="utf-8"
    )

    assert "--name QRC" in source
    assert "--onedir" in source
    assert "--onefile" not in source
    assert "dist\\QRC\\QRC.exe" in source
    assert "write_release_manifest.py" in source
    assert 'if exist "assets\\app_icon.ico"' in source
    assert "--icon=assets\\app_icon.ico" in source
    assert "--add-data=translations;translations" in source


def test_shortcut_dry_run_uses_qrc_name_and_target_working_directory(tmp_path):
    target = tmp_path / "release" / "QRC.exe"
    target.parent.mkdir()
    target.write_bytes(b"MZ")
    _write_manifest(target)
    desktop = tmp_path / "Desktop"
    missing_icon = tmp_path / "quant_collector_app" / "assets" / "app_icon.ico"

    result = _dry_run(target=target, desktop=desktop, icon=missing_icon)
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert f"ShortcutPath={desktop / 'QRC.lnk'}" in output
    assert f"TargetPath={target}" in output
    assert f"WorkingDirectory={target.parent}" in output
    assert "IconLocation=<application default>" in output
    assert "Icon file not found" in output
    assert "DryRun=True" in output
    assert f"ValidatedVersion={APP_VERSION}" in output
    assert not (desktop / "QRC.lnk").exists()


def test_shortcut_dry_run_reports_existing_icon_without_creating_link(tmp_path):
    target = tmp_path / "release" / "QRC.exe"
    target.parent.mkdir()
    target.write_bytes(b"MZ")
    _write_manifest(target)
    desktop = tmp_path / "Desktop"
    icon = tmp_path / "assets" / "app_icon.ico"
    icon.parent.mkdir()
    icon.write_bytes(b"icon")

    result = _dry_run(
        target=target,
        desktop=desktop,
        icon=icon,
        shortcut_name="QRC",
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert f"IconLocation={icon}" in output
    assert not (desktop / "QRC.lnk").exists()


def test_shortcut_dry_run_uses_bundled_icon_by_default(tmp_path):
    target = tmp_path / "release" / "QRC.exe"
    target.parent.mkdir()
    target.write_bytes(b"MZ")
    _write_manifest(target)
    desktop = tmp_path / "Desktop"
    expected_icon = target.parent / "_internal" / "assets" / "app_icon.ico"
    expected_icon.parent.mkdir(parents=True)
    expected_icon.write_bytes(b"packaged-icon")

    result = _dry_run(target=target, desktop=desktop, icon=None)
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert f"IconLocation={expected_icon}" in output
    assert not (desktop / "QRC.lnk").exists()


def test_shortcut_dry_run_refuses_target_without_release_manifest(tmp_path):
    target = tmp_path / "release" / "QRC.exe"
    target.parent.mkdir()
    target.write_bytes(b"MZ")

    result = _dry_run(
        target=target,
        desktop=tmp_path / "Desktop",
        icon=None,
    )

    assert result.returncode != 0
    assert "manifest" in (result.stdout + result.stderr).lower()


def test_shortcut_dry_run_refuses_target_that_no_longer_matches_manifest(tmp_path):
    target = tmp_path / "release" / "QRC.exe"
    target.parent.mkdir()
    target.write_bytes(b"MZ-current")
    _write_manifest(target)
    target.write_bytes(b"MZ-stale-or-replaced")

    result = _dry_run(
        target=target,
        desktop=tmp_path / "Desktop",
        icon=None,
    )

    assert result.returncode != 0
    assert "hash" in (result.stdout + result.stderr).lower()


def test_shortcut_dry_run_refuses_package_without_native_launch_gate(tmp_path):
    target = tmp_path / "release" / "QRC.exe"
    target.parent.mkdir()
    target.write_bytes(b"MZ-current")
    manifest = _write_manifest(target)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["native_launch_verified"] = False
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    result = _dry_run(
        target=target,
        desktop=tmp_path / "Desktop",
        icon=None,
    )

    assert result.returncode != 0
    assert "native" in (result.stdout + result.stderr).lower()


def test_shortcut_is_in_clean_package_and_documented():
    from scripts.clean_release import ROOT_CONTENT

    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    release = (REPO_ROOT / "docs" / "release.md").read_text(encoding="utf-8")

    assert "scripts/create_desktop_shortcut.ps1" in ROOT_CONTENT
    for text in (readme, release):
        assert "QRC.lnk" in text
        assert "quant_collector_app/assets/app_icon.ico" in text
        assert "create_desktop_shortcut.ps1" in text
        assert "ExecutionPolicy Bypass" in text
