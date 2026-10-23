"""
Gestore degli Effetti Sonori (SFX) e Soundboard Istantanea ad Alta Chiarezza.
Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
Versione: 2.6.0:
- 20 effetti sonori masterizzati per GdR (armi, creature, magie, ambiente).
- Caricamento in RAM come PCM float32 stereo a 48kHz tramite PyAV (zero VLC, zero problemi di codec).
- Integrazione diretta con AudioEngine: ducking sample-accurate e soft-knee limiter.
- Riconoscimento vocale ultra-rapido con parsing delle negazioni e matching esatto a confini di parola:
  nessuna falsa attivazione tipo "al massimo" -> crollo, "lampada" -> tuono, "cardinale" -> porta.
- Gestione sicura degli SFX personalizzati in %APPDATA%/BardoAI/data/custom_sfx:
  nessun PermissionError in Program Files, nessuna sovrascrittura di file utente all'avvio.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import av
import numpy as np

from analyzer import normalize_italian, split_affirmed_and_negated_text
from storage import CUSTOM_SFX_DIR, DATA_DIR, ensure_data_dir


def get_bundled_sfx_dir() -> Path:
    """Ritorna la cartella `sfx/` inclusa nell'applicazione (read-only)."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parent
    bundled = base / "sfx"
    bundled.mkdir(parents=True, exist_ok=True)
    return bundled


def get_custom_sfx_dir() -> Path:
    """Ritorna la cartella scrivibile per gli SFX personalizzati dell'utente."""
    ensure_data_dir()
    return CUSTOM_SFX_DIR


