from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from PySide6 import QtWidgets

from app_i18n import tr
from analysis.feature_engineering import build_enhanced_event_features
from strategy_consistency.consistency import analyze_strategy_consistency
from strategy_consistency.profile import default_reversal_long_profile
from strategy_consistency.report import write_strategy_consistency_report
from ui_style import style_primary_button, style_secondary_button


WARNING_CODE_PATTERNS = [
    ("low_sample_count", ("sample_count below", "sample count is below")),
    ("mixed_direction", ("direction_consistency_pct below", "direction is mixed")),
    ("high_untagged", ("untagged_pct too high", "many events have no tags")),
    ("high_missing_note", ("missing_note_pct above", "many events have no notes")),
    ("low_similar_context_agreement", ("similar_context_agreement_pct too low", "fewer than 3 usable context features")),
    ("possible_selection_bias", ("possible_selection_bias", "selection bias")),
    ("forbidden_tags", ("forbidden_tag_hit_count", "forbidden tag")),
]


def warning_code_to_text(code_or_text: str, language: str = "zh_CN") -> str:
    text = str(code_or_text or "")
    normalized = text.strip().lower()
    for code, patterns in WARNING_CODE_PATTERNS:
        if normalized == code or any(pattern in normalized for pattern in patterns):
            return tr(f"warning_{code}", language, text)
    return text


class StrategyConsistencyPanel(QtWidgets.QWidget):
    def __init__(self, app_window, parent=None):
        super().__init__(parent)
        self.app_window = app_window
        self.last_result: dict | None = None
        self._build_ui()

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        self.summaryText = QtWidgets.QPlainTextEdit()
        self.summaryText.setReadOnly(True)

        row = QtWidgets.QHBoxLayout()
        self.btnRun = QtWidgets.QPushButton()
        self.btnExport = QtWidgets.QPushButton()
        self.btnRun.setStyleSheet(style_primary_button())
        self.btnExport.setStyleSheet(style_secondary_button())
        row.addWidget(self.btnRun)
        row.addWidget(self.btnExport)

        root.addLayout(row)
        root.addWidget(self.summaryText, stretch=1)
        self.btnRun.clicked.connect(self.run_audit)
        self.btnExport.clicked.connect(self.export_report)
        self.retranslate_ui()

    def _language(self) -> str:
        return str(getattr(self.app_window, "current_language", "zh_CN") or "zh_CN")

    def _tr(self, key: str, default: str | None = None) -> str:
        return tr(key, self._language(), default)

    def retranslate_ui(self):
        self.btnRun.setText(self._tr("run_consistency_audit"))
        self.btnExport.setText(self._tr("export_consistency_report"))
        if self.last_result:
            self.summaryText.setPlainText(self._format_result(self.last_result))
        else:
            self.summaryText.setPlainText(self._tr("consistency_not_run_hint"))

    def _session_id(self) -> str | None:
        return getattr(self.app_window, "session_id", None)

    def _table(self, name: str) -> pd.DataFrame:
        session_id = self._session_id()
        storage = getattr(self.app_window, "storage", None)
        if not session_id or storage is None:
            return pd.DataFrame()
        try:
            return pd.DataFrame(storage.fetch_table(name, "session_id=?", (session_id,)))
        except Exception:
            return pd.DataFrame()

    def _features_for_audit(self, events: pd.DataFrame) -> tuple[pd.DataFrame, list[str], str]:
        windows = self._table("event_windows")
        fallback = self._table("event_features")
        try:
            enhanced = build_enhanced_event_features(windows, events)
            if isinstance(enhanced, pd.DataFrame) and not enhanced.empty:
                return enhanced, [], "enhanced_event_features"
            return fallback, ["enhanced_event_features is empty; fallback to event_features."], "event_features_fallback"
        except Exception as exc:
            return fallback, [f"enhanced_event_features failed; fallback to event_features: {type(exc).__name__}: {exc}"], "event_features_fallback"

    def _format_result(self, result: dict) -> str:
        warnings = result.get("warnings") or []
        gates = result.get("gate_failures") or []
        lines = [
            self._tr("consistency_audit_title"),
            "",
            f"{self._tr('consistency_score')}: {result.get('strategy_consistency_score')}",
            f"{self._tr('recommendation')}: {result.get('recommendation')}",
            f"{self._tr('sample_count')}: {result.get('sample_count')}",
            f"{self._tr('direction_consistency_pct')}: {result.get('direction_consistency_pct')}",
            f"{self._tr('untagged_pct')}: {result.get('untagged_pct')}",
            f"{self._tr('missing_note_pct')}: {result.get('missing_note_pct')}",
            f"{self._tr('similar_context_agreement_pct')}: {result.get('similar_context_agreement_pct')}",
            f"{self._tr('profile_feature_match_all_pct')}: {result.get('profile_feature_match_all_pct')}",
            f"{self._tr('feature_source')}: {result.get('feature_source')}",
            "",
            f"{self._tr('gate_failures')}:",
        ]
        language = self._language()
        lines.extend([f"- {warning_code_to_text(g, language)}" for g in gates] or [f"- {self._tr('none')}"])
        lines.extend(["", f"{self._tr('warnings')}:"])
        lines.extend([f"- {warning_code_to_text(w, language)}" for w in warnings] or [f"- {self._tr('none')}"])
        lines.extend(["", self._tr("consistency_disclaimer")])
        return "\n".join(lines)

    def run_audit(self):
        try:
            events = self._table("trade_events")
            trades = self._table("trades")
            features, feature_warnings, source = self._features_for_audit(events)
            result = analyze_strategy_consistency(events, features, trades, default_reversal_long_profile())
            result["feature_source"] = source
            if feature_warnings:
                result.setdefault("warnings", [])
                result["warnings"].extend(feature_warnings)
            self.last_result = result
            self.summaryText.setPlainText(self._format_result(result))
        except Exception as exc:
            self.summaryText.setPlainText(f"{self._tr('consistency_audit_failed')}: {type(exc).__name__}: {exc}")

    def export_report(self):
        if not self.last_result:
            self.run_audit()
        if not self.last_result:
            return
        target = QtWidgets.QFileDialog.getExistingDirectory(self, self._tr("select_consistency_export_dir"))
        if not target:
            return
        try:
            out_dir = Path(target)
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "strategy_consistency.json").write_text(
                json.dumps(self.last_result, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            report = write_strategy_consistency_report(self.last_result, out_dir / "strategy_consistency_report.md")
            self.summaryText.appendPlainText(f"\n{self._tr('consistency_exported')}: {report}")
        except Exception as exc:
            self.summaryText.appendPlainText(f"\n{self._tr('consistency_export_failed')}: {type(exc).__name__}: {exc}")
