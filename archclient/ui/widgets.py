# -*- coding: utf-8 -*-
"""Custom-painted widgets: frosted glass, buttons, sidebar, switch, segmented, toast... (QPainter, animated)."""
from __future__ import annotations

import math

from PyQt6.QtCore import (QEasingCurve, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation,
                          pyqtProperty, pyqtSignal, QPropertyAnimation)
from PyQt6.QtGui import (QBrush, QColor, QFontMetrics, QLinearGradient, QPainter, QPainterPath,
                         QPen, QPixmap)
from PyQt6.QtWidgets import (QAbstractButton, QComboBox, QFrame, QGraphicsOpacityEffect,
                             QLabel, QScrollArea, QSizePolicy, QWidget, QListView)

from . import ctx as _ctx
from . import theme as T
from .icons import icon_pixmap


def _anim(parent, start, end, ms, cb, curve=QEasingCurve.Type.OutCubic) -> QVariantAnimation:
    a = QVariantAnimation(parent)
    a.setStartValue(start)
    a.setEndValue(end)
    a.setDuration(ms)
    a.setEasingCurve(curve)
    a.valueChanged.connect(cb)
    return a


class HoverAnim:
    """Smooth 0..1 hover progress for any widget."""

    def __init__(self, widget, ms=150):
        self.w = widget
        self.v = 0.0
        self.a = QVariantAnimation(widget)
        self.a.setDuration(ms)
        self.a.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.a.valueChanged.connect(self._set)

    def _set(self, v):
        self.v = float(v)
        self.w.update()

    def to(self, target: float):
        self.a.stop()
        self.a.setStartValue(self.v)
        self.a.setEndValue(float(target))
        self.a.start()


# ==========================================================================
# FROSTED GLASS
# ==========================================================================
class Glass(QFrame):
    """Glass panel: faint translucent white fill + thin bright border + a highlight streak on top."""

    def __init__(self, radius=16, parent=None, strength=1.0):
        super().__init__(parent)
        self.radius = radius
        self.strength = strength
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, self.radius, self.radius)
        p.fillPath(path, QColor(255, 255, 255, int(13 * self.strength)))
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0.0, QColor(255, 255, 255, int(12 * self.strength)))
        g.setColorAt(0.5, QColor(255, 255, 255, 0))
        p.fillPath(path, QBrush(g))
        p.setPen(QPen(QColor(255, 255, 255, int(24 * self.strength)), 1))
        p.drawPath(path)


class Label(QLabel):
    def __init__(self, text="", size=13, weight=400, color=T.TEXT, parent=None, wrap=False):
        super().__init__(text, parent)
        self.setStyleSheet(f"color:{color}; font-size:{size}px; font-weight:{weight}; background:transparent;")
        self.setWordWrap(wrap)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)


class ElidedLabel(QLabel):
    """Single line, elided to '…' based on width."""

    def __init__(self, text="", size=12, color=T.MUTED, parent=None):
        super().__init__(parent)
        self._full = text
        self._color = color
        self.setStyleSheet(f"font-size:{size}px; background:transparent;")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(10)

    def setText(self, text):  # noqa: N802
        self._full = text or ""
        self.setToolTip(self._full if len(self._full) > 60 else "")
        self.update()

    def sizeHint(self):  # noqa: N802
        return QSize(100, QFontMetrics(self.font()).height() + 2)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setPen(QColor(self._color))
        p.setFont(self.font())
        fm = QFontMetrics(self.font())
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   fm.elidedText(self._full, Qt.TextElideMode.ElideRight, self.width()))


