from __future__ import annotations

from pathlib import Path
from typing import Any


COMPONENT_LABELS = {
    "sample_sufficiency": "样本充分性",
    "profile_completeness": "策略定义完整度",
    "entry_tag_consistency": "入场标签一致性",
    "direction_discipline": "方向纪律",
    "entry_setup_consistency": "入场设置一致性",
    "risk_execution_discipline": "风险与执行纪律",
    "exit_discipline": "退出纪律",
    "result_stability": "行为稳定性近似诊断",
    "data_quality_audit": "数据质量与审计",
}
TEXT_MAP = {
    "no StrategyProfile: cap 65": "未提供 StrategyProfile：总分上限 65。",
    "closed_trades < 10: cap 40": "已平仓交易少于 10 笔：总分上限 40。",
    "closed_trades < 30: cap 60": "已平仓交易少于 30 笔：总分上限 60。",
    "no labels: cap 55": "缺少入场标签：总分上限 55。",
    "no risk metadata: cap 75": "缺少风险元数据：总分上限 75。",
    "no exit metadata: cap 80": "缺少退出元数据：总分上限 80。",
    "data quality failed: cap 50": "数据质量未通过：总分上限 50。",
    "leakage audit failed: score invalid": "未来函数审计失败：评分无效。",
    "direction discipline cannot be fully evaluated without a strategy profile": "未提供 StrategyProfile，方向纪律无法充分评价。",
    "side_concentration: direction preference is observed but no allowed_sides is declared": "观察到单边方向集中，但未声明允许交易方向。",
    "no StrategyProfile is declared; direction concentration is descriptive only": "未提供 StrategyProfile；方向集中度仅为描述信息。",
    "directional_coverage_warning: profile declares both sides but only one side is observed": "方向覆盖警告：策略声明双向交易，但样本仅出现单一方向。",
    "closed trade sample is insufficient for a strong consistency conclusion": "已平仓样本不足，不支持强一致性结论。",
    "entry labels are missing": "缺少入场标签。",
    "risk metadata is missing": "缺少风险元数据。",
    "exit reason metadata is missing": "缺少退出原因元数据。",
    "declare a StrategyProfile before interpreting consistency": "解释一致性评分前，应先声明 StrategyProfile。",
    "record fee, slippage and risk rules": "记录手续费、滑点和风险规则。",
    "record exit reasons or exit event types": "记录退出原因或退出事件类型。",
    "repair leakage audit failures before scoring": "修复未来函数审计失败项后再评分。",
    "invalid_due_to_leakage": "因未来函数泄漏而无效",
    "suitable_for_analysis": "可进入后续研究审查",
    "needs_manual_review": "需要人工复核",
    "not_suitable_for_rule_mining": "不适合进行规则挖掘",
    "behavior appears repeatable; continue with out-of-sample audit": "行为具有一定可重复性，应继续进行样本外审计。",
    "partially defined behavior; manual review is required": "行为规则仅部分明确，需要人工复核。",
    "insufficient evidence of a repeatable audited strategy": "缺少足够证据证明存在可重复、可审计的策略行为。",
    "sample_count below min_sample_count": "样本数低于策略档案要求的最小值。",
    "untagged_pct too high": "未标注比例过高。",
    "possible_selection_bias_warning is true": "可能存在选择性标注偏差。",
    "forbidden_tag_hit_count > 0": "命中禁止标签。",
}


def _fmt(value: Any) -> str:
    if value is None:
        return "无效 / N/A"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _zh(value: Any) -> str:
    return TEXT_MAP.get(str(value), str(value))


def write_strategy_consistency_report(result: dict, output_path: Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    components = result.get("component_scores") or result.get("score_components") or {}
    caps = result.get("caps_applied") or []
    warnings = result.get("warnings") or []
    gates = result.get("gate_failures") or []
    actions = result.get("suggested_actions") or []
    top_tags = result.get("top_tags") or {}
    lines = [
        "# 策略一致性审计报告",
        "",
        "## 策略一致性结论",
        "",
        f"- 评分模型：{result.get('model_version', 'legacy')}",
        f"- 一致性评分：{_fmt(result.get('total_score', result.get('strategy_consistency_score')))}",
        f"- 结论：{_zh(result.get('recommendation', 'unknown'))}",
        f"- 解释：{_zh(result.get('interpretation', ''))}",
        "- 策略一致性不等于策略有效性。",
        "- 策略一致性不是盈利评分，也不是收益预测。",
        "- 只做多/只做空不是一致性问题。只有当策略声明要求双向交易时，方向覆盖不足才是问题。",
        "- 无 StrategyProfile 时，方向纪律无法充分评价，因此不应获得高分。",
        "",
        "## 分项评分",
        "",
    ]
    lines.extend([f"- {COMPONENT_LABELS.get(key, key)}: {_fmt(value)}" for key, value in components.items()] or ["- 无"])
    lines.extend(["- result_stability：行为稳定性近似诊断，不是完整样本外绩效验证。"])
    lines.extend(["", "## 分数上限", ""])
    lines.extend([f"- {_zh(item)}" for item in caps] or ["- 无"])
    lines.extend(["", "## 硬性门槛失败项", ""])
    lines.extend([f"- {_zh(item)}" for item in gates] or ["- 无"])
    lines.extend(
        [
            "",
            "## 样本概览",
            "",
            f"- 入场样本数：{result.get('sample_count', 0)}",
            f"- 已平仓交易数：{result.get('closed_trade_count', result.get('close_event_count', 0))}",
            f"- LONG 样本数：{result.get('long_count', 0)}",
            f"- SHORT 样本数：{result.get('short_count', 0)}",
            f"- 方向集中度：{_fmt(result.get('side_concentration_pct'))}%",
            f"- 声明方向命中率：{_fmt(result.get('direction_consistency_pct'))}%",
            "",
            "## 标签与入场设置",
            "",
            f"- 未标注比例：{_fmt(result.get('untagged_pct'))}%",
            f"- 备注缺失比例：{_fmt(result.get('missing_note_pct'))}%",
            f"- 必需标签命中率：{_fmt(result.get('required_tag_coverage_pct'))}%",
            f"- 禁止标签命中数：{result.get('forbidden_tag_hit_count', 0)}",
            f"- 标签熵：{_fmt(result.get('label_entropy'))}",
            f"- Profile 全条件命中率：{_fmt(result.get('profile_feature_match_all_pct'))}%",
            f"- 相似市场设置动作一致率：{_fmt(result.get('similar_context_agreement_pct'))}%",
            "",
            "Top 标签：",
        ]
    )
    lines.extend([f"- {tag}: {count}" for tag, count in top_tags.items()] or ["- 无"])
    lines.extend(["", "## 审计警告", ""])
    lines.extend([f"- {_zh(warning)}" for warning in warnings] or ["- 无"])
    lines.extend(["", "## 建议动作", ""])
    lines.extend([f"- {_zh(action)}" for action in actions] or ["- 无"])
    lines.extend(
        [
            "",
            "## 重要声明",
            "",
            "- 一致性评分衡量行为是否可描述、可重复、可审计，不衡量盈利能力。",
            "- 未来函数审计失败时，评分无效。",
            "- 样本量不足、风险元数据缺失或退出记录缺失时，结论受限。",
            "- 本报告不构成投资建议。",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
