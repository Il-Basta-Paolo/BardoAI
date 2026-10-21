"""
Motore di analisi vocale e semantica contestuale in Italiano per Bardo AI:
1. Comandi vocali diretti ("Bardo metti combattimento", "Bardo pausa", "Prossima traccia")
2. Classificatore Semantico di Pericolo, Tono e Ritmo con VETO RIGIDO anti-errore:
   - Impedisce matematicamente che frasi di pericolo, fuoco, ferite, morte, agonia o attacco possano MAI
     attivare musiche rilassanti/riposo/taverna/esplorazione (es. "state bruciando vivi" -> Combattimento/Boss!).
3. Analisi morfologica italiana (frasi, parole chiave e radici verbali sicure).
4. Analisi narrativa tramite AI opzionale (Google Gemini, Ollama locale o OpenAI).
"""

import json
import re
import unicodedata
from collections import deque
from typing import Dict, Any, List, Optional, Deque, Tuple

import httpx


def normalize_italian(text: str) -> str:
    """
    Normalizza il testo italiano rimuovendo accenti, punteggiatura superflua e convertendo in minuscolo.
    """
    text = text.lower().strip()
    text = re.sub(r"['’`]", " ", text)
    nfkd = unicodedata.normalize("NFKD", text)
    no_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    cleaned = re.sub(r"[^a-z0-9\s-]", " ", no_accents)
    return re.sub(r"\s+", " ", cleaned).strip()


# Frasi e radici di PERICOLO ESTREMO / AGONIA / BOSS / CATASTROFE
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

# Radici morfologiche italiane di PERICOLO / VIOLENZA / DANNO / COMBATTIMENTO
# Se una qualsiasi di queste radici è presente nella frase, TUTTE le atmosfere calme/riposo/taverna
# ricevono un VETO ASSOLUTO (-999 punti) e il motore indirizza verso Combattimento / Boss / Azione!
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
    "massacr",    # massacro, massacrati
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

DANGER_EXACT_WORDS = {
    "rogo", "acido", "veleno", "sangue", "danni", "danno",
    "spada", "spadata", "spade", "ascia", "scudo", "freccia", "frecce",
    "balestra", "iniziativa", "nemico", "nemici", "mostro", "mostri",
    "orco", "orchi", "goblin", "troll", "drago", "demone", "lich",
    "morte", "morto", "morti", "pericolo", "trappola", "imboscata",
    "carica", "caricano", "morde", "zanne", "urlo", "urla", "panico", "terrore",
    "fuoco", "bomba", "granata", "sparo", "spara",
}

CALM_MOOD_IDS = {
    "accampamento", "taverna", "citta", "esplorazione", "vittoria",
    "indagine", "metropoli", "club", "spazio",
}

CALM_TONE_PROFILES = {
    "calm_rest", "upbeat_tavern", "city", "exploration", "victory",
}

