from __future__ import annotations

from project_paths import REPO_ROOT


def test_v160_capture_creates_an_explicit_incomplete_range_before_waiting():
    source = (
        REPO_ROOT / "scripts" / "capture_v160_acceptance.py"
    ).read_text(encoding="utf-8")

    range_change = source.index("missing_data_date = QtCore.QDate")
    report_capture = source.index('decision.stepButtons["version_report"].click()')
    audit_click = source.index("decision.btnAuditResearchData.click()")
    incomplete_wait = source.index(
        'wait_until(app, lambda: decision.state.completeness == "incomplete")'
    )
    assert report_capture < range_change < audit_click < incomplete_wait
