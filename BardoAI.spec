# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('sfx', 'sfx'), ('bardo_icon.ico', '.')]
binaries = []
hiddenimports = [
    'PySide6', 'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets',
    'av', 'sounddevice', 'numpy', 'keyring', 'pydantic',
    'vosk', 'faster_whisper', 'onnxruntime', 'httpx',
    'ui', 'ui.main_window', 'ui.styles',
    'ui.widgets.mood_grid', 'ui.widgets.soundboard',
    'ui.widgets.transport', 'ui.widgets.voice_monitor',
    'ui.dialogs.settings_dialog', 'ui.dialogs.shortcuts_dialog',
]

for mod in ['ytmusicapi', '_sounddevice_data', 'keyring', 'vosk', 'ctranslate2']:
    try:
        tmp = collect_all(mod)
        datas += tmp[0]
        binaries += tmp[1]
        hiddenimports += tmp[2]
    except Exception:
        pass

a = Analysis(
    ['desktop_app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'customtkinter', 'vlc', 'fastapi', 'uvicorn'],
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
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='bardo_icon.ico',
    version='version_bardo.txt',
)
