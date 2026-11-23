# -*- coding: utf-8 -*-
"""Color palette + global stylesheet. Neutral dark tone, one soft green accent taken from the logo."""
from __future__ import annotations

from PyQt6.QtGui import QColor

# background
BG_TOP = "#14171d"
BG_BOTTOM = "#0d0f13"
# text
TEXT = "#e6e8ed"
MUTED = "#8c94a3"
FAINT = "#5c6472"
# accent + status
ACCENT = "#4da3d4"
ACCENT_HI = "#6ab6e2"
OK = "#5fbd8b"
WARN = "#d8a54b"
ERR = "#e27882"

FONT_STACK = ('"Inter", "Segoe UI Variable Text", "Segoe UI", "Noto Sans", "Cantarell", "Ubuntu", '
              '"DejaVu Sans", sans-serif')
MONO_STACK = '"JetBrains Mono", "Cascadia Mono", "Consolas", "Fira Code", "Noto Sans Mono", "DejaVu Sans Mono", monospace'


def qc(hex_or_color, alpha: float | None = None) -> QColor:
    c = QColor(hex_or_color)
    if alpha is not None:
        c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def kind_color(kind: str) -> str:
    return {"ok": OK, "success": OK, "ready": OK, "warn": WARN, "busy": WARN,
            "error": ERR, "err": ERR, "playing": ACCENT, "info": ACCENT,
            "idle": FAINT}.get(kind, MUTED)


def build_qss() -> str:
    return f"""
* {{ font-family: {FONT_STACK}; font-size: 13px; color: {TEXT}; outline: 0; }}
QToolTip {{ background: #1b1f27; color: {TEXT}; border: 1px solid rgba(255,255,255,0.10);
           border-radius: 8px; padding: 5px 9px; }}

QLineEdit {{ background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.09);
            border-radius: 10px; padding: 0 12px; min-height: 36px;
            selection-background-color: {ACCENT}; selection-color: #0b0d11; }}
QLineEdit:hover {{ border-color: rgba(255,255,255,0.16); }}
QLineEdit:focus {{ border-color: {ACCENT}; background: rgba(255,255,255,0.07); }}
QLineEdit:disabled {{ color: {FAINT}; }}

QComboBox {{ background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.09);
            border-radius: 10px; padding: 0 34px 0 12px; min-height: 36px;
            combobox-popup: 0; }}
QComboBox:hover {{ border-color: rgba(255,255,255,0.16); }}
QComboBox:focus, QComboBox:on {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 30px; }}
QComboBox::down-arrow {{ image: none; }}
QComboBox QAbstractItemView {{ background: #181b22; border: 1px solid rgba(255,255,255,0.10);
            border-radius: 10px; padding: 4px; selection-background-color: rgba(77,163,212,0.22);
            selection-color: {TEXT}; outline: 0; }}
QComboBox QAbstractItemView::item {{ min-height: 30px; padding: 0 10px; border-radius: 6px; }}

QPlainTextEdit {{ background: transparent; border: none; selection-background-color: {ACCENT};
                 selection-color: #0b0d11; font-family: {MONO_STACK}; font-size: 12px; }}

QSlider::groove:horizontal {{ height: 4px; background: rgba(255,255,255,0.10); border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: #f2f5f9; width: 14px; height: 14px; margin: -5px 0;
                             border-radius: 7px; }}
QSlider::handle:horizontal:hover {{ background: #ffffff; width: 16px; height: 16px; margin: -6px 0;
                                   border-radius: 8px; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: rgba(255,255,255,0.14); border-radius: 3px; min-height: 36px;
                              margin: 0 2px; }}
QScrollBar::handle:vertical:hover {{ background: rgba(255,255,255,0.26); }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: rgba(255,255,255,0.14); border-radius: 3px; min-width: 36px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; width: 0; }}

QListWidget {{ background: transparent; border: none; }}
QListWidget::item {{ background: transparent; }}
QMenu {{ background: #181b22; border: 1px solid rgba(255,255,255,0.10); border-radius: 10px; padding: 5px; }}
QMenu::item {{ padding: 7px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: rgba(77,163,212,0.22); }}
"""
