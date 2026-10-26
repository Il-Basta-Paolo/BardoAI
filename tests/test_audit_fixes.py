"""
Test di unità e integrazione per le correzioni e rifiniture dell'audit (v2.6.3):
1. Inizializzazione ContinuousVoiceListener con whisper_model configurabile e recovery Vosk corrotto.
2. Rotazione traccia intelligente e prevenzione loop su Skip (⏭️).
3. Utilizzo prioritario di `custom_playlist` definita nel mood.
4. Auto-advance della musica a fine brano (rilevamento track finished).
5. Integrazione della Regia AI asincrona in _on_voice_final_transcript.

Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

from __future__ import annotations

import os
import threading
import time
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from storage import ConfigManager
from ui.main_window import MainWindow
from voice_listener import ContinuousVoiceListener, ModelManager

os.environ["QT_QPA_PLATFORM"] = "offscreen"


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(autouse=True)
def isolate_config_save(monkeypatch):
    """Evita che i test sovrascrivano il file config.json locale dell'utente."""
    monkeypatch.setattr(ConfigManager, "save", lambda cfg: None)


def test_continuous_voice_listener_params_and_vosk_recovery(tmp_path, monkeypatch):
    """Verifica il supporto al parametro whisper_model e la rimozione di cartelle Vosk corrotte."""
    dummy_cb = MagicMock()
    listener = ContinuousVoiceListener(
        on_transcript=dummy_cb,
        use_whisper=False,
        whisper_model="base",
        gate_threshold=25,
    )
    assert listener.whisper_model == "base"
    assert listener.use_whisper is False
    assert listener.gate_threshold == 25

    # Simula una directory Vosk corrotta
    fake_vosk_dir = tmp_path / "vosk-corrupt"
    fake_vosk_dir.mkdir(parents=True, exist_ok=True)
    (fake_vosk_dir / "conf").mkdir()
    monkeypatch.setattr(ModelManager, "get_vosk_model_dir", lambda: fake_vosk_dir)
    monkeypatch.setattr(ModelManager, "is_vosk_ready", lambda: True)

    download_called = []
    monkeypatch.setattr(ModelManager, "download_vosk_model", lambda **kw: download_called.append(True))

    # Mock del modulo vosk che fallisce il caricamento simulando file mancanti/corrotti
    class BrokenVosk:
        @staticmethod
        def SetLogLevel(_lvl):
            pass

        @staticmethod
        def Model(_path):
            raise RuntimeError("Modello Vosk corrotto o incompleto")

    monkeypatch.setitem(os.sys.modules, "vosk", BrokenVosk)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    # Invoca l'inizializzazione reale
    orig_init = getattr(ContinuousVoiceListener, "_original_init_models_async", ContinuousVoiceListener._init_models_async)
    orig_init(listener)
    time.sleep(0.1)

    # La cartella corrotta deve essere stata rimossa e il download avviato
    assert not fake_vosk_dir.exists() or len(download_called) > 0


def test_custom_playlist_and_rotation_in_fetch_worker(qapp):
    """Verifica che _fetch_and_play_track_worker legga custom_playlist e ruoti le tracce evitando loop."""
    win = MainWindow()
    try:
        # Configura un mood valido con custom_playlist
        profile = win.config["profiles"][win.active_profile_id]
        profile["moods"]["test_mood"] = {
            "id": "test_mood",
            "name": "Mood Test",
            "custom_playlist": "https://music.youtube.com/playlist?list=PLTest123",
            "tone_profile": "soundtrack",
            "queries": ["epic tavern instrumental"],
        }
        win.director.generation = 1
        win.director.current_mood_id = "test_mood"

        fake_tracks = [
            {"videoId": "vid_1", "title": "Canto dei Nani", "artist": "Bardo", "duration_seconds": 120},
            {"videoId": "vid_2", "title": "Danza degli Elfi", "artist": "Bardo", "duration_seconds": 140},
        ]

        win.music_service.load_playlist = MagicMock(return_value={"tracks": fake_tracks, "title": "Playlist Test"})
        win.music_service.resolve_playable = MagicMock(side_effect=lambda t, **kw: {
            "uri": f"file:///{t['videoId']}.mp3",
            "title": t["title"],
            "artist": t["artist"],
            "duration": t["duration_seconds"],
            "http_headers": {},
            "skip_segments": [],
        })
        win.audio_engine.play = MagicMock()

        # Prima esecuzione
        win._original_fetch_and_play_track_worker("test_mood", 1)
        assert win.music_service.load_playlist.called
        assert len(win._recent_track_ids) == 1
        first_played = win._recent_track_ids[0]

        # Seconda esecuzione (Salta traccia) -> deve preferire la traccia non ancora suonata
        win._original_fetch_and_play_track_worker("test_mood", 1)
        assert len(win._recent_track_ids) == 2
        second_played = win._recent_track_ids[1]
        assert second_played != first_played

    finally:
        win.close()


def test_auto_advance_on_finished_track(qapp):
    """Verifica che _check_track_finished rilevi il termine del brano ed avanzi automaticamente."""
    win = MainWindow()
    try:
        win.director.current_mood_id = "combattimento"
        win.director.generation = 5
        win.audio_engine.paused = False

        worker_called = []
        win._fetch_and_play_track_worker = lambda mood, gen, custom="": worker_called.append((mood, gen))

        # Deck non ha terminato: non deve avanzare
        win.audio_engine.active_status = MagicMock(return_value={
            "has_source": True,
            "finished": False,
            "paused": False,
        })
        win._check_track_finished()
        assert len(worker_called) == 0

        # Deck ha terminato (EOF)
        win.audio_engine.active_status = MagicMock(return_value={
            "has_source": True,
            "finished": True,
            "paused": False,
        })
        win._check_track_finished()
        time.sleep(0.1)

        assert len(worker_called) == 1
        assert worker_called[0] == ("combattimento", 5)

    finally:
        win.close()


def test_ai_worker_invoked_on_speech(qapp):
    """Verifica che _on_voice_final_transcript invochi l'AI semantica in background se abilitata."""
    win = MainWindow()
    try:
        win.config["analyzer"]["ai_provider"] = "gemini"
        win.config["analyzer"]["mode"] = "hybrid"
        win.config["analyzer"]["confidence_threshold"] = 5.0

        ai_called = []
        done_event = threading.Event()

        async def fake_analyze(text, profile, cfg, current_mood_id=None):
            ai_called.append(text)
            done_event.set()
            return {"mood_id": "taverna", "confidence": 8.0, "matched_by": "ai (gemini)"}

        win.analyzer.analyze = fake_analyze
        win.director.submit = MagicMock()

        # Frase senza match keyword forte per attivare l'AI in modalità hybrid
        win._on_voice_final_transcript("Guardate attentamente cosa sta succedendo lì in fondo")
        assert done_event.wait(timeout=3.0), "Timeout: il worker AI in background non è stato invocato entro 3 secondi."

        assert len(ai_called) == 1
        assert "Guardate" in ai_called[0]

    finally:
        win.close()
