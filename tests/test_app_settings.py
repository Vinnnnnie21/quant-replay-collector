from __future__ import annotations

import json

import pytest

import app_config
from app_settings import build_app_settings_update, load_app_settings, save_app_settings


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


def test_build_app_settings_update_preserves_existing_safe_values_and_drops_secrets():
    settings = build_app_settings_update(
        {
            "language": "zh_CN",
            "llm_provider": "mock",
            "custom_setting": "keep",
            "api_key": "secret",
        },
        language="en_US",
        llm_provider="local",
        local_api_url="http://127.0.0.1:8765",
        fill_mode="CLOSE",
        fee_bps=5.0,
        slippage_bps=2.0,
        trade_notional=2_000.0,
        initial_equity=20_000.0,
    )

    assert settings["language"] == "en_US"
    assert settings["llm_provider"] == "local"
    assert settings["custom_setting"] == "keep"
    assert settings["fill_mode"] == "CLOSE"
    assert settings["fee_bps"] == 5.0
    assert settings["trade_notional"] == 2_000.0
    assert "api_key" not in settings


def test_broken_app_settings_are_backed_up_and_defaulted(tmp_path):
    path = tmp_path / "app_settings.json"
    path.write_text("{broken", encoding="utf-8")

    with pytest.warns(UserWarning, match="invalid"):
        loaded = load_app_settings(path)

    assert loaded["language"] == "zh_CN"
    assert list(tmp_path.glob("app_settings.*.broken.json"))


def test_broken_theme_settings_are_backed_up_and_defaulted(tmp_path, monkeypatch):
    path = tmp_path / "theme_settings.json"
    path.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(app_config, "THEME_CONFIG_PATH", path)

    with pytest.warns(UserWarning, match="invalid"):
        loaded = app_config.load_theme_settings()

    assert loaded["name"] == app_config.DEFAULT_THEME["name"]
    assert list(tmp_path.glob("theme_settings.*.broken.json"))
