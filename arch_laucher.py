#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Arch Client — Minecraft launcher cho Linux và Windows.

Chạy:  python3 arch_laucher.py   (Windows: run.bat)
Lần đầu launcher tự cài thư viện còn thiếu (PyQt6, minecraft-launcher-lib, requests).
"""
import os
import sys

if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    if getattr(sys, "frozen", False):
        import multiprocessing
        multiprocessing.freeze_support()
    from archclient.bootstrap import ensure_environment
    ensure_environment()
    from archclient.ui.app import main
    sys.exit(main())
