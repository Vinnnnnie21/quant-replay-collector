from __future__ import annotations

import json
import os
from typing import Any

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None


RESPONSE_KEYS = [
    "summary",
    "key_findings",
    "weak_evidence",
    "possible_rules",
    "risk_warnings",
    "next_data_to_collect",
    "questions_for_user",
    "not_investment_advice",
]


def _load_env():
    if load_dotenv is not None:
        load_dotenv()


def build_analysis_prompt(llm_context: dict) -> str:
    context_json = json.dumps(llm_context, ensure_ascii=False, indent=2, default=str)
    return (
        "你是交易复盘和量化研究分析助手，只能解释统计结果、生成研究假设和提出下一步验证计划。\n"
        "禁止：直接买卖建议；保证盈利；把样本内统计当成未来确定收益；忽略样本量不足；"
        "忽略选择偏差；忽略未来函数风险；生成实盘下单指令。\n"
        "必须声明：这不是投资建议，候选规则只是待验证假设。\n\n"
        f"压缩后的研究上下文如下：\n{context_json}"
    )


def _base_response() -> dict[str, Any]:
    return {
        "summary": "",
        "key_findings": [],
        "weak_evidence": [],
        "possible_rules": [],
        "risk_warnings": [
            "这不是投资建议。",
            "样本量不足不能下结论。",
            "统计相关不等于因果。",
            "回放收益不代表实盘收益。",
            "候选规则需要样本外验证。",
        ],
        "next_data_to_collect": [],
        "questions_for_user": [],
        "not_investment_advice": True,
    }


def analyze_with_mock(llm_context: dict) -> dict[str, Any]:
    response = _base_response()
    audit = llm_context.get("data_audit_summary", {})
    rules = llm_context.get("candidate_rules_top", [])
    response.update(
        {
            "summary": f"当前会话包含 {audit.get('event_count', 0)} 个事件样本和 {audit.get('trade_count', 0)} 笔交易。此结果只适合复盘和研究。",
            "key_findings": [
                "已生成压缩分析上下文，未暴露完整数据库和完整 K 线。",
                "候选规则仅用于后续验证，不是交易信号。",
            ],
            "weak_evidence": llm_context.get("sample_warnings", []),
            "possible_rules": [r.get("rule_text") for r in rules[:5] if isinstance(r, dict) and r.get("rule_text")],
            "next_data_to_collect": llm_context.get("next_data_to_collect", []),
            "questions_for_user": [
                "哪些大跌反转样本是你认为最标准的？",
                "失败样本是否也按同一标准完整标注？",
            ],
        }
    )
    return response


def analyze_with_openai(llm_context: dict) -> dict[str, Any]:
    import requests

    _load_env()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 未设置；真实外部 LLM 调用默认关闭。")
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是只读量化研究分析助手，不提供实时买卖建议。"},
            {"role": "user", "content": build_analysis_prompt(llm_context)},
        ],
        "temperature": 0.2,
    }
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"]
    out = _base_response()
    out["summary"] = text
    return out


def analyze_with_custom_http(llm_context: dict) -> dict[str, Any]:
    import requests

    _load_env()
    url = os.getenv("CUSTOM_LLM_URL")
    api_key = os.getenv("CUSTOM_LLM_API_KEY")
    if not url or not api_key:
        raise RuntimeError("CUSTOM_LLM_URL 或 CUSTOM_LLM_API_KEY 未设置；真实外部 LLM 调用默认关闭。")
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
        json={"prompt": build_analysis_prompt(llm_context), "context": llm_context},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict):
        out = _base_response()
        out.update({k: data.get(k, out[k]) for k in RESPONSE_KEYS})
        return out
    out = _base_response()
    out["summary"] = str(data)
    return out


def analyze_strategy_context(llm_context: dict, provider: str = "mock") -> dict[str, Any]:
    provider = str(provider or "mock").strip().lower()
    if provider == "mock":
        return analyze_with_mock(llm_context)
    if provider == "openai":
        return analyze_with_openai(llm_context)
    if provider == "custom_http":
        return analyze_with_custom_http(llm_context)
    raise ValueError(f"Unsupported LLM provider: {provider}")
