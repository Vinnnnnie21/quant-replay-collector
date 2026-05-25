from __future__ import annotations

from typing import Any

from .profile import StrategyProfile


COMPONENT_LIMITS = {
    "sample_sufficiency": 10.0,
    "profile_completeness": 15.0,
    "entry_tag_consistency": 15.0,
    "direction_discipline": 10.0,
    "entry_setup_consistency": 10.0,
    "risk_execution_discipline": 15.0,
    "exit_discipline": 10.0,
    "result_stability": 10.0,
    "data_quality_audit": 5.0,
}


def sample_sufficiency_score(closed_trades: int) -> float:
    if closed_trades >= 50:
        return 10.0
    if closed_trades >= 30:
        return 8.0
    if closed_trades >= 10:
        return 5.0
    if closed_trades >= 5:
        return 2.0
    return 0.0


def profile_completeness_score(profile: StrategyProfile | None, provided: bool) -> float:
    if not provided or profile is None:
        return 0.0
    checks = [
        bool(profile.allowed_sides),
        bool(profile.required_entry_tags),
        bool(profile.risk_model),
        profile.stop_loss_pct is not None or profile.take_profit_pct is not None,
        profile.max_holding_bars is not None or bool(profile.exit_rules_required),
        bool(profile.allowed_symbols) or bool(profile.allowed_intervals) or bool(profile.allowed_regimes),
    ]
    return round(sum(checks) / len(checks) * COMPONENT_LIMITS["profile_completeness"], 2)


def apply_score_caps(
    score: float,
    *,
    profile_provided: bool,
    closed_trades: int,
    has_labels: bool,
    has_risk_metadata: bool,
    has_exit_metadata: bool,
    leakage_audit_status: str,
    data_quality_status: str,
) -> tuple[float | None, list[str]]:
    if str(leakage_audit_status).upper() != "PASS":
        return None, ["leakage audit failed: score invalid"]
    caps: list[tuple[float, str]] = []
    if not profile_provided:
        caps.append((65.0, "no StrategyProfile: cap 65"))
    if closed_trades < 10:
        caps.append((40.0, "closed_trades < 10: cap 40"))
    elif closed_trades < 30:
        caps.append((60.0, "closed_trades < 30: cap 60"))
    if not has_labels:
        caps.append((55.0, "no labels: cap 55"))
    if not has_risk_metadata:
        caps.append((75.0, "no risk metadata: cap 75"))
    if not has_exit_metadata:
        caps.append((80.0, "no exit metadata: cap 80"))
    if str(data_quality_status).upper() not in {"PASS", "OK"}:
        caps.append((50.0, "data quality failed: cap 50"))
    cap = min([value for value, _reason in caps], default=100.0)
    return round(min(float(score), cap), 2), [reason for _value, reason in caps]


def score_interpretation(total_score: float | None) -> str:
    if total_score is None:
        return "invalid_due_to_leakage"
    if total_score >= 80.0:
        return "behavior appears repeatable; continue with out-of-sample audit"
    if total_score >= 60.0:
        return "partially defined behavior; manual review is required"
    return "insufficient evidence of a repeatable audited strategy"


def rounded_components(values: dict[str, Any]) -> dict[str, float]:
    return {key: round(max(0.0, min(float(value), COMPONENT_LIMITS[key])), 2) for key, value in values.items()}
