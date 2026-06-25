from __future__ import annotations

from textwrap import dedent


THEME_SCHEMA_VERSION = 3
THEME_NAME = "灰色配色"

def _rgb_hex(red: int, green: int, blue: int) -> str:
    return f"#{red:02x}{green:02x}{blue:02x}"


COLORS = {
    "bg_primary": "#1F1F1E",
    "bg_secondary": "#262626",
    "bg_tertiary": "#2C2C2A",
    "bg_card": "#2A2A28",
    "bg_input": "#1C1C1A",
    "bg_hover": "#31312F",
    "bg_pressed": "#181816",
    "border_default": "#3A3733",
    "border_strong": "#4A4742",
    "divider": "#2E2D2B",
    "text_primary": "#F6F6F4",
    "text_secondary": "#B5B3AD",
    "text_tertiary": "#8F8D83",
    "text_disabled": "#5C5A55",
    "accent": "#7A7772",
    "accent_hover": "#8E8B86",
    "accent_soft": "#22211F",
    "accent_text": "#B5B3AD",
    "focus": "#6B6863",
    "success": "#22C55E",
    "success_soft": "#123522",
    "success_text": "#A7E8BE",
    "success_hover": "#17452B",
    "success_pressed": "#0D2A1A",
    "danger": "#EF4444",
    "danger_soft": "#3A1719",
    "danger_text": "#F3A4A4",
    "danger_hover": "#4A1D20",
    "danger_pressed": "#2B1012",
    "danger_ghost_border": "#593036",
    "danger_ghost_text": "#B76A72",
    "danger_ghost_hover_bg": "#271417",
    "danger_ghost_hover_border": "#87404A",
    "danger_ghost_hover_text": "#E28D96",
    "warning": "#F59E0B",
    "warning_soft": "#39280D",
    "info": "#3B82F6",
    "selection": "#2E2E2C",
    "chart_bg": "#1F1F1E",
    "chart_up": "#22C55E",
    "chart_down": "#EF4444",
    "chart_volume_up": "#198C48",
    "chart_volume_down": "#AF3434",
    "chart_grid": "#2E2D2B",
    "chart_axis": "#6B6863",
    "chart_crosshair": "#8C8983",
    "chart_wick": "#B0ADA7",
    "marker_close_long": "#8DD5AA",
    "marker_close_short": "#E89A9A",
    # Neutral (non-trade) button surface. Themes override these; trade buttons
    # (open/close long/short) keep their success/danger colors.
    "btn_bg": "#2C2C2A",
    "btn_text": "#F6F6F4",
    "btn_hover": "#31312F",
    "btn_pressed": "#181816",
    "btn_border": "#4A4742",
}
COLORS.update(
    {
        "window_bg": COLORS["bg_primary"],
        "surface_0": COLORS["bg_primary"],
        "surface_1": COLORS["bg_secondary"],
        "surface_2": COLORS["bg_card"],
        "input_bg": COLORS["bg_input"],
        "hover_bg": COLORS["bg_hover"],
        "border_soft": COLORS["divider"],
        "border": COLORS["border_default"],
        "text_muted": COLORS["text_tertiary"],
        "brand": COLORS["accent"],
        "brand_hover": COLORS["accent_hover"],
        "brand_soft": COLORS["accent_soft"],
        "green": COLORS["success"],
        "green_dim": COLORS["success_soft"],
        "red": COLORS["danger"],
        "red_dim": COLORS["danger_soft"],
        "volume_green": COLORS["chart_volume_up"],
        "volume_red": COLORS["chart_volume_down"],
        "crosshair": COLORS["chart_crosshair"],
        "panel_bg": COLORS["bg_secondary"],
        "panel_bg_alt": COLORS["bg_card"],
        "accent_dim": COLORS["accent_soft"],
    }
)

THEME_TOKEN_KEYS = tuple(COLORS.keys())

_LEGACY_TO_TOKEN_KEYS = {
    "window_bg": "bg_primary",
    "panel_bg": "bg_secondary",
    "panel_bg_alt": "bg_card",
    "base_bg": "chart_bg",
    "chart_bg": "chart_bg",
    "text": "text_primary",
    "text_primary": "text_primary",
    "text_secondary": "text_secondary",
    "text_muted": "text_tertiary",
    "axis": "chart_axis",
    "grid": "chart_grid",
    "candle_up": "chart_up",
    "candle_down": "chart_down",
    "volume_up": "chart_volume_up",
    "volume_down": "chart_volume_down",
    "wick": "chart_wick",
    "current_price_up": "chart_up",
    "current_price_down": "chart_down",
    "crosshair": "chart_crosshair",
    "accent": "accent",
    "selection": "selection",
}

_DERIVED_THEME_KEYS = {
    "window_bg": "bg_primary",
    "surface_0": "bg_primary",
    "surface_1": "bg_secondary",
    "surface_2": "bg_card",
    "panel_bg": "bg_secondary",
    "panel_bg_alt": "bg_card",
    "base_bg": "chart_bg",
    "input_bg": "bg_input",
    "hover_bg": "bg_hover",
    "border": "border_default",
    "border_soft": "divider",
    "text": "text_primary",
    "text_muted": "text_tertiary",
    "axis": "chart_axis",
    "grid": "chart_grid",
    "candle_up": "chart_up",
    "candle_down": "chart_down",
    "volume_up": "chart_volume_up",
    "volume_down": "chart_volume_down",
    "wick": "chart_wick",
    "crosshair": "chart_crosshair",
    "brand": "accent",
    "brand_hover": "accent_hover",
    "brand_soft": "accent_soft",
    "green": "success",
    "green_dim": "success_soft",
    "red": "danger",
    "red_dim": "danger_soft",
    "volume_green": "chart_volume_up",
    "volume_red": "chart_volume_down",
    "accent_dim": "accent_soft",
}

