"""
Test per director.py:
- Macchina a stati centrale con lock
- Token di generazione monotoni per prevenire race conditions su fetch lenti (bug #8 di bastaaaa.md)
- Logica di isteresi: passaggio a pericolo istantaneo, de-escalation a calma controllata
"""

import time
import pytest
from config_defaults import DEFAULT_CONFIG
from director import Director, SceneDecision, URGENT_MOOD_IDS


def test_director_generation_token():
    director = Director()
    initial_gen = director.generation

    # Scelta manuale da soundboard/GUI
    dec = director.manual_select("combattimento")
    assert dec.mood_id == "combattimento"
    assert director.current_mood_id == "combattimento"
    assert director.generation > initial_gen

    # Token successivo
    dec2 = director.manual_select("taverna")
    assert dec2.mood_id == "taverna"
    assert director.generation > dec.generation


def test_director_hysteresis_and_danger():
    director = Director()
    moods = DEFAULT_CONFIG["profiles"]["fantasy_dnd"]["moods"]

    # 1. Scena di pericolo improvvisa: deve scattare SUBITO
    res_danger = {
        "mood_id": "combattimento",
        "danger_level": "combat_danger",
        "confidence": 8.0,
        "matched_by": "keyword",
    }
    d1 = director.submit(res_danger, moods)
    assert d1 is not None
    assert d1.mood_id == "combattimento"
    assert director.current_mood_id == "combattimento"

    # 2. Una singola frase di calma pronunciata un secondo dopo (dentro la min_scene_duration)
    # NON deve cambiare immediatamente la scena di combattimento
    res_calm = {
        "mood_id": "calma",
        "danger_level": "none",
        "confidence": 4.0,
        "matched_by": "keyword",
    }
    d2 = director.submit(res_calm, moods)
    assert d2 is None  # Rifiutato dall'isteresi!
    assert director.current_mood_id == "combattimento"

    # 3. Comandi vocali espliciti invece forzano il cambio immediatamente
    res_command = {
        "mood_id": "taverna",
        "matched_by": "command",
    }
    d3 = director.submit(res_command, moods)
    assert d3 is not None
    assert d3.mood_id == "taverna"
    assert director.current_mood_id == "taverna"
