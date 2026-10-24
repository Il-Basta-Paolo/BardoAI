"""
Test per il VU-Meter avanzato con Noise Gate visivo in PySide6.
Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

import os
from typing import Generator
import pytest
from PySide6.QtWidgets import QApplication

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

from ui.widgets.voice_monitor import NoiseGateBar, VoiceMonitorWidget


@pytest.fixture(scope="module")
def qapp() -> Generator[QApplication, None, None]:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_noise_gate_bar_defaults(qapp):
    """Verifica le proprietà di default e il clamping di NoiseGateBar."""
    bar = NoiseGateBar(threshold=20)
    assert bar.threshold == 20
    assert bar.value() == 0
    assert not bar.is_gate_open
    assert "20%" in bar.toolTip()

    # Clamping
    bar.set_threshold(150)
    assert bar.threshold == 99
    bar.set_threshold(-5)
    assert bar.threshold == 1


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


def test_noise_gate_bar_paint_event_offscreen(qapp):
    """Verifica che il rendering personalizzato di paintEvent avvenga senza errori grafici né eccezioni."""
    bar = NoiseGateBar(threshold=20)
    bar.resize(150, 10)
    bar.show()

    # Test paint con gate chiuso (sotto soglia)
    bar.setValue(10)
    bar.repaint()

    # Test paint con gate aperto (sopra soglia)
    bar.setValue(45)
    bar.repaint()

    # Test paint a zero
    bar.setValue(0)
    bar.repaint()
