"""
Modulo di ascolto vocale nativo continuo in Italiano per l'applicazione Desktop (.exe).
Usa `sounddevice` per catturare l'audio dal microfono di Windows (con indicatore di livello in tempo reale)
e `SpeechRecognition` per la trascrizione continua in italiano (it-IT).
"""

import queue
import threading
import time
from typing import Callable, List, Dict, Any, Optional

import numpy as np
import sounddevice as sd
import speech_recognition as sr


class ContinuousVoiceListener:
    SAMPLE_RATE = 16000
    BLOCK_DURATION = 0.15  # 150ms per blocco

    def __init__(
        self,
        on_transcript: Callable[[str], None],
        on_status: Optional[Callable[[str], None]] = None,
        on_level: Optional[Callable[[float], None]] = None,
    ) -> None:
        self.on_transcript = on_transcript
        self.on_status = on_status
        self.on_level = on_level

        self.recognizer = sr.Recognizer()
        self.is_listening = False
        self.selected_device_index: Optional[int] = None

        self._audio_queue: "queue.Queue[sr.AudioData]" = queue.Queue()
        self._capture_thread: Optional[threading.Thread] = None
        self._worker_thread: Optional[threading.Thread] = None

    @staticmethod
    def get_input_devices() -> List[Dict[str, Any]]:
        """
        Restituisce l'elenco dei microfoni disponibili su Windows.
        """
        devices_out: List[Dict[str, Any]] = [
            {"index": None, "name": "🎙️ Microfono Predefinito di Windows"}
        ]
        seen_names = set()
        try:
            all_devs = sd.query_devices()
            for idx, dev in enumerate(all_devs):
                if dev.get("max_input_channels", 0) > 0:
                    name = dev.get("name", f"Dispositivo {idx}").strip()
                    # Evita duplicati dovuti ai vari host API di Windows (MME, DirectSound, WASAPI)
                    if name not in seen_names and "Mapper" not in name:
                        seen_names.add(name)
                        devices_out.append({"index": idx, "name": f"🎙️ {name}"})
        except Exception as e:
            print(f"[VoiceListener] Errore lettura dispositivi audio: {e}")
        return devices_out

    def set_device(self, device_index: Optional[int]) -> None:
        was_running = self.is_listening
        if was_running:
            self.stop()
        self.selected_device_index = device_index
        if was_running:
            self.start()

    def start(self) -> None:
        if self.is_listening:
            return
        self.is_listening = True
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._worker_thread = threading.Thread(target=self._transcribe_loop, daemon=True)
        self._capture_thread.start()
        self._worker_thread.start()
        if self.on_status:
            self.on_status("🎙️ In ascolto continuo in italiano... Parla liberamente!")

    def stop(self) -> None:
        self.is_listening = False
        if self.on_level:
            self.on_level(0.0)
        if self.on_status:
            self.on_status("Microfono in pausa.")

    def _capture_loop(self) -> None:
        blocksize = int(self.SAMPLE_RATE * self.BLOCK_DURATION)
        speech_frames: List[bytes] = []
        silence_blocks = 0
        active_speech_blocks = 0

        # Soglia RMS adattiva per distinguere voce dal rumore di fondo
        ambient_rms = 180.0
        min_voice_rms = 280.0
        max_phrase_blocks = int(5.2 / self.BLOCK_DURATION)  # invia ogni ~5s anche se si parla senza sosta
        silence_blocks_to_cut = int(0.85 / self.BLOCK_DURATION)  # ~0.85s di pausa chiude la frase

        try:
            with sd.InputStream(
                samplerate=self.SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=blocksize,
                device=self.selected_device_index,
            ) as stream:
                while self.is_listening:
                    data, _ = stream.read(blocksize)
                    if not self.is_listening:
                        break

                    # Calcola volume RMS del blocco corrente
                    float_data = data.astype(np.float32)
                    rms = float(np.sqrt(np.mean(np.square(float_data))))

                    # Invia livello normalizzato (0.0 - 1.0) alla GUI
                    if self.on_level:
                        norm_lvl = min(1.0, max(0.0, (rms - 80.0) / 3200.0))
                        self.on_level(norm_lvl)

                    threshold = max(min_voice_rms, ambient_rms * 1.9)

                    if rms > threshold:
                        speech_frames.append(data.tobytes())
                        active_speech_blocks += 1
                        silence_blocks = 0
                    else:
                        # Aggiorna lentamente la stima del rumore ambientale
                        ambient_rms = 0.96 * ambient_rms + 0.04 * rms
                        if active_speech_blocks > 0:
                            speech_frames.append(data.tobytes())
                            silence_blocks += 1

                    # Se abbiamo parlato e c'è una breve pausa (o frase lunga), invia alla trascrizione
                    if active_speech_blocks >= 3 and (
                        silence_blocks >= silence_blocks_to_cut
                        or active_speech_blocks >= max_phrase_blocks
                    ):
                        raw_bytes = b"".join(speech_frames)
                        audio_data = sr.AudioData(raw_bytes, self.SAMPLE_RATE, 2)
                        self._audio_queue.put(audio_data)
                        speech_frames.clear()
                        active_speech_blocks = 0
                        silence_blocks = 0

        except Exception as e:
            self.is_listening = False
            if self.on_status:
                self.on_status(f"⚠️ Errore microfono: {e}")

    def _transcribe_loop(self) -> None:
        while self.is_listening:
            try:
                audio_data = self._audio_queue.get(timeout=0.4)
            except queue.Empty:
                continue

            try:
                if self.on_status:
                    self.on_status("⏳ Elaborazione frase in italiano...")
                text = self.recognizer.recognize_google(audio_data, language="it-IT")
                if text and text.strip():
                    self.on_transcript(text.strip())
                if self.is_listening and self.on_status:
                    self.on_status("🎙️ In ascolto continuo in italiano... Parla liberamente!")
            except sr.UnknownValueError:
                # Audio non comprensibile o semplice rumore
                if self.is_listening and self.on_status:
                    self.on_status("🎙️ In ascolto continuo in italiano... Parla liberamente!")
            except sr.RequestError as e:
                if self.on_status:
                    self.on_status(f"⚠️ Errore rete riconoscimento vocale: {e}")
            except Exception as e:
                print(f"[VoiceListener] Errore trascrizione: {e}")
