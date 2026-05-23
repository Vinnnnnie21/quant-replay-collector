from __future__ import annotations

import pytest

from llm_client import analyze_strategy_context, analyze_with_openai, build_analysis_prompt


def _context():
    return {
        "data_audit_summary": {"event_count": 10, "trade_count": 2},
        "candidate_rules_top": [{"rule_text": "pre_ret_20 <= -0.03"}],
        "sample_warnings": ["样本不足"],
        "next_data_to_collect": ["失败样本"],
    }


def test_mock_provider_returns_required_structure():
    result = analyze_strategy_context(_context(), provider="mock")

    for key in [
        "summary",
        "key_findings",
        "weak_evidence",
        "possible_rules",
        "risk_warnings",
        "next_data_to_collect",
        "questions_for_user",
        "not_investment_advice",
    ]:
        assert key in result
    assert result["not_investment_advice"] is True


def test_openai_provider_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        analyze_with_openai(_context())


def test_prompt_contains_risk_boundaries():
    prompt = build_analysis_prompt(_context())

    assert "不是投资建议" in prompt
    assert "实盘下单" in prompt
    assert "样本量不足" in prompt
