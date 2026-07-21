from __future__ import annotations

import self_check


def test_core_is_default_and_does_not_run_gui(monkeypatch):
    monkeypatch.setattr(self_check, "_run_core_check", lambda: {"status": "ok", "warnings": []})
    monkeypatch.setattr(self_check, "_gui_dependency_check", lambda: (_ for _ in ()).throw(AssertionError("gui called")))
    result = self_check.run_self_check()
    assert result["status"] == "ok"
    assert result["mode"] == "core"


def test_gui_mode_reports_dependency_failure(monkeypatch):
    monkeypatch.setattr(
        self_check,
        "_gui_dependency_check",
        lambda: {"status": "failed", "available": False, "reason": "GUI dependency unavailable: PySide6"},
    )
    result = self_check.run_self_check("gui")
    assert result["status"] == "failed"
    assert "PySide6" in result["gui"]["reason"]


def test_all_mode_runs_core_and_gui(monkeypatch):
    monkeypatch.setattr(self_check, "_run_core_check", lambda: {"status": "ok", "warnings": []})
    monkeypatch.setattr(self_check, "_gui_dependency_check", lambda: {"status": "ok", "available": True, "reason": None})
    result = self_check.run_self_check("all")
    assert result["status"] == "ok"
    assert result["gui"]["available"] is True


def test_all_mode_reports_gui_even_if_core_fails(monkeypatch):
    monkeypatch.setattr(self_check, "_run_core_check", lambda: {"status": "failed", "warnings": []})
    monkeypatch.setattr(self_check, "_gui_dependency_check", lambda: {"status": "failed", "available": False, "reason": "missing GUI"})
    result = self_check.run_self_check("all")
    assert result["status"] == "failed"
    assert result["gui"]["reason"] == "missing GUI"
