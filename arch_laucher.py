#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Arch Client - Minecraft Fabric launcher (ttkbootstrap, flatly theme)
# Auto-detects the OS and installs missing packages, creates .minecraft,
# installs shortcuts (.desktop on Linux / Start Menu + Desktop on Windows),
# and writes error logs to a txt file.
#
# Manual install if needed:
#   pip install minecraft-launcher-lib requests ttkbootstrap --break-system-packages

import os
import re
import sys
import json
import time
import shutil
import tarfile
import zipfile
import platform
import threading
import traceback
import importlib
import subprocess
import urllib.request
import webbrowser
from pathlib import Path
from datetime import datetime

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ==========================================================================
# FROZEN: True khi launcher đã được đóng gói thành .exe (PyInstaller).
# Khi đó sys.executable là chính file .exe (không phải python.exe thật), nên
# KHÔNG được gọi "sys.executable -m pip install ..." (sẽ chỉ tự mở lại app,
# không cài được gì — đây là nguyên nhân bản Windows đóng gói bị lỗi
# "không tải được thư viện"). Mọi thư viện bắt buộc đã được nhúng sẵn vào
# .exe lúc build (xem build_windows.py), nên bootstrap chỉ cần kiểm tra chứ
# không cần tự pip install nữa khi FROZEN=True.
FROZEN = bool(getattr(sys, "frozen", False))

# Thư mục chứa .exe (khi đóng gói) — dùng để tìm img/, client/ đặt cạnh
# .exe, KHÔNG dùng sys._MEIPASS (thư mục tạm, bị xoá sau khi thoát app).
if FROZEN:
    EXE_DIR = Path(sys.executable).resolve().parent
else:
    EXE_DIR = Path(__file__).resolve().parent

# ==========================================================================
# BOOTSTRAP: nhận diện hệ điều hành + tự cài gói còn thiếu
# ==========================================================================

REQUIRED_PIP_PACKAGES = {
    # tên module python -> tên gói pip (bắt buộc — thiếu thì launcher không chạy được)
    "ttkbootstrap": "ttkbootstrap",
    "minecraft_launcher_lib": "minecraft-launcher-lib",
    "requests": "requests",
    "PIL": "pillow",
}

OPTIONAL_PIP_PACKAGES = {
    # tính năng phụ — thiếu vẫn chạy launcher bình thường
    "pypresence": "pypresence",
    # trình duyệt nhúng trong launcher (Modrinth / trang mod)
    "tkinterweb": "tkinterweb",
    "webview": "pywebview",
}


def _bprint(msg):
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "utf-8"
        safe_msg = str(msg).encode(enc, errors="replace").decode(enc, errors="replace")
        print(safe_msg, flush=True)

# ==========================================================================
# GHI LOG LỖI RA FILE .txt (mọi lỗi trong launcher đều được lưu lại)
# ==========================================================================

ERROR_LOG_DIR = Path.home() / ".config" / "arch-client-launcher" / "error_logs"


def write_error_log(context, exc=None, extra_text=None):
    """Ghi lỗi ra file .txt kèm timestamp + traceback đầy đủ.

    context: mô tả ngắn nơi xảy ra lỗi (vd 'Cài Fabric', 'Khởi chạy game')
    exc: exception object (nếu có) — nếu None sẽ tự lấy traceback hiện tại
    extra_text: text bổ sung muốn ghi kèm (không bắt buộc)
    Trả về đường dẫn file log đã ghi, hoặc None nếu ghi thất bại.
    """
    try:
        ERROR_LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_ctx = "".join(c if c.isalnum() else "_" for c in context)[:40] or "loi"
        log_path = ERROR_LOG_DIR / f"error_{ts}_{safe_ctx}.txt"

        tb_text = traceback.format_exc()
        if tb_text.strip() == "NoneType: None":
            tb_text = "(không có traceback — lỗi được báo cáo thủ công)"

        lines = [
            "=" * 70,
            "ARCH CLIENT — BÁO CÁO LỖI",
            "=" * 70,
            f"Thời gian     : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Ngữ cảnh      : {context}",
            f"Hệ điều hành  : {OS_INFO['pretty'] if 'OS_INFO' in globals() else platform.platform()}",
            f"Python        : {sys.version.split()[0]}",
        ]
        if exc is not None:
            lines.append(f"Loại lỗi      : {type(exc).__name__}")
            lines.append(f"Nội dung      : {exc}")
        if extra_text:
            lines.append("-" * 70)
            lines.append(str(extra_text))
        lines.append("-" * 70)
        lines.append("Traceback đầy đủ:")
        lines.append(tb_text)
        lines.append("=" * 70)

        log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        _bprint(f"📝 Đã ghi file lỗi: {log_path}")
        return log_path
    except Exception as log_err:
        # Ghi log lỗi thất bại thì cũng không được làm crash thêm launcher
        _bprint(f"⚠ Không thể ghi file lỗi: {log_err}")
        return None


def _thread_excepthook(args):
    """Bắt mọi lỗi chưa được xử lý xảy ra trong các thread nền (vd cài Fabric,
    tải mod, khởi chạy game) và ghi lại thành file .txt thay vì làm treo im lặng."""
    context = f"Thread nền: {args.thread.name if args.thread else 'unknown'}"
    write_error_log(context, exc=args.exc_value)


def _main_excepthook(exc_type, exc_value, exc_tb):
    """Bắt mọi lỗi chưa được xử lý ở luồng chính (GUI) và ghi lại thành file .txt."""
    write_error_log("Luồng chính (GUI)", exc=exc_value)
    traceback.print_exception(exc_type, exc_value, exc_tb)


sys.excepthook = _main_excepthook
try:
    threading.excepthook = _thread_excepthook
except AttributeError:
    pass  # Python < 3.8 không có threading.excepthook


def detect_os():
    """Nhận diện hệ điều hành và trình quản lý gói phù hợp.

    Hỗ trợ: Windows 10/11, Arch Linux + các distro dựa trên Arch
    (Manjaro, EndeavourOS, Garuda, CachyOS, ...), Debian/Ubuntu + các
    distro dựa trên Debian (Mint, Pop!_OS, Zorin, ...).
    """
    system = platform.system()  # 'Windows', 'Linux', 'Darwin'
    info = {"system": system, "distro_id": "", "distro_like": "",
            "pkg_manager": None, "pretty": system}

    if system == "Windows":
        build = 0
        try:
            build = sys.getwindowsversion().build
        except Exception:
            pass
        if build >= 22000:
            info["pretty"] = "Windows 11"
        elif build:
            info["pretty"] = "Windows 10"
        else:
            info["pretty"] = "Windows"
        info["pkg_manager"] = None  # trên Windows chỉ cần pip

    elif system == "Linux":
        os_release = {}
        try:
            for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    os_release[k] = v.strip().strip('"')
        except Exception:
            pass
        distro_id = os_release.get("ID", "").lower()
        distro_like = os_release.get("ID_LIKE", "").lower()
        info["distro_id"] = distro_id
        info["distro_like"] = distro_like
        info["pretty"] = os_release.get("PRETTY_NAME", "Linux")

        if distro_id == "arch" or "arch" in distro_like:
            info["pkg_manager"] = "pacman"
        elif distro_id in ("debian", "ubuntu") or "debian" in distro_like or "ubuntu" in distro_like:
            info["pkg_manager"] = "apt"
        elif shutil.which("pacman"):
            info["pkg_manager"] = "pacman"
        elif shutil.which("apt-get") or shutil.which("apt"):
            info["pkg_manager"] = "apt"

    else:
        info["pretty"] = system or "Không xác định"

    return info


def _run(cmd, use_sudo=False):
    if use_sudo and os.name != "nt":
        try:
            if os.geteuid() != 0:
                cmd = ["sudo"] + cmd
        except AttributeError:
            pass
    _bprint("  $ " + " ".join(cmd))
    try:
        subprocess.run(cmd, check=True)
        return True
    except Exception as e:
        _bprint(f"  ⚠ Lệnh thất bại: {e}")
        return False


def ensure_system_packages(osinfo):
    """Cài gói hệ thống cần thiết theo distro: Tk + WebKit (cho trình duyệt nhúng)."""
    if osinfo["system"] != "Linux":
        # Windows: WebView2 thường có sẵn trên Win10/11 — pywebview dùng Edge WebView2.
        return

    pm = osinfo["pkg_manager"]
    need_tk = False
    try:
        import tkinter  # noqa: F401
    except ImportError:
        need_tk = True

    if need_tk:
        _bprint("⏳ Thiếu tkinter (Tk) trên hệ thống — đang tự động cài đặt...")
        if pm == "pacman":
            _run(["pacman", "-Sy", "--needed", "--noconfirm", "tk"], use_sudo=True)
        elif pm == "apt":
            _run(["apt-get", "update"], use_sudo=True)
            _run(["apt-get", "install", "-y", "python3-tk"], use_sudo=True)
        else:
            _bprint("⚠ Không nhận diện được trình quản lý gói (pacman/apt).")
            _bprint("  Hãy tự cài thủ công: gói 'tk' (Arch) hoặc 'python3-tk' (Debian/Ubuntu).")

    # WebKitGTK / GI — cần cho pywebview + một số backend trình duyệt nhúng trên Linux.
    _bprint("⏳ Kiểm tra gói trình duyệt nhúng (WebKit)...")
    if pm == "pacman":
        _run(["pacman", "-Sy", "--needed", "--noconfirm",
              "webkit2gtk-4.1", "python-gobject"], use_sudo=True) or             _run(["pacman", "-Sy", "--needed", "--noconfirm",
                  "webkit2gtk", "python-gobject"], use_sudo=True)
    elif pm == "apt":
        _run(["apt-get", "update"], use_sudo=True)
        _run(["apt-get", "install", "-y",
              "python3-gi", "python3-gi-cairo", "gir1.2-webkit2-4.1"], use_sudo=True) or             _run(["apt-get", "install", "-y",
                  "python3-gi", "python3-gi-cairo", "gir1.2-webkit2-4.0"], use_sudo=True)
    else:
        _bprint("ℹ Có thể cần cài WebKitGTK thủ công nếu trình duyệt nhúng không mở được.")


def _pip_install(packages):
    if FROZEN:
        # Đang chạy dưới dạng .exe đã đóng gói — sys.executable là chính
        # file .exe, KHÔNG phải python.exe, nên "-m pip" sẽ không chạy được
        # (đây chính là lỗi "không tải được thư viện" trên bản Windows cũ).
        # Không còn cần thiết vì mọi gói bắt buộc đã được nhúng sẵn lúc build.
        _bprint("  ↳ Bản .exe đóng gói sẵn — bỏ qua bước pip install (đã nhúng sẵn thư viện).")
        return False
    base = [sys.executable, "-m", "pip", "install"] + packages
    _bprint("  $ " + " ".join(base))
    result = subprocess.run(base, capture_output=True, text=True)
    if result.returncode == 0:
        return True
    combined = (result.stdout or "") + (result.stderr or "")
    if "externally-managed-environment" in combined or "break-system-packages" in combined:
        base2 = base + ["--break-system-packages"]
        _bprint("  ↳ Môi trường Python 'externally-managed' — thử lại với --break-system-packages")
        _bprint("  $ " + " ".join(base2))
        result2 = subprocess.run(base2, capture_output=True, text=True)
        if result2.returncode == 0:
            return True
        _bprint(result2.stdout)
        _bprint(result2.stderr)
        return False
    _bprint(combined)
    return False


def ensure_python_packages():
    """Kiểm tra & tự động cài các thư viện Python còn thiếu."""
    missing = []
    for mod_name, pip_name in REQUIRED_PIP_PACKAGES.items():
        try:
            importlib.import_module(mod_name)
        except ImportError:
            missing.append(pip_name)
    if missing:
        if FROZEN:
            # Không nên xảy ra: bản .exe build đúng đã nhúng sẵn mọi gói bắt
            # buộc. Nếu vẫn thiếu, đây là lỗi khi build chứ người dùng không
            # tự sửa bằng pip được (vì không có Python/pip trên máy họ).
            _bprint(f"❌ Bản .exe này bị thiếu thư viện: {', '.join(missing)}.")
            _bprint("   Đây là lỗi khi build .exe (chưa nhúng đủ thư viện) — "
                     "hãy build lại bằng build_windows.py, không phải lỗi ở máy người dùng.")
            write_error_log("Bootstrap — .exe thiếu thư viện đã nhúng",
                             extra_text=f"Các gói còn thiếu: {', '.join(missing)}")
            sys.exit(1)
        _bprint(f"⏳ Thiếu thư viện Python: {', '.join(missing)} — đang tự động cài đặt qua pip...")
        ok = _pip_install(missing)
        if ok:
            _bprint("✅ Đã cài xong thư viện Python.")
            importlib.invalidate_caches()
        else:
            _bprint("❌ Cài tự động thất bại. Hãy cài thủ công bằng lệnh:")
            _bprint(f"   {sys.executable} -m pip install {' '.join(missing)} --break-system-packages")
            write_error_log("Bootstrap — cài thư viện Python thất bại",
                             extra_text=f"Các gói còn thiếu: {', '.join(missing)}")
            sys.exit(1)

    # Gói phụ (Discord Rich Presence...) — cố gắng cài nhưng KHÔNG chặn launcher
    # nếu thất bại (không có mạng, v.v.) vì đây chỉ là tính năng cộng thêm.
    opt_missing = []
    for mod_name, pip_name in OPTIONAL_PIP_PACKAGES.items():
        try:
            importlib.import_module(mod_name)
        except ImportError:
            opt_missing.append(pip_name)
    if opt_missing:
        _bprint(f"⏳ Thư viện phụ còn thiếu: {', '.join(opt_missing)} — thử cài (không bắt buộc)...")
        if _pip_install(opt_missing):
            _bprint("✅ Đã cài xong thư viện phụ.")
            importlib.invalidate_caches()
        else:
            _bprint("ℹ Không cài được một số thư viện phụ (Discord RPC / trình duyệt nhúng) — "
                     "launcher vẫn chạy; tab Browser có thể bị hạn chế.")


def bootstrap_environment():
    osinfo = detect_os()
    _bprint(f"🖥  Hệ điều hành phát hiện được: {osinfo['pretty']}")
    ensure_system_packages(osinfo)
    ensure_python_packages()
    return osinfo


OS_INFO = bootstrap_environment()

# ==========================================================================

import tkinter as tk
from tkinter import filedialog


def _tk_report_callback_exception(self, exc_type, exc_value, exc_tb):
    """Mọi lỗi xảy ra bên trong các callback của Tkinter (nút bấm, sự kiện,
    .after(...)) đều đi qua đây thay vì sys.excepthook — ghi lại thành .txt
    để launcher không bao giờ 'lặng lẽ' bỏ qua lỗi."""
    write_error_log("Callback giao diện (Tkinter)", exc=exc_value)
    traceback.print_exception(exc_type, exc_value, exc_tb)


tk.Tk.report_callback_exception = _tk_report_callback_exception

try:
    import ttkbootstrap as tb
    from ttkbootstrap.constants import *
    from ttkbootstrap import ScrolledText
except ImportError:
    import traceback
    print("Lỗi import ttkbootstrap — chi tiết:")
    traceback.print_exc()
    print("\nNếu dòng lỗi trên nhắc tới 'tkinter': cài gói hệ thống 'sudo pacman -S tk' (Arch) "
          "hoặc 'sudo apt install python3-tk' (Debian/Ubuntu).")
    print("Nếu nhắc tới thư viện khác (vd PIL/Pillow): pip install --force-reinstall pillow --break-system-packages")
    sys.exit(1)

try:
    import minecraft_launcher_lib as mll
except ImportError:
    mll = None

try:
    import requests
except ImportError:
    requests = None

# ===== Patch toàn cục =====
# 1) Windows: mọi subprocess (java, powershell...) chạy KHÔNG bật cửa sổ cmd.
if sys.platform == "win32":
    _orig_popen_init = subprocess.Popen.__init__

    def _popen_init_nowin(self, *a, **kw):
        kw["creationflags"] = kw.get("creationflags", 0) | 0x08000000  # CREATE_NO_WINDOW
        _orig_popen_init(self, *a, **kw)

    subprocess.Popen.__init__ = _popen_init_nowin

# 2) Tắt xác minh chứng chỉ HTTPS (hết lỗi SSL / CERTIFICATE_VERIFY_FAILED khi tải).
try:
    import ssl as _ssl
    _ssl._create_default_https_context = _ssl._create_unverified_context
    os.environ["PYTHONHTTPSVERIFY"] = "0"
except Exception:
    pass
if requests is not None:
    try:
        import urllib3
        urllib3.disable_warnings()
    except Exception:
        pass
    _orig_merge_env = requests.Session.merge_environment_settings

    def _merge_env_noverify(self, url, proxies, stream, verify, cert):
        st = _orig_merge_env(self, url, proxies, stream, verify, cert)
        st["verify"] = False
        return st

    requests.Session.merge_environment_settings = _merge_env_noverify


def fetch_to(url, dest):
    """Tải file bằng requests (có User-Agent), ghi .part rồi đổi tên."""
    dest = Path(dest)
    tmp = dest.with_name(dest.name + ".part")
    with requests.get(url, stream=True, timeout=60, allow_redirects=True,
                      headers={"User-Agent": "ArchClient/2.1 (launcher)"}) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=262144):
                if chunk:
                    f.write(chunk)
    os.replace(tmp, dest)


def _jar_is(slug, name):
    """Jar này có phải mod `slug` không (sodium ≠ sodium-extra)."""
    n = name.lower()
    if slug in ("sodium", "iris"):
        return re.match(rf"^{re.escape(slug)}(?:[-_+ ]?(?:fabric|mc|v?\d)|\.jar$)", n) is not None
    return slug in n


def _mod_ver_tuple(version_number):
    """'mc1.21.11-0.8.14-fabric' -> (0, 8, 14)."""
    v = re.sub(r"mc\d+(?:\.\d+)*", "", version_number or "")
    m = re.search(r"\d+(?:\.\d+)+", v)
    return tuple(int(x) for x in m.group(0).split(".")) if m else ()


def _pad3(t):
    return tuple(t) + (0,) * max(0, 3 - len(t))


