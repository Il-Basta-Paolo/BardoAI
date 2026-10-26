"""
Test di unità e integrazione per l'autenticazione YouTube Music (Bardo AI).
Verifica:
1. Rilevamento dello stato di autenticazione (ospite vs autenticato).
2. Generazione e salvataggio sicuro degli headers con SAPISIDHASH.
3. Disconnessione e pulizia delle credenziali.
4. Recupero delle playlist personali dell'utente.
5. Presenza e corretto comportamento della scheda YouTube Music in SettingsDialog.

Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

import json
import os
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from music_service import MusicService
import storage
from ui.dialogs.settings_dialog import SettingsDialog


@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_auth_status_detection_guest_and_authenticated(tmp_path, monkeypatch):
    """Verifica che lo stato di autenticazione rifletta l'esistenza di YTMUSIC_AUTH_FILE."""
    fake_auth_file = tmp_path / "ytmusic_auth.json"
    monkeypatch.setattr(storage, "YTMUSIC_AUTH_FILE", fake_auth_file)
    import music_service
    monkeypatch.setattr(music_service, "YTMUSIC_AUTH_FILE", fake_auth_file)

    mock_ytdlp = MagicMock()
    ms = MusicService(mock_ytdlp)

    # 1. Non autenticato
    assert ms.is_authenticated is False
    status = ms.get_auth_status()
    assert status["authenticated"] is False
    assert status["auth_file_exists"] is False

    # 2. Autenticato (creando il file di auth)
    fake_auth_file.write_text(json.dumps({"cookie": "test_cookie", "authorization": "test_auth"}), encoding="utf-8")
    assert ms.is_authenticated is True
    status = ms.get_auth_status()
    assert status["authenticated"] is True
    assert status["auth_file_exists"] is True


def test_save_auth_cookie_string_success_and_error(tmp_path, monkeypatch):
    """Verifica che la conversione da stringa cookie ad header JSON avvenga correttamente."""
    fake_auth_file = tmp_path / "ytmusic_auth.json"
    monkeypatch.setattr(storage, "YTMUSIC_AUTH_FILE", fake_auth_file)
    import music_service
    monkeypatch.setattr(music_service, "YTMUSIC_AUTH_FILE", fake_auth_file)

    # Cookie valido contenente SAPISID
    cookie_sample = "VISITOR_INFO1_LIVE=xyz; SAPISID=abc123secret; SID=sid456"
    MusicService._save_auth_cookie_string(cookie_sample)

    assert fake_auth_file.is_file()
    data = json.loads(fake_auth_file.read_text(encoding="utf-8"))
    assert "cookie" in data
    assert "authorization" in data
    assert "user-agent" in data
    assert data["x-goog-authuser"] == "0"
    assert "SAPISID=abc123secret" in data["cookie"]

    # Cookie non valido (manca SAPISID)
    try:
        MusicService._save_auth_cookie_string("SID=only_sid")
        raise AssertionError("Doveva sollevare ValueError per cookie privo di SAPISID")
    except ValueError:
        pass


def test_disconnect_account(tmp_path, monkeypatch):
    """Verifica che disconnect_account cancelli il file auth e reimposti il client in modalità ospite."""
    fake_auth_file = tmp_path / "ytmusic_auth.json"
    fake_auth_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(storage, "YTMUSIC_AUTH_FILE", fake_auth_file)
    import music_service
    monkeypatch.setattr(music_service, "YTMUSIC_AUTH_FILE", fake_auth_file)

    mock_ytdlp = MagicMock()
    ms = MusicService(mock_ytdlp)
    assert ms.is_authenticated is True

    ms.disconnect_account()
    assert fake_auth_file.exists() is False
    assert ms.is_authenticated is False


def test_get_user_playlists(tmp_path, monkeypatch):
    """Verifica il parsing e il recupero delle playlist personali dell'utente connesso."""
    fake_auth_file = tmp_path / "ytmusic_auth.json"
    fake_auth_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(storage, "YTMUSIC_AUTH_FILE", fake_auth_file)
    import music_service
    monkeypatch.setattr(music_service, "YTMUSIC_AUTH_FILE", fake_auth_file)

    mock_ytdlp = MagicMock()
    ms = MusicService(mock_ytdlp)

    mock_client = MagicMock()
    mock_client.get_library_playlists.return_value = [
        {
            "playlistId": "PL123",
            "title": "Taverna Campagna 1",
            "count": "24",
            "thumbnails": [{"url": "https://img.jpg"}],
        }
    ]
    ms.ytm = mock_client

    playlists = ms.get_user_playlists(limit=10)
    assert len(playlists) == 1
    assert playlists[0]["playlistId"] == "PL123"
    assert playlists[0]["title"] == "Taverna Campagna 1"
    assert playlists[0]["thumbnail"] == "https://img.jpg"


def test_settings_dialog_ytmusic_tab(qapp):
    """Verifica la presenza e i controlli della nuova scheda YouTube Music nelle Impostazioni."""
    cfg = storage.load_config()
    dlg = SettingsDialog(cfg)

    # Verifica presenza tab YouTube Music
    tab_titles = [dlg.tab_widget.tabText(i) for i in range(dlg.tab_widget.count())]
    assert "YouTube Music" in tab_titles
    assert dlg.tab_widget.tabText(0) == "YouTube Music"

    # Verifica widget di controllo
    assert hasattr(dlg, "btn_ytm_login")
    assert hasattr(dlg, "btn_ytm_disconnect")
    assert hasattr(dlg, "btn_ytm_test")
    assert hasattr(dlg, "lbl_ytm_status")

    # Stato iniziale ospite: pulsante disconnetti disabilitato
    assert dlg.btn_ytm_disconnect.isEnabled() is False
    assert "Modalità Ospite" in dlg.lbl_ytm_status.text()
    dlg.close()
