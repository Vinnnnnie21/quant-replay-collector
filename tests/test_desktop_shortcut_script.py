from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "create_desktop_shortcut.ps1"


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
    assert "C:\\Users\\32499" not in source
    assert "GetFolderPath" in source


def test_windows_build_produces_qrc_exe_and_uses_icon_only_when_available():
    source = (REPO_ROOT / "quant_collector_app" / "build_windows.bat").read_text(
        encoding="utf-8"
    )

    assert "--name QRC" in source
    assert "dist\\QRC.exe" in source
    assert 'if exist "assets\\app_icon.ico"' in source
    assert "--icon=assets\\app_icon.ico" in source


def test_shortcut_dry_run_uses_qrc_name_and_target_working_directory(tmp_path):
    target = tmp_path / "release" / "QRC.exe"
    target.parent.mkdir()
    target.write_bytes(b"MZ")
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
    assert not (desktop / "QRC.lnk").exists()


def test_shortcut_dry_run_reports_existing_icon_without_creating_link(tmp_path):
    target = tmp_path / "release" / "QRC.exe"
    target.parent.mkdir()
    target.write_bytes(b"MZ")
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
    desktop = tmp_path / "Desktop"
    expected_icon = REPO_ROOT / "quant_collector_app" / "assets" / "app_icon.ico"

    result = _dry_run(target=target, desktop=desktop, icon=None)
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert f"IconLocation={expected_icon}" in output
    assert not (desktop / "QRC.lnk").exists()


def test_shortcut_is_in_clean_package_and_documented():
    from scripts.clean_release import ROOT_CONTENT

    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    release = (REPO_ROOT / "docs" / "release.md").read_text(encoding="utf-8")

    assert "scripts/create_desktop_shortcut.ps1" in ROOT_CONTENT
    for text in (readme, release):
        assert "QRC.lnk" in text
        assert "quant_collector_app/assets/app_icon.ico" in text
        assert "create_desktop_shortcut.ps1" in text
