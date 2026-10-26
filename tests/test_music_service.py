"""
Test per music_service.py e ytmusic_service.py:
- Filtro 'solo strumentale' a parole intere (bug #7 di bastaaaa.md):
  'Enchanted' non viene scartato per 'chant', 'Defeat' non per 'feat', 'Operation' non per 'opera', 'Beginning' non per 'inn'.
- Costruzione query e sanitizzazione titoli

Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

__author__ = "Paolo Basta"

from music_service import (
    is_instrumental_candidate,
    clean_music_title,
)


def test_instrumental_vocal_filter_boundary_regex():
    # Test bug #7: queste tracce valide NON devono essere scartate
    assert is_instrumental_candidate("Enchanted Forest Adventure") is True
    assert is_instrumental_candidate("The Defeat of the Goblin King") is True
    assert is_instrumental_candidate("Covert Operation Theme") is True
    assert is_instrumental_candidate("At the Beginning of Time") is True
    assert is_instrumental_candidate("Warrior's Chant of Victory (Instrumental)") is True

    # Tracce che contengono esplicitamente indicazioni di parti cantate DEVONO essere scartate
    assert is_instrumental_candidate("Tavern Song (feat. Voice Artist)") is False
    assert is_instrumental_candidate("Epic Battle Vocal Theme") is False
    assert is_instrumental_candidate("Ballad of Heroes (with lyrics)") is False


def test_clean_music_title():
    raw1 = "Epic Tavern Music (Official Video) [HD] [1080p]"
    assert clean_music_title(raw1) == "Epic Tavern Music"

    raw2 = "Dungeon Ambient Track (HQ Audio) - Fantasy"
    clean2 = clean_music_title(raw2)
    assert "HQ Audio" not in clean2
    assert "Dungeon Ambient Track" in clean2
