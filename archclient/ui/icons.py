# -*- coding: utf-8 -*-
"""SVG icons (Lucide set, ISC license) drawn with QtSvg, recolored at runtime — no emoji font needed."""
from __future__ import annotations

import re

from PyQt6.QtCore import QByteArray, QRectF, Qt
from PyQt6.QtGui import QImage, QPainter, QPixmap

from ..bootstrap import resource_path

try:
    from PyQt6.QtSvg import QSvgRenderer
except Exception:  # pragma: no cover
    QSvgRenderer = None

_svg_text: dict = {}
_pix_cache: dict = {}
_MAX_CACHE = 400


def _load(name: str) -> str:
    if name not in _svg_text:
        try:
            _svg_text[name] = (resource_path(f"assets/icons/{name}.svg")).read_text(encoding="utf-8")
        except Exception:
            _svg_text[name] = ""
    return _svg_text[name]


def icon_pixmap(name: str, color: str = "#e6e8ed", size: int = 20, dpr: float = 2.0,
                stroke: float = 1.8) -> QPixmap:
    key = (name, color, size, round(dpr, 2), stroke)
    pm = _pix_cache.get(key)
    if pm is not None:
        return pm
    px = max(1, int(round(size * dpr)))
    img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    svg = _load(name)
    if svg and QSvgRenderer is not None:
        svg = svg.replace("currentColor", color)
        svg = re.sub(r'stroke-width="[\d.]+"', f'stroke-width="{stroke}"', svg, count=1)
        r = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        if r.isValid():
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            r.render(p, QRectF(0, 0, px, px))
            p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    if len(_pix_cache) > _MAX_CACHE:
        _pix_cache.clear()
    _pix_cache[key] = pm
    return pm


def paint_icon(p: QPainter, name: str, color: str, x: float, y: float, size: int,
               dpr: float | None = None, stroke: float = 1.8) -> None:
    """Draw the icon with its top-left corner at (x, y)."""
    pm = icon_pixmap(name, color, size, dpr or max(1.0, p.device().devicePixelRatioF()
                                                    if hasattr(p.device(), "devicePixelRatioF") else 1.0), stroke)
    p.drawPixmap(int(round(x)), int(round(y)), pm)
