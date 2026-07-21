from __future__ import annotations

import pandas as pd

from analysis.data_audit import audit_event_features, audit_export_tables, audit_ml_dataset


def test_audit_empty_data():
    audit = audit_export_tables({})
    assert audit["event_features"]["is_empty"] is True
    assert audit["sample_warning"] == "strong_warning"


def test_audit_normal_data():
    features = pd.DataFrame({"event_id": ["e1"], "event_type": ["OPEN"], "side": ["LONG"], "symbol": ["BTCUSDT"], "interval": ["1m"]})
    audit = audit_event_features(features)
    assert audit["event_id_unique"] is True
    assert audit["event_type_counts"]["OPEN"] == 1


def test_audit_detects_ml_feature_leakage():
    features = pd.DataFrame({"event_id": ["e1"], "fwd_ret_10": [0.01]})
    labels = pd.DataFrame({"event_id": ["e1"], "fwd_ret_10": [0.01]})
    sample_index = pd.DataFrame({"event_id": ["e1"]})
    audit = audit_ml_dataset(features, labels, sample_index)
    assert audit["has_leakage"] is True
    assert "fwd_ret_10" in audit["leakage_columns"]


def test_audit_duplicate_event_id():
    features = pd.DataFrame({"event_id": ["e1", "e1"]})
    audit = audit_event_features(features)
    assert audit["event_id_unique"] is False


def test_audit_missing_label():
    audit = audit_ml_dataset(pd.DataFrame({"event_id": ["e1"]}), pd.DataFrame({"event_id": ["e1"]}), pd.DataFrame({"event_id": ["e1"]}))
    assert audit["has_label"] is False


def test_sample_warning_levels():
    assert audit_event_features(pd.DataFrame({"event_id": range(10)}))["sample_warning"] == "strong_warning"
    assert audit_event_features(pd.DataFrame({"event_id": range(50)}))["sample_warning"] == "weak_warning"
    assert audit_event_features(pd.DataFrame({"event_id": range(120)}))["sample_warning"] == "usable_for_exploration"

