"""
Director — il "Regista" di Bardo AI: UNICO punto che decide quando cambiare atmosfera.
Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

from __future__ import annotations

import threading

__author__ = "Paolo Basta"
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional

URGENT_TONES = {"fast_combat", "epic_boss"}
URGENT_MOOD_IDS = {"combattimento", "boss", "terrore", "fuga", "sparatoria", "inseguimento_poliziesco"}


@dataclass
class SceneDecision:
    """Decisione emessa dal Director quando la scena deve effettivamente cambiare."""

    generation: int
    mood_id: str
    env_data: Optional[Dict[str, Any]] = None
    custom_query: str = ""
    reason: str = ""
    matched_by: str = ""

    @property
    def custom_search_query(self) -> str:
        return self.custom_query



@dataclass
class _Signal:
    ts: float
    key: str  # "mood_id|env_id"
    mood_id: str
    weight: float
    result: Dict[str, Any] = field(default_factory=dict)


class Director:
    def __init__(
        self,
        on_scene_change: Optional[Callable[[SceneDecision], None]] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._lock = threading.RLock()
        self._clock = clock
        self.on_scene_change = on_scene_change

        self.current_mood_id: Optional[str] = None
        self.current_env_id: Optional[str] = None
        self.generation: int = 0
        self.locked: bool = False

        self.cooldown_seconds: float = 18.0
        self.min_scene_duration: float = 8.0
        self.hysteresis_window: float = 25.0
        self.calm_required_weight: float = 2.0  # quanti "segnali forti" servono per tornare alla calma

        self._scene_started_at: float = -1e9
        self._cooldown_until: float = -1e9
        self._signals: Deque[_Signal] = deque(maxlen=32)

    # ------------------------------------------------------------------ config
    def configure(self, analyzer_cfg: Dict[str, Any]) -> None:
        with self._lock:
            self.cooldown_seconds = float(analyzer_cfg.get("cooldown_seconds", 18) or 0)
            self.min_scene_duration = float(analyzer_cfg.get("min_scene_duration_seconds", 8.0) or 0)
            self.hysteresis_window = float(analyzer_cfg.get("hysteresis_window_seconds", 25.0) or 1)

    def set_locked(self, locked: bool) -> None:
        with self._lock:
            self.locked = bool(locked)

    def reset(self) -> None:
        """Usato al cambio profilo: azzera stato e invalida le ricerche in corso."""
        with self._lock:
            self.current_mood_id = None
            self.current_env_id = None
            self._signals.clear()
            self.generation += 1

    def is_current(self, generation: int) -> bool:
        with self._lock:
            return generation == self.generation

    def cooldown_remaining(self) -> float:
        with self._lock:
            return max(0.0, self._cooldown_until - self._clock())

    # ----------------------------------------------------------------- core
    @staticmethod
    def _is_urgent(mood: Optional[Dict[str, Any]], mood_id: str, result: Dict[str, Any]) -> bool:
        if result.get("danger_level") in ("combat_danger", "catastrophic"):
            return True
        if mood_id in URGENT_MOOD_IDS:
            return True
        return bool(mood and mood.get("tone_profile") in URGENT_TONES)

    def manual_select(self, mood_id: str, env_data: Optional[Dict[str, Any]] = None, custom_query: str = "") -> SceneDecision:
        """Scelta manuale dalla UI: sempre immediata, ignora lock e cooldown."""
        with self._lock:
            return self._commit(mood_id, env_data, custom_query, reason="Manuale", matched_by="manual")

    def submit(self, result: Dict[str, Any], moods: Dict[str, Any]) -> Optional[SceneDecision]:
        """
        Riceve il risultato dell'analyzer e decide se cambiare scena.
        Ritorna la SceneDecision (e chiama on_scene_change) solo se la scena cambia davvero.
        """
        mood_id = result.get("mood_id")
        if not mood_id or mood_id not in moods:
            return None
        mood = moods.get(mood_id)
        env_id = result.get("env_id")
        matched_by = str(result.get("matched_by") or "")
        is_command = matched_by == "command"
        now = self._clock()

        with self._lock:
            # Comandi vocali espliciti: immediati anche con musica bloccata
            if is_command:
                return self._commit(mood_id, result if env_id else None, result.get("custom_search_query", ""),
                                    reason="Comando vocale", matched_by=matched_by)

            if self.locked:
                return None

            same_scene = mood_id == self.current_mood_id and (env_id or None) == self.current_env_id
            if same_scene:
                # Rinforza la scena corrente: i segnali opposti accumulati perdono valore
                self._signals.clear()
                return None

            urgent = self._is_urgent(mood, mood_id, result)
            current_urgent = self.current_mood_id in URGENT_MOOD_IDS

            # 1. Pericolo: scatta subito (nessun cooldown, nessuna isteresi)
            if urgent and not current_urgent:
                return self._commit(mood_id, result if env_id else None, result.get("custom_search_query", ""),
                                    reason="Pericolo immediato", matched_by=matched_by)

            # 2. Prima scena della sessione: parte subito
            if self.current_mood_id is None:
                return self._commit(mood_id, result if env_id else None, result.get("custom_search_query", ""),
                                    reason="Prima scena", matched_by=matched_by)

            # 3. Durata minima della scena attuale
            if now - self._scene_started_at < self.min_scene_duration:
                self._push_signal(now, mood_id, env_id, result)
                return None

            # 4. Accumulo dei segnali coerenti nella finestra di isteresi
            weight = self._push_signal(now, mood_id, env_id, result)
            strong_env_switch = bool(env_id) and env_id != self.current_env_id and float(result.get("confidence", 0)) >= 9.0
            # Uscire da una scena urgente verso la calma richiede più conferme
            required = self.calm_required_weight * (1.5 if current_urgent else 1.0)
            if result.get("force_change") and not current_urgent:
                required = min(required, 1.0)

            if not strong_env_switch and weight < required:
                return None

            # 5. Cooldown tra cambi automatici (gli ambienti espliciti e forti lo bypassano)
            if not strong_env_switch and now < self._cooldown_until:
                return None

            return self._commit(mood_id, result if env_id else None, result.get("custom_search_query", ""),
                                reason=f"Segnali coerenti ({weight:.1f})", matched_by=matched_by)

    # -------------------------------------------------------------- helpers
    def _push_signal(self, now: float, mood_id: str, env_id: Optional[str], result: Dict[str, Any]) -> float:
        key = f"{mood_id}|{env_id or ''}"
        conf = float(result.get("confidence", 0) or 0)
        # Peso normalizzato: un match forte (frase o bioma) vale ~1, una sola keyword ~0.5
        w = max(0.3, min(1.5, conf / 5.0))
        if result.get("force_change"):
            w = max(w, 1.0)
        self._signals.append(_Signal(now, key, mood_id, w, result))
        cutoff = now - self.hysteresis_window
        return sum(s.weight for s in self._signals if s.key == key and s.ts >= cutoff)

    def _commit(self, mood_id: str, env_data: Optional[Dict[str, Any]], custom_query: str,
                reason: str, matched_by: str) -> SceneDecision:
        now = self._clock()
        self.current_mood_id = mood_id
        self.current_env_id = (env_data or {}).get("env_id")
        self.generation += 1
        self._scene_started_at = now
        if self.cooldown_seconds > 0:
            self._cooldown_until = now + self.cooldown_seconds
        self._signals.clear()
        decision = SceneDecision(
            generation=self.generation,
            mood_id=mood_id,
            env_data=env_data,
            custom_query=custom_query or "",
            reason=reason,
            matched_by=matched_by,
        )
        cb = self.on_scene_change
        if cb:
            cb(decision)
        return decision

    def recent_signals(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [{"key": s.key, "weight": s.weight, "age": self._clock() - s.ts} for s in self._signals]
