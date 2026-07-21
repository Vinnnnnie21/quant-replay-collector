from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from quant_collector_app.app_config import APP_VERSION


def _load_script():
    path = Path("scripts/write_release_manifest.py")
    spec = importlib.util.spec_from_file_location("write_release_manifest", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_onedir_manifest_is_reproducible_and_covers_entrypoint_hash(tmp_path):
    module = _load_script()
    package = tmp_path / "QRC"
    package.mkdir()
    executable = package / "QRC.exe"
    executable.write_bytes(b"MZ-current-release")
    internal = package / "_internal"
    internal.mkdir()
    (internal / "library.zip").write_bytes(b"runtime")

    first = module.write_release_manifest(package, "QRC.exe")
    first_bytes = (package / "release-manifest.json").read_bytes()
    second = module.write_release_manifest(package, "QRC.exe")

    assert second == first
    assert (package / "release-manifest.json").read_bytes() == first_bytes
    assert first["application_version"] == APP_VERSION
    assert first["database_schema_version"] == 19
    assert first["package_format"] == "onedir"
    assert first["build_time_utc"].endswith("Z")
    assert first["git_commit"]
    assert isinstance(first["git_worktree_dirty"], bool)
    assert first["python_version"]
    assert first["qt_version"]
    assert first["native_launch_verified"] is False
    assert first["entrypoint"] == "QRC.exe"
    assert first["entrypoint_sha256"] == next(
        row["sha256"] for row in first["files"] if row["path"] == "QRC.exe"
    )
    assert {row["path"] for row in first["files"]} == {
        "QRC.exe",
        "_internal/library.zip",
    }
    json.loads(first_bytes.decode("utf-8"))


def test_manifest_rejects_entrypoint_outside_package(tmp_path):
    module = _load_script()
    package = tmp_path / "QRC"
    package.mkdir()
    outside = tmp_path / "old-QRC.exe"
    outside.write_bytes(b"MZ-old")

    try:
        module.write_release_manifest(package, outside)
    except ValueError as exc:
        assert "inside" in str(exc)
    else:
        raise AssertionError("outside entrypoint was accepted")


def test_manifest_refuses_a_windows_junction_in_the_package(tmp_path, monkeypatch):
    module = _load_script()
    package = tmp_path / "QRC"
    package.mkdir()
    executable = package / "QRC.exe"
    executable.write_bytes(b"MZ-current-release")
    junction = package / "_internal"
    junction.mkdir()
    (junction / "private.db").write_bytes(b"outside")
    original_is_junction = getattr(Path, "is_junction", None)

    def fake_is_junction(path):
        if Path(path) == junction:
            return True
        return bool(original_is_junction(path)) if original_is_junction else False

    monkeypatch.setattr(Path, "is_junction", fake_is_junction, raising=False)

    with pytest.raises(ValueError, match="link"):
        module.write_release_manifest(package, executable)

    assert not (package / "release-manifest.json").exists()
