Arch Client is a Minecraft launcher for 64-bit Windows 10 and 11, written in Python with PyQt6. This is the first stable release.

## Downloads

| File | Description |
| --- | --- |
| `ArchClient-1.0.0-windows-x64-setup.exe` | Installer (recommended). Installs into `%LOCALAPPDATA%\Programs\ArchClient` for the current user, with Start-menu and optional desktop shortcuts. No admin rights needed. |
| `ArchClient-1.0.0-windows-x64.zip` | Portable version. Extract anywhere and run `ArchClient.exe`. No installation required. |
| `ArchClient-1.0.0-windows-x64-standalone.exe` | Everything in a single `.exe`. Slowest to start; handy if you want just one file. |
| `ArchClient-source-v1.0.0.zip` | Full source tree of this release. |

## Requirements

- Windows 10 or later (64-bit)

## Installation

- **Installer:** run `ArchClient-1.0.0-windows-x64-setup.exe` and follow the wizard.
- **Portable:** extract `ArchClient-1.0.0-windows-x64.zip` to any folder and run `ArchClient.exe`.
- **Standalone:** run `ArchClient-1.0.0-windows-x64-standalone.exe` directly.

None of the files are code-signed, so SmartScreen may show "Windows protected your PC" on first start. Click **More info → Run anyway**.

## Features

- Every Minecraft version (release, snapshot, beta, alpha) and the Vanilla, Fabric, Quilt, Forge and NeoForge loaders. Missing game files, the loader and Java are installed automatically.
- Per-version Java management (Java 8 / 17 / 21 / 25), installed per user without admin rights.
- Mod search and installation from Modrinth, with dependencies and SHA-512 verification.
- One-click performance setup on the Optimize page (Sodium, Lithium, Iris, FerriteCore and more).
- Multiple accounts: any number of offline names and Microsoft accounts, several games at the same time.
- English and Vietnamese interface.

## SHA-256

```
{{SHA256}}
cd2f4d607668c8f33cdf56e08fc2ff71290e8c399492a64bad9cd0eee279c74d  ArchClient-source-v1.0.0.zip
```

## Source

Released under the GPL-3.0 license. Also available in the Source code (zip / tar.gz) archives below, or in the `windows` branch of this repository.
