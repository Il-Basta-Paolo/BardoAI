"""
Test per analyzer.py:
- Parsing delle negazioni clausola per clausola
- Disambiguazione omografi e falsi positivi (danno, fuoco, costa, farò, reale)
- Veto del pericolo (danger veto)
- Riconoscimento biomi pulito
"""

from analyzer import (
    SceneAnalyzer,
    split_affirmed_and_negated_text,
    preprocess_text_for_analysis,
)


def test_split_affirmed_and_negated_text():
    # Test 1: frase con negazione semplice
    raw = "Non c'è nessun pericolo, siamo al sicuro nella stanza"
    aff, neg = split_affirmed_and_negated_text(raw)
    assert "pericolo" in neg
    assert "sicuro" in aff

    # Test 2: frase mista con congiunzione avversativa
    raw = "Non sentite alcun rumore ma all'improvviso vedete un'ombra minacciosa"
    aff, neg = split_affirmed_and_negated_text(raw)
    assert "rumore" in neg
    assert "ombra minacciosa" in aff or "ombra" in aff

    # Test 3: nessuna negazione
    raw = "I goblin caricano con le loro scimitarre"
    aff, neg = split_affirmed_and_negated_text(raw)
    assert "goblin" in aff
    assert neg == ""


def test_homograph_disambiguation_rules():
    # 1. "vi danno il benvenuto" NON deve diventare danno da combattimento
    txt1 = "Gli abitanti del villaggio vi danno il caloroso benvenuto"
    p1 = preprocess_text_for_analysis(txt1)
    assert " danno " not in f" {p1} "

    # 2. "intorno al fuoco" NON deve attivare pericolo/combattimento
    txt2 = "Ci sediamo tranquilli intorno al fuoco a riposare"
    p2 = preprocess_text_for_analysis(txt2)
    assert " fuoco " not in f" {p2} "
    assert "falo" in p2 or "bivacco" in p2 or "fuoco" not in p2

    # 3. "costa dieci monete" NON deve attivare il bioma mare/costa
    txt3 = "Questa pozione costa dieci monete d'oro"
    p3 = preprocess_text_for_analysis(txt3)
    assert " costa " not in f" {p3} "

    # 4. "lo farò" normalizzato NON deve attivare il bioma faro/costa
    txt4 = "Non temete, lo farò io stesso al più presto"
    p4 = preprocess_text_for_analysis(txt4)
    assert " faro " not in f" {p4} "

    # 5. "è reale" NON deve attivare castello/corte reale
    txt5 = "Quello che vedete è reale, non è un'illusione"
    p5 = preprocess_text_for_analysis(txt5)
    assert " reale " not in f" {p5} "


def test_biome_classification_no_false_positives():
    analyzer = SceneAnalyzer()

    # "costa dieci monete d'oro" non deve rilevare il bioma costa/mare
    res = analyzer.analyze_quick("Questa birra vi costa tre monete", profile_id="fantasy_dnd")
    assert res.biome != "costa"
    assert res.biome != "mare"

    # "è reale" non deve rilevare castello
    res2 = analyzer.analyze_quick("Il problema che affrontiamo è reale e concreto", profile_id="fantasy_dnd")
    assert res2.biome != "castello"

    # Una vera descrizione della costa deve invece rilevare il bioma costa
    res3 = analyzer.analyze_quick("Camminiamo sulla spiaggia sabbiosa della costa marina", profile_id="fantasy_dnd")
    assert res3.biome in ("costa", "mare", "mare_oceano")


def test_danger_veto_rule():
    analyzer = SceneAnalyzer()

    # Se ci sono parole calme ma anche un attacco improvviso, il pericolo deve prevalere immediatamente
    combat_text = "I viandanti riposavano sereni quando all'improvviso un'imboscata di orchi li attacca"
    res = analyzer.analyze_quick(combat_text, profile_id="fantasy_dnd")
    assert res.mood in ("combattimento", "tensione", "boss")

    # Ma se il pericolo è negato, NON deve scattare il combattimento
    safe_text = "Non c'è nessun pericolo e nessun nemico, siamo completamente al sicuro"
    res_safe = analyzer.analyze_quick(safe_text, profile_id="fantasy_dnd")
    assert res_safe.mood not in ("combattimento", "boss")


def test_analyze_quick_with_dict_profile():
    from config_defaults import DEFAULT_CONFIG
    analyzer = SceneAnalyzer()
    profile_dict = DEFAULT_CONFIG["profiles"]["fantasy_dnd"]
    res = analyzer.analyze_quick("I goblin scoccano le loro frecce!", profile_id=profile_dict)
    assert res.mood in ("combattimento", "tensione")
