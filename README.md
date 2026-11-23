# Arch Client

A Minecraft launcher for Linux. Supports every Minecraft version and the Vanilla, Fabric, Quilt, Forge and NeoForge loaders. Written in Python with PyQt6.

Version 1.0. Windows build: `windows` branch.

## Features

- Pick any Minecraft version (release, snapshot, beta, alpha) and loader, then press Play. Whatever is missing (game files, loader, Java) is installed first.
- Installs the right Java per Minecraft version (Temurin, portable, no root): Java 8 for 1.16 and older, 17 for 1.17–1.20.4, 21 for 1.20.5+, 25 for 26.x. Several Java versions can sit side by side.
- Files page: browse, open, delete and add mods, resource packs, shaders and schematics.
- Mods page: search and install from Modrinth. Required dependencies are installed too and downloads are checked against SHA-512.
- Optimize page: one-click performance mods (Sodium, Lithium, Iris, FerriteCore; Embeddium, ModernFix and others for Forge/NeoForge) plus an optimized `options.txt`.
- Linux tweaks: gamemode, MangoHud, jemalloc, Mesa/NVIDIA environment variables, CPU governor hint, transparent huge pages, ZGC.
- Console with launcher and game logs (capped at 4000 lines).
- Multiple accounts: any number of offline names and Microsoft accounts. Pick one next to the Play button; press Play again to open another game with a different account. Several games can run at the same time (output in the Console is prefixed with the account name).
- English and Vietnamese UI, interface sounds that can be turned off.
- Creates its menu and desktop shortcuts on first start. If you remove them in Settings they are not recreated.
- Closing the launcher does not kill a running game. Errors are written to `~/.config/arch-client-launcher/error_logs/`.

## Download

