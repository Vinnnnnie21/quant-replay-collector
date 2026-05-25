from __future__ import annotations

from pathlib import Path


class AnalysisService:
    """Lazy research-pack entry point used by background work."""

    def run_research_pack(
        self,
        output_dir: Path,
        windows,
        events,
        trades,
        selected_label: str = "fwd_ret_10_side_adj",
        language: str = "zh_CN",
    ):
        from research.dataset import run_research_pack

        return run_research_pack(
            Path(output_dir),
            windows,
            events,
            trades,
            selected_label=selected_label,
            language=language,
        )


__all__ = ["AnalysisService"]
