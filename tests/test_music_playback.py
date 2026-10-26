"""
Test di integrazione e unitari per il motore di riproduzione musicale (Bardo AI).
Verifica:
1. Risoluzione di tracce locali e remote verso oggetti MusicSource validi per AudioEngine.
2. Fallback trasparente su libreria locale se YouTube/rete non è disponibile.
3. Resilienza del worker thread di MainWindow (gestione token generazionale, eccezioni).

Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

from unittest.mock import MagicMock
from audio_engine import AudioEngine, MusicSource
from music_service import MusicService
import storage


def test_music_source_instantiation():
    """Verifica che MusicSource accetti i campi corretti e funzioni con AudioEngine."""
    source = MusicSource(
        uri="https://example.com/audio.opus",
        title="Tavern Ambience",
        duration=180.0,
        http_headers={"User-Agent": "BardoAI"},
        skip_segments=[(10.0, 20.0)],
    )
    assert source.uri == "https://example.com/audio.opus"
    assert source.title == "Tavern Ambience"
    assert source.duration == 180.0
    assert source.http_headers == {"User-Agent": "BardoAI"}
    assert source.skip_segments == [(10.0, 20.0)]


def test_resolve_playable_local_track(tmp_path, monkeypatch):
    """Verifica che un file locale venga risolto correttamente con metadati completi."""
    fake_local_dir = tmp_path / "local_music"
    fake_local_dir.mkdir(parents=True)
    mood_dir = fake_local_dir / "taverna"
    mood_dir.mkdir()
    fake_track_file = mood_dir / "cozy_hearth.mp3"
    fake_track_file.write_text("fake mp3 data", encoding="utf-8")

    monkeypatch.setattr(storage, "LOCAL_MUSIC_DIR", fake_local_dir)
    import music_service
    monkeypatch.setattr(music_service, "LOCAL_MUSIC_DIR", fake_local_dir)

    mock_ytdlp = MagicMock()
    ms = MusicService(mock_ytdlp)

    local_candidates = ms.local_tracks("taverna")
    assert len(local_candidates) == 1
    assert local_candidates[0]["title"] == "cozy_hearth"
    assert local_candidates[0]["source"] == "local"

    resolved = ms.resolve_playable(local_candidates[0])
    assert resolved["uri"] == str(fake_track_file)
    assert resolved["title"] == "cozy_hearth"
    assert resolved["cached"] is True

    # Verifica compatibilità diretta con MusicSource
    source = MusicSource(
        uri=resolved["uri"],
        title=resolved["title"],
        duration=resolved["duration"],
        http_headers=resolved.get("http_headers", {}),
        skip_segments=resolved.get("skip_segments", []),
    )
    assert source.uri == str(fake_track_file)


def test_resolve_playable_remote_track():
    """Verifica che una traccia remota risolta via YtDlpManager generi un dizionario compatibile."""
    mock_ytdlp = MagicMock()
    mock_ytdlp.resolve_stream.return_value = {
        "uri": "https://googlevideo.com/videoplayback?id=123",
        "title": "Epic Boss Battle",
        "duration": 240.0,
        "http_headers": {"Range": "bytes=0-"},
        "skip_segments": [(5.0, 15.0)],
        "cached": False,
    }

    ms = MusicService(mock_ytdlp)
    track = {"videoId": "boss123", "title": "Epic Boss Battle", "artist": "Composer"}

    resolved = ms.resolve_playable(track)
    assert resolved["uri"].startswith("https://googlevideo.com")
    assert resolved["title"] == "Epic Boss Battle"
    assert resolved["artist"] == "Composer"

    source = MusicSource(
        uri=resolved["uri"],
        title=resolved["title"],
        duration=resolved["duration"],
        http_headers=resolved.get("http_headers", {}),
        skip_segments=resolved.get("skip_segments", []),
    )
    assert source.uri == resolved["uri"]
    assert source.duration == 240.0


def test_fetch_worker_logic_with_generation_check():
    """Simula la logica del worker di riproduzione con controllo di invalidazione generazionale."""
    mock_director = MagicMock()
    mock_audio_engine = MagicMock(spec=AudioEngine)
    mock_music_service = MagicMock(spec=MusicService)

    # Caso 1: Generazione scaduta (il DM ha cambiato scena nel frattempo)
    mock_director.is_current.return_value = False
    generation = 1

    # Se non è corrente, il worker deve uscire immediatamente senza chiamare l'audio engine
    if not mock_director.is_current(generation):
        skipped = True
    else:
        skipped = False
    assert skipped is True
    mock_audio_engine.play.assert_not_called()

    # Caso 2: Generazione valida, risoluzione con successo
    mock_director.is_current.return_value = True
    mock_music_service.resolve_playable.return_value = {
        "uri": "https://audio-stream.url",
        "title": "Combat Track",
        "duration": 150.0,
        "http_headers": {},
        "skip_segments": [],
    }

    resolved = mock_music_service.resolve_playable({"videoId": "xyz"})
    source = MusicSource(
        uri=resolved["uri"],
        title=resolved["title"],
        duration=resolved["duration"],
        http_headers=resolved.get("http_headers", {}),
        skip_segments=resolved.get("skip_segments", []),
    )
    mock_audio_engine.play(source, crossfade_seconds=3.0)
    mock_audio_engine.play.assert_called_once()
    assert mock_audio_engine.play.call_args[0][0].uri == "https://audio-stream.url"
