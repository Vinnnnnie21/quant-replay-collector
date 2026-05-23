from __future__ import annotations

from textwrap import dedent


THEME_NAME = "交易暗色"

COLORS = {
    "window_bg": "#0b0f14",
    "panel_bg": "#111820",
    "panel_bg_alt": "#151d27",
    "chart_bg": "#080c10",
    "hover_bg": "#1b2532",
    "border": "#2a3340",
    "border_soft": "#242b36",
    "text_primary": "#e6edf3",
    "text_secondary": "#aeb8c4",
    "text_muted": "#6f7b89",
    "green": "#21b26f",
    "red": "#e05260",
    "orange": "#d99032",
    "blue": "#4f8cff",
    "purple": "#9b6bd3",
    "warning": "#e6b450",
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
    "window_bg": COLORS["window_bg"],
    "panel_bg": COLORS["panel_bg"],
    "panel_bg_alt": COLORS["panel_bg_alt"],
    "base_bg": COLORS["chart_bg"],
    "chart_bg": COLORS["chart_bg"],
    "text": COLORS["text_primary"],
    "text_primary": COLORS["text_primary"],
    "text_secondary": COLORS["text_secondary"],
    "text_muted": COLORS["text_muted"],
    "axis": COLORS["text_muted"],
    "grid": COLORS["border"],
    "grid_alpha": 22,
    "candle_up": COLORS["green"],
    "candle_down": COLORS["red"],
    "volume_up": COLORS["green"],
    "volume_down": COLORS["red"],
    "wick": "#8b98a7",
    "current_price_up": "#2fd182",
    "current_price_down": "#ef6b75",
    "current_price_label_text": "#06110c",
    "crosshair": COLORS["blue"],
    "crosshair_alpha": 130,
    "premium_buy": COLORS["blue"],
    "premium_sell": COLORS["orange"],
    "premium_avg": COLORS["purple"],
}

RESEARCH_SLATE_THEME = {
    **EXCHANGE_DARK_THEME,
    "name": "研究灰蓝",
    "window_bg": "#0c1117",
    "panel_bg": "#121a24",
    "panel_bg_alt": "#182231",
    "base_bg": "#090e13",
    "chart_bg": "#090e13",
    "grid": "#283242",
    "candle_up": "#26a982",
    "candle_down": "#e15d58",
    "current_price_up": "#2fc995",
    "current_price_down": "#ee746f",
    "premium_avg": "#8d75d8",
}

CONTRAST_DARK_THEME = {
    **EXCHANGE_DARK_THEME,
    "name": "高对比暗色",
    "window_bg": "#070a0f",
    "panel_bg": "#0f1720",
    "panel_bg_alt": "#16212d",
    "base_bg": "#05080c",
    "chart_bg": "#05080c",
    "text": "#f2f6fa",
    "text_primary": "#f2f6fa",
    "axis": "#a7b2c0",
    "grid": "#303b49",
    "grid_alpha": 28,
    "candle_up": "#2dbd7f",
    "candle_down": "#f0626a",
}


def theme_value(theme: dict | None, key: str) -> str:
    merged = dict(EXCHANGE_DARK_THEME)
    merged.update(theme or {})
    return str(merged.get(key, COLORS.get(key, "")))


