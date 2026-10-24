"""
Test per l'esportazione e importazione di profili di campagna (.bardo.json).
Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

import json
import os
from typing import Generator
from unittest.mock import patch
import pytest
from PySide6.QtWidgets import QApplication

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

from storage import (
    ConfigManager,
    export_profile_to_file,
    import_profile_from_file,
    generate_unique_profile_id,
)


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


def test_export_profile_to_file(tmp_path):
    """Verifica che un profilo venga esportato correttamente in un pacchetto .bardo.json valido."""
    cfg = ConfigManager.load()
    prof = cfg["profiles"]["fantasy_dnd"]

    export_path = tmp_path / "fantasy_dnd.bardo.json"
    success = export_profile_to_file(prof, export_path)
    assert success is True
    assert export_path.is_file()

    data = json.loads(export_path.read_text(encoding="utf-8"))
    assert data["format"] == "bardo_profile"
    assert data["version"] == "1.0"
    assert data["profile"]["name"] == "Fantasy & D&D"
    assert "combattimento" in data["profile"]["moods"]


def test_import_profile_success(tmp_path, clean_config):
    """Verifica l'importazione con successo di un file di profilo valido."""
    cfg = ConfigManager.load()

    custom_prof_data = {
        "format": "bardo_profile",
        "version": "1.0",
        "profile": {
            "id": "strahd_campaign",
            "name": "La Maledizione di Strahd",
            "icon": "🧛",
            "description": "Atmosfere gotiche e cupe per Ravenloft",
            "moods": {
                "castello": {
                    "id": "castello",
                    "name": "Castello Ravenloft",
                    "color": "#7e22ce",
                    "queries": ["gothic organ dark ambient"],
                },
                "nebbia": {
                    "id": "nebbia",
                    "name": "Nebbie di Barovia",
                    "color": "#475569",
                    "queries": ["creepy forest fog ambient"],
                },
            },
        },
    }

    import_path = tmp_path / "strahd.bardo.json"
    import_path.write_text(json.dumps(custom_prof_data), encoding="utf-8")

    ok, msg, imported = import_profile_from_file(import_path, cfg)
    assert ok is True
    assert imported is not None
    assert imported["id"] == "strahd_campaign"
    assert imported["name"] == "La Maledizione di Strahd"
    assert "castello" in imported["moods"]

    # Verifica persistenza in configurazione
    reloaded = ConfigManager.load()
    assert "strahd_campaign" in reloaded["profiles"]
    assert reloaded["profiles"]["strahd_campaign"]["name"] == "La Maledizione di Strahd"


def test_import_profile_collision_resolution(tmp_path, clean_config):
    """Verifica che importare due volte un profilo con lo stesso nome o ID generi un ID univoco."""
    cfg = ConfigManager.load()

    prof_data = {
        "format": "bardo_profile",
        "version": "1.0",
        "profile": {
            "id": "custom_sci_fi",
            "name": "Spazio Profondo",
            "icon": "🚀",
            "moods": {
                "orbita": {
                    "id": "orbita",
                    "name": "In Orbita",
                    "queries": ["space ambient"],
                }
            },
        },
    }

    file1 = tmp_path / "space1.bardo.json"
    file1.write_text(json.dumps(prof_data), encoding="utf-8")

    ok1, _, imp1 = import_profile_from_file(file1, cfg)
    assert ok1 is True
    assert imp1["id"] == "custom_sci_fi"

    # Seconda importazione dello stesso profilo
    ok2, _, imp2 = import_profile_from_file(file1, cfg)
    assert ok2 is True
    assert imp2["id"] == "custom_sci_fi_2"
    assert imp2["id"] in cfg["profiles"]
    assert imp1["id"] in cfg["profiles"]


def test_import_corrupted_and_invalid_files(tmp_path, clean_config):
    """Verifica che file corrotti o mancanti di campi obbligatori vengano rifiutati con un messaggio chiaro."""
    cfg = ConfigManager.load()

    # 1. File inesistente
    ok, msg, _ = import_profile_from_file(tmp_path / "non_esiste.json", cfg)
    assert ok is False
    assert "non trovato" in msg

    # 2. Sintassi JSON errata
    corrupt_file = tmp_path / "bad.json"
    corrupt_file.write_text("{ questo non è un json valido !!!", encoding="utf-8")
    ok, msg, _ = import_profile_from_file(corrupt_file, cfg)
    assert ok is False
    assert "non valido" in msg.lower()

    # 3. Profilo senza nome
    no_name_file = tmp_path / "no_name.json"
    no_name_file.write_text(json.dumps({"moods": {"a": {"name": "A"}}}), encoding="utf-8")
    ok, msg, _ = import_profile_from_file(no_name_file, cfg)
    assert ok is False
    assert "nome" in msg.lower()

    # 4. Profilo senza mood
    no_moods_file = tmp_path / "no_moods.json"
    no_moods_file.write_text(json.dumps({"name": "Test Senza Mood", "moods": {}}), encoding="utf-8")
    ok, msg, _ = import_profile_from_file(no_moods_file, cfg)
    assert ok is False
    assert "atmosfera" in msg.lower()


def test_generate_unique_profile_id():
    """Verifica la logica di generazione slug univoci."""
    existing = {"campagna": {}, "campagna_2": {}, "fantasy_dnd": {}}
    assert generate_unique_profile_id("Nuova Campagna", existing) == "nuova_campagna"
    assert generate_unique_profile_id("Campagna", existing) == "campagna_3"
    assert generate_unique_profile_id("fantasy_dnd", existing, current_id="fantasy_dnd") == "fantasy_dnd_2"


def test_main_window_export_import_ui(qapp, tmp_path, clean_config):
    """Verifica l'interazione dei pulsanti di esportazione e importazione in MainWindow."""
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        # 1. Verifica presenza pulsanti
        assert hasattr(win, "btn_export_profile")
        assert hasattr(win, "btn_import_profile")
        assert win.btn_export_profile.toolTip() != ""
        assert win.btn_import_profile.toolTip() != ""

        # 2. Test export mockato
        target_export_file = tmp_path / "exported.bardo.json"
        with patch("PySide6.QtWidgets.QFileDialog.getSaveFileName", return_value=(str(target_export_file), "")):
            with patch("PySide6.QtWidgets.QMessageBox.information"):
                win._on_export_profile_clicked()
        assert target_export_file.is_file()

        # 3. Test import mockato
        import_prof = {
            "name": "Campagna Cyber",
            "icon": "🤖",
            "moods": {"cyber": {"name": "Neon", "queries": ["synthwave"]}},
        }
        import_file = tmp_path / "cyber.bardo.json"
        export_profile_to_file(import_prof, import_file)

        with patch("PySide6.QtWidgets.QFileDialog.getOpenFileName", return_value=(str(import_file), "")):
            with patch("PySide6.QtWidgets.QMessageBox.information"):
                win._on_import_profile_clicked()

        # Verifica che il nuovo profilo sia attivo
        assert win.active_profile_id == "campagna_cyber"
        assert win.combo_profile.currentData() == "campagna_cyber"
    finally:
        win.voice_listener.stop()
