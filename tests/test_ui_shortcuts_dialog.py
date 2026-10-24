"""
Test per la finestra Guida alle Scorciatoie da Tastiera e il Menu Aiuto in PySide6.
Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

import os
from typing import Generator
from unittest.mock import MagicMock
import pytest

from PySide6.QtWidgets import QApplication, QMessageBox

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

from storage import ConfigManager
from ui.dialogs.shortcuts_dialog import ShortcutsDialog


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


def test_shortcuts_dialog_rendering(qapp):
    """Verifica che la finestra ShortcutsDialog contenga tutte le 4 sezioni e le scorciatoie chiave."""
    dlg = ShortcutsDialog()
    try:
        assert "Scorciatoie" in dlg.windowTitle()
        assert len(dlg.SHORTCUT_SECTIONS) == 4

        # Estrae tutte le chiavi presenti
        all_keys = [k for _, shortcuts in dlg.SHORTCUT_SECTIONS for k, _ in shortcuts]
        assert "Ctrl + M" in all_keys
        assert "Ctrl + Spazio" in all_keys
        assert "Ctrl + Destra" in all_keys
        assert "Ctrl + Su" in all_keys
        assert "Ctrl + Giù" in all_keys
        assert "Ctrl + F11" in all_keys
        assert "Ctrl + F" in all_keys
        assert "Esc" in all_keys
        assert "F1" in all_keys
    finally:
        dlg.close()


def test_main_window_help_menu_actions(qapp, clean_config):
    """Verifica che il pulsante Aiuto nell'header contenga le 3 azioni attese."""
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        assert win.btn_help is not None
        actions = win.menu_help.actions()
        assert len(actions) == 3

        texts = [a.text() for a in actions]
        assert any("Scorciatoie" in t for t in texts)
        assert any("FAQ" in t for t in texts)
        assert any("Informazioni" in t for t in texts)
    finally:
        win.close()


def test_main_window_f1_shortcut_triggers_dialog(qapp, clean_config):
    """Verifica che la pressione di F1 chiami il metodo per aprire la guida scorciatoie."""
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        win._open_shortcuts_dialog = MagicMock()
        win.shortcut_help.activated.emit()
        win._open_shortcuts_dialog.assert_called_once()
    finally:
        win.close()


def test_open_about_dialog(qapp, clean_config, monkeypatch):
    """Verifica che la finestra About mostri la versione e attribuisca il software a Paolo Basta."""
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        mock_about = MagicMock()
        monkeypatch.setattr(QMessageBox, "about", mock_about)

        win._open_about_dialog()
        mock_about.assert_called_once()

        args = mock_about.call_args[0]
        text_content = args[2]
        assert "v2.6.1" in text_content
        assert "Paolo Basta" in text_content
    finally:
        win.close()
