#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_windows.py — builds Arch Client for Windows, OPTIMIZED TO AVOID BEING
FLAGGED BY WINDOWS DEFENDER / ANTIVIRUS.

Why the old .exe often triggered Defender's "Trojan:Win32/Wacatac.B!ml":
  1. --onefile: the .exe unpacks tens of MB into %TEMP% and keeps running
     from there. This is exactly what droppers/packers do, so Defender's ML
     heuristics score it very high. This is the #1 cause.
  2. The .exe has NO version resource (company, product, version)
     -> Defender/SmartScreen treat it as "anonymous software" and add
     suspicion points.
  3. UPX compression -> always treated as a packer (already disabled here
     with --noupx).
  4. No code signing -> SmartScreen still warns on first run.

This script handles 1, 2 and 3 automatically:
  * Builds --onedir by default (an ArchClient/ folder containing
    ArchClient.exe + DLLs) and zips it as ArchClient-windows.zip. The onedir
    build is almost NEVER flagged because nothing self-extracts to %TEMP%.
  * Generates version_info.txt (CompanyName / ProductName / FileVersion)
    and embeds it in the .exe via --version-file.
  * Ships a manifest with requestedExecutionLevel = asInvoker (asking for
    admin rights is another Defender red flag).
  * Excludes heavy unused modules -> smaller file, less suspicious.
  * --noupx, --clean.

Problem 4 (code signing) needs a paid certificate; the script can't do that
for you.

Usage:
    python build_windows.py                 # onedir + zip  (RECOMMENDED)
    python build_windows.py --onefile       # single .exe (easier to get flagged)
    python build_windows.py --onefile --sign-self   # onefile + self-signed
"""
from __future__ import annotations

import os
import sys

# The Windows console on GitHub Actions uses a codepage that doesn't understand
# Unicode -> printing emoji/Vietnamese crashes immediately. Force UTF-8 up front.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import shutil
import zipfile
import argparse
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAIN_SCRIPT = HERE / "arch_laucher.py"
APP_NAME = "ArchClient"

# Metadata embedded in the .exe — the more complete, the lower the heuristic score.
APP_VERSION = "1.3.0"  # Beta 1.3
COMPANY_NAME = "Arch Client"
PRODUCT_NAME = "Arch Client Launcher"
FILE_DESC = "Arch Client - Minecraft Fabric Launcher"
COPYRIGHT = "Free for personal, non-commercial use"

REQUIRED_PACKAGES = ["ttkbootstrap", "minecraft-launcher-lib", "requests", "pillow"]
OPTIONAL_PACKAGES = ["pypresence", "tkinterweb", "pywebview"]
BUILD_TOOLS = ["pyinstaller"]

# Large unused modules -> excluded to keep the .exe small and "clean".
EXCLUDES = [
    "matplotlib", "numpy", "scipy", "pandas", "pytest", "IPython",
    "notebook", "PyQt5", "PyQt6", "PySide2", "PySide6", "sqlite3",
    "test", "unittest", "pydoc_data", "distutils",
]


def run(cmd, check=True):
    print("  $ " + " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, check=check)


def pip_install(packages, required=True):
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade"] + packages
    try:
        run(cmd)
    except subprocess.CalledProcessError:
        if required:
            raise
        print(f"  ⚠ Skipping optional package(s) that failed to install: {packages}")


def ensure_icon() -> str | None:
    """PyInstaller --icon needs a .ico; if only icon.png exists, convert it with Pillow."""
    ico_path = HERE / "img" / "icon.ico"
    png_path = HERE / "img" / "icon.png"
    if ico_path.exists():
        return str(ico_path)
    if not png_path.exists():
        return None
    try:
        from PIL import Image
        img = Image.open(png_path).convert("RGBA")
        img.save(ico_path, format="ICO",
                 sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        return str(ico_path)
    except Exception as e:
        print(f"  ⚠ Could not create icon.ico ({e}) — continuing the build.")
        return None


def write_version_file() -> Path:
    """Generate the version resource for the .exe.

    An .exe without metadata is treated by Defender as anonymous software and
    gets extra heuristic points. With full CompanyName/ProductName/FileVersion
    the flag rate drops noticeably (and SmartScreen shows the product name
    instead of 'Unknown Publisher').
    """
    parts = (APP_VERSION.split(".") + ["0", "0", "0", "0"])[:4]
    nums = ", ".join(str(int(p)) for p in parts)
    content = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({nums}),
    prodvers=({nums}),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'040904B0',
        [StringStruct(u'CompanyName', u'{COMPANY_NAME}'),
         StringStruct(u'FileDescription', u'{FILE_DESC}'),
         StringStruct(u'FileVersion', u'{APP_VERSION}'),
         StringStruct(u'InternalName', u'{APP_NAME}'),
         StringStruct(u'LegalCopyright', u'{COPYRIGHT}'),
         StringStruct(u'OriginalFilename', u'{APP_NAME}.exe'),
         StringStruct(u'ProductName', u'{PRODUCT_NAME}'),
         StringStruct(u'ProductVersion', u'{APP_VERSION}')])
    ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"""
    path = HERE / "version_info.txt"
    path.write_text(content, encoding="utf-8")
    return path


def write_manifest() -> Path:
    """asInvoker manifest: do NOT request admin rights.

    Asking for elevation without needing it is a strong suspicion signal.
    Arch Client doesn't need admin (Java is downloaded into the user's
    ~/.config folder).
    """
    content = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <assemblyIdentity version="{APP_VERSION}.0" processorArchitecture="*"
                    name="{COMPANY_NAME}.{APP_NAME}" type="win32"/>
  <description>{FILE_DESC}</description>
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
    <security>
      <requestedPrivileges>
        <requestedExecutionLevel level="asInvoker" uiAccess="false"/>
      </requestedPrivileges>
    </security>
  </trustInfo>
  <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1">
    <application>
      <!-- Windows 10 / 11 -->
      <supportedOS Id="{{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}}"/>
    </application>
  </compatibility>
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true</dpiAware>
    </windowsSettings>
  </application>