SPACING = {
    "xs": 4,
    "sm": 6,
    "md": 8,
    "lg": 12,
    "xl": 16,
}

FONT_SIZES = {
    "small": 11,
    "normal": 12,
    "medium": 13,
    "large": 16,
}

EXCHANGE_DARK_THEME = {
    "name": THEME_NAME,
    "theme_schema_version": THEME_SCHEMA_VERSION,
    "window_bg": COLORS["window_bg"],
    "panel_bg": COLORS["panel_bg"],
    "panel_bg_alt": COLORS["panel_bg_alt"],
    "base_bg": COLORS["chart_bg"],
    "chart_bg": COLORS["chart_bg"],
    "text": COLORS["text_primary"],
    "text_primary": COLORS["text_primary"],
    "text_secondary": COLORS["text_secondary"],
    "text_muted": COLORS["text_muted"],
    "axis": COLORS["chart_axis"],
    "grid": COLORS["chart_grid"],
    "grid_alpha": 14,
    "candle_up": COLORS["chart_up"],
    "candle_down": COLORS["chart_down"],
    "volume_up": COLORS["chart_volume_up"],
    "volume_down": COLORS["chart_volume_down"],
    "wick": COLORS["chart_wick"],
    "current_price_up": COLORS["chart_up"],
    "current_price_down": COLORS["chart_down"],
    "current_price_label_text": "#07100D",
    "crosshair": COLORS["crosshair"],
    "crosshair_alpha": 95,
    "premium_buy": COLORS["success"],
    "premium_sell": COLORS["danger"],
    "premium_avg": COLORS["chart_axis"],
    "marker_close_long": COLORS["marker_close_long"],
    "marker_close_short": COLORS["marker_close_short"],
    "accent": COLORS["accent"],
    "selection": COLORS["selection"],
}

RESEARCH_SLATE_THEME = {
    **EXCHANGE_DARK_THEME,
    "name": "研究配色",
    "window_bg": COLORS["bg_primary"],
    "panel_bg": COLORS["bg_secondary"],
    "panel_bg_alt": COLORS["bg_card"],
    "base_bg": COLORS["chart_bg"],
    "chart_bg": COLORS["chart_bg"],
    "grid": COLORS["chart_grid"],
    "grid_alpha": 16,
}

CONTRAST_DARK_THEME = {
    **EXCHANGE_DARK_THEME,
    "name": "高对比配色",
    "window_bg": "#050709",
    "panel_bg": "#101720",
    "panel_bg_alt": "#202936",
    "base_bg": "#040607",
    "chart_bg": "#040607",
    "text": "#F2F6F8",
    "text_primary": "#F2F6F8",
    "text_secondary": "#C2CAD3",
    "axis": "#9AA4AE",
    "grid": "#2A3542",
    "grid_alpha": 20,
}


OKX_DARK_THEME = {
    "name": "黑色配色",
    "theme_schema_version": THEME_SCHEMA_VERSION,
    # Near-black trading chrome (OKX dark).
    "bg_primary": "#000000",
    "bg_secondary": "#0E0E10",
    "bg_tertiary": "#131316",
    "bg_card": "#17171A",
    "bg_input": "#0A0A0C",
    "bg_hover": "#1E1E22",
    "bg_pressed": "#050506",
    "border_default": "#26262A",
    "border_strong": "#34343A",
    "divider": "#1C1C20",
    "text_primary": "#EAECEF",
    "text_secondary": "#9A9CA3",
    "text_tertiary": "#6B6E76",
    "text_disabled": "#4A4C52",
    # Accent tied to the OKX buy-green for tab underline / focus.
    "accent": "#2EBD85",
    "accent_hover": "#34CE92",
    "accent_soft": "#0E2A1F",
    "accent_text": "#6FE3B0",
    "focus": "#1C6E4E",
    # Buy / long -> solid green button with white text.
    "success": "#2EBD85",
    "success_soft": "#2EBD85",
    "success_text": "#FFFFFF",
    "success_hover": "#29AB78",
    "success_pressed": "#23976A",
    # Sell / short -> solid pink-red button with white text.
    "danger": "#F0577E",
    "danger_soft": "#F0577E",
    "danger_text": "#FFFFFF",
    "danger_hover": "#E14B70",
    "danger_pressed": "#CE3F63",
    "danger_ghost_border": "#5A2A38",
    "danger_ghost_text": "#D17288",
    "danger_ghost_hover_bg": "#241218",
    "danger_ghost_hover_border": "#87405A",
    "danger_ghost_hover_text": "#EA8AA4",
    "warning": "#F5A623",
    "warning_soft": "#3A2A0E",
    "info": "#3D7EFF",
    "selection": "#1E1E22",
    # Non-trade buttons -> dark raised pills, clearly lifted off the black chrome,
    # with white text (and a drop shadow added at runtime for the float effect).
    "btn_bg": "#202024",
    "btn_text": "#EAECEF",
    "btn_hover": "#2A2A30",
    "btn_pressed": "#161619",
    "btn_border": "#3A3A40",
    # Chart layer (green up / red down).
    "chart_bg": "#000000",
    "chart_up": "#2EBD85",
    "chart_down": "#EC5B5B",
    "chart_volume_up": "#1C7F58",
    "chart_volume_down": "#8E3A44",
    "chart_grid": "#16161A",
    "chart_axis": "#6B6E76",
    "chart_crosshair": "#8A8D95",
    "chart_wick": "#A8AAB2",
    "marker_close_long": "#7FD8B4",
    "marker_close_short": "#F0A8B8",
    # Non-color theme knobs and derived-but-explicit chart helpers.
    "grid_alpha": 14,
    "crosshair_alpha": 95,
    "current_price_label_text": "#06120D",
    "current_price_up": "#2EBD85",
    "current_price_down": "#EC5B5B",
    "premium_buy": "#2EBD85",
    "premium_sell": "#EC5B5B",
    "premium_avg": "#6B6E76",
    "base_bg": "#000000",
}


