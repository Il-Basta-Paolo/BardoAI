"""
Test per il selettore del dispositivo di output audio in AudioEngine e TransportBar.
Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

import os
from typing import Generator
from unittest.mock import MagicMock, patch
import pytest
from PySide6.QtWidgets import QApplication

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

from audio_engine import AudioEngine
from storage import ConfigManager
from ui.widgets.transport import TransportBar


@pytest.fixture(scope="module")
def qapp() -> Generator[QApplication, None, None]:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def clean_config():
    orig_cfg = ConfigManager.load()
    yield
    ConfigManager.save(orig_cfg)


def test_audio_engine_get_output_devices():
    """Verifica che get_output_devices restituisca sempre il predefinito di sistema e i dispositivi rilevati."""
    devs = AudioEngine.get_output_devices()
    assert isinstance(devs, list)
    assert len(devs) >= 1
    # Il primo elemento deve essere l'uscita predefinita di Windows
    assert devs[0]["index"] is None
    assert "Predefinita" in devs[0]["name"]
    for d in devs:
        assert "index" in d
        assert "name" in d


def test_audio_engine_set_output_device_mock():
    """Verifica che il cambio dispositivo riavvii lo stream con l'indice specificato e gestisca il fallback."""
    engine = AudioEngine()

    with patch("sounddevice.OutputStream") as mock_stream_cls:
        mock_instance = MagicMock()
        mock_stream_cls.return_value = mock_instance

        # 1. Impostazione dispositivo specifico (es. 2)
        success = engine.set_output_device(2)
        assert engine.selected_device_index == 2
        assert success is True
        mock_stream_cls.assert_called_with(
            samplerate=48000,
            channels=2,
            dtype="float32",
            blocksize=1024,
            device=2,
            callback=engine._callback,
        )

        # 2. Ripristino uscita predefinita (None)
        success_none = engine.set_output_device(None)
        assert engine.selected_device_index is None
        assert success_none is True


def test_audio_engine_fallback_on_invalid_device():
    """Verifica che se un dispositivo fallisce l'apertura, AudioEngine ripieghi su None (default)."""
    engine = AudioEngine()

    call_count = 0

    def fake_stream(**kwargs):
        nonlocal call_count
        call_count += 1
        if kwargs.get("device") == 999:
            raise RuntimeError("Dispositivo audio non disponibile")
        return MagicMock()

    with patch("sounddevice.OutputStream", side_effect=fake_stream):
        engine.set_output_device(999)
        # Deve essere ripiegato su None dopo l'eccezione
        assert engine.selected_device_index is None
        assert call_count >= 2


def test_transport_bar_populate_and_select(qapp):
    """Verifica che TransportBar popoli correttamente il menu e selezioni il dispositivo richiesto."""
    bar = TransportBar()
    sample_devs = [
        {"index": None, "name": "🔊 Uscita Predefinita"},
        {"index": 2, "name": "🔊 Cuffie Gaming"},
        {"index": 5, "name": "🔊 VB-Audio Virtual Cable"},
    ]

    bar.populate_output_devices(sample_devs)
    assert bar.device_combo.count() == 3
    assert bar.device_combo.itemText(0) == "🔊 Uscita Predefinita"
    assert bar.device_combo.itemData(1) == 2

    # Selezione con indice esistente
    bar.select_device(5)
    assert bar.device_combo.currentData() == 5

    # Selezione con indice None
    bar.select_device(None)
    assert bar.device_combo.currentData() is None

    # Selezione con indice inesistente -> fallback su indice 0 (None)
    bar.select_device(9999)
    assert bar.device_combo.currentData() is None


def test_transport_bar_output_device_signal(qapp):
    """Verifica che il cambio manuale nel combobox emetta il segnale output_device_changed."""
    bar = TransportBar()
    sample_devs = [
        {"index": None, "name": "🔊 Predefinito"},
        {"index": 4, "name": "🔊 Casse Monitor"},
    ]
    bar.populate_output_devices(sample_devs)

    received = []
    bar.output_device_changed.connect(received.append)

    bar.device_combo.setCurrentIndex(1)
    assert received == [4]


def test_main_window_output_device_wiring(qapp, clean_config):
    """Verifica l'integrazione di MainWindow con il selettore di output e il salvataggio configurazione."""
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        with patch.object(win.audio_engine, "set_output_device") as mock_set_out:
            win._on_output_device_changed(3)
            mock_set_out.assert_called_with(3)

        assert win.config["audio"]["output_device"] == 3

        # Verifica persistenza
        reloaded = ConfigManager.load()
        assert reloaded.get("audio", {}).get("output_device") == 3
    finally:
        win.voice_listener.stop()