def build_app_qss(theme: dict | None = None) -> str:
    t = dict(EXCHANGE_DARK_THEME)
    t.update(theme or {})
    return dedent(
        f"""
        QWidget {{
            background-color: {t['window_bg']};
            color: {t['text']};
            font-size: {FONT_SIZES['normal']}px;
        }}

        QFrame[role="header"] {{
            background-color: {t.get('panel_bg_alt', COLORS['panel_bg_alt'])};
            border: 1px solid {COLORS['border_soft']};
            border-radius: 12px;
        }}

        QFrame[role="sidebar"],
        QFrame[role="chartCard"],
        QFrame[role="rightPanel"],
        QFrame[role="logDrawer"] {{
            background-color: {t['panel_bg']};
            border: 1px solid {COLORS['border_soft']};
            border-radius: 12px;
        }}

        QFrame[role="metricBlock"] {{
            background-color: {t.get('panel_bg_alt', COLORS['panel_bg_alt'])};
            border: 1px solid {COLORS['border_soft']};
            border-radius: 8px;
        }}

        QLabel[role="appTitle"] {{
            color: {t['text']};
            font-size: {FONT_SIZES['large']}px;
            font-weight: 700;
            background: transparent;
        }}

        QLabel[role="muted"] {{
            color: {COLORS['text_muted']};
            background: transparent;
        }}

        QLabel[role="metric"] {{
            color: {t['text']};
            font-size: {FONT_SIZES['medium']}px;
            font-weight: 600;
            background: transparent;
        }}

        QLabel[role="pill"],
        QLabel[role="pillMuted"],
        QLabel[role="pillLive"],
        QLabel[role="pillWarning"] {{
            border-radius: 10px;
            padding: 3px 8px;
            background-color: {COLORS['hover_bg']};
            border: 1px solid {COLORS['border']};
            color: {COLORS['text_secondary']};
        }}

        QLabel[role="pillLive"] {{
            background-color: rgba(33, 178, 111, 46);
            border-color: {COLORS['green']};
            color: {COLORS['green']};
        }}

        QLabel[role="pillWarning"] {{
            background-color: rgba(224, 82, 96, 41);
            border-color: {COLORS['red']};
            color: {COLORS['red']};
        }}

        QGroupBox {{
            background-color: {t.get('panel_bg_alt', COLORS['panel_bg_alt'])};
            border: 1px solid {COLORS['border_soft']};
            border-radius: 10px;
            margin-top: 18px;
            padding: 10px 8px 8px 8px;
            color: {t['text']};
            font-weight: 600;
        }}

        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 10px;
            top: 3px;
            padding: 0 4px;
            color: {COLORS['text_secondary']};
            background-color: transparent;
        }}

        QPushButton {{
            background-color: {COLORS['hover_bg']};
            color: {t['text']};
            border: 1px solid {COLORS['border']};
            border-radius: 8px;
            padding: 7px 10px;
            min-height: 24px;
        }}

        QPushButton:hover {{
            background-color: #223044;
            border-color: #344357;
        }}

        QPushButton:pressed {{
            background-color: #121a24;
        }}

        QPushButton:disabled {{
            color: {COLORS['text_muted']};
            background-color: #111722;
            border-color: {COLORS['border_soft']};
        }}

        QLineEdit,
        QComboBox,
        QDateEdit,
        QDoubleSpinBox,
        QSpinBox {{
            background-color: #0f151d;
            color: {t['text']};
            border: 1px solid {COLORS['border']};
            border-radius: 6px;
            padding: 5px 7px;
            min-height: 24px;
        }}

        QLineEdit:focus,
        QComboBox:focus,
        QDateEdit:focus,
        QDoubleSpinBox:focus,
        QSpinBox:focus {{
            border-color: {COLORS['blue']};
        }}

        QComboBox[role="symbolSelector"] {{
            background-color: #0f151d;
            color: {t['text']};
            border: 1px solid {COLORS['border']};
            border-radius: 6px;
            padding: 5px 8px;
            selection-background-color: #0f151d;
        }}

        QComboBox[role="symbolSelector"]:hover {{
            background-color: {COLORS['hover_bg']};
            border-color: {COLORS['blue']};
        }}

        QComboBox[role="symbolSelector"]::drop-down {{
            border: none;
            width: 18px;
            background-color: transparent;
        }}

        QComboBox[role="symbolSelector"] QAbstractItemView {{
            background-color: #0f151d;
            color: {t['text']};
            border: 1px solid {COLORS['border']};
            selection-background-color: {COLORS['hover_bg']};
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
            color: {COLORS['text_secondary']};
            background-color: transparent;
        }}

        QCheckBox::indicator {{
            width: 14px;
            height: 14px;
            border-radius: 4px;
            border: 1px solid {COLORS['border']};
            background-color: #0f151d;
        }}

        QCheckBox::indicator:checked {{
            background-color: {COLORS['blue']};
            border-color: {COLORS['blue']};
        }}

        QCheckBox[role="tagChip"] {{
            background-color: #101720;
            color: {COLORS['text_secondary']};
            border: 1px solid {COLORS['border_soft']};
            border-radius: 10px;
            padding: 4px 8px;
            spacing: 0;
        }}

        QCheckBox[role="tagChip"]:hover {{
            background-color: {COLORS['hover_bg']};
            border-color: {COLORS['border']};
        }}

        QCheckBox[role="tagChip"]:checked {{
            background-color: rgba(79, 140, 255, 51);
            color: {t['text']};
            border-color: {COLORS['blue']};
        }}

        QCheckBox[role="tagChip"]::indicator {{
            width: 0;
            height: 0;
            border: none;
            background: transparent;
        }}

        QPlainTextEdit {{
            background-color: #0f151d;
            color: {t['text']};
            border: 1px solid {COLORS['border_soft']};
            border-radius: 8px;
            padding: 7px;
            selection-background-color: rgba(79, 140, 255, 82);
        }}

        QTabWidget::pane {{
            background-color: {t['panel_bg']};
            border: 1px solid {COLORS['border_soft']};
            border-radius: 10px;
            top: -1px;
        }}

        QTabBar::tab {{
            background-color: #101720;
            color: {COLORS['text_secondary']};
            border: 1px solid {COLORS['border_soft']};
            border-bottom: none;
            padding: 7px 12px;
            margin-right: 2px;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
        }}

        QTabBar::tab:selected {{
            background-color: {t.get('panel_bg_alt', COLORS['panel_bg_alt'])};
            color: {t['text']};
            border-color: {COLORS['border']};
        }}

        QTableWidget {{
            background-color: #0f151d;
            alternate-background-color: #121a24;
            color: {t['text']};
            gridline-color: {COLORS['border_soft']};
            border: 1px solid {COLORS['border_soft']};
            border-radius: 8px;
            selection-background-color: rgba(79, 140, 255, 71);
            selection-color: {t['text']};
        }}

        QTableWidget::item {{
            padding: 3px 6px;
            border: none;
        }}

        QTableWidget::item:hover {{
            background-color: {COLORS['hover_bg']};
        }}

        QListWidget {{
            background-color: #0f151d;
            color: {t['text']};
            border: 1px solid {COLORS['border_soft']};
            border-radius: 8px;
            padding: 4px;
            outline: none;
        }}

        QListWidget::item {{
            min-height: 24px;
            padding: 3px 8px;
            border-radius: 6px;
        }}

        QListWidget::item:hover {{
            background-color: {COLORS['hover_bg']};
        }}

        QListWidget::item:selected {{
            background-color: rgba(79, 140, 255, 71);
            color: {t['text']};
        }}

        QHeaderView::section {{
            background-color: #0c1219;
            color: {COLORS['text_secondary']};
            border: none;
            border-right: 1px solid {COLORS['border_soft']};
            border-bottom: 1px solid {COLORS['border']};
            padding: 5px 6px;
            font-weight: 600;
        }}

        QSlider::groove:horizontal {{
            height: 4px;
            border-radius: 2px;
            background: {COLORS['border']};
        }}

        QSlider::handle:horizontal {{
            background: {COLORS['blue']};
            border: 1px solid {COLORS['blue']};
            width: 14px;
            margin: -5px 0;
            border-radius: 7px;
        }}

        QScrollBar:vertical,
        QScrollBar:horizontal {{
            background: #0f151d;
            border: none;
            width: 10px;
            height: 10px;
        }}

        QScrollBar::handle:vertical,
        QScrollBar::handle:horizontal {{
            background: {COLORS['border']};
            border-radius: 5px;
            min-height: 24px;
            min-width: 24px;
        }}

        QScrollBar::handle:hover {{
            background: #3a4656;
        }}
        """
    ).strip()