_THEME_COLOR_KEYS = set(THEME_TOKEN_KEYS) | set(_LEGACY_TO_TOKEN_KEYS) | {
    "current_price_up",
    "current_price_down",
    "current_price_label_text",
    "premium_buy",
    "premium_sell",
    "premium_avg",
    "marker_close_long",
    "marker_close_short",
}


def _is_hex_color(value: object) -> bool:
    text = str(value).strip()
    if len(text) != 7 or not text.startswith("#"):
        return False
    return all(ch in "0123456789abcdefABCDEF" for ch in text[1:])


def _clamp_int(value: object, fallback: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, number))


def _base_theme_tokens() -> dict:
    theme = {key: value for key, value in COLORS.items() if _is_hex_color(value)}
    theme.update(
        {
            "name": THEME_NAME,
            "theme_schema_version": THEME_SCHEMA_VERSION,
            "grid_alpha": 14,
            "crosshair_alpha": 95,
            "current_price_label_text": "#0D0D0B",
            "premium_buy": COLORS["success"],
            "premium_sell": COLORS["danger"],
            "premium_avg": COLORS["chart_axis"],
            "marker_close_long": COLORS["marker_close_long"],
            "marker_close_short": COLORS["marker_close_short"],
        }
    )
    return _sync_derived_theme_keys(theme)


def _sync_derived_theme_keys(theme: dict) -> dict:
    for alias, source in _DERIVED_THEME_KEYS.items():
        theme[alias] = theme[source]
    theme["chart_bg"] = theme["chart_bg"]
    theme["current_price_up"] = theme.get("current_price_up") if _is_hex_color(theme.get("current_price_up")) else theme["chart_up"]
    theme["current_price_down"] = (
        theme.get("current_price_down") if _is_hex_color(theme.get("current_price_down")) else theme["chart_down"]
    )
    return theme


def normalize_theme_settings(theme: dict | None) -> dict:
    incoming = dict(theme or {})
    normalized = _base_theme_tokens()

    schema = incoming.get("theme_schema_version")
    if schema == THEME_SCHEMA_VERSION:
        for key, value in incoming.items():
            if key in _THEME_COLOR_KEYS:
                if _is_hex_color(value):
                    normalized[key] = str(value).strip().upper()
            elif key == "grid_alpha":
                normalized[key] = _clamp_int(value, normalized[key], 12, 20)
            elif key == "crosshair_alpha":
                normalized[key] = _clamp_int(value, normalized[key], 80, 110)
            elif key == "name":
                normalized[key] = str(value)
    elif schema == 2:
        if incoming.get("name"):
            normalized["name"] = str(incoming["name"])
        for key, token_key in _LEGACY_TO_TOKEN_KEYS.items():
            value = incoming.get(key)
            if _is_hex_color(value):
                normalized[token_key] = str(value).strip().upper()
        for key in ("current_price_label_text", "premium_buy", "premium_sell", "premium_avg", "marker_close_long", "marker_close_short"):
            value = incoming.get(key)
            if _is_hex_color(value):
                normalized[key] = str(value).strip().upper()
        normalized["grid_alpha"] = _clamp_int(incoming.get("grid_alpha"), normalized["grid_alpha"], 12, 20)
        normalized["crosshair_alpha"] = _clamp_int(incoming.get("crosshair_alpha"), normalized["crosshair_alpha"], 80, 110)
    elif incoming.get("name"):
        normalized["name"] = str(incoming["name"])

    normalized["theme_schema_version"] = THEME_SCHEMA_VERSION
    normalized["grid_alpha"] = _clamp_int(normalized.get("grid_alpha"), 14, 12, 20)
    normalized["crosshair_alpha"] = _clamp_int(
        normalized.get("crosshair_alpha"), 95, 80, 110
    )
    for key in _THEME_COLOR_KEYS:
        if not _is_hex_color(normalized.get(key)):
            normalized[key] = COLORS.get(key, _base_theme_tokens().get(key, COLORS["text_primary"]))
    return _sync_derived_theme_keys(normalized)


def theme_value(theme: dict | None, key: str) -> str:
    merged = normalize_theme_settings(theme)
    return str(merged.get(key, COLORS.get(key, "")))


