"""
Test per la sincronizzazione del selettore profilo e della griglia atmosfere in PySide6.
Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

import os
from typing import Generator
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


def test_startup_profile_fantasy(qapp, clean_config, monkeypatch):
    """Verifica che all'avvio con profilo fantasy, combobox e griglia siano allineati su Fantasy."""
    cfg = ConfigManager.load()
    cfg["active_profile_id"] = "fantasy_dnd"
    ConfigManager.save(cfg)

    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        assert win.combo_profile.currentData() == "fantasy_dnd"
        assert win.active_profile_id == "fantasy_dnd"
        cards = list(win.mood_grid._cards.keys())
        assert "esplorazione" in cards
        assert "taverna" in cards
        assert "combattimento" in cards
        assert "metropoli" not in cards
    finally:
        win.close()


def test_startup_profile_scifi(qapp, clean_config, monkeypatch):
    """Verifica che all'avvio con profilo scifi, combobox e griglia siano allineati su Sci-Fi (bug fix)."""
    cfg = ConfigManager.load()
    cfg["active_profile_id"] = "scifi_cyberpunk"
    ConfigManager.save(cfg)

    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        assert win.combo_profile.currentData() == "scifi_cyberpunk"
        assert win.active_profile_id == "scifi_cyberpunk"
        cards = list(win.mood_grid._cards.keys())
        assert "metropoli" in cards
        assert "club" in cards
        assert "esplorazione" not in cards
    finally:
        win.close()


def test_combobox_change_updates_mood_grid(qapp, clean_config):
    """Verifica che la selezione da menu a tendina aggiorni la griglia e la config."""
    cfg = ConfigManager.load()
    cfg["active_profile_id"] = "fantasy_dnd"
    ConfigManager.save(cfg)

    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        idx = win.combo_profile.findData("horror_cthulhu")
        assert idx >= 0
        win.combo_profile.setCurrentIndex(idx)

        assert win.active_profile_id == "horror_cthulhu"
        cards = list(win.mood_grid._cards.keys())
        assert "indagine" in cards
        assert "terrore" in cards

        # Verifica persistenza
        reloaded = ConfigManager.load()
        assert reloaded["active_profile_id"] == "horror_cthulhu"
    finally:
        win.close()


def test_programmatic_apply_profile_syncs_combo(qapp, clean_config):
    """Verifica che _apply_profile aggiorni anche il combobox senza ricorsione."""
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        win._apply_profile("giallo_investigativo")
        assert win.combo_profile.currentData() == "giallo_investigativo"
        assert win.active_profile_id == "giallo_investigativo"
        cards = list(win.mood_grid._cards.keys())
        assert "scena_crimine" in cards
        assert "deduzione" in cards
    finally:
        win.close()
