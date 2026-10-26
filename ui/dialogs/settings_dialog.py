"""
Finestra di configurazione e impostazioni (Settings Dialog) in PySide6 per Bardo AI.
Salva in modo sicuro le credenziali nel Credential Manager (SecretVault) e aggiorna i parametri del Director.
Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional

__author__ = "Paolo Basta"

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config_defaults import APP_VERSION
from music_service import MusicService
from storage import ConfigManager, SecretVault
from ytdlp_manager import YtDlpManager


class SettingsDialog(QDialog):
    def __init__(
        self,
        current_config: Dict[str, Any],
        parent: Optional[QWidget] = None,
        music_service: Optional[MusicService] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Impostazioni di Bardo AI v{APP_VERSION}")
        self.setFixedSize(580, 520)
        self.setStyleSheet("background-color: #0b0f19; color: #f8fafc;")

        self.config = current_config
        self.analyzer_cfg = current_config.get("analyzer", {})
        self.audio_cfg = current_config.get("audio", {})
        self.stt_cfg = current_config.get("stt", {})
        self.music_service = music_service if music_service is not None else MusicService(YtDlpManager())

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        self._build_ytmusic_tab()
        self._build_ai_tab()
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

    # ================================================================ Tab YouTube Music
    def _build_ytmusic_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        desc = QLabel(
            "<b>Accesso Rapido a YouTube Music:</b><br>"
            "YouTube Music funziona già gratis e senza account. Se colleghi il tuo account Google, "
            "potrai accedere direttamente alle tue playlist personali e ai brani preferiti."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #cbd5e1; font-size: 11px;")
        layout.addWidget(desc)

        status_box = QGroupBox("Stato Account")
        status_layout = QVBoxLayout(status_box)
        status_layout.setSpacing(8)

        self.lbl_ytm_status = QLabel()
        self.lbl_ytm_status.setWordWrap(True)
        status_layout.addWidget(self.lbl_ytm_status)

        layout.addWidget(status_box)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_ytm_login = QPushButton("🔑 Accedi con Google (1 Clic)")
        self.btn_ytm_login.setStyleSheet(
            "background-color: #ef4444; color: white; font-weight: bold; padding: 8px 14px; border-radius: 4px;"
        )
        self.btn_ytm_login.clicked.connect(self._start_ytm_browser_login)
        btn_layout.addWidget(self.btn_ytm_login)

        self.btn_ytm_disconnect = QPushButton("Disconnetti")
        self.btn_ytm_disconnect.setStyleSheet(
            "background-color: #334155; color: #f87171; font-weight: 600; padding: 8px 14px; border-radius: 4px;"
        )
        self.btn_ytm_disconnect.clicked.connect(self._disconnect_ytmusic)
        btn_layout.addWidget(self.btn_ytm_disconnect)

        self.btn_ytm_test = QPushButton("Verifica Connessione")
        self.btn_ytm_test.clicked.connect(self._test_ytmusic)
        btn_layout.addWidget(self.btn_ytm_test)

        layout.addLayout(btn_layout)

        adv_box = QGroupBox("Opzioni Avanzate (Incolla Cookie / Headers manualmente)")
        adv_layout = QVBoxLayout(adv_box)
        adv_layout.setSpacing(6)

        self.txt_manual_headers = QTextEdit()
        self.txt_manual_headers.setMaximumHeight(65)
        self.txt_manual_headers.setPlaceholderText("Incolla qui la stringa Cookie o gli header di rete se preferisci non usare Edge/Chrome...")
        adv_layout.addWidget(self.txt_manual_headers)

        btn_save_manual = QPushButton("Salva Cookie Manuali")
        btn_save_manual.clicked.connect(self._save_manual_ytm_headers)
        adv_layout.addWidget(btn_save_manual)

        layout.addWidget(adv_box)
        layout.addStretch()

        self._update_ytm_status_display()
        self.tab_widget.addTab(tab, "YouTube Music")

    def _update_ytm_status_display(self) -> None:
        ms = getattr(self, "music_service", None)
        if ms is None:
            ms = MusicService(YtDlpManager())
            self.music_service = ms

        if ms.is_authenticated:
            self.lbl_ytm_status.setText(
                "<span style='color: #10b981; font-weight: bold; font-size: 13px;'>🟢 Account Google Connesso</span><br>"
                "<span style='color: #94a3b8; font-size: 11px;'>Le tue playlist personali di YouTube Music sono sincronizzate e memorizzate.</span>"
            )
            self.btn_ytm_login.setText("Riconnetti / Cambia Account")
            self.btn_ytm_disconnect.setEnabled(True)
        else:
            self.lbl_ytm_status.setText(
                "<span style='color: #94a3b8; font-weight: bold; font-size: 13px;'>⚪ Modalità Ospite Standard</span><br>"
                "<span style='color: #64748b; font-size: 11px;'>Nessun account collegato. Bardo AI cerca e suona comunque tutta la musica gratis.</span>"
            )
            self.btn_ytm_login.setText("🔑 Accedi con Google (1 Clic)")
            self.btn_ytm_disconnect.setEnabled(False)

    def reject(self) -> None:
        if getattr(self, "_active_ytm_cancel_event", None):
            self._active_ytm_cancel_event.set()
        super().reject()

    def closeEvent(self, event) -> None:
        if getattr(self, "_active_ytm_cancel_event", None):
            self._active_ytm_cancel_event.set()
        super().closeEvent(event)

    def _start_ytm_browser_login(self) -> None:
        ms = getattr(self, "music_service", None)
        if ms is None:
            ms = MusicService(YtDlpManager())
            self.music_service = ms

        cancel_event = threading.Event()
        self._active_ytm_cancel_event = cancel_event
        progress = QProgressDialog(
            "Apertura finestra di login su YouTube Music...\nAccedi con il tuo account Google nel browser.",
            "Annulla",
            0,
            0,
            self,
        )
        progress.setWindowTitle("Accesso YouTube Music")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.canceled.connect(cancel_event.set)
        progress.show()

        res_holder = {}
        err_holder = {}
        status_msg = ["Apertura finestra di login su YouTube Music...\nAccedi con il tuo account Google nel browser."]

        def _on_progress(msg: str) -> None:
            status_msg[0] = f"{msg}\nAccedi con il tuo account Google nel browser."

        def _worker() -> None:
            try:
                res = ms.login_with_browser_window(
                    timeout_sec=180,
                    cancel_event=cancel_event,
                    progress_cb=_on_progress,
                )
                res_holder["res"] = res
            except Exception as e:
                err_holder["err"] = str(e)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

        def _poll() -> None:
            if not self.isVisible():
                cancel_event.set()
                progress.close()
                return
            progress.setLabelText(status_msg[0])
            if thread.is_alive():
                QTimer.singleShot(250, _poll)
                return
            self._active_ytm_cancel_event = None
            progress.close()
            if "res" in res_holder:
                self._update_ytm_status_display()
                QMessageBox.information(
                    self,
                    "Accesso Riuscito",
                    "Account Google / YouTube Music collegato con successo!\n"
                    "L'accesso rimarrà memorizzato permanentemente.",
                )
            elif "err" in err_holder:
                err_msg = err_holder["err"]
                if "annullato" not in err_msg.lower():
                    QMessageBox.warning(self, "Accesso Non Completato", f"{err_msg}")

        QTimer.singleShot(250, _poll)

    def _disconnect_ytmusic(self) -> None:
        reply = QMessageBox.question(
            self,
            "Disconnetti YouTube Music",
            "Vuoi davvero disconnettere l'account Google da Bardo AI?\n"
            "L'app tornerà in modalità ospite standard.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            ms = getattr(self, "music_service", None)
            if ms:
                ms.disconnect_account()
            self._update_ytm_status_display()
            QMessageBox.information(self, "Disconnesso", "Account disconnesso con successo.")

    def _test_ytmusic(self) -> None:
        ms = getattr(self, "music_service", None)
        if ms is None:
            ms = MusicService(YtDlpManager())
            self.music_service = ms
        try:
            client = ms._client()
            if client is None:
                QMessageBox.critical(self, "Errore", "Impossibile inizializzare il client YouTube Music.")
                return
            if ms.is_authenticated:
                pls = ms.get_user_playlists(limit=5)
                pl_info = f"Trovate {len(pls)} playlist personali." if pls else "Libreria personale accessibile."
                QMessageBox.information(
                    self,
                    "Connessione Verificata",
                    f"✅ Connesso a YouTube Music con successo!\n{pl_info}",
                )
            else:
                tracks = ms.search_tracks("fantasy tavern", limit=1)
                if tracks:
                    QMessageBox.information(
                        self,
                        "Connessione Verificata",
                        "✅ YouTube Music è attivo e funzionante in modalità ospite!",
                    )
                else:
                    QMessageBox.warning(self, "Verifica", "Nessun risultato ricevuto da YouTube Music.")
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Verifica connessione fallita: {e}")

    def _save_manual_ytm_headers(self) -> None:
        text = self.txt_manual_headers.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "Attenzione", "Incolla prima i cookie o gli headers nel riquadro.")
            return
        ms = getattr(self, "music_service", None)
        if ms is None:
            ms = MusicService(YtDlpManager())
            self.music_service = ms
        try:
            ms.save_manual_headers(text)
            self._update_ytm_status_display()
            self.txt_manual_headers.clear()
            QMessageBox.information(self, "Successo", "Cookie salvati con successo! Account collegato.")
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Impossibile salvare i cookie: {e}")

    # ================================================================ Tab AI
    def _build_ai_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # Provider Selector
        prov_row = QHBoxLayout()
        lbl_prov = QLabel("<b>Modalità Regia AI:</b>")
        self.combo_provider = QComboBox()
        self.combo_provider.addItem("Regole Semantiche Locali (100% Offline - Zero Cloud)", "keywords")
        self.combo_provider.addItem("Google Gemini (Cloud API)", "gemini")
        self.combo_provider.addItem("OpenAI (ChatGPT API)", "openai")
        self.combo_provider.addItem("Ollama (Server Locale)", "ollama")

        curr_prov = self.analyzer_cfg.get("ai_provider", "keywords")
        idx = self.combo_provider.findData(curr_prov)
        if idx < 0:
            idx = self.combo_provider.findText(curr_prov)
        if idx >= 0:
            self.combo_provider.setCurrentIndex(idx)
        else:
            self.combo_provider.setCurrentIndex(0)

        prov_row.addWidget(lbl_prov)
        prov_row.addWidget(self.combo_provider, 1)
        layout.addLayout(prov_row)

        # 1. Box Keywords (Offline)
        self.box_keywords = QGroupBox("Modalità 100% Offline e Privata")
        kw_layout = QVBoxLayout(self.box_keywords)
        kw_info = QLabel(
            "<b>✓ Regole Locali Attive:</b><br>"
            "Bardo AI analizza il contesto del tavolo e il parlato in tempo reale tramite modelli vocali locali "
            "(Silero VAD + Vosk / Whisper) e il motore euristico italiano con parsing delle negazioni.<br><br>"
            "• Nessuna API Key o connessione cloud richiesta.<br>"
            "• Nessun dato inviato all'esterno (privacy totale al tavolo).<br>"
            "• Latenza immediata per cambi scena ed effetti sonori."
        )
        kw_info.setWordWrap(True)
        kw_info.setStyleSheet("color: #a7f3d0; font-size: 11px;")
        kw_layout.addWidget(kw_info)
        layout.addWidget(self.box_keywords)

        # 2. Box Gemini
        self.box_gemini = QGroupBox("Configurazione Google Gemini")
        gemini_layout = QFormLayout(self.box_gemini)
        gemini_layout.setSpacing(8)
        self.txt_gemini_key = QLineEdit()
        self.txt_gemini_key.setEchoMode(QLineEdit.Password)
        self.txt_gemini_key.setText(SecretVault.get_secret("gemini_api_key", ""))
        self.txt_gemini_key.setPlaceholderText("Incolla API Key Gemini...")
        gemini_layout.addRow("Chiave API Gemini:", self.txt_gemini_key)

        self.txt_gemini_model = QLineEdit()
        self.txt_gemini_model.setText(self.analyzer_cfg.get("gemini_model", "gemini-2.5-flash"))
        gemini_layout.addRow("Modello Gemini:", self.txt_gemini_model)
        layout.addWidget(self.box_gemini)

        # 3. Box OpenAI
        self.box_openai = QGroupBox("Configurazione OpenAI")
        openai_layout = QFormLayout(self.box_openai)
        openai_layout.setSpacing(8)
        self.txt_openai_key = QLineEdit()
        self.txt_openai_key.setEchoMode(QLineEdit.Password)
        self.txt_openai_key.setText(SecretVault.get_secret("openai_api_key", ""))
        self.txt_openai_key.setPlaceholderText("sk-...")
        openai_layout.addRow("Chiave API OpenAI:", self.txt_openai_key)

        self.txt_openai_model = QLineEdit()
        self.txt_openai_model.setText(self.analyzer_cfg.get("openai_model", "gpt-4o-mini"))
        openai_layout.addRow("Modello OpenAI:", self.txt_openai_model)

        self.txt_openai_url = QLineEdit()
        self.txt_openai_url.setText(self.analyzer_cfg.get("openai_base_url", "https://api.openai.com/v1"))
        openai_layout.addRow("Base URL OpenAI:", self.txt_openai_url)
        layout.addWidget(self.box_openai)

        # 4. Box Ollama
        self.box_ollama = QGroupBox("Configurazione Ollama (Locale)")
        ollama_layout = QFormLayout(self.box_ollama)
        ollama_layout.setSpacing(8)
        self.txt_ollama_url = QLineEdit()
        self.txt_ollama_url.setText(self.analyzer_cfg.get("ollama_url", "http://localhost:11434"))
        ollama_layout.addRow("URL Server Ollama:", self.txt_ollama_url)

        self.txt_ollama_model = QLineEdit()
        self.txt_ollama_model.setText(self.analyzer_cfg.get("ollama_model", "llama3.2"))
        ollama_layout.addRow("Modello Ollama:", self.txt_ollama_model)
        layout.addWidget(self.box_ollama)

        # Parametri Regia (Comuni a tutte le modalità)
        self.box_regia = QGroupBox("Parametri Regia Musicale")
        regia_layout = QFormLayout(self.box_regia)
        regia_layout.setSpacing(8)

        self.spin_cooldown = QSpinBox()
        self.spin_cooldown.setRange(5, 60)
        self.spin_cooldown.setValue(int(self.analyzer_cfg.get("cooldown_seconds", 18)))
        regia_layout.addRow("Cooldown Regia (sec):", self.spin_cooldown)

        self.spin_min_dur = QDoubleSpinBox()
        self.spin_min_dur.setRange(3.0, 30.0)
        self.spin_min_dur.setValue(float(self.analyzer_cfg.get("min_scene_duration_seconds", 8.0)))
        regia_layout.addRow("Durata Minima Scena (sec):", self.spin_min_dur)

        self.spin_hysteresis = QDoubleSpinBox()
        self.spin_hysteresis.setRange(10.0, 60.0)
        self.spin_hysteresis.setValue(float(self.analyzer_cfg.get("hysteresis_window_seconds", 25.0)))
        regia_layout.addRow("Finestra Isteresi Calma (sec):", self.spin_hysteresis)

        layout.addWidget(self.box_regia)
        layout.addStretch()

        self.combo_provider.currentIndexChanged.connect(self._on_ai_provider_changed)
        self._on_ai_provider_changed()

        self.tab_widget.addTab(tab, "Intelligenza Artificiale")

    def _on_ai_provider_changed(self) -> None:
        prov = self.combo_provider.currentData() or self.combo_provider.currentText()
        self.box_keywords.setVisible(prov == "keywords")
        self.box_gemini.setVisible(prov == "gemini")
        self.box_openai.setVisible(prov == "openai")
        self.box_ollama.setVisible(prov == "ollama")

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
        # 1. Salva i segreti in SecretVault (o rimuovili se svuotati)
        gemini_k = self.txt_gemini_key.text().strip()
        SecretVault.set_secret("gemini_api_key", gemini_k)

        openai_k = self.txt_openai_key.text().strip()
        SecretVault.set_secret("openai_api_key", openai_k)

        # 2. Aggiorna configurazione
        prov = self.combo_provider.currentData() or self.combo_provider.currentText()
        self.analyzer_cfg["ai_provider"] = prov
        self.analyzer_cfg["gemini_api_key"] = gemini_k
        self.analyzer_cfg["openai_api_key"] = openai_k
        self.analyzer_cfg["gemini_model"] = self.txt_gemini_model.text().strip() or "gemini-2.5-flash"
        self.analyzer_cfg["openai_model"] = self.txt_openai_model.text().strip() or "gpt-4o-mini"
        self.analyzer_cfg["openai_base_url"] = self.txt_openai_url.text().strip() or "https://api.openai.com/v1"
        self.analyzer_cfg["ollama_url"] = self.txt_ollama_url.text().strip() or "http://localhost:11434"
        self.analyzer_cfg["ollama_model"] = self.txt_ollama_model.text().strip() or "llama3.2"

        self.analyzer_cfg["cooldown_seconds"] = self.spin_cooldown.value()
        self.analyzer_cfg["min_scene_duration_seconds"] = self.spin_min_dur.value()
        self.analyzer_cfg["hysteresis_window_seconds"] = self.spin_hysteresis.value()

        self.audio_cfg["crossfade_seconds"] = self.spin_crossfade.value()
        self.audio_cfg["cache_max_mb"] = self.spin_cache_mb.value()

        self.config["analyzer"] = self.analyzer_cfg
        self.config["audio"] = self.audio_cfg

        ConfigManager.save(self.config)
        self.accept()