def build_app_qss(theme: dict | None = None) -> str:
    t = normalize_theme_settings(theme)
    okx_neutral_buttons = str(t.get("name")) == str(OKX_DARK_THEME["name"])
    default_button_bg = t["btn_bg"] if okx_neutral_buttons else t["bg_card"]
    default_button_text = t["btn_text"] if okx_neutral_buttons else t["text"]
    default_button_border = t["btn_border"] if okx_neutral_buttons else t["border_default"]
    default_button_hover = t["btn_hover"] if okx_neutral_buttons else t["bg_hover"]
    default_button_hover_border = t["btn_border"] if okx_neutral_buttons else t["border_strong"]
    default_button_pressed = t["btn_pressed"] if okx_neutral_buttons else t["bg_pressed"]
    default_button_checked_bg = t["btn_bg"] if okx_neutral_buttons else t["selection"]
    default_button_checked_border = t["btn_border"] if okx_neutral_buttons else t["focus"]
    default_button_checked_text = t["btn_text"] if okx_neutral_buttons else t["text"]
    default_button_disabled_bg = t["btn_bg"] if okx_neutral_buttons else t["bg_tertiary"]
    default_button_disabled_text = t["btn_text"] if okx_neutral_buttons else t["text_disabled"]
    default_button_disabled_border = t["btn_border"] if okx_neutral_buttons else t["divider"]
    danger_ghost_bg = t["btn_bg"] if okx_neutral_buttons else "transparent"
    danger_ghost_text = t["btn_text"] if okx_neutral_buttons else t["danger_ghost_text"]
    danger_ghost_border = t["btn_border"] if okx_neutral_buttons else t["danger_ghost_border"]
    danger_ghost_hover_bg = t["btn_hover"] if okx_neutral_buttons else t["danger_ghost_hover_bg"]
    danger_ghost_hover_text = t["btn_text"] if okx_neutral_buttons else t["danger_ghost_hover_text"]
    danger_ghost_hover_border = t["btn_border"] if okx_neutral_buttons else t["danger_ghost_hover_border"]
    return dedent(
        f"""
        QMainWindow,
        QWidget#appRoot {{
            background-color: {t['bg_primary']};
        }}

        QWidget {{
            color: {t['text_primary']};
            font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
            font-size: {FONT_SIZES['normal']}px;
        }}

        QScrollArea,
        QScrollArea::viewport,
        QScrollArea > QWidget,
        QScrollArea > QWidget > QWidget,
        QStackedWidget,
        QSplitter,
        QWidget[role="transparent"],
        QWidget[role="tabPage"] {{
            background-color: transparent;
        }}

        QFrame[role="header"] {{
            background-color: {t['bg_secondary']};
            border: 1px solid {t['divider']};
            border-radius: 4px;
        }}

        QFrame[role="sidebar"] {{
            background-color: {t['bg_secondary']};
            border: 1px solid {t['border_default']};
            border-radius: 6px;
        }}

        QFrame[role="rightPanel"] {{
            background-color: {t['bg_secondary']};
            border: 1px solid {t['border_default']};
            border-radius: 6px;
        }}

        QFrame[role="logDrawer"] {{
            background-color: {t['bg_secondary']};
            border: 1px solid {t['border_default']};
            border-radius: 6px;
        }}

        QFrame[role="sectionCard"] {{
            background-color: {t['bg_card']};
            border: 1px solid {t['border_default']};
            border-radius: 6px;
        }}

        QFrame[role="softPanel"] {{
            background-color: transparent;
            border: none;
            border-radius: 6px;
        }}

        QFrame[role="sideSeparator"] {{
            background-color: {t['divider']};
            min-height: 1px;
            max-height: 1px;
            border: none;
        }}

        QFrame[role="chartCard"] {{
            background-color: {t['bg_primary']};
            border: 1px solid {t['divider']};
            border-radius: 6px;
        }}

        QFrame[role="metricBlock"] {{
            background-color: {t['bg_card']};
            border: 1px solid {t['border_default']};
            border-radius: 6px;
        }}

        QFrame[role="statusBlock"] {{
            background-color: {t['bg_card']};
            border: 1px solid {t['border_default']};
            border-radius: 6px;
        }}

        QFrame[role="chartToolbar"] {{
            background-color: {t['bg_secondary']};
            border: 1px solid {t['divider']};
            border-radius: 5px;
        }}

        QFrame[role="recentEventItem"] {{
            background-color: {t['bg_tertiary']};
            border: 1px solid {t['divider']};
            border-radius: 5px;
        }}

        QFrame[role="emptyState"] {{
            background-color: {t['bg_secondary']};
            border: 1px dashed {t['border_default']};
            border-radius: 6px;
        }}

        QLabel {{
            background: transparent;
        }}

        QLabel[role="appTitle"] {{
            color: {t['text']};
            font-size: {FONT_SIZES['large']}px;
            font-weight: 700;
        }}

        QLabel[role="headerMark"] {{
            color: {t['brand']};
            font-size: {FONT_SIZES['small']}px;
            font-weight: 800;
        }}

        QLabel[role="headerValue"] {{
            color: {t['text']};
            font-size: {FONT_SIZES['medium']}px;
            font-weight: 650;
        }}

        QLabel[role="headerMain"] {{
            color: {t['text']};
            font-size: {FONT_SIZES['medium']}px;
            font-weight: 600;
        }}

        QLabel[role="headerMuted"] {{
            color: {t['text_secondary']};
            font-size: {FONT_SIZES['normal']}px;
        }}

        QLabel[role="headerSeparator"] {{
            color: {t['border']};
            font-size: {FONT_SIZES['medium']}px;
        }}

        QLabel[role="sectionTitle"] {{
            color: {t['text_secondary']};
            font-size: {FONT_SIZES['medium']}px;
            font-weight: 700;
        }}

        QLabel[role="toolbarTitle"] {{
            color: {t['text_secondary']};
            font-size: {FONT_SIZES['small']}px;
            font-weight: 750;
            padding: 0 6px;
        }}

        QLabel[role="sideTitle"] {{
            color: {t['text_secondary']};
            font-size: {FONT_SIZES['small']}px;
            font-weight: 750;
            letter-spacing: 0;
        }}

        QLabel[role="emptyTitle"] {{
            color: {t['text_secondary']};
            font-size: {FONT_SIZES['medium']}px;
            font-weight: 700;
        }}

        QLabel[role="emptyText"] {{
            color: {t['text_muted']};
            font-size: {FONT_SIZES['small']}px;
        }}

        QLabel[role="muted"],
        QLabel[role="tiny"] {{
            color: {t['text_muted']};
        }}

        QLabel[role="tiny"] {{
            font-size: {FONT_SIZES['small']}px;
        }}

        QLabel[role="metric"],
        QLabel[role="statusValue"] {{
            color: {t['text']};
            font-size: {FONT_SIZES['medium']}px;
            font-weight: 650;
        }}

        QLabel[role="valuePositive"] {{
            color: {t['green']};
            font-weight: 700;
        }}

        QLabel[role="valueNegative"] {{
            color: {t['red']};
            font-weight: 700;
        }}

        QLabel[role="valueAccent"] {{
            color: {t['text']};
            font-weight: 700;
        }}

        QLabel[role="pill"],
        QLabel[role="pillMuted"],
        QLabel[role="pillLive"],
        QLabel[role="pillWarning"] {{
            border-radius: 8px;
            padding: 2px 7px;
            background-color: {t['bg_hover']};
            border: 1px solid {t['border_default']};
            color: {t['text_secondary']};
            font-size: {FONT_SIZES['small']}px;
        }}

        QLabel[role="pillLive"] {{
            background-color: {t['selection']};
            border-color: {t['focus']};
            color: {t['text']};
        }}

        QLabel[role="pillWarning"] {{
            background-color: {t['warning_soft']};
            border-color: {t['warning']};
            color: {t['warning']};
        }}

        QGroupBox {{
            background-color: transparent;
            border: none;
            border-top: 1px solid {t['border_soft']};
            border-radius: 0;
            margin-top: 12px;
            padding: 6px 0 0 0;
            color: {t['text']};
            font-weight: 650;
        }}

        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 0;
            top: 0;
            padding: 0 6px 0 0;
            color: {t['text_secondary']};
            background-color: transparent;
            font-size: {FONT_SIZES['small']}px;
        }}

        QGroupBox[role="sideSection"] {{
            background-color: {t['bg_tertiary']};
            border: 1px solid {t['border_default']};
            border-radius: 6px;
            margin-top: 12px;
            padding: 6px 6px 8px 6px;
            color: {t['text_primary']};
            font-weight: 650;
        }}

        QGroupBox[role="sideSection"]::title {{
            subcontrol-origin: margin;
            left: 8px;
            top: 0;
            padding: 0 5px;
            color: {t['text_secondary']};
            background-color: {t['bg_tertiary']};
            font-size: {FONT_SIZES['small']}px;
        }}

        QPushButton {{
            background-color: {default_button_bg};
            color: {default_button_text};
            border: 1px solid {default_button_border};
            border-radius: 5px;
            padding: 4px 8px;
            min-height: 20px;
            font-weight: 600;
        }}

        QPushButton:hover {{
            background-color: {default_button_hover};
            border-color: {default_button_hover_border};
        }}

        QPushButton:pressed {{
            background-color: {default_button_pressed};
        }}

        QPushButton:checked {{
            background-color: {default_button_checked_bg};
            border-color: {default_button_checked_border};
            color: {default_button_checked_text};
        }}

        QPushButton:disabled {{
            color: {default_button_disabled_text};
            background-color: {default_button_disabled_bg};
            border-color: {default_button_disabled_border};
        }}

        QPushButton[role="primaryButton"] {{
            background-color: {t['btn_bg']};
            color: {t['btn_text']};
            border: 1px solid {t['btn_border']};
            border-radius: 14px;
            padding: 5px 14px;
        }}

        QPushButton[role="primaryButton"]:hover {{
            background-color: {t['btn_hover']};
            border-color: {t['btn_border']};
        }}

        QPushButton[role="primaryButton"]:pressed {{
            background-color: {t['btn_pressed']};
        }}

        QPushButton[role="secondaryButton"] {{
            background-color: {t['btn_bg']};
            color: {t['btn_text']};
            border: 1px solid {t['btn_border']};
            border-radius: 14px;
            padding: 5px 14px;
        }}

        QPushButton[role="secondaryButton"]:hover {{
            background-color: {t['btn_hover']};
            color: {t['btn_text']};
            border-color: {t['btn_border']};
        }}

        QPushButton[role="secondaryButton"]:pressed {{
            background-color: {t['btn_pressed']};
        }}

        QPushButton[role="successButton"] {{
            background-color: {t['success_soft']};
            color: {t['success_text']};
            border: 1px solid {t['success']};
            border-radius: 14px;
            padding: 5px 14px;
        }}

        QPushButton[role="successButton"]:hover {{
            background-color: {t['success_hover']};
        }}

        QPushButton[role="successButton"]:pressed {{
            background-color: {t['success_pressed']};
        }}

        QPushButton[role="dangerButton"] {{
            background-color: {t['danger_soft']};
            color: {t['danger_text']};
            border: 1px solid {t['danger']};
            border-radius: 14px;
            padding: 5px 14px;
        }}

        QPushButton[role="dangerButton"]:hover {{
            background-color: {t['danger_hover']};
        }}

        QPushButton[role="dangerButton"]:pressed {{
            background-color: {t['danger_pressed']};
        }}

        QPushButton[role="successButton"]:disabled {{
            background-color: {t['success_soft']};
            color: {t['success_text']};
            border-color: {t['success']};
        }}

        QPushButton[role="dangerButton"]:disabled {{
            background-color: {t['danger_soft']};
            color: {t['danger_text']};
            border-color: {t['danger']};
        }}

        QPushButton[role="dangerGhostButton"] {{
            background-color: {danger_ghost_bg};
            color: {danger_ghost_text};
            border: 1px solid {danger_ghost_border};
            border-radius: 4px;
            padding: 4px 8px;
            min-height: 18px;
            font-size: {FONT_SIZES['small']}px;
        }}

        QPushButton[role="dangerGhostButton"]:hover {{
            background-color: {danger_ghost_hover_bg};
            color: {danger_ghost_hover_text};
            border-color: {danger_ghost_hover_border};
        }}

        QPushButton[role="toolTab"],
        QPushButton[role="intervalChip"],
        QPushButton[role="iconTool"],
        QPushButton[role="compactButton"] {{
            padding: 3px 8px;
            min-height: 18px;
            border-radius: 4px;
            font-size: {FONT_SIZES['small']}px;
            background-color: transparent;
        }}

        QPushButton[role="toolTab"]:checked {{
            background-color: {t['selection']};
            border-color: {t['focus']};
            color: {t['text']};
        }}

        QPushButton[role="intervalChip"]:checked {{
            background-color: {t['brand_soft']};
            border-color: {t['brand']};
            color: {t['brand_hover']};
        }}

        QPushButton[role="dangerGhost"] {{
            padding: 4px 8px;
            min-height: 18px;
            color: {t['danger_ghost_text']};
            background-color: transparent;
            border: 1px solid {t['danger_ghost_border']};
            border-radius: 4px;
            font-size: {FONT_SIZES['small']}px;
        }}

        QToolButton[role="compactButton"] {{
            padding: 3px 8px;
            min-height: 18px;
            border-radius: 4px;
            font-size: {FONT_SIZES['small']}px;
            color: {t['text_tertiary']};
            background-color: transparent;
            border: 1px solid {t['divider']};
        }}

        QToolButton[role="compactButton"]:checked {{
            color: {t['text']};
            border-color: {t['focus']};
            background-color: {t['selection']};
        }}

        QToolButton[role="timeframeChip"] {{
            padding: 3px 9px;
            min-height: 20px;
            border-radius: 4px;
            font-size: {FONT_SIZES['small']}px;
            color: {t['text_secondary']};
            background-color: transparent;
            border: 1px solid {t['border_default']};
        }}

        QToolButton[role="timeframeChip"]:checked {{
            color: {t['accent_text']};
            border-color: {t['accent']};
            background-color: {t['accent_soft']};
        }}

        QToolButton[role="timeframeChip"]:hover {{
            color: {t['text']};
            border-color: {t['border_strong']};
            background-color: {t['bg_hover']};
        }}

        QLineEdit,
        QComboBox,
        QDateEdit,
        QDoubleSpinBox,
        QSpinBox {{
            background-color: {t['input_bg']};
            color: {t['text']};
            border: 1px solid {t['border_default']};
            border-radius: 5px;
            padding: 4px 7px;
            min-height: 22px;
        }}

        QLineEdit:focus,
        QComboBox:focus,
        QDateEdit:focus,
        QDoubleSpinBox:focus,
        QSpinBox:focus {{
            border-color: {t['focus']};
        }}

        QComboBox[role="symbolSelector"] {{
            background-color: {t['input_bg']};
            color: {t['text']};
            border: 1px solid {t['border']};
            border-radius: 5px;
            padding: 5px 8px;
            selection-background-color: {t['selection']};
        }}

        QComboBox[role="symbolSelector"]:hover {{
            background-color: {t['bg_hover']};
            border-color: {t['border_strong']};
        }}

        QComboBox[role="symbolSelector"]::drop-down {{
            border: none;
            width: 18px;
            background-color: transparent;
        }}

        QComboBox QAbstractItemView {{
            background-color: {t['input_bg']};
            color: {t['text']};
            border: 1px solid {t['border_default']};
            selection-background-color: {t['selection']};
            selection-color: {t['text']};
        }}

        QComboBox::drop-down,
        QDateEdit::drop-down,
        QDoubleSpinBox::up-button,
        QDoubleSpinBox::down-button,
        QSpinBox::up-button,
        QSpinBox::down-button {{
            border: none;
            width: 18px;
        }}

        QCheckBox {{
            spacing: 6px;
            color: {t['text_secondary']};
            background-color: transparent;
        }}

        QCheckBox::indicator {{
            width: 14px;
            height: 14px;
            border-radius: 4px;
            border: 1px solid {t['border_default']};
            background-color: {t['input_bg']};
        }}

        QCheckBox::indicator:checked {{
            background-color: {t['selection']};
            border-color: {t['focus']};
        }}

        QCheckBox[role="tagChip"] {{
            background-color: {t['bg_tertiary']};
            color: {t['text_secondary']};
            border: 1px solid {t['border_default']};
            border-radius: 10px;
            padding: 4px 8px;
            spacing: 0;
        }}

        QCheckBox[role="tagChip"]:hover {{
            background-color: {t['bg_hover']};
            border-color: {t['border_strong']};
        }}

        QCheckBox[role="tagChip"]:checked {{
            background-color: {t['accent_soft']};
            color: {t['accent_text']};
            border-color: {t['accent']};
        }}

        QCheckBox[role="tagChip"]::indicator {{
            width: 0;
            height: 0;
            border: none;
            background: transparent;
        }}

        QPlainTextEdit {{
            background-color: {t['input_bg']};
            color: {t['text']};
            border: 1px solid {t['border_default']};
            border-radius: 6px;
            padding: 7px;
            selection-background-color: {t['selection']};
            selection-color: {t['text']};
        }}

        QPlainTextEdit[role="logText"] {{
            font-family: Consolas, "Cascadia Mono", monospace;
            font-size: {FONT_SIZES['small']}px;
        }}

        QTabWidget::pane {{
            background-color: {t['panel_bg']};
            border: 1px solid {t['border_default']};
            border-radius: 5px;
            top: -1px;
        }}

        QTabBar::tab {{
            background-color: transparent;
            color: {t['text_secondary']};
            border: none;
            border-bottom: 1px solid transparent;
            padding: 6px 11px;
            margin-right: 2px;
            min-height: 18px;
        }}

        QTabBar::tab:selected {{
            background-color: transparent;
            color: {t['text']};
            border-bottom: 2px solid {t['brand']};
        }}

        QTableWidget {{
            background-color: {t['input_bg']};
            alternate-background-color: {t['bg_secondary']};
            color: {t['text']};
            gridline-color: {t['divider']};
            border: 1px solid {t['border_default']};
            border-radius: 6px;
            selection-background-color: {t['selection']};
            selection-color: {t['text']};
        }}

        QTableWidget::item:selected,
        QTableView::item:selected {{
            background-color: {t['selection']};
            color: {t['text']};
        }}

        QTableWidget::item {{
            padding: 3px 6px;
            border: none;
        }}

        QTableWidget::item:hover {{
            background-color: {t['bg_hover']};
        }}

        QListWidget {{
            background-color: {t['input_bg']};
            color: {t['text']};
            border: 1px solid {t['border_default']};
            border-radius: 6px;
            padding: 4px;
            outline: none;
        }}

        QListWidget::item {{
            min-height: 24px;
            padding: 3px 8px;
            border-radius: 5px;
        }}

        QListWidget::item:hover {{
            background-color: {t['bg_hover']};
        }}

        QListWidget::item:selected {{
            background-color: {t['selection']};
            color: {t['text']};
        }}

        QHeaderView::section {{
            background-color: {t['bg_tertiary']};
            color: {t['text_secondary']};
            border: none;
            border-right: 1px solid {t['divider']};
            border-bottom: 1px solid {t['border_default']};
            padding: 5px 6px;
            font-weight: 600;
        }}

        QSlider::groove:horizontal {{
            height: 4px;
            border-radius: 2px;
            background: {t['border_default']};
        }}

        QSlider::sub-page:horizontal {{
            background: {t['focus']};
            border-radius: 2px;
        }}

        QSlider::add-page:horizontal {{
            background: {t['divider']};
            border-radius: 2px;
        }}

        QSlider::handle:horizontal {{
            background: {t['text_secondary']};
            border: 1px solid {t['border_strong']};
            width: 14px;
            margin: -5px 0;
            border-radius: 7px;
        }}

        QSplitter::handle {{
            background-color: {t['divider']};
        }}

        QSplitter::handle:horizontal {{
            width: 4px;
        }}

        QSplitter::handle:vertical {{
            height: 4px;
        }}

        QScrollBar:vertical,
        QScrollBar:horizontal {{
            background: {t['input_bg']};
            border: none;
            width: 10px;
            height: 10px;
        }}

        QScrollBar::handle:vertical,
        QScrollBar::handle:horizontal {{
            background: {t['border_default']};
            border-radius: 5px;
            min-height: 24px;
            min-width: 24px;
        }}

        QScrollBar::handle:hover {{
            background: {t['border_strong']};
        }}

        QScrollBar::add-line,
        QScrollBar::sub-line {{
            width: 0;
            height: 0;
        }}
        """
    ).strip()
