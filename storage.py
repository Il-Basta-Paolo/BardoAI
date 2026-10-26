"""
Gestione persistenza configurazione (Pydantic v2), salvataggio atomico thread-safe,
preservazione integrale delle personalizzazioni/eliminazioni dell'utente e
cassaforte credenziali nel Credential Manager di Windows (`keyring`).
Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

import copy
import json
import os
import re
import shutil
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import keyring
from pydantic import BaseModel, Field, field_validator

from config_defaults import APP_VERSION, CONFIG_SCHEMA_VERSION, DEFAULT_CONFIG

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent


def _resolve_writable_data_dir() -> Path:
    """
    Usa `<cartella_installazione>/data` se scrivibile, oppure ripiega automaticamente su
    `%LOCALAPPDATA%\\BardoAI\\data` se l'app è installata in `C:\\Program Files\\BardoAI`.
    """
    local_data = BASE_DIR / "data"
    try:
        local_data.mkdir(parents=True, exist_ok=True)
        probe = local_data / f".write_test_{os.getpid()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return local_data
    except Exception:
        appdata = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        fallback = appdata / "BardoAI" / "data"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


DATA_DIR = _resolve_writable_data_dir()


def get_data_dir() -> Path:
    return DATA_DIR


CONFIG_FILE = DATA_DIR / "config.json"
CUSTOM_SFX_DIR = DATA_DIR / "custom_sfx"
AUDIO_CACHE_DIR = DATA_DIR / "audio_cache"
LOCAL_MUSIC_DIR = DATA_DIR / "local_music"
MODELS_DIR = DATA_DIR / "models"
BIN_DIR = DATA_DIR / "bin"
YTMUSIC_AUTH_FILE = DATA_DIR / "ytmusic_auth.json"

_CONFIG_LOCK = threading.RLock()
KEYRING_SERVICE = "BardoAI_GdR_v2"


class SecretVault:
    """
    Gestisce i segreti (API key AI, cookie di sessione Google/Spotify, token e client secret)
    nel Credential Manager di Windows tramite `keyring`, evitando file in chiaro su disco.
    Include una cache in memoria per non interrogare il Credential Manager a ogni lettura.
    """

    _mem_cache: Dict[str, str] = {}
    _lock = threading.RLock()

    @classmethod
    def get_secret(cls, key: str, default: str = "") -> str:
        with cls._lock:
            if key in cls._mem_cache:
                return cls._mem_cache[key]
            try:
                val = keyring.get_password(KEYRING_SERVICE, key)
                if val is not None:
                    cls._mem_cache[key] = val
                    return val
            except Exception:
                pass
            return default

    @classmethod
    def set_secret(cls, key: str, value: str) -> None:
        with cls._lock:
            clean = (value or "").strip()
            cls._mem_cache[key] = clean
            try:
                if clean:
                    keyring.set_password(KEYRING_SERVICE, key, clean)
                else:
                    keyring.delete_password(KEYRING_SERVICE, key)
            except Exception:
                pass

    @classmethod
    def delete_secret(cls, key: str) -> None:
        with cls._lock:
            cls._mem_cache.pop(key, None)
            try:
                keyring.delete_password(KEYRING_SERVICE, key)
            except Exception:
                pass


# =============================================================================
# MODELLI PYDANTIC PER VALIDAZIONE ROBUSTA DELLA CONFIGURAZIONE
# =============================================================================

class AnalyzerSettingsModel(BaseModel):
    mode: str = "hybrid"
    cooldown_seconds: float = 18.0
    confidence_threshold: float = 2.2
    min_scene_duration_seconds: float = 8.0
    hysteresis_window_seconds: float = 25.0
    ai_provider: str = "keywords"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    @field_validator("cooldown_seconds", mode="before")
    @classmethod
    def _coerce_cooldown(cls, v: Any) -> float:
        try:
            val = float(v)
            return max(0.0, min(600.0, val))
        except (ValueError, TypeError):
            return 18.0

    @field_validator("confidence_threshold", mode="before")
    @classmethod
    def _coerce_threshold(cls, v: Any) -> float:
        try:
            val = float(v)
            return max(0.5, min(20.0, val))
        except (ValueError, TypeError):
            return 2.2

    @field_validator("gemini_model", mode="before")
    @classmethod
    def _upgrade_deprecated_gemini_model(cls, v: Any) -> str:
        s = str(v or "").strip()
        if not s or s in ("gemini-1.5-flash", "gemini-2.0-flash"):
            return "gemini-2.5-flash"
        return s


class AudioSettingsModel(BaseModel):
    output_device: Optional[int] = None
    master_volume: int = 75
    crossfade_seconds: float = 3.5
    music_provider: str = "ytmusic"
    cache_enabled: bool = True
    cache_max_mb: int = 500
    auto_update_ytdlp: bool = True
    sponsorblock_enabled: bool = True
    prefer_user_playlist_over_biome: bool = True

    @field_validator("master_volume", mode="before")
    @classmethod
    def _clamp_vol(cls, v: Any) -> int:
        try:
            return max(0, min(100, int(round(float(v)))))
        except (ValueError, TypeError):
            return 75

    @field_validator("crossfade_seconds", mode="before")
    @classmethod
    def _clamp_cf(cls, v: Any) -> float:
        try:
            return max(0.0, min(15.0, round(float(v), 1)))
        except (ValueError, TypeError):
            return 3.5


class STTSettingsModel(BaseModel):
    engine: str = "local"
    vosk_enabled: bool = True
    whisper_enabled: bool = True
    whisper_model: str = "small"
    vad_threshold: float = 0.45
    gate_threshold: int = 20


class MoodModel(BaseModel):
    id: str = ""
    name: str
    icon: str = "🎵"
    color: str = "#10b981"
    tone_profile: str = "exploration"
    description: str = ""
    seed_tracks: List[Dict[str, Any]] = Field(default_factory=list)
    queries: List[str] = Field(default_factory=list)
    custom_playlist: str = ""
    pinned_tracks: List[Dict[str, Any]] = Field(default_factory=list)
    phrases: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CUSTOM_SFX_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    BIN_DIR.mkdir(parents=True, exist_ok=True)


def cleanup_legacy_browser_profiles() -> None:
    """
    Rimuove profili temporanei obsoleti lasciati dalla vecchia versione webapp.
    Preserva i file di autenticazione dell'utente (ytmusic_auth.json, spotify_auth.json).
    """
    for folder_name in ("spotify_browser_profile",):
        target = DATA_DIR / folder_name
        if target.exists():
            try:
                shutil.rmtree(target, ignore_errors=True)
            except Exception:
                pass


def atomic_write_json(target_path: Path, data: Dict[str, Any]) -> None:
    """
    Scrive un file JSON in modo atomico usando un file temporaneo nella stessa directory
    e `os.replace`, prevenendo qualsiasi corruzione in caso di chiusura improvvisa o crash.
    """
    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path_str = tempfile.mkstemp(
        prefix=f".{target_path.name}.",
        suffix=".tmp",
        dir=str(target_path.parent),
    )
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp_path), str(target_path))
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def generate_unique_mood_id(name: str, existing_moods: Dict[str, Any], current_id: Optional[str] = None) -> str:
    """
    Genera un ID univoco per un'atmosfera senza mai sovrascrivere un'atmosfera già esistente
    se l'utente crea una nuova atmosfera con un nome simile (es. 'Combattimento' -> 'combattimento_2').
    """
    if current_id:
        return current_id
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "atmosfera").lower()).strip("_") or "atmosfera"
    if slug not in existing_moods:
        return slug
    counter = 2
    while f"{slug}_{counter}" in existing_moods:
        counter += 1
    return f"{slug}_{counter}"


class ExportedProfilePackage(BaseModel):
    """Contenitore per l'esportazione autonoma di un profilo in formato .bardo.json."""

    format: str = "bardo_profile"
    version: str = "1.0"
    app_version: str = APP_VERSION
    exported_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    profile: Dict[str, Any]


