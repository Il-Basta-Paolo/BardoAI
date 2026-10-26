"""
Test per sfx_manager.py:
- Nessun falso positivo da stem matching errato (bug #6 di bastaaaa.md)
- Negazioni che inibiscono l'attivazione
- Riconoscimento accurato di frasi e parole chiave
- Gestione sicura degli SFX personalizzati

Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

__author__ = "Paolo Basta"

from pathlib import Path

from sfx_manager import SFXManager


def test_stem_collision_prevention():
    mgr = SFXManager()

    # 1. "al massimo" NON deve suonare il crollo (stem mass-)
    res1 = mgr.detect_and_play_from_speech("Dobbiamo muoverci al massimo delle nostre forze")
    assert not any(x["sfx"]["id"] == "crollo" for x in res1)

    # 2. "lampada" NON deve suonare il tuono (stem lamp-)
    res2 = mgr.detect_and_play_from_speech("Prendete la lampada a olio per illuminare la stanza")
    assert not any(x["sfx"]["id"] == "tuono" for x in res2)

    # 3. "cardinale" NON deve suonare la porta (stem cardin-)
    res3 = mgr.detect_and_play_from_speech("Il cardinale fa il suo ingresso nel palazzo")
    assert not any(x["sfx"]["id"] == "porta_scricchiola" for x in res3)

    # 4. "frecciatina" NON deve suonare la freccia (stem frecc-)
    res4 = mgr.detect_and_play_from_speech("Il ladro lancia una frecciatina sarcastica al bardo")
    assert not any(x["sfx"]["id"] == "freccia" for x in res4)


def test_sfx_negations():
    mgr = SFXManager()

    # Negazione su dadi
    res1 = mgr.detect_and_play_from_speech("Non tirate i dadi per favore, è solo una scena narrativa")
    assert not any(x["sfx"]["id"] == "dadi" for x in res1)

    # Negazione su drago / ruggito
    res2 = mgr.detect_and_play_from_speech("Non sentite alcun ruggito nella caverna silenziosa")
    assert not any(x["sfx"]["id"] == "ruggito_drago" for x in res2)


def test_sfx_true_positives():
    mgr = SFXManager()

    # Spada
    res1 = mgr.detect_and_play_from_speech("Il paladino colpisce con la spada il bersaglio")
    assert any(x["sfx"]["id"] == "spada" for x in res1)

    # Fulmine
    res2 = mgr.detect_and_play_from_speech("Un violento fulmine squarcia il cielo buio")
    assert any(x["sfx"]["id"] == "fulmine" for x in res2)

    # Vero masso -> crollo
    res3 = mgr.detect_and_play_from_speech("Un enorme masso si stacca dalla parete e precipita")
    assert any(x["sfx"]["id"] == "crollo" for x in res3)


def test_custom_sfx_management(tmp_path: Path):
    custom_dir = tmp_path / "custom_sfx"
    custom_dir.mkdir(parents=True, exist_ok=True)

    fake_sound = tmp_path / "test_laser.wav"
    # Scrive un piccolo WAV valido
    import wave
    with wave.open(str(fake_sound), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(b"\x00\x00" * 4800)

    mgr = SFXManager(custom_sfx_dir=custom_dir)
    ok = mgr.add_custom_sfx(
        sfx_id="laser_gun",
        name="Cannone Laser",
        source_audio_path=fake_sound,
        category="Personalizzati",
        keywords=["laser", "blaster"],
        phrases=["spara con il blaster"],
    )
    assert ok is True

    # Verifica presenza nella libreria
    lib = mgr.get_library()
    assert "laser_gun" in lib

    # Test rilevamento vocale del custom SFX
    res = mgr.detect_and_play_from_speech("Il mercenario spara con il blaster contro il droide")
    assert any(x["sfx"]["id"] == "laser_gun" for x in res)

    # Cancellazione
    deleted = mgr.delete_custom_sfx("laser_gun")
    assert deleted is True
    assert "laser_gun" not in mgr.get_library()