def _button_qss(
    bg: str,
    border: str,
    hover: str,
    pressed: str,
    text: str = COLORS["text_primary"],
    radius: int = 6,
    hover_border: str | None = None,
    hover_text: str | None = None,
) -> str:
    hover_border = hover_border or border
    hover_text = hover_text or text
    return dedent(
        f"""
        QPushButton {{
            background-color: {bg};
            color: {text};
            border: 1px solid {border};
            border-radius: {radius}px;
            padding: 5px 10px;
            min-height: 22px;
            font-weight: 650;
        }}
        QPushButton:hover {{ background-color: {hover}; border-color: {hover_border}; color: {hover_text}; }}
        QPushButton:pressed {{ background-color: {pressed}; }}
        QPushButton:disabled {{
            color: {COLORS['text_disabled']};
            background-color: {COLORS['bg_tertiary']};
            border-color: {COLORS['divider']};
        }}
        """
    ).strip()


def style_primary_button() -> str:
    return _button_qss(
        COLORS["bg_tertiary"],
        COLORS["border_strong"],
        COLORS["bg_hover"],
        COLORS["bg_pressed"],
        COLORS["text_primary"],
        hover_border=COLORS["accent"],
    )


def style_danger_button() -> str:
    return _button_qss(
        COLORS["danger_soft"],
        COLORS["danger"],
        COLORS["danger_hover"],
        COLORS["danger_pressed"],
        COLORS["danger_text"],
    )


