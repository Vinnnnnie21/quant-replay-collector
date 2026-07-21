from __future__ import annotations

import pytest

from research.validation import oos_degradation_gate


def test_oos_degradation_gate_passes_stable_metric_and_rejects_large_drop():
    passed = oos_degradation_gate(0.02, 0.018, max_degradation_ratio=0.25)
    rejected = oos_degradation_gate(0.02, 0.005, max_degradation_ratio=0.25)

    assert passed["passed"] is True
    assert passed["degradation_ratio"] == pytest.approx(0.1)
    assert rejected["passed"] is False
    assert rejected["status"] == "rejected_oos_degradation"
    assert rejected["degradation_ratio"] == pytest.approx(0.75)


def test_oos_degradation_gate_marks_missing_metric_unavailable():
    result = oos_degradation_gate(None, 0.01, max_degradation_ratio=0.25)

    assert result["passed"] is False
    assert result["status"] == "unavailable"
    assert result["warning"] == "metric_unavailable"
    assert result["degradation_ratio"] is None
