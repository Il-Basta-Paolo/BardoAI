"""
Motore di analisi semantica, morfologica e contestuale in Italiano per Bardo AI v2.6.0.
Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

import json
import re

__author__ = "Paolo Basta"
import unicodedata
from collections import deque
from typing import Dict, Any, List, Optional, Deque, Tuple, Set

import httpx


# Pattern omografi da disambiguare PRIMA della rimozione degli accenti
# (es. "farò" verbo futuro vs "faro" sostantivo marittimo; "dà" verbo dare)
_ACCENTED_FUTURE_FARE_RE = re.compile(r"\bfar[òo]\b", re.IGNORECASE)


def normalize_italian(text: str) -> str:
    """
    Normalizza il testo italiano convertendo in minuscolo, preservando i confini di parola
    e neutralizzando gli omografi accentati (es. 'farò' -> 'faro_verbo').
    """
    raw = text.lower().strip()
    # Se c'è esplicitamente l'accento grave su "farò", marcalo come verbo futuro
    raw = re.sub(r"\bfar[ò]\b", "faroverbo", raw)
    raw = re.sub(r"['’`]", " ", raw)
    nfkd = unicodedata.normalize("NFKD", raw)
    no_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    cleaned = re.sub(r"[^a-z0-9\s-]", " ", no_accents)
    norm = re.sub(r"\s+", " ", cleaned).strip()
    # Anche senza accento (es. output STT "lo faro", "ce la faro", "non lo faro", "cosa faro", "ti faro", "vi faro"):
    norm = re.sub(
        r"\b(lo|la|li|le|ne|cosa|come|quando|non|ti|vi|ci|mi|gli|si)\s+faro\b",
        r"\1 faroverbo",
        norm,
    )
    norm = re.sub(r"\bfaro\s+(del\s+mio|un|una|qualcosa|questo|quello|come|subito|dopo|domani)\b", r"faroverbo \1", norm)
    return norm


# =============================================================================
# PARSER DI NEGAZIONE ITALIANO PER CLAUSOLA SINTATTICA
# =============================================================================

# Congiunzioni avversative o cambi di clausola dove termina l'effetto di una negazione precedente
CLAUSE_BREAK_PATTERN = re.compile(
    r"(?:[,;.:!?]+|\b(?:ma|pero|tuttavia|eppure|anzi|invece|all\s+improvviso|improvvisamente|quando\s+ad\s+un\s+tratto|ad\s+un\s+tratto)\b)",
    re.IGNORECASE,
)

# Espressioni di negazione in italiano che annullano i trigger di pericolo/scena/SFX che le seguono nella stessa clausola
NEGATION_TOKENS = {
    "non", "nessun", "nessuno", "nessuna", "senza", "mai", "mica",
    "neanche", "nemmeno", "neppure", "niente", "nulla", "zero",
}

NEGATION_PHRASES = (
    "non c e",
    "non ci sono",
    "non vedete",
    "non sentite",
    "non trovate",
    "non subisci",
    "non subite",
    "non parte",
    "non scatta",
    "senza alcun",
    "senza nessun",
    "nessuna traccia di",
)

# Espressioni in cui "danno" è la 3ª persona plurale del verbo "dare" e NON un danno da combattimento
SAFE_DARE_PATTERNS = (
    "vi danno", "mi danno", "ti danno", "ci danno", "gli danno", "le danno", "si danno",
    "danno il benvenuto", "danno ospitalita", "danno da bere", "danno da mangiare",
    "danno una mano", "danno alloggio", "danno indicazioni", "danno informazioni",
    "danno ragione", "danno ascolto", "danno inizio alla festa", "danno spettacolo",
    "danno su", "danno sulla", "danno sul", "finestre che danno",
)

# Espressioni in cui "fuoco" indica un fuoco tranquillo (camino, bivacco, accampamento, cucina) e NON un combattimento
SAFE_COZY_FIRE_PATTERNS = (
    "intorno al fuoco",
    "accanto al fuoco",
    "vicino al fuoco",
    "davanti al fuoco",
    "attorno al fuoco",
    "fuoco da campo",
    "fuoco del camino",
    "fuoco acceso",
    "bel fuoco",
    "calore del fuoco",
    "scaldarsi al fuoco",
    "scaldatevi al fuoco",
    "vi scaldate al fuoco",
    "seduti al fuoco",
    "accendete il fuoco",
    "accendere il fuoco",
    "accendiamo il fuoco",
    "accendete il falo",
    "intorno al falo",
    "fuoco per cucinare",
    "pentola sul fuoco",
    "carne sul fuoco",
)


def split_affirmed_and_negated_text(raw_text: str) -> Tuple[str, str]:
    """
    Divide il testo in clausole sintattiche (separate da punteggiatura o congiunzioni avversative come 'ma', 'però', 'all'improvviso')
    e separa le porzioni AFFERMATE da quelle NEGATE.
    Restituisce: (affirmed_norm_text, negated_norm_text)
    Esempio:
      - "Non ci sono nemici nella stanza" -> affirmed="", negated="non ci sono nemici nella stanza"
      - "Non ci sono nemici, ma un orco vi attacca!" -> affirmed="un orco vi attacca", negated="non ci sono nemici"
      - "Avanzate senza fare rumore e senza sfoderare la spada" -> affirmed="avanzate", negated="senza fare rumore e senza sfoderare la spada"
    """
    clauses = CLAUSE_BREAK_PATTERN.split(raw_text)
    affirmed_parts: List[str] = []
    negated_parts: List[str] = []

    for clause in clauses:
        norm_c = normalize_italian(clause)
        if not norm_c:
            continue

        tokens = norm_c.split()
        neg_start_idx: Optional[int] = None

        for i, tok in enumerate(tokens):
            if tok in NEGATION_TOKENS:
                # Eccezione: "non morti" / "non-morti" / "non morto" è un sostantivo (undead), non una negazione!
                if tok == "non" and i + 1 < len(tokens) and tokens[i + 1].startswith("mort"):
                    continue
                neg_start_idx = i
                break

        if neg_start_idx is None:
            for np_pat in NEGATION_PHRASES:
                if np_pat in norm_c:
                    neg_start_idx = 0
                    break

        if neg_start_idx is None:
            affirmed_parts.append(norm_c)
        else:
            if neg_start_idx > 0:
                affirmed_parts.append(" ".join(tokens[:neg_start_idx]))
            negated_parts.append(" ".join(tokens[neg_start_idx:]))

    return " ".join(affirmed_parts).strip(), " ".join(negated_parts).strip()


def clean_false_positive_collocations(norm_text: str) -> str:
    """
    Neutralizza nel testo affermato i costrutti idiomatici che contengono omografi
    di parole di pericolo o biomi (es. 'vi danno il benvenuto', 'costa dieci monete', 'è reale').
    """
    out = norm_text
    for pat in SAFE_DARE_PATTERNS:
        if pat in out:
            out = out.replace(pat, pat.replace("danno", "offrono"))
    for pat in SAFE_COZY_FIRE_PATTERNS:
        if pat in out:
            out = out.replace(pat, pat.replace("fuoco", "bivacco"))
    # "costa <numero>" o "quanto costa" -> verbo costare (prezzo), non costa marittima
    out = re.sub(
        r"\bcosta\s+(?:solo\s+|circa\s+|almeno\s+)?(?:\d+|un|una|due|tre|quattro|cinque|sei|sette|otto|nove|dieci|venti|trenta|quaranta|cinquanta|cento|mille|poco|troppo|molto| caro|cara|monete|oro)\b",
        "prezzo monete",
        out,
    )
    out = re.sub(r"\b(?:quanto|cosa|che)\s+costa\b", "prezzo", out)
    # "è reale", "non è reale", "mondo reale", "in tempo reale", "vita reale" -> aggettivo "vero", non "del Re"
    out = re.sub(r"\b(?:e|sembra|mondo|tempo|vita|visione|tutto|molto)\s+reale\b", "vero", out)
    return out


def preprocess_text_for_analysis(text: str) -> str:
    """Normalizza e pulisce le collocazioni di falsi positivi nel testo."""
    norm = normalize_italian(text)
    return clean_false_positive_collocations(norm)



# =============================================================================
# DIZIONARIO DI PERICOLO, BOSS E BIOMI
# =============================================================================

CATASTROPHIC_PHRASES = [
    "state bruciando vivi",
    "bruciando vivi",
    "bruciati vivi",
    "bruciano vivi",
    "avvolti dalle fiamme",
    "avvolto dalle fiamme",
    "siete in fiamme",
    "prendete fuoco",
    "prende fuoco",
    "soffio di fuoco",
    "palla di fuoco",
    "cade nella lava",
    "fiume di lava",
    "state morendo",
    "stiamo morendo",
    "sta morendo",
    "siete spacciati",
    "ruggito assordante",
    "azioni leggendarie",
    "resistenza leggendaria",
    "boss finale",
    "seconda fase",
    "massacro totale",
    "urla di agonia",
    "urla di dolore",
]

COMBAT_DAMAGE_PHRASES = (
    "subisci danno",
    "subite danno",
    "subisce danno",
    "punti danno",
    "punto danno",
    "fai danno",
    "fa danno",
    "fanno danno",
    "tiro del danno",
    "tira il danno",
    "tirate i danni",
    "quanti danni",
    "subisci danni",
    "subite danni",
    "danno da fuoco",
    "danno da acido",
    "danno da veleno",
    "danno da taglio",
    "danno contundente",
    "danno perforante",
    "danno necrotico",
    "danno radioso",
    "danno psichico",
    "prendete fuoco",
    "prende fuoco",
    "aprono il fuoco",
    "aprite il fuoco",
    "a fuoco",
    "in fiamme",
)

DANGER_WORD_STEMS = (
    "bruci",      # brucia, bruciando, bruciate, bruciare, bruciati
    "fiamm",      # fiamma, fiamme, fiammata
    "incend",     # incendio, incendiato
    "incener",    # incenerito, incenerire
    "esplod",     # esplode, esplodono, esplodere
    "esplos",     # esplosione, esplosioni
    "uccid",      # uccide, uccidono, uccidere, ucciso
    "ammazz",     # ammazza, ammazzare, ammazzati
    "morir",      # morire, morirete
    "morend",     # morendo
    "muor",       # muore, muoiono
    "agoni",      # agonia, agonizzante
    "sbran",      # sbrana, sbranato, sbranare
    "divor",      # divora, divorato
    "squarci",    # squarcia, squarciato, squarcio
    "lacer",      # lacera, lacerato
    "decapit",    # decapita, decapitato
    "massacr",     # massacro, massacrati
    "stermin",    # sterminio, sterminati
    "assal",      # assale, assalgono, assalto, assaliti
    "imboscat",   # imboscata
    "attacc",     # attacca, attaccano, attaccare, attacco
    "colpisc",    # colpisce, colpiscono
    "colpit",     # colpito, colpiti
    "combatt",    # combattimento, combattere, combattete
    "battagli",   # battaglia
    "ferit",      # ferita, ferite, ferito, feriti
    "sanguin",    # sanguina, sanguinando, sanguinante
    "dissangu",   # dissanguato
    "soffoc",     # soffoca, soffocando
    "anneg",      # annega, annegando
    "strangol",   # strangola, strangolato
    "avvelen",    # avvelenato, avvelena
    "schiacci",   # schiaccia, schiacciato
    "pugnal",     # pugnale, pugnala, pugnalata
    "fendent",    # fendente
    "artigli",    # artigli, artigliata
    "azzann",     # azzanna, azzannato
    "sparator",   # sparatoria
    "proiettil",  # proiettile, proiettili
)

# NOTA: "danno" e "fuoco" NON sono in DANGER_EXACT_WORDS isolati (vengono gestiti tramite COMBAT_DAMAGE_PHRASES
# e controllo di contesto, mentre "danni" plurale è sempre inequivocabile).
DANGER_EXACT_WORDS = {
    "rogo", "acido", "veleno", "danni",
    "spada", "spadata", "spade", "ascia", "freccia", "frecce",
    "balestra", "iniziativa", "nemico", "nemici",
    "orco", "orchi", "goblin", "troll", "drago", "demone", "lich",
    "imboscata", "caricano", "morde", "zanne", "panico", "terrore",
    "bomba", "granata", "sparo", "spara", "sparatoria",
}

CALM_MOOD_IDS = {
    "accampamento", "taverna", "citta", "esplorazione", "vittoria",
    "indagine", "rifugio", "metropoli", "club", "spazio",
    "scena_crimine", "deduzione", "rivelazione",
}

CALM_TONE_PROFILES = {
    "calm_rest", "upbeat_tavern", "city", "exploration", "victory",
}

# =============================================================================
# 15 BIOMI E AMBIENTI PRIVI DI PAROLE SINGOLE AMBIGUE
# =============================================================================
ENVIRONMENT_BIOMES: List[Dict[str, Any]] = [
    {
        "env_id": "neve_ghiaccio",
        "name": "❄️ Valle Innevata & Ghiaccio",
        "color": "#38bdf8",
        "preferred_moods": ["esplorazione", "spazio", "indagine"],
        "specificity": 1.6,
        "phrases": [
            "valle innevata", "montagne innevate", "vette innevate", "foresta innevata",
            "distesa di neve", "distesa di ghiaccio", "bufera di neve", "tormenta di neve",
            "freddo gelido", "freddo polare", "vento gelido", "lago ghiacciato",
            "terre del nord", "passo innevato", "sotto la neve", "sta nevicando",
            "in mezzo alla neve", "tra i ghiacci",
        ],
        "keywords": [
            "neve", "ghiaccio", "ghiacciaio", "gelo", "tundra", "artico",
            "tormenta", "bufera", "brina", "slavina", "valanga", "iceberg",
        ],
        "stems": ("innev", "nevic", "ghiacci", "gelid", "glac"),
        "query": "Skyrim Frostfall Wind Guide You winter snow tundra rpg instrumental",
        "seed_tracks": [
            {"videoId": "2-ggCHn4Zjo", "title": "Frostfall (Snow & Ice Instrumental)", "artist": "Jeremy Soule (Skyrim OST)", "duration": "3:27", "thumbnail": "https://i.ytimg.com/vi/2-ggCHn4Zjo/hqdefault.jpg"},
            {"videoId": "2lBU5bi-u-I", "title": "The Jerall Mountains (Snowy Valley Instrumental)", "artist": "Jeremy Soule (Skyrim OST)", "duration": "3:20", "thumbnail": "https://i.ytimg.com/vi/2lBU5bi-u-I/hqdefault.jpg"},
            {"videoId": "sx3aFAfQrZA", "title": "Tundra (Winter Instrumental)", "artist": "Jeremy Soule (Skyrim OST)", "duration": "3:50", "thumbnail": "https://i.ytimg.com/vi/sx3aFAfQrZA/hqdefault.jpg"},
            {"videoId": "kUBs_JjIW8s", "title": "The White River (Northern Valley Instrumental)", "artist": "Jeremy Soule (Skyrim OST)", "duration": "3:30", "thumbnail": "https://i.ytimg.com/vi/kUBs_JjIW8s/hqdefault.jpg"},
            {"videoId": "mNwz8f3oYKU", "title": "Wind Guide You (Winter Instrumental)", "artist": "Jeremy Soule (Skyrim OST)", "duration": "9:06", "thumbnail": "https://i.ytimg.com/vi/mNwz8f3oYKU/hqdefault.jpg"},
        ],
    },
    {
        "env_id": "deserto",
        "name": "🏜️ Deserto & Dune",
        "color": "#f59e0b",
        "preferred_moods": ["esplorazione", "metropoli", "indagine"],
        "specificity": 1.6,
        "phrases": [
            "nel deserto", "in un deserto", "attraversate il deserto", "dune di sabbia",
            "distesa di sabbia", "sole cocente", "tempesta di sabbia", "vento caldo del deserto",
            "oasi nel deserto", "carovana nel deserto", "antica piramide", "deserto sconfinato",
            "deserto infinito",
        ],
        "keywords": [
            "deserto", "duna", "dune", "sabbia", "oasi", "miraggio", "cammello", "cammelli",
            "piramide", "piramidi", "faraone", "sfinge", "siccita", "beduini",
        ],
        "stems": ("desert", "sabbios", "piramid"),
        "query": "Arabian desert dunes oasis RPG soundtrack oud duduk instrumental",
        "seed_tracks": [
            {"videoId": "BzLt1KhbCIM", "title": "Desert Sky Melodies (Desert Instrumental)", "artist": "Etrusco Music", "duration": "6:04", "thumbnail": "https://i.ytimg.com/vi/BzLt1KhbCIM/hqdefault.jpg"},
            {"videoId": "xNA31r-3jqw", "title": "Whispers of the Dunes (Desert Soundscape Instrumental)", "artist": "Etrusco Music", "duration": "5:48", "thumbnail": "https://i.ytimg.com/vi/xNA31r-3jqw/hqdefault.jpg"},
            {"videoId": "3y5FxGGJh4w", "title": "Sacred Sands of Persia (Ney & Santur Instrumental)", "artist": "Darvish Music", "duration": "2:27", "thumbnail": "https://i.ytimg.com/vi/3y5FxGGJh4w/hqdefault.jpg"},
            {"videoId": "eOypXs-m24U", "title": "Sacred Desert Flames (Instrumental)", "artist": "Darvish Music", "duration": "2:38", "thumbnail": "https://i.ytimg.com/vi/eOypXs-m24U/hqdefault.jpg"},
        ],
    },
    {
        "env_id": "mare_oceano",
        "name": "🌊 Alto Mare & Navigazione",
        "color": "#0284c7",
        "preferred_moods": ["esplorazione", "citta", "spazio"],
        "specificity": 1.5,
        # NOTA: Rimosse "costa" e "faro" come parole singole (che causavano falsi positivi con "costa 10 monete" e "lo farò").
        # Sono ora riconosciute solo in frasi chiare ("lungo la costa", "torre del faro", "faro sul mare", "alto mare", ecc.).
        "phrases": [
            "alto mare", "in mezzo al mare", "in mezzo all oceano", "a bordo della nave",
            "salpate in alto mare", "salpate l ancora", "issate le vele", "ponte della nave",
            "nave pirata", "isola deserta", "sulla spiaggia", "lungo la costa",
            "costa frastagliata", "scogliera a picco", "torre del faro", "faro sul mare",
            "navigate verso", "in mare aperto", "solcate le onde",
        ],
        "keywords": [
            "mare", "oceano", "veliero", "galeone", "scialuppa", "arcipelago",
            "spiaggia", "scogliera", "baia", "laguna", "navigare", "navigazione",
            "ciurma", "pirata", "pirati", "timone", "vele", "salpate", "salpare",
        ],
        "stems": ("ocean", "navig", "marittim"),
        "query": "Divinity Original Sin 2 The Queen High Seas ocean ship voyage rpg instrumental",
        "seed_tracks": [
            {"videoId": "MF3xdAPqQtU", "title": "The Queen's High Seas (Ocean Voyage Instrumental)", "artist": "Borislav Slavov (Divinity: Original Sin 2 OST)", "duration": "2:34", "thumbnail": "https://i.ytimg.com/vi/MF3xdAPqQtU/hqdefault.jpg"},
            {"videoId": "Ij4MpaR4dq0", "title": "The Queen's High Seas (Instrumental)", "artist": "Dryante", "duration": "2:34", "thumbnail": "https://i.ytimg.com/vi/Ij4MpaR4dq0/hqdefault.jpg"},
            {"videoId": "pfvjHzOE2S0", "title": "The Queen's High Seas (Guitar Instrumental)", "artist": "John Oeth", "duration": "1:44", "thumbnail": "https://i.ytimg.com/vi/pfvjHzOE2S0/hqdefault.jpg"},
            {"videoId": "LWENbt8T0dc", "title": "The Queen's High Seas (Harp & Piano Instrumental)", "artist": "Kara Comparetto", "duration": "2:41", "thumbnail": "https://i.ytimg.com/vi/LWENbt8T0dc/hqdefault.jpg"},
        ],
    },
    {
        "env_id": "palude",
        "name": "🌿 Palude & Acquitrino",
        "color": "#4d7c0f",
        "preferred_moods": ["esplorazione", "dungeon", "tensione"],
        "specificity": 1.6,
        "phrases": [
            "in una palude", "nella palude", "palude nebbiosa", "acquitrino putrido",
            "nebbia fitta nella palude", "acqua stagnante", "fango fino alle ginocchia",
            "alberi marci", "vi addentrate nella palude",
        ],
        "keywords": [
            "palude", "paludi", "acquitrino", "pantano", "stagno", "mangrovie",
            "fangoso", "stagnante", "torbiera", "brughiera",
        ],
        "stems": ("palud", "acquitrin", "pantan", "fangos"),
        "query": "dark swamp marshland bog ambient rpg soundtrack instrumental",
        "seed_tracks": [
            {"videoId": "M1emYoQvIMI", "title": "Mire of Lost Lanterns (Swamp RPG Instrumental)", "artist": "Medieval Bard", "duration": "4:10", "thumbnail": "https://i.ytimg.com/vi/M1emYoQvIMI/hqdefault.jpg"},
            {"videoId": "JDmVqrLqf_Q", "title": "Dead Marshes (Swamp Instrumental)", "artist": "Brand X Music", "duration": "1:40", "thumbnail": "https://i.ytimg.com/vi/JDmVqrLqf_Q/hqdefault.jpg"},
            {"videoId": "Mtc7Osnlnhs", "title": "Despair Ambient (Dark Marsh Instrumental)", "artist": "Gabriel Brosteanu", "duration": "1:51", "thumbnail": "https://i.ytimg.com/vi/Mtc7Osnlnhs/hqdefault.jpg"},
        ],
    },
    {
        "env_id": "giungla",
        "name": "🌴 Giungla & Foresta Tropicale",
        "color": "#15803d",
        "preferred_moods": ["esplorazione", "tensione"],
        "specificity": 1.6,
        "phrases": [
            "in una giungla", "nella giungla", "foresta pluviale", "foresta tropicale",
            "vegetazione fitta", "tra le liane", "rovine nella giungla",
        ],
        "keywords": [
            "giungla", "liane", "tropicale", "pluviale", "amazzonia", "bambu", "machete",
        ],
        "stems": ("giungl", "tropical", "pluvial"),
        "query": "jungle tribal drums flute exploration rpg soundtrack instrumental",
        "seed_tracks": [
            {"videoId": "H4pa0mA8DYU", "title": "Tribal Jungle Exploration (RPG Instrumental)", "artist": "RM Production Music", "duration": "60:00", "thumbnail": "https://i.ytimg.com/vi/H4pa0mA8DYU/hqdefault.jpg"},
            {"videoId": "hfU2FPkPYlE", "title": "Jungle Drums & Vibes (Instrumental)", "artist": "Cosmic Soundscapes", "duration": "60:00", "thumbnail": "https://i.ytimg.com/vi/hfU2FPkPYlE/hqdefault.jpg"},
        ],
    },
    {
        "env_id": "vulcano_cenere",
        "name": "🌋 Vulcano & Terre Desolate",
        "color": "#ea580c",
        "preferred_moods": ["esplorazione", "dungeon", "tensione"],
        "specificity": 1.6,
        "phrases": [
            "terre desolate", "terra bruciata", "cratere del vulcano", "pendici del vulcano",
            "pioggia di cenere", "fiumi di lava", "odore di zolfo", "terra vulcanica",
        ],
        "keywords": [
            "vulcano", "cratere", "cenere", "zolfo", "geyser",
            "ossidiana", "caldera", "lapilli", "magma", "lava",
        ],
        "stems": ("vulcan",),
        "query": "volcanic ashlands Mordor dark orchestral ambient rpg instrumental",
        "seed_tracks": [
            {"videoId": "5hgebnIc_3Q", "title": "The Black Land (Volcanic Wasteland Instrumental)", "artist": "Dreyma", "duration": "3:27", "thumbnail": "https://i.ytimg.com/vi/5hgebnIc_3Q/hqdefault.jpg"},
            {"videoId": "g_6jujXtZ_M", "title": "The Fires of Orodruin (Volcano Instrumental)", "artist": "Dreyma", "duration": "5:10", "thumbnail": "https://i.ytimg.com/vi/g_6jujXtZ_M/hqdefault.jpg"},
            {"videoId": "qHNzdTMiriA", "title": "Deep Volcanic Chamber (Instrumental)", "artist": "Ambient Realms", "duration": "2:58", "thumbnail": "https://i.ytimg.com/vi/qHNzdTMiriA/hqdefault.jpg"},
        ],
    },
    {
        "env_id": "tempesta",
        "name": "⛈️ Tempesta & Temporale",
        "color": "#475569",
        "preferred_moods": ["esplorazione", "tensione", "indagine"],
        "specificity": 1.5,
        "phrases": [
            "scoppia una tempesta", "scoppia un temporale", "piove a dirotto",
            "sotto la pioggia battente", "vento impetuoso", "cielo in tempesta",
            "sotto il diluvio",
        ],
        "keywords": [
            "tempesta", "temporale", "diluvio", "nubifragio", "uragano", "tifone",
            "acquazzone", "grandine",
        ],
        "stems": ("tempest", "temporal", "diluvi", "nubifrag"),
        "query": "Stormy Night Brandon Fiechter dark rain RPG soundtrack instrumental",
        "seed_tracks": [
            {"videoId": "CL86A34hzfU", "title": "Stormy Night (Rain & Storm Instrumental)", "artist": "Brandon Fiechter", "duration": "3:46", "thumbnail": "https://i.ytimg.com/vi/CL86A34hzfU/hqdefault.jpg"},
            {"videoId": "ECYLHiXvrBQ", "title": "Blade Runner Blues (Rainy Atmosphere Instrumental)", "artist": "Vangelis", "duration": "8:55", "thumbnail": "https://i.ytimg.com/vi/ECYLHiXvrBQ/hqdefault.jpg"},
        ],
    },
    {
        "env_id": "castello_corte",
        "name": "👑 Castello & Corte Reale",
        "color": "#eab308",
        "preferred_moods": ["citta", "esplorazione"],
        "specificity": 1.5,
        # NOTA: Rimosso "reale" isolato (che faceva scattare il castello con "è reale" / "in tempo reale").
        "phrases": [
            "sala del trono", "corte del re", "corte reale", "palazzo reale", "castello reale",
            "al cospetto del re", "al cospetto della regina", "banchetto reale", "salone delle feste",
            "entrate nel castello", "dentro la reggia",
        ],
        "keywords": [
            "reggia", "trono", "monarca", "imperatore",
            "regina", "principe", "principessa", "aristocrazia", "feudo",
        ],
        "stems": ("reggi", "aristocr"),
        "query": "medieval royal court castle throne room harpsichord lute instrumental",
        "seed_tracks": [
            {"videoId": "btaUZ25yNU8", "title": "In the Palace of Fair King (Royal Court Instrumental)", "artist": "Andrei Krylov", "duration": "1:39", "thumbnail": "https://i.ytimg.com/vi/btaUZ25yNU8/hqdefault.jpg"},
            {"videoId": "qa-05_BLb6M", "title": "The Royal Palace Theme (Orchestral Instrumental)", "artist": "BBC Philharmonic Orchestra", "duration": "3:46", "thumbnail": "https://i.ytimg.com/vi/qa-05_BLb6M/hqdefault.jpg"},
            {"videoId": "O3QJbxZZl3c", "title": "Music from the Royal Court (Instrumental)", "artist": "Nordic Brass Ensemble", "duration": "3:04", "thumbnail": "https://i.ytimg.com/vi/O3QJbxZZl3c/hqdefault.jpg"},
        ],
    },
    {
        "env_id": "tempio_sacro",
        "name": "⛪ Tempio & Santuario Sacro",
        "color": "#a855f7",
        "preferred_moods": ["mistero", "esplorazione", "citta"],
        "specificity": 1.5,
        "phrases": [
            "tempio sacro", "antico tempio", "entrate nel tempio", "dentro la cattedrale",
            "dentro la chiesa", "santuario divino", "altare sacro", "monastero antico",
        ],
        "keywords": [
            "tempio", "santuario", "cattedrale", "chiesa", "monastero", "abbazia", "convento",
            "cappella", "sacerdote", "preghiera", "reliquia",
        ],
        "stems": ("cattedral", "santuari", "monaster"),
        "query": "Holy Temple Michael Ghelfi sacred cathedral ambient rpg instrumental",
        "seed_tracks": [
            {"videoId": "UkYyGgXAuAY", "title": "Holy Temple (Sacred Sanctuary Instrumental)", "artist": "Michael Ghelfi", "duration": "7:28", "thumbnail": "https://i.ytimg.com/vi/UkYyGgXAuAY/hqdefault.jpg"},
            {"videoId": "eESwtNbtgAY", "title": "Gothic Lute Mystery in Salisbury Cathedral (Instrumental)", "artist": "Andrei Krylov", "duration": "1:39", "thumbnail": "https://i.ytimg.com/vi/eESwtNbtgAY/hqdefault.jpg"},
            {"videoId": "9yaLNg4-IMc", "title": "Forgotten Vale (Sacred Instrumental)", "artist": "Dreyma", "duration": "3:55", "thumbnail": "https://i.ytimg.com/vi/9yaLNg4-IMc/hqdefault.jpg"},
        ],
    },
    {
        "env_id": "cimitero_rovine",
        "name": "🪦 Cimitero & Rovine Maledette",
        "color": "#64748b",
        "preferred_moods": ["dungeon", "tensione", "occulto"],
        "specificity": 1.6,
        "phrases": [
            "in un cimitero", "nel cimitero", "vecchio cimitero", "tra le lapidi",
            "villaggio abbandonato", "citta fantasma", "rovine maledette",
            "terra maledetta", "processione funebre",
        ],
        "keywords": [
            "cimitero", "lapide", "lapidi", "necropoli", "mausoleo", "camposanto",
            "spettrale", "fantasma", "fantasmi",
        ],
        "stems": ("cimiter", "necrop", "camposant"),
        "query": "Dark Cemetery Derek Fiechter graveyard gothic strings rpg instrumental",
        "seed_tracks": [
            {"videoId": "n38lNt8fQyA", "title": "Dark Cemetery (Graveyard Instrumental)", "artist": "Derek Fiechter, Brandon Fiechter", "duration": "3:36", "thumbnail": "https://i.ytimg.com/vi/n38lNt8fQyA/hqdefault.jpg"},
            {"videoId": "vbzharKhJGg", "title": "Echoes of the Dead (Cursed Ruins Instrumental)", "artist": "dark grach", "duration": "2:07", "thumbnail": "https://i.ytimg.com/vi/vbzharKhJGg/hqdefault.jpg"},
            {"videoId": "IaBfH33sepA", "title": "Graveyard Symphony (Gothic Instrumental)", "artist": "Shinto Shadows", "duration": "1:46", "thumbnail": "https://i.ytimg.com/vi/IaBfH33sepA/hqdefault.jpg"},
        ],
    },
    {
        "env_id": "miniera_caverna",
        "name": "⛏️ Miniera & Caverna Nanica",
        "color": "#d97706",
        "preferred_moods": ["dungeon", "esplorazione"],
        "specificity": 1.5,
        "phrases": [
            "in una miniera", "nella miniera", "miniera abbandonata", "citta nanica",
            "forgia dei nani", "caverna sotterranea", "grotta profonda",
            "caverna di cristallo", "sotto la montagna",
        ],
        "keywords": [
            "miniera", "miniere", "nanico", "nanica", "forgia", "fucina", "incudine",
            "piccone", "mithril", "stalattiti", "stalagmiti",
        ],
        "stems": ("minier", "nanic", "stalattit", "stalagmit"),
        "query": "dwarven city forge underground cavern mine rpg soundtrack instrumental",
        "seed_tracks": [
            {"videoId": "s2k0HHYgNRQ", "title": "Dwarven Castles (Underground Mine Instrumental)", "artist": "MOAIGAMES", "duration": "2:06", "thumbnail": "https://i.ytimg.com/vi/s2k0HHYgNRQ/hqdefault.jpg"},
            {"videoId": "m9RlHnOmkPI", "title": "Underground Caverns (RPG Instrumental)", "artist": "Michael Ghelfi", "duration": "7:43", "thumbnail": "https://i.ytimg.com/vi/m9RlHnOmkPI/hqdefault.jpg"},
            {"videoId": "8deoTE4VMIs", "title": "Underdark (Deep Cavern Instrumental)", "artist": "Soundscapes & Ambience", "duration": "4:00", "thumbnail": "https://i.ytimg.com/vi/8deoTE4VMIs/hqdefault.jpg"},
        ],
    },
    {
        "env_id": "fiera_carnevale",
        "name": "🎪 Fiera, Circo & Festival",
        "color": "#ec4899",
        "preferred_moods": ["taverna", "citta"],
        "specificity": 1.5,
        "phrases": [
            "fiera del paese", "festa del villaggio", "tendone del circo",
            "ballo in maschera", "torneo cavalleresco", "nel mezzo del festival",
        ],
        "keywords": [
            "fiera", "carnevale", "circo", "festival", "giullare", "acrobati",
            "tendone", "giostra", "torneo",
        ],
        "stems": ("carneval", "giullar"),
        "query": "Medieval Festival Michael Ghelfi fair carnival lute fiddle instrumental",
        "seed_tracks": [
            {"videoId": "T9IfGvWC32E", "title": "Medieval Festival (Fair & Carnival Instrumental)", "artist": "Michael Ghelfi", "duration": "7:43", "thumbnail": "https://i.ytimg.com/vi/T9IfGvWC32E/hqdefault.jpg"},
            {"videoId": "TYn-UrP_fEQ", "title": "Swifthoof Tavern (Festival Instrumental)", "artist": "Derek Fiechter, Brandon Fiechter", "duration": "3:25", "thumbnail": "https://i.ytimg.com/vi/TYn-UrP_fEQ/hqdefault.jpg"},
            {"videoId": "sgvKM_wxkvY", "title": "Unseelie Court (Carnival Instrumental)", "artist": "Derek Fiechter, Brandon Fiechter", "duration": "3:53", "thumbnail": "https://i.ytimg.com/vi/sgvKM_wxkvY/hqdefault.jpg"},
        ],
    },
    {
        "env_id": "biblioteca_torre",
        "name": "📚 Biblioteca & Torre Arcana",
        "color": "#8b5cf6",
        "preferred_moods": ["mistero", "indagine", "deduzione"],
        "specificity": 1.5,
        "phrases": [
            "antica biblioteca", "torre del mago", "torre arcana", "accademia di magia",
            "laboratorio alchemico", "scaffali pieni di libri", "osservatorio astronomico",
            "entrate nella biblioteca",
        ],
        "keywords": [
            "biblioteca", "accademia", "osservatorio",
            "alchimia", "alchemico", "manoscritti", "grimorio",
        ],
        "stems": ("bibliotec", "alchem", "accademi"),
        "query": "Skyrim Secunda Masser arcane library wizard tower mystery rpg instrumental",
        "seed_tracks": [
            {"videoId": "VPgZFgOvJDE", "title": "Secunda (Arcane Library Instrumental)", "artist": "Jeremy Soule (Skyrim OST)", "duration": "2:04", "thumbnail": "https://i.ytimg.com/vi/VPgZFgOvJDE/hqdefault.jpg"},
            {"videoId": "KGsjpcUT9ho", "title": "Masser (Wizard Tower Instrumental)", "artist": "Jeremy Soule (Skyrim OST)", "duration": "6:05", "thumbnail": "https://i.ytimg.com/vi/KGsjpcUT9ho/hqdefault.jpg"},
            {"videoId": "liWYQGjB6TM", "title": "Celestial Nexus (Arcane Instrumental)", "artist": "Everrune", "duration": "1:25", "thumbnail": "https://i.ytimg.com/vi/liWYQGjB6TM/hqdefault.jpg"},
        ],
    },
    {
        "env_id": "montagna",
        "name": "⛰️ Montagne & Vette Rocciose",
        "color": "#64748b",
        "preferred_moods": ["esplorazione"],
        "specificity": 1.2,
        "phrases": [
            "passo di montagna", "sentiero di montagna", "vette rocciose", "scalate la montagna",
            "in cima alla montagna", "canyon roccioso", "tra le montagne", "sulle montagne",
        ],
        "keywords": [
            "montagna", "montagne", "vetta", "vette", "dirupo", "precipizio",
            "burrone", "altipiano", "altopiano", "valico",
        ],
        "stems": ("montagn",),
        "query": "Skyrim The Jerall Mountains Jeremy Soule highland mountain rpg instrumental",
        "seed_tracks": [
            {"videoId": "2lBU5bi-u-I", "title": "The Jerall Mountains (Highland Instrumental)", "artist": "Jeremy Soule (Skyrim OST)", "duration": "3:20", "thumbnail": "https://i.ytimg.com/vi/2lBU5bi-u-I/hqdefault.jpg"},
            {"videoId": "ZarbRbkV4ak", "title": "Far Horizons (Mountain Pass Instrumental)", "artist": "Jeremy Soule (Skyrim OST)", "duration": "5:32", "thumbnail": "https://i.ytimg.com/vi/ZarbRbkV4ak/hqdefault.jpg"},
            {"videoId": "PdAp2wrBr_I", "title": "Snowy Mountains (Instrumental)", "artist": "Jesper Kyd", "duration": "1:18", "thumbnail": "https://i.ytimg.com/vi/PdAp2wrBr_I/hqdefault.jpg"},
        ],
    },
    {
        "env_id": "foresta_valle",
        "name": "🌲 Foresta & Vallata Verde",
        "color": "#10b981",
        "preferred_moods": ["esplorazione"],
        "specificity": 1.1,
        "phrases": [
            "in una valle", "nella valle", "in una foresta", "nella foresta", "nel bosco",
            "bosco elfico", "foresta incantata", "foresta antica", "verde vallata",
            "radura nel bosco", "lungo il fiume", "attraversate il bosco", "attraversate la foresta",
        ],
        "keywords": [
            "vallata", "foresta", "boscaglia", "radura",
            "prateria", "ruscello", "cascata", "elfico",
        ],
        "stems": ("forest", "vallat", "prateri"),
        "query": "Elder Scrolls Through Sunflower Fields Far Horizons forest valley rpg instrumental",
        "seed_tracks": [
            {"videoId": "wZ5B82Zvgqg", "title": "Through Sunflower Fields (Valley Instrumental)", "artist": "Brad Derrick (Elder Scrolls OST)", "duration": "9:00", "thumbnail": "https://i.ytimg.com/vi/wZ5B82Zvgqg/hqdefault.jpg"},
            {"videoId": "ZarbRbkV4ak", "title": "Far Horizons (Forest & Valley Instrumental)", "artist": "Jeremy Soule (Skyrim OST)", "duration": "5:32", "thumbnail": "https://i.ytimg.com/vi/ZarbRbkV4ak/hqdefault.jpg"},
            {"videoId": "05q762SYKEA", "title": "Halfling Hills (Green Valley Instrumental)", "artist": "Derek Fiechter", "duration": "4:36", "thumbnail": "https://i.ytimg.com/vi/05q762SYKEA/hqdefault.jpg"},
            {"videoId": "R6R5AJtjOeU", "title": "The Road to Baldur's Gate (Instrumental)", "artist": "Borislav Slavov", "duration": "2:08", "thumbnail": "https://i.ytimg.com/vi/R6R5AJtjOeU/hqdefault.jpg"},
        ],
    },
]

LOCATIVE_PATTERNS = (
    "siete in ", "siete nel ", "siete nella ", "siete nello ", "siete nei ", "siete nelle ", "siete sul ", "siete sulla ",
    "siamo in ", "siamo nel ", "siamo nella ", "vi trovate ", "entrate ", "entrano ", "arrivate ", "arriviamo ",
    "attraversate ", "camminate ", "viaggiate ", "davanti a voi ", "intorno a voi ", "vi addentrate ", "scendete ", "salite ",
    "navigate ", "salpate ", "sbarcate ", "giungete ",
)


class HybridAnalyzer:
    def __init__(self) -> None:
        self.context_window: Deque[str] = deque(maxlen=4)

    def clear_context(self) -> None:
        self.context_window.clear()

    def _detect_environment_biome(
        self,
        norm_text: str,
        words: Set[str],
        moods: Dict[str, Any],
        is_direct_command: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        Rileva se la frase descrive uno specifico bioma o ambiente.
        Per evitare falsi positivi da singole parole fuori contesto:
        - Richiede una frase multi-parola del bioma, OPPURE un indicatore locativo + keyword,
          OPPURE almeno 2 keyword distinte del bioma (a meno che non sia un comando vocale esplicito "bardo metti ...").
        """
        has_locative = any(lp in norm_text for lp in LOCATIVE_PATTERNS)
        best_biome: Optional[Dict[str, Any]] = None
        best_score = 0.0
        best_hits: List[str] = []

        for biome in ENVIRONMENT_BIOMES:
            raw_score = 0.0
            hits: List[str] = []
            phrase_matched = False

            for phrase in biome.get("phrases", []):
                if phrase in norm_text:
                    raw_score += 6.5
                    hits.append(phrase)
                    phrase_matched = True

            kw_count = 0
            for kw in biome.get("keywords", []):
                if kw in words:
                    raw_score += 3.8
                    hits.append(kw)
                    kw_count += 1

            for stem in biome.get("stems", ()):
                for w in words:
                    if len(w) >= 5 and w.startswith(stem) and w not in hits:
                        raw_score += 3.8
                        hits.append(w)
                        kw_count += 1
                        break

            if raw_score > 0:
                if has_locative:
                    raw_score += 2.8

                # Regola anti-falso-positivo: una singola parola chiave isolata senza frase né locativo
                # non basta per forzare un bioma (a meno di un comando diretto "bardo metti neve")!
                if not is_direct_command and not phrase_matched and not has_locative and kw_count < 2:
                    continue

                weighted_score = round(raw_score * float(biome.get("specificity", 1.0)), 2)
                if weighted_score > best_score:
                    best_score = weighted_score
                    best_biome = biome
                    best_hits = list(dict.fromkeys(hits))

        min_required = 3.0 if is_direct_command else 5.2
        if not best_biome or best_score < min_required:
            return None

        target_mood_id = None
        for pm in best_biome.get("preferred_moods", []):
            if pm in moods:
                target_mood_id = pm
                break
        if not target_mood_id:
            target_mood_id = "esplorazione" if "esplorazione" in moods else next(iter(moods.keys()), None)
        if not target_mood_id:
            return None

        return {
            "mood_id": target_mood_id,
            "env_id": best_biome["env_id"],
            "env_name": best_biome["name"],
            "env_color": best_biome.get("color", "#10b981"),
            "env_seed_tracks": list(best_biome.get("seed_tracks", [])),
            "custom_search_query": best_biome["query"],
            "confidence": best_score,
            "matched_by": "environment",
            "matched_terms": best_hits,
            "force_change": True,
        }

    def detect_voice_command(
        self, norm_text: str, moods: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Rileva comandi vocali espliciti rivolti all'app (es. "bardo metti taverna", "bardo metti deserto").
        """
        if re.search(r"\b(bardo|musica)\b.*\b(pausa|ferma|stop|silenzio|zitto)\b", norm_text) or norm_text in (
            "stop musica", "ferma la musica", "pausa musica", "silenzio bardo"
        ):
            return {"voice_action": "pause", "reason": "Comando vocale: Pausa"}

        if re.search(r"\b(bardo|musica)\b.*\b(riprendi|continua|play|riproduci)\b", norm_text):
            return {"voice_action": "resume", "reason": "Comando vocale: Riprendi"}

        if re.search(r"\b(bardo|musica|cambia|prossima)\b.*\b(traccia|canzone|brano)\b", norm_text) or "prossima traccia" in norm_text:
            return {"voice_action": "next", "reason": "Comando vocale: Prossima traccia"}

        cmd_match = re.search(
            r"\b(?:bardo\s+metti|metti\s+musica|musica\s+da|atmosfera\s+da|cambio\s+scena)\s+(.+)$",
            norm_text,
        )
        if cmd_match:
            target = cmd_match.group(1).strip()
            env_res = self._detect_environment_biome(target, set(target.split()), moods, is_direct_command=True)
            if env_res:
                env_res["matched_by"] = "command"
                env_res["confidence"] = 10.0
                return env_res

            for mood_id, mood in moods.items():
                mood_name_norm = normalize_italian(mood.get("name", ""))
                if (
                    mood_id in target
                    or target in mood_name_norm
                    or any(w in target for w in mood_name_norm.split() if len(w) > 3)
                ):
                    return {
                        "mood_id": mood_id,
                        "confidence": 10.0,
                        "matched_by": "command",
                        "matched_terms": [f"Comando: {mood.get('name')}"],
                        "force_change": True,
                    }
        return None

    def _detect_danger_and_urgency(self, affirmed_text: str, words: Set[str]) -> Tuple[str, List[str]]:
        """
        Analizza SOLO la porzione AFFERMATA (non negata) della frase per verificare se contiene
        indicatori di pericolo attivo, fuoco/fiamme ostili, agonia, danno o combattimento.
        Restituisce: ("none" | "combat_danger" | "catastrophic", lista_termini_rilevati)
        """
        if not affirmed_text:
            return "none", []

        # Se la frase parla di un fuoco da campo/camino ("intorno al fuoco", "fuoco del camino", ecc.)
        # rimuovi la sequenza innocua prima di cercare pericoli
        working_text = affirmed_text
        for cozy_pat in SAFE_COZY_FIRE_PATTERNS:
            if cozy_pat in working_text:
                working_text = working_text.replace(cozy_pat, "bivacco tranquillo")

        working_words = set(working_text.split())

        catastrophic_hits: List[str] = []
        for pat in CATASTROPHIC_PHRASES:
            if pat in working_text:
                catastrophic_hits.append(pat)

        danger_hits: List[str] = []
        for dmg_pat in COMBAT_DAMAGE_PHRASES:
            if dmg_pat in working_text:
                danger_hits.append(dmg_pat)

        for w in working_words:
            if w in DANGER_EXACT_WORDS:
                danger_hits.append(w)
            elif len(w) >= 5 and w.startswith(DANGER_WORD_STEMS):
                # Evita falsi positivi: "feritoia" non è "ferito", "armadio" non è "arma"
                if w in ("feritoia", "feritoie"):
                    continue
                danger_hits.append(w)

        if catastrophic_hits:
            return "catastrophic", list(dict.fromkeys(catastrophic_hits + danger_hits[:2]))
        if danger_hits:
            return "combat_danger", list(dict.fromkeys(danger_hits))
        return "none", []

    def analyze_keywords(
        self,
        raw_text: str,
        profile: Dict[str, Any],
        threshold: float = 2.0,
    ) -> Dict[str, Any]:
        """
        Analizza il testo parlato in italiano applicando:
        1. Comandi vocali diretti
        2. Separazione tra clausole affermate e clausole negate ("non ci sono nemici" non attiva combattimento!)
        3. Disambiguazione degli omografi ("vi danno il benvenuto", "intorno al fuoco", "costa 10 monete", "lo farò")
        4. Veto semantico rigido sui pericoli
        5. Matching preciso di frasi, parole chiave e morfologia sicura.
        """
        full_norm = normalize_italian(raw_text)
        if not full_norm:
            return {"mood_id": None, "confidence": 0.0, "matched_by": "none", "matched_terms": []}

        moods: Dict[str, Any] = profile.get("moods", {})

        # 1. Controlla prima se è un comando vocale diretto
        cmd = self.detect_voice_command(full_norm, moods)
        if cmd:
            return cmd

        # 2. Gestione esplicita di fine combattimento / ritorno alla calma
        combat_end_patterns = [
            "combattimento e finito",
            "fine del combattimento",
            "scontro e finito",
            "battaglia e finita",
            "nemici sono morti",
            "pericolo e passato",
            "siete fuori pericolo",
            "pericolo scampato",
            "uscite dal combattimento",
        ]
        for pat in combat_end_patterns:
            if pat in full_norm:
                if "vittoria" in moods:
                    return {
                        "mood_id": "vittoria",
                        "confidence": 5.5,
                        "matched_by": "keywords",
                        "matched_terms": [pat],
                        "force_change": True,
                    }
                default_mood = profile.get("default_mood")
                if default_mood and default_mood in moods:
                    return {
                        "mood_id": default_mood,
                        "confidence": 5.0,
                        "matched_by": "keywords",
                        "matched_terms": [pat],
                        "force_change": True,
                    }

        # 3. Separa le clausole affermate da quelle negate ("non ci sono nemici, ma entrate nella locanda")
        affirmed_raw, negated_raw = split_affirmed_and_negated_text(raw_text)
        affirmed_text = clean_false_positive_collocations(affirmed_raw)

        if not affirmed_text:
            return {
                "mood_id": None,
                "confidence": 0.0,
                "matched_by": "negated",
                "matched_terms": [],
                "negated_clause": negated_raw,
            }

        words = set(affirmed_text.split())
        danger_level, danger_terms = self._detect_danger_and_urgency(affirmed_text, words)

        # 4. Se non c'è pericolo attivo, verifica se il GM sta descrivendo un BIOMA/AMBIENTE specifico
        env_res: Optional[Dict[str, Any]] = None
        if danger_level == "none":
            env_res = self._detect_environment_biome(affirmed_text, words, moods, is_direct_command=False)

        scores: Dict[str, float] = {}
        matched_terms_map: Dict[str, List[str]] = {}

        for mood_id, mood in moods.items():
            tone = mood.get("tone_profile", "")
            is_calm_mood = (mood_id in CALM_MOOD_IDS) or (tone in CALM_TONE_PROFILES)

            # VETO SEMANTICO RIGIDO: se c'è pericolo attivo affermato, le atmosfere calme vengono bloccate
            if danger_level != "none" and is_calm_mood:
                continue

            score = 0.0
            hits: List[str] = []

            for phrase in mood.get("phrases", []):
                norm_phrase = normalize_italian(phrase)
                if norm_phrase and norm_phrase in affirmed_text:
                    score += 4.5
                    hits.append(phrase)

            for kw in mood.get("keywords", []):
                norm_kw = normalize_italian(kw)
                if not norm_kw:
                    continue
                if " " in norm_kw:
                    if norm_kw in affirmed_text:
                        score += 3.2
                        hits.append(kw)
                elif norm_kw in words:
                    score += 2.4
                    hits.append(kw)
                elif len(norm_kw) >= 6:
                    # Matching morfologico controllato (solo desinenza finale o/a/i/e su radici >= 5 char)
                    stem = norm_kw[:-1]
                    for w in words:
                        if (
                            len(w) >= 6
                            and abs(len(w) - len(norm_kw)) <= 2
                            and w.startswith(stem)
                            and w not in ("massimo", "massima", "massimi", "lampada", "lampade", "cardinale")
                        ):
                            score += 1.8
                            hits.append(kw)
                            break

            if danger_level != "none":
                has_boss_entity = any(
                    bw in words
                    for bw in ("drago", "demone", "diavolo", "lich", "colosso", "titano", "boss", "arcimago", "vampiro")
                )
                if mood_id == "boss" or tone == "epic_boss":
                    if has_boss_entity:
                        score += 8.0
                        hits.append("Scontro Boss")
                    elif danger_level == "catastrophic":
                        score += 4.5
                        for dt in danger_terms[:2]:
                            if dt not in hits:
                                hits.append(dt)
                elif mood_id in ("combattimento", "sparatoria", "fuga", "terrore", "inseguimento_poliziesco") or tone == "fast_combat":
                    score += 4.2
                    for dt in danger_terms[:2]:
                        if dt not in hits:
                            hits.append(dt)

            if score > 0:
                scores[mood_id] = round(score, 2)
                matched_terms_map[mood_id] = list(dict.fromkeys(hits))

        if env_res:
            if not scores:
                return env_res
            best_mood_id = max(scores, key=lambda k: scores[k])
            best_score = scores[best_mood_id]
            if best_mood_id in ("taverna", "accampamento", "vittoria", "club", "rivelazione") and best_score >= env_res["confidence"] * 0.75:
                pass
            else:
                env_res["all_scores"] = scores
                return env_res

        if not scores:
            return {
                "mood_id": None,
                "confidence": 0.0,
                "matched_by": "none",
                "matched_terms": [],
                "all_scores": {},
            }

        best_mood_id = max(scores, key=lambda k: scores[k])
        best_score = scores[best_mood_id]

        if best_score >= threshold:
            return {
                "mood_id": best_mood_id,
                "confidence": best_score,
                "matched_by": "keywords",
                "matched_terms": matched_terms_map.get(best_mood_id, []),
                "all_scores": scores,
                "danger_level": danger_level,
            }

        return {
            "mood_id": None,
            "best_candidate": best_mood_id,
            "confidence": best_score,
            "matched_by": "none",
            "matched_terms": matched_terms_map.get(best_mood_id, []),
            "all_scores": scores,
        }

    async def analyze_with_ai(
        self,
        raw_text: str,
        profile: Dict[str, Any],
        analyzer_cfg: Dict[str, Any],
        current_mood_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Usa un modello AI opzionale (Gemini, Ollama locale o OpenAI) per interpretare
        il contesto narrativo, passando la chiave Gemini tramite header `x-goog-api-key`
        (mai nell'URL!).
        """
        moods = profile.get("moods", {})
        if not moods:
            return {"mood_id": None, "confidence": 0.0, "matched_by": "none"}

        affirmed_raw, _ = split_affirmed_and_negated_text(raw_text)
        affirmed_clean = clean_false_positive_collocations(affirmed_raw)
        danger_level, _ = self._detect_danger_and_urgency(affirmed_clean, set(affirmed_clean.split()))

        moods_catalog = []
        for mid, m in moods.items():
            tone = m.get("tone_profile", "")
            if danger_level != "none" and (mid in CALM_MOOD_IDS or tone in CALM_TONE_PROFILES):
                continue
            moods_catalog.append(f'- "{mid}": {m.get("name")} ({m.get("description", "")})')
        moods_str = "\n".join(moods_catalog)

        recent_context = " | ".join(self.context_window) if self.context_window else raw_text

        prompt = f"""Sei il regista musicale di una sessione di gioco di ruolo in italiano ({profile.get('name')}).
Analizza le ultime frasi pronunciate al tavolo da gioco e scegli l'atmosfera musicale più adatta al RITMO e al TONO della scena.
REGOLE CRITICHE:
1. Rispetta le negazioni ("non ci sono nemici" = NON è combattimento).
2. Se i personaggi sono davvero in pericolo attivo, stanno bruciando, subiscono danni o combattono, scegli SEMPRE un'atmosfera ad alta intensità (combattimento/boss/terrore/fuga) e MAI riposo o taverna!
3. La musica deve essere ESCLUSIVAMENTE STRUMENTALE (100% instrumental, senza parole e senza cantato). Se compili custom_search_query, includi sempre "instrumental".

Atmosfere disponibili:
{moods_str}

Atmosfera attualmente attiva: "{current_mood_id or 'nessuna'}"
Contesto recente: "{recent_context}"
Ultima frase pronunciata: "{raw_text}"

Rispondi ESCLUSIVAMENTE con un oggetto JSON valido:
{{
  "mood_id": "id_dell_atmosfera_scelta_oppure_null_se_non_chiaro",
  "confidence": 0.0_a_10.0,
  "reason": "breve spiegazione in italiano (max 8 parole)",
  "custom_search_query": ""
}}"""

        provider = analyzer_cfg.get("ai_provider", "gemini")
        try:
            if provider == "gemini":
                api_key = (analyzer_cfg.get("gemini_api_key") or "").strip()
                if not api_key:
                    return {"mood_id": None, "confidence": 0.0, "matched_by": "none", "ai_error": "API Key Gemini non configurata"}
                model = analyzer_cfg.get("gemini_model") or "gemini-2.5-flash"
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
                headers = {
                    "x-goog-api-key": api_key,
                    "Content-Type": "application/json",
                }
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.1,
                        "responseMimeType": "application/json",
                    },
                }
                async with httpx.AsyncClient(timeout=6.0) as client:
                    resp = await client.post(url, json=payload, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                    text_out = data["candidates"][0]["content"]["parts"][0]["text"]
                    parsed = json.loads(text_out)

            elif provider == "ollama":
                base_url = (analyzer_cfg.get("ollama_url") or "http://localhost:11434").rstrip("/")
                model = analyzer_cfg.get("ollama_model") or "llama3.2"
                payload = {
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                }
                async with httpx.AsyncClient(timeout=8.0) as client:
                    resp = await client.post(f"{base_url}/api/generate", json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    parsed = json.loads(data.get("response", "{}"))

            elif provider == "openai":
                api_key = (analyzer_cfg.get("openai_api_key") or "").strip()
                if not api_key:
                    return {"mood_id": None, "confidence": 0.0, "matched_by": "none", "ai_error": "API Key OpenAI non configurata"}
                base_url = (analyzer_cfg.get("openai_base_url") or "https://api.openai.com/v1").rstrip("/")
                model = analyzer_cfg.get("openai_model") or "gpt-4o-mini"
                headers = {"Authorization": f"Bearer {api_key}"}
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                }
                async with httpx.AsyncClient(timeout=6.0) as client:
                    resp = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                    text_out = data["choices"][0]["message"]["content"]
                    parsed = json.loads(text_out)
            else:
                return {"mood_id": None, "confidence": 0.0, "matched_by": "none"}

            mood_id = parsed.get("mood_id")
            conf = float(parsed.get("confidence") or 0.0)
            reason = parsed.get("reason") or "Contesto narrativo AI"
            custom_query = parsed.get("custom_search_query") or ""

            if danger_level != "none" and mood_id in CALM_MOOD_IDS:
                return {"mood_id": None, "confidence": 0.0, "matched_by": "none"}

            if mood_id in moods and conf >= 5.5:
                return {
                    "mood_id": mood_id,
                    "confidence": conf,
                    "matched_by": f"ai ({provider})",
                    "matched_terms": [reason],
                    "custom_search_query": custom_query,
                }
            return {
                "mood_id": None,
                "confidence": conf,
                "matched_by": "none",
                "matched_terms": [reason] if reason else [],
            }
        except Exception as e:
            # Oscura eventuali chiavi nel caso remoto compaiano in messaggi di eccezione
            safe_err = re.sub(r"AIza[0-9A-Za-z_-]{20,}", "[REDACTED_KEY]", str(e))
            return {
                "mood_id": None,
                "confidence": 0.0,
                "matched_by": "none",
                "ai_error": safe_err,
            }

    async def analyze(
        self,
        raw_text: str,
        profile: Dict[str, Any],
        analyzer_cfg: Dict[str, Any],
        current_mood_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        cleaned = raw_text.strip()
        if not cleaned:
            return {"mood_id": None, "confidence": 0.0, "matched_by": "none", "matched_terms": []}

        self.context_window.append(cleaned)
        mode = analyzer_cfg.get("mode", "hybrid")
        threshold = float(analyzer_cfg.get("confidence_threshold", 2.2))

        kw_result = self.analyze_keywords(cleaned, profile, threshold=threshold)

        if kw_result.get("voice_action") or kw_result.get("matched_by") == "command":
            return kw_result

        if mode == "keywords":
            return kw_result

        if mode == "hybrid":
            if kw_result.get("mood_id") and kw_result.get("confidence", 0) >= threshold:
                return kw_result
            if kw_result.get("matched_by") == "negated":
                return kw_result
            ai_res = await self.analyze_with_ai(cleaned, profile, analyzer_cfg, current_mood_id)
            if ai_res.get("mood_id"):
                return ai_res
            return kw_result

        if mode == "ai_always":
            ai_res = await self.analyze_with_ai(cleaned, profile, analyzer_cfg, current_mood_id)
            if ai_res.get("mood_id"):
                return ai_res
            return kw_result

        return kw_result

    def analyze_quick(self, raw_text: str, profile_id: Any = "fantasy_dnd") -> "AnalysisResult":
        """Analisi sincrona ad alta velocità basata su regole/keyword, ideale per unit test e verifiche rapide."""
        if isinstance(profile_id, dict):
            profile = profile_id
        else:
            from config_defaults import DEFAULT_CONFIG
            profiles = DEFAULT_CONFIG["profiles"]
            profile = profiles.get(profile_id) or profiles.get("fantasy_dnd") or next(iter(profiles.values()))
        res = self.analyze_keywords(raw_text, profile)
        return AnalysisResult(res)


class AnalysisResult:
    """Wrapper ergonomico per accedere ai risultati di analisi sia come attributi che come dict."""

    def __init__(self, data: Dict[str, Any]) -> None:
        self.data = data
        self.mood = data.get("mood_id")
        self.biome = data.get("env_id")
        self.confidence = float(data.get("confidence", 0.0) or 0.0)
        self.matched_by = str(data.get("matched_by") or "")
        self.matched_terms = list(data.get("matched_terms") or [])
        self.danger_level = str(data.get("danger_level") or "none")

    def __getitem__(self, item: str) -> Any:
        return self.data.get(item)

    def get(self, item: str, default: Any = None) -> Any:
        return self.data.get(item, default)


SceneAnalyzer = HybridAnalyzer

