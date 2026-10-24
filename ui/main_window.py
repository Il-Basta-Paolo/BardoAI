"""
Finestra Principale di Bardo AI v2.6.1 (MainWindow) in PySide6.
Collega l'interfaccia grafica modulare con il Director, l'AudioEngine,
il MusicService, il ContinuousVoiceListener e l'SFXManager.
Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any, Dict

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from analyzer import SceneAnalyzer
from audio_engine import AudioEngine, MusicSource
from config_defaults import list_available_profiles
from director import Director, SceneDecision
from music_service import MusicService
from sfx_manager import SFXManager
from storage import ConfigManager
from ui.dialogs.settings_dialog import SettingsDialog
from ui.styles import DARK_THEME_QSS
from ui.widgets.mood_grid import MoodGridWidget
from ui.widgets.soundboard import SoundboardWidget
from ui.widgets.transport import TransportBar
from ui.widgets.voice_monitor import VoiceMonitorWidget
from voice_listener import ContinuousVoiceListener
from ytdlp_manager import YtDlpManager


class EventBridge(QObject):
    """Bridge per emettere segnali Qt da thread di worker in modo sicuro."""
    sig_transcript = Signal(str, bool)
    sig_level = Signal(float)
    sig_status = Signal(str)
    sig_scene_changed = Signal(object)
    sig_track_started = Signal(str, str)
    sig_error = Signal(str)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Bardo AI v2.6.1 — Regia Musicale Intelligente & Soundboard GdR")
        self.resize(1120, 800)
        self.setMinimumSize(960, 680)

        # Icona
        for cand in [
            Path(getattr(sys, "_MEIPASS", "")) / "bardo_icon.ico",
            Path(__file__).resolve().parent.parent / "bardo_icon.ico",
            Path(sys.executable).parent / "bardo_icon.ico",
        ]:
            if cand.is_file():
                self.setWindowIcon(QIcon(str(cand)))
                break

        self.setStyleSheet(DARK_THEME_QSS)

        # 1. Carica configurazione
        self.config = ConfigManager.load()
        self.bridge = EventBridge()

        # 2. Inizializza Motori Core
        self._init_core_engines()

        # 3. Costruisce l'interfaccia
        self._build_ui()

        # 4. Collega Segnali e Timer
        self._connect_signals()

        # 5. Timer di aggiornamento cooldown (10 Hz)
        self.cooldown_timer = QTimer(self)
        self.cooldown_timer.timeout.connect(self._update_cooldown_badge)
        self.cooldown_timer.start(100)

        # 6. Avvia microfono e imposta primo profilo
        self._apply_profile(self.active_profile_id)
        self.voice_listener.start()

    def _init_core_engines(self) -> None:
        # Audio Engine (Sounddevice + PyAV)
        self.audio_engine = AudioEngine()
        music_vol = int(self.config.get("audio", {}).get("music_volume", 75))
        sfx_vol = int(self.config.get("audio", {}).get("sfx_volume", 80))
        self.audio_engine.set_music_volume(music_vol)
        self.audio_engine.set_sfx_volume(sfx_vol)

        # YtDlp e Music Service
        self.ytdlp_mgr = YtDlpManager()
        self.music_service = MusicService(self.ytdlp_mgr)

        # SFX Manager
        self.sfx_manager = SFXManager(
            audio_engine=self.audio_engine,
            on_sfx_triggered=self._on_sfx_triggered,
        )

        # Scene Analyzer e Director
        self.analyzer = SceneAnalyzer()
        self.director = Director(
            on_scene_change=self._on_director_scene_change,
        )
        self.director.configure(self.config.get("analyzer", {}))

        # Profilo attivo
        self.active_profile_id = self.config.get("active_profile_id", "fantasy_dnd")

        # Voice Listener
        self.voice_listener = ContinuousVoiceListener(
            on_transcript=self._on_voice_final_transcript,
            on_partial_transcript=self._on_voice_partial_transcript,
            on_status=lambda s: self.bridge.sig_status.emit(s),
            on_level=lambda lvl: self.bridge.sig_level.emit(lvl),
        )

    # ================================================================ UI Layout
    def _build_ui(self) -> None:
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(14, 12, 14, 12)
        root_layout.setSpacing(10)

        # 1. Barra Superiore (Header)
        top_bar = QHBoxLayout()
        top_bar.setSpacing(12)

        lbl_app = QLabel("BARDO AI")
        lbl_app.setObjectName("headerTitle")
        lbl_v2 = QLabel("v2.6.1")
        lbl_v2.setStyleSheet("font-size: 11px; background-color: #3b82f6; color: white; padding: 2px 6px; border-radius: 4px; font-weight: bold;")
        top_bar.addWidget(lbl_app)
        top_bar.addWidget(lbl_v2)
        top_bar.addSpacing(16)

        # Selettore Profilo (4 Profili)
        top_bar.addWidget(QLabel("PROFILO GDR:"))
        self.combo_profile = QComboBox()
        profiles = list_available_profiles(self.config)
        for p in profiles:
            self.combo_profile.addItem(f"{p.get('icon', '🎭')} {p.get('name', p['id'])}", p["id"])

        # Sincronizza l'indice iniziale del selettore con il profilo attivo salvato
        init_idx = self.combo_profile.findData(self.active_profile_id)
        if init_idx >= 0:
            self.combo_profile.setCurrentIndex(init_idx)

        top_bar.addWidget(self.combo_profile)
        top_bar.addStretch()

        # Pulsante Impostazioni
        btn_settings = QPushButton("⚙️ Impostazioni")
        btn_settings.clicked.connect(self._open_settings)
        top_bar.addWidget(btn_settings)

        root_layout.addLayout(top_bar)

        # 2. Area Centrale (Splitter: Atmosfere in alto, Soundboard in basso)
        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)

        # Sezione Atmosfere (Moods)
        mood_container = QWidget()
        mood_layout = QVBoxLayout(mood_container)
        mood_layout.setContentsMargins(0, 0, 0, 0)
        mood_layout.setSpacing(6)
        lbl_mood_hdr = QLabel("ATMOSFERE MUSICALI DELLA SCENA")
        lbl_mood_hdr.setObjectName("sectionTitle")
        mood_layout.addWidget(lbl_mood_hdr)
        self.mood_grid = MoodGridWidget()
        mood_layout.addWidget(self.mood_grid)
        splitter.addWidget(mood_container)

        # Sezione Soundboard
        sfx_container = QWidget()
        sfx_layout = QVBoxLayout(sfx_container)
        sfx_layout.setContentsMargins(0, 0, 0, 0)
        sfx_layout.setSpacing(6)
        self.soundboard = SoundboardWidget()
        self.soundboard.set_library(self.sfx_manager.get_library())
        sfx_layout.addWidget(self.soundboard)
        splitter.addWidget(sfx_container)

        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 4)
        root_layout.addWidget(splitter)

        # 3. Widget Monitoraggio Vocale
        self.voice_monitor = VoiceMonitorWidget()
        self.voice_monitor.populate_devices(ContinuousVoiceListener.get_input_devices())
        root_layout.addWidget(self.voice_monitor)

        # 4. Barra di Trasporto Audio
        self.transport = TransportBar()
        root_layout.addWidget(self.transport)

    # ================================================================ Signal Wiring
    def _connect_signals(self) -> None:
        # Combo Profilo
        self.combo_profile.currentIndexChanged.connect(self._on_profile_combo_changed)

        # Mood Grid
        self.mood_grid.mood_selected.connect(self._on_mood_button_clicked)

        # Soundboard
        self.soundboard.sfx_triggered.connect(lambda sid: self.sfx_manager.play_sfx(sid, reason="Soundboard"))
        self.soundboard.custom_sfx_added.connect(self._on_custom_sfx_added)
        self.soundboard.custom_sfx_deleted.connect(self._on_custom_sfx_deleted)

        # Voice Monitor
        self.voice_monitor.device_changed.connect(self.voice_listener.set_device)
        self.voice_monitor.mic_toggled.connect(self._on_mic_toggle_clicked)

        # Transport Bar
        self.transport.play_pause_clicked.connect(self._on_play_pause)
        self.transport.skip_clicked.connect(self._on_skip_track)
        self.transport.music_volume_changed.connect(self.audio_engine.set_music_volume)
        self.transport.sfx_volume_changed.connect(self.audio_engine.set_sfx_volume)
        self.transport.lock_toggled.connect(self.director.set_locked)

        # Event Bridge (Thread-Safe UI Updates)
        self.bridge.sig_transcript.connect(self.voice_monitor.set_transcript)
        self.bridge.sig_level.connect(self.voice_monitor.set_level)
        self.bridge.sig_status.connect(self.voice_monitor.set_status)
        self.bridge.sig_scene_changed.connect(self._on_ui_scene_changed)
        self.bridge.sig_track_started.connect(self.transport.update_track)

    # ================================================================ Voice & SFX Handlers
    def _on_voice_partial_transcript(self, partial_text: str) -> None:
        """Streaming STT Vosk (~150-200ms): trigger istantaneo per SFX senza attendere la fine frase."""
        self.bridge.sig_transcript.emit(partial_text, True)
        self.sfx_manager.detect_and_play_from_speech(partial_text)

    def _on_voice_final_transcript(self, text: str) -> None:
        """Trascrizione completa frase (Whisper/Vosk): analisi per cambio atmosfera e bioma."""
        self.bridge.sig_transcript.emit(text, False)
        # Esegue l'analisi della scena
        profile = self.config["profiles"].get(self.active_profile_id, {})
        moods = profile.get("moods", {})
        res = self.analyzer.analyze_keywords(text, profile)
        if res.get("mood_id"):
            self.director.submit(res, moods)

    def _on_sfx_triggered(self, sfx_item: Dict[str, Any], reason: str) -> None:
        self.bridge.sig_status.emit(f"💥 SFX: {sfx_item.get('name')} ({reason})")

    # ================================================================ Director & Music Flow
    def _on_director_scene_change(self, decision: SceneDecision) -> None:
        self.bridge.sig_scene_changed.emit(decision)

    def _on_ui_scene_changed(self, decision: SceneDecision) -> None:
        self.mood_grid.set_active_mood(decision.mood_id)
        self.bridge.sig_status.emit(f"🎬 Scena: {decision.mood_id} ({decision.reason})")
        # Avvia la ricerca e riproduzione della traccia in background con il token generato
        threading.Thread(
            target=self._fetch_and_play_track_worker,
            args=(decision.mood_id, decision.generation, decision.custom_search_query),
            daemon=True,
            name=f"track-fetch-{decision.generation}",
        ).start()

    def _fetch_and_play_track_worker(self, mood_id: str, generation: int, custom_query: str = "") -> None:
        """Scarica/recupera la traccia e la invia all'AudioEngine solo se il token è ancora valido (bug #8)."""
        if not self.director.is_current(generation):
            return

        profile = self.config["profiles"].get(self.active_profile_id, {})
        mood_data = profile.get("moods", {}).get(mood_id, {})
        tone = mood_data.get("tone_profile", "soundtrack")

        # Risolve la traccia (cache, YouTube Music o fallback locale)
        track = None
        # 1. Prova seed tracks
        seed_tracks = mood_data.get("seed_tracks", [])
        if seed_tracks:
            import random
            track = random.choice(seed_tracks)

        if not track:
            # 2. Cerca tramite query
            queries = mood_data.get("queries", [f"{mood_id} soundtrack instrumental"])
            query = custom_query or queries[0]
            tracks = self.music_service.search_tracks(query, limit=5, tone_profile=tone)
            if tracks:
                track = tracks[0]

        if not self.director.is_current(generation) or not track:
            return

        resolved = self.music_service.resolve_playable(track, tone_profile=tone)
        if not self.director.is_current(generation):
            return

        audio_url = resolved.get("audio_url")
        if not audio_url:
            return

        title = resolved.get("title", "Traccia")
        artist = resolved.get("artist", "")
        duration = float(resolved.get("duration", 180))

        source = MusicSource(
            url=audio_url,
            title=title,
            artist=artist,
            duration=duration,
        )
        crossfade = float(self.config.get("audio", {}).get("crossfade_seconds", 4.0))
        self.audio_engine.play(source, crossfade_seconds=crossfade)
        self.bridge.sig_track_started.emit(title, artist)

    # ================================================================ Transport Controls
    def _on_mood_button_clicked(self, mood_id: str) -> None:
        self.director.manual_select(mood_id)

    def _on_play_pause(self) -> None:
        new_state = not self.audio_engine.paused
        self.audio_engine.set_paused(new_state)
        self.transport.set_playing_state(not new_state)

    def _on_skip_track(self) -> None:
        if self.director.current_mood_id:
            self.director.manual_select(self.director.current_mood_id)

    def _on_mic_toggle_clicked(self, active: bool) -> None:
        if active:
            self.voice_listener.start()
        else:
            self.voice_listener.stop()

    def _update_cooldown_badge(self) -> None:
        rem = self.director.cooldown_remaining()
        self.transport.update_cooldown(rem)

    # ================================================================ Profile & Settings
    def _on_profile_combo_changed(self, index: int) -> None:
        pid = self.combo_profile.itemData(index)
        if pid and pid != self.active_profile_id:
            self._apply_profile(pid)

    def _apply_profile(self, profile_id: str) -> None:
        self.active_profile_id = profile_id
        self.config["active_profile_id"] = profile_id
        ConfigManager.save(self.config)

        # Sincronizza il selettore a tendina se non allineato (senza generare rimbalzi di segnali)
        if hasattr(self, "combo_profile"):
            idx = self.combo_profile.findData(profile_id)
            if idx >= 0 and self.combo_profile.currentIndex() != idx:
                self.combo_profile.blockSignals(True)
                self.combo_profile.setCurrentIndex(idx)
                self.combo_profile.blockSignals(False)

        self.director.reset()
        profile = self.config["profiles"].get(profile_id, {})
        moods = profile.get("moods", {})
        self.mood_grid.populate(moods)

        # Seleziona la prima atmosfera come default
        if moods:
            first_mood = next(iter(moods.keys()))
            self.director.manual_select(first_mood)

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.config, self)
        if dlg.exec() == QDialog.Accepted:
            self.config = ConfigManager.load()
            self.director.configure(self.config.get("analyzer", {}))
            self.audio_engine.set_music_volume(int(self.config.get("audio", {}).get("music_volume", 75)))
            self.audio_engine.set_sfx_volume(int(self.config.get("audio", {}).get("sfx_volume", 80)))

    # ================================================================ Custom SFX
    def _on_custom_sfx_added(self, data: Dict[str, Any]) -> None:
        ok = self.sfx_manager.add_custom_sfx(
            sfx_id=data["sfx_id"],
            name=data["name"],
            source_audio_path=data["source_path"],
            keywords=data.get("keywords", []),
        )
        if ok:
            self.soundboard.set_library(self.sfx_manager.get_library())
            self.bridge.sig_status.emit(f"✅ SFX '{data['name']}' aggiunto con successo!")

    def _on_custom_sfx_deleted(self, sfx_id: str) -> None:
        self.sfx_manager.delete_custom_sfx(sfx_id)
        self.soundboard.set_library(self.sfx_manager.get_library())
        self.bridge.sig_status.emit(f"🗑️ SFX '{sfx_id}' rimosso.")

    def closeEvent(self, event) -> None:
        self.voice_listener.stop()
        self.audio_engine.shutdown()
        event.accept()
