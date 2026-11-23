#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Arch Client — Minecraft launcher for Linux and Windows.

Run:  python3 arch_laucher.py   (Windows: run.bat)
On first start the launcher installs the missing libraries itself
(PyQt6, minecraft-launcher-lib, requests).
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
