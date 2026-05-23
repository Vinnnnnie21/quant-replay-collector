from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


RISK_LINES = [
    "本报告只用于交易训练、复盘和研究。",
    "统计相关不等于因果。",
    "样本量不足时不能下结论。",
    "人工标注存在选择偏差。",
    "回放收益不代表实盘收益。",
    "候选规则不是交易建议。",
    "本报告不构成投资建议。",
]


def _df_head_md(df: pd.DataFrame | None, n: int = 10) -> str:
    if df is None or df.empty:
        return "暂无数据。"
    head = df.head(n)
    try:
        return head.to_markdown(index=False)
    except Exception:
        return head.to_string(index=False)


def _dict_lines(data: dict[str, Any] | None, keys: list[str] | None = None) -> list[str]:
    data = data or {}
    items = [(k, data.get(k)) for k in (keys or list(data.keys()))]
    return [f"- {k}: {v}" for k, v in items if v is not None]


def write_strategy_research_report(
    output_dir: Path,
    audit: dict,
    event_study: pd.DataFrame,
    binning: pd.DataFrame,
    candidate_rules: pd.DataFrame,
    performance_summary: pd.DataFrame | dict,
    metadata: dict,
) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    perf = performance_summary
    if isinstance(perf, pd.DataFrame):
        perf_dict = perf.iloc[0].to_dict() if not perf.empty else {}
    else:
        perf_dict = dict(perf or {})

    event_features = (audit or {}).get("event_features", {})
    ml_dataset = (audit or {}).get("ml_dataset", {})
    warnings = (audit or {}).get("warnings", [])

    lines = [
        "# Strategy Research Report",
        "",
        "Quant Replay Collector 自动生成的策略研究报告。",
        "",
        "## 1. 项目和 session 信息",
        "",
        *_dict_lines(metadata),
        "",
        "## 2. 样本总览",
        "",
        f"- event_features 行数：{event_features.get('row_count', 0)}",
        f"- ml_features 行数：{ml_dataset.get('ml_features_rows', 0)}",
        f"- ml_labels 行数：{ml_dataset.get('ml_labels_rows', 0)}",
        f"- 样本量状态：{(audit or {}).get('sample_warning')}",
        "",
        "## 3. 数据质量警告",
        "",
        *([f"- {w}" for w in warnings] or ["- 暂无明显警告。"]),
        "",
        "## 4. 标签分布",
        "",
        "标签分布需结合 `strategy_labels.csv` 和 `event_study_summary.csv` 查看。样本量小于 30 时仅能作为记录，不能作为结论。",
        "",
        "## 5. 事件研究摘要",
        "",
        _df_head_md(event_study, 10),
        "",
        "## 6. 特征分箱摘要",
        "",
        _df_head_md(binning, 10),
        "",
        "## 7. 候选规则 Top 10",
        "",
        _df_head_md(candidate_rules, 10),
        "",
        "## 8. 绩效摘要",
        "",
        *_dict_lines(
            perf_dict,
            [
                "total_trades",
                "closed_trades",
                "win_rate_pct",
                "average_return_pct",
                "total_return_pct",
                "max_drawdown_pct",
                "profit_factor",
                "recent_trade_result",
            ],
        ),
        "",
        "## 9. 权益曲线摘要",
        "",
        f"- 初始权益：{perf_dict.get('initial_equity')}",
        f"- 最终权益：{perf_dict.get('final_equity')}",
        f"- 总净盈亏：{perf_dict.get('total_net_pnl')}",
        "",
        "## 10. 未来函数隔离说明",
        "",
        "`ml_features.csv` 不应包含 `fwd_*`、`post_*`、`mfe_10`、`mae_10`、`manual_trade_final_return_pct`、`manual_trade_holding_bars` 等结果或未来字段。",
        "",
        "## 11. 研究限制",
        "",
        *[f"- {line}" for line in RISK_LINES],
        "",
        "## 12. 下一步应收集的数据",
        "",
        "- 收集更多失败样本和未开仓观察样本。",
        "- 增加大跌后没有反转的负样本。",
        "- 按不同周期、不同品种拆分验证。",
        "- 进行样本外验证后再考虑规则回测。",
        "",
    ]
    path = output_dir / "strategy_research_report.md"
    path.write_text("\n".join(str(x) for x in lines), encoding="utf-8")
    return path
