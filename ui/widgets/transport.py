"""
Barra di controllo della riproduzione musicale (Transport Bar) in PySide6 per Bardo AI.
Include controlli per play/pause, cambio traccia, volume musica e SFX,
blocco scena, selezione dispositivi di uscita audio e modalità mini-player.
Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

__author__ = "Paolo Basta"


class TransportBar(QFrame):
    play_pause_clicked = Signal()
    skip_clicked = Signal()
    music_volume_changed = Signal(int)
    sfx_volume_changed = Signal(int)
    lock_toggled = Signal(bool)
    output_device_changed = Signal(object)  # Optional[int]
    restore_clicked = Signal()
    mic_toggled = Signal(bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setFixedHeight(82)

        self._main_layout = QHBoxLayout(self)
        self._main_layout.setContentsMargins(16, 10, 16, 10)
        self._main_layout.setSpacing(16)

        # 1. Info Brano in Riproduzione (Sinistra)
        track_info_box = QVBoxLayout()
        track_info_box.setSpacing(2)

        self.track_title_label = QLabel("Nessun brano in riproduzione")
        self.track_title_label.setStyleSheet("font-weight: 600; font-size: 14px; color: #f8fafc;")
        self.track_title_label.setMaximumWidth(280)

        self.track_artist_label = QLabel("In attesa della scena...")
        self.track_artist_label.setStyleSheet("font-size: 12px; color: #94a3b8;")

        track_info_box.addWidget(self.track_title_label)
        track_info_box.addWidget(self.track_artist_label)
        self._main_layout.addLayout(track_info_box)

        # Separatore verticale 1
        self.sep1 = QFrame()
        self.sep1.setFrameShape(QFrame.VLine)
        self.sep1.setStyleSheet("color: #1e293b;")
        self._main_layout.addWidget(self.sep1)

        # 2. Pulsanti Trasporto (Centro-Sinistra)
        ctrl_layout = QHBoxLayout()
        ctrl_layout.setSpacing(8)

        self.btn_play_pause = QPushButton("⏸")
        self.btn_play_pause.setToolTip("Riproduci / Pausa (Ctrl+Spazio)")
        self.btn_play_pause.setFixedSize(40, 40)
        self.btn_play_pause.setStyleSheet("font-size: 16px; border-radius: 20px; background-color: #3b82f6;")
        self.btn_play_pause.clicked.connect(self.play_pause_clicked.emit)

        self.btn_skip = QPushButton("⏭")
        self.btn_skip.setToolTip("Passa alla traccia successiva (Ctrl+Destra)")
        self.btn_skip.setFixedSize(36, 36)
        self.btn_skip.setStyleSheet("font-size: 14px; border-radius: 18px;")
        self.btn_skip.clicked.connect(self.skip_clicked.emit)

        ctrl_layout.addWidget(self.btn_play_pause)
        ctrl_layout.addWidget(self.btn_skip)
        self._main_layout.addLayout(ctrl_layout)

        # 3. Slider Volume Musica (Centro)
        self.vol_music_container = QWidget()
        vol_music_box = QVBoxLayout(self.vol_music_container)
        vol_music_box.setContentsMargins(0, 0, 0, 0)
        vol_music_box.setSpacing(2)
        lbl_music_hdr = QHBoxLayout()
        lbl_music_hdr.addWidget(QLabel("🎵 Musica"))
        self.lbl_music_pct = QLabel("75%")
        self.lbl_music_pct.setStyleSheet("color: #94a3b8; font-size: 11px;")
        lbl_music_hdr.addStretch()
        lbl_music_hdr.addWidget(self.lbl_music_pct)

        self.slider_music = QSlider(Qt.Horizontal)
        self.slider_music.setToolTip("Volume Musica (Ctrl+Su / Ctrl+Giù)")
        self.slider_music.setRange(0, 100)
        self.slider_music.setValue(75)
        self.slider_music.setFixedWidth(140)
        self.slider_music.valueChanged.connect(self._on_music_vol_changed)

        vol_music_box.addLayout(lbl_music_hdr)
        vol_music_box.addWidget(self.slider_music)
        self._main_layout.addWidget(self.vol_music_container)

        # 4. Slider Volume SFX (Centro-Destra)
        self.vol_sfx_container = QWidget()
        vol_sfx_box = QVBoxLayout(self.vol_sfx_container)
        vol_sfx_box.setContentsMargins(0, 0, 0, 0)
        vol_sfx_box.setSpacing(2)
        lbl_sfx_hdr = QHBoxLayout()
        lbl_sfx_hdr.addWidget(QLabel("💥 SFX"))
        self.lbl_sfx_pct = QLabel("80%")
        self.lbl_sfx_pct.setStyleSheet("color: #94a3b8; font-size: 11px;")
        lbl_sfx_hdr.addStretch()
        lbl_sfx_hdr.addWidget(self.lbl_sfx_pct)

        self.slider_sfx = QSlider(Qt.Horizontal)
        self.slider_sfx.setRange(0, 100)
        self.slider_sfx.setValue(80)
        self.slider_sfx.setFixedWidth(140)
        self.slider_sfx.valueChanged.connect(self._on_sfx_vol_changed)

        vol_sfx_box.addLayout(lbl_sfx_hdr)
        vol_sfx_box.addWidget(self.slider_sfx)
        self._main_layout.addWidget(self.vol_sfx_container)

        # 4.5 Selettore Dispositivo di Uscita Audio (Cuffie / Casse / Virtual Cable)
        self.out_dev_container = QWidget()
        out_dev_box = QVBoxLayout(self.out_dev_container)
        out_dev_box.setContentsMargins(0, 0, 0, 0)
        out_dev_box.setSpacing(2)
        lbl_out_hdr = QLabel("🔊 Uscita Audio")
        lbl_out_hdr.setStyleSheet("color: #94a3b8; font-size: 11px;")
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(160)
        self.device_combo.setMaximumWidth(220)
        self.device_combo.setToolTip("Dispositivo di uscita audio per musica ed effetti sonori")
        self.device_combo.currentIndexChanged.connect(self._on_device_selected)
        out_dev_box.addWidget(lbl_out_hdr)
        out_dev_box.addWidget(self.device_combo)
        self._main_layout.addWidget(self.out_dev_container)

        # Separatore verticale 2
        self.sep2 = QFrame()
        self.sep2.setFrameShape(QFrame.VLine)
        self.sep2.setStyleSheet("color: #1e293b;")
        self._main_layout.addWidget(self.sep2)

        # 5. Pulsante Lock Regia e Badge Cooldown (Destra)
        self.lock_container = QWidget()
        lock_box = QVBoxLayout(self.lock_container)
        lock_box.setContentsMargins(0, 0, 0, 0)
        lock_box.setSpacing(4)

        self.btn_lock = QPushButton("🔓 Sbloccato")
        self.btn_lock.setObjectName("lockBtn")
        self.btn_lock.setCheckable(True)
        self.btn_lock.setChecked(False)
        self.btn_lock.toggled.connect(self._on_lock_toggled)

        self.lbl_cooldown = QLabel("🟢 Pronto")
        self.lbl_cooldown.setAlignment(Qt.AlignCenter)
        self.lbl_cooldown.setStyleSheet("font-size: 11px; color: #10b981; font-weight: 600;")

        lock_box.addWidget(self.btn_lock)
        lock_box.addWidget(self.lbl_cooldown)
        self._main_layout.addWidget(self.lock_container)

        # 6. Controlli dedicati al Mini-Player PiP (Nascosti in vista estesa)
        self.btn_mic_quick = QPushButton("🎙️")
        self.btn_mic_quick.setToolTip("Attiva / Disattiva Microfono Vocale (Ctrl+M)")
        self.btn_mic_quick.setFixedSize(36, 36)
        self.btn_mic_quick.setCheckable(True)
        self.btn_mic_quick.setChecked(True)
        self.btn_mic_quick.setStyleSheet("font-size: 16px; border-radius: 18px; background-color: #10b981; color: white;")
        self.btn_mic_quick.toggled.connect(self._on_quick_mic_toggled)
        self.btn_mic_quick.hide()
        self._main_layout.addWidget(self.btn_mic_quick)

        self.btn_restore = QPushButton("⤢")
        self.btn_restore.setToolTip("Ripristina finestra intera (Ctrl+F11)")
        self.btn_restore.setFixedSize(36, 36)
        self.btn_restore.setStyleSheet(
            "font-size: 16px; font-weight: bold; border-radius: 18px; background-color: #334155; color: #f8fafc;"
        )
        self.btn_restore.clicked.connect(self.restore_clicked.emit)
        self.btn_restore.hide()
        self._main_layout.addWidget(self.btn_restore)

    def populate_output_devices(self, devices: List[Dict[str, Any]]) -> None:
        """Popola il menu a tendina delle uscite audio senza emettere segnali spuri."""
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        for dev in devices:
            self.device_combo.addItem(dev["name"], dev["index"])
        self.device_combo.blockSignals(False)

    def select_device(self, device_index: Optional[int]) -> None:
        """Seleziona l'uscita audio indicata nel menu a tendina."""
        self.device_combo.blockSignals(True)
        idx = self.device_combo.findData(device_index)
        if idx >= 0:
            self.device_combo.setCurrentIndex(idx)
        else:
            self.device_combo.setCurrentIndex(0)
        self.device_combo.blockSignals(False)

    def _on_device_selected(self, index: int) -> None:
        dev_idx = self.device_combo.itemData(index)
        self.output_device_changed.emit(dev_idx)

    def _on_music_vol_changed(self, val: int) -> None:
        self.lbl_music_pct.setText(f"{val}%")
        self.music_volume_changed.emit(val)

    def _on_sfx_vol_changed(self, val: int) -> None:
        self.lbl_sfx_pct.setText(f"{val}%")
        self.sfx_volume_changed.emit(val)

    def _on_lock_toggled(self, checked: bool) -> None:
        if checked:
            self.btn_lock.setText("🔒 Bloccato")
            self.btn_lock.setStyleSheet("background-color: #ea580c; color: white; font-weight: bold;")
        else:
            self.btn_lock.setText("🔓 Sbloccato")
            self.btn_lock.setStyleSheet("")
        self.lock_toggled.emit(checked)

    def update_track(self, title: str, artist: str = "") -> None:
        self.track_title_label.setText(title or "Traccia audio")
        self.track_artist_label.setText(artist or "Bardo AI")
        self.btn_play_pause.setText("⏸")

    def set_playing_state(self, is_playing: bool) -> None:
        self.btn_play_pause.setText("⏸" if is_playing else "▶")

    def update_cooldown(self, remaining_sec: float) -> None:
        if remaining_sec <= 0.2:
            self.lbl_cooldown.setText("🟢 Pronto")
            self.lbl_cooldown.setStyleSheet("font-size: 11px; color: #10b981; font-weight: 600;")
        else:
            self.lbl_cooldown.setText(f"⏳ {remaining_sec:.0f}s")
            self.lbl_cooldown.setStyleSheet("font-size: 11px; color: #f59e0b; font-weight: 600;")

    def step_music_volume(self, delta: int) -> int:
        """Modifica il volume della musica di delta punti percentuali con clamping [0, 100]."""
        new_val = max(0, min(100, self.slider_music.value() + delta))
        self.slider_music.setValue(new_val)
        return new_val

    def set_music_volume(self, vol: int) -> None:
        """Imposta la posizione dello slider musica e aggiorna la percentuale senza emettere segnali ridondanti."""
        val = max(0, min(100, int(vol)))
        self.slider_music.blockSignals(True)
        self.slider_music.setValue(val)
        self.lbl_music_pct.setText(f"{val}%")
        self.slider_music.blockSignals(False)

    def set_sfx_volume(self, vol: int) -> None:
        """Imposta la posizione dello slider SFX e aggiorna la percentuale senza emettere segnali ridondanti."""
        val = max(0, min(100, int(vol)))
        self.slider_sfx.blockSignals(True)
        self.slider_sfx.setValue(val)
        self.lbl_sfx_pct.setText(f"{val}%")
        self.slider_sfx.blockSignals(False)

    def set_compact_mode(self, compact: bool) -> None:
        """Passa dalla modalità desktop estesa alla modalità compatta per Mini-Player PiP e viceversa."""
        if compact:
            self.setFixedHeight(72)
            self._main_layout.setContentsMargins(12, 6, 12, 6)
            self._main_layout.setSpacing(10)
            self.sep1.hide()
            self.vol_sfx_container.hide()
            self.out_dev_container.hide()
            self.sep2.hide()
            self.lock_container.hide()
            self.slider_music.setFixedWidth(100)
            self.track_title_label.setMaximumWidth(170)
            self.btn_mic_quick.show()
            self.btn_restore.show()
        else:
            self.setFixedHeight(82)
            self._main_layout.setContentsMargins(16, 10, 16, 10)
            self._main_layout.setSpacing(16)
            self.sep1.show()
            self.vol_sfx_container.show()
            self.out_dev_container.show()
            self.sep2.show()
            self.lock_container.show()
            self.slider_music.setFixedWidth(140)
            self.track_title_label.setMaximumWidth(280)
            self.btn_mic_quick.hide()
            self.btn_restore.hide()

    def _on_quick_mic_toggled(self, checked: bool) -> None:
        self._update_mic_quick_style(checked)
        self.mic_toggled.emit(checked)

    def _update_mic_quick_style(self, active: bool) -> None:
        if active:
            self.btn_mic_quick.setText("🎙️")
            self.btn_mic_quick.setStyleSheet(
                "font-size: 16px; border-radius: 18px; background-color: #10b981; color: white;"
            )
        else:
            self.btn_mic_quick.setText("🔇")
            self.btn_mic_quick.setStyleSheet(
                "font-size: 16px; border-radius: 18px; background-color: #ef4444; color: white;"
            )

    def set_mic_active(self, active: bool) -> None:
        """Aggiorna lo stato visivo del pulsante microfono rapido senza ri-emettere segnali."""
        self.btn_mic_quick.blockSignals(True)
        self.btn_mic_quick.setChecked(active)
        self._update_mic_quick_style(active)
        self.btn_mic_quick.blockSignals(False)
