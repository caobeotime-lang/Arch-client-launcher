# -*- coding: utf-8 -*-
"""Interface sounds — synthesizes its own WAV files (nothing to download), played via Qt or paplay/pw-play/aplay."""
from __future__ import annotations

import json
import math
import os
import shutil
import struct
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

from .bootstrap import CACHE_DIR, IS_WINDOWS, hidden_kwargs, write_error_log

SR = 44100
SOUND_DIR = CACHE_DIR / "sounds" / "v2"


def _env(i: int, n: int, attack=0.004, power=3.0) -> float:
    """Envelope: very fast attack, smooth release so there is no 'click' at either end."""
    t = i / max(1, n - 1)
    a = min(1.0, i / (SR * attack))
    return a * (1.0 - t) ** power


def _tone(freq, dur, amp=0.4, f_end=None, power=3.0, harm=0.25) -> list:
    n = int(SR * dur)
    out, phase = [], 0.0
    for i in range(n):
        f = freq if f_end is None else freq + (f_end - freq) * (i / max(1, n - 1))
        phase += 2 * math.pi * f / SR
        s = math.sin(phase) + harm * math.sin(2 * phase)
        out.append(s * amp * _env(i, n, power=power))
    return out


def _mix(*parts) -> list:
    """Each part is (offset in seconds, samples)."""
    length = max(int(SR * off) + len(smp) for off, smp in parts)
    buf = [0.0] * length
    for off, smp in parts:
        o = int(SR * off)
        for i, v in enumerate(smp):
            buf[o + i] += v
    return buf


def _write(path: Path, samples: list) -> None:
    peak = max(1e-6, max(abs(s) for s in samples))
    scale = min(1.0, 0.92 / peak)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, s * scale)) * 32767)) for s in samples))


def _build() -> dict:
    return {
        "hover": _tone(2400, 0.028, 0.10, power=2.0, harm=0.0),
        "click": _tone(620, 0.075, 0.38, f_end=420, power=2.5),
        "nav": _tone(780, 0.06, 0.28, f_end=980, power=2.2),
        "on": _mix((0, _tone(660, 0.09, 0.32)), (0.07, _tone(990, 0.12, 0.32))),
        "off": _mix((0, _tone(900, 0.09, 0.30)), (0.07, _tone(600, 0.12, 0.30))),
        "success": _mix((0, _tone(523, 0.16, 0.28)), (0.09, _tone(659, 0.16, 0.28)),
                        (0.18, _tone(784, 0.30, 0.30, power=2.2))),
        "error": _mix((0, _tone(260, 0.14, 0.38, power=2.0)), (0.15, _tone(200, 0.22, 0.38, power=2.0))),
        "launch": _tone(280, 0.55, 0.36, f_end=1100, power=1.6, harm=0.3),
        "notify": _mix((0, _tone(880, 0.10, 0.26)), (0.10, _tone(1175, 0.18, 0.26))),
    }


def ensure_sounds() -> dict:
    """Returns {name: path}; creates the WAV files when missing."""
    paths = {}
    try:
        SOUND_DIR.mkdir(parents=True, exist_ok=True)
        names = ["hover", "click", "nav", "on", "off", "success", "error", "launch", "notify"]
        if not all((SOUND_DIR / f"{n}.wav").exists() for n in names):
            for name, smp in _build().items():
                _write(SOUND_DIR / f"{name}.wav", smp)
        for n in names:
            paths[n] = SOUND_DIR / f"{n}.wav"
    except Exception as e:
        write_error_log("Generating interface sounds", exc=e)
    return paths


_PROBE_CODE = (
    "import sys\n"
    "from PyQt6.QtCore import QCoreApplication\n"
    "app = QCoreApplication(sys.argv)\n"
    "from PyQt6.QtMultimedia import QMediaDevices, QSoundEffect\n"
    "n = len(QMediaDevices.audioOutputs())\n"
    "e = QSoundEffect(); e.setVolume(0.0)\n"
    "print('QTAUDIO', n)\n"
)
_PROBE_FILE = CACHE_DIR / "audio_probe.json"


