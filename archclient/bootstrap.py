# -*- coding: utf-8 -*-
"""Khởi động: nhận diện distro, ghi log lỗi, tự cài thư viện còn thiếu.

File này KHÔNG import Qt ở mức module — nó chạy trước khi Qt tồn tại.
"""
from __future__ import annotations

import os
import re
import sys
import shutil
import platform
import importlib
import threading
import traceback
import subprocess
from pathlib import Path
from datetime import datetime

FROZEN = bool(getattr(sys, "frozen", False))
IS_WINDOWS = sys.platform == "win32"
NO_WINDOW = 0x08000000        # CREATE_NO_WINDOW: app windowed không được nháy cửa sổ console khi gọi lệnh con


_popen_patched = False


def hide_child_consoles() -> None:
    """Windows: thư viện bên thứ ba (installer Forge của minecraft-launcher-lib…) gọi subprocess không kèm
    CREATE_NO_WINDOW -> bật cửa sổ console đen. Mặc định thêm cờ đó cho mọi tiến trình con."""
    global _popen_patched
    if not IS_WINDOWS or _popen_patched:
        return
    orig = subprocess.Popen.__init__

    def init(self, *a, **kw):
        if len(a) < 14:                       # creationflags là tham số vị trí thứ 14
            kw["creationflags"] = kw.get("creationflags", 0) | NO_WINDOW
        orig(self, *a, **kw)

    subprocess.Popen.__init__ = init
    _popen_patched = True


def hidden_kwargs() -> dict:
    """Tham số subprocess để không bật cửa sổ đen trên Windows (không có tác dụng ở nơi khác)."""
    return {"creationflags": NO_WINDOW} if IS_WINDOWS else {}

if FROZEN:
    APP_DIR = Path(os.environ.get("APPDIR") or Path(sys.executable).resolve().parent)
else:
    APP_DIR = Path(__file__).resolve().parent.parent


def _xdg(var: str, fallback: str) -> Path:
    v = os.environ.get(var)
    return Path(v) if v and os.path.isabs(v) else Path.home() / fallback


def _win_base() -> Path:
    """%LOCALAPPDATA%\\ArchClient — nằm ngoài Roaming để JDK / cache lớn không bị đồng bộ theo tài khoản."""
    v = os.environ.get("LOCALAPPDATA")
    return (Path(v) if v and os.path.isabs(v) else Path.home() / "AppData" / "Local") / "ArchClient"


if IS_WINDOWS:
    CONFIG_DIR = _win_base()
    CACHE_DIR = _win_base() / "cache"
else:
    CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config") / "arch-client-launcher"
    CACHE_DIR = _xdg("XDG_CACHE_HOME", ".cache") / "arch-client"
ERROR_LOG_DIR = CONFIG_DIR / "error_logs"
GAME_LOG_DIR = CONFIG_DIR / "logs"


def resource_path(rel: str) -> Path:
    """Tìm file đi kèm (assets/, img/) cả khi chạy source, PyInstaller hay AppImage."""
    cands = [APP_DIR / rel]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        cands.append(Path(meipass) / rel)
    if os.environ.get("APPDIR"):
        cands.append(Path(os.environ["APPDIR"]) / "usr" / "bin" / rel)
    for c in cands:
        if c.exists():
            return c
    return cands[0]


def bprint(msg) -> None:
    try:
        print(msg, flush=True)
    except Exception:
        try:
            enc = sys.stdout.encoding or "utf-8"
            print(str(msg).encode(enc, errors="replace").decode(enc, errors="replace"), flush=True)
        except Exception:
            pass


# --------------------------------------------------------------------------
# Nhận diện hệ điều hành
# --------------------------------------------------------------------------
_OS_INFO: dict | None = None


