
# -*- mode: python ; coding: utf-8 -*-

# ============================================================
# CPLDD - PyInstaller Specification
# Portable Windows DLL Deployment Helper
#
# Build:
#   python -m PyInstaller --clean --noconfirm cpldd.spec
#
# Output:
#   dist/cpldd.exe
# ============================================================

from pathlib import Path

block_cipher = None

# ------------------------------------------------------------
# Project paths
# ------------------------------------------------------------

PROJECT_DIR = Path(SPECPATH).resolve()
ENTRY_SCRIPT = PROJECT_DIR / "cpldd.py"

if not ENTRY_SCRIPT.is_file():
    raise FileNotFoundError(
        f"CPLDD entry script not found: {ENTRY_SCRIPT}"
    )

# ------------------------------------------------------------
# Analysis
# ------------------------------------------------------------

a = Analysis(
    [str(ENTRY_SCRIPT)],

    pathex=[
        str(PROJECT_DIR),
    ],

    # External tools are discovered from active PATH.
    binaries=[],
    datas=[],

    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],

    noarchive=False,
)

# ------------------------------------------------------------
# Python archive
# ------------------------------------------------------------

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher,
)

# ------------------------------------------------------------
# Standalone executable
# ------------------------------------------------------------

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],

    name="cpldd",

    # Console application
    console=True,

    # Debugging
    debug=False,
    bootloader_ignore_signals=False,
    disable_windowed_traceback=False,

    # Binary options
    strip=False,
    upx=False,
    upx_exclude=[],

    # Runtime
    runtime_tmpdir=None,

    # Windows
    argv_emulation=False,
    target_arch=None,

    # Code signing (disabled)
    codesign_identity=None,
    entitlements_file=None,
)
