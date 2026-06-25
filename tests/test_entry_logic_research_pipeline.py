from __future__ import annotations

import json

import pandas as pd
import pytest

from exporter import Exporter
from storage import StorageManager
from test_exporter_basic import insert_complete_trade, insert_session, make_storage
from test_storage_trade_flow import SESSION_ID

from quant_collector_app.research.active_label_selection import build_label_review_queue
from quant_collector_app.research.entry_annotations import DecisionTiming, EntryAnnotation, HumanDecision
from quant_collector_app.research.entry_context_features import FeatureSpec, build_entry_context_features
from quant_collector_app.research.entry_logic_report import build_entry_logic_report, write_entry_logic_report
from quant_collector_app.research.entry_experiment_registry import load_experiment_manifest
from quant_collector_app.research.entry_logic_experiment import run_entry_logic_experiment
from quant_collector_app.research.entry_logic_scoring import fit_entry_prototype, score_entry_similarity
from quant_collector_app.research.entry_observation_universe import generate_entry_observation_universe
from quant_collector_app.research.entry_outcome_labels import LabelSpec, build_entry_outcome_labels
from quant_collector_app.research.temporal_validation import chronological_train_val_test_split


FORBIDDEN_CONTEXT_TOKENS = ("fwd_ret", "future", "mfe", "mae", "hit_tp", "hit_sl")
FEATURE_COLS = ["lower_shadow_ratio", "volume_zscore_20", "range_pct", "drop_from_recent_high_20"]


