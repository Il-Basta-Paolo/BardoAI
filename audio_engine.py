"""
AudioEngine — UN SOLO mixer audio (sounddevice) per musica (deck A/B) + effetti sonori + ducking.
Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

from __future__ import annotations

import math
import threading

__author__ = "Paolo Basta"
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

import numpy as np
import sounddevice as sd

try:
    import av  # PyAV
except Exception:  # pragma: no cover - verificato in avvio
    av = None  # type: ignore

SAMPLE_RATE = 48000
CHANNELS = 2
BLOCK_SIZE = 1024
BUFFER_SECONDS = 8.0


def perceptual_gain(vol_0_100: float, exponent: float = 2.2) -> float:
    """Curva di volume percettiva: 50% sullo slider ≈ metà del volume percepito."""
    v = max(0.0, min(100.0, float(vol_0_100))) / 100.0
    return float(v ** exponent)


def decode_file_to_array(path: Path, max_seconds: float = 30.0) -> Optional[np.ndarray]:
    """Decodifica un file audio qualsiasi (wav/mp3/ogg/m4a/flac) in un array float32 (N, 2) a 48 kHz."""
    if av is None or not path.exists():
        return None
    try:
        chunks: List[np.ndarray] = []
        total = 0
        limit = int(max_seconds * SAMPLE_RATE)
        with av.open(str(path)) as container:
            stream = next(s for s in container.streams if s.type == "audio")
            resampler = av.AudioResampler(format="flt", layout="stereo", rate=SAMPLE_RATE)
            for frame in container.decode(stream):
                for rf in resampler.resample(frame):
                    arr = rf.to_ndarray().reshape(-1, CHANNELS)
                    chunks.append(arr.astype(np.float32, copy=False))
                    total += len(arr)
                if total >= limit:
                    break
            for rf in resampler.resample(None):
                chunks.append(rf.to_ndarray().reshape(-1, CHANNELS).astype(np.float32, copy=False))
        if not chunks:
            return None
        return np.ascontiguousarray(np.concatenate(chunks)[:limit])
    except Exception as e:
        print(f"[AudioEngine] Errore decodifica {path.name}: {e}")
        return None


@dataclass
class MusicSource:
    """Sorgente musicale riproducibile: URL di stream, file in cache o file locale."""

    uri: str
    title: str = ""
    duration: float = 0.0
    http_headers: Dict[str, str] = field(default_factory=dict)
    skip_segments: List[Tuple[float, float]] = field(default_factory=list)


class _Deck:
    """Un "piatto" musicale: thread di decodifica + buffer PCM + inviluppo di guadagno."""

    def __init__(self, deck_id: str) -> None:
        self.deck_id = deck_id
        self.lock = threading.Lock()
        self.buffer: Deque[np.ndarray] = deque()
        self.buffered_frames = 0
        self.head_offset = 0  # frame già consumati del primo chunk
        self.source: Optional[MusicSource] = None
        self.token = 0
        self.position_frames = 0
        self.duration = 0.0
        self.eof = False
        self.error: Optional[str] = None
        self.started = False  # primo audio ricevuto
        self.seek_request: Optional[float] = None
        self.stop_event = threading.Event()
        self.space_cond = threading.Condition(self.lock)
        self.thread: Optional[threading.Thread] = None
        # Inviluppo di guadagno (S-curve): gain = g0 + (g1-g0) * (1-cos(pi*t))/2
        self.gain = 0.0
        self.fade_from = 0.0
        self.fade_to = 0.0
        self.fade_len = 0
        self.fade_pos = 0

    # ---- inviluppo
    def start_fade(self, target: float, seconds: float) -> None:
        self.fade_from = self.gain  # parte SEMPRE dal valore attuale → nessun salto
        self.fade_to = float(target)
        self.fade_len = max(1, int(seconds * SAMPLE_RATE))
        self.fade_pos = 0

    def gain_ramp(self, n: int) -> np.ndarray:
        if self.fade_pos >= self.fade_len:
            self.gain = self.fade_to
            return np.full(n, self.gain, dtype=np.float32)
        idx = np.arange(self.fade_pos, self.fade_pos + n, dtype=np.float32)
        t = np.clip(idx / float(self.fade_len), 0.0, 1.0)
        curve = (1.0 - np.cos(np.pi * t)) * 0.5
        ramp = (self.fade_from + (self.fade_to - self.fade_from) * curve).astype(np.float32)
        self.fade_pos = min(self.fade_len, self.fade_pos + n)
        self.gain = float(ramp[-1])
        return ramp

    # ---- buffer
    def pull(self, n: int) -> np.ndarray:
        out = np.zeros((n, CHANNELS), dtype=np.float32)
        filled = 0
        with self.lock:
            while filled < n and self.buffer:
                chunk = self.buffer[0]
                avail = len(chunk) - self.head_offset
                take = min(avail, n - filled)
                out[filled:filled + take] = chunk[self.head_offset:self.head_offset + take]
                filled += take
                self.head_offset += take
                if self.head_offset >= len(chunk):
                    self.buffer.popleft()
                    self.head_offset = 0
            self.buffered_frames -= filled
            self.position_frames += filled
            if filled:
                self.space_cond.notify_all()
        return out

    def clear_buffer(self) -> None:
        with self.lock:
            self.buffer.clear()
            self.buffered_frames = 0
            self.head_offset = 0
            self.space_cond.notify_all()

    @property
    def finished(self) -> bool:
        return self.eof and self.buffered_frames <= 0

    @property
    def position_seconds(self) -> float:
        return self.position_frames / float(SAMPLE_RATE)


class AudioEngine:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._decks = {"A": _Deck("A"), "B": _Deck("B")}
        self.active_deck_id = "A"
        self.paused = False

        self.music_volume = 75
        self._music_gain_target = perceptual_gain(75)
        self._music_gain = self._music_gain_target

        self.sfx_volume = 80
        self._sfx_gain_target = perceptual_gain(80)
        self._sfx_gain = self._sfx_gain_target
        self._sfx_voices: List[List[Any]] = []  # [array, pos, trim]

        # Ducking: inviluppo smussato campione per campione
        self._duck_level = 1.0
        self._duck_target = 1.0
        self._duck_until_frame = 0
        self._frame_clock = 0

        self._stream: Optional[sd.OutputStream] = None
        self.last_error: Optional[str] = None
        self.available = av is not None
        self._start_stream()

    # ================================================================ stream
    def _start_stream(self) -> None:
        try:
            self._stream = sd.OutputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="float32",
                blocksize=BLOCK_SIZE,
                callback=self._callback,
            )
            self._stream.start()
            self.last_error = None
        except Exception as e:
            self.last_error = f"Impossibile aprire l'uscita audio: {e}"
            self._stream = None
            print(f"[AudioEngine] {self.last_error}")

    def ensure_stream(self) -> bool:
        """Assicura che lo stream di output audio sia attivo, tentando la riapertura se necessario."""
        if self._stream is not None:
            try:
                if self._stream.active:
                    return True
            except Exception:
                pass
        self._start_stream()
        return self._stream is not None

    def _callback(self, outdata: np.ndarray, frames: int, _t: Any, _status: Any) -> None:
        mix = np.zeros((frames, CHANNELS), dtype=np.float32)
        with self._lock:
            self._frame_clock += frames
            # --- smoothing volumi (≈ 30 ms)
            a = 1.0 - math.exp(-frames / (0.03 * SAMPLE_RATE))
            self._music_gain += a * (self._music_gain_target - self._music_gain)
            self._sfx_gain += a * (self._sfx_gain_target - self._sfx_gain)

            # --- ducking: discesa 80 ms, risalita 500 ms
            target = self._duck_target if self._frame_clock < self._duck_until_frame else 1.0
            tau = 0.08 if target < self._duck_level else 0.5
            coef = 1.0 - math.exp(-1.0 / (tau * SAMPLE_RATE))
            duck_curve = np.empty(frames, dtype=np.float32)
            lvl = self._duck_level
            # forma chiusa del filtro esponenziale su `frames` campioni
            decay = (1.0 - coef) ** np.arange(1, frames + 1, dtype=np.float32)
            duck_curve[:] = target + (lvl - target) * decay
            self._duck_level = float(duck_curve[-1])

            # --- musica
            if not self.paused:
                for deck in self._decks.values():
                    if deck.source is None or (deck.gain <= 1e-4 and deck.fade_pos >= deck.fade_len and deck.fade_to <= 1e-4):
                        continue
                    pcm = deck.pull(frames)
                    ramp = deck.gain_ramp(frames)
                    mix += pcm * ramp[:, None]
                mix *= (self._music_gain * duck_curve)[:, None]

            # --- effetti sonori
            if self._sfx_voices:
                sfx_mix = np.zeros((frames, CHANNELS), dtype=np.float32)
                alive = []
                for voice in self._sfx_voices:
                    arr, pos, trim = voice
                    n = min(frames, len(arr) - pos)
                    if n > 0:
                        sfx_mix[:n] += arr[pos:pos + n] * trim
                        voice[1] = pos + n
                    if voice[1] < len(arr):
                        alive.append(voice)
                self._sfx_voices = alive
                mix += sfx_mix * self._sfx_gain

        np.tanh(mix, out=mix)  # soft limiter trasparente
        outdata[:] = mix

    # ================================================================ volumi
    def set_music_volume(self, vol: int) -> None:
        with self._lock:
            self.music_volume = max(0, min(100, int(vol)))
            self._music_gain_target = perceptual_gain(self.music_volume)

    def set_sfx_volume(self, vol: int) -> None:
        with self._lock:
            self.sfx_volume = max(0, min(100, int(vol)))
            self._sfx_gain_target = perceptual_gain(self.sfx_volume, 2.0) * 0.9

    def duck(self, duration_sec: float) -> None:
        """Attenua la musica (max −2.5 dB, proporzionale al volume SFX) per la durata dell'effetto."""
        with self._lock:
            if self.sfx_volume <= 10:
                return
            depth = 0.25 * ((self.sfx_volume / 100.0) ** 1.4)
            self._duck_target = min(self._duck_target if self._frame_clock < self._duck_until_frame else 1.0, 1.0 - depth)
            hold = max(0.4, min(2.5, duration_sec * 0.6))
            self._duck_until_frame = max(self._duck_until_frame, self._frame_clock + int(hold * SAMPLE_RATE))

    # ================================================================ SFX
    def play_sfx_array(self, arr: np.ndarray, trim: float = 1.0) -> float:
        self.ensure_stream()
        with self._lock:
            if len(self._sfx_voices) >= 12:  # polifonia limitata per non saturare
                self._sfx_voices.pop(0)
            self._sfx_voices.append([arr, 0, float(trim)])
        return len(arr) / float(SAMPLE_RATE)

    play_sfx = play_sfx_array

    # ================================================================ musica
    def play(self, source: MusicSource, crossfade_seconds: float) -> int:
        """
        Avvia `source` sul deck inattivo e fa il crossfade S-curve dal deck attuale.
        Ritorna il token del deck (usato per riconoscere gli eventi di fine brano).
        """
        self.ensure_stream()
        with self._lock:
            old = self._decks[self.active_deck_id]
            new_id = "B" if self.active_deck_id == "A" else "A"
            new = self._decks[new_id]
            self._stop_deck(new)
            new.token += 1
            new.source = source
            new.duration = source.duration
            new.position_frames = 0
            new.eof = False
            new.error = None
            new.started = False
            new.gain = 0.0
            new.fade_from = new.fade_to = 0.0
            new.fade_len = 1
            new.fade_pos = 1
            new.stop_event = threading.Event()
            token = new.token
            self.active_deck_id = new_id
            self.paused = False
            fade = max(0.05, float(crossfade_seconds))
            old_playing = old.source is not None and old.gain > 1e-3
            self._pending_fade = (new, old if old_playing else None, fade)

        new.thread = threading.Thread(target=self._decode_worker, args=(new, token), daemon=True, name=f"decode-{new_id}")
        new.thread.start()
        return token

    def _begin_crossfade_when_ready(self, deck: _Deck, token: int) -> None:
        with self._lock:
            pend = getattr(self, "_pending_fade", None)
            if not pend or pend[0] is not deck or deck.token != token:
                return
            new, old, fade = pend
            self._pending_fade = None
            new.start_fade(1.0, fade if old is not None else min(fade, 2.0))
            if old is not None:
                old.start_fade(0.0, fade)
                threading.Timer(fade + 0.2, self._stop_if_silent, args=(old, old.token)).start()

    def _stop_if_silent(self, deck: _Deck, token: int) -> None:
        with self._lock:
            if deck.token == token and deck.deck_id != self.active_deck_id and deck.gain <= 1e-3:
                self._stop_deck(deck)

    def _stop_deck(self, deck: _Deck) -> None:
        deck.stop_event.set()
        with deck.lock:
            deck.space_cond.notify_all()
        deck.clear_buffer()
        deck.source = None
        deck.gain = 0.0
        deck.fade_to = 0.0
        deck.fade_pos = deck.fade_len

    def stop(self, fade_seconds: float = 1.0) -> None:
        with self._lock:
            for d in self._decks.values():
                d.start_fade(0.0, fade_seconds)

    def pause(self) -> None:
        with self._lock:
            self.paused = True

    def resume(self) -> None:
        with self._lock:
            self.paused = False

    def seek(self, seconds: float) -> None:
        deck = self._decks[self.active_deck_id]
        with deck.lock:
            deck.seek_request = max(0.0, float(seconds))
            deck.space_cond.notify_all()

    def active_status(self) -> Dict[str, Any]:
        deck = self._decks[self.active_deck_id]
        return {
            "token": deck.token,
            "deck": deck.deck_id,
            "position": deck.position_seconds,
            "duration": deck.duration,
            "finished": deck.source is not None and deck.finished,
            "error": deck.error,
            "started": deck.started,
            "has_source": deck.source is not None,
            "paused": self.paused,
        }

    # ================================================================ decoder
    def _decode_worker(self, deck: _Deck, token: int) -> None:
        src = deck.source
        if src is None or av is None:
            deck.error = "PyAV non disponibile" if av is None else "Sorgente mancante"
            deck.eof = True
            return
        max_frames = int(BUFFER_SECONDS * SAMPLE_RATE)
        options: Dict[str, str] = {}
        if src.uri.startswith("http"):
            options = {
                "reconnect": "1",
                "reconnect_streamed": "1",
                "reconnect_delay_max": "5",
                "rw_timeout": "15000000",
            }
            ua = src.http_headers.get("User-Agent")
            if ua:
                options["user_agent"] = ua
            extra = "".join(f"{k}: {v}\r\n" for k, v in src.http_headers.items() if k.lower() != "user-agent")
            if extra:
                options["headers"] = extra
        try:
            with av.open(src.uri, options=options, timeout=15.0) as container:
                stream = next(s for s in container.streams if s.type == "audio")
                if not deck.duration and container.duration:
                    deck.duration = container.duration / 1_000_000.0
                resampler = av.AudioResampler(format="flt", layout="stereo", rate=SAMPLE_RATE)
                segments = sorted(src.skip_segments)
                frame_iter = container.decode(stream)
                while not deck.stop_event.is_set():
                    # seek richiesto dalla UI o salto SponsorBlock
                    seek_to = None
                    with deck.lock:
                        if deck.seek_request is not None:
                            seek_to = deck.seek_request
                            deck.seek_request = None
                    if seek_to is not None:
                        container.seek(int(seek_to / stream.time_base), stream=stream, any_frame=False, backward=True)
                        deck.clear_buffer()
                        deck.position_frames = int(seek_to * SAMPLE_RATE)
                        resampler = av.AudioResampler(format="flt", layout="stereo", rate=SAMPLE_RATE)
                        frame_iter = container.decode(stream)
                    try:
                        frame = next(frame_iter)
                    except StopIteration:
                        break
                    ts = float(frame.pts * stream.time_base) if frame.pts is not None else None
                    if ts is not None and segments:
                        skip = next(((s, e) for s, e in segments if s <= ts < e - 0.5), None)
                        if skip:
                            with deck.lock:
                                deck.seek_request = skip[1]
                            segments = [seg for seg in segments if seg != skip]
                            continue
                    for rf in resampler.resample(frame):
                        arr = rf.to_ndarray().reshape(-1, CHANNELS).astype(np.float32, copy=False)
                        with deck.lock:
                            while deck.buffered_frames >= max_frames and not deck.stop_event.is_set() and deck.seek_request is None:
                                deck.space_cond.wait(timeout=0.5)
                            if deck.stop_event.is_set():
                                return
                            deck.buffer.append(arr)
                            deck.buffered_frames += len(arr)
                    if not deck.started and deck.buffered_frames > SAMPLE_RATE * 0.5:
                        deck.started = True
                        self._begin_crossfade_when_ready(deck, token)
            if not deck.started and deck.buffered_frames > 0:
                deck.started = True
                self._begin_crossfade_when_ready(deck, token)
        except Exception as e:
            deck.error = str(e)[:300]
        finally:
            deck.eof = True

    def shutdown(self) -> None:
        with self._lock:
            for d in self._decks.values():
                self._stop_deck(d)
        try:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
        except Exception:
            pass
