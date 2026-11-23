Arch Client is a Minecraft launcher for 64-bit Linux, written in Python with PyQt6. This is the first stable release.

## Downloads

| File | Description |
| --- | --- |
| `ArchClient-1.0.0-linux-x86_64.tar.gz` | Prebuilt launcher, ready to run, includes `install.sh` (installs into `~/.local`, no sudo needed). |
| `ArchClient-1.0.0-amd64.deb` | Package for Debian, Ubuntu, Linux Mint and other .deb distros. |
| `ArchClient-1.0.0-x86_64.rpm` | Package for Fedora, RHEL, openSUSE and other .rpm distros. |
| `ArchClient-1.0.0-x86_64.pkg.tar.zst` | Package for Arch Linux and derivatives. |
| `ArchClient-1.0.0-x86_64.AppImage` | Portable AppImage, one file (requires `libfuse2`). |
| `ArchClient-source-v1.0.0.zip` | Full source tree of this release. |

## Requirements

- 64-bit Linux with glibc 2.35 or newer (built on Ubuntu 22.04): Ubuntu 22.04+, Debian 12, Linux Mint 21+, Fedora 36+, Arch Linux and derivatives

## Installation

Tarball:

1. Extract `ArchClient-1.0.0-linux-x86_64.tar.gz`.
2. Run `ArchClient/ArchClient`, or run `ArchClient/install.sh` to install into `~/.local` with an application-menu entry (no sudo needed).

Packages:

```bash
sudo apt install ./ArchClient-1.0.0-amd64.deb          # Debian, Ubuntu, Mint
sudo dnf install ./ArchClient-1.0.0-x86_64.rpm         # Fedora, RHEL
sudo pacman -U ./ArchClient-1.0.0-x86_64.pkg.tar.zst   # Arch Linux
```

AppImage:

```bash
chmod +x ArchClient-1.0.0-x86_64.AppImage
./ArchClient-1.0.0-x86_64.AppImage
```

## Features

- Every Minecraft version (release, snapshot, beta, alpha) and the Vanilla, Fabric, Quilt, Forge and NeoForge loaders. Missing game files, the loader and Java are installed automatically.
- Per-version Java management (Java 8 / 17 / 21 / 25), installed per user.
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

Released under the GPL-3.0 license. Also available in the Source code (zip / tar.gz) archives below, or in the `linux` branch of this repository.
