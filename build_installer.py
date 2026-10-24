"""
Script di generazione dell'eseguibile e dell'installer distribuibile di Bardo AI v2.6.2:
Autore: Paolo Basta
1. Verifica/compila `BardoAI.exe` tramite PyInstaller e `BardoAI.spec` (PySide6, PyAV, Zero VLC).
2. Crea l'archivio payload compresso con `BardoAI.exe`, `sfx/*.wav`, `bardo_icon.ico` e `LEGGIMI.txt`.
3. Compila il setup finale `BardoAI_Setup.exe`.
4. Calcola le impronte crittografiche SHA-256 e genera `dist/SHA256SUMS.txt`.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from PIL import Image, ImageDraw

BASE_DIR = Path(__file__).resolve().parent
ICON_PATH = BASE_DIR / "bardo_icon.ico"
PAYLOAD_ZIP = BASE_DIR / "installer_payload.zip"


def get_pyinstaller_cmd() -> str:
    """Risolve in modo affidabile il percorso dell'eseguibile PyInstaller (venv, script o PATH)."""
    candidates = [
        BASE_DIR / ".venv" / "Scripts" / "pyinstaller.exe",
        Path(sys.executable).parent / "Scripts" / "pyinstaller.exe",
        Path(sys.executable).parent / "pyinstaller.exe",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    which_cmd = shutil.which("pyinstaller")
    if which_cmd:
        return which_cmd
    return "pyinstaller"


def ensure_bardo_icon() -> None:
    """Genera l'icona `.ico` solo se non già presente nel repository (risolve bug #29 di bastaaaa.md)."""
    if ICON_PATH.is_file():
        print(f"[1/5] Icona esistente trovata: {ICON_PATH.name} (nessuna sovrascrittura)")
        return

    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Scudo circolare blu notte con bordo dorato
    draw.ellipse((8, 8, 248, 248), fill=(15, 23, 42, 255), outline=(245, 158, 11, 255), width=10)
    draw.ellipse((24, 24, 232, 232), fill=(30, 27, 75, 255), outline=(251, 191, 36, 200), width=4)

    # Cassa del Liuto
    draw.ellipse((68, 106, 174, 212), fill=(217, 119, 6, 255), outline=(254, 243, 199, 255), width=5)
    draw.ellipse((103, 141, 139, 177), fill=(69, 26, 3, 255), outline=(251, 191, 36, 255), width=3)

    img.save(
        ICON_PATH,
        format="ICO",
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
    )
    print(f"[1/5] Icona generata: {ICON_PATH}")


def build_bardo_exe() -> None:
    """Compila BardoAI.exe usando BardoAI.spec senza sovrascriverlo."""
    pyinstaller_cmd = get_pyinstaller_cmd()
    print("[2/5] Compilazione di BardoAI.exe (PySide6 + PyAV)...")
    subprocess.run([pyinstaller_cmd, "--noconfirm", "BardoAI.spec"], cwd=str(BASE_DIR), check=True)
    dist_exe = BASE_DIR / "dist" / "BardoAI.exe"
    if dist_exe.is_file():
        shutil.copy2(dist_exe, BASE_DIR / "BardoAI.exe")


def build_payload_zip() -> None:
    """Crea `installer_payload.zip` (100% privo di VLC, zero file DLL di terze parti non necessarie)."""
    print("[3/5] Creazione archivio payload per l'installer (motore PyAV interno, zero VLC)...")
    readme_text = """====================================================================
🪕 BARDO AI v2.6.2 — REGIA MUSICALE INTELLIGENTE & SOUNDBOARD GDR
Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
====================================================================

Benvenuto in Bardo AI v2.6.2!
Tutto il necessario (incluso il motore audio sounddevice + PyAV e i
20 effetti sonori stereo GdR) è già contenuto in questa cartella.

COME INIZIARE:
1. Avvia "Bardo AI" dall'icona sul Desktop o nel Menu Start.
2. Parla liberamente in italiano durante la sessione GdR.
3. Gli effetti sonori (spade, frecce, magie, ruggiti, dadi) scattano
   in tempo reale a latenza zero con audio ducking automatico!
"""
    with zipfile.ZipFile(PAYLOAD_ZIP, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        exe_path = BASE_DIR / "BardoAI.exe"
        if exe_path.is_file():
            zf.write(exe_path, "BardoAI.exe")
        if ICON_PATH.is_file():
            zf.write(ICON_PATH, "bardo_icon.ico")
        zf.writestr("LEGGIMI.txt", readme_text)

        sfx_dir = BASE_DIR / "sfx"
        if sfx_dir.is_dir():
            for wav in sorted(sfx_dir.glob("*.wav")):
                zf.write(wav, f"sfx/{wav.name}")

    if PAYLOAD_ZIP.is_file():
        size_mb = PAYLOAD_ZIP.stat().st_size / (1024 * 1024)
        print(f"      -> Payload creato: {PAYLOAD_ZIP.name} ({size_mb:.1f} MB)")


def build_setup_exe() -> None:
    """Compila BardoAI_Setup.exe usando BardoAI_Setup.spec."""
    pyinstaller_cmd = get_pyinstaller_cmd()
    print("[4/5] Compilazione di BardoAI_Setup.exe...")
    subprocess.run([pyinstaller_cmd, "--noconfirm", "BardoAI_Setup.spec"], cwd=str(BASE_DIR), check=True)
    dist_exe = BASE_DIR / "dist" / "BardoAI_Setup.exe"
    if dist_exe.is_file():
        shutil.copy2(dist_exe, BASE_DIR / "BardoAI_Setup.exe")


def calculate_sha256(filepath: Path) -> str:
    """Calcola l'hash crittografico SHA-256 di un file a blocchi di 64KB."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def generate_checksums() -> None:
    """Genera il file standard SHA256SUMS.txt per tutti i binari presenti in dist/."""
    dist_dir = BASE_DIR / "dist"
    files = ["BardoAI.exe", "BardoAI_Setup.exe"]
    lines = []
    print("[5/5] Generazione impronte crittografiche SHA-256...")
    for fname in files:
        target = dist_dir / fname
        if target.is_file():
            digest = calculate_sha256(target)
            lines.append(f"{digest}  {fname}")
            print(f"      -> {fname}: {digest}")

    if lines:
        sums_file = dist_dir / "SHA256SUMS.txt"
        sums_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"      -> File generato con successo: {sums_file.name}")


if __name__ == "__main__":
    ensure_bardo_icon()
    if "--quick-setup" not in sys.argv or not (BASE_DIR / "BardoAI.exe").exists():
        build_bardo_exe()
    build_payload_zip()
    if "--skip-installer-exe" not in sys.argv:
        build_setup_exe()
    generate_checksums()
    print("[COMPLETATO] Build completato con successo!")
