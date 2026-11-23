#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_linux.py — đóng gói Arch Client cho Linux.

Đối chiếu với build_windows.py:
  * Windows lo chuyện Defender / SmartScreen gắn cờ .exe.
  * Linux không có vấn đề đó, nhưng có vấn đề khác: glibc. Một file build
    trên Arch/Ubuntu mới sẽ KHÔNG chạy được trên distro có glibc cũ hơn.
    Vì vậy nên build trên distro cũ nhất mà bạn muốn hỗ trợ
    (Ubuntu 22.04 là mốc an toàn — xem workflow linuxbuild.yml).

Ba kiểu đóng gói:
    python build_linux.py                # onedir + .tar.gz  (KHUYÊN DÙNG)
    python build_linux.py --onefile      # 1 file chạy duy nhất
    python build_linux.py --appimage     # .AppImage (chạy trên mọi distro)

Bản tar.gz giải nén ra là chạy được ngay, kèm sẵn install.sh để tạo
shortcut .desktop trong menu ứng dụng.
"""
from __future__ import annotations

import os
import sys
import shutil
import tarfile
import argparse
import subprocess
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAIN_SCRIPT = HERE / "arch_laucher.py"
IMG_DIR = HERE / "img"
ASSETS_DIR = HERE / "assets"
APP_NAME = "ArchClient"
APP_VERSION = "1.0.0"
DIST = HERE / "dist"
BUILD = HERE / "build"

REQUIRED_PACKAGES = ["PyQt6", "minecraft-launcher-lib>=8.0", "requests"]
OPTIONAL_PACKAGES = ["pypresence"]
BUILD_TOOLS = ["pyinstaller"]

# Module nặng không dùng tới -> gói nhỏ hơn, khởi động nhanh hơn.
EXCLUDES = [
    "matplotlib", "numpy", "scipy", "pandas", "pytest", "IPython", "notebook",
    "PyQt5", "PySide2", "PySide6", "tkinter", "test", "unittest", "pydoc_data",
    "PyQt6.QtWebEngineCore", "PyQt6.QtWebEngineWidgets", "PyQt6.QtQml", "PyQt6.QtQuick",
    "PyQt6.QtPdf", "PyQt6.Qt3DCore", "PyQt6.QtBluetooth", "PyQt6.QtSql", "PyQt6.QtTest",
]

APPIMAGETOOL_URL = (
    "https://github.com/AppImage/AppImageKit/releases/download/continuous/"
    "appimagetool-x86_64.AppImage"
)

DESKTOP_ENTRY = f"""[Desktop Entry]
Type=Application
Name=Arch Client
GenericName=Minecraft Launcher
Comment=Launcher Minecraft Fabric tối ưu FPS cho Linux
Exec={{exec}}
Icon=arch-client
Terminal=false
Categories=Game;ActionGame;
StartupWMClass=arch-client
Keywords=minecraft;fabric;launcher;
"""

INSTALL_SH = """#!/usr/bin/env bash
# Cài Arch Client vào ~/.local (không cần sudo).
set -e
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$HOME/.local/share/arch-client"
BIN="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor/256x256/apps"

mkdir -p "$TARGET" "$BIN" "$APPS" "$ICONS"
cp -r "$HERE/." "$TARGET/"
ln -sf "$TARGET/ArchClient" "$BIN/arch-client"
[ -f "$TARGET/img/icon.png" ] && cp "$TARGET/img/icon.png" "$ICONS/arch-client.png"

cat > "$APPS/arch-client.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Arch Client
Comment=Launcher Minecraft Fabric tối ưu FPS cho Linux
Exec=$TARGET/ArchClient
Icon=arch-client
Terminal=false
Categories=Game;ActionGame;
StartupWMClass=arch-client
EOF

chmod +x "$APPS/arch-client.desktop" "$TARGET/ArchClient" 2>/dev/null || true
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" || true