def _tok_ok(ver, tok):
    if tok in ("", "*"):
        return True
    m = re.match(r"^(>=|<=|>|<|=|~|\^)?(.+)$", tok)
    op, v = (m.group(1) or "="), m.group(2)
    nums, wild = [], False
    for part in v.split("+")[0].split("-")[0].split("."):
        if part in ("x", "X", "*"):
            wild = True
            break
        if part.isdigit():
            nums.append(int(part))
        else:
            break
    t, n = tuple(nums), len(nums)
    pv, pt = _pad3(ver), _pad3(t)
    if op == ">=":
        return pv >= pt
    if op == ">":
        return pv > pt
    if op == "<=":
        return pv <= pt
    if op == "<":
        return pv < pt
    if op == "~":
        return pv >= pt and tuple(ver[:min(2, max(n, 1))]) == t[:min(2, max(n, 1))]
    if op == "^":
        k = next((i for i, x in enumerate(t) if x != 0), max(n - 1, 0))
        return pv >= pt and tuple(ver[:k + 1]) == t[:k + 1]
    if wild or n < 3:
        return tuple(ver[:n]) == t
    return pv == pt


def _satisfies(ver, pred):
    """Kiểm tra version thoả điều kiện kiểu fabric.mod.json (str hoặc list)."""
    if isinstance(pred, list):
        return any(_satisfies(ver, x) for x in pred)
    for alt in str(pred).split("||"):
        if all(_tok_ok(ver, tok) for tok in alt.split()):
            return True
    return False


def _jar_depends(jar_path, key):
    try:
        with zipfile.ZipFile(jar_path) as z:
            d = json.loads(z.read("fabric.mod.json").decode("utf-8-sig"), strict=False)
        return (d.get("depends") or {}).get(key)
    except Exception:
        return None


try:
    from PIL import Image, ImageTk
except ImportError:
    Image = ImageTk = None

try:
    from pypresence import Presence as DiscordPresence
except ImportError:
    DiscordPresence = None

try:
    from tkinterweb import HtmlFrame as TkHtmlFrame
except ImportError:
    TkHtmlFrame = None

try:
    import webview as pywebview
except ImportError:
    pywebview = None

DISCORD_CLIENT_ID = "1545310964331843584"

# Trang mặc định khi mở browser (HTTPS). URL có version được gắn lúc runtime.
BROWSER_HOME = "https://modrinth.com/mods?l=fabric"
BROWSER_QUICK = [
    ("Modrinth", "https://modrinth.com/mods?l=fabric"),
    ("CurseForge", "https://www.curseforge.com/minecraft/search?class=mc-mods"),
    ("Planet MC", "https://www.planetminecraft.com/resources/mods/?order=order_popularity"),
]

# Công cụ tìm kiếm cho thanh địa chỉ (giống trình duyệt thật): gõ từ khoá
# không phải URL -> tự chuyển thành truy vấn tìm kiếm của engine đang chọn.
SEARCH_ENGINES = {
    "DuckDuckGo": "https://duckduckgo.com/?q={q}",
    "Google":     "https://www.google.com/search?q={q}",
    "Bing":       "https://www.bing.com/search?q={q}",
    "Startpage":  "https://www.startpage.com/sp/search?query={q}",
    "Brave":      "https://search.brave.com/search?q={q}",
    "Modrinth":   "https://modrinth.com/mods?q={q}",
    "CurseForge": "https://www.curseforge.com/minecraft/search?class=mc-mods&search={q}",
    "YouTube":    "https://www.youtube.com/results?search_query={q}",
}
DEFAULT_SEARCH_ENGINE = "DuckDuckGo"

# Host của engine tìm kiếm: KHÔNG được coi là tracker, nếu không thì bấm tìm
# kiếm sẽ bị chính bộ lọc chặn (bing.com/google nằm trong danh sách ads).
SEARCH_ENGINE_HOSTS = {
    "duckduckgo.com", "html.duckduckgo.com", "lite.duckduckgo.com",
    "google.com", "www.google.com",
    "bing.com", "www.bing.com",
    "startpage.com", "www.startpage.com",
    "search.brave.com", "brave.com",
    "youtube.com", "www.youtube.com", "m.youtube.com",
    "modrinth.com", "www.modrinth.com",
    "curseforge.com", "www.curseforge.com",
}


def is_search_engine_url(url: str) -> bool:
    host = _host_of(url)
    return bool(host) and host in SEARCH_ENGINE_HOSTS


def looks_like_url(text: str) -> bool:
    """True nếu chuỗi trông như địa chỉ web; False nếu là từ khoá cần tìm."""
    s = (text or "").strip()
    if not s:
        return False
    if re.match(r"^[a-z][a-z0-9+.-]*://", s, re.I):
        return True
    if " " in s:
        return False
    if s.lower().startswith("localhost"):
        return True
    return bool(re.match(r"^[\w.-]+\.[a-z]{2,}([/:?#]|$)", s, re.I))


def build_search_url(query: str, engine: str = DEFAULT_SEARCH_ENGINE) -> str:
    from urllib.parse import quote_plus
    tmpl = SEARCH_ENGINES.get(engine) or SEARCH_ENGINES[DEFAULT_SEARCH_ENGINE]
    return tmpl.format(q=quote_plus((query or "").strip()))

# Danh sách domain tracker / ads / telemetry — chặn khi điều hướng & strip tham số.
TRACKER_DOMAINS = {
    "google-analytics.com", "googletagmanager.com", "googleadservices.com",
    "doubleclick.net", "googlesyndication.com", "adservice.google.com",
    "facebook.net", "facebook.com", "connect.facebook.net",
    "scorecardresearch.com", "quantserve.com", "outbrain.com", "taboola.com",
    "hotjar.com", "mouseflow.com", "fullstory.com", "mixpanel.com",
    "segment.io", "segment.com", "amplitude.com", "sentry.io",
    "newrelic.com", "nr-data.net", "clarity.ms", "bat.bing.com",
    "ads.twitter.com", "analytics.twitter.com", "t.co",
    "adnxs.com", "advertising.com", "criteo.com", "pubmatic.com",
    "moatads.com", "amazon-adsystem.com", "mc.yandex.ru",
}
TRACKING_QUERY_KEYS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "dclid", "msclkid", "mc_eid", "yclid",
    "_ga", "_gl", "ref", "referrer", "source",
}