def generate_unique_profile_id(
    name: str, existing_profiles: Dict[str, Any], current_id: Optional[str] = None
) -> str:
    """Genera un ID univoco per un profilo senza sovrascrivere profili esistenti."""
    if current_id and current_id not in existing_profiles:
        return current_id
    base_slug = current_id if current_id else (re.sub(r"[^a-z0-9]+", "_", (name or "campagna").lower()).strip("_") or "campagna")
    if base_slug not in existing_profiles:
        return base_slug
    counter = 2
    while f"{base_slug}_{counter}" in existing_profiles:
        counter += 1
    return f"{base_slug}_{counter}"


def export_profile_to_file(profile_data: Dict[str, Any], target_path: Path) -> bool:
    """Esporta un profilo di campagna in un file standalone .bardo.json validato."""
    try:
        pkg = ExportedProfilePackage(profile=copy.deepcopy(profile_data))
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(pkg.model_dump(), f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[Storage] Errore esportazione profilo {target_path}: {e}")
        return False


def import_profile_from_file(
    file_path: Path, cfg: Dict[str, Any]
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Importa e valida un profilo da un file .bardo.json:
    - Valida il pacchetto con ExportedProfilePackage.
    - Assegna un ID univoco in caso di collisione.
    - Inserisce il profilo in cfg['profiles'] e salva la configurazione su disco.
    """
    if not file_path.is_file():
        return False, "File del profilo non trovato o non accessibile.", None
    try:
        raw_text = file_path.read_text(encoding="utf-8")
        data = json.loads(raw_text)
    except Exception as e:
        return False, f"File JSON non valido o corrotto: {e}", None

    profile_dict: Dict[str, Any]
    if isinstance(data, dict) and "format" in data and "profile" in data:
        try:
            pkg = ExportedProfilePackage(**data)
            profile_dict = pkg.profile
        except Exception as e:
            return False, f"Struttura pacchetto profilo non valida: {e}", None
    elif isinstance(data, dict) and ("name" in data or "moods" in data):
        profile_dict = data
    else:
        return False, "Il file non contiene un profilo Bardo AI valido.", None

    name = str(profile_dict.get("name", "")).strip()
    if not name:
        return False, "Il profilo non contiene un nome valido.", None

    moods = profile_dict.get("moods")
    if not isinstance(moods, dict) or len(moods) == 0:
        return False, "Il profilo deve contenere almeno un'atmosfera musicale valida.", None

    validated_moods: Dict[str, Any] = {}
    for mid, mdata in moods.items():
        if isinstance(mdata, dict):
            try:
                m_copy = copy.deepcopy(mdata)
                if "id" not in m_copy:
                    m_copy["id"] = mid
                m_model = MoodModel(**m_copy)
                validated_moods[mid] = m_model.model_dump()
            except Exception as e:
                print(f"[Storage] Mood {mid} non valido scartato: {e}")
    if not validated_moods:
        return False, "Nessun mood valido trovato nel profilo da importare.", None

    profiles = cfg.setdefault("profiles", {})
    orig_id = str(profile_dict.get("id", "")).strip()
    unique_id = generate_unique_profile_id(name, profiles, current_id=orig_id if orig_id else None)

    imported = {
        "id": unique_id,
        "name": name,
        "icon": str(profile_dict.get("icon", "🎭")),
        "description": str(profile_dict.get("description", "")),
        "moods": validated_moods,
    }
    profiles[unique_id] = imported
    save_config(cfg)
    return True, f"Profilo '{name}' importato con successo!", imported


def _merge_mood_preserving_user_edits(default_mood: Dict[str, Any], user_mood: Dict[str, Any]) -> Dict[str, Any]:
    """
    Unisce un mood predefinito con quello salvato dall'utente:
    - Preserva SEMPRE le modifiche dell'utente a name, icon, color, description, phrases, keywords,
      queries, custom_playlist, pinned_tracks, tone_profile e seed_tracks.
    - Se a un mood salvato da una vecchia versione mancavano `tone_profile` o `seed_tracks`
      (perché il vecchio `save_mood` li scartava), li ripristina dal default!
    """
    merged = copy.deepcopy(default_mood)
    for k in (
        "id",
        "name",
        "icon",
        "color",
        "description",
        "custom_playlist",
        "pinned_tracks",
        "phrases",
        "keywords",
        "queries",
    ):
        if k in user_mood and user_mood[k] is not None:
            merged[k] = copy.deepcopy(user_mood[k])

    if user_mood.get("tone_profile"):
        merged["tone_profile"] = user_mood["tone_profile"]
    if user_mood.get("seed_tracks"):
        merged["seed_tracks"] = copy.deepcopy(user_mood["seed_tracks"])

    valid = MoodModel(**merged)
    return valid.model_dump()


def load_config() -> Dict[str, Any]:
    """
    Carica la configurazione da disco in modo sicuro:
    - Non riscrive inutilmente il file su disco durante la lettura (a meno che non manchi).
    - Migra eventuali API key salvate in chiaro nel Credential Manager (`SecretVault`).
    - Rispetta i profili e i mood eliminati dall'utente (`user_overrides`) e mantiene tutte le modifiche utente.
    - Se il file JSON è corrotto, ne salva una copia di backup `config.corrupt.bak` prima di ripiegare sui default.
    """
    with _CONFIG_LOCK:
        ensure_data_dir()
        cleanup_legacy_browser_profiles()

        if not CONFIG_FILE.exists():
            fresh = copy.deepcopy(DEFAULT_CONFIG)
            fresh["analyzer"]["gemini_api_key"] = SecretVault.get_secret("gemini_api_key", "")
            fresh["analyzer"]["openai_api_key"] = SecretVault.get_secret("openai_api_key", "")
            save_config(fresh)
            return fresh

        try:
            raw_text = CONFIG_FILE.read_text(encoding="utf-8")
            user_cfg = json.loads(raw_text)
        except Exception as e:
            print(f"[Storage] Attenzione: config.json corrotto ({e}), creo backup config.corrupt.bak")
            try:
                shutil.copy2(CONFIG_FILE, DATA_DIR / "config.corrupt.bak")
            except Exception:
                pass
            fallback = copy.deepcopy(DEFAULT_CONFIG)
            fallback["_corrupt_warning"] = str(e)
            return fallback

        merged = copy.deepcopy(DEFAULT_CONFIG)
        overrides = user_cfg.get("user_overrides") if isinstance(user_cfg.get("user_overrides"), dict) else {}
        deleted_profiles: List[str] = list(overrides.get("deleted_profiles") or [])
        deleted_moods: Dict[str, List[str]] = {
            k: list(v) for k, v in (overrides.get("deleted_moods") or {}).items() if isinstance(v, list)
        }
        merged["user_overrides"] = {
            "deleted_profiles": deleted_profiles,
            "deleted_moods": deleted_moods,
        }

        # Validazione sezioni tramite Pydantic
        raw_analyzer = dict(merged["analyzer"])
        if isinstance(user_cfg.get("analyzer"), dict):
            raw_analyzer.update(user_cfg["analyzer"])
        validated_analyzer = AnalyzerSettingsModel(**raw_analyzer).model_dump()

        # Migrazione trasparente delle API key nel Credential Manager
        need_save_for_secret_migration = False
        for secret_field in ("gemini_api_key", "openai_api_key"):
            plain_val = (validated_analyzer.get(secret_field) or "").strip()
            if plain_val:
                SecretVault.set_secret(secret_field, plain_val)
                need_save_for_secret_migration = True
            validated_analyzer[secret_field] = SecretVault.get_secret(secret_field, plain_val)
        merged["analyzer"] = validated_analyzer

        raw_audio = dict(merged["audio"])
        if isinstance(user_cfg.get("audio"), dict):
            raw_audio.update(user_cfg["audio"])
        merged["audio"] = AudioSettingsModel(**raw_audio).model_dump()

        raw_stt = dict(merged["stt"])
        if isinstance(user_cfg.get("stt"), dict):
            raw_stt.update(user_cfg["stt"])
        merged["stt"] = STTSettingsModel(**raw_stt).model_dump()

        if isinstance(user_cfg.get("sfx"), dict):
            merged["sfx"].update(copy.deepcopy(user_cfg["sfx"]))

        # Gestione profili: rispetta eliminazioni e modifiche dell'utente
        user_profiles = user_cfg.get("profiles") if isinstance(user_cfg.get("profiles"), dict) else {}

        # Se nella versione precedente un profilo o mood predefinito era stato rimosso da `profiles`,
        # registralo automaticamente in `deleted_profiles` / `deleted_moods`!
        if user_profiles and "user_overrides" not in user_cfg:
            for def_pid in list(DEFAULT_CONFIG["profiles"].keys()):
                if def_pid not in user_profiles and def_pid != "giallo_investigativo":
                    if def_pid not in deleted_profiles:
                        deleted_profiles.append(def_pid)

        for def_pid in deleted_profiles:
            merged["profiles"].pop(def_pid, None)

        for pid, u_prof in user_profiles.items():
            if pid in deleted_profiles or not isinstance(u_prof, dict):
                continue
            if pid not in merged["profiles"]:
                # Profilo personalizzato creato dall'utente
                merged["profiles"][pid] = copy.deepcopy(u_prof)
            else:
                # Profilo predefinito: preserva nome/icona/descrizione personalizzati e unisci i mood
                def_prof = merged["profiles"][pid]
                for meta_k in ("name", "icon", "description", "default_mood"):
                    if u_prof.get(meta_k):
                        def_prof[meta_k] = u_prof[meta_k]

                def_moods = def_prof.get("moods", {})
                u_moods = u_prof.get("moods") if isinstance(u_prof.get("moods"), dict) else {}

                # Se nella vecchia config l'utente aveva cancellato un mood predefinito, ricordalo
                if u_moods and "user_overrides" not in user_cfg:
                    for d_mid in list(def_moods.keys()):
                        if d_mid not in u_moods:
                            deleted_moods.setdefault(pid, [])
                            if d_mid not in deleted_moods[pid]:
                                deleted_moods[pid].append(d_mid)

                for del_mid in deleted_moods.get(pid, []):
                    def_moods.pop(del_mid, None)

                for mid, u_m in u_moods.items():
                    if mid in deleted_moods.get(pid, []) or not isinstance(u_m, dict):
                        continue
                    u_m = dict(u_m)
                    u_m.setdefault("id", mid)
                    if mid not in def_moods:
                        def_moods[mid] = MoodModel(**u_m).model_dump()
                    else:
                        def_moods[mid] = _merge_mood_preserving_user_edits(def_moods[mid], u_m)

        if not merged["profiles"]:
            merged["profiles"] = copy.deepcopy(DEFAULT_CONFIG["profiles"])
            merged["user_overrides"]["deleted_profiles"] = []

        active_pid = user_cfg.get("active_profile_id", "fantasy_dnd")
        if active_pid not in merged["profiles"]:
            active_pid = next(iter(merged["profiles"].keys()))
        merged["active_profile_id"] = active_pid

        if need_save_for_secret_migration:
            save_config(merged)

        return merged


class ConfigManager:
    """Wrapper ergonomico per la gestione della configurazione."""

    @staticmethod
    def load() -> Dict[str, Any]:
        return load_config()

    @staticmethod
    def save(cfg: Dict[str, Any]) -> None:
        save_config(cfg)

    @staticmethod
    def load_from_file(path: Path) -> Dict[str, Any]:
        return load_config_from_path(path)


def load_config_from_path(path: Path) -> Dict[str, Any]:
    """Carica ed esegue la migrazione da un file specifico (usato nei test e backup)."""
    with _CONFIG_LOCK:
        if not path.is_file():
            return copy.deepcopy(DEFAULT_CONFIG)
        try:
            raw_text = path.read_text(encoding="utf-8")
            user_cfg = json.loads(raw_text)
        except Exception:
            return copy.deepcopy(DEFAULT_CONFIG)

        # Migrazione inline
        merged = copy.deepcopy(DEFAULT_CONFIG)
        merged["schema_version"] = 2
        # Migra eventuali segreti
        if user_cfg.get("gemini_api_key"):
            SecretVault.set_secret("gemini_api_key", user_cfg.pop("gemini_api_key"))
        if user_cfg.get("custom_sfx"):
            merged["custom_sfx"] = user_cfg["custom_sfx"]
        return merged


load_config_with_migration = load_config_from_path


def save_config(cfg: Dict[str, Any]) -> None:
    """
    Salva la configurazione in modo atomico e thread-safe:
    - Sposta le chiavi API nel Credential Manager (`SecretVault`) e scrive stringhe vuote nel JSON su disco.
    """
    with _CONFIG_LOCK:
        ensure_data_dir()
        disk_copy = copy.deepcopy(cfg)
        disk_copy.pop("_corrupt_warning", None)
        disk_copy["schema_version"] = CONFIG_SCHEMA_VERSION

        analyzer_sec = disk_copy.get("analyzer")
        if isinstance(analyzer_sec, dict):
            for secret_field in ("gemini_api_key", "openai_api_key"):
                if secret_field in analyzer_sec:
                    val = (analyzer_sec.get(secret_field) or "").strip()
                    if val:
                        SecretVault.set_secret(secret_field, val)
                    analyzer_sec[secret_field] = ""

        atomic_write_json(CONFIG_FILE, disk_copy)


def mark_profile_deleted(cfg: Dict[str, Any], profile_id: str) -> None:
    overrides = cfg.setdefault("user_overrides", {"deleted_profiles": [], "deleted_moods": {}})
    del_list = overrides.setdefault("deleted_profiles", [])
    if profile_id in DEFAULT_CONFIG["profiles"] and profile_id not in del_list:
        del_list.append(profile_id)
    cfg.get("profiles", {}).pop(profile_id, None)


def mark_mood_deleted(cfg: Dict[str, Any], profile_id: str, mood_id: str) -> None:
    overrides = cfg.setdefault("user_overrides", {"deleted_profiles": [], "deleted_moods": {}})
    del_moods = overrides.setdefault("deleted_moods", {})
    prof_del = del_moods.setdefault(profile_id, [])
    if (
        profile_id in DEFAULT_CONFIG["profiles"]
        and mood_id in DEFAULT_CONFIG["profiles"][profile_id].get("moods", {})
        and mood_id not in prof_del
    ):
        prof_del.append(mood_id)
    prof = cfg.get("profiles", {}).get(profile_id)
    if prof and "moods" in prof:
        prof["moods"].pop(mood_id, None)


def reset_default_profiles() -> Dict[str, Any]:
    with _CONFIG_LOCK:
        cfg = load_config()
        cfg["profiles"] = copy.deepcopy(DEFAULT_CONFIG["profiles"])
        cfg["user_overrides"] = {"deleted_profiles": [], "deleted_moods": {}}
        if cfg["active_profile_id"] not in cfg["profiles"]:
            cfg["active_profile_id"] = "fantasy_dnd"
        save_config(cfg)
        return cfg
