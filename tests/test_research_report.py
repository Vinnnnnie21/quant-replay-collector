from __future__ import annotations

import json

from research.dataset import run_research_pack
from test_feature_label_separation import research_input


def test_research_pack_writes_report_and_manifest(tmp_path):
    windows, events, trades = research_input(40)
    result = run_research_pack(tmp_path, windows, events, trades)
    report_path = tmp_path / "research_report.md"
    manifest_path = tmp_path / "research_manifest.json"
    assert report_path.exists()
    assert manifest_path.exists()
    text = report_path.read_text(encoding="utf-8")
    assert "未来函数审计" in text
    assert "候选规则不是交易信号" in text
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["experiment_id"].startswith("exp_")
    assert len(manifest["dataset_hash"]) == 64
    assert result["leakage_audit"]["status"] == "PASS"


def test_research_report_supports_english_output(tmp_path):
    windows, events, trades = research_input(40)
    run_research_pack(tmp_path, windows, events, trades, language="en_US")
    text = (tmp_path / "research_report.md").read_text(encoding="utf-8")
    assert "# Quant Research Report" in text
    assert "Leakage Audit" in text
    assert "not trading signals" in text