</assembly>
"""
    path = HERE / f"{APP_NAME}.manifest"
    path.write_text(content, encoding="utf-8")
    return path


def sign_self_signed(target: Path):
    """Sign with a self-signed certificate.

    Does NOT silence SmartScreen (the certificate isn't issued by a CA), but a
    valid signature still lowers the heuristic score in some AVs. Needs PowerShell.
    """
    ps = f"""
$ErrorActionPreference = 'Stop'
$cert = Get-ChildItem Cert:\\CurrentUser\\My | Where-Object {{ $_.Subject -eq 'CN={COMPANY_NAME}' }} | Select-Object -First 1
if (-not $cert) {{
  $cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject 'CN={COMPANY_NAME}' -CertStoreLocation Cert:\\CurrentUser\\My -NotAfter (Get-Date).AddYears(5)
}}
Set-AuthenticodeSignature -FilePath '{target}' -Certificate $cert -TimestampServer 'http://timestamp.digicert.com' | Out-Null
Write-Host 'Signed OK'
"""
    try:
        run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps])
        print("  ✅ Self-signed signature applied.")
    except Exception as e:
        print(f"  ⚠ Self-signing failed ({e}) — skipped, the build is still usable.")


def zip_dir(folder: Path, zip_path: Path):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in folder.rglob("*"):
            if p.is_file():
                z.write(p, p.relative_to(folder.parent))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--onefile", action="store_true",
                    help="Pack into a single .exe (EASILY FLAGGED BY ANTIVIRUS).")
    ap.add_argument("--sign-self", action="store_true",
                    help="Self-sign after building (Windows, needs PowerShell).")
    ap.add_argument("--no-zip", action="store_true", help="Do not zip the dist folder.")
    args = ap.parse_args()

    if sys.platform != "win32":
        print("⚠ This script builds the Windows version — run it on Windows.")
        print("  (PyInstaller does not cross-compile: to get an .exe you must build on Windows.)")

    if not MAIN_SCRIPT.exists():
        sys.exit(f"❌ Not found: {MAIN_SCRIPT}")

    print("== 1/5: Installing required packages ==")
    pip_install(REQUIRED_PACKAGES, required=True)

    print("== 2/5: Installing optional packages (Discord RPC, embedded browser…) ==")
    pip_install(OPTIONAL_PACKAGES, required=False)

    print("== 3/5: Installing PyInstaller ==")
    pip_install(BUILD_TOOLS, required=True)

    print("== 4/5: Generating anti-false-positive metadata ==")
    icon = ensure_icon()
    version_file = write_version_file()
    manifest = write_manifest()
    print(f"  ✓ version resource: {version_file.name}")
    print(f"  ✓ manifest asInvoker: {manifest.name}")

    print("== 5/5: Packaging ==")
    for d in ("build", "dist"):
        shutil.rmtree(HERE / d, ignore_errors=True)
    spec_file = HERE / f"{APP_NAME}.spec"
    if spec_file.exists():
        spec_file.unlink()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile" if args.onefile else "--onedir",
        "--windowed",
        "--noupx",                      # UPX = packer = red flag for every AV
        "--clean", "--noconfirm",
        "--name", APP_NAME,
        "--version-file", str(version_file),
        "--manifest", str(manifest),
        "--collect-all", "ttkbootstrap",
    ]
    if icon:
        cmd += ["--icon", icon]
    for mod in EXCLUDES:
        cmd += ["--exclude-module", mod]

    img_dir = HERE / "img"
    if img_dir.exists():
        sep = ";" if sys.platform == "win32" else ":"
        cmd += ["--add-data", f"{img_dir}{sep}img"]

    for hidden in ("pypresence", "tkinterweb", "webview", "PIL._tkinter_finder"):
        cmd += ["--hidden-import", hidden]

    cmd += [str(MAIN_SCRIPT)]
    run(cmd)

    if args.onefile:
        exe_path = HERE / "dist" / f"{APP_NAME}.exe"
        if not exe_path.exists():
            sys.exit("❌ Build failed — no .exe found in dist/.")
        if args.sign_self and sys.platform == "win32":
            sign_self_signed(exe_path)
        print(f"\n✅ Build finished: {exe_path}")
        print("⚠ The --onefile build self-extracts to %TEMP% -> Defender may still flag it.")
        print("  If it is falsely flagged, rebuild WITHOUT --onefile (onedir build).")
        return

    app_dir = HERE / "dist" / APP_NAME
    exe_path = app_dir / f"{APP_NAME}.exe"
    if not exe_path.exists():
        sys.exit("❌ Build failed — no .exe found in dist/.")
    if args.sign_self and sys.platform == "win32":
        sign_self_signed(exe_path)

    print(f"\n✅ Build finished: {app_dir}")
    if not args.no_zip:
        zip_path = HERE / "dist" / f"{APP_NAME}-windows.zip"
        zip_dir(app_dir, zip_path)
        size = zip_path.stat().st_size / 1024 / 1024
        print(f"✅ Zipped: {zip_path}  ({size:.1f} MB)")
        print("   Send this .zip to users — extract it and run ArchClient.exe.")
    print("\n📌 The onedir build is almost never flagged by Defender because it does not self-extract")
    print("   to %TEMP% like the --onefile build does.")


if __name__ == "__main__":
    main()
