# -*- coding: utf-8 -*-
"""Ngữ cảnh dùng chung cho mọi widget: cấu hình, controller, dịch chuỗi, âm thanh."""
from __future__ import annotations

from ..i18n import tr


class Ctx:
    def __init__(self, cfg, ctl, bus, sound, lang):
        self.cfg = cfg
        self.ctl = ctl
        self.bus = bus
        self.sound = sound
        self.lang = lang
        self.window = None   # gán sau khi tạo cửa sổ chính

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


# Ctx hiện hành — widget cấp thấp (nút, switch…) lấy âm thanh từ đây.
_current: Ctx | None = None


def set_current(ctx: Ctx) -> None:
    global _current
    _current = ctx


def play(name: str) -> None:
    if _current is not None:
        _current.play(name)
