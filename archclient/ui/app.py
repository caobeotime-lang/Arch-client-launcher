# -*- coding: utf-8 -*-
"""GUI entry point: creates the QApplication, splash and main window."""
from __future__ import annotations

import ctypes
import os
import sys
import threading

from PyQt6.QtCore import QLockFile, QObject, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from .. import APP_ID, APP_NAME, core
from ..bootstrap import CONFIG_DIR, detect_os, resource_path, write_error_log
from ..controller import Bus, Controller
from ..i18n import detect_language, tr
from ..sound import SoundPlayer
from . import ctx as ctxmod
from .ctx import Ctx
from .theme import build_qss


def x11_has_compositor():
    """True/False when the X server answers whether a compositor runs; None when unknown."""
    try:
        x11 = ctypes.CDLL("libX11.so.6")
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XDefaultScreen.argtypes = [ctypes.c_void_p]
        x11.XInternAtom.restype = ctypes.c_ulong
        x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        x11.XGetSelectionOwner.restype = ctypes.c_ulong
        x11.XGetSelectionOwner.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        d = x11.XOpenDisplay(None)
        if not d:
            return None
        try:
            atom = x11.XInternAtom(d, f"_NET_WM_CM_S{x11.XDefaultScreen(d)}".encode(), 0)
            return x11.XGetSelectionOwner(d, atom) != 0
        finally:
            x11.XCloseDisplay(d)
    except Exception:
        return None


def decide_translucent(cfg, platform_name: str) -> bool:
    mode = str(cfg.get("translucent", "auto")).lower()
    env = os.environ.get("ARCH_TRANSLUCENT", "").lower()
    if env in ("0", "off", "false"):
        return False
    if env in ("1", "on", "true"):
        return True
    if mode in ("off", "false", "0"):
        return False
    if mode in ("on", "true", "1"):
        return True
    if core.IS_WINDOWS:
        return True              # DWM always composites
    if platform_name == "xcb" and os.environ.get("XDG_SESSION_TYPE", "").lower() != "wayland":
        has = x11_has_compositor()
        return True if has is None else bool(has)
    return True


class _Init(QObject):
    done = pyqtSignal(str)


def main(argv=None) -> int:
    argv = list(argv or sys.argv)
    if core.IS_WINDOWS:
        core.winsys.set_app_user_model_id()      # taskbar shows Arch Client's icon + group
    # On real Wayland let Qt choose; never force xcb.
    app = QApplication(argv)
    app.setApplicationName(APP_ID)        # WM_CLASS = arch-client (matches StartupWMClass)
    app.setApplicationDisplayName(APP_NAME)
    app.setDesktopFileName(APP_ID)       # matches arch-client.desktop -> correct icon on taskbar/Wayland
    app.setStyle("Fusion")
    app.setStyleSheet(build_qss())
    icon = resource_path("img/icon.png")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(CONFIG_DIR / "app.lock"))
    lock.setStaleLockTime(30000)
    if not lock.tryLock(150):
        print(tr("vi", "already_running"))
        return 0

    cfg = core.load_config()
    translucent = decide_translucent(cfg, app.platformName())

    from .window import MainWindow, Splash
    splash = Splash(translucent)
    splash.set_status(tr(cfg.get("lang") if cfg.get("lang") in ("vi", "en") else "en", "splash_start"))
    splash.center()
    splash.show()

    init = _Init()

    def work():
        try:
            lang = cfg.get("lang", "auto")
            if lang not in ("vi", "en"):
                lang = cfg.get("lang_detected") if cfg.get("lang_detected") in ("vi", "en") else ""
                if not lang:
                    lang = detect_language(core.requests, 2.5)
                    cfg["lang_detected"] = lang
            core.ensure_minecraft_dir(core.Path(cfg["mc_dir"]))
        except Exception as e:
            write_error_log("Startup", exc=e)
            lang = "en"
        init.done.emit(lang)

    holder = {}

    def start(lang):
        try:
            bus = Bus()
            ctl = Controller(bus, cfg, lang)
            sound = SoundPlayer(cfg.get("sound", True), cfg.get("sound_volume", 60))
            ctx = Ctx(cfg, ctl, bus, sound, lang)
            ctxmod.set_current(ctx)
            win = MainWindow(ctx, translucent)
            holder["win"], holder["ctx"] = win, ctx
            win.show()
            splash.close()
            info = detect_os()
            ctl.log(f"{info.get('pretty')} · {app.platformName()} · Python {sys.version.split()[0]}", "dim")
            if not translucent:
                ctl.log("No compositor detected: translucent background off (set ARCH_TRANSLUCENT=1 to force it on).", "dim")
            QTimer.singleShot(250, ctl.check_java_startup)
            QTimer.singleShot(400, ctl.restore_login)
            QTimer.singleShot(500, win.reload_versions)
            QTimer.singleShot(600, ctl.startup_shortcuts)
            QTimer.singleShot(700, ctl.startup_windows)
            QTimer.singleShot(900, ctl.init_discord)
            QTimer.singleShot(1200, sound.preload)
        except Exception as e:
            write_error_log("Building the interface", exc=e)
            raise

    init.done.connect(lambda lang: QTimer.singleShot(700, lambda: start(lang)))
    splash.set_status(tr("en", "splash_lang"))
    threading.Thread(target=work, name="arch-init", daemon=True).start()
    rc = app.exec()
    lock.unlock()
    return rc