def detect_os() -> dict:
    global _OS_INFO
    if _OS_INFO is not None:
        return _OS_INFO

    info = {"system": platform.system(), "distro_id": "", "distro_like": "",
            "pkg_manager": None, "pretty": platform.system() or "Linux",
            "immutable": False, "musl": False}

    if info["system"] == "Linux":
        rel = {}
        try:
            for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    rel[k] = v.strip().strip('"')
        except Exception:
            pass
        did = rel.get("ID", "").lower()
        like = rel.get("ID_LIKE", "").lower()
        info.update(distro_id=did, distro_like=like, pretty=rel.get("PRETTY_NAME", "Linux"))

        def has(*names):
            return any(n == did or n in like.split() for n in names)

        if has("arch"):
            pm = "pacman"
        elif has("debian", "ubuntu"):
            pm = "apt"
        elif has("fedora", "rhel", "centos", "nobara"):
            pm = "dnf"
        elif has("opensuse", "opensuse-tumbleweed", "opensuse-leap", "suse"):
            pm = "zypper"
        elif did == "void":
            pm = "xbps"
        elif did == "alpine":
            pm = "apk"
        else:
            pm = None
            for exe, name in (("pacman", "pacman"), ("apt-get", "apt"), ("dnf", "dnf"),
                              ("zypper", "zypper"), ("xbps-install", "xbps"), ("apk", "apk")):
                if shutil.which(exe):
                    pm = name
                    break
        info["pkg_manager"] = pm
        info["immutable"] = bool(
            did in ("steamos", "bazzite", "silverblue", "kinoite", "nixos")
            or Path("/run/ostree-booted").exists()
            or os.environ.get("FLATPAK_ID") or os.environ.get("SNAP"))
        info["musl"] = did == "alpine" or any(Path("/lib").glob("ld-musl-*"))
    elif info["system"] == "Windows":
        build = 0
        try:
            build = int(getattr(sys, "getwindowsversion")().build)
        except Exception:
            pass
        name = "Windows 11" if build >= 22000 else "Windows 10" if build >= 10240 else "Windows"
        info.update(distro_id="windows", pretty=f"{name} (build {build})" if build else name,
                    pkg_manager="winget" if shutil.which("winget") else None)
    _OS_INFO = info
    return info


# --------------------------------------------------------------------------
# Ghi log lỗi ra file
# --------------------------------------------------------------------------
def write_error_log(context, exc=None, extra_text=None):
    """Ghi lỗi (kèm traceback) ra ~/.config/arch-client-launcher/error_logs/."""
    try:
        ERROR_LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = "".join(c if c.isalnum() else "_" for c in str(context))[:40] or "loi"
        path = ERROR_LOG_DIR / f"error_{ts}_{safe}.txt"
        if exc is not None and getattr(exc, "__traceback__", None):
            tb_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        else:
            tb_text = traceback.format_exc()
            if tb_text.strip() == "NoneType: None":
                tb_text = "(không có traceback)"
        lines = ["=" * 70, "ARCH CLIENT — BÁO CÁO LỖI", "=" * 70,
                 f"Thời gian : {datetime.now():%Y-%m-%d %H:%M:%S}",
                 f"Ngữ cảnh  : {context}",
                 f"Hệ điều hành: {detect_os().get('pretty')}",
                 f"Python    : {sys.version.split()[0]}"]
        if exc is not None:
            lines += [f"Loại lỗi  : {type(exc).__name__}", f"Nội dung  : {exc}"]
        if extra_text:
            lines += ["-" * 70, str(extra_text)]
        lines += ["-" * 70, tb_text, "=" * 70]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        _prune_logs(ERROR_LOG_DIR, keep=60)
        bprint(f"[log] đã ghi file lỗi: {path}")
        return path
    except Exception as e:  # ghi log lỗi cũng không được làm crash thêm
        bprint(f"[log] không ghi được file lỗi: {e}")
        return None


