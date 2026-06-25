from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

try:
    from i18n import tr as _i18n_tr
except ImportError:
    from ..i18n import tr as _i18n_tr


def _tr(key: str, language: str = "zh_CN", default: str | None = None) -> str:
    return _i18n_tr(key, language, default)


def _risk_lines(language: str) -> list[str]:
    return [
        _tr("report.risk_line_train_only", language),
        _tr("report.risk_line_correlation", language),
        _tr("report.risk_line_sample_size", language),
        _tr("report.risk_line_bias", language),
        _tr("report.risk_line_replay", language),
        _tr("report.risk_line_rules", language),
        _tr("report.risk_line_advice", language),
    ]


def _df_head_md(df: pd.DataFrame | None, n: int = 10, language: str = "zh_CN") -> str:
    if df is None or df.empty:
        return _tr("report.no_data", language)
    head = df.head(n)
    try:
        return head.to_markdown(index=False)
    except Exception:
        return head.to_string(index=False)



def write_strategy_research_report(
    output_dir: Path,
    audit: dict,
    event_study: pd.DataFrame,
    binning: pd.DataFrame,
    candidate_rules: pd.DataFrame,
    performance_summary: pd.DataFrame | dict,
    metadata: dict,
    language: str = "zh_CN",
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
    warnings_list = (audit or {}).get("warnings", [])

    lines = [
        f"# {_tr('report.title', language)}",
        "",
        _tr("report.subtitle", language),
        "",
        f"## 1. {_tr('report.section_project', language)}",
        "",
        *[f"- {k}: {v}" for k, v in metadata.items() if v is not None],
        "",
        f"## 2. {_tr('report.section_overview', language)}",
        "",
        f"- {_tr('report.label_event_features_rows', language)}：{event_features.get('row_count', 0)}",
        f"- {_tr('report.label_ml_features_rows', language)}：{ml_dataset.get('ml_features_rows', 0)}",
        f"- {_tr('report.label_ml_labels_rows', language)}：{ml_dataset.get('ml_labels_rows', 0)}",
        f"- {_tr('report.label_sample_status', language)}：{(audit or {}).get('sample_warning')}",
        "",
        f"## 3. {_tr('report.section_quality', language)}",
        "",
        *([f"- {w}" for w in warnings_list] or [f"- {_tr('report.no_warnings', language)}"]),
        "",
        f"## 4. {_tr('report.section_labels', language)}",
        "",
        _tr("report.labels_note", language),
        "",
        f"## 5. {_tr('report.section_event_study', language)}",
        "",
        _df_head_md(event_study, 10, language),
        "",
        f"## 6. {_tr('report.section_binning', language)}",
        "",
        _df_head_md(binning, 10, language),
        "",
        f"## 7. {_tr('report.section_rules', language)}",
        "",
        _df_head_md(candidate_rules, 10, language),
        "",
        f"## 8. {_tr('report.section_performance', language)}",
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
        f"## 9. {_tr('report.section_equity', language)}",
        "",
        f"- {_tr('report.label_initial_equity', language)}：{perf_dict.get('initial_equity')}",
        f"- {_tr('report.label_final_equity', language)}：{perf_dict.get('final_equity')}",
        f"- {_tr('report.label_total_pnl', language)}：{perf_dict.get('total_net_pnl')}",
        "",
        f"## 10. {_tr('report.section_leakage', language)}",
        "",
        _tr("report.leakage_note", language),
        "",
        f"## 11. {_tr('report.section_limitations', language)}",
        "",
        *[f"- {line}" for line in _risk_lines(language)],
        "",
        f"## 12. {_tr('report.section_next', language)}",
        "",
        f"- {_tr('report.next_item_collect_failure', language)}",
        f"- {_tr('report.next_item_negative', language)}",
        f"- {_tr('report.next_item_multi_interval', language)}",
        f"- {_tr('report.next_item_oos', language)}",
        "",
    ]
    path = output_dir / "strategy_research_report.md"
    path.write_text("\n".join(str(x) for x in lines), encoding="utf-8")
    return path
