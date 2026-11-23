# -*- coding: utf-8 -*-
"""Controller: chạy các tác vụ nền (Java, Fabric, game, Modrinth…) và báo về GUI qua Bus.

Mọi tác vụ chạy ở thread riêng; GUI chỉ nhận signal nên không bao giờ bị treo.
"""
from __future__ import annotations

import os
import re
import html
import time
import shutil
import threading
import subprocess
import http.server
from urllib.parse import urlsplit, parse_qs
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from . import APP_VERSION
from . import core
from .bootstrap import GAME_LOG_DIR, ERROR_LOG_DIR, detect_os, write_error_log
from .i18n import tr

try:
    from pypresence import Presence
except Exception:  # pragma: no cover
    Presence = None

DISCORD_CLIENT_ID = "1545310964331843584"
_INSTALL_LOCK = threading.Lock()  # chỉ một trình cài mod ghi manifest tại một thời điểm


def _is_network_error(exc: BaseException) -> bool:
    mod = type(exc).__module__ or ""
    return (mod.startswith(("requests", "urllib3")) or isinstance(exc, (ConnectionError, TimeoutError))
            or "SSL" in type(exc).__name__)


class Bus(QObject):
    log = pyqtSignal(str, str)         # nội dung, mức (info/ok/warn/error/dim/game)
    status = pyqtSignal(str, str)      # kind: ready|busy|error|playing, text
    java = pyqtSignal(str, str)        # text, kind: idle|busy|ok|warn|error
    progress = pyqtSignal(int, int)    # value, max (max<0 ẩn, 0 = không xác định)
    refresh = pyqtSignal()
    toast = pyqtSignal(str, str)       # text, kind: info|ok|warn|error
    sound = pyqtSignal(str)
    game = pyqtSignal(bool)
    login_prompt = pyqtSignal(str, bool)   # (url, tự động bắt kết quả?)
    login_done = pyqtSignal(str)
    login_fail = pyqtSignal(str)
    login_out = pyqtSignal()
    accounts = pyqtSignal()            # danh sách / tài khoản đang chọn thay đổi
    cfg_changed = pyqtSignal()
    invoke = pyqtSignal(object)        # chạy 1 callable trên luồng GUI


