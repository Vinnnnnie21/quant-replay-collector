from __future__ import annotations

from pathlib import Path

import pandas as pd

from i18n import tr


def _text(key: str, language: str, default: str) -> str:
    return tr(f"research.report.{key}", language, default)


def _column_name(column: str, language: str) -> str:
    return tr(f"research.column.{column}", language, column)


def _table(data: pd.DataFrame, language: str, rows: int = 10) -> str:
    if data is None or data.empty:
        return _text("empty", language, "No qualifying results.")
    display = data.head(rows).rename(columns=lambda column: _column_name(str(column), language))
    try:
        return display.to_markdown(index=False)
    except Exception:
        return display.to_string(index=False)


def write_research_report(
    output_path: Path,
    manifest: dict,
    audit: dict,
    leakage: dict,
    label_distribution: pd.DataFrame,
    event_study: pd.DataFrame,
    factor_binning: pd.DataFrame,
    factor_ic: pd.DataFrame,
    candidate_rules: pd.DataFrame,
    walk_forward: pd.DataFrame,
    language: str = "zh_CN",
) -> Path:
    output_path = Path(output_path)
    zh = language != "en_US"
    dataset_lines = (
        [
            f"- 实验 ID：`{manifest.get('experiment_id')}`",
            f"- 数据集哈希：`{manifest.get('dataset_hash')}`",
            f"- 样本数：{audit.get('sample_count', 0)}",
            f"- 目标标签：`{manifest.get('selected_label')}`",
            f"- 品种：{', '.join(manifest.get('symbols', [])) or '无'}",
            f"- 周期：{', '.join(manifest.get('intervals', [])) or '无'}",
        ]
        if zh
        else [
            f"- Experiment ID: `{manifest.get('experiment_id')}`",
            f"- Dataset hash: `{manifest.get('dataset_hash')}`",
            f"- Sample count: {audit.get('sample_count', 0)}",
            f"- Selected label: `{manifest.get('selected_label')}`",
            f"- Symbols: {', '.join(manifest.get('symbols', [])) or 'none'}",
            f"- Intervals: {', '.join(manifest.get('intervals', [])) or 'none'}",
        ]
    )
    quality_lines = (
        [
            f"- 有效样本：{audit.get('valid_sample_count', 0)}",
            f"- 无效样本：{audit.get('invalid_sample_count', 0)}",
            f"- 重复事件 ID：{audit.get('duplicate_event_id_count', 0)}",
            f"- 缺失特征单元格：{audit.get('missing_feature_count', 0)}",
            f"- 缺失标签单元格：{audit.get('missing_label_count', 0)}",
            f"- 样本警告：{audit.get('small_sample_warning', '')}",
        ]
        if zh
        else [
            f"- Valid samples: {audit.get('valid_sample_count', 0)}",
            f"- Invalid samples: {audit.get('invalid_sample_count', 0)}",
            f"- Duplicate event IDs: {audit.get('duplicate_event_id_count', 0)}",
            f"- Missing feature cells: {audit.get('missing_feature_count', 0)}",
            f"- Missing label cells: {audit.get('missing_label_count', 0)}",
            f"- Sample warning: {audit.get('small_sample_warning', '')}",
        ]
    )
    leakage_lines = (
        [
            f"- 状态：{leakage.get('status')}",
            f"- 禁止进入特征的字段：{', '.join(leakage.get('forbidden_feature_columns', [])) or '无'}",
            "- 状态为 PASS 时，模型输入已排除未来标签字段。",
        ]
        if zh
        else [
            f"- Status: {leakage.get('status')}",
            f"- Forbidden feature columns: {', '.join(leakage.get('forbidden_feature_columns', [])) or 'none'}",
            "- All model inputs have excluded future label fields when status is PASS.",
        ]
    )
    warning_lines = (
        [
            f"- {audit.get('small_sample_warning', '无法评估样本量。')}",
            "- 多个因子与规则检验会提高假阳性风险。",
            "- 因子 IC 的近似 p-value 不处理金融时间序列的自相关、异方差或重叠未来收益标签，只能作为探索性证据。",
            "- 训练期到后续测试期的衰减应视为过拟合风险。",
        ]
        if zh
        else [
            f"- {audit.get('small_sample_warning', 'Sample-size assessment unavailable.')}",
            "- Multiple factor and rule tests increase false-positive risk.",
            "- Factor IC approximate p-value does not adjust for serial dependence, heteroskedasticity or overlapping forward-return labels; treat it as exploratory evidence only.",
            "- Any degradation from train to later test periods must be treated as overfit risk.",
        ]
    )
    limitation_lines = (
        [
            "- 结果依赖主观事件选择和标注质量。",
            "- K 线回放和简化执行成本假设不等同于实盘交易。",
            f"- {_text('labels_only', language, '')}",
            "- 候选规则不是交易信号。",
            f"- {_text('not_advice', language, '')}",
        ]
        if zh
        else [
            "- Results depend on discretionary event selection and annotation quality.",
            "- Kline replay and simplified execution assumptions do not reproduce live trading.",
            f"- {_text('labels_only', language, '')}",
            "- Candidate rules are not trading signals.",
            f"- {_text('not_advice', language, '')}",
        ]
    )
    lines = [
        f"# {_text('title', language, 'Quant Research Report')}",
        "",
        _text("exploratory", language, ""),
        "",
        f"## {_text('dataset', language, 'Dataset')}",
        "",
        *dataset_lines,
        "",
        f"## {_text('data_quality', language, 'Data Quality')}",
        "",
        *quality_lines,
        "",
        f"## {_text('leakage_audit', language, 'Leakage Audit')}",
        "",
        *leakage_lines,
        "",
        f"## {_text('label_distribution', language, 'Label Distribution')}",
        "",
        _table(label_distribution, language),
        "",
        f"## {_text('event_study', language, 'Event Study')}",
        "",
        _table(event_study, language),
        "",
        f"## {_text('factor_binning', language, 'Factor Binning')}",
        "",
        _table(factor_binning, language),
        "",
        f"## {_text('factor_ic', language, 'Factor IC')}",
        "",
        _table(factor_ic, language),
        "",
        f"## {_text('candidate_rules', language, 'Candidate Rules')}",
        "",
        _table(candidate_rules, language),
        "",
        _text("rules_warning", language, ""),
        "",
        f"## {_text('walk_forward', language, 'Walk-forward Validation')}",
        "",
        _table(walk_forward, language),
        "",
        f"## {_text('warnings', language, 'Research Warnings')}",
        "",
        *warning_lines,
        "",
        f"## {_text('limitations', language, 'Limitations')}",
        "",
        *limitation_lines,
        "",
    ]
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
