# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for AlohaMini Controller v3
# Run from repo root:
#   pyinstaller lerobot_alohamini/examples/alohamini/controller_v3.spec

from pathlib import Path
import sys

HERE = Path("lerobot_alohamini/examples/alohamini")
MESHES = Path("AlohaMini/simulation/src/Aloha/meshes")

a = Analysis(
    [str(HERE / "controller_v3.py")],
    pathex=["."],
    binaries=[],
    datas=[
        # Read-only HTML UI
        (str(HERE / "ui_main.html"),         "."),
        (str(HERE / "ui_settings.html"),     "."),
        (str(HERE / "ui_arm_settings.html"), "."),
        # 3D mesh files for arm visualiser
        (str(MESHES), "meshes"),
    ],
    hiddenimports=[
        "flask",
        "werkzeug",
        "zmq",
        "zmq.backend.cython",
        "pygame",
        "cv2",
        "numpy",
        "urllib.request",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib", "scipy", "pandas",
        "torch", "torchvision", "PIL",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="alohamini-controller",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,          # keep console for log output
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
