"""
Widget di monitoraggio vocale, VU-meter in tempo reale e trascrizione live in PySide6.
"""

from typing import Any, Dict, List
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
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


class NoiseGateBar(QProgressBar):
    """Barra di livello audio (VU-Meter) con indicatore visivo della soglia di Noise Gate."""

    def __init__(self, parent: QWidget = None, threshold: int = 20) -> None:
        super().__init__(parent)
        self.threshold = max(1, min(99, threshold))
        self.setRange(0, 100)
        self.setValue(0)
        self.setTextVisible(False)
        self.setFixedHeight(10)
        self.setToolTip(
            f"VU-Meter con soglia Noise Gate (linea al {self.threshold}%).\n"
            "Sotto la linea: rumore di fondo filtrato.\n"
            "Sopra la linea: voce del Master riconosciuta."
        )

    def set_threshold(self, threshold: int) -> None:
        self.threshold = max(1, min(99, threshold))
        self.setToolTip(
            f"VU-Meter con soglia Noise Gate (linea al {self.threshold}%).\n"
            "Sotto la linea: rumore di fondo filtrato.\n"
            "Sopra la linea: voce del Master riconosciuta."
        )
        self.update()

    @property
    def is_gate_open(self) -> bool:
        return self.value() >= self.threshold

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = float(self.width())
        h = float(self.height())
        val = float(self.value())

        # 1. Sfondo scuro (track)
        bg_rect = QRectF(0, 0, w, h)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#1e293b"))
        painter.drawRoundedRect(bg_rect, 4, 4)

        # 2. Barra di riempimento (progress fill)
        if val > 0:
            fill_w = max(4.0, (val / 100.0) * w)
            fill_rect = QRectF(0, 0, fill_w, h)

            if val < self.threshold:
                # Sotto soglia: colore slate/ambra spento (rumore ambiente)
                painter.setBrush(QColor("#64748b"))
            else:
                # Sopra soglia: gradiente brillante da verde a ciano e rosso per picchi
                grad = QLinearGradient(0, 0, w, 0)
                grad.setColorAt(0.0, QColor("#10b981"))
                grad.setColorAt(0.7, QColor("#06b6d4"))
                grad.setColorAt(0.95, QColor("#ef4444"))
                painter.setBrush(grad)

            painter.drawRoundedRect(fill_rect, 4, 4)

        # 3. Tacca visiva della soglia (Noise Gate Needle)
        gate_x = (self.threshold / 100.0) * w
        pen = QPen(QColor("#f8fafc"))
        pen.setWidthF(1.5)
        painter.setPen(pen)
        painter.drawLine(gate_x, 0.0, gate_x, h)

        painter.end()


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
        self.btn_mic_toggle.setToolTip("Attiva o disattiva il microfono (Ctrl+M)")
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

        # 2. VU Meter (Barra di livello audio con soglia Noise Gate)
        vu_box = QHBoxLayout()
        vu_box.setSpacing(6)
        lbl_mic_title = QLabel("LIVELLO:")
        lbl_mic_title.setStyleSheet("font-size: 10px; font-weight: 600; color: #94a3b8;")
        vu_box.addWidget(lbl_mic_title)

        self.vu_bar = NoiseGateBar(threshold=20)
        vu_box.addWidget(self.vu_bar, stretch=1)

        self.lbl_gate_status = QLabel("SOTTO SOGLIA")
        self.lbl_gate_status.setStyleSheet(
            "font-size: 9px; font-weight: 700; color: #64748b; background-color: #0f172a; "
            "padding: 1px 5px; border-radius: 3px;"
        )
        self.lbl_gate_status.setToolTip(
            "Stato del filtro rumore (Noise Gate): attiva il riconoscimento solo oltre la soglia."
        )
        vu_box.addWidget(self.lbl_gate_status)

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
        if self.vu_bar.is_gate_open:
            self.lbl_gate_status.setText("🎙️ VOCE")
            self.lbl_gate_status.setStyleSheet(
                "font-size: 9px; font-weight: 700; color: #10b981; background-color: #064e3b; "
                "padding: 1px 5px; border-radius: 3px;"
            )
        else:
            self.lbl_gate_status.setText("SOTTO SOGLIA")
            self.lbl_gate_status.setStyleSheet(
                "font-size: 9px; font-weight: 700; color: #64748b; background-color: #0f172a; "
                "padding: 1px 5px; border-radius: 3px;"
            )

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