def _prune_logs(folder: Path, keep: int) -> None:
    try:
        files = sorted(folder.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[keep:]:
            old.unlink(missing_ok=True)
    except Exception:
        pass


def install_excepthooks() -> None:
    def main_hook(t, v, tb):
        write_error_log("Luồng chính (GUI)", exc=v)
        try:
            traceback.print_exception(t, v, tb)
        except Exception:                     # pythonw / bản đóng gói windowed không có stderr
            pass

    def thread_hook(args):
        write_error_log(f"Luồng nền: {args.thread.name if args.thread else '?'}",
                        exc=args.exc_value)

    sys.excepthook = main_hook
    try:
        threading.excepthook = thread_hook
    except AttributeError:
        pass


# --------------------------------------------------------------------------
# Chạy lệnh cần quyền root: sudo (có terminal) -> pkexec (hộp thoại polkit)
# --------------------------------------------------------------------------
def run_privileged(cmd: list, log=bprint) -> bool:
    if IS_WINDOWS:
        return False              # Windows không dùng sudo; tác vụ cần quyền admin được xử lý riêng (UAC)
    full = list(cmd)
    try:
        is_root = os.geteuid() == 0
    except AttributeError:
        is_root = False
    if not is_root:
        has_tty = False
        try:
            has_tty = sys.stdin is not None and sys.stdin.isatty()
        except Exception:
            pass
        if has_tty and shutil.which("sudo"):
            full = ["sudo"] + full
        elif shutil.which("pkexec") and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            full = ["pkexec"] + full
        elif shutil.which("sudo"):
            full = ["sudo", "-n"] + full
        else:
            log("Khong co sudo/pkexec de cai goi he thong.")
            return False
    log("  $ " + " ".join(full))
    try:
        r = subprocess.run(full, stdin=subprocess.DEVNULL if full[0] != "sudo" or "-n" in full else None,
                           capture_output=False)
        return r.returncode == 0
    except Exception as e:
        log(f"  Lenh that bai: {e}")
        return False


def install_system_packages(osinfo: dict, pkgs_by_pm: dict, log=bprint) -> bool:
    pm = osinfo.get("pkg_manager")
    pkgs = pkgs_by_pm.get(pm)
    if not pkgs or osinfo.get("immutable"):
        return False
    if pm == "pacman":
        return run_privileged(["pacman", "-Sy", "--needed", "--noconfirm"] + pkgs, log)
    if pm == "apt":
        run_privileged(["apt-get", "update"], log)
        return run_privileged(["apt-get", "install", "-y"] + pkgs, log)
    if pm == "dnf":
        return run_privileged(["dnf", "install", "-y"] + pkgs, log)
    if pm == "zypper":
        return run_privileged(["zypper", "--non-interactive", "install"] + pkgs, log)
    if pm == "xbps":
        return run_privileged(["xbps-install", "-Sy"] + pkgs, log)
    if pm == "apk":
        return run_privileged(["apk", "add"] + pkgs, log)
    return False


# --------------------------------------------------------------------------
# pip
# --------------------------------------------------------------------------
REQUIRED_PIP = {
    # module -> gói pip
    "PyQt6.QtWidgets": "PyQt6",
    "PyQt6.QtSvg": "PyQt6",
    "minecraft_launcher_lib.mod_loader": "minecraft-launcher-lib>=8.0",   # Forge/NeoForge/Quilt/Fabric thống nhất
    "requests": "requests",
}
OPTIONAL_PIP = {"pypresence": "pypresence"}

# Gói hệ thống thay thế khi pip bị chặn / không có wheel
PYQT_SYSTEM_PKGS = {
    "pacman": ["python-pyqt6"],
    "apt": ["python3-pyqt6", "python3-pyqt6.qtsvg"],
    "dnf": ["python3-pyqt6"],
    "zypper": ["python3-qt6"],
    "xbps": ["python3-PyQt6"],
    "apk": ["py3-qt6"],
}

# Thư viện X11/xcb mà plugin nền tảng của Qt cần (thiếu -> Qt tự abort).
QT_XCB_LIBS = ["xcb-cursor", "xkbcommon-x11", "xcb-icccm", "xcb-keysyms",
               "xcb-image", "xcb-render-util", "xcb-shape", "xcb-xkb"]
QT_XCB_PKGS = {
    "apt": ["libxcb-cursor0", "libxkbcommon-x11-0", "libxcb-icccm4", "libxcb-keysyms1",
            "libxcb-image0", "libxcb-render-util0", "libxcb-shape0", "libxcb-xkb1",
            "libgl1", "libegl1", "libfontconfig1", "libdbus-1-3"],
    "pacman": ["xcb-util-cursor", "libxkbcommon-x11", "xcb-util-wm", "xcb-util-keysyms",
               "xcb-util-image", "xcb-util-renderutil"],
    "dnf": ["xcb-util-cursor", "libxkbcommon-x11", "xcb-util-wm", "xcb-util-keysyms",
            "xcb-util-image", "xcb-util-renderutil"],
    "zypper": ["libxcb-cursor0", "libxkbcommon-x11-0", "libxcb-icccm4", "libxcb-keysyms1",
               "libxcb-image0", "libxcb-render-util0"],
    "xbps": ["xcb-util-cursor", "libxkbcommon-x11", "xcb-util-wm", "xcb-util-keysyms",
             "xcb-util-image", "xcb-util-renderutil"],
    "apk": ["xcb-util-cursor", "libxkbcommon-x11", "xcb-util-wm", "xcb-util-keysyms",
            "xcb-util-image", "xcb-util-renderutil"],
}
_LIB_DIRS = ["/usr/lib", "/usr/lib64", "/lib", "/lib64", "/usr/local/lib",
             "/usr/lib/x86_64-linux-gnu", "/lib/x86_64-linux-gnu",
             "/usr/lib/aarch64-linux-gnu", "/lib/aarch64-linux-gnu"]


def _pip_install(packages: list) -> bool:
    if FROZEN:
        return False
    exe = sys.executable
    if IS_WINDOWS and exe.lower().endswith("pythonw.exe"):
        exe = exe[:-len("pythonw.exe")] + "python.exe"      # pythonw không có stdout, pip sẽ hỏng
    base = [exe, "-m", "pip", "install", "--disable-pip-version-check"] + packages
    attempts = [base, base + ["--break-system-packages"],
                base + ["--user", "--break-system-packages"], base + ["--user"]]
    if IS_WINDOWS:
        attempts = [base, base + ["--user"]]
    for cmd in attempts:
        bprint("  $ " + " ".join(cmd))
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=900, **hidden_kwargs())
        except Exception as e:
            bprint(f"  loi chay pip: {e}")
            return False
        if r.returncode == 0:
            return True
        out = (r.stdout or "") + (r.stderr or "")
        if "No module named pip" in out:
            bprint("  He thong chua co pip (cai goi 'python3-pip').")
            return False
    return False


