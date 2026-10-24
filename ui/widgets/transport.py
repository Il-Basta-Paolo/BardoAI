"""
Barra di controllo della riproduzione musicale (Transport Bar) in PySide6.
Include controlli per play/pause, cambio traccia, volume musica e SFX,
blocco scena e indicatore cooldown.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class TransportBar(QFrame):
    play_pause_clicked = Signal()
    skip_clicked = Signal()
    music_volume_changed = Signal(int)
    sfx_volume_changed = Signal(int)
    lock_toggled = Signal(bool)

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setFixedHeight(82)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(16, 10, 16, 10)
        main_layout.setSpacing(16)

        # 1. Info Brano in Riproduzione (Sinistra)
        track_info_box = QVBoxLayout()
        track_info_box.setSpacing(2)

        self.track_title_label = QLabel("Nessun brano in riproduzione")
        self.track_title_label.setStyleSheet("font-weight: 600; font-size: 14px; color: #f8fafc;")
        self.track_title_label.setMaximumWidth(280)

        self.track_artist_label = QLabel("In attesa della scena...")
        self.track_artist_label.setStyleSheet("font-size: 12px; color: #94a3b8;")

        track_info_box.addWidget(self.track_title_label)
        track_info_box.addWidget(self.track_artist_label)
        main_layout.addLayout(track_info_box)

        # Separatore verticale
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.VLine)
        sep1.setStyleSheet("color: #1e293b;")
        main_layout.addWidget(sep1)

        # 2. Pulsanti Trasporto (Centro-Sinistra)
        ctrl_layout = QHBoxLayout()
        ctrl_layout.setSpacing(8)

        self.btn_play_pause = QPushButton("⏸")
        self.btn_play_pause.setToolTip("Riproduci / Pausa (Ctrl+Spazio)")
        self.btn_play_pause.setFixedSize(40, 40)
        self.btn_play_pause.setStyleSheet("font-size: 16px; border-radius: 20px; background-color: #3b82f6;")
        self.btn_play_pause.clicked.connect(self.play_pause_clicked.emit)

        self.btn_skip = QPushButton("⏭")
        self.btn_skip.setToolTip("Passa alla traccia successiva (Ctrl+Destra)")
        self.btn_skip.setFixedSize(36, 36)
        self.btn_skip.setStyleSheet("font-size: 14px; border-radius: 18px;")
        self.btn_skip.clicked.connect(self.skip_clicked.emit)

        ctrl_layout.addWidget(self.btn_play_pause)
        ctrl_layout.addWidget(self.btn_skip)
        main_layout.addLayout(ctrl_layout)

        # 3. Slider Volume Musica (Centro)
        vol_music_box = QVBoxLayout()
        vol_music_box.setSpacing(2)
        lbl_music_hdr = QHBoxLayout()
        lbl_music_hdr.addWidget(QLabel("🎵 Musica"))
        self.lbl_music_pct = QLabel("75%")
        self.lbl_music_pct.setStyleSheet("color: #94a3b8; font-size: 11px;")
        lbl_music_hdr.addStretch()
        lbl_music_hdr.addWidget(self.lbl_music_pct)

        self.slider_music = QSlider(Qt.Horizontal)
        self.slider_music.setToolTip("Volume Musica (Ctrl+Su / Ctrl+Giù)")
        self.slider_music.setRange(0, 100)
        self.slider_music.setValue(75)
        self.slider_music.setFixedWidth(140)
        self.slider_music.valueChanged.connect(self._on_music_vol_changed)

        vol_music_box.addLayout(lbl_music_hdr)
        vol_music_box.addWidget(self.slider_music)
        main_layout.addLayout(vol_music_box)

        # 4. Slider Volume SFX (Centro-Destra)
        vol_sfx_box = QVBoxLayout()
        vol_sfx_box.setSpacing(2)
        lbl_sfx_hdr = QHBoxLayout()
        lbl_sfx_hdr.addWidget(QLabel("💥 SFX"))
        self.lbl_sfx_pct = QLabel("80%")
        self.lbl_sfx_pct.setStyleSheet("color: #94a3b8; font-size: 11px;")
        lbl_sfx_hdr.addStretch()
        lbl_sfx_hdr.addWidget(self.lbl_sfx_pct)

        self.slider_sfx = QSlider(Qt.Horizontal)
        self.slider_sfx.setRange(0, 100)
        self.slider_sfx.setValue(80)
        self.slider_sfx.setFixedWidth(140)
        self.slider_sfx.valueChanged.connect(self._on_sfx_vol_changed)

        vol_sfx_box.addLayout(lbl_sfx_hdr)
        vol_sfx_box.addWidget(self.slider_sfx)
        main_layout.addLayout(vol_sfx_box)

        # Separatore verticale
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.VLine)
        sep2.setStyleSheet("color: #1e293b;")
        main_layout.addWidget(sep2)

        # 5. Pulsante Lock Regia e Badge Cooldown (Destra)
        lock_box = QVBoxLayout()
        lock_box.setSpacing(4)

        self.btn_lock = QPushButton("🔓 Sbloccato")
        self.btn_lock.setObjectName("lockBtn")
        self.btn_lock.setCheckable(True)
        self.btn_lock.setChecked(False)
        self.btn_lock.toggled.connect(self._on_lock_toggled)

        self.lbl_cooldown = QLabel("🟢 Pronto")
        self.lbl_cooldown.setAlignment(Qt.AlignCenter)
        self.lbl_cooldown.setStyleSheet("font-size: 11px; color: #10b981; font-weight: 600;")

        lock_box.addWidget(self.btn_lock)
        lock_box.addWidget(self.lbl_cooldown)
        main_layout.addLayout(lock_box)

    def _on_music_vol_changed(self, val: int) -> None:
        self.lbl_music_pct.setText(f"{val}%")
        self.music_volume_changed.emit(val)

    def _on_sfx_vol_changed(self, val: int) -> None:
        self.lbl_sfx_pct.setText(f"{val}%")
        self.sfx_volume_changed.emit(val)

    def _on_lock_toggled(self, checked: bool) -> None:
        if checked:
            self.btn_lock.setText("🔒 Bloccato")
            self.btn_lock.setStyleSheet("background-color: #ea580c; color: white; font-weight: bold;")
        else:
            self.btn_lock.setText("🔓 Sbloccato")
            self.btn_lock.setStyleSheet("")
        self.lock_toggled.emit(checked)

    def update_track(self, title: str, artist: str = "") -> None:
        self.track_title_label.setText(title or "Traccia audio")
        self.track_artist_label.setText(artist or "Bardo AI")

    def set_playing_state(self, is_playing: bool) -> None:
        self.btn_play_pause.setText("⏸" if is_playing else "▶")

    def update_cooldown(self, remaining_sec: float) -> None:
        if remaining_sec <= 0.2:
            self.lbl_cooldown.setText("🟢 Pronto")
            self.lbl_cooldown.setStyleSheet("font-size: 11px; color: #10b981; font-weight: 600;")
        else:
            self.lbl_cooldown.setText(f"⏳ {remaining_sec:.0f}s")
            self.lbl_cooldown.setStyleSheet("font-size: 11px; color: #f59e0b; font-weight: 600;")

    def step_music_volume(self, delta: int) -> int:
        """Modifica il volume della musica di delta punti percentuali con clamping [0, 100]."""
        new_val = max(0, min(100, self.slider_music.value() + delta))
        self.slider_music.setValue(new_val)
        return new_val
