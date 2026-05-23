from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

import api_server
from storage import StorageManager


def _seed_storage(tmp_path):
    storage = StorageManager(tmp_path / "api.db")
    storage.upsert_session(
        {
            "session_id": "sess_api",
            "symbol": "BTCUSDT",
            "interval": "5m",
            "start_date_bjt": "2026-01-01",
            "end_date_bjt": "2026-01-02",
            "cursor_bar_index": 1,
            "follow_latest": 0,
            "speed": 1.0,
            "last_opened_at": "2026-01-01T00:00:00+08:00",
            "last_saved_at": "2026-01-01T00:00:00+08:00",
            "app_version": "test",
        }
    )
    return storage


def test_health_endpoint():
    client = TestClient(api_server.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_invalid_session_id_returns_400(monkeypatch, tmp_path):
    monkeypatch.setattr(api_server, "storage", _seed_storage(tmp_path))
    client = TestClient(api_server.app)
    resp = client.get("/api/session/bad$id/summary")
    assert resp.status_code == 400


def test_llm_context_endpoint_does_not_leak_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(api_server, "storage", _seed_storage(tmp_path))
    client = TestClient(api_server.app)

    resp = client.get("/api/session/sess_api/llm-context?max_rows=1")

    assert resp.status_code == 200
    text = resp.text
    assert str(tmp_path) not in text
    assert "forbidden_interpretations" in text


def test_mock_analysis_returns_text(monkeypatch, tmp_path):
    monkeypatch.setattr(api_server, "storage", _seed_storage(tmp_path))
    client = TestClient(api_server.app)

    resp = client.post("/api/session/sess_api/llm-analysis/mock")

    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]
    assert data["not_investment_advice"] is True