echo "✅ Đã cài xong. Mở bằng menu ứng dụng hoặc lệnh: arch-client"
echo "   (nếu lệnh chưa chạy được, thêm ~/.local/bin vào PATH)"
"""


def run(cmd, check=True, **kw):
    print("  $ " + " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, check=check, **kw)


def ensure_tools():
    print("⏳ Kiểm tra thư viện build...")
    missing = []
    for mod, pkg in [("PyQt6", "PyQt6"),
                     ("minecraft_launcher_lib", "minecraft-launcher-lib"),
                     ("requests", "requests"),
                     ("PyInstaller", "pyinstaller")]:
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if missing:
        run([sys.executable, "-m", "pip", "install", *missing, "--break-system-packages"],
            check=False)
        run([sys.executable, "-m", "pip", "install", *missing], check=False)
    for pkg in OPTIONAL_PACKAGES:
        run([sys.executable, "-m", "pip", "install", pkg], check=False)


def pyinstaller_args(onefile: bool) -> list:
    args = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--windowed", "--name", APP_NAME,
        "--add-data", f"{IMG_DIR}{os.pathsep}img",
        "--add-data", f"{ASSETS_DIR}{os.pathsep}assets",
        "--hidden-import", "PyQt6.QtSvg",
        "--hidden-import", "PyQt6.QtMultimedia",
        "--noupx",
    ]
    for mod in EXCLUDES:
        args += ["--exclude-module", mod]
    args += ["--onefile" if onefile else "--onedir", str(MAIN_SCRIPT)]
    return args


def make_tarball(src_dir: Path, out: Path):
    (src_dir / "install.sh").write_text(INSTALL_SH, encoding="utf-8")
    os.chmod(src_dir / "install.sh", 0o755)
    print(f"📦 Đóng gói {out.name}...")
    with tarfile.open(out, "w:gz") as tar:
        tar.add(src_dir, arcname=APP_NAME)
    print(f"✅ {out}  ({out.stat().st_size / 1e6:.1f} MB)")


def make_appimage(onedir: Path):
    appdir = BUILD / f"{APP_NAME}.AppDir"
    if appdir.exists():
        shutil.rmtree(appdir)
    (appdir / "usr" / "bin").mkdir(parents=True)
    (appdir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps").mkdir(parents=True)

    shutil.copytree(onedir, appdir / "usr" / "bin", dirs_exist_ok=True)
    # AppRun đặt APPDIR = gốc AppDir, mà launcher tìm img/ ngay cạnh APPDIR
    # -> phải đặt một bản img/ ở gốc, không chỉ trong usr/bin.
    for d in (IMG_DIR, ASSETS_DIR):
        if d.exists():
            shutil.copytree(d, appdir / d.name, dirs_exist_ok=True)
    icon = IMG_DIR / "icon.png"
    if icon.exists():
        shutil.copy(icon, appdir / "arch-client.png")
        shutil.copy(icon, appdir / "usr" / "share" / "icons" / "hicolor"
                    / "256x256" / "apps" / "arch-client.png")

    (appdir / "arch-client.desktop").write_text(
        DESKTOP_ENTRY.format(exec="AppRun"), encoding="utf-8")
    apprun = appdir / "AppRun"
    apprun.write_text(
        "#!/bin/sh\n"
        'HERE="$(dirname "$(readlink -f "$0")")"\n'
        'export APPDIR="$HERE"\n'
        f'exec "$HERE/usr/bin/{APP_NAME}" "$@"\n',
        encoding="utf-8")
    os.chmod(apprun, 0o755)

    tool = BUILD / "appimagetool.AppImage"
    if not tool.exists():
        print("⏳ Tải appimagetool...")
        urllib.request.urlretrieve(APPIMAGETOOL_URL, tool)
        os.chmod(tool, 0o755)

    out = DIST / f"{APP_NAME}-{APP_VERSION}-x86_64.AppImage"
    env = dict(os.environ, ARCH="x86_64")
    try:
        run([str(tool), str(appdir), str(out)], env=env)
    except Exception:
        # Môi trường CI/container thường không có FUSE -> chạy kiểu giải nén.
        run([str(tool), "--appimage-extract-and-run", str(appdir), str(out)], env=env)
    print(f"✅ {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--onefile", action="store_true", help="1 file chạy duy nhất")
    ap.add_argument("--appimage", action="store_true", help="xuất thêm .AppImage")
    ap.add_argument("--skip-deps", action="store_true")
    a = ap.parse_args()

    if not MAIN_SCRIPT.exists():
        sys.exit(f"❌ Không thấy {MAIN_SCRIPT}")
    if not a.skip_deps:
        ensure_tools()

    for d in (DIST, BUILD):
        if (d / APP_NAME).exists():
            shutil.rmtree(d / APP_NAME, ignore_errors=True)
    run(pyinstaller_args(a.onefile))

    if a.onefile:
        print(f"✅ {DIST / APP_NAME}")
        if a.appimage:
            sys.exit("ℹ --appimage cần bản onedir, bỏ --onefile rồi chạy lại.")
        return

    onedir = DIST / APP_NAME
    for d in (IMG_DIR, ASSETS_DIR):
        if d.exists():
            shutil.copytree(d, onedir / d.name, dirs_exist_ok=True)
    make_tarball(onedir, DIST / f"{APP_NAME}-{APP_VERSION}-linux-x86_64.tar.gz")
    if a.appimage:
        make_appimage(onedir)


if __name__ == "__main__":
    main()
