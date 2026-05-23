from __future__ import annotations

from pathlib import Path
from typing import Any


def _fmt(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def write_strategy_consistency_report(result: dict, output_path: Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    warnings = result.get("warnings") or []
    gates = result.get("gate_failures") or []
    top_tags = result.get("top_tags") or {}
    conflicts = result.get("conflict_examples") or []
    label_detail = result.get("label_score_detail") or {}

    lines = [
        "# 策略一致性审计报告",
        "",
        "## 策略一致性结论",
        "",
        f"- 一致性评分：{_fmt(result.get('strategy_consistency_score'))}",
        f"- 结论：{result.get('recommendation', 'unknown')}",
        "- 说明：策略一致性不等于策略有效性，也不是盈利能力评分。",
        "",
        "## Gate Failures",
        "",
    ]
    lines.extend([f"- {item}" for item in gates] or ["- 无"])
    lines.extend(
        [
            "",
            "命中 gate_failures 时，不建议继续规则挖掘或把样本交给大模型生成策略。",
            "",
            "## 样本总览",
            "",
            f"- 样本数：{result.get('sample_count', 0)}",
            f"- 开仓事件数：{result.get('open_event_count', 0)}",
            f"- 平仓事件数：{result.get('close_event_count', 0)}",
            f"- LONG 样本数：{result.get('long_count', 0)}",
            f"- SHORT 样本数：{result.get('short_count', 0)}",
            "",
            "## 方向一致性",
            "",
            f"- 方向一致性：{_fmt(result.get('direction_consistency_pct'))}%",
            f"- 混杂方向警告：{result.get('mixed_direction_warning')}",
            "",
            "## 标签一致性",
            "",
            f"- 未打标签比例：{_fmt(result.get('untagged_pct'))}%",
            f"- 缺少备注比例：{_fmt(result.get('missing_note_pct'))}%",
            f"- Top 标签覆盖率：{_fmt(result.get('top_tag_coverage_pct'))}%",
            f"- 必需标签覆盖率：{_fmt(result.get('required_tag_coverage_pct'))}%",
            f"- 禁止标签命中数：{result.get('forbidden_tag_hit_count', 0)}",
            f"- 标签熵：{_fmt(result.get('label_entropy'))}",
            "",
            "标签分数明细：",
        ]
    )
    lines.extend([f"- {k}: {v}" for k, v in label_detail.items()] or ["- 无"])
    lines.extend(["", "Top 标签："])
    lines.extend([f"- {k}: {v}" for k, v in top_tags.items()] or ["- 无"])
    lines.extend(
        [
            "",
            "## 市场状态一致性",
            "",
            f"- pre_ret_20 均值：{_fmt(result.get('pre_ret_20_mean'))}",
            f"- pre_ret_20 中位数：{_fmt(result.get('pre_ret_20_median'))}",
            f"- pre_ret_20 为负比例：{_fmt(result.get('pre_ret_20_negative_pct'))}%",
            f"- pre_max_drawdown_20 均值：{_fmt(result.get('pre_max_drawdown_20_mean'))}",
            f"- event_lower_wick_ratio 均值：{_fmt(result.get('event_lower_wick_ratio_mean'))}",
            f"- event_volume_ratio_20 均值：{_fmt(result.get('event_volume_ratio_20_mean'))}",
            f"- profile 条件平均命中率：{_fmt(result.get('profile_feature_match_pct'))}%",
            f"- profile 任一条件命中率：{_fmt(result.get('profile_feature_match_any_pct'))}%",
            f"- profile 全部条件命中率：{_fmt(result.get('profile_feature_match_all_pct'))}%",
            "",
            "## 相似场景动作一致性",
            "",
            f"- 相似场景动作一致率：{_fmt(result.get('similar_context_agreement_pct'))}%",
            f"- 可比较样本数：{result.get('neighbor_sample_count', 0)}",
            "",
            "冲突样本示例：",
        ]
    )
    lines.extend(
        [
            f"- {c.get('event_id')} vs {c.get('neighbor_event_id')}: {c.get('action')} / {c.get('neighbor_action')}"
            for c in conflicts[:10]
        ]
        or ["- 无"]
    )
    lines.extend(
        [
            "",
            "## 时间稳定性",
            "",
            f"- 方向漂移警告：{result.get('direction_drift_warning')}",
            f"- 标签漂移警告：{result.get('tag_drift_warning')}",
            f"- 特征漂移警告：{result.get('feature_drift_warning')}",
            "",
            "## 风险警告",
            "",
        ]
    )
    lines.extend([f"- {w}" for w in warnings] or ["- 无"])
    lines.extend(
        [
            "",
            "## 是否适合进入后续分析",
            "",
            f"- recommendation：{result.get('recommendation', 'unknown')}",
            "- `suitable_for_analysis`：样本一致性较好，可以进入特征分析、规则挖掘和回测，但仍需样本外验证。",
            "- `needs_manual_review`：需要人工复核样本定义、标签和失败样本覆盖。",
            "- `not_suitable_for_rule_mining`：不建议继续规则挖掘，先清洗或重新标注样本。",
            "",
            "## 重要声明",
            "",
            "- 策略一致性不等于策略有效性。",
            "- 一致性评分不是盈利能力。",
            "- 本报告不构成投资建议。",
            "- 命中 gate_failures 时不建议继续规则挖掘。",
            "- 低一致性样本不能直接用于策略生成。",
            "- 样本混杂时不应继续做规则挖掘。",
            "- 如果样本量不足，不能下结论。",
            "- 如果缺少失败样本，可能存在选择性标注偏差。",
            "- 回放和回测收益不代表实盘收益。",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
