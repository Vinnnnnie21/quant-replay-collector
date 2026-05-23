from __future__ import annotations

import json

from strategy_consistency.report import write_strategy_consistency_report


def _result():
    return {
        "strategy_consistency_score": 72.5,
        "recommendation": "needs_manual_review",
        "sample_count": 35,
        "open_event_count": 35,
        "close_event_count": 10,
        "long_count": 35,
        "short_count": 0,
        "direction_consistency_pct": 100.0,
        "untagged_pct": 10.0,
        "missing_note_pct": 20.0,
        "top_tags": {"长下影": 20},
        "warnings": ["sample warning"],
        "gate_failures": ["sample_count below min_sample_count"],
        "label_score_detail": {"label_score_pct": 70.0},
        "profile_feature_match_all_pct": 65.0,
    }


def test_strategy_consistency_report_generates_markdown(tmp_path):
    path = write_strategy_consistency_report(_result(), tmp_path / "strategy_consistency_report.md")
    text = path.read_text(encoding="utf-8")
    assert "策略一致性结论" in text
    assert "策略一致性不等于策略有效性" in text
    assert "不构成投资建议" in text


def test_gate_failures_written_to_json_and_markdown(tmp_path):
    result = _result()
    (tmp_path / "strategy_consistency.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    path = write_strategy_consistency_report(result, tmp_path / "strategy_consistency_report.md")
    text = path.read_text(encoding="utf-8")
    payload = json.loads((tmp_path / "strategy_consistency.json").read_text(encoding="utf-8"))
    assert payload["gate_failures"]
    assert "Gate Failures" in text
    assert "sample_count below min_sample_count" in text
