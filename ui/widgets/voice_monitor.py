"""
Widget di monitoraggio vocale, VU-meter in tempo reale e trascrizione live in PySide6.
"""

from typing import Any, Dict, List
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class VoiceMonitorWidget(QFrame):
    device_changed = Signal(object)  # Optional[int]
    mic_toggled = Signal(bool)

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setFixedHeight(84)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(14, 10, 14, 10)
        main_layout.setSpacing(14)

        # 1. Selettore Microfono e Tasto Mute (Sinistra)
        left_box = QVBoxLayout()
        left_box.setSpacing(4)

        top_ctrl = QHBoxLayout()
        self.btn_mic_toggle = QPushButton("🎙️ Ascolto Attivo")
        self.btn_mic_toggle.setCheckable(True)
        self.btn_mic_toggle.setChecked(True)
        self.btn_mic_toggle.setStyleSheet("font-weight: 600; font-size: 11px; background-color: #10b981; color: white;")
        self.btn_mic_toggle.toggled.connect(self._on_mic_toggled)
        top_ctrl.addWidget(self.btn_mic_toggle)

        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(180)
        self.device_combo.currentIndexChanged.connect(self._on_device_selected)
        top_ctrl.addWidget(self.device_combo)
        left_box.addLayout(top_ctrl)

        # 2. VU Meter (Barra di livello audio)
        vu_box = QHBoxLayout()
        vu_box.setSpacing(6)
        vu_box.addWidget(QLabel("LIVELLO:"))
        self.vu_bar = QProgressBar()
        self.vu_bar.setRange(0, 100)
        self.vu_bar.setValue(0)
        self.vu_bar.setTextVisible(False)
        self.vu_bar.setFixedHeight(8)
        self.vu_bar.setStyleSheet(
            "QProgressBar { background-color: #1e293b; border-radius: 4px; border: none; }"
            "QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10b981, stop:0.7 #38bdf8, stop:0.95 #ef4444); border-radius: 4px; }"
        )
        vu_box.addWidget(self.vu_bar)
        left_box.addLayout(vu_box)

        main_layout.addLayout(left_box)

        # Separatore verticale
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color: #1e293b;")
        main_layout.addWidget(sep)

        # 3. Trascrizione Live e Badge Atmosfera (Destra)
        transcript_box = QVBoxLayout()
        transcript_box.setSpacing(2)

        lbl_hdr = QHBoxLayout()
        lbl_hdr.addWidget(QLabel("TRASCRIZIONE VOCALE"))
        self.badge_status = QLabel("In ascolto offline")
        self.badge_status.setStyleSheet("font-size: 10px; color: #94a3b8;")
        lbl_hdr.addStretch()
        lbl_hdr.addWidget(self.badge_status)
        transcript_box.addLayout(lbl_hdr)

        self.lbl_transcript = QLabel("Parla liberamente durante la sessione...")
        self.lbl_transcript.setStyleSheet(
            "background-color: #0b0f19; padding: 4px 8px; border-radius: 6px; font-style: italic; color: #e2e8f0; font-size: 12px;"
        )
        transcript_box.addWidget(self.lbl_transcript)

        main_layout.addLayout(transcript_box)

    def populate_devices(self, devices: List[Dict[str, Any]]) -> None:
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        for dev in devices:
            self.device_combo.addItem(dev["name"], dev["index"])
        self.device_combo.blockSignals(False)

    def _on_device_selected(self, index: int) -> None:
        dev_idx = self.device_combo.itemData(index)
        self.device_changed.emit(dev_idx)

    def _on_mic_toggled(self, active: bool) -> None:
        if active:
            self.btn_mic_toggle.setText("🎙️ Ascolto Attivo")
            self.btn_mic_toggle.setStyleSheet("font-weight: 600; font-size: 11px; background-color: #10b981; color: white;")
        else:
            self.btn_mic_toggle.setText("🔇 Microfono Muto")
            self.btn_mic_toggle.setStyleSheet("font-weight: 600; font-size: 11px; background-color: #475569; color: #cbd5e1;")
            self.set_level(0.0)
        self.mic_toggled.emit(active)

    def set_level(self, level: float) -> None:
        val = int(min(100, max(0, level * 100)))
        self.vu_bar.setValue(val)

    def set_transcript(self, text: str, is_partial: bool = False) -> None:
        if is_partial:
            self.lbl_transcript.setText(f"🗣️ {text} ...")
            self.lbl_transcript.setStyleSheet(
                "background-color: #0b0f19; padding: 4px 8px; border-radius: 6px; font-style: italic; color: #94a3b8; font-size: 12px;"
            )
        else:
            self.lbl_transcript.setText(f"💬 \"{text}\"")
            self.lbl_transcript.setStyleSheet(
                "background-color: #0b0f19; padding: 4px 8px; border-radius: 6px; font-weight: 500; color: #f8fafc; font-size: 12px; border: 1px solid #3b82f6;"
            )

    def set_status(self, status: str) -> None:
        self.badge_status.setText(status)
