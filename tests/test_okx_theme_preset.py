from __future__ import annotations

"""Pure-Python behaviour tests for the OKX dark preset and theme-driven styling.

These tests intentionally avoid importing Qt so they can run in any environment.
They verify that selecting a preset actually changes the resolved palette
(the previous bug: presets only set derived keys, which were overwritten by the
final derived-key sync, so switching presets did nothing).
"""

import app_config
from ui_style import (
    COLORS,
    EXCHANGE_DARK_THEME,
    OKX_DARK_THEME,
    THEME_SCHEMA_VERSION,
    build_app_qss,
    normalize_theme_settings,
)


def _qss_block(qss: str, selector: str) -> str:
    start = qss.index(selector)
    end = qss.index("}", start)
    return qss[start:end]


def test_okx_preset_is_registered_and_named():
    assert OKX_DARK_THEME["name"] == "黑色配色"
    assert OKX_DARK_THEME["name"] in app_config.THEME_PRESETS
    # Claude dark must remain available alongside OKX.
    assert EXCHANGE_DARK_THEME["name"] == "灰色配色"
    assert EXCHANGE_DARK_THEME["name"] in app_config.THEME_PRESETS


def test_okx_preset_uses_green_up_red_down_near_black_background():
    okx = normalize_theme_settings(OKX_DARK_THEME)
    # Near-black trading background, clearly darker than Claude neutral.
    assert okx["bg_primary"] == "#000000"
    # Green up / red down (OKX international default).
    assert okx["chart_up"] == "#2EBD85"
    assert okx["chart_down"] == "#EC5B5B"
    assert okx["success"] == "#2EBD85"
    assert okx["danger"] == "#F0577E"


def test_selecting_preset_actually_changes_resolved_palette():
    """Regression: presets must change token keys, not only derived aliases."""
    claude = normalize_theme_settings(EXCHANGE_DARK_THEME)
    okx = normalize_theme_settings(OKX_DARK_THEME)

    assert claude["bg_primary"] != okx["bg_primary"]
    assert claude["accent"] != okx["accent"]
    # Derived aliases must follow the token source after normalization.
    assert okx["window_bg"] == okx["bg_primary"]
    assert okx["candle_up"] == okx["chart_up"]
    assert okx["green"] == okx["success"]


def test_build_app_qss_renders_okx_tokens_for_chrome_and_buttons():
    qss = build_app_qss(OKX_DARK_THEME)
    okx = normalize_theme_settings(OKX_DARK_THEME)

    root = _qss_block(qss, "QMainWindow,")
    assert okx["bg_primary"] in root

    success_btn = _qss_block(qss, 'QPushButton[role="successButton"] {')
    assert okx["success_soft"] in success_btn

    danger_btn = _qss_block(qss, 'QPushButton[role="dangerButton"] {')
    assert okx["danger_soft"] in danger_btn


def test_claude_dark_remains_neutral_reference():
    claude = normalize_theme_settings(EXCHANGE_DARK_THEME)
    assert claude["bg_primary"] == COLORS["bg_primary"]
    assert claude["theme_schema_version"] == THEME_SCHEMA_VERSION


def test_okx_neutral_buttons_are_dark_pills_claude_stays_neutral():
    okx = normalize_theme_settings(OKX_DARK_THEME)
    claude = normalize_theme_settings(EXCHANGE_DARK_THEME)
    # Non-trade buttons: dark raised pill (lighter than the black chrome) + white
    # text in OKX; neutral grey in Claude.
    assert okx["btn_bg"] == "#202024"
    assert okx["btn_text"] == "#EAECEF"
    assert claude["btn_bg"] == COLORS["btn_bg"] != okx["btn_bg"]
    # Near-black OKX background, clearly darker than the buttons.
    assert okx["bg_primary"] == "#000000"


def test_build_app_qss_okx_buttons_white_rounded_and_trades_solid():
    qss = build_app_qss(OKX_DARK_THEME)
    okx = normalize_theme_settings(OKX_DARK_THEME)

    default_button = _qss_block(qss, "QPushButton {")
    assert okx["btn_bg"] in default_button
    assert okx["btn_text"] in default_button

    default_disabled = _qss_block(qss, "QPushButton:disabled {")
    assert okx["btn_bg"] in default_disabled
    assert okx["btn_text"] in default_disabled

    primary = _qss_block(qss, 'QPushButton[role="primaryButton"] {')
    assert okx["btn_bg"] in primary           # white fill
    assert okx["btn_text"] in primary         # dark text
    assert "border-radius: 14px" in primary   # rounded pill

    secondary = _qss_block(qss, 'QPushButton[role="secondaryButton"] {')
    assert okx["btn_bg"] in secondary
    assert "border-radius: 14px" in secondary

    danger_ghost = _qss_block(qss, 'QPushButton[role="dangerGhostButton"] {')
    assert okx["btn_bg"] in danger_ghost
    assert okx["btn_text"] in danger_ghost

    # Trade buttons stay coloured (solid green / pink) and rounded.
    success = _qss_block(qss, 'QPushButton[role="successButton"] {')
    assert okx["success_soft"] in success
    assert "border-radius: 14px" in success
    danger = _qss_block(qss, 'QPushButton[role="dangerButton"] {')
    assert okx["danger_soft"] in danger
    assert "border-radius: 14px" in danger

    success_disabled = _qss_block(qss, 'QPushButton[role="successButton"]:disabled {')
    assert okx["success_soft"] in success_disabled
    assert okx["success_text"] in success_disabled
    danger_disabled = _qss_block(qss, 'QPushButton[role="dangerButton"]:disabled {')
    assert okx["danger_soft"] in danger_disabled
    assert okx["danger_text"] in danger_disabled


