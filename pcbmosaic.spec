# -*- mode: python ; coding: utf-8 -*-
"""
Spec PyInstaller pour produire un .exe Windows portable.

Utilisation :

    pip install pyinstaller
    pyinstaller pcbmosaic.spec --clean --noconfirm

Le binaire arrive dans dist\\PCB-Mosaic-Maker.exe.

Notes :
- ``--onefile`` : le binaire embarque tout (Python + Qt + OpenCV + skimage).
- ``console=False`` : pas de fenêtre console au lancement.
- Les modules Qt non utilisés (WebEngine, Multimedia, Charts, 3D…) sont
  exclus pour faire descendre le binaire de ~280 MB à ~150 MB.
"""
from PyInstaller.utils.hooks import collect_submodules


# Ce qui est inutile pour ce projet et alourdit beaucoup le binaire.
EXCLUDED = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebChannel",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DExtras",
    "PySide6.QtBluetooth",
    "PySide6.QtNetworkAuth",
    "PySide6.QtPositioning",
    "PySide6.QtLocation",
    "PySide6.QtNfc",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtTextToSpeech",
    "tkinter",
    "matplotlib",
    "pandas",
    "PyQt5",
    "PyQt6",
]


# scikit-image charge ses sous-modules dynamiquement → on les déclare.
HIDDEN = list(set(
    collect_submodules("skimage.metrics")
    + collect_submodules("skimage.transform")
    + collect_submodules("skimage._shared")
))


a = Analysis(
    ["run.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=HIDDEN,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDED,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="PCB-Mosaic-Maker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
