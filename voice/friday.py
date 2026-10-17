#!/usr/bin/env python3
"""
FRIDAY — SASTRAVA CEO's personal voice client (Iron-Man style).

Runs hidden in the background. Sleeps until the CEO gives the initiation command:

        *clap* *clap*  ->  "fire up baby daddy's home"

Then FRIDAY wakes (female neural voice), greets the boss, and enters a
conversation loop: it records each spoken command, transcribes it, sends it to
the FINESSE backend (POST /api/voice), speaks the reply, and — when the command
is real work — the backend dispatches the agent swarm. Say a sleep phrase
("stand down" / "go to sleep" / "that's all") to return to the clap-wait state.

Design (Karpathy style — small, readable, hackable):
  listen_for_claps()      mic amplitude transient onset -> count 2 claps
  _confirm_wake_phrase()  short STT window -> fuzzy match the wake phrase
  record_until_silence()  energy VAD -> capture one utterance
  transcribe()            faster-whisper (base.en, CPU int8)
  speak()                 edge-tts neural (online) -> pyttsx3 SAPI (offline fallback)
  api_login/api_voice()   talk to the FINESSE backend with a CEO JWT

Everything is tunable from friday.json (see config.example.json). Audio devices
do not exist in the build sandbox, so this file is written to compile clean and
run/tune on the CEO's machine.
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
import queue
import difflib
import tempfile
import logging
from pathlib import Path

# ----------------------------------------------------------------------------
# Config + logging (no console when built with --noconsole, so log to a file)
# ----------------------------------------------------------------------------
APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "SASTRAVA_FRIDAY"
APP_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = APP_DIR / "friday.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("friday")


DEFAULTS = {
    "base_url": "http://127.0.0.1:8600",
    "account_email": "",
    "account_password": "",
    "wake_phrase": "hey friday",
    "sleep_phrases": ["stand down", "go to sleep", "that's all", "thats all", "goodbye friday"],
    "wake_match_threshold": 0.55,      # fuzzy ratio to accept the wake phrase
    "tts_engine": "edge",              # edge | pyttsx3
    "edge_voice": "en-GB-RyanNeural",  # JARVIS = British male neural voice
    "pyttsx3_voice_hint": "david",     # offline SAPI male fallback (Microsoft David)
    "whisper_model": "base.en",        # tiny.en | base.en | small.en
    "sample_rate": 16000,
    # --- clap detection (tune to your mic/room) ---
    "clap_peak_mult": 5.0,             # a clap peaks >= this * rolling noise floor
    "clap_min_abs": 0.18,              # ...and at least this absolute amplitude (0..1)
    "clap_min_gap_s": 0.12,            # debounce between the two claps
    "clap_max_gap_s": 0.9,             # two claps must land within this window
    # --- utterance capture (energy VAD) ---
    "vad_start_rms": 0.020,            # start capturing above this RMS
    "vad_silence_s": 0.9,              # stop after this much trailing silence
    "vad_max_s": 15.0,                 # hard cap on one utterance
    "phrase_window_s": 3.0,            # how long to listen for the wake phrase after claps
    # --- self-boot the backend so ONE exe brings the whole system up on login ---
    "auto_start_backend": True,
    "project_root": "",
    "backend_python": "",
}


def load_config() -> dict:
    """friday.json next to the exe/script, else in %APPDATA%\\SASTRAVA_FRIDAY, else defaults."""
    cfg = dict(DEFAULTS)
    here = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    for candidate in (Path(sys.executable).parent / "friday.json" if getattr(sys, "frozen", False) else None,
                      here / "friday.json", APP_DIR / "friday.json", Path.cwd() / "friday.json"):
        if candidate and candidate.exists():
            try:
                cfg.update(json.loads(candidate.read_text(encoding="utf-8")))
                log.info("config loaded from %s", candidate)
                break
            except Exception as e:  # noqa: BLE001
                log.warning("bad config %s: %s", candidate, e)
    # env overrides win (handy for the build machine / CI)
    if os.environ.get("FINESSE_BASE_URL"):
        cfg["base_url"] = os.environ["FINESSE_BASE_URL"]
    if os.environ.get("FINESSE_EMAIL"):
        cfg["account_email"] = os.environ["FINESSE_EMAIL"]
    if os.environ.get("FINESSE_PASSWORD"):
        cfg["account_password"] = os.environ["FINESSE_PASSWORD"]
    return cfg


# ----------------------------------------------------------------------------
# FRIDAY
# ----------------------------------------------------------------------------
class Friday:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.sr = int(cfg["sample_rate"])
        self.token: str | None = None
        self._whisper = None
        self._pyttsx = None
        # lazy heavy imports so --help / compile never need audio/ML wheels
        import numpy as np
        self.np = np

    # ---- backend ----------------------------------------------------------
    def api_login(self) -> bool:
        import requests
        if not self.cfg.get("account_email") or not self.cfg.get("account_password"):
            log.error("Set account_email/account_password in friday.json or FINESSE_EMAIL/FINESSE_PASSWORD.")
            return False
        try:
            r = requests.post(f"{self.cfg['base_url']}/api/login",
                              json={"email": self.cfg["account_email"],
                                    "password": self.cfg["account_password"]},
                              timeout=8)
            if r.status_code == 200:
                self.token = r.json()["token"]
                log.info("logged in to FINESSE as %s", self.cfg["account_email"])
                return True
            log.warning("login failed: %s %s", r.status_code, r.text[:200])
        except Exception as e:  # noqa: BLE001
            log.warning("login error (backend up?): %s", e)
        return False

    def api_voice(self, text: str, wake: bool = False) -> str:
        """POST /api/voice and return FRIDAY's spoken reply text."""
        import requests
        if not self.token and not self.api_login():
            return "I can't reach the platform, boss. Is the FINESSE server running?"
        try:
            r = requests.post(f"{self.cfg['base_url']}/api/voice",
                              json={"text": text, "wake": wake},
                              headers={"Authorization": f"Bearer {self.token}"}, timeout=60)
            if r.status_code == 401:                       # token expired -> retry once
                self.token = None
                if self.api_login():
                    return self.api_voice(text, wake)
            if r.status_code == 200:
                return r.json().get("speech", "")
            log.warning("voice api %s: %s", r.status_code, r.text[:200])
            return "Something went wrong talking to the platform, boss."
        except Exception as e:  # noqa: BLE001
            log.warning("voice api error: %s", e)
            return "The platform isn't responding right now, boss."

    # ---- speech in --------------------------------------------------------
    def _whisper_model(self):
        if self._whisper is None:
            from faster_whisper import WhisperModel
            log.info("loading whisper '%s' (cpu int8)…", self.cfg["whisper_model"])
            self._whisper = WhisperModel(self.cfg["whisper_model"], device="cpu", compute_type="int8")
        return self._whisper

    def transcribe(self, audio) -> str:
        """audio: float32 mono numpy array at self.sr -> lowercased text."""
        if audio is None or len(audio) == 0:
            return ""
        segments, _ = self._whisper_model().transcribe(audio, language="en", beam_size=1)
        return " ".join(s.text for s in segments).strip().lower()

    def _rms(self, block) -> float:
        return float(self.np.sqrt(self.np.mean(self.np.square(block))) + 1e-9)

    def listen_for_claps(self) -> None:
        """Block until two claps land inside the configured window. Cheap: only RMS/peak."""
        import sounddevice as sd
        c = self.cfg
        block = int(self.sr * 0.03)               # 30 ms frames
        noise = 0.02                               # rolling noise floor (EMA)
        last_clap = 0.0
        clap_count = 0
        log.info("💤 sleeping — waiting for two claps…")
        with sd.InputStream(samplerate=self.sr, channels=1, blocksize=block, dtype="float32") as stream:
            while True:
                data, _ = stream.read(block)
                mono = data[:, 0]
                peak = float(self.np.max(self.np.abs(mono)))
                rms = self._rms(mono)
                noise = 0.995 * noise + 0.005 * rms  # slow EMA baseline
                now = time.time()
                is_clap = peak >= max(c["clap_min_abs"], c["clap_peak_mult"] * noise)
                if is_clap and (now - last_clap) >= c["clap_min_gap_s"]:
                    if clap_count and (now - last_clap) <= c["clap_max_gap_s"]:
                        clap_count += 1
                    else:
                        clap_count = 1
                    last_clap = now
                    log.info("clap %d (peak=%.3f floor=%.3f)", clap_count, peak, noise)
                    if clap_count >= 2:
                        return
                # reset a stale single clap
                if clap_count == 1 and (now - last_clap) > c["clap_max_gap_s"]:
                    clap_count = 0

    def record_fixed(self, seconds: float):
        import sounddevice as sd
        frames = int(self.sr * seconds)
        audio = sd.rec(frames, samplerate=self.sr, channels=1, dtype="float32")
        sd.wait()
        return audio[:, 0]

    def record_until_silence(self):
        """Energy VAD: wait for speech, capture, stop after trailing silence."""
        import sounddevice as sd
        c = self.cfg
        block = int(self.sr * 0.03)
        collected, started = [], False
        silence_run = 0.0
        t0 = time.time()
        with sd.InputStream(samplerate=self.sr, channels=1, blocksize=block, dtype="float32") as stream:
            while True:
                data, _ = stream.read(block)
                mono = data[:, 0]
                rms = self._rms(mono)
                if not started:
                    if rms >= c["vad_start_rms"]:
                        started = True
                        collected.append(mono.copy())
                    elif time.time() - t0 > 6.0:      # nothing said -> give up
                        return None
                else:
                    collected.append(mono.copy())
                    silence_run = silence_run + 0.03 if rms < c["vad_start_rms"] else 0.0
                    if silence_run >= c["vad_silence_s"]:
                        break
                    if time.time() - t0 > c["vad_max_s"]:
                        break
        return self.np.concatenate(collected) if collected else None

    def _confirm_wake_phrase(self) -> bool:
        """After claps: listen briefly and fuzzy-match the wake phrase."""
        audio = self.record_fixed(self.cfg["phrase_window_s"])
        heard = self.transcribe(audio)
        if not heard:
            return False
        want = self.cfg["wake_phrase"].lower()
        ratio = difflib.SequenceMatcher(None, want, heard).ratio()
        # also accept if the distinctive tokens are present (robust to STT slips)
        tokens_ok = ("fire" in heard and ("baby" in heard or "daddy" in heard or "home" in heard))
        log.info("wake heard: %r (ratio=%.2f, tokens_ok=%s)", heard, ratio, tokens_ok)
        return ratio >= self.cfg["wake_match_threshold"] or tokens_ok

    # ---- speech out -------------------------------------------------------
    def speak(self, text: str) -> None:
        if not text:
            return
        log.info("FRIDAY: %s", text)
        if self.cfg["tts_engine"] == "edge":
            try:
                return self._speak_edge(text)
            except Exception as e:  # noqa: BLE001
                log.warning("edge-tts failed (%s) — falling back to SAPI", e)
        self._speak_pyttsx3(text)

    def _speak_edge(self, text: str) -> None:
        import asyncio
        import edge_tts
        tmp = Path(tempfile.gettempdir()) / f"friday_{int(time.time()*1000)}.mp3"

        async def _synth():
            communicate = edge_tts.Communicate(text, self.cfg["edge_voice"])
            await communicate.save(str(tmp))

        asyncio.run(_synth())
        self._play_mp3(tmp)
        try:
            tmp.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass

    def _play_mp3(self, path: Path) -> None:
        # Prefer playsound (handles mp3 via Windows MCI); fall back to miniaudio.
        try:
            from playsound import playsound
            playsound(str(path), block=True)
            return
        except Exception as e:  # noqa: BLE001
            log.warning("playsound failed (%s) — trying miniaudio", e)
        try:
            import miniaudio  # optional
            stream = miniaudio.stream_file(str(path))
            with miniaudio.PlaybackDevice() as device:
                device.start(stream)
                time.sleep(0.1)
        except Exception as e:  # noqa: BLE001
            log.warning("miniaudio playback failed: %s", e)

    def _speak_pyttsx3(self, text: str) -> None:
        try:
            import pyttsx3
            if self._pyttsx is None:
                self._pyttsx = pyttsx3.init()
                hint = self.cfg["pyttsx3_voice_hint"].lower()
                for v in self._pyttsx.getProperty("voices"):
                    if hint in (v.name or "").lower() or hint in (v.id or "").lower():
                        self._pyttsx.setProperty("voice", v.id)
                        break
                self._pyttsx.setProperty("rate", 178)
            self._pyttsx.say(text)
            self._pyttsx.runAndWait()
        except Exception as e:  # noqa: BLE001
            log.error("pyttsx3 failed: %s", e)

    # ---- main loop --------------------------------------------------------
    def _is_sleep(self, text: str) -> bool:
        return any(p in text for p in self.cfg["sleep_phrases"])

    def conversation(self) -> None:
        """One awake session: greet, then take commands until a sleep phrase."""
        self.speak(self.api_voice("", wake=True))
        while True:
            audio = self.record_until_silence()
            text = self.transcribe(audio)
            if not text:
                continue
            log.info("BOSS: %s", text)
            if self._is_sleep(text):
                self.speak("Standing down, boss. Two claps and the phrase when you need me.")
                return
            self.speak(self.api_voice(text))

    def ensure_backend(self) -> None:
        """Bring the FINESSE backend up if it isn't already — so this one exe boots
        the WHOLE system (backend + voice) on login. Hidden, no console window."""
        if not self.cfg.get("auto_start_backend"):
            return
        import requests
        try:
            if requests.get(f"{self.cfg['base_url']}/health", timeout=2).status_code == 200:
                log.info("backend already running")
                return
        except Exception:  # noqa: BLE001
            pass
        root, py = self.cfg.get("project_root"), self.cfg.get("backend_python")
        if not (root and py and Path(py).exists()):
            log.warning("auto_start_backend on, but project_root/backend_python not found — skip")
            return
        try:
            import subprocess
            CREATE_NO_WINDOW = 0x08000000
            subprocess.Popen([py, "run.py"], cwd=root, creationflags=CREATE_NO_WINDOW,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            log.info("starting FINESSE backend: %s run.py (cwd=%s)", py, root)
        except Exception as e:  # noqa: BLE001
            log.warning("could not auto-start backend: %s", e)

    def run(self) -> None:
        log.info("FRIDAY online. Backend: %s", self.cfg["base_url"])
        self.ensure_backend()
        # warm the login early — waits (up to ~2 min) for the backend to finish booting
        for _ in range(30):
            if self.api_login():
                break
            time.sleep(4)
        while True:
            try:
                self.listen_for_claps()
                if self._confirm_wake_phrase():
                    self.conversation()
                else:
                    log.info("claps heard but wake phrase not confirmed — back to sleep")
            except KeyboardInterrupt:
                log.info("interrupted — exiting")
                return
            except Exception as e:  # noqa: BLE001
                log.exception("loop error: %s", e)
                time.sleep(2)


def main() -> None:
    cfg = load_config()
    if "--selftest" in sys.argv:
        # No audio in the sandbox: just prove config + backend wiring load.
        log.info("SELFTEST config: %s", {k: cfg[k] for k in ("base_url", "wake_phrase", "edge_voice", "whisper_model")})
        f = Friday(cfg)
        log.info("SELFTEST login ok: %s", f.api_login())
        return
    Friday(cfg).run()


if __name__ == "__main__":
    main()