def test_widget_effects_helpers_are_import_safe():
    """The shadow helpers must never raise, even with no Qt widget."""
    from views.widget_effects import apply_button_shadow, apply_role_button_shadows

    apply_button_shadow(None)
    assert apply_role_button_shadows(None) == 0


def test_role_button_local_qss_paints_the_fill():
    """The per-button local stylesheet must carry the background fill that the
    window-level stylesheet fails to paint on Fusion."""
    from ui_style import LOCAL_STYLE_BUTTON_ROLES, role_button_local_qss

    # Neutral action buttons, chips and the ghost button all get a local fill.
    assert {
        "primaryButton",
        "secondaryButton",
        "successButton",
        "dangerButton",
        "intervalChip",
        "compactButton",
        "dangerGhostButton",
    } <= set(LOCAL_STYLE_BUTTON_ROLES)

    okx = normalize_theme_settings(OKX_DARK_THEME)
    # Neutral buttons: a dark raised pill (distinct from the black chrome) + white text.
    assert okx["btn_bg"] == "#202024"
    assert f"background-color: {okx['btn_bg']}" in role_button_local_qss("primaryButton", OKX_DARK_THEME)
    assert f"color: {okx['btn_text']}" in role_button_local_qss("primaryButton", OKX_DARK_THEME)
    # Chips share the neutral fill; QToolButton selector is supported.
    assert f"background-color: {okx['btn_bg']}" in role_button_local_qss("intervalChip", OKX_DARK_THEME)
    assert "QToolButton {" in role_button_local_qss("compactButton", OKX_DARK_THEME, widget="QToolButton")
    # Trade buttons stay solid green / pink.
    assert "background-color: #2EBD85" in role_button_local_qss("successButton", OKX_DARK_THEME)
    assert "background-color: #F0577E" in role_button_local_qss("dangerButton", OKX_DARK_THEME)
    # Claude neutral buttons stay grey.
    assert "background-color: #2C2C2A" in role_button_local_qss("primaryButton", EXCHANGE_DARK_THEME)
    # Checkbox tag role is left alone.
    assert role_button_local_qss("tagChip", OKX_DARK_THEME) == ""


def test_themed_input_qss_matches_dark_pill():
    """Combo boxes, date editors and event-tag checkboxes share the dark fill."""
    from ui_style import themed_input_qss

    okx = normalize_theme_settings(OKX_DARK_THEME)
    combo = themed_input_qss("combo", OKX_DARK_THEME)
    assert "QComboBox {" in combo
    assert f"background-color: {okx['btn_bg']}" in combo
    assert "border-radius: 12px" in combo

    date = themed_input_qss("date", OKX_DARK_THEME)
    assert "QDateEdit {" in date
    assert f"background-color: {okx['btn_bg']}" in date

    tag = themed_input_qss("tagcheck", OKX_DARK_THEME)
    assert f"background-color: {okx['btn_bg']}" in tag
    assert f"background-color: {okx['accent_soft']}" in tag  # checked = accent
    assert "indicator {" in tag  # native tick hidden -> pill look
    assert themed_input_qss("unknown", OKX_DARK_THEME) == ""


def test_widget_effects_never_attach_graphics_effect():
    """Regression: a QGraphicsDropShadowEffect on a button both strips its QSS
    fill and aborts (native crash) when the widget is torn down via deleteLater.
    The helpers must stay no-ops and never wire one up."""
    import inspect

    import views.widget_effects as we

    assert "setGraphicsEffect" not in inspect.getsource(we)

    class _FakeButton:
        def property(self, _name):
            return "primaryButton"

        def setGraphicsEffect(self, _effect):  # pragma: no cover
            raise AssertionError("must not attach a graphics effect")

    assert we.apply_role_button_shadows(_FakeButton()) == 0
    we.apply_button_shadow(_FakeButton())
