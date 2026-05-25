from __future__ import annotations

import pandas as pd

from time_series_analysis.report import build_time_series_report, write_time_series_report


def test_chinese_time_series_report_is_generated(tmp_path):
    close = [100.0 + index * 0.1 for index in range(80)]
    frame = pd.DataFrame(
        {
            "bar_index": range(80),
            "open_time_bjt": pd.date_range("2026-01-01", periods=80, freq="min").astype(str),
            "open": close,
            "high": [value + 0.2 for value in close],
            "low": [value - 0.2 for value in close],
            "close": close,
            "volume": [10.0] * 80,
        }
    )
    result = build_time_series_report(frame)
    path = write_time_series_report(result, tmp_path / "time_series_report.md")
    text = path.read_text(encoding="utf-8")
    assert "# 金融时间序列诊断报告" in text
    assert "尾部风险" in text
    assert "不是交易信号" in text
    assert "需要多币种收益矩阵" in text
    assert "Ljung-Box p 值" in text
