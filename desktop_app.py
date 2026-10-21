"""
Bardo AI — Applicazione Desktop Nativa Windows (.exe)
Supporto vocale in italiano per Giochi di Ruolo con:
- Streaming e Crossfade automatico da YouTube Music per le atmosfere di sottofondo
- Libreria interna di 20 Effetti Sonori (SFX) masterizzati ad alta chiarezza, attivabili con la voce o dalla Soundboard
- Architettura UI Zero-Flicker: contenitori a geometria bloccata (pack_propagate/grid_propagate False), zero ricalcoli di layout al cambio traccia e coda eventi thread-safe.
"""

import asyncio
import copy
import io
import queue
import random
import shutil
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable

import customtkinter as ctk
from tkinter import messagebox, filedialog
from PIL import Image, ImageDraw

from storage import load_config, save_config, reset_default_profiles
from ytmusic_service import YTMusicService
from analyzer import HybridAnalyzer
from desktop_audio_player import DesktopAudioPlayer
from voice_listener import ContinuousVoiceListener
from sfx_manager import SFXManager

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("green")


def _make_placeholder_cover(size: int = 80) -> ctk.CTkImage:
    """Crea un'immagine placeholder 80x80 fissa per evitare cambi di geometria tra testo e immagine."""
    img = Image.new("RGB", (size, size), color=(30, 41, 59))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([2, 2, size - 3, size - 3], radius=8, outline=(51, 65, 85), width=2)
    # Disegna una nota musicale stilizzata al centro
    cx, cy = size // 2, size // 2
    draw.ellipse([cx - 12, cy + 2, cx - 2, cy + 12], fill=(16, 185, 129))
    draw.ellipse([cx + 4, cy - 2, cx + 14, cy + 8], fill=(16, 185, 129))
    draw.line([cx - 3, cy + 6, cx - 3, cy - 14], fill=(16, 185, 129), width=3)
    draw.line([cx + 13, cy + 2, cx + 13, cy - 18], fill=(16, 185, 129), width=3)
    draw.line([cx - 3, cy - 14, cx + 13, cy - 18], fill=(16, 185, 129), width=4)
    return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))