# =============================================================================
# SISTEMA DINAMICO DI RICONOSCIMENTO AMBIENTI E BIOMI (100% STRUMENTALE)
# Permette a Bardo AI di reagire istantaneamente a descrizioni ambientali come:
# "siete in una valle innevata", "siete in un deserto", "siete in una palude",
# "siete in alto mare", "entrate in un tempio", "siete in un cimitero", ecc.
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
            "nel deserto", "in un deserto", "dune di sabbia", "distesa di sabbia",
            "sole cocente", "tempesta di sabbia", "vento caldo del deserto",
            "oasi nel deserto", "carovana nel deserto", "antica piramide", "deserto sconfinato",
        ],
        "keywords": [
            "deserto", "duna", "dune", "sabbia", "oasi", "miraggio", "cammello", "cammelli",
            "piramide", "piramidi", "faraone", "sfinge", "arido", "arida", "siccita", "beduini", "canyon",
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
        "phrases": [
            "alto mare", "in mezzo al mare", "in mezzo all oceano", "a bordo della nave",
            "salpate l ancora", "issate le vele", "ponte della nave", "nave pirata",
            "isola deserta", "sulla spiaggia", "lungo la costa", "scogliera a picco",
        ],
        "keywords": [
            "mare", "oceano", "nave", "veliero", "galeone", "barca", "scialuppa", "isola",
            "arcipelago", "spiaggia", "costa", "scogliera", "baia", "laguna", "onde",
            "navigare", "navigazione", "ciurma", "pirata", "pirati", "capitano", "timone", "vele", "faro",
        ],
        "stems": ("ocean", "navig", "marittim", "costier"),
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
            "in una palude", "nella palude", "acquitrino putrido", "nebbia fitta nella palude",
            "acqua stagnante", "fango fino alle ginocchia", "alberi marci",
        ],
        "keywords": [
            "palude", "paludi", "acquitrino", "pantano", "stagno", "mangrovie",
            "fango", "fangoso", "stagnante", "putrido", "torbiera", "brughiera",
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
            "giungla", "liane", "tropicale", "pluviale", "amazzonia", "bambu", "tribale", "scimmie", "machete",
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
            "vulcano", "cratere", "cenere", "zolfo", "geyser", "desolazione", "desolata", "desolato",
            "ossidiana", "caldera", "lapilli", "magma", "lava",
        ],
        "stems": ("vulcan", "desolat"),
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
            "sotto la pioggia", "vento impetuoso", "cielo in tempesta",
        ],
        "keywords": [
            "tempesta", "temporale", "diluvio", "nubifragio", "uragano", "tifone",
            "pioggia", "acquazzone", "grandine",
        ],
        "stems": ("tempest", "temporal", "diluvi", "piov"),
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
        "phrases": [
            "sala del trono", "corte del re", "palazzo reale", "castello reale",
            "al cospetto del re", "al cospetto della regina", "banchetto reale", "salone delle feste",
        ],
        "keywords": [
            "castello", "reggia", "trono", "corte", "reale", "monarca", "imperatore",
            "regina", "principe", "principessa", "nobile", "nobili", "aristocrazia", "duca", "barone", "feudo",
        ],
        "stems": ("castell", "reggi", "aristocr"),
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
            "tempio sacro", "antico tempio", "dentro la cattedrale", "dentro la chiesa",
            "santuario divino", "altare sacro", "monastero antico",
        ],
        "keywords": [
            "tempio", "santuario", "cattedrale", "chiesa", "monastero", "abbazia", "convento",
            "capella", "sacro", "sacra", "divino", "divina", "celestiale", "sacerdote", "preghiera", "reliquia",
        ],
        "stems": ("tempi", "cattedral", "santuari", "monaster"),
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
            "in un cimitero", "vecchio cimitero", "tra le lapidi", "villaggio abbandonato",
            "citta fantasma", "rovine maledette", "terra maledetta", "processione funebre",
        ],
        "keywords": [
            "cimitero", "lapide", "lapidi", "necropoli", "mausoleo", "camposanto",
            "maledetto", "maledetta", "spettrale", "fantasma", "fantasmi", "spettro", "corvi", "forca",
        ],
        "stems": ("cimiter", "necrop", "maledett", "spettral"),
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
            "in una miniera", "miniera abbandonata", "citta nanica", "forgia dei nani",
            "caverna sotterranea", "grotta profonda", "caverna di cristallo", "sotto la montagna",
        ],
        "keywords": [
            "miniera", "miniere", "nani", "nanico", "nanica", "forgia", "fucina", "incudine",
            "piccone", "mithril", "stalattiti", "stalagmiti", "grotta", "caverna", "caverne", "sottosuolo",
        ],
        "stems": ("minier", "cavern", "grott", "nanic"),
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
            "ballo in maschera", "torneo cavalleresco",
        ],
        "keywords": [
            "fiera", "carnevale", "circo", "festival", "giullare", "acrobati",
            "tendone", "giostra", "torneo", "spettacolo",
        ],
        "stems": ("carneval", "spettacol"),
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
        "preferred_moods": ["mistero", "indagine"],
        "specificity": 1.5,
        "phrases": [
            "antica biblioteca", "torre del mago", "torre arcana", "accademia di magia",
            "laboratorio alchemico", "scaffali pieni di libri", "osservatorio astronomico",
        ],
        "keywords": [
            "biblioteca", "libreria", "torre", "accademia", "universita", "osservatorio",
            "laboratorio", "alchimia", "alchemico", "pergamene", "tomi", "manoscritti",
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
        "specificity": 1.1,
        "phrases": [
            "passo di montagna", "sentiero di montagna", "vette rocciose", "scalate la montagna",
            "in cima alla montagna", "canyon roccioso", "tra le montagne",
        ],
        "keywords": [
            "montagna", "montagne", "vetta", "vette", "picco", "dirupo", "precipizio",
            "burrone", "rupe", "altipiano", "altopiano", "valico",
        ],
        "stems": ("montagn", "roccios"),
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
        "specificity": 1.0,
        "phrases": [
            "in una valle", "nella valle", "in una foresta", "nella foresta", "nel bosco",
            "bosco elfico", "foresta incantata", "foresta antica", "verde vallata",
            "radura nel bosco", "lungo il fiume", "attraversate il bosco",
        ],
        "keywords": [
            "valle", "vallata", "foresta", "bosco", "boscaglia", "radura", "alberi", "quercia",
            "prato", "prateria", "pianura", "collina", "colline", "fiume", "ruscello", "cascata", "elfico",
        ],
        "stems": ("forest", "vallat", "collin", "prateri"),
        "query": "Elder Scrolls Through Sunflower Fields Far Horizons forest valley rpg instrumental",
        "seed_tracks": [
            {"videoId": "wZ5B82Zvgqg", "title": "Through Sunflower Fields (Valley Instrumental)", "artist": "Brad Derrick (Elder Scrolls OST)", "duration": "9:00", "thumbnail": "https://i.ytimg.com/vi/wZ5B82Zvgqg/hqdefault.jpg"},
            {"videoId": "ZarbRbkV4ak", "title": "Far Horizons (Forest & Valley Instrumental)", "artist": "Jeremy Soule (Skyrim OST)", "duration": "5:32", "thumbnail": "https://i.ytimg.com/vi/ZarbRbkV4ak/hqdefault.jpg"},
            {"videoId": "05q762SYKEA", "title": "Halfling Hills (Green Valley Instrumental)", "artist": "Derek Fiechter", "duration": "4:36", "thumbnail": "https://i.ytimg.com/vi/05q762SYKEA/hqdefault.jpg"},
            {"videoId": "R6R5AJtjOeU", "title": "The Road to Baldur's Gate (Instrumental)", "artist": "Borislav Slavov", "duration": "2:08", "thumbnail": "https://i.ytimg.com/vi/R6R5AJtjOeU/hqdefault.jpg"},
        ],
    },
]