def _host_of(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return (urlparse(url).hostname or "").lower().lstrip(".")
    except Exception:
        return ""


def is_tracker_url(url: str) -> bool:
    host = _host_of(url)
    if not host:
        return False
    # Engine tìm kiếm là đích người dùng chủ động mở -> luôn cho qua.
    if host in SEARCH_ENGINE_HOSTS:
        return False
    for t in TRACKER_DOMAINS:
        if host == t or host.endswith("." + t):
            return True
    return False


def strip_tracking_params(url: str) -> str:
    try:
        from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
        p = urlparse(url)
        if not p.query:
            return url
        q = parse_qs(p.query, keep_blank_values=True)
        cleaned = {k: v for k, v in q.items() if k.lower() not in TRACKING_QUERY_KEYS}
        return urlunparse(p._replace(query=urlencode(cleaned, doseq=True)))
    except Exception:
        return url


def sanitize_browse_url(url: str) -> str:
    """Chỉ cho phép http(s); mặc định thêm https; chặn tracker; bỏ param theo dõi."""
    u = (url or "").strip()
    if not u:
        return BROWSER_HOME
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    if is_tracker_url(u):
        return BROWSER_HOME
    return strip_tracking_params(u)


# JS chống tracker tối thiểu tiêm vào trang (chặn beacon / pixel phổ biến).
ANTI_TRACKER_JS = r"""
(function(){
  try {
    var blocked = /google-analytics|googletagmanager|doubleclick|facebook\.net|hotjar|scorecardresearch|clarity\.ms|segment\.|mixpanel|amplitude/i;
    var obs = new MutationObserver(function(muts){
      muts.forEach(function(m){
        m.addedNodes && m.addedNodes.forEach(function(n){
          if (!n || n.nodeType !== 1) return;
          var tag = (n.tagName||'').toLowerCase();
          var src = n.src || n.href || '';
          if ((tag==='script'||tag==='img'||tag==='iframe') && blocked.test(src)) {
            n.remove();
          }
        });
      });
    });
    obs.observe(document.documentElement, {childList:true, subtree:true});
    if (navigator.sendBeacon) {
      navigator.sendBeacon = function(){ return false; };
    }
  } catch(e) {}
})();
"""

APP_DIR = EXE_DIR  # thư mục chứa .exe (hoặc chứa .py khi chạy bằng source)
ICON_PATH = APP_DIR / "img" / "icon.png"
BANNER_PATH = APP_DIR / "img" / "banner.png"

if FROZEN and (not ICON_PATH.exists() or not BANNER_PATH.exists()):
    # img/ không được đặt cạnh .exe — dùng bản dự phòng đã nhúng sẵn bên
    # trong .exe lúc build (PyInstaller giải nén vào sys._MEIPASS khi chạy).
    _bundled_img_dir = Path(getattr(sys, "_MEIPASS", str(APP_DIR))) / "img"
    if not ICON_PATH.exists() and (_bundled_img_dir / "icon.png").exists():
        ICON_PATH = _bundled_img_dir / "icon.png"
    if not BANNER_PATH.exists() and (_bundled_img_dir / "banner.png").exists():
        BANNER_PATH = _bundled_img_dir / "banner.png"
WEBSITE_URL = "https://archclient.netlify.app"


def _soft_round_mask(size, radius=10):
    """Mask bo góc mềm cho icon — không tròn 100% kiểu avatar mạng xã hội."""
    from PIL import ImageDraw
    w, h = size
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    r = max(2, min(radius, w // 4, h // 4))
    draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=255)
    return mask


def _load_image(path, size=None, rounded=False, radius=10):
    if Image is None or not path.exists():
        return None
    try:
        img = Image.open(path).convert("RGBA")
        if size:
            # Cover crop vuông rồi resize — icon không bị méo / letterbox xấu
            tw, th = size
            src_w, src_h = img.size
            scale = max(tw / src_w, th / src_h)
            nw, nh = max(1, int(src_w * scale)), max(1, int(src_h * scale))
            img = img.resize((nw, nh), Image.LANCZOS)
            left = (nw - tw) // 2
            top = (nh - th) // 2
            img = img.crop((left, top, left + tw, top + th))
        if rounded and Image is not None:
            try:
                mask = _soft_round_mask(img.size, radius=radius)
                out = Image.new("RGBA", img.size, (0, 0, 0, 0))
                out.paste(img, (0, 0), mask=mask)
                img = out
            except Exception:
                pass
        return ImageTk.PhotoImage(img)
    except Exception:
        return None


def load_icon_image(size=None, rounded=True):
    """Tải img/icon.png — bo góc nhẹ để không lộ góc vuông cứng."""
    if size is None:
        return _load_image(ICON_PATH, rounded=rounded, radius=12)
    r = max(4, min(size) // 6)
    return _load_image(ICON_PATH, size=size, rounded=rounded, radius=r)


def load_banner_image(max_width=None, max_height=120):
    """Tải banner: giới hạn chiều cao để không chiếm nửa launcher, giữ tỉ lệ."""
    if Image is None or not BANNER_PATH.exists():
        return None
    try:
        img = Image.open(BANNER_PATH).convert("RGBA")
        w, h = img.size
        scale = 1.0
        if max_width and w > max_width:
            scale = min(scale, max_width / w)
        if max_height and h * scale > max_height:
            scale = min(scale, max_height / h)
        if scale < 1.0:
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
        # Bo góc rất nhẹ cho banner
        try:
            from PIL import ImageDraw
            mask = Image.new("L", img.size, 0)
            draw = ImageDraw.Draw(mask)
            draw.rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius=8, fill=255)
            out = Image.new("RGBA", img.size, (0, 0, 0, 0))
            out.paste(img, (0, 0), mask=mask)
            img = out
        except Exception:
            pass
        return ImageTk.PhotoImage(img)
    except Exception:
        return None

# ==========================================================================
# I18N: đa ngôn ngữ (VI/EN, tự động phát hiện theo vị trí máy qua IP)
# ==========================================================================

LANG_STRINGS = {
    "vi": {
        # ---- khung chính ----
        "app_subtitle": "Minecraft {ver} · Fabric · Tối ưu FPS tối đa",
        "status_ready": "Sẵn sàng",
        "status_error": "Lỗi",
        "status_working": "Đang xử lý...",
        "tab_overview": "  📊 Tổng quan  ",
        "tab_settings": "  ⚙️ Cài đặt  ",
        "tab_optimize": "  🚀 Tối ưu FPS  ",
        "tab_log": "  🖥️ Console  ",
        "tab_browser": "  🌐 Browser / Mods  ",
        "mc_dir_label": "Thư mục .minecraft:",
        "btn_choose": "Chọn...",
        "btn_install_fabric": "⬇ Cài / Cập nhật Fabric",
        "btn_play": "▶  CHƠI NGAY",
        "btn_website": "🌐 Website",
        "btn_clear_console": "🗑 Xoá console",
        "btn_save_console": "💾 Lưu log ra .txt",
        "splash_detect": "Đang xác định vị trí & ngôn ngữ...",
        "splash_load": "Đang tải cấu hình...",
        "shortcut_title": "Shortcut desktop / Start Menu",
        "shortcut_install": "Cài shortcut",
        "shortcut_remove": "Gỡ shortcut",
        "shortcut_note": "Linux: file .desktop (Debian, Ubuntu, Arch, Manjaro, …). Windows: icon Desktop + Start Menu.",
        "lang_title": "Ngôn ngữ giao diện",
        "lang_auto": "Tự động (theo IP / quốc gia)",
        "lang_vi": "Tiếng Việt",
        "lang_en": "English",
        "lang_hint": "Tự động = nhận diện theo IP (VN → Tiếng Việt).",
        "ver_title": "Phiên bản Minecraft",
        "ver_note": "Fabric + mod sẽ theo phiên bản đang chọn.",
        "no_mod_for_ver": "Không có bản mod cho phiên bản {ver} + Fabric.",
        # ---- tab tổng quan ----
        "ov_files_title": "Chi tiết file",
        "ov_col_type": "Loại",
        "ov_col_name": "Tên file",
        # ---- tab cài đặt ----
        "set_java": "Java",
        "set_java_browse": "Chọn file...",
        "set_java_unchecked": "☕ Chưa kiểm tra Java",
        "set_java_target": "  Bản cần cài:",
        "set_java_install": "⬇ Kiểm tra / Cài Java tự động",
        "set_ram": "RAM cấp cho game",
        "set_username": "Tên người chơi",
        "set_client_id": "Azure client_id",
        "set_login": "Login Microsoft",
        "set_save": "💾 Lưu cài đặt",
        # ---- tab tối ưu ----
        "opt_title": "🚀 Tối ưu FPS / hiệu năng",
        "opt_sub": "Ghi options.txt tối ưu + tải mod tối ưu còn thiếu từ Modrinth",
        "opt_box": "Mod tối ưu hoá",
        "opt_apply": "🚀 Áp dụng tối ưu FPS ngay",
        "opt_running": "Đang tối ưu...",
        # ---- tab browser ----
        "br_tip": "Trình duyệt mod · tìm & tải Mod / Resource Pack / Shader · chặn tracker khi mở web",
        "br_mode_store": "Kho nội dung (Modrinth)",
        "br_mode_web": "Trang web",
        "br_install_engine": "Cài engine browser",
        "br_type_mod": "🧩 Mods",
        "br_type_resourcepack": "🎨 Resource Packs",
        "br_type_shader": "✨ Shaders",
        "br_type_modpack": "📦 Modpacks",
        "br_search_label": "Tìm:",
        "br_btn_search": "Tìm",
        "br_btn_download": "⬇ Tải mục đã chọn",
        "br_btn_open_page": "Mở trang",
        "br_hint": "Gõ từ khoá → Tìm → chọn một dòng → Tải. Ảnh minh hoạ tải nền, không làm chậm app.",
        "br_col_icon": "Ảnh",
        "br_col_name": "Tên",
        "br_col_author": "Tác giả",
        "br_col_downloads": "Lượt tải",
        "br_col_desc": "Mô tả",
        "br_searching": "Đang tìm «{q}» trên Modrinth…",
        "br_found": "Tìm thấy {n} kết quả (MC {ver}) · chọn một dòng → Tải",
        "br_empty": "Không có kết quả «{q}» cho MC {ver}",
        "br_need_requests": "Thiếu thư viện requests",
        "br_need_query": "Nhập từ khoá để tìm",
        "br_select_first": "Chọn một mục trong danh sách trước",
        "br_downloading": "Đang tải {name}…",
        "br_downloaded": "✅ Đã tải {name} → thư mục {folder}",
        "br_download_fail": "⚠ {name}: không có bản phù hợp MC {ver}",
        "br_error_search": "Lỗi tìm kiếm: {err}",
        "br_error_download": "Lỗi tải: {err}",
        "br_search_engine": "Tìm bằng:",
        "br_url_placeholder": "Nhập địa chỉ web hoặc từ khoá cần tìm…",
        "br_btn_go": "Go",
        "br_btn_web_search": "🔍 Tìm",
        "br_private_window": "Cửa sổ riêng",
        "br_home": "Home",
        "br_engine_ok": "Engine nhúng OK · anti-tracker bật",
        "br_engine_missing_title": "Chưa có engine trang web nhúng",
        "br_engine_missing_body": (
            "Tab «Kho nội dung» vẫn dùng được ngay (không cần WebKit).\n"
            "Muốn xem trang web đầy đủ trong launcher: bấm «Cài engine browser» "
            "rồi khởi động lại — hoặc dùng «Cửa sổ riêng» (hiển thị chuẩn nhất)."
        ),
        "br_open_secure": "Mở cửa sổ web an toàn",
        "br_use_store": "Dùng Kho nội dung hoặc Cửa sổ riêng",
        "br_blocked_tracker": "Đã chặn URL tracker",
        "br_loading": "Đang tải · {host} · anti-tracker",
        "br_loaded": "OK · {host} · đã chặn tracker",
        "br_load_error": "Lỗi tải trang: {err}",
        "br_no_engine": "Không có engine nhúng — bấm «Cửa sổ riêng» hoặc «Cài engine browser»",
        "br_installing_engine": "Đang cài engine…",
        "br_engine_installed": "Cài xong — thử tab Trang web",
        "br_engine_partial": "Cài chưa đủ — dùng Kho nội dung",
        # ---- console ----
        "log_title": "🖥️  Console",
    },
    "en": {
        # ---- main shell ----
        "app_subtitle": "Minecraft {ver} · Fabric · Max FPS optimization",
        "status_ready": "Ready",
        "status_error": "Error",
        "status_working": "Working...",
        "tab_overview": "  📊 Overview  ",
        "tab_settings": "  ⚙️ Settings  ",
        "tab_optimize": "  🚀 FPS Optimize  ",
        "tab_log": "  🖥️ Console  ",
        "tab_browser": "  🌐 Browser / Mods  ",
        "mc_dir_label": ".minecraft folder:",
        "btn_choose": "Browse...",
        "btn_install_fabric": "⬇ Install / Update Fabric",
        "btn_play": "▶  PLAY NOW",
        "btn_website": "🌐 Website",
        "btn_clear_console": "🗑 Clear console",
        "btn_save_console": "💾 Save log as .txt",
        "splash_detect": "Detecting location & language...",
        "splash_load": "Loading configuration...",
        "shortcut_title": "Desktop / Start Menu shortcut",
        "shortcut_install": "Install shortcut",
        "shortcut_remove": "Remove shortcut",
        "shortcut_note": "Linux: XDG .desktop (Debian, Ubuntu, Arch, Manjaro, …). Windows: Desktop + Start Menu .lnk.",
        "lang_title": "Interface language",
        "lang_auto": "Auto (by IP / country)",
        "lang_vi": "Vietnamese",
        "lang_en": "English",
        "lang_hint": "Auto = detected from your IP (VN → Vietnamese).",
        "ver_title": "Minecraft version",
        "ver_note": "Fabric + mods follow the selected version.",
        "no_mod_for_ver": "No build available for {ver} + Fabric.",
        # ---- overview tab ----
        "ov_files_title": "Installed files",
        "ov_col_type": "Type",
        "ov_col_name": "File name",
        # ---- settings tab ----
        "set_java": "Java",
        "set_java_browse": "Browse...",
        "set_java_unchecked": "☕ Java not checked yet",
        "set_java_target": "  Version to install:",
        "set_java_install": "⬇ Check / Auto-install Java",
        "set_ram": "RAM allocated to the game",
        "set_username": "Player name",
        "set_client_id": "Azure client_id",
        "set_login": "Sign in with Microsoft",
        "set_save": "💾 Save settings",
        # ---- optimize tab ----
        "opt_title": "🚀 FPS / performance optimization",
        "opt_sub": "Write a tuned options.txt + download the missing performance mods from Modrinth",
        "opt_box": "Performance mods",
        "opt_apply": "🚀 Apply FPS optimization now",
        "opt_running": "Optimizing...",
        # ---- browser tab ----
        "br_tip": "Mod browser · search & download Mods / Resource Packs / Shaders · trackers blocked while browsing",
        "br_mode_store": "Content store (Modrinth)",
        "br_mode_web": "Web page",
        "br_install_engine": "Install browser engine",
        "br_type_mod": "🧩 Mods",
        "br_type_resourcepack": "🎨 Resource Packs",
        "br_type_shader": "✨ Shaders",
        "br_type_modpack": "📦 Modpacks",
        "br_search_label": "Search:",
        "br_btn_search": "Search",
        "br_btn_download": "⬇ Download selected",
        "br_btn_open_page": "Open page",
        "br_hint": "Type a keyword → Search → pick a row → Download. Thumbnails load in the background.",
        "br_col_icon": "Icon",
        "br_col_name": "Name",
        "br_col_author": "Author",
        "br_col_downloads": "Downloads",
        "br_col_desc": "Description",
        "br_searching": "Searching «{q}» on Modrinth…",
        "br_found": "Found {n} results (MC {ver}) · pick a row → Download",
        "br_empty": "No results for «{q}» on MC {ver}",
        "br_need_requests": "Missing the requests library",
        "br_need_query": "Type a keyword to search",
        "br_select_first": "Select an item from the list first",
        "br_downloading": "Downloading {name}…",
        "br_downloaded": "✅ Downloaded {name} → {folder} folder",
        "br_download_fail": "⚠ {name}: no build matching MC {ver}",
        "br_error_search": "Search error: {err}",
        "br_error_download": "Download error: {err}",
        "br_search_engine": "Search with:",
        "br_url_placeholder": "Enter a web address or a search keyword…",
        "br_btn_go": "Go",
        "br_btn_web_search": "🔍 Search",
        "br_private_window": "Private window",
        "br_home": "Home",
        "br_engine_ok": "Embedded engine ready · anti-tracker on",
        "br_engine_missing_title": "No embedded web engine yet",
        "br_engine_missing_body": (
            "The «Content store» tab works right away (no WebKit needed).\n"
            "To view full web pages inside the launcher: click «Install browser engine» "
            "and restart — or use «Private window» (best rendering)."
        ),
        "br_open_secure": "Open secure web window",
        "br_use_store": "Use the Content store or a Private window",
        "br_blocked_tracker": "Tracker URL blocked",
        "br_loading": "Loading · {host} · anti-tracker",
        "br_loaded": "OK · {host} · trackers blocked",
        "br_load_error": "Page load error: {err}",
        "br_no_engine": "No embedded engine — click «Private window» or «Install browser engine»",
        "br_installing_engine": "Installing engine…",
        "br_engine_installed": "Done — try the Web page tab",
        "br_engine_partial": "Install incomplete — use the Content store",
        # ---- console ----
        "log_title": "🖥️  Console",
    },
}

# Mô tả mod tối ưu hoá theo ngôn ngữ (dùng cho tab Tối ưu FPS).
MOD_DESCRIPTIONS = {
    "vi": {
        "sodium": "Render engine siêu nhanh — bắt buộc cho FPS cao",
        "lithium": "Tối ưu logic game, giảm tick lag",
        "starlight": "Tối ưu ánh sáng, giảm lag chunk",
        "ferrite-core": "Giảm RAM sử dụng",
        "krypton": "Tối ưu mạng, giảm lag khi chơi server",
        "lazydfu": "Giảm thời gian khởi động game",
        "iris": "Hỗ trợ shader, tương thích Sodium",
        "modernfix": "Giảm RAM + tăng tốc thời gian khởi động",
        "entityculling": "Bỏ qua render entity ngoài tầm nhìn — tăng FPS mạnh",
        "immediatelyfast": "Tối ưu vẽ UI/immediate rendering, tăng FPS thêm",
    },
    "en": {
        "sodium": "Blazing-fast render engine — required for high FPS",
        "lithium": "Optimizes game logic, cuts tick lag",
        "starlight": "Rewrites lighting, removes chunk lag",
        "ferrite-core": "Lowers memory usage",
        "krypton": "Network optimizations, less lag on servers",
        "lazydfu": "Much faster game startup",
        "iris": "Shader support, works with Sodium",
        "modernfix": "Less RAM + faster startup times",
        "entityculling": "Skips rendering entities you can't see — big FPS gain",
        "immediatelyfast": "Speeds up UI / immediate-mode rendering",
    },
}


def detect_language():
    """Tự động chọn 'vi' nếu máy đang ở Việt Nam (qua IP), ngược lại 'en'.
    Không có mạng thì fallback theo locale hệ thống, cuối cùng fallback 'en'."""
    if requests is not None:
        for url in ("https://ipapi.co/json/", "https://ipwho.is/"):
            try:
                r = requests.get(url, timeout=4)
                r.raise_for_status()
                data = r.json()
                country = (data.get("country_code") or data.get("country") or "").upper()
                if country:
                    return "vi" if country == "VN" else "en"
            except Exception:
                continue
    try:
        import locale
        loc = locale.getdefaultlocale()[0] or ""
        if loc.lower().startswith("vi"):
            return "vi"
    except Exception:
        pass
    return "en"


# --------------------------------------------------------------------------

def resolve_language(cfg_lang="auto"):
    """cfg_lang: 'auto' | 'vi' | 'en' — auto = nhận diện IP (VN→vi)."""
    if cfg_lang in ("vi", "en"):
        return cfg_lang
    return detect_language()



# Phiên bản Minecraft hỗ trợ (Fabric) — chọn trong Settings / Tổng quan
MC_VERSIONS = [
    "1.20.1", "1.20.2", "1.20.3", "1.20.4", "1.20.5", "1.20.6",
    "1.21", "1.21.1", "1.21.2", "1.21.3", "1.21.4", "1.21.5",
    "1.21.6", "1.21.7", "1.21.8", "1.21.9", "1.21.10", "1.21.11",
]
# mặc định khi chưa có config
MC_VERSION = "1.21.1"
_OLD_DEFAULT_MC_DIR = Path.home() / ".minecraft"
if sys.platform == "win32":
    # Windows: %APPDATA%\.minecraft (AppData\Roaming), same place as the official launcher.
    DEFAULT_MC_DIR = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")) / ".minecraft"
else:
    DEFAULT_MC_DIR = _OLD_DEFAULT_MC_DIR
CONFIG_DIR = Path.home() / ".config" / "arch-client-launcher"
CONFIG_FILE = CONFIG_DIR / "config.json"

# Minecraft 1.20.5+ (bao gồm 1.21.x) yêu cầu tối thiểu Java 21 để chạy.
JAVA_MAJOR_REQUIRED = 21
# Các bản Java người dùng có thể tự chọn để cài (21 = tối thiểu, 26 = mới nhất).
JAVA_VERSION_CHOICES = [str(v) for v in range(21, 27)]
JRE_DIR = CONFIG_DIR / "jre"

OPTIMIZATION_MODS = {
    "sodium":            "Render engine siêu nhanh — bắt buộc cho FPS cao",
    "lithium":           "Tối ưu logic game, giảm tick lag",
    "starlight":         "Tối ưu ánh sáng, giảm lag chunk",
    "ferrite-core":       "Giảm RAM sử dụng",
    "krypton":           "Tối ưu mạng, giảm lag khi chơi server",
    "lazydfu":           "Giảm thời gian khởi động game",
    "iris":              "Hỗ trợ shader, tương thích Sodium",
    "modernfix":         "Giảm RAM + tăng tốc thời gian khởi động",
    "entityculling":     "Bỏ qua render entity ngoài tầm nhìn — tăng FPS mạnh",
    "immediatelyfast":   "Tối ưu vẽ UI/immediate rendering, tăng FPS thêm",
}

OPTIMIZED_OPTIONS = {
    "maxFps": "260", "renderDistance": "8", "simulationDistance": "6",
    "particles": "1", "ao": "1", "graphicsMode": "0", "clouds": "0",
    "biomeBlendRadius": "0", "entityShadows": "false", "vsync": "false",
    "guiScale": "2", "mipmapLevels": "0", "fboEnable": "true", "enableVsync": "false",
}

CATEGORIES = [
    ("mods", {".jar"}, "🧩", "Mods"),
    ("resourcepacks", {".zip"}, "🎨", "Resource Packs"),
    ("shaderpacks", {".zip"}, "✨", "Shaderpacks"),
    ("schematics", {".litematic", ".schem", ".nbt", ".schematic"}, "🧱", "Schematics"),
]



def default_config():
    return {
        "mc_dir": str(DEFAULT_MC_DIR), "java_path": "java", "ram_mb": 3072,
        "username": "Player", "azure_client_id": "",
        "auto_install_shortcuts": True,
        "mc_version": MC_VERSION,
        "lang": "auto",  # auto | vi | en
        "java_major": JAVA_MAJOR_REQUIRED,  # bản Java sẽ tự cài: 21..26
        "search_engine": DEFAULT_SEARCH_ENGINE,  # DuckDuckGo | Google | Bing | ...
    }


def load_config():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        try:
            cfg = default_config()
            cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
            try:
                if (sys.platform == "win32"
                        and Path(cfg.get("mc_dir", "")) == _OLD_DEFAULT_MC_DIR
                        and not _OLD_DEFAULT_MC_DIR.exists()):
                    cfg["mc_dir"] = str(DEFAULT_MC_DIR)
            except Exception:
                pass
            return cfg
        except Exception:
            pass
    return default_config()


def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


REQUIRED_MC_SUBDIRS = [
    "mods", "resourcepacks", "shaderpacks", "schematics",
    "saves", "screenshots", "config", "logs", "crash-reports", "versions",
]


def ensure_minecraft_dir_safe(mc_dir: Path):
    """Never crash: on failure fall back to DEFAULT_MC_DIR. Returns (dir, result)."""
    for cand in (Path(mc_dir), DEFAULT_MC_DIR):
        try:
            res = ensure_minecraft_dir(cand)
            res["error"] = None if cand == Path(mc_dir) else f"cannot use {mc_dir}, using {cand}"
            return cand, res
        except Exception as e:
            write_error_log("Create .minecraft", exc=e)
    return Path(mc_dir), {"first_time": False, "created": [],
                          "error": f"cannot create {mc_dir}"}


def ensure_minecraft_dir(mc_dir: Path) -> dict:
    """Tự động nhận diện & khởi tạo cấu trúc thư mục .minecraft.

    - Nếu thư mục .minecraft chưa hề tồn tại: tự tạo TẤT CẢ các thư mục con cần thiết.
    - Nếu đã tồn tại nhưng thiếu một vài thư mục con (vd người dùng mới cài lại
      game, hoặc thư mục bị xoá nhầm): chỉ tạo bù đúng những cái đang thiếu.

    Trả về dict:
        {"first_time": bool, "created": [tên các thư mục con vừa được tạo]}
    """
    first_time = not mc_dir.exists()
    mc_dir.mkdir(parents=True, exist_ok=True)

    created = []
    for d in REQUIRED_MC_SUBDIRS:
        sub = mc_dir / d
        if not sub.exists():
            sub.mkdir(parents=True, exist_ok=True)
            created.append(d)

    # options.txt không bắt buộc nhưng nếu thiếu hoàn toàn (máy mới),
    # ghi sẵn 1 file rỗng để game không lỗi khi đọc lần đầu.
    opt_path = mc_dir / "options.txt"
    if first_time and not opt_path.exists():
        try:
            opt_path.write_text("", encoding="utf-8")
        except Exception:
            pass

    return {"first_time": first_time, "created": created}



# ==========================================================================
# SHORTCUT: Linux .desktop (XDG) + Windows .lnk (Desktop / Start Menu)
# ==========================================================================
# Debian / Ubuntu / Mint / Pop!_OS / Arch / Manjaro / EndeavourOS / Garuda /
# CachyOS / Fedora đều đọc ~/.local/share/applications/*.desktop.
# Windows 10/11: Desktop + %APPDATA%\Microsoft\Windows\Start Menu\Programs.

SHORTCUT_DESKTOP_ID = "arch-client.desktop"
SHORTCUT_WINDOWS_NAME = "Arch Client.lnk"
SHORTCUT_ICON_NAME = "arch-client"


def _desktop_quote(value: str) -> str:
    if re.search(r"""[\s"'\\$`<>~|&;*?!#()\[\]{}]""", value):
        esc = (value.replace("\\", "\\\\").replace('"', '\\"')
                    .replace("$", "\\$").replace("`", "\\`"))
        return f'"{esc}"'
    return value


def linux_applications_dir() -> Path:
    data_home = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    return Path(data_home) / "applications"


def linux_desktop_dir() -> Path:
    try:
        r = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True,
                           text=True, timeout=4)
        p = Path((r.stdout or "").strip())
        if r.returncode == 0 and str(p) and p.exists():
            return p
    except Exception:
        pass
    dirs_file = Path.home() / ".config" / "user-dirs.dirs"
    if dirs_file.exists():
        try:
            for line in dirs_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("XDG_DESKTOP_DIR="):
                    raw = line.split("=", 1)[1].strip().strip('"')
                    raw = raw.replace("$HOME", str(Path.home()))
                    p = Path(raw)
                    if p.exists():
                        return p
        except Exception:
            pass
    home = Path.home()
    for name in ("Desktop", "Máy tính", "Bàn làm việc", "Schreibtisch",
                 "Bureau", "Escritorio", "Pulpit"):
        cand = home / name
        if cand.is_dir():
            return cand
    return home / "Desktop"


def linux_hicolor_root() -> Path:
    data_home = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    return Path(data_home) / "icons" / "hicolor"


def install_linux_icons() -> str:
    if not ICON_PATH.exists():
        return "minecraft"
    try:
        root = linux_hicolor_root()
        if Image is not None:
            src_img = Image.open(ICON_PATH).convert("RGBA")
            for size in (16, 24, 32, 48, 64, 128, 256):
                dest = root / f"{size}x{size}" / "apps" / f"{SHORTCUT_ICON_NAME}.png"
                dest.parent.mkdir(parents=True, exist_ok=True)
                src_img.resize((size, size), Image.LANCZOS).save(dest, "PNG")
        else:
            dest = root / "256x256" / "apps" / f"{SHORTCUT_ICON_NAME}.png"
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ICON_PATH, dest)
        try:
            subprocess.run(
                ["gtk-update-icon-cache", "-f", "-t", str(root)],
                capture_output=True, timeout=8,
            )
        except Exception:
            pass
        return SHORTCUT_ICON_NAME
    except Exception:
        return str(ICON_PATH)


def build_desktop_entry(exec_python: str, script_path: Path, icon: str,
                        working_dir: Path) -> str:
    exec_line = f"{_desktop_quote(exec_python)} {_desktop_quote(str(script_path))}"
    comment = f"Minecraft Fabric launcher"
    return (
        "[Desktop Entry]\n"
        "Version=1.0\n"
        "Type=Application\n"
        "Name=Arch Client\n"
        "GenericName=Minecraft Launcher\n"
        f"Comment={comment}\n"
        f"Exec={exec_line}\n"
        f"TryExec={exec_python}\n"
        f"Icon={icon}\n"
        f"Path={working_dir}\n"
        "Terminal=false\n"
        "StartupNotify=true\n"
        "Categories=Game;ActionGame;\n"
        "Keywords=minecraft;fabric;launcher;arch-client;\n"
        "StartupWMClass=Arch Client\n"
        "PrefersNonDefaultGPU=false\n"
        "X-GNOME-UsesNotifications=true\n"
    )


def _mark_linux_desktop_trusted(path: Path) -> None:
    try:
        os.chmod(path, 0o755)
    except Exception:
        pass
    for args in (
        ["gio", "set", str(path), "metadata::trusted", "true"],
        ["gio", "set", str(path), "metadata::trusted", "yes"],
    ):
        try:
            subprocess.run(args, capture_output=True, timeout=4)
        except Exception:
            pass


def install_linux_shortcuts() -> dict:
    apps = linux_applications_dir()
    apps.mkdir(parents=True, exist_ok=True)
    desktop = linux_desktop_dir()
    icon = install_linux_icons()
    python = sys.executable
    text = build_desktop_entry(python, Path(__file__).resolve(), icon, APP_DIR)
    written = []
    app_file = apps / SHORTCUT_DESKTOP_ID
    app_file.write_text(text, encoding="utf-8")
    os.chmod(app_file, 0o755)
    written.append(str(app_file))
    desk_file = None
    try:
        desktop.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    if desktop.exists():
        desk_file = desktop / SHORTCUT_DESKTOP_ID
        desk_file.write_text(text, encoding="utf-8")
        _mark_linux_desktop_trusted(desk_file)
        written.append(str(desk_file))
    for cmd in (
        ["update-desktop-database", str(apps)],
        ["xdg-desktop-menu", "forceupdate"],
    ):
        try:
            subprocess.run(cmd, capture_output=True, timeout=8)
        except Exception:
            pass
    return {
        "files": written,
        "applications": str(app_file),
        "desktop": str(desk_file) if desk_file else None,
    }


