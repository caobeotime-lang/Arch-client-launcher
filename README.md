# Arch Laucher

A Minecraft Fabric launcher written in Python. Originally built for my own
CachyOS/KDE Plasma setup, it now runs on Windows as well as Arch- and
Debian-based Linux distros. The goal was simple: click once and play —
no manually installing Java, setting up Fabric, or worrying about the
stock launcher not reading whatever messy mod folder structure you left
behind.

The UI uses `ttkbootstrap` (flatly theme), with a real terminal-style
console built right into the app for watching logs, and the launcher
handles nearly everything during first-time setup on its own.

![Arch Client icon](img/icon.png)

---

## Why this exists

Mojang's official launcher doesn't support Fabric, and third-party
launchers (MultiMC, Prism...) are great but a bit heavy if all you need is
a fixed, pre-optimized mod set without much manual tweaking. Arch Client
automates that part: open it up, it detects what's missing and installs
it, builds the `.minecraft` folder structure, and comes with a one-click
"Optimize FPS" button that pulls a curated mod set from Modrinth.

## Features

- **Automatic OS detection** — Windows 10/11, Arch Linux and Arch-based
  distros (Manjaro, EndeavourOS, Garuda, CachyOS...), Debian/Ubuntu and
  Debian-based distros (Mint, Pop!_OS, Zorin...).
- **Auto-installs missing Python packages** at startup (`ttkbootstrap`,
  `minecraft-launcher-lib`, `requests`, `Pillow`...), and automatically
  handles the `externally-managed-environment` error common on newer
  distros by falling back to `--break-system-packages`.
- **Auto-installs missing system packages** for `tkinter`, via `pacman`
  or `apt` depending on the distro.
- **Auto-detects and installs the right Java version** for the target
  Minecraft version (Java 21+ for 1.20.5 and up), downloading directly
  from Adoptium if needed, or trying the system's package manager first.
- **Auto-builds the `.minecraft` folder structure** — creates everything
  from scratch if nothing exists, or fills in just the missing
  subfolders if an older setup is already there.
- **Installs/updates Fabric** for the targeted Minecraft version with a
  single click, no extra steps.
- **One-click FPS optimization** — writes a pre-tuned `options.txt` and
  automatically downloads popular performance mods (Sodium, Lithium,
  Starlight, FerriteCore, Krypton, LazyDFU, Iris, ModernFix,
  EntityCulling, ImmediatelyFast) from Modrinth, matched to the correct
  Minecraft + Fabric version.
- **Microsoft login** for playing online.
- **Discord Rich Presence** (optional) — shows what you're playing / which
  tab you're on right on Discord; simply skipped if `pypresence` isn't
  installed.
- **Built-in console** — watch game logs live inside the app, save logs
  to a `.txt` file when you need to report a bug.
- **Automatic error logging** — every unhandled exception (main thread,
  background thread, or UI callback) is caught and written to a
  timestamped `.txt` file in
  `~/.config/arch-client-launcher/error_logs/`, with a full traceback —
  never a silent crash.
- **Built-in content browser** — search Modrinth for mods, resource packs
  and shaders, each row showing the project's icon, author, download count
  and description. Downloads land in `mods/`, `resourcepacks/` or
  `shaderpacks/` automatically.
- **Real browser behaviour** — a smart address bar (type a URL to open it,
  type anything else to search) plus a search-engine picker: DuckDuckGo,
  Google, Bing, Startpage, Brave, YouTube, Modrinth and CurseForge. Known
  tracker domains and tracking query parameters are stripped on the way.
- **Fully bilingual UI (VI/EN)** — every tab, button, label and status
  message is translated; auto-selected from your IP, with a system-locale
  fallback and a manual override in Settings.
- **Auto-adds a bundled client mod** — if the launcher ships with a
  `client/` folder containing a `.jar` file, it's automatically copied
  into `mods/` if missing or outdated.

## Folder structure

