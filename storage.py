"""
Gestione persistenza configurazione e credenziali YouTube Music.
Sincronizza automaticamente gli aggiornamenti del motore (seed_tracks, tone_profile, keywords e phrases)
con l'eventuale file `data/config.json` già salvato, preservando playlist e brani fissati dall'utente.
"""

import copy
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any

from config_defaults import DEFAULT_CONFIG

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent


def _resolve_writable_data_dir() -> Path:
    """
    Usa `<cartella_installazione>/data` se scrivibile (es. `D:\\Giochi\\BardoAI`, `C:\\BardoAI`, AppData),
    oppure ripiega automaticamente su `%LOCALAPPDATA%\\BardoAI\\data` se l'utente ha scelto di installare
    il programma in una cartella di sistema protetta come `C:\\Program Files\\BardoAI`.
    """
    local_data = BASE_DIR / "data"
    try:
        local_data.mkdir(parents=True, exist_ok=True)
        probe = local_data / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return local_data
    except Exception:
        appdata = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        fallback = appdata / "BardoAI" / "data"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


DATA_DIR = _resolve_writable_data_dir()
CONFIG_FILE = DATA_DIR / "config.json"
YTMUSIC_AUTH_FILE = DATA_DIR / "ytmusic_auth.json"
SPOTIFY_AUTH_FILE = DATA_DIR / "spotify_auth.json"


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> Dict[str, Any]:
    ensure_data_dir()
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return copy.deepcopy(DEFAULT_CONFIG)

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            user_cfg = json.load(f)
        merged = copy.deepcopy(DEFAULT_CONFIG)
        if "active_profile_id" in user_cfg:
            merged["active_profile_id"] = user_cfg["active_profile_id"]
        if "analyzer" in user_cfg and isinstance(user_cfg["analyzer"], dict):
            merged["analyzer"].update(user_cfg["analyzer"])
        if "audio" in user_cfg and isinstance(user_cfg["audio"], dict):
            merged["audio"].update(user_cfg["audio"])
        if "sfx" in user_cfg and isinstance(user_cfg["sfx"], dict):
            merged["sfx"] = user_cfg["sfx"]

        if "profiles" in user_cfg and isinstance(user_cfg["profiles"], dict):
            for pid, u_prof in user_cfg["profiles"].items():
                if pid not in merged["profiles"]:
                    merged["profiles"][pid] = u_prof
                else:
                    # Per i profili predefiniti, aggiorna regole/seed/query ma preserva custom_playlist,
                    # pinned_tracks e atmosfere aggiunte dall'utente
                    def_moods = merged["profiles"][pid].get("moods", {})
                    u_moods = u_prof.get("moods", {})
                    for mid, u_m in u_moods.items():
                        if mid not in def_moods:
                            def_moods[mid] = u_m
                        else:
                            if u_m.get("custom_playlist"):
                                def_moods[mid]["custom_playlist"] = u_m["custom_playlist"]
                            if u_m.get("pinned_tracks"):
                                def_moods[mid]["pinned_tracks"] = u_m["pinned_tracks"]
        save_config(merged)
        return merged
    except Exception:
        return copy.deepcopy(DEFAULT_CONFIG)


def save_config(cfg: Dict[str, Any]) -> None:
    ensure_data_dir()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def reset_default_profiles() -> Dict[str, Any]:
    cfg = load_config()
    cfg["profiles"] = copy.deepcopy(DEFAULT_CONFIG["profiles"])
    if cfg["active_profile_id"] not in cfg["profiles"]:
        cfg["active_profile_id"] = "fantasy_dnd"
    save_config(cfg)
    return cfg