def style_success_button() -> str:
    return _button_qss(
        COLORS["success_soft"],
        COLORS["success"],
        COLORS["success_hover"],
        COLORS["success_pressed"],
        COLORS["success_text"],
    )


def style_secondary_button() -> str:
    return _button_qss(
        COLORS["bg_card"],
        COLORS["border_default"],
        COLORS["bg_hover"],
        COLORS["bg_pressed"],
        COLORS["text_secondary"],
        hover_text=COLORS["text_primary"],
    )


def style_danger_ghost_button() -> str:
    return _button_qss(
        "transparent",
        COLORS["danger_ghost_border"],
        COLORS["danger_ghost_hover_bg"],
        COLORS["danger_pressed"],
        COLORS["danger_ghost_text"],
        radius=4,
        hover_border=COLORS["danger_ghost_hover_border"],
        hover_text=COLORS["danger_ghost_hover_text"],
    )


def style_table() -> str:
    return dedent(
        f"""
        QTableWidget {{
            background-color: {COLORS['input_bg']};
            color: {COLORS['text_primary']};
            border: 1px solid {COLORS['border_default']};
            border-radius: 6px;
            gridline-color: {COLORS['divider']};
            selection-background-color: {COLORS['selection']};
        }}
        """
    ).strip()


def style_panel() -> str:
    return dedent(
        f"""
        QFrame {{
            background-color: {COLORS['panel_bg']};
            border: 1px solid {COLORS['border_default']};
            border-radius: 6px;
        }}
        """
    ).strip()


