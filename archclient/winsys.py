# -*- coding: utf-8 -*-
"""Tối ưu và tích hợp riêng cho Windows.

File này import được trên mọi hệ điều hành (``winreg`` / ``ctypes.windll`` chỉ được đụng tới khi
hàm chạy thật trên Windows) nên test được bằng registry giả trên Linux.

Nguyên tắc: mọi thay đổi vào hệ thống đều
  * nằm trong HKEY_CURRENT_USER (không cần quyền admin, không hiện UAC),
  * có bản sao lưu giá trị cũ để trả lại nguyên trạng khi người dùng tắt tuỳ chọn,
  * lỗi thì bỏ qua và ghi log, không bao giờ làm game không chạy được.
"""
from __future__ import annotations

import json
import os
import re
import struct
import subprocess
import sys
from pathlib import Path

from . import APP_ID, APP_NAME
from .bootstrap import (APP_DIR, CACHE_DIR, CONFIG_DIR, FROZEN, IS_WINDOWS, NO_WINDOW,
                        hidden_kwargs, resource_path)

# --------------------------------------------------------------------------
# Truy cập registry (có thể thay bằng bản giả khi test)
# --------------------------------------------------------------------------
_winreg = None


def _reg():
    global _winreg
    if _winreg is None:
        import winreg          # chỉ có trên Windows
        _winreg = winreg
    return _winreg


def reg_get(path: str, name: str):
    """Giá trị registry dưới HKCU hoặc None nếu chưa có."""
    w = _reg()
    try:
        with w.OpenKey(w.HKEY_CURRENT_USER, path, 0, w.KEY_READ) as k:
            return w.QueryValueEx(k, name)[0]
    except OSError:
        return None


def reg_set(path: str, name: str, value, kind: str = "sz") -> None:
    w = _reg()
    typ = w.REG_DWORD if kind == "dword" else w.REG_SZ
    with w.CreateKeyEx(w.HKEY_CURRENT_USER, path, 0, w.KEY_SET_VALUE) as k:
        w.SetValueEx(k, name, 0, typ, value)


def reg_delete(path: str, name: str) -> None:
    w = _reg()
    try:
        with w.OpenKey(w.HKEY_CURRENT_USER, path, 0, w.KEY_SET_VALUE) as k:
            w.DeleteValue(k, name)
    except OSError:
        pass


def _hklm_names(path: str, value: str) -> list:
    """Đọc `value` của mọi key con trực tiếp của HKLM\\path."""
    w = _reg()
    out = []
    try:
        with w.OpenKey(w.HKEY_LOCAL_MACHINE, path, 0, w.KEY_READ) as root:
            i = 0
            while True:
                try:
                    sub = w.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                if not sub.isdigit():
                    continue
                try:
                    with w.OpenKey(root, sub, 0, w.KEY_READ) as k:
                        out.append(str(w.QueryValueEx(k, value)[0]))
                except OSError:
                    continue
    except OSError:
        pass
    return out


