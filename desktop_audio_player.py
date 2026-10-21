"""
Motore Audio Nativo Desktop con Doppio Player VLC, Crossfade S-Curve a 50Hz e Audio Ducking per SFX.
Caratteristiche:
- Volumi indipendenti garantiti da `--aout=directsound` su Windows.
- Pre-buffering silenzioso della nuova traccia mentre la precedente continua a suonare.
- Dissolvenza incrociata Coseno S-Curve a 50 aggiornamenti al secondo.
- Pre-caricamento posticipato DOPO la fine del crossfade (zero contesa GIL/CPU o rete durante la transizione).
- Audio Ducking automatico quando suona un Effetto Sonoro (SFX), per far risaltare ogni effetto sopra la musica.
"""

import math
import threading
import time
from typing import Dict, Any, List, Optional, Callable

import vlc_runtime  # noqa: F401
import vlc

from ytmusic_service import YTMusicService


class DesktopAudioPlayer:
    def __init__(
        self,
        ytm_service: YTMusicService,
        on_track_change: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_state_change: Optional[Callable[[bool, str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.ytm = ytm_service
        self.on_track_change = on_track_change
        self.on_state_change = on_state_change
        self.on_error = on_error

        vlc_args = [
            "--no-video",
            "--vout=none",
            "--aout=directsound",
            "--intf=dummy",
            "--no-stats",
            "--no-sub-autodetect-file",
            "--network-caching=1200",
            "--quiet",
        ]
        self.vlc_instance = vlc.Instance(*vlc_args)
        self.players = {
            "A": self.vlc_instance.media_player_new(),
            "B": self.vlc_instance.media_player_new(),
        }
        # Volume "logico" e guadagno inviluppo crossfade (0..1) per ciascuno slot
        self.slot_volumes: Dict[str, float] = {"A": 0.0, "B": 0.0}
        self.slot_gains: Dict[str, float] = {"A": 0.0, "B": 0.0}
        self.active_slot = "A"

        self.queue: List[Dict[str, Any]] = []
        self.current_index: int = -1
        self.is_playing: bool = False
        self.is_crossfading: bool = False

        self.master_volume: int = 75
        self.crossfade_seconds: float = 4.0

        # Audio Ducking morbido e musicale per amalgamare gli SFX con la musica
        self._duck_factor: float = 1.0
        self._duck_until: float = 0.0
        self._duck_token: int = 0

        self._fade_token = 0
        self._load_token = 0
        self._auto_next_triggered_for_index = -1
        self._running = True

        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def shutdown(self) -> None:
        self._running = False
        self._fade_token += 1
        self._duck_token += 1
        try:
            self.players["A"].stop()
            self.players["B"].stop()
        except Exception:
            pass

    def duck_for_sfx(self, duration_sec: float = 1.6, sfx_volume: int = 80) -> None:
        """
        Attenua delicatamente la musica di sottofondo (con discesa morbida di 110ms e risalita
        cosinusoidale di 550ms) in proporzione al volume degli effetti sonori:
        - A volume SFX 100%, la musica scende solo al 78% (-2.1 dB), senza mai "sparire" o creare vuoti innaturali.
        - A volume SFX 50%, la musica scende appena al 92%.
        - Sotto il 10% di volume SFX, nessun ducking.
        """
        vol_clamped = max(0, min(100, int(sfx_volume)))
        if vol_clamped <= 10:
            return

        # Profondità di ducking proporzionale al volume SFX (max 22% di attenuazione a SFX=100%)
        duck_depth = 0.22 * ((vol_clamped / 100.0) ** 1.45)
        target_duck = max(0.76, 1.0 - duck_depth)

        now = time.time()
        hold_time = max(0.40, min(2.0, float(duration_sec) * 0.58))
        self._duck_until = max(self._duck_until, now + hold_time)
        self._duck_token += 1
        my_token = self._duck_token

        def duck_and_restore_worker() -> None:
            # 1. Discesa morbida (110ms) invece di taglio netto istantaneo
            down_steps = 6
            start_down = self._duck_factor
            goal_down = min(start_down, target_duck)
            if start_down - goal_down > 0.01:
                for s in range(1, down_steps + 1):
                    if not self._running or my_token != self._duck_token:
                        return
                    ratio = s / down_steps
                    self._duck_factor = start_down - (start_down - goal_down) * (0.5 * (1.0 - math.cos(ratio * math.pi)))
                    self._apply_hardware_volumes()
                    time.sleep(0.018)
            else:
                self._duck_factor = goal_down
                self._apply_hardware_volumes()

            # 2. Mantenimento durante il corpo centrale dell'effetto
            while self._running and my_token == self._duck_token:
                rem = self._duck_until - time.time()
                if rem <= 0:
                    break
                time.sleep(min(0.04, max(0.01, rem)))

            if not self._running or my_token != self._duck_token:
                return

            # 3. Risalita morbida in 0.55s (22 step da 25ms) durante la coda di riverbero dell'effetto
            steps = 22
            start_f = self._duck_factor
            for s in range(1, steps + 1):
                if not self._running or my_token != self._duck_token:
                    return
                ratio = s / steps
                self._duck_factor = start_f + (1.0 - start_f) * (0.5 * (1.0 - math.cos(ratio * math.pi)))
                self._apply_hardware_volumes()
                time.sleep(0.025)

            self._duck_factor = 1.0
            self._apply_hardware_volumes()

        threading.Thread(target=duck_and_restore_worker, daemon=True).start()

    @staticmethod
    def _perceptual_music_vol(master_vol: int) -> float:
        """Curva di volume percettiva per lo slider della musica (0..100 -> 0..100)."""
        v = max(0, min(100, int(master_vol)))
        if v <= 0:
            return 0.0
        return float(((v / 100.0) ** 1.35) * 100.0)

    def _apply_hardware_volumes(self) -> None:
        base_master = self._perceptual_music_vol(self.master_volume)
        for slot in ("A", "B"):
            gain = self.slot_gains.get(slot, 0.0)
            logical_vol = base_master * gain
            self.slot_volumes[slot] = logical_vol
            hw_vol = max(0, min(100, int(round(logical_vol * self._duck_factor))))
            try:
                self.players[slot].audio_set_volume(hw_vol)
            except Exception:
                pass

    def _set_slot_gain(self, slot: str, gain: float) -> None:
        g = max(0.0, min(1.0, float(gain)))
        self.slot_gains[slot] = g
        base_master = self._perceptual_music_vol(self.master_volume)
        logical_vol = base_master * g
        self.slot_volumes[slot] = logical_vol
        hw_vol = max(0, min(100, int(round(logical_vol * self._duck_factor))))
        try:
            self.players[slot].audio_set_volume(hw_vol)
        except Exception:
            pass

    def _set_slot_volume(self, slot: str, vol: float) -> None:
        clamped = max(0.0, min(100.0, float(vol)))
        ref = float(self.master_volume) if self.master_volume > 0 else 100.0
        gain = max(0.0, min(1.0, clamped / ref)) if clamped > 0 else 0.0
        self._set_slot_gain(slot, gain)

    def set_queue_and_play(self, tracks: List[Dict[str, Any]], start_index: int = 0) -> None:
        if not tracks:
            return
        self.queue = list(tracks)
        self.current_index = max(0, min(start_index, len(self.queue) - 1))
        self._auto_next_triggered_for_index = -1
        self.play_track_at(self.current_index)

    def play_track_at(self, index: int) -> None:
        if not self.queue or index < 0 or index >= len(self.queue):
            return
        self.current_index = index
        self._auto_next_triggered_for_index = -1
        track = self.queue[index]

        if self.on_track_change:
            self.on_track_change(track)

        self._load_token += 1
        current_token = self._load_token

        threading.Thread(
            target=self._resolve_and_start_worker,
            args=(track, current_token),
            daemon=True,
        ).start()

    def _resolve_and_start_worker(self, track: Dict[str, Any], token: int) -> None:
        video_id = track.get("videoId")
        if not video_id:
            return

        try:
            if self.on_state_change:
                self.on_state_change(
                    self.is_playing,
                    f"Caricamento: {track.get('title', '')[:26]}...",
                )

            stream_data = self.ytm.get_direct_audio_url(video_id)
            if token != self._load_token:
                return

            stream_url = stream_data.get("stream_url")
            if not stream_url:
                raise ValueError("URL audio non trovato")

            self._start_smooth_crossfade(stream_url, token)

        except Exception as e:
            if self.on_error:
                self.on_error(f"Impossibile riprodurre '{track.get('title')}': {e}")
            if len(self.queue) > 1 and token == self._load_token:
                time.sleep(0.4)
                self.next_track()

    def _prefetch_next_after_fade(self, token: int) -> None:
        """
        Pre-carica il solo brano successivo DOPO il completamento del crossfade,
        così non c'è mai contesa di rete o GIL durante l'avvio/dissolvenza del brano.
        """
        if token != self._load_token or len(self.queue) <= 1:
            return
        nxt_idx = (self.current_index + 1) % len(self.queue)
        nxt_vid = self.queue[nxt_idx].get("videoId")
        if nxt_vid:
            try:
                self.ytm.get_direct_audio_url(nxt_vid)
            except Exception:
                pass

    def _notify_state(self, is_playing: bool, text: str) -> None:
        if self.on_state_change:
            try:
                self.on_state_change(is_playing, text)
            except Exception:
                pass

    def _start_smooth_crossfade(self, stream_url: str, load_token: int) -> None:
        prev_slot = self.active_slot
        next_slot = "B" if prev_slot == "A" else "A"

        outgoing = self.players[prev_slot]
        incoming = self.players[next_slot]

        self.active_slot = next_slot
        self._fade_token += 1
        my_fade_token = self._fade_token

        was_outgoing_playing = outgoing.is_playing() == 1
        start_out_gain = self.slot_gains.get(prev_slot, 1.0)
        if was_outgoing_playing and start_out_gain <= 0.05:
            start_out_gain = 1.0

        media = self.vlc_instance.media_new(stream_url)
        incoming.set_media(media)
        self._set_slot_gain(next_slot, 0.0)
        incoming.play()

        def crossfade_worker() -> None:
            wait_start = time.time()
            while time.time() - wait_start < 4.0:
                if my_fade_token != self._fade_token:
                    return
                try:
                    incoming.audio_set_volume(0)
                    if incoming.is_playing() == 1 and incoming.get_time() > 40:
                        break
                except Exception:
                    pass
                time.sleep(0.02)

            if my_fade_token != self._fade_token:
                return

            fade_sec = float(self.crossfade_seconds)

            if not was_outgoing_playing or fade_sec <= 0.1:
                quick_fade = min(3.0, max(2.0, fade_sec)) if not was_outgoing_playing and fade_sec > 0 else 0.0
                if quick_fade > 0:
                    self.is_playing = True
                    self.is_crossfading = True
                    self._notify_state(True, "Dissolvenza in entrata...")
                    steps = int(quick_fade * 50)
                    dt = quick_fade / steps
                    for s in range(1, steps + 1):
                        if my_fade_token != self._fade_token:
                            return
                        ratio = s / steps
                        gain = 0.5 * (1.0 - math.cos(ratio * math.pi))
                        self._set_slot_gain(next_slot, gain)
                        time.sleep(dt)
                else:
                    self._set_slot_gain(next_slot, 1.0)

                try:
                    outgoing.stop()
                except Exception:
                    pass
                self._set_slot_gain(prev_slot, 0.0)
                self.is_playing = True
                self.is_crossfading = False
                self._notify_state(True, "In riproduzione")
                self._prefetch_next_after_fade(load_token)
                return

            self.is_playing = True
            self.is_crossfading = True
            self._notify_state(True, "Dissolvenza incrociata...")

            fps = 50
            total_steps = max(15, int(fade_sec * fps))
            step_delay = fade_sec / total_steps

            for step in range(1, total_steps + 1):
                if my_fade_token != self._fade_token:
                    return

                ratio = step / total_steps
                in_gain = 0.5 * (1.0 - math.cos(ratio * math.pi))
                out_gain = 0.5 * (1.0 + math.cos(ratio * math.pi))

                self._set_slot_gain(next_slot, in_gain)
                self._set_slot_gain(prev_slot, start_out_gain * out_gain)
                time.sleep(step_delay)

            if my_fade_token == self._fade_token:
                self._set_slot_gain(prev_slot, 0.0)
                try:
                    outgoing.stop()
                except Exception:
                    pass
                self._set_slot_gain(next_slot, 1.0)
                self.is_crossfading = False
                self._notify_state(True, "In riproduzione")
                self._prefetch_next_after_fade(load_token)

        threading.Thread(target=crossfade_worker, daemon=True).start()

    def pause(self) -> None:
        player = self.players[self.active_slot]
        if player.is_playing() == 1:
            player.pause()
            self.is_playing = False
            self._notify_state(False, "In pausa")

    def resume(self) -> None:
        player = self.players[self.active_slot]
        if not self.is_playing and self.queue:
            player.play()
            self._set_slot_gain(self.active_slot, 1.0)
            self.is_playing = True
            self._notify_state(True, "In riproduzione")

    def toggle_play_pause(self) -> None:
        if self.is_playing:
            self.pause()
        else:
            self.resume()

    def next_track(self) -> None:
        if not self.queue:
            return
        nxt = (self.current_index + 1) % len(self.queue)
        self.play_track_at(nxt)

    def prev_track(self) -> None:
        if not self.queue:
            return
        prv = (self.current_index - 1) % len(self.queue)
        self.play_track_at(prv)

    def set_volume(self, volume: int) -> None:
        self.master_volume = max(0, min(100, int(volume)))
        if not self.is_crossfading and self.is_playing:
            self.slot_gains[self.active_slot] = 1.0
        self._apply_hardware_volumes()

    def set_position_pct(self, pct: float) -> None:
        player = self.players[self.active_slot]
        try:
            player.set_position(max(0.0, min(0.99, float(pct))))
        except Exception:
            pass

    def get_progress(self) -> Dict[str, Any]:
        player = self.players[self.active_slot]
        try:
            cur_ms = max(0, player.get_time())
            dur_ms = max(0, player.get_length())
            pct = (cur_ms / dur_ms) if dur_ms > 0 else 0.0
            return {
                "current": int(cur_ms / 1000),
                "duration": int(dur_ms / 1000),
                "pct": max(0.0, min(1.0, pct)),
            }
        except Exception:
            return {"current": 0, "duration": 0, "pct": 0.0}

    def _monitor_loop(self) -> None:
        while self._running:
            time.sleep(0.4)
            if not self.is_playing or self.is_crossfading or not self.queue:
                continue
            try:
                p = self.players[self.active_slot]
                state = p.get_state()

                if state in (vlc.State.Ended, vlc.State.Error):
                    if self._auto_next_triggered_for_index != self.current_index:
                        self._auto_next_triggered_for_index = self.current_index
                        self.next_track()
                    continue

                dur_ms = p.get_length()
                cur_ms = p.get_time()
                if dur_ms > 15000 and cur_ms > 5000:
                    rem_sec = (dur_ms - cur_ms) / 1000.0
                    trigger_window = max(2.0, float(self.crossfade_seconds) + 0.8)
                    if 0.2 < rem_sec <= trigger_window:
                        if self._auto_next_triggered_for_index != self.current_index:
                            self._auto_next_triggered_for_index = self.current_index
                            self.next_track()
            except Exception:
                pass
