"""
Test per il VU-Meter avanzato con Noise Gate visivo e interattivo in PySide6.
Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

import os
from typing import Generator
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

from ui.widgets.voice_monitor import NoiseGateBar, VoiceMonitorWidget
from voice_listener import ContinuousVoiceListener


@pytest.fixture(scope="module")
def qapp() -> Generator[QApplication, None, None]:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_noise_gate_bar_defaults(qapp):
    """Verifica le proprietà di default e il clamping [5-85%] di NoiseGateBar."""
    bar = NoiseGateBar(threshold=20)
    assert bar.threshold == 20
    assert bar.value() == 0
    assert not bar.is_gate_open
    assert "20%" in bar.toolTip()

    # Clamping range sicuro [5% - 85%]
    bar.set_threshold(150)
    assert bar.threshold == 85
    bar.set_threshold(-5)
    assert bar.threshold == 5


def test_noise_gate_bar_open_close(qapp):
    """Verifica l'apertura e chiusura del Noise Gate in base al livello audio."""
    bar = NoiseGateBar(threshold=25)

    bar.setValue(10)
    assert not bar.is_gate_open

    bar.setValue(24)
    assert not bar.is_gate_open

    bar.setValue(25)
    assert bar.is_gate_open

    bar.setValue(80)
    assert bar.is_gate_open


def test_noise_gate_bar_mouse_drag_and_signals(qapp):
    """Verifica che il click e il trascinamento del mouse sulla barra aggiornino la soglia ed emettano il segnale."""
    bar = NoiseGateBar(threshold=20)
    bar.resize(200, 12)

    received_thresholds = []
    bar.threshold_changed.connect(received_thresholds.append)

    # 1. Click a X = 80 (su 200px corrisponde al 40%)
    pos_press = QPointF(80.0, 6.0)
    press_event = QMouseEvent(
        QEvent.MouseButtonPress,
        pos_press,
        pos_press,
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    bar.mousePressEvent(press_event)
    assert bar._dragging is True
    assert bar.threshold == 40
    assert received_thresholds == [40]

    # 2. Trascinamento a X = 120 (su 200px corrisponde al 60%)
    pos_move = QPointF(120.0, 6.0)
    move_event = QMouseEvent(
        QEvent.MouseMove,
        pos_move,
        pos_move,
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    bar.mouseMoveEvent(move_event)
    assert bar.threshold == 60
    assert received_thresholds == [40, 60]

    # 3. Rilascio del mouse
    release_event = QMouseEvent(
        QEvent.MouseButtonRelease,
        pos_move,
        pos_move,
        Qt.LeftButton,
        Qt.NoButton,
        Qt.NoModifier,
    )
    bar.mouseReleaseEvent(release_event)
    assert bar._dragging is False


def test_noise_gate_bar_mouse_clamping(qapp):
    """Verifica che il trascinamento oltre i limiti mantenga la soglia tra il 5% e l'85%."""
    bar = NoiseGateBar(threshold=20)
    bar.resize(200, 12)

    # Click quasi all'inizio (X=2px -> 1%)
    pos_low = QPointF(2.0, 6.0)
    press_low = QMouseEvent(
        QEvent.MouseButtonPress,
        pos_low,
        pos_low,
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    bar.mousePressEvent(press_low)
    assert bar.threshold == 5  # Clamped al minimo di sicurezza

    # Click all'estrema destra (X=198px -> 99%)
    pos_high = QPointF(198.0, 6.0)
    press_high = QMouseEvent(
        QEvent.MouseButtonPress,
        pos_high,
        pos_high,
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    bar.mousePressEvent(press_high)
    assert bar.threshold == 85  # Clamped al massimo di sicurezza


def test_voice_monitor_widget_threshold_feedback(qapp):
    """Verifica che VoiceMonitorWidget mostri il badge temporaneo SOGLIA: X% quando calibrato."""
    widget = VoiceMonitorWidget()
    received = []
    widget.threshold_changed.connect(received.append)

    # Simulazione cambio soglia dalla barra
    widget.vu_bar.set_threshold(35)
    widget.vu_bar.threshold_changed.emit(35)

    assert received == [35]
    assert widget.lbl_gate_status.text() == "SOGLIA: 35%"
    assert widget._calibrating is True

    # Ripristino
    widget._restore_gate_label()
    assert widget._calibrating is False
    assert widget.lbl_gate_status.text() == "SOTTO SOGLIA"


def test_voice_monitor_widget_level_and_label(qapp):
    """Verifica che VoiceMonitorWidget aggiorni reattivamente sia la barra che l'etichetta del Noise Gate."""
    widget = VoiceMonitorWidget()

    # Stato iniziale
    assert widget.vu_bar.value() == 0
    assert widget.lbl_gate_status.text() == "SOTTO SOGLIA"

    # Livello sotto soglia (es. 10% di rumore dadi/respiro)
    widget.set_level(0.10)
    assert widget.vu_bar.value() == 10
    assert widget.lbl_gate_status.text() == "SOTTO SOGLIA"

    # Livello sopra soglia (es. 35% voce del DM)
    widget.set_level(0.35)
    assert widget.vu_bar.value() == 35
    assert widget.lbl_gate_status.text() == "🎙️ VOCE"

    # Ritorno al silenzio
    widget.set_level(0.0)
    assert widget.vu_bar.value() == 0
    assert widget.lbl_gate_status.text() == "SOTTO SOGLIA"


def test_voice_listener_gate_threshold():
    """Verifica che ContinuousVoiceListener riceva e mantenga la soglia del Noise Gate."""
    from unittest.mock import patch

    with patch.object(ContinuousVoiceListener, "_init_models_async"):
        listener = ContinuousVoiceListener(
            on_transcript=lambda t: None,
            use_whisper=False,
            gate_threshold=30,
        )
        assert listener.gate_threshold == 30

        listener.set_gate_threshold(50)
        assert listener.gate_threshold == 50

        # Clamping
        listener.set_gate_threshold(200)
        assert listener.gate_threshold == 85
        listener.set_gate_threshold(-50)
        assert listener.gate_threshold == 5


def test_noise_gate_bar_paint_event_offscreen(qapp):
    """Verifica che il rendering personalizzato di paintEvent avvenga senza errori grafici né eccezioni."""
    bar = NoiseGateBar(threshold=20)
    bar.resize(150, 12)
    bar.show()

    # Test paint con gate chiuso (sotto soglia)
    bar.setValue(10)
    bar.repaint()

    # Test paint con gate aperto (sopra soglia)
    bar.setValue(45)
    bar.repaint()

    # Test paint durante trascinamento
    bar._dragging = True
    bar.repaint()
    bar._dragging = False

    # Test paint a zero
    bar.setValue(0)
    bar.repaint()
