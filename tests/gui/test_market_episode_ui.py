from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest


QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from research.market_episodes import (
    MarketEpisodeService,
    ResearchSampleWindow,
    TimeRange,
)
from storage import StorageManager
from views.decision_research_workspace import DecisionResearchWorkspace


def _at(minute: int) -> datetime:
    return datetime(2026, 6, 1, tzinfo=UTC) + timedelta(minutes=minute)


def test_decision_research_renders_episode_composition_and_correction_entry(tmp_path):
    service = MarketEpisodeService(StorageManager(tmp_path / "episodes.db"))
    grouping = service.create_automatic_grouping(
        (
            ResearchSampleWindow(
                sample_id="btc",
                symbol="BTCUSDT",
                timeframe="1m",
                feature_window=TimeRange(_at(0), _at(10)),
                outcome_window=TimeRange(_at(10), _at(20)),
            ),
            ResearchSampleWindow(
                sample_id="eth",
                symbol="ETHUSDT",
                timeframe="5m",
                feature_window=TimeRange(_at(15), _at(25)),
                outcome_window=TimeRange(_at(25), _at(30)),
            ),
        ),
        created_at=_at(100),
    )
    workspace = DecisionResearchWorkspace(language="zh_CN")
    requested: list[str] = []
    workspace.episodeCorrectionRequested.connect(requested.append)

    try:
        workspace.render_episode_audit(
            service.audit_summary(grouping.grouping_version_id)
        )

        assert workspace.episodeAuditTitle.text() == "独立行情片段"
        assert "1 个片段" in workspace.episodeAuditSummary.text()
        assert "2 个样本" in workspace.episodeAuditSummary.text()
        assert "BTCUSDT" in workspace.episodeCompositionText.text()
        assert "ETHUSDT" in workspace.episodeCompositionText.text()
        assert "1m" in workspace.episodeCompositionText.text()
        assert "5m" in workspace.episodeCompositionText.text()
        assert "自动" in workspace.episodeCompositionText.text()

        workspace.btnCorrectEpisodes.click()

        assert requested == [grouping.grouping_version_id]
    finally:
        workspace.close()
