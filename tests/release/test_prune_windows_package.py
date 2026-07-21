from __future__ import annotations

from pathlib import Path

import pytest

from project_paths import APP_DIR
from scripts.prune_windows_package import prune_windows_package


def test_prune_removes_only_known_dependency_test_and_sample_trees(tmp_path):
    package = tmp_path / "QRC"
    pyarrow_tests = package / "_internal" / "pyarrow" / "tests" / "data"
    sklearn_samples = package / "_internal" / "sklearn" / "datasets" / "data"
    pyarrow_tests.mkdir(parents=True)
    sklearn_samples.mkdir(parents=True)
    (pyarrow_tests / "sample.parquet").write_bytes(b"sample")
    (sklearn_samples / "sample.csv").write_text("sample", encoding="utf-8")
    keep = package / "_internal" / "pyarrow" / "__init__.py"
    keep.write_text("keep", encoding="utf-8")

    removed = prune_windows_package(package)

    assert set(removed) == {
        "_internal/pyarrow/tests",
        "_internal/sklearn/datasets",
    }
    assert not pyarrow_tests.exists()
    assert not sklearn_samples.exists()
    assert keep.read_text(encoding="utf-8") == "keep"


def test_windows_build_prunes_before_archive_verification():
    source = (APP_DIR / "build_windows.bat").read_text(encoding="utf-8")

    prune = source.index("prune_windows_package.py")
    verify = source.index("verify_frozen_archive.py")
    assert prune < verify


def test_prune_refuses_a_windows_junction_target(tmp_path, monkeypatch):
    package = tmp_path / "QRC"
    target = package / "_internal" / "pyarrow" / "tests"
    target.mkdir(parents=True)
    (target / "keep.txt").write_text("keep", encoding="utf-8")
    original_is_junction = getattr(Path, "is_junction", None)

    def fake_is_junction(path):
        if Path(path) == target:
            return True
        return bool(original_is_junction(path)) if original_is_junction else False

    monkeypatch.setattr(Path, "is_junction", fake_is_junction, raising=False)

    with pytest.raises(ValueError, match="link"):
        prune_windows_package(package)

    assert (target / "keep.txt").read_text(encoding="utf-8") == "keep"
