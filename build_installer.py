"""
Script di generazione completa dell'Installer distribuibile `BardoAI_Setup.exe`:
1. Genera l'icona multi-risoluzione `bardo_icon.ico` (scudo dorato GdR con liuto/nota musicale).
2. Compila `BardoAI.exe` con l'icona integrata e i 20 effetti sonori stereo.
3. Crea l'archivio compresso `installer_payload.zip` includendo:
   - `BardoAI.exe` + `bardo_icon.ico`
   - `sfx/*.wav` (20 effetti sonori stereo rimasterizzati)
   - `vlc/` (`libvlc.dll`, `libvlccore.dll` e plugin audio/rete di VLC)
   - `LEGGIMI.txt`
4. Compila il Setup Wizard grafico (`installer_gui.py`) nel singolo file `BardoAI_Setup.exe`.
"""

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from PIL import Image, ImageDraw

BASE_DIR = Path(__file__).resolve().parent
ICON_PATH = BASE_DIR / "bardo_icon.ico"
PAYLOAD_ZIP = BASE_DIR / "installer_payload.zip"
VLC_SYSTEM_DIR = Path(r"C:\Program Files\VideoLAN\VLC")

# Cartelle di plugin VLC necessarie per lo streaming audio HTTP/HTTPS e la decodifica (zero video pesante)
VLC_PLUGIN_FOLDERS = [
    "access",
    "audio_filter",
    "audio_mixer",
    "audio_output",
    "codec",
    "demux",
    "keystore",
    "logger",
    "meta_engine",
    "misc",
    "packetizer",
    "stream_extractor",
    "stream_filter",
]

# Escludiamo solo i pesanti encoder/decoder esclusivamente video per mantenere l'installer leggero e veloce
EXCLUDED_VIDEO_CODECS = {
    "libx265_plugin.dll",
    "libx264_plugin.dll",
    "libx26410b_plugin.dll",
    "libaom_plugin.dll",
    "libdav1d_plugin.dll",
    "liblibass_plugin.dll",
    "libzvbi_plugin.dll",
    "libqsv_plugin.dll",
    "libvpx_plugin.dll",
    "libtheora_plugin.dll",
    "libaribsub_plugin.dll",
    "libdxva2_plugin.dll",
    "libd3d11va_plugin.dll",
    "libjpeg_plugin.dll",
    "libpng_plugin.dll",
    "libsvgdec_plugin.dll",
    "libschroedinger_plugin.dll",
    "libtwolame_plugin.dll",
}


def generate_bardo_icon() -> None:
    """Disegna un'icona `.ico` ad alta risoluzione (256x256 -> 16x16) per Bardo AI."""
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Scudo circolare blu notte / cremisi con doppio bordo dorato
    draw.ellipse((8, 8, 248, 248), fill=(15, 23, 42, 255), outline=(245, 158, 11, 255), width=10)
    draw.ellipse((24, 24, 232, 232), fill=(30, 27, 75, 255), outline=(251, 191, 36, 200), width=4)

    # Cassa armonica del Liuto del Bardo (oro ambrato / legno caldo)
    draw.ellipse((68, 106, 174, 212), fill=(217, 119, 6, 255), outline=(254, 243, 199, 255), width=5)
    # Rosone centrale del liuto
    draw.ellipse((103, 141, 139, 177), fill=(69, 26, 3, 255), outline=(251, 191, 36, 255), width=3)

    # Manico diagonale del liuto
    neck_pts = [(142, 112), (158, 128), (206, 64), (188, 48)]
    draw.polygon(neck_pts, fill=(180, 83, 9, 255), outline=(254, 243, 199, 255))

    # Paletta del liuto
    head_pts = [(188, 48), (206, 64), (222, 52), (204, 36)]
    draw.polygon(head_pts, fill=(245, 158, 11, 255))

    # Corde dorate luminose
    draw.line((112, 168, 194, 54), fill=(254, 240, 138, 255), width=3)
    draw.line((122, 176, 200, 60), fill=(254, 240, 138, 255), width=3)

    # Nota musicale magica (verde smeraldo/oro) in alto a sinistra
    draw.ellipse((54, 72, 82, 96), fill=(16, 185, 129, 255))
    draw.rectangle((76, 42, 84, 84), fill=(16, 185, 129, 255))
    draw.polygon([(76, 42), (106, 50), (106, 62), (76, 54)], fill=(52, 211, 153, 255))

    img.save(
        ICON_PATH,
        format="ICO",
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
    )
    print(f"[1/4] Icona generata: {ICON_PATH}")