def probe_qt_audio() -> bool:
    """QtMultimedia can crash the whole process (segfault) on machines with no audio device or a broken
    backend — try/except cannot catch that. So probe it in a child process first and remember the result."""
    try:
        d = json.loads(_PROBE_FILE.read_text(encoding="utf-8"))
        if d.get("v") == 1 and time.time() - d.get("t", 0) < 14 * 86400:
            return bool(d.get("ok"))
    except Exception:
        pass
    if getattr(sys, "frozen", False):   # frozen build: sys.executable is the app itself -> do not probe
        # Windows: QSoundEffect does not crash when speakers are missing; the device is re-checked on the GUI thread (_make_effects).
        # Linux: use pw-play/paplay.
        return IS_WINDOWS
    ok = False
    try:
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        exe = sys.executable
        if IS_WINDOWS and exe.lower().endswith("pythonw.exe"):
            exe = exe[:-len("pythonw.exe")] + "python.exe"       # pythonw has no stdout to read the result from
        r = subprocess.run([exe, "-c", _PROBE_CODE], env=env, timeout=12,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, **hidden_kwargs())
        ok = r.returncode == 0 and any(l.startswith("QTAUDIO") and int(l.split()[1]) > 0
                                       for l in r.stdout.splitlines())
    except Exception:
        ok = False
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _PROBE_FILE.write_text(json.dumps({"v": 1, "t": time.time(), "ok": ok}), encoding="utf-8")
    except Exception:
        pass
    return ok


class SoundPlayer:
    """Play an interface sound, never raises."""

    MIN_GAP = {"hover": 0.07}

    def __init__(self, enabled=True, volume=60):
        self.enabled = bool(enabled)
        self.volume = max(0, min(100, int(volume)))
        self._paths: dict = {}
        self._effects: dict = {}
        self._qt_ok = False       # True only when the child-process probe succeeded
        self._ready = False       # files + probe finished (runs in background)
        self._starting = False
        self._cli = None
        self._procs: list = []
        self._last: dict = {}

    def preload(self) -> None:
        """Generate WAVs + probe the audio backend on a background thread (never blocks the UI)."""
        if self._ready or self._starting:
            return
        self._starting = True

        def work():
            try:
                self._paths = ensure_sounds()
                if IS_WINDOWS:
                    try:
                        import winsound  # noqa: F401
                        self._cli = "winsound"       # fallback when Qt Multimedia is unavailable
                    except ImportError:
                        pass
                else:
                    for exe in ("pw-play", "paplay", "aplay"):
                        if shutil.which(exe):
                            self._cli = exe
                            break
                self._qt_ok = probe_qt_audio()
            except Exception as e:
                write_error_log("Audio init", exc=e)
            self._ready = True
        threading.Thread(target=work, name="arch-sound-init", daemon=True).start()

    def _make_effects(self) -> None:
        """Create QSoundEffect (must run on the GUI thread). Called on first playback."""
        try:
            from PyQt6.QtMultimedia import QMediaDevices, QSoundEffect
            from PyQt6.QtCore import QUrl
            if IS_WINDOWS and not QMediaDevices.audioOutputs():
                self._qt_ok = False          # no speakers/headphones: skip the effects
                return
            for name, p in self._paths.items():
                e = QSoundEffect()
                e.setSource(QUrl.fromLocalFile(str(p)))
                e.setVolume(self._vol(name))
                self._effects[name] = e
        except Exception:
            self._qt_ok = False

    def _vol(self, name: str) -> float:
        base = self.volume / 100.0
        return base * (0.5 if name == "hover" else 1.0)

    def set_volume(self, v: int) -> None:
        self.volume = max(0, min(100, int(v)))
        for name, e in self._effects.items():
            try:
                e.setVolume(self._vol(name))
            except Exception:
                pass

    def play(self, name: str) -> None:
        if not self.enabled or self.volume <= 0:
            return
        now = time.monotonic()
        gap = self.MIN_GAP.get(name, 0.0)
        if now - self._last.get(name, 0.0) < gap:
            return
        self._last[name] = now
        try:
            if not self._ready:
                self.preload()
                return
            if self._qt_ok and not self._effects:
                self._make_effects()
            e = self._effects.get(name)
            if self._qt_ok and e is not None:
                from PyQt6.QtMultimedia import QSoundEffect
                if e.status() != QSoundEffect.Status.Error:
                    e.play()
                    return
            self._play_cli(name)
        except Exception:
            pass

    def _play_cli(self, name: str) -> None:
        if not self._cli or name == "hover":   # hover is too frequent to spawn a process
            return
        self._procs = [p for p in self._procs if p.poll() is None]
        if len(self._procs) >= 4:
            return
        path = self._paths.get(name)
        if not path:
            return
        if self._cli == "winsound":
            import winsound
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            return
        cmd = [self._cli, str(path)]
        if self._cli == "paplay":
            cmd = ["paplay", f"--volume={int(65536 * self.volume / 100)}", str(path)]
        elif self._cli == "pw-play":
            cmd = ["pw-play", f"--volume={self.volume / 100:.2f}", str(path)]
        self._procs.append(subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

    def shutdown(self) -> None:
        for p in self._procs:
            try:
                p.terminate()
            except Exception:
                pass
        self._procs.clear()
        self._effects.clear()
