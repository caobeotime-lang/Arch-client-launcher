# -*- coding: utf-8 -*-
"""Controller: runs background tasks (Java, Fabric, game, Modrinth...) and reports to the GUI via Bus.

Every task runs in its own thread; the GUI only receives signals so it never freezes.
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
_INSTALL_LOCK = threading.Lock()  # only one mod installer writes the manifest at a time


def _is_network_error(exc: BaseException) -> bool:
    mod = type(exc).__module__ or ""
    return (mod.startswith(("requests", "urllib3")) or isinstance(exc, (ConnectionError, TimeoutError))
            or "SSL" in type(exc).__name__)


class Bus(QObject):
    log = pyqtSignal(str, str)         # message, level (info/ok/warn/error/dim/game)
    status = pyqtSignal(str, str)      # kind: ready|busy|error|playing, text
    java = pyqtSignal(str, str)        # text, kind: idle|busy|ok|warn|error
    progress = pyqtSignal(int, int)    # value, max (max<0 hidden, 0 = indeterminate)
    refresh = pyqtSignal()
    toast = pyqtSignal(str, str)       # text, kind: info|ok|warn|error
    sound = pyqtSignal(str)
    game = pyqtSignal(bool)
    login_prompt = pyqtSignal(str, bool)   # (url, catch the result automatically?)
    login_done = pyqtSignal(str)
    login_fail = pyqtSignal(str)
    login_out = pyqtSignal()
    accounts = pyqtSignal()            # account list / active account changed
    cfg_changed = pyqtSignal()
    invoke = pyqtSignal(object)        # run a callable on the GUI thread


class Controller:
    def __init__(self, bus: Bus, cfg: dict, lang: str):
        self.bus = bus
        self.cfg = cfg
        self.lang = lang
        self.mc_dir = Path(cfg["mc_dir"])
        self.mc_version = cfg.get("mc_version") or core.DEFAULT_MC_VERSION
        self.loader = cfg.get("loader") if cfg.get("loader") in core.LOADER_IDS else "fabric"
        self._tokens: dict = {}            # account id -> {"access", "uuid", "t"} (kept in RAM only)
        self._games: dict = {}             # sequence number -> {"proc", "name", "log"}; games run in parallel
        self._game_seq = 0
        self._cleanups: list = []          # cleanup after the last game exits (Windows: restore power plan)
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

    # ------------------------------------------------------------ utilities
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
        """Run fn on the worker pool; on_ok/on_err run again on the GUI thread."""
        fut = self._pool.submit(fn)

        def done(f):
            try:
                res = f.result()
            except Exception as exc:
                if not _is_network_error(exc):      # losing the network is normal, no error report file
                    write_error_log("Background task", exc=exc)
                if on_err:
                    self.bus.invoke.emit(lambda err=exc: on_err(err))
                return
            if on_ok:
                self.bus.invoke.emit(lambda: on_ok(res))

        fut.add_done_callback(done)

    def run_exclusive(self, name, fn, *args) -> bool:
        """Run fn in its own thread; the same task name cannot run twice."""
        with self._lock:
            if name in self._running:
                self.bus.toast.emit(self.t("busy_wait"), "warn")
                return False
            self._running.add(name)

        def runner():
            try:
                fn(*args)
            except Exception as e:
                self.log(f"Error: {e}", "error")
                p = None if _is_network_error(e) else write_error_log(f"Task {name}", exc=e)
                if p:
                    self.log(f"Details: {p}", "dim")
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
        """Version change: check only, do not download Java (it installs itself when installing a loader / pressing Play)."""
        if self.is_running("java"):       # already checking / installing: do not report "busy" on every version change
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
            self.log(f"Using Java {found[1]}: {found[0]}", "ok")
            self._java_ok_state(*found)
            return
        if not auto:
            self.bus.java.emit(self.t("java_lazy", need=need), "warn")
            return
        if exe and ver:
            self.log(f"Current Java is {ver}, Minecraft {self.mc_version} needs Java {need} — installing the right version automatically.", "warn")
        else:
            self.log(f"No Java found — installing OpenJDK {need} automatically.", "warn")
        self._install_java(need)

    def install_java(self):
        self.run_exclusive("java", self._install_java, None)

    def _install_java(self, target=None):
        need = self.java_required()
        if target is None:                     # "install Java" button pressed: follow the selected version
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
        self.log(f"Installing OpenJDK {target}…", "info")
        exe = None
        try:
            exe = core.install_java_portable(
                target, self.log,
                progress=lambda d, t: self.bus.progress.emit(d // 1024, t // 1024) if t else None)
        except Exception as e:
            self.log(f"Portable download failed: {e}", "warn")
            if detect_os().get("pkg_manager") and not detect_os().get("immutable"):
                self.log(f"Trying the package manager ({detect_os()['pkg_manager']})…", "info")
                if core.install_java_via_pkg_manager(target, self.log):
                    found = core.find_any_java(need)
                    if found:
                        exe = found[0]
        if not exe:
            self.log("Could not install Java automatically. Install OpenJDK manually, then pick the java binary in Settings.", "error")
            self.bus.java.emit(self.t("java_fail"), "error")
            self.status("error")
            self.bus.sound.emit("error")
            return
        ver = core.get_java_version(exe) or target
        self.log(f"Installed Java {ver}: {exe}", "ok")
        self._java_ok_state(exe, ver)
        self.status("ready")
        self.bus.sound.emit("success")
        self.bus.toast.emit(self.t("java_ok", v=ver), "ok")

    def _ensure_java(self, need: int):
        """Return (java path, major) satisfying `need`; finds / downloads it when missing. None on failure."""
        exe = self.current_java()
        ver = core.get_java_version(exe) if exe else None
        if exe and ver and core.java_acceptable(ver, need):
            return exe, ver
        found = core.find_any_java(need)
        if found:
            self._java_ok_state(*found)
            return found
        self.log(f"Java {need} needed — installing…", "info")
        self._install_java(need)
        found = core.find_any_java(need)
        if found:
            self._java_ok_state(*found)
        return found

    # ------------------------------------------------------------ Loader (Vanilla / Fabric / Quilt / Forge / NeoForge)
    def install_loader(self):
        if core.mll is None:
            self.log("minecraft-launcher-lib is missing", "error")
            return
        if not hasattr(core.mll, "mod_loader"):
            self.log("minecraft-launcher-lib is too old (needs >= 8.0): pip install -U minecraft-launcher-lib", "error")
            self.bus.toast.emit(self.t("mll_old"), "error")
            return
        self.run_exclusive("loader", self._install_loader)

    install_fabric = install_loader      # legacy name

    def _install_loader(self):
        """Install vanilla / a loader for (self.loader, self.mc_version). Returns the profile id or None."""
        loader, mc = self.loader, self.mc_version
        label = core.loader_label(loader)
        self.status("busy")
        self.mc_dir.mkdir(parents=True, exist_ok=True)
        if core.loader_supports(loader, mc) is False:
            self.log(f"{label} does not support Minecraft {mc}.", "error")
            self.bus.toast.emit(self.t("loader_unsupported", loader=label, ver=mc), "error")
            self.status("error")
            self.bus.sound.emit("error")
            return None
        found = self._ensure_java(self.java_required())
        if not found:
            self.log("No suitable Java found. Use Settings > Check / install Java first.", "error")
            self.status("error")
            self.bus.toast.emit(self.t("need_java"), "error")
            self.bus.sound.emit("error")
            return None
        java = found[0]
        self.log(f"Installing {label} for Minecraft {mc}…", "info")
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
            self.log(f"{label} install failed ({n}): {e}", "error")
            self.bus.toast.emit(msg, "error")
            self.status("error")
            self.bus.sound.emit("error")
            if n not in ("UnsupportedVersion", "VersionNotFound"):
                write_error_log(f"Install {label} {mc}", exc=e)
            return None
        self.log(f"{label} installed successfully.", "ok")
        self.status("ready")
        self.bus.sound.emit("success")
        self.bus.toast.emit(self.t("loader_ok", loader=label), "ok")
        self.bus.refresh.emit()
        return vid

    # ------------------------------------------------------------ Microsoft
    REDIRECT = "https://login.microsoftonline.com/consumers/oauth2/nativeclient"   # manual paste-URL mode
    LOGIN_TIMEOUT = 240

    def login_microsoft(self, client_id: str, manual: bool = False):
        """Default: open the browser, return to the launcher automatically after sign-in (temporary localhost port).
        manual=True: use the nativeclient address, the user pastes the final URL into the launcher."""
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
        self.log("Opened the browser for Microsoft sign-in.", "info")
        self.bus.login_prompt.emit(url, server is not None)
        if server:
            threading.Thread(target=self._wait_callback, args=(server,), name="arch-login-cb",
                             daemon=True).start()

    def _start_callback_server(self):
        """Temporary HTTP server on 127.0.0.1 (random port) that catches Microsoft's redirect address."""
        box = {}
        done_html = (
            "<!doctype html><meta charset=utf-8><title>Arch Client</title>"
            "<body style='margin:0;height:100vh;display:grid;place-items:center;background:#14171d;"
            "color:#e6e8ed;font:16px system-ui,sans-serif'><div style='text-align:center'>"
            "<h2 style='font-weight:600;margin:0 0 8px'>{title}</h2>"
            "<p style='color:#8c94a3;margin:0'>{body}</p></div></body>")

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):   # stay quiet
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
        srv, self._cb_server = self._cb_server, None   # the waiting thread sees the change -> exits by itself
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
        self.log(f"Signed in: {token['name']}", "ok")
        self.bus.login_done.emit(token["name"])
        self.bus.sound.emit("success")

    def _login_error_text(self, e) -> str:
        n = type(e).__name__
        if n == "AccountNotOwnMinecraft":
            return self.t("login_no_game")
        if n == "AzureAppNotPermitted":
            return self.t("login_app_denied")
        return self.t("login_failed", err=str(e)[:160])

    # ------------------------------------------------------------ Accounts
    TOKEN_MAX_AGE = 6 * 3600           # Minecraft tokens live ~24h: refresh when older than 6h

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
        """Add (or re-select if it already exists) an offline account. Returns the account."""
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
        self.log(f"Removed account {acc['name']}.", "info")

    def _store_token(self, token: dict, client_id: str, activate: bool) -> dict:
        """Store the Microsoft token under the right account (matched by uuid, added when new)."""
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
        """App start: refresh the session of EVERY Microsoft account via refresh token (background, quiet)."""
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
                        self.log(f"{acc['name']}'s Microsoft session expired — please sign in again.", "warn")
                    else:
                        self.log(f"Could not restore {acc['name']}'s session (skipped): {e}", "dim")
                    continue
                self._store_token(token, acc["client"], activate=False)
                self.log(f"Signed in: {token['name']}", "ok")
            act = self.get_account()
            if act and act["type"] == "microsoft" and not act.get("expired"):
                self.bus.login_done.emit(act["name"])
        self._pool.submit(job)

    def _token_for(self, acc: dict) -> dict:
        """Return a valid token for the Microsoft account; refresh when stale. Raises RuntimeError when re-sign-in is needed."""
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
                    self.log(f"Could not refresh the token, using the old one: {e}", "warn")
                    return cached
                else:
                    raise RuntimeError(self.t("acc_refresh_fail", name=acc["name"], err=str(e)[:120]))
        raise RuntimeError(self.t("acc_expired", name=acc["name"]))

    def logout(self):
        """Remove the selected Microsoft account (falls back to the first account when the selected one is not Microsoft)."""
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
        """Run the game with the selected account (or account_id). Call repeatedly to run several games at once."""
        if core.mll is None:
            self.log("minecraft-launcher-lib is missing", "error")
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
            self.log(f"{label} {self.mc_version} not installed — installing before launch.", "info")
            version_id = self._install_loader()
            if not version_id:
                return
            self.status("busy")
        need = core.java_major_from_json(self.mc_dir, version_id) or self.java_required()
        found = self._ensure_java(need)
        if not found:
            self.log(f"No suitable Java {need} found. Use Settings > Check / install Java.", "error")
            self.bus.toast.emit(self.t("need_java"), "error")
            self.bus.java.emit(self.t("java_old", v="?", need=need), "error")
            self.status("error")
            self.bus.sound.emit("error")
            return
        java, jver = found
        gdir = self.ensure_game_dir()
        self.log(f"Preparing launch: {version_id} ({acc['name']})", "info")

        ram = int(self.cfg.get("ram_mb", 3072))
        safe = core.clamp_ram_mb(ram)
        if self.game_count():                       # other games running: avoid exhausting system RAM
            avail = core.detect_available_ram_mb()
            if avail and safe + 512 > avail:
                self.log(self.t("low_ram_multi", need=safe, avail=avail), "warn")
                self.bus.toast.emit(self.t("low_ram_multi", need=safe, avail=avail), "warn")
        if safe != ram:
            self.log(f"RAM {ram} MB exceeds 75% of system RAM — lowering to {safe} MB so the OOM-killer never kills the game.", "warn")
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
        # Write the game's stdout to a FILE and read its tail: closing the launcher does not kill the
        # game or break the log with SIGPIPE, unlike piping stdout directly.
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
        self.log(f"Launching Minecraft… ({name})", "ok")
        self.status("playing", self.t("st_playing_n", n=n) if n > 1 else None)
        self.bus.game.emit(True)
        self.bus.sound.emit("launch")
        self.set_discord(f"Playing Minecraft {self.mc_version}", f"{label} · Arch Client")
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
                        for line in f.read().splitlines():  # the rest
                            emit(line)
                        break
                    time.sleep(0.15)
        except Exception as e:
            write_error_log("Reading game log", exc=e)
        code = proc.wait()
        with self._lock:
            self._games.pop(gid, None)
            last = not any(x["proc"].poll() is None for x in self._games.values())
            cleanups, self._cleanups = (self._cleanups, []) if last else ([], self._cleanups)
        for cleanup in cleanups:             # Windows: restore the old power plan when the LAST game exits
            try:
                cleanup()
            except Exception as e:
                write_error_log("Restoring power plan", exc=e)
        left = self.game_count()
        self.bus.game.emit(left > 0)
        if code != 0:
            self.log(f"[{name}] " + self.t("game_crash", code=code), "error")
            p = write_error_log(f"Minecraft crash (code {code}, {name})",
                                extra_text="--- last 200 lines of the game log ---\n" + "\n".join(tail))
            if p:
                self.log(f"Crash details: {p}", "dim")
            self.status("error")
            self.bus.sound.emit("error")
        else:
            self.log(f"[{name}] " + self.t("game_closed"), "info")
        if left:
            self.status("playing", self.t("st_playing_n", n=left) if left > 1 else None)
        elif code == 0:
            self.status("ready")
            self.set_discord("Browsing the launcher", "Arch Client")
        else:
            self.set_discord("Browsing the launcher", "Arch Client")

    # ------------------------------------------------------------ Optimize
    def apply_optimization(self, slugs: list):
        self.run_exclusive("optimize", self._apply_optimization, list(slugs))

    def _apply_optimization(self, slugs):
        self.status("busy", self.t("opt_running"))
        self.log("Starting optimization…", "info")
        gdir = self.ensure_game_dir()
        opt = core.write_optimized_options(gdir)
        self.log(f"Updated {opt}", "ok")
        order = sorted(slugs, key=lambda s: 0 if s == "iris" else 1)  # Iris pins Sodium, install it first
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
                self.log(f"  Download failed {slug}: {e}", "error")
                write_error_log(f"Optimize - download {slug}", exc=e)
        self.bus.progress.emit(total, max(total, 1))
        self.log(f"Optimization complete: {okc}/{total} mods. Restart the game to apply.", "ok")
        self.status("ready")
        self.bus.refresh.emit()
        self.bus.sound.emit("success")
        self.bus.toast.emit(self.t("opt_done"), "ok")

    def set_win_tweak(self, key: str, on: bool):
        """Windows: apply / undo an option immediately when the user flips the switch (registry writes are fast)."""
        if not core.IS_WINDOWS:
            return
        try:
            exe = self.current_java()
            core.apply_windows_tweak(self.cfg, key, on, exe)
        except Exception as e:
            write_error_log(f"Windows option {key}", exc=e)

    def startup_windows(self):
        """Windows: if the launcher died while playing last time, restore the power plan."""
        if core.IS_WINDOWS:
            self.call_async(core.winsys.restore_power_plan, lambda _r: None, lambda _e: None)

    def install_gaming_tools(self):
        def job():
            self.status("busy")
            self.log("Installing gamemode / MangoHud / jemalloc…", "info")
            ok = core.install_gaming_tools(self.log)
            self.log("Installed. Re-enable the options and rescan the hardware." if ok else
                     "Could not install automatically — install the «gamemode» and «mangohud» packages manually.",
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
            self.log(f"Download failed {name}: {e}", "error")
            self.bus.sound.emit("error")
            on_done(False, e)

        self.call_async(job, ok, err)

    # ------------------------------------------------------------ Shortcut
    def install_shortcuts(self, quiet=False):
        def job():
            files = core.install_shortcuts()
            for f in files:
                self.log(f"  {f}", "dim")
            self.log("Shortcut installed.", "ok")
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
                self.log(f"  Removed: {f}", "dim")
            self.cfg["shortcut_opt_out"] = True       # user removed them on purpose -> do not recreate
            self.save()
            self.bus.cfg_changed.emit()
        self.run_exclusive("shortcut", job)

    def startup_shortcuts(self):
        """Create shortcuts on app start (unless the user removed them on purpose); fix them if they point elsewhere."""
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
                self.log("Discord Rich Presence connected.", "dim")
                self.set_discord("Browsing the launcher", "Arch Client")
            except Exception:
                self._rpc = None  # Discord not running: skip silently
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
