#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_linux.py — package Arch Client for Linux.

Compare with build_windows.py:
  * Windows deals with Defender / SmartScreen flagging .exe files.
  * Linux does not have that problem, but it has another one: glibc. A binary built
    on a newer Arch/Ubuntu will NOT run on distros with an older glibc.
    So build on the oldest distro you want to support
    (Ubuntu 22.04 is the safe baseline — see the linuxbuild.yml workflow).

Three packaging modes:
    python build_linux.py                # onedir + .tar.gz  (RECOMMENDED)
    python build_linux.py --onefile      # a single runnable file
    python build_linux.py --appimage     # .AppImage (runs on any distro)
    python build_linux.py --deb          # .deb (Debian/Ubuntu/Mint); also stages the tree fpm uses for .rpm / .pkg.tar.zst

The tar.gz is ready to run right after extraction and ships an install.sh that creates
the .desktop shortcut in the application menu.
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


def _read_version() -> str:
    """Read the version from archclient/__init__.py so build file names always match the app."""
    try:
        for line in (HERE / "archclient" / "__init__.py").read_text(encoding="utf-8").splitlines():
            if line.startswith("APP_VERSION"):
                return line.split("=", 1)[1].strip().strip("\"'")
    except OSError:
        pass
    return "0"


APP_VERSION = _read_version()
DIST = HERE / "dist"
BUILD = HERE / "build"

REQUIRED_PACKAGES = ["PyQt6", "minecraft-launcher-lib>=8.0", "requests"]
OPTIONAL_PACKAGES = ["pypresence"]
BUILD_TOOLS = ["pyinstaller"]

# Heavy unused modules -> smaller bundle, faster startup.
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
Comment=Multi-loader Minecraft launcher (Vanilla, Fabric, Quilt, Forge, NeoForge) for Linux
Exec={{exec}}
Icon=arch-client
Terminal=false
Categories=Game;ActionGame;
StartupWMClass=arch-client
Keywords=minecraft;fabric;launcher;
"""

INSTALL_SH = """#!/usr/bin/env bash
# Install Arch Client into ~/.local (no sudo needed).
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
Comment=Multi-loader Minecraft launcher (Vanilla, Fabric, Quilt, Forge, NeoForge) for Linux
Exec=$TARGET/ArchClient
Icon=arch-client
Terminal=false
Categories=Game;ActionGame;
StartupWMClass=arch-client
EOF

chmod +x "$APPS/arch-client.desktop" "$TARGET/ArchClient" 2>/dev/null || true
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" || true

