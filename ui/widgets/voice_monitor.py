"""
Widget di monitoraggio vocale, VU-meter in tempo reale e trascrizione live in PySide6 per Bardo AI.
Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from PySide6.QtCore import QRectF, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

__author__ = "Paolo Basta"


class NoiseGateBar(QProgressBar):
    """
    Barra di livello audio (VU-Meter) con soglia di Noise Gate interattiva e regolabile col mouse.
    Permette al Master di calibrare la sensibilità trascinando o cliccando la maniglia della soglia.
    """

    threshold_changed = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None, threshold: int = 20) -> None:
        super().__init__(parent)
        self.threshold = max(5, min(85, threshold))
        self._dragging = False
        self._hovering_handle = False

        self.setRange(0, 100)
        self.setValue(0)
        self.setTextVisible(False)
        self.setFixedHeight(12)
        self.setMouseTracking(True)
        self._update_tooltip()

    def _update_tooltip(self) -> None:
        self.setToolTip(
            f"Soglia Noise Gate: {self.threshold}%\n"
            "• Trascina o clicca per regolare la sensibilità.\n"
            "• Sotto la linea: rumore filtrato (dadi, respiro).\n"
            "• Sopra la linea: voce del Master riconosciuta."
        )

    def set_threshold(self, threshold: int) -> None:
        clamped = max(5, min(85, threshold))
        if clamped != self.threshold:
            self.threshold = clamped
            self._update_tooltip()
            self.update()

    @property
    def is_gate_open(self) -> bool:
        return self.value() >= self.threshold

    def _pos_to_threshold(self, x: float) -> int:
        w = max(1.0, float(self.width()))
        ratio = x / w
        val = int(round(ratio * 100.0))
        return max(5, min(85, val))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._dragging = True
            new_th = self._pos_to_threshold(event.position().x())
            self.set_threshold(new_th)
            self.threshold_changed.emit(self.threshold)
            QToolTip.showText(event.globalPosition().toPoint(), f"Soglia Noise Gate: {self.threshold}%", self)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos_x = event.position().x()
        w = float(self.width())
        gate_x = (self.threshold / 100.0) * w

        if self._dragging:
            new_th = self._pos_to_threshold(pos_x)
            if new_th != self.threshold:
                self.set_threshold(new_th)
                self.threshold_changed.emit(self.threshold)
            QToolTip.showText(event.globalPosition().toPoint(), f"Soglia Noise Gate: {self.threshold}%", self)
            self.setCursor(Qt.SizeHorCursor)
            event.accept()
            return

        # Rilevamento hover sulla maniglietta (entro 7px dalla soglia)
        if abs(pos_x - gate_x) <= 7.0:
            self._hovering_handle = True
            self.setCursor(Qt.SizeHorCursor)
        else:
            self._hovering_handle = False
            self.setCursor(Qt.PointingHandCursor)

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._dragging = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        self._dragging = False
        self._hovering_handle = False
        self.setCursor(Qt.ArrowCursor)
        super().leaveEvent(event)

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
                # Sotto soglia: colore slate/neutro (rumore di fondo)
                painter.setBrush(QColor("#64748b"))
            else:
                # Sopra soglia: gradiente brillante da verde a ciano e picco rosso
                grad = QLinearGradient(0, 0, w, 0)
                grad.setColorAt(0.0, QColor("#10b981"))
                grad.setColorAt(0.7, QColor("#06b6d4"))
                grad.setColorAt(0.95, QColor("#ef4444"))
                painter.setBrush(grad)

            painter.drawRoundedRect(fill_rect, 4, 4)

        # 3. Tacca visiva e Maniglia della soglia (Noise Gate Slider Handle)
        gate_x = (self.threshold / 100.0) * w

        # Linea verticale di riferimento
        line_pen = QPen(QColor("#94a3b8"), 1.0, Qt.DashLine if not self._dragging else Qt.SolidLine)
        painter.setPen(line_pen)
        painter.drawLine(gate_x, 0.0, gate_x, h)

        # Cursore/Maniglia a slitta (afferrabile dal mouse)
        handle_w = 6.0
        handle_h = h
        handle_rect = QRectF(gate_x - (handle_w / 2.0), 0.5, handle_w, handle_h - 1.0)

        handle_color = QColor("#f8fafc") if (self._hovering_handle or self._dragging) else QColor("#cbd5e1")
        painter.setPen(QPen(QColor("#0f172a"), 1.0))
        painter.setBrush(handle_color)
        painter.drawRoundedRect(handle_rect, 2.0, 2.0)

        # Linea di grip centrale sulla maniglia
        painter.setPen(QPen(QColor("#64748b"), 1.0))
        painter.drawLine(gate_x, 2.5, gate_x, h - 2.5)

        painter.end()


class VoiceMonitorWidget(QFrame):
    device_changed = Signal(object)  # Optional[int]
    mic_toggled = Signal(bool)
    threshold_changed = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
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
        self.vu_bar.threshold_changed.connect(self._on_threshold_changed)
        vu_box.addWidget(self.vu_bar, stretch=1)

        self._calibrating = False
        self._feedback_timer = QTimer(self)
        self._feedback_timer.setSingleShot(True)
        self._feedback_timer.timeout.connect(self._restore_gate_label)

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

    def _on_threshold_changed(self, threshold: int) -> None:
        self._calibrating = True
        self.lbl_gate_status.setText(f"SOGLIA: {threshold}%")
        self.lbl_gate_status.setStyleSheet(
            "font-size: 9px; font-weight: 700; color: #38bdf8; background-color: #0c4a6e; "
            "padding: 1px 5px; border-radius: 3px;"
        )
        self._feedback_timer.start(1200)
        self.threshold_changed.emit(threshold)

    def _restore_gate_label(self) -> None:
        self._calibrating = False
        self.set_level(self.vu_bar.value() / 100.0)

    def set_gate_threshold(self, threshold: int) -> None:
        self.vu_bar.set_threshold(threshold)

    def set_level(self, level: float) -> None:
        val = int(min(100, max(0, level * 100)))
        self.vu_bar.setValue(val)
        if self._calibrating:
            return
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
