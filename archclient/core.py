# -*- coding: utf-8 -*-
"""Lõi launcher — KHÔNG phụ thuộc giao diện.

Cấu hình, tối ưu Linux, Java, Fabric, Modrinth, shortcut. Mọi hàm nhận một
callback ``log(msg, level)`` thay vì in thẳng, để GUI hiển thị lên Console.
"""
from __future__ import annotations

import os
import re
import sys
import json
import uuid
import time
import shutil
import hashlib
import tarfile
import platform
import threading
import subprocess
from pathlib import Path

from . import APP_VERSION, APP_ID, APP_NAME
from .bootstrap import (APP_DIR, CONFIG_DIR, CACHE_DIR, FROZEN, GAME_LOG_DIR, IS_WINDOWS,
                        bprint, detect_os, hidden_kwargs, resource_path, run_privileged,
                        install_system_packages, write_error_log)
from . import winsys

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

try:
    import minecraft_launcher_lib as mll
except Exception:  # pragma: no cover
    mll = None


def _default_log(msg, level="info"):
    bprint(f"[{level}] {msg}")


# ==========================================================================
# HẰNG SỐ
# ==========================================================================
CONFIG_FILE = CONFIG_DIR / "config.json"
if IS_WINDOWS:     # cùng chỗ với launcher chính thức -> mod, save, resource pack có sẵn dùng được ngay
    DEFAULT_MC_DIR = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / ".minecraft"
else:
    DEFAULT_MC_DIR = Path.home() / ".minecraft"
JAVA_EXE = "java.exe" if IS_WINDOWS else "java"
JRE_DIR = CONFIG_DIR / "jre"
SHADER_CACHE_DIR = CONFIG_DIR / "shader-cache"
ICON_PATH = resource_path("img/icon.png")
UA = f"ArchClient/{APP_VERSION} (+https://archclient.netlify.app)"

MC_VERSIONS = [
    "1.20.1", "1.20.2", "1.20.3", "1.20.4", "1.20.5", "1.20.6",
    "1.21", "1.21.1", "1.21.2", "1.21.3", "1.21.4", "1.21.5",
    "1.21.6", "1.21.7", "1.21.8", "1.21.9", "1.21.10", "1.21.11",
]
DEFAULT_MC_VERSION = "1.21.1"
JAVA_VERSION_CHOICES = ["8", "17", "21", "22", "23", "24", "25", "26"]

OPTIMIZATION_MODS = [
    "sodium", "lithium", "starlight", "ferrite-core", "krypton",
    "lazydfu", "iris", "modernfix", "entityculling", "immediatelyfast",
]
_OPT_FORGE = ["embeddium", "ferrite-core", "modernfix", "entityculling", "immediatelyfast",
              "badoptimizations", "sodium-options-api"]

# (id, tên hiển thị, icon Lucide) — thứ tự hiển thị trong launcher
LOADERS = [
    ("vanilla", "Vanilla", "loader-vanilla"),
    ("fabric", "Fabric", "loader-fabric"),
    ("quilt", "Quilt", "loader-quilt"),
    ("forge", "Forge", "loader-forge"),
    ("neoforge", "NeoForge", "loader-neoforge"),
]
LOADER_IDS = [x[0] for x in LOADERS]
# loader Modrinth chấp nhận cho từng loader (Quilt chạy được mod Fabric)
MODRINTH_LOADERS = {"fabric": ["fabric"], "quilt": ["quilt", "fabric"],
                    "forge": ["forge"], "neoforge": ["neoforge"]}
VERSION_KINDS = ["release", "snapshot", "all"]


def loader_label(lid: str) -> str:
    return next((n for i, n, _ in LOADERS if i == lid), lid)


def loader_icon(lid: str) -> str:
    return next((ic for i, _, ic in LOADERS if i == lid), "loader-vanilla")


def optimization_mods(loader: str) -> list:
    if loader in ("forge", "neoforge"):
        return list(_OPT_FORGE)
    if loader in ("fabric", "quilt"):
        return list(OPTIMIZATION_MODS)
    return []

OPTIMIZED_OPTIONS = {
    "maxFps": "260", "renderDistance": "8", "simulationDistance": "6",
    "particles": "1", "ao": "1", "graphicsMode": "0", "clouds": "0",
    "biomeBlendRadius": "0", "entityShadows": "false", "vsync": "false",
    "guiScale": "2", "mipmapLevels": "0", "fboEnable": "true", "enableVsync": "false",
}

# (khoá thư mục, đuôi file, khoá i18n)
CATEGORIES = [
    ("mods", {".jar"}, "cat_mods"),
    ("resourcepacks", {".zip"}, "cat_resourcepacks"),
    ("shaderpacks", {".zip"}, "cat_shaderpacks"),
    ("schematics", {".litematic", ".schem", ".nbt", ".schematic"}, "cat_schematics"),
]
REQUIRED_MC_SUBDIRS = ["mods", "resourcepacks", "shaderpacks", "schematics", "saves",
                       "screenshots", "config", "logs", "crash-reports", "versions"]

BROWSE_TYPES = [  # (project_type Modrinth, thư mục đích, khoá i18n)
    ("mod", "mods", "type_mod"),
    ("resourcepack", "resourcepacks", "type_resourcepack"),
    ("shader", "shaderpacks", "type_shader"),
]


def required_java_major(mc_version: str) -> int:
    """Java tối thiểu theo phiên bản Minecraft (ước lượng; bản đã cài thì đọc javaVersion trong json).
    <=1.16.x: 8 · 1.17–1.20.4: 17 · 1.20.5–1.x: 21 · 26.x trở đi: 25."""
    v = (mc_version or "").strip()
    m = re.match(r"^(\d\d)w(\d\d)[a-z]", v)            # snapshot dạng 24w14a
    if m:
        key = (int(m.group(1)), int(m.group(2)))
        if key >= (25, 45):
            return 25
        return 21 if key >= (24, 14) else 17 if key >= (21, 19) else 8
    m = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", v)
    if not m:
        return 8 if re.match(r"^(a|b|c|rd|inf)[-\d.]", v) else 21
    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    if major >= 26:
        return 25
    if major != 1:
        return 21
    if (minor, patch) >= (20, 5):
        return 21
    return 17 if minor >= 17 else 8


def java_acceptable(have: int, need: int) -> bool:
    """MC <=1.16 (và Forge cũ) chỉ chạy ổn trên Java 8; các bản mới cần >= yêu cầu."""
    if need <= 8:
        return have == 8
    return have >= need


def java_major_from_json(mc_dir: Path, version_id: str):
    """Đọc javaVersion.majorVersion trong json phiên bản đã cài (theo cả bản cha)."""
    seen = set()
    vid = version_id
    while vid and vid not in seen:
        seen.add(vid)
        try:
            data = json.loads((mc_dir / "versions" / vid / f"{vid}.json").read_text(encoding="utf-8"))
        except Exception:
            return None
        jv = data.get("javaVersion") or {}
        if jv.get("majorVersion"):
            return int(jv["majorVersion"])
        vid = data.get("inheritsFrom")
    return None