echo "✅ Installed. Open it from the application menu or run: arch-client"
echo "   (if the command is not found yet, add ~/.local/bin to your PATH)"
"""


def run(cmd, check=True, **kw):
    print("  $ " + " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, check=check, **kw)


def ensure_tools():
    print("⏳ Checking build dependencies...")
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
    print(f"📦 Packing {out.name}...")
    with tarfile.open(out, "w:gz") as tar:
        tar.add(src_dir, arcname=APP_NAME)
    print(f"✅ {out}  ({out.stat().st_size / 1e6:.1f} MB)")


PKG_NAME = "arch-client"
PKG_DESC = "Minecraft launcher (Vanilla, Fabric, Quilt, Forge, NeoForge) for Linux"


def stage_package_root(onedir: Path) -> Path:
    """Stage a system-style tree (/opt, /usr/bin, menu, icon) shared by the .deb / .rpm / Arch package."""
    root = BUILD / "pkgroot"
    if root.exists():
        shutil.rmtree(root)
    opt = root / "opt" / PKG_NAME
    opt.parent.mkdir(parents=True)
    shutil.copytree(onedir, opt, symlinks=True)
    (opt / "install.sh").unlink(missing_ok=True)      # only for the tar.gz build
    (root / "usr" / "bin").mkdir(parents=True)
    (root / "usr" / "bin" / PKG_NAME).symlink_to(f"/opt/{PKG_NAME}/{APP_NAME}")
    apps = root / "usr" / "share" / "applications"
    apps.mkdir(parents=True)
    (apps / f"{PKG_NAME}.desktop").write_text(
        DESKTOP_ENTRY.format(exec=PKG_NAME), encoding="utf-8")
    icon = IMG_DIR / "icon.png"
    if icon.exists():
        icons = root / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps"
        icons.mkdir(parents=True)
        shutil.copy(icon, icons / f"{PKG_NAME}.png")
    return root


def make_deb(onedir: Path) -> Path:
    root = stage_package_root(onedir)
    debroot = BUILD / "debroot"
    if debroot.exists():
        shutil.rmtree(debroot)
    shutil.copytree(root, debroot, symlinks=True)
    ctl = debroot / "DEBIAN"
    ctl.mkdir()
    size_kb = sum(f.stat().st_size for f in root.rglob("*") if f.is_file()) // 1024
    (ctl / "control").write_text(
        f"Package: {PKG_NAME}\n"
        f"Version: {APP_VERSION}\n"
        "Section: games\n"
        "Priority: optional\n"
        "Architecture: amd64\n"
        f"Installed-Size: {size_kb}\n"
        "Maintainer: Arch Client <noreply@archclient.netlify.app>\n"
        "Depends: libc6 (>= 2.35), libgl1, libegl1\n"
        "Recommends: libxcb-cursor0, libxkbcommon-x11-0, libxcb-icccm4, libxcb-keysyms1, "
        "libxcb-image0, libxcb-render-util0, libxcb-shape0\n"
        f"Description: {PKG_DESC}\n"
        " Installs the right Java per Minecraft version and mods from Modrinth.\n",
        encoding="utf-8")
    (ctl / "postinst").write_text(
        "#!/bin/sh\nset -e\n"
        "command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true\n"
        "command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -f -t /usr/share/icons/hicolor || true\n"
        "exit 0\n", encoding="utf-8")
    os.chmod(ctl / "postinst", 0o755)
    DIST.mkdir(exist_ok=True)
    out = DIST / f"{APP_NAME}-{APP_VERSION}-amd64.deb"
    run(["dpkg-deb", "--build", "--root-owner-group", str(debroot), str(out)])
    print(f"✅ {out}")
    return out


def make_appimage(onedir: Path):
    appdir = BUILD / f"{APP_NAME}.AppDir"
    if appdir.exists():
        shutil.rmtree(appdir)
    (appdir / "usr" / "bin").mkdir(parents=True)
    (appdir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps").mkdir(parents=True)

    shutil.copytree(onedir, appdir / "usr" / "bin", dirs_exist_ok=True)
    # AppRun sets APPDIR = the AppDir root, and the launcher looks for img/ right next to APPDIR
    # -> place a copy of img/ at the root, not only inside usr/bin.
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
        print("⏳ Downloading appimagetool...")
        urllib.request.urlretrieve(APPIMAGETOOL_URL, tool)
        os.chmod(tool, 0o755)

    out = DIST / f"{APP_NAME}-{APP_VERSION}-x86_64.AppImage"
    env = dict(os.environ, ARCH="x86_64")
    try:
        run([str(tool), str(appdir), str(out)], env=env)
    except Exception:
        # CI/container environments usually lack FUSE -> run in extract-and-run mode.
        run([str(tool), "--appimage-extract-and-run", str(appdir), str(out)], env=env)
    print(f"✅ {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--onefile", action="store_true", help="build a single runnable file")
    ap.add_argument("--appimage", action="store_true", help="also build an .AppImage")
    ap.add_argument("--deb", action="store_true", help="also build a .deb and stage build/pkgroot (for fpm)")
    ap.add_argument("--skip-deps", action="store_true")
    a = ap.parse_args()

    if not MAIN_SCRIPT.exists():
        sys.exit(f"❌ Missing {MAIN_SCRIPT}")
    if not a.skip_deps:
        ensure_tools()

    for d in (DIST, BUILD):
        if (d / APP_NAME).exists():
            shutil.rmtree(d / APP_NAME, ignore_errors=True)
    run(pyinstaller_args(a.onefile))

    if a.onefile:
        print(f"✅ {DIST / APP_NAME}")
        if a.appimage:
            sys.exit("ℹ --appimage needs the onedir build; drop --onefile and run again.")
        return

    onedir = DIST / APP_NAME
    for d in (IMG_DIR, ASSETS_DIR):
        if d.exists():
            shutil.copytree(d, onedir / d.name, dirs_exist_ok=True)
    make_tarball(onedir, DIST / f"{APP_NAME}-{APP_VERSION}-linux-x86_64.tar.gz")
    if a.appimage:
        make_appimage(onedir)
    if a.deb:
        make_deb(onedir)


if __name__ == "__main__":
    main()
