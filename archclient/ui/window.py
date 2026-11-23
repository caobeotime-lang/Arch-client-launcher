# -*- coding: utf-8 -*-
"""Cửa sổ chính: kính mờ bo góc, sidebar nổi, thanh trên, các trang, modal, toast."""
from __future__ import annotations

import math
import threading
from pathlib import Path

from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import (QBrush, QColor, QDesktopServices, QIcon, QKeySequence, QLinearGradient, QPainter,
                         QPainterPath, QPen, QPixmap, QRadialGradient, QShortcut)
from PyQt6.QtWidgets import (QButtonGroup, QHBoxLayout, QLabel, QLineEdit, QStackedWidget, QVBoxLayout, QWidget)

from .. import APP_NAME, WEBSITE_URL, core
from ..bootstrap import resource_path
from ..i18n import detect_language
from . import theme as T
from .pages import (ConsolePage, FilesPage, HomePage, ModsPage, OptimizePage, SettingsPage, hbox, open_url,
                    vbox)
from .widgets import (Btn, Glass, IconBtn, Label, Rail, SideButton, StatusPill, Toast, blur_pixmap, fade_in)

NAV = [("home", "house", "nav_home"), ("files", "folder-open", "nav_files"), ("mods", "puzzle", "nav_mods"),
       ("optimize", "zap", "nav_optimize"), ("console", "terminal", "nav_console")]
BOTTOM = [("settings", "settings", "nav_settings")]
SHADOW = 16
RADIUS = 18


# ==========================================================================
# THANH TRÊN
# ==========================================================================
class TopBar(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setFixedHeight(68)
        self._drag = None

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            h = self.win.windowHandle()
            if h is not None and h.startSystemMove():
                return
            self._drag = e.globalPosition().toPoint() - self.win.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):  # noqa: N802
        if self._drag is not None and e.buttons() & Qt.MouseButton.LeftButton and not self.win.isMaximized():
            self.win.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _e):  # noqa: N802
        self._drag = None

    def mouseDoubleClickEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self.win.toggle_max()


class Brand(QWidget):
    """Logo + tên, đặt đầu sidebar. Tên hiện dần khi sidebar mở."""

    def __init__(self, rail_w=68):
        super().__init__()
        self.rail_w = rail_w
        self.expand = 0.0
        self.pm = QPixmap(str(resource_path("img/logo.png")))
        self.setFixedHeight(64)

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        s = 34
        if not self.pm.isNull():
            p.drawPixmap(QRect(int((self.rail_w - s) / 2), int((self.height() - s) / 2) + 2, s, s), self.pm)
        if self.expand > 0.05:
            f = self.font()
            f.setPixelSize(15)
            f.setWeight(f.Weight.Bold)
            p.setFont(f)
            c = QColor(T.TEXT)
            c.setAlphaF(min(1.0, self.expand))
            p.setPen(c)
            x = self.rail_w - 2 + 8 * (1 - self.expand)
            p.drawText(QRect(int(x), 2, 140, self.height()), Qt.AlignmentFlag.AlignVCenter, APP_NAME)


