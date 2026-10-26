"""
Bardo AI — Installazione Guidata (Setup Wizard Grafico per Windows).
Permette di scegliere liberamente qualsiasi cartella o disco di destinazione:
- Selezione tramite finestra "📂 Sfoglia Cartella..." di Windows
- Digitazione manuale di qualsiasi percorso
- Pulsanti rapidi per Cartella Utente, C:\\BardoAI, Program Files e tutti i dischi fissi rilevati (D:\\, E:\\, ecc.)
- Verifica in tempo reale dello spazio disponibile sul disco scelto
- Elevazione automatica UAC (Amministratore) se l'utente sceglie cartelle di sistema come C:\\Program Files
"""

import ctypes
import os
import shutil
import subprocess
import sys
import threading
import winreg
import zipfile
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import List, Tuple
import customtkinter as ctk


APP_NAME = "Bardo AI"
APP_VERSION = "2.6.3"
APP_PUBLISHER = "Paolo Basta"
EXE_NAME = "BardoAI.exe"
REQUIRED_SPACE_MB = 260


def get_bundled_resource(filename: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / filename


def get_default_install_dir() -> Path:
    local_appdata = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local_appdata) / "Programs" / "BardoAI"


def get_available_drives() -> List[str]:
    """Rileva tutte le unità disco disponibili su Windows (es. ['C:\\', 'D:\\'])."""
    drives = []
    try:
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for i in range(26):
            if bitmask & (1 << i):
                drive = f"{chr(65 + i)}:\\"
                if os.path.exists(drive):
                    drives.append(drive)
    except Exception:
        drives = ["C:\\"]
    return drives


def can_write_to_location(target_dir: Path) -> bool:
    """Verifica se l'utente corrente ha i permessi di scrittura nel percorso selezionato."""
    probe_dir = target_dir
    while not probe_dir.exists() and probe_dir.parent != probe_dir:
        probe_dir = probe_dir.parent
    try:
        test_file = probe_dir / f".bardo_setup_probe_{os.getpid()}"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def get_free_space_gb(target_dir: Path) -> Tuple[float, str]:
    """Restituisce lo spazio libero in GB sull'unità disco del percorso selezionato."""
    probe_dir = target_dir
    while not probe_dir.exists() and probe_dir.parent != probe_dir:
        probe_dir = probe_dir.parent
    try:
        usage = shutil.disk_usage(str(probe_dir))
        free_gb = usage.free / (1024 ** 3)
        drive_root = probe_dir.drive or str(probe_dir)[:3]
        return free_gb, drive_root
    except Exception:
        return 0.0, "Disco"


def get_user_desktop_dir() -> Path:
    """Restituisce il percorso reale del Desktop dell'utente, gestendo anche OneDrive e percorsi reindirizzati."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            val, _ = winreg.QueryValueEx(k, "Desktop")
            expanded = os.path.expandvars(val)
            if Path(expanded).is_dir():
                return Path(expanded)
    except Exception:
        pass
    home = Path.home()
    if (home / "OneDrive" / "Desktop").is_dir():
        return home / "OneDrive" / "Desktop"
    return home / "Desktop"


def create_windows_shortcut(target_path: Path, shortcut_path: Path, icon_path: Path, description: str) -> None:
    """Crea un collegamento .lnk su Windows gestendo correttamente caratteri speciali e apostrofi (risolve bug #21)."""
    shortcut_path.parent.mkdir(parents=True, exist_ok=True)
    esc_sc = str(shortcut_path).replace("'", "''")
    esc_target = str(target_path).replace("'", "''")
    esc_work = str(target_path.parent).replace("'", "''")
    esc_icon = str(icon_path).replace("'", "''")
    esc_desc = str(description).replace("'", "''")
    ps_script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{esc_sc}'); "
        f"$s.TargetPath = '{esc_target}'; "
        f"$s.WorkingDirectory = '{esc_work}'; "
        f"$s.IconLocation = '{esc_icon},0'; "
        f"$s.Description = '{esc_desc}'; "
        "$s.Save()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
    )


def register_uninstaller(install_dir: Path, uninstaller_bat: Path, icon_path: Path) -> None:
    """Registra Bardo AI in 'Impostazioni -> App installate'."""
    try:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\BardoAI"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "Bardo AI — Regia Musicale & Soundboard GdR")
            winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
            winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, APP_PUBLISHER)
            winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, str(icon_path))
            winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(install_dir))
            winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, f'cmd.exe /c "{str(uninstaller_bat)}"')
            winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
    except Exception:
        pass


