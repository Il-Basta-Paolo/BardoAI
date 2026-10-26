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
