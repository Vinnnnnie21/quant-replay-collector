from __future__ import annotations

import json
import sys
from types import SimpleNamespace

from startup import (
    StartupTimeline,
    native_smoke_exit_delay_ms,
    native_smoke_workspace,
    open_native_smoke_workspace,
)


def test_startup_timeline_is_opt_in_and_records_named_milestones(tmp_path):
    disabled = StartupTimeline.from_environment({}, clock=lambda: 10.0)
    disabled.mark("process_start")
    assert disabled.events == ()

    ticks = iter((20.0, 20.2, 20.5))
    output = tmp_path / "startup.json"
    enabled = StartupTimeline.from_environment(
        {
            "QRC_STARTUP_TIMING": "1",
            "QRC_STARTUP_TIMING_FILE": str(output),
        },
        clock=lambda: next(ticks),
    )
    enabled.mark("process_start")
    enabled.mark("qapplication_ready")
    enabled.mark("storage_ready")
    enabled.flush()

    assert tuple(event.name for event in enabled.events) == (
        "process_start",
        "qapplication_ready",
        "storage_ready",
    )
    assert tuple(event.elapsed_seconds for event in enabled.events) == (
        0.0,
        0.2,
        0.5,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["events"][-1] == {
        "name": "storage_ready",
        "elapsed_seconds": 0.5,
    }


def test_package_entrypoint_propagates_friendly_startup_exit_code(monkeypatch):
    from quant_collector_app import __main__ as package_main

    monkeypatch.setitem(sys.modules, "main_app", SimpleNamespace(main=lambda: 2))

    assert package_main.main() == 2


def test_startup_timeline_uses_process_origin_from_launcher_environment():
    ticks = iter((101.25, 102.0))
    timeline = StartupTimeline.from_environment(
        {
            "QRC_STARTUP_TIMING": "1",
            "QRC_PROCESS_START_PERF_COUNTER": "100.0",
        },
        clock=lambda: next(ticks),
    )

    timeline.mark("process_start")
    timeline.mark("qapplication_ready")

    assert tuple(event.elapsed_seconds for event in timeline.events) == (
        0.0,
        2.0,
    )


def test_native_smoke_exit_delay_is_opt_in_and_bounded():
    assert native_smoke_exit_delay_ms({}) is None
    assert native_smoke_exit_delay_ms({"QRC_NATIVE_SMOKE_EXIT_MS": "750"}) == 750
    assert native_smoke_exit_delay_ms({"QRC_NATIVE_SMOKE_EXIT_MS": "0"}) is None
    assert native_smoke_exit_delay_ms({"QRC_NATIVE_SMOKE_EXIT_MS": "999999"}) is None
    assert native_smoke_exit_delay_ms({"QRC_NATIVE_SMOKE_EXIT_MS": "bad"}) is None


def test_native_smoke_workspace_is_allowlisted_and_drives_public_navigation():
    assert native_smoke_workspace({}) is None
    assert native_smoke_workspace({"QRC_NATIVE_SMOKE_WORKSPACE": "unknown"}) is None
    assert native_smoke_workspace({"QRC_NATIVE_SMOKE_WORKSPACE": "decision_exit"}) == "decision_exit"

    calls: list[object] = []

    class Tabs:
        def setCurrentIndex(self, value):
            calls.append(("mode", value))

    class Button:
        def click(self):
            calls.append("report")

    class Decision:
        modeTabs = Tabs()
        stepButtons = {"version_report": Button()}

    class Analysis:
        decisionResearchWorkspace = Decision()

    class Window:
        _analysis_workspace = Analysis()

        def open_analysis_workspace(self):
            calls.append("analysis")

        def open_decision_research_workspace(self):
            calls.append("decision")

    window = Window()
    open_native_smoke_workspace(window, "analysis")
    open_native_smoke_workspace(window, "decision_entry")
    open_native_smoke_workspace(window, "decision_exit")
    open_native_smoke_workspace(window, "version_report")

    assert calls == [
        "analysis",
        "decision",
        ("mode", 0),
        "decision",
        ("mode", 1),
        "decision",
        "report",
    ]