def write_uninstaller_script(install_dir: Path) -> Path:
    """Crea uno script di disinstallazione sicuro che elimina solo i file di Bardo AI (risolve bug #18)."""
    desktop_lnk = get_user_desktop_dir() / "Bardo AI.lnk"
    start_menu_dir = (
        Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Bardo AI"
    )
    bat_path = install_dir / "Disinstalla_BardoAI.bat"
    bat_content = f"""@echo off
chcp 65001 >nul
title Disinstallazione di Bardo AI

echo Arresto di eventuali istanze di Bardo AI in esecuzione...
taskkill /F /IM BardoAI.exe >nul 2>&1
timeout /t 1 /nobreak >nul

echo Rimozione collegamenti Desktop e Menu Start...
if exist "{desktop_lnk}" del /F /Q "{desktop_lnk}"
if exist "{start_menu_dir}" rmdir /S /Q "{start_menu_dir}"

echo Rimozione voce dal registro di Windows...
reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\BardoAI" /f >nul 2>&1

echo Rimozione file dell'applicazione...
if exist "%~dp0BardoAI.exe" del /F /Q "%~dp0BardoAI.exe"
if exist "%~dp0bardo_icon.ico" del /F /Q "%~dp0bardo_icon.ico"
if exist "%~dp0LEGGIMI.txt" del /F /Q "%~dp0LEGGIMI.txt"
if exist "%~dp0sfx" rmdir /S /Q "%~dp0sfx"

echo Rimozione directory Bardo AI se vuota...
cd /d "%TEMP%"
start /b "" cmd /c "timeout /t 2 /nobreak >nul & if exist \\"{install_dir}\\BardoAI.exe\\" (rem) else (rmdir \\"{install_dir}\\" >nul 2>&1)"
echo Disinstallazione completata con successo!
exit
"""
    bat_path.write_text(bat_content, encoding="utf-8")
    return bat_path