DEFAULT_SFX_LIBRARY: Dict[str, Dict[str, Any]] = {
    "spada": {
        "id": "spada",
        "name": "Spadata / Lame",
        "icon": "⚔️",
        "category": "Armi",
        "color": "#ef4444",
        "file": "spada.wav",
        "hint": "spada • fendente • pugnale",
        "phrases": [
            "colpisce con la sua spada",
            "colpisce con la spada",
            "sfodera la spada",
            "tira un fendente",
            "colpo di spada",
            "affonda la lama",
            "ti pugnala",
            "incrociano le lame",
            "attacca con la spada",
        ],
        "keywords": [
            "spada", "spade", "spadata", "spadate", "fendente", "fendenti", "lama", "lame",
            "pugnale", "pugnali", "pugnalata", "pugnalate", "sciabola", "sciabole", "stocco",
            "spadone", "spadoni", "coltellata", "coltellate", "katana",
        ],
    },
    "artigli": {
        "id": "artigli",
        "name": "Artigliata / Morso",
        "icon": "🐾",
        "category": "Armi",
        "color": "#dc2626",
        "file": "artigli.wav",
        "hint": "artigli • zampata • morde",
        "phrases": [
            "colpisce con gli artigli",
            "graffia con gli artigli",
            "tira un artigliata",
            "lacera la carne",
            "zampata feroce",
            "azzanna alla gola",
        ],
        "keywords": [
            "artigli", "artiglio", "artigliata", "artigliate", "graffio", "graffi",
            "graffia", "zampata", "zampate", "squarcio", "squarcia", "lacera", "zanne",
            "morso", "morsi", "morde", "azzanna",
        ],
    },
    "scudo": {
        "id": "scudo",
        "name": "Parata / Scudo",
        "icon": "🛡️",
        "category": "Armi",
        "color": "#3b82f6",
        "file": "scudo.wav",
        "hint": "scudo • parata • corazza",
        "phrases": [
            "para con lo scudo",
            "blocca con lo scudo",
            "impatto sullo scudo",
            "alza lo scudo",
            "colpisce l armatura",
            "colpo di martello",
        ],
        "keywords": [
            "scudo", "scudi", "parata", "parate", "para", "corazza", "corazze",
            "elmo", "elmi", "martello", "martelli", "manganello", "mazza", "mazze",
        ],
    },
    "freccia": {
        "id": "freccia",
        "name": "Freccia / Arco",
        "icon": "🏹",
        "category": "Armi",
        "color": "#10b981",
        "file": "freccia.wav",
        "hint": "freccia • arco • balestra",
        "phrases": [
            "scocca una freccia",
            "tira con l arco",
            "spara con la balestra",
            "freccia sibila",
            "tende l arco",
        ],
        "keywords": [
            "freccia", "frecce", "arco", "archi", "balestra", "balestre",
            "dardo", "dardi", "scocca", "scoccare", "faretra",
        ],
    },
    "ruggito_drago": {
        "id": "ruggito_drago",
        "name": "Ruggito Drago",
        "icon": "🐉",
        "category": "Creature",
        "color": "#f97316",
        "file": "ruggito_drago.wav",
        "hint": "drago • ruggito • ruggisce",
        "phrases": [
            "ruggito assordante",
            "il drago ruggisce",
            "ruggisce ferocemente",
            "emette un ruggito",
        ],
        "keywords": [
            "ruggito", "ruggiti", "ruggisce", "ruggire", "drago", "draghi",
            "tirannosauro", "behemoth", "idra", "wyvern",
        ],
    },
    "mostro_ringhio": {
        "id": "mostro_ringhio",
        "name": "Ringhio / Orco",
        "icon": "👹",
        "category": "Creature",
        "color": "#ea580c",
        "file": "mostro_ringhio.wav",
        "hint": "ringhia • orco • troll",
        "phrases": [
            "ringhia contro di voi",
            "verso gutturale",
            "il mostro ringhia",
            "grido di guerra dell orco",
        ],
        "keywords": [
            "ringhio", "ringhi", "ringhia", "ringhiare", "grugnito", "grugniti",
            "grugnisce", "orco", "orchi", "goblin", "troll", "ogre", "demone",
            "demoni", "bestia", "bestie", "belva", "belve", "minotauro",
        ],
    },
    "lupo": {
        "id": "lupo",
        "name": "Ululato Lupo",
        "icon": "🐺",
        "category": "Creature",
        "color": "#64748b",
        "file": "lupo.wav",
        "hint": "ululato • lupo • branco",
        "phrases": [
            "ululato nella notte",
            "lupi in lontananza",
            "il lupo ulula",
        ],
        "keywords": [
            "ululato", "ululati", "ulula", "ululare", "lupo", "lupi",
            "licantropo", "licantropi", "mannaro", "mannari", "branco",
        ],
    },
    "zombie": {
        "id": "zombie",
        "name": "Zombie / Spettro",
        "icon": "🧟",
        "category": "Creature",
        "color": "#84cc16",
        "file": "zombie.wav",
        "hint": "zombie • non-morto • gemito",
        "phrases": [
            "gemito dei non morti",
            "zombie si avvicina",
            "lamento spettrale",
        ],
        "keywords": [
            "zombie", "zombi", "non-morto", "non-morti", "nonmorto", "nonmorti",
            "ghoul", "spettro", "spettri", "fantasma", "fantasmi", "gemito", "gemiti",
        ],
    },
    "urlo": {
        "id": "urlo",
        "name": "Urlo / Grido",
        "icon": "😱",
        "category": "Creature",
        "color": "#e11d48",
        "file": "urlo.wav",
        "hint": "urlo • grido • strillo",
        "phrases": [
            "urlo agghiacciante",
            "grido di dolore",
            "urla di terrore",
        ],
        "keywords": [
            "urlo", "urla", "urlare", "grido", "grida", "strillo", "strilli", "strilla",
        ],
    },
    "palla_di_fuoco": {
        "id": "palla_di_fuoco",
        "name": "Fuoco / Esplosione",
        "icon": "🔥",
        "category": "Magia",
        "color": "#ef4444",
        "file": "palla_di_fuoco.wav",
        "hint": "fuoco • brucia • esplode",
        "phrases": [
            "lancia palla di fuoco",
            "palla di fuoco",
            "soffio di fuoco",
            "grande esplosione",
            "esplode in mille pezzi",
            "state bruciando",
            "bruciando vivi",
            "prendete fuoco",
            "avvolti dalle fiamme",
        ],
        "keywords": [
            "esplosione", "esplosioni", "esplode", "esplodere", "fiammata", "fiammate",
            "fiamme", "incendio", "incendi", "bomba", "bombe", "dinamite", "granata",
            "granate", "pirosfera", "brucia", "bruciando", "bruciate", "bruciare", "rogo",
        ],
    },
    "fulmine": {
        "id": "fulmine",
        "name": "Fulmine / Scossa",
        "icon": "⚡",
        "category": "Magia",
        "color": "#eab308",
        "file": "fulmine.wav",
        "hint": "fulmine • saetta • scossa",
        "phrases": [
            "colpito da un fulmine",
            "lancia un fulmine",
            "scarica elettrica",
            "raggio elettrico",
        ],
        "keywords": [
            "fulmine", "fulmini", "saetta", "saette", "elettrico", "elettrica",
            "elettricita", "scossa", "scosse", "folgore", "folgori",
        ],
    },
    "incantesimo": {
        "id": "incantesimo",
        "name": "Incantesimo / Cura",
        "icon": "✨",
        "category": "Magia",
        "color": "#a855f7",
        "file": "incantesimo.wav",
        "hint": "incantesimo • cura • magia",
        "phrases": [
            "lancia un incantesimo",
            "cura ferite",
            "beve la pozione",
            "luce magica",
            "parola guaritrice",
        ],
        "keywords": [
            "incantesimo", "incantesimi", "magia", "magie", "pozione", "pozioni",
            "guarigione", "guarigioni", "cura", "curare", "benedizione", "teletrasporto",
            "evoca", "evocare", "mana",
        ],
    },
    "porta_scricchiola": {
        "id": "porta_scricchiola",
        "name": "Porta / Cigolio",
        "icon": "🚪",
        "category": "Ambiente",
        "color": "#b45309",
        "file": "porta_scricchiola.wav",
        "hint": "porta • scricchiola • botola",
        "phrases": [
            "la porta scricchiola",
            "apre la porta lentamente",
            "aprite la porta",
            "cigolio sinistro",
        ],
        "keywords": [
            "scricchiola", "scricchiolio", "cigola", "cigolio", "cardine", "cardini",
            "botola", "botole", "portone", "portoni",
        ],
    },
    "crollo": {
        "id": "crollo",
        "name": "Crollo / Schianto",
        "icon": "💥",
        "category": "Ambiente",
        "color": "#78716c",
        "file": "crollo.wav",
        "hint": "crolla • sfonda • frana",
        "phrases": [
            "sfonda la porta",
            "il soffitto crolla",
            "cade a terra con un tonfo",
            "frana di rocce",
        ],
        "keywords": [
            "crollo", "crolli", "crolla", "crollare", "sfonda", "sfondare",
            "frana", "frane", "macigno", "macigni", "masso", "massi", "schianto",
        ],
    },
    "monete": {
        "id": "monete",
        "name": "Monete / Tesoro",
        "icon": "💰",
        "category": "Ambiente",
        "color": "#f59e0b",
        "file": "monete.wav",
        "hint": "monete • oro • forziere",
        "phrases": [
            "monete d oro",
            "borsello di monete",
            "paga l oste",
            "trovate un tesoro",
        ],
        "keywords": [
            "monete", "moneta", "oro", "ducati", "ducato", "borsello", "forziere",
            "forzieri", "bottino", "pagare", "ricompensa",
        ],
    },
    "dadi": {
        "id": "dadi",
        "name": "Tiro di Dadi",
        "icon": "🎲",
        "category": "Ambiente",
        "color": "#ec4899",
        "file": "dadi.wav",
        "hint": "dadi • critico • iniziativa",
        "phrases": [
            "tira il dado",
            "tirate i dadi",
            "venti naturale",
            "uno naturale",
            "tiro salvezza",
            "tirate iniziativa",
        ],
        "keywords": [
            "dado", "dadi", "d20", "critico", "fallimento",
        ],
    },
    "brindisi": {
        "id": "brindisi",
        "name": "Brindisi / Birra",
        "icon": "🍺",
        "category": "Ambiente",
        "color": "#d97706",
        "file": "brindisi.wav",
        "hint": "brindisi • boccale • birra",
        "phrases": [
            "facciamo un brindisi",
            "alza il boccale",
            "alla salute",
            "versa da bere",
        ],
        "keywords": [
            "brindisi", "brindare", "boccale", "boccali", "calice", "calici",
            "bicchiere", "bicchieri", "birra", "vino",
        ],
    },
    "tuono": {
        "id": "tuono",
        "name": "Tuono / Tempesta",
        "icon": "⛈️",
        "category": "Ambiente",
        "color": "#38bdf8",
        "file": "tuono.wav",
        "hint": "tuono • temporale • lampo",
        "phrases": [
            "rombo di tuono",
            "scoppia un temporale",
            "lampi e tuoni",
        ],
        "keywords": [
            "tuono", "tuoni", "temporale", "temporali", "tempesta", "tempeste",
            "lampo", "lampi", "nubifragio",
        ],
    },
    "campana": {
        "id": "campana",
        "name": "Campana a Morto",
        "icon": "🔔",
        "category": "Ambiente",
        "color": "#ca8a04",
        "file": "campana.wav",
        "hint": "campana • rintocco • gong",
        "phrases": [
            "suona la campana",
            "rintocchi di mezzanotte",
            "campana a morto",
        ],
        "keywords": [
            "campana", "campane", "rintocco", "rintocchi", "campanile", "gong",
        ],
    },
    "battito": {
        "id": "battito",
        "name": "Battito Cardiaco",
        "icon": "❤️",
        "category": "Ambiente",
        "color": "#be123c",
        "file": "battito.wav",
        "hint": "battito • cuore • panico",
        "phrases": [
            "cuore batte forte",
            "battito cardiaco",
            "cuore in gola",
        ],
        "keywords": [
            "battito", "battiti", "pulsazione", "pulsazioni", "cuore", "ansia", "panico",
        ],
    },
}


