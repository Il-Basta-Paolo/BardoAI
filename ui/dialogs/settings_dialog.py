"""
Finestra di configurazione e impostazioni (Settings Dialog) in PySide6.
Salva in modo sicuro le credenziali nel Credential Manager (SecretVault) e aggiorna i parametri del Director.
"""

from typing import Any, Dict
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from storage import ConfigManager, SecretVault


class SettingsDialog(QDialog):
    def __init__(self, current_config: Dict[str, Any], parent: QWidget = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Impostazioni di Bardo AI v2.6.0")
        self.setFixedSize(540, 420)
        self.setStyleSheet("background-color: #0b0f19; color: #f8fafc;")

        self.config = current_config
        self.analyzer_cfg = current_config.get("analyzer", {})
        self.audio_cfg = current_config.get("audio", {})
        self.stt_cfg = current_config.get("stt", {})

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        self._build_ai_tab()
        self._build_spotify_tab()
        self._build_audio_tab()

        # Bottoni OK / Annulla
        btn_box = QHBoxLayout()
        btn_cancel = QPushButton("Annulla")
        btn_cancel.clicked.connect(self.reject)
        btn_save = QPushButton("Salva Modifiche")
        btn_save.setObjectName("primaryBtn")
        btn_save.clicked.connect(self._save_and_close)
        btn_box.addStretch()
        btn_box.addWidget(btn_cancel)
        btn_box.addWidget(btn_save)
        main_layout.addLayout(btn_box)

    # ================================================================ Tab AI
    def _build_ai_tab(self) -> None:
        tab = QWidget()
        layout = QFormLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.combo_provider = QComboBox()
        self.combo_provider.addItems(["gemini", "ollama", "openai", "keywords"])
        curr_prov = self.analyzer_cfg.get("ai_provider", "gemini")
        idx = self.combo_provider.findText(curr_prov)
        if idx >= 0:
            self.combo_provider.setCurrentIndex(idx)
        layout.addRow("Provider AI:", self.combo_provider)

        # Gemini API Key (letta da SecretVault)
        self.txt_gemini_key = QLineEdit()
        self.txt_gemini_key.setEchoMode(QLineEdit.Password)
        self.txt_gemini_key.setText(SecretVault.get_secret("gemini_api_key", ""))
        self.txt_gemini_key.setPlaceholderText("Incolla API Key Gemini...")
        layout.addRow("Chiave API Gemini:", self.txt_gemini_key)

        # Modello Gemini
        self.txt_gemini_model = QLineEdit()
        self.txt_gemini_model.setText(self.analyzer_cfg.get("gemini_model", "gemini-2.5-flash"))
        layout.addRow("Modello Gemini:", self.txt_gemini_model)

        # Parametri Regia
        self.spin_cooldown = QSpinBox()
        self.spin_cooldown.setRange(5, 60)
        self.spin_cooldown.setValue(int(self.analyzer_cfg.get("cooldown_seconds", 18)))
        layout.addRow("Cooldown Regia (sec):", self.spin_cooldown)

        self.spin_min_dur = QDoubleSpinBox()
        self.spin_min_dur.setRange(3.0, 30.0)
        self.spin_min_dur.setValue(float(self.analyzer_cfg.get("min_scene_duration_seconds", 8.0)))
        layout.addRow("Durata Minima Scena (sec):", self.spin_min_dur)

        self.spin_hysteresis = QDoubleSpinBox()
        self.spin_hysteresis.setRange(10.0, 60.0)
        self.spin_hysteresis.setValue(float(self.analyzer_cfg.get("hysteresis_window_seconds", 25.0)))
        layout.addRow("Finestra Isteresi Calma (sec):", self.spin_hysteresis)

        self.tab_widget.addTab(tab, "Intelligenza Artificiale")

    # ================================================================ Tab Spotify
    def _build_spotify_tab(self) -> None:
        tab = QWidget()
        layout = QFormLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        info = QLabel("Configura Spotify Client Credentials per importare playlist e metadati ufficiali:")
        info.setWordWrap(True)
        info.setStyleSheet("color: #94a3b8; font-size: 11px;")
        layout.addRow(info)

        self.txt_spotify_id = QLineEdit()
        self.txt_spotify_id.setText(SecretVault.get_secret("spotify_client_id", ""))
        self.txt_spotify_id.setPlaceholderText("Client ID da developer.spotify.com")
        layout.addRow("Client ID:", self.txt_spotify_id)

        self.txt_spotify_secret = QLineEdit()
        self.txt_spotify_secret.setEchoMode(QLineEdit.Password)
        self.txt_spotify_secret.setText(SecretVault.get_secret("spotify_client_secret", ""))
        self.txt_spotify_secret.setPlaceholderText("Client Secret...")
        layout.addRow("Client Secret:", self.txt_spotify_secret)

        btn_test_sp = QPushButton("Verifica Connessione Spotify")
        btn_test_sp.clicked.connect(self._test_spotify)
        layout.addRow("", btn_test_sp)

        self.tab_widget.addTab(tab, "Spotify")

    def _test_spotify(self) -> None:
        cid = self.txt_spotify_id.text().strip()
        sec = self.txt_spotify_secret.text().strip()
        if not cid or not sec:
            QMessageBox.warning(self, "Attenzione", "Inserisci sia Client ID che Client Secret.")
            return
        from music_service import SpotifyMetadata
        SpotifyMetadata.set_credentials(cid, sec)
        sp = SpotifyMetadata()
        if sp.test_credentials():
            QMessageBox.information(self, "Successo", "Connessione alle API Spotify riuscita!")
        else:
            QMessageBox.critical(self, "Errore", "Credenziali Spotify non valide o non abilitate.")

    # ================================================================ Tab Audio & Cache
    def _build_audio_tab(self) -> None:
        tab = QWidget()
        layout = QFormLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.spin_crossfade = QDoubleSpinBox()
        self.spin_crossfade.setRange(0.5, 12.0)
        self.spin_crossfade.setSingleStep(0.5)
        self.spin_crossfade.setValue(float(self.audio_cfg.get("crossfade_seconds", 4.0)))
        layout.addRow("Durata Crossfade (sec):", self.spin_crossfade)

        self.spin_cache_mb = QSpinBox()
        self.spin_cache_mb.setRange(200, 5000)
        self.spin_cache_mb.setValue(int(self.audio_cfg.get("cache_max_mb", 1024)))
        layout.addRow("Limite Cache Audio (MB):", self.spin_cache_mb)

        self.tab_widget.addTab(tab, "Audio & Cache")

    # ================================================================ Save
    def _save_and_close(self) -> None:
        # 1. Salva i segreti in SecretVault
        gemini_k = self.txt_gemini_key.text().strip()
        if gemini_k:
            SecretVault.set_secret("gemini_api_key", gemini_k)

        sp_id = self.txt_spotify_id.text().strip()
        sp_sec = self.txt_spotify_secret.text().strip()
        if sp_id:
            SecretVault.set_secret("spotify_client_id", sp_id)
        if sp_sec:
            SecretVault.set_secret("spotify_client_secret", sp_sec)

        # 2. Aggiorna configurazione
        self.analyzer_cfg["ai_provider"] = self.combo_provider.currentText()
        self.analyzer_cfg["gemini_model"] = self.txt_gemini_model.text().strip()
        self.analyzer_cfg["cooldown_seconds"] = self.spin_cooldown.value()
        self.analyzer_cfg["min_scene_duration_seconds"] = self.spin_min_dur.value()
        self.analyzer_cfg["hysteresis_window_seconds"] = self.spin_hysteresis.value()

        self.audio_cfg["crossfade_seconds"] = self.spin_crossfade.value()
        self.audio_cfg["cache_max_mb"] = self.spin_cache_mb.value()

        self.config["analyzer"] = self.analyzer_cfg
        self.config["audio"] = self.audio_cfg

        ConfigManager.save(self.config)
        self.accept()