# Indicatori sintattici italiani di posizione/ingresso in un ambiente ("siete in...", "entrate in...", "vi trovate...")
LOCATIVE_PATTERNS = (
    "siete in ", "siete nel ", "siete nella ", "siete nello ", "siete nei ", "siete nelle ", "siete sul ", "siete sulla ",
    "siamo in ", "siamo nel ", "siamo nella ", "vi trovate ", "entrate ", "entrano ", "arrivate ", "arriviamo ",
    "attraversate ", "camminate ", "viaggiate ", "davanti a voi ", "intorno a voi ", "vi addentrate ", "scendete ", "salite ",
)


class HybridAnalyzer:
    def __init__(self) -> None:
        self.context_window: Deque[str] = deque(maxlen=4)

    def clear_context(self) -> None:
        self.context_window.clear()

    def _detect_environment_biome(
        self, norm_text: str, words: set, moods: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Rileva se la frase descrive uno specifico bioma o ambiente (es. "siete in una valle innevata",
        "siete in un deserto", "siete in una palude", "alto mare", "sala del trono", "tempio", ecc.)
        e restituisce tracce e query 100% strumentali pertinenti all'ambiente esatto.
        """
        has_locative = any(lp in norm_text for lp in LOCATIVE_PATTERNS)
        best_biome: Optional[Dict[str, Any]] = None
        best_score = 0.0
        best_hits: List[str] = []

        for biome in ENVIRONMENT_BIOMES:
            raw_score = 0.0
            hits: List[str] = []

            for phrase in biome.get("phrases", []):
                if phrase in norm_text:
                    raw_score += 6.0
                    hits.append(phrase)

            for kw in biome.get("keywords", []):
                if kw in words:
                    raw_score += 4.2
                    hits.append(kw)

            for stem in biome.get("stems", ()):
                for w in words:
                    if len(w) >= 4 and w.startswith(stem) and w not in hits:
                        raw_score += 4.2
                        hits.append(w)
                        break

            if raw_score > 0:
                if has_locative:
                    raw_score += 2.5
                weighted_score = round(raw_score * float(biome.get("specificity", 1.0)), 2)
                if weighted_score > best_score:
                    best_score = weighted_score
                    best_biome = biome
                    best_hits = list(dict.fromkeys(hits))

        if not best_biome or best_score < 3.5:
            return None

        # Scegli il mood contenitore attivo nel profilo corrente (default: esplorazione o il primo disponibile)
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
            # Prima controlla se il comando richiede un ambiente specifico (es. "bardo metti deserto", "musica da neve")
            env_res = self._detect_environment_biome(target, set(target.split()), moods)
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

    def _detect_danger_and_urgency(self, norm_text: str, words: set) -> Tuple[str, List[str]]:
        """
        Analizza se la frase contiene indicatori di pericolo attivo, fuoco/fiamme, agonia, danno o combattimento.
        Restituisce: ("none" | "combat_danger" | "catastrophic", lista_termini_rilevati)
        """
        # Eccezione: se la frase dice esplicitamente "fuoco da campo" o "intorno al fuoco" senza parole di danno
        if ("fuoco da campo" in norm_text or "accendete il falo" in norm_text) and not any(
            w.startswith(("bruci", "danni", "attacc", "ferit", "muor", "morend")) for w in words
        ):
            return "none", []

        catastrophic_hits: List[str] = []
        for pat in CATASTROPHIC_PHRASES:
            if pat in norm_text:
                catastrophic_hits.append(pat)

        danger_hits: List[str] = []
        for w in words:
            if w in DANGER_EXACT_WORDS:
                danger_hits.append(w)
            elif len(w) >= 5 and w.startswith(DANGER_WORD_STEMS):
                danger_hits.append(w)

        if catastrophic_hits:
            return "catastrophic", catastrophic_hits + danger_hits[:2]
        if danger_hits:
            return "combat_danger", danger_hits
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
        2. Pattern di fine scontro / vittoria
        3. Veto semantico anti-errore (nessuna scena di pericolo/fuoco/ferite può mai attivare Riposo/Taverna!)
        4. Matching di frasi, parole chiave e radici morfologiche.
        """
        norm_text = normalize_italian(raw_text)
        if not norm_text:
            return {"mood_id": None, "confidence": 0.0, "matched_by": "none", "matched_terms": []}

        moods: Dict[str, Any] = profile.get("moods", {})

        # 1. Controlla prima se è un comando vocale diretto
        cmd = self.detect_voice_command(norm_text, moods)
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
            "uscite dal combattimento",
        ]
        for pat in combat_end_patterns:
            if pat in norm_text:
                if "vittoria" in moods:
                    return {
                        "mood_id": "vittoria",
                        "confidence": 5.0,
                        "matched_by": "keywords",
                        "matched_terms": [pat],
                    }
                default_mood = profile.get("default_mood")
                if default_mood and default_mood in moods:
                    return {
                        "mood_id": default_mood,
                        "confidence": 4.5,
                        "matched_by": "keywords",
                        "matched_terms": [pat],
                    }

        words = set(norm_text.split())
        danger_level, danger_terms = self._detect_danger_and_urgency(norm_text, words)

        # 3. Se non c'è pericolo/combattimento attivo, controlla se il GM sta descrivendo un BIOMA/AMBIENTE specifico
        # (es. "siete in una valle innevata", "siete in un deserto", "siete in una palude", "alto mare", ecc.)
        env_res: Optional[Dict[str, Any]] = None
        if danger_level == "none":
            env_res = self._detect_environment_biome(norm_text, words, moods)

        scores: Dict[str, float] = {}
        matched_terms_map: Dict[str, List[str]] = {}

        for mood_id, mood in moods.items():
            tone = mood.get("tone_profile", "")
            is_calm_mood = (mood_id in CALM_MOOD_IDS) or (tone in CALM_TONE_PROFILES)

            # VETO SEMANTICO RIGIDO: se c'è pericolo, fuoco, ferite, morte o combattimento nella frase,
            # le atmosfere calme/riposo/taverna vengono BLOCCATE!
            if danger_level != "none" and is_calm_mood:
                continue

            score = 0.0
            hits: List[str] = []

            # Frasi multi-parola (peso alto: 4.0)
            for phrase in mood.get("phrases", []):
                norm_phrase = normalize_italian(phrase)
                if norm_phrase and norm_phrase in norm_text:
                    score += 4.0
                    hits.append(phrase)

            # Parole chiave singole e radici morfologiche sicure (lunghezza >= 6)
            for kw in mood.get("keywords", []):
                norm_kw = normalize_italian(kw)
                if not norm_kw:
                    continue
                if " " in norm_kw:
                    if norm_kw in norm_text:
                        score += 3.0
                        hits.append(kw)
                elif norm_kw in words:
                    score += 2.2
                    hits.append(kw)
                elif len(norm_kw) >= 6:
                    stem = norm_kw[:-1]
                    for w in words:
                        if len(w) >= 6 and abs(len(w) - len(norm_kw)) <= 3 and w.startswith(stem):
                            score += 1.8
                            hits.append(kw)
                            break

            # Boost semantico automatico per le atmosfere di Combattimento / Azione / Boss quando c'è pericolo!
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
                elif mood_id in ("combattimento", "sparatoria", "fuga", "terrore") or tone == "fast_combat":
                    score += 4.2
                    for dt in danger_terms[:2]:
                        if dt not in hits:
                            hits.append(dt)

            if score > 0:
                scores[mood_id] = round(score, 2)
                matched_terms_map[mood_id] = list(dict.fromkeys(hits))

        if env_res:
            # Se è stato rilevato un ambiente/bioma specifico (es. "valle innevata", "deserto", "palude", "mare"),
            # ha priorità assoluta a meno che la frase non sia esplicitamente su taverna/riposo/vittoria con punteggio superiore
            if not scores:
                return env_res
            best_mood_id = max(scores, key=lambda k: scores[k])
            best_score = scores[best_mood_id]
            if best_mood_id in ("taverna", "accampamento", "vittoria", "club") and best_score > env_res["confidence"]:
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
        Usa un modello AI (Gemini, Ollama locale o OpenAI) per interpretare il contesto
        narrativo del Game Master, rispettando anch'esso il veto semantico sui pericoli.
        """
        moods = profile.get("moods", {})
        if not moods:
            return {"mood_id": None, "confidence": 0.0, "matched_by": "none"}

        norm_text = normalize_italian(raw_text)
        danger_level, _ = self._detect_danger_and_urgency(norm_text, set(norm_text.split()))

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
1. Se i personaggi sono in pericolo, stanno bruciando, subiscono danni o combattono, scegli SEMPRE un'atmosfera ad alta intensità (combattimento/boss/terrore/fuga) e MAI riposo o taverna!
2. La musica deve essere ESCLUSIVAMENTE STRUMENTALE (100% instrumental, senza parole e senza cantato). Se compili custom_search_query, includi sempre "instrumental".

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
                model = analyzer_cfg.get("gemini_model") or "gemini-2.0-flash"
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.1,
                        "responseMimeType": "application/json",
                    },
                }
                async with httpx.AsyncClient(timeout=6.0) as client:
                    resp = await client.post(url, json=payload)
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
            return {
                "mood_id": None,
                "confidence": 0.0,
                "matched_by": "none",
                "ai_error": str(e),
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
        threshold = float(analyzer_cfg.get("confidence_threshold", 2.0))

        kw_result = self.analyze_keywords(cleaned, profile, threshold=threshold)

        if kw_result.get("voice_action") or kw_result.get("matched_by") == "command":
            return kw_result

        if mode == "keywords":
            return kw_result

        if mode == "hybrid":
            if kw_result.get("mood_id") and kw_result.get("confidence", 0) >= threshold:
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