# Roles whose background must be painted by a LOCAL stylesheet on the button.
# A global (window-level) stylesheet reliably paints these buttons' border, text
# and radius, but NOT their background-color in deep widget trees on Fusion — the
# fill falls back to the palette Button colour. Setting the rule directly on the
# button forces full QSS rendering so the fill paints. (Confirmed empirically.)
LOCAL_STYLE_BUTTON_ROLES = (
    "primaryButton",
    "secondaryButton",
    "successButton",
    "dangerButton",
    "intervalChip",
    "compactButton",
    "dangerGhostButton",
    "timeframeChip",
)

# Non-trade roles that share the neutral "raised dark pill" look.
_NEUTRAL_PILL_ROLES = ("primaryButton", "secondaryButton", "dangerGhostButton")
_NEUTRAL_CHIP_ROLES = ("intervalChip", "compactButton", "timeframeChip")


def role_button_local_qss(role: str, theme: dict | None = None, *, widget: str = "QPushButton") -> str:
    """Return a LOCAL stylesheet (set directly on the control) for a role button.

    ``widget`` is the selector type (``QPushButton`` or ``QToolButton``).
    Returns "" for roles that do not need an explicit background fill.
    """
    t = normalize_theme_settings(theme)

    if role in _NEUTRAL_PILL_ROLES or role in _NEUTRAL_CHIP_ROLES:
        chip = role in _NEUTRAL_CHIP_ROLES
        radius = 10 if chip else 14
        padding = "3px 12px" if chip else "5px 14px"
        min_h = 18 if chip else 22
        min_w = 40 if chip else 0
        return dedent(
            f"""
            {widget} {{
                background-color: {t['btn_bg']};
                color: {t['btn_text']};
                border: 1px solid {t['btn_border']};
                border-radius: {radius}px;
                padding: {padding};
                min-height: {min_h}px;
                min-width: {min_w}px;
                font-weight: 600;
            }}
            {widget}:hover {{ background-color: {t['btn_hover']}; border-color: {t['btn_border']}; }}
            {widget}:pressed {{ background-color: {t['btn_pressed']}; }}
            {widget}:checked {{ background-color: {t['accent_soft']}; color: {t['accent_text']}; border-color: {t['accent']}; }}
            {widget}:disabled {{ color: {t['text_disabled']}; background-color: {t['bg_tertiary']}; border-color: {t['divider']}; }}
            """
        ).strip()
    if role == "successButton":
        return dedent(
            f"""
            {widget} {{
                background-color: {t['success_soft']};
                color: {t['success_text']};
                border: 1px solid {t['success']};
                border-radius: 14px;
                padding: 5px 14px;
                min-height: 22px;
                font-weight: 650;
            }}
            {widget}:hover {{ background-color: {t['success_hover']}; }}
            {widget}:pressed {{ background-color: {t['success_pressed']}; }}
            """
        ).strip()
    if role == "dangerButton":
        return dedent(
            f"""
            {widget} {{
                background-color: {t['danger_soft']};
                color: {t['danger_text']};
                border: 1px solid {t['danger']};
                border-radius: 14px;
                padding: 5px 14px;
                min-height: 22px;
                font-weight: 650;
            }}
            {widget}:hover {{ background-color: {t['danger_hover']}; }}
            {widget}:pressed {{ background-color: {t['danger_pressed']}; }}
            """
        ).strip()
    return ""