def windows_desktop_dir() -> Path:
    userprofile = Path(os.environ.get("USERPROFILE", str(Path.home())))
    onedrive = os.environ.get("OneDrive")
    candidates = []
    if onedrive:
        candidates.append(Path(onedrive) / "Desktop")
    candidates.append(userprofile / "Desktop")
    public = os.environ.get("PUBLIC")
    if public:
        candidates.append(Path(public) / "Desktop")
    for c in candidates:
        if c.is_dir():
            return c
    return userprofile / "Desktop"


def windows_start_menu_dir() -> Path:
    appdata = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    d = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def windows_python_target() -> Path:
    if FROZEN:
        # Bản .exe đóng gói: shortcut chạy thẳng file .exe, không cần python.
        return Path(sys.executable)
    exe = Path(sys.executable)
    if exe.name.lower() in ("python.exe", "python3.exe"):
        pythonw = exe.with_name("pythonw.exe")
        if pythonw.exists():
            return pythonw
    return exe


def windows_ico_path():
    dest = CONFIG_DIR / "arch-client.ico"
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    if Image is None or not ICON_PATH.exists():
        return dest if dest.exists() else None
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        img = Image.open(ICON_PATH).convert("RGBA")
        img.save(dest, format="ICO",
                 sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        return dest
    except Exception:
        return None


def _ps_single(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def install_windows_shortcuts() -> dict:
    target = str(windows_python_target())
    workdir = str(APP_DIR)
    ico = windows_ico_path()
    icon_loc = f"{ico},0" if ico else f"{target},0"
    desktop = windows_desktop_dir()
    start = windows_start_menu_dir()
    desktop.mkdir(parents=True, exist_ok=True)
    links = [str(desktop / SHORTCUT_WINDOWS_NAME), str(start / SHORTCUT_WINDOWS_NAME)]
    if FROZEN:
        # .exe tự chạy được — không cần truyền script.py làm tham số nữa.
        arg = ""
    else:
        script = str(Path(__file__).resolve())
        arg = f'"{script}"'
    lines = [
        "$ErrorActionPreference = 'Stop'",
        "$W = New-Object -ComObject WScript.Shell",
        "function New-ArchShortcut([string]$Path) {",
        "  $s = $W.CreateShortcut($Path)",
        f"  $s.TargetPath = {_ps_single(target)}",
        f"  $s.Arguments = {_ps_single(arg)}",
        f"  $s.WorkingDirectory = {_ps_single(workdir)}",
        f"  $s.Description = {_ps_single('Arch Client — Minecraft Fabric Launcher')}",
        "  $s.WindowStyle = 1",
        f"  $s.IconLocation = {_ps_single(icon_loc)}",
        "  $s.Save()",
        "}",
    ]
    for link in links:
        lines.append(f"New-ArchShortcut {_ps_single(link)}")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    ps_file = CONFIG_DIR / "_mk_shortcut.ps1"
    ps_file.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps_file)],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "PowerShell failed").strip()
            raise RuntimeError(err)
    finally:
        try:
            ps_file.unlink()
        except Exception:
            pass
    return {"files": links, "desktop": links[0], "start_menu": links[1]}


def shortcut_locations() -> dict:
    system = platform.system()
    if system == "Windows":
        return {
            "desktop": str(windows_desktop_dir() / SHORTCUT_WINDOWS_NAME),
            "menu": str(windows_start_menu_dir() / SHORTCUT_WINDOWS_NAME),
        }
    if system == "Linux":
        return {
            "desktop": str(linux_desktop_dir() / SHORTCUT_DESKTOP_ID),
            "menu": str(linux_applications_dir() / SHORTCUT_DESKTOP_ID),
        }
    return {}


def shortcuts_present() -> bool:
    locs = shortcut_locations()
    return any(Path(p).exists() for p in locs.values()) if locs else False


def remove_installed_shortcuts() -> list:
    removed = []
    for p in shortcut_locations().values():
        path = Path(p)
        if path.exists():
            path.unlink()
            removed.append(str(path))
    return removed


def install_os_shortcuts() -> dict:
    system = platform.system()
    if system == "Linux":
        return {"os": "Linux", **install_linux_shortcuts()}
    if system == "Windows":
        return {"os": "Windows", **install_windows_shortcuts()}
    raise RuntimeError(
        f"OS chưa hỗ trợ tự cài shortcut (chỉ Linux & Windows): {system or 'unknown'}"
    )


# ==========================================================================
# JAVA (OpenJDK): tự nhận diện thiếu Java trên mọi OS và tự động cài
# ==========================================================================

def find_bundled_java() -> "Path | None":
    """Tìm file java đã được launcher tự tải & giải nén trước đó (nếu có)."""
    if not JRE_DIR.exists():
        return None
    exe_name = "java.exe" if platform.system() == "Windows" else "java"
    matches = [p for p in JRE_DIR.rglob(exe_name) if p.parent.name == "bin"]
    if not matches:
        return None
    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0]


def get_java_version(java_exe) -> "int | None":
    """Chạy `java -version` và trả về số phiên bản chính (vd 21), None nếu lỗi."""
    try:
        result = subprocess.run([str(java_exe), "-version"], capture_output=True,
                                  text=True, timeout=10)
        output = (result.stdout or "") + (result.stderr or "")
        m = re.search(r'version\s+"(\d+)', output)
        if not m:
            m = re.search(r'(\d+)\.\d+\.\d+', output)
        return int(m.group(1)) if m else None
    except Exception:
        return None


def resolve_java_path(configured: str) -> "str | None":
    """Quy đổi giá trị người dùng nhập (đường dẫn tuyệt đối hoặc chỉ 'java')
    thành đường dẫn thực thi được, hoặc None nếu không tìm thấy."""
    configured = (configured or "").strip() or "java"
    if os.path.isabs(configured) and Path(configured).exists():
        return configured
    found = shutil.which(configured)
    return found


def adoptium_download_info(java_major=JAVA_MAJOR_REQUIRED):
    """Trả về (url, ext) cho bản OpenJDK (Eclipse Temurin) phù hợp OS/kiến trúc
    hiện tại, hoặc (None, None) nếu OS không được hỗ trợ tự động cài."""
    system = platform.system()
    machine = platform.machine().lower()

    if system == "Windows":
        os_name, ext = "windows", "zip"
    elif system == "Linux":
        os_name, ext = "linux", "tar.gz"
    else:
        return None, None

    if machine in ("amd64", "x86_64"):
        arch = "x64"
    elif machine in ("arm64", "aarch64"):
        arch = "aarch64"
    else:
        return None, None

    url = (f"https://api.adoptium.net/v3/binary/latest/{java_major}/ga/"
           f"{os_name}/{arch}/jdk/hotspot/normal/eclipse?project=jdk")
    return url, ext


def download_file(url, dest_path: Path, log_fn=_bprint):
    """Tải file với log tiến độ theo mốc 10%. Ném exception nếu lỗi mạng."""
    with requests.get(url, stream=True, timeout=60, allow_redirects=True) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        downloaded = 0
        last_pct = -100
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=262144):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = int(downloaded * 100 / total)
                    if pct - last_pct >= 10:
                        mb_done = downloaded // (1024 * 1024)
                        mb_total = total // (1024 * 1024)
                        log_fn(f"  ⬇ {pct}% ({mb_done}MB / {mb_total}MB)")
                        last_pct = pct
    return dest_path


def extract_archive(archive_path: Path, dest_dir: Path, ext: str):
    dest_dir.mkdir(parents=True, exist_ok=True)
    if ext == "zip":
        with zipfile.ZipFile(archive_path) as z:
            z.extractall(dest_dir)
    else:
        with tarfile.open(archive_path) as t:
            t.extractall(dest_dir)


def install_java_via_pkg_manager(osinfo, java_major=JAVA_MAJOR_REQUIRED) -> bool:
    """Thử cài OpenJDK qua trình quản lý gói của distro Linux trước (nhanh
    hơn và tích hợp hệ thống tốt hơn bản tải rời). Trả về True nếu có vẻ
    thành công (không đảm bảo đúng version — hàm gọi sẽ tự kiểm tra lại)."""
    pm = osinfo.get("pkg_manager")
    if pm == "pacman":
        return _run(["pacman", "-Sy", "--needed", "--noconfirm", "jdk-openjdk"], use_sudo=True)
    elif pm == "apt":
        _run(["apt-get", "update"], use_sudo=True)
        ok = _run(["apt-get", "install", "-y", f"openjdk-{java_major}-jdk"], use_sudo=True)
        if not ok:
            ok = _run(["apt-get", "install", "-y", "default-jdk"], use_sudo=True)
        return ok
    return False