# --------------------------------------------------------------------------
# Chạy lệnh con (không bật cửa sổ console)
# --------------------------------------------------------------------------
def run_hidden(cmd: list, timeout: float = 10, env=None):
    """subprocess.run ẩn cửa sổ; trả None nếu lệnh không chạy được."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              encoding="utf-8", errors="replace", env=env, **hidden_kwargs())
    except Exception:
        return None


# --------------------------------------------------------------------------
# Phần cứng
# --------------------------------------------------------------------------
_DISPLAY_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
_SKIP_ADAPTERS = ("basic display", "basic render", "remote", "virtual", "indirect", "mirror", "parsec")


def gpu_names() -> list:
    names = []
    for n in _hklm_names(_DISPLAY_CLASS, "DriverDesc"):
        if any(s in n.lower() for s in _SKIP_ADAPTERS) or n in names:
            continue
        names.append(n)
    return names


def gpu_vendors(names: list) -> list:
    found = []
    for n in names:
        low = n.lower()
        for key, vendor in (("nvidia", "nvidia"), ("geforce", "nvidia"), ("amd", "amd"), ("radeon", "amd"),
                            ("intel", "intel"), ("qualcomm", "qualcomm"), ("adreno", "qualcomm")):
            if key in low:
                if vendor not in found:
                    found.append(vendor)
                break
    return found


def memory_status_mb():
    """(tổng, còn trống) RAM tính bằng MB; (0, 0) nếu không đọc được."""
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]

        st = MEMORYSTATUSEX()
        st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return int(st.ullTotalPhys) >> 20, int(st.ullAvailPhys) >> 20
    except Exception:
        pass
    return 0, 0


def windows_label() -> str:
    try:
        build = int(sys.getwindowsversion().build)      # type: ignore[attr-defined]
        return "Windows 11" if build >= 22000 else "Windows 10"
    except Exception:
        return "Windows"


# --------------------------------------------------------------------------
# Power plan
# --------------------------------------------------------------------------
SCHEME_HIGH = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
SCHEME_ULTIMATE = "e9a42b02-d5df-448d-aa00-03f14749eb61"
_GUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
POWER_STATE = CONFIG_DIR / "power_restore.json"
_plan_cache = {"t": 0.0, "v": None}


def active_power_scheme():
    """(guid, tên) của power plan đang dùng hoặc None. Tên có thể bị Windows địa phương hoá."""
    r = run_hidden(["powercfg", "/getactivescheme"], timeout=6)
    if not r or r.returncode != 0:
        return None
    m = re.search(f"({_GUID})\\s*(?:\\((.*?)\\))?", r.stdout or "")
    return (m.group(1).lower(), (m.group(2) or "").strip()) if m else None


def active_power_name(max_age: float = 30.0) -> str:
    """Tên power plan, có cache vì hay được gọi khi vẽ giao diện."""
    import time
    now = time.monotonic()
    if _plan_cache["v"] is not None and now - _plan_cache["t"] < max_age:
        return _plan_cache["v"]
    cur = active_power_scheme()
    val = (cur[1] or cur[0]) if cur else "?"
    _plan_cache.update(t=now, v=val)
    return val


def invalidate_power_cache() -> None:
    _plan_cache.update(t=0.0, v=None)


def available_power_schemes() -> list:
    r = run_hidden(["powercfg", "/list"], timeout=6)
    return [g.lower() for g in re.findall(_GUID, (r.stdout if r else "") or "")]


def _set_scheme(guid: str) -> bool:
    r = run_hidden(["powercfg", "/setactive", guid], timeout=8)
    invalidate_power_cache()
    return bool(r and r.returncode == 0)


def boost_power_plan(state_file: Path = None) -> str:
    """Chuyển sang plan hiệu năng cao khi chơi. Ghi plan cũ ra file để khôi phục kể cả khi launcher bị tắt đột ngột.
    Trả về tên plan đã bật, hoặc '' nếu không đổi (đã ở plan cao / máy không có / lỗi)."""
    state_file = state_file or POWER_STATE
    cur = active_power_scheme()
    if not cur:
        return ""
    have = available_power_schemes()
    target = next((g for g in (SCHEME_ULTIMATE, SCHEME_HIGH) if g in have), None)
    if not target or cur[0] in (SCHEME_HIGH, SCHEME_ULTIMATE):
        return ""
    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps({"restore": cur[0], "name": cur[1]}), encoding="utf-8")
    except OSError:
        return ""
    if _set_scheme(target):
        return "Ultimate Performance" if target == SCHEME_ULTIMATE else "High performance"
    state_file.unlink(missing_ok=True)
    return ""


def restore_power_plan(state_file: Path = None) -> bool:
    """Trả lại plan cũ nếu trước đó đã đổi. An toàn khi gọi nhiều lần."""
    state_file = state_file or POWER_STATE
    try:
        guid = json.loads(state_file.read_text(encoding="utf-8")).get("restore")
    except (OSError, ValueError):
        return False
    ok = bool(guid) and re.fullmatch(_GUID, guid) is not None and _set_scheme(guid)
    if ok:
        state_file.unlink(missing_ok=True)
    return ok


# --------------------------------------------------------------------------
# Tinh chỉnh registry
# --------------------------------------------------------------------------
GPU_PREF_KEY = r"Software\Microsoft\DirectX\UserGpuPreferences"
LAYERS_KEY = r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"
FSO_FLAG = "DISABLEDXMAXIMIZEDWINDOWEDMODE"
BACKUP_FILE = CONFIG_DIR / "win_backup.json"

# tuỳ chọn toàn hệ thống: (key con, tên giá trị, giá trị khi BẬT tuỳ chọn)
GLOBAL_REG = {
    "win_gamemode": [(r"Software\Microsoft\GameBar", "AutoGameModeEnabled", 1),
                     (r"Software\Microsoft\GameBar", "AllowAutoGameMode", 1)],
    "win_disable_dvr": [(r"System\GameConfigStore", "GameDVR_Enabled", 0),
                        (r"Software\Microsoft\Windows\CurrentVersion\GameDVR", "AppCaptureEnabled", 0)],
}


def _load_backup(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_backup(path: Path, data: dict) -> None:
    try:
        if data:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=1), encoding="utf-8")
        else:
            path.unlink(missing_ok=True)
    except OSError:
        pass


def apply_global(key: str, backup_file: Path = None) -> bool:
    """Bật tuỳ chọn toàn hệ thống; lưu giá trị gốc (lần đầu) để trả lại được."""
    items = GLOBAL_REG.get(key)
    if not items:
        return False
    backup_file = backup_file or BACKUP_FILE
    bk = _load_backup(backup_file)
    try:
        for path, name, val in items:
            bid = f"{path}|{name}"
            if bid not in bk:
                old = reg_get(path, name)
                bk[bid] = {"existed": old is not None, "value": old}
            if reg_get(path, name) != val:
                reg_set(path, name, val, "dword")
        _save_backup(backup_file, bk)
        return True
    except Exception:
        return False


def restore_global(key: str, backup_file: Path = None) -> bool:
    items = GLOBAL_REG.get(key)
    if not items:
        return False
    backup_file = backup_file or BACKUP_FILE
    bk = _load_backup(backup_file)
    try:
        for path, name, _val in items:
            rec = bk.pop(f"{path}|{name}", None)
            if rec is None:
                continue
            if rec.get("existed") and rec.get("value") is not None:
                reg_set(path, name, int(rec["value"]), "dword")
            else:
                reg_delete(path, name)
        _save_backup(backup_file, bk)
        return True
    except Exception:
        return False


def _exe_key(exe) -> str:
    return str(Path(exe)).replace("/", "\\") if IS_WINDOWS else str(exe)


def _java_pair(java_exe) -> list:
    """java.exe và javaw.exe cùng thư mục — Windows áp tuỳ chọn theo từng file exe."""
    p = Path(java_exe)
    out = [p]
    twin = p.with_name("javaw.exe" if p.name.lower() == "java.exe" else "java.exe")
    if twin != p:
        out.append(twin)
    return out


def set_gpu_preference(java_exe, high: bool = True) -> bool:
    """Settings > Display > Graphics: ép java.exe dùng GPU hiệu năng cao (laptop 2 GPU hay chạy nhầm iGPU)."""
    try:
        for exe in _java_pair(java_exe):
            key = _exe_key(exe)
            if high:
                if reg_get(GPU_PREF_KEY, key) != "GpuPreference=2;":
                    reg_set(GPU_PREF_KEY, key, "GpuPreference=2;")
            else:
                reg_delete(GPU_PREF_KEY, key)
        return True
    except Exception:
        return False


def get_gpu_preference(java_exe) -> bool:
    try:
        return reg_get(GPU_PREF_KEY, _exe_key(java_exe)) == "GpuPreference=2;"
    except Exception:
        return False


def _layer_flags(value) -> list:
    return [t for t in str(value or "").split() if t != "~"]


def set_fullscreen_opt_disabled(java_exe, disabled: bool = True) -> bool:
    """Tắt 'Fullscreen Optimizations' cho java.exe (giảm input lag / giật khi alt-tab ở toàn màn hình)."""
    try:
        for exe in _java_pair(java_exe):
            key = _exe_key(exe)
            flags = _layer_flags(reg_get(LAYERS_KEY, key))
            if disabled and FSO_FLAG not in flags:
                flags.append(FSO_FLAG)
            elif not disabled and FSO_FLAG in flags:
                flags.remove(FSO_FLAG)
            else:
                continue
            if flags:
                reg_set(LAYERS_KEY, key, "~ " + " ".join(flags))
            else:
                reg_delete(LAYERS_KEY, key)
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------
# Tiến trình game
# --------------------------------------------------------------------------
ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000
CREATE_NEW_PROCESS_GROUP = 0x00000200


def game_creationflags(high_priority: bool) -> int:
    """Cờ Popen cho game: không bật console, tách nhóm tiến trình, (tuỳ chọn) ưu tiên CPU cao hơn bình thường."""
    flags = NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    if high_priority:
        flags |= ABOVE_NORMAL_PRIORITY_CLASS
    return flags


# --------------------------------------------------------------------------
# Shortcut .lnk
# --------------------------------------------------------------------------
SHORTCUT_NAME = f"{APP_NAME}.lnk"
SHORTCUT_META = CONFIG_DIR / "shortcut.json"
ICO_PATH = CONFIG_DIR / "arch-client.ico"


def start_menu_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def desktop_dir() -> Path:
    """Thư mục Desktop thật (đúng cả khi bị OneDrive chuyển hướng)."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(520)
        # CSIDL_DESKTOPDIRECTORY = 0x10
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 and buf.value:
            return Path(buf.value)
    except Exception:
        pass
    return Path(os.environ.get("USERPROFILE") or Path.home()) / "Desktop"


