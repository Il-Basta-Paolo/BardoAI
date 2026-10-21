"""
Inizializzatore automatico del motore LibVLC embedded.
Permette a Bardo AI di funzionare su qualsiasi PC Windows (anche di amici che non hanno
VLC Media Player installato) caricando `libvlc.dll`, `libvlccore.dll` e `plugins/`
dalla sottocartella locale `vlc/` distribuita dall'installer.
"""

import os
import sys
from pathlib import Path


def ensure_vlc_environment() -> None:
    candidates = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "vlc")
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "vlc")
    else:
        src_dir = Path(__file__).resolve().parent
        candidates.append(src_dir / "vlc")

    # Fallback alle installazioni standard di sistema se presenti
    candidates.extend([
        Path(r"C:\Program Files\VideoLAN\VLC"),
        Path(r"C:\Program Files (x86)\VideoLAN\VLC"),
    ])

    for vlc_dir in candidates:
        libvlc_dll = vlc_dir / "libvlc.dll"
        plugins_dir = vlc_dir / "plugins"
        if libvlc_dll.exists() and plugins_dir.exists():
            vlc_str = str(vlc_dir.resolve())
            os.environ["PYTHON_VLC_MODULE_PATH"] = vlc_str
            os.environ["PYTHON_VLC_LIB_PATH"] = str(libvlc_dll.resolve())
            os.environ["VLC_PLUGIN_PATH"] = str(plugins_dir.resolve())
            os.environ["PATH"] = vlc_str + os.pathsep + os.environ.get("PATH", "")
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(vlc_str)
                except Exception:
                    pass
            break


ensure_vlc_environment()
