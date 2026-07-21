from __future__ import annotations

import pandas as pd

from analysis.report_writer import write_strategy_research_report


def test_report_writer_handles_empty_data(tmp_path):
    path = write_strategy_research_report(
        tmp_path,
        audit={},
        event_study=pd.DataFrame(),
        binning=pd.DataFrame(),
        candidate_rules=pd.DataFrame(),
        performance_summary={},
        metadata={"session_id": "sess_1"},
    )

    text = path.read_text(encoding="utf-8")
    assert path.exists()
    assert "样本总览" in text
    assert "不构成投资建议" in text


def test_report_writer_generates_required_sections(tmp_path):
    event_study = pd.DataFrame([{"label_tag": "long_lower_wick", "sample_count": 5}])
    binning = pd.DataFrame([{"feature": "pre_ret_20", "label": "label_win_10", "sample_count": 5}])
    rules = pd.DataFrame([{"rule_text": "pre_ret_20 <= -0.03", "sample_count": 30}])

    path = write_strategy_research_report(
        tmp_path,
        audit={
            "event_features": {"row_count": 5},
            "ml_dataset": {"ml_features_rows": 5, "ml_labels_rows": 5},
            "sample_warning": "strong_warning",
            "warnings": ["样本量不足"],
        },
        event_study=event_study,
        binning=binning,
        candidate_rules=rules,
        performance_summary={"total_trades": 2, "closed_trades": 1},
        metadata={"session_id": "sess_1", "symbol": "BTCUSDT"},
    )

    text = path.read_text(encoding="utf-8")
    for heading in [
        "项目和 session 信息",
        "数据质量警告",
        "特征分箱摘要",
        "候选规则 Top 10",
        "未来函数隔离说明",
        "研究限制",
    ]:
        assert heading in text
    assert "候选规则不是交易建议" in text
