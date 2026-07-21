from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

def _load_script():
    path = Path("scripts/cleanup_test_artifacts.py")
    spec = importlib.util.spec_from_file_location("cleanup_test_artifacts", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cleanup_is_dry_run_by_default_and_never_touches_legacy_roots(tmp_path):
    module = _load_script()
    artifact = tmp_path / ".test-artifacts" / "pytest-tmp" / "case"
    artifact.mkdir(parents=True)
    (artifact / "result.txt").write_text("ok", encoding="utf-8")
    legacy = tmp_path / ".pytest_tmp_user_asset"
    legacy.mkdir()
    (legacy / "keep.txt").write_text("keep", encoding="utf-8")
    unknown = tmp_path / ".test-artifacts" / "user-note"
    unknown.write_text("keep", encoding="utf-8")

    report = module.cleanup_test_artifacts(tmp_path)

    assert report.planned == (Path("pytest-tmp"),)
    assert report.removed == ()
    assert artifact.exists()
    assert legacy.exists()
    assert unknown.exists()


def test_cleanup_apply_removes_only_the_scoped_artifact_contents(tmp_path):
    module = _load_script()
    artifact_root = tmp_path / ".test-artifacts"
    (artifact_root / "pytest-cache").mkdir(parents=True)
    (artifact_root / "pytest-cache" / "state").write_text("x", encoding="utf-8")
    unrelated = tmp_path / "user-report.txt"
    unrelated.write_text("keep", encoding="utf-8")

    report = module.cleanup_test_artifacts(tmp_path, apply=True)

    assert report.removed == (Path("pytest-cache"),)
    assert report.failures == ()
    assert artifact_root.exists()
    assert tuple(artifact_root.iterdir()) == ()
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_cleanup_recognizes_the_release_scoped_pytest_root(tmp_path):
    scoped = tmp_path / ".test-artifacts" / "v1.6.0" / "pytest-tmp"
    scoped.mkdir(parents=True)
    (scoped / "result.txt").write_text("ok", encoding="utf-8")

    module = _load_script()
    report = module.cleanup_test_artifacts(tmp_path, apply=True)

    assert report.removed == (Path("v1.6.0"),)
    assert report.failures == ()
    assert not scoped.exists()


def test_cleanup_recognizes_only_process_scoped_pytest_run_prefix(tmp_path):
    artifact_root = tmp_path / ".test-artifacts"
    run = artifact_root / "pytest-tmp-run-123-abc"
    keep = artifact_root / "pytest-tmp-user-note"
    run.mkdir(parents=True)
    keep.mkdir()

    module = _load_script()
    report = module.cleanup_test_artifacts(tmp_path)

    assert report.planned == (Path("pytest-tmp-run-123-abc"),)
    assert keep.exists()


def test_cleanup_refuses_an_artifact_root_that_is_not_a_directory(tmp_path):
    module = _load_script()
    artifact_root = tmp_path / ".test-artifacts"
    artifact_root.write_text("not a directory", encoding="utf-8")

    try:
        module.cleanup_test_artifacts(tmp_path, apply=True)
    except ValueError as exc:
        assert "real directory" in str(exc)
    else:
        raise AssertionError("unsafe artifact root was accepted")

    assert artifact_root.read_text(encoding="utf-8") == "not a directory"


def test_cleanup_never_removes_a_windows_junction_child(tmp_path, monkeypatch):
    module = _load_script()
    child = tmp_path / ".test-artifacts" / "pytest-cache"
    child.mkdir(parents=True)
    (child / "keep.txt").write_text("keep", encoding="utf-8")

    original_is_junction = getattr(Path, "is_junction", None)

    def fake_is_junction(path):
        if Path(path) == child:
            return True
        return bool(original_is_junction(path)) if original_is_junction else False

    monkeypatch.setattr(Path, "is_junction", fake_is_junction, raising=False)

    report = module.cleanup_test_artifacts(tmp_path, apply=True)

    assert report.removed == ()
    assert report.failures == ((Path("pytest-cache"), "symbolic links and junctions are not followed"),)
    assert (child / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_cleanup_reports_acl_failure_and_continues_with_next_known_root(
    tmp_path,
    monkeypatch,
    capsys,
):
    module = _load_script()
    artifact_root = tmp_path / ".test-artifacts"
    cache = artifact_root / "pytest-cache"
    temporary = artifact_root / "pytest-tmp"
    cache.mkdir(parents=True)
    temporary.mkdir()
    original_rmtree = module.shutil.rmtree

    def fail_cache(path):
        if Path(path).name == "pytest-cache":
            raise PermissionError("ACL denied")
        original_rmtree(path)

    monkeypatch.setattr(module.shutil, "rmtree", fail_cache)

    report = module.cleanup_test_artifacts(tmp_path, apply=True)

    assert cache.exists()
    assert not temporary.exists()
    assert report.removed == (Path("pytest-tmp"),)
    assert report.failures[0][0] == Path("pytest-cache")
    assert "ACL denied" in report.failures[0][1]
    assert capsys.readouterr().out == ""
