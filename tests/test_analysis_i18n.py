"""i18n contract for the data-analysis page.

Guards against language mixing on the analysis workspace:
  - no hard-coded alphabetic UI text (everything user-visible goes through _tr),
  - every static tr key it uses exists in BOTH zh_CN and en_US,
  - the en_US table never falls back to Chinese for those keys.

These are pure source/JSON checks, so they run without Qt.
"""

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "quant_collector_app"
SRC = (APP / "analysis_workspace.py").read_text(encoding="utf-8")
ZH = json.loads((APP / "translations" / "zh_CN.json").read_text(encoding="utf-8"))
EN = json.loads((APP / "translations" / "en_US.json").read_text(encoding="utf-8"))

_UI_SETTERS = {
    "setText", "setPlainText", "setPlaceholderText", "setToolTip", "setWindowTitle",
    "setTabText", "setTitle", "setHorizontalHeaderLabels", "addItem", "insertItem",
}
_UI_CTORS = {"QPushButton", "QLabel", "QCheckBox", "QRadioButton", "QGroupBox", "QAction", "QToolButton"}
_CJK = re.compile(r"[一-鿿]")


def _hardcoded_ui_literals():
    hits = []
    for node in ast.walk(ast.parse(SRC)):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
        if name in _UI_SETTERS or name in _UI_CTORS:
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and any(c.isalpha() for c in arg.value):
                    hits.append((node.lineno, name, arg.value))
    return hits


def _static_keys():
    keys = set(re.findall(r'_tr\(\s*["\']([^"\']+)["\']', SRC))
    keys |= set(re.findall(r'(?<![\w.])tr\(\s*["\']([^"\']+)["\']', SRC))
    return {k for k in keys if "{" not in k}


def test_no_hardcoded_ui_text_in_analysis_workspace():
    hits = _hardcoded_ui_literals()
    assert hits == [], f"hard-coded UI text must go through _tr: {hits}"


def test_all_static_keys_present_in_both_languages():
    keys = _static_keys()
    missing_zh = sorted(k for k in keys if k not in ZH)
    missing_en = sorted(k for k in keys if k not in EN)
    assert not missing_zh, f"keys missing from zh_CN: {missing_zh}"
    assert not missing_en, f"keys missing from en_US: {missing_en}"


def test_english_table_not_chinese_for_used_keys():
    bad = sorted(k for k in _static_keys() if k in EN and _CJK.search(EN[k]))
    assert not bad, f"en_US still Chinese for: {bad}"


def test_entry_decision_keys_exist_in_both_languages():
    for key in ("entry_logic.entry", "entry_logic.reject", "entry_logic.uncertain"):
        assert key in ZH, f"{key} missing from zh_CN"
        assert key in EN, f"{key} missing from en_US"
