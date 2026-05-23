from __future__ import annotations

import json

from app_settings import load_app_settings, save_app_settings


def test_app_settings_save_and_load(tmp_path):
    path = tmp_path / "app_settings.json"
    save_app_settings(
        {
            "language": "en_US",
            "llm_provider": "mock",
            "fee_bps": 5.5,
            "openai_api_key": "should-not-be-saved",
            "api_key": "should-not-be-saved",
        },
        path,
    )

    loaded = load_app_settings(path)
    raw = json.loads(path.read_text(encoding="utf-8"))

    assert loaded["language"] == "en_US"
    assert loaded["llm_provider"] == "mock"
    assert loaded["fee_bps"] == 5.5
    assert "openai_api_key" not in raw
    assert "api_key" not in raw


def test_app_settings_missing_file_uses_defaults(tmp_path):
    loaded = load_app_settings(tmp_path / "missing.json")
    assert loaded["language"] == "zh_CN"
    assert loaded["llm_provider"] == "mock"
