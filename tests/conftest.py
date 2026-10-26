"""
Configurazione e fixture globali per la suite di test pytest di Bardo AI.
Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

import pytest
from storage import SecretVault


@pytest.fixture(autouse=True)
def mock_secret_vault(monkeypatch):
    """
    Isola permanentemente SecretVault durante tutti i test unitari in una memoria in-RAM.
    Previene categoricamente la scrittura o lettura nel Windows Credential Manager dell'utente.
    """
    store = {}
    monkeypatch.setattr(SecretVault, "_mem_cache", store)
    monkeypatch.setattr(SecretVault, "get_secret", lambda key, default="": store.get(key, default))
    monkeypatch.setattr(SecretVault, "set_secret", lambda key, val: store.__setitem__(key, val))
    monkeypatch.setattr(SecretVault, "delete_secret", lambda key: store.pop(key, None))
    yield


@pytest.fixture(autouse=True)
def mock_ytdlp_bootstrap(monkeypatch):
    """
    Impedisce a YtDlpManager di scaricare binari o avviare thread/processi
    esterni (yt-dlp/deno) durante l'intera esecuzione della suite di test unitari.
    Garantisce stabilità e previene access violation su pipe Windows in CI.
    """
    from ytdlp_manager import YtDlpManager

    def _dummy_ensure_ready_async(self, auto_update: bool = True) -> None:
        self._ready.set()

    monkeypatch.setattr(YtDlpManager, "ensure_ready_async", _dummy_ensure_ready_async)
    monkeypatch.setattr(YtDlpManager, "_bootstrap", lambda self, auto_update=True: self._ready.set())
    yield


@pytest.fixture(autouse=True)
def mock_voice_listener(monkeypatch):
    """
    Impedisce categoricamente a ContinuousVoiceListener di scaricare modelli vocali (Vosk/Whisper),
    aprire stream microfonici reali o avviare thread di cattura durante l'intera suite di test.
    Garantisce stabilità ed elimina i crash da thread I/O orfani in CI su Windows.
    """
    from voice_listener import ContinuousVoiceListener, ModelManager

    monkeypatch.setattr(ContinuousVoiceListener, "_init_models_async", lambda self: None)
    monkeypatch.setattr(ContinuousVoiceListener, "start", lambda self: None)
    monkeypatch.setattr(ContinuousVoiceListener, "stop", lambda self: None)
    monkeypatch.setattr(ModelManager, "download_vosk_model", classmethod(lambda cls, progress_callback=None, on_complete=None: None))
    yield
