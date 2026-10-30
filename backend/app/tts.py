"""Spoken guidance with Supertonic 3 (voice F1, "Sarah").

Supertonic runs as its own loopback-only service on the server (`supertonic serve`, systemd
unit supertonic-tts.service, separate venv in /home/ubuntu/supertonic-tts). The app only calls it
over HTTP with httpx, so no new package is added to the app's lock files.

- Text never leaves the server and is never logged.
- Same sentence -> same audio, so finished audio is cached in memory.
- Any failure raises TtsUnavailable; the screen then falls back to the browser's own voice.
"""
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import os
import re
import threading

import httpx

DEFAULT_URL = "http://127.0.0.1:7788"
DEFAULT_VOICE = "F1"  # Supertonic built-in female voice 1, listed as "Sarah" by voice-name wrappers
MAX_TEXT = 300
CACHE_SIZE = 200
MEDIA_TYPE = "audio/flac"  # about half the size of WAV; Chrome, Edge, Firefox and Safari play it

_COUNTERS = ["", "한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉"]


class TtsUnavailable(RuntimeError):
    """Fixed message: never carries the text or the service response."""


def spoken_text(text: str) -> str:
    """Written forms the voice reads badly or rejects: units, symbols, '1곳'."""
    s = " ".join(str(text).split())
    s = re.sub(r"(\d)\s*mm\b", r"\1밀리미터", s)
    s = re.sub(r"(\d)\s*km\b", r"\1킬로미터", s)
    s = re.sub(r"(\d)\s*m\b", r"\1미터", s)
    s = re.sub(r"(?<!\d)([1-9])곳", lambda m: f"{_COUNTERS[int(m.group(1))]} 곳", s)
    s = s.replace("→", " 에서 ").replace("·", ", ").replace("ㆍ", ", ").replace("/", ", ")
    s = re.sub(r"[()\[\]{}<>~*_#|\"“”‘’]", " ", s)
    s = re.sub(r"[^0-9A-Za-z가-힣 .,?!'%:-]", " ", s)  # anything else the model may not know
    s = re.sub(r"\s+([,.?!])", r"\1", " ".join(s.split()))
    return s.strip(" ,")


@dataclass(frozen=True)
class TtsSettings:
    url: str
    voice: str
    speed: float
    timeout_s: float


def settings() -> TtsSettings:
    def number(name: str, default: float, low: float, high: float) -> float:
        try:
            value = float(os.environ.get(name) or default)
        except ValueError:
            value = default
        return min(max(value, low), high)

    return TtsSettings(
        url=os.environ.get("KIROTHON_TTS_URL", DEFAULT_URL).strip().rstrip("/"),
        voice=(os.environ.get("KIROTHON_TTS_VOICE") or DEFAULT_VOICE).strip(),
        speed=number("KIROTHON_TTS_SPEED", 1.05, 0.7, 2.0),
        timeout_s=number("KIROTHON_TTS_TIMEOUT_S", 10.0, 1.0, 30.0),
    )


class SupertonicTts:
    def __init__(self, *, transport: httpx.BaseTransport | None = None):
        self._transport = transport
        self._cache: OrderedDict[str, bytes] = OrderedDict()
        self._lock = threading.Lock()

    def synthesize(self, text: str) -> bytes:
        cfg = settings()
        if not cfg.url:
            raise TtsUnavailable()
        spoken = spoken_text(text)
        if not spoken:
            raise TtsUnavailable()
        key = hashlib.sha256(f"{cfg.voice}|{cfg.speed}|{spoken}".encode("utf-8")).hexdigest()
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        body = {"text": spoken, "voice": cfg.voice, "lang": "ko", "speed": cfg.speed, "response_format": "flac"}
        try:
            with httpx.Client(timeout=cfg.timeout_s, transport=self._transport) as client:
                response = client.post(f"{cfg.url}/v1/tts", json=body)
        except httpx.HTTPError:
            raise TtsUnavailable() from None
        if response.status_code != 200 or not response.content:
            raise TtsUnavailable()
        audio = response.content
        with self._lock:
            self._cache[key] = audio
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
        return audio


@lru_cache(maxsize=1)
def get_tts() -> SupertonicTts:
    return SupertonicTts()
