from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile

import pytest

from quant_collector_app.app_config import APP_VERSION
from quant_collector_app.release_metadata import WINDOWS_PACKAGE_BASENAME
from project_paths import REPO_ROOT
from scripts.package_windows_release import package_windows_release


def _verified_package(tmp_path):
    package = tmp_path / "QRC"
    package.mkdir()
    executable = package / "QRC.exe"
    executable.write_bytes(b"MZ-formal")
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    (package / "release-manifest.json").write_text(
        json.dumps(
            {
                "application_version": APP_VERSION,
                "package_format": "onedir",
                "native_launch_verified": True,
                "entrypoint": "QRC.exe",
                "entrypoint_sha256": digest,
            }
        ),
        encoding="utf-8",
    )
    return package


def test_verified_onedir_is_atomically_packaged_under_formal_windows_name(tmp_path):
    package = _verified_package(tmp_path)

    archive = package_windows_release(package, tmp_path / "release")

    assert archive.name == f"{WINDOWS_PACKAGE_BASENAME}.zip"
    assert archive.is_file()
    with zipfile.ZipFile(archive) as bundle:
        assert set(bundle.namelist()) == {
            f"{WINDOWS_PACKAGE_BASENAME}/QRC.exe",
            f"{WINDOWS_PACKAGE_BASENAME}/release-manifest.json",
        }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("application_version", "1.5.2"),
        ("package_format", "onefile"),
        ("native_launch_verified", False),
        ("entrypoint_sha256", "0" * 64),
    ],
)
def test_packaging_refuses_unverified_or_mismatched_build(tmp_path, field, value):
    package = _verified_package(tmp_path)
    manifest_path = package / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[field] = value
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError):
        package_windows_release(package, tmp_path / "release")


def test_packaging_cli_resolves_project_modules_outside_repository_cwd(tmp_path):
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "package_windows_release.py"),
            "--help",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_packaging_refuses_a_windows_junction_in_the_package(tmp_path, monkeypatch):
    package = _verified_package(tmp_path)
    junction = package / "_internal"
    junction.mkdir()
    (junction / "private.db").write_bytes(b"outside")
    original_is_junction = getattr(type(junction), "is_junction", None)

    def fake_is_junction(path):
        if path == junction:
            return True
        return bool(original_is_junction(path)) if original_is_junction else False

    monkeypatch.setattr(type(junction), "is_junction", fake_is_junction, raising=False)

    with pytest.raises(ValueError, match="link"):
        package_windows_release(package, tmp_path / "release")

    assert not (tmp_path / "release" / f"{WINDOWS_PACKAGE_BASENAME}.zip").exists()
