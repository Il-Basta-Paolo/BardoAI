"""
Test per la modalità Finestra Fluttuante Automatica (Auto-Float PiP) in PySide6.
Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

import os
from typing import Generator
from unittest.mock import MagicMock
import pytest

from PySide6.QtCore import QEvent, Qt
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


def test_auto_float_default_state(qapp, clean_config):
    """Verifica che la modalità Auto-Float sia attiva di default e i widget inizializzati."""
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        win.show()
        assert win.auto_float_enabled is True
        assert win.is_floating is False
        assert "ON" in win.btn_auto_float.text()
        assert win.splitter.isVisible() is True
    finally:
        win.close()


def test_enter_floating_mode(qapp, clean_config):
    """Verifica che l'attivazione della modalità fluttuante riduca la finestra e imposti Always-on-Top."""
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        win.show()
        win._enter_floating_mode()
        assert win.is_floating is True
        assert win.top_bar_widget.isVisible() is False
        assert win.splitter.isVisible() is False
        assert win.voice_monitor.isVisible() is False
        assert win.transport.btn_restore.isVisible() is True
        assert win.transport.btn_mic_quick.isVisible() is True
        assert win.transport.out_dev_container.isVisible() is False
        assert win.transport.vol_sfx_container.isVisible() is False
        assert win.transport.lock_container.isVisible() is False
        assert bool(win.windowFlags() & Qt.WindowStaysOnTopHint) is True
        assert win.minimumWidth() == 460
        assert win.minimumHeight() == 76
    finally:
        win.close()


def test_exit_floating_mode(qapp, clean_config):
    """Verifica che l'uscita dalla modalità fluttuante ripristini la griglia e le dimensioni standard."""
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        win.show()
        win._enter_floating_mode()
        assert win.is_floating is True

        win._exit_floating_mode()
        assert win.is_floating is False
        assert win.top_bar_widget.isVisible() is True
        assert win.splitter.isVisible() is True
        assert win.voice_monitor.isVisible() is True
        assert win.transport.btn_restore.isVisible() is False
        assert win.transport.btn_mic_quick.isVisible() is False
        assert win.transport.out_dev_container.isVisible() is True
        assert win.transport.vol_sfx_container.isVisible() is True
        assert win.transport.lock_container.isVisible() is True
        assert bool(win.windowFlags() & Qt.WindowStaysOnTopHint) is False
        assert win.minimumWidth() == 960
        assert win.minimumHeight() == 680
    finally:
        win.close()


def test_floating_restore_button(qapp, clean_config):
    """Verifica che il pulsante '⤢' (btn_restore) nel transport bar ripristini la finestra estesa."""
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        win.show()
        win._enter_floating_mode()
        assert win.is_floating is True

        # Click sul pulsante di ripristino
        win.transport.btn_restore.click()
        assert win.is_floating is False
        assert win.splitter.isVisible() is True
        assert win.top_bar_widget.isVisible() is True
        assert win.voice_monitor.isVisible() is True
    finally:
        win.close()


def test_floating_mic_sync(qapp, clean_config):
    """Verifica che il pulsante rapido microfono nel transport bar e nel voice monitor siano sincronizzati."""
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        win.show()
        win._enter_floating_mode()
        assert win.transport.btn_mic_quick.isChecked() is True

        # Muta il microfono dal pulsante rapido del transport bar
        win.transport.btn_mic_quick.click()
        assert win.transport.btn_mic_quick.isChecked() is False
        assert win.voice_monitor.btn_mic_toggle.isChecked() is False
        assert "🔇" in win.transport.btn_mic_quick.text()

        # Riattiva il microfono dal voice monitor
        win.voice_monitor.btn_mic_toggle.setChecked(True)
        assert win.transport.btn_mic_quick.isChecked() is True
        assert "🎙️" in win.transport.btn_mic_quick.text()
    finally:
        win.close()


def test_toggle_auto_float_button_and_shortcut(qapp, clean_config):
    """Verifica che l'interruttore e la scorciatoia Ctrl+F11 invertano correttamente lo stato."""
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        assert win.auto_float_enabled is True

        # Click sul pulsante
        win.btn_auto_float.click()
        assert win.auto_float_enabled is False
        assert "OFF" in win.btn_auto_float.text()

        # Attivazione con scorciatoia Ctrl+F11
        win.shortcut_auto_float.activated.emit()
        assert win.auto_float_enabled is True
        assert "ON" in win.btn_auto_float.text()
    finally:
        win.close()


def test_change_event_focus_trigger(qapp, clean_config):
    """Verifica che la perdita di focus (ActivationChange) scateni l'Auto-Float quando attivo."""
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        win._enter_floating_mode = MagicMock()
        win._exit_floating_mode = MagicMock()

        # 1. Simula perdita di focus (quando abilitato)
        win.auto_float_enabled = True
        win.is_floating = False
        win.isActiveWindow = MagicMock(return_value=False)
        event = QEvent(QEvent.ActivationChange)
        win.changeEvent(event)
        win._enter_floating_mode.assert_called_once()

        # 2. Simula riacquisto del focus
        win.is_floating = True
        win.isActiveWindow = MagicMock(return_value=True)
        win.changeEvent(event)
        win._exit_floating_mode.assert_called_once()
    finally:
        win.close()


def test_change_event_inhibited_by_modal_or_minimized(qapp, clean_config, monkeypatch):
    """Verifica che la presenza di una finestra modale o lo stato minimizzato inibiscano l'Auto-Float."""
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        win._enter_floating_mode = MagicMock()
        win.auto_float_enabled = True
        win.is_floating = False
        win.isActiveWindow = MagicMock(return_value=False)
        event = QEvent(QEvent.ActivationChange)

        # 1. Simula finestra modale aperta
        fake_modal = MagicMock()
        monkeypatch.setattr(QApplication, "activeModalWidget", staticmethod(lambda: fake_modal))
        win.changeEvent(event)
        win._enter_floating_mode.assert_not_called()

        # 2. Simula finestra minimizzata su barra applicazioni
        monkeypatch.setattr(QApplication, "activeModalWidget", staticmethod(lambda: None))
        win.isMinimized = MagicMock(return_value=True)
        win.changeEvent(event)
        win._enter_floating_mode.assert_not_called()
    finally:
        win.close()


def test_transport_volume_setters_and_config_sync(qapp, clean_config):
    """Verifica i setter di volume in TransportBar e la sincronizzazione con la configurazione di MainWindow."""
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        # Verifica setter TransportBar
        win.transport.set_music_volume(42)
        assert win.transport.slider_music.value() == 42
        assert win.transport.lbl_music_pct.text() == "42%"

        win.transport.set_sfx_volume(65)
        assert win.transport.slider_sfx.value() == 65
        assert win.transport.lbl_sfx_pct.text() == "65%"

        # Clamping
        win.transport.set_music_volume(150)
        assert win.transport.slider_music.value() == 100
        win.transport.set_sfx_volume(-20)
        assert win.transport.slider_sfx.value() == 0

        # Verifica sincronizzazione callback con self.config
        win._on_music_volume_changed(55)
        assert win.config["audio"]["master_volume"] == 55
        assert win.audio_engine.music_volume == 55

        win._on_sfx_volume_changed(72)
        assert win.config["sfx"]["volume"] == 72
        assert win.audio_engine.sfx_volume == 72
    finally:
        win.close()