def shortcut_paths() -> dict:
    return {"desktop": desktop_dir() / SHORTCUT_NAME, "menu": start_menu_dir() / SHORTCUT_NAME}


def launch_target():
    """(file chạy, tham số, thư mục làm việc)."""
    if FROZEN:
        exe = Path(sys.executable)
        return str(exe), "", str(exe.parent)
    py = Path(sys.executable)
    pyw = py.with_name("pythonw.exe")
    runner = pyw if pyw.exists() else py
    script = APP_DIR / "arch_laucher.py"
    return str(runner), f'"{script}"', str(APP_DIR)


def _signature() -> str:
    t, a, w = launch_target()
    return f"{t}|{a}|{w}"


def build_ico(pngs: list) -> bytes:
    """Ghép các ảnh PNG [(kích thước, bytes)] thành file .ico (định dạng PNG-trong-ICO, Windows Vista+)."""
    pngs = sorted(pngs, key=lambda x: x[0])
    head = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    entries, blobs = b"", b""
    for size, data in pngs:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset + len(blobs))
        blobs += data
    return head + entries + blobs


def make_ico(dest: Path, source=None) -> bool:
    """Tạo .ico nhiều kích thước từ img/icon.png bằng Qt (Windows cần .ico cho shortcut)."""
    src = Path(source) if source else resource_path("img/icon.png")
    try:
        from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt
        from PyQt6.QtGui import QImage
        img = QImage(str(src))
        if img.isNull():
            return False
        pngs = []
        for size in (16, 24, 32, 48, 64, 128, 256):
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            img.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                       Qt.TransformationMode.SmoothTransformation).save(buf, "PNG")
            buf.close()
            pngs.append((size, bytes(ba)))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(build_ico(pngs))
        return True
    except Exception:
        return False