def update_main_spec_and_build() -> None:
    """Aggiorna BardoAI.spec per includere `bardo_icon.ico` e ricompila `BardoAI.exe`."""
    spec_content = """# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('sfx', 'sfx'), ('bardo_icon.ico', '.')]
binaries = []
hiddenimports = []
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('ytmusicapi')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('_sounddevice_data')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['desktop_app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='BardoAI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='bardo_icon.ico',
)
"""
    (BASE_DIR / "BardoAI.spec").write_text(spec_content, encoding="utf-8")
    pyinstaller_exe = BASE_DIR / ".venv" / "Scripts" / "pyinstaller.exe"
    print("[2/4] Compilazione di BardoAI.exe con icona personalizzata...")
    subprocess.run([str(pyinstaller_exe), "--noconfirm", "BardoAI.spec"], cwd=str(BASE_DIR), check=True)
    shutil.copy2(BASE_DIR / "dist" / "BardoAI.exe", BASE_DIR / "BardoAI.exe")


def build_payload_zip() -> None:
    """Crea `installer_payload.zip` con BardoAI.exe, sfx/*.wav, bardo_icon.ico e il runtime VLC."""
    print("[3/4] Creazione archivio payload per l'installer (con motore VLC e SFX Stereo)...")
    readme_text = """====================================================================
🪕 BARDO AI — REGIA MUSICALE & SOUNDBOARD VOCALE PER GDR
====================================================================

Benvenuto in Bardo AI!
Non devi installare nient'altro: tutto il necessario (incluso il motore
audio e i 20 effetti sonori stereo) è già presente in questa cartella.

COME INIZIARE:
1. Avvia "Bardo AI" dall'icona sul Desktop o nel Menu Start.
2. Clicca su "🎙️ Avvia Ascolto Vocale" e parla normalmente in italiano
   durante la tua sessione GdR (es. "Entrate in una locanda",
   "Siete in una valle innevata", "Inizia il combattimento!").
3. Pronuncia azioni come "Ti colpisce con la sua spada!" o clicca sui
   pulsanti della Soundboard per attivare gli effetti sonori.
4. Dalle "⚙️ Impostazioni" in alto a destra puoi collegare facoltativamente
   il tuo account Spotify o YouTube Music con 1 click!
"""
    with zipfile.ZipFile(PAYLOAD_ZIP, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.write(BASE_DIR / "BardoAI.exe", "BardoAI.exe")
        zf.write(ICON_PATH, "bardo_icon.ico")
        zf.writestr("LEGGIMI.txt", readme_text)

        for wav in sorted((BASE_DIR / "sfx").glob("*.wav")):
            zf.write(wav, f"sfx/{wav.name}")

        if VLC_SYSTEM_DIR.exists():
            for dll_name in ("libvlc.dll", "libvlccore.dll"):
                dll_path = VLC_SYSTEM_DIR / dll_name
                if dll_path.exists():
                    zf.write(dll_path, f"vlc/{dll_name}")

            plugins_root = VLC_SYSTEM_DIR / "plugins"
            plugins_dat = plugins_root / "plugins.dat"
            if plugins_dat.exists():
                zf.write(plugins_dat, "vlc/plugins/plugins.dat")

            for folder in VLC_PLUGIN_FOLDERS:
                sub = plugins_root / folder
                if not sub.exists():
                    continue
                for f in sub.rglob("*.dll"):
                    if f.name.lower() in EXCLUDED_VIDEO_CODECS:
                        continue
                    rel = f.relative_to(plugins_root).as_posix()
                    zf.write(f, f"vlc/plugins/{rel}")

    size_mb = PAYLOAD_ZIP.stat().st_size / (1024 * 1024)
    print(f"      -> Payload creato: {PAYLOAD_ZIP.name} ({size_mb:.1f} MB)")


def build_setup_exe() -> None:
    """Compila `installer_gui.py` nel singolo eseguibile distribuibile `BardoAI_Setup.exe`."""
    print("[4/4] Compilazione dell'installer grafico BardoAI_Setup.exe...")
    pyinstaller_exe = BASE_DIR / ".venv" / "Scripts" / "pyinstaller.exe"
    cmd = [
        str(pyinstaller_exe),
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--name",
        "BardoAI_Setup",
        "--icon",
        str(ICON_PATH),
        "--add-data",
        f"{PAYLOAD_ZIP};.",
        "--add-data",
        f"{ICON_PATH};.",
        "--collect-all",
        "customtkinter",
        "installer_gui.py",
    ]
    subprocess.run(cmd, cwd=str(BASE_DIR), check=True)
    dist_setup = BASE_DIR / "dist" / "BardoAI_Setup.exe"
    target_setup = BASE_DIR / "BardoAI_Setup.exe"
    shutil.copy2(dist_setup, target_setup)
    PAYLOAD_ZIP.unlink(missing_ok=True)
    setup_mb = target_setup.stat().st_size / (1024 * 1024)
    print(f"\n[COMPLETATO] Installer pronto: {target_setup} ({setup_mb:.1f} MB)")


if __name__ == "__main__":
    generate_bardo_icon()
    if "--quick-setup" not in sys.argv or not (BASE_DIR / "BardoAI.exe").exists():
        update_main_spec_and_build()
    build_payload_zip()
    build_setup_exe()