def _button_qss(bg: str, border: str, hover: str, pressed: str, text: str = COLORS["text_primary"], radius: int = 8) -> str:
    return dedent(
        f"""
        QPushButton {{
            background-color: {bg};
            color: {text};
            border: 1px solid {border};
            border-radius: {radius}px;
            padding: 8px 12px;
            min-height: 28px;
            font-weight: 600;
        }}
        QPushButton:hover {{ background-color: {hover}; }}
        QPushButton:pressed {{ background-color: {pressed}; }}
        QPushButton:disabled {{
            color: {COLORS['text_muted']};
            background-color: #111722;
            border-color: {COLORS['border_soft']};
        }}
        """
    ).strip()


def style_primary_button() -> str:
    return _button_qss("#17243a", COLORS["blue"], "#203553", "#101a2a")


def style_danger_button() -> str:
    return _button_qss("#2a171b", COLORS["red"], "#3a2025", "#1d1013", radius=10)


def style_success_button() -> str:
    return _button_qss("#13281f", COLORS["green"], "#1a382c", "#0d1d16", radius=10)


def style_secondary_button() -> str:
    return _button_qss("#1b2532", COLORS["border"], "#223044", "#121a24")


def style_table() -> str:
    return dedent(
        f"""
        QTableWidget {{
            background-color: #0f151d;
            color: {COLORS['text_primary']};
            border: 1px solid {COLORS['border_soft']};
            border-radius: 8px;
            gridline-color: {COLORS['border_soft']};
        }}
        """
    ).strip()


def style_panel() -> str:
    return dedent(
        f"""
        QFrame {{
            background-color: {COLORS['panel_bg']};
            border: 1px solid {COLORS['border_soft']};
            border-radius: 12px;
        }}
        """
    ).strip()
