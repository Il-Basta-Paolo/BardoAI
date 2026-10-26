"""
Modulo di ascolto vocale continuo e Speech-to-Text (STT) 100% locale per Bardo AI v2.6.3
Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
Caratteristiche:
- Streaming STT a bassissima latenza (~150-200ms) tramite Vosk per l'attivazione immediata degli SFX.
- Trascrizione di fine frase ad alta precisione tramite faster-whisper (o Vosk final) per la regia d'atmosfera.
- VAD (Voice Activity Detection) adattivo con soglia automatica sul rumore di fondo.
- Gestione thread-safe con arresto deterministico (stop/join) su cambio microfono (risolve bug #9 di bastaaaa.md).
- Bounded audio queue e protezione da burst di rumore (risolve bug #10 di bastaaaa.md).
- Gestione automatica del download dei modelli in %APPDATA%/BardoAI/data/models senza bloccare l'interfaccia.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import shutil
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx
import numpy as np
import sounddevice as sd

from storage import MODELS_DIR, ensure_data_dir

# URLs e modelli predefiniti
VOSK_MODEL_NAME = "vosk-model-small-it-0.22"
VOSK_MODEL_URL = f"https://alphacephei.com/vosk/models/{VOSK_MODEL_NAME}.zip"
WHISPER_MODEL_SIZE = "tiny"


class ModelManager:
    """Gestisce il download e la verifica dei modelli STT locali (Vosk e Whisper)."""

    @classmethod
    def get_vosk_model_dir(cls) -> Path:
        ensure_data_dir()
        return MODELS_DIR / VOSK_MODEL_NAME

    @classmethod
    def is_vosk_ready(cls) -> bool:
        vdir = cls.get_vosk_model_dir()
        if not vdir.is_dir():
            return False
        # Un modello Vosk valido contiene almeno am/final.mdl o conf/model.conf
        return (vdir / "conf").is_dir() or (vdir / "am").is_dir() or any(vdir.glob("*.mdl"))

    @classmethod
    def download_vosk_model(
        cls,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        on_complete: Optional[Callable[[bool, str], None]] = None,
    ) -> None:
        """Scarica e decomprime il modello Vosk italiano (~45MB) in background."""
        if cls.is_vosk_ready():
            if on_complete:
                on_complete(True, "Modello Vosk già pronto.")
            return

        def _worker() -> None:
            zip_dest = MODELS_DIR / f"{VOSK_MODEL_NAME}.zip"
            try:
                ensure_data_dir()
                if progress_callback:
                    progress_callback(0.05, "Avvio download modello vocale italiano (Vosk, 45MB)...")

                with httpx.stream("GET", VOSK_MODEL_URL, follow_redirects=True, timeout=60.0) as resp:
                    resp.raise_for_status()
                    total = float(resp.headers.get("content-length", 45 * 1024 * 1024))
                    downloaded = 0
                    with open(zip_dest, "wb") as f:
                        for chunk in resp.iter_bytes(chunk_size=128 * 1024):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                if progress_callback and total > 0:
                                    pct = min(0.90, 0.05 + 0.85 * (downloaded / total))
                                    mb = downloaded / (1024 * 1024)
                                    tot_mb = total / (1024 * 1024)
                                    progress_callback(pct, f"Download modello: {mb:.1f}/{tot_mb:.1f} MB ({int(pct*100)}%)")

                if progress_callback:
                    progress_callback(0.92, "Estrazione archivio modello vocale...")

                with zipfile.ZipFile(zip_dest, "r") as zf:
                    zf.extractall(MODELS_DIR)

                zip_dest.unlink(missing_ok=True)

                if cls.is_vosk_ready():
                    if progress_callback:
                        progress_callback(1.0, "Modello vocale Vosk installato con successo!")
                    if on_complete:
                        on_complete(True, "Vosk pronto.")
                else:
                    if on_complete:
                        on_complete(False, "Estrazione completata ma directory modello non valida.")
            except Exception as e:
                zip_dest.unlink(missing_ok=True)
                if on_complete:
                    on_complete(False, f"Errore download modello Vosk: {e}")

        t = threading.Thread(target=_worker, daemon=True, name="vosk-downloader")
        t.start()


class ContinuousVoiceListener:
    """
    Motore di ascolto microfonico e trascrizione 100% locale:
    - Audio capture a 16000Hz mono int16 via sounddevice.
    - Vosk in streaming per rilevare parziali ad alta velocità (~150-200ms) per gli SFX.
    - Faster-Whisper (o Vosk final) su completamento frase per il cambio d'atmosfera.
    - Arresto e riavvio thread-safe senza lock contention (bug #9 risolto).
    """

    SAMPLE_RATE = 16000
    BLOCK_DURATION = 0.064  # ~64ms per blocco (1024 campioni)
    MAX_SPEECH_DURATION = 8.0  # durata max frase prima dello spezzamento forzato
    SILENCE_CUTOFF_SEC = 0.75   # silenzio che chiude la frase

    def __init__(
        self,
        on_transcript: Callable[[str], None],
        on_partial_transcript: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        on_level: Optional[Callable[[float], None]] = None,
        use_whisper: bool = True,
        whisper_model: str = "small",
        gate_threshold: int = 20,
    ) -> None:
        self.on_transcript = on_transcript
        self.on_partial_transcript = on_partial_transcript
        self.on_status = on_status
        self.on_level = on_level
        self.use_whisper = use_whisper
        self.whisper_model = whisper_model or WHISPER_MODEL_SIZE
        self._gate_threshold = max(5, min(85, gate_threshold))

        self.selected_device_index: Optional[int] = None
        self.is_listening: bool = False

        self._stop_event = threading.Event()
        self._generation_token: int = 0
        self._lock = threading.Lock()

        self._capture_thread: Optional[threading.Thread] = None
        self._transcribe_thread: Optional[threading.Thread] = None

        # Queue limitata per prevenire accumulo infinito in caso di spike di rumore (bug #10)
        self._phrase_queue: "queue.Queue[Tuple[int, bytes]]" = queue.Queue(maxsize=15)

        # Modelli STT
        self._vosk_model: Optional[Any] = None
        self._vosk_recognizer: Optional[Any] = None
        self._whisper_model: Optional[Any] = None
        self._whisper_loading: bool = False

        self._init_models_async()

    def _init_models_async(self) -> None:
        """Inizializza i modelli in un thread di avvio."""
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return

        def _loader() -> None:
            # 1. Carica Vosk se disponibile
            if ModelManager.is_vosk_ready():
                try:
                    import vosk
                    vosk.SetLogLevel(-1)
                    vpath = str(ModelManager.get_vosk_model_dir())
                    self._vosk_model = vosk.Model(vpath)
                    print("[VoiceListener] Modello Vosk italiano caricato con successo.")
                except Exception as e:
                    print(f"[VoiceListener] Impossibile caricare Vosk (modello corrotto o incompleto): {e}")
                    shutil.rmtree(ModelManager.get_vosk_model_dir(), ignore_errors=True)
                    print("[VoiceListener] Cartella modello rimossa. Avvio nuovo download...")
                    ModelManager.download_vosk_model(
                        progress_callback=lambda p, s: self._notify_status(f"📥 {s}"),
                        on_complete=self._on_vosk_download_finished,
                    )
            else:
                print("[VoiceListener] Modello Vosk non presente. Download automatico in corso...")
                ModelManager.download_vosk_model(
                    progress_callback=lambda p, s: self._notify_status(f"📥 {s}"),
                    on_complete=self._on_vosk_download_finished,
                )

            # 2. Carica Faster-Whisper se richiesto
            if self.use_whisper:
                try:
                    from faster_whisper import WhisperModel
                    whisper_dir = MODELS_DIR / "whisper"
                    whisper_dir.mkdir(parents=True, exist_ok=True)
                    self._notify_status(f"Caricamento Faster-Whisper ({self.whisper_model}, CPU int8)...")
                    self._whisper_model = WhisperModel(
                        self.whisper_model,
                        device="cpu",
                        compute_type="int8",
                        download_root=str(whisper_dir),
                    )
                    print(f"[VoiceListener] Faster-Whisper ({self.whisper_model}) inizializzato.")
                except Exception as e:
                    print(f"[VoiceListener] Faster-Whisper non disponibile (uso fallback Vosk): {e}")

            if self.is_listening:
                self._notify_status("🎙️ In ascolto vocale (100% offline)... Parla liberamente!")

        threading.Thread(target=_loader, daemon=True, name="stt-model-loader").start()

    def _on_vosk_download_finished(self, success: bool, msg: str) -> None:
        if success:
            try:
                import vosk
                vosk.SetLogLevel(-1)
                vpath = str(ModelManager.get_vosk_model_dir())
                self._vosk_model = vosk.Model(vpath)
                self._notify_status("🎙️ Modello vocale pronto! In ascolto...")
            except Exception as e:
                self._notify_status(f"⚠️ Errore inizializzazione Vosk: {e}")
        else:
            self._notify_status(f"⚠️ {msg}")

    def _notify_status(self, msg: str) -> None:
        if self.on_status:
            try:
                self.on_status(msg)
            except Exception:
                pass

    # ================================================================ Dispositivi Audio
    @staticmethod
    def get_input_devices() -> List[Dict[str, Any]]:
        """Restituisce l'elenco dei microfoni disponibili su Windows."""
        devices_out: List[Dict[str, Any]] = [
            {"index": None, "name": "🎙️ Microfono Predefinito di Windows"}
        ]
        seen_names = set()
        try:
            all_devs = sd.query_devices()
            for idx, dev in enumerate(all_devs):
                if dev.get("max_input_channels", 0) > 0:
                    name = str(dev.get("name", f"Dispositivo {idx}")).strip()
                    if name not in seen_names and "Mapper" not in name:
                        seen_names.add(name)
                        devices_out.append({"index": idx, "name": f"🎙️ {name}"})
        except Exception as e:
            print(f"[VoiceListener] Errore lettura dispositivi audio: {e}")
        return devices_out

    # ================================================================ Thread Control
    def set_device(self, device_index: Optional[int]) -> None:
        """
        Cambia il dispositivo microfono in modo thread-safe (risolve bug #9 di bastaaaa.md).
        Arresta con join i thread attivi prima di aprire il nuovo dispositivo.
        """
        with self._lock:
            was_running = self.is_listening
            if was_running:
                self._stop_internal()
            self.selected_device_index = device_index
            if was_running:
                self._start_internal()

    def set_gate_threshold(self, threshold_pct: int) -> None:
        """Imposta dinamicamente la soglia di Noise Gate (VAD) in percentuale (5-85%)."""
        with self._lock:
            self._gate_threshold = max(5, min(85, threshold_pct))

    @property
    def gate_threshold(self) -> int:
        with self._lock:
            return self._gate_threshold

    def start(self) -> None:
        with self._lock:
            if self.is_listening:
                return
            self._start_internal()

    def stop(self) -> None:
        with self._lock:
            if not self.is_listening:
                return
            self._stop_internal()

    def _start_internal(self) -> None:
        self.is_listening = True
        self._stop_event.clear()
        self._generation_token += 1
        gen = self._generation_token

        # Svuota la queue
        while not self._phrase_queue.empty():
            try:
                self._phrase_queue.get_nowait()
            except queue.Empty:
                break

        # Crea un recognizer Vosk per questo stream se il modello è pronto
        if self._vosk_model is not None:
            try:
                import vosk
                self._vosk_recognizer = vosk.KaldiRecognizer(self._vosk_model, self.SAMPLE_RATE)
                self._vosk_recognizer.SetWords(False)
            except Exception as e:
                print(f"[VoiceListener] Errore creazione KaldiRecognizer: {e}")
                self._vosk_recognizer = None
        else:
            self._vosk_recognizer = None

        self._capture_thread = threading.Thread(
            target=self._capture_loop,
            args=(gen,),
            daemon=True,
            name=f"mic-capture-{gen}",
        )
        self._transcribe_thread = threading.Thread(
            target=self._transcribe_loop,
            args=(gen,),
            daemon=True,
            name=f"stt-worker-{gen}",
        )
        self._capture_thread.start()
        self._transcribe_thread.start()

        self._notify_status("🎙️ In ascolto vocale... Parla liberamente!")

    def _stop_internal(self) -> None:
        self.is_listening = False
        self._stop_event.set()
        self._generation_token += 1

        # Attesa controllata della chiusura dei thread (risolve bug #9)
        if self._capture_thread is not None and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=1.5)
        if self._transcribe_thread is not None and self._transcribe_thread.is_alive():
            self._transcribe_thread.join(timeout=1.5)

        self._capture_thread = None
        self._transcribe_thread = None

        if self.on_level:
            try:
                self.on_level(0.0)
            except Exception:
                pass
        self._notify_status("Microfono in pausa.")

    # ================================================================ Capture Loop
    def _capture_loop(self, token: int) -> None:
        blocksize = int(self.SAMPLE_RATE * self.BLOCK_DURATION)
        speech_frames: List[bytes] = []
        silence_blocks = 0
        active_speech_blocks = 0

        ambient_rms = 160.0
        max_blocks = int(self.MAX_SPEECH_DURATION / self.BLOCK_DURATION)
        silence_cut_blocks = int(self.SILENCE_CUTOFF_SEC / self.BLOCK_DURATION)

        try:
            with sd.RawInputStream(
                samplerate=self.SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=blocksize,
                device=self.selected_device_index,
            ) as stream:
                while self.is_listening and token == self._generation_token and not self._stop_event.is_set():
                    data, overflowed = stream.read(blocksize)
                    if self._stop_event.is_set() or token != self._generation_token:
                        break

                    # Calcolo RMS
                    raw_bytes = bytes(data)
                    samples = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32)
                    rms = float(np.sqrt(np.mean(np.square(samples))))

                    # VU Meter
                    if self.on_level:
                        norm = min(1.0, max(0.0, (rms - 60.0) / 3000.0))
                        try:
                            self.on_level(norm)
                        except Exception:
                            pass

                    cur_thresh_pct = getattr(self, "_gate_threshold", 20)
                    dyn_min_rms = 60.0 + (cur_thresh_pct / 100.0) * 1500.0
                    threshold = max(dyn_min_rms, ambient_rms * 1.85)

                    # Streaming Vosk per SFX istantanei (~150-200ms)
                    if self._vosk_recognizer is not None:
                        try:
                            if self._vosk_recognizer.AcceptWaveform(raw_bytes):
                                res = json.loads(self._vosk_recognizer.Result())
                                txt = res.get("text", "").strip()
                                if txt and self.on_partial_transcript:
                                    self.on_partial_transcript(txt)
                            else:
                                partial = json.loads(self._vosk_recognizer.PartialResult())
                                ptxt = partial.get("partial", "").strip()
                                if ptxt and self.on_partial_transcript:
                                    self.on_partial_transcript(ptxt)
                        except Exception:
                            pass

                    # VAD per segmentazione frasi
                    if rms > threshold:
                        speech_frames.append(raw_bytes)
                        active_speech_blocks += 1
                        silence_blocks = 0
                    else:
                        ambient_rms = 0.96 * ambient_rms + 0.04 * rms
                        if active_speech_blocks > 0:
                            speech_frames.append(raw_bytes)
                            silence_blocks += 1

                    # Chiusura frase
                    if active_speech_blocks >= 4 and (
                        silence_blocks >= silence_cut_blocks
                        or active_speech_blocks >= max_blocks
                    ):
                        full_audio = b"".join(speech_frames)
                        speech_frames.clear()
                        active_speech_blocks = 0
                        silence_blocks = 0

                        # Reset Vosk recognizer per la prossima frase
                        if self._vosk_recognizer is not None:
                            try:
                                self._vosk_recognizer.Reset()
                            except Exception:
                                pass

                        # Mette in queue evitando overflow (risolve bug #10)
                        try:
                            self._phrase_queue.put_nowait((token, full_audio))
                        except queue.Full:
                            try:
                                self._phrase_queue.get_nowait()
                                self._phrase_queue.put_nowait((token, full_audio))
                            except Exception:
                                pass

        except Exception as e:
            if token == self._generation_token:
                self.is_listening = False
                self._notify_status(f"⚠️ Errore microfono: {e}")

    # ================================================================ Transcribe Loop
    def _transcribe_loop(self, token: int) -> None:
        while self.is_listening and token == self._generation_token and not self._stop_event.is_set():
            try:
                task_token, audio_bytes = self._phrase_queue.get(timeout=0.3)
            except queue.Empty:
                continue

            if task_token != self._generation_token or self._stop_event.is_set():
                continue

            text = self._transcribe_phrase(audio_bytes)
            if text and text.strip() and task_token == self._generation_token:
                try:
                    self.on_transcript(text.strip())
                except Exception as e:
                    print(f"[VoiceListener] Errore callback on_transcript: {e}")

    def _transcribe_phrase(self, audio_bytes: bytes) -> str:
        """Trascrive un'intera frase usando faster-whisper o Vosk come fallback."""
        if len(audio_bytes) < 3200:  # meno di 0.2s di audio, ignora
            return ""

        # 1. Tentativo Faster-Whisper
        if self._whisper_model is not None:
            try:
                pcm_float = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
                segments, _info = self._whisper_model.transcribe(
                    pcm_float,
                    language="it",
                    beam_size=1,
                    best_of=1,
                    temperature=0.0,
                    vad_filter=True,
                )
                txt = " ".join(s.text.strip() for s in segments if s.text).strip()
                if txt:
                    return txt
            except Exception as e:
                print(f"[VoiceListener] Errore trascrizione Whisper: {e}")

        # 2. Fallback Vosk su intera frase
        if self._vosk_model is not None:
            try:
                import vosk
                rec = vosk.KaldiRecognizer(self._vosk_model, self.SAMPLE_RATE)
                rec.AcceptWaveform(audio_bytes)
                res = json.loads(rec.FinalResult())
                txt = res.get("text", "").strip()
                if txt:
                    return txt
            except Exception as e:
                print(f"[VoiceListener] Errore trascrizione Vosk fallback: {e}")

        return ""