def load_audio_file_to_pcm(path: Path, target_sample_rate: int = 48000) -> Optional[np.ndarray]:
    """
    Decodifica qualsiasi file audio supportato da PyAV (WAV, MP3, OGG, FLAC) in PCM
    float32 stereo (N, 2) a 48000Hz normalizzato in [-1.0, 1.0].
    """
    if not path.is_file():
        return None
    try:
        container = av.open(str(path))
        if not container.streams.audio:
            container.close()
            return None
        resampler = av.AudioResampler(format="fltp", layout="stereo", rate=target_sample_rate)
        chunks: List[np.ndarray] = []
        for frame in container.decode(audio=0):
            for resampled in resampler.resample(frame):
                chunks.append(resampled.to_ndarray())
        container.close()
        if not chunks:
            return None
        # to_ndarray con layout stereo restituisce (2, frames)
        full = np.concatenate(chunks, axis=1).T.astype(np.float32)
        # Assicura limiti numerici corretti
        np.clip(full, -1.0, 1.0, out=full)
        return full
    except Exception as e:
        print(f"[SFXManager] Errore decodifica audio {path}: {e}")
        return None


class SFXManager:
    """
    Gestore della Soundboard e degli SFX guidati dalla voce.
    Si interfaccia direttamente con l'AudioEngine per il playback sample-accurate e il ducking.
    """

    SAMPLE_RATE = 48000

    def __init__(
        self,
        audio_engine: Optional[Any] = None,
        on_sfx_triggered: Optional[Callable[[Dict[str, Any], str], None]] = None,
        custom_sfx_dir: Optional[Path] = None,
        bundled_sfx_dir: Optional[Path] = None,
    ) -> None:
        self.audio_engine = audio_engine
        self.on_sfx_triggered = on_sfx_triggered

        self.bundled_dir = bundled_sfx_dir or get_bundled_sfx_dir()
        self.custom_dir = custom_sfx_dir or get_custom_sfx_dir()

        self.voice_sfx_enabled: bool = True
        self.per_sfx_cooldown: float = 2.2
        self._last_played_ts: Dict[str, float] = {}

        # Cache PCM in RAM: path_str -> np.ndarray (N, 2) float32
        self._pcm_cache: Dict[str, np.ndarray] = {}
        self._cache_lock = threading.Lock()

        # Cache regex compilate per keyword e frasi
        self._compiled_keywords: Dict[str, List[re.Pattern]] = {}
        self._compiled_phrases: Dict[str, List[str]] = {}

        # Libreria personalizzata persistita su file
        self._custom_manifest_path = self.custom_dir / "manifest.json"
        self._custom_library: Dict[str, Dict[str, Any]] = self._load_custom_manifest()

        self._compile_matchers()
        self._preload_bundled_sfx()

    # ================================================================ Custom Manifest
    def _load_custom_manifest(self) -> Dict[str, Dict[str, Any]]:
        if not self._custom_manifest_path.is_file():
            return {}
        try:
            with open(self._custom_manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception as e:
            print(f"[SFXManager] Errore lettura manifest custom SFX: {e}")
            return {}

    def _save_custom_manifest(self) -> None:
        try:
            tmp = self._custom_manifest_path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._custom_library, f, indent=2, ensure_ascii=False)
            tmp.replace(self._custom_manifest_path)
        except Exception as e:
            print(f"[SFXManager] Errore salvataggio manifest custom SFX: {e}")

    # ================================================================ Preload & Regex
    def _compile_matchers(self) -> None:
        lib = self.get_library()
        new_kw: Dict[str, List[re.Pattern]] = {}
        new_ph: Dict[str, List[str]] = {}
        for sid, item in lib.items():
            # Compila keyword con word boundary esatti: \bkeyword\b
            patterns = []
            for kw in item.get("keywords", []):
                norm = normalize_italian(kw).strip()
                if norm:
                    pat = re.compile(rf"\b{re.escape(norm)}\b", re.IGNORECASE)
                    patterns.append(pat)
            new_kw[sid] = patterns

            # Normalizza le frasi
            phrases = []
            for ph in item.get("phrases", []):
                norm_p = normalize_italian(ph).strip()
                if norm_p:
                    phrases.append(norm_p)
            new_ph[sid] = phrases

        self._compiled_keywords = new_kw
        self._compiled_phrases = new_ph

    def _preload_bundled_sfx(self) -> None:
        """Pre-carica in memoria i WAV predefiniti in un thread in background per non bloccare l'avvio."""
        def worker() -> None:
            for sid, item in DEFAULT_SFX_LIBRARY.items():
                p = self.resolve_file(item.get("file", f"{sid}.wav"))
                if p:
                    self._get_or_load_pcm(p)

        t = threading.Thread(target=worker, daemon=True, name="sfx-preload")
        t.start()

    def resolve_file(self, filename: str) -> Optional[Path]:
        """
        Risolve un file audio:
        1. Cerca in custom_dir (file aggiunto dall'utente)
        2. Cerca in bundled_dir (asset inclusi)
        3. Cerca come percorso assoluto
        """
        cand_custom = self.custom_dir / filename
        if cand_custom.is_file():
            return cand_custom
        cand_bundled = self.bundled_dir / filename
        if cand_bundled.is_file():
            return cand_bundled
        cand_abs = Path(filename)
        if cand_abs.is_file():
            return cand_abs
        return None

    def _get_or_load_pcm(self, path: Path) -> Optional[np.ndarray]:
        key = str(path.resolve())
        with self._cache_lock:
            if key in self._pcm_cache:
                return self._pcm_cache[key]
        arr = load_audio_file_to_pcm(path, self.SAMPLE_RATE)
        if arr is not None:
            with self._cache_lock:
                self._pcm_cache[key] = arr
        return arr

    # ================================================================ Library Access
    def get_library(self) -> Dict[str, Dict[str, Any]]:
        """Restituisce l'unione ordinata della libreria predefinita e di quella personalizzata."""
        lib = dict(DEFAULT_SFX_LIBRARY)
        lib.update(self._custom_library)
        return lib

    def get_categories(self) -> List[str]:
        cats = ["Tutti", "Armi", "Creature", "Magia", "Ambiente"]
        if self._custom_library:
            cats.append("Personalizzati")
        return cats

    def add_custom_sfx(
        self,
        sfx_id: str,
        name: str,
        source_audio_path: Path,
        category: str = "Personalizzati",
        icon: str = "🎵",
        color: str = "#8b5cf6",
        keywords: Optional[List[str]] = None,
        phrases: Optional[List[str]] = None,
    ) -> bool:
        """
        Aggiunge un SFX personalizzato: copia il file audio nella directory custom
        e registra l'effetto nel manifest. Nessun rischio di permessi in Program Files.
        """
        if not source_audio_path.is_file():
            return False
        dest_filename = f"{sfx_id}{source_audio_path.suffix.lower()}"
        dest_path = self.custom_dir / dest_filename
        try:
            shutil.copy2(source_audio_path, dest_path)
        except Exception as e:
            print(f"[SFXManager] Impossibile copiare il file SFX {source_audio_path}: {e}")
            return False

        item: Dict[str, Any] = {
            "id": sfx_id,
            "name": name,
            "icon": icon,
            "category": category,
            "color": color,
            "file": dest_filename,
            "hint": ", ".join((keywords or [])[:3]),
            "phrases": phrases or [],
            "keywords": keywords or [],
            "trim": 1.0,
            "custom": True,
        }
        self._custom_library[sfx_id] = item
        self._save_custom_manifest()
        self._compile_matchers()
        self._get_or_load_pcm(dest_path)
        return True

    def delete_custom_sfx(self, sfx_id: str) -> bool:
        """Rimuove un SFX personalizzato e cancella il file corrispondente se presente in custom_dir."""
        if sfx_id not in self._custom_library:
            return False
        item = self._custom_library.pop(sfx_id)
        self._save_custom_manifest()
        self._compile_matchers()
        dest = self.custom_dir / item.get("file", "")
        if dest.is_file():
            try:
                dest.unlink()
            except Exception:
                pass
        return True

    # ================================================================ Playback
    def play_sfx(
        self,
        sfx_id: str,
        reason: str = "Soundboard",
        duck_music: bool = True,
    ) -> bool:
        """
        Riproduce l'effetto sonoro tramite l'AudioEngine polifonico ed effettua il ducking della musica.
        """
        lib = self.get_library()
        item = lib.get(sfx_id)
        if not item:
            return False

        file_path = self.resolve_file(item.get("file", f"{sfx_id}.wav"))
        if not file_path:
            print(f"[SFXManager] File SFX non trovato: {item.get('file')}")
            return False

        arr = self._get_or_load_pcm(file_path)
        if arr is None or len(arr) == 0:
            return False

        trim = float(item.get("trim", 1.0))
        dur_sec = len(arr) / float(self.SAMPLE_RATE)
        self._last_played_ts[sfx_id] = time.time()

        if self.audio_engine is not None:
            try:
                self.audio_engine.play_sfx(arr, trim)
                if duck_music:
                    self.audio_engine.duck(dur_sec)
            except Exception as e:
                print(f"[SFXManager] Errore riproduzione in AudioEngine: {e}")
                return False

        if self.on_sfx_triggered:
            try:
                self.on_sfx_triggered(item, reason)
            except Exception:
                pass

        return True

    # ================================================================ Voice Matching
    def detect_and_play_from_speech(self, raw_text: str) -> List[Dict[str, Any]]:
        """
        Analizza il testo della voce trascritto in streaming o a fine frase.
        Caratteristiche chiave per prevenire falsi positivi (risolve bug #6 di bastaaaa.md):
        1. Parsing delle negazioni: se un termine è in una clausola negata ("non tirate i dadi"), NON si attiva.
        2. Boundary regex esatti: "al massimo" non attiva "masso" (crollo), "lampada" non attiva "lampo" (tuono),
           "cardinale" non attiva "cardini" (porta).
        3. Nessuno stem trimming arbitrario tipo `stem = kw[:-1]`.
        4. Cooldown per-SFX (2.2s).
        """
        if not self.voice_sfx_enabled or not raw_text.strip():
            return []

        # Divide il testo in clausole affermate e negate
        affirmed_text, _ = split_affirmed_and_negated_text(raw_text)
        if not affirmed_text:
            return []

        norm_text = affirmed_text.strip()
        if not norm_text:
            return []

        now = time.time()
        scored_matches: List[Tuple[float, str, str]] = []

        lib = self.get_library()
        for sfx_id, item in lib.items():
            if now - self._last_played_ts.get(sfx_id, 0.0) < self.per_sfx_cooldown:
                continue

            score = 0.0
            matched_term = ""

            # 1. Matching su frasi intere
            for phrase in self._compiled_phrases.get(sfx_id, []):
                if phrase in norm_text:
                    score += 4.0
                    matched_term = phrase
                    break

            # 2. Matching su parole chiave con confini esatti (\bword\b)
            if score == 0.0:
                for pat in self._compiled_keywords.get(sfx_id, []):
                    m = pat.search(norm_text)
                    if m:
                        score += 2.5
                        matched_term = m.group(0)
                        break

            if score >= 2.0:
                scored_matches.append((score, sfx_id, matched_term))

        if not scored_matches:
            return []

        # Ordina per punteggio e limita a massimo 2 effetti per battuta vocale
        scored_matches.sort(key=lambda x: x[0], reverse=True)
        selected = scored_matches[:2]
        triggered: List[Dict[str, Any]] = []

        for idx, (_sc, sfx_id, term) in enumerate(selected):
            item = lib[sfx_id]
            triggered.append({"sfx": item, "term": term})
            if idx == 0:
                self.play_sfx(sfx_id, reason=f'Voce: "{term}"')
            else:
                threading.Timer(
                    0.65,
                    lambda sid=sfx_id, trm=term: self.play_sfx(sid, reason=f'Voce: "{trm}"'),
                ).start()

        return triggered
