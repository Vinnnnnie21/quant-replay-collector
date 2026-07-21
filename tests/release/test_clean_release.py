from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.clean_release import ROOT_CONTENT, build_release, excluded_reason


def test_clean_release_includes_the_windowed_root_launcher():
    assert "run_app.pyw" in ROOT_CONTENT
    assert "requirements-lock.txt" in ROOT_CONTENT
    assert "scripts/cleanup_test_artifacts.py" in ROOT_CONTENT
    assert "scripts/write_release_manifest.py" in ROOT_CONTENT


def test_excluded_runtime_paths():
    for value in [
        ".venv/Lib/site-packages/private.py",
        "Backup/source.py",
        "dist/previous/archive.zip",
        "performance_reports/startup_profile.json",
        ".pytest_cache/x",
        ".test-artifacts/pytest-tmp/output.txt",
        "quant_collector_app/__pycache__/main.pyc",
        "quant_collector_app/data/cache/bars.csv",
        "quant_collector_app/data/research_snapshots/snapshot-1/export_manifest.json",
        "quant_collector_app/data/quant_replay.db",
        "quant_collector_app/logs/app.log",
        "quant_collector_app/logs/.gitkeep",
        "quant_collector_app/data/app_settings.json",
        "quant_collector_app/.env",
        "docs/local.sqlite",
        "tests/debug.log",
        "tests/local-release.zip",
    ]:
        assert excluded_reason(Path(value)) is not None


def test_build_release_skips_user_runtime_data(tmp_path):
    source = tmp_path / "source"
    output = tmp_path / "out"
    (source / "quant_collector_app" / "data" / "cache").mkdir(parents=True)
    (source / "quant_collector_app" / "main.py").write_text("pass\n", encoding="utf-8")
    (source / "quant_collector_app" / "data" / "cache" / "bars.csv").write_text("x\n", encoding="utf-8")
    (source / "quant_collector_app" / "data" / "local.db").write_bytes(b"db")
    (source / "quant_collector_app" / ".env").write_text("TOKEN=private\n", encoding="utf-8")
    (source / "quant_collector_app" / "local.sqlite").write_bytes(b"sqlite")
    (source / "quant_collector_app" / "logs").mkdir(parents=True)
    (source / "quant_collector_app" / "logs" / ".gitkeep").write_text("\n", encoding="utf-8")
    (source / "README.md").write_text("readme\n", encoding="utf-8")
    (source / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")

    report = build_release(output, source)

    assert (output / "README.md").exists()
    assert (output / "pytest.ini").exists()
    assert (output / "quant_collector_app" / "main.py").exists()
    assert not (output / "quant_collector_app" / "data" / "cache" / "bars.csv").exists()
    assert not (output / "quant_collector_app" / "data" / "local.db").exists()
    assert not (output / "quant_collector_app" / ".env").exists()
    assert not (output / "quant_collector_app" / "local.sqlite").exists()
    assert not (output / "quant_collector_app" / "logs").exists()
    assert (output / "clean_release_report.json").exists()
    assert (output / "clean_release_report.md").exists()
    assert report["skipped_file_count"] == 5


def test_build_release_refuses_to_delete_an_existing_unmarked_output(tmp_path):
    source = tmp_path / "source"
    output = tmp_path / "unrelated-output"
    source.mkdir()
    output.mkdir()
    (source / "README.md").write_text("readme\n", encoding="utf-8")
    protected = output / "keep.txt"
    protected.write_text("user-owned\n", encoding="utf-8")

    with pytest.raises(ValueError, match="generated clean release"):
        build_release(output, source)

    assert protected.read_text(encoding="utf-8") == "user-owned\n"


def test_build_release_can_replace_its_own_marked_output(tmp_path):
    source = tmp_path / "source"
    output = tmp_path / "clean-output"
    source.mkdir()
    output.mkdir()
    (source / "README.md").write_text("current\n", encoding="utf-8")
    (output / "stale.txt").write_text("stale\n", encoding="utf-8")
    (output / "clean_release_report.json").write_text(
        json.dumps({"project": "Quant Replay Collector"}),
        encoding="utf-8",
    )

    build_release(output, source)

    assert (output / "README.md").read_text(encoding="utf-8") == "current\n"
    assert not (output / "stale.txt").exists()


def test_build_release_does_not_follow_source_symbolic_links(tmp_path, monkeypatch):
    source = tmp_path / "source"
    output = tmp_path / "clean-output"
    (source / "docs").mkdir(parents=True)
    link = source / "docs" / "linked-secret.txt"
    link.write_text("private\n", encoding="utf-8")
    original_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda self: self == link or original_is_symlink(self),
    )

    report = build_release(output, source)

    assert not (output / "docs" / "linked-secret.txt").exists()
    assert report["skipped_count_by_reason"]["symbolic_link"] == 1