All downloads are on the [Releases page](https://github.com/caobeotime-lang/Arch-client-launcher/releases/tag/v1.0.0-linux):

| File | What it is |
|---|---|
| `ArchClient-1.0.0-linux-x86_64.tar.gz` | Ready to run, includes `install.sh` (installs into `~/.local`, no sudo). |
| `ArchClient-1.0.0-amd64.deb` | Debian, Ubuntu, Mint: `sudo apt install ./ArchClient-1.0.0-amd64.deb` |
| `ArchClient-1.0.0-x86_64.rpm` | Fedora, RHEL, openSUSE: `sudo dnf install ./ArchClient-1.0.0-x86_64.rpm` |
| `ArchClient-1.0.0-x86_64.pkg.tar.zst` | Arch Linux: `sudo pacman -U ./ArchClient-1.0.0-x86_64.pkg.tar.zst` |
| `ArchClient-1.0.0-x86_64.AppImage` | Portable, one file (requires `libfuse2`). |
| `ArchClient-source-v1.0.0.zip` | Source code of this release. |

## Run

Requires Python 3.10+. On first start the launcher installs `PyQt6`, `minecraft-launcher-lib` and `requests` if they are missing.

```bash
git clone https://github.com/caobeotime-lang/Arch-client-launcher.git
cd Arch-client-launcher
git checkout linux
./run.sh            # or: python3 arch_laucher.py
```

To install the dependencies yourself: `pip install -r requirements.txt`

### Distro notes

| Problem | Fix |
|---|---|
| "xcb-cursor0 / libxcb-cursor0 is needed" | The launcher tries to install it. Otherwise: `sudo apt install libxcb-cursor0`, `sudo pacman -S xcb-util-cursor` or `sudo dnf install xcb-util-cursor` |
| pip reports "externally-managed-environment" | The launcher retries with `--break-system-packages` / `--user`. Or use a venv: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/python arch_laucher.py` |
| Fedora Silverblue / SteamOS (read-only root) | Use a venv as above. Java is downloaded as a portable build, so no system package is needed. |

## Loaders and versions

| Loader | Notes |
|---|---|
| Vanilla | Uses `~/.minecraft` directly. |
| Fabric / Quilt | Fabric mods run on Quilt. |
| Forge / NeoForge | The installer is run with the correct Java. Old Forge (1.7–1.12) needs Java 8, which the launcher handles. |

- The version list comes from Mojang and is filtered by loader. Settings → *Version type* shows snapshots, betas and alphas. The list is cached, so it still opens offline.
- All loaders share `~/.minecraft` by default (mods, saves and config as in the stock launcher). Turn on *Separate folder per loader* in Settings to give each loader and version its own `~/.minecraft/instances/<loader>-<version>/`. Game files, libraries and assets stay shared.
- Loader icons are `assets/icons/loader-<name>.svg` (Lucide icons by default). Replace a file with the same name to use another logo.

### OptiFine

OptiFine has no official download API, so the launcher does not fetch it. Download the `.jar` from optifine.net, select **Forge** for the matching version and add the file under Files → Mods → Add file. For FPS, Fabric with Sodium and Iris is usually faster.

## Microsoft login

Settings → Account → **Add Microsoft account**. The launcher opens your browser and catches the redirect on `localhost`; nothing needs to be pasted. Each account's session is remembered and refreshed before launch. Repeat to add more accounts; remove one with the trash icon.

You need your own Azure app (enter its `client_id` in Settings):
1. Azure Portal → App registrations → New registration, account type *Personal Microsoft accounts*.
2. Authentication → add the **Mobile and desktop applications** platform with redirect URI `http://localhost` (and `https://login.microsoftonline.com/consumers/oauth2/nativeclient` if you want the paste-URL mode).
3. Enable *Allow public client flows*.
4. Microsoft must approve a new Azure app before it can call the Minecraft API: [request form](https://aka.ms/mce-reviewappid). Until then you get a "not permitted" error.

Without an Azure app you can still play offline: add an offline account in Settings → Account.

Running several games at once: every game uses the same game folder unless *Separate folder per loader* is on, so avoid opening the same world twice. Each game needs its own RAM; the launcher warns when free memory is low. Servers kick two sessions of the same Microsoft account, so use a different account per game.

The token is stored in `~/.config/arch-client-launcher/config.json` (mode 600).

## Transparency and blur

The translucent window needs a compositor. The launcher detects this:

- Wayland (GNOME, KDE, Hyprland, Sway and others): always on.
- X11: on if a compositor is running (KWin, Mutter, picom, ...); otherwise a solid background is used to avoid black borders.

Override with `ARCH_TRANSLUCENT=1 ./run.sh` or `ARCH_TRANSLUCENT=0 ./run.sh`.

## Building

```bash
python3 build_linux.py             # onedir + .tar.gz
python3 build_linux.py --appimage  # also an .AppImage
python3 build_linux.py --deb       # also a .deb (Debian, Ubuntu, Mint)
```

The GitHub Actions workflow `.github/workflows/linuxbuild.yml` builds on every push to the `linux` branch and uploads the tar.gz, AppImage, .deb, .rpm and .pkg.tar.zst to the `v1.0.0-linux` release. It builds on Ubuntu 22.04, so the result runs on distros with glibc 2.35 or newer.

## Layout

```
arch_laucher.py        entry point
archclient/
  core.py              non-GUI logic (Java, Modrinth, Linux tweaks, config)
  controller.py        background jobs and signals to the GUI
  bootstrap.py         dependency install, distro detection, error logs
  winsys.py            Windows-only code (unused on Linux)
  sound.py             interface sounds (WAVs are synthesized)
  i18n.py              English / Vietnamese strings
  ui/                  theme, widgets, pages, main window
assets/icons/          Lucide icons (SVG) and loader icons
img/                   app icon and logo
```

## Notes

- Launcher data: `~/.config/arch-client-launcher/`, cache: `~/.cache/arch-client/`, game: `~/.minecraft` (changeable in Settings).
- Sound uses Qt Multimedia when an audio device exists, otherwise `pw-play`, `paplay` or `aplay`.
- Not affiliated with Mojang or Microsoft.

## License

Source code: see [LICENSE](LICENSE). Icons from [Lucide](https://lucide.dev), ISC license (`assets/icons/LICENSE-lucide.txt`).
