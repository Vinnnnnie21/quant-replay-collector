from __future__ import annotations

import json

from scripts.clean_release import build_release


def test_public_clean_release_report_omits_local_paths_and_skipped_file_names(tmp_path):
    source = tmp_path / "private-source"
    output = tmp_path / "private-output"
    (source / "quant_collector_app" / "data" / "cache").mkdir(parents=True)
    (source / "quant_collector_app" / "main.py").write_text("pass\n", encoding="utf-8")
    (source / "quant_collector_app" / "data" / "cache" / "BTCUSDT-2026-01.csv").write_text(
        "private\n",
        encoding="utf-8",
    )
    (source / "docs" / "agents").mkdir(parents=True)
    (source / "docs" / "agents" / "domain.md").write_text("local workflow\n", encoding="utf-8")
    (source / "README.md").write_text("readme\n", encoding="utf-8")

    report = build_release(output, source)
    report_json = (output / "clean_release_report.json").read_text(encoding="utf-8")
    report_markdown = (output / "clean_release_report.md").read_text(encoding="utf-8")
    parsed = json.loads(report_json)

    assert report["public_report"] is True
    assert "source_root" not in parsed
    assert "output_dir" not in parsed
    assert "skipped_files" not in parsed
    assert "copied_files" not in parsed
    assert "skipped_count_by_reason" in parsed
    assert parsed["skipped_count_by_reason"]["local_agent_files"] == 1
    assert str(source) not in report_json
    assert str(output) not in report_json
    assert str(source) not in report_markdown
    assert str(output) not in report_markdown
    assert "BTCUSDT-2026-01.csv" not in report_json
    assert "BTCUSDT-2026-01.csv" not in report_markdown
    assert not (output / "docs" / "agents").exists()


def test_private_report_details_require_explicit_opt_in(tmp_path):
    source = tmp_path / "source"
    output = tmp_path / "out"
    (source / "README.md").parent.mkdir(parents=True)
    (source / "README.md").write_text("readme\n", encoding="utf-8")

    report = build_release(output, source, include_private_report=True)

    assert report["public_report"] is False
    assert report["source_root"] == str(source.resolve())
    assert report["output_dir"] == str(output.resolve())
    assert "copied_files" in report
    assert "skipped_files" in report
