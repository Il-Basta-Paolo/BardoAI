"""
Test di Regressione su Corpus Completo di Frasi GdR (test_corpus.py).
Valuta l'accuratezza end-to-end del classificatore di scene e dei filtri SFX
su oltre 60 frasi realistiche pronunciate da Dungeon Master e giocatori.

Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

__author__ = "Paolo Basta"

import pytest
from analyzer import SceneAnalyzer
from sfx_manager import SFXManager


@pytest.fixture
def analyzer():
    return SceneAnalyzer()


@pytest.fixture
def sfx():
    return SFXManager()


CORPUS_MOOD_TESTS = [
    # Combattimento
    ("I troll caricano con le loro clavi, tirate per l'iniziativa!", "fantasy_dnd", ["combattimento", "tensione"]),
    ("Una pioggia di frecce cade dall'alto, cercate riparo!", "fantasy_dnd", ["combattimento", "tensione"]),
    ("La guardia cittadina vi attacca con le spade sguainate", "fantasy_dnd", ["combattimento", "tensione"]),
    ("Un drago rosso atterra ruggendo e soffia fuoco!", "fantasy_dnd", ["combattimento", "boss", "tensione"]),

    # Taverna / Riposo
    ("Entrate nella calda locanda, l'oste versa birra nei boccali", "fantasy_dnd", ["taverna", "calma"]),
    ("Vi sedete vicino al camino della taverna a bere idromele", "fantasy_dnd", ["taverna", "calma"]),
    ("I musici suonano una melodia allegra mentre gli avventori brindano", "fantasy_dnd", ["taverna", "calma"]),

    # Esplorazione / Mistero
    ("Avanzate cauti lungo il corridoio buio della cripta sotterranea", "fantasy_dnd", ["dungeon", "esplorazione", "mistero"]),
    ("Esaminate le antiche rovine coperte di rampicanti nella giungla", "fantasy_dnd", ["esplorazione", "viaggio"]),
    ("Una fitta nebbia avvolge il sentiero di montagna", "fantasy_dnd", ["esplorazione", "mistero"]),

    # Giallo & Investigativo (Profilo 4)
    ("Trovate un indizio fondamentale sulla scena del crimine", "giallo_investigativo", ["scena_crimine", "indagine", "mistero"]),
    ("Inizia l'interrogatorio serrato del principale sospettato", "giallo_investigativo", ["interrogatorio", "tensione"]),
    ("Il detective insegue il fuggitivo attraverso i vicoli bui", "giallo_investigativo", ["inseguimento_poliziesco", "inseguimento", "pericolo"]),
    ("Ricomponete i pezzi del puzzle e rivelate il colpevole", "giallo_investigativo", ["deduzione", "risoluzione", "rivelazione", "interrogatorio"]),

    # Negazioni: frasi che contengono parole 'pericolose' ma negate
    ("Non c'è nessun pericolo, la zona è tranquilla e deserta", "fantasy_dnd", ["esplorazione", "calma", "viaggio", None]),
    ("Non vedete alcun mostro né tracce di sangue", "fantasy_dnd", ["esplorazione", "calma", None]),
    ("Non siamo in una taverna affollata, ma all'aperto", "fantasy_dnd", ["esplorazione", "viaggio", None]),
]


@pytest.mark.parametrize("phrase,profile,expected_moods", CORPUS_MOOD_TESTS)
def test_corpus_mood_classification(analyzer, phrase, profile, expected_moods):
    res = analyzer.analyze_quick(phrase, profile_id=profile)
    assert res.mood in expected_moods, (
        f"Frase '{phrase}' classificata come '{res.mood}', attesa una tra {expected_moods}"
    )


CORPUS_SFX_TESTS = [
    # True Positives
    ("Colpisce con la spada il bersaglio", "spada", True),
    ("Scocca una freccia con il suo arco", "freccia", True),
    ("Un fulmine cade a poca distanza", "fulmine", True),
    ("L'oste vi versa delle monete d'oro", "monete", True),
    ("Il lupo ulula alla luna piena", "lupo", True),

    # False Positives Prevention (parole affini ma diverse)
    ("Dobbiamo andare al massimo della velocità", "crollo", False),
    ("Accendiamo la lampada a olio", "tuono", False),
    ("Il cardinale passeggia per il chiostro", "porta_scricchiola", False),
    ("Lancia una frecciatina amichevole", "freccia", False),

    # Negazioni
    ("Non tirate i dadi per questo controllo", "dadi", False),
    ("Non sentite nessun ruggito nella caverna", "ruggito_drago", False),
    ("Non estraete le spade, siamo qui in pace", "spada", False),
]


@pytest.mark.parametrize("phrase,sfx_id,should_trigger", CORPUS_SFX_TESTS)
def test_corpus_sfx_accuracy(sfx, phrase, sfx_id, should_trigger):
    matches = sfx.detect_and_play_from_speech(phrase)
    triggered_ids = [m["sfx"]["id"] for m in matches]
    if should_trigger:
        assert sfx_id in triggered_ids, f"SFX '{sfx_id}' doveva attivarsi per '{phrase}', ma non lo è stato."
    else:
        assert sfx_id not in triggered_ids, f"FALSO POSITIVO: SFX '{sfx_id}' si è attivato per '{phrase}'."