```
Arch client laucher/
├── arch_laucher.py      # the entire launcher, run this file
├── client/              # (optional) bundled client mod, auto-copied into mods/
│   └── arch-client-1.21.11.jar
└── img/
    ├── icon.png          # window/taskbar icon
    └── banner.png        # banner shown on the Overview tab and splash screen
```

If `img/icon.png` or `img/banner.png` are missing, the launcher still
runs fine — it just shows text instead of the image. The `client/` folder
is also optional; if it's not there, the launcher simply skips the mod-copy
step without any error.

## Requirements

- Python 3.9 or newer (uses `sys.getwindowsversion` and modern type hints,
  so a fairly recent version is needed).
- An internet connection on first run (to install libraries, download
  Fabric, download Java, and detect language via IP). It works offline
  afterward, aside from features that need internet (downloading mods,
  logging in).
- On Linux, working `sudo` access is needed if the launcher has to install
  system packages (`tk`, `jdk-openjdk`...) — it automatically prepends
  `sudo` to commands when required.

## Installation & running

No setup required beforehand — clone or download the repo and run it
directly:

```bash
python3 arch_laucher.py
```

The first run will take a bit longer since the launcher has to install
missing Python packages, detect Java, and build the `.minecraft` folder
structure. Later runs will be faster since everything's already in place.

If you'd rather install everything manually first:

```bash
pip install minecraft-launcher-lib requests ttkbootstrap pillow --break-system-packages
```

## Usage guide

The main window is split into 4 tabs:

| Tab | What it's for |
|---|---|
| 📊 Overview | Choose the `.minecraft` folder, view the list of mod/resourcepack/shaderpack/schematic files currently installed. |
| ⚙️ Settings | Auto-check/install Java, log in with Microsoft, adjust RAM allocated to the game. |
| 🚀 Optimize FPS | One click to write optimized FPS settings + download the selected performance mod set. |
| 🌐 Browser / Mods | Search Modrinth for **mods, resource packs and shaders** with thumbnails, download straight into the right folder, or browse the web with a built-in address bar and a search-engine picker (DuckDuckGo, Google, Bing, Startpage, Brave, YouTube). |
| 🖥️ Console | Watch live logs while the game runs, clear the console, save logs to a file. |

The footer always has 2 fixed buttons: **⬇ Install / Update Fabric**
(click before playing for the first time or after changing versions) and
**▶ PLAY NOW**. The standard flow for a first run: install Fabric → check
Java in the Settings tab → log in with Microsoft (if playing online) →
click Play Now.

## Troubleshooting

**Launcher won't open, reports missing `tkinter`**
Your distro ships `tkinter` separately from base Python. Install it with
`sudo pacman -S tk` (Arch) or `sudo apt install python3-tk`
(Debian/Ubuntu), then run again — the launcher also tries to do this
itself if it has sudo access, but if your environment doesn't allow
automatic sudo, you'll need to do it manually.

