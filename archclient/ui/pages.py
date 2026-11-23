# -*- coding: utf-8 -*-
"""Pages: Home, Files, Mods, Optimize, Console, Settings."""
from __future__ import annotations

import shutil
import subprocess
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QModelIndex, QRectF, QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import (QColor, QDesktopServices, QFontMetrics, QIcon, QPainter, QPainterPath,
                         QPen, QPixmap, QTextCharFormat, QTextCursor, QAction)
from PyQt6.QtWidgets import (QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QPlainTextEdit, QSlider, QStyle, QStyledItemDelegate,
                             QVBoxLayout, QWidget, QAbstractItemView, QSizePolicy, QApplication)

from .. import core
from ..bootstrap import ERROR_LOG_DIR, resource_path, write_error_log
from . import theme as T
from .icons import icon_pixmap
from .widgets import (Btn, ElidedLabel, Glass, HoverAnim, IconBtn, Label, Progress, Scroll, Segmented,
                      Select, Sep, Switch, fade_in)


def open_path(path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def open_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


class Page(QWidget):
    key = ""

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx

    def on_show(self):
        pass

    def retranslate(self):
        pass

    def tr_(self, key, **kw):
        return self.ctx.tr(key, **kw)


def vbox(margins=(0, 0, 0, 0), spacing=0, parent=None):
    lay = QVBoxLayout(parent) if parent is not None else QVBoxLayout()
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return lay


def hbox(margins=(0, 0, 0, 0), spacing=0, parent=None):
    lay = QHBoxLayout(parent) if parent is not None else QHBoxLayout()
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return lay


def scroll_page(page: Page, content: QWidget):
    s = Scroll()
    s.set_content(content)
    lay = vbox(parent=page)
    lay.addWidget(s)
    return s


# ==========================================================================
# HOME
# ==========================================================================
class Meter(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.frac = 0.0
        self.mark = None
        self.setFixedHeight(6)

    def set_values(self, frac, mark=None):
        self.frac, self.mark = max(0.0, min(1.0, frac)), mark
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 22))
        p.drawRoundedRect(r, 3, 3)
        p.setBrush(QColor(T.ACCENT))
        p.drawRoundedRect(QRectF(0, 0, r.width() * self.frac, r.height()), 3, 3)
        if self.mark is not None:
            x = r.width() * max(0.0, min(1.0, self.mark))
            p.setBrush(QColor(255, 255, 255, 150))
            p.drawRoundedRect(QRectF(x - 1, -2, 2, r.height() + 4), 1, 1)


class StatCard(Glass):
    def __init__(self, icon, parent=None):
        super().__init__(16, parent)
        self.icon_name = icon
        lay = vbox((18, 16, 18, 16), 4, self)
        top = hbox(spacing=8)
        self.ico = QLabel()
        self.ico.setPixmap(icon_pixmap(icon, T.MUTED, 16, self.devicePixelRatioF()))
        self.ico.setStyleSheet("background:transparent;")
        self.title = Label("", 12, 500, T.MUTED)
        top.addWidget(self.ico)
        top.addWidget(self.title)
        top.addStretch(1)
        self.action = None
        lay.addLayout(top)
        lay.addSpacing(6)
        self.value = Label("—", 20, 600)
        lay.addWidget(self.value)
        self.detail = Label("", 12, 400, T.MUTED, wrap=True)
        lay.addWidget(self.detail)
        self.extra = vbox(spacing=0)
        lay.addLayout(self.extra)
        lay.addStretch(1)
        self.setMinimumHeight(136)

    def add_action(self, btn):
        self.action = btn
        self.layout().itemAt(0).layout().addWidget(btn)

    def set(self, value, detail="", color=T.TEXT):
        self.value.setText(value)
        self.value.setStyleSheet(f"color:{color}; font-size:20px; font-weight:600; background:transparent;")
        self.detail.setText(detail)


class CountTile(Glass):
    clicked = pyqtSignal(str)

    def __init__(self, key, icon, parent=None):
        super().__init__(14, parent)
        self.key, self.icon_name = key, icon
        self._h = HoverAnim(self, 140)
        self._count = 0
        self._label = ""
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(84)

    def set(self, count, label):
        self._count, self._label = count, label
        self.update()

    def enterEvent(self, e):  # noqa: N802
        self._h.to(1)
        super().enterEvent(e)

    def leaveEvent(self, e):  # noqa: N802
        self._h.to(0)
        super().leaveEvent(e)

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.key)

    def paintEvent(self, e):  # noqa: N802
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self._h.v
        if h > 0.01:
            path = QPainterPath()
            path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 14, 14)
            p.fillPath(path, T.qc(T.ACCENT, 0.08 * h))
            p.setPen(QPen(T.qc(T.ACCENT, 0.5 * h), 1))
            p.drawPath(path)
        col = T.ACCENT_HI if h > 0.5 else T.MUTED
        p.drawPixmap(18, 16, icon_pixmap(self.icon_name, col, 16, self.devicePixelRatioF()))
        f = self.font()
        f.setPixelSize(12)
        p.setFont(f)
        p.setPen(QColor(T.MUTED))
        p.drawText(QRectF(42, 14, self.width() - 50, 20), Qt.AlignmentFlag.AlignVCenter, self._label)
        f.setPixelSize(24)
        f.setWeight(f.Weight.DemiBold)
        p.setFont(f)
        p.setPen(QColor(T.TEXT))
        p.drawText(QRectF(18, 38, self.width() - 30, 36), Qt.AlignmentFlag.AlignVCenter, str(self._count))


