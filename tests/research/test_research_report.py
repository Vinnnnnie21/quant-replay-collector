from __future__ import annotations

import json

import pytest

from app_config import APP_VERSION
from research.dataset import run_research_pack
from tests.research.test_feature_label_separation import research_input


def test_research_pack_writes_report_and_manifest(tmp_path):
    windows, events, trades = research_input(40)
    result = run_research_pack(tmp_path, windows, events, trades)
    report_path = tmp_path / "research_report.md"
    manifest_path = tmp_path / "research_manifest.json"
    assert report_path.exists()
    assert manifest_path.exists()
    text = report_path.read_text(encoding="utf-8")
    assert "未来函数审计" in text
    assert "候选规则不是交易信号" in text
    assert "因子 IC" in text
    assert "近似 p-value" in text
    assert "探索性证据" in text
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["experiment_id"].startswith("exp_")
    assert len(manifest["dataset_hash"]) == 64
    assert manifest["application_version"] == APP_VERSION
    calculations = {item["calculation"] for item in manifest["randomized_statistics"]}
    assert "iid_bootstrap_event_study" in calculations
    assert "block_bootstrap_factor_ic" in calculations
    assert result["leakage_audit"]["status"] == "PASS"


def test_research_manifest_records_actual_randomized_resource_settings(tmp_path):
    windows, events, trades = research_input(40)

    result = run_research_pack(tmp_path, windows, events, trades)

    manifest = json.loads((tmp_path / "research_manifest.json").read_text(encoding="utf-8"))
    settings = manifest["randomized_statistics"]
    required = {
        "calculation",
        "random_seed",
        "simulation_count",
        "confidence",
        "method_version",
        "application_version",
        "batch_size",
        "batch_count",
        "work_items",
        "resource_budget",
        "max_batch_work_items",
    }
    assert settings
    assert all(required <= set(item) for item in settings)
    assert all(item["application_version"] == APP_VERSION for item in settings)
    json.dumps(settings, allow_nan=False)
    first_event_setting = next(
        item for item in settings if item["calculation"] == "iid_bootstrap_event_study"
    )
    source_row = result["event_study"].iloc[first_event_setting["execution_index"]]
    assert first_event_setting["work_items"] == source_row["bootstrap_work_items"]
    assert first_event_setting["batch_size"] == source_row["bootstrap_batch_size"]
    assert first_event_setting["resource_budget"] == source_row["bootstrap_resource_budget"]


def test_research_pack_resource_limit_does_not_write_success_manifest(tmp_path):
    windows, events, trades = research_input(40)

    with pytest.raises(ValueError, match="bootstrap resource limit exceeded"):
        run_research_pack(
            tmp_path,
            windows,
            events,
            trades,
            randomized_max_work_items=1,
        )

    assert not (tmp_path / "research_manifest.json").exists()


def test_research_pack_cancellation_propagates_without_success_manifest(tmp_path):
    windows, events, trades = research_input(40)

    with pytest.raises(RuntimeError, match="research calculation cancelled") as exc_info:
        run_research_pack(
            tmp_path,
            windows,
            events,
            trades,
            cancelled=lambda: True,
        )

    assert type(exc_info.value).__name__ == "ResearchCancelled"
    assert not (tmp_path / "research_manifest.json").exists()


def test_research_pack_csv_cancellation_does_not_publish_partial_output(tmp_path):
    windows, events, trades = research_input(40)
    cancel_requested = False

    def progress(message: str) -> None:
        nonlocal cancel_requested
        if message == "Writing research table: feature_registry.csv (chunk 1/1)":
            cancel_requested = True

    with pytest.raises(RuntimeError, match="research calculation cancelled") as exc_info:
        run_research_pack(
            tmp_path,
            windows,
            events,
            trades,
            cancelled=lambda: cancel_requested,
            progress=progress,
        )

    assert type(exc_info.value).__name__ == "ResearchCancelled"
    assert not (tmp_path / "feature_registry.csv").exists()
    assert not list(tmp_path.glob("*.partial"))
    assert not (tmp_path / "research_manifest.json").exists()


def test_research_report_supports_english_output(tmp_path):
    windows, events, trades = research_input(40)
    run_research_pack(tmp_path, windows, events, trades, language="en_US")
    text = (tmp_path / "research_report.md").read_text(encoding="utf-8")
    assert "# Quant Research Report" in text
    assert "Leakage Audit" in text
    assert "not trading signals" in text
    assert "Factor IC" in text
    assert "approximate p-value" in text
    assert "Randomized Statistics" in text
    assert "random_seed=42" in text
    assert "simulation_count=1000" in text
    assert "confidence=0.95" in text
    assert "resource_budget=" in text
    assert "work_items=" in text
    assert "batch_size=" in text
    assert "batch_count=" in text
    assert "method_version=" in text