# ==========================================================================
# MODAL (lớp phủ mờ trong cửa sổ)
# ==========================================================================
class Modal(QWidget):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self._snap: QPixmap | None = None
        self._card: QWidget | None = None
        self._on_cancel = None
        self.hide()

    def open(self, title, body=None, extra: QWidget | None = None, buttons=(), focus=None):
        """buttons: [(nhãn, kind, callback hoặc None, đóng_lại)]"""
        self.close_card(silent=True)
        m = self.win.m
        self.setGeometry(m, m, self.win.width() - 2 * m, self.win.height() - 2 * m)
        self._snap = blur_pixmap(self.win.grab_inner())
        card = Glass(18)
        card.setStyleSheet("background:transparent;")
        card.setParent(self)
        lay = vbox((26, 24, 26, 22), 10, card)
        lay.addWidget(Label(title, 17, 650))
        if body:
            lay.addWidget(Label(body, 13, 400, T.MUTED, wrap=True))
        if extra is not None:
            lay.addSpacing(4)
            lay.addWidget(extra)
        lay.addSpacing(10)
        row = hbox(spacing=10)
        row.addStretch(1)
        self._btns = []
        for label, kind, cb, close in buttons:
            b = Btn(label, None, kind)
            b.clicked.connect(lambda _=False, cb=cb, close=close: self._press(cb, close))
            row.addWidget(b)
            self._btns.append(b)
        lay.addLayout(row)
        card.setFixedWidth(min(460, self.width() - 40))
        card.adjustSize()
        card.move((self.width() - card.width()) // 2, (self.height() - card.height()) // 2 - 10)
        self._card = card
        cancel = [b for b in buttons if b[1] != "primary" and b[1] != "danger"]
        self._on_cancel = cancel[0][2] if cancel else None
        self.show()
        self.raise_()
        card.show()
        fade_in(self, 170)
        (focus or (self._btns[-1] if self._btns else self)).setFocus()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _press(self, cb, close):
        if close:
            self.close_card()
        if cb:
            cb()

    def close_card(self, silent=False):
        if self._card is not None:
            self._card.hide()
            self._card.deleteLater()
            self._card = None
        self._snap = None
        self.hide()

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() == Qt.Key.Key_Escape:
            self.close_card()
            if self._on_cancel:
                self._on_cancel()
        else:
            super().keyPressEvent(e)

    def mousePressEvent(self, e):  # noqa: N802
        if self._card is not None and not self._card.geometry().contains(e.position().toPoint()):
            self.close_card()

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        r = self.win.radius
        path.addRoundedRect(QRectF(self.rect()), r, r)
        p.setClipPath(path)
        if self._snap is not None:
            p.drawPixmap(0, 0, self._snap)
        p.fillPath(path, QColor(6, 8, 12, 150))


# ==========================================================================
# CỬA SỔ CHÍNH
# ==========================================================================
class MainWindow(QWidget):
    def __init__(self, ctx, translucent: bool):
        super().__init__()
        self.ctx = ctx
        ctx.window = self
        self.translucent = translucent
        self.m = SHADOW if translucent else 5
        self.radius = RADIUS
        self._t = 0.0
        self._glass = int(ctx.cfg.get("glass_opacity", 88)) / 100.0
        self._anim_on = bool(ctx.cfg.get("bg_anim", True))
        self._shadow: QPixmap | None = None
        self._shadow_key = None
        self._playing = False

        self.setWindowTitle(APP_NAME)
        icon = resource_path("img/icon.png")
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        if translucent:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setMinimumSize(900, 620)
        w, h = int(ctx.cfg.get("win_w", 1080)), int(ctx.cfg.get("win_h", 720))
        self.resize(max(900, w), max(620, h))

        # --- nội dung
        self.body = QWidget(self)
        self.body.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(self.m, self.m, self.m, self.m)
        outer.addWidget(self.body)
        bl = QHBoxLayout(self.body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        bl.addSpacing(Rail.W0)
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        bl.addLayout(right, 1)

        self.top = TopBar(self)
        tl = hbox((8, 0, 18, 0), 10, self.top)
        tcol = vbox(spacing=1)
        tcol.addStretch(1)
        self.title = Label("", 20, 700)
        self.subtitle = Label("", 12, 400, T.MUTED)
        tcol.addWidget(self.title)
        tcol.addWidget(self.subtitle)
        tcol.addStretch(1)
        tl.addSpacing(16)
        tl.addLayout(tcol)
        tl.addStretch(1)
        self.pill = StatusPill()
        self.btn_play = Btn("", "play", "primary", "md")
        tl.addWidget(self.pill)
        tl.addSpacing(4)
        tl.addWidget(self.btn_play)
        tl.addSpacing(10)
        self.b_min = IconBtn("minus", "")
        self.b_max = IconBtn("square", "")
        self.b_close = IconBtn("x", "", danger=True)
        for b in (self.b_min, self.b_max, self.b_close):
            tl.addWidget(b)
        right.addWidget(self.top)

        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)
        stack_wrap = self.stack
        stack_wrap.setContentsMargins(0, 0, 0, 0)

        self.home = HomePage(ctx)
        self.files = FilesPage(ctx)
        self.mods = ModsPage(ctx)
        self.optimize = OptimizePage(ctx)
        self.console = ConsolePage(ctx)
        self.settings = SettingsPage(ctx)
        self.pages = {p.key: p for p in (self.home, self.files, self.mods, self.optimize,
                                         self.console, self.settings)}
        for p in self.pages.values():
            holder = QWidget()
            hl = vbox((6, 4, 26, 24), 0, holder)
            hl.addWidget(p)
            p._holder = holder
            self.stack.addWidget(holder)

        # --- sidebar nổi (con trực tiếp của cửa sổ, nằm trên cùng)
        self.rail = Rail(self, self.grab_under_rail)
        rl = vbox((0, 6, 0, 12), 2, self.rail)
        self.brand = Brand()
        rl.addWidget(self.brand)
        rl.addSpacing(8)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.nav_btn = {}
        for key, icon_name, lk in NAV:
            b = SideButton(icon_name)
            self.nav_btn[key] = b
            self.group.addButton(b)
            rl.addWidget(b)
        rl.addStretch(1)
        for key, icon_name, lk in BOTTOM:
            b = SideButton(icon_name)
            self.nav_btn[key] = b
            self.group.addButton(b)
            rl.addWidget(b)
        self.web_btn = SideButton("globe")
        self.web_btn.setCheckable(False)
        rl.addWidget(self.web_btn)
        self.rail.set_buttons(list(self.nav_btn.values()) + [self.web_btn])
        self.rail.progress.connect(self._rail_progress)

        for key, b in self.nav_btn.items():
            b.clicked.connect(lambda _=False, k=key: self.go(k))
        self.web_btn.clicked.connect(lambda: open_url(WEBSITE_URL))
        self.home.request_files.connect(self._home_to_files)

        # --- lớp phủ
        self.toast_w = Toast(self)
        self.modal = Modal(self)
        self.modal.hide()

        # --- điều khiển cửa sổ + phím tắt
        self.b_min.clicked.connect(self.showMinimized)
        self.b_max.clicked.connect(self.toggle_max)
        self.b_close.clicked.connect(self.close)
        self.btn_play.clicked.connect(lambda: ctx.ctl.launch())
        self.home.play.clicked.connect(lambda: ctx.ctl.launch())
        for i, (key, _i, _l) in enumerate(NAV + BOTTOM):
            sc = QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self)
            sc.activated.connect(lambda k=key: self.go(k))
        QShortcut(QKeySequence("Ctrl+Q"), self).activated.connect(self.close)

        # --- bus
        bus = ctx.bus
        bus.log.connect(self.console.append)
        bus.status.connect(self._on_status)
        bus.java.connect(self._on_java)
        bus.progress.connect(self._on_progress)
        bus.refresh.connect(self.refresh_all)
        bus.toast.connect(self.toast)
        bus.sound.connect(ctx.play)
        bus.game.connect(self._on_game)
        bus.login_prompt.connect(self._login_prompt)
        bus.login_done.connect(self._login_done)
        bus.login_fail.connect(self._login_fail)
        bus.login_out.connect(self._login_out)
        bus.accounts.connect(self.home.refresh_accounts)
        bus.accounts.connect(self.settings.rebuild_accounts)
        bus.cfg_changed.connect(self._cfg_changed)

        # --- nền động
        self._timer = QTimer(self)
        self._timer.setInterval(66)
        self._timer.timeout.connect(self._tick)
        self.set_bg_anim(self._anim_on)

        self.retranslate()
        self.go("home", animate=False)
        self.pill.set_state("ready", ctx.tr("st_ready"))

    def _rail_progress(self, e):
        self.brand.expand = max(0.0, (e - 0.35) / 0.65)
        self.brand.update()

    # ------------------------------------------------------------ vẽ nền
    def _tick(self):
        if not self.isActiveWindow() or self.isMinimized() or self._playing:
            return
        self._t += 0.066
        self.update()

    def set_bg_anim(self, on):
        self._anim_on = on
        if on:
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def set_glass(self, v):
        self._glass = max(0.5, min(1.0, v / 100.0))
        self.update()

    def _make_shadow(self):
        dpr = self.devicePixelRatioF()
        key = (self.width(), self.height(), self.m, self.radius, dpr)
        if key == self._shadow_key and self._shadow is not None:
            return self._shadow
        pm = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        m = self.m
        base = QRectF(m, m + 5, self.width() - 2 * m, self.height() - 2 * m)
        for i in range(m, 0, -1):
            a = int(5.2 * (1 - i / (m + 1)) + 0.8)
            p.setBrush(QColor(0, 0, 0, a))
            p.drawRoundedRect(base.adjusted(-i, -i, i, i), self.radius + i, self.radius + i)
        p.end()
        self._shadow, self._shadow_key = pm, key
        return pm

    def _paint_bg(self, p: QPainter):
        m = self.m
        rect = QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m)
        if self.translucent and m and not (self.isMaximized() or self.isFullScreen()):
            p.drawPixmap(0, 0, self._make_shadow())
        path = QPainterPath()
        path.addRoundedRect(rect, self.radius, self.radius)
        a = self._glass if self.translucent else 1.0
        g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        top, bot = QColor(T.BG_TOP), QColor(T.BG_BOTTOM)
        top.setAlphaF(a)
        bot.setAlphaF(a)
        g.setColorAt(0, top)
        g.setColorAt(1, bot)
        p.fillPath(path, QBrush(g))
        p.save()
        p.setClipPath(path)
        t = self._t
        w, h = rect.width(), rect.height()
        # hai quầng sáng rất nhẹ trôi chậm — chỉ để nền không "chết"
        for cx, cy, rad, col, al in (
            (0.18 + 0.07 * math.sin(t * 0.17), 0.12 + 0.05 * math.cos(t * 0.13), 0.55, T.ACCENT, 0.075),
            (0.86 + 0.05 * math.cos(t * 0.11), 0.92 + 0.04 * math.sin(t * 0.15), 0.50, "#7a86a8", 0.045),
        ):
            rg = QRadialGradient(QPointF(rect.x() + w * cx, rect.y() + h * cy), max(w, h) * rad)
            c0 = QColor(col)
            c0.setAlphaF(al * (a if a < 1 else 1.0) + 0.0)
            c1 = QColor(col)
            c1.setAlphaF(0.0)
            rg.setColorAt(0, c0)
            rg.setColorAt(1, c1)
            p.fillRect(rect, QBrush(rg))
        p.restore()
        p.setPen(QPen(QColor(255, 255, 255, 26), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), self.radius, self.radius)

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._paint_bg(p)

    def grab_inner(self) -> QPixmap:
        """Ảnh nền + nội dung (không có sidebar) của vùng trong khung."""
        m = self.m
        dpr = self.devicePixelRatioF()
        w, h = self.width() - 2 * m, self.height() - 2 * m
        pm = QPixmap(int(w * dpr), int(h * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(-m, -m)
        self._paint_bg(p)
        p.translate(m, m)
        self.body.render(p, QPoint(0, 0))
        p.end()
        return pm

    def grab_under_rail(self) -> QPixmap:
        pm = self.grab_inner()
        dpr = pm.devicePixelRatio()
        return pm.copy(0, 0, int(Rail.W1 * dpr), pm.height())

    # ------------------------------------------------------------ hình học / trạng thái
    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        self._place_overlays()

    def _place_overlays(self):
        m = self.m
        self.rail.setFixedHeight(max(0, self.height() - 2 * m))
        self.rail.move(m, m)
        self.rail.raise_()
        self.toast_w.reposition()
        if self.modal.isVisible():
            self.modal.setGeometry(m, m, self.width() - 2 * m, self.height() - 2 * m)

    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        self._place_overlays()

    def changeEvent(self, e):  # noqa: N802
        if e.type() == QEvent.Type.WindowStateChange:
            full = self.isMaximized() or self.isFullScreen()
            m = 0 if full else (SHADOW if self.translucent else 5)
            if m != self.m:
                self.m = m
                self.radius = 0 if full else RADIUS
                self.layout().setContentsMargins(m, m, m, m)
                self._shadow = None
                self.b_max.setIconName("copy" if full else "square")
                QTimer.singleShot(0, self._place_overlays)
                self.update()
        super().changeEvent(e)

    def toggle_max(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    # --- kéo giãn cửa sổ bằng vùng đệm bóng
    def _edges(self, pos):
        if self.isMaximized() or self.isFullScreen():
            return Qt.Edge(0)
        z = max(self.m, 6)
        e = Qt.Edge(0)
        if pos.x() < z:
            e |= Qt.Edge.LeftEdge
        if pos.x() > self.width() - z:
            e |= Qt.Edge.RightEdge
        if pos.y() < z:
            e |= Qt.Edge.TopEdge
        if pos.y() > self.height() - z:
            e |= Qt.Edge.BottomEdge
        return e

    def mouseMoveEvent(self, e):  # noqa: N802
        ed = self._edges(e.position().toPoint())
        L, R, T_, B = Qt.Edge.LeftEdge, Qt.Edge.RightEdge, Qt.Edge.TopEdge, Qt.Edge.BottomEdge
        if (ed & L and ed & T_) or (ed & R and ed & B):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif (ed & R and ed & T_) or (ed & L and ed & B):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif ed & (L | R):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif ed & (T_ | B):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.unsetCursor()

    def mousePressEvent(self, e):  # noqa: N802
        ed = self._edges(e.position().toPoint())
        if ed and e.button() == Qt.MouseButton.LeftButton and self.windowHandle() is not None:
            self.windowHandle().startSystemResize(ed)

    # ------------------------------------------------------------ điều hướng
    def go(self, key, animate=True):
        page = self.pages[key]
        self.stack.setCurrentWidget(page._holder)
        for k, b in self.nav_btn.items():
            b.blockSignals(True)
            b.setChecked(k == key)
            b.blockSignals(False)
            b._on_toggled(k == key)
        self.title.setText(self.ctx.tr("nav_" + key))
        self.subtitle.setText(self.ctx.tr("sub_" + key, ver=self.ctx.ctl.mc_version))
        page.on_show()
        if animate:
            fade_in(page._holder, 190)
            self.ctx.play("nav")
        self._cur = key
        self.ctx.ctl.set_discord(self.ctx.tr("nav_" + key), f"Minecraft {self.ctx.ctl.mc_version} · {core.loader_label(self.ctx.ctl.loader)}")

    def _home_to_files(self, cat):
        self.files.select_category(cat)
        self.go("files")

    # ------------------------------------------------------------ dịch
    def retranslate(self):
        t = self.ctx.tr
        for key, _i, _l in NAV + BOTTOM:
            self.nav_btn[key].setLabel(t("nav_" + key))
        self.web_btn.setLabel(t("nav_website"))
        self.b_min.setToolTip(t("minimize"))
        self.b_max.setToolTip(t("maximize"))
        self.b_close.setToolTip(t("close"))
        for p in self.pages.values():
            p.retranslate()
        cur = getattr(self, "_cur", "home")
        self.title.setText(t("nav_" + cur))
        self.subtitle.setText(t("sub_" + cur, ver=self.ctx.ctl.mc_version))
        self.btn_play.setText(t(self._play_key()))
        self._on_status(self._status_kind if hasattr(self, "_status_kind") else "ready",
                        self._status_text if hasattr(self, "_status_text") else "")

    def apply_language(self, key):
        def commit(lang):
            self.ctx.set_lang(lang)
            self.retranslate()
            self.toast(self.ctx.tr("lang_changed"), "ok")

        if key in ("vi", "en"):
            commit(key)
            return
        cached = self.ctx.cfg.get("lang_detected")
        if cached in ("vi", "en"):
            commit(cached)
            return

        def work():
            import requests
            lang = detect_language(requests, 2.5)
            self.ctx.cfg["lang_detected"] = lang
            self.ctx.ctl.save()
            self.ctx.bus.invoke.emit(lambda: commit(lang))
        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------ phản hồi từ controller
    def _on_status(self, kind, text):
        self._status_kind, self._status_text = kind, text
        key = {"ready": "st_ready", "busy": "st_busy", "error": "st_error", "playing": "st_playing"}.get(kind, "st_ready")
        self.pill.set_state(kind, text or self.ctx.tr(key))

    def _on_java(self, text, kind):
        self.home.set_java(text, kind)
        self.settings.set_java(text, kind)

    def _sync_busy(self):
        ctl = self.ctx.ctl
        fabric = ctl.is_running("loader")
        self.home.fabric.setBusy(fabric)
        self.home.fabric.setEnabled(not fabric)
        self.optimize.set_busy(ctl.is_running("optimize"))
        launching = ctl.is_running("game") and not ctl.game_running()
        self.btn_play.setBusy(launching)
        self.home.play.setBusy(launching)

    def _on_progress(self, v, mx):
        self.home.progress.set_progress(v, mx)
        self.optimize.progress.set_progress(v, mx)
        self._sync_busy()

    def _play_key(self):
        return "btn_play_another" if self.ctx.ctl.game_running() else "btn_play"

    def _on_game(self, playing):
        self._playing = playing
        self.btn_play.setText(self.ctx.tr(self._play_key()))
        self.home.set_playing(playing)
        self._sync_busy()
        if playing and self.ctx.cfg.get("minimize_on_launch"):
            self.showMinimized()
        if not playing:
            self.update()

    def _cfg_changed(self):
        self.settings.java_path.setText(self.ctx.cfg.get("java_path", "java"))
        self.settings.refresh_shortcuts()

    def toast(self, text, kind="info"):
        self.toast_w.show_message(text, kind)

    # ------------------------------------------------------------ hành động chung
    def on_version(self, ver):
        ctl = self.ctx.ctl
        if not ver or ver == ctl.mc_version:
            return
        ctl.mc_version = ver
        self.ctx.cfg["mc_version"] = ver
        ctl.save()
        self.home.set_version_silent(ver)
        self.settings.set_version_silent(ver)
        self.toast(self.ctx.tr("ver_changed", ver=ver), "info")
        self.context_changed()

    def on_loader(self, lid):
        ctl = self.ctx.ctl
        if lid == ctl.loader or lid not in core.LOADER_IDS:
            return
        ctl.loader = lid
        self.ctx.cfg["loader"] = lid
        ctl.save()
        self.home.set_loader_silent(lid)
        self.toast(self.ctx.tr("loader_changed", loader=core.loader_label(lid)), "info")
        kind = self.ctx.cfg.get("ver_kind", "release")
        cur = ctl.mc_version

        def job():
            return core.loader_supports(lid, cur), core.list_mc_versions("release", lid, "")

        def done(res):
            ok, rel = res
            if lid != ctl.loader:
                return
            if ok is False and rel:        # loader không có bản MC đang chọn -> nhảy sang bản mới nhất nó hỗ trợ
                ctl.mc_version = rel[0]
                self.ctx.cfg["mc_version"] = rel[0]
                ctl.save()
                self.toast(self.ctx.tr("ver_changed", ver=rel[0]), "info")
            self.reload_versions()
            self.context_changed()
        ctl.call_async(job, done)
        self.context_changed()

    def reload_versions(self):
        """Nạp lại danh sách phiên bản theo loại (release/snapshot/all) và loader (nền, có cache)."""
        ctl = self.ctx.ctl
        kind = self.ctx.cfg.get("ver_kind", "release")
        if kind not in core.VERSION_KINDS:
            kind = "release"
        self._ver_seq = getattr(self, "_ver_seq", 0) + 1
        seq, lid, cur = self._ver_seq, ctl.loader, ctl.mc_version

        def done(lst):
            if seq != self._ver_seq or not lst:
                return
            now = ctl.mc_version
            if now not in lst:
                lst = [now] + lst
            self.home.set_versions(lst, now)
            self.settings.set_versions(lst, now)
        ctl.call_async(lambda: core.list_mc_versions(kind, lid, cur), done)

    def context_changed(self):
        """Đổi phiên bản / loader / thư mục: làm mới mọi trang phụ thuộc vào chúng."""
        ctl = self.ctx.ctl
        self.home.retranslate()
        self.optimize.rebuild_mods()
        self.mods.version_changed()
        self.files.refresh()
        self.subtitle.setText(self.ctx.tr("sub_" + getattr(self, "_cur", "home"), ver=ctl.mc_version))
        ctl.check_java_quiet()
        ctl.set_discord(f"Minecraft {ctl.mc_version}", f"{core.loader_label(ctl.loader)} · Arch Client")

    def set_mc_dir(self, path: Path):
        info = core.ensure_minecraft_dir(path)
        ctl = self.ctx.ctl
        ctl.mc_dir = path
        self.ctx.cfg["mc_dir"] = str(path)
        ctl.save()
        if info["created"]:
            ctl.log(f"Đã tạo thư mục con còn thiếu: {', '.join(info['created'])}", "dim")
        self.refresh_all()

    def refresh_all(self):
        self.home.refresh()
        self.files.refresh()

    def set_playing_state(self, playing):
        self._on_game(playing)

    def confirm(self, title, body, yes_label, on_yes, danger=False):
        t = self.ctx.tr
        self.modal.open(title, body, None, buttons=[
            (t("btn_cancel"), "ghost", None, True),
            (yes_label, "danger" if danger else "primary", on_yes, True)])

    def _login_prompt(self, url, auto):
        QDesktopServices.openUrl(QUrl(url))
        t = self.ctx.tr
        ctl = self.ctx.ctl
        self._login_modal = True
        if auto:
            def paste():
                ctl.login_cancel()
                ctl.login_microsoft(self.ctx.cfg.get("azure_client_id", ""), manual=True)
            self.modal.open(t("login_title"), t("login_body_auto"), None, buttons=[
                (t("btn_cancel"), "ghost", ctl.login_cancel, True),
                (t("btn_paste_url"), "primary", paste, True)])
            return
        field = QLineEdit()
        field.setPlaceholderText(t("login_ph"))
        field.setMinimumWidth(360)

        def ok():
            ctl.login_finish(field.text())
        field.returnPressed.connect(lambda: (self.modal.close_card(), ok()))
        self.modal.open(t("login_title"), t("login_body"), field, buttons=[
            (t("btn_cancel"), "ghost", None, True), (t("btn_ok"), "primary", ok, True)], focus=field)

    def _close_login_modal(self):
        if getattr(self, "_login_modal", False):
            self._login_modal = False
            self.modal.close_card()

    def _login_done(self, name):
        self._close_login_modal()
        self.toast(self.ctx.tr("login_ok", name=name), "ok")

    def _login_fail(self, msg):
        self._close_login_modal()
        self.toast(msg, "error")

    def _login_out(self):
        self.toast(self.ctx.tr("logout_ok"), "info")

    # ------------------------------------------------------------ đóng
    def closeEvent(self, e):  # noqa: N802
        try:
            if not (self.isMaximized() or self.isFullScreen()):
                self.ctx.cfg["win_w"], self.ctx.cfg["win_h"] = self.width(), self.height()
            self.ctx.ctl.save()
            self.ctx.ctl.shutdown()
            self.ctx.sound.shutdown()
        except Exception:
            pass
        e.accept()


# ==========================================================================
# SPLASH
# ==========================================================================
class Splash(QWidget):
    def __init__(self, translucent=True):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint)
        self.translucent = translucent
        if translucent:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(380, 250)
        self._text = ""
        self._ph = 0.0
        self.pm = QPixmap(str(resource_path("img/logo.png")))
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_status(self, text):
        self._text = text
        self.update()

    def _tick(self):
        self._ph = (self._ph + 0.014) % 1.0
        self.update()

    def center(self):
        scr = self.screen().availableGeometry() if self.screen() else QRect(0, 0, 1280, 720)
        self.move(scr.center() - QPoint(self.width() // 2, self.height() // 2))

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(8, 8, -8, -8) if self.translucent else QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(r, 20, 20)
        if self.translucent:
            for i in range(8, 0, -1):
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(0, 0, 0, 5))
                p.drawRoundedRect(r.adjusted(-i, -i + 3, i, i + 3), 20 + i, 20 + i)
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0, QColor(T.BG_TOP))
        g.setColorAt(1, QColor(T.BG_BOTTOM))
        p.fillPath(path, QBrush(g))
        rg = QRadialGradient(QPointF(r.center().x(), r.top() + 40), 220)
        c0 = QColor(T.ACCENT)
        c0.setAlphaF(0.10)
        c1 = QColor(T.ACCENT)
        c1.setAlphaF(0.0)
        rg.setColorAt(0, c0)
        rg.setColorAt(1, c1)
        p.save()
        p.setClipPath(path)
        p.fillRect(r, QBrush(rg))
        p.restore()
        p.setPen(QPen(QColor(255, 255, 255, 28), 1))
        p.drawPath(path)
        if not self.pm.isNull():
            p.drawPixmap(QRect(int(self.width() / 2 - 36), 40, 72, 72), self.pm)
        f = self.font()
        f.setPixelSize(20)
        f.setWeight(f.Weight.Bold)
        p.setFont(f)
        p.setPen(QColor(T.TEXT))
        p.drawText(QRectF(0, 122, self.width(), 30), Qt.AlignmentFlag.AlignCenter, APP_NAME)
        f.setPixelSize(12)
        f.setWeight(f.Weight.Normal)
        p.setFont(f)
        p.setPen(QColor(T.MUTED))
        p.drawText(QRectF(0, 154, self.width(), 20), Qt.AlignmentFlag.AlignCenter, self._text)
        bar = QRectF(r.center().x() - 80, 196, 160, 3)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 24))
        p.drawRoundedRect(bar, 1.5, 1.5)
        seg = 56.0
        x = bar.x() + (bar.width() + seg) * self._ph - seg
        clip = QPainterPath()
        clip.addRoundedRect(bar, 1.5, 1.5)
        p.setClipPath(clip)
        p.setBrush(QColor(T.ACCENT))
        p.drawRoundedRect(QRectF(x, bar.y(), seg, bar.height()), 1.5, 1.5)
