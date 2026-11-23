# Arch Client for Windows

A Minecraft launcher for Windows 10 and 11 (64-bit). Supports every Minecraft version and the Vanilla, Fabric, Quilt, Forge and NeoForge loaders. Written in Python with PyQt6.

Version 1.0. Qt 6 needs Windows 10 or newer; Windows 7 and 8 are not supported. Linux build: `linux` branch.

## Install

**Option 1: the .exe (recommended).** Download `ArchClient-1.0.0-windows-x64.zip` (GitHub Actions → Artifacts, or build it yourself, see below), extract it and run `ArchClient.exe`. Python is not required.

The file is not code-signed, so Windows SmartScreen may show "Windows protected your PC" on first run. Click **More info → Run anyway**.

**Option 2: from source.** Install Python 3.10+ from [python.org](https://www.python.org/downloads/) (tick *Add python.exe to PATH*) and double-click `run.bat`. It installs the dependencies on first run.

On first start the launcher creates shortcuts in the Start Menu and on the Desktop. If you remove them in Settings they are not recreated.

## Features

- Pick any Minecraft version (release, snapshot, beta, alpha) and loader, then press Play. Whatever is missing (game files, loader, Java) is installed first.
- Installs the right Java per Minecraft version (Temurin zip, portable, no admin): Java 8 for 1.16 and older, 17 for 1.17–1.20.4, 21 for 1.20.5+, 25 for 26.x. Existing installs are used first (Adoptium, Microsoft, Zulu, Corretto, the official launcher's runtime). If the download fails it falls back to `winget`.
- Files page: browse, open, delete and add mods, resource packs, shaders and schematics.
- Mods page: search and install from Modrinth, with required dependencies and SHA-512 checks.
- Optimize page: one-click performance mods (Sodium, Lithium, Iris, FerriteCore; Embeddium, ModernFix and others for Forge/NeoForge) plus an optimized `options.txt`.
- Console with launcher and game logs (capped at 4000 lines).
- Multiple accounts: any number of offline names and Microsoft accounts. Pick one next to the Play button; press Play again to open another game with a different account. Several games can run at the same time (output in the Console is prefixed with the account name).
- English and Vietnamese UI, interface sounds that can be turned off.
- No console windows flash up when the launcher runs helper programs.

## Windows tweaks

Optimize → Windows tweaks. None of these need admin rights or show a UAC prompt. They only change settings of your own account, and switching an option off restores the previous value.

| Option | What it does | Default |
|---|---|---|
| High-performance GPU | Sets `java.exe` and `javaw.exe` to *High performance* under Settings → Display → Graphics. Hybrid-GPU laptops often run Java on the integrated GPU. | On |
| Game Mode | Turns Windows Game Mode on. | On |
| Higher CPU priority | Runs the game at *Above normal* priority. | On |
| High-performance power plan | Switches to *High performance* (or *Ultimate* if present) only while the game runs and restores the old plan on exit. If the launcher is killed mid-game, the plan is restored on the next start. | Off |
| Disable Game DVR | Stops Xbox Game Bar background capture. | Off |
| Disable Fullscreen Optimizations | Applied to `java.exe`. Can lower input lag in fullscreen. | Off |
| ZGC instead of G1 | Only used with 8 GB or more of RAM and Java 17+. | Off |

The launcher also caps the game's RAM at 75% of the machine's memory and uses tuned JVM flags.

It deliberately does not add Windows Defender exclusions for the game folder: mods are a common malware vector and the speedup is small.

## Where data lives

- Game: `%APPDATA%\.minecraft`, the same folder as the official launcher, so existing mods, saves and resource packs work immediately. Changeable in Settings.
- Config, portable Java and error logs: `%LOCALAPPDATA%\ArchClient\`. `config.json` holds the login token.

## Loaders and versions

| Loader | Notes |
|---|---|
| Vanilla | Uses `.minecraft` directly. |
| Fabric / Quilt | Fabric mods run on Quilt. |
| Forge / NeoForge | The installer is run with the correct Java. Old Forge (1.7–1.12) needs Java 8, which the launcher handles. |

- All loaders share `.minecraft` by default. Turn on *Separate folder per loader* in Settings to give each loader and version its own `instances\<loader>-<version>\`.
- **OptiFine** has no official download API. Download the `.jar` from optifine.net, select **Forge** for the matching version and add the file under Files → Mods → Add file. For FPS, Fabric with Sodium and Iris is usually faster.
- Loader icons are `assets\icons\loader-<name>.svg`. Replace a file with the same name to use another logo.

## Microsoft login

Settings → Account → **Add Microsoft account**. The launcher opens your browser and catches the redirect on `localhost`; nothing needs to be pasted. Each account's session is remembered and refreshed before launch. Repeat to add more accounts; remove one with the trash icon.

You need your own Azure app (enter its `client_id` in Settings):
1. Azure Portal → App registrations → New registration, account type *Personal Microsoft accounts*.
2. Authentication → add the **Mobile and desktop applications** platform with redirect URI `http://localhost`.
3. Enable *Allow public client flows*.
4. Microsoft must approve a new Azure app before it can call the Minecraft API: [request form](https://aka.ms/mce-reviewappid).

Without an Azure app you can still play offline: add an offline account in Settings → Account.

Running several games at once: every game uses the same game folder unless *Separate folder per loader* is on, so avoid opening the same world twice. Each game needs its own RAM; the launcher warns when free memory is low. Servers kick two sessions of the same Microsoft account, so use a different account per game.

## Building ArchClient.exe

On Windows with Python 3.10+:

```bat
python build_windows.py            :: folder + .zip in dist\
python build_windows.py --onefile  :: single .exe (slower to start, more likely to be flagged by Defender)
```

Or push to the `windows` branch: the GitHub Actions workflow `.github/workflows/windowsbuild.yml` builds it and uploads the zip as an artifact.

## Layout

```
arch_laucher.py        entry point
archclient/
  core.py              non-GUI logic (Java, Modrinth, config)
  winsys.py            Windows-only code: registry, power plan, .lnk shortcuts, Java lookup
  controller.py        background jobs and signals to the GUI
  bootstrap.py         paths, dependency install, error logs
  sound.py, i18n.py, ui/
assets/icons/          Lucide icons (SVG) and loader icons
img/                   app icon and logo (icon.ico is used for the exe and shortcuts)
```

Not affiliated with Mojang or Microsoft. Source code: see [LICENSE](LICENSE). Icons from [Lucide](https://lucide.dev), ISC license.
