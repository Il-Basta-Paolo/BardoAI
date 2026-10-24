"""
Finestra di dialogo per la guida alle scorciatoie da tastiera (ShortcutsDialog) in PySide6.
Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

from typing import List, Tuple
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class ShortcutsDialog(QDialog):
    """Mostra l'elenco completo e organizzato delle scorciatoie da tastiera di Bardo AI."""

    SHORTCUT_SECTIONS: List[Tuple[str, List[Tuple[str, str]]]] = [
        (
            "🎙️ Microfono & Voce",
            [
                ("Ctrl + M", "Attiva / Disattiva Microfono (Mute rapido durante la sessione)"),
            ],
        ),
        (
            "🎵 Riproduzione & Mixer Musicale",
            [
                ("Ctrl + Spazio", "Play / Pausa musica di sottofondo"),
                ("Ctrl + Destra", "Salta alla traccia successiva (Skip immediato)"),
                ("Ctrl + Su", "Aumenta volume musica (+5%)"),
                ("Ctrl + Giù", "Abbassa volume musica (-5%)"),
            ],
        ),
        (
            "🪟 Regia & Schermo",
            [
                ("Ctrl + F11", "Attiva / Disattiva Auto-Float (Mini PiP Always-on-Top su cambio finestra)"),
                ("F1", "Apri questa guida alle scorciatoie da tastiera"),
            ],
        ),
        (
            "💥 Soundboard & Ricerca",
            [
                ("Ctrl + F", "Metti a fuoco la barra di ricerca rapida nella Soundboard"),
                ("Esc", "Azzera la ricerca e rilascia il focus per tornare al gioco"),
            ],
        ),
    ]

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Scorciatoie da Tastiera — Bardo AI")
        self.setFixedSize(580, 520)
        self.setStyleSheet("background-color: #0b0f19; color: #f8fafc;")

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 18, 18, 14)
        main_layout.setSpacing(12)

        # Header
        lbl_title = QLabel("⌨️ Scorciatoie da Tastiera Rapide")
        lbl_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #38bdf8;")
        lbl_desc = QLabel(
            "Comandi rapidi pensati per il Dungeon Master per gestire audio, microfono "
            "e soundboard senza togliere le mani dal tavolo o interrompere il gioco."
        )
        lbl_desc.setStyleSheet("font-size: 11px; color: #94a3b8;")
        lbl_desc.setWordWrap(True)

        main_layout.addWidget(lbl_title)
        main_layout.addWidget(lbl_desc)

        # Area scrollabile per le categorie
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 4, 4, 4)
        container_layout.setSpacing(12)

        for section_title, shortcuts in self.SHORTCUT_SECTIONS:
            sec_card = self._create_section_card(section_title, shortcuts)
            container_layout.addWidget(sec_card)

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

        # Barra inferiore con tasto Chiudi
        bottom_bar = QHBoxLayout()
        bottom_bar.addStretch()
        btn_close = QPushButton("Chiudi (Esc)")
        btn_close.setStyleSheet("background-color: #3b82f6; color: white; font-weight: 600; padding: 6px 16px; border-radius: 4px;")
        btn_close.clicked.connect(self.accept)
        bottom_bar.addWidget(btn_close)
        main_layout.addLayout(bottom_bar)

    def _create_section_card(self, title: str, shortcuts: List[Tuple[str, str]]) -> QFrame:
        card = QFrame()
        card.setStyleSheet("background-color: #0f172a; border: 1px solid #1e293b; border-radius: 6px;")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        lbl_sec = QLabel(title)
        lbl_sec.setStyleSheet("font-size: 12px; font-weight: bold; color: #f1f5f9;")
        layout.addWidget(lbl_sec)

        grid = QGridLayout()
        grid.setContentsMargins(4, 2, 4, 2)
        grid.setSpacing(6)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)

        for row, (key, desc) in enumerate(shortcuts):
            key_badge = QLabel(f"  {key}  ")
            key_badge.setStyleSheet(
                "background-color: #1e293b; color: #38bdf8; font-family: monospace; "
                "font-size: 11px; font-weight: bold; border: 1px solid #334155; border-radius: 4px; padding: 2px 4px;"
            )
            key_badge.setAlignment(Qt.AlignCenter)

            desc_lbl = QLabel(desc)
            desc_lbl.setStyleSheet("font-size: 11px; color: #cbd5e1;")
            desc_lbl.setWordWrap(True)

            grid.addWidget(key_badge, row, 0)
            grid.addWidget(desc_lbl, row, 1)

        layout.addLayout(grid)
        return card