# ==========================================================================
# BUTTONS
# ==========================================================================
class Btn(QAbstractButton):
    """Custom-painted button. kind: primary | ghost | subtle | danger."""

    def __init__(self, text="", icon=None, kind="ghost", size="md", parent=None):
        super().__init__(parent)
        self.kind = kind
        self.icon_name = icon
        self.size_name = size
        self._h = HoverAnim(self)
        self._press = False
        self._kbd = False
        self._busy = False
        self._spin = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self.setText(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.setFixedHeight({"sm": 30, "md": 36, "lg": 46}.get(size, 36))
        self.clicked.connect(lambda: _ctx.play("click"))

    def setBusy(self, busy: bool):  # noqa: N802
        self._busy = busy
        if busy:
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def setIconName(self, name):  # noqa: N802
        self.icon_name = name
        self.update()

    def setText(self, text):  # noqa: N802
        super().setText(text)
        self.updateGeometry()

    def _tick(self):
        self._spin = (self._spin + 14) % 360
        self.update()

    def _fs(self):
        return {"sm": 12, "md": 13, "lg": 15}.get(self.size_name, 13)

    def sizeHint(self):  # noqa: N802
        f = self.font()
        f.setPixelSize(self._fs())
        f.setWeight(f.Weight.DemiBold if self.kind == "primary" else f.Weight.Medium)
        w = QFontMetrics(f).horizontalAdvance(self.text()) if self.text() else 0
        icon_w = (self._isz() + (8 if self.text() else 0)) if (self.icon_name or self._busy) else 0
        pad = {"sm": 12, "md": 16, "lg": 24}.get(self.size_name, 16)
        return QSize(w + icon_w + pad * 2, self.height())

    def _isz(self):
        return {"sm": 14, "md": 16, "lg": 18}.get(self.size_name, 16)

    def enterEvent(self, e):  # noqa: N802
        self._h.to(1.0)
        if self.isEnabled():
            _ctx.play("hover")
        super().enterEvent(e)

    def leaveEvent(self, e):  # noqa: N802
        self._h.to(0.0)
        self._press = False
        super().leaveEvent(e)

    def mousePressEvent(self, e):  # noqa: N802
        self._press = True
        self.update()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):  # noqa: N802
        self._press = False
        self.update()
        super().mouseReleaseEvent(e)

    def focusInEvent(self, e):  # noqa: N802
        self._kbd = e.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason,
                                   Qt.FocusReason.ShortcutFocusReason)
        super().focusInEvent(e)

    def focusOutEvent(self, e):  # noqa: N802
        self._kbd = False
        super().focusOutEvent(e)

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.click()
        else:
            super().keyPressEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self._h.v
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = 10 if self.size_name != "lg" else 13
        enabled = self.isEnabled()
        press = 0.12 if self._press else 0.0

        if self.kind == "primary":
            base, hi = QColor(T.ACCENT), QColor(T.ACCENT_HI)
            col = QColor(int(base.red() + (hi.red() - base.red()) * h),
                         int(base.green() + (hi.green() - base.green()) * h),
                         int(base.blue() + (hi.blue() - base.blue()) * h))
            if press:
                col = col.darker(112)
            if not enabled:
                col = QColor(T.ACCENT)
                col.setAlphaF(0.35)
            path = QPainterPath()
            path.addRoundedRect(r, radius, radius)
            p.fillPath(path, col)
            fg = QColor("#08121a") if enabled else QColor(255, 255, 255, 110)
        elif self.kind == "danger":
            a = 0.10 + 0.12 * h + press
            path = QPainterPath()
            path.addRoundedRect(r, radius, radius)
            p.fillPath(path, T.qc(T.ERR, a))
            p.setPen(QPen(T.qc(T.ERR, 0.35 + 0.25 * h), 1))
            p.drawPath(path)
            fg = QColor(T.ERR)
        elif self.kind == "subtle":
            path = QPainterPath()
            path.addRoundedRect(r, radius, radius)
            p.fillPath(path, QColor(255, 255, 255, int(255 * (0.0 + 0.07 * h + press * 0.5))))
            fg = QColor(T.TEXT) if enabled else QColor(T.FAINT)
            fg = QColor(int(140 + 90 * h), int(148 + 84 * h), int(163 + 70 * h)) if enabled else fg
        else:  # ghost
            path = QPainterPath()
            path.addRoundedRect(r, radius, radius)
            p.fillPath(path, QColor(255, 255, 255, int(255 * (0.04 + 0.06 * h + press * 0.5))))
            p.setPen(QPen(QColor(255, 255, 255, int(255 * (0.10 + 0.08 * h))), 1))
            p.drawPath(path)
            fg = QColor(T.TEXT) if enabled else QColor(T.FAINT)

        if self.hasFocus() and self._kbd:
            p.setPen(QPen(T.qc(T.ACCENT, 0.9), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(-1, -1, 1, 1), radius + 1, radius + 1)

        f = self.font()
        f.setPixelSize(self._fs())
        f.setWeight(f.Weight.DemiBold if self.kind == "primary" else f.Weight.Medium)
        p.setFont(f)
        fm = QFontMetrics(f)
        tw = fm.horizontalAdvance(self.text()) if self.text() else 0
        isz = self._isz()
        has_icon = bool(self.icon_name) or self._busy
        total = tw + ((isz + (8 if tw else 0)) if has_icon else 0)
        x = (self.width() - total) / 2.0
        cy = self.height() / 2.0
        if has_icon:
            if self._busy:
                p.setPen(QPen(fg, 2, cap=Qt.PenCapStyle.RoundCap))
                p.drawArc(QRectF(x + 1, cy - isz / 2 + 1, isz - 2, isz - 2), int(-self._spin * 16), 270 * 16)
            else:
                pm = icon_pixmap(self.icon_name, fg.name(), isz, self.devicePixelRatioF())
                p.drawPixmap(int(x), int(cy - isz / 2), pm)
            x += isz + (8 if tw else 0)
        if tw:
            p.setPen(fg)
            p.drawText(QRectF(x, 0, tw + 2, self.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       self.text())


class IconBtn(QAbstractButton):
    """Round icon button (window controls, small actions)."""

    def __init__(self, icon, tip="", size=32, danger=False, parent=None):
        super().__init__(parent)
        self.icon_name = icon
        self.danger = danger
        self._h = HoverAnim(self, 120)
        self.setFixedSize(size, size)
        self.setToolTip(tip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clicked.connect(lambda: _ctx.play("click"))

    def setIconName(self, n):  # noqa: N802
        self.icon_name = n
        self.update()

    def enterEvent(self, e):  # noqa: N802
        self._h.to(1)
        super().enterEvent(e)

    def leaveEvent(self, e):  # noqa: N802
        self._h.to(0)
        super().leaveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self._h.v
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self.danger:
            bg = T.qc(T.ERR, 0.0 + 0.85 * h)
        else:
            bg = QColor(255, 255, 255, int(24 * h))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, 9, 9)
        col = "#ffffff" if (self.danger and h > 0.5) else (T.TEXT if h > 0.01 else T.MUTED)
        sz = 16
        pm = icon_pixmap(self.icon_name, col, sz, self.devicePixelRatioF())
        p.drawPixmap(int((self.width() - sz) / 2), int((self.height() - sz) / 2), pm)


# ==========================================================================
# SWITCH / SEGMENTED / SELECT
# ==========================================================================
class Switch(QAbstractButton):
    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(40, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._t = 1.0 if checked else 0.0
        self._a = _anim(self, 0.0, 1.0, 160, self._set)
        self.toggled.connect(self._on_toggle)
        self._h = HoverAnim(self, 120)

    def _set(self, v):
        self._t = float(v)
        self.update()

    def _on_toggle(self, on):
        self._a.stop()
        self._a.setStartValue(self._t)
        self._a.setEndValue(1.0 if on else 0.0)
        self._a.start()
        _ctx.play("on" if on else "off")

    def setCheckedSilent(self, on):  # noqa: N802
        self.blockSignals(True)
        self.setChecked(on)
        self.blockSignals(False)
        self._t = 1.0 if on else 0.0
        self.update()

    def enterEvent(self, e):  # noqa: N802
        self._h.to(1)
        super().enterEvent(e)

    def leaveEvent(self, e):  # noqa: N802
        self._h.to(0)
        super().leaveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self._t
        off = QColor(255, 255, 255, int(30 + 14 * self._h.v))
        on = QColor(T.ACCENT)
        col = QColor(int(off.red() + (on.red() - off.red()) * t), int(off.green() + (on.green() - off.green()) * t),
                     int(off.blue() + (on.blue() - off.blue()) * t),
                     int(off.alpha() + (255 - off.alpha()) * t))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(QRectF(0, 1, self.width(), self.height() - 2), 10, 10)
        d = 16
        x = 3 + (self.width() - d - 6) * t
        p.setBrush(QColor("#ffffff") if t > 0.5 else QColor("#c4cad4"))
        p.drawEllipse(QRectF(x, (self.height() - d) / 2, d, d))
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(T.qc(T.ACCENT, 0.9), 1.5))
            p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 11, 11)

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.toggle()
        else:
            super().keyPressEvent(e)


class Segmented(QWidget):
    """Pill-shaped selector with a glowing thumb that slides between options."""
    changed = pyqtSignal(str)

    def __init__(self, options, current=None, parent=None):
        super().__init__(parent)
        opts = list(options)                # [(key, label)] or [(key, label, icon)]
        self._icons = {o[0]: o[2] for o in opts if len(o) > 2}
        self._opts = [(o[0], o[1]) for o in opts]
        self._cur = current if current is not None else (self._opts[0][0] if self._opts else None)
        self._hover = -1
        self._x = 0.0
        self._w = 0.0
        self._anim = _anim(self, 0.0, 1.0, 200, self._step)
        self._from = (0.0, 0.0)
        self._to = (0.0, 0.0)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(38)
        self._snap = True

    def _fm(self):
        f = self.font()
        f.setPixelSize(13)
        f.setWeight(f.Weight.Medium)
        return f, QFontMetrics(f)

    def _rects(self):
        _, fm = self._fm()
        x = 4.0
        out = []
        for k, lab in self._opts:
            w = fm.horizontalAdvance(lab) + 26 + (22 if k in self._icons else 0)
            out.append(QRectF(x, 4, w, self.height() - 8))
            x += w + 2
        return out

    def sizeHint(self):  # noqa: N802
        rs = self._rects()
        return QSize(int(rs[-1].right() + 4) if rs else 40, 38)

    def minimumSizeHint(self):  # noqa: N802
        return self.sizeHint()

    def set_labels(self, labels: dict):
        self._opts = [(k, labels.get(k, lab)) for k, lab in self._opts]
        self.updateGeometry()
        self._snap = True
        self.update()

    def current(self):
        return self._cur

    def setCurrent(self, key, animate=True):  # noqa: N802
        if key == self._cur:
            return
        self._cur = key
        self._start_anim(animate)
        self.update()

    def _target(self):
        rs = self._rects()
        for (k, _l), r in zip(self._opts, rs):
            if k == self._cur:
                return r.x(), r.width()
        return 0.0, 0.0

    def _start_anim(self, animate=True):
        tx, tw = self._target()
        if not animate:
            self._x, self._w = tx, tw
            return
        self._from = (self._x, self._w)
        self._to = (tx, tw)
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def _step(self, v):
        v = float(v)
        self._x = self._from[0] + (self._to[0] - self._from[0]) * v
        self._w = self._from[1] + (self._to[1] - self._from[1]) * v
        self.update()

    def mouseMoveEvent(self, e):  # noqa: N802
        idx = -1
        for i, r in enumerate(self._rects()):
            if r.contains(QPointF(e.position())):
                idx = i
        if idx != self._hover:
            self._hover = idx
            if idx >= 0:
                _ctx.play("hover")
            self.update()

    def leaveEvent(self, _e):  # noqa: N802
        self._hover = -1
        self.update()

    def mousePressEvent(self, e):  # noqa: N802
        for (k, _l), r in zip(self._opts, self._rects()):
            if r.contains(QPointF(e.position())) and k != self._cur:
                self._cur = k
                self._start_anim(True)
                _ctx.play("nav")
                self.changed.emit(k)
                self.update()
                return

    def paintEvent(self, _e):
        if self._snap:
            self._x, self._w = self._target()
            self._snap = False
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = QPainterPath()
        bg.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        p.fillPath(bg, QColor(255, 255, 255, 12))
        p.setPen(QPen(QColor(255, 255, 255, 22), 1))
        p.drawPath(bg)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(T.qc(T.ACCENT, 0.20))
        pill = QRectF(self._x, 4, self._w, self.height() - 8)
        p.drawRoundedRect(pill, 9, 9)
        p.setPen(QPen(T.qc(T.ACCENT, 0.45), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(pill.adjusted(0.5, 0.5, -0.5, -0.5), 9, 9)
        f, _fm = self._fm()
        p.setFont(f)
        for i, ((k, lab), r) in enumerate(zip(self._opts, self._rects())):
            sel = k == self._cur
            col = QColor(T.TEXT) if sel else (QColor(T.TEXT) if i == self._hover else QColor(T.MUTED))
            p.setPen(col)
            ic = self._icons.get(k)
            if ic:
                dpr = self.devicePixelRatioF()
                pm = icon_pixmap(ic, col.name(), 16, dpr)
                tw = QFontMetrics(f).horizontalAdvance(lab)
                x0 = r.center().x() - (16 + 6 + tw) / 2
                p.drawPixmap(int(x0), int(r.center().y() - 8), pm)
                p.drawText(QRectF(x0 + 22, r.y(), tw + 4, r.height()),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, lab)
            else:
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, lab)


class Select(QComboBox):
    """Combobox: glass background + custom-painted chevron."""

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QListView()
        self.setView(v)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setMaxVisibleItems(10)
        pop = self.view().window()
        try:
            pop.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint |
                               Qt.WindowType.NoDropShadowWindowHint)
            pop.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        except Exception:
            pass

    def enterEvent(self, e):  # noqa: N802
        _ctx.play("hover")
        super().enterEvent(e)

    def showPopup(self):  # noqa: N802
        _ctx.play("click")
        super().showPopup()

    def paintEvent(self, e):  # noqa: N802
        super().paintEvent(e)
        p = QPainter(self)
        pm = icon_pixmap("chevron-down", T.MUTED, 14, self.devicePixelRatioF())
        p.drawPixmap(self.width() - 26, int((self.height() - 14) / 2), pm)


# ==========================================================================
# SIDEBAR
# ==========================================================================
class SideButton(QAbstractButton):
    """Sidebar button: fixed icon on the left, label slides in when the sidebar expands."""
    H = 46

    def __init__(self, icon, label="", parent=None, rail_w=68):
        super().__init__(parent)
        self.icon_name = icon
        self._label = label
        self.rail_w = rail_w
        self.setCheckable(True)
        self.setFixedHeight(self.H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._h = HoverAnim(self, 160)
        self._sel = 1.0 if self.isChecked() else 0.0
        self._sa = _anim(self, 0.0, 1.0, 220, self._set_sel)
        self.expand = 0.0      # 0..1, driven by the Rail
        self.toggled.connect(self._on_toggled)
        self.setMouseTracking(True)

    def setLabel(self, text):  # noqa: N802
        self._label = text
        self.update()

    def set_expand(self, v):
        self.expand = v
        self.update()

    def _set_sel(self, v):
        self._sel = float(v)
        self.update()

    def _on_toggled(self, on):
        self._sa.stop()
        self._sa.setStartValue(self._sel)
        self._sa.setEndValue(1.0 if on else 0.0)
        self._sa.start()

    def enterEvent(self, e):  # noqa: N802
        self._h.to(1)
        _ctx.play("hover")
        super().enterEvent(e)

    def leaveEvent(self, e):  # noqa: N802
        self._h.to(0)
        super().leaveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h, s, ex = self._h.v, self._sel, self.expand
        w = self.width()
        pad = 10
        r = QRectF(pad, 3, w - pad * 2, self.height() - 6)
        # background: slight glow on hover, accent tint when selected
        p.setPen(Qt.PenStyle.NoPen)
        if s > 0.01:
            p.setBrush(T.qc(T.ACCENT, 0.16 * s))
            p.drawRoundedRect(r, 12, 12)
        if h > 0.01:
            p.setBrush(QColor(255, 255, 255, int(16 * h * (1 - 0.6 * s))))
            p.drawRoundedRect(r, 12, 12)
        # indicator bar on the left
        if s > 0.01:
            p.setBrush(T.qc(T.ACCENT, s))
            bh = 20 * s
            p.drawRoundedRect(QRectF(2, (self.height() - bh) / 2, 3.5, bh), 2, 2)
        # icon: slight zoom + nudge on hover
        isz = 20
        scale = 1.0 + 0.12 * h
        col = QColor(int(140 + 91 * max(h, s)), int(148 + 84 * max(h, s)), int(163 + 70 * max(h, s)))
        if s > 0.5:
            col = QColor(T.ACCENT_HI)
        pm = icon_pixmap(self.icon_name, col.name(), isz, self.devicePixelRatioF())
        cx = self.rail_w / 2.0
        cy = self.height() / 2.0
        p.save()
        p.translate(cx + 1.5 * h, cy)
        p.scale(scale, scale)
        p.drawPixmap(int(-isz / 2), int(-isz / 2), pm)
        p.restore()
        # label
        if ex > 0.02 and self._label:
            f = self.font()
            f.setPixelSize(13)
            f.setWeight(f.Weight.DemiBold if s > 0.5 else f.Weight.Medium)
            p.setFont(f)
            tcol = QColor(T.TEXT) if (s > 0.5 or h > 0.1) else QColor(T.MUTED)
            tcol.setAlphaF(min(1.0, ex))
            p.setPen(tcol)
            x = self.rail_w - 4 + 8 * (1 - ex)
            p.drawText(QRectF(x, 0, max(0, w - x - 8), self.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._label)
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(T.qc(T.ACCENT, 0.8), 1.5))
            p.drawRoundedRect(r, 12, 12)


def blur_pixmap(pm: QPixmap, factor: float = 0.07) -> QPixmap:
    """Cheap smooth blur: downscale two steps then upscale with interpolation."""
    if pm.isNull():
        return pm
    w, h = pm.width(), pm.height()
    s1 = pm.scaled(max(2, int(w * 0.3)), max(2, int(h * 0.3)), Qt.AspectRatioMode.IgnoreAspectRatio,
                   Qt.TransformationMode.SmoothTransformation)
    s2 = s1.scaled(max(2, int(w * factor)), max(2, int(h * factor)), Qt.AspectRatioMode.IgnoreAspectRatio,
                   Qt.TransformationMode.SmoothTransformation)
    out = s2.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    out.setDevicePixelRatio(pm.devicePixelRatio())
    return out


class Rail(QFrame):
    """Floating sidebar: collapsed to 68px (icons only), expands on hover with a real frosted-glass
    background (a snapshot of the content underneath gets blurred)."""
    W0, W1 = 68, 214
    progress = pyqtSignal(float)

    def __init__(self, parent, grab_fn):
        super().__init__(parent)
        self._grab = grab_fn          # () -> QPixmap of the content behind the rail
        self._snap: QPixmap | None = None
        self._e = 0.0
        self.buttons: list = []
        self.setFixedWidth(self.W0)
        self.setMouseTracking(True)
        self._anim = _anim(self, 0.0, 1.0, 230, self._step, QEasingCurve.Type.OutCubic)
        self._leave_t = QTimer(self)
        self._leave_t.setSingleShot(True)
        self._leave_t.setInterval(140)
        self._leave_t.timeout.connect(lambda: self._go(0.0))
        self.radius = 18

    def set_buttons(self, buttons):
        self.buttons = buttons

    def _step(self, v):
        self._e = float(v)
        self.setFixedWidth(int(self.W0 + (self.W1 - self.W0) * self._e))
        for b in self.buttons:
            b.set_expand(max(0.0, (self._e - 0.35) / 0.65))
        self.progress.emit(self._e)
        self.update()

    def _go(self, target):
        if target > 0.5 and self._e < 0.5 and self._snap is None:
            try:
                self._snap = blur_pixmap(self._grab())
            except Exception:
                self._snap = None
        self._anim.stop()
        self._anim.setStartValue(self._e)
        self._anim.setEndValue(target)
        self._anim.setDuration(int(230 * abs(target - self._e) + 60))
        if target == 0.0:
            self._anim.finished.connect(self._drop_snap_once)
        self._anim.start()

    def _drop_snap_once(self):
        try:
            self._anim.finished.disconnect(self._drop_snap_once)
        except Exception:
            pass
        if self._e <= 0.001:
            self._snap = None

    def enterEvent(self, e):  # noqa: N802
        self._leave_t.stop()
        self._go(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):  # noqa: N802
        self._leave_t.start()
        super().leaveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        rad = getattr(self.window(), "radius", self.radius) if self.window() is not self else 0
        path = QPainterPath()
        path.moveTo(w, 0)
        path.lineTo(rad, 0)
        path.quadTo(0, 0, 0, rad)
        path.lineTo(0, h - rad)
        path.quadTo(0, h, rad, h)
        path.lineTo(w, h)
        path.closeSubpath()
        p.setClipPath(path)
        # base glass background
        p.fillPath(path, QColor(255, 255, 255, 8))
        if self._snap is not None and self._e > 0.01:
            p.setOpacity(min(1.0, self._e * 1.3))
            p.drawPixmap(0, 0, self._snap, 0, 0, int(w * self._snap.devicePixelRatio()),
                         int(h * self._snap.devicePixelRatio()))
            p.setOpacity(1.0)
            p.fillPath(path, QColor(12, 14, 18, int(150 * self._e)))
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, int(16 + 14 * self._e)), 1))
        p.drawLine(w - 1, 6, w - 1, h - 6)


