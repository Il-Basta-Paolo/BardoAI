"""
Gestore della Libreria Interna di Effetti Sonori (SFX) e Soundboard Istantanea ad Alta Chiarezza.
Include:
- Catalogo di 20 effetti sonori GdR masterizzati ad alta presenza (spadate, artigliate, frecce, scudi, ruggiti, magie, porte, dadi, monete, ecc.)
- Motore audio PCM in-memory a latenza zero tramite `sounddevice` (nessun taglio dell'attacco iniziale, polifonia a 6 canali)
- Audio Ducking automatico della musica di sottofondo quando parte un effetto sonoro (così ogni effetto si sente nitido sopra la musica)
- Riconoscimento vocale immediato di frasi e parole in italiano
"""

import shutil
import sys
import threading
import time
import wave
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable, Tuple

import numpy as np
import sounddevice as sd
import vlc_runtime  # noqa: F401
import vlc

from analyzer import normalize_italian


def resolve_sfx_directories() -> Path:
    """
    Risolve la cartella `sfx/` sia in esecuzione da sorgente sia dentro il file .exe (PyInstaller).
    Sincronizza automaticamente i 20 suoni masterizzati nella cartella `sfx/` accanto a BardoAI.exe.
    """
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        user_sfx_dir = exe_dir / "sfx"
        try:
            user_sfx_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        bundled_sfx_dir = Path(getattr(sys, "_MEIPASS", exe_dir)) / "sfx"
        if bundled_sfx_dir.exists() and bundled_sfx_dir.resolve() != user_sfx_dir.resolve():
            for wav_file in bundled_sfx_dir.glob("*.wav"):
                target = user_sfx_dir / wav_file.name
                try:
                    if (
                        not target.exists()
                        or target.stat().st_size != wav_file.stat().st_size
                        or abs(target.stat().st_mtime - wav_file.stat().st_mtime) > 1.0
                    ):
                        shutil.copy2(wav_file, target)
                except Exception:
                    pass
        if user_sfx_dir.exists() and any(user_sfx_dir.glob("*.wav")):
            return user_sfx_dir
        if bundled_sfx_dir.exists():
            return bundled_sfx_dir
        return user_sfx_dir
    else:
        src_sfx_dir = Path(__file__).resolve().parent / "sfx"
        src_sfx_dir.mkdir(parents=True, exist_ok=True)
        return src_sfx_dir


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
            "spada", "spadata", "spade", "fendente", "lama", "pugnale",
            "pugnalata", "sciabola", "stocco", "spadone", "coltellata", "katana",
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
            "artigli", "artiglio", "artigliata", "artigliate", "graffio",
            "graffia", "zampata", "squarcio", "squarcia", "lacera", "zanne", "morso", "morde", "azzanna",
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
            "scudo", "scudi", "parata", "para", "corazza", "elmo", "martello", "manganello", "mazza",
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
            "freccia", "frecce", "arco", "balestra", "dardo", "scocca", "scoccare", "faretra",
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
            "ruggito", "ruggisce", "ruggire", "drago", "tirannosauro", "behemoth", "idra", "wyvern",
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
            "ringhio", "ringhia", "ringhiare", "grugnito", "grugnisce", "orco",
            "goblin", "troll", "ogre", "demone", "bestia", "belva", "minotauro",
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
            "ululato", "ulula", "ululare", "lupo", "lupi", "licantropo", "mannaro", "branco",
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
            "zombie", "zombi", "non-morto", "non-morti", "ghoul", "spettro", "fantasma", "gemito",
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
            "urlo", "urla", "urlare", "grido", "grida", "strillo", "strilla",
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
            "esplosione", "esplode", "esplodere", "fiammata", "fiamme", "incendio",
            "bomba", "dinamite", "granata", "pirosfera", "brucia", "bruciando",
            "bruciate", "bruciare", "rogo",
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
            "fulmine", "fulmini", "saetta", "elettrico", "elettricita", "scossa", "folgore",
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
            "incantesimo", "magia", "pozione", "guarigione", "cura", "curare",
            "benedizione", "teletrasporto", "evoca", "mana",
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
            "scricchiola", "scricchiolio", "cigola", "cigolio", "cardini", "botola", "portone",
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
            "crollo", "crolla", "sfonda", "sfondare", "frana", "macigno", "masso", "schianto",
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
            "monete", "moneta", "oro", "ducati", "borsello", "forziere", "bottino", "pagare", "ricompensa",
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
            "brindisi", "brindare", "boccale", "boccali", "calice", "bicchiere", "birra", "vino",
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
            "tuono", "tuoni", "temporale", "tempesta", "lampo", "nubifragio",
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
            "battito", "pulsazione", "cuore", "ansia", "panico",
        ],
    },
}