def _missing_modules() -> list:
    miss = []
    for mod, pipname in REQUIRED_PIP.items():
        try:
            importlib.import_module(mod)
        except Exception:
            if pipname not in miss:
                miss.append(pipname)
    return miss


def _has_lib(name: str, cache: dict = {}) -> bool:
    if not cache:
        for d in _LIB_DIRS:
            try:
                for f in os.listdir(d):
                    cache[f] = True
            except Exception:
                pass
        try:
            ld = shutil.which("ldconfig") or "/sbin/ldconfig"
            out = subprocess.run([ld, "-p"], capture_output=True, text=True, timeout=5).stdout
            for line in out.splitlines():
                m = re.match(r"\s*(\S+)\s", line)
                if m:
                    cache[m.group(1)] = True
        except Exception:
            pass
        cache["__loaded__"] = True
    prefix = f"lib{name}.so"
    return any(k.startswith(prefix) for k in cache)


def ensure_qt_runtime(osinfo: dict) -> None:
    """Kiểm tra thư viện xcb mà Qt cần (hay thiếu: libxcb-cursor0). Chỉ chạy 1 lần."""
    if osinfo["system"] != "Linux" or FROZEN:
        return
    marker = CONFIG_DIR / ".qt_runtime_checked"
    if marker.exists():
        return
    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" and os.environ.get("WAYLAND_DISPLAY"):
        return  # Wayland không cần cụm xcb
    missing = [n for n in QT_XCB_LIBS if not _has_lib(n)]
    # Nếu quét không ra thư viện nào thì có thể máy lạ (NixOS...) — đừng làm phiền.
    if missing and len(missing) < len(QT_XCB_LIBS):
        bprint(f"Thieu thu vien cho Qt: {', '.join(missing)} — dang cai goi he thong...")
        install_system_packages(osinfo, QT_XCB_PKGS)
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        marker.write_text("1", encoding="utf-8")
    except Exception:
        pass


def ensure_python_packages(osinfo: dict) -> None:
    missing = _missing_modules()
    if missing:
        if FROZEN:
            bprint(f"Ban dong goi thieu thu vien: {', '.join(missing)} — hay build lai.")
            write_error_log("Bootstrap - bản đóng gói thiếu thư viện", extra_text=", ".join(missing))
            sys.exit(1)
        bprint(f"Thieu thu vien Python: {', '.join(missing)} — dang cai bang pip...")
        ok = _pip_install(missing)
        importlib.invalidate_caches()
        if not ok or _missing_modules():
            if "PyQt6" in missing:
                bprint("pip khong cai duoc PyQt6 — thu goi he thong...")
                install_system_packages(osinfo, PYQT_SYSTEM_PKGS)
                importlib.invalidate_caches()
        still = _missing_modules()
        if still:
            bprint("Khong cai tu dong duoc. Hay chay:")
            extra = "" if IS_WINDOWS else " --break-system-packages"
            bprint(f"   {sys.executable} -m pip install {' '.join(still)}{extra}")
            write_error_log("Bootstrap - cài thư viện thất bại", extra_text=", ".join(still))
            sys.exit(1)

    opt = []
    for mod, pipname in OPTIONAL_PIP.items():
        try:
            importlib.import_module(mod)
        except Exception:
            opt.append(pipname)
    if opt and not FROZEN:
        marker = CONFIG_DIR / ".optional_pip_tried"
        if not marker.exists():  # chỉ thử một lần, không làm chậm các lần mở sau
            _pip_install(opt)
            try:
                CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                marker.write_text("1", encoding="utf-8")
            except Exception:
                pass
            importlib.invalidate_caches()


def ensure_environment() -> dict:
    install_excepthooks()
    hide_child_consoles()
    osinfo = detect_os()
    if osinfo["system"] not in ("Linux", "Windows"):
        bprint("Launcher chi ho tro Linux va Windows.")
    ensure_python_packages(osinfo)
    ensure_qt_runtime(osinfo)
    return osinfo