def themed_input_qss(kind: str, theme: dict | None = None) -> str:
    """Local stylesheet for themed input controls so they match the dark pill look.

    ``kind`` is one of "combo" (QComboBox), "date" (QDateEdit) or "tagcheck"
    (QCheckBox event tags rendered as toggle pills). Like role buttons, these
    need a LOCAL stylesheet to paint their fill reliably on Fusion.
    """
    t = normalize_theme_settings(theme)
    base = (
        f"background-color: {t['btn_bg']}; color: {t['btn_text']}; "
        f"border: 1px solid {t['btn_border']}; border-radius: 12px; "
        f"padding: 5px 12px; min-height: 20px;"
    )
    if kind == "combo":
        return dedent(
            f"""
            QComboBox {{ {base} }}
            QComboBox:hover {{ border-color: {t['accent']}; }}
            QComboBox::drop-down {{ border: none; width: 18px; }}
            QComboBox QAbstractItemView {{
                background-color: {t['bg_card']};
                color: {t['text_primary']};
                selection-background-color: {t['selection']};
                border: 1px solid {t['border_default']};
                outline: none;
            }}
            """
        ).strip()
    if kind == "date":
        return dedent(
            f"""
            QDateEdit {{ {base} }}
            QDateEdit:hover {{ border-color: {t['accent']}; }}
            QDateEdit::drop-down {{ border: none; width: 18px; }}
            """
        ).strip()
    if kind == "lineedit":
        return dedent(
            f"""
            QLineEdit {{ {base} }}
            QLineEdit:focus {{ border-color: {t['accent']}; }}
            """
        ).strip()
    if kind == "tagcheck":
        return dedent(
            f"""
            QCheckBox {{
                background-color: {t['btn_bg']};
                color: {t['btn_text']};
                border: 1px solid {t['btn_border']};
                border-radius: 10px;
                padding: 4px 10px;
                min-height: 16px;
            }}
            QCheckBox:hover {{ background-color: {t['btn_hover']}; border-color: {t['accent']}; }}
            QCheckBox:checked {{ background-color: {t['accent_soft']}; color: {t['accent_text']}; border-color: {t['accent']}; }}
            QCheckBox::indicator {{ width: 0px; height: 0px; margin: 0px; }}
            """
        ).strip()
    return ""
