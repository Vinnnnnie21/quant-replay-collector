from __future__ import annotations

from pathlib import Path

from scripts.clean_release import build_release, excluded_reason


def test_excluded_runtime_paths():
    for value in [
        ".venv/Lib/site-packages/private.py",
        "Backup/source.py",
        "dist/previous/archive.zip",
        "performance_reports/startup_profile.json",
        ".pytest_cache/x",
        "quant_collector_app/__pycache__/main.pyc",
        "quant_collector_app/data/cache/bars.csv",
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
