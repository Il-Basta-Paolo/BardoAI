"""
Bardo AI v2.6.1 — Regia Musicale Intelligente & Soundboard Vocale per Sessioni GdR.
Entry point desktop PySide6.
Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

from __future__ import annotations

import os
import sys

__author__ = "Paolo Basta"
__version__ = "2.6.1"

# Abilita rendering High DPI per schermi 4K e display moderni su Windows
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from storage import ensure_data_dir
from ui.main_window import MainWindow


def main() -> None:
    # Assicura che le cartelle dati necessarie esistano
    ensure_data_dir()

    app = QApplication(sys.argv)
    app.setApplicationName("Bardo AI")
    app.setApplicationVersion("2.6.1")
    app.setOrganizationName("Paolo Basta")
    app.setOrganizationDomain("github.com/Il-Basta-Paolo/BardoAI")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