_LNK_PS = (
    "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:ARCH_LNK);"
    "$s.TargetPath=$env:ARCH_TARGET;$s.Arguments=$env:ARCH_ARGS;"
    "$s.WorkingDirectory=$env:ARCH_CWD;$s.IconLocation=$env:ARCH_ICON;"
    "$s.Description='Minecraft launcher';$s.Save()"
)


def _write_lnk(lnk: Path, target: str, args: str, cwd: str, icon: str) -> bool:
    lnk.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, ARCH_LNK=str(lnk), ARCH_TARGET=target, ARCH_ARGS=args,
               ARCH_CWD=cwd, ARCH_ICON=icon)
    r = run_hidden(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                    "-Command", _LNK_PS], timeout=25, env=env)
    return bool(r and r.returncode == 0 and lnk.exists())


def shortcuts_present() -> bool:
    return any(p.exists() for p in shortcut_paths().values())


def shortcuts_stale() -> bool:
    """Shortcut đã tạo nhưng launcher đã được chuyển sang chỗ khác / đổi Python."""
    try:
        meta = json.loads(SHORTCUT_META.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return shortcuts_present()
    return meta.get("sig") != _signature()


def install_shortcuts() -> list:
    """Tạo shortcut ở Start Menu và Desktop. Trả về danh sách file đã ghi."""
    target, args, cwd = launch_target()
    icon = str(ICO_PATH) if make_ico(ICO_PATH) else target
    written = []
    for p in shortcut_paths().values():
        if _write_lnk(p, target, args, cwd, icon):
            written.append(str(p))
    if not written:
        raise RuntimeError("Không tạo được shortcut (PowerShell bị chặn?)")
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        SHORTCUT_META.write_text(json.dumps({"sig": _signature()}), encoding="utf-8")
    except OSError:
        pass
    return written


def remove_shortcuts() -> list:
    removed = []
    for p in shortcut_paths().values():
        if p.exists():
            p.unlink()
            removed.append(str(p))
    SHORTCUT_META.unlink(missing_ok=True)
    return removed


# --------------------------------------------------------------------------
# Taskbar
# --------------------------------------------------------------------------
def set_app_user_model_id(app_id: str = f"ArchClient.{APP_ID}") -> None:
    """Để icon và nhóm cửa sổ trên taskbar là của Arch Client, không phải của python.exe."""
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


# --------------------------------------------------------------------------
# Java
# --------------------------------------------------------------------------
def system_java_dirs() -> list:
    """Các thư mục chứa JDK/JRE phổ biến trên Windows, kể cả runtime của launcher chính thức."""
    out = []
    env = os.environ
    pf = [env.get("ProgramFiles"), env.get("ProgramFiles(x86)"), env.get("ProgramW6432")]
    for base in {p for p in pf if p}:
        for vendor in ("Eclipse Adoptium", "Java", "Microsoft", "Zulu", "BellSoft", "Amazon Corretto",
                       "Semeru", "AdoptOpenJDK", "RedHat", "OpenJDK"):
            root = Path(base) / vendor
            if root.is_dir():
                try:
                    out += [d for d in root.iterdir() if d.is_dir()]
                except OSError:
                    pass
    if env.get("JAVA_HOME"):
        out.append(Path(env["JAVA_HOME"]))
    appdata = env.get("APPDATA")
    if appdata:        # Java mà launcher Minecraft chính thức đã tải: runtime/<tên>/windows-x64/<tên>/bin/java.exe
        rt = Path(appdata) / ".minecraft" / "runtime"
        if rt.is_dir():
            try:
                for name in rt.iterdir():
                    for plat in name.iterdir() if name.is_dir() else []:
                        if plat.is_dir():
                            out += [d for d in plat.iterdir() if (d / "bin" / "java.exe").exists()]
            except OSError:
                pass
    return out


WINGET_JDK = "EclipseAdoptium.Temurin.{v}.JDK"


def winget_install_java(major: int, log=lambda m, l="info": None) -> bool:
    """Phương án dự phòng khi tải bản portable lỗi: cài Temurin qua winget (Windows có thể hiện UAC)."""
    import shutil
    if not shutil.which("winget"):
        return False
    log(f"winget install Temurin {major}…", "dim")
    r = run_hidden(["winget", "install", "--id", WINGET_JDK.format(v=int(major)), "-e", "--silent",
                    "--accept-package-agreements", "--accept-source-agreements"], timeout=900)
    return bool(r and r.returncode == 0)
