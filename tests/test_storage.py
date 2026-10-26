"""
Test per storage.py e config_defaults.py:
- Migrazione automatica schema v2
- Presenza del 4° profilo "Giallo & Investigativo"
- Preservazione delle personalizzazioni utente
- SecretVault con keyring e assenza di plaintext delle API key nel config.json
- Scrittura atomica

Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

__author__ = "Paolo Basta"

import json
from pathlib import Path

from config_defaults import (
    DEFAULT_CONFIG,
    CONFIG_SCHEMA_VERSION,
    get_profile_by_id,
    list_available_profiles,
)
from storage import (
    SecretVault,
    atomic_write_json,
    load_config_with_migration,
)


def test_config_v2_schema_and_profiles():
    # Verifica che lo schema sia v2
    assert DEFAULT_CONFIG.get("schema_version") == CONFIG_SCHEMA_VERSION == 2

    # Verifica che ci siano 4 profili predefiniti (risolve bug #32)
    profiles = list_available_profiles(DEFAULT_CONFIG)
    assert len(profiles) == 4
    profile_ids = [p["id"] for p in profiles]
    assert "fantasy_dnd" in profile_ids
    assert "horror_cthulhu" in profile_ids
    assert "scifi_cyberpunk" in profile_ids
    assert "giallo_investigativo" in profile_ids

    # Verifica il profilo Giallo & Investigativo e i suoi mood
    inv = get_profile_by_id(DEFAULT_CONFIG, "giallo_investigativo")
    assert inv is not None
    assert "Giallo" in inv["name"]
    assert len(inv["moods"]) >= 5


def test_atomic_write(tmp_path: Path):
    target = tmp_path / "test_file.json"
    data = {"test_key": "valore_sicuro", "numero": 42}
    atomic_write_json(target, data)
    assert target.is_file()

    with open(target, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded == data


def test_config_migration_from_v1(tmp_path: Path):
    v1_cfg = {
        "active_profile": "fantasy",
        "profiles": {
            "fantasy": {
                "id": "fantasy",
                "name": "Fantasy Classico",
                "moods": {
                    "taverna": {
                        "name": "Taverna",
                        "keywords": ["locanda", "birra"],
                        "youtube_queries": ["celtic tavern music"],
                    }
                },
            }
        },
        "gemini_api_key": "MIGRATION_TEST_KEY_123",
        "custom_sfx": {"mio_effetto": {"name": "Mio Effetto", "file": "mio.wav"}},
    }
    v1_file = tmp_path / "config_v1.json"
    atomic_write_json(v1_file, v1_cfg)

    # Migrazione
    migrated = load_config_with_migration(v1_file)
    assert migrated["schema_version"] == 2
    # Il 4° profilo deve essere stato aggiunto automaticamente
    assert "giallo_investigativo" in migrated["profiles"]
    # La chiave non deve essere più salvata in chiaro nel root level
    assert migrated.get("gemini_api_key") is None
    assert migrated["analyzer"]["gemini_api_key"] == ""
    # Le personalizzazioni utente (custom_sfx) sono preservate
    assert "mio_effetto" in migrated["custom_sfx"]


def test_secret_vault_integration():
    SecretVault.set_secret("test_service", "secret_val_xyz")
    read_back = SecretVault.get_secret("test_service")
    assert read_back == "secret_val_xyz"
    SecretVault.delete_secret("test_service")
    assert SecretVault.get_secret("test_service") == ""
