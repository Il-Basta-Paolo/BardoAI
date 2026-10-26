"""
Griglia dinamica e responsiva per la selezione delle atmosfere (Moods) in PySide6 per Bardo AI.
Supporta qualsiasi numero di atmosfere (>9) senza nascondere elementi (risolve bug #12 di bastaaaa.md).
Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

__author__ = "Paolo Basta"


class MoodCard(QFrame):
    clicked = Signal(str)

    def __init__(self, mood_data: Dict[str, Any], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.mood_id = mood_data.get("id", "")
        self.mood_color = mood_data.get("color", "#3b82f6")
        self.is_active = False

        self.setObjectName("card")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(85)
        self.setToolTip(mood_data.get("description", ""))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        # Riga 1: Icona ed Etichetta Nome
        top_row = QHBoxLayout()
        icon = QLabel(mood_data.get("icon", "🎭"))
        icon.setStyleSheet("font-size: 20px;")
        top_row.addWidget(icon)

        self.name_label = QLabel(mood_data.get("name", self.mood_id))
        self.name_label.setStyleSheet("font-size: 13px; font-weight: 600; color: #f8fafc;")
        top_row.addWidget(self.name_label)
        top_row.addStretch()
        layout.addLayout(top_row)

        # Riga 2: Badge del tono musicale
        tone = mood_data.get("tone_profile", "soundtrack")
        tone_lbl = QLabel(tone.replace("_", " ").upper())
        tone_lbl.setStyleSheet(f"font-size: 10px; color: {self.mood_color}; font-weight: 700; letter-spacing: 0.5px;")
        layout.addWidget(tone_lbl)

        self._update_style()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.mood_id)

    def set_active(self, active: bool) -> None:
        self.is_active = active
        self._update_style()

    def _update_style(self) -> None:
        if self.is_active:
            self.setStyleSheet(
                f"QFrame#card {{ background-color: #1e293b; border: 2px solid {self.mood_color}; border-radius: 8px; }}"
            )
        else:
            self.setStyleSheet(
                "QFrame#card { background-color: #151c2c; border: 1px solid #1e293b; border-radius: 8px; }"
                "QFrame#card:hover { background-color: #1e293b; border-color: #334155; }"
            )


class MoodGridWidget(QWidget):
    mood_selected = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._cards: Dict[str, MoodCard] = {}
        self._active_mood_id: Optional[str] = None

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(8)

        # Scroll area per supportare qualsiasi numero di atmosfere senza overflow
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.container = QWidget()
        self.grid_layout = QGridLayout(self.container)
        self.grid_layout.setContentsMargins(4, 4, 4, 4)
        self.grid_layout.setSpacing(10)

        self.scroll.setWidget(self.container)
        main_layout.addWidget(self.scroll)

    def populate(self, moods_dict: Dict[str, Any]) -> None:
        # Pulisce la griglia precedente
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._cards.clear()

        # Ricostruisce le card in 3 colonne
        columns = 3
        for idx, (mood_id, data) in enumerate(moods_dict.items()):
            row = idx // columns
            col = idx % columns
            card = MoodCard(data)
            card.clicked.connect(self._on_card_clicked)
            self.grid_layout.addWidget(card, row, col)
            self._cards[mood_id] = card

        if self._active_mood_id and self._active_mood_id in self._cards:
            self._cards[self._active_mood_id].set_active(True)

    def _on_card_clicked(self, mood_id: str) -> None:
        self.set_active_mood(mood_id)
        self.mood_selected.emit(mood_id)

    def set_active_mood(self, mood_id: Optional[str]) -> None:
        self._active_mood_id = mood_id
        for mid, card in self._cards.items():
            card.set_active(mid == mood_id)
