from __future__ import annotations

import app_health


def test_health_report_checks_runtime_paths_and_database(tmp_path, monkeypatch):
    monkeypatch.setattr(app_health, "REQUIRED_DEPENDENCIES", ("json",))
    report = app_health.run_health_checks(tmp_path / "runtime", tmp_path / "health.db")

    assert report["status"] == "ok"
    assert report["database"]["connectable"] is True
    assert all(row["writable"] for row in report["directories"])


def test_health_report_marks_missing_required_dependency(tmp_path, monkeypatch):
    monkeypatch.setattr(app_health, "REQUIRED_DEPENDENCIES", ("qrc_missing_dependency_123",))
    report = app_health.run_health_checks(tmp_path / "runtime", tmp_path / "health.db")

    assert report["status"] == "failed"
    assert "missing dependency: qrc_missing_dependency_123" in report["errors"]


def test_core_health_check_does_not_require_gui_dependencies(tmp_path, monkeypatch):
    monkeypatch.setattr(app_health, "CORE_REQUIRED_DEPENDENCIES", ("json",))
    monkeypatch.setattr(app_health, "GUI_REQUIRED_DEPENDENCIES", ("qrc_missing_gui_dependency_123",))
    report = app_health.run_health_checks(tmp_path / "runtime", require_gui=False)
    assert report["status"] == "ok"
    assert "qrc_missing_gui_dependency_123" not in report["required_dependencies"]
