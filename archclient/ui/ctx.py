# -*- coding: utf-8 -*-
"""Shared context for every widget: config, controller, string translation, sound."""
from __future__ import annotations

from ..i18n import tr


class Ctx:
    def __init__(self, cfg, ctl, bus, sound, lang):
        self.cfg = cfg
        self.ctl = ctl
        self.bus = bus
        self.sound = sound
        self.lang = lang
        self.window = None   # set once the main window exists

    def tr(self, key, **kw):
        return tr(self.lang, key, **kw)

    def play(self, name):
        try:
            self.sound.play(name)
        except Exception:
            pass

    def set_lang(self, lang):
        self.lang = lang
        self.ctl.lang = lang

    def toast(self, text, kind="info"):
        self.bus.toast.emit(text, kind)


# The active Ctx — low-level widgets (buttons, switches...) get their sounds from here.
_current: Ctx | None = None


def set_current(ctx: Ctx) -> None:
    global _current
    _current = ctx


def play(name: str) -> None:
    if _current is not None:
        _current.play(name)
