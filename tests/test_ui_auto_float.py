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
        win._enter_floating_mode()
        assert win.is_floating is True
        assert win.splitter.isVisible() is False
        assert bool(win.windowFlags() & Qt.WindowStaysOnTopHint) is True
        assert win.minimumWidth() == 480
        assert win.minimumHeight() == 160
    finally:
        win.close()


def test_exit_floating_mode(qapp, clean_config):
    """Verifica che l'uscita dalla modalità fluttuante ripristini la griglia e le dimensioni standard."""
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        win._enter_floating_mode()
        assert win.is_floating is True

        win._exit_floating_mode()
        assert win.is_floating is False
        assert win.splitter.isVisible() is True
        assert bool(win.windowFlags() & Qt.WindowStaysOnTopHint) is False
        assert win.minimumWidth() == 960
        assert win.minimumHeight() == 680
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