# ==========================================================================
# DANH SÁCH PHIÊN BẢN MINECRAFT (Mojang) + LOADER
# ==========================================================================
VERSION_MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
_LIST_TTL = 12 * 3600


def _cached_json(name: str, fetch, ttl=_LIST_TTL):
    """Lấy dữ liệu mạng, cache ở ~/.cache; mất mạng thì dùng cache cũ; không có gì thì None."""
    path = CACHE_DIR / name
    try:
        if time.time() - path.stat().st_mtime < ttl:
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    try:
        data = fetch()
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            pass
        return data
    except Exception:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None


def fetch_version_manifest():
    def fetch():
        if requests is None:
            raise RuntimeError("requests")
        r = requests.get(VERSION_MANIFEST_URL, timeout=15, headers={"User-Agent": UA})
        r.raise_for_status()
        return [{"id": v["id"], "type": v["type"]} for v in r.json()["versions"]]
    return _cached_json("mc_versions.json", fetch)


def fetch_loader_versions(loader: str):
    """Các bản Minecraft mà loader hỗ trợ (set id) hoặc None nếu không lấy được."""
    def fetch():
        return list(mll.mod_loader.get_mod_loader(loader).get_minecraft_versions(False))
    if mll is None or not hasattr(mll, "mod_loader"):
        return None
    return _cached_json(f"loader_{loader}.json", fetch)


def list_mc_versions(kind: str = "release", loader: str = "vanilla", current: str = "") -> list:
    """Danh sách id phiên bản (mới nhất trước) theo loại + loader. Luôn có bản `current`."""
    types = {"release": {"release"}, "snapshot": {"release", "snapshot"}}.get(
        kind, {"release", "snapshot", "old_beta", "old_alpha"})
    manifest = fetch_version_manifest()
    if manifest:
        out = [v["id"] for v in manifest if v["type"] in types]
        if loader != "vanilla":
            sup = fetch_loader_versions(loader)
            if sup is not None:
                sset = set(sup)
                out = [v for v in out if v in sset]
    else:
        out = list(reversed(MC_VERSIONS))
    if current and current not in out:
        out.insert(0, current)
    return out


def list_mc_versions_offline(current: str = "") -> list:
    """Danh sách dựng nhanh lúc mở app (cache hoặc danh sách dự phòng), không gọi mạng."""
    try:
        data = json.loads((CACHE_DIR / "mc_versions.json").read_text(encoding="utf-8"))
        out = [v["id"] for v in data if v["type"] == "release"]
    except Exception:
        out = list(reversed(MC_VERSIONS))
    if current and current not in out:
        out.insert(0, current)
    return out


def loader_supports(loader: str, mc_version: str):
    """True/False nếu biết, None nếu không rõ (mất mạng)."""
    if loader == "vanilla":
        return True
    sup = fetch_loader_versions(loader)
    return None if sup is None else mc_version in sup


def find_installed_version(mc_dir: Path, loader: str, mc_version: str):
    """Tìm id profile đã cài cho (loader, bản MC): vanilla = chính mc_version, các loader khác quét versions/."""
    vdir = mc_dir / "versions"

    def has_json(name):
        return (vdir / name / f"{name}.json").exists()

    if loader == "vanilla":
        return mc_version if has_json(mc_version) else None
    try:
        dirs = [d for d in vdir.iterdir() if d.is_dir() and has_json(d.name)]
    except OSError:
        return None
    cands = []
    for d in dirs:
        n = d.name
        try:
            inh = json.loads((d / f"{n}.json").read_text(encoding="utf-8")).get("inheritsFrom")
        except Exception:
            inh = None
        if loader == "fabric":
            ok = (m := re.match(r"^fabric-loader-([\d.]+)-(.+)$", n)) and m.group(2) == mc_version
        elif loader == "quilt":
            ok = (m := re.match(r"^quilt-loader-([\d.]+)-(.+)$", n)) and m.group(2) == mc_version
        elif loader == "forge":
            ok = ("forge" in n.lower() and "neoforge" not in n.lower()
                  and (inh == mc_version or n.startswith(mc_version + "-")))
        elif loader == "neoforge":
            ok = n.lower().startswith("neoforge-") and (inh == mc_version or inh is None and mc_version in n)
        else:
            ok = False
        if ok:
            cands.append((n, (d / f"{n}.json").stat().st_mtime))
    if not cands:
        return None
    cands.sort(key=lambda x: x[1], reverse=True)
    return cands[0][0]


def game_dir_for(mc_dir: Path, loader: str, mc_version: str, isolate: bool = True) -> Path:
    """Thư mục chơi (mods, saves…). Loader có mod được tách riêng theo phiên bản để mod không lẫn nhau."""
    if loader == "vanilla" or not isolate:
        return mc_dir
    return mc_dir / "instances" / f"{loader}-{mc_version}"


# ==========================================================================
# TỐI ƯU RIÊNG CHO LINUX
# ==========================================================================
IS_LINUX = sys.platform.startswith("linux")
_PCI_VENDOR = {"0x10de": "nvidia", "0x1002": "amd", "0x1022": "amd", "0x8086": "intel"}

# (khoá config, khoá i18n, mặc định, lệnh cần có)
LINUX_TWEAKS = [
    ("linux_gamemode",      "tw_gamemode",      True,  "gamemoderun"),
    ("linux_mangohud",      "tw_mangohud",      False, "mangohud"),
    ("linux_glthread",      "tw_glthread",      True,  None),
    ("linux_shader_cache",  "tw_shader_cache",  True,  None),
    ("linux_allocator",     "tw_allocator",     True,  None),
    ("linux_thp",           "tw_thp",           True,  None),
    ("linux_dgpu",          "tw_dgpu",          False, None),
    ("linux_no_vsync",      "tw_no_vsync",      False, None),
    ("linux_wm_fix",        "tw_wm_fix",        True,  None),
    ("linux_system_glfw",   "tw_system_glfw",   False, None),
    ("linux_high_priority", "tw_high_priority", False, "nice"),
    ("linux_zgc",           "tw_zgc",           False, None),
]

# Tinh chỉnh riêng cho Windows (key config, key i18n, mặc định, lệnh cần có)
WIN_TWEAKS = [
    ("win_gpu_pref",      "tw_gpu_pref",      True,  None),
    ("win_gamemode",      "tw_win_gamemode",  True,  None),
    ("win_high_priority", "tw_win_priority",  True,  None),
    ("win_power_plan",    "tw_power_plan",    False, None),
    ("win_disable_dvr",   "tw_disable_dvr",   False, None),
    ("win_disable_fso",   "tw_disable_fso",   False, None),
    ("win_zgc",           "tw_zgc",           False, None),
]
ALL_TWEAKS = LINUX_TWEAKS + WIN_TWEAKS
PLATFORM_TWEAKS = WIN_TWEAKS if IS_WINDOWS else LINUX_TWEAKS