**Game crashes right on launch, Java log shows an error related to
`MessageFormat` / `Mod resolution failed`**
This means two mods in `mods/` are conflicting (one mod needs another
you haven't installed, or two mods declare themselves incompatible) — a
bug in Fabric Loader itself causes the real error message to get masked
by an unrelated exception that looks like a date-format error. Look for
the `Mod resolution failed` and `Immediate reason:` lines right above the
crash in `latest.log` (or in the log file the launcher automatically
writes to `error_logs/`) to find out exactly which mods are conflicting,
then remove or swap one out.

**Automatic Python package installation fails**
Usually because there's no internet on first run, or pip is blocked by a
firewall/proxy. Install manually using the command the launcher prints
in the console (it already includes the `--break-system-packages` flag),
or check your internet connection first.

**Discord Rich Presence doesn't show up**
Missing `pypresence` — not required, the launcher still works fine, you
just lose the Discord status feature. Install it with
`pip install pypresence --break-system-packages` if you want to enable it.

## Building the Windows `.exe` (no manual Python / pip needed)

On a machine **with Python** (only the build machine needs it — people
receiving the `.exe` do not), run:

```bash
python build_windows.py            # recommended: onedir + ArchClient-windows.zip
python build_windows.py --onefile  # single .exe (more likely to be AV-flagged)
```

The script installs every dependency (`ttkbootstrap`, `minecraft-launcher-lib`,
`requests`, `pillow`, `pypresence`, `tkinterweb`, `pywebview`), installs
PyInstaller, generates an embedded version resource + an `asInvoker`
manifest, and packages everything into `dist/ArchClient/` (zipped as
`dist/ArchClient-windows.zip`).

Send the `.zip` to users — they unzip it and double-click `ArchClient.exe`:

- No Python, no `pip install`.
- No manual Java install — the launcher detects a missing Java 21 and
  downloads Eclipse Temurin (Adoptium) on its own.
- Same UI and features as running from source.

The launcher detects when it is running as a frozen `.exe` (`FROZEN`) and
skips the runtime pip step entirely, since every library is embedded at
build time.

## Windows Defender flags the .exe — why, and how it's fixed

Older builds got tagged as `Trojan:Win32/Wacatac.B!ml`. That is a false
positive, and it had four causes:

| Cause | Fix |
|---|---|
| `--onefile` unpacks tens of MB into `%TEMP%` then executes from there — textbook dropper behaviour for Defender's ML heuristics | Default build is now `--onedir` (a folder + DLLs, no self-extraction) |
| The `.exe` carried no version resource, so it looked like anonymous software | `build_windows.py` generates `version_info.txt` (CompanyName, ProductName, FileVersion) and passes `--version-file` |
| UPX compression looks like a packer | `--noupx` (already in place) |
| Not code-signed, so SmartScreen warns on first run | Needs a paid certificate. `--sign-self` adds a self-signed signature, which helps some engines but not SmartScreen |

If a build still gets flagged:

1. Use the `--onedir` build (the default) rather than `--onefile`.
2. Report the false positive at
   <https://www.microsoft.com/en-us/wdsi/filesubmission> — Microsoft usually
   clears it within a few days, for everyone.
3. As a stopgap, users can add an exclusion:
   **Windows Security → Virus & threat protection → Manage settings →
   Exclusions**.
4. Note that the launcher downloads a JRE and mod `.jar` files at runtime,
   which some behavioural engines also dislike. That behaviour is genuine and
   intentional.

## Security

- HTTPS certificate verification is enabled (CA bundle from `certifi`).
- Mod downloads are verified against the SHA-512/SHA-1 hash from the Modrinth API; Java is verified against the official SHA-256 from Adoptium. A mismatch aborts the install.
- Archives with path-traversal entries are rejected.
- Every release ships a `SHA256SUMS.txt` — see [SECURITY.md](SECURITY.md) for how to verify it.

## Contributing

Personal repo, no formal contribution process yet. If you find a bug or
have an idea for improvement, feel free to open an issue describing:
your OS, Python version, and the log/traceback if it crashed — much
easier to debug than a description alone.

## License

This software is **free for personal, non-commercial use**. You're
allowed to download, modify, and redistribute it for free. You are
**not** allowed to sell it, rent it, repackage it for profit, or use it
for any commercial purpose in any form without prior written consent
from the author. See the [`LICENSE`](LICENSE) file for details.

Note: this license only applies to the launcher's code (`arch_laucher.py`).
Third-party mods the launcher downloads (Sodium, Lithium, Iris, Fabric
API...) retain their original authors' licenses — the launcher does not
own and grants no additional rights over those files.

## Credits

Thanks to the open-source projects Arch Client relies on:
[Fabric](https://fabricmc.net/),
[minecraft-launcher-lib](https://github.com/JakobDev/minecraft-launcher-lib),
[ttkbootstrap](https://ttkbootstrap.readthedocs.io/), and all the authors
of the FPS optimization mods listed above on
[Modrinth](https://modrinth.com/).

---

🌐 [archclient.netlify.app](https://archclient.netlify.app)