# ==========================================================================
# PROGRESS / STATUS / TOAST
# ==========================================================================
class Progress(QWidget):
    """Slim bar: determinate (value/max) or indeterminate (bounces back and forth). max<0 -> hidden."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(4)
        self._val = 0.0
        self._max = -1
        self._shown = 0.0
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)
        self._a = _anim(self, 0.0, 0.0, 200, self._set_val)
        self._fade = _anim(self, 0.0, 1.0, 200, self._set_fade)
        self.hide()

    def _set_val(self, v):
        self._shown = float(v)
        self.update()

    def _set_fade(self, v):
        self.setWindowOpacity(1.0)
        self.update()

    def set_progress(self, value, maximum):
        if maximum < 0:
            self._max = -1
            self._timer.stop()
            self.hide()
            return
        self._max = maximum
        self._val = value
        if not self.isVisible():
            self.show()
        if maximum == 0:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
            frac = max(0.0, min(1.0, value / maximum))
            self._a.stop()
            self._a.setStartValue(self._shown)
            self._a.setEndValue(frac)
            self._a.start()
        self.update()

    def _tick(self):
        self._phase = (self._phase + 0.018) % 1.0
        self.update()

    def hideEvent(self, e):  # noqa: N802
        self._timer.stop()
        super().hideEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 22))
        p.drawRoundedRect(r, 2, 2)
        p.setBrush(QColor(T.ACCENT))
        if self._max == 0:
            seg = r.width() * 0.32
            x = (r.width() + seg) * self._phase - seg
            clip = QPainterPath()
            clip.addRoundedRect(r, 2, 2)
            p.setClipPath(clip)
            p.drawRoundedRect(QRectF(x, 0, seg, r.height()), 2, 2)
        else:
            p.drawRoundedRect(QRectF(0, 0, r.width() * self._shown, r.height()), 2, 2)


class StatusPill(QWidget):
    """Colored dot + text (pulses while busy)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""
        self._kind = "ready"
        self._pulse = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)
        self.setFixedHeight(30)

    def set_state(self, kind, text):
        self._kind, self._text = kind, text
        if kind in ("busy", "playing"):
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
            self._pulse = 0.0
        self.updateGeometry()
        self.update()

    def _tick(self):
        self._pulse = (self._pulse + 0.035) % 1.0
        self.update()

    def hideEvent(self, e):  # noqa: N802
        self._timer.stop()
        super().hideEvent(e)

    def showEvent(self, e):  # noqa: N802
        if self._kind in ("busy", "playing"):
            self._timer.start()
        super().showEvent(e)

    def _font(self):
        f = self.font()
        f.setPixelSize(12)
        f.setWeight(f.Weight.Medium)
        return f

    def sizeHint(self):  # noqa: N802
        return QSize(QFontMetrics(self._font()).horizontalAdvance(self._text) + 40, 30)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = QColor(T.kind_color(self._kind))
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 15, 15)
        p.fillPath(path, QColor(255, 255, 255, 12))
        p.setPen(QPen(QColor(255, 255, 255, 22), 1))
        p.drawPath(path)
        cx, cy = 16, self.height() / 2
        if self._pulse > 0:
            ring = QColor(col)
            ring.setAlphaF(0.5 * (1 - self._pulse))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(ring)
            rr = 3.5 + 6 * self._pulse
            p.drawEllipse(QPointF(cx, cy), rr, rr)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawEllipse(QPointF(cx, cy), 3.5, 3.5)
        p.setFont(self._font())
        p.setPen(QColor(T.TEXT))
        p.drawText(QRectF(28, 0, self.width() - 34, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._text)


class Toast(QWidget):
    """Small floating toast at the bottom center of the window; hides itself."""

    def __init__(self, parent):
        super().__init__(parent)
        self._text = ""
        self._kind = "info"
        self._fx = QGraphicsOpacityEffect(self)
        self._fx.setOpacity(0.0)
        self.setGraphicsEffect(self._fx)
        self._a = QPropertyAnimation(self._fx, b"opacity", self)
        self._a.setDuration(220)
        self._t = QTimer(self)
        self._t.setSingleShot(True)
        self._t.timeout.connect(self._hide)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

    def _font(self):
        f = self.font()
        f.setPixelSize(13)
        f.setWeight(f.Weight.Medium)
        return f

    def show_message(self, text, kind="info", ms=2600):
        self._text, self._kind = text, kind
        fm = QFontMetrics(self._font())
        self.setFixedSize(min(560, fm.horizontalAdvance(text) + 66), 42)
        self.reposition()
        self.show()
        self.raise_()
        self._a.stop()
        self._a.setStartValue(self._fx.opacity())
        self._a.setEndValue(1.0)
        self._a.start()
        self._t.start(ms)

    def reposition(self):
        par = self.parentWidget()
        if par:
            self.move((par.width() - self.width()) // 2, par.height() - self.height() - 34)

    def _hide(self):
        self._a.stop()
        self._a.setStartValue(self._fx.opacity())
        self._a.setEndValue(0.0)
        self._a.finished.connect(self._after_hide)
        self._a.start()

    def _after_hide(self):
        try:
            self._a.finished.disconnect(self._after_hide)
        except Exception:
            pass
        if self._fx.opacity() < 0.01:
            self.hide()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 14, 14)
        p.fillPath(path, QColor(24, 28, 35, 245))
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.drawPath(path)
        col = T.kind_color(self._kind)
        name = {"ok": "check", "warn": "circle-alert", "error": "circle-alert"}.get(self._kind, "check")
        if self._kind == "info":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(col))
            p.drawEllipse(QPointF(22, self.height() / 2), 4, 4)
        else:
            p.drawPixmap(14, int((self.height() - 16) / 2), icon_pixmap(name, col, 16, self.devicePixelRatioF()))
        p.setFont(self._font())
        p.setPen(QColor(T.TEXT))
        p.drawText(QRectF(40, 0, self.width() - 50, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._text)


# ==========================================================================
# HELPERS
# ==========================================================================
class Scroll(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.viewport().setAutoFillBackground(False)
        self.setStyleSheet("QScrollArea{background:transparent;border:none;}")

    def set_content(self, w: QWidget):
        w.setAutoFillBackground(False)
        w.setStyleSheet("background:transparent;")
        self.setWidget(w)


class Sep(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(1)

    def paintEvent(self, _e):
        QPainter(self).fillRect(self.rect(), QColor(255, 255, 255, 18))


def fade_in(widget: QWidget, ms=200):
    """Show a widget with a fade-in; removes the effect afterwards so rendering stays cheap."""
    fx = QGraphicsOpacityEffect(widget)
    fx.setOpacity(0.0)
    widget.setGraphicsEffect(fx)
    a = QPropertyAnimation(fx, b"opacity", widget)
    a.setDuration(ms)
    a.setStartValue(0.0)
    a.setEndValue(1.0)
    a.setEasingCurve(QEasingCurve.Type.OutCubic)

    def done():
        try:
            widget.setGraphicsEffect(None)
        except RuntimeError:
            pass
    a.finished.connect(done)
    a.start()
    return a