class BardoInstallerWizard(ctk.CTk):
    def __init__(self, initial_dir: str = "", auto_start: bool = False) -> None:
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.title(f"🪕 Installazione di {APP_NAME} v{APP_VERSION}")
        self.geometry("680x590")
        self.resizable(False, False)
        self.configure(fg_color="#0b0e14")

        ico = get_bundled_resource("bardo_icon.ico")
        if ico.exists():
            try:
                self.iconbitmap(str(ico))
            except Exception:
                pass

        start_dir = initial_dir.strip() if initial_dir.strip() else str(get_default_install_dir())
        self.install_dir_var = ctk.StringVar(value=start_dir)
        self.append_subfolder_var = ctk.BooleanVar(value=True)
        self.chk_desktop_var = ctk.BooleanVar(value=True)
        self.chk_startmenu_var = ctk.BooleanVar(value=True)
        self.chk_launch_var = ctk.BooleanVar(value=True)
        self._installing = False

        self._build_ui()
        self.install_dir_var.trace_add("write", lambda *_: self._update_disk_info())
        self._update_disk_info()

        if auto_start:
            self.after(250, self._start_installation)

    def _build_ui(self) -> None:
        # 1. Banner superiore
        header = ctk.CTkFrame(self, fg_color="#131822", corner_radius=0, height=86)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(fill="both", expand=True, padx=24, pady=12)

        ctk.CTkLabel(
            title_box,
            text=f"🪕 {APP_NAME} — Installazione Guidata per Windows",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#f8fafc",
            anchor="w",
        ).pack(fill="x")

        ctk.CTkLabel(
            title_box,
            text="Regia Musicale Automatica (Spotify & YouTube Music) + Soundboard Vocale GdR in Italiano",
            font=ctk.CTkFont(size=12),
            text_color="#fbbf24",
            anchor="w",
        ).pack(fill="x", pady=(3, 0))

        # 2. Corpo centrale
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=12)

        # Scheda scelta cartella di installazione (In primo piano!)
        dir_frame = ctk.CTkFrame(body, fg_color="#131822", corner_radius=10, border_width=2, border_color="#059669")
        dir_frame.pack(fill="x", pady=(0, 10))

        top_dir_row = ctk.CTkFrame(dir_frame, fg_color="transparent")
        top_dir_row.pack(fill="x", padx=14, pady=(10, 4))

        ctk.CTkLabel(
            top_dir_row,
            text="📂 Scegli dove installare Bardo AI:",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#f1f5f9",
            anchor="w",
        ).pack(side="left")

        self.lbl_disk_space = ctk.CTkLabel(
            top_dir_row,
            text="",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#34d399",
            anchor="e",
        )
        self.lbl_disk_space.pack(side="right")

        dir_row = ctk.CTkFrame(dir_frame, fg_color="transparent")
        dir_row.pack(fill="x", padx=14, pady=(2, 6))

        self.entry_dir = ctk.CTkEntry(
            dir_row,
            textvariable=self.install_dir_var,
            height=34,
            font=ctk.CTkFont(size=12),
            placeholder_text="Inserisci o sfoglia il percorso di installazione...",
        )
        self.entry_dir.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.btn_browse = ctk.CTkButton(
            dir_row,
            text="📂 Sfoglia Cartella...",
            width=145,
            height=34,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#0284c7",
            hover_color="#0369a1",
            command=self._on_browse,
        )
        self.btn_browse.pack(side="right")

        # Pulsanti di scelta rapida percorso (Utente, C:\BardoAI, Program Files, Dischi D:\ / E:\ ...)
        presets_row = ctk.CTkFrame(dir_frame, fg_color="transparent")
        presets_row.pack(fill="x", padx=14, pady=(2, 6))

        ctk.CTkLabel(
            presets_row,
            text="Percorsi rapidi:",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8",
        ).pack(side="left", padx=(0, 6))

        presets = [
            ("🏠 AppData (Consigliato)", str(get_default_install_dir())),
            ("💿 C:\\BardoAI", r"C:\BardoAI"),
            ("🗂️ Program Files", r"C:\Program Files\BardoAI"),
        ]
        for drv in get_available_drives():
            if not drv.upper().startswith("C:"):
                presets.append((f"💾 Disco {drv[:2]}", f"{drv}BardoAI"))

        for label, target_p in presets[:5]:
            ctk.CTkButton(
                presets_row,
                text=label,
                height=24,
                width=90,
                font=ctk.CTkFont(size=11),
                fg_color="#1e293b",
                hover_color="#334155",
                command=lambda p=target_p: self.install_dir_var.set(p),
            ).pack(side="left", padx=3)

        ctk.CTkCheckBox(
            dir_frame,
            text="Aggiungi automaticamente la sottocartella '\\BardoAI' quando selezioni una cartella con 'Sfoglia'",
            variable=self.append_subfolder_var,
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8",
            checkbox_width=18,
            checkbox_height=18,
        ).pack(anchor="w", padx=14, pady=(2, 10))

        # Scheda contenuti inclusi
        features_card = ctk.CTkFrame(body, fg_color="#131822", corner_radius=10, border_width=1, border_color="#1e293b")
        features_card.pack(fill="x", pady=(0, 10))

        features_text = (
            "✨  Pacchetto All-in-One (non serve installare né Python né VLC Media Player):\n"
            "  •  Applicazione BardoAI.exe + Motore Audio LibVLC con Crossfade S-Curve integrato\n"
            "  •  Libreria di 20 Effetti Sonori GdR rimasterizzati in Stereo 3D + Login Spotify & YT Music"
        )
        ctk.CTkLabel(
            features_card,
            text=features_text,
            font=ctk.CTkFont(size=11),
            text_color="#cbd5e1",
            justify="left",
            anchor="w",
        ).pack(fill="x", padx=14, pady=8)

        # Opzioni collegamenti
        opts_frame = ctk.CTkFrame(body, fg_color="#131822", corner_radius=10, border_width=1, border_color="#1e293b")
        opts_frame.pack(fill="x", pady=(0, 10))

        ctk.CTkCheckBox(
            opts_frame,
            text="Crea icona sul Desktop (Bardo AI)",
            variable=self.chk_desktop_var,
            font=ctk.CTkFont(size=12),
            checkbox_width=20,
            checkbox_height=20,
        ).pack(anchor="w", padx=14, pady=(8, 4))

        ctk.CTkCheckBox(
            opts_frame,
            text="Crea collegamento nel Menu Start di Windows",
            variable=self.chk_startmenu_var,
            font=ctk.CTkFont(size=12),
            checkbox_width=20,
            checkbox_height=20,
        ).pack(anchor="w", padx=14, pady=4)

        ctk.CTkCheckBox(
            opts_frame,
            text="Avvia Bardo AI al termine dell'installazione",
            variable=self.chk_launch_var,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#34d399",
            checkbox_width=20,
            checkbox_height=20,
        ).pack(anchor="w", padx=14, pady=(4, 8))

        # Barra di progresso
        prog_frame = ctk.CTkFrame(body, fg_color="transparent")
        prog_frame.pack(fill="x", pady=(2, 0))

        self.lbl_status = ctk.CTkLabel(
            prog_frame,
            text="Scegli la cartella di destinazione e clicca su 'Installa Bardo AI'.",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8",
            anchor="w",
        )
        self.lbl_status.pack(fill="x", pady=(0, 4))

        self.progress = ctk.CTkProgressBar(prog_frame, height=12, progress_color="#10b981")
        self.progress.set(0.0)
        self.progress.pack(fill="x")

        # 3. Barra pulsanti inferiore
        footer = ctk.CTkFrame(self, fg_color="#131822", corner_radius=0, height=60)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)

        self.btn_cancel = ctk.CTkButton(
            footer,
            text="Annulla",
            width=110,
            height=36,
            fg_color="#1e293b",
            hover_color="#334155",
            command=self.destroy,
        )
        self.btn_cancel.pack(side="left", padx=24, pady=12)

        self.btn_install = ctk.CTkButton(
            footer,
            text="🚀 Installa Bardo AI",
            width=220,
            height=38,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#059669",
            hover_color="#047857",
            command=self._start_installation,
        )
        self.btn_install.pack(side="right", padx=24, pady=11)

    def _update_disk_info(self) -> None:
        raw_path = self.install_dir_var.get().strip()
        if not raw_path:
            self.lbl_disk_space.configure(text="Inserisci un percorso valido", text_color="#f87171")
            return
        try:
            target = Path(raw_path)
            free_gb, drive_label = get_free_space_gb(target)
            if free_gb > 0:
                needs_admin = not can_write_to_location(target)
                admin_tag = " (Richiede Admin 🛡️)" if needs_admin else ""
                self.lbl_disk_space.configure(
                    text=f"Richiesti: ~{REQUIRED_SPACE_MB} MB • Liberi su {drive_label}: {free_gb:.1f} GB{admin_tag}",
                    text_color="#fbbf24" if needs_admin else "#34d399",
                )
            else:
                self.lbl_disk_space.configure(text=f"Richiesti: ~{REQUIRED_SPACE_MB} MB", text_color="#94a3b8")
        except Exception:
            self.lbl_disk_space.configure(text="", text_color="#94a3b8")

    def _on_browse(self) -> None:
        current = self.install_dir_var.get().strip()
        initial = current if os.path.exists(current) else str(Path.home())
        chosen = filedialog.askdirectory(
            title="Scegli la cartella in cui installare Bardo AI",
            initialdir=initial,
        )
        if chosen:
            target = Path(chosen)
            if self.append_subfolder_var.get() and target.name.lower() not in ("bardoai", "bardo ai", "bardo_ai"):
                target = target / "BardoAI"
            self.install_dir_var.set(str(target))

    def _set_status(self, text: str, pct: float) -> None:
        self.after(0, lambda: (self.lbl_status.configure(text=text), self.progress.set(max(0.0, min(1.0, pct)))))

    def _start_installation(self) -> None:
        if self._installing:
            return
        raw_dir = self.install_dir_var.get().strip()
        if not raw_dir:
            messagebox.showwarning("Percorso Mancante", "Seleziona o inserisci una cartella dove installare Bardo AI.")
            return

        install_dir = Path(raw_dir)
        payload_zip = get_bundled_resource("installer_payload.zip")
        if not payload_zip.exists():
            messagebox.showerror("Errore Pacchetto", f"Archivio interno non trovato:\n{payload_zip}")
            return

        # Se l'utente ha scelto una cartella protetta di sistema (es. C:\Program Files\BardoAI),
        # richiede automaticamente l'elevazione UAC di Windows!
        if not can_write_to_location(install_dir):
            ans = messagebox.askyesno(
                "Permessi di Amministratore Richiesti",
                f"La cartella scelta:\n{install_dir}\n\n"
                "è una cartella di sistema protetta di Windows.\n"
                "Vuoi autorizzare l'installazione come Amministratore in questa cartella?",
            )
            if not ans:
                return
            try:
                params = f'--install-dir "{str(install_dir)}" --auto-start'
                ret = ctypes.windll.shell32.ShellExecuteW(
                    None, "runas", sys.executable, params, None, 1
                )
                if int(ret) > 32:
                    self.destroy()
                    return
            except Exception as e:
                messagebox.showerror("Errore Permessi", f"Impossibile ottenere i permessi di Amministratore:\n{e}")
                return

        self._installing = True
        self.btn_install.configure(state="disabled", text="⏳ Installazione in corso...")
        self.btn_browse.configure(state="disabled")
        self.entry_dir.configure(state="disabled")

        threading.Thread(target=self._install_worker, args=(install_dir, payload_zip), daemon=True).start()

    def _install_worker(self, install_dir: Path, payload_zip: Path) -> None:
        try:
            self._set_status("Chiusura di eventuali istanze aperte di Bardo AI...", 0.05)
            subprocess.run(
                ["taskkill", "/F", "/IM", EXE_NAME],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            )

            install_dir.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(payload_zip, "r") as zf:
                members = zf.infolist()
                total = max(1, len(members))
                for idx, member in enumerate(members, start=1):
                    pct = 0.08 + 0.78 * (idx / total)
                    short_name = Path(member.filename).name
                    if idx % 5 == 0 or idx == total or short_name == EXE_NAME:
                        self._set_status(f"Estrazione in {install_dir.name}: {short_name} ({idx}/{total})...", pct)
                    zf.extract(member, install_dir)

            exe_path = install_dir / EXE_NAME
            icon_path = install_dir / "bardo_icon.ico"
            if not icon_path.exists():
                icon_path = exe_path

            self._set_status("Configurazione disinstallatore e registro di Windows...", 0.90)
            uninstaller_bat = write_uninstaller_script(install_dir)
            register_uninstaller(install_dir, uninstaller_bat, icon_path)

            if self.chk_desktop_var.get():
                self._set_status("Creazione collegamento sul Desktop...", 0.94)
                desktop_dirs = [
                    Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop",
                    Path(os.environ.get("USERPROFILE", str(Path.home()))) / "OneDrive" / "Desktop",
                ]
                for d_dir in desktop_dirs:
                    if d_dir.exists():
                        create_windows_shortcut(
                            exe_path,
                            d_dir / "Bardo AI.lnk",
                            icon_path,
                            "Bardo AI — Regia Musicale & Soundboard Vocale per GdR",
                        )
                        break

            if self.chk_startmenu_var.get():
                self._set_status("Creazione collegamenti nel Menu Start...", 0.97)
                start_menu_dir = (
                    Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
                    / "Microsoft"
                    / "Windows"
                    / "Start Menu"
                    / "Programs"
                    / "Bardo AI"
                )
                create_windows_shortcut(
                    exe_path,
                    start_menu_dir / "Bardo AI.lnk",
                    icon_path,
                    "Avvia Bardo AI",
                )
                create_windows_shortcut(
                    uninstaller_bat,
                    start_menu_dir / "Disinstalla Bardo AI.lnk",
                    icon_path,
                    "Disinstalla Bardo AI",
                )

            self._set_status(f"✅ Installato con successo in: {install_dir}", 1.0)
            self.after(0, lambda: self._on_install_success(exe_path))

        except Exception as e:
            err_text = str(e)
            self._installing = False
            self.after(
                0,
                lambda msg=err_text: (
                    self.btn_install.configure(state="normal", text="🚀 Installa Bardo AI"),
                    self.btn_browse.configure(state="normal"),
                    self.entry_dir.configure(state="normal"),
                    messagebox.showerror("Errore durante l'installazione", f"Si è verificato un errore:\n{msg}"),
                ),
            )

    def _on_install_success(self, exe_path: Path) -> None:
        self.btn_install.configure(text="✅ Installato!", fg_color="#10b981")
        self.btn_cancel.configure(text="Chiudi")
        if self.chk_launch_var.get() and exe_path.exists():
            try:
                subprocess.Popen([str(exe_path)], cwd=str(exe_path.parent))
            except Exception:
                pass
            self.after(600, self.destroy)
        else:
            messagebox.showinfo(
                "Installazione Completata",
                f"Bardo AI è stato installato con successo nella cartella scelta:\n{exe_path.parent}\n\n"
                "Trovi l'icona 'Bardo AI' sul tuo Desktop e nel Menu Start!",
            )
            self.destroy()


if __name__ == "__main__":
    init_dir = ""
    auto_go = False
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--install-dir" and i + 1 < len(args):
            init_dir = args[i + 1]
        elif a == "--auto-start":
            auto_go = True
    app = BardoInstallerWizard(initial_dir=init_dir, auto_start=auto_go)
    app.mainloop()