class BardoDesktopApp(ctk.CTk):
    QUEUE_SLOTS = 8

    def __init__(self) -> None:
        super().__init__()

        self.title("🪕 Bardo AI — Regia Musicale & Soundboard Vocale per GdR (Spotify • YouTube Music • SFX)")
        self.geometry("1400x900")
        self.minsize(1180, 820)
        self.configure(fg_color="#0b0e14")
        try:
            ico_candidates = [
                Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "bardo_icon.ico",
                Path(sys.executable).resolve().parent / "bardo_icon.ico",
                Path(__file__).resolve().parent / "bardo_icon.ico",
            ]
            for ico in ico_candidates:
                if ico.exists():
                    self.iconbitmap(str(ico))
                    break
        except Exception:
            pass

        # Coda thread-safe per aggiornamenti UI da thread secondari (Zero contesa Tcl/Tk)
        self._ui_queue: "queue.SimpleQueue[Callable[[], None]]" = queue.SimpleQueue()

        # Stato applicazione
        self.cfg: Dict[str, Any] = load_config()
        self.active_profile_id: str = self.cfg.get("active_profile_id", "fantasy_dnd")
        self.current_mood_id: Optional[str] = None
        self.current_env_id: Optional[str] = None
        self._rendered_mood_id: Optional[str] = None
        self.is_mood_locked: bool = False
        self.cooldown_until: float = 0.0
        self.selected_sfx_category: str = "Tutti"

        # Cache testi UI per evitare .configure() ridondanti
        self._last_cur_time_str = "0:00"
        self._last_dur_time_str = "0:00"
        self._last_cooldown_str = ""
        self._last_status_str = "Pronto"
        self._last_play_btn_str = "▶️"

        # Servizi backend integrati nell'eseguibile
        self.ytm_service = YTMusicService()
        self.analyzer = HybridAnalyzer()
        self.player = DesktopAudioPlayer(
            ytm_service=self.ytm_service,
            on_track_change=self._on_player_track_change,
            on_state_change=self._on_player_state_change,
            on_error=self._on_player_error,
        )
        self.player.master_volume = int(self.cfg.get("audio", {}).get("master_volume", 75))
        self.player.crossfade_seconds = float(self.cfg.get("audio", {}).get("crossfade_seconds", 3.5))

        # Gestore Effetti Sonori (SFX) con Audio Ducking automatico sulla musica
        self.sfx_manager = SFXManager(
            on_sfx_triggered=self._on_sfx_triggered,
            on_duck_music=self.player.duck_for_sfx,
        )
        sfx_cfg = self.cfg.setdefault("sfx", {})
        self.sfx_manager.set_volume(int(sfx_cfg.get("volume", 75)))
        self.sfx_manager.voice_sfx_enabled = bool(sfx_cfg.get("voice_enabled", True))
        self.sfx_manager.duck_music_enabled = bool(sfx_cfg.get("duck_music", True))
        self._save_cfg_after_id: Optional[str] = None
        self._syncing_sfx_slider: bool = False

        # Ascolto vocale continuo
        self.voice_listener = ContinuousVoiceListener(
            on_transcript=self._on_voice_transcript,
            on_status=self._on_voice_status,
            on_level=self._on_voice_level,
        )
        self.mic_devices = ContinuousVoiceListener.get_input_devices()

        self._placeholder_cover = _make_placeholder_cover(80)
        self._current_cover_img = self._placeholder_cover

        # Costruzione interfaccia a geometria bloccata
        self._build_topbar()
        self._build_main_layout()
        self._sync_ui_from_config()

        # Loop UI ad alta reattività (80ms)
        self.after(80, self._ui_tick)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _post_ui(self, fn: Callable[[], None]) -> None:
        """Accoda una funzione da eseguire nel thread principale Tkinter in modo 100% thread-safe."""
        self._ui_queue.put(fn)

    # =========================================================================
    # COSTRUZIONE INTERFACCIA GRAFICA (GEOMETRIA BLOCCATA = ZERO FLICKER)
    # =========================================================================

    def _build_topbar(self) -> None:
        self.topbar = ctk.CTkFrame(self, fg_color="#131822", corner_radius=0, height=58)
        self.topbar.pack(fill="x", side="top", padx=0, pady=0)
        self.topbar.pack_propagate(False)

        brand_frame = ctk.CTkFrame(self.topbar, fg_color="transparent")
        brand_frame.pack(side="left", padx=18, pady=8)

        ctk.CTkLabel(
            brand_frame,
            text="🪕 Bardo AI",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#f1f5f9",
        ).pack(side="left", padx=(0, 8))

        ctk.CTkLabel(
            brand_frame,
            text="YT Music + SFX",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#4c0519",
            text_color="#fda4af",
            corner_radius=8,
            padx=8,
            pady=2,
        ).pack(side="left")

        prof_frame = ctk.CTkFrame(self.topbar, fg_color="transparent")
        prof_frame.pack(side="left", padx=20, pady=8)

        ctk.CTkLabel(
            prof_frame,
            text="Ambientazione:",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#94a3b8",
        ).pack(side="left", padx=(0, 8))

        self.profile_combo = ctk.CTkOptionMenu(
            prof_frame,
            width=220,
            fg_color="#1e293b",
            button_color="#334155",
            command=self._on_profile_selected,
        )
        self.profile_combo.pack(side="left", padx=4)

        ctk.CTkButton(
            prof_frame,
            text="➕ Profilo",
            width=84,
            height=30,
            fg_color="#1e293b",
            hover_color="#334155",
            command=self._open_new_profile_dialog,
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            prof_frame,
            text="🗑️",
            width=36,
            height=30,
            fg_color="#1e293b",
            hover_color="#7f1d1d",
            command=self._delete_current_profile,
        ).pack(side="left", padx=2)

        actions_frame = ctk.CTkFrame(self.topbar, fg_color="transparent")
        actions_frame.pack(side="right", padx=18, pady=8)

        self.btn_spotify_top = ctk.CTkButton(
            actions_frame,
            text="🟢 Login Spotify & Playlist",
            fg_color="#15803d",
            hover_color="#16a34a",
            height=34,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._open_ytm_dialog(default_tab="🟢 Spotify"),
        )
        self.btn_spotify_top.pack(side="left", padx=5)

        self.btn_ytm_top = ctk.CTkButton(
            actions_frame,
            text="🔴 Account YT Music",
            fg_color="#881337",
            hover_color="#9f1239",
            height=34,
            command=lambda: self._open_ytm_dialog(default_tab="🔴 YouTube Music"),
        )
        self.btn_ytm_top.pack(side="left", padx=5)

        ctk.CTkButton(
            actions_frame,
            text="🧠 Impostazioni Voce & AI",
            fg_color="#1e293b",
            hover_color="#334155",
            height=34,
            command=self._open_ai_settings_dialog,
        ).pack(side="left", padx=6)

    def _build_main_layout(self) -> None:
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True, padx=14, pady=10)
        self.main_container.grid_columnconfigure(0, weight=1)
        self.main_container.grid_columnconfigure(1, weight=0, minsize=405)
        self.main_container.grid_rowconfigure(0, weight=1)

        # COLONNA SINISTRA (VOCE + ATMOSFERE + SOUNDBOARD SFX)
        self.left_col = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.left_col.grid_propagate(False)
        self.left_col.pack_propagate(False)
        self.left_col.grid_rowconfigure(0, weight=0, minsize=178)  # Pannello Voce (altezza fissa)
        self.left_col.grid_rowconfigure(1, weight=11)              # Atmosfere Musicali (griglia 3x3)
        self.left_col.grid_rowconfigure(2, weight=10)              # Soundboard 20 SFX (griglia 4x5)
        self.left_col.grid_columnconfigure(0, weight=1)

        self._build_voice_panel()
        self._build_moods_panel()
        self._build_sfx_soundboard_panel()

        # COLONNA DESTRA (PLAYER YOUTUBE MUSIC CON CROSSFADE - LARGHEZZA FISSA BLOCCATA)
        self.right_col = ctk.CTkFrame(
            self.main_container, fg_color="#131822", corner_radius=12, width=405
        )
        self.right_col.grid(row=0, column=1, sticky="nsew")
        # IMPORTANTE: blocca SIA grid_propagate SIA pack_propagate così nessun testo può mai allargare right_col!
        self.right_col.grid_propagate(False)
        self.right_col.pack_propagate(False)
        self._build_player_panel()

    def _build_voice_panel(self) -> None:
        voice_card = ctk.CTkFrame(self.left_col, fg_color="#131822", corner_radius=12, height=172)
        voice_card.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
        voice_card.pack_propagate(False)
        voice_card.grid_propagate(False)

        top_row = ctk.CTkFrame(voice_card, fg_color="transparent", height=38)
        top_row.pack(fill="x", padx=12, pady=(8, 3))
        top_row.pack_propagate(False)

        self.btn_mic = ctk.CTkButton(
            top_row,
            text="🎙️ Avvia Ascolto Vocale (IT)",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#059669",
            hover_color="#10b981",
            height=32,
            width=205,
            corner_radius=16,
            command=self._toggle_microphone,
        )
        self.btn_mic.pack(side="left", padx=(0, 6))

        self.btn_lock = ctk.CTkButton(
            top_row,
            text="🔓 Cambio Musica Auto",
            fg_color="#1e293b",
            hover_color="#334155",
            height=30,
            width=148,
            command=self._toggle_mood_lock,
        )
        self.btn_lock.pack(side="left", padx=3)

        self.btn_voice_sfx = ctk.CTkButton(
            top_row,
            text="⚔️ SFX Vocali: ON" if self.sfx_manager.voice_sfx_enabled else "🔇 SFX Vocali: OFF",
            fg_color="#065f46" if self.sfx_manager.voice_sfx_enabled else "#1e293b",
            hover_color="#047857",
            height=30,
            width=132,
            command=self._toggle_voice_sfx,
        )
        self.btn_voice_sfx.pack(side="left", padx=3)

        mic_names = [d["name"] for d in self.mic_devices]
        self.mic_combo = ctk.CTkOptionMenu(
            top_row,
            values=mic_names,
            width=185,
            height=30,
            fg_color="#1e293b",
            button_color="#334155",
            command=self._on_mic_device_changed,
        )
        self.mic_combo.pack(side="left", padx=4)

        self.lbl_cooldown = ctk.CTkLabel(
            top_row,
            text="",
            width=110,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#fbbf24",
        )
        self.lbl_cooldown.pack(side="right", padx=4)

        self.lbl_mode_badge = ctk.CTkLabel(
            top_row,
            text="Modalità: Ibrida",
            font=ctk.CTkFont(size=11),
            fg_color="#1e293b",
            corner_radius=8,
            padx=8,
            pady=2,
        )
        self.lbl_mode_badge.pack(side="right", padx=4)

        lvl_row = ctk.CTkFrame(voice_card, fg_color="transparent", height=20)
        lvl_row.pack(fill="x", padx=12, pady=(0, 2))
        lvl_row.pack_propagate(False)

        ctk.CTkLabel(
            lvl_row,
            text="Livello Voce:",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8",
        ).pack(side="left", padx=(0, 6))

        self.mic_level_bar = ctk.CTkProgressBar(
            lvl_row, width=130, height=8, progress_color="#10b981"
        )
        self.mic_level_bar.set(0.0)
        self.mic_level_bar.pack(side="left", padx=(0, 10))

        self.lbl_mic_status = ctk.CTkLabel(
            lvl_row,
            text="Microfono in pausa — clicca 'Avvia Ascolto Vocale' o usa le prove rapide",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8",
            anchor="w",
        )
        self.lbl_mic_status.pack(side="left", fill="x", expand=True)

        transcript_box = ctk.CTkFrame(voice_card, fg_color="#0b0e14", corner_radius=8, height=46)
        transcript_box.pack(fill="x", padx=12, pady=2)
        transcript_box.pack_propagate(False)

        self.lbl_live_transcript = ctk.CTkLabel(
            transcript_box,
            text="« Parla al microfono... es: 'Ti colpisce con la sua spada!' o 'Entrate nella locanda' »",
            width=760,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#f1f5f9",
            anchor="w",
        )
        self.lbl_live_transcript.pack(fill="x", padx=10, pady=(4, 0))

        status_sub_row = ctk.CTkFrame(transcript_box, fg_color="transparent", height=18)
        status_sub_row.pack(fill="x", padx=10, pady=(0, 2))
        status_sub_row.pack_propagate(False)

        self.lbl_last_trigger = ctk.CTkLabel(
            status_sub_row,
            text="Scena: nessuna",
            width=330,
            height=18,
            font=ctk.CTkFont(size=11),
            text_color="#10b981",
            anchor="w",
        )
        self.lbl_last_trigger.pack(side="left", padx=(0, 12))

        self.lbl_last_sfx = ctk.CTkLabel(
            status_sub_row,
            text="Ultimo Effetto SFX: nessuno",
            width=420,
            height=18,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#f59e0b",
            anchor="w",
        )
        self.lbl_last_sfx.pack(side="left")

        bottom_voice = ctk.CTkFrame(voice_card, fg_color="transparent", height=32)
        bottom_voice.pack(fill="x", padx=12, pady=(3, 6))
        bottom_voice.pack_propagate(False)

        self.entry_simulate = ctk.CTkEntry(
            bottom_voice,
            placeholder_text="Prova frase (es. 'L'orco ringhia e ti colpisce con la sua spada!')...",
            height=28,
        )
        self.entry_simulate.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.entry_simulate.bind("<Return>", lambda _e: self._on_simulate_submit())

        ctk.CTkButton(
            bottom_voice,
            text="Analizza",
            width=80,
            height=28,
            command=self._on_simulate_submit,
        ).pack(side="left", padx=(0, 8))

        sample_phrases = [
            ("⚔️ Spada", "Ti colpisce con la sua spada!"),
            ("🐾 Artigli", "Il mostro ringhia e ti tira un'artigliata!"),
            ("🐉 Drago", "Il drago ruggisce e lancia una palla di fuoco!"),
            ("🍺 Brindisi", "Entrate nella locanda e facciamo un brindisi!"),
            ("🎲 Dadi", "Tirate i dadi per iniziativa!"),
        ]
        for label, phrase in sample_phrases:
            ctk.CTkButton(
                bottom_voice,
                text=label,
                height=26,
                width=78,
                font=ctk.CTkFont(size=11),
                fg_color="#1e293b",
                hover_color="#334155",
                command=lambda p=phrase: self._run_quick_phrase(p),
            ).pack(side="left", padx=2)

    def _build_moods_panel(self) -> None:
        moods_card = ctk.CTkFrame(self.left_col, fg_color="#131822", corner_radius=12)
        moods_card.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        moods_card.grid_propagate(False)
        moods_card.pack_propagate(False)
        moods_card.grid_rowconfigure(0, weight=0, minsize=38)
        moods_card.grid_rowconfigure(1, weight=1)
        moods_card.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(moods_card, fg_color="transparent", height=34)
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=(6, 2))
        header.pack_propagate(False)

        self.lbl_profile_title = ctk.CTkLabel(
            header,
            text="🐉 Atmosfere Musicali (YouTube Music)",
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        self.lbl_profile_title.pack(side="left")

        ctk.CTkButton(
            header,
            text="➕ Nuova Atmosfera",
            height=26,
            width=130,
            font=ctk.CTkFont(size=11),
            command=lambda: self._open_edit_mood_dialog(None),
        ).pack(side="right")

        # Griglia statica (NON CTkScrollableFrame!) -> Zero ricalcoli Canvas/Scrollregion!
        self.moods_grid = ctk.CTkFrame(moods_card, fg_color="transparent")
        self.moods_grid.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.moods_grid.grid_propagate(False)
        for col in range(3):
            self.moods_grid.grid_columnconfigure(col, weight=1, uniform="mood_col")
        for row in range(3):
            self.moods_grid.grid_rowconfigure(row, weight=1, uniform="mood_row")

    def _build_sfx_soundboard_panel(self) -> None:
        """
        Costruisce la Soundboard integrata a 20 pulsanti visibili tutti insieme (griglia 4x5 statica)
        con parole chiave vocali chiaramente indicate su ogni pulsante e Audio Ducking automatico.
        """
        sfx_card = ctk.CTkFrame(self.left_col, fg_color="#131822", corner_radius=12)
        sfx_card.grid(row=2, column=0, sticky="nsew")
        sfx_card.grid_propagate(False)
        sfx_card.pack_propagate(False)
        sfx_card.grid_rowconfigure(0, weight=0, minsize=38)
        sfx_card.grid_rowconfigure(1, weight=1)
        sfx_card.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(sfx_card, fg_color="transparent", height=34)
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=(6, 2))
        header.pack_propagate(False)

        ctk.CTkLabel(
            header,
            text="🔊 Soundboard Effetti Sonori (Clicca o pronuncia le parole sotto ciascun effetto)",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#f59e0b",
        ).pack(side="left", padx=(0, 10))

        self.cat_buttons: Dict[str, ctk.CTkButton] = {}
        for cat in ["Tutti", "Armi", "Creature", "Magia", "Ambiente"]:
            b_cat = ctk.CTkButton(
                header,
                text=cat,
                width=58,
                height=24,
                font=ctk.CTkFont(size=11),
                fg_color="#059669" if self.selected_sfx_category == cat else "#1e293b",
                hover_color="#475569",
                command=lambda c=cat: self._filter_sfx_category(c),
            )
            b_cat.pack(side="left", padx=2)
            self.cat_buttons[cat] = b_cat

        ctk.CTkButton(
            header,
            text="➕ Suono",
            height=24,
            width=74,
            font=ctk.CTkFont(size=11),
            fg_color="#1e293b",
            hover_color="#334155",
            command=self._open_add_custom_sfx_dialog,
        ).pack(side="right", padx=(6, 0))

        self.btn_duck = ctk.CTkButton(
            header,
            text="🔉 Ducking: ON" if self.sfx_manager.duck_music_enabled else "🔉 Ducking: OFF",
            height=24,
            width=96,
            font=ctk.CTkFont(size=11),
            fg_color="#065f46" if self.sfx_manager.duck_music_enabled else "#1e293b",
            hover_color="#047857",
            command=self._toggle_duck_music,
        )
        self.btn_duck.pack(side="right", padx=4)

        self.sfx_vol_slider = ctk.CTkSlider(
            header,
            from_=0,
            to=100,
            width=110,
            command=self._on_sfx_volume_changed,
        )
        self.sfx_vol_slider.set(self.sfx_manager.sfx_volume)
        self.sfx_vol_slider.pack(side="right", padx=4)

        self.lbl_sfx_vol = ctk.CTkLabel(
            header,
            text=f"💥 Vol Effetti: {self.sfx_manager.sfx_volume}%",
            width=115,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#fbbf24",
        )
        self.lbl_sfx_vol.pack(side="right", padx=2)

        # Griglia statica 4x5 (tutti i 20 effetti visibili subito senza scrollbar né flicker!)
        self.sfx_grid = ctk.CTkFrame(sfx_card, fg_color="transparent")
        self.sfx_grid.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.sfx_grid.grid_propagate(False)
        for col in range(5):
            self.sfx_grid.grid_columnconfigure(col, weight=1, uniform="sfx_col")
        for row in range(4):
            self.sfx_grid.grid_rowconfigure(row, weight=1, uniform="sfx_row")

    def _build_player_panel(self) -> None:
        # 1. Intestazione Player (altezza fissa 34px)
        top_p = ctk.CTkFrame(self.right_col, fg_color="transparent", height=34)
        top_p.pack(fill="x", padx=14, pady=(12, 4))
        top_p.pack_propagate(False)

        self.lbl_active_mood_badge = ctk.CTkLabel(
            top_p,
            text="Nessuna atmosfera",
            width=175,
            height=26,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#1e293b",
            corner_radius=8,
            padx=8,
            pady=2,
            anchor="w",
        )
        self.lbl_active_mood_badge.pack(side="left")

        self.lbl_player_status = ctk.CTkLabel(
            top_p,
            text="Pronto",
            width=190,
            height=26,
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8",
            anchor="e",
        )
        self.lbl_player_status.pack(side="right")

        # 2. Box Copertina + Titolo Traccia (altezza fissa 102px)
        showcase = ctk.CTkFrame(self.right_col, fg_color="#0b0e14", corner_radius=10, height=102)
        showcase.pack(fill="x", padx=14, pady=4)
        showcase.pack_propagate(False)

        self.lbl_cover = ctk.CTkLabel(
            showcase,
            text="",
            image=self._placeholder_cover,
            width=80,
            height=80,
            fg_color="#1e293b",
            corner_radius=8,
        )
        self.lbl_cover.pack(side="left", padx=10, pady=10)

        meta_frame = ctk.CTkFrame(showcase, fg_color="transparent")
        meta_frame.pack(side="left", fill="both", expand=True, padx=(0, 10), pady=8)
        meta_frame.pack_propagate(False)

        self.lbl_track_title = ctk.CTkLabel(
            meta_frame,
            text="Pronto a suonare",
            width=260,
            height=20,
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
            justify="left",
        )
        self.lbl_track_title.pack(fill="x")

        self.lbl_track_artist = ctk.CTkLabel(
            meta_frame,
            text="Scegli un'atmosfera o parla al microfono",
            width=260,
            height=18,
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8",
            anchor="w",
        )
        self.lbl_track_artist.pack(fill="x", pady=(2, 6))

        links_row = ctk.CTkFrame(meta_frame, fg_color="transparent", height=26)
        links_row.pack(fill="x")
        links_row.pack_propagate(False)

        ctk.CTkButton(
            links_row,
            text="📌 Fissa brano",
            width=96,
            height=24,
            font=ctk.CTkFont(size=11),
            fg_color="#1e293b",
            hover_color="#334155",
            command=self._pin_current_track,
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            links_row,
            text="↗ YT Music",
            width=84,
            height=24,
            font=ctk.CTkFont(size=11),
            fg_color="#4c0519",
            hover_color="#881337",
            command=self._open_current_in_browser,
        ).pack(side="left")

        # 3. Controlli trasporto (altezza fissa 42px)
        ctrl_row = ctk.CTkFrame(self.right_col, fg_color="transparent", height=42)
        ctrl_row.pack(fill="x", padx=14, pady=4)
        ctrl_row.pack_propagate(False)

        btn_inner = ctk.CTkFrame(ctrl_row, fg_color="transparent")
        btn_inner.pack(anchor="center")

        ctk.CTkButton(
            btn_inner, text="⏮️", width=44, height=34, fg_color="#1e293b", command=self.player.prev_track
        ).pack(side="left", padx=5)

        self.btn_play_pause = ctk.CTkButton(
            btn_inner,
            text="▶️",
            width=58,
            height=36,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self._on_play_pause_clicked,
        )
        self.btn_play_pause.pack(side="left", padx=5)

        ctk.CTkButton(
            btn_inner, text="⏭️", width=44, height=34, fg_color="#1e293b", command=self.player.next_track
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            btn_inner, text="🔀", width=44, height=34, fg_color="#1e293b", command=self._shuffle_queue
        ).pack(side="left", padx=5)

        # 4. Barra avanzamento (altezza fissa 26px + larghezze tempo fisse)
        prog_row = ctk.CTkFrame(self.right_col, fg_color="transparent", height=26)
        prog_row.pack(fill="x", padx=14, pady=2)
        prog_row.pack_propagate(False)

        self.lbl_cur_time = ctk.CTkLabel(
            prog_row, text="0:00", width=36, font=ctk.CTkFont(size=11), text_color="#94a3b8", anchor="w"
        )
        self.lbl_cur_time.pack(side="left", padx=(0, 4))

        self.seek_slider = ctk.CTkSlider(
            prog_row, from_=0.0, to=1.0, number_of_steps=100, command=self._on_seek_slider
        )
        self.seek_slider.set(0.0)
        self.seek_slider.pack(side="left", fill="x", expand=True)

        self.lbl_dur_time = ctk.CTkLabel(
            prog_row, text="0:00", width=36, font=ctk.CTkFont(size=11), text_color="#94a3b8", anchor="e"
        )
        self.lbl_dur_time.pack(side="left", padx=(4, 0))

        # 5. Slider Volume Musica, Volume Effetti (SFX) & Crossfade (altezza fissa 100px)
        sliders_card = ctk.CTkFrame(self.right_col, fg_color="#0b0e14", corner_radius=8, height=100)
        sliders_card.pack(fill="x", padx=14, pady=4)
        sliders_card.pack_propagate(False)

        v_row = ctk.CTkFrame(sliders_card, fg_color="transparent", height=28)
        v_row.pack(fill="x", padx=10, pady=(5, 1))
        v_row.pack_propagate(False)
        self.lbl_vol = ctk.CTkLabel(
            v_row, text=f"🔊 Vol Musica: {self.player.master_volume}%", width=155, font=ctk.CTkFont(size=12), anchor="w"
        )
        self.lbl_vol.pack(side="left")
        self.vol_slider = ctk.CTkSlider(
            v_row, from_=0, to=100, width=180, command=self._on_volume_changed
        )
        self.vol_slider.set(self.player.master_volume)
        self.vol_slider.pack(side="right")

        sfx_v_row = ctk.CTkFrame(sliders_card, fg_color="transparent", height=28)
        sfx_v_row.pack(fill="x", padx=10, pady=1)
        sfx_v_row.pack_propagate(False)
        self.lbl_sfx_vol_right = ctk.CTkLabel(
            sfx_v_row,
            text=f"💥 Vol Effetti: {self.sfx_manager.sfx_volume}%",
            width=155,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#fbbf24",
            anchor="w",
        )
        self.lbl_sfx_vol_right.pack(side="left")
        self.sfx_vol_slider_right = ctk.CTkSlider(
            sfx_v_row, from_=0, to=100, width=180, command=self._on_sfx_volume_changed
        )
        self.sfx_vol_slider_right.set(self.sfx_manager.sfx_volume)
        self.sfx_vol_slider_right.pack(side="right")

        cf_row = ctk.CTkFrame(sliders_card, fg_color="transparent", height=28)
        cf_row.pack(fill="x", padx=10, pady=(1, 5))
        cf_row.pack_propagate(False)
        self.lbl_cf = ctk.CTkLabel(
            cf_row, text=f"🌊 Crossfade: {self.player.crossfade_seconds:.1f}s", width=155, font=ctk.CTkFont(size=12), anchor="w"
        )
        self.lbl_cf.pack(side="left")
        self.cf_slider = ctk.CTkSlider(
            cf_row, from_=0.0, to=10.0, number_of_steps=20, width=180, command=self._on_crossfade_changed
        )
        self.cf_slider.set(self.player.crossfade_seconds)
        self.cf_slider.pack(side="right")

        # 6. Ricerca diretta su YouTube Music (altezza fissa 34px)
        search_row = ctk.CTkFrame(self.right_col, fg_color="transparent", height=34)
        search_row.pack(fill="x", padx=14, pady=4)
        search_row.pack_propagate(False)

        self.entry_ytm_search = ctk.CTkEntry(
            search_row, placeholder_text="🔍 Cerca un brano su YouTube Music...", height=30
        )
        self.entry_ytm_search.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.entry_ytm_search.bind("<Return>", lambda _e: self._on_direct_search())

        ctk.CTkButton(
            search_row, text="Cerca", width=68, height=30, command=self._on_direct_search
        ).pack(side="right")

        # 7. Coda di riproduzione statica (8 slot pre-allocati -> ZERO flicker al cambio brano!)
        q_head_frame = ctk.CTkFrame(self.right_col, fg_color="transparent", height=24)
        q_head_frame.pack(fill="x", padx=16, pady=(4, 2))
        q_head_frame.pack_propagate(False)

        self.lbl_queue_header = ctk.CTkLabel(
            q_head_frame,
            text="🎶 Coda di Riproduzione (0 brani)",
            width=340,
            height=22,
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        )
        self.lbl_queue_header.pack(side="left")

        self.queue_frame = ctk.CTkFrame(self.right_col, fg_color="#0b0e14", corner_radius=8)
        self.queue_frame.pack(fill="both", expand=True, padx=14, pady=(2, 12))
        self.queue_frame.pack_propagate(False)

        self.queue_slots: List[Dict[str, Any]] = []
        for slot_idx in range(self.QUEUE_SLOTS):
            row_f = ctk.CTkFrame(self.queue_frame, fg_color="transparent", height=38)
            row_f.pack(fill="x", padx=4, pady=2)
            row_f.pack_propagate(False)

            btn = ctk.CTkButton(
                row_f,
                text="—",
                anchor="w",
                height=36,
                fg_color="#131822",
                hover_color="#1e293b",
                text_color="#64748b",
                font=ctk.CTkFont(size=11),
                state="disabled",
                command=lambda i=slot_idx: self._on_queue_slot_clicked(i),
            )
            btn.pack(fill="both", expand=True)
            self.queue_slots.append({
                "btn": btn,
                "track_idx": -1,
                "text": "—",
                "fg": "#131822",
                "state": "disabled",
            })

    # =========================================================================
    # SINCRONIZZAZIONE STATO -> UI (AGGIORNAMENTI DIFFERENZIALI ZERO-FLICKER)
    # =========================================================================

    def _get_active_profile(self) -> Dict[str, Any]:
        profiles = self.cfg.get("profiles", {})
        return profiles.get(self.active_profile_id) or next(iter(profiles.values()))

    def _get_sfx_library(self) -> Dict[str, Dict[str, Any]]:
        custom_sfx = self.cfg.get("sfx", {}).get("custom_items", {})
        return self.sfx_manager.get_library(custom_sfx)

    def _sync_ui_from_config(self) -> None:
        profiles = self.cfg.get("profiles", {})
        self.profile_map: Dict[str, str] = {}
        display_names: List[str] = []
        active_display = ""

        for pid, prof in profiles.items():
            disp = f"{prof.get('icon', '🎲')} {prof.get('name', pid)}"
            self.profile_map[disp] = pid
            display_names.append(disp)
            if pid == self.active_profile_id:
                active_display = disp

        self.profile_combo.configure(values=display_names)
        if active_display:
            self.profile_combo.set(active_display)

        mode = self.cfg.get("analyzer", {}).get("mode", "hybrid")
        mode_labels = {
            "hybrid": "Modalità: Ibrida (Parole + AI)",
            "keywords": "Modalità: Parole Chiave (IT)",
            "ai_always": "Modalità: Sempre AI",
        }
        self.lbl_mode_badge.configure(text=mode_labels.get(mode, "Modalità: Ibrida"))

        self._render_moods_grid()
        self._render_sfx_grid()

    def _render_moods_grid(self) -> None:
        for widget in self.moods_grid.winfo_children():
            widget.destroy()

        prof = self._get_active_profile()
        self.lbl_profile_title.configure(
            text=f"{prof.get('icon', '🐉')} Atmosfere Musicali — {prof.get('name', '')}"
        )

        self.mood_widgets: Dict[str, Dict[str, Any]] = {}
        moods = list(prof.get("moods", {}).items())[:9]
        for idx, (mood_id, mood) in enumerate(moods):
            r = idx // 3
            c = idx % 3
            is_active = mood_id == self.current_mood_id
            color = mood.get("color", "#10b981")

            # NOTA: border_width resta SEMPRE 2 così non c'è mai ridisegno geometrico del Canvas!
            card = ctk.CTkFrame(
                self.moods_grid,
                fg_color="#1a2232" if is_active else "#0b0e14",
                border_width=2,
                border_color=color if is_active else "#1e293b",
                corner_radius=10,
            )
            card.grid(row=r, column=c, sticky="nsew", padx=4, pady=4)
            card.pack_propagate(False)

            top = ctk.CTkFrame(card, fg_color="transparent", height=26)
            top.pack(fill="x", padx=8, pady=(6, 1))
            top.pack_propagate(False)

            lbl_title = ctk.CTkLabel(
                top,
                text=f"{mood.get('icon', '🎵')} {mood.get('name', mood_id)}",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=color if is_active else "#f1f5f9",
                anchor="w",
            )
            lbl_title.pack(side="left")

            ctk.CTkButton(
                top,
                text="⚙️",
                width=24,
                height=22,
                fg_color="transparent",
                hover_color="#334155",
                command=lambda mid=mood_id: self._open_edit_mood_dialog(mid),
            ).pack(side="right")

            sample_kw = (mood.get("phrases", [])[:1] + mood.get("keywords", [])[:2])[:2]
            kw_str = ", ".join(f'"{k}"' for k in sample_kw)
            has_pl = bool((mood.get("custom_playlist") or "").strip())
            extra_info = []
            if has_pl:
                extra_info.append("🎵 Playlist")
            if kw_str:
                extra_info.append(kw_str)
            sub_txt = (" • ".join(extra_info) if extra_info else mood.get("description", ""))[:42]

            ctk.CTkLabel(
                card,
                text=sub_txt,
                font=ctk.CTkFont(size=10),
                text_color="#94a3b8",
                anchor="w",
            ).pack(fill="x", padx=8, pady=(0, 3))

            btn_act = ctk.CTkButton(
                card,
                text="🔊 In Riproduzione" if is_active else "▶️ Avvia Atmosfera",
                height=24,
                font=ctk.CTkFont(size=11, weight="bold"),
                fg_color=color if is_active else "#1e293b",
                hover_color=color,
                command=lambda mid=mood_id: self._trigger_mood(mid, manual=True),
            )
            btn_act.pack(fill="x", side="bottom", padx=8, pady=(0, 6))

            self.mood_widgets[mood_id] = {
                "card": card,
                "title": lbl_title,
                "btn": btn_act,
                "color": color,
                "active": is_active,
            }
        self._rendered_mood_id = self.current_mood_id

    def _update_moods_active_state(self) -> None:
        """
        Aggiorna SOLO la card appena disattivata e quella appena attivata (al massimo 2 widget su 9),
        mantenendo `border_width=2` invariato per azzerare qualsiasi flicker!
        """
        if not hasattr(self, "mood_widgets") or not self.mood_widgets:
            self._render_moods_grid()
            return

        for mood_id, refs in self.mood_widgets.items():
            is_active = mood_id == self.current_mood_id
            if refs.get("active") == is_active:
                continue
            refs["active"] = is_active
            card = refs["card"]
            if not card.winfo_exists():
                continue
            color = refs["color"]
            card.configure(
                fg_color="#1a2232" if is_active else "#0b0e14",
                border_color=color if is_active else "#1e293b",
            )
            refs["title"].configure(text_color=color if is_active else "#f1f5f9")
            refs["btn"].configure(
                text="🔊 In Riproduzione" if is_active else "▶️ Avvia Atmosfera",
                fg_color=color if is_active else "#1e293b",
            )
        self._rendered_mood_id = self.current_mood_id

    def _render_sfx_grid(self) -> None:
        for widget in self.sfx_grid.winfo_children():
            widget.destroy()

        lib = self._get_sfx_library()
        filtered = [
            item
            for item in lib.values()
            if self.selected_sfx_category == "Tutti"
            or item.get("category") == self.selected_sfx_category
        ][:20]

        self.sfx_buttons: Dict[str, ctk.CTkButton] = {}
        for idx, item in enumerate(filtered):
            r = idx // 5
            c = idx % 5
            sfx_id = item["id"]
            color = item.get("color", "#f59e0b")
            hint = item.get("hint") or " • ".join((item.get("keywords") or [])[:3])

            cell = ctk.CTkFrame(
                self.sfx_grid,
                fg_color="#0b0e14",
                border_width=1,
                border_color="#252f42",
                corner_radius=8,
            )
            cell.grid(row=r, column=c, sticky="nsew", padx=3, pady=3)
            cell.pack_propagate(False)

            btn = ctk.CTkButton(
                cell,
                text=f"{item.get('icon', '🔊')} {item.get('name', sfx_id)}\n🗣️ {hint[:26]}",
                font=ctk.CTkFont(size=11, weight="bold"),
                fg_color="#172030",
                hover_color=color,
                corner_radius=7,
                command=lambda sid=sfx_id: self.sfx_manager.play_sfx(
                    sid, reason="Soundboard", library=self._get_sfx_library()
                ),
            )
            btn.pack(fill="both", expand=True, padx=2, pady=2)
            self.sfx_buttons[sfx_id] = btn

    def _filter_sfx_category(self, category: str) -> None:
        if self.selected_sfx_category == category:
            return
        self.selected_sfx_category = category
        for cat, b in getattr(self, "cat_buttons", {}).items():
            b.configure(fg_color="#059669" if cat == category else "#1e293b")
        self._render_sfx_grid()

    def _toggle_duck_music(self) -> None:
        self.sfx_manager.duck_music_enabled = not self.sfx_manager.duck_music_enabled
        en = self.sfx_manager.duck_music_enabled
        self.btn_duck.configure(
            text="🔉 Ducking: ON" if en else "🔉 Ducking: OFF",
            fg_color="#065f46" if en else "#1e293b",
        )
        self.cfg.setdefault("sfx", {})["duck_music"] = en
        save_config(self.cfg)

    def _on_sfx_triggered(self, item: Dict[str, Any], reason: str) -> None:
        def update_ui() -> None:
            sfx_id = item.get("id", "")
            self.lbl_last_sfx.configure(
                text=f"Ultimo SFX: {item.get('icon', '')} {item.get('name')} ({reason})"
            )
            btn = getattr(self, "sfx_buttons", {}).get(sfx_id)
            if btn and btn.winfo_exists():
                color = item.get("color", "#f59e0b")
                btn.configure(fg_color=color)
                self.after(
                    550,
                    lambda b=btn: b.configure(fg_color="#172030") if b.winfo_exists() else None,
                )

        self._post_ui(update_ui)

    def _schedule_save_config(self) -> None:
        """Salva la configurazione su disco con debounce (350ms) per non rallentare lo scorrimento degli slider."""
        if getattr(self, "_save_cfg_after_id", None):
            try:
                self.after_cancel(self._save_cfg_after_id)
            except Exception:
                pass
        self._save_cfg_after_id = self.after(350, lambda: save_config(self.cfg))

    def _on_sfx_volume_changed(self, val: float) -> None:
        if getattr(self, "_syncing_sfx_slider", False):
            return
        self._syncing_sfx_slider = True
        try:
            v = max(0, min(100, int(round(float(val)))))
            self.sfx_manager.set_volume(v)
            self.lbl_sfx_vol.configure(text=f"💥 Vol Effetti: {v}%")
            if hasattr(self, "lbl_sfx_vol_right"):
                self.lbl_sfx_vol_right.configure(text=f"💥 Vol Effetti: {v}%")
            if hasattr(self, "sfx_vol_slider") and int(round(self.sfx_vol_slider.get())) != v:
                self.sfx_vol_slider.set(v)
            if hasattr(self, "sfx_vol_slider_right") and int(round(self.sfx_vol_slider_right.get())) != v:
                self.sfx_vol_slider_right.set(v)
            self.cfg.setdefault("sfx", {})["volume"] = v
            self._schedule_save_config()
        finally:
            self._syncing_sfx_slider = False

    def _toggle_voice_sfx(self) -> None:
        self.sfx_manager.voice_sfx_enabled = not self.sfx_manager.voice_sfx_enabled
        enabled = self.sfx_manager.voice_sfx_enabled
        self.btn_voice_sfx.configure(
            text="⚔️ SFX Vocali: ON" if enabled else "🔇 SFX Vocali: OFF",
            fg_color="#065f46" if enabled else "#1e293b",
        )
        self.cfg.setdefault("sfx", {})["voice_enabled"] = enabled
        save_config(self.cfg)

    def _on_queue_slot_clicked(self, slot_idx: int) -> None:
        if 0 <= slot_idx < len(self.queue_slots):
            t_idx = self.queue_slots[slot_idx]["track_idx"]
            if 0 <= t_idx < len(self.player.queue):
                self.player.play_track_at(t_idx)

    def _render_queue(self) -> None:
        """
        Aggiorna gli 8 slot statici della coda solo dove il testo o il colore è effettivamente cambiato.
        Nessun widget viene mai creato, distrutto o rimappato -> ZERO FLICKER!
        """
        tracks = self.player.queue
        cur_idx = max(0, self.player.current_index)
        header_txt = f"🎶 Coda di Riproduzione ({len(tracks)} brani)"
        if self.lbl_queue_header.cget("text") != header_txt:
            self.lbl_queue_header.configure(text=header_txt)

        # Finestra scorrevole sugli 8 slot centrata sul brano corrente
        start_idx = 0
        if len(tracks) > self.QUEUE_SLOTS and cur_idx >= self.QUEUE_SLOTS - 2:
            start_idx = min(cur_idx - 2, len(tracks) - self.QUEUE_SLOTS)

        for slot_i, slot in enumerate(self.queue_slots):
            t_idx = start_idx + slot_i
            btn = slot["btn"]
            if t_idx < len(tracks):
                t = tracks[t_idx]
                is_cur = t_idx == self.player.current_index
                prefix = "▶ " if is_cur else f"{t_idx + 1}. "
                title = (t.get("title") or "Brano").replace("\n", " ")[:32]
                artist = (t.get("artist") or "YouTube Music").replace("\n", " ")[:22]
                new_text = f"{prefix}{title} — {artist}"
                new_fg = "#064e3b" if is_cur else "#131822"
                new_tc = "#ffffff" if is_cur else "#cbd5e1"
                new_state = "normal"
                slot["track_idx"] = t_idx
            else:
                new_text = "—"
                new_fg = "#131822"
                new_tc = "#475569"
                new_state = "disabled"
                slot["track_idx"] = -1

            if (
                slot["text"] != new_text
                or slot["fg"] != new_fg
                or slot["state"] != new_state
            ):
                slot["text"] = new_text
                slot["fg"] = new_fg
                slot["state"] = new_state
                btn.configure(
                    text=new_text,
                    fg_color=new_fg,
                    text_color=new_tc,
                    state=new_state,
                )

    def _update_queue_active_state(self) -> None:
        self._render_queue()

    # =========================================================================
    # LOGICA MICROFONO, ANALISI VOCALE (SFX + ATMOSFERE)
    # =========================================================================

    def _toggle_microphone(self) -> None:
        if self.voice_listener.is_listening:
            self.voice_listener.stop()
            self.btn_mic.configure(
                text="🎙️ Avvia Ascolto Vocale (IT)",
                fg_color="#059669",
                hover_color="#10b981",
            )
        else:
            self.voice_listener.start()
            self.btn_mic.configure(
                text="⏹️ Ascolto Attivo (Pausa)",
                fg_color="#dc2626",
                hover_color="#ef4444",
            )

    def _on_mic_device_changed(self, selected_name: str) -> None:
        for d in self.mic_devices:
            if d["name"] == selected_name:
                self.voice_listener.set_device(d["index"])
                break

    def _toggle_mood_lock(self) -> None:
        self.is_mood_locked = not self.is_mood_locked
        if self.is_mood_locked:
            self.btn_lock.configure(text="🔒 Musica Bloccata", fg_color="#78350f")
        else:
            self.btn_lock.configure(text="🔓 Cambio Musica Auto", fg_color="#1e293b")

    def _on_voice_level(self, level: float) -> None:
        self._post_ui(lambda: self.mic_level_bar.set(level))

    def _on_voice_status(self, status: str) -> None:
        self._post_ui(lambda: self.lbl_mic_status.configure(text=status[:85]))

    def _on_voice_transcript(self, text: str) -> None:
        self._post_ui(lambda: self._process_spoken_phrase(text, bypass_cooldown=False))

    def _on_simulate_submit(self) -> None:
        text = self.entry_simulate.get().strip()
        if not text:
            return
        self.entry_simulate.delete(0, "end")
        self._process_spoken_phrase(text, bypass_cooldown=True)

    def _run_quick_phrase(self, phrase: str) -> None:
        self._process_spoken_phrase(phrase, bypass_cooldown=True)

    def _process_spoken_phrase(self, text: str, bypass_cooldown: bool = False) -> None:
        clean_t = text.replace("\n", " ")[:95]
        self.lbl_live_transcript.configure(text=f"« {clean_t} »")

        # 1. Rilevamento e riproduzione ISTANTANEA degli Effetti Sonori (SFX) con Ducking automatico
        self.sfx_manager.detect_and_play_from_speech(text, library=self._get_sfx_library())

        # 2. Analisi dell'atmosfera musicale (Parole chiave + AI)
        def worker() -> None:
            prof = self._get_active_profile()
            analyzer_cfg = self.cfg.get("analyzer", {})
            res = asyncio.run(
                self.analyzer.analyze(
                    raw_text=text,
                    profile=prof,
                    analyzer_cfg=analyzer_cfg,
                    current_mood_id=self.current_mood_id,
                )
            )
            self._post_ui(lambda: self._handle_analysis_result(res, bypass_cooldown))

        threading.Thread(target=worker, daemon=True).start()

    def _handle_analysis_result(self, res: Dict[str, Any], bypass_cooldown: bool) -> None:
        voice_action = res.get("voice_action")
        if voice_action:
            self.lbl_last_trigger.configure(text=f"Comando: {res.get('reason', voice_action)[:40]}")
            if voice_action == "pause":
                self.player.pause()
            elif voice_action == "resume":
                self.player.resume()
            elif voice_action == "next":
                self.player.next_track()
            return

        mood_id = res.get("mood_id")
        env_id = res.get("env_id")
        env_name = res.get("env_name")
        terms = ", ".join(res.get("matched_terms") or [])
        matched_by = res.get("matched_by", "none")
        is_command = matched_by == "command"
        is_env_switch = bool(env_id and env_id != self.current_env_id)

        if not mood_id:
            return

        prof = self._get_active_profile()
        mood = prof.get("moods", {}).get(mood_id)
        if not mood:
            return

        scene_label = env_name if env_name else mood.get("name", "")
        self.lbl_last_trigger.configure(
            text=f"Scena: {scene_label} ({(terms or matched_by)[:28]})",
            text_color="#10b981",
        )

        if self.is_mood_locked and not is_command and not bypass_cooldown:
            return

        # Se è lo stesso mood e lo stesso ambiente già attivo, non riavviare la traccia
        if env_id:
            if env_id == self.current_env_id and mood_id == self.current_mood_id and not is_command and not bypass_cooldown:
                return
        else:
            if mood_id == self.current_mood_id and self.current_env_id is None and not is_command and not bypass_cooldown:
                return

        now = time.time()
        # I cambi di ambiente espliciti (es. da "valle innevata" a "deserto") o di combattimento bypassano il cooldown!
        is_urgent_mood = mood_id in ("combattimento", "boss", "terrore", "fuga", "sparatoria")
        if (
            not is_command
            and not is_env_switch
            and not is_urgent_mood
            and not bypass_cooldown
            and self.current_mood_id
            and now < self.cooldown_until
        ):
            return

        cd_sec = float(self.cfg.get("analyzer", {}).get("cooldown_seconds", 18))
        if cd_sec > 0:
            self.cooldown_until = time.time() + cd_sec

        custom_q = res.get("custom_search_query", "")
        self._trigger_mood(
            mood_id,
            manual=False,
            custom_query=custom_q,
            env_data=res if env_id else None,
        )

    def _trigger_mood(
        self,
        mood_id: str,
        manual: bool = False,
        custom_query: str = "",
        env_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        prof = self._get_active_profile()
        mood = prof.get("moods", {}).get(mood_id)
        if not mood:
            return

        self.current_mood_id = mood_id
        self.current_env_id = env_data.get("env_id") if env_data else None
        self._update_moods_active_state()

        if env_data and env_data.get("env_name"):
            badge_txt = str(env_data["env_name"])[:22]
            badge_color = env_data.get("env_color") or mood.get("color", "#10b981")
        else:
            badge_txt = f"{mood.get('icon', '🎵')} {mood.get('name', '')[:18]}"
            badge_color = mood.get("color", "#10b981")

        self.lbl_active_mood_badge.configure(
            text=badge_txt,
            fg_color=badge_color,
            text_color="#ffffff",
        )
        self._set_status_text("Ricerca brani...")

        def fetch_worker() -> None:
            tracks: List[Dict[str, Any]] = []
            seen: set[str] = set()
            tone_profile = (mood.get("tone_profile") or "").strip()

            # 1. Se è stato attivato un BIOMA/AMBIENTE specifico (es. "valle innevata", "deserto", "mare", "palude"),
            # usa in cima alla coda i suoi brani strumentali certificati (env_seed_tracks)!
            if env_data and env_data.get("env_seed_tracks"):
                env_seeds = [
                    dict(st)
                    for st in (env_data.get("env_seed_tracks") or [])
                    if isinstance(st, dict) and st.get("videoId")
                ]
                random.shuffle(env_seeds)
                for st in env_seeds:
                    if st["videoId"] not in seen:
                        tracks.append(st)
                        seen.add(st["videoId"])

            # 2. Altrimenti usa i brani fissati e le playlist/seed del mood principale
            if not env_data:
                for pt in mood.get("pinned_tracks") or []:
                    if isinstance(pt, dict) and pt.get("videoId") and pt["videoId"] not in seen:
                        tracks.append(pt)
                        seen.add(pt["videoId"])

                custom_pl = (mood.get("custom_playlist") or "").strip()
                if custom_pl and not custom_query:
                    try:
                        pl_info = self.ytm_service.get_playlist_tracks(custom_pl, limit=30)
                        pl_tracks = pl_info.get("tracks") or []
                        random.shuffle(pl_tracks)
                        for t in pl_tracks:
                            if t["videoId"] not in seen:
                                tracks.append(t)
                                seen.add(t["videoId"])
                    except Exception as e:
                        print(f"[Bardo] Errore playlist '{custom_pl}', uso ricerca automatica: {e}")

                if not custom_pl and not custom_query:
                    seed_list = [
                        dict(st)
                        for st in (mood.get("seed_tracks") or [])
                        if isinstance(st, dict) and st.get("videoId")
                    ]
                    random.shuffle(seed_list)
                    for st in seed_list:
                        if st["videoId"] not in seen:
                            tracks.append(st)
                            seen.add(st["videoId"])

            if len(tracks) < 12 or custom_query:
                queries = mood.get("queries") or [f"{mood.get('name')} rpg instrumental"]
                q = custom_query.strip() if custom_query.strip() else random.choice(queries)
                searched = self.ytm_service.search_tracks(
                    q, limit=10, tone_profile=tone_profile
                )
                for st in searched:
                    if st["videoId"] not in seen:
                        tracks.append(st)
                        seen.add(st["videoId"])

            self._post_ui(lambda: self._apply_mood_tracks(tracks))

        threading.Thread(target=fetch_worker, daemon=True).start()

    def _apply_mood_tracks(self, tracks: List[Dict[str, Any]]) -> None:
        if not tracks:
            self._set_status_text("Nessun brano trovato")
            return
        self.player.queue = list(tracks)
        self.player.current_index = 0
        # play_track_at(0) invocherà _on_player_track_change che aggiornerà la coda una sola volta!
        self.player.play_track_at(0)

    def _set_status_text(self, text: str) -> None:
        short = text[:28]
        if short != self._last_status_str:
            self._last_status_str = short
            self.lbl_player_status.configure(text=short)

    # =========================================================================
    # CALLBACK PLAYER AUDIO E CONTROLLI
    # =========================================================================

    def _on_player_track_change(self, track: Dict[str, Any]) -> None:
        def update_ui() -> None:
            title = (track.get("title") or "Brano").replace("\n", " ")[:34]
            artist = (track.get("artist") or "YouTube Music").replace("\n", " ")[:36]
            if self.lbl_track_title.cget("text") != title:
                self.lbl_track_title.configure(text=title)
            if self.lbl_track_artist.cget("text") != artist:
                self.lbl_track_artist.configure(text=artist)
            self._render_queue()

        self._post_ui(update_ui)

        thumb_url = track.get("thumbnail")
        if thumb_url:
            def thumb_worker() -> None:
                try:
                    req = urllib.request.Request(thumb_url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=4) as resp:
                        raw = resp.read()
                    pil_img = Image.open(io.BytesIO(raw)).convert("RGB").resize((80, 80))
                    ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(80, 80))
                    def apply_thumb() -> None:
                        self._current_cover_img = ctk_img
                        self.lbl_cover.configure(image=ctk_img)
                    self._post_ui(apply_thumb)
                except Exception:
                    pass

            threading.Thread(target=thumb_worker, daemon=True).start()

    def _on_player_state_change(self, is_playing: bool, status_text: str) -> None:
        def update() -> None:
            btn_txt = "⏸️" if is_playing else "▶️"
            if btn_txt != self._last_play_btn_str:
                self._last_play_btn_str = btn_txt
                self.btn_play_pause.configure(text=btn_txt)
            self._set_status_text(status_text)

        self._post_ui(update)

    def _on_player_error(self, err_msg: str) -> None:
        self._post_ui(lambda: self._set_status_text("Cambio traccia..."))

    def _on_play_pause_clicked(self) -> None:
        if not self.player.queue:
            prof = self._get_active_profile()
            default_mood = prof.get("default_mood") or next(iter(prof.get("moods", {}).keys()), None)
            if default_mood:
                self._trigger_mood(default_mood, manual=True)
            return
        self.player.toggle_play_pause()

    def _shuffle_queue(self) -> None:
        if len(self.player.queue) <= 1:
            return
        random.shuffle(self.player.queue)
        self.player.play_track_at(0)

    def _on_volume_changed(self, val: float) -> None:
        v = max(0, min(100, int(round(float(val)))))
        self.lbl_vol.configure(text=f"🔊 Vol Musica: {v}%")
        self.player.set_volume(v)
        self.cfg.setdefault("audio", {})["master_volume"] = v
        self._schedule_save_config()

    def _on_crossfade_changed(self, val: float) -> None:
        cf = round(float(val), 1)
        self.lbl_cf.configure(text=f"🌊 Crossfade: {cf:.1f}s")
        self.player.crossfade_seconds = cf
        self.cfg.setdefault("audio", {})["crossfade_seconds"] = cf
        self._schedule_save_config()

    def _on_seek_slider(self, val: float) -> None:
        self.player.set_position_pct(val)

    def _on_direct_search(self) -> None:
        q = self.entry_ytm_search.get().strip()
        if not q:
            return
        self._set_status_text(f"Cerco '{q[:16]}'...")

        def worker() -> None:
            tracks = self.ytm_service.search_tracks(q, limit=12)
            self._post_ui(lambda: self._apply_mood_tracks(tracks))

        threading.Thread(target=worker, daemon=True).start()

    def _pin_current_track(self) -> None:
        if not self.current_mood_id or not self.player.queue:
            return
        track = self.player.queue[self.player.current_index]
        prof = self._get_active_profile()
        mood = prof.get("moods", {}).get(self.current_mood_id)
        if not mood:
            return
        pinned = mood.setdefault("pinned_tracks", [])
        if not any(t.get("videoId") == track.get("videoId") for t in pinned):
            pinned.insert(0, track)
            save_config(self.cfg)
            self._set_status_text("Brano fissato!")

    def _open_current_in_browser(self) -> None:
        if not self.player.queue or self.player.current_index < 0:
            webbrowser.open("https://music.youtube.com")
            return
        track = self.player.queue[self.player.current_index]
        url = track.get("ytmusic_url") or f"https://music.youtube.com/watch?v={track.get('videoId')}"
        webbrowser.open(url)

    def _ui_tick(self) -> None:
        # 1. Svuota tutti gli aggiornamenti UI accodati dai thread secondari
        while True:
            try:
                fn = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception:
                pass

        # 2. Aggiorna barra avanzamento solo se il valore testuale è cambiato
        if self.player.is_playing:
            prog = self.player.get_progress()
            cur_s = prog["current"]
            dur_s = prog["duration"]
            cur_str = f"{cur_s // 60}:{cur_s % 60:02d}"
            dur_str = f"{dur_s // 60}:{dur_s % 60:02d}"
            if cur_str != self._last_cur_time_str:
                self._last_cur_time_str = cur_str
                self.lbl_cur_time.configure(text=cur_str)
            if dur_str != self._last_dur_time_str:
                self._last_dur_time_str = dur_str
                self.lbl_dur_time.configure(text=dur_str)
            if dur_s > 0:
                self.seek_slider.set(prog["pct"])

        rem = int(self.cooldown_until - time.time())
        cd_str = f"Cooldown: {rem}s" if rem > 0 else ""
        if cd_str != self._last_cooldown_str:
            self._last_cooldown_str = cd_str
            self.lbl_cooldown.configure(text=cd_str)

        self.after(100, self._ui_tick)

    # =========================================================================
    # FINESTRE DI DIALOGO (AGGIUNGI SUONO SFX, PROFILI, ATMOSFERE, YT MUSIC, AI)
    # =========================================================================

    def _open_add_custom_sfx_dialog(self) -> None:
        win = ctk.CTkToplevel(self)
        win.title("➕ Aggiungi Effetto Sonoro (SFX) alla Soundboard")
        win.geometry("500x430")
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(win, text="Icona (Emoji) e Nome Suono:", font=ctk.CTkFont(weight="bold")).pack(
            anchor="w", padx=16, pady=(14, 4)
        )
        r1 = ctk.CTkFrame(win, fg_color="transparent")
        r1.pack(fill="x", padx=16)
        ent_icon = ctk.CTkEntry(r1, width=60)
        ent_icon.insert(0, "🔊")
        ent_icon.pack(side="left", padx=(0, 8))
        ent_name = ctk.CTkEntry(r1, placeholder_text="es. Pistola Laser / Ruggiti / Campana")
        ent_name.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(win, text="Categoria:", font=ctk.CTkFont(weight="bold")).pack(
            anchor="w", padx=16, pady=(10, 4)
        )
        cat_combo = ctk.CTkOptionMenu(win, values=["Armi", "Creature", "Magia", "Ambiente"])
        cat_combo.pack(fill="x", padx=16)

        ctk.CTkLabel(
            win, text="Parole chiave vocali in italiano (separate da virgola):", font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=16, pady=(10, 4))
        ent_kw = ctk.CTkEntry(win, placeholder_text="es. pistola, sparo, laser, colpo")
        ent_kw.pack(fill="x", padx=16)

        ctk.CTkLabel(win, text="File Audio (.wav / .mp3):", font=ctk.CTkFont(weight="bold")).pack(
            anchor="w", padx=16, pady=(10, 4)
        )
        file_row = ctk.CTkFrame(win, fg_color="transparent")
        file_row.pack(fill="x", padx=16)
        ent_file = ctk.CTkEntry(file_row, placeholder_text="Seleziona un file audio dal PC...")
        ent_file.pack(side="left", fill="x", expand=True, padx=(0, 8))

        def pick_file() -> None:
            fp = filedialog.askopenfilename(
                title="Scegli file audio SFX",
                filetypes=[("File Audio", "*.wav *.mp3 *.ogg *.m4a")],
            )
            if fp:
                ent_file.delete(0, "end")
                ent_file.insert(0, fp)

        ctk.CTkButton(file_row, text="Sfoglia...", width=85, command=pick_file).pack(side="right")

        def save_custom_sfx() -> None:
            name = ent_name.get().strip()
            src_path_str = ent_file.get().strip()
            if not name or not src_path_str:
                return
            src_path = Path(src_path_str)
            if not src_path.exists():
                messagebox.showerror("Errore", "Il file audio selezionato non esiste.")
                return

            sfx_id = f"custom_{int(time.time())}"
            dest_name = f"{sfx_id}{src_path.suffix}"
            dest_path = self.sfx_manager.sfx_dir / dest_name
            shutil.copy2(src_path, dest_path)

            kws = [k.strip() for k in ent_kw.get().split(",") if k.strip()]
            custom_items = self.cfg.setdefault("sfx", {}).setdefault("custom_items", {})
            custom_items[sfx_id] = {
                "id": sfx_id,
                "name": name,
                "icon": ent_icon.get().strip() or "🔊",
                "category": cat_combo.get(),
                "color": "#f59e0b",
                "file": dest_name,
                "hint": " • ".join((kws or [name.lower()])[:3]),
                "phrases": [],
                "keywords": kws or [name.lower()],
            }
            save_config(self.cfg)
            self._render_sfx_grid()
            win.destroy()

        ctk.CTkButton(win, text="💾 Salva nella Soundboard", height=36, command=save_custom_sfx).pack(
            fill="x", padx=16, pady=20
        )

    def _on_profile_selected(self, selected_disp: str) -> None:
        pid = self.profile_map.get(selected_disp)
        if pid and pid in self.cfg["profiles"]:
            self.active_profile_id = pid
            self.cfg["active_profile_id"] = pid
            self.current_mood_id = None
            save_config(self.cfg)
            self._sync_ui_from_config()

    def _delete_current_profile(self) -> None:
        if len(self.cfg["profiles"]) <= 1:
            messagebox.showwarning("Attenzione", "Non puoi eliminare l'unico profilo rimasto.")
            return
        prof = self._get_active_profile()
        if not messagebox.askyesno("Conferma", f"Vuoi eliminare il profilo '{prof.get('name')}'?"):
            return
        del self.cfg["profiles"][self.active_profile_id]
        self.active_profile_id = next(iter(self.cfg["profiles"].keys()))
        self.cfg["active_profile_id"] = self.active_profile_id
        save_config(self.cfg)
        self._sync_ui_from_config()

    def _open_new_profile_dialog(self) -> None:
        win = ctk.CTkToplevel(self)
        win.title("➕ Crea Nuovo Profilo Ambientazione")
        win.geometry("480x360")
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(win, text="Icona (Emoji) e Nome Ambientazione:", font=ctk.CTkFont(weight="bold")).pack(
            anchor="w", padx=16, pady=(14, 4)
        )
        row = ctk.CTkFrame(win, fg_color="transparent")
        row.pack(fill="x", padx=16)
        ent_icon = ctk.CTkEntry(row, width=60)
        ent_icon.insert(0, "🎲")
        ent_icon.pack(side="left", padx=(0, 8))
        ent_name = ctk.CTkEntry(row, placeholder_text="es. Vampiri / Western / Pirati")
        ent_name.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(win, text="Descrizione:", font=ctk.CTkFont(weight="bold")).pack(
            anchor="w", padx=16, pady=(12, 4)
        )
        ent_desc = ctk.CTkEntry(win, placeholder_text="Descrizione della campagna...")
        ent_desc.pack(fill="x", padx=16)

        ctk.CTkLabel(win, text="Copia atmosfere iniziali da:", font=ctk.CTkFont(weight="bold")).pack(
            anchor="w", padx=16, pady=(12, 4)
        )
        tpl_combo = ctk.CTkOptionMenu(
            win, values=["Fantasy & D&D", "Horror & Investigativo", "Sci-Fi & Cyberpunk", "Profilo Vuoto"]
        )
        tpl_combo.pack(fill="x", padx=16)

        def create() -> None:
            name = ent_name.get().strip()
            if not name:
                return
            pid = f"prof_{int(time.time())}"
            tpl_map = {
                "Fantasy & D&D": "fantasy_dnd",
                "Horror & Investigativo": "horror_cthulhu",
                "Sci-Fi & Cyberpunk": "scifi_cyberpunk",
            }
            tpl_id = tpl_map.get(tpl_combo.get())
            moods = copy.deepcopy(self.cfg["profiles"][tpl_id]["moods"]) if tpl_id in self.cfg["profiles"] else {}

            self.cfg["profiles"][pid] = {
                "id": pid,
                "name": name,
                "icon": ent_icon.get().strip() or "🎲",
                "description": ent_desc.get().strip(),
                "default_mood": next(iter(moods.keys()), ""),
                "moods": moods,
            }
            self.active_profile_id = pid
            self.cfg["active_profile_id"] = pid
            save_config(self.cfg)
            self._sync_ui_from_config()
            win.destroy()

        ctk.CTkButton(win, text="✨ Crea Profilo", height=36, command=create).pack(
            fill="x", padx=16, pady=20
        )

    def _open_edit_mood_dialog(self, mood_id: Optional[str]) -> None:
        prof = self._get_active_profile()
        is_edit = bool(mood_id and mood_id in prof.get("moods", {}))
        mood = (
            prof["moods"][mood_id]
            if is_edit
            else {
                "id": "",
                "name": "",
                "icon": "🎵",
                "color": "#10b981",
                "description": "",
                "phrases": [],
                "keywords": [],
                "queries": [],
                "custom_playlist": "",
            }
        )

        win = ctk.CTkToplevel(self)
        win.title(f"⚙️ Modifica Atmosfera: {mood.get('name')}" if is_edit else "➕ Nuova Atmosfera")
        win.geometry("620x660")
        win.transient(self)
        win.grab_set()

        scroll = ctk.CTkScrollableFrame(win, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(scroll, text="Icona, Nome Atmosfera e Colore Hex:", font=ctk.CTkFont(weight="bold")).pack(
            anchor="w", pady=(4, 4)
        )
        r1 = ctk.CTkFrame(scroll, fg_color="transparent")
        r1.pack(fill="x")
        ent_icon = ctk.CTkEntry(r1, width=60)
        ent_icon.insert(0, mood.get("icon", "🎵"))
        ent_icon.pack(side="left", padx=(0, 6))

        ent_name = ctk.CTkEntry(r1, placeholder_text="Nome (es. Battaglia Navale)")
        ent_name.insert(0, mood.get("name", ""))
        ent_name.pack(side="left", fill="x", expand=True, padx=(0, 6))

        ent_color = ctk.CTkEntry(r1, width=100)
        ent_color.insert(0, mood.get("color", "#10b981"))
        ent_color.pack(side="left")

        ctk.CTkLabel(scroll, text="Descrizione scena:", font=ctk.CTkFont(weight="bold")).pack(
            anchor="w", pady=(10, 4)
        )
        ent_desc = ctk.CTkEntry(scroll)
        ent_desc.insert(0, mood.get("description", ""))
        ent_desc.pack(fill="x")

        ctk.CTkLabel(
            scroll, text="Frasi Chiave Trigger in Italiano (una per riga — priorità alta):", font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", pady=(10, 4))
        txt_phrases = ctk.CTkTextbox(scroll, height=80)
        txt_phrases.insert("1.0", "\n".join(mood.get("phrases", [])))
        txt_phrases.pack(fill="x")

        ctk.CTkLabel(
            scroll, text="Parole Chiave in Italiano (separate da virgola):", font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", pady=(10, 4))
        txt_kw = ctk.CTkTextbox(scroll, height=70)
        txt_kw.insert("1.0", ", ".join(mood.get("keywords", [])))
        txt_kw.pack(fill="x")

        ctk.CTkLabel(
            scroll, text="Query di ricerca su YouTube Music (una per riga):", font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", pady=(10, 4))
        txt_queries = ctk.CTkTextbox(scroll, height=70)
        txt_queries.insert("1.0", "\n".join(mood.get("queries", [])))
        txt_queries.pack(fill="x")

        ctk.CTkLabel(
            scroll,
            text="Link o ID Playlist Personale (Spotify oppure YouTube Music — opzionale):",
            font=ctk.CTkFont(weight="bold"),
        ).pack(anchor="w", pady=(10, 4))
        ent_pl = ctk.CTkEntry(
            scroll,
            placeholder_text="es. https://open.spotify.com/playlist/... oppure https://music.youtube.com/playlist?list=...",
        )
        ent_pl.insert(0, mood.get("custom_playlist", ""))
        ent_pl.pack(fill="x")

        btn_row = ctk.CTkFrame(scroll, fg_color="transparent")
        btn_row.pack(fill="x", pady=16)

        def save_mood() -> None:
            name = ent_name.get().strip()
            if not name:
                return
            mid = mood_id or name.lower().replace(" ", "_")
            phrases = [s.strip() for s in txt_phrases.get("1.0", "end").splitlines() if s.strip()]
            kws = [s.strip() for s in txt_kw.get("1.0", "end").replace("\n", ",").split(",") if s.strip()]
            queries = [s.strip() for s in txt_queries.get("1.0", "end").splitlines() if s.strip()]

            prof["moods"][mid] = {
                "id": mid,
                "name": name,
                "icon": ent_icon.get().strip() or "🎵",
                "color": ent_color.get().strip() or "#10b981",
                "description": ent_desc.get().strip(),
                "phrases": phrases,
                "keywords": kws,
                "queries": queries or [f"{name} rpg instrumental"],
                "custom_playlist": ent_pl.get().strip(),
                "pinned_tracks": mood.get("pinned_tracks", []),
            }
            save_config(self.cfg)
            self._render_moods_grid()
            win.destroy()

        def del_mood() -> None:
            if is_edit and messagebox.askyesno("Conferma", f"Eliminare l'atmosfera '{mood.get('name')}'?"):
                del prof["moods"][mood_id]
                save_config(self.cfg)
                self._render_moods_grid()
                win.destroy()

        if is_edit:
            ctk.CTkButton(btn_row, text="🗑️ Elimina", fg_color="#7f1d1d", command=del_mood).pack(side="left")

        ctk.CTkButton(btn_row, text="💾 Salva Atmosfera", command=save_mood).pack(side="right")

    def _open_ytm_dialog(self, default_tab: str = "🟢 Spotify") -> None:
        win = ctk.CTkToplevel(self)
        win.title("🎵 Account Musicale & Playlist (Spotify / YouTube Music)")
        win.geometry("820x720")
        win.transient(self)
        win.grab_set()

        prof = self._get_active_profile()
        mood_choices = ["-- Solo Riproduci Subito --"] + [
            f"{m['id']} :: {m.get('icon', '')} {m.get('name')}" for m in prof.get("moods", {}).values()
        ]

        # Selettore Provider Principale in alto
        top_prov_frame = ctk.CTkFrame(win, fg_color="#131822", corner_radius=8)
        top_prov_frame.pack(fill="x", padx=14, pady=(10, 4))

        ctk.CTkLabel(
            top_prov_frame,
            text="Servizio Musicale Preferito:",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(side="left", padx=12, pady=8)

        cur_prov = self.cfg.get("audio", {}).get("music_provider", "spotify")
        self.ytm_service.active_provider = cur_prov

        def on_prov_change(val: str) -> None:
            p_code = "spotify" if "Spotify" in val else "ytmusic"
            self.ytm_service.active_provider = p_code
            self.cfg.setdefault("audio", {})["music_provider"] = p_code
            save_config(self.cfg)

        prov_seg = ctk.CTkSegmentedButton(
            top_prov_frame,
            values=["🟢 Spotify", "🔴 YouTube Music"],
            selected_color="#15803d",
            selected_hover_color="#16a34a",
            command=on_prov_change,
        )
        prov_seg.set("🟢 Spotify" if cur_prov == "spotify" else "🔴 YouTube Music")
        prov_seg.pack(side="left", padx=8, pady=8)

        tabs = ctk.CTkTabview(win, fg_color="#0f141d")
        tabs.pack(fill="both", expand=True, padx=14, pady=(2, 12))
        tab_sp = tabs.add("🟢 Spotify")
        tab_yt = tabs.add("🔴 YouTube Music")
        if default_tab in ("🟢 Spotify", "🔴 YouTube Music"):
            tabs.set(default_tab)

        # =====================================================================
        # TAB 1: SPOTIFY (LOGIN 1-CLIC, PLAYLIST PERSONALI, CREDENZIALI API)
        # =====================================================================
        sp_scroll = ctk.CTkScrollableFrame(tab_sp, fg_color="transparent")
        sp_scroll.pack(fill="both", expand=True, padx=6, pady=6)

        sp_box1 = ctk.CTkFrame(sp_scroll, fg_color="#131822", corner_radius=10)
        sp_box1.pack(fill="x", pady=(0, 10))

        sp_status = self.ytm_service.spotify.get_auth_status()
        sp_status_txt = (
            f"✅ Connesso a Spotify ({sp_status.get('user_name')})"
            if sp_status["authenticated"]
            else "Non collegato (Puoi accedere con 1 clic o usare link playlist Spotify)"
        )
        lbl_sp_status = ctk.CTkLabel(
            sp_box1,
            text=f"1. Il tuo Account Spotify — {sp_status_txt}",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#22c55e" if sp_status["authenticated"] else "#f1f5f9",
        )
        lbl_sp_status.pack(anchor="w", padx=12, pady=(10, 4))

        ctk.CTkLabel(
            sp_box1,
            text="Clicca il pulsante verde qui sotto: si aprirà una finestra di login Spotify. Accedi normalmente al tuo account Spotify; non appena si apre il Web Player, la finestra si chiuderà da sola e importerà qui sotto tutte le tue playlist!",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8",
            wraplength=730,
            justify="left",
        ).pack(anchor="w", padx=12, pady=(0, 8))

        sp_btn_row = ctk.CTkFrame(sp_box1, fg_color="transparent")
        sp_btn_row.pack(fill="x", padx=12, pady=(0, 10))

        sp_pl_frame = ctk.CTkFrame(sp_box1, fg_color="#0b0e14", corner_radius=8)
        sp_pl_frame.pack(fill="x", padx=12, pady=(0, 10))

        def render_spotify_playlists(playlists: List[Dict[str, Any]]) -> None:
            for w in sp_pl_frame.winfo_children():
                w.destroy()
            if not playlists:
                ctk.CTkLabel(
                    sp_pl_frame,
                    text="Nessuna playlist caricata.",
                    font=ctk.CTkFont(size=11),
                    text_color="#64748b",
                ).pack(padx=10, pady=8)
                return

            ctk.CTkLabel(
                sp_pl_frame,
                text=f"🟢 Playlist Spotify Disponibili ({len(playlists)}):",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color="#22c55e",
            ).pack(anchor="w", padx=10, pady=(8, 4))

            for pl in playlists[:18]:
                row_p = ctk.CTkFrame(sp_pl_frame, fg_color="#131822", corner_radius=6)
                row_p.pack(fill="x", padx=8, pady=3)
                cnt = f" ({pl.get('count')})" if pl.get("count") else ""
                ctk.CTkLabel(
                    row_p,
                    text=f"🟢 {pl.get('title', 'Playlist Spotify')[:44]}{cnt}",
                    font=ctk.CTkFont(size=12, weight="bold"),
                ).pack(side="left", padx=10, pady=6)

                def play_sp_pl(pid: str = pl["playlistId"], title: str = pl.get("title", "")) -> None:
                    lbl_sp_status.configure(text=f"⏳ Carico brani Spotify di '{title}'...", text_color="#fbbf24")
                    def w() -> None:
                        try:
                            data = self.ytm_service.spotify.get_playlist_tracks(pid, limit=40)
                            self._post_ui(
                                lambda: (
                                    self._apply_mood_tracks(data.get("tracks", [])),
                                    lbl_sp_status.configure(
                                        text=f"🔊 In riproduzione da Spotify: {title} ({data.get('trackCount', 0)} brani)",
                                        text_color="#22c55e",
                                    ),
                                )
                            )
                        except Exception as e:
                            self._post_ui(lambda: messagebox.showerror("Errore Playlist Spotify", str(e)))
                    threading.Thread(target=w, daemon=True).start()

                def assign_sp_pl(pid: str = pl["playlistId"], title: str = pl.get("title", "")) -> None:
                    sel = sp_combo_assign.get()
                    if "::" not in sel:
                        messagebox.showinfo(
                            "Seleziona un'atmosfera",
                            "Scegli prima un'atmosfera nel menu a tendina 'Abbina a Scena' qui sotto (Sezione 2), poi clicca 'Abbina'!",
                        )
                        return
                    mid = sel.split("::")[0].strip()
                    if mid in prof["moods"]:
                        prof["moods"][mid]["custom_playlist"] = f"https://open.spotify.com/playlist/{pid}"
                        save_config(self.cfg)
                        self._render_moods_grid()
                        lbl_sp_status.configure(
                            text=f"✅ Playlist Spotify '{title}' abbinata a '{prof['moods'][mid]['name']}'!",
                            text_color="#22c55e",
                        )

                ctk.CTkButton(
                    row_p,
                    text="▶️ Riproduci",
                    width=95,
                    height=26,
                    fg_color="#15803d",
                    hover_color="#16a34a",
                    command=play_sp_pl,
                ).pack(side="right", padx=6, pady=4)

                ctk.CTkButton(
                    row_p,
                    text="📌 Abbina",
                    width=78,
                    height=26,
                    fg_color="#1e293b",
                    hover_color="#334155",
                    command=assign_sp_pl,
                ).pack(side="right", padx=2, pady=4)

        def start_spotify_window_login() -> None:
            lbl_sp_status.configure(
                text="⏳ Finestra Spotify aperta! Effettua l'accesso nella finestra che si è aperta...",
                text_color="#fbbf24",
            )
            def worker() -> None:
                try:
                    res = self.ytm_service.spotify.login_via_browser_window()
                    self.ytm_service.active_provider = "spotify"
                    self.cfg.setdefault("audio", {})["music_provider"] = "spotify"
                    save_config(self.cfg)
                    self._post_ui(
                        lambda: (
                            prov_seg.set("🟢 Spotify"),
                            lbl_sp_status.configure(
                                text=f"✅ Account Spotify Collegato ({res.get('user_name')}) — {res['playlists_count']} playlist!",
                                text_color="#22c55e",
                            ),
                            render_spotify_playlists(res.get("playlists", [])),
                        )
                    )
                except Exception as e:
                    self._post_ui(
                        lambda: lbl_sp_status.configure(text=f"⚠️ {e}", text_color="#ef4444")
                    )
            threading.Thread(target=worker, daemon=True).start()

        def reload_spotify_playlists() -> None:
            pls = self.ytm_service.spotify.get_user_playlists()
            render_spotify_playlists(pls)

        def disconnect_spotify() -> None:
            self.ytm_service.spotify.disconnect_account()
            lbl_sp_status.configure(text="Account Spotify scollegato.", text_color="#94a3b8")
            render_spotify_playlists(self.ytm_service.spotify.get_user_playlists())

        ctk.CTkButton(
            sp_btn_row,
            text="🟢 Accedi con Finestra Spotify (1 Clic)",
            fg_color="#15803d",
            hover_color="#16a34a",
            height=36,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=start_spotify_window_login,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            sp_btn_row,
            text="🔄 Aggiorna Playlist",
            fg_color="#1e293b",
            height=36,
            command=reload_spotify_playlists,
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            sp_btn_row,
            text="Scollega",
            fg_color="#7f1d1d",
            width=80,
            height=36,
            command=disconnect_spotify,
        ).pack(side="right", padx=4)

        # Sezione 2 Spotify: Importa o Abbina qualsiasi link Playlist Spotify
        sp_box2 = ctk.CTkFrame(sp_scroll, fg_color="#131822", corner_radius=10)
        sp_box2.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(
            sp_box2,
            text="2. Importa o Abbina qualsiasi Playlist Spotify tramite Link (Funziona anche senza login!)",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(anchor="w", padx=12, pady=(10, 4))

        ent_sp_url = ctk.CTkEntry(
            sp_box2,
            placeholder_text="Incolla link playlist Spotify: https://open.spotify.com/playlist/37i9dQZF1DXdfOcg1fm0VG",
        )
        ent_sp_url.pack(fill="x", padx=12, pady=4)

        sp_combo_assign = ctk.CTkOptionMenu(sp_box2, values=mood_choices)
        sp_combo_assign.pack(fill="x", padx=12, pady=4)

        lbl_sp_pl_res = ctk.CTkLabel(sp_box2, text="", text_color="#22c55e")
        lbl_sp_pl_res.pack(anchor="w", padx=12)

        def import_sp_pl() -> None:
            url = ent_sp_url.get().strip()
            if not url:
                return
            lbl_sp_pl_res.configure(text="⏳ Caricamento playlist da Spotify...", text_color="#fbbf24")
            def worker() -> None:
                try:
                    pl_data = self.ytm_service.spotify.get_playlist_tracks(url, limit=45)
                    sel = sp_combo_assign.get()
                    if "::" in sel:
                        mid = sel.split("::")[0].strip()
                        if mid in prof["moods"]:
                            prof["moods"][mid]["custom_playlist"] = f"https://open.spotify.com/playlist/{pl_data['playlistId']}"
                            save_config(self.cfg)
                    self._post_ui(
                        lambda: (
                            lbl_sp_pl_res.configure(
                                text=f"✅ Playlist Spotify '{pl_data['title']}' ({pl_data['trackCount']} brani) caricata!",
                                text_color="#22c55e",
                            ),
                            self._render_moods_grid(),
                            self._apply_mood_tracks(pl_data.get("tracks", [])),
                        )
                    )
                except Exception as e:
                    self._post_ui(lambda: lbl_sp_pl_res.configure(text=f"⚠️ Errore: {e}", text_color="#ef4444"))
            threading.Thread(target=worker, daemon=True).start()

        ctk.CTkButton(
            sp_box2,
            text="📥 Importa e Riproduci Playlist Spotify",
            fg_color="#15803d",
            hover_color="#16a34a",
            command=import_sp_pl,
        ).pack(anchor="e", padx=12, pady=8)

        # Sezione 3 Spotify: Metodo Alternativo (Client ID/Secret oppure Cookie sp_dc / Token)
        sp_box3 = ctk.CTkFrame(sp_scroll, fg_color="#131822", corner_radius=10)
        sp_box3.pack(fill="x", pady=4)
        ctk.CTkLabel(
            sp_box3,
            text="3. Metodo Alternativo Spotify (Client ID & Secret API oppure Cookie sp_dc / Token / cURL)",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=12, pady=(8, 4))

        cred_row = ctk.CTkFrame(sp_box3, fg_color="transparent")
        cred_row.pack(fill="x", padx=12, pady=4)
        ent_sp_cid = ctk.CTkEntry(cred_row, placeholder_text="Spotify Client ID (Opzionale)")
        ent_sp_cid.insert(0, self.ytm_service.spotify.auth_data.get("client_id", ""))
        ent_sp_cid.pack(side="left", fill="x", expand=True, padx=(0, 4))

        ent_sp_csec = ctk.CTkEntry(cred_row, placeholder_text="Spotify Client Secret (Opzionale)", show="*")
        ent_sp_csec.insert(0, self.ytm_service.spotify.auth_data.get("client_secret", ""))
        ent_sp_csec.pack(side="left", fill="x", expand=True, padx=(4, 4))

        ent_sp_user = ctk.CTkEntry(cred_row, placeholder_text="Tuo Username Spotify (Opzionale)", width=180)
        ent_sp_user.pack(side="left", padx=(4, 0))

        txt_sp_raw = ctk.CTkTextbox(sp_box3, height=60)
        txt_sp_raw.pack(fill="x", padx=12, pady=4)

        def connect_sp_manual() -> None:
            try:
                res = self.ytm_service.spotify.connect_with_credentials_or_raw(
                    client_id=ent_sp_cid.get(),
                    client_secret=ent_sp_csec.get(),
                    spotify_username=ent_sp_user.get(),
                    raw_input=txt_sp_raw.get("1.0", "end"),
                )
                self.ytm_service.active_provider = "spotify"
                self.cfg.setdefault("audio", {})["music_provider"] = "spotify"
                save_config(self.cfg)
                prov_seg.set("🟢 Spotify")
                lbl_sp_status.configure(
                    text=f"✅ Spotify Collegato ({res.get('user_name')}) — {res['playlists_count']} playlist",
                    text_color="#22c55e",
                )
                render_spotify_playlists(res.get("playlists", []))
            except Exception as e:
                messagebox.showerror("Errore Spotify", str(e))

        ctk.CTkButton(
            sp_box3,
            text="🔗 Collega Spotify Manualmente",
            fg_color="#15803d",
            hover_color="#16a34a",
            command=connect_sp_manual,
        ).pack(anchor="e", padx=12, pady=8)

        render_spotify_playlists(self.ytm_service.spotify.get_user_playlists())

        # =====================================================================
        # TAB 2: YOUTUBE MUSIC
        # =====================================================================
        scroll = ctk.CTkScrollableFrame(tab_yt, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=6, pady=6)

        b_login = ctk.CTkFrame(scroll, fg_color="#131822", corner_radius=10)
        b_login.pack(fill="x", pady=(0, 12))

        status_str = (
            "✅ Account Google / YouTube Music Collegato!"
            if self.ytm_service.is_authenticated
            else "Non collegato (Modalità ospite attiva)"
        )
        lbl_auth_status = ctk.CTkLabel(
            b_login,
            text=f"1. Il tuo Account YouTube Music — {status_str}",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#10b981" if self.ytm_service.is_authenticated else "#f1f5f9",
        )
        lbl_auth_status.pack(anchor="w", padx=12, pady=(10, 4))

        ctk.CTkLabel(
            b_login,
            text="Clicca il pulsante qui sotto: si aprirà una finestra di YouTube Music. Fai normalmente il login col tuo account Google; appena avrai effettuato l'accesso, la finestra si chiuderà da sola e vedrai qui sotto tutte le tue playlist!",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8",
            wraplength=700,
            justify="left",
        ).pack(anchor="w", padx=12, pady=(0, 8))

        btn_login_row = ctk.CTkFrame(b_login, fg_color="transparent")
        btn_login_row.pack(fill="x", padx=12, pady=(0, 10))

        pl_list_frame = ctk.CTkFrame(b_login, fg_color="#0b0e14", corner_radius=8)
        pl_list_frame.pack(fill="x", padx=12, pady=(0, 10))

        def render_user_playlists(playlists: List[Dict[str, Any]]) -> None:
            for w in pl_list_frame.winfo_children():
                w.destroy()
            if not playlists:
                ctk.CTkLabel(
                    pl_list_frame,
                    text="Nessuna playlist personale caricata. Clicca 'Accedi con Finestra Google' o 'Carica le mie Playlist'.",
                    font=ctk.CTkFont(size=11),
                    text_color="#64748b",
                ).pack(padx=10, pady=8)
                return

            ctk.CTkLabel(
                pl_list_frame,
                text=f"📚 Le tue Playlist su YouTube Music ({len(playlists)}):",
                font=ctk.CTkFont(size=12, weight="bold"),
            ).pack(anchor="w", padx=10, pady=(8, 4))

            for pl in playlists[:15]:
                row_p = ctk.CTkFrame(pl_list_frame, fg_color="#131822", corner_radius=6)
                row_p.pack(fill="x", padx=8, pady=3)
                ctk.CTkLabel(
                    row_p,
                    text=f"🎵 {pl.get('title', 'Playlist')}",
                    font=ctk.CTkFont(size=12, weight="bold"),
                ).pack(side="left", padx=10, pady=6)

                def play_this_pl(pid: str = pl["playlistId"], title: str = pl.get("title", "")) -> None:
                    lbl_auth_status.configure(text=f"⏳ Carico brani di '{title}'...")
                    def w() -> None:
                        try:
                            data = self.ytm_service.get_playlist_tracks(pid, limit=35)
                            self._post_ui(lambda: (
                                self._apply_mood_tracks(data.get("tracks", [])),
                                lbl_auth_status.configure(text=f"🔊 In riproduzione: {title}"),
                            ))
                        except Exception as e:
                            self._post_ui(lambda: messagebox.showerror("Errore", str(e)))
                    threading.Thread(target=w, daemon=True).start()

                ctk.CTkButton(
                    row_p, text="▶️ Riproduci", width=95, height=26, command=play_this_pl
                ).pack(side="right", padx=6, pady=4)

        def start_window_login() -> None:
            lbl_auth_status.configure(
                text="⏳ Finestra aperta! Effettua l'accesso a Google nella finestra che si è aperta...",
                text_color="#fbbf24",
            )
            def worker() -> None:
                try:
                    res = self.ytm_service.login_with_browser_window()
                    self._post_ui(
                        lambda: (
                            lbl_auth_status.configure(
                                text=f"✅ Account Collegato con successo! ({res['playlists_count']} playlist trovate)",
                                text_color="#10b981",
                            ),
                            render_user_playlists(res.get("playlists", [])),
                        )
                    )
                except Exception as e:
                    self._post_ui(
                        lambda: lbl_auth_status.configure(
                            text=f"⚠️ {e}", text_color="#ef4444"
                        )
                    )
            threading.Thread(target=worker, daemon=True).start()

        def load_my_playlists() -> None:
            if not self.ytm_service.is_authenticated:
                messagebox.showinfo("Info", "Clicca prima su '🔑 Accedi con Finestra Google / YouTube Music'!")
                return
            pls = self.ytm_service.get_user_playlists(limit=30)
            render_user_playlists(pls)

        ctk.CTkButton(
            btn_login_row,
            text="🔑 Accedi con Finestra Google / YouTube Music (1 Clic)",
            fg_color="#059669",
            hover_color="#10b981",
            height=36,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=start_window_login,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_login_row,
            text="🔄 Carica le mie Playlist",
            fg_color="#1e293b",
            height=36,
            command=load_my_playlists,
        ).pack(side="left", padx=4)

        if self.ytm_service.is_authenticated:
            render_user_playlists(self.ytm_service.get_user_playlists(limit=20))
        else:
            render_user_playlists([])

        b1 = ctk.CTkFrame(scroll, fg_color="#131822", corner_radius=10)
        b1.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(
            b1,
            text="2. Importa o Abbina una Playlist tramite Link (Funziona anche senza login)",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(anchor="w", padx=12, pady=(10, 4))

        ent_pl_url = ctk.CTkEntry(b1, placeholder_text="Incolla link playlist: https://music.youtube.com/playlist?list=PL...")
        ent_pl_url.pack(fill="x", padx=12, pady=4)

        combo_assign = ctk.CTkOptionMenu(b1, values=mood_choices)
        combo_assign.pack(fill="x", padx=12, pady=4)

        lbl_pl_res = ctk.CTkLabel(b1, text="", text_color="#10b981")
        lbl_pl_res.pack(anchor="w", padx=12)

        def import_pl() -> None:
            url = ent_pl_url.get().strip()
            if not url:
                return
            lbl_pl_res.configure(text="⏳ Caricamento playlist...")

            def worker() -> None:
                try:
                    pl_data = self.ytm_service.get_playlist_tracks(url, limit=35)
                    sel = combo_assign.get()
                    if "::" in sel:
                        mid = sel.split("::")[0].strip()
                        if mid in prof["moods"]:
                            prof["moods"][mid]["custom_playlist"] = pl_data["playlistId"]
                            save_config(self.cfg)
                    self._post_ui(
                        lambda: (
                            lbl_pl_res.configure(
                                text=f"✅ Playlist '{pl_data['title']}' ({pl_data['trackCount']} brani) caricata!"
                            ),
                            self._render_moods_grid(),
                            self._apply_mood_tracks(pl_data.get("tracks", [])),
                        )
                    )
                except Exception as e:
                    self._post_ui(lambda: lbl_pl_res.configure(text=f"⚠️ Errore: {e}", text_color="#ef4444"))

            threading.Thread(target=worker, daemon=True).start()

        ctk.CTkButton(b1, text="📥 Importa e Riproduci Playlist", command=import_pl).pack(
            anchor="e", padx=12, pady=8
        )

        b2 = ctk.CTkFrame(scroll, fg_color="#131822", corner_radius=10)
        b2.pack(fill="x", pady=4)
        ctk.CTkLabel(
            b2,
            text="3. Metodo Alternativo Manuale (Incolla cURL, Cookie o Request Headers)",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=12, pady=(8, 4))

        txt_headers = ctk.CTkTextbox(b2, height=75)
        txt_headers.pack(fill="x", padx=12, pady=4)

        def connect_acc() -> None:
            raw = txt_headers.get("1.0", "end").strip()
            if not raw:
                return
            try:
                res = self.ytm_service.connect_with_headers(raw)
                lbl_auth_status.configure(
                    text=f"✅ Account Collegato — {res['playlists_count']} playlist trovate",
                    text_color="#10b981",
                )
                render_user_playlists(res.get("playlists", []))
            except Exception as e:
                messagebox.showerror("Errore autenticazione", str(e))

        ctk.CTkButton(b2, text="🔗 Collega tramite Testo Incollato", command=connect_acc).pack(
            anchor="e", padx=12, pady=8
        )

    def _open_ai_settings_dialog(self) -> None:
        win = ctk.CTkToplevel(self)
        win.title("🧠 Impostazioni Riconoscimento Vocale & Intelligenza Artificiale")
        win.geometry("620x650")
        win.transient(self)
        win.grab_set()

        an_cfg = self.cfg.get("analyzer", {})
        scroll = ctk.CTkScrollableFrame(win, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=14, pady=14)

        info_box = ctk.CTkFrame(scroll, fg_color="#131822", corner_radius=8)
        info_box.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(
            info_box,
            text="💡 Cosa significa 'Provider AI' e serve davvero?\n"
                 "• L'app funziona GIÀ SUBITO al 100% gratis grazie al suo dizionario interno italiano (che riconosce parole e frasi come 'spada', 'locanda', 'tirate iniziativa').\n"
                 "• Il 'Provider AI' è OPZIONALE: serve solo se vuoi collegare un'Intelligenza Artificiale esterna (come Google Gemini, ChatGPT o Ollama sul tuo PC) per far capire all'app anche frasi poetiche o implicite dove non pronunci nessuna parola chiave.\n"
                 "• Se non vuoi usare una chiave AI esterna, scegli 'keywords' (Solo Parole Chiave) o lascia così com'è!",
            font=ctk.CTkFont(size=11),
            text_color="#cbd5e1",
            wraplength=560,
            justify="left",
        ).pack(padx=12, pady=10)

        ctk.CTkLabel(scroll, text="Modalità di Analisi:", font=ctk.CTkFont(weight="bold")).pack(anchor="w")
        mode_combo = ctk.CTkOptionMenu(scroll, values=["hybrid", "keywords", "ai_always"])
        mode_combo.set(an_cfg.get("mode", "hybrid"))
        mode_combo.pack(fill="x", pady=(4, 10))

        ctk.CTkLabel(scroll, text="Cooldown tra cambi musica automatici (secondi):", font=ctk.CTkFont(weight="bold")).pack(
            anchor="w"
        )
        ent_cd = ctk.CTkEntry(scroll)
        ent_cd.insert(0, str(an_cfg.get("cooldown_seconds", 18)))
        ent_cd.pack(fill="x", pady=(4, 10))

        ctk.CTkLabel(
            scroll,
            text="Servizio AI Opzionale (Provider AI: 'gemini' = Google, 'ollama' = PC locale, 'openai' = ChatGPT):",
            font=ctk.CTkFont(weight="bold"),
        ).pack(anchor="w")
        prov_combo = ctk.CTkOptionMenu(scroll, values=["gemini", "ollama", "openai"])
        prov_combo.set(an_cfg.get("ai_provider", "gemini"))
        prov_combo.pack(fill="x", pady=(4, 10))

        ctk.CTkLabel(scroll, text="Google Gemini API Key (Opzionale - gratuita su aistudio.google.com):", font=ctk.CTkFont(weight="bold")).pack(anchor="w")
        ent_gem_key = ctk.CTkEntry(scroll, show="*")
        ent_gem_key.insert(0, an_cfg.get("gemini_api_key", ""))
        ent_gem_key.pack(fill="x", pady=(4, 10))

        ctk.CTkLabel(scroll, text="Ollama URL & Modello (Opzionale - se hai Ollama installato sul PC):", font=ctk.CTkFont(weight="bold")).pack(
            anchor="w"
        )
        ent_ol_url = ctk.CTkEntry(scroll)
        ent_ol_url.insert(0, an_cfg.get("ollama_url", "http://localhost:11434"))
        ent_ol_url.pack(fill="x", pady=(4, 4))
        ent_ol_mod = ctk.CTkEntry(scroll)
        ent_ol_mod.insert(0, an_cfg.get("ollama_model", "llama3.2"))
        ent_ol_mod.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(scroll, text="OpenAI API Key (Opzionale - ChatGPT):", font=ctk.CTkFont(weight="bold")).pack(anchor="w")
        ent_oa_key = ctk.CTkEntry(scroll, show="*")
        ent_oa_key.insert(0, an_cfg.get("openai_api_key", ""))
        ent_oa_key.pack(fill="x", pady=(4, 14))

        def save_ai() -> None:
            self.cfg["analyzer"].update(
                {
                    "mode": mode_combo.get(),
                    "cooldown_seconds": int(float(ent_cd.get() or 18)),
                    "ai_provider": prov_combo.get(),
                    "gemini_api_key": ent_gem_key.get().strip(),
                    "ollama_url": ent_ol_url.get().strip(),
                    "ollama_model": ent_ol_mod.get().strip(),
                    "openai_api_key": ent_oa_key.get().strip(),
                }
            )
            save_config(self.cfg)
            self._sync_ui_from_config()
            win.destroy()

        def reset_prof() -> None:
            if messagebox.askyesno("Ripristina", "Ripristinare i profili predefiniti?"):
                self.cfg = reset_default_profiles()
                self._sync_ui_from_config()
                win.destroy()

        ctk.CTkButton(scroll, text="💾 Salva Impostazioni", height=36, command=save_ai).pack(fill="x", pady=6)
        ctk.CTkButton(
            scroll, text="🔄 Ripristina Profili Predefiniti", fg_color="#1e293b", command=reset_prof
        ).pack(fill="x", pady=4)

    def _on_close(self) -> None:
        self.voice_listener.stop()
        self.sfx_manager.shutdown()
        self.player.shutdown()
        self.destroy()


if __name__ == "__main__":
    app = BardoDesktopApp()
    app.mainloop()