class App(tb.Window):
    def __init__(self, lang="vi"):
        super().__init__(themename="flatly")
        self.cfg = load_config()
        # ngôn ngữ: config (auto/vi/en) ưu tiên hơn tham số splash nếu user đã chọn tay
        cfg_lang = self.cfg.get("lang", "auto")
        if cfg_lang in ("vi", "en"):
            lang = cfg_lang
        self.lang = lang if lang in LANG_STRINGS else "en"
        self.LANG = LANG_STRINGS[self.lang]

        ver = self.cfg.get("mc_version") or MC_VERSION
        if ver not in MC_VERSIONS:
            MC_VERSIONS.append(ver)
        self.mc_version = ver

        self.title("Arch Client — Minecraft " + self.mc_version)
        self.geometry("920x680")
        self.minsize(780, 580)

        self._icon_full = load_icon_image()
        if self._icon_full:
            self.iconphoto(True, self._icon_full)

        self.mc_dir = Path(self.cfg["mc_dir"])
        self.access_token = None
        self.uuid = None

        self.discord_rpc = None
        self.discord_start_time = int(time.time())

        self.mc_dir, mc_dir_result = ensure_minecraft_dir_safe(self.mc_dir)
        self.cfg["mc_dir"] = str(self.mc_dir)

        self._build_header()
        self._build_footer()
        self._build_body()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.refresh_all()

        self.log(f"🖥 Hệ điều hành: {OS_INFO['pretty']}")
        if mc_dir_result.get("error"):
            self.log(f"⚠ .minecraft: {mc_dir_result['error']}")
        if mc_dir_result["first_time"]:
            self.log(f"📁 Chưa có .minecraft — đã tự động tạo mới hoàn toàn tại: {self.mc_dir}")
            self.log(f"   (đã tạo {len(mc_dir_result['created'])} thư mục con: "
                      f"{', '.join(mc_dir_result['created'])})")
        elif mc_dir_result["created"]:
            self.log(f"🔍 Đã nhận diện .minecraft có sẵn nhưng thiếu thư mục con — đã tạo bù: "
                      f"{', '.join(mc_dir_result['created'])}")
        else:
            self.log("✅ Cấu trúc thư mục .minecraft đầy đủ, không thiếu gì.")
        if mll is None:
            self.log("⚠ Thiếu 'minecraft-launcher-lib' — pip install minecraft-launcher-lib --break-system-packages")
        if requests is None:
            self.log("⚠ Thiếu 'requests' — pip install requests --break-system-packages")

        # Tự động kiểm tra & cài Java nếu thiếu/quá cũ — chạy nền, không chặn UI.
        self.after(200, self.check_java_startup)

        # Discord Rich Presence — hiện đang làm gì / tải gì ngay trên Discord.
        self.after(300, self._init_discord_rpc)

        # Tự cài .desktop (Linux) / Start Menu + Desktop (Windows) nếu chưa có.
        self.after(400, self.install_shortcuts_startup)

        # HUD: pulse status nhẹ + fade-in notebook (không lòe loẹt).
        self._status_pulse_on = True
        self.after(600, self._pulse_status_badge)
        self.after(50, self._fade_in_body)

    # ---------------------------------------------------------------- header
    def t(self, key, default=None, **kw):
        """Lấy chuỗi theo ngôn ngữ hiện tại; thiếu key thì lùi về EN rồi default."""
        s = self.LANG.get(key)
        if s is None:
            s = LANG_STRINGS["en"].get(key)
        if s is None:
            s = default if default is not None else key
        if kw:
            try:
                return s.format(**kw)
            except Exception:
                return s
        return s

    def mod_desc(self, slug):
        """Mô tả mod tối ưu hoá theo ngôn ngữ hiện tại."""
        table = MOD_DESCRIPTIONS.get(self.lang) or MOD_DESCRIPTIONS["en"]
        return table.get(slug) or MOD_DESCRIPTIONS["en"].get(slug, "")

    def _build_header(self):
        # Header gọn: logo bo góc + title, status bên phải — tránh logo nhỏ méo góc cứng.
        header = tb.Frame(self, bootstyle="primary", padding=(16, 14))
        header.pack(fill="x")

        left = tb.Frame(header, bootstyle="primary")
        left.pack(side="left", fill="y")

        title_row = tb.Frame(left, bootstyle="primary")
        title_row.pack(anchor="w")

        self._header_logo = load_icon_image(size=(36, 36), rounded=True)
        if self._header_logo:
            tb.Label(title_row, image=self._header_logo, bootstyle="inverse-primary").pack(
                side="left", padx=(0, 10))
        tb.Label(title_row, text="ARCH CLIENT", font=("", 18, "bold"),
                  bootstyle="inverse-primary").pack(side="left")

        tb.Label(
            left,
            text=self.LANG["app_subtitle"].format(ver=self.mc_version),
            font=("", 9),
            bootstyle="inverse-primary",
        ).pack(anchor="w", pady=(2, 0))

        right = tb.Frame(header, bootstyle="primary")
        right.pack(side="right")
        self.status_badge = tb.Label(
            right,
            text=f"● {self.LANG['status_ready']}",
            bootstyle="inverse-success",
            font=("", 10, "bold"),
        )
        self.status_badge.pack(anchor="e", pady=(4, 0))
        self._status_text_base = self.LANG["status_ready"]

    # ------------------------------------------------------------------ body
    def _build_body(self):
        self.nb = tb.Notebook(self, bootstyle="primary")
        self.nb.pack(fill="both", expand=True, padx=14, pady=(10, 4))

        self.tab_overview = tb.Frame(self.nb, padding=14)
        self.tab_settings = tb.Frame(self.nb, padding=14)
        self.tab_optimize = tb.Frame(self.nb, padding=14)
        self.tab_browser = tb.Frame(self.nb, padding=8)
        self.tab_log = tb.Frame(self.nb, padding=10)

        self.nb.add(self.tab_overview, text=self.LANG["tab_overview"])
        self.nb.add(self.tab_settings, text=self.LANG["tab_settings"])
        self.nb.add(self.tab_optimize, text=self.LANG["tab_optimize"])
        self.nb.add(self.tab_browser, text=self.LANG.get("tab_browser", "  Browser  "))
        self.nb.add(self.tab_log, text=self.LANG["tab_log"])

        self._build_overview_tab()
        self._build_settings_tab()
        self._build_optimize_tab()
        self._build_browser_tab()
        self._build_log_tab()

        self._discord_tab_states = {
            str(self.tab_overview): "Đang xem: Tổng quan",
            str(self.tab_settings): "Đang xem: Cài đặt",
            str(self.tab_optimize): "Đang xem: Tối ưu FPS",
            str(self.tab_browser): "Đang duyệt: Browser (chống tracker)",
            str(self.tab_log): "Đang xem: Console",
        }
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    # --------------------------------------------------------------- footer
    def _build_footer(self):
        bar = tb.Frame(self, padding=(14, 10))
        bar.pack(side="bottom", fill="x")

        tb.Separator(self, bootstyle="secondary").pack(side="bottom", fill="x")

        left = tb.Frame(bar)
        left.pack(side="left")

        tb.Button(left, text=self.LANG["btn_install_fabric"], bootstyle="info-outline",
                   command=self.install_fabric_thread).pack(side="left", ipady=4)

        tb.Button(left, text=self.LANG["btn_website"], bootstyle="primary-outline",
                   command=self.open_website).pack(side="left", padx=(10, 0), ipady=4)

        self.play_btn = tb.Button(bar, text=self.LANG["btn_play"], bootstyle="success",
                                    width=20, command=self.launch_game_thread)
        self.play_btn.pack(side="right", ipady=6)

    def open_website(self):
        webbrowser.open(WEBSITE_URL)

    # ---------------------------------------------------------- overview tab
    def _build_overview_tab(self):
        f = self.tab_overview

        # Hàng phiên bản Minecraft (không banner)
        verbar = tb.Frame(f)
        verbar.pack(fill="x", pady=(0, 10))
        tb.Label(verbar, text=self.LANG.get("ver_title", "Phiên bản Minecraft") + ":",
                  font=("", 9, "bold")).pack(side="left")
        self.ver_var = tk.StringVar(value=self.mc_version)
        self.ver_combo = tb.Combobox(
            verbar, textvariable=self.ver_var, values=MC_VERSIONS,
            width=12, bootstyle="primary", state="readonly",
        )
        self.ver_combo.pack(side="left", padx=8)
        self.ver_combo.bind("<<ComboboxSelected>>", self._on_version_changed)
        tb.Label(verbar, text=self.LANG.get("ver_note", ""),
                  bootstyle="secondary", font=("", 8)).pack(side="left", padx=(4, 0))

        dirbar = tb.Frame(f)
        dirbar.pack(fill="x", pady=(0, 12))
        tb.Label(dirbar, text=self.LANG["mc_dir_label"], font=("", 9, "bold")).pack(side="left")
        self.dir_var = tk.StringVar(value=str(self.mc_dir))
        tb.Entry(dirbar, textvariable=self.dir_var, bootstyle="primary").pack(
            side="left", fill="x", expand=True, padx=8)
        tb.Button(dirbar, text=self.LANG["btn_choose"], bootstyle="secondary-outline",
                   command=self.choose_dir).pack(side="left", padx=2)
        tb.Button(dirbar, text="⟳", bootstyle="secondary-outline", width=3,
                   command=self.refresh_all).pack(side="left")

        # File list
        list_wrap = tb.Labelframe(f, text=self.t("ov_files_title"), padding=8,
                                   bootstyle="secondary")
        list_wrap.pack(fill="both", expand=True)

        cols = ("loai", "ten")
        self.tree = tb.Treeview(list_wrap, columns=cols, show="headings",
                                  bootstyle="primary", height=12)
        self.tree.heading("loai", text=self.t("ov_col_type"))
        self.tree.heading("ten", text=self.t("ov_col_name"))
        self.tree.column("loai", width=140, anchor="w")
        self.tree.column("ten", width=560, anchor="w")
        self.tree.pack(fill="both", expand=True, side="left")

        sb = tb.Scrollbar(list_wrap, orient="vertical", command=self.tree.yview, bootstyle="round-primary")
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)

    def choose_dir(self):
        d = filedialog.askdirectory(initialdir=str(self.mc_dir))
        if d:
            self.mc_dir = Path(d)
            self.mc_dir, result = ensure_minecraft_dir_safe(self.mc_dir)
            if result.get("error"):
                self.log(f"⚠ .minecraft: {result['error']}")
            self.dir_var.set(str(self.mc_dir))
            self.cfg["mc_dir"] = str(self.mc_dir)
            save_config(self.cfg)
            self.refresh_all()
            if result["first_time"]:
                self.log(f"📁 Đã tự động khởi tạo thư mục .minecraft mới tại: {self.mc_dir}")
            elif result["created"]:
                self.log(f"🔍 Đã tạo bù thư mục con còn thiếu: {', '.join(result['created'])}")

    def refresh_all(self):
        if hasattr(self, "dir_var"):
            self.mc_dir = Path(self.dir_var.get())
        self.tree.delete(*self.tree.get_children())
        totals = {}
        for key, exts, icon, label in CATEGORIES:
            p = self.mc_dir / key
            items = []
            if p.exists():
                for item in p.iterdir():
                    if item.is_dir():
                        items.append(item.name + "/")
                    elif item.suffix.lower() in exts:
                        items.append(item.name)
            items.sort()
            totals[key] = len(items)
            for it in items:
                self.tree.insert("", "end", values=(f"{icon} {label}", it))
        installed = set()
        mods_dir = self.mc_dir / "mods"
        if mods_dir.exists():
            installed = {f.name.split("-")[0].lower() for f in mods_dir.glob("*.jar")}
        self._installed_mods = installed

    # --------------------------------------------------------- settings tab
    def _build_settings_tab(self):
        f = self.tab_settings
        pad = {"pady": 8}

        # ---- Ngôn ngữ ----
        tb.Label(f, text=self.LANG.get("lang_title", "Ngôn ngữ"), font=("", 11, "bold")).grid(
            row=0, column=0, sticky="w", **pad)
        self.lang_var = tk.StringVar(value=self.cfg.get("lang", "auto"))
        lang_row = tb.Frame(f)
        lang_row.grid(row=0, column=1, columnspan=2, sticky="w", **pad)
        for val, key in (("auto", "lang_auto"), ("vi", "lang_vi"), ("en", "lang_en")):
            tb.Radiobutton(
                lang_row, text=self.LANG.get(key, val), value=val,
                variable=self.lang_var, bootstyle="primary-toolbutton",
                command=self._on_lang_setting_changed,
            ).pack(side="left", padx=(0, 8))
        tb.Label(
            f,
            text=self.t("lang_hint"),
            bootstyle="secondary", font=("", 8),
        ).grid(row=1, column=1, columnspan=2, sticky="w", pady=(0, 6))

        # ---- Phiên bản MC ----
        tb.Label(f, text=self.LANG.get("ver_title", "Phiên bản Minecraft"),
                  font=("", 11, "bold")).grid(row=2, column=0, sticky="w", **pad)
        self.settings_ver_var = tk.StringVar(value=self.mc_version)
        ver_row = tb.Frame(f)
        ver_row.grid(row=2, column=1, columnspan=2, sticky="w", **pad)
        self.settings_ver_combo = tb.Combobox(
            ver_row, textvariable=self.settings_ver_var, values=MC_VERSIONS,
            width=14, bootstyle="primary", state="readonly",
        )
        self.settings_ver_combo.pack(side="left")
        self.settings_ver_combo.bind("<<ComboboxSelected>>", self._on_version_changed)
        tb.Label(ver_row, text=self.LANG.get("ver_note", ""),
                  bootstyle="secondary", font=("", 8)).pack(side="left", padx=10)

        # ---- Java ----
        tb.Label(f, text=self.t("set_java"), font=("", 11, "bold")).grid(
            row=3, column=0, sticky="w", **pad)
        self.java_var = tk.StringVar(value=self.cfg["java_path"])
        tb.Entry(f, textvariable=self.java_var, width=45, bootstyle="primary").grid(
            row=3, column=1, sticky="w", **pad)
        tb.Button(f, text=self.t("set_java_browse"), bootstyle="secondary-outline",
                   command=self.choose_java).grid(row=3, column=2, sticky="w", padx=6)

        java_row = tb.Frame(f)
        java_row.grid(row=4, column=1, columnspan=2, sticky="w", pady=(0, 6))
        self.java_status_lbl = tb.Label(java_row, text=self.t("set_java_unchecked"),
                                          bootstyle="secondary", font=("", 9))
        self.java_status_lbl.pack(side="left")

        tb.Label(java_row, text=self.t("set_java_target"), bootstyle="secondary").pack(
            side="left", padx=(12, 4))
        self.java_major_var = tk.StringVar(
            value=str(self.cfg.get("java_major", JAVA_MAJOR_REQUIRED)))
        self.java_major_combo = tb.Combobox(
            java_row, textvariable=self.java_major_var, values=JAVA_VERSION_CHOICES,
            width=4, bootstyle="primary", state="readonly",
        )
        self.java_major_combo.pack(side="left")
        self.java_major_combo.bind("<<ComboboxSelected>>", self._on_java_major_changed)

        tb.Button(java_row, text=self.t("set_java_install"), bootstyle="info-outline",
                   command=self.install_java_thread).pack(side="left", padx=(12, 0))

        tb.Label(f, text=self.t("set_ram"), font=("", 11, "bold")).grid(
            row=5, column=0, sticky="w", **pad)
        ram_wrap = tb.Frame(f)
        ram_wrap.grid(row=5, column=1, sticky="w", **pad)
        self.ram_var = tk.IntVar(value=int(self.cfg.get("ram_mb", 3072)))
        tb.Spinbox(ram_wrap, from_=1024, to=32768, increment=512,
                    textvariable=self.ram_var, width=10, bootstyle="primary").pack(side="left")
        tb.Label(ram_wrap, text=" MB", bootstyle="secondary").pack(side="left")

        tb.Label(f, text=self.t("set_username"), font=("", 11, "bold")).grid(
            row=6, column=0, sticky="w", **pad)
        self.user_var = tk.StringVar(value=self.cfg.get("username", "Player"))
        tb.Entry(f, textvariable=self.user_var, width=30, bootstyle="primary").grid(
            row=6, column=1, sticky="w", **pad)

        tb.Label(f, text=self.t("set_client_id"), font=("", 11, "bold")).grid(
            row=7, column=0, sticky="w", **pad)
        self.client_id_var = tk.StringVar(value=self.cfg.get("azure_client_id", ""))
        tb.Entry(f, textvariable=self.client_id_var, width=45, bootstyle="primary").grid(
            row=7, column=1, sticky="w", **pad)
        tb.Button(f, text=self.t("set_login"), bootstyle="info-outline",
                   command=self.login_microsoft_thread).grid(row=7, column=2, sticky="w", padx=6)

        tb.Button(f, text=self.t("set_save"), bootstyle="success",
                   command=self.save_settings).grid(row=8, column=1, sticky="w", pady=12)

        # ---- Shortcuts ----
        tb.Separator(f).grid(row=9, column=0, columnspan=3, sticky="ew", pady=(4, 8))
        tb.Label(f, text=self.LANG.get("shortcut_title", "Shortcut"),
                  font=("", 11, "bold")).grid(row=10, column=0, columnspan=3, sticky="w")
        self.shortcut_status_lbl = tb.Label(f, text="…", bootstyle="secondary", font=("", 9))
        self.shortcut_status_lbl.grid(row=11, column=0, columnspan=3, sticky="w", pady=(4, 8))
        sc_btns = tb.Frame(f)
        sc_btns.grid(row=12, column=0, columnspan=3, sticky="w")
        tb.Button(sc_btns, text=self.LANG.get("shortcut_install", "Cài shortcut"),
                   bootstyle="info", command=self.install_shortcuts_thread).pack(side="left")
        tb.Button(sc_btns, text=self.LANG.get("shortcut_remove", "Gỡ shortcut"),
                   bootstyle="secondary-outline",
                   command=self.remove_shortcuts_thread).pack(side="left", padx=(10, 0))
        tb.Label(f, text=self.LANG.get("shortcut_note", ""),
                  bootstyle="secondary", wraplength=620, justify="left").grid(
            row=13, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.after(0, self._refresh_shortcut_status)


    def _on_ram_change(self, val):
        self.ram_lbl.config(text=f"{int(float(val))} MB")

    def choose_java(self):
        p = filedialog.askopenfilename(title="Chọn java executable")
        if p:
            self.java_var.set(p)

    def save_settings(self):
        # đồng bộ version từ combo nào đang có
        ver = None
        if hasattr(self, "settings_ver_var"):
            ver = self.settings_ver_var.get().strip()
        elif hasattr(self, "ver_var"):
            ver = self.ver_var.get().strip()
        if ver:
            self.mc_version = ver
            self.cfg["mc_version"] = ver
        if hasattr(self, "lang_var"):
            self.cfg["lang"] = self.lang_var.get()
        self.cfg.update({
            "java_path": self.java_var.get(), "ram_mb": int(self.ram_var.get()),
            "username": self.user_var.get(), "azure_client_id": self.client_id_var.get(),
            "mc_dir": str(self.mc_dir),
        })
        save_config(self.cfg)
        self.title("Arch Client — Minecraft " + self.mc_version)
        try:
            if hasattr(self, "ver_var"):
                self.ver_var.set(self.mc_version)
            if hasattr(self, "settings_ver_var"):
                self.settings_ver_var.set(self.mc_version)
        except Exception:
            pass
        self.log(f"✅ Đã lưu cài đặt (MC {self.mc_version}, lang={self.cfg.get('lang')}).")

    def _on_version_changed(self, _event=None):
        """Đổi phiên bản MC: cập nhật config, title, gợi ý cài lại Fabric."""
        ver = None
        if _event is not None:
            w = _event.widget
            try:
                ver = w.get()
            except Exception:
                ver = None
        if not ver:
            if hasattr(self, "settings_ver_var"):
                ver = self.settings_ver_var.get()
            elif hasattr(self, "ver_var"):
                ver = self.ver_var.get()
        if not ver:
            return
        self.mc_version = ver
        self.cfg["mc_version"] = ver
        save_config(self.cfg)
        self.title("Arch Client — Minecraft " + ver)
        try:
            if hasattr(self, "ver_var"):
                self.ver_var.set(ver)
            if hasattr(self, "settings_ver_var"):
                self.settings_ver_var.set(ver)
        except Exception:
            pass
        try:
            self.LANG  # refresh subtitle if header label exists
            # header subtitle is static label — rebuild text via children scan skip
        except Exception:
            pass
        self.log(f"🎮 Phiên bản chơi: {ver} — bấm «Cài / Cập nhật Fabric» để khớp loader.")
        self.set_discord_activity(f"Phiên bản {ver}", "Arch Client")

    def _on_lang_setting_changed(self):
        """Lưu lựa chọn ngôn ngữ; áp dụng ngay nếu vi/en (auto cần restart)."""
        choice = self.lang_var.get()
        self.cfg["lang"] = choice
        save_config(self.cfg)
        if choice in ("vi", "en"):
            self.lang = choice
            self.LANG = LANG_STRINGS[choice]
            self.log(f"🌐 Ngôn ngữ: {choice} — một số nhãn tab áp dụng sau khi mở lại launcher.")
        else:
            detected = detect_language()
            self.log(f"🌐 Ngôn ngữ: tự động (IP → {detected}). Mở lại launcher để áp dụng đầy đủ.")

    # ------------------------------------------------------------- Java
    def _set_java_status(self, text, bootstyle="secondary"):
        self.after(0, lambda: self.java_status_lbl.config(text=text, bootstyle=bootstyle))

    def check_java_startup(self):
        """Tự động kiểm tra Java ngay khi mở launcher — chạy nền, không chặn UI.
        Nếu thiếu hoặc quá cũ, tự động tải OpenJDK phù hợp mà không cần bấm gì."""
        threading.Thread(target=self._check_java_background, daemon=True).start()

    def _check_java_background(self):
        try:
            configured = self.java_var.get().strip() or "java"
            exe = resolve_java_path(configured)
            version = get_java_version(exe) if exe else None

            if exe and version and version >= JAVA_MAJOR_REQUIRED:
                self.log(f"☕ Đã có Java {version} tại: {exe}")
                self._set_java_status(f"☕ Java {version} — OK", "success")
                return

            # Chưa có Java hợp lệ theo cấu hình — thử bản đã tự cài trước đó
            bundled = find_bundled_java()
            if bundled:
                bv = get_java_version(bundled)
                if bv and bv >= JAVA_MAJOR_REQUIRED:
                    self.java_var.set(str(bundled))
                    self.cfg["java_path"] = str(bundled)
                    save_config(self.cfg)
                    self.log(f"☕ Dùng lại Java {bv} đã tải trước đó: {bundled}")
                    self._set_java_status(f"☕ Java {bv} — OK", "success")
                    return

            if exe and version:
                self.log(f"⚠ Java hiện tại là bản {version}, Minecraft {self.mc_version} "
                          f"cần Java {JAVA_MAJOR_REQUIRED}+ — sẽ tự động cài bản phù hợp.")
            else:
                self.log(f"⚠ Chưa tìm thấy Java trên máy — sẽ tự động cài OpenJDK "
                          f"{JAVA_MAJOR_REQUIRED} (Eclipse Temurin).")
            self._set_java_status("☕ Đang tự động cài Java...", "warning")
            self._install_java_auto()
        except Exception as e:
            self.log(f"❌ Lỗi khi kiểm tra Java: {e}")
            write_error_log("Kiểm tra Java lúc khởi động", exc=e)

    def install_java_thread(self):
        threading.Thread(target=self._install_java_auto, daemon=True).start()

    def _on_java_major_changed(self, event=None):
        try:
            self.cfg["java_major"] = int(self.java_major_var.get())
            save_config(self.cfg)
            self.log(f"☕ Sẽ cài OpenJDK {self.cfg['java_major']} ở lần bấm cài tiếp theo.")
        except Exception:
            pass

    def _install_java_auto(self):
        try:
            # Bản Java người dùng chọn trong Settings (21-26), mặc định = tối thiểu bắt buộc.
            try:
                target_major = int(self.java_major_var.get())
            except Exception:
                target_major = int(self.cfg.get("java_major", JAVA_MAJOR_REQUIRED))

            self.set_status("Đang cài Java...", "inverse-warning")
            self._set_java_status("☕ Đang cài đặt...", "warning")
            self.log(f"☕ Bắt đầu cài OpenJDK {target_major}...")

            # Bước 1 (chỉ Linux): thử qua trình quản lý gói hệ thống trước —
            # nhanh hơn, cập nhật được qua hệ thống, phù hợp CachyOS/Arch/Debian/Ubuntu.
            if OS_INFO.get("system") == "Linux" and OS_INFO.get("pkg_manager"):
                self.log(f"  → Thử cài qua trình quản lý gói ({OS_INFO['pkg_manager']})...")
                if install_java_via_pkg_manager(OS_INFO, target_major):
                    exe = shutil.which("java")
                    ver = get_java_version(exe) if exe else None
                    if exe and ver and ver >= JAVA_MAJOR_REQUIRED:
                        self.java_var.set(exe)
                        self.cfg["java_path"] = exe
                        save_config(self.cfg)
                        self.log(f"✅ Đã cài Java {ver} qua trình quản lý gói: {exe}")
                        self._set_java_status(f"☕ Java {ver} — OK", "success")
                        self.set_status(self.t("status_ready"))
                        return
                    self.log("  ⚠ Gói hệ thống không đủ mới hoặc không có sẵn — "
                              "chuyển sang tải bản OpenJDK rời (portable).")
                else:
                    self.log("  ⚠ Không cài được qua trình quản lý gói — "
                              "chuyển sang tải bản OpenJDK rời (portable).")

            # Bước 2 (Windows luôn dùng cách này, Linux dùng khi bước 1 thất bại):
            # tải thẳng bản Eclipse Temurin (Adoptium) — không cần quyền quản trị.
            if requests is None:
                self.log("❌ Thiếu thư viện 'requests' nên không thể tự tải Java. "
                          "Cài thủ công: pip install requests --break-system-packages")
                self._set_java_status("☕ Cần cài Java thủ công", "danger")
                self.set_status(self.t("status_error"), "inverse-danger")
                return

            url, ext = adoptium_download_info(target_major)
            if not url:
                self.log(f"❌ Không hỗ trợ tự động cài Java trên hệ điều hành/kiến trúc này "
                          f"({OS_INFO.get('pretty')}). Vui lòng cài Java {target_major} thủ công "
                          "rồi chọn file java trong mục Cài đặt.")
                self._set_java_status("☕ Cần cài Java thủ công", "danger")
                self.set_status(self.t("status_error"), "inverse-danger")
                return

            JRE_DIR.mkdir(parents=True, exist_ok=True)
            archive_path = JRE_DIR / f"openjdk{target_major}.{ext}"
            self.log(f"⬇ Đang tải OpenJDK {target_major} (Eclipse Temurin)... "
                      "có thể mất vài phút tuỳ tốc độ mạng.")
            download_file(url, archive_path, log_fn=self.log)

            self.log("📦 Đang giải nén Java...")
            extract_archive(archive_path, JRE_DIR, ext)
            archive_path.unlink(missing_ok=True)

            java_exe = find_bundled_java()
            if not java_exe:
                raise RuntimeError("Đã tải và giải nén nhưng không tìm thấy file java bên trong.")
            if platform.system() != "Windows":
                try:
                    os.chmod(java_exe, 0o755)
                except Exception:
                    pass

            ver = get_java_version(java_exe) or target_major
            self.java_var.set(str(java_exe))
            self.cfg["java_path"] = str(java_exe)
            save_config(self.cfg)
            self.log(f"✅ Đã cài Java {ver} thành công tại: {java_exe}")
            self._set_java_status(f"☕ Java {ver} — OK", "success")
            self.set_status(self.t("status_ready"))
        except Exception as e:
            self.log(f"❌ Lỗi khi cài Java: {e}")
            log_path = write_error_log("Cài OpenJDK tự động", exc=e)
            if log_path:
                self.log(f"📝 Chi tiết lỗi đã ghi vào: {log_path}")
            self._set_java_status("☕ Cài Java thất bại", "danger")
            self.set_status(self.t("status_error"), "inverse-danger")

    # -------------------------------------------------------- optimize tab
    def _build_optimize_tab(self):
        f = self.tab_optimize
        tb.Label(f, text=self.t("opt_title"), font=("", 14, "bold")).pack(anchor="w")
        tb.Label(f, text=self.t("opt_sub"),
                  bootstyle="secondary").pack(anchor="w", pady=(0, 12))

        self.mod_vars = {}
        box = tb.Labelframe(f, text=self.t("opt_box"), padding=10, bootstyle="secondary")
        box.pack(fill="x", pady=(0, 14))
        for slug in OPTIMIZATION_MODS:
            desc = self.mod_desc(slug)
            var = tk.BooleanVar(value=True)
            self.mod_vars[slug] = var
            row = tb.Frame(box)
            row.pack(fill="x", pady=2)
            tb.Checkbutton(row, variable=var, bootstyle="success-round-toggle").pack(side="left")
            tb.Label(row, text=f"  {slug}", font=("", 10, "bold")).pack(side="left")
            tb.Label(row, text=f" — {desc}", bootstyle="secondary").pack(side="left")

        self.opt_progress = tb.Progressbar(f, mode="indeterminate", bootstyle="success-striped")
        self.opt_progress.pack(fill="x", pady=(4, 10))

        tb.Button(f, text=self.t("opt_apply"), bootstyle="success",
                   command=self.apply_optimization_thread).pack(anchor="w")

    # ----------------------------------------------------------- Browser tab
    # Kho nội dung Modrinth: Mods / Resource Packs / Shaders / Modpacks,
    # có ảnh minh hoạ cho từng mục (tải nền, không chặn UI) + trình duyệt web
    # kèm công cụ tìm kiếm (DuckDuckGo, Google, Bing…) giống trình duyệt thật.

    # project_type Modrinth -> (thư mục đích trong .minecraft, key i18n)
    BROWSE_TYPES = [
        ("mod", "mods", "br_type_mod"),
        ("resourcepack", "resourcepacks", "br_type_resourcepack"),
        ("shader", "shaderpacks", "br_type_shader"),
    ]
    THUMB_SIZE = 36
    MODRINTH_UA = "ArchClient/2.1 (launcher)"

    def _build_browser_tab(self):
        f = self.tab_browser
        self._browser_history = []
        self._browser_hist_i = -1
        self._html_frame = None
        self._browser_mode = "mods"
        self._thumb_cache = {}        # url -> PhotoImage (giữ tham chiếu, tránh GC)
        self._row_images = {}         # iid -> PhotoImage
        self._blank_thumb = None
        self._thumb_token = 0         # huỷ ảnh của lượt tìm cũ

        tb.Label(f, text=self.t("br_tip"), bootstyle="secondary", font=("", 8)).pack(
            anchor="w", pady=(0, 6))

        mode_bar = tb.Frame(f)
        mode_bar.pack(fill="x", pady=(0, 6))
        self._btn_mode_mods = tb.Button(
            mode_bar, text=self.t("br_mode_store"), bootstyle="info",
            command=lambda: self._browser_show_mode("mods"))
        self._btn_mode_mods.pack(side="left", padx=(0, 6))
        self._btn_mode_web = tb.Button(
            mode_bar, text=self.t("br_mode_web"), bootstyle="secondary-outline",
            command=lambda: self._browser_show_mode("web"))
        self._btn_mode_web.pack(side="left", padx=(0, 6))
        tb.Button(mode_bar, text=self.t("br_install_engine"), bootstyle="secondary-outline",
                   command=self._browser_reinstall_deps).pack(side="right")

        # =============================== PANEL: kho nội dung Modrinth =========
        self._panel_mods = tb.Frame(f)
        self._panel_mods.pack(fill="both", expand=True)

        # hàng chọn loại nội dung: Mods / Resource Packs / Shaders / Modpacks
        type_row = tb.Frame(self._panel_mods)
        type_row.pack(fill="x", pady=(0, 6))
        self.browse_type_var = tk.StringVar(value="mod")
        for ptype, _folder, key in self.BROWSE_TYPES:
            tb.Radiobutton(
                type_row, text=self.t(key), value=ptype,
                variable=self.browse_type_var, bootstyle="info-toolbutton",
                command=self._modrinth_search,
            ).pack(side="left", padx=(0, 6))

        search_row = tb.Frame(self._panel_mods)
        search_row.pack(fill="x", pady=(0, 6))
        tb.Label(search_row, text=self.t("br_search_label"),
                  font=("", 9, "bold")).pack(side="left")
        self.mod_search_var = tk.StringVar(value="")
        ent = tb.Entry(search_row, textvariable=self.mod_search_var, bootstyle="primary")
        ent.pack(side="left", fill="x", expand=True, padx=8)
        ent.bind("<Return>", lambda e: self._modrinth_search())
        tb.Button(search_row, text=self.t("br_btn_search"), bootstyle="primary",
                   command=self._modrinth_search).pack(side="left", padx=(0, 4))
        tb.Button(search_row, text=self.t("br_btn_download"), bootstyle="success",
                   command=self._modrinth_download_selected).pack(side="left", padx=(0, 4))
        tb.Button(search_row, text=self.t("br_btn_open_page"), bootstyle="secondary-outline",
                   command=self._modrinth_open_selected_page).pack(side="left")

        self.browser_status = tb.Label(self._panel_mods, text=self.t("br_hint"),
                                        bootstyle="secondary", font=("", 8))
        self.browser_status.pack(anchor="w", pady=(0, 4))

        list_wrap = tb.Frame(self._panel_mods)
        list_wrap.pack(fill="both", expand=True)

        # show="tree headings": cột #0 dùng để hiển thị ẢNH của mod/pack.
        cols = ("name", "author", "downloads", "desc")
        self.mod_tree = tb.Treeview(
            list_wrap, columns=cols, show="tree headings",
            bootstyle="primary", height=10)
        self.mod_tree.heading("#0", text=self.t("br_col_icon"))
        self.mod_tree.heading("name", text=self.t("br_col_name"))
        self.mod_tree.heading("author", text=self.t("br_col_author"))
        self.mod_tree.heading("downloads", text=self.t("br_col_downloads"))
        self.mod_tree.heading("desc", text=self.t("br_col_desc"))
        self.mod_tree.column("#0", width=56, minwidth=56, stretch=False, anchor="center")
        self.mod_tree.column("name", width=210, anchor="w")
        self.mod_tree.column("author", width=120, anchor="w")
        self.mod_tree.column("downloads", width=90, anchor="e")
        self.mod_tree.column("desc", width=360, anchor="w")
        self.mod_tree.pack(side="left", fill="both", expand=True)
        self.mod_tree.bind("<Double-1>", lambda e: self._modrinth_download_selected())

        sb = tb.Scrollbar(list_wrap, orient="vertical", command=self.mod_tree.yview,
                           bootstyle="round-primary")
        sb.pack(side="right", fill="y")
        self.mod_tree.configure(yscrollcommand=sb.set)

        # Hàng phải đủ cao mới thấy ảnh 36px (mặc định ttk chỉ ~20px).
        try:
            self.style.configure("Treeview", rowheight=self.THUMB_SIZE + 10)
        except Exception:
            pass

        self._mod_results = []

        # ======================================== PANEL: trình duyệt web ======
        self._panel_web = tb.Frame(f)

        bar = tb.Frame(self._panel_web)
        bar.pack(fill="x", pady=(0, 6))
        tb.Button(bar, text="◀", width=3, bootstyle="secondary-outline",
                   command=self._browser_back).pack(side="left", padx=(0, 2))
        tb.Button(bar, text="▶", width=3, bootstyle="secondary-outline",
                   command=self._browser_forward).pack(side="left", padx=(0, 2))
        tb.Button(bar, text="↻", width=3, bootstyle="secondary-outline",
                   command=self._browser_reload).pack(side="left", padx=(0, 4))
        tb.Button(bar, text=self.t("br_home"), bootstyle="info-outline",
                   command=self._browser_go_home).pack(side="left", padx=(0, 6))
        self.browser_url_var = tk.StringVar(value=BROWSER_HOME)
        url_entry = tb.Entry(bar, textvariable=self.browser_url_var, bootstyle="primary")
        url_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        url_entry.bind("<Return>", lambda e: self._browser_go())
        tb.Button(bar, text=self.t("br_btn_go"), bootstyle="primary",
                   command=self._browser_go).pack(side="left", padx=(0, 4))
        tb.Button(bar, text=self.t("br_private_window"), bootstyle="secondary-outline",
                   command=self._browser_open_secure_window).pack(side="left")

        # ---- hàng công cụ tìm kiếm (giống trình duyệt thật) ----
        engine_row = tb.Frame(self._panel_web)
        engine_row.pack(fill="x", pady=(0, 6))
        tb.Label(engine_row, text=self.t("br_search_engine"),
                  font=("", 9, "bold")).pack(side="left", padx=(0, 6))
        self.search_engine_var = tk.StringVar(
            value=self.cfg.get("search_engine", DEFAULT_SEARCH_ENGINE))
        self.search_engine_combo = tb.Combobox(
            engine_row, textvariable=self.search_engine_var,
            values=list(SEARCH_ENGINES.keys()), width=13,
            bootstyle="info", state="readonly")
        self.search_engine_combo.pack(side="left", padx=(0, 8))
        self.search_engine_combo.bind("<<ComboboxSelected>>", self._on_search_engine_changed)

        self.web_query_var = tk.StringVar(value="")
        q_entry = tb.Entry(engine_row, textvariable=self.web_query_var, bootstyle="info")
        q_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        q_entry.bind("<Return>", lambda e: self._browser_web_search())
        tb.Button(engine_row, text=self.t("br_btn_web_search"), bootstyle="info",
                   command=self._browser_web_search).pack(side="left")

        quick = tb.Frame(self._panel_web)
        quick.pack(fill="x", pady=(0, 6))
        tb.Button(quick, text="Modrinth", bootstyle="secondary-outline",
                   command=self._browser_go_home).pack(side="left", padx=(0, 6))
        tb.Button(
            quick, text="CurseForge", bootstyle="secondary-outline",
            command=lambda: self._browser_navigate(
                "https://www.curseforge.com/minecraft/search?class=mc-mods"
                f"&page=1&pageSize=20&sortBy=relevancy&gameVersion={self.mc_version}"),
        ).pack(side="left", padx=(0, 6))
        tb.Button(
            quick, text="Planet MC", bootstyle="secondary-outline",
            command=lambda: self._browser_navigate(
                "https://www.planetminecraft.com/resources/mods/?order=order_popularity"),
        ).pack(side="left", padx=(0, 6))
        tb.Button(
            quick, text="Resource Packs", bootstyle="secondary-outline",
            command=lambda: self._browser_navigate(
                f"https://modrinth.com/resourcepacks?g={self.mc_version}"),
        ).pack(side="left", padx=(0, 6))

        self.browser_web_status = tb.Label(self._panel_web, text="",
                                            bootstyle="secondary", font=("", 8))
        self.browser_web_status.pack(anchor="w", pady=(0, 4))

        self._browser_host = tb.Frame(self._panel_web, bootstyle="secondary")
        self._browser_host.pack(fill="both", expand=True)

        self._browser_init_engine()
        self._browser_show_mode("mods")
        self.after(400, self._modrinth_search)

    # ------------------------------------------------------------- chế độ
    def _browser_show_mode(self, mode):
        self._browser_mode = mode
        if mode == "mods":
            self._panel_web.pack_forget()
            self._panel_mods.pack(fill="both", expand=True)
            try:
                self._btn_mode_mods.configure(bootstyle="info")
                self._btn_mode_web.configure(bootstyle="secondary-outline")
            except Exception:
                pass
        else:
            self._panel_mods.pack_forget()
            self._panel_web.pack(fill="both", expand=True)
            try:
                self._btn_mode_web.configure(bootstyle="info")
                self._btn_mode_mods.configure(bootstyle="secondary-outline")
            except Exception:
                pass
            if self._html_frame is None:
                self._browser_init_engine()

    def _browser_init_engine(self):
        for w in self._browser_host.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass
        self._html_frame = None
        global TkHtmlFrame
        if TkHtmlFrame is None:
            try:
                from tkinterweb import HtmlFrame as _HF
                TkHtmlFrame = _HF
            except Exception:
                TkHtmlFrame = None
        if TkHtmlFrame is not None:
            try:
                self._html_frame = TkHtmlFrame(self._browser_host, messages_enabled=False)
                self._html_frame.pack(fill="both", expand=True)
                self.browser_web_status.config(text=self.t("br_engine_ok"))
                self.after(200, lambda: self._browser_navigate(BROWSER_HOME, push=True))
                return
            except Exception as e:
                self._html_frame = None
                self.log(f"ℹ Embedded browser error: {e}")
        help_box = tb.Frame(self._browser_host, padding=14)
        help_box.pack(fill="both", expand=True)
        tb.Label(help_box, text=self.t("br_engine_missing_title"),
                  font=("", 11, "bold")).pack(anchor="w")
        tb.Label(help_box, text=self.t("br_engine_missing_body"),
                  bootstyle="secondary", wraplength=620, justify="left").pack(
            anchor="w", pady=(8, 10))
        tb.Button(help_box, text=self.t("br_open_secure"), bootstyle="info",
                   command=self._browser_open_secure_window).pack(anchor="w")
        self.browser_web_status.config(text=self.t("br_use_store"))

    def _browser_set_status(self, text):
        for attr in ("browser_status", "browser_web_status"):
            try:
                getattr(self, attr).config(text=text)
            except Exception:
                pass

    # ------------------------------------------------- Modrinth: tìm kiếm
    def _current_browse_type(self):
        try:
            return self.browse_type_var.get() or "mod"
        except Exception:
            return "mod"

    def _browse_folder_for(self, ptype):
        for t, folder, _key in self.BROWSE_TYPES:
            if t == ptype:
                return folder
        return "mods"

    def _modrinth_facets(self, ptype):
        """Facet tìm kiếm. Chỉ mod/modpack mới cần loader fabric; resource pack
        và shader không gắn loader (gắn vào là ra 0 kết quả)."""
        facets = [f'["project_type:{ptype}"]', f'["versions:{self.mc_version}"]']
        if ptype == "mod":
            facets.insert(1, '["categories:fabric"]')
        return "[" + ",".join(facets) + "]"

    def _modrinth_search(self):
        if requests is None:
            self._browser_set_status(self.t("br_need_requests"))
            return
        ptype = self._current_browse_type()
        q = (self.mod_search_var.get() or "").strip()
        self._browser_set_status(self.t("br_searching", q=q or "top"))
        self._thumb_token += 1
        token = self._thumb_token

        def job():
            try:
                params = {
                    "query": q,
                    "limit": 20,
                    "index": "relevance" if q else "downloads",
                    "facets": self._modrinth_facets(ptype),
                }
                r = requests.get("https://api.modrinth.com/v2/search", params=params,
                                  timeout=20, headers={"User-Agent": self.MODRINTH_UA})
                r.raise_for_status()
                hits = r.json().get("hits") or []
                self._mod_results = hits
                self.after(0, lambda: self._fill_results(hits, q, ptype, token))
            except Exception as e:
                self.after(0, lambda: self._browser_set_status(
                    self.t("br_error_search", err=e)))
                write_error_log("Modrinth search", exc=e)

        threading.Thread(target=job, daemon=True).start()

    def _blank_thumb_image(self):
        """Ảnh trống cùng kích thước -> các hàng chưa có icon vẫn thẳng hàng."""
        if self._blank_thumb is None and ImageTk is not None and Image is not None:
            try:
                s = self.THUMB_SIZE
                self._blank_thumb = ImageTk.PhotoImage(
                    Image.new("RGBA", (s, s), (0, 0, 0, 0)))
            except Exception:
                self._blank_thumb = None
        return self._blank_thumb

    def _fill_results(self, hits, q, ptype, token):
        self.mod_tree.delete(*self.mod_tree.get_children())
        self._row_images.clear()
        blank = self._blank_thumb_image()
        for i, h in enumerate(hits):
            name = h.get("title") or h.get("slug") or "?"
            author = h.get("author") or ""
            dl = h.get("downloads") or 0
            desc = (h.get("description") or "").replace("\n", " ")
            if len(desc) > 110:
                desc = desc[:110] + "…"
            iid = str(i)
            kwargs = {"image": blank} if blank is not None else {}
            self.mod_tree.insert("", "end", iid=iid,
                                  values=(name, author, f"{dl:,}", desc), **kwargs)
            icon_url = h.get("icon_url") or ""
            if icon_url:
                self._queue_thumbnail(iid, icon_url, token)
        if not hits:
            self._browser_set_status(self.t("br_empty", q=q or "…", ver=self.mc_version))
        else:
            self._browser_set_status(
                self.t("br_found", n=len(hits), ver=self.mc_version))

    # --------------------------------------------- Modrinth: ảnh minh hoạ
    def _queue_thumbnail(self, iid, url, token):
        """Tải ảnh icon ở luồng nền; tạo PhotoImage trên luồng UI (Tk không
        thread-safe). Ảnh của lượt tìm cũ bị bỏ qua qua cơ chế token."""
        if Image is None or ImageTk is None or requests is None:
            return
        cached = self._thumb_cache.get(url)
        if cached is not None:
            self._apply_thumbnail(iid, cached, token)
            return

        def job():
            try:
                r = requests.get(url, timeout=12,
                                  headers={"User-Agent": self.MODRINTH_UA})
                r.raise_for_status()
                data = r.content
                # Modrinth có icon .svg — Pillow không đọc được, bỏ qua im lặng.
                if b"<svg" in data[:512].lower():
                    return
                self.after(0, lambda: self._make_thumbnail(iid, url, data, token))
            except Exception:
                pass

        threading.Thread(target=job, daemon=True).start()

    def _make_thumbnail(self, iid, url, data, token):
        if token != self._thumb_token:
            return
        try:
            from io import BytesIO
            s = self.THUMB_SIZE
            img = Image.open(BytesIO(data)).convert("RGBA")
            img = img.resize((s, s), getattr(Image, "LANCZOS", Image.BICUBIC))
            try:
                img.putalpha(_soft_round_mask((s, s), radius=8))
            except Exception:
                pass
            photo = ImageTk.PhotoImage(img)
            self._thumb_cache[url] = photo
            self._apply_thumbnail(iid, photo, token)
        except Exception:
            pass

    def _apply_thumbnail(self, iid, photo, token):
        if token != self._thumb_token:
            return
        try:
            self._row_images[iid] = photo   # giữ tham chiếu, nếu không ảnh biến mất
            self.mod_tree.item(iid, image=photo)
        except Exception:
            pass

    # ------------------------------------------- Modrinth: tải / mở trang
    def _selected_hit(self):
        sel = self.mod_tree.selection()
        if not sel:
            self._browser_set_status(self.t("br_select_first"))
            return None
        try:
            return self._mod_results[int(sel[0])]
        except Exception:
            self._browser_set_status(self.t("br_select_first"))
            return None

    def _modrinth_open_selected_page(self):
        hit = self._selected_hit()
        if not hit:
            return
        ptype = self._current_browse_type()
        slug = hit.get("slug") or hit.get("project_id")
        path = {"mod": "mod", "resourcepack": "resourcepack",
                "shader": "shader"}.get(ptype, "mod")
        self._browser_show_mode("web")
        self._browser_navigate(f"https://modrinth.com/{path}/{slug}", push=True)

    def _modrinth_download_selected(self):
        hit = self._selected_hit()
        if not hit:
            return
        ptype = self._current_browse_type()
        slug = hit.get("slug") or hit.get("project_id")
        name = hit.get("title") or slug
        folder = self._browse_folder_for(ptype)
        self._browser_set_status(self.t("br_downloading", name=name))
        self.set_status(self.t("status_working"), "inverse-warning")

        def job():
            try:
                if ptype == "mod":
                    ok = self._download_modrinth_mod(slug)
                else:
                    ok = self._download_modrinth_content(slug, ptype)
                if ok:
                    self.after(0, lambda: self._browser_set_status(
                        self.t("br_downloaded", name=name, folder=folder)))
                else:
                    self.after(0, lambda: self._browser_set_status(
                        self.t("br_download_fail", name=name, ver=self.mc_version)))
                self.after(0, lambda: self.set_status(self.t("status_ready")))
                self.after(0, self.refresh_all)
            except Exception as e:
                self.after(0, lambda: self._browser_set_status(
                    self.t("br_error_download", err=e)))
                write_error_log(f"Download {ptype} ({slug})", exc=e)

        threading.Thread(target=job, daemon=True).start()

    def _download_modrinth_content(self, slug, ptype):
        """Tải resource pack / shader / modpack về đúng thư mục trong .minecraft.
        Resource pack thường hỗ trợ nhiều phiên bản nên nếu lọc theo đúng
        mc_version mà rỗng thì thử lại không lọc (lấy bản mới nhất)."""
        if requests is None:
            return False
        folder = self._browse_folder_for(ptype)
        dest_dir = self.mc_dir / folder
        dest_dir.mkdir(parents=True, exist_ok=True)

        base = f"https://api.modrinth.com/v2/project/{slug}/version"
        urls = [f'{base}?game_versions=["{self.mc_version}"]', base]
        versions = []
        for api in urls:
            try:
                r = requests.get(api, timeout=15,
                                  headers={"User-Agent": self.MODRINTH_UA})
                r.raise_for_status()
                versions = r.json() or []
            except Exception:
                versions = []
            if versions:
                break
        if not versions:
            return False

        files = versions[0].get("files") or []
        if not files:
            return False
        finfo = next((x for x in files if x.get("primary")), files[0])
        dest = dest_dir / finfo["filename"]
        if dest.exists():
            self.log(f"  ⏭ {finfo['filename']}: already installed, skipped.")
            return True
        self.log(f"  ⬇ Downloading {finfo['filename']} → {folder}/ ...")
        fetch_to(finfo["url"], dest)
        self.log(f"  ✅ Done: {finfo['filename']}")
        return True

    # ---------------------------------------------------- điều hướng web
    def _on_search_engine_changed(self, _event=None):
        try:
            self.cfg["search_engine"] = self.search_engine_var.get()
            save_config(self.cfg)
        except Exception:
            pass

    def _browser_web_search(self):
        q = (self.web_query_var.get() or "").strip()
        if not q:
            return
        engine = self.search_engine_var.get() or DEFAULT_SEARCH_ENGINE
        self._browser_navigate(build_search_url(q, engine), push=True)

    def _browser_go_home(self):
        self._browser_navigate(
            f"https://modrinth.com/mods?g={self.mc_version}&l=fabric", push=True)

    def _browser_go(self):
        """Thanh địa chỉ thông minh: URL thì mở, không thì tìm bằng engine."""
        raw = (self.browser_url_var.get() or "").strip()
        if not raw:
            return
        if looks_like_url(raw):
            self._browser_navigate(raw, push=True)
        else:
            engine = self.search_engine_var.get() or DEFAULT_SEARCH_ENGINE
            self._browser_navigate(build_search_url(raw, engine), push=True)

    def _browser_navigate(self, url, push=True):
        url = sanitize_browse_url(url)
        if is_tracker_url(url):
            self._browser_set_status(self.t("br_blocked_tracker"))
            self.log(f"🛡 Browser: blocked tracker {url}")
            return
        self.browser_url_var.set(url)
        if push:
            if self._browser_hist_i >= 0:
                self._browser_history = self._browser_history[: self._browser_hist_i + 1]
            self._browser_history.append(url)
            self._browser_hist_i = len(self._browser_history) - 1

        host = _host_of(url)
        self._browser_set_status(self.t("br_loading", host=host))
        self.set_discord_activity("Browsing mods", host or "Browser")

        if self._html_frame is not None:
            try:
                if hasattr(self._html_frame, "load_website"):
                    self._html_frame.load_website(url)
                elif hasattr(self._html_frame, "load_url"):
                    self._html_frame.load_url(url)
                else:
                    self._html_frame.load_html(
                        f'<meta http-equiv="refresh" content="0;url={url}">')
                self._browser_inject_shield()
                self._browser_set_status(self.t("br_loaded", host=host))
            except Exception as e:
                self._browser_set_status(self.t("br_load_error", err=e))
                self.log(f"❌ Embedded browser: {e}")
        else:
            self._browser_set_status(self.t("br_no_engine"))

    def _browser_inject_shield(self):
        try:
            if self._html_frame is None:
                return
            for meth in ("run_javascript", "evaluate_js", "execute_script"):
                if hasattr(self._html_frame, meth):
                    getattr(self._html_frame, meth)(ANTI_TRACKER_JS)
                    break
        except Exception:
            pass

    def _browser_back(self):
        if self._browser_hist_i > 0:
            self._browser_hist_i -= 1
            self._browser_navigate(self._browser_history[self._browser_hist_i], push=False)

    def _browser_forward(self):
        if self._browser_hist_i + 1 < len(self._browser_history):
            self._browser_hist_i += 1
            self._browser_navigate(self._browser_history[self._browser_hist_i], push=False)

    def _browser_reload(self):
        if self._browser_hist_i >= 0 and self._browser_history:
            self._browser_navigate(self._browser_history[self._browser_hist_i], push=False)

    def _browser_open_secure_window(self):
        global pywebview
        if pywebview is None:
            try:
                import webview as _wv
                pywebview = _wv
            except Exception:
                pywebview = None
        if pywebview is None:
            self.log("⚠ pywebview missing — installing…")
            self._browser_reinstall_deps()
            try:
                webbrowser.open(sanitize_browse_url(self.browser_url_var.get()))
            except Exception:
                pass
            return
        url = sanitize_browse_url(self.browser_url_var.get())

        def _runner():
            try:
                window = pywebview.create_window(
                    "Arch Client Browser", url, width=1100, height=720, text_select=True)

                def _on_loaded():
                    try:
                        window.evaluate_js(ANTI_TRACKER_JS)
                    except Exception:
                        pass

                try:
                    window.events.loaded += _on_loaded
                except Exception:
                    pass
                try:
                    pywebview.start(private_mode=True)
                except TypeError:
                    pywebview.start()
            except Exception as e:
                self.log(f"❌ pywebview error: {e}")
                write_error_log("Browser pywebview", exc=e)
                try:
                    webbrowser.open(url)
                except Exception:
                    pass

        threading.Thread(target=_runner, daemon=True).start()

    def _browser_reinstall_deps(self):
        def job():
            self.log("⏳ Installing browser packages (tkinterweb, pywebview)…")
            self.after(0, lambda: self._browser_set_status(self.t("br_installing_engine")))
            ok = _pip_install(["tkinterweb", "pywebview"])
            if OS_INFO.get("system") == "Linux":
                ensure_system_packages(OS_INFO)
            if ok:
                self.log("✅ Browser packages installed.")
                self.after(0, lambda: self._browser_set_status(self.t("br_engine_installed")))
                self.after(0, self._browser_init_engine)
            else:
                self.log("⚠ Engine install incomplete — the content store still works.")
                self.after(0, lambda: self._browser_set_status(self.t("br_engine_partial")))
        threading.Thread(target=job, daemon=True).start()

    # -------------------------------------------------------------- log tab
    # -------------------------------------------------------------- log tab
    def _build_log_tab(self):
        f = self.tab_log

        toolbar = tb.Frame(f)
        toolbar.pack(fill="x", pady=(0, 8))
        tb.Label(toolbar, text=self.t("log_title"), font=("", 12, "bold")).pack(side="left")
        tb.Button(toolbar, text=self.LANG["btn_save_console"], bootstyle="info-outline",
                   command=self.save_console_to_file).pack(side="right", padx=(6, 0))
        tb.Button(toolbar, text=self.LANG["btn_clear_console"], bootstyle="secondary-outline",
                   command=self.clear_console).pack(side="right")

        # Khung console kiểu terminal thật (nền tối, chữ đơn cách) — đặt trong
        # khung viền xanh để vẫn ăn khớp với tông trắng-xanh của launcher.
        console_wrap = tb.Frame(f, bootstyle="primary", padding=2)
        console_wrap.pack(fill="both", expand=True)

        self.log_widget = ScrolledText(console_wrap, autohide=True, height=18,
                                         font=("Consolas", 10))
        self.log_widget.pack(fill="both", expand=True, padx=1, pady=1)
        txt = self.log_widget.text
        txt.configure(bg="#0b1220", fg="#d7e3f4", insertbackground="#d7e3f4",
                       relief="flat", padx=8, pady=6)

        # Tag màu theo cấp độ log — giống console launcher thật
        txt.tag_configure("ts", foreground="#5b7ca8")
        txt.tag_configure("lvl_info", foreground="#7fb2ff")
        txt.tag_configure("lvl_success", foreground="#33d17a")
        txt.tag_configure("lvl_warn", foreground="#f2c94c")
        txt.tag_configure("lvl_error", foreground="#ff6b6b")
        txt.tag_configure("lvl_default", foreground="#d7e3f4")

    def clear_console(self):
        self.log_widget.text.delete("1.0", "end")

    def save_console_to_file(self):
        content = self.log_widget.text.get("1.0", "end").strip()
        try:
            ERROR_LOG_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = ERROR_LOG_DIR / f"console_{ts}.txt"
            out_path.write_text(content + "\n", encoding="utf-8")
            self.log(f"💾 Đã lưu console ra file: {out_path}")
        except Exception as e:
            self.log(f"❌ Không thể lưu console: {e}")

    def log(self, msg, level=None):
        """Ghi 1 dòng ra console kèm timestamp + màu theo cấp độ.

        level tự suy ra từ nội dung nếu không truyền vào (dựa trên icon
        ❌/⚠/✅ đã được dùng nhất quán khắp launcher).
        """
        text = str(msg)
        if level is None:
            if text.startswith("❌"):
                level = "error"
            elif text.startswith("⚠"):
                level = "warn"
            elif text.startswith("✅") or text.startswith("🎉"):
                level = "success"
            elif text.startswith(("🖥", "📁", "🔍", "⏳", "👉", "▶", "🚀", "⬇", "🔑", "📝", "💾", "ℹ")):
                level = "info"
            else:
                level = "default"
        tag = f"lvl_{level}" if level in ("info", "success", "warn", "error") else "lvl_default"

        def _do():
            txt = self.log_widget.text
            ts = datetime.now().strftime("%H:%M:%S")
            txt.insert("end", f"[{ts}] ", "ts")
            txt.insert("end", text + "\n", tag)
            txt.see("end")
        self.after(0, _do)

    def set_status(self, text, style="inverse-success"):
        self._status_text_base = text
        self._status_style = style
        self.after(0, lambda: self.status_badge.config(text=f"● {text}", bootstyle=style))

    def _pulse_status_badge(self):
        """Nhịp status rất nhẹ (chấm ● sáng/tắt) — không đổi màu loạn."""
        if not getattr(self, "_status_pulse_on", False):
            return
        if not hasattr(self, "status_badge"):
            return
        try:
            base = getattr(self, "_status_text_base", self.LANG.get("status_ready", "Ready"))
            style = getattr(self, "_status_style", "inverse-success")
            # chỉ pulse khi đang "Sẵn sàng" / Ready — tránh làm phiền lúc đang tải
            ready_words = (self.LANG.get("status_ready", "Ready"), "Sẵn sàng", "Ready")
            if base in ready_words:
                self._pulse_phase = not getattr(self, "_pulse_phase", False)
                dot = "●" if self._pulse_phase else "○"
                self.status_badge.config(text=f"{dot} {base}", bootstyle=style)
            self.after(900, self._pulse_status_badge)
        except Exception:
            pass

    def _fade_in_body(self):
        """Hiện notebook sau 1 nhịp — cảm giác mở launcher mượt hơn (tk không fade alpha dễ)."""
        try:
            if hasattr(self, "nb"):
                self.nb.pack_configure(pady=(8, 4))
        except Exception:
            pass

    # -------------------------------------------------- Discord Rich Presence
    def _init_discord_rpc(self):
        if DiscordPresence is None:
            self.log("ℹ Discord Rich Presence: chưa cài 'pypresence' — bỏ qua (không ảnh hưởng launcher).")
            return

        def _connect():
            try:
                rpc = DiscordPresence(DISCORD_CLIENT_ID)
                rpc.connect()
                self.discord_rpc = rpc
                self.log("🎮 Đã kết nối Discord Rich Presence.")
                self.set_discord_activity("Đang mở Arch Client", "Tổng quan")
            except Exception as e:
                self.discord_rpc = None
                self.log(f"ℹ Không kết nối được Discord (Discord có đang mở không?): {e}")

        threading.Thread(target=_connect, daemon=True).start()

    def set_discord_activity(self, details, state=None):
        """Cập nhật trạng thái hiện lên Discord: đang làm gì (details) /
        đang ở đâu hay tải gì (state). Lỗi khi cập nhật (Discord bị đóng
        giữa chừng...) được bỏ qua âm thầm, không làm ảnh hưởng launcher."""
        if not self.discord_rpc:
            return
        try:
            self.discord_rpc.update(
                details=details,
                state=state or "Arch Client",
                start=self.discord_start_time,
                large_image="logo",
                large_text="Arch Client — Minecraft Fabric Launcher",
            )
        except Exception:
            self.discord_rpc = None

    def _on_tab_changed(self, _event=None):
        try:
            current = self.nb.select()
            label = self._discord_tab_states.get(current, "Đang xem launcher")
            self.set_discord_activity(label, f"Minecraft {self.mc_version} · Fabric")
        except Exception:
            pass

    def _on_close(self):
        if self.discord_rpc:
            try:
                self.discord_rpc.close()
            except Exception:
                pass
        self.destroy()


    # ------------------------------------------------------- Desktop shortcuts
    def install_shortcuts_startup(self):
        """Tự cài shortcut lần đầu (hoặc khi file bị xoá) — không chặn UI."""
        if not self.cfg.get("auto_install_shortcuts", True):
            self._refresh_shortcut_status()
            return
        if shortcuts_present():
            self.log("✅ Shortcut desktop / Start Menu đã có sẵn.")
            self._refresh_shortcut_status()
            return
        threading.Thread(target=self._install_shortcuts_job, daemon=True).start()

    def install_shortcuts_thread(self):
        threading.Thread(target=self._install_shortcuts_job, daemon=True).start()

    def _install_shortcuts_job(self):
        try:
            self.set_status("Đang cài shortcut...", "inverse-warning")
            self.log("⏳ Đang cài shortcut desktop / Start Menu...")
            result = install_os_shortcuts()
            for f in result.get("files") or []:
                self.log(f"  ✅ {f}")
            self.log("✅ Đã cài shortcut. Mở menu ứng dụng hoặc Start Menu để thấy Arch Client.")
            self.cfg["auto_install_shortcuts"] = True
            save_config(self.cfg)
            self.after(0, self._refresh_shortcut_status)
            self.set_status(self.t("status_ready"))
        except Exception as e:
            self.log(f"❌ Lỗi cài shortcut: {e}")
            log_path = write_error_log("Cài shortcut desktop", exc=e)
            if log_path:
                self.log(f"📝 Chi tiết lỗi đã ghi vào: {log_path}")
            self.set_status(self.t("status_error"), "inverse-danger")
            self.after(0, self._refresh_shortcut_status)

    def remove_shortcuts_thread(self):
        def job():
            try:
                removed = remove_installed_shortcuts()
                if removed:
                    for f in removed:
                        self.log(f"  🗑 Đã gỡ: {f}")
                    self.log("✅ Đã gỡ shortcut.")
                else:
                    self.log("ℹ Không tìm thấy shortcut để gỡ.")
                self.cfg["auto_install_shortcuts"] = False
                save_config(self.cfg)
                self.after(0, self._refresh_shortcut_status)
            except Exception as e:
                self.log(f"❌ Lỗi gỡ shortcut: {e}")
                write_error_log("Gỡ shortcut desktop", exc=e)
        threading.Thread(target=job, daemon=True).start()

    def _refresh_shortcut_status(self):
        locs = shortcut_locations()
        if not hasattr(self, "shortcut_status_lbl"):
            return
        if not locs:
            text = "Hệ điều hành này chưa hỗ trợ tự cài shortcut (chỉ Linux & Windows)."
            style = "secondary"
        else:
            existing = [p for p in locs.values() if Path(p).exists()]
            if existing:
                text = "Đã cài: " + "  ·  ".join(existing)
                style = "success"
            else:
                text = ("Chưa cài shortcut. Bấm «Cài shortcut» — hoặc mở lại launcher "
                        "để tự cài (.desktop trên Linux, .lnk trên Windows).")
                style = "warning"
        self.shortcut_status_lbl.config(text=text, bootstyle=style)

    # ------------------------------------------------------- Fabric install
    def install_fabric_thread(self):
        if mll is None:
            self.log("❌ Cần cài minecraft-launcher-lib")
            return
        threading.Thread(target=self._install_fabric, daemon=True).start()

    BASE_MODS = ("fabric-api", "modmenu")

    def _ensure_base_mods(self):
        """Tự tải Fabric API + Mod Menu (nếu chưa có) khớp phiên bản MC."""
        if requests is None:
            return
        self.log("📦 Kiểm tra Fabric API + Mod Menu...")
        for slug in self.BASE_MODS:
            self._download_modrinth_mod(slug)

    def _install_fabric(self):
        try:
            self.set_status("Đang cài Fabric...", "inverse-warning")
            self.mc_dir.mkdir(parents=True, exist_ok=True)

            # Trước đây gọi mll.fabric.install_fabric() không truyền java=...,
            # nên lib tự gọi lệnh "java" trơn qua PATH — nếu Windows chưa có
            # Java trong PATH thì subprocess báo FileNotFoundError (WinError 2).
            # Giờ resolve đúng java_path đã cấu hình (hoặc bản Java tự tải) rồi
            # truyền thẳng vào, không phụ thuộc PATH của Windows nữa.
            java_exe = resolve_java_path(self.java_var.get())
            if not java_exe:
                self.log("❌ Không tìm thấy Java. Vào tab Cài đặt, bấm "
                          "'⬇ Kiểm tra / Cài Java tự động' trước khi cài Fabric.")
                self.set_status(self.t("status_error"), "inverse-danger")
                return

            self.log(f"⏳ Đang cài Fabric Loader cho Minecraft {self.mc_version} "
                      f"(dùng Java: {java_exe})...")
            callback = {
                "setStatus": lambda text: self.log(f"  {text}"),
                "setProgress": lambda value: None,
                "setMax": lambda value: None,
            }
            mll.fabric.install_fabric(
                self.mc_version, str(self.mc_dir), callback=callback, java=java_exe
            )
            self.log("✅ Cài Fabric thành công!")
            self._ensure_base_mods()
            self.set_status(self.t("status_ready"))
        except Exception as e:
            self.log(f"❌ Lỗi khi cài Fabric: {e}")
            log_path = write_error_log("Cài Fabric", exc=e)
            if log_path:
                self.log(f"📝 Chi tiết lỗi đã ghi vào: {log_path}")
            self.set_status(self.t("status_error"), "inverse-danger")

    # ------------------------------------------------------- Microsoft auth
    def login_microsoft_thread(self):
        if mll is None:
            self.log("❌ Cần cài minecraft-launcher-lib")
            return
        client_id = self.client_id_var.get().strip()
        if not client_id:
            self.log("⚠ Điền Azure client_id trước khi login Microsoft.")
            return
        threading.Thread(target=self._login_microsoft, args=(client_id,), daemon=True).start()

    def _login_microsoft(self, client_id):
        try:
            redirect_uri = "https://login.microsoftonline.com/consumers/oauth2/nativeclient"
            login_url, state, code_verifier = mll.microsoft_account.get_secure_login_data(
                client_id, redirect_uri)
            self.log("👉 Mở trình duyệt và đăng nhập tại:")
            self.log(login_url)
            self.log("Sau khi đăng nhập, copy URL redirect cuối cùng, dán vào terminal đang chạy launcher.")
            redirect_url = input("Dán URL redirect vào đây rồi Enter: ").strip()
            auth_code = mll.microsoft_account.parse_auth_code_url(redirect_url, state)
            token = mll.microsoft_account.complete_login(
                client_id, None, redirect_uri, auth_code, code_verifier)
            self.access_token = token["access_token"]
            self.uuid = token["id"]
            self.user_var.set(token["name"])
            self.log(f"✅ Đăng nhập thành công: {token['name']}")
        except Exception as e:
            self.log(f"❌ Lỗi đăng nhập Microsoft: {e}")
            log_path = write_error_log("Đăng nhập Microsoft", exc=e)
            if log_path:
                self.log(f"📝 Chi tiết lỗi đã ghi vào: {log_path}")

    # ------------------------------------------------------------- Launch
    def launch_game_thread(self):
        if mll is None:
            self.log("❌ Cần cài minecraft-launcher-lib")
            return
        threading.Thread(target=self._launch_game, daemon=True).start()

    def _launch_game(self):
        try:
            self.set_status("Đang khởi chạy...", "inverse-warning")

            java_path = self.java_var.get().strip() or "java"
            resolved_java = resolve_java_path(java_path)
            if not resolved_java:
                self.log(f"❌ Không tìm thấy Java tại '{java_path}'. "
                          "Bấm 'Kiểm tra / Cài Java tự động' trong tab Cài đặt trước.")
                self.set_status("Thiếu Java", "inverse-danger")
                return
            jver = get_java_version(resolved_java)
            if jver and jver < JAVA_MAJOR_REQUIRED:
                self.log(f"⚠ Java hiện tại là bản {jver}, Minecraft {self.mc_version} cần Java "
                          f"{JAVA_MAJOR_REQUIRED}+. Bấm 'Kiểm tra / Cài Java tự động' để cập nhật.")
                self.set_status("Java quá cũ", "inverse-danger")
                return

            versions = [
                v["id"] for v in mll.utils.get_installed_versions(str(self.mc_dir))
                if v["id"].startswith("fabric-loader") and self.mc_version in v["id"]
            ]
            if not versions:
                self.log("⚠ Chưa cài Fabric cho phiên bản này. Bấm 'Cài / Cập nhật Fabric' trước.")
                self.set_status("Chưa cài Fabric", "inverse-danger")
                return
            version_id = versions[0]
            self.log(f"🚀 Chuẩn bị chạy: {version_id}")
            self._ensure_base_mods()

            ram = int(self.ram_var.get())
            jvm_args = [
                f"-Xms{ram}M", f"-Xmx{ram}M",
                "-XX:+UseG1GC", "-XX:+ParallelRefProcEnabled",
                "-XX:MaxGCPauseMillis=200", "-XX:+UnlockExperimentalVMOptions",
                "-XX:+DisableExplicitGC", "-XX:+AlwaysPreTouch",
                "-XX:G1NewSizePercent=30", "-XX:G1MaxNewSizePercent=40",
                "-XX:G1HeapRegionSize=8M", "-XX:G1ReservePercent=20",
                "-XX:G1HeapWastePercent=5", "-XX:G1MixedGCCountTarget=4",
                "-XX:InitiatingHeapOccupancyPercent=15",
                "-XX:G1MixedGCLiveThresholdPercent=90",
                "-XX:G1RSetUpdatingPauseTimePercent=5",
                "-XX:SurvivorRatio=32", "-XX:+PerfDisableSharedMem",
                "-XX:MaxTenuringThreshold=1",
            ]
            options = {
                "username": self.user_var.get() or "Player",
                "uuid": self.uuid or "00000000-0000-0000-0000-000000000000",
                "token": self.access_token or "0",
                "jvmArguments": jvm_args,
                "launcherName": "ArchClient",
                "launcherVersion": "2.0",
            }
            command = mll.command.get_minecraft_command(version_id, str(self.mc_dir), options)
            command[0] = resolved_java

            self.log("▶ Đang khởi chạy Minecraft...")
            proc = subprocess.Popen(command, cwd=str(self.mc_dir),
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      text=True, bufsize=1)
            self.set_status("Đang chơi", "inverse-success")

            def stream_output():
                game_log_lines = []
                for line in proc.stdout:
                    game_log_lines.append(line.rstrip())
                    self.log(line.rstrip())
                ret = proc.wait()
                if ret != 0:
                    self.log(f"❌ Minecraft thoát với mã lỗi {ret}.")
                    log_path = write_error_log(
                        f"Minecraft crash (mã lỗi {ret})",
                        extra_text="--- 200 dòng cuối của game log ---\n" +
                                    "\n".join(game_log_lines[-200:]))
                    if log_path:
                        self.log(f"📝 Chi tiết crash đã ghi vào: {log_path}")
                    self.set_status("Crash", "inverse-danger")
                else:
                    self.log("ℹ Minecraft đã đóng.")
                    self.set_status(self.t("status_ready"))

            threading.Thread(target=stream_output, daemon=True).start()
        except FileNotFoundError as e:
            self.log(f"❌ Không tìm thấy Java tại '{self.java_var.get() or 'java'}': {e}")
            self.log("   Hãy kiểm tra lại đường dẫn Java trong tab Cài đặt.")
            write_error_log("Khởi chạy game — thiếu Java", exc=e)
            self.set_status(self.t("status_error"), "inverse-danger")
        except Exception as e:
            self.log(f"❌ Lỗi khi khởi chạy: {e}")
            log_path = write_error_log("Khởi chạy game", exc=e)
            if log_path:
                self.log(f"📝 Chi tiết lỗi đã ghi vào: {log_path}")
            self.set_status(self.t("status_error"), "inverse-danger")

    # -------------------------------------------------------- Optimization
    def apply_optimization_thread(self):
        threading.Thread(target=self._apply_optimization, daemon=True).start()

    def _write_optimized_options(self):
        opt_path = self.mc_dir / "options.txt"
        existing = {}
        if opt_path.exists():
            for line in opt_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    existing[k] = v
        existing.update(OPTIMIZED_OPTIONS)
        opt_path.write_text("\n".join(f"{k}:{v}" for k, v in existing.items()) + "\n",
                             encoding="utf-8")
        self.log(f"✅ Đã cập nhật {opt_path} với thiết lập tối ưu FPS.")

    def _modrinth_version_list(self, slug):
        """Lấy danh sách bản của 1 mod Modrinth khớp self.mc_version + Fabric,
        sắp xếp mới nhất trước (API trả sẵn theo thứ tự này)."""
        api = (f"https://api.modrinth.com/v2/project/{slug}/version"
               f'?loaders=["fabric"]&game_versions=["{self.mc_version}"]')
        r = requests.get(api, timeout=15, headers={"User-Agent": "ArchClient/2.0"})
        r.raise_for_status()
        return r.json()

    def _modrinth_project_slug(self, project_id):
        """Đổi project_id (vd trong 'dependencies') thành slug (vd 'sodium')."""
        r = requests.get(f"https://api.modrinth.com/v2/project/{project_id}",
                          timeout=15, headers={"User-Agent": "ArchClient/2.0"})
        r.raise_for_status()
        return r.json().get("slug", project_id)

    def _pick_file(self, version_obj):
        files = version_obj.get("files") or []
        return next((x for x in files if x.get("primary")), files[0])

    def _download_modrinth_version(self, slug, version_obj, mods_dir):
        """Tải đúng 1 bản của mod; xoá jar cũ cùng mod để khỏi có 2 bản song song."""
        fi = self._pick_file(version_obj)
        dest = mods_dir / fi["filename"]
        for old in mods_dir.glob("*.jar"):
            if _jar_is(slug, old.name) and old.name != fi["filename"]:
                old.unlink(missing_ok=True)
        if dest.exists() and dest.stat().st_size > 0:
            self.log(f"  ⏭ {fi['filename']}: đã có.")
            return dest
        self.log(f"  ⬇ Đang tải {slug} (MC {self.mc_version})...")
        fetch_to(fi["url"], dest)
        self.log(f"  ✅ Đã tải: {fi['filename']}")
        return dest

    def _find_sodium_for_iris(self, iris_obj, iris_jar):
        """Chọn bản Sodium khớp Iris: (1) bản Iris ghim sẵn, (2) range trong
        fabric.mod.json của Iris, (3) bản Sodium mới nhất không muộn hơn Iris."""
        sodium_versions = self._modrinth_version_list("sodium")
        for dep in iris_obj.get("dependencies", []):
            if dep.get("dependency_type") == "required" and dep.get("version_id"):
                try:
                    pslug = self._modrinth_project_slug(dep.get("project_id"))
                except Exception:
                    pslug = ""
                if pslug == "sodium":
                    r = requests.get(
                        f"https://api.modrinth.com/v2/version/{dep['version_id']}",
                        timeout=15, headers={"User-Agent": "ArchClient/2.0"})
                    r.raise_for_status()
                    return r.json()
        rng = _jar_depends(iris_jar, "sodium")
        if rng is not None:
            for v in sodium_versions:  # mới nhất trước
                vt = _mod_ver_tuple(v.get("version_number"))
                if vt and _satisfies(vt, rng):
                    return v
        iris_date = iris_obj.get("date_published", "")
        cands = [v for v in sodium_versions if v.get("date_published", "") <= iris_date]
        return (cands or sodium_versions or [None])[0]

    def _install_iris_with_sodium(self, mods_dir):
        """Cài Iris + Sodium khớp nhau (như nút 'Download with deps' của Modrinth)."""
        iris_versions = self._modrinth_version_list("iris")
        if not iris_versions:
            self.log(f"  ⚠ iris: không có bản cho MC {self.mc_version} + Fabric.")
            return False
        iris_obj = iris_versions[0]
        iris_jar = self._download_modrinth_version("iris", iris_obj, mods_dir)
        sod = self._find_sodium_for_iris(iris_obj, iris_jar)
        if not sod:
            self.log("  ⚠ Không tìm được bản Sodium khớp với Iris.")
            return False
        self._download_modrinth_version("sodium", sod, mods_dir)
        self.log(f"  🔧 Iris {iris_obj.get('version_number')} + "
                 f"Sodium {sod.get('version_number')} (khớp nhau).")
        return True

    def _download_modrinth_mod(self, slug):
        """Tải 1 mod Modrinth khớp self.mc_version + Fabric. Iris/Sodium luôn
        được cài thành cặp khớp nhau."""
        if requests is None:
            self.log("⚠ Thiếu 'requests', bỏ qua tải mod tự động.")
            return False
        mods_dir = self.mc_dir / "mods"
        mods_dir.mkdir(parents=True, exist_ok=True)
        try:
            has_iris = any(_jar_is("iris", fp.name) for fp in mods_dir.glob("*.jar"))
            if slug == "iris" or (slug == "sodium" and has_iris):
                return self._install_iris_with_sodium(mods_dir)

            if slug != "sodium" and any(_jar_is(slug, fp.name) for fp in mods_dir.glob("*.jar")):
                self.log(f"  ⏭ {slug}: đã có, bỏ qua.")
                return True

            versions = self._modrinth_version_list(slug)
            if not versions:
                msg = self.LANG.get(
                    "no_mod_for_ver",
                    "Không có bản mod cho phiên bản {ver} + Fabric.",
                ).format(ver=self.mc_version)
                self.log(f"  ⚠ {slug}: {msg}")
                return False
            self._download_modrinth_version(slug, versions[0], mods_dir)
            return True
        except Exception as e:
            self.log(f"  ❌ Lỗi tải {slug}: {e}")
            write_error_log(f"Tải mod Modrinth ({slug})", exc=e)
            return False

    def _apply_optimization(self):
        self.after(0, self.opt_progress.start)
        self.set_status(self.t("opt_running"), "inverse-warning")
        self.log("🚀 Bắt đầu tối ưu FPS...")
        try:
            self._write_optimized_options()
            for slug, var in self.mod_vars.items():
                if var.get():
                    self._download_modrinth_mod(slug)
            self.log("🎉 Hoàn tất tối ưu! Khởi động lại game để áp dụng.")
            self.set_status(self.t("status_ready"))
        except Exception as e:
            self.log(f"❌ Lỗi khi tối ưu FPS: {e}")
            log_path = write_error_log("Tối ưu FPS", exc=e)
            if log_path:
                self.log(f"📝 Chi tiết lỗi đã ghi vào: {log_path}")
            self.set_status(self.t("status_error"), "inverse-danger")
        finally:
            # Luôn dừng thanh tiến trình dù thành công hay lỗi, tránh treo UI
            self.after(0, self.opt_progress.stop)
            self.after(0, self.refresh_all)


class SplashScreen(tb.Window):
    """Splash gọn: logo bo góc + title, không nhồi banner to làm cửa sổ méo."""

    def __init__(self):
        super().__init__(themename="flatly")
        self.title("Arch Client")
        self.overrideredirect(True)
        self.attributes("-topmost", True)

        width, height = 380, 240
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - width) // 2
        y = (sh - height) // 2
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.resizable(False, False)

        self._icon_full = load_icon_image(size=(64, 64), rounded=True)
        if self._icon_full:
            try:
                self.iconphoto(True, self._icon_full)
            except Exception:
                pass

        outer = tb.Frame(self, bootstyle="primary", padding=0)
        outer.pack(fill=BOTH, expand=True)

        container = tb.Frame(outer, padding=28)
        container.pack(fill=BOTH, expand=True)

        if self._icon_full:
            tb.Label(container, image=self._icon_full, bootstyle="inverse-primary").pack(
                pady=(8, 10))
        tb.Label(
            container, text="ARCH CLIENT",
            font=("Segoe UI", 16, "bold"), bootstyle="inverse-primary",
        ).pack()
        tb.Label(
            container, text="Minecraft · Fabric",
            font=("Segoe UI", 9), bootstyle="inverse-primary",
        ).pack(pady=(2, 14))

        self.status_var = tk.StringVar(value="")
        tb.Label(
            container, textvariable=self.status_var,
            font=("Segoe UI", 9), bootstyle="inverse-primary",
        ).pack(pady=(0, 10))

        self.bar = tb.Progressbar(
            container, mode="indeterminate", bootstyle="secondary-striped", length=280,
        )
        self.bar.pack(pady=(0, 6))
        self.bar.start(14)

    def set_status(self, text):
        self.status_var.set(text)


def run_with_splash():
    splash = SplashScreen()

    def worker():
        splash.after(0, lambda: splash.set_status(LANG_STRINGS["vi"]["splash_detect"]))
        cfg = load_config()
        lang = resolve_language(cfg.get("lang", "auto"))
        strings = LANG_STRINGS.get(lang, LANG_STRINGS["en"])
        splash.after(0, lambda: splash.set_status(strings["splash_load"]))
        time.sleep(0.3)
        splash.after(0, lambda: finish(lang))

    def finish(lang):
        splash.bar.stop()
        splash.destroy()
        App(lang=lang).mainloop()

    threading.Thread(target=worker, daemon=True).start()
    splash.mainloop()


if __name__ == "__main__":
    if FROZEN:
        # An toàn khi đóng gói kiểu --onefile: nếu có thư viện nào đó âm
        # thầm dùng multiprocessing mà thiếu freeze_support(), tiến trình
        # con sẽ tự chạy lại toàn bộ .exe từ đầu -> mở đè hàng loạt cửa sổ
        # -> ngốn RAM. Gọi freeze_support() sớm nhất có thể để chặn việc đó.
        import multiprocessing
        multiprocessing.freeze_support()
    run_with_splash()