class Controller:
    def __init__(self, bus: Bus, cfg: dict, lang: str):
        self.bus = bus
        self.cfg = cfg
        self.lang = lang
        self.mc_dir = Path(cfg["mc_dir"])
        self.mc_version = cfg.get("mc_version") or core.DEFAULT_MC_VERSION
        self.loader = cfg.get("loader") if cfg.get("loader") in core.LOADER_IDS else "fabric"
        self._tokens: dict = {}            # id tài khoản -> {"access", "uuid", "t"} (chỉ giữ trong RAM)
        self._games: dict = {}             # số thứ tự -> {"proc", "name", "log"}; nhiều game chạy song song
        self._game_seq = 0
        self._cleanups: list = []          # việc dọn sau khi game cuối cùng tắt (Windows: trả power plan)
        self._running: set = set()
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="arch-io")
        self._ms = None
        self._cb_server = None
        self._rpc = None
        self._rpc_lock = threading.Lock()
        self._rpc_start = int(time.time())
        self._last_status_line = ""
        self.bus.invoke.connect(self._run_invoked)

    # ------------------------------------------------------------ tiện ích
    @staticmethod
    def _run_invoked(fn):
        try:
            fn()
        except Exception as e:
            write_error_log("Callback GUI", exc=e)

    def t(self, key, **kw):
        return tr(self.lang, key, **kw)

    def log(self, msg, level="info"):
        self.bus.log.emit(str(msg), level)

    def status(self, kind="ready", text=None):
        self.bus.status.emit(kind, text or "")

    def save(self):
        core.save_config(self.cfg)

    def call_async(self, fn, on_ok=None, on_err=None):
        """Chạy fn ở pool nền; on_ok/on_err chạy lại trên luồng GUI."""
        fut = self._pool.submit(fn)

        def done(f):
            try:
                res = f.result()
            except Exception as exc:
                if not _is_network_error(exc):      # mất mạng là chuyện thường, không ghi file báo lỗi
                    write_error_log("Tác vụ nền", exc=exc)
                if on_err:
                    self.bus.invoke.emit(lambda err=exc: on_err(err))
                return
            if on_ok:
                self.bus.invoke.emit(lambda: on_ok(res))

        fut.add_done_callback(done)

    def run_exclusive(self, name, fn, *args) -> bool:
        """Chạy fn ở thread riêng; không cho chạy trùng cùng tên tác vụ."""
        with self._lock:
            if name in self._running:
                self.bus.toast.emit(self.t("busy_wait"), "warn")
                return False
            self._running.add(name)

        def runner():
            try:
                fn(*args)
            except Exception as e:
                self.log(f"Lỗi: {e}", "error")
                p = None if _is_network_error(e) else write_error_log(f"Tác vụ {name}", exc=e)
                if p:
                    self.log(f"Chi tiết: {p}", "dim")
                self.status("error")
                self.bus.sound.emit("error")
            finally:
                with self._lock:
                    self._running.discard(name)
                self.bus.progress.emit(0, -1)

        threading.Thread(target=runner, name=f"arch-{name}", daemon=True).start()
        return True

    def is_running(self, name) -> bool:
        with self._lock:
            return name in self._running

    # ------------------------------------------------------------ Java
    def current_java(self):
        return core.resolve_java_path(self.cfg.get("java_path"))

    def java_required(self) -> int:
        return core.required_java_major(self.mc_version)

    @property
    def game_dir(self) -> Path:
        return core.game_dir_for(self.mc_dir, self.loader, self.mc_version, bool(self.cfg.get("isolate", False)))

    def ensure_game_dir(self) -> Path:
        gd = self.game_dir
        core.ensure_minecraft_dir(gd, instance=gd != self.mc_dir)
        return gd

    def check_java_startup(self):
        self.run_exclusive("java", self._check_java, True)

    def check_java_quiet(self):
        """Đổi phiên bản: chỉ kiểm tra, không tự tải Java (sẽ tự cài khi cài loader / bấm Chơi)."""
        if self.is_running("java"):       # đang kiểm tra / cài rồi: đừng báo "bận" mỗi lần đổi phiên bản
            return
        self.run_exclusive("java", self._check_java, False)

    def _java_ok_state(self, exe, ver):
        self.cfg["java_path"] = str(exe)
        self.save()
        self.bus.java.emit(self.t("java_ok", v=ver), "ok")
        self.bus.cfg_changed.emit()

    def _check_java(self, auto=True):
        need = self.java_required()
        self.bus.java.emit(self.t("java_checking"), "busy")
        exe = self.current_java()
        ver = core.get_java_version(exe) if exe else None
        if exe and ver and core.java_acceptable(ver, need):
            self.log(f"Java {ver}: {exe}", "ok")
            self.bus.java.emit(self.t("java_ok", v=ver), "ok")
            return
        found = core.find_any_java(need)
        if found:
            self.log(f"Dùng Java {found[1]}: {found[0]}", "ok")
            self._java_ok_state(*found)
            return
        if not auto:
            self.bus.java.emit(self.t("java_lazy", need=need), "warn")
            return
        if exe and ver:
            self.log(f"Java hiện tại là bản {ver}, Minecraft {self.mc_version} cần Java {need} — tự động cài bản phù hợp.", "warn")
        else:
            self.log(f"Chưa tìm thấy Java — tự động cài OpenJDK {need}.", "warn")
        self._install_java(need)

    def install_java(self):
        self.run_exclusive("java", self._install_java, None)

    def _install_java(self, target=None):
        need = self.java_required()
        if target is None:                     # bấm nút "cài Java": theo phiên bản đang chọn
            try:
                target = int(self.cfg.get("java_major") or need)
            except Exception:
                target = need
            target = need if need <= 8 else max(target, need)
        target = int(target)
        need = target
        self.status("busy")
        self.bus.java.emit(self.t("java_installing"), "busy")
        self.bus.progress.emit(0, 0)
        self.log(f"Bắt đầu cài OpenJDK {target}…", "info")
        exe = None
        try:
            exe = core.install_java_portable(
                target, self.log,
                progress=lambda d, t: self.bus.progress.emit(d // 1024, t // 1024) if t else None)
        except Exception as e:
            self.log(f"Tải bản portable thất bại: {e}", "warn")
            if detect_os().get("pkg_manager") and not detect_os().get("immutable"):
                self.log(f"Thử cài qua trình quản lý gói ({detect_os()['pkg_manager']})…", "info")
                if core.install_java_via_pkg_manager(target, self.log):
                    found = core.find_any_java(need)
                    if found:
                        exe = found[0]
        if not exe:
            self.log("Không cài được Java tự động. Hãy cài OpenJDK thủ công rồi chọn file java trong Cài đặt.", "error")
            self.bus.java.emit(self.t("java_fail"), "error")
            self.status("error")
            self.bus.sound.emit("error")
            return
        ver = core.get_java_version(exe) or target
        self.log(f"Đã cài Java {ver}: {exe}", "ok")
        self._java_ok_state(exe, ver)
        self.status("ready")
        self.bus.sound.emit("success")
        self.bus.toast.emit(self.t("java_ok", v=ver), "ok")

    def _ensure_java(self, need: int):
        """Trả về (đường dẫn java, major) thoả `need`; tự tìm / tải nếu thiếu. None nếu thất bại."""
        exe = self.current_java()
        ver = core.get_java_version(exe) if exe else None
        if exe and ver and core.java_acceptable(ver, need):
            return exe, ver
        found = core.find_any_java(need)
        if found:
            self._java_ok_state(*found)
            return found
        self.log(f"Cần Java {need} — đang tự cài…", "info")
        self._install_java(need)
        found = core.find_any_java(need)
        if found:
            self._java_ok_state(*found)
        return found

    # ------------------------------------------------------------ Loader (Vanilla / Fabric / Quilt / Forge / NeoForge)
    def install_loader(self):
        if core.mll is None:
            self.log("Thiếu minecraft-launcher-lib", "error")
            return
        if not hasattr(core.mll, "mod_loader"):
            self.log("minecraft-launcher-lib quá cũ (cần >= 8.0): pip install -U minecraft-launcher-lib", "error")
            self.bus.toast.emit(self.t("mll_old"), "error")
            return
        self.run_exclusive("loader", self._install_loader)

    install_fabric = install_loader      # tên cũ

    def _install_loader(self):
        """Cài vanilla / loader cho (self.loader, self.mc_version). Trả về id profile hoặc None."""
        loader, mc = self.loader, self.mc_version
        label = core.loader_label(loader)
        self.status("busy")
        self.mc_dir.mkdir(parents=True, exist_ok=True)
        if core.loader_supports(loader, mc) is False:
            self.log(f"{label} chưa hỗ trợ Minecraft {mc}.", "error")
            self.bus.toast.emit(self.t("loader_unsupported", loader=label, ver=mc), "error")
            self.status("error")
            self.bus.sound.emit("error")
            return None
        found = self._ensure_java(self.java_required())
        if not found:
            self.log("Không tìm thấy Java phù hợp. Vào Cài đặt > Kiểm tra / cài Java trước.", "error")
            self.status("error")
            self.bus.toast.emit(self.t("need_java"), "error")
            self.bus.sound.emit("error")
            return None
        java = found[0]
        self.log(f"Đang cài {label} cho Minecraft {mc}…", "info")
        state = {"max": 0}

        def set_status(text):
            if text and text != self._last_status_line:
                self._last_status_line = text
                self.log(f"  {text}", "dim")

        def set_max(v):
            state["max"] = int(v or 0)

        def set_progress(v):
            if state["max"] > 0:
                self.bus.progress.emit(int(v), state["max"])

        cb = {"setStatus": set_status, "setProgress": set_progress, "setMax": set_max}
        self.bus.progress.emit(0, 0)
        try:
            if loader == "vanilla":
                core.mll.install.install_minecraft_version(mc, str(self.mc_dir), callback=cb)
                vid = mc
            else:
                vid = core.mll.mod_loader.get_mod_loader(loader).install(
                    mc, str(self.mc_dir), callback=cb, java=str(java))
        except Exception as e:
            n = type(e).__name__
            msg = (self.t("loader_unsupported", loader=label, ver=mc) if n == "UnsupportedVersion"
                   else self.t("loader_failed", loader=label))
            self.log(f"Cài {label} thất bại ({n}): {e}", "error")
            self.bus.toast.emit(msg, "error")
            self.status("error")
            self.bus.sound.emit("error")
            if n not in ("UnsupportedVersion", "VersionNotFound"):
                write_error_log(f"Cài {label} {mc}", exc=e)
            return None
        self.log(f"Cài {label} thành công.", "ok")
        self.status("ready")
        self.bus.sound.emit("success")
        self.bus.toast.emit(self.t("loader_ok", loader=label), "ok")
        self.bus.refresh.emit()
        return vid

    # ------------------------------------------------------------ Microsoft
    REDIRECT = "https://login.microsoftonline.com/consumers/oauth2/nativeclient"   # chế độ dán URL thủ công
    LOGIN_TIMEOUT = 240

    def login_microsoft(self, client_id: str, manual: bool = False):
        """Mặc định: mở trình duyệt, đăng nhập xong tự quay lại launcher (cổng localhost tạm thời).
        manual=True: dùng địa chỉ nativeclient, người dùng dán URL cuối cùng vào launcher."""
        if core.mll is None:
            return
        if not client_id.strip():
            self.bus.toast.emit(self.t("login_need_id"), "warn")
            return
        self.login_cancel()
        self.run_exclusive("login-start", self._login_start, client_id.strip(), manual)

    def _login_start(self, client_id, manual):
        server = None if manual else self._start_callback_server()
        redirect = f"http://localhost:{server.server_port}" if server else self.REDIRECT
        url, state, verifier = core.mll.microsoft_account.get_secure_login_data(client_id, redirect)
        self._ms = (client_id, state, verifier, redirect)
        self._cb_server = server
        self.log("Đã mở trình duyệt để đăng nhập Microsoft.", "info")
        self.bus.login_prompt.emit(url, server is not None)
        if server:
            threading.Thread(target=self._wait_callback, args=(server,), name="arch-login-cb",
                             daemon=True).start()

    def _start_callback_server(self):
        """HTTP server tạm trên 127.0.0.1 (cổng ngẫu nhiên) để bắt địa chỉ chuyển hướng của Microsoft."""
        box = {}
        done_html = (
            "<!doctype html><meta charset=utf-8><title>Arch Client</title>"
            "<body style='margin:0;height:100vh;display:grid;place-items:center;background:#14171d;"
            "color:#e6e8ed;font:16px system-ui,sans-serif'><div style='text-align:center'>"
            "<h2 style='font-weight:600;margin:0 0 8px'>{title}</h2>"
            "<p style='color:#8c94a3;margin:0'>{body}</p></div></body>")

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):   # im lặng
                pass

            def do_GET(self):  # noqa: N802
                q = parse_qs(urlsplit(self.path).query)
                if "code" not in q and "error" not in q:
                    self.send_response(404)
                    self.end_headers()
                    return
                ok = "code" in q
                page = done_html.format(
                    title=html.escape(tr(box["lang"], "login_page_ok" if ok else "login_page_err")),
                    body=html.escape(tr(box["lang"], "login_page_hint")))
                data = page.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(data)
                box["url"] = f"http://localhost:{self.server.server_port}{self.path}"

        try:
            srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        except OSError:
            return None
        srv.timeout = 0.5
        box["lang"] = self.lang
        srv._box = box
        return srv

    def _wait_callback(self, srv):
        box = srv._box
        end = time.time() + self.LOGIN_TIMEOUT
        try:
            while time.time() < end and self._cb_server is srv and "url" not in box:
                srv.handle_request()
        finally:
            try:
                srv.server_close()
            except Exception:
                pass
        if self._cb_server is srv:
            self._cb_server = None
            if "url" in box:
                self.login_finish(box["url"])
            else:
                self.bus.login_fail.emit(self.t("login_timeout"))

    def login_cancel(self):
        srv, self._cb_server = self._cb_server, None   # luồng chờ thấy _cb_server đổi -> tự thoát
        if srv is not None:
            self._ms = None

    def login_finish(self, redirect_url: str):
        if not self._ms or not redirect_url.strip():
            return
        self.run_exclusive("login-finish", self._login_finish, redirect_url.strip())

    def _login_finish(self, redirect_url):
        client_id, state, verifier, redirect = self._ms
        ma = core.mll.microsoft_account
        try:
            code = ma.parse_auth_code_url(redirect_url, state)
            token = ma.complete_login(client_id, None, redirect, code, verifier)
        except Exception as e:
            self.bus.login_fail.emit(self._login_error_text(e))
            raise
        self._ms = None
        self._apply_token(token, client_id)
        self.log(f"Đăng nhập thành công: {token['name']}", "ok")
        self.bus.login_done.emit(token["name"])
        self.bus.sound.emit("success")

    def _login_error_text(self, e) -> str:
        n = type(e).__name__
        if n == "AccountNotOwnMinecraft":
            return self.t("login_no_game")
        if n == "AzureAppNotPermitted":
            return self.t("login_app_denied")
        return self.t("login_failed", err=str(e)[:160])

    # ------------------------------------------------------------ Tài khoản
    TOKEN_MAX_AGE = 6 * 3600           # token Minecraft sống ~24h: làm mới nếu đã cũ hơn 6h

    def accounts(self) -> list:
        return self.cfg.setdefault("accounts", [])

    def get_account(self, aid=None):
        accs = self.accounts()
        want = aid or self.cfg.get("active_account")
        return next((a for a in accs if a["id"] == want), accs[0] if accs else None)

    def account_label(self, acc) -> str:
        kind = self.t("acc_ms") if acc["type"] == "microsoft" else self.t("acc_offline")
        return f"{acc['name']}  ·  {kind}"

    @property
    def access_token(self):
        acc = self.get_account()
        tok = self._tokens.get(acc["id"]) if acc else None
        return tok["access"] if tok else None

    def set_active_account(self, aid: str):
        acc = self.get_account(aid)
        if not acc:
            return
        self.cfg["active_account"] = acc["id"]
        self.cfg["username"] = acc["name"]
        self.save()
        self.bus.accounts.emit()

    def add_offline_account(self, name: str):
        """Thêm (hoặc chọn lại nếu đã có) tài khoản offline. Trả về account."""
        clean = re.sub(r"[^A-Za-z0-9_]", "", name or "")[:16]
        if len(clean) < 3:
            self.bus.toast.emit(self.t("acc_bad_name"), "warn")
            return None
        acc = next((a for a in self.accounts() if a["type"] == "offline" and a["name"].lower() == clean.lower()), None)
        if acc is None:
            acc = {"id": core.new_account_id(), "type": "offline", "name": clean}
            self.accounts().append(acc)
        self.set_active_account(acc["id"])
        return acc

    def remove_account(self, aid: str):
        accs = self.accounts()
        acc = next((a for a in accs if a["id"] == aid), None)
        if not acc:
            return
        accs.remove(acc)
        self._tokens.pop(aid, None)
        if not accs:
            accs.append({"id": core.new_account_id(), "type": "offline", "name": "Player"})
        if self.cfg.get("active_account") == aid:
            self.cfg["active_account"] = accs[0]["id"]
            self.cfg["username"] = accs[0]["name"]
        self.save()
        self.bus.accounts.emit()
        if acc["type"] == "microsoft":
            self.bus.login_out.emit()
        self.log(f"Đã xoá tài khoản {acc['name']}.", "info")

    def _store_token(self, token: dict, client_id: str, activate: bool) -> dict:
        """Ghi token Microsoft vào đúng tài khoản (tìm theo uuid, chưa có thì thêm)."""
        accs = self.accounts()
        acc = next((a for a in accs if a["type"] == "microsoft" and a.get("uuid") == token["id"]), None)
        if acc is None:
            acc = {"id": core.new_account_id(), "type": "microsoft"}
            accs.append(acc)
        acc.update(name=token["name"], uuid=token["id"], client=client_id, expired=False)
        if token.get("refresh_token"):
            acc["refresh"] = token["refresh_token"]
        self._tokens[acc["id"]] = {"access": token["access_token"], "uuid": token["id"], "t": time.time()}
        if activate:
            self.cfg["active_account"] = acc["id"]
            self.cfg["username"] = acc["name"]
        self.save()
        self.bus.accounts.emit()
        return acc

    def _apply_token(self, token: dict, client_id: str):
        self._store_token(token, client_id, activate=True)

    def restore_login(self):
        """Mở app: lấy lại phiên của MỌI tài khoản Microsoft bằng refresh token (nền, im lặng)."""
        if core.mll is None:
            return
        todo = [a for a in self.accounts() if a["type"] == "microsoft" and a.get("refresh") and a.get("client")
                and not a.get("expired")]
        if not todo:
            return

        def job():
            ma = core.mll.microsoft_account
            for acc in todo:
                try:
                    token = ma.complete_refresh(acc["client"], None, None, acc["refresh"])
                except Exception as e:
                    if type(e).__name__ in ("InvalidRefreshToken", "AccountNotOwnMinecraft", "AzureAppNotPermitted"):
                        acc["expired"] = True
                        self.save()
                        self.bus.accounts.emit()
                        self.log(f"Phiên Microsoft của {acc['name']} đã hết hạn — hãy đăng nhập lại.", "warn")
                    else:
                        self.log(f"Chưa khôi phục được phiên của {acc['name']} (bỏ qua): {e}", "dim")
                    continue
                self._store_token(token, acc["client"], activate=False)
                self.log(f"Đã đăng nhập: {token['name']}", "ok")
            act = self.get_account()
            if act and act["type"] == "microsoft" and not act.get("expired"):
                self.bus.login_done.emit(act["name"])
        self._pool.submit(job)

    def _token_for(self, acc: dict) -> dict:
        """Token còn hạn cho tài khoản Microsoft; làm mới nếu cũ. Ném RuntimeError nếu phải đăng nhập lại."""
        cached = self._tokens.get(acc["id"])
        if cached and time.time() - cached["t"] < self.TOKEN_MAX_AGE:
            return cached
        if acc.get("refresh") and acc.get("client") and not acc.get("expired"):
            try:
                token = core.mll.microsoft_account.complete_refresh(acc["client"], None, None, acc["refresh"])
                self._store_token(token, acc["client"], activate=False)
                return self._tokens[acc["id"]]
            except Exception as e:
                if type(e).__name__ in ("InvalidRefreshToken", "AccountNotOwnMinecraft", "AzureAppNotPermitted"):
                    acc["expired"] = True
                    self.save()
                    self.bus.accounts.emit()
                elif cached:
                    self.log(f"Không làm mới được token, dùng token cũ: {e}", "warn")
                    return cached
                else:
                    raise RuntimeError(self.t("acc_refresh_fail", name=acc["name"], err=str(e)[:120]))
        raise RuntimeError(self.t("acc_expired", name=acc["name"]))

    def logout(self):
        """Gỡ tài khoản Microsoft đang chọn (nếu tài khoản đang chọn không phải Microsoft thì gỡ cái đầu tiên)."""
        self.login_cancel()
        acc = self.get_account()
        if not acc or acc["type"] != "microsoft":
            acc = next((a for a in self.accounts() if a["type"] == "microsoft"), None)
        if acc:
            self.remove_account(acc["id"])

    # ------------------------------------------------------------ Game
    def game_running(self) -> bool:
        return self.game_count() > 0

    def game_count(self) -> int:
        with self._lock:
            return sum(1 for g in self._games.values() if g["proc"].poll() is None)

    @property
    def game_proc(self):
        with self._lock:
            procs = [g["proc"] for g in self._games.values()]
        return procs[-1] if procs else None

    def launch(self, account_id=None):
        """Chạy game bằng tài khoản đang chọn (hoặc account_id). Có thể gọi nhiều lần để mở nhiều game cùng lúc."""
        if core.mll is None:
            self.log("Thiếu minecraft-launcher-lib", "error")
            return
        acc = self.get_account(account_id if isinstance(account_id, str) else None)
        if acc is None:
            return
        with self._lock:
            dup = any(g["acc"] == acc["id"] and g["proc"].poll() is None for g in self._games.values())
        if dup:
            self.bus.toast.emit(self.t("acc_dup", name=acc["name"]), "warn")
        self.run_exclusive("game", self._launch, acc["id"])

    def _launch(self, account_id):
        self.status("busy")
        acc = self.get_account(account_id)
        auth_token, auth_uuid = "0", None
        if acc["type"] == "microsoft":
            try:
                tok = self._token_for(acc)
            except RuntimeError as e:
                self.log(str(e), "error")
                self.bus.toast.emit(str(e), "error")
                self.status("error")
                self.bus.sound.emit("error")
                return
            auth_token, auth_uuid = tok["access"], tok["uuid"]
        label = core.loader_label(self.loader)
        version_id = core.find_installed_version(self.mc_dir, self.loader, self.mc_version)
        if not version_id:
            self.log(f"Chưa cài {label} {self.mc_version} — tự cài trước khi chơi.", "info")
            version_id = self._install_loader()
            if not version_id:
                return
            self.status("busy")
        need = core.java_major_from_json(self.mc_dir, version_id) or self.java_required()
        found = self._ensure_java(need)
        if not found:
            self.log(f"Không tìm thấy Java {need} phù hợp. Vào Cài đặt > Kiểm tra / cài Java.", "error")
            self.bus.toast.emit(self.t("need_java"), "error")
            self.bus.java.emit(self.t("java_old", v="?", need=need), "error")
            self.status("error")
            self.bus.sound.emit("error")
            return
        java, jver = found
        gdir = self.ensure_game_dir()
        self.log(f"Chuẩn bị chạy: {version_id} ({acc['name']})", "info")

        ram = int(self.cfg.get("ram_mb", 3072))
        safe = core.clamp_ram_mb(ram)
        if self.game_count():                       # đang có game khác: tránh cạn RAM máy
            avail = core.detect_available_ram_mb()
            if avail and safe + 512 > avail:
                self.log(self.t("low_ram_multi", need=safe, avail=avail), "warn")
                self.bus.toast.emit(self.t("low_ram_multi", need=safe, avail=avail), "warn")
        if safe != ram:
            self.log(f"RAM {ram} MB vượt 75% RAM máy — hạ xuống {safe} MB để tránh bị OOM-killer giết game.", "warn")
        name = acc["name"] if acc["type"] == "microsoft" else core.valid_username(acc["name"])
        options = {
            "username": name,
            "uuid": auth_uuid or core.offline_uuid(name),
            "token": auth_token,
            "jvmArguments": core.jvm_args(safe, self.cfg, java_major=jver),
            "launcherName": "ArchClient",
            "launcherVersion": APP_VERSION,
            "gameDirectory": str(gdir),
        }
        command = core.mll.command.get_minecraft_command(version_id, str(self.mc_dir), options)
        command[0] = java
        env = core.build_launch_env(self.cfg)
        prefix = core.build_launch_prefix(self.cfg)
        if prefix:
            command = prefix + command
        for line in core.describe_launch_setup(self.cfg):
            self.log(line, "dim")

        popen_extra = {"start_new_session": True}
        cleanup = None
        if core.IS_WINDOWS:
            flags, cleanup = core.prepare_windows_launch(self.cfg, java, self.log)
            popen_extra = {"creationflags": flags}

        GAME_LOG_DIR.mkdir(parents=True, exist_ok=True)
        self._prune_game_logs()
        safe_name = re.sub(r"\W", "_", name)
        log_path = GAME_LOG_DIR / f"game-{safe_name}-{time.strftime('%H%M%S')}.log"
        # Ghi stdout của game ra FILE rồi đọc đuôi file: đóng launcher không làm game
        # bị SIGPIPE / mất log như khi nối thẳng qua pipe.
        try:
            with open(log_path, "wb") as logf:
                proc = subprocess.Popen(command, cwd=str(gdir), stdin=subprocess.DEVNULL,
                                        stdout=logf, stderr=subprocess.STDOUT, env=env, **popen_extra)
        except Exception:
            if cleanup:
                cleanup()
            raise
        with self._lock:
            self._game_seq += 1
            gid = self._game_seq
            self._games[gid] = {"proc": proc, "name": name, "acc": acc["id"], "log": log_path}
            if cleanup:
                self._cleanups.append(cleanup)
        n = self.game_count()
        self.log(f"Đang khởi chạy Minecraft… ({name})", "ok")
        self.status("playing", self.t("st_playing_n", n=n) if n > 1 else None)
        self.bus.game.emit(True)
        self.bus.sound.emit("launch")
        self.set_discord(f"Đang chơi Minecraft {self.mc_version}", f"{label} · Arch Client")
        threading.Thread(target=self._tail_game, args=(gid,), name="arch-tail", daemon=True).start()

    @staticmethod
    def _prune_game_logs(keep: int = 12):
        try:
            files = sorted(GAME_LOG_DIR.glob("game-*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
            for f in files[keep:]:
                f.unlink(missing_ok=True)
        except OSError:
            pass

    def _tail_game(self, gid: int):
        with self._lock:
            g = self._games[gid]
        proc, log_path, name = g["proc"], g["log"], g["name"]
        tail = deque(maxlen=200)

        def emit(line):
            tail.append(line)
            with self._lock:
                multi = len(self._games) > 1
            self.log(f"[{name}] {line}" if multi else line, "game")

        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                while True:
                    line = f.readline()
                    if line:
                        emit(line.rstrip())
                        continue
                    if proc.poll() is not None:
                        for line in f.read().splitlines():  # nốt phần còn lại
                            emit(line)
                        break
                    time.sleep(0.15)
        except Exception as e:
            write_error_log("Đọc log game", exc=e)
        code = proc.wait()
        with self._lock:
            self._games.pop(gid, None)
            last = not any(x["proc"].poll() is None for x in self._games.values())
            cleanups, self._cleanups = (self._cleanups, []) if last else ([], self._cleanups)
        for cleanup in cleanups:             # Windows: trả power plan cũ khi game CUỐI CÙNG tắt
            try:
                cleanup()
            except Exception as e:
                write_error_log("Khôi phục power plan", exc=e)
        left = self.game_count()
        self.bus.game.emit(left > 0)
        if code != 0:
            self.log(f"[{name}] " + self.t("game_crash", code=code), "error")
            p = write_error_log(f"Minecraft crash (mã {code}, {name})",
                                extra_text="--- 200 dòng cuối của game log ---\n" + "\n".join(tail))
            if p:
                self.log(f"Chi tiết crash: {p}", "dim")
            self.status("error")
            self.bus.sound.emit("error")
        else:
            self.log(f"[{name}] " + self.t("game_closed"), "info")
        if left:
            self.status("playing", self.t("st_playing_n", n=left) if left > 1 else None)
        elif code == 0:
            self.status("ready")
            self.set_discord("Đang xem launcher", "Arch Client")
        else:
            self.set_discord("Đang xem launcher", "Arch Client")

    # ------------------------------------------------------------ Tối ưu
    def apply_optimization(self, slugs: list):
        self.run_exclusive("optimize", self._apply_optimization, list(slugs))

    def _apply_optimization(self, slugs):
        self.status("busy", self.t("opt_running"))
        self.log("Bắt đầu tối ưu…", "info")
        gdir = self.ensure_game_dir()
        opt = core.write_optimized_options(gdir)
        self.log(f"Đã cập nhật {opt}", "ok")
        order = sorted(slugs, key=lambda s: 0 if s == "iris" else 1)  # Iris ghim bản Sodium, cài trước
        total = len(order)
        okc = 0
        for i, slug in enumerate(order):
            self.bus.progress.emit(i, max(total, 1))
            inst = core.ModrinthInstaller(gdir, self.mc_version, self.log, loader=self.loader)
            try:
                with _INSTALL_LOCK:
                    if inst.install(slug, "mod"):
                        okc += 1
            except Exception as e:
                self.log(f"  Lỗi tải {slug}: {e}", "error")
                write_error_log(f"Tối ưu - tải {slug}", exc=e)
        self.bus.progress.emit(total, max(total, 1))
        self.log(f"Hoàn tất tối ưu: {okc}/{total} mod. Khởi động lại game để áp dụng.", "ok")
        self.status("ready")
        self.bus.refresh.emit()
        self.bus.sound.emit("success")
        self.bus.toast.emit(self.t("opt_done"), "ok")

    def set_win_tweak(self, key: str, on: bool):
        """Windows: áp / hoàn tác ngay tuỳ chọn khi người dùng gạt công tắc (ghi registry rất nhanh)."""
        if not core.IS_WINDOWS:
            return
        try:
            exe = self.current_java()
            core.apply_windows_tweak(self.cfg, key, on, exe)
        except Exception as e:
            write_error_log(f"Tuỳ chọn Windows {key}", exc=e)

    def startup_windows(self):
        """Windows: nếu lần trước launcher tắt đột ngột lúc đang chơi thì trả lại power plan."""
        if core.IS_WINDOWS:
            self.call_async(core.winsys.restore_power_plan, lambda _r: None, lambda _e: None)

    def install_gaming_tools(self):
        def job():
            self.status("busy")
            self.log("Đang cài gamemode / MangoHud / jemalloc…", "info")
            ok = core.install_gaming_tools(self.log)
            self.log("Cài xong. Bật lại các tuỳ chọn rồi quét lại phần cứng." if ok else
                     "Không cài được tự động — hãy cài thủ công gói «gamemode» và «mangohud».",
                     "ok" if ok else "warn")
            self.status("ready")
            self.bus.sound.emit("success" if ok else "error")
            self.bus.refresh.emit()
        self.run_exclusive("gaming-tools", job)

    # ------------------------------------------------------------ Modrinth
    def search_mods(self, query, ptype, offset, on_ok, on_err):
        ver, loader = self.mc_version, self.loader
        self.call_async(lambda: core.modrinth_search(query, ptype, ver, offset, loader=loader), on_ok, on_err)

    def fetch_thumb(self, url, px, on_ok):
        def job():
            import requests
            from PyQt6.QtGui import QImage
            from PyQt6.QtCore import Qt
            r = requests.get(url, timeout=12, headers={"User-Agent": core.UA}, stream=True)
            r.raise_for_status()
            data = r.raw.read(2_000_000, decode_content=True)
            img = QImage()
            if b"<svg" in data[:600].lower():
                try:
                    from PyQt6.QtSvg import QSvgRenderer
                    from PyQt6.QtGui import QPainter
                    rend = QSvgRenderer(data)
                    img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
                    img.fill(0)
                    p = QPainter(img)
                    rend.render(p)
                    p.end()
                    return img
                except Exception:
                    return None
            if not img.loadFromData(data):
                return None
            return img.scaled(px, px, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                              Qt.TransformationMode.SmoothTransformation)
        self.call_async(job, on_ok)

    def download_project(self, slug, ptype, name, on_done):
        ver, loader = self.mc_version, self.loader
        gdir = self.ensure_game_dir()

        def job():
            inst = core.ModrinthInstaller(gdir, ver, self.log, loader=loader)
            with _INSTALL_LOCK:
                return inst.install(slug, ptype)

        def ok(res):
            self.bus.refresh.emit()
            self.bus.sound.emit("success" if res else "error")
            on_done(bool(res), None)

        def err(e):
            self.log(f"Lỗi tải {name}: {e}", "error")
            self.bus.sound.emit("error")
            on_done(False, e)

        self.call_async(job, ok, err)

    # ------------------------------------------------------------ Shortcut
    def install_shortcuts(self, quiet=False):
        def job():
            files = core.install_shortcuts()
            for f in files:
                self.log(f"  {f}", "dim")
            self.log("Đã cài shortcut.", "ok")
            self.cfg["shortcut_opt_out"] = False
            self.save()
            self.bus.cfg_changed.emit()
            if not quiet:
                self.bus.sound.emit("success")
        self.run_exclusive("shortcut", job)

    def remove_shortcuts(self):
        def job():
            removed = core.remove_shortcuts()
            for f in removed:
                self.log(f"  Đã gỡ: {f}", "dim")
            self.cfg["shortcut_opt_out"] = True       # người dùng chủ động gỡ -> đừng tự tạo lại
            self.save()
            self.bus.cfg_changed.emit()
        self.run_exclusive("shortcut", job)

    def startup_shortcuts(self):
        """Tự tạo shortcut khi mở app (trừ khi người dùng đã chủ động gỡ); tự sửa nếu trỏ sai chỗ."""
        if self.cfg.get("shortcut_opt_out"):
            return
        if not core.shortcuts_present() or core.shortcuts_stale():
            self.install_shortcuts(quiet=True)

    # ------------------------------------------------------------ Discord
    def init_discord(self):
        if Presence is None:
            return

        def job():
            try:
                rpc = Presence(DISCORD_CLIENT_ID)
                rpc.connect()
                with self._rpc_lock:
                    self._rpc = rpc
                self.log("Đã kết nối Discord Rich Presence.", "dim")
                self.set_discord("Đang xem launcher", "Arch Client")
            except Exception:
                self._rpc = None  # Discord không mở: bỏ qua im lặng
        self._pool.submit(job)

    def set_discord(self, details, state=None):
        if self._rpc is None:
            return

        def job():
            with self._rpc_lock:
                if self._rpc is None:
                    return
                try:
                    self._rpc.update(details=details, state=state or "Arch Client",
                                     start=self._rpc_start, large_image="logo",
                                     large_text="Arch Client — Minecraft Launcher")
                except Exception:
                    self._rpc = None
        self._pool.submit(job)

    def shutdown(self):
        with self._rpc_lock:
            if self._rpc is not None:
                try:
                    self._rpc.close()
                except Exception:
                    pass
                self._rpc = None
        self._pool.shutdown(wait=False, cancel_futures=True)
