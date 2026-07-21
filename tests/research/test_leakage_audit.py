from __future__ import annotations

import pandas as pd
import pytest

from research.factor_audit import assert_feature_safe, leakage_audit


def test_leakage_audit_fails_for_future_feature_columns():
    features = pd.DataFrame({"event_id": ["e1"], "body_pct": [0.2], "fwd_ret_10": [0.01]})
    audit = leakage_audit(features)
    assert audit["status"] == "FAIL"
    assert audit["forbidden_feature_columns"] == ["fwd_ret_10"]
    with pytest.raises(ValueError):
        assert_feature_safe(features)
