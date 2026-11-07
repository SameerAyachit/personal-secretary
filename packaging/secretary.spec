# -*- mode: python ; coding: utf-8 -*-

"""PyInstaller spec for Secretary (one-folder build).

Data files (plan §8 Windows pitfalls, C-14):
  - tzdata (zoneinfo on Windows)
  - vendored tiktoken cl100k_base encoding file
  - migrations/ (schema migrations)
  - src/secretary/ui/theme (QSS/theme assets)

Built with: pyinstaller packaging/secretary.spec
"""

from __future__ import annotations

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# tzdata package data (zoneinfo is required on Windows).
tzdata_datas = collect_data_files("tzdata")

a = Analysis(
    ["../src/secretary/__main__.py"],
    pathex=[".."],
    binaries=[],
    datas=[
        *tzdata_datas,
        # Vendored tiktoken encoding (tokens.py sets TIKTOKEN_CACHE_DIR to this folder).
        ("../src/secretary/llm/vendor/cl100k_base.tiktoken", "secretary/llm/vendor"),
        # Schema migrations must ship with the app.
        ("../migrations", "migrations"),
        # QSS/theme assets generated from design tokens.
        ("../src/secretary/ui/theme", "secretary/ui/theme"),
    ],
    hiddenimports=[
        "secretary.llm.openai_compat",
        "secretary.llm.probe",
        "secretary.notify.tray",
        "secretary.notify.popup",
        "secretary.hotkey",
        "tzdata",
        "keyring",
        "desktop_notifier",
        "dateparser",
        "httpx",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_tmpdir=None,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="secretary",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # no UPX (antivirus friendliness, plan §20.5 C-38)
    runtime_tmpdir=None,
    console=False,  # windowed; diagnostics write to a log file (C-37)
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="",  # production icon added at release (human-gated)
    version="version_info.txt",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="secretary",
)
