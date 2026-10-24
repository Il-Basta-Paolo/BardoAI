"""
Soundboard interattiva a categorie con supporto per effetti personalizzati illimitati in PySide6.
Risolve il bug #12 di bastaaaa.md (mostra tutti gli effetti, non solo i primi 20).
"""

from pathlib import Path
from typing import Any, Dict
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


class SFXButton(QFrame):
    triggered = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, sfx_data: Dict[str, Any], parent: QWidget = None) -> None:
        super().__init__(parent)
        self.sfx_id = sfx_data.get("id", "")
        self.is_custom = bool(sfx_data.get("custom", False))

        self.setObjectName("card")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(70)
        self.setToolTip(sfx_data.get("hint", ""))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(2)

        top_row = QHBoxLayout()
        icon_lbl = QLabel(sfx_data.get("icon", "💥"))
        icon_lbl.setStyleSheet("font-size: 16px;")
        top_row.addWidget(icon_lbl)

        name_lbl = QLabel(sfx_data.get("name", self.sfx_id))
        name_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #f8fafc;")
        top_row.addWidget(name_lbl)
        top_row.addStretch()

        if self.is_custom:
            badge = QLabel("USER")
            badge.setStyleSheet("font-size: 9px; color: #8b5cf6; font-weight: bold;")
            top_row.addWidget(badge)

        layout.addLayout(top_row)

        hint = sfx_data.get("hint", "")
        if hint:
            hint_lbl = QLabel(hint)
            hint_lbl.setStyleSheet("font-size: 10px; color: #64748b;")
            layout.addWidget(hint_lbl)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.triggered.emit(self.sfx_id)
        elif event.button() == Qt.RightButton and self.is_custom:
            menu = QMenu(self)
            del_act = menu.addAction("🗑️ Elimina questo effetto personalizzato")
            del_act.triggered.connect(lambda: self.delete_requested.emit(self.sfx_id))
            menu.exec(event.globalPos())


class AddCustomSFXDialog(QDialog):
    """Dialog per aggiungere un SFX personalizzato senza errori di permessi."""

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Aggiungi Effetto Sonoro Personalizzato")
        self.setFixedSize(420, 280)
        self.setStyleSheet("background-color: #0f172a; color: #f8fafc;")

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Nome
        layout.addWidget(QLabel("Nome dell'Effetto:"))
        self.txt_name = QLineEdit()
        self.txt_name.setPlaceholderText("Es. Cannone Laser, Ruggitone, ecc.")
        layout.addWidget(self.txt_name)

        # File Audio
        layout.addWidget(QLabel("File Audio (WAV, MP3, OGG, FLAC):"))
        file_row = QHBoxLayout()
        self.txt_path = QLineEdit()
        self.txt_path.setReadOnly(True)
        btn_browse = QPushButton("Sfoglia...")
        btn_browse.clicked.connect(self._browse_file)
        file_row.addWidget(self.txt_path)
        file_row.addWidget(btn_browse)
        layout.addLayout(file_row)

        # Parole chiave per la voce
        layout.addWidget(QLabel("Parole Chiave per attivarlo a voce (separate da virgola):"))
        self.txt_keywords = QLineEdit()
        self.txt_keywords.setPlaceholderText("Es. laser, sparo, cannone")
        layout.addWidget(self.txt_keywords)

        # Bottoni
        btn_row = QHBoxLayout()
        btn_cancel = QPushButton("Annulla")
        btn_cancel.clicked.connect(self.reject)
        btn_save = QPushButton("Salva Effetto")
        btn_save.setObjectName("primaryBtn")
        btn_save.clicked.connect(self._validate_and_accept)
        btn_row.addStretch()
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_save)
        layout.addLayout(btn_row)

    def _browse_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleziona File Audio",
            "",
            "Audio Files (*.wav *.mp3 *.ogg *.flac);;All Files (*.*)",
        )
        if path:
            self.txt_path.setText(path)
            if not self.txt_name.text():
                self.txt_name.setText(Path(path).stem.replace("_", " ").title())

    def _validate_and_accept(self) -> None:
        if not self.txt_name.text().strip() or not self.txt_path.text().strip():
            return
        self.accept()

    def get_data(self) -> Dict[str, Any]:
        p = Path(self.txt_path.text())
        kws = [k.strip() for k in self.txt_keywords.text().split(",") if k.strip()]
        sfx_id = f"custom_{p.stem.lower()}"
        return {
            "sfx_id": sfx_id,
            "name": self.txt_name.text().strip(),
            "source_path": p,
            "keywords": kws,
        }


class SoundboardWidget(QWidget):
    sfx_triggered = Signal(str)
    custom_sfx_added = Signal(dict)
    custom_sfx_deleted = Signal(str)

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self._sfx_library: Dict[str, Any] = {}

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(6)

        # Header con pulsante per aggiungere SFX
        header_row = QHBoxLayout()
        header_row.addWidget(QLabel("SOUNDBOARD EFFETTI RAPIDI"))
        header_row.addStretch()
        btn_add = QPushButton("➕ Aggiungi SFX...")
        btn_add.setStyleSheet("font-size: 11px; padding: 4px 10px;")
        btn_add.clicked.connect(self._open_add_dialog)
        header_row.addWidget(btn_add)
        main_layout.addLayout(header_row)

        # Tab per categoria
        self.tab_widget = QTabWidget()
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        main_layout.addWidget(self.tab_widget)

    def set_library(self, lib: Dict[str, Any]) -> None:
        self._sfx_library = lib
        self._rebuild_tabs()

    def _rebuild_tabs(self) -> None:
        curr_idx = max(0, self.tab_widget.currentIndex())
        self.tab_widget.clear()

        categories = ["Tutti", "Armi", "Creature", "Magia", "Ambiente", "Personalizzati"]
        for cat in categories:
            tab_page = self._build_category_page(cat)
            self.tab_widget.addTab(tab_page, cat)

        if curr_idx < self.tab_widget.count():
            self.tab_widget.setCurrentIndex(curr_idx)

    def _build_category_page(self, category: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        container = QWidget()
        grid = QGridLayout(container)
        grid.setContentsMargins(4, 4, 4, 4)
        grid.setSpacing(8)

        columns = 4
        matched_items = []
        for sid, item in self._sfx_library.items():
            item_cat = item.get("category", "")
            if category == "Tutti":
                matched_items.append((sid, item))
            elif category == "Personalizzati" and item.get("custom"):
                matched_items.append((sid, item))
            elif item_cat == category:
                matched_items.append((sid, item))

        for idx, (sid, item) in enumerate(matched_items):
            row = idx // columns
            col = idx % columns
            btn = SFXButton(item)
            btn.triggered.connect(self.sfx_triggered.emit)
            btn.delete_requested.connect(self.custom_sfx_deleted.emit)
            grid.addWidget(btn, row, col)

        scroll.setWidget(container)
        layout.addWidget(scroll)
        return page

    def _on_tab_changed(self, _idx: int) -> None:
        pass

    def _open_add_dialog(self) -> None:
        dlg = AddCustomSFXDialog(self)
        if dlg.exec() == QDialog.Accepted:
            data = dlg.get_data()
            self.custom_sfx_added.emit(data)