_ALLOCATORS = ["libjemalloc.so.2", "libjemalloc.so", "libmimalloc.so.2", "libmimalloc.so"]
_LIB_DIRS = ["/usr/lib", "/usr/lib64", "/usr/local/lib", "/usr/lib/x86_64-linux-gnu",
             "/lib/x86_64-linux-gnu", "/usr/lib/aarch64-linux-gnu"]


def detect_session_type() -> str:
    xdg = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if xdg in ("wayland", "x11"):
        return xdg
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "unknown"


def detect_gpu_vendors() -> list:
    if IS_WINDOWS:
        return winsys.gpu_vendors(winsys.gpu_names())
    found = []
    try:
        for p in sorted(Path("/sys/class/drm").glob("card*/device/vendor")):
            name = _PCI_VENDOR.get(p.read_text(errors="ignore").strip().lower())
            if name and name not in found:
                found.append(name)
    except Exception:
        pass
    if not found and shutil.which("lspci"):
        try:
            out = subprocess.run(["lspci"], capture_output=True, text=True, timeout=5).stdout.lower()
            for line in out.splitlines():
                if "vga" in line or "3d controller" in line or "display" in line:
                    for key, name in (("nvidia", "nvidia"), ("amd", "amd"),
                                      ("ati", "amd"), ("intel", "intel")):
                        if key in line and name not in found:
                            found.append(name)
        except Exception:
            pass
    return found


def detect_cpu_governor():
    if IS_WINDOWS:
        return winsys.active_power_name()      # trên Windows, "governor" là power plan
    try:
        return Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor").read_text().strip()
    except Exception:
        return None


def detect_total_ram_mb() -> int:
    if IS_WINDOWS:
        return winsys.memory_status_mb()[0]
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
    except Exception:
        pass
    return 0


def detect_available_ram_mb() -> int:
    if IS_WINDOWS:
        return winsys.memory_status_mb()[1]
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except Exception:
        pass
    return 0


