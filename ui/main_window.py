"""
Finestra Principale di Bardo AI v2.6.3 (MainWindow) in PySide6.
Collega l'interfaccia grafica modulare con il Director, l'AudioEngine,
il MusicService, il ContinuousVoiceListener e l'SFXManager.
Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

from __future__ import annotations

import re
import sys
import threading
from collections import deque
from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from analyzer import SceneAnalyzer
from audio_engine import AudioEngine, MusicSource
from config_defaults import APP_VERSION, list_available_profiles
from director import Director, SceneDecision
from music_service import MusicService
from sfx_manager import SFXManager
from storage import ConfigManager, export_profile_to_file, import_profile_from_file
from ui.dialogs.settings_dialog import SettingsDialog
from ui.dialogs.shortcuts_dialog import ShortcutsDialog
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
        self.setWindowTitle(f"Bardo AI v{APP_VERSION} — Regia Musicale Intelligente & Soundboard GdR")
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

        # Stato modalità fluttuante (Auto-Float PiP)
        self.auto_float_enabled = bool(self.config.get("ui", {}).get("auto_float", True))
        self.is_floating = False
        self._normal_geometry = None
        self._recent_track_ids: deque[str] = deque(maxlen=25)
        self._auto_advancing: bool = False

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
        self.track_monitor_timer = QTimer(self)
        self.track_monitor_timer.timeout.connect(self._check_track_finished)
        self.track_monitor_timer.start(1000)

        # 6. Scorciatoie da tastiera (Hotkeys)
        self._setup_shortcuts()

        # 6. Avvia microfono e imposta primo profilo
        self._apply_profile(self.active_profile_id)
        self.voice_listener.start()

    def _init_core_engines(self) -> None:
        # Audio Engine (Sounddevice + PyAV)
        self.audio_engine = AudioEngine()
        saved_output_dev = self.config.get("audio", {}).get("output_device", None)
        if saved_output_dev is not None:
            self.audio_engine.set_output_device(saved_output_dev)
        music_vol = int(
            self.config.get("audio", {}).get("master_volume", self.config.get("audio", {}).get("music_volume", 75))
        )
        sfx_vol = int(
            self.config.get("sfx", {}).get("volume", self.config.get("audio", {}).get("sfx_volume", 80))
        )
        self.audio_engine.set_music_volume(music_vol)
        self.audio_engine.set_sfx_volume(sfx_vol)

        # YtDlp e Music Service
        self.ytdlp_mgr = YtDlpManager(status_cb=lambda s: self.bridge.sig_status.emit(s))
        self.ytdlp_mgr.ensure_ready_async()
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
            use_whisper=bool(self.config.get("stt", {}).get("whisper_enabled", True)),
            whisper_model=str(self.config.get("stt", {}).get("whisper_model", "small")),
            gate_threshold=int(self.config.get("stt", {}).get("gate_threshold", 20)),
        )

    # ================================================================ UI Layout
    def _build_ui(self) -> None:
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.root_layout = QVBoxLayout(central_widget)
        self.root_layout.setContentsMargins(14, 12, 14, 12)
        self.root_layout.setSpacing(10)

        # 1. Barra Superiore (Header racchiusa in un widget per il PiP)
        self.top_bar_widget = QWidget()
        top_bar = QHBoxLayout(self.top_bar_widget)
        top_bar.setContentsMargins(0, 0, 0, 0)
        top_bar.setSpacing(12)

        lbl_app = QLabel("BARDO AI")
        lbl_app.setObjectName("headerTitle")
        lbl_v2 = QLabel(f"v{APP_VERSION}")
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

        # Pulsanti Esporta / Importa Profilo
        self.btn_export_profile = QPushButton("📤")
        self.btn_export_profile.setToolTip("Esporta il profilo corrente in file .bardo.json")
        self.btn_export_profile.setFixedWidth(32)
        self.btn_export_profile.clicked.connect(self._on_export_profile_clicked)
        top_bar.addWidget(self.btn_export_profile)

        self.btn_import_profile = QPushButton("📥")
        self.btn_import_profile.setToolTip("Importa un profilo di campagna (.bardo.json)")
        self.btn_import_profile.setFixedWidth(32)
        self.btn_import_profile.clicked.connect(self._on_import_profile_clicked)
        top_bar.addWidget(self.btn_import_profile)
        top_bar.addStretch()

        # Interruttore Auto-Float (Mini-Player automatico Always-on-Top)
        self.btn_auto_float = QPushButton()
        self.btn_auto_float.setCheckable(True)
        self.btn_auto_float.setChecked(self.auto_float_enabled)
        self.btn_auto_float.clicked.connect(self._toggle_auto_float)
        self._update_auto_float_button_style()
        top_bar.addWidget(self.btn_auto_float)

        # Pulsante Impostazioni
        btn_settings = QPushButton("⚙️ Impostazioni")
        btn_settings.clicked.connect(self._open_settings)
        top_bar.addWidget(btn_settings)

        # Menu a tendina Aiuto
        self.btn_help = QPushButton("❓ Aiuto ▾")
        self.menu_help = QMenu(self)
        self.act_shortcuts = self.menu_help.addAction("⌨️ Scorciatoie da Tastiera... (F1)")
        self.act_shortcuts.triggered.connect(self._open_shortcuts_dialog)
        self.act_faq = self.menu_help.addAction("💡 Domande Frequenti (FAQ)...")
        self.act_faq.triggered.connect(self._open_faq_dialog)
        self.act_about = self.menu_help.addAction("ℹ️ Informazioni su Bardo AI...")
        self.act_about.triggered.connect(self._open_about_dialog)
        self.btn_help.setMenu(self.menu_help)
        top_bar.addWidget(self.btn_help)

        self.root_layout.addWidget(self.top_bar_widget)

        # 2. Area Centrale (Splitter: Atmosfere in alto, Soundboard in basso)
        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.setChildrenCollapsible(False)

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
        self.splitter.addWidget(mood_container)

        # Sezione Soundboard
        sfx_container = QWidget()
        sfx_layout = QVBoxLayout(sfx_container)
        sfx_layout.setContentsMargins(0, 0, 0, 0)
        sfx_layout.setSpacing(6)
        self.soundboard = SoundboardWidget()
        self.soundboard.set_library(self.sfx_manager.get_library())
        sfx_layout.addWidget(self.soundboard)
        self.splitter.addWidget(sfx_container)

        self.splitter.setStretchFactor(0, 5)
        self.splitter.setStretchFactor(1, 4)
        self.root_layout.addWidget(self.splitter)

        # 3. Widget Monitoraggio Vocale
        self.voice_monitor = VoiceMonitorWidget()
        init_gate = int(self.config.get("stt", {}).get("gate_threshold", 20))
        self.voice_monitor.set_gate_threshold(init_gate)
        self.voice_monitor.populate_devices(ContinuousVoiceListener.get_input_devices())
        self.root_layout.addWidget(self.voice_monitor)

        # 4. Barra di Trasporto Audio
        self.transport = TransportBar()
        music_vol = int(
            self.config.get("audio", {}).get("master_volume", self.config.get("audio", {}).get("music_volume", 75))
        )
        sfx_vol = int(
            self.config.get("sfx", {}).get("volume", self.config.get("audio", {}).get("sfx_volume", 80))
        )
        self.transport.set_music_volume(music_vol)
        self.transport.set_sfx_volume(sfx_vol)
        self.transport.populate_output_devices(AudioEngine.get_output_devices())
        saved_out = self.config.get("audio", {}).get("output_device", None)
        self.transport.select_device(saved_out)
        self.root_layout.addWidget(self.transport)

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
        self.voice_monitor.mic_toggled.connect(self.transport.set_mic_active)
        self.voice_monitor.threshold_changed.connect(self._on_gate_threshold_changed)

        # Transport Bar
        self.transport.play_pause_clicked.connect(self._on_play_pause)
        self.transport.skip_clicked.connect(self._on_skip_track)
        self.transport.music_volume_changed.connect(self._on_music_volume_changed)
        self.transport.sfx_volume_changed.connect(self._on_sfx_volume_changed)
        self.transport.lock_toggled.connect(self.director.set_locked)
        self.transport.output_device_changed.connect(self._on_output_device_changed)
        self.transport.restore_clicked.connect(self._exit_floating_mode)
        self.transport.mic_toggled.connect(self.voice_monitor.btn_mic_toggle.setChecked)

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
        analyzer_cfg = self.config.get("analyzer", {})
        provider = analyzer_cfg.get("ai_provider", "keywords")
        mode = analyzer_cfg.get("mode", "hybrid")

        if provider == "keywords" or mode == "keywords":
            res = self.analyzer.analyze_keywords(text, profile)
            if res.get("mood_id"):
                self.director.submit(res, moods)
            return

        threshold = float(analyzer_cfg.get("confidence_threshold", 2.2))
        kw_res = self.analyzer.analyze_keywords(text, profile, threshold=threshold)
        if kw_res.get("voice_action") or kw_res.get("matched_by") == "command":
            if kw_res.get("mood_id"):
                self.director.submit(kw_res, moods)
            return

        if mode == "hybrid" and kw_res.get("mood_id") and float(kw_res.get("confidence", 0)) >= threshold:
            self.director.submit(kw_res, moods)
            return

        curr_gen = self.director.generation
        curr_mood = self.director.current_mood_id

        def _ai_worker() -> None:
            import asyncio
            try:
                ai_res = asyncio.run(
                    self.analyzer.analyze(text, profile, analyzer_cfg, current_mood_id=curr_mood)
                )
                if self.director.is_current(curr_gen) and ai_res and ai_res.get("mood_id"):
                    self.director.submit(ai_res, moods)
                elif kw_res.get("mood_id") and self.director.is_current(curr_gen):
                    self.director.submit(kw_res, moods)
            except Exception as e_ai:
                print(f"[AIWorker] Errore analisi AI: {e_ai}")
                if kw_res.get("mood_id") and self.director.is_current(curr_gen):
                    self.director.submit(kw_res, moods)

        threading.Thread(target=_ai_worker, daemon=True, name=f"ai-analyze-{curr_gen}").start()
        return



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

        try:
            track = None
            # 1. Prova playlist personalizzata del mood (se configurata)
            custom_pl = str(mood_data.get("custom_playlist") or "").strip()
            if custom_pl:
                try:
                    pl_info = self.music_service.load_playlist(custom_pl, limit=40)
                    pl_tracks = pl_info.get("tracks") or []
                    if pl_tracks:
                        unheard = [
                            t for t in pl_tracks
                            if (t.get("videoId") or t.get("title")) not in self._recent_track_ids
                        ]
                        cand_pool = unheard if unheard else pl_tracks
                        import random
                        track = random.choice(cand_pool)
                except Exception as e_pl:
                    print(f"[MusicWorker] Errore caricamento custom_playlist mood '{mood_id}': {e_pl}")

            # 2. Prova seed tracks
            seed_tracks = mood_data.get("seed_tracks", [])
            if seed_tracks:
                import random
                unheard = [
                    t for t in seed_tracks
                    if (t.get("videoId") or t.get("title")) not in self._recent_track_ids
                ]
                cand_pool = unheard if unheard else seed_tracks
                import random
                track = random.choice(cand_pool)

            if not track:
                # 3. Cerca tramite query
                queries = mood_data.get("queries", [f"{mood_id} soundtrack instrumental"])
                query = custom_query or queries[0]
                tracks = self.music_service.search_tracks(query, limit=10, tone_profile=tone)
                if tracks:
                    unheard = [
                        t for t in tracks
                        if (t.get("videoId") or t.get("title")) not in self._recent_track_ids
                    ]
                    cand_pool = unheard if unheard else tracks
                    import random
                    track = random.choice(cand_pool)

            if not self.director.is_current(generation):
                return

            resolved = None
            if track:
                try:
                    resolved = self.music_service.resolve_playable(track, tone_profile=tone)
                except Exception as e_res:
                    print(f"[MusicWorker] Risoluzione traccia online fallita ({e_res}), provo fallback locale...")
                    resolved = None

            # Fallback su tracce locali se lo stream online non è risolvibile
            if not resolved or not (resolved.get("uri") or resolved.get("audio_url")):
                local_candidates = self.music_service.local_tracks(mood_id)
                if local_candidates:
                    chosen_local = local_candidates[0]
                    track = chosen_local
                    resolved = self.music_service.resolve_playable(chosen_local, tone_profile=tone)
                    try:
                        self.bridge.sig_status.emit(f"📁 Uso musica locale: {resolved.get('title', 'Brano')}")
                    except (RuntimeError, Exception):
                        pass

            if not self.director.is_current(generation) or not resolved:
                return

            audio_uri = resolved.get("uri") or resolved.get("audio_url")
            if not audio_uri:
                try:
                    self.bridge.sig_status.emit(f"⚠️ Nessun audio disponibile per '{mood_id}'")
                except (RuntimeError, Exception):
                    pass
                return

            title = resolved.get("title") or (track.get("title", "Traccia") if track else "Traccia")
            artist = resolved.get("artist") or (track.get("artist", "") if track else "")
            duration = float(resolved.get("duration") or (track.get("duration_seconds", 180) if track else 180))

            source = MusicSource(
                uri=audio_uri,
                title=title,
                duration=duration,
                http_headers=resolved.get("http_headers", {}),
                skip_segments=resolved.get("skip_segments", []),
            )
            crossfade = float(self.config.get("audio", {}).get("crossfade_seconds", 4.0))
            self.audio_engine.play(source, crossfade_seconds=crossfade)
            track_key = (track.get("videoId") if track else "") or title or audio_uri
            if track_key:
                self._recent_track_ids.append(track_key)
            try:
                self.bridge.sig_track_started.emit(title, artist)
                self.bridge.sig_status.emit(f"▶️ In riproduzione: {title}")
            except (RuntimeError, Exception):
                pass
        except Exception as e:
            print(f"[MusicWorker] Errore riproduzione scena {mood_id}: {e}")
            try:
                self.bridge.sig_status.emit(f"⚠️ Errore riproduzione ({mood_id}): {e}")
            except (RuntimeError, Exception):
                pass

    # ================================================================ Transport Controls
    def _setup_shortcuts(self) -> None:
        """Inizializza le scorciatoie da tastiera per il controllo immediato al tavolo."""
        self.shortcut_mic = QShortcut(QKeySequence("Ctrl+M"), self)
        self.shortcut_mic.activated.connect(self._toggle_mic)

        self.shortcut_play_pause = QShortcut(QKeySequence("Ctrl+Space"), self)
        self.shortcut_play_pause.activated.connect(self._on_play_pause)

        self.shortcut_skip = QShortcut(QKeySequence("Ctrl+Right"), self)
        self.shortcut_skip.activated.connect(self._on_skip_track)

        self.shortcut_vol_up = QShortcut(QKeySequence("Ctrl+Up"), self)
        self.shortcut_vol_up.activated.connect(self._on_volume_up)

        self.shortcut_vol_down = QShortcut(QKeySequence("Ctrl+Down"), self)
        self.shortcut_vol_down.activated.connect(self._on_volume_down)

        # Ctrl+F11: Attiva / Disattiva Auto-Float PiP
        self.shortcut_auto_float = QShortcut(QKeySequence("Ctrl+F11"), self)
        self.shortcut_auto_float.activated.connect(self._toggle_auto_float)

        # F1: Guida Scorciatoie da Tastiera
        self.shortcut_help = QShortcut(QKeySequence("F1"), self)
        self.shortcut_help.activated.connect(self._open_shortcuts_dialog)

    def _toggle_mic(self) -> None:
        """Inverte lo stato del microfono tramite tasto rapido (Ctrl+M)."""
        self.voice_monitor.btn_mic_toggle.toggle()

    def _on_volume_up(self) -> None:
        """Aumenta il volume della musica del 5% (Ctrl+Su)."""
        self.transport.step_music_volume(5)

    def _on_volume_down(self) -> None:
        """Abbassa il volume della musica del 5% (Ctrl+Giù)."""
        self.transport.step_music_volume(-5)

    def _on_music_volume_changed(self, vol: int) -> None:
        """Riceve la modifica del volume musica dallo slider e aggiorna audio engine e configurazione."""
        self.audio_engine.set_music_volume(vol)
        if "audio" not in self.config or not isinstance(self.config["audio"], dict):
            self.config["audio"] = {}
        self.config["audio"]["master_volume"] = vol

    def _on_sfx_volume_changed(self, vol: int) -> None:
        """Riceve la modifica del volume SFX dallo slider e aggiorna audio engine e configurazione."""
        self.audio_engine.set_sfx_volume(vol)
        if "sfx" not in self.config or not isinstance(self.config["sfx"], dict):
            self.config["sfx"] = {}
        self.config["sfx"]["volume"] = vol

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

    def _on_gate_threshold_changed(self, threshold: int) -> None:
        """Calibra dinamicamente la sensibilità del Voice Activity Detection (VAD) e salva la configurazione."""
        self.voice_listener.set_gate_threshold(threshold)
        if "stt" not in self.config:
            self.config["stt"] = {}
        self.config["stt"]["gate_threshold"] = threshold
        ConfigManager.save(self.config)

    def _on_output_device_changed(self, device_index: Optional[int]) -> None:
        """Cambia a caldo il dispositivo di output audio e persiste la scelta in configurazione."""
        self.audio_engine.set_output_device(device_index)
        if "audio" not in self.config:
            self.config["audio"] = {}
        self.config["audio"]["output_device"] = device_index
        ConfigManager.save(self.config)

    def _update_cooldown_badge(self) -> None:
        rem = self.director.cooldown_remaining()
        self.transport.update_cooldown(rem)

    def _check_track_finished(self) -> None:
        """Controlla se il brano attivo è giunto a termine ed avanza automaticamente alla traccia successiva."""
        if getattr(self, "_is_closing", False) or self.audio_engine.paused:
            return
        status = self.audio_engine.active_status()
        if status.get("has_source") and status.get("finished"):
            current_mood = self.director.current_mood_id
            if current_mood and not getattr(self, "_auto_advancing", False):
                self._auto_advancing = True
                self.bridge.sig_status.emit(f"🔄 Brano terminato. Caricamento traccia successiva ({current_mood})...")

                def _advance() -> None:
                    try:
                        self._fetch_and_play_track_worker(current_mood, self.director.generation)
                    finally:
                        self._auto_advancing = False

                threading.Thread(
                    target=_advance,
                    daemon=True,
                    name=f"auto-advance-{self.director.generation}",
                ).start()

    # ================================================================ Profile & Settings
    def _reload_profile_combo(self, select_id: Optional[str] = None) -> None:
        """Ricarica l'elenco dei profili nel menu a tendina preservando o impostando la selezione."""
        self.combo_profile.blockSignals(True)
        self.combo_profile.clear()
        profiles = list_available_profiles(self.config)
        for p in profiles:
            self.combo_profile.addItem(f"{p.get('icon', '🎭')} {p.get('name', p['id'])}", p["id"])
        target_id = select_id or self.active_profile_id
        idx = self.combo_profile.findData(target_id)
        if idx >= 0:
            self.combo_profile.setCurrentIndex(idx)
        self.combo_profile.blockSignals(False)

    def _on_export_profile_clicked(self) -> None:
        """Esporta il profilo attivo corrente in un file .bardo.json."""
        current_profile = self.config.get("profiles", {}).get(self.active_profile_id)
        if not current_profile:
            QMessageBox.warning(self, "Attenzione", "Nessun profilo selezionato da esportare.")
            return

        slug = re.sub(r"[^a-zA-Z0-9_\-]+", "_", current_profile.get("name", "profilo")).strip("_")
        default_filename = f"{slug}.bardo.json"

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Esporta Profilo di Campagna",
            default_filename,
            "Profilo Bardo AI (*.bardo.json);;File JSON (*.json)",
        )
        if not file_path:
            return

        ok = export_profile_to_file(current_profile, Path(file_path))
        if ok:
            QMessageBox.information(
                self,
                "Esportazione Completata",
                f"Il profilo '{current_profile.get('name')}' è stato esportato con successo in:\n{file_path}",
            )
        else:
            QMessageBox.critical(
                self,
                "Errore di Esportazione",
                f"Impossibile scrivere il file di profilo:\n{file_path}",
            )

    def _on_import_profile_clicked(self) -> None:
        """Importa un profilo da un file .bardo.json e lo attiva all'istante."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Importa Profilo di Campagna",
            "",
            "Profilo Bardo AI (*.bardo.json);;File JSON (*.json);;Tutti i file (*.*)",
        )
        if not file_path:
            return

        ok, msg, imported_prof = import_profile_from_file(Path(file_path), self.config)
        if ok and imported_prof:
            new_id = imported_prof["id"]
            self._reload_profile_combo(select_id=new_id)
            self._apply_profile(new_id)
            QMessageBox.information(self, "Profilo Importato", msg)
        else:
            QMessageBox.warning(self, "Importazione Fallita", msg)
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
        profile = self.config.get("profiles", {}).get(profile_id, {})
        moods = profile.get("moods", {})
        self.mood_grid.populate(moods)

        # Seleziona la prima atmosfera come default
        if moods:
            first_mood = next(iter(moods.keys()))
            self.director.manual_select(first_mood)

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.config, self, music_service=self.music_service)
        res = dlg.exec()
        self.music_service.reload_client()
        if res == QDialog.Accepted:
            self.config = ConfigManager.load()
            self.director.configure(self.config.get("analyzer", {}))
            music_vol = int(
                self.config.get("audio", {}).get("master_volume", self.config.get("audio", {}).get("music_volume", 75))
            )
            sfx_vol = int(
                self.config.get("sfx", {}).get("volume", self.config.get("audio", {}).get("sfx_volume", 80))
            )
            self.audio_engine.set_music_volume(music_vol)
            self.audio_engine.set_sfx_volume(sfx_vol)
            self.transport.set_music_volume(music_vol)
            self.transport.set_sfx_volume(sfx_vol)
            if self.music_service.is_authenticated:
                self.bridge.sig_status.emit("🟢 YouTube Music collegato.")

    def _open_shortcuts_dialog(self) -> None:
        """Apre la finestra di dialogo con l'elenco delle scorciatoie da tastiera (F1)."""
        dlg = ShortcutsDialog(self)
        dlg.exec()

    def _open_faq_dialog(self) -> None:
        """Apre la guida alle Domande Frequenti (docs/FAQ.md)."""
        faq_path = Path(__file__).resolve().parent.parent / "docs" / "FAQ.md"
        if faq_path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(faq_path)))
        else:
            QDesktopServices.openUrl(QUrl("https://github.com/Il-Basta-Paolo/BardoAI/blob/main/docs/FAQ.md"))

    def _open_about_dialog(self) -> None:
        """Mostra le informazioni sull'applicazione, autore e versione."""
        QMessageBox.about(
            self,
            "Informazioni su Bardo AI",
            f"<h3>Bardo AI v{APP_VERSION}</h3>"
            "<p><b>Regia musicale autonoma ed effetti sonori vocali per sessioni GdR</b></p>"
            "<p>Autore: <b>Paolo Basta</b> (<a href='https://github.com/Il-Basta-Paolo'>@Il-Basta-Paolo</a>)<br>"
            "Repository: <a href='https://github.com/Il-Basta-Paolo/BardoAI'>github.com/Il-Basta-Paolo/BardoAI</a><br>"
            "Licenza: Open Source MIT</p>"
            "<p>Elaborazione vocale 100% offline tramite Vosk e Faster-Whisper. "
            "Mixer audio stereo a 48kHz basato su PyAV e sounddevice.</p>",
        )

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

    # ================================================================ Auto-Float (PiP) Logic
    def _update_auto_float_button_style(self) -> None:
        """Aggiorna il testo, il tooltip e lo stile visivo del pulsante Auto-Float."""
        if self.auto_float_enabled:
            self.btn_auto_float.setText("⚡ Auto-Float: ON")
            self.btn_auto_float.setToolTip(
                "Auto-Float ATTIVO (Ctrl+F11):\n"
                "Quando clicchi su un'altra finestra (Roll20, Foundry, browser),\n"
                "Bardo AI diventa una mini-barra fluttuante Always-on-Top.\n"
                "Clicca qui per disattivarlo."
            )
            self.btn_auto_float.setStyleSheet(
                "font-size: 11px; font-weight: 600; background-color: #059669; color: white; border-radius: 4px; padding: 4px 8px;"
            )
        else:
            self.btn_auto_float.setText("⚡ Auto-Float: OFF")
            self.btn_auto_float.setToolTip(
                "Auto-Float DISATTIVATO (Ctrl+F11):\n"
                "Bardo AI si comporta come una normale finestra Windows.\n"
                "Clicca qui per attivare il mini-player automatico."
            )
            self.btn_auto_float.setStyleSheet(
                "font-size: 11px; font-weight: 600; background-color: #334155; color: #94a3b8; border-radius: 4px; padding: 4px 8px;"
            )

    def _toggle_auto_float(self) -> None:
        """Abilita o disabilita la modalità Auto-Float (Picture-in-Picture)."""
        self.auto_float_enabled = not self.auto_float_enabled
        if "ui" not in self.config:
            self.config["ui"] = {}
        self.config["ui"]["auto_float"] = self.auto_float_enabled
        ConfigManager.save(self.config)

        self.btn_auto_float.setChecked(self.auto_float_enabled)
        self._update_auto_float_button_style()

        # Se disattivato mentre la finestra è ridotta a mini-barra, ripristina la vista estesa
        if not self.auto_float_enabled and self.is_floating:
            self._exit_floating_mode()

    def _enter_floating_mode(self) -> None:
        """Riduce l'interfaccia a una mini-barra Always-on-Top nell'angolo dello schermo."""
        if self.is_floating:
            return
        self.is_floating = True
        self._normal_geometry = self.geometry()

        # Nasconde tutti gli elementi non essenziali per il mini-player
        self.top_bar_widget.hide()
        self.splitter.hide()
        self.voice_monitor.hide()

        # Attiva la modalità compatta sul transport bar
        self.transport.set_compact_mode(True)
        self.root_layout.setContentsMargins(6, 6, 6, 6)
        self.root_layout.setSpacing(0)

        # Consente il ridimensionamento a dimensioni compatte da mini-player
        self.setMinimumSize(460, 76)
        self.resize(540, 84)

        # Sposta la finestra in basso a destra nello schermo corrente
        screen = self.screen().availableGeometry() if self.screen() else None
        if screen:
            new_x = screen.right() - 540 - 24
            new_y = screen.bottom() - 84 - 48
            self.move(new_x, new_y)

        # Applica il flag Always-on-Top senza rubare il focus all'applicazione attiva
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.show()

    def _exit_floating_mode(self) -> None:
        """Ripristina la finestra alla modalità estesa standard a grandezza naturale."""
        if not self.is_floating:
            return
        self.is_floating = False

        # Rimuove il flag Always-on-Top
        self.setAttribute(Qt.WA_ShowWithoutActivating, False)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, False)

        # Ripristina margini e spaziatura standard
        self.root_layout.setContentsMargins(14, 12, 14, 12)
        self.root_layout.setSpacing(10)

        # Ripristina la dimensione minima standard e mostra tutti i componenti
        self.setMinimumSize(960, 680)
        self.top_bar_widget.show()
        self.splitter.show()
        self.voice_monitor.show()
        self.transport.set_compact_mode(False)

        # Ripristina la geometria precedente
        if self._normal_geometry:
            self.setGeometry(self._normal_geometry)
        else:
            self.resize(1120, 800)

        self.show()

    def changeEvent(self, event: QEvent) -> None:
        """Intercetta il cambio di attivazione della finestra per l'Auto-Float PiP."""
        if event.type() == QEvent.ActivationChange:
            if not self.isActiveWindow():
                if (
                    self.auto_float_enabled
                    and not self.is_floating
                    and not self.isMinimized()
                    and QApplication.activeModalWidget() is None
                ):
                    self._enter_floating_mode()
            else:
                if self.is_floating:
                    self._exit_floating_mode()
        super().changeEvent(event)

    def closeEvent(self, event) -> None:
        self._is_closing = True
        self.director.reset()
        self.voice_listener.stop()
        self.audio_engine.shutdown()
        ConfigManager.save(self.config)
        event.accept()
