"""
Test per le scorciatoie da tastiera rapide (Hotkeys) in PySide6.
Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

import os
from typing import Generator
from unittest.mock import MagicMock
import pytest

from PySide6.QtWidgets import QApplication

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

from storage import ConfigManager


@pytest.fixture(scope="module")
def qapp() -> Generator[QApplication, None, None]:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def clean_config():
    """Garantisce un file di configurazione pulito e ripristinato dopo ogni test."""
    orig_cfg = ConfigManager.load()
    yield
    ConfigManager.save(orig_cfg)


def test_shortcut_mic_toggle(qapp, clean_config):
    """Verifica che la scorciatoia Ctrl+M inverta correttamente lo stato del microfono."""
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        assert win.voice_monitor.btn_mic_toggle.isChecked() is True

        # Simula attivazione scorciatoia Ctrl+M
        win.shortcut_mic.activated.emit()
        assert win.voice_monitor.btn_mic_toggle.isChecked() is False
        assert "Muto" in win.voice_monitor.btn_mic_toggle.text()

        # Riattiva con Ctrl+M
        win.shortcut_mic.activated.emit()
        assert win.voice_monitor.btn_mic_toggle.isChecked() is True
        assert "Attivo" in win.voice_monitor.btn_mic_toggle.text()
    finally:
        win.close()


def test_shortcut_play_pause(qapp, clean_config):
    """Verifica che la scorciatoia Ctrl+Spazio alterni Play e Pausa nel motore audio."""
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        assert win.audio_engine.paused is False
        assert win.transport.btn_play_pause.text() == "⏸"

        # Simula Ctrl+Spazio -> Pausa
        win.shortcut_play_pause.activated.emit()
        assert win.audio_engine.paused is True
        assert win.transport.btn_play_pause.text() == "▶"

        # Simula di nuovo Ctrl+Spazio -> Riproduci
        win.shortcut_play_pause.activated.emit()
        assert win.audio_engine.paused is False
        assert win.transport.btn_play_pause.text() == "⏸"
    finally:
        win.close()


def test_shortcut_skip_track(qapp, clean_config):
    """Verifica che la scorciatoia Ctrl+Destra comandi il salto alla traccia successiva."""
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        win.director.current_mood_id = "combattimento"
        win.director.manual_select = MagicMock()

        # Simula Ctrl+Destra -> Skip
        win.shortcut_skip.activated.emit()
        win.director.manual_select.assert_called_once_with("combattimento")
    finally:
        win.close()


def test_shortcut_volume_controls_and_clamping(qapp, clean_config):
    """Verifica che Ctrl+Su e Ctrl+Giù regolino il volume master musica con clamping corretto."""
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        win.transport.slider_music.setValue(50)
        assert win.transport.slider_music.value() == 50

        # Ctrl+Su (+5%)
        win.shortcut_vol_up.activated.emit()
        assert win.transport.slider_music.value() == 55

        # Ctrl+Giù (-5%) due volte
        win.shortcut_vol_down.activated.emit()
        win.shortcut_vol_down.activated.emit()
        assert win.transport.slider_music.value() == 45

        # Clamping superiore a 100
        win.transport.slider_music.setValue(98)
        win.shortcut_vol_up.activated.emit()
        assert win.transport.slider_music.value() == 100
        win.shortcut_vol_up.activated.emit()
        assert win.transport.slider_music.value() == 100

        # Clamping inferiore a 0
        win.transport.slider_music.setValue(3)
        win.shortcut_vol_down.activated.emit()
        assert win.transport.slider_music.value() == 0
        win.shortcut_vol_down.activated.emit()
        assert win.transport.slider_music.value() == 0
    finally:
        win.close()


def test_tooltips_contain_shortcuts(qapp, clean_config):
    """Verifica che i tooltip dei pulsanti mostrino chiaramente le scorciatoie da tastiera."""
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        assert "Ctrl+M" in win.voice_monitor.btn_mic_toggle.toolTip()
        assert "Ctrl+Spazio" in win.transport.btn_play_pause.toolTip()
        assert "Ctrl+Destra" in win.transport.btn_skip.toolTip()
        assert "Ctrl+Su" in win.transport.slider_music.toolTip()
    finally:
        win.close()