def suggest_ram_mb() -> int:
    total = detect_total_ram_mb()
    if not total:
        return 3072
    return max(2048, min(8192, (int(total * 0.45) // 512) * 512))


def thp_available() -> bool:
    try:
        return "[never]" not in Path("/sys/kernel/mm/transparent_hugepage/enabled").read_text()
    except Exception:
        return False


def numa_nodes() -> int:
    try:
        return max(1, len(list(Path("/sys/devices/system/node").glob("node[0-9]*"))))
    except Exception:
        return 1


def _ldconfig_lines() -> list:
    try:
        ld = shutil.which("ldconfig") or "/sbin/ldconfig"
        return subprocess.run([ld, "-p"], capture_output=True, text=True, timeout=5).stdout.splitlines()
    except Exception:
        return []


def find_allocator_preload():
    for d in _LIB_DIRS:
        for name in _ALLOCATORS:
            p = Path(d) / name
            if p.exists():
                return str(p)
    lines = _ldconfig_lines()
    for name in _ALLOCATORS:
        for line in lines:
            if name in line and "=>" in line:
                return line.split("=>")[-1].strip()
    return None


def find_system_glfw():
    for d in _LIB_DIRS:
        for name in ("libglfw.so.3", "libglfw.so"):
            p = Path(d) / name
            if p.exists():
                return str(p)
    return None


def tweak_on(cfg, key) -> bool:
    for k, _i, default, _n in ALL_TWEAKS:
        if k == key:
            return bool(cfg.get(key, default))
    return bool(cfg.get(key, False))


def build_launch_env(cfg) -> dict:
    env = os.environ.copy()
    if not IS_LINUX:
        return env
    env.pop("_JAVA_OPTIONS", None)       # hay đè lên -Xmx của launcher
    env.pop("JAVA_TOOL_OPTIONS", None)
    vendors = detect_gpu_vendors()

    if tweak_on(cfg, "linux_glthread"):
        env["mesa_glthread"] = "true"
        env["__GL_THREADED_OPTIMIZATIONS"] = "1"
    if tweak_on(cfg, "linux_shader_cache"):
        try:
            SHADER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        env["MESA_SHADER_CACHE_DIR"] = str(SHADER_CACHE_DIR)
        env["MESA_SHADER_CACHE_MAX_SIZE"] = "4G"
        env["__GL_SHADER_DISK_CACHE"] = "1"
        env["__GL_SHADER_DISK_CACHE_SKIP_CLEANUP"] = "1"
        env["__GL_SHADER_DISK_CACHE_PATH"] = str(SHADER_CACHE_DIR)
    if tweak_on(cfg, "linux_no_vsync"):
        env["vblank_mode"] = "0"
        env["__GL_SYNC_TO_VBLANK"] = "0"
    if tweak_on(cfg, "linux_wm_fix"):
        env["_JAVA_AWT_WM_NONREPARENTING"] = "1"
    if tweak_on(cfg, "linux_dgpu"):
        if "nvidia" in vendors:
            env["__NV_PRIME_RENDER_OFFLOAD"] = "1"
            env["__GLX_VENDOR_LIBRARY_NAME"] = "nvidia"
            env["__VK_LAYER_NV_optimus"] = "NVIDIA_only"
        else:
            env["DRI_PRIME"] = "1"
    if tweak_on(cfg, "linux_allocator"):
        lib = find_allocator_preload()
        if lib:
            env["LD_PRELOAD"] = (env.get("LD_PRELOAD", "") + " " + lib).strip()
    return env


def build_launch_prefix(cfg) -> list:
    if not IS_LINUX:
        return []
    prefix = []
    if tweak_on(cfg, "linux_gamemode") and shutil.which("gamemoderun"):
        prefix.append("gamemoderun")
    if tweak_on(cfg, "linux_mangohud") and shutil.which("mangohud"):
        prefix.append("mangohud")
    if tweak_on(cfg, "linux_dgpu") and shutil.which("prime-run") and "nvidia" in detect_gpu_vendors():
        prefix.insert(0, "prime-run")
    if tweak_on(cfg, "linux_high_priority") and shutil.which("nice"):
        prefix = ["nice", "-n", "-5"] + prefix
    return prefix


BASE_JVM_ARGS_G1 = [
    "-XX:+UseG1GC", "-XX:+ParallelRefProcEnabled", "-XX:MaxGCPauseMillis=200",
    "-XX:+UnlockExperimentalVMOptions", "-XX:+DisableExplicitGC", "-XX:+AlwaysPreTouch",
    "-XX:G1NewSizePercent=30", "-XX:G1MaxNewSizePercent=40", "-XX:G1HeapRegionSize=8M",
    "-XX:G1ReservePercent=20", "-XX:G1HeapWastePercent=5", "-XX:G1MixedGCCountTarget=4",
    "-XX:InitiatingHeapOccupancyPercent=15", "-XX:G1MixedGCLiveThresholdPercent=90",
    "-XX:G1RSetUpdatingPauseTimePercent=5", "-XX:SurvivorRatio=32",
    "-XX:+PerfDisableSharedMem", "-XX:MaxTenuringThreshold=1",
]
BASE_JVM_ARGS_ZGC = ["-XX:+UnlockExperimentalVMOptions", "-XX:+UseZGC",
                     "-XX:+DisableExplicitGC", "-XX:+AlwaysPreTouch", "-XX:+PerfDisableSharedMem"]


def clamp_ram_mb(ram: int) -> int:
    """Không cấp quá 75% RAM máy — vượt là OOM-killer của Linux giết game."""
    total = detect_total_ram_mb()
    if total and ram > int(total * 0.75):
        return max(1024, (int(total * 0.75) // 512) * 512)
    return ram


def jvm_args(ram: int, cfg, java_major=None) -> list:
    ram = clamp_ram_mb(int(ram))
    zgc_key = "win_zgc" if IS_WINDOWS else "linux_zgc"
    if tweak_on(cfg, zgc_key) and ram >= 8192 and (not java_major or java_major >= 17):
        args = [f"-Xms{ram}M", f"-Xmx{ram}M"] + list(BASE_JVM_ARGS_ZGC)
        if java_major and java_major <= 23:
            args.append("-XX:+ZGenerational")
    else:
        args = [f"-Xms{ram}M", f"-Xmx{ram}M"] + list(BASE_JVM_ARGS_G1)
    if IS_LINUX and tweak_on(cfg, "linux_thp"):
        if thp_available():
            args.append("-XX:+UseTransparentHugePages")
        if numa_nodes() > 1:
            args += ["-XX:+UseNUMA", "-XX:+UseNUMAInterleaving"]
    if IS_LINUX or IS_WINDOWS:
        args.append("-Dorg.lwjgl.util.NoChecks=true")
        args.append("-Dlog4j2.formatMsgNoLookups=true")   # vá Log4Shell cho các bản MC 1.12–1.18 cũ
    if IS_LINUX and tweak_on(cfg, "linux_system_glfw"):
        glfw = find_system_glfw()
        if glfw:
            args.append(f"-Dorg.lwjgl.glfw.libname={glfw}")
    return args


linux_jvm_args = jvm_args        # tên cũ, giữ để tương thích


def hw_summary() -> dict:
    if IS_WINDOWS:
        names = winsys.gpu_names()
        vendors = winsys.gpu_vendors(names)
        return {
            "gpu": " + ".join(names) or "?",
            "hybrid": len(vendors) > 1,
            "session": winsys.windows_label(),
            "cores": os.cpu_count() or 0,
            "gov": winsys.active_power_name(),
            "ram": detect_total_ram_mb(),
            "suggest_ram": suggest_ram_mb(),
            "gamemode": True, "mangohud": False, "allocator": None, "glfw": None,
        }
    return linux_hw_summary()


def linux_hw_summary() -> dict:
    gpus = detect_gpu_vendors()
    return {
        "gpu": " + ".join(g.upper() for g in gpus) or "?",
        "hybrid": len(gpus) > 1,
        "session": detect_session_type(),
        "cores": os.cpu_count() or 0,
        "gov": detect_cpu_governor() or "?",
        "ram": detect_total_ram_mb(),
        "suggest_ram": suggest_ram_mb(),
        "gamemode": bool(shutil.which("gamemoderun")),
        "mangohud": bool(shutil.which("mangohud")),
        "allocator": find_allocator_preload(),
        "glfw": find_system_glfw(),
    }


def describe_launch_setup(cfg) -> list:
    lines = []
    if IS_WINDOWS:
        return lines            # phần Windows do prepare_windows_launch() tự ghi log
    prefix = build_launch_prefix(cfg)
    if prefix:
        lines.append("wrapper: " + " ".join(prefix))
    env = build_launch_env(cfg)
    watch = ["mesa_glthread", "__GL_THREADED_OPTIMIZATIONS", "vblank_mode", "__GL_SYNC_TO_VBLANK",
             "DRI_PRIME", "__NV_PRIME_RENDER_OFFLOAD", "LD_PRELOAD", "MESA_SHADER_CACHE_DIR",
             "_JAVA_AWT_WM_NONREPARENTING"]
    shown = [f"{k}={env[k]}" for k in watch if k in env and env[k] != os.environ.get(k)]
    if shown:
        lines.append("env: " + "  ".join(shown))
    gov = detect_cpu_governor()
    if gov in ("powersave", "conservative") and not shutil.which("gamemoderun"):
        lines.append(f"CPU governor = {gov}: cài «gamemode» hoặc đổi sang «performance» để hết tụt FPS.")
    return lines


GAMING_PACKAGES = {
    "pacman": ["gamemode", "mangohud", "jemalloc"],
    "apt": ["gamemode", "mangohud", "libjemalloc2"],
    "dnf": ["gamemode", "mangohud", "jemalloc"],
    "zypper": ["gamemode", "mangohud", "jemalloc"],
    "xbps": ["gamemode", "MangoHud", "jemalloc"],
}


def install_gaming_tools(log=_default_log) -> bool:
    osinfo = detect_os()
    if osinfo.get("immutable") or osinfo.get("pkg_manager") not in GAMING_PACKAGES:
        return False
    return install_system_packages(osinfo, GAMING_PACKAGES, lambda m: log(m, "dim"))


# ==========================================================================
# WINDOWS: chuẩn bị trước khi chạy game / dọn sau khi game tắt
# ==========================================================================
def apply_windows_tweak(cfg, key: str, on: bool, java_exe=None) -> None:
    """Áp / hoàn tác ngay một tuỳ chọn Windows khi người dùng bật tắt công tắc."""
    if not IS_WINDOWS:
        return
    if key in winsys.GLOBAL_REG:
        (winsys.apply_global if on else winsys.restore_global)(key)
    elif java_exe and key == "win_gpu_pref":
        winsys.set_gpu_preference(java_exe, on)
    elif java_exe and key == "win_disable_fso":
        winsys.set_fullscreen_opt_disabled(java_exe, on)


def prepare_windows_launch(cfg, java_exe, log=_default_log):
    """Áp các tối ưu Windows trước khi chạy game. Trả về (creationflags cho Popen, hàm dọn_sau_khi_game_tắt)."""
    if not IS_WINDOWS:
        return 0, (lambda: None)
    done = []
    if tweak_on(cfg, "win_gpu_pref") and winsys.set_gpu_preference(java_exe, True):
        done.append("GPU hiệu năng cao")
    if tweak_on(cfg, "win_gamemode") and winsys.apply_global("win_gamemode"):
        done.append("Game Mode")
    if tweak_on(cfg, "win_disable_dvr") and winsys.apply_global("win_disable_dvr"):
        done.append("tắt Game DVR")
    if tweak_on(cfg, "win_disable_fso") and winsys.set_fullscreen_opt_disabled(java_exe, True):
        done.append("tắt Fullscreen Optimizations")
    restore = False
    if tweak_on(cfg, "win_power_plan"):
        plan = winsys.boost_power_plan()
        if plan:
            restore = True
            done.append(f"power plan {plan}")
        else:
            log("Power plan: giữ nguyên (đã ở chế độ cao hoặc máy không có plan hiệu năng cao).", "dim")
    prio = tweak_on(cfg, "win_high_priority")
    if prio:
        done.append("ưu tiên CPU")
    if done:
        log("Tối ưu Windows: " + ", ".join(done), "dim")
    return winsys.game_creationflags(prio), (winsys.restore_power_plan if restore else (lambda: None))


# ==========================================================================
# CẤU HÌNH
# ==========================================================================
_cfg_lock = threading.Lock()


def default_config() -> dict:
    return {
        "mc_dir": str(DEFAULT_MC_DIR), "java_path": "java", "ram_mb": 3072,
        "username": "Player", "azure_client_id": "",
        "accounts": [], "active_account": "",
        "shortcut_opt_out": False,
        "mc_version": DEFAULT_MC_VERSION,
        "lang": "auto", "lang_detected": "",
        "java_major": 21,
        # giao diện
        "sound": True, "sound_volume": 60, "glass_opacity": 88,
        "bg_anim": True, "minimize_on_launch": False, "translucent": "auto",
        **{key: default for key, _i, default, _n in ALL_TWEAKS},
    }


def load_config() -> dict:
    cfg = default_config()
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    cfg.update(data)
            except Exception:
                # file hỏng: giữ lại bản sao để người dùng cứu, rồi dùng mặc định
                try:
                    shutil.copy2(CONFIG_FILE, CONFIG_FILE.with_suffix(".json.bad"))
                except Exception:
                    pass
    except Exception:
        pass
    if cfg.get("mc_version") not in MC_VERSIONS:
        MC_VERSIONS.append(str(cfg.get("mc_version") or DEFAULT_MC_VERSION))
    migrate_accounts(cfg)
    return cfg


# ==========================================================================
# TÀI KHOẢN (nhiều tài khoản offline + Microsoft)
# ==========================================================================
def new_account_id() -> str:
    return uuid.uuid4().hex[:8]


def migrate_accounts(cfg: dict) -> None:
    """Đảm bảo cfg['accounts'] hợp lệ. Cấu hình cũ (username / ms_refresh / ms_client) được đổi thành danh sách tài khoản."""
    accs = cfg.get("accounts")
    clean = []
    if isinstance(accs, list):
        for a in accs:
            if isinstance(a, dict) and a.get("type") in ("offline", "microsoft") and a.get("name"):
                a.setdefault("id", new_account_id())
                clean.append(a)
    if not clean:
        if cfg.get("ms_refresh") and cfg.get("ms_client"):
            clean.append({"id": new_account_id(), "type": "microsoft",
                          "name": str(cfg.get("username") or "Player"), "uuid": None,
                          "refresh": cfg["ms_refresh"], "client": cfg["ms_client"]})
        else:
            clean.append({"id": new_account_id(), "type": "offline",
                          "name": valid_username(cfg.get("username", "Player"))})
    for k in ("ms_refresh", "ms_client"):
        cfg.pop(k, None)
    cfg["accounts"] = clean
    if cfg.get("active_account") not in {a["id"] for a in clean}:
        cfg["active_account"] = clean[0]["id"]
    active = next(a for a in clean if a["id"] == cfg["active_account"])
    cfg["username"] = active["name"]


def save_config(cfg: dict) -> None:
    """Ghi nguyên tử (file tạm + replace) để mất điện/crash không làm hỏng config."""
    with _cfg_lock:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            tmp = CONFIG_FILE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
            try:
                os.chmod(tmp, 0o600)   # có thể chứa refresh token đăng nhập
            except OSError:
                pass
            os.replace(tmp, CONFIG_FILE)
        except Exception as e:
            write_error_log("Lưu cấu hình", exc=e)


def ensure_minecraft_dir(mc_dir: Path, instance: bool = False) -> dict:
    """instance=True: thư mục chơi riêng (không cần versions/, vì dùng chung versions của .minecraft chính)."""
    first_time = not mc_dir.exists()
    mc_dir.mkdir(parents=True, exist_ok=True)
    created = []
    for d in REQUIRED_MC_SUBDIRS:
        if instance and d == "versions":
            continue
        sub = mc_dir / d
        if not sub.exists():
            sub.mkdir(parents=True, exist_ok=True)
            created.append(d)
    opt = mc_dir / "options.txt"
    if first_time and not opt.exists():
        try:
            opt.write_text("", encoding="utf-8")
        except Exception:
            pass
    return {"first_time": first_time, "created": created}


def scan_category(mc_dir: Path, key: str, exts: set) -> list:
    """Danh sách (tên, kích thước byte, là_thư_mục) trong 1 thư mục con của .minecraft."""
    out = []
    p = mc_dir / key
    try:
        if p.is_dir():
            for item in p.iterdir():
                try:
                    if item.is_dir():
                        out.append((item.name, 0, True))
                    elif item.suffix.lower() in exts:
                        out.append((item.name, item.stat().st_size, False))
                except OSError:
                    continue
    except OSError:
        pass
    out.sort(key=lambda t: t[0].lower())
    return out


def human_size(n: int) -> str:
    f = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if f < 1024 or unit == "GB":
            return f"{int(f)} {unit}" if unit == "B" else f"{f:.1f} {unit}"
        f /= 1024
    return f"{n} B"


# ==========================================================================
# SHORTCUT .desktop (XDG)
# ==========================================================================
SHORTCUT_DESKTOP_ID = f"{APP_ID}.desktop"


def _desktop_quote(value: str) -> str:
    if re.search(r"""[\s"'\\$`<>~|&;*?!#()\[\]{}]""", value):
        esc = value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
        return f'"{esc}"'
    return value


def _xdg_data_home() -> Path:
    v = os.environ.get("XDG_DATA_HOME")
    return Path(v) if v and os.path.isabs(v) else Path.home() / ".local" / "share"


def linux_applications_dir() -> Path:
    return _xdg_data_home() / "applications"


def linux_desktop_dir() -> Path:
    try:
        r = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, timeout=4)
        p = Path((r.stdout or "").strip())
        if r.returncode == 0 and str(p) and p.exists():
            return p
    except Exception:
        pass
    dirs_file = Path.home() / ".config" / "user-dirs.dirs"
    try:
        for line in dirs_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("XDG_DESKTOP_DIR="):
                raw = line.split("=", 1)[1].strip().strip('"').replace("$HOME", str(Path.home()))
                if Path(raw).exists():
                    return Path(raw)
    except Exception:
        pass
    for name in ("Desktop", "Máy tính", "Bàn làm việc", "Schreibtisch", "Bureau", "Escritorio", "Pulpit"):
        if (Path.home() / name).is_dir():
            return Path.home() / name
    return Path.home() / "Desktop"


def install_linux_icons() -> str:
    """Xuất icon vào hicolor bằng Qt (không cần Pillow)."""
    if not ICON_PATH.exists():
        return "applications-games"
    try:
        from PyQt6.QtGui import QImage
        from PyQt6.QtCore import Qt
        src = QImage(str(ICON_PATH))
        root = _xdg_data_home() / "icons" / "hicolor"
        for size in (16, 24, 32, 48, 64, 128, 256):
            dest = root / f"{size}x{size}" / "apps" / f"{APP_ID}.png"
            dest.parent.mkdir(parents=True, exist_ok=True)
            src.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                       Qt.TransformationMode.SmoothTransformation).save(str(dest), "PNG")
        try:
            subprocess.run(["gtk-update-icon-cache", "-f", "-t", str(root)],
                           capture_output=True, timeout=8)
        except Exception:
            pass
        return APP_ID
    except Exception:
        return str(ICON_PATH)


def _exec_line() -> str:
    if FROZEN:
        return _desktop_quote(sys.executable)
    script = APP_DIR / "arch_laucher.py"
    return f"{_desktop_quote(sys.executable)} {_desktop_quote(str(script))}"


def build_desktop_entry(icon: str) -> str:
    return (
        "[Desktop Entry]\nVersion=1.0\nType=Application\n"
        f"Name={APP_NAME}\nGenericName=Minecraft Launcher\n"
        "Comment=Minecraft Fabric launcher\n"
        f"Exec={_exec_line()}\nIcon={icon}\nPath={APP_DIR}\n"
        "Terminal=false\nStartupNotify=true\nCategories=Game;ActionGame;\n"
        f"Keywords=minecraft;fabric;launcher;arch-client;\nStartupWMClass={APP_ID}\n"
    )


def _trust_desktop_file(path: Path) -> None:
    try:
        os.chmod(path, 0o755)
    except Exception:
        pass
    for val in ("true", "yes"):
        try:
            subprocess.run(["gio", "set", str(path), "metadata::trusted", val],
                           capture_output=True, timeout=4)
        except Exception:
            pass


def shortcut_locations() -> dict:
    if IS_WINDOWS:
        return {k: str(v) for k, v in winsys.shortcut_paths().items()}
    return {"desktop": str(linux_desktop_dir() / SHORTCUT_DESKTOP_ID),
            "menu": str(linux_applications_dir() / SHORTCUT_DESKTOP_ID)}


def shortcuts_present() -> bool:
    return any(Path(p).exists() for p in shortcut_locations().values())


def shortcuts_stale() -> bool:
    """Có shortcut nhưng trỏ sai (vd đã di chuyển thư mục launcher) -> cần ghi lại."""
    if IS_WINDOWS:
        return winsys.shortcuts_stale()
    try:
        text = (linux_applications_dir() / SHORTCUT_DESKTOP_ID).read_text(encoding="utf-8")
    except OSError:
        return False
    return f"Exec={_exec_line()}\n" not in text


def install_shortcuts() -> list:
    if IS_WINDOWS:
        return winsys.install_shortcuts()
    apps = linux_applications_dir()
    apps.mkdir(parents=True, exist_ok=True)
    text = build_desktop_entry(install_linux_icons())
    written = []
    app_file = apps / SHORTCUT_DESKTOP_ID
    app_file.write_text(text, encoding="utf-8")
    os.chmod(app_file, 0o755)
    written.append(str(app_file))
    desktop = linux_desktop_dir()
    try:
        desktop.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    if desktop.exists():
        f = desktop / SHORTCUT_DESKTOP_ID
        f.write_text(text, encoding="utf-8")
        _trust_desktop_file(f)
        written.append(str(f))
    for cmd in (["update-desktop-database", str(apps)], ["xdg-desktop-menu", "forceupdate"],
                ["kbuildsycoca6"], ["kbuildsycoca5"]):      # KDE: làm mới menu ứng dụng ngay
        if not shutil.which(cmd[0]):
            continue
        try:
            subprocess.run(cmd, capture_output=True, timeout=8)
        except Exception:
            pass
    return written


def remove_shortcuts() -> list:
    if IS_WINDOWS:
        return winsys.remove_shortcuts()
    removed = []
    for p in shortcut_locations().values():
        path = Path(p)
        if path.exists():
            path.unlink()
            removed.append(str(path))
    return removed


# ==========================================================================
# JAVA
# ==========================================================================
def find_bundled_java(major=None):
    """Java portable do launcher tải. major=None: bản mới nhất; có major: đúng bản đó."""
    if not JRE_DIR.exists():
        return None
    if major is not None:
        exe = JRE_DIR / f"jdk-{int(major)}" / "bin" / JAVA_EXE
        return exe if exe.is_file() else None
    matches = [p for p in JRE_DIR.rglob(JAVA_EXE) if p.parent.name == "bin" and p.is_file()]
    if not matches:
        return None
    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0]


def find_any_java(need: int):
    """Tìm Java thoả `need`: bản portable đúng major, rồi các JDK hệ thống (/usr/lib/jvm…), rồi `java` trong PATH."""
    cands = []
    p = find_bundled_java(need)
    if p:
        cands.append(p)
    if IS_WINDOWS:
        for d in winsys.system_java_dirs():
            exe = d / "bin" / JAVA_EXE
            if exe.is_file():
                cands.append(exe)
    else:
        for base in ("/usr/lib/jvm", "/usr/lib64/jvm", "/usr/java", str(Path.home() / ".sdkman/candidates/java")):
            try:
                for d in sorted(Path(base).iterdir()):
                    exe = d / "bin" / "java"
                    if exe.is_file() and os.access(exe, os.X_OK):
                        cands.append(exe)
            except OSError:
                pass
    sysjava = shutil.which("java")
    if sysjava:
        cands.append(Path(sysjava))
    first = None
    for exe in cands:
        v = get_java_version(exe)
        if v and java_acceptable(v, need):
            if v == need:
                return exe, v
            first = first or (exe, v)
    return first


def get_java_version(java_exe):
    try:
        r = subprocess.run([str(java_exe), "-version"], capture_output=True, text=True, timeout=15,
                           **hidden_kwargs())
        out = (r.stdout or "") + (r.stderr or "")
        m = re.search(r'version\s+"(\d+)(?:\.(\d+))?', out) or re.search(r"(\d+)\.(\d+)\.\d+", out)
        if not m:
            return None
        major = int(m.group(1))
        if major == 1 and m.group(2):       # Java 8 và cũ hơn ghi "1.8.0_402" -> 8
            return int(m.group(2))
        return major
    except Exception:
        return None


def resolve_java_path(configured: str):
    configured = (configured or "").strip() or "java"
    if os.path.isabs(configured) and os.access(configured, os.X_OK):
        return configured
    return shutil.which(configured)


def adoptium_info(java_major: int):
    """(url, tên file, sha256) của OpenJDK Temurin hợp với máy, hoặc (None,)*3."""
    machine = platform.machine().lower()
    if machine in ("amd64", "x86_64"):
        arch = "x64"
    elif machine in ("arm64", "aarch64"):
        arch = "aarch64"
    else:
        return None, None, None
    os_name = "windows" if IS_WINDOWS else "alpine-linux" if detect_os().get("musl") else "linux"
    ext = ".zip" if IS_WINDOWS else ".tar.gz"
    api = (f"https://api.adoptium.net/v3/assets/latest/{java_major}/hotspot"
           f"?architecture={arch}&image_type=jdk&os={os_name}&vendor=eclipse")
    try:
        r = requests.get(api, timeout=20, headers={"User-Agent": UA})
        r.raise_for_status()
        for item in r.json():
            pkg = (item.get("binary") or {}).get("package") or {}
            if pkg.get("link") and pkg.get("name", "").endswith(ext):
                return pkg["link"], pkg["name"], pkg.get("checksum")
    except Exception:
        pass
    url = (f"https://api.adoptium.net/v3/binary/latest/{java_major}/ga/{os_name}/{arch}"
           f"/jdk/hotspot/normal/eclipse?project=jdk")
    return url, f"openjdk{java_major}{ext}", None


def download_file(url, dest: Path, progress=None, sha256=None, sha512=None,
                  headers=None, timeout=60) -> Path:
    """Tải về file .part rồi đổi tên — không bao giờ để lại file nửa vời. Kiểm tra hash nếu có."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    h256 = hashlib.sha256() if sha256 else None
    h512 = hashlib.sha512() if sha512 else None
    hdr = {"User-Agent": UA}
    hdr.update(headers or {})
    try:
        with requests.get(url, stream=True, timeout=timeout, allow_redirects=True, headers=hdr) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length") or 0)
            done = 0
            with open(part, "wb") as f:
                for chunk in r.iter_content(chunk_size=256 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    if h256:
                        h256.update(chunk)
                    if h512:
                        h512.update(chunk)
                    if progress:
                        progress(done, total)
        if h256 and h256.hexdigest().lower() != str(sha256).lower():
            raise IOError("Sai checksum SHA-256 — file tải về bị hỏng")
        if h512 and h512.hexdigest().lower() != str(sha512).lower():
            raise IOError("Sai checksum SHA-512 — file tải về bị hỏng")
        os.replace(part, dest)
        return dest
    finally:
        try:
            if part.exists():
                part.unlink()
        except Exception:
            pass


def safe_extract_tar(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    with tarfile.open(archive) as t:
        for m in t.getmembers():
            target = (dest / m.name).resolve()
            if not str(target).startswith(str(root)):
                raise IOError(f"Tệp nén chứa đường dẫn nguy hiểm: {m.name}")
        try:
            t.extractall(dest, filter="data")  # Python 3.12+
        except TypeError:
            t.extractall(dest)


def safe_extract_zip(archive: Path, dest: Path) -> None:
    import zipfile
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            target = (dest / name).resolve()
            if target != root and root not in target.parents:
                raise IOError(f"Tệp nén chứa đường dẫn nguy hiểm: {name}")
        z.extractall(dest)


def _extract_archive(archive: Path, dest: Path) -> None:
    if str(archive).lower().endswith(".zip"):
        safe_extract_zip(archive, dest)
    else:
        safe_extract_tar(archive, dest)


JAVA_PKG = {
    "pacman": lambda v: [f"jdk{v}-openjdk"],
    "apt": lambda v: [f"openjdk-{v}-jdk"],
    "dnf": lambda v: [f"java-{v}-openjdk-devel"],
    "zypper": lambda v: [f"java-{v}-openjdk-devel"],
    "xbps": lambda v: [f"openjdk{v}"],
    "apk": lambda v: [f"openjdk{v}-jdk"],
}


def install_java_via_pkg_manager(java_major: int, log=_default_log) -> bool:
    if IS_WINDOWS:
        return winsys.winget_install_java(java_major, log)
    osinfo = detect_os()
    pm = osinfo.get("pkg_manager")
    if osinfo.get("immutable") or pm not in JAVA_PKG:
        return False
    return install_system_packages(osinfo, {pm: JAVA_PKG[pm](java_major)}, lambda m: log(m, "dim"))


def install_java_portable(java_major: int, log=_default_log, progress=None):
    """Tải Temurin về thư mục cấu hình của launcher (không cần root / admin, mọi distro và Windows)."""
    if requests is None:
        raise RuntimeError("Thiếu thư viện 'requests'")
    url, name, sha = adoptium_info(java_major)
    if not url:
        raise RuntimeError("Kiến trúc CPU này chưa được hỗ trợ tự động cài Java")
    JRE_DIR.mkdir(parents=True, exist_ok=True)
    archive = JRE_DIR / (name or f"openjdk{java_major}{'.zip' if IS_WINDOWS else '.tar.gz'}")
    log(f"Đang tải OpenJDK {java_major} (Eclipse Temurin)…", "info")
    last = [-10]

    def prog(done, total):
        if progress:
            progress(done, total)
        if total:
            pct = done * 100 // total
            if pct - last[0] >= 20:
                last[0] = pct
                log(f"  {pct}%  ({done >> 20} / {total >> 20} MB)", "dim")

    download_file(url, archive, progress=prog, sha256=sha)
    log("Đang giải nén Java…", "info")
    tmp = JRE_DIR / f".extract-{int(java_major)}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        _extract_archive(archive, tmp)
        tops = [p for p in tmp.iterdir() if (p / "bin" / JAVA_EXE).exists()]
        if not tops:
            raise RuntimeError("Đã giải nén nhưng không thấy file java")
        dest = JRE_DIR / f"jdk-{int(java_major)}"
        shutil.rmtree(dest, ignore_errors=True)      # chỉ thay đúng bản cùng major, các major khác giữ nguyên
        shutil.move(str(tops[0]), str(dest))
    finally:
        archive.unlink(missing_ok=True)
        shutil.rmtree(tmp, ignore_errors=True)
    exe = dest / "bin" / JAVA_EXE
    if not IS_WINDOWS:
        os.chmod(exe, 0o755)
    return exe


# ==========================================================================
# FABRIC / PHIÊN BẢN
# ==========================================================================
def offline_uuid(name: str) -> str:
    """UUID offline giống Minecraft: nameUUIDFromBytes('OfflinePlayer:<tên>')."""
    digest = bytearray(hashlib.md5(("OfflinePlayer:" + name).encode("utf-8")).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(digest)))


def valid_username(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]", "", name or "")[:16]
    return name if len(name) >= 3 else "Player"


# ==========================================================================
# MODRINTH
# ==========================================================================
MODRINTH_API = "https://api.modrinth.com/v2"


def _mr_get(path, **kw):
    if requests is None:
        raise RuntimeError("Thiếu thư viện 'requests'")
    kw.setdefault("timeout", 20)
    r = requests.get(MODRINTH_API + path, headers={"User-Agent": UA}, **kw)
    r.raise_for_status()
    return r.json()


def modrinth_search(query, ptype, mc_version, offset=0, limit=20, loader="fabric"):
    facets = [[f"project_type:{ptype}"], [f"versions:{mc_version}"]]
    if ptype == "mod":
        loaders = MODRINTH_LOADERS.get(loader)
        if not loaders:        # vanilla: không có mod
            return [], 0
        facets.insert(1, [f"categories:{x}" for x in loaders])
    data = _mr_get("/search", params={
        "query": query, "limit": limit, "offset": offset,
        "index": "relevance" if query else "downloads",
        "facets": json.dumps(facets)})
    return data.get("hits") or [], int(data.get("total_hits") or 0)


def modrinth_versions(project, mc_version=None, loaders=None):
    params = {}
    if loaders:
        params["loaders"] = json.dumps(list(loaders))
    if mc_version:
        params["game_versions"] = json.dumps([mc_version])
    return _mr_get(f"/project/{project}/version", params=params) or []


def _pick_file(version: dict):
    files = version.get("files") or []
    if not files:
        return None
    return next((f for f in files if f.get("primary")), files[0])


class ModrinthInstaller:
    """Cài mod / resource pack / shader về đúng thư mục, kèm phụ thuộc bắt buộc.

    * Ghi lại file đã cài vào ``.archclient-installed.json`` trong .minecraft để
      nâng cấp đúng file cũ (không xoá nhầm mod khác trùng tên).
    * Tải qua file .part + kiểm tra SHA-512 nên không bao giờ có .jar hỏng.
    * Phụ thuộc có ghim phiên bản (vd Iris ghim bản Sodium) được cài đúng bản ghim.
    """

    FOLDER = {"mod": "mods", "resourcepack": "resourcepacks", "shader": "shaderpacks"}

    def __init__(self, mc_dir: Path, mc_version: str, log=_default_log, progress=None, loader="fabric"):
        self.mc_dir = Path(mc_dir)          # thư mục chơi (game dir), nơi có mods/…
        self.mc_version = mc_version
        self.loaders = MODRINTH_LOADERS.get(loader, ["fabric"])
        self.log = log
        self.progress = progress
        self.manifest_path = self.mc_dir / ".archclient-installed.json"
        self.manifest = self._load()
        self._seen: set = set()

    # ---- manifest
    def _load(self) -> dict:
        try:
            d = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def _save(self) -> None:
        try:
            tmp = self.manifest_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.manifest, indent=1), encoding="utf-8")
            os.replace(tmp, self.manifest_path)
        except Exception:
            pass

    @staticmethod
    def _legacy_present(folder: Path, slug: str) -> bool:
        names = {slug.lower(), slug.lower().replace("-", ""), slug.lower().replace("-", "_")}
        pat = re.compile(r"^(?:" + "|".join(re.escape(n) for n in names) + r")(?:[-_+. ]?(?:fabric|forge|neoforge|quilt|mc|v?\d))")
        try:
            return any(pat.match(f.name.lower()) for f in folder.glob("*.jar"))
        except OSError:
            return False

    # ---- tải 1 phiên bản
    def _download_version(self, version: dict, folder_name: str, pinned=False) -> bool:
        pf = _pick_file(version)
        if not pf:
            return False
        pid = version.get("project_id") or version.get("id")
        folder = self.mc_dir / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        fname = os.path.basename(pf["filename"])
        dest = folder / fname
        size = pf.get("size")
        if dest.exists() and (not size or dest.stat().st_size == size):
            self.log(f"  {fname}: đã có bản này", "dim")
        else:
            self.log(f"  Đang tải {fname} …", "info")
            sha512 = (pf.get("hashes") or {}).get("sha512")
            download_file(pf["url"], dest, progress=self.progress, sha512=sha512)
            self.log(f"  Xong: {fname}", "ok")
        old = self.manifest.get(pid)
        if old and old.get("file") and old["file"] != fname:
            try:
                (folder / os.path.basename(old["file"])).unlink(missing_ok=True)
            except Exception:
                pass
        self.manifest[pid] = {"file": fname, "folder": folder_name, "pinned": bool(pinned),
                              "name": version.get("name") or fname}
        self._save()
        return True

    def _fetch_versions(self, project: str, ptype: str) -> list:
        if ptype == "mod":
            return modrinth_versions(project, self.mc_version, self.loaders)
        versions = modrinth_versions(project, self.mc_version)
        return versions or modrinth_versions(project)  # pack thường hỗ trợ nhiều bản

    # ---- cài dự án
    def install(self, slug: str, ptype: str = "mod", with_deps=True, depth=0) -> bool:
        folder_name = self.FOLDER.get(ptype, "mods")
        versions = self._fetch_versions(slug, ptype)
        if not versions:
            self.log(f"  {slug}: không có bản cho Minecraft {self.mc_version}", "warn")
            return False
        chosen = versions[0]
        pid = chosen.get("project_id") or slug
        self._seen.add(pid)
        folder = self.mc_dir / folder_name
        rec = self.manifest.get(pid)
        pf = _pick_file(chosen)
        if rec and (folder / rec["file"]).exists() and rec.get("pinned"):
            self.log(f"  {slug}: giữ bản đã ghim theo phụ thuộc", "dim")
        elif rec and pf and rec["file"] == os.path.basename(pf["filename"]) and (folder / rec["file"]).exists():
            self.log(f"  {slug}: đã là bản mới nhất", "dim")
        elif not rec and ptype == "mod" and self._legacy_present(folder, slug):
            self.log(f"  {slug}: đã có sẵn, bỏ qua", "dim")
        else:
            if not self._download_version(chosen, folder_name):
                self.log(f"  {slug}: không có file để tải", "warn")
                return False
        if with_deps and ptype == "mod" and depth < 3:
            self._install_deps(chosen, depth)
        return True

    def _install_deps(self, version: dict, depth: int) -> None:
        for dep in version.get("dependencies") or []:
            if dep.get("dependency_type") != "required":
                continue
            dpid, dvid = dep.get("project_id"), dep.get("version_id")
            key = dpid or dvid
            if not key or key in self._seen:
                continue
            self._seen.add(key)
            try:
                if dvid:
                    dver = _mr_get(f"/version/{dvid}")
                else:
                    vs = modrinth_versions(dpid, self.mc_version, self.loaders)
                    dver = vs[0] if vs else None
                if not dver:
                    self.log(f"  Phụ thuộc {key}: không có bản hợp", "warn")
                    continue
                dpid = dver.get("project_id") or dpid
                self._seen.add(dpid)
                pf = _pick_file(dver)
                rec = self.manifest.get(dpid)
                have = rec and (self.mc_dir / rec["folder"] / rec["file"]).exists()
                if have and (not dvid or (pf and rec["file"] == os.path.basename(pf["filename"]))):
                    continue
                if not have and not dvid:
                    proj = _mr_get(f"/project/{dpid}")
                    if self._legacy_present(self.mc_dir / "mods", proj.get("slug", "")):
                        continue
                self.log(f"  Phụ thuộc bắt buộc: {dver.get('name') or dpid}", "dim")
                if self._download_version(dver, "mods", pinned=bool(dvid)):
                    if depth + 1 < 3:
                        self._install_deps(dver, depth + 1)
            except Exception as e:
                self.log(f"  Lỗi cài phụ thuộc {key}: {e}", "warn")
                write_error_log(f"Phụ thuộc Modrinth ({key})", exc=e)


def write_optimized_options(mc_dir: Path) -> Path:
    opt = mc_dir / "options.txt"
    existing = {}
    if opt.exists():
        for line in opt.read_text(encoding="utf-8", errors="ignore").splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                existing[k] = v
    existing.update(OPTIMIZED_OPTIONS)
    tmp = opt.with_suffix(".tmp")
    tmp.write_text("\n".join(f"{k}:{v}" for k, v in existing.items()) + "\n", encoding="utf-8")
    os.replace(tmp, opt)
    return opt
