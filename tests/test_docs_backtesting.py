from __future__ import annotations

from pathlib import Path


def test_backtesting_document_describes_current_research_only_workflow():
    path = Path(__file__).resolve().parents[1] / "docs" / "backtesting.md"
    text = path.read_text(encoding="utf-8")
    lower = text.lower()

    assert "strategyruleparams" in lower
    assert "deep_v_reversal" in lower
    assert "long_only" in lower
    assert "open_time_bjt" in lower
    assert "[start, end)" in lower
    assert "manual-vs-rule" in lower
    assert "research-only" in lower
    assert "no live trading" in lower
    assert "no investment advice" in lower
    assert "fwd_ret" in lower
    assert "outcome_labels" in lower
    assert "future profit guarantee" not in lower
