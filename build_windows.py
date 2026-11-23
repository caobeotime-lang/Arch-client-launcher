# -*- coding: utf-8 -*-
"""
build_windows.py — đóng gói Arch Client thành ArchClient.exe cho Windows 10/11 (64-bit).

    python build_windows.py             # thư mục ArchClient\\ + file .zip  (KHUYÊN DÙNG)
    python build_windows.py --onefile   # 1 file .exe duy nhất (khởi động chậm hơn vài giây)

Vì sao mặc định là onedir:
  * onefile tự giải nén vào %TEMP% mỗi lần mở -> chậm và hay bị Windows Defender / SmartScreen chặn.
  * onedir mở nhanh hơn và ít bị gắn cờ hơn.
Không có chữ ký số nên lần đầu SmartScreen có thể hiện "Windows protected your PC":
bấm "More info" -> "Run anyway". Muốn hết hẳn cảnh báo phải mua chứng chỉ code-signing.

Chạy trên Windows (PyInstaller không build chéo từ Linux/macOS).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAIN_SCRIPT = HERE / "arch_laucher.py"
IMG_DIR = HERE / "img"
ASSETS_DIR = HERE / "assets"
ICON = IMG_DIR / "icon.ico"
APP_NAME = "ArchClient"
DIST = HERE / "dist"

REQUIRED = ["PyQt6", "minecraft-launcher-lib>=8.0", "requests", "pypresence", "pyinstaller"]

EXCLUDES = [
    "matplotlib", "numpy", "scipy", "pandas", "pytest", "IPython", "notebook",
    "PyQt5", "PySide2", "PySide6", "tkinter", "test", "unittest", "pydoc_data",
    "PyQt6.QtWebEngineCore", "PyQt6.QtWebEngineWidgets", "PyQt6.QtQml", "PyQt6.QtQuick",
    "PyQt6.QtPdf", "PyQt6.Qt3DCore", "PyQt6.QtBluetooth", "PyQt6.QtSql", "PyQt6.QtTest",
]


def run(cmd, check=True):
    print("  $ " + " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, check=check)


def version() -> str:
    for line in (HERE / "archclient" / "__init__.py").read_text(encoding="utf-8").splitlines():
        if line.startswith("APP_VERSION"):
            return line.split("=", 1)[1].strip().strip("\"'")
    return "0"


def ensure_icon() -> None:
    """Tạo img/icon.ico từ icon.png nếu chưa có (cần PyQt6)."""
    if ICON.exists():
        return
    sys.path.insert(0, str(HERE))
    from archclient import winsys
    if not winsys.make_ico(ICON, IMG_DIR / "icon.png"):
        print("! Không tạo được icon.ico — exe sẽ dùng icon mặc định.")


def pyinstaller_args(onefile: bool) -> list:
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
            "--name", APP_NAME,
            "--add-data", f"{IMG_DIR}{os.pathsep}img",
            "--add-data", f"{ASSETS_DIR}{os.pathsep}assets",
            "--hidden-import", "PyQt6.QtSvg", "--hidden-import", "PyQt6.QtMultimedia",
            "--hidden-import", "winreg", "--hidden-import", "winsound",
            "--noupx"]
    if ICON.exists():
        args += ["--icon", str(ICON)]
    for mod in EXCLUDES:
        args += ["--exclude-module", mod]
    args += ["--onefile" if onefile else "--onedir", str(MAIN_SCRIPT)]
    return args


def make_zip(src: Path, out: Path) -> None:
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in sorted(src.rglob("*")):
            if f.is_file():
                z.write(f, Path(APP_NAME) / f.relative_to(src))
    print(f"OK {out}  ({out.stat().st_size / 1e6:.1f} MB)")


def main() -> None:
    if sys.platform != "win32":
        sys.exit("build_windows.py phải chạy trên Windows (PyInstaller không build chéo).")
    ap = argparse.ArgumentParser()
    ap.add_argument("--onefile", action="store_true")
    ap.add_argument("--skip-deps", action="store_true")
    a = ap.parse_args()
    if not a.skip_deps:
        run([sys.executable, "-m", "pip", "install", "--upgrade", *REQUIRED])
    ensure_icon()
    shutil.rmtree(DIST / APP_NAME, ignore_errors=True)
    run(pyinstaller_args(a.onefile))
    if a.onefile:
        print(f"OK {DIST / (APP_NAME + '.exe')}")
        return
    onedir = DIST / APP_NAME
    for d in (IMG_DIR, ASSETS_DIR):          # để resource_path tìm thấy cả cạnh file exe
        shutil.copytree(d, onedir / d.name, dirs_exist_ok=True)
    if not (onedir / f"{APP_NAME}.exe").exists():
        sys.exit("Build xong nhưng không thấy ArchClient.exe")
    make_zip(onedir, DIST / f"{APP_NAME}-{version()}-windows-x64.zip")


if __name__ == "__main__":
    main()
