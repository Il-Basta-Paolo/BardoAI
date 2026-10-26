"""
Test unitari per la finestra Impostazioni (SettingsDialog) in PySide6.
Verifica il comportamento dinamico del tab Intelligenza Artificiale e la gestione sicura delle credenziali.
Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

import copy
import os
from typing import Generator
import pytest

from PySide6.QtWidgets import QApplication

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

from config_defaults import APP_VERSION, DEFAULT_CONFIG
from storage import SecretVault
from ui.dialogs.settings_dialog import SettingsDialog


@pytest.fixture(scope="module")
def qapp() -> Generator[QApplication, None, None]:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_settings_dialog_default_ai_tab(qapp):
    """Verifica che il tab AI si apra di default in modalità 'keywords' offline, senza campi API visibili."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    dlg = SettingsDialog(cfg)
    dlg.show()
    try:
        assert APP_VERSION in dlg.windowTitle()
        prov = dlg.combo_provider.currentData() or dlg.combo_provider.currentText()
        assert prov == "keywords"

        # Il box informativo offline deve essere visibile, i box cloud nascosti
        assert not dlg.box_keywords.isHidden()
        assert dlg.box_gemini.isHidden()
        assert dlg.box_openai.isHidden()
        assert dlg.box_ollama.isHidden()

        # Nessuna API key pre-compilata
        assert dlg.txt_gemini_key.text() == ""
        assert dlg.txt_openai_key.text() == ""
    finally:
        dlg.close()


def test_settings_dialog_ai_provider_switching(qapp):
    """Verifica che cambiando il provider AI nel combo box, i riquadri corrispondenti si mostrino o nascondano."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    dlg = SettingsDialog(cfg)
    dlg.show()
    try:
        # Seleziona Gemini
        idx_gemini = dlg.combo_provider.findData("gemini")
        assert idx_gemini >= 0
        dlg.combo_provider.setCurrentIndex(idx_gemini)
        assert dlg.box_keywords.isHidden()
        assert not dlg.box_gemini.isHidden()
        assert dlg.box_openai.isHidden()
        assert dlg.box_ollama.isHidden()

        # Seleziona OpenAI
        idx_openai = dlg.combo_provider.findData("openai")
        assert idx_openai >= 0
        dlg.combo_provider.setCurrentIndex(idx_openai)
        assert dlg.box_keywords.isHidden()
        assert dlg.box_gemini.isHidden()
        assert not dlg.box_openai.isHidden()
        assert dlg.box_ollama.isHidden()

        # Seleziona Ollama
        idx_ollama = dlg.combo_provider.findData("ollama")
        assert idx_ollama >= 0
        dlg.combo_provider.setCurrentIndex(idx_ollama)
        assert dlg.box_keywords.isHidden()
        assert dlg.box_gemini.isHidden()
        assert dlg.box_openai.isHidden()
        assert not dlg.box_ollama.isHidden()

        # Torna a Keywords
        idx_kw = dlg.combo_provider.findData("keywords")
        assert idx_kw >= 0
        dlg.combo_provider.setCurrentIndex(idx_kw)
        assert not dlg.box_keywords.isHidden()
        assert dlg.box_gemini.isHidden()
        assert dlg.box_openai.isHidden()
        assert dlg.box_ollama.isHidden()
    finally:
        dlg.close()


def test_settings_dialog_save_secrets(qapp, monkeypatch):
    """Verifica che il salvataggio memorizzi le chiavi in SecretVault e le elimini se svuotate."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    dlg = SettingsDialog(cfg)
    try:
        # Simula inserimento API key Gemini
        dlg.txt_gemini_key.setText("AIzaSyFakeKey123")
        dlg.txt_openai_key.setText("sk-fake-openai-999")
        dlg.txt_gemini_model.setText("gemini-1.5-pro")

        # Salva
        dlg._save_and_close()

        assert SecretVault.get_secret("gemini_api_key") == "AIzaSyFakeKey123"
        assert SecretVault.get_secret("openai_api_key") == "sk-fake-openai-999"
        assert dlg.analyzer_cfg["gemini_model"] == "gemini-1.5-pro"

        # Ora simula la rimozione delle chiavi
        dlg.txt_gemini_key.setText("")
        dlg.txt_openai_key.setText("")
        dlg._save_and_close()

        assert SecretVault.get_secret("gemini_api_key") == ""
        assert SecretVault.get_secret("openai_api_key") == ""
    finally:
        dlg.close()
