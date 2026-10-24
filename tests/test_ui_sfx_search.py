"""
Test per la Barra di Ricerca Istantanea nella Soundboard in PySide6.
Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

import os
from typing import Generator
import pytest

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

from ui.widgets.soundboard import SoundboardWidget


@pytest.fixture(scope="module")
def qapp() -> Generator[QApplication, None, None]:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


SAMPLE_LIBRARY = {
    "spada": {
        "id": "spada",
        "name": "Spada e Fendente",
        "category": "Armi",
        "keywords": ["lama", "affondo", "fendente"],
        "hint": "Clangore di spade",
    },
    "ruggito_drago": {
        "id": "ruggito_drago",
        "name": "Drago Ruggente",
        "category": "Creature",
        "keywords": ["mostro", "fiamme"],
        "hint": "Ruggito possente",
    },
    "fulmine": {
        "id": "fulmine",
        "name": "Saetta e Fulmine",
        "category": "Magia",
        "keywords": ["elettricità", "tuono"],
        "hint": "Scossa elettrica",
    },
    "taverna": {
        "id": "taverna",
        "name": "Boccali in Taverna",
        "category": "Ambiente",
        "keywords": ["birra", "brindisi"],
        "hint": "Baccano da locanda",
    },
}


def test_search_box_properties(qapp):
    """Verifica che il campo di ricerca abbia il placeholder corretto e il clear button abilitato."""
    sb = SoundboardWidget()
    assert "Ctrl+F" in sb.search_box.placeholderText()
    assert sb.search_box.isClearButtonEnabled() is True


def test_search_filter_by_name_and_reset(qapp):
    """Verifica che la ricerca filtri in tempo reale per nome e ripristini tutti i bottoni quando vuota."""
    sb = SoundboardWidget()
    sb.set_library(SAMPLE_LIBRARY)
    sb.show()

    # Tutti i pulsanti della tab "Tutti" sono inizialmente visibili
    all_btns = sb._category_buttons["Tutti"]
    assert len(all_btns) == 4
    for btn, _ in all_btns:
        assert btn.isVisible() is True

    # Cerca "Spada"
    sb.search_box.setText("spada")
    for btn, item in all_btns:
        if item["id"] == "spada":
            assert btn.isVisible() is True
        else:
            assert btn.isVisible() is False

    # Ripristina ricerca vuota
    sb.search_box.setText("")
    for btn, _ in all_btns:
        assert btn.isVisible() is True


def test_search_filter_by_keyword(qapp):
    """Verifica che la ricerca trovi gli effetti anche tramite le loro parole chiave vocali."""
    sb = SoundboardWidget()
    sb.set_library(SAMPLE_LIBRARY)
    sb.show()

    all_btns = sb._category_buttons["Tutti"]

    # Cerca "fiamme" (parola chiave di ruggito_drago)
    sb.search_box.setText("fiamme")
    for btn, item in all_btns:
        if item["id"] == "ruggito_drago":
            assert btn.isVisible() is True
        else:
            assert btn.isVisible() is False


def test_search_auto_switch_to_tutti_and_restore(qapp):
    """Verifica che digitando una ricerca si passi alla tab Tutti, per poi tornare alla tab precedente."""
    sb = SoundboardWidget()
    sb.set_library(SAMPLE_LIBRARY)
    sb.show()

    # Utente seleziona la tab "Creature" (indice 2)
    sb.tab_widget.setCurrentIndex(2)
    assert sb.tab_widget.currentIndex() == 2

    # Digita una ricerca
    sb.search_box.setText("fulmine")
    assert sb.tab_widget.currentIndex() == 0  # Passato a Tutti

    # Cancella la ricerca
    sb.search_box.setText("")
    assert sb.tab_widget.currentIndex() == 2  # Tornato a Creature


def test_search_shortcut_and_escape_key(qapp):
    """Verifica che Ctrl+F metta a fuoco il campo e il tasto Escape azzeri la ricerca."""
    import warnings

    sb = SoundboardWidget()
    sb.set_library(SAMPLE_LIBRARY)
    sb.show()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        qapp.setActiveWindow(sb)

    # Attiva scorciatoia Ctrl+F
    sb.shortcut_search.activated.emit()
    assert sb.search_box.hasFocus() is True

    # Scrive del testo e simula pressione Escape
    sb.search_box.setText("drago")
    assert sb.search_box.text() == "drago"

    key_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
    sb.search_box.keyPressEvent(key_event)

    assert sb.search_box.text() == ""
    assert sb.search_box.hasFocus() is False