class SFXManager:
    """
    Motore SFX stereo ibrido a latenza zero:
    - Pre-carica i file `.wav` in RAM come array float32 stereo (N, 2) a 44.1kHz e li riproduce con un mixer polifonico
      `sounddevice.OutputStream` sempre pronto (0ms di ritardo, nessun taglio iniziale, polifonia illimitata).
    - Curva di volume psicoacustica logaritmica (in dB) applicata in tempo reale nel callback audio.
    - Attiva un ducking morbido e proporzionale sulla musica di sottofondo così l'effetto si amalgama con naturalezza.
    """

    SAMPLE_RATE = 44100

    def __init__(
        self,
        on_sfx_triggered: Optional[Callable[[Dict[str, Any], str], None]] = None,
        on_duck_music: Optional[Callable[..., None]] = None,
    ) -> None:
        self.sfx_dir: Path = resolve_sfx_directories()
        self.on_sfx_triggered = on_sfx_triggered
        self.on_duck_music = on_duck_music

        self.sfx_volume: int = 80
        self._target_gain: float = self._vol_to_gain(self.sfx_volume)
        self._smoothed_gain: float = self._target_gain
        self.voice_sfx_enabled: bool = True
        self.duck_music_enabled: bool = True
        self._last_played_ts: Dict[str, float] = {}
        self.per_sfx_cooldown: float = 2.2

        # Cache PCM in RAM: path_str -> np.ndarray (float32 stereo (N, 2) 44100Hz)
        self._pcm_cache: Dict[str, np.ndarray] = {}
        self._active_voices: List[List[Any]] = []  # [[array_stereo, cursor_int, rel_trim_float], ...]
        self._mixer_lock = threading.Lock()
        self._stream: Optional[sd.OutputStream] = None

        # Fallback VLC solo per eventuali file custom .mp3/.ogg aggiunti dall'utente
        self._vlc_fallback: Optional[vlc.Instance] = None
        self._vlc_player: Optional[vlc.MediaPlayer] = None

        self._preload_wav_library()
        self._start_pcm_mixer_stream()

    @staticmethod
    def _vol_to_gain(vol: int) -> float:
        """
        Converte il valore 0..100 dello slider in guadagno lineare tramite curva psicoacustica (x^2.35).
        Garantisce che a 50% il volume percepito sia realmente dimezzato, sotto 25% sia discreto
        e a 0% sia silenzio assoluto.
        """
        v = max(0, min(100, int(vol)))
        if v <= 0:
            return 0.0
        norm = v / 100.0
        return float((norm ** 2.35) * 0.88)

    def _preload_wav_library(self) -> None:
        for wav_path in self.sfx_dir.glob("*.wav"):
            self._load_wav_into_ram(wav_path)

    def _load_wav_into_ram(self, wav_path: Path) -> Optional[np.ndarray]:
        key = str(wav_path.resolve())
        if key in self._pcm_cache:
            return self._pcm_cache[key]
        if not wav_path.exists():
            return None
        try:
            with wave.open(str(wav_path), "rb") as w:
                n_ch = w.getnchannels()
                sampwidth = w.getsampwidth()
                rate = w.getframerate()
                frames = w.readframes(w.getnframes())

            if sampwidth == 2:
                arr = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
            elif sampwidth == 4:
                arr = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
            else:
                arr = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0

            if n_ch <= 1:
                arr = np.stack([arr, arr], axis=1)
            else:
                arr = arr.reshape(-1, n_ch)[:, :2]

            if rate != self.SAMPLE_RATE and len(arr) > 0:
                new_len = max(1, int(len(arr) * self.SAMPLE_RATE / rate))
                old_idx = np.arange(len(arr))
                new_idx = np.linspace(0, len(arr) - 1, new_len)
                ch_l = np.interp(new_idx, old_idx, arr[:, 0]).astype(np.float32)
                ch_r = np.interp(new_idx, old_idx, arr[:, 1]).astype(np.float32)
                arr = np.stack([ch_l, ch_r], axis=1)

            self._pcm_cache[key] = arr
            return arr
        except Exception as e:
            print(f"[SFXManager] Errore caricamento WAV {wav_path}: {e}")
            return None

    def _start_pcm_mixer_stream(self) -> None:
        def audio_callback(outdata: np.ndarray, frames: int, _time_info: Any, _status: Any) -> None:
            outdata.fill(0.0)
            with self._mixer_lock:
                # Inseguimento morbido del guadagno target per evitare click durante il trascinamento dello slider
                self._smoothed_gain += 0.35 * (self._target_gain - self._smoothed_gain)
                if not self._active_voices:
                    return
                still_active = []
                mix = np.zeros((frames, 2), dtype=np.float32)
                master_g = self._smoothed_gain
                for voice in self._active_voices:
                    arr, pos, rel_trim = voice
                    rem = len(arr) - pos
                    if rem <= 0:
                        continue
                    n = min(frames, rem)
                    mix[:n] += arr[pos : pos + n] * (rel_trim * master_g)
                    voice[1] = pos + n
                    if voice[1] < len(arr):
                        still_active.append(voice)
                self._active_voices = still_active
                # Soft-limiter trasparente senza clipping duro
                np.tanh(mix, out=mix)
                outdata[:, 0] = mix[:, 0]
                if outdata.shape[1] > 1:
                    outdata[:, 1] = mix[:, 1]

        try:
            self._stream = sd.OutputStream(
                samplerate=self.SAMPLE_RATE,
                channels=2,
                dtype="float32",
                blocksize=512,
                callback=audio_callback,
            )
            self._stream.start()
        except Exception as e:
            print(f"[SFXManager] Impossibile avviare stream PCM diretto, uso fallback: {e}")
            self._stream = None

    def set_volume(self, vol: int) -> None:
        self.sfx_volume = max(0, min(100, int(vol)))
        new_gain = self._vol_to_gain(self.sfx_volume)
        with self._mixer_lock:
            self._target_gain = new_gain
        if self._vlc_player is not None:
            try:
                vlc_vol = int(round((self.sfx_volume / 100.0) ** 1.8 * 100.0))
                self._vlc_player.audio_set_volume(max(0, min(100, vlc_vol)))
            except Exception:
                pass

    def get_library(self, custom_sfx_cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
        lib = dict(DEFAULT_SFX_LIBRARY)
        if custom_sfx_cfg and isinstance(custom_sfx_cfg, dict):
            lib.update(custom_sfx_cfg)
        return lib

    def play_sfx(
        self,
        sfx_id: str,
        reason: str = "Soundboard",
        library: Optional[Dict[str, Any]] = None,
    ) -> bool:
        lib = library or DEFAULT_SFX_LIBRARY
        item = lib.get(sfx_id)
        if not item:
            return False

        file_path = self.sfx_dir / item.get("file", f"{sfx_id}.wav")
        if not file_path.exists():
            print(f"[SFXManager] File audio non trovato: {file_path}")
            return False

        #Sincronizza sempre _target_gain con sfx_volume corrente
        self._target_gain = self._vol_to_gain(self.sfx_volume)
        if self.sfx_volume <= 0:
            self._last_played_ts[sfx_id] = time.time()
            if self.on_sfx_triggered:
                try:
                    self.on_sfx_triggered(item, reason)
                except Exception:
                    pass
            return True

        dur_sec = 1.8
        rel_trim = float(item.get("trim", 1.0))

        arr = self._load_wav_into_ram(file_path) if file_path.suffix.lower() == ".wav" else None
        if arr is not None and self._stream is not None and self._stream.active:
            dur_sec = len(arr) / float(self.SAMPLE_RATE)
            with self._mixer_lock:
                self._active_voices.append([arr, 0, rel_trim])
            self._last_played_ts[sfx_id] = time.time()
        else:
            # Fallback per MP3/OGG personalizzati
            try:
                if self._vlc_fallback is None:
                    self._vlc_fallback = vlc.Instance(
                        "--no-video", "--vout=none", "--aout=directsound", "--intf=dummy", "--quiet"
                    )
                    self._vlc_player = self._vlc_fallback.media_player_new()
                media = self._vlc_fallback.media_new(str(file_path))
                self._vlc_player.set_media(media)
                vlc_vol = int(round((self.sfx_volume / 100.0) ** 1.8 * 100.0))
                self._vlc_player.audio_set_volume(max(0, min(100, vlc_vol)))
                self._vlc_player.play()
                self._last_played_ts[sfx_id] = time.time()
            except Exception:
                return False

        # Ducking morbido e proporzionale al volume degli effetti
        if self.duck_music_enabled and self.on_duck_music and self.sfx_volume > 10:
            try:
                self.on_duck_music(dur_sec, self.sfx_volume)
            except TypeError:
                try:
                    self.on_duck_music(dur_sec)
                except Exception:
                    pass
            except Exception:
                pass

        if self.on_sfx_triggered:
            try:
                self.on_sfx_triggered(item, reason)
            except Exception:
                pass
        return True

    def detect_and_play_from_speech(
        self,
        raw_text: str,
        library: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        if not self.voice_sfx_enabled:
            return []

        norm_text = normalize_italian(raw_text)
        if not norm_text:
            return []

        lib = library or DEFAULT_SFX_LIBRARY
        words = set(norm_text.split())
        now = time.time()

        scored_matches: List[Tuple[float, str, str]] = []

        for sfx_id, item in lib.items():
            if now - self._last_played_ts.get(sfx_id, 0.0) < self.per_sfx_cooldown:
                continue

            score = 0.0
            matched_term = ""

            for phrase in item.get("phrases", []):
                np_phrase = normalize_italian(phrase)
                if np_phrase and np_phrase in norm_text:
                    score += 4.0
                    matched_term = phrase
                    break

            if score == 0.0:
                for kw in item.get("keywords", []):
                    np_kw = normalize_italian(kw)
                    if not np_kw:
                        continue
                    if np_kw in words:
                        score += 2.5
                        matched_term = kw
                        break
                    elif len(np_kw) >= 5:
                        stem = np_kw[:-1]
                        if any(w.startswith(stem) for w in words if len(w) >= 5):
                            score += 2.0
                            matched_term = kw
                            break

            if score >= 2.0:
                scored_matches.append((score, sfx_id, matched_term))

        if not scored_matches:
            return []

        scored_matches.sort(key=lambda x: x[0], reverse=True)
        selected = scored_matches[:2]
        triggered_items: List[Dict[str, Any]] = []

        for idx, (_sc, sfx_id, term) in enumerate(selected):
            item = lib[sfx_id]
            triggered_items.append({"sfx": item, "term": term})
            if idx == 0:
                self.play_sfx(sfx_id, reason=f'Voce: "{term}"', library=lib)
            else:
                threading.Timer(
                    0.65,
                    lambda sid=sfx_id, trm=term: self.play_sfx(sid, reason=f'Voce: "{trm}"', library=lib),
                ).start()

        return triggered_items

    def shutdown(self) -> None:
        try:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
        except Exception:
            pass
        try:
            if self._vlc_player is not None:
                self._vlc_player.stop()
        except Exception:
            pass