class HomePage(Page):
    key = "home"
    request_files = pyqtSignal(str)

    def __init__(self, ctx):
        super().__init__(ctx)
        c = QWidget()
        root = vbox((0, 0, 8, 0), 16, c)

        # --- hero
        self.hero = Glass(20)
        hl = hbox((30, 26, 30, 26), 24, self.hero)
        left = vbox(spacing=0)
        self.title = Label("", 28, 700)
        self.sub = Label("", 14, 400, T.MUTED, wrap=True)
        left.addWidget(self.title)
        left.addSpacing(6)
        left.addWidget(self.sub)
        left.addSpacing(20)
        self.ver_lbl = Label("", 12, 500, T.MUTED)
        left.addWidget(self.ver_lbl)
        left.addSpacing(6)
        self.ver = Select()
        self.ver.addItems(core.list_mc_versions_offline(ctx.ctl.mc_version))
        self.ver.setCurrentText(ctx.ctl.mc_version)
        self.ver.setFixedWidth(170)
        left.addWidget(self.ver)
        left.addSpacing(14)
        self.loader_lbl = Label("", 12, 500, T.MUTED)
        left.addWidget(self.loader_lbl)
        left.addSpacing(6)
        self.loader = Segmented([(i, n, ic) for i, n, ic in core.LOADERS], ctx.ctl.loader)
        left.addWidget(self.loader, 0, Qt.AlignmentFlag.AlignLeft)
        left.addSpacing(14)
        self.acct_lbl = Label("", 12, 500, T.MUTED)
        left.addWidget(self.acct_lbl)
        left.addSpacing(6)
        self.acct = Select()
        self.acct.setFixedWidth(260)
        left.addWidget(self.acct, 0, Qt.AlignmentFlag.AlignLeft)
        left.addSpacing(20)
        btns = hbox(spacing=10)
        self.play = Btn("", "play", "primary", "lg")
        self.fabric = Btn("", "download", "ghost", "lg")
        btns.addWidget(self.play)
        btns.addWidget(self.fabric)
        btns.addStretch(1)
        left.addLayout(btns)
        left.addSpacing(14)
        self.progress = Progress()
        left.addWidget(self.progress)
        left.addStretch(1)
        hl.addLayout(left, 1)
        logo = QLabel()
        pm = QPixmap(str(resource_path("img/logo.png")))
        if not pm.isNull():
            sz = 150
            pm = pm.scaled(int(sz * self.devicePixelRatioF()), int(sz * self.devicePixelRatioF()),
                           Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            pm.setDevicePixelRatio(self.devicePixelRatioF())
            logo.setPixmap(pm)
        logo.setStyleSheet("background:transparent;")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setFixedWidth(190)
        hl.addWidget(logo, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(self.hero)

        # --- info cards
        cards = hbox(spacing=14)
        self.c_java = StatCard("coffee")
        self.btn_java = Btn("", "refresh-cw", "subtle", "sm")
        self.c_java.add_action(self.btn_java)
        self.c_ram = StatCard("layers")
        self.ram_meter = Meter()
        self.c_ram.extra.addSpacing(6)
        self.c_ram.extra.addWidget(self.ram_meter)
        self.c_sys = StatCard("cpu")
        for w in (self.c_java, self.c_ram, self.c_sys):
            cards.addWidget(w, 1)
        root.addLayout(cards)

        # --- installed
        self.inst_title = Label("", 13, 600)
        root.addWidget(self.inst_title)
        tiles = hbox(spacing=14)
        self.tiles = {}
        for (key, _e, lk), ic in zip(core.CATEGORIES, ("puzzle", "package", "layers", "folder")):
            t = CountTile(key, ic)
            t.clicked.connect(self.request_files.emit)
            self.tiles[key] = (t, lk)
            tiles.addWidget(t, 1)
        root.addLayout(tiles)
        root.addStretch(1)
        scroll_page(self, c)

        self.fabric.clicked.connect(ctx.ctl.install_loader)
        self.btn_java.clicked.connect(ctx.ctl.install_java)
        self.ver.activated.connect(lambda _i: ctx.window.on_version(self.ver.currentText()))
        self.loader.changed.connect(lambda k: ctx.window.on_loader(k))
        self.acct.activated.connect(lambda _i: ctx.ctl.set_active_account(self.acct.currentData()))
        self._java = (None, "idle")
        self.refresh_accounts()
        self.retranslate()
        self.refresh()

    def set_version_silent(self, ver):
        self.ver.blockSignals(True)
        if self.ver.findText(ver) < 0:
            self.ver.addItem(ver)
        self.ver.setCurrentText(ver)
        self.ver.blockSignals(False)
        self.retranslate()

    def set_versions(self, versions, current):
        self.ver.blockSignals(True)
        self.ver.clear()
        self.ver.addItems(versions)
        self.ver.setCurrentText(current)
        self.ver.blockSignals(False)

    def set_loader_silent(self, lid):
        self.loader.setCurrent(lid)
        self.retranslate()

    def set_java(self, text, kind):
        self._java = (text, kind)
        col = {"ok": T.OK, "error": T.ERR, "warn": T.WARN, "busy": T.WARN}.get(kind, T.TEXT)
        self.c_java.set(text, "", col)
        self.btn_java.setBusy(kind == "busy")
        self.btn_java.setEnabled(kind != "busy")

    def refresh_accounts(self):
        ctl = self.ctx.ctl
        self.acct.blockSignals(True)
        self.acct.clear()
        cur = 0
        for i, a in enumerate(ctl.accounts()):
            self.acct.addItem(ctl.account_label(a), a["id"])
            if a["id"] == ctl.cfg.get("active_account"):
                cur = i
        self.acct.setCurrentIndex(cur)
        self.acct.blockSignals(False)

    def _play_key(self):
        return "btn_play_another" if self.ctx.ctl.game_running() else "btn_play"

    def set_playing(self, playing):
        self.play.setText(self.tr_(self._play_key()))        # always clickable: launch another game with another account

    def retranslate(self):
        t = self.tr_
        self.title.setText(t("hero_title"))
        self.sub.setText(t("hero_sub", ver=self.ctx.ctl.mc_version, loader=core.loader_label(self.ctx.ctl.loader)))
        self.ver_lbl.setText(t("ver_label"))
        self.loader_lbl.setText(t("loader_label"))
        self.play.setText(t(self._play_key()))
        self.acct_lbl.setText(t("acc_label"))
        self.refresh_accounts()
        lid = self.ctx.ctl.loader
        self.fabric.setText(t("btn_install_vanilla") if lid == "vanilla"
                            else t("btn_install_loader", loader=core.loader_label(lid)))
        self.c_java.title.setText(t("card_java"))
        self.c_ram.title.setText(t("card_ram"))
        self.c_sys.title.setText(t("card_system"))
        self.inst_title.setText(t("installed_title"))
        if self._java[0] is None:
            self.c_java.set(t("java_unchecked"), "", T.MUTED)
        self.refresh()

    def refresh(self):
        ctl, t = self.ctx.ctl, self.tr_
        for key, exts, lk in core.CATEGORIES:
            n = len(core.scan_category(ctl.game_dir, key, exts))
            tile, _ = self.tiles[key]
            tile.set(n, t(lk))
        hw = core.hw_summary()
        ram = int(self.ctx.cfg.get("ram_mb", 3072))
        total = max(1, hw["ram"])
        self.c_ram.set(f"{ram / 1024:.1f} GB", t("ram_of", used=f"{ram / 1024:.1f}", total=f"{total / 1024:.1f}"))
        self.ram_meter.set_values(ram / total, hw["suggest_ram"] / total)
        self.c_sys.set(hw["gpu"], f"{hw['session'].upper()}  ·  " + t("sys_cpu", cores=hw["cores"], gov=hw["gov"]))


# ==========================================================================
# FILES
# ==========================================================================
class FileDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):  # noqa: N802
        return QSize(100, 40)

    def paint(self, p, option, index):  # noqa: N802
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(option.rect).adjusted(2, 1, -2, -1)
        sel = bool(option.state & QStyle.StateFlag.State_Selected)
        hov = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if sel or hov:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(T.qc(T.ACCENT, 0.20) if sel else QColor(255, 255, 255, 12))
            p.drawRoundedRect(r, 9, 9)
        icon = index.data(Qt.ItemDataRole.UserRole + 2) or "puzzle"
        p.drawPixmap(int(r.x() + 12), int(r.y() + (r.height() - 16) / 2),
                     icon_pixmap(icon, T.ACCENT_HI if sel else T.MUTED, 16, p.device().devicePixelRatioF()))
        size = index.data(Qt.ItemDataRole.UserRole + 1) or ""
        f = option.font
        f.setPixelSize(13)
        p.setFont(f)
        fm = QFontMetrics(f)
        sw = fm.horizontalAdvance(size) + 8
        p.setPen(QColor(T.FAINT))
        p.drawText(QRectF(r.right() - sw - 8, r.y(), sw, r.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, size)
        p.setPen(QColor(T.TEXT))
        name = fm.elidedText(index.data(Qt.ItemDataRole.DisplayRole) or "", Qt.TextElideMode.ElideMiddle,
                             int(r.width() - sw - 52))
        p.drawText(QRectF(r.x() + 38, r.y(), r.width() - sw - 52, r.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)
        p.restore()


class FilesPage(Page):
    key = "files"

    def __init__(self, ctx):
        super().__init__(ctx)
        lay = vbox((0, 0, 0, 0), 14, self)
        top = hbox(spacing=10)
        self.path = QLineEdit()
        self.path.setReadOnly(True)
        self.btn_dir = Btn("", "folder", "ghost")
        self.btn_open = Btn("", "external-link", "ghost")
        self.btn_add = Btn("", "file-plus", "ghost")
        top.addWidget(self.path, 1)
        top.addWidget(self.btn_add)
        top.addWidget(self.btn_dir)
        top.addWidget(self.btn_open)
        lay.addLayout(top)
        self.seg = Segmented([(k, k) for k, _e, _l in core.CATEGORIES], "mods")
        sr = hbox()
        sr.addWidget(self.seg)
        sr.addStretch(1)
        lay.addLayout(sr)
        self.panel = Glass(16)
        pl = vbox((8, 8, 8, 8), 0, self.panel)
        self.list = QListWidget()
        self.list.setItemDelegate(FileDelegate(self.list))
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.setUniformItemSizes(True)
        self.list.setMouseTracking(True)
        self.list.viewport().setAutoFillBackground(False)
        self.list.setFrameShape(QListWidget.Shape.NoFrame)
        pl.addWidget(self.list)
        self.empty = Label("", 13, 400, T.FAINT)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pl.addWidget(self.empty)
        lay.addWidget(self.panel, 1)
        foot = hbox(spacing=10)
        self.count = Label("", 12, 400, T.MUTED)
        self.btn_refresh = Btn("", "refresh-cw", "subtle", "sm")
        self.btn_del = Btn("", "trash-2", "danger", "sm")
        foot.addWidget(self.count)
        foot.addStretch(1)
        foot.addWidget(self.btn_refresh)
        foot.addWidget(self.btn_del)
        lay.addLayout(foot)

        self.seg.changed.connect(lambda _k: self.refresh())
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_open.clicked.connect(self._open_current)
        self.btn_dir.clicked.connect(self._choose_dir)
        self.btn_add.clicked.connect(self._add_files)
        self.btn_del.clicked.connect(self._delete)
        self.list.itemSelectionChanged.connect(self._sel_changed)
        self.list.itemDoubleClicked.connect(lambda _i: self._open_current())
        self.retranslate()
        self.refresh()

    def select_category(self, key):
        self.seg.setCurrent(key)
        self.refresh()

    def _cur(self):
        key = self.seg.current()
        for k, exts, lk in core.CATEGORIES:
            if k == key:
                return k, exts, lk
        return core.CATEGORIES[0]

    def _open_current(self):
        key, _e, _l = self._cur()
        d = self.ctx.ctl.ensure_game_dir() / key
        d.mkdir(parents=True, exist_ok=True)
        open_path(d)

    def _choose_dir(self):
        d = QFileDialog.getExistingDirectory(self, self.tr_("btn_change_dir"), str(self.ctx.ctl.mc_dir))
        if d:
            self.ctx.window.set_mc_dir(Path(d))

    def _add_files(self):
        """Add an existing file (e.g. an OptiFine .jar you downloaded) into the folder of the current tab."""
        key, exts, _lk = self._cur()
        flt = "Files (" + " ".join("*" + e for e in sorted(exts)) + ");;All (*)"
        paths, _ = QFileDialog.getOpenFileNames(self, self.tr_("btn_add_file"), str(Path.home() / "Downloads"), flt)
        if not paths:
            return
        dest = self.ctx.ctl.ensure_game_dir() / key
        dest.mkdir(parents=True, exist_ok=True)
        n = 0
        for p in paths:
            try:
                shutil.copy2(p, dest / Path(p).name)
                n += 1
            except OSError as e:
                self.ctx.ctl.log(f"Could not add {Path(p).name}: {e}", "error")
        self.ctx.toast(self.tr_("added_n", n=n), "ok")
        self.ctx.window.refresh_all()

    def _sel_changed(self):
        self.btn_del.setEnabled(bool(self.list.selectedItems()))

    def _delete(self):
        items = self.list.selectedItems()
        if not items:
            return
        key, _e, _l = self._cur()
        names = [i.text() for i in items]
        base = self.ctx.ctl.game_dir / key

        def do():
            n = 0
            for name in names:
                tgt = base / name
                try:
                    if tgt.is_dir():
                        shutil.rmtree(tgt)
                    else:
                        tgt.unlink()
                    n += 1
                except OSError as e:
                    self.ctx.ctl.log(f"Could not delete {name}: {e}", "error")
            self.ctx.toast(self.tr_("deleted", n=n), "ok")
            self.ctx.window.refresh_all()
        self.ctx.window.confirm(self.tr_("delete_title", n=len(names)), self.tr_("delete_body"),
                                self.tr_("btn_confirm"), do, danger=True)

    def retranslate(self):
        t = self.tr_
        self.path.setPlaceholderText(t("files_dir"))
        self.btn_dir.setText(t("btn_change_dir"))
        self.btn_open.setText(t("btn_open_dir"))
        self.btn_add.setText(t("btn_add_file"))
        self.btn_refresh.setText(t("btn_refresh"))
        self.btn_del.setText(t("btn_delete"))
        self.empty.setText(t("files_empty"))
        self.seg.set_labels({k: t(lk) for k, _e, lk in core.CATEGORIES})
        self.refresh()

    def on_show(self):
        self.refresh()

    def refresh(self):
        self.path.setText(str(self.ctx.ctl.game_dir))
        key, exts, _lk = self._cur()
        rows = core.scan_category(self.ctx.ctl.game_dir, key, exts)
        self.list.setUpdatesEnabled(False)
        self.list.clear()
        icon = {"mods": "puzzle", "resourcepacks": "package", "shaderpacks": "layers",
                "schematics": "layers"}.get(key, "package")
        for name, size, isdir in rows:
            it = QListWidgetItem(name + ("/" if isdir else ""))
            it.setData(Qt.ItemDataRole.UserRole + 1, "" if isdir else core.human_size(size))
            it.setData(Qt.ItemDataRole.UserRole + 2, "folder" if isdir else icon)
            it.setText(name)
            self.list.addItem(it)
        self.list.setUpdatesEnabled(True)
        self.empty.setVisible(not rows)
        self.list.setVisible(bool(rows))
        self.count.setText(self.tr_("files_count", n=len(rows)))
        self._sel_changed()


# ==========================================================================
# MODS (Modrinth)
# ==========================================================================
class Thumb(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pm: QPixmap | None = None
        self.setFixedSize(56, 56)

    def set_pixmap(self, pm):
        self.pm = pm
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 56, 56), 12, 12)
        p.setClipPath(path)
        if self.pm is None:
            p.fillPath(path, QColor(255, 255, 255, 14))
            p.drawPixmap(20, 20, icon_pixmap("puzzle", T.FAINT, 16, self.devicePixelRatioF()))
        else:
            p.drawPixmap(QRectF(0, 0, 56, 56).toRect(), self.pm)


class ModCard(Glass):
    download = pyqtSignal(object)
    open_page = pyqtSignal(object)

    def __init__(self, hit: dict, t):
        super().__init__(14)
        self.hit = hit
        self.setFixedHeight(84)
        lay = hbox((14, 12, 14, 12), 14, self)
        self.thumb = Thumb()
        lay.addWidget(self.thumb)
        col = vbox(spacing=2)
        self.title = Label(hit.get("title") or hit.get("slug") or "?", 14, 600)
        dl = hit.get("downloads") or 0
        meta = f"{hit.get('author') or ''}   ·   {t('downloads', n=f'{dl:,}')}"
        self.meta = ElidedLabel(meta, 12, T.FAINT)
        self.desc = ElidedLabel((hit.get("description") or "").replace("\n", " "), 12, T.MUTED)
        col.addWidget(self.title)
        col.addWidget(self.meta)
        col.addWidget(self.desc)
        lay.addLayout(col, 1)
        self.btn_page = IconBtn("globe", t("btn_open_page"), 34)
        self.btn = Btn(t("btn_download"), "download", "primary", "md")
        self.btn.setMinimumWidth(104)
        lay.addWidget(self.btn_page)
        lay.addWidget(self.btn)
        self.btn.clicked.connect(lambda: self.download.emit(self))
        self.btn_page.clicked.connect(lambda: self.open_page.emit(self))
        self._t = t

    def set_state(self, state):
        t = self._t
        if state == "busy":
            self.btn.setBusy(True)
            self.btn.setEnabled(False)
            self.btn.setText("")
        else:
            self.btn.setBusy(False)
            self.btn.setEnabled(True)
            if state == "done":
                self.btn.setIconName("check")
                self.btn.setText(t("mods_done", name="").strip() or "OK")
            elif state == "fail":
                self.btn.setIconName("refresh-cw")
                self.btn.setText(t("btn_retry"))
            else:
                self.btn.setIconName("download")
                self.btn.setText(t("btn_download"))


class ModsPage(Page):
    key = "mods"

    def __init__(self, ctx):
        super().__init__(ctx)
        lay = vbox((0, 0, 0, 0), 14, self)
        top = hbox(spacing=10)
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self._sicon = QAction(self)
        self.search.addAction(self._sicon, QLineEdit.ActionPosition.LeadingPosition)
        self._sicon.setIcon(QIcon(icon_pixmap("search", T.MUTED, 16, 2.0)))
        self.btn_search = Btn("", "search", "primary")
        top.addWidget(self.search, 1)
        top.addWidget(self.btn_search)
        lay.addLayout(top)
        row = hbox(spacing=12)
        self.seg = Segmented([(k, k) for k, _f, _l in core.BROWSE_TYPES], "mod")
        self.status = Label("", 12, 400, T.MUTED)
        row.addWidget(self.seg)
        row.addWidget(self.status, 1)
        lay.addLayout(row)
        self.scroll = Scroll()
        holder = QWidget()
        self.col = vbox((0, 0, 8, 0), 10, holder)
        self.col.addStretch(1)
        self.scroll.set_content(holder)
        lay.addWidget(self.scroll, 1)
        self.more = Btn("", "chevron-down", "ghost")
        self.more.hide()
        self.col.insertWidget(0, self.more, 0, Qt.AlignmentFlag.AlignHCenter)

        self._token = 0
        self._offset = 0
        self._total = 0
        self._cards: list = []
        self._thumbs: OrderedDict = OrderedDict()   # url -> QPixmap (LRU)
        self._first = True
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(480)
        self._debounce.timeout.connect(lambda: self.do_search(True))
        self.search.textChanged.connect(lambda _s: self._debounce.start())
        self.search.returnPressed.connect(lambda: self.do_search(True))
        self.btn_search.clicked.connect(lambda: self.do_search(True))
        self.seg.changed.connect(lambda _k: self.do_search(True))
        self.more.clicked.connect(lambda: self.do_search(False))
        self.retranslate()

    def on_show(self):
        if self._first:
            self._first = False
            self.do_search(True)

    def retranslate(self):
        t = self.tr_
        self.search.setPlaceholderText(t("search_ph"))
        self.seg.set_labels({k: t(lk) for k, _f, lk in core.BROWSE_TYPES})
        self.more.setText(t("btn_load_more"))
        self.btn_search.setText("")

    def version_changed(self):
        if not self._first:
            self.do_search(True)

    def _clear(self):
        for c in self._cards:
            self.col.removeWidget(c)
            c.deleteLater()
        self._cards.clear()

    def do_search(self, reset=True):
        self._debounce.stop()
        if reset:
            self._token += 1
            self._offset = 0
            self._clear()
            self.more.hide()
        tok = self._token
        self.status.setText(self.tr_("mods_searching"))
        self.status.setStyleSheet(f"color:{T.MUTED}; font-size:12px; background:transparent;")
        self.ctx.ctl.search_mods(self.search.text().strip(), self.seg.current(), self._offset,
                                 lambda res: self._results(tok, res),
                                 lambda e: self._error(tok, e))

    def _error(self, tok, e):
        if tok != self._token:
            return
        name = type(e).__name__
        offline = any(k in name for k in ("Connection", "Timeout", "Proxy", "SSL")) or isinstance(e, OSError)
        self.status.setText(self.tr_("mods_offline") if offline else self.tr_("mods_error", err=str(e)[:90]))
        self.status.setStyleSheet(f"color:{T.ERR}; font-size:12px; background:transparent;")
        self.more.setText(self.tr_("btn_retry"))
        self.more.setIconName("refresh-cw")
        self.more.show()

    def _results(self, tok, res):
        if tok != self._token:
            return
        hits, total = res
        self._total = total
        self.more.setText(self.tr_("btn_load_more"))
        self.more.setIconName("chevron-down")
        t = self.tr_
        for h in hits:
            card = ModCard(h, t)
            card.download.connect(self._download)
            card.open_page.connect(self._open_page)
            self.col.insertWidget(self.col.count() - 1, card)
            self._cards.append(card)
            url = h.get("icon_url") or ""
            if url:
                self._load_thumb(card, url)
        self._offset += len(hits)
        self.more.setVisible(self._offset < total)
        # the "load more" button always sits right before the final spacer
        self.col.removeWidget(self.more)
        self.col.insertWidget(self.col.count() - 1, self.more, 0, Qt.AlignmentFlag.AlignHCenter)
        ver = self.ctx.ctl.mc_version
        self.status.setStyleSheet(f"color:{T.MUTED}; font-size:12px; background:transparent;")
        if not total and self.ctx.ctl.loader == "vanilla" and self.seg.current() == "mod":
            self.status.setText(t("mods_vanilla"))
        else:
            self.status.setText(t("mods_found", n=f"{total:,}", ver=ver) if total else t("mods_empty", ver=ver))
        if hits and len(self._cards) == len(hits):
            fade_in(self.scroll.widget(), 220)

    def _load_thumb(self, card, url):
        pm = self._thumbs.get(url)
        if pm is not None:
            self._thumbs.move_to_end(url)
            card.thumb.set_pixmap(pm)
            return
        px = int(56 * max(1.0, self.devicePixelRatioF()))

        def done(img):
            if img is None:
                return
            try:
                pm2 = QPixmap.fromImage(img)
                pm2.setDevicePixelRatio(1.0)
                self._thumbs[url] = pm2
                while len(self._thumbs) > 120:      # cap image memory
                    self._thumbs.popitem(last=False)
                card.thumb.set_pixmap(pm2)
            except RuntimeError:
                pass   # card already removed
        self.ctx.ctl.fetch_thumb(url, px, done)

    def _open_page(self, card):
        slug = card.hit.get("slug") or card.hit.get("project_id")
        ptype = self.seg.current()
        open_url(f"https://modrinth.com/{ptype}/{slug}")

    def _download(self, card):
        hit = card.hit
        slug = hit.get("slug") or hit.get("project_id")
        name = hit.get("title") or slug
        ptype = self.seg.current()
        ctl = self.ctx.ctl
        card.set_state("busy")
        self.status.setText(self.tr_("mods_downloading", name=name))

        def done(ok, err):
            try:
                card.set_state("done" if ok else "fail")
            except RuntimeError:
                pass
            if ok:
                self.ctx.toast(self.tr_("mods_done", name=name), "ok")
            else:
                msg = self.tr_("mods_fail", name=name, ver=ctl.mc_version) if err is None else str(err)[:80]
                self.ctx.toast(msg, "error")
        ctl.download_project(slug, ptype, name, done)


# ==========================================================================
# OPTIMIZE
# ==========================================================================
class ToggleRow(QWidget):
    def __init__(self, checked, parent=None):
        super().__init__(parent)
        lay = hbox((0, 6, 0, 6), 14, self)
        self.sw = Switch(checked)
        lay.addWidget(self.sw, 0, Qt.AlignmentFlag.AlignTop)
        col = vbox(spacing=1)
        self.name = Label("", 13, 600)
        self.desc = Label("", 12, 400, T.MUTED, wrap=True)
        self.warn = Label("", 11, 500, T.WARN)
        self.warn.hide()
        col.addWidget(self.name)
        col.addWidget(self.desc)
        col.addWidget(self.warn)
        lay.addLayout(col, 1)


class OptimizePage(Page):
    key = "optimize"

    def __init__(self, ctx):
        super().__init__(ctx)
        c = QWidget()
        root = vbox((0, 0, 8, 0), 16, c)

        # --- performance mods
        self.g1 = Glass(18)
        l1 = vbox((24, 20, 24, 20), 6, self.g1)
        head = hbox(spacing=12)
        hc = vbox(spacing=2)
        self.t1 = Label("", 16, 650)
        self.s1 = Label("", 12, 400, T.MUTED)
        hc.addWidget(self.t1)
        hc.addWidget(self.s1)
        head.addLayout(hc, 1)
        self.apply = Btn("", "zap", "primary")
        head.addWidget(self.apply)
        l1.addLayout(head)
        l1.addSpacing(8)
        l1.addWidget(Sep())
        self.mod_rows = {}
        self.mod_box = vbox((0, 0, 0, 0), 0)
        l1.addLayout(self.mod_box)
        self.vanilla_note = Label("", 13, 400, T.MUTED, wrap=True)
        l1.addWidget(self.vanilla_note)
        self.rebuild_mods()
        self.progress = Progress()
        l1.addSpacing(6)
        l1.addWidget(self.progress)
        root.addWidget(self.g1)

        # --- platform tweaks (Linux / Windows)
        self.g2 = Glass(18)
        l2 = vbox((24, 20, 24, 20), 8, self.g2)
        self.t2 = Label("", 16, 650)
        self.s2 = Label("", 12, 400, T.MUTED)
        l2.addWidget(self.t2)
        l2.addWidget(self.s2)
        self.chips = hbox(spacing=8)
        self.chip_labels = []
        for _ in range(4):
            lb = Label("", 12, 500, T.TEXT)
            lb.setStyleSheet(f"color:{T.TEXT}; font-size:12px; font-weight:500; background:rgba(255,255,255,0.06);"
                             "border:1px solid rgba(255,255,255,0.08); border-radius:11px; padding:4px 11px;")
            self.chip_labels.append(lb)
            self.chips.addWidget(lb)
        self.chips.addStretch(1)
        l2.addSpacing(4)
        l2.addLayout(self.chips)
        l2.addSpacing(6)
        l2.addWidget(Sep())
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(36)
        self.grid.setVerticalSpacing(2)
        self.tweak_rows = {}
        for i, (key, lk, default, need) in enumerate(core.PLATFORM_TWEAKS):
            r = ToggleRow(bool(ctx.cfg.get(key, default)))
            r.sw.toggled.connect(lambda on, k=key: self._tweak(k, on))
            self.tweak_rows[key] = (r, lk, need)
            self.grid.addWidget(r, i // 2, i % 2)
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 1)
        l2.addLayout(self.grid)
        brow = hbox(spacing=10)
        self.rescan = Btn("", "refresh-cw", "ghost", "md")
        self.tools = Btn("", "download", "ghost", "md")
        brow.addWidget(self.rescan)
        brow.addWidget(self.tools)
        brow.addStretch(1)
        l2.addSpacing(6)
        l2.addLayout(brow)
        root.addWidget(self.g2)
        root.addStretch(1)
        scroll_page(self, c)

        self.apply.clicked.connect(self._apply)
        self.rescan.clicked.connect(self.refresh_hw)
        self.tools.clicked.connect(ctx.ctl.install_gaming_tools)
        osinfo = core.detect_os()
        self.tools.setVisible(not core.IS_WINDOWS and osinfo.get("pkg_manager") in core.GAMING_PACKAGES
                              and not osinfo.get("immutable"))
        self.retranslate()

    def rebuild_mods(self):
        """The optimization mod list depends on the selected loader."""
        while self.mod_box.count():
            w = self.mod_box.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self.mod_rows = {}
        slugs = core.optimization_mods(self.ctx.ctl.loader)
        for slug in slugs:
            r = ToggleRow(True)
            r.name.setText(slug)
            self.mod_rows[slug] = r
            self.mod_box.addWidget(r)
        self.vanilla_note.setVisible(not slugs)
        self.apply.setEnabled(bool(slugs))
        if hasattr(self, "t1"):
            self.retranslate_mods()

    def retranslate_mods(self):
        for slug, r in self.mod_rows.items():
            r.desc.setText(self.tr_(f"mod_{slug}"))
        self.vanilla_note.setText(self.tr_("opt_vanilla"))

    def _tweak(self, key, on):
        self.ctx.cfg[key] = bool(on)
        self.ctx.ctl.save()
        if core.IS_WINDOWS:
            self.ctx.ctl.set_win_tweak(key, bool(on))

    def _apply(self):
        slugs = [s for s, r in self.mod_rows.items() if r.sw.isChecked()]
        if slugs:
            self.ctx.ctl.apply_optimization(slugs)

    def set_busy(self, busy):
        self.apply.setBusy(busy)
        self.apply.setEnabled(not busy)
        self.apply.setText(self.tr_("opt_running" if busy else "opt_apply"))

    def retranslate(self):
        t = self.tr_
        self.t1.setText(t("opt_mods_title"))
        self.s1.setText(t("opt_mods_sub"))
        self.apply.setText(t("opt_apply"))
        self.retranslate_mods()
        self.t2.setText(t("lin_title"))
        self.s2.setText(t("lin_sub"))
        self.rescan.setText(t("btn_rescan"))
        self.tools.setText(t("btn_install_tools"))
        for key, (r, lk, need) in self.tweak_rows.items():
            r.name.setText(t(lk))
            r.desc.setText(t(lk + "_d"))
        self.refresh_hw()

    def refresh_hw(self):
        if core.IS_WINDOWS:
            core.winsys.invalidate_power_cache()
        hw = core.hw_summary()
        vals = [f"GPU  {hw['gpu']}", hw["session"].upper(), f"CPU  {hw['cores']}c · {hw['gov']}",
                f"RAM  {hw['ram'] / 1024:.1f} GB"]
        for lb, v in zip(self.chip_labels, vals):
            lb.setText(v)
        for key, (r, lk, need) in self.tweak_rows.items():
            if need and not shutil.which(need):
                r.warn.setText(self.tr_("missing_cmd", cmd=need))
                r.warn.show()
            else:
                r.warn.hide()


# ==========================================================================
# CONSOLE
# ==========================================================================
class ConsolePage(Page):
    key = "console"
    LEVEL_COL = {"info": "#c6ccd8", "ok": T.OK, "warn": T.WARN, "error": T.ERR,
                 "dim": T.FAINT, "game": "#98a1b1"}

    def __init__(self, ctx):
        super().__init__(ctx)
        lay = vbox((0, 0, 0, 0), 12, self)
        bar = hbox(spacing=8)
        self.b_clear = Btn("", "trash-2", "ghost", "sm")
        self.b_save = Btn("", "save", "ghost", "sm")
        self.b_copy = Btn("", "copy", "ghost", "sm")
        self.b_logs = Btn("", "folder-open", "ghost", "sm")
        for b in (self.b_clear, self.b_save, self.b_copy, self.b_logs):
            bar.addWidget(b)
        bar.addStretch(1)
        lay.addLayout(bar)
        panel = Glass(16)
        pl = vbox((10, 10, 4, 10), 0, panel)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(4000)      # console memory cap
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.view.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.view.viewport().setAutoFillBackground(False)
        pl.addWidget(self.view)
        lay.addWidget(panel, 1)

        self._queue: list = []
        self._flush = QTimer(self)
        self._flush.setInterval(60)
        self._flush.timeout.connect(self._do_flush)
        self._fmt_cache = {}

        self.b_clear.clicked.connect(self.view.clear)
        self.b_save.clicked.connect(self._save)
        self.b_copy.clicked.connect(self._copy)
        self.b_logs.clicked.connect(lambda: (ERROR_LOG_DIR.mkdir(parents=True, exist_ok=True), open_path(ERROR_LOG_DIR)))
        self.retranslate()

    def retranslate(self):
        t = self.tr_
        self.b_clear.setText(t("btn_clear"))
        self.b_save.setText(t("btn_save_log"))
        self.b_copy.setText(t("btn_copy"))
        self.b_logs.setText(t("btn_open_logs"))

    def append(self, text, level="info"):
        self._queue.append((time.time(), text, level))
        if len(self._queue) > 6000:         # guard against overflow when a game spams the log
            del self._queue[:2000]
        if not self._flush.isActive():
            self._flush.start()

    def _fmt(self, color):
        f = self._fmt_cache.get(color)
        if f is None:
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            self._fmt_cache[color] = f
        return f

    def _do_flush(self):
        if not self._queue:
            self._flush.stop()
            return
        batch, self._queue = self._queue[:400], self._queue[400:]
        sb = self.view.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum() - 4
        cur = QTextCursor(self.view.document())
        cur.movePosition(QTextCursor.MoveOperation.End)
        cur.beginEditBlock()
        for ts, text, level in batch:
            col = self.LEVEL_COL.get(level, "#c6ccd8")
            if level == "game":
                up = text[:200]
                if "ERROR" in up or "Exception" in up or "FATAL" in up:
                    col = T.ERR
                elif "WARN" in up:
                    col = T.WARN
            stamp = datetime.fromtimestamp(ts).strftime("%H:%M:%S")
            cur.insertText(stamp + "  ", self._fmt(T.FAINT))
            cur.insertText(text + "\n", self._fmt(col))
        cur.endEditBlock()
        if at_bottom:
            sb.setValue(sb.maximum())

    def _save(self):
        GAME = Path.home() / "arch-client-log.txt"
        path, _ = QFileDialog.getSaveFileName(self, self.tr_("btn_save_log"), str(GAME), "Text (*.txt)")
        if path:
            try:
                Path(path).write_text(self.view.toPlainText(), encoding="utf-8")
                self.ctx.toast(self.tr_("log_saved", path=path), "ok")
            except OSError as e:
                self.ctx.toast(str(e), "error")

    def _copy(self):
        QApplication.clipboard().setText(self.view.toPlainText())
        self.ctx.toast(self.tr_("log_copied"), "ok")


# ==========================================================================
# SETTINGS
# ==========================================================================
class SettingRow(QWidget):
    def __init__(self, control: QWidget, vertical=False, stretch=False, parent=None):
        super().__init__(parent)
        lay = hbox((0, 8, 0, 8), 18, self) if not vertical else vbox((0, 8, 0, 8), 8, self)
        col = vbox(spacing=2)
        self.name = Label("", 13, 600)
        self.desc = Label("", 12, 400, T.MUTED, wrap=True)
        self.desc.hide()
        col.addWidget(self.name)
        col.addWidget(self.desc)
        lay.addLayout(col, 1 if not vertical else 0)
        if stretch and not vertical:
            lay.addWidget(control, 2)
        else:
            lay.addWidget(control, 0, Qt.AlignmentFlag.AlignRight if not vertical else Qt.AlignmentFlag.AlignLeft)
        self.control = control

    def set(self, name, desc=None):
        self.name.setText(name)
        if desc:
            self.desc.setText(desc)
            self.desc.show()
        else:
            self.desc.hide()


class Section(Glass):
    def __init__(self):
        super().__init__(18)
        self.lay = vbox((24, 18, 24, 14), 0, self)
        self.title = Label("", 15, 650)
        self.lay.addWidget(self.title)
        self.lay.addSpacing(6)

    def add(self, w):
        if self.lay.count() > 2:
            self.lay.addWidget(Sep())
        self.lay.addWidget(w)


class SettingsPage(Page):
    key = "settings"

    def __init__(self, ctx):
        super().__init__(ctx)
        cfg = ctx.cfg
        c = QWidget()
        root = vbox((0, 0, 8, 0), 16, c)
        self._save_t = QTimer(self)
        self._save_t.setSingleShot(True)
        self._save_t.setInterval(350)
        self._save_t.timeout.connect(self._flush_save)

        # --- chung
        self.s_gen = Section()
        self.lang = Segmented([("auto", "Auto"), ("vi", "Tiếng Việt"), ("en", "English")], cfg.get("lang", "auto"))
        self.r_lang = SettingRow(self.lang)
        self.ver = Select()
        self.ver.addItems(core.list_mc_versions_offline(ctx.ctl.mc_version))
        self.ver.setCurrentText(ctx.ctl.mc_version)
        self.ver.setFixedWidth(170)
        self.r_ver = SettingRow(self.ver)
        self.ver_kind = Segmented([("release", "Release"), ("snapshot", "+ Snapshot"), ("all", "All")],
                                  cfg.get("ver_kind", "release") if cfg.get("ver_kind") in core.VERSION_KINDS else "release")
        self.r_kind = SettingRow(self.ver_kind)
        self.sw_isolate = Switch(bool(cfg.get("isolate", False)))
        self.r_isolate = SettingRow(self.sw_isolate)
        for r in (self.r_lang, self.r_ver, self.r_kind, self.r_isolate):
            self.s_gen.add(r)
        root.addWidget(self.s_gen)

        # --- java
        self.s_java = Section()
        jbox = QWidget()
        jl = hbox(spacing=8, parent=jbox)
        self.java_path = QLineEdit(cfg.get("java_path", "java"))
        self.btn_jbrowse = Btn("", "folder-open", "ghost")
        jl.addWidget(self.java_path, 1)
        jl.addWidget(self.btn_jbrowse)
        self.r_jpath = SettingRow(jbox, stretch=True)
        self.java_major = Select()
        self.java_major.addItems(core.JAVA_VERSION_CHOICES)
        self.java_major.setCurrentText(str(cfg.get("java_major", 21)))
        self.java_major.setFixedWidth(100)
        self.r_jmajor = SettingRow(self.java_major)
        jw = QWidget()
        jwl = hbox(spacing=12, parent=jw)
        self.java_status = Label("", 12, 500, T.MUTED)
        self.btn_jinstall = Btn("", "refresh-cw", "ghost")
        jwl.addWidget(self.java_status)
        jwl.addWidget(self.btn_jinstall)
        self.r_jinst = SettingRow(jw)
        for r in (self.r_jpath, self.r_jmajor, self.r_jinst):
            self.s_java.add(r)
        root.addWidget(self.s_java)

        # --- memory
        self.s_mem = Section()
        total = core.detect_total_ram_mb() or 8192
        self.ram_max = max(2048, min(total, 32768))
        mw = QWidget()
        ml = hbox(spacing=14, parent=mw)
        self.ram = QSlider(Qt.Orientation.Horizontal)
        self.ram.setRange(1024, self.ram_max)
        self.ram.setSingleStep(512)
        self.ram.setPageStep(512)
        self.ram.setValue(int(cfg.get("ram_mb", 3072)))
        self.ram.setMinimumWidth(240)
        self.ram_lbl = Label("", 14, 650)
        self.ram_lbl.setFixedWidth(64)
        ml.addWidget(self.ram, 1)
        ml.addWidget(self.ram_lbl)
        self.r_ram = SettingRow(mw, stretch=True)
        self.s_mem.add(self.r_ram)
        root.addWidget(self.s_mem)

        # --- accounts
        self.s_acc = Section()
        self.acc_box = QWidget()
        self.acc_lay = vbox((0, 0, 0, 0), 0, self.acc_box)
        self.s_acc.add(self.acc_box)
        nw = QWidget()
        nl = hbox(spacing=8, parent=nw)
        self.username = QLineEdit()          # name for a new offline account
        self.username.setMaxLength(16)
        self.username.setMinimumWidth(180)
        self.btn_add = Btn("", "user", "ghost")
        nl.addWidget(self.username, 1)
        nl.addWidget(self.btn_add)
        self.r_user = SettingRow(nw, stretch=True)
        cw = QWidget()
        cl = hbox(spacing=8, parent=cw)
        self.client_id = QLineEdit(cfg.get("azure_client_id", ""))
        self.client_id.setMinimumWidth(240)
        self.btn_login = Btn("", "user", "ghost")
        cl.addWidget(self.client_id, 1)
        cl.addWidget(self.btn_login)
        self.r_cid = SettingRow(cw, stretch=True)
        for r in (self.r_user, self.r_cid):
            self.s_acc.add(r)
        root.addWidget(self.s_acc)

        # --- interface
        self.s_ui = Section()
        self.sw_sound = Switch(bool(cfg.get("sound", True)))
        self.r_sound = SettingRow(self.sw_sound)
        vw = QWidget()
        vl = hbox(spacing=12, parent=vw)
        self.vol = QSlider(Qt.Orientation.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(int(cfg.get("sound_volume", 60)))
        self.vol.setMinimumWidth(200)
        vl.addWidget(self.vol)
        self.r_vol = SettingRow(vw, stretch=True)
        gw = QWidget()
        gl = hbox(spacing=12, parent=gw)
        self.glass = QSlider(Qt.Orientation.Horizontal)
        self.glass.setRange(55, 100)
        self.glass.setValue(int(cfg.get("glass_opacity", 88)))
        self.glass.setMinimumWidth(200)
        gl.addWidget(self.glass)
        self.r_glass = SettingRow(gw, stretch=True)
        self.sw_anim = Switch(bool(cfg.get("bg_anim", True)))
        self.r_anim = SettingRow(self.sw_anim)
        self.sw_min = Switch(bool(cfg.get("minimize_on_launch", False)))
        self.r_min = SettingRow(self.sw_min)
        for r in (self.r_sound, self.r_vol, self.r_glass, self.r_anim, self.r_min):
            self.s_ui.add(r)
        root.addWidget(self.s_ui)

        # --- shortcut
        self.s_sc = Section()
        sw = QWidget()
        sl = hbox(spacing=10, parent=sw)
        self.sc_status = Label("", 12, 500, T.MUTED)
        self.b_sc_in = Btn("", "download", "ghost")
        self.b_sc_rm = Btn("", "trash-2", "ghost")
        sl.addWidget(self.sc_status)
        sl.addWidget(self.b_sc_in)
        sl.addWidget(self.b_sc_rm)
        self.r_sc = SettingRow(sw)
        self.s_sc.add(self.r_sc)
        root.addWidget(self.s_sc)
        root.addStretch(1)
        scroll_page(self, c)

        # --- connection
        self.lang.changed.connect(self._on_lang)
        self.ver.activated.connect(lambda _i: ctx.window.on_version(self.ver.currentText()))
        self.java_path.editingFinished.connect(self._store)
        self.btn_jbrowse.clicked.connect(self._browse_java)
        self.java_major.activated.connect(lambda _i: self._store())
        self.btn_jinstall.clicked.connect(ctx.ctl.install_java)
        self.ram.valueChanged.connect(self._on_ram)
        self.username.returnPressed.connect(self._add_offline)
        self.btn_add.clicked.connect(self._add_offline)
        self.client_id.editingFinished.connect(self._store)
        self.btn_login.clicked.connect(lambda: ctx.ctl.login_microsoft(self.client_id.text()))
        self.sw_sound.toggled.connect(self._on_sound)
        self.vol.valueChanged.connect(self._on_volume)
        self.vol.sliderReleased.connect(lambda: ctx.play("click"))
        self.glass.valueChanged.connect(self._on_glass)
        self.sw_anim.toggled.connect(self._on_anim)
        self.ver_kind.changed.connect(self._on_kind)
        self.sw_isolate.toggled.connect(self._on_isolate)
        self.sw_min.toggled.connect(lambda on: self._set("minimize_on_launch", bool(on)))
        self.b_sc_in.clicked.connect(ctx.ctl.install_shortcuts)
        self.b_sc_rm.clicked.connect(ctx.ctl.remove_shortcuts)
        self._java = ("", "idle")
        self.retranslate()
        self.refresh_shortcuts()

    # ----- lưu
    def _set(self, key, val):
        self.ctx.cfg[key] = val
        self._save_t.start()

    def _flush_save(self):
        self.ctx.ctl.save()

    def _store(self):
        c = self.ctx.cfg
        c["java_path"] = self.java_path.text().strip() or "java"
        try:
            c["java_major"] = int(self.java_major.currentText())
        except ValueError:
            pass
        c["azure_client_id"] = self.client_id.text().strip()
        self._save_t.start()

    def _add_offline(self):
        if self.ctx.ctl.add_offline_account(self.username.text()):
            self.username.clear()

    def rebuild_accounts(self):
        """Redraw the account list (offline + Microsoft)."""
        ctl, t = self.ctx.ctl, self.tr_
        while self.acc_lay.count():
            w = self.acc_lay.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        active = ctl.cfg.get("active_account")
        for i, a in enumerate(ctl.accounts()):
            if i:
                self.acc_lay.addWidget(Sep())
            row = QWidget()
            lay = hbox((0, 8, 0, 8), 12, row)
            ico = QLabel()
            ico.setPixmap(icon_pixmap("user", T.MUTED, 18, self.devicePixelRatioF()))
            ico.setStyleSheet("background:transparent;")
            lay.addWidget(ico)
            col = vbox(spacing=2)
            col.addWidget(Label(a["name"], 13, 600))
            if a.get("expired"):
                col.addWidget(Label(f"{t('acc_ms')} · {t('acc_relogin')}", 12, 400, T.WARN))
            else:
                col.addWidget(Label(t("acc_ms") if a["type"] == "microsoft" else t("acc_offline"), 12, 400, T.MUTED))
            lay.addLayout(col, 1)
            if a["id"] == active:
                lay.addWidget(Label(t("acc_active"), 12, 600, T.ACCENT))
            else:
                use = Btn(t("acc_use"), None, "ghost", "sm")
                use.clicked.connect(lambda _=False, i=a["id"]: ctl.set_active_account(i))
                lay.addWidget(use)
            rm = Btn("", "trash-2", "subtle", "sm")
            rm.setToolTip(t("acc_remove"))
            rm.clicked.connect(lambda _=False, i=a["id"]: ctl.remove_account(i))
            lay.addWidget(rm)
            self.acc_lay.addWidget(row)

    def set_username(self, name):          # legacy compat: the list updates itself via bus.accounts
        pass

    def set_logged(self, on: bool):
        pass

    def set_version_silent(self, ver):
        self.ver.blockSignals(True)
        if self.ver.findText(ver) < 0:
            self.ver.addItem(ver)
        self.ver.setCurrentText(ver)
        self.ver.blockSignals(False)

    def _browse_java(self):
        start = "/usr/lib/jvm"
        if core.IS_WINDOWS:
            start = next((d for d in (r"C:\Program Files\Eclipse Adoptium", r"C:\Program Files\Java",
                                      str(core.JRE_DIR)) if Path(d).is_dir()), str(Path.home()))
        p, _ = QFileDialog.getOpenFileName(self, self.tr_("set_java_path"), start)
        if p:
            self.java_path.setText(p)
            self._store()

    def _on_lang(self, key):
        self._set("lang", key)
        self.ctx.window.apply_language(key)

    def _on_ram(self, v):
        v = (int(v) // 512) * 512
        self.ram_lbl.setText(f"{v / 1024:.1f} GB")
        self._set("ram_mb", v)
        self.ctx.window.home.refresh()

    def _on_sound(self, on):
        self._set("sound", bool(on))
        self.ctx.sound.enabled = bool(on)
        if on:
            self.ctx.sound.play("click")

    def _on_volume(self, v):
        self._set("sound_volume", int(v))
        self.ctx.sound.set_volume(int(v))

    def _on_glass(self, v):
        self._set("glass_opacity", int(v))
        self.ctx.window.set_glass(int(v))

    def _on_kind(self, k):
        self._set("ver_kind", k)
        self.ctx.window.reload_versions()

    def _on_isolate(self, on):
        self._set("isolate", bool(on))
        self.ctx.window.context_changed()

    def set_versions(self, versions, current):
        self.ver.blockSignals(True)
        self.ver.clear()
        self.ver.addItems(versions)
        self.ver.setCurrentText(current)
        self.ver.blockSignals(False)

    def _on_anim(self, on):
        self._set("bg_anim", bool(on))
        self.ctx.window.set_bg_anim(bool(on))

    # ----- status
    def set_java(self, text, kind):
        self._java = (text, kind)
        col = {"ok": T.OK, "error": T.ERR, "warn": T.WARN, "busy": T.WARN}.get(kind, T.MUTED)
        self.java_status.setText(text)
        self.java_status.setStyleSheet(f"color:{col}; font-size:12px; font-weight:500; background:transparent;")
        self.btn_jinstall.setBusy(kind == "busy")
        self.btn_jinstall.setEnabled(kind != "busy")
        self.java_path.setText(self.ctx.cfg.get("java_path", "java"))

    def refresh_shortcuts(self):
        ok = core.shortcuts_present()
        self.sc_status.setText(self.tr_("sc_installed" if ok else "sc_missing"))
        self.sc_status.setStyleSheet(
            f"color:{T.OK if ok else T.MUTED}; font-size:12px; font-weight:500; background:transparent;")

    def retranslate(self):
        t = self.tr_
        self.s_gen.title.setText(t("set_general"))
        self.r_lang.set(t("set_language"))
        self.lang.set_labels({"auto": t("lang_auto"), "vi": t("lang_vi"), "en": t("lang_en")})
        self.r_ver.set(t("set_version"))
        self.r_kind.set(t("set_ver_kind"), t("ver_kind_d"))
        self.ver_kind.set_labels({"release": t("kind_release"), "snapshot": t("kind_snapshot"), "all": t("kind_all")})
        self.r_isolate.set(t("set_isolate"), t("set_isolate_d"))
        self.s_java.title.setText(t("set_java"))
        self.r_jpath.set(t("set_java_path"))
        self.r_jmajor.set(t("set_java_target"))
        self.r_jinst.set(t("btn_install_java"))
        self.btn_jinstall.setText(t("btn_install_java"))
        self.btn_jbrowse.setText(t("btn_browse"))
        self.s_mem.title.setText(t("set_memory"))
        self.r_ram.set(t("set_ram"), t("ram_hint", n=f"{core.suggest_ram_mb() / 1024:.1f}"))
        self.ram_lbl.setText(f"{(self.ram.value() // 512) * 512 / 1024:.1f} GB")
        self.s_acc.title.setText(t("set_account"))
        self.r_user.set(t("acc_add_offline"), t("acc_add_offline_d"))
        self.username.setPlaceholderText(t("acc_name_ph"))
        self.btn_add.setText(t("btn_add"))
        self.rebuild_accounts()
        self.r_cid.set(t("set_client_id"))
        self.btn_login.setText(t("btn_login"))
        self.s_ui.title.setText(t("set_interface"))
        self.r_sound.set(t("set_sound"))
        self.r_vol.set(t("set_volume"))
        self.r_glass.set(t("set_glass"))
        self.r_anim.set(t("set_bg_anim"))
        self.r_min.set(t("set_minimize"))
        self.s_sc.title.setText(t("set_shortcut"))
        self.r_sc.set(t("set_shortcut"))
        self.b_sc_in.setText(t("btn_sc_install"))
        self.b_sc_rm.setText(t("btn_sc_remove"))
        self.refresh_shortcuts()
        if self._java[0]:
            self.set_java(*self._java)