def _ohlcv() -> pd.DataFrame:
    rows = []
    event_bars = {20, 30, 40, 50}
    for index in range(70):
        open_time = pd.Timestamp("2026-01-01T00:00:00Z") + pd.Timedelta(minutes=index)
        base = 120.0 - index * 0.35
        if index in event_bars:
            open_price = base
            close = base + 0.45
            high = close + 0.7
            low = base - 6.0
            volume = 620.0 + index
        else:
            open_price = base + 0.25
            close = base - 0.15
            high = max(open_price, close) + 0.35
            low = min(open_price, close) - 0.35
            volume = 100.0 + index % 5
        rows.append(
            {
                "bar_index": index,
                "open_time": open_time.isoformat().replace("+00:00", "Z"),
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
        )
    return pd.DataFrame(rows)


def _annotations(observations: pd.DataFrame) -> pd.DataFrame:
    decisions = [
        HumanDecision.ENTRY,
        HumanDecision.REJECT,
        HumanDecision.UNLABELED,
        HumanDecision.UNLABELED,
    ]
    rows = []
    for index, observation in observations.head(4).reset_index(drop=True).iterrows():
        decision = decisions[index]
        rows.append(
            EntryAnnotation(
                annotation_id=f"ann_{index}",
                session_id="session_pipeline",
                symbol=str(observation["symbol"]),
                interval=str(observation["interval"]),
                bar_index=int(observation["bar_index"]) if decision is not HumanDecision.UNLABELED else None,
                bar_time=str(observation["bar_time"]),
                human_decision=decision,
                confidence=None if decision is HumanDecision.UNLABELED else 4,
                reason_tags=["manual_review"] if decision is not HumanDecision.UNLABELED else [],
                note="integration fixture",
                decision_timing=DecisionTiming(str(observation["decision_timing"])),
                created_at=f"2026-01-01T01:0{index}:00Z",
                app_version="test",
                is_active=decision is not HumanDecision.UNLABELED,
            ).to_dict()
            | {"observation_id": str(observation["observation_id"])}
        )
    return pd.DataFrame(rows)


def _run_pipeline(tmp_path):
    klines = _ohlcv()
    observations = generate_entry_observation_universe(
        klines,
        symbol="BTCUSDT",
        interval="1m",
        min_prior_drop_pct=0.005,
        min_range_pct=0.02,
        volume_ratio_threshold=1.2,
        volume_zscore_threshold=0.5,
        lower_shadow_ratio_threshold=0.35,
    ).head(4).reset_index(drop=True)
    annotations = _annotations(observations)
    context_features = build_entry_context_features(klines, observations)
    outcome_labels = build_entry_outcome_labels(klines, observations, horizons=[3, 5, 10, 20])
    split = chronological_train_val_test_split(observations, 0.5, 0.25, 0.25)
    prototype = fit_entry_prototype(context_features, annotations, FEATURE_COLS)
    scores = score_entry_similarity(context_features, prototype)
    review_queue = build_label_review_queue(
        scores,
        annotations,
        context_features,
        {"name": "high_similarity", "top_k": 2},
    )
    report = build_entry_logic_report(
        annotations_df=annotations,
        features_df=context_features,
        scores_df=scores,
        review_queue_df=review_queue,
        split_summary={
            "split_method": "purged_chronological",
            "train_count": len(split["train"]),
            "validation_count": len(split["val"]),
            "test_count": len(split["test"]),
            "unlabeled_scored_count": 2,
            "purged_count": 0,
            "embargoed_count": 0,
            "episode_leakage_count": 0,
            "horizon_bars": 5,
            "embargo_bars": 0,
        },
        metadata={
            "symbol": "BTCUSDT",
            "interval": "1m",
            "model_type": "prototype_similarity",
            "selected_threshold": 0.5,
            "threshold_tuning_metric": "precision_at_k",
            "validation_metrics": {"validation_precision_at_k": 1.0},
            "frozen_test_metrics": {"test_precision_at_k": 1.0},
            "review_queue_config": {"name": "high_similarity", "top_k": 2},
        },
        feature_cols=FEATURE_COLS,
    )
    write_entry_logic_report(tmp_path / "entry_logic_report.md", tmp_path / "entry_logic_report.json", report)
    return {
        "observations": observations,
        "annotations": annotations,
        "context_features": context_features,
        "outcome_labels": outcome_labels,
        "split": split,
        "prototype": prototype,
        "scores": scores,
        "review_queue": review_queue,
        "report": report,
        "markdown": (tmp_path / "entry_logic_report.md").read_text(encoding="utf-8"),
        "json_report": json.loads((tmp_path / "entry_logic_report.json").read_text(encoding="utf-8")),
    }


def test_entry_logic_research_pipeline_is_reproducible_without_future_leakage(tmp_path):
    first = _run_pipeline(tmp_path / "first")
    second = _run_pipeline(tmp_path / "second")

    assert len(first["observations"]) == 4
    assert first["observations"]["observation_id"].tolist() == second["observations"]["observation_id"].tolist()
    assert {"setup_bar_index", "decision_bar_index", "feature_cutoff_bar_index", "feature_timing_policy", "candle_id", "candidate_source", "data_version"} <= set(first["observations"].columns)
    assert first["scores"]["human_entry_similarity"].round(10).tolist() == second["scores"]["human_entry_similarity"].round(10).tolist()
    assert first["review_queue"]["observation_id"].tolist() == second["review_queue"]["observation_id"].tolist()
    assert first["review_queue"]["review_id"].tolist() == second["review_queue"]["review_id"].tolist()

    context_columns = " ".join(first["context_features"].columns).lower()
    assert {"setup_bar_index", "decision_bar_index", "feature_cutoff_bar_index", "feature_timing_policy"} <= set(first["context_features"].columns)
    assert first["context_features"].attrs["feature_quality_report"]["feature_timing_policy"]
    assert not any(token in context_columns for token in FORBIDDEN_CONTEXT_TOKENS)
    assert {"fwd_ret_5", "mfe_10", "mae_10", "hit_tp_10", "hit_sl_10"} <= set(first["outcome_labels"].columns)
    assert not {"fwd_ret_5", "mfe_10", "mae_10", "hit_tp_10", "hit_sl_10"} & set(first["context_features"].columns)

    score_columns = " ".join(first["scores"].columns).lower()
    assert "human_entry_similarity" in first["scores"].columns
    assert "buy_signal" not in score_columns

    assert set(first["annotations"]["human_decision"]) == {"ENTRY", "REJECT", "UNLABELED"}
    assert first["prototype"]["entry_count"] == 1
    assert first["review_queue"]["observation_id"].isin(
        first["annotations"].loc[first["annotations"]["human_decision"] == "UNLABELED", "observation_id"]
    ).all()
    assert not first["review_queue"]["observation_id"].isin(
        first["annotations"].loc[first["annotations"]["human_decision"].isin(["ENTRY", "REJECT"]), "observation_id"]
    ).any()

    assert first["split"]["train"]["bar_index"].max() < first["split"]["val"]["bar_index"].min()
    assert first["split"]["val"]["bar_index"].max() < first["split"]["test"]["bar_index"].min()

    report_text = first["markdown"]
    report_json = first["json_report"]
    assert report_json["annotation_overview"]["ENTRY"] == 1
    assert report_json["annotation_overview"]["REJECT"] == 1
    assert report_json["annotation_overview"]["UNLABELED"] == 2
    assert report_json["leakage_check"]["status"] == "PASS"
    assert report_json["feature_quality_report"]["feature_timing_policy"]
    assert report_json["dataset_summary"]["unlabeled_used_for_training"] is False
    assert report_json["split_summary"]["split_method"] == "purged_chronological"
    assert report_json["model_summary"]["threshold_tuning_metric"] == "precision_at_k"
    assert "UNLABELED not used for training" in report_text
    assert "test is frozen evaluation" in report_text
    assert "human_entry_similarity" in report_text
    assert "buy_signal" not in report_text
    assert any("交易信号" in statement for statement in report_json["risk_statements"])

def _long_ohlcv(count: int = 160) -> pd.DataFrame:
    rows = []
    current_setups = {20, 44, 68, 92, 116, 140}
    confirmation_setups = {32, 56, 80, 104, 128, 152}
    for index in range(count):
        base = 220.0 - index * 0.45
        open_price = base + 0.2
        close = base - 0.2
        high = max(open_price, close) + 0.25
        low = min(open_price, close) - 0.25
        volume = 100.0 + index % 7
        if index in current_setups:
            open_price = base
            close = base + 0.45
            high = close + 0.6
            low = base - 5.8
            volume = 700.0 + index
        if index in confirmation_setups:
            open_price = base
            close = base - 0.7
            high = base + 4.0
            low = base - 0.9
            volume = 720.0 + index
        if (index - 1) in confirmation_setups:
            open_price = base - 0.5
            close = base + 2.0
            high = close + 0.25
            low = open_price - 0.25
            volume = 220.0 + index
        rows.append(
            {
                "bar_index": index,
                "open_time": (pd.Timestamp("2026-01-01T00:00:00Z") + pd.Timedelta(minutes=index))
                .isoformat()
                .replace("+00:00", "Z"),
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
        )
    return pd.DataFrame(rows)


def _long_observations() -> pd.DataFrame:
    observations = generate_entry_observation_universe(
        _long_ohlcv(),
        symbol="BTCUSDT",
        interval="1m",
        drop_lookback=5,
        min_prior_drop_pct=0.005,
        min_range_pct=0.01,
        volume_ratio_threshold=1.2,
        volume_zscore_threshold=0.5,
        lower_shadow_ratio_threshold=0.35,
        confirmation_body_ratio_threshold=0.55,
    ).reset_index(drop=True)
    assert len(observations) >= 12
    assert "NEXT_BAR_CONFIRMATION" in set(observations["decision_timing"])
    return observations


def _annotation_payload(observation: pd.Series, decision: HumanDecision, index: int, *, annotation_id: str | None = None) -> dict:
    return EntryAnnotation(
        annotation_id=annotation_id or f"ann_long_{index:02d}",
        observation_id=str(observation["observation_id"]),
        session_id="session_long_pipeline",
        symbol=str(observation["symbol"]),
        interval=str(observation["interval"]),
        bar_index=int(observation["decision_bar_index"]),
        bar_time=str(observation["decision_bar_time"]),
        setup_bar_index=int(observation["setup_bar_index"]),
        decision_bar_index=int(observation["decision_bar_index"]),
        setup_bar_time=str(observation["setup_bar_time"]),
        decision_bar_time=str(observation["decision_bar_time"]),
        human_decision=decision,
        confidence=None if decision is HumanDecision.UNLABELED else 4,
        reason_tags=["manual_review"] if decision is not HumanDecision.UNLABELED else [],
        note=f"long pipeline {decision.value.lower()}",
        decision_timing=DecisionTiming(str(observation["decision_timing"])),
        annotation_version="entry_annotations_v1",
        created_at=f"2026-01-01T03:{index:02d}:00Z",
        updated_at=f"2026-01-01T03:{index:02d}:00Z",
        app_version="test",
        is_active=True,
    ).to_dict()


def _long_annotations(observations: pd.DataFrame) -> pd.DataFrame:
    decisions = [
        HumanDecision.ENTRY,
        HumanDecision.REJECT,
        HumanDecision.ENTRY,
        HumanDecision.REJECT,
        HumanDecision.ENTRY,
        HumanDecision.REJECT,
        HumanDecision.ENTRY,
        HumanDecision.REJECT,
        HumanDecision.ENTRY,
        HumanDecision.UNCERTAIN,
        HumanDecision.UNLABELED,
        HumanDecision.UNLABELED,
    ]
    rows = [
        _annotation_payload(observation, decisions[index], index)
        for index, (_, observation) in enumerate(observations.head(len(decisions)).iterrows())
    ]
    return pd.DataFrame(rows)


def _assert_no_forbidden_context_fields(frame: pd.DataFrame) -> None:
    lowered = " ".join(str(column).lower() for column in frame.columns)
    assert not any(token in lowered for token in FORBIDDEN_CONTEXT_TOKENS)
    assert "buy_signal" not in lowered


def _export_entry_logic_payload(
    observations: pd.DataFrame,
    annotations: pd.DataFrame,
    features: pd.DataFrame,
    outcomes: pd.DataFrame,
    experiment: dict,
    report: dict,
):
    def provider(session_id: str) -> dict[str, object]:
        assert session_id == SESSION_ID
        return {
            "entry_annotations": annotations,
            "entry_observation_universe": observations,
            "entry_context_features": features,
            "entry_outcome_labels": outcomes,
            "entry_logic_scores": experiment["scores"],
            "entry_review_queue": experiment["review_queue"],
            "split_summary": report["split_summary"],
        }

    return provider


def test_real_research_pipeline_runs_from_klines_to_exporter(tmp_path):
    klines = _long_ohlcv()
    observations = _long_observations()
    annotations = _long_annotations(observations)
    labeled_ids = set(annotations.loc[annotations["human_decision"].isin(["ENTRY", "REJECT"]), "observation_id"])
    uncertain_ids = set(annotations.loc[annotations["human_decision"] == "UNCERTAIN", "observation_id"])
    unlabeled_ids = set(annotations.loc[annotations["human_decision"] == "UNLABELED", "observation_id"])

    features_setup_only = build_entry_context_features(
        klines,
        observations,
        feature_spec=FeatureSpec(feature_version="entry_context_long_v1", allow_confirmation_bar=False),
    )
    features_with_confirmation = build_entry_context_features(
        klines,
        observations,
        feature_spec=FeatureSpec(feature_version="entry_context_long_v2", allow_confirmation_bar=True),
    )
    next_setup_only = features_setup_only[features_setup_only["decision_timing"] == "NEXT_BAR_CONFIRMATION"]
    next_with_confirmation = features_with_confirmation[
        features_with_confirmation["decision_timing"] == "NEXT_BAR_CONFIRMATION"
    ]
    assert not next_setup_only.empty
    assert (next_setup_only["feature_cutoff_bar_index"] == next_setup_only["setup_bar_index"]).all()
    assert (next_with_confirmation["feature_cutoff_bar_index"] == next_with_confirmation["decision_bar_index"]).all()
    _assert_no_forbidden_context_fields(features_setup_only)
    _assert_no_forbidden_context_fields(features_with_confirmation)

    label_spec = LabelSpec(
        label_version="entry_outcome_long_v1",
        horizons=(5, 10),
        same_bar_policy="stop_loss_first",
    )
    outcomes = build_entry_outcome_labels(klines, observations, label_spec=label_spec)
    assert {"fwd_ret_5", "fwd_ret_10", "mfe_10", "mae_10", "hit_tp_10", "hit_sl_10"} <= set(outcomes.columns)
    assert set(outcomes.columns).isdisjoint(set(FEATURE_COLS))

    experiment = run_entry_logic_experiment(
        features_setup_only,
        annotations,
        feature_cols=FEATURE_COLS,
        output_dir=tmp_path / "experiment",
        split_config={
            "method": "purged_chronological",
            "train_ratio": 0.5,
            "validation_ratio": 0.25,
            "test_ratio": 0.25,
            "horizon_bars": 10,
            "embargo_bars": 2,
            "episode_gap_bars": 2,
        },
        model_config={"threshold_metric": "precision_at_k"},
        metadata={"app_version": "test", "label_version": label_spec.label_version},
        top_k=3,
        review_queue_config={"name": "high_similarity", "top_k": 3},
    )

    split_ids = set(experiment["split"].train["observation_id"]) | set(experiment["split"].validation["observation_id"]) | set(experiment["split"].test["observation_id"])
    split_decisions = pd.concat(
        [experiment["split"].train, experiment["split"].validation, experiment["split"].test],
        ignore_index=True,
    )["human_decision"]
    assert split_ids <= labeled_ids
    assert split_ids.isdisjoint(uncertain_ids)
    assert split_ids.isdisjoint(unlabeled_ids)
    assert set(split_decisions) <= {"ENTRY", "REJECT"}
    assert set(experiment["scored_unlabeled"]["observation_id"]) == unlabeled_ids
    assert set(experiment["review_queue"]["observation_id"]) <= unlabeled_ids
    assert experiment["threshold_selection"]["selected_on"] == "validation"
    assert experiment["threshold_selection"]["test_used_for_threshold"] is False
    assert experiment["test_metrics"]["threshold"] == experiment["threshold"]
    assert {"purged_count", "embargoed_count", "episode_leakage_count"} <= set(experiment["split_summary"])

    manifest = load_experiment_manifest(experiment["manifest_path"])
    assert manifest["split_method"] == "purged_chronological"
    assert manifest["feature_timing_policy"] == "setup_bar_only"
    assert manifest["allow_confirmation_bar"] is False
    assert manifest["validation_metrics"]
    assert manifest["frozen_test_metrics"]

    report = build_entry_logic_report(
        annotations_df=annotations,
        features_df=features_setup_only,
        outcomes_df=outcomes,
        scores_df=experiment["scores"],
        review_queue_df=experiment["review_queue"],
        split_summary={**experiment["split_summary"], "unlabeled_scored_count": len(experiment["scored_unlabeled"])},
        metadata={
            "model_type": experiment["model_config"]["model_type"],
            "selected_threshold": experiment["threshold"],
            "threshold_tuning_metric": "precision_at_k",
            "validation_metrics": experiment["threshold_selection"],
            "frozen_test_metrics": experiment["test_metrics"],
            "review_queue_config": {"name": "high_similarity", "top_k": 3},
        },
        feature_cols=FEATURE_COLS,
        outcome_cols=["fwd_ret_5", "fwd_ret_10", "mfe_10", "mae_10"],
    )
    write_entry_logic_report(tmp_path / "report.md", tmp_path / "report.json", report)
    markdown = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "not a trading signal" in markdown
    assert "UNLABELED not used for training" in markdown
    assert "test is frozen evaluation" in markdown
    assert "buy_signal" not in markdown

    storage = make_storage(tmp_path)
    insert_session(storage)
    insert_complete_trade(storage)
    export_dir = Exporter(
        storage,
        entry_logic_provider=_export_entry_logic_payload(observations, annotations, features_setup_only, outcomes, experiment, report),
    ).export_session(SESSION_ID, tmp_path / "exports")
    dictionary = (export_dir / "data_dictionary.md").read_text(encoding="utf-8").lower()
    exported_context = pd.read_csv(export_dir / "entry_context_features.csv")
    exported_outcomes = pd.read_csv(export_dir / "entry_outcome_labels.csv")
    assert "decision-time input candidate" in dictionary
    assert "post-event labels" in dictionary
    assert "not a trade list" in dictionary
    assert "buy_signal" not in dictionary
    _assert_no_forbidden_context_fields(exported_context)
    assert "fwd_ret_10" in exported_outcomes.columns


def test_annotation_decision_change_then_experiment_uses_active_version(tmp_path):
    observations = _long_observations()
    annotations = _long_annotations(observations)
    storage = StorageManager(tmp_path / "annotation_change_pipeline.db")
    first = annotations.iloc[0].to_dict()
    replacement = _annotation_payload(observations.iloc[0], HumanDecision.REJECT, 99, annotation_id="ann_replacement")
    storage.save_entry_annotation(first)
    storage.save_entry_annotation(replacement)
    for _, row in annotations.iloc[1:].iterrows():
        storage.save_entry_annotation(row.to_dict())

    active = storage.list_entry_annotations(session_id="session_long_pipeline")
    history = storage.list_entry_annotation_history(annotation_id=first["annotation_id"])
    active_for_first = [row for row in active if row.get("observation_id") == first["observation_id"]]
    assert len(active_for_first) == 1
    assert active_for_first[0]["human_decision"] == "REJECT"
    assert history[0]["previous_payload"]["human_decision"] == "ENTRY"

    features = build_entry_context_features(
        _long_ohlcv(),
        observations,
        feature_spec=FeatureSpec(feature_version="entry_context_long_v1", allow_confirmation_bar=False),
    )
    experiment = run_entry_logic_experiment(
        features,
        pd.DataFrame(active),
        feature_cols=FEATURE_COLS,
        output_dir=tmp_path / "rerun",
        split_config={
            "method": "purged_chronological",
            "train_ratio": 0.5,
            "validation_ratio": 0.25,
            "test_ratio": 0.25,
            "horizon_bars": 10,
            "embargo_bars": 2,
            "episode_gap_bars": 2,
        },
        metadata={"app_version": "test", "label_version": "entry_outcome_long_v1"},
        top_k=2,
    )
    counts = experiment["metrics"]["annotation_counts"]
    assert counts["ENTRY"] == 4
    assert counts["REJECT"] == 5
    assert counts["UNCERTAIN"] == 1
    assert counts["UNLABELED"] == 2
