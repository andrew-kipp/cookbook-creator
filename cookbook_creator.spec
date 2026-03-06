# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Recipe and Cookbook Creator
Build with: pyinstaller cookbook_creator.spec
Output: dist/RecipeAndCookbookCreator.exe
"""

import os
import sys
from pathlib import Path

# Locate the tkinterdnd2 package so we can bundle its native DLL
try:
    import tkinterdnd2
    _dnd_pkg_dir = Path(tkinterdnd2.__file__).parent
    _dnd_tkdnd_dir = _dnd_pkg_dir / 'tkdnd'
    _dnd_data = [
        (str(_dnd_pkg_dir / 'TkinterDnD.py'), 'tkinterdnd2'),
        (str(_dnd_pkg_dir / '__init__.py'),    'tkinterdnd2'),
        (str(_dnd_tkdnd_dir),                  'tkinterdnd2/tkdnd'),
    ]
except Exception:
    _dnd_data = []

a = Analysis(
    ['app.py'],
    pathex=['.'],
    binaries=[],
    datas=_dnd_data,
    hiddenimports=[
        # Our recipe modules
        'PaprikaExtract',
        'JSONToPDFRecipe',
        'CreatePaprikaImport',
        'PDFToJSONRecipe',
        'RecipeFormatter',
        # tkinterdnd2
        'tkinterdnd2',
        'tkinterdnd2.TkinterDnD',
        # reportlab fonts / internals
        'reportlab',
        'reportlab.graphics',
        'reportlab.platypus',
        'reportlab.lib',
        'reportlab.lib.pagesizes',
        'reportlab.lib.styles',
        'reportlab.lib.units',
        'reportlab.lib.enums',
        'reportlab.lib.colors',
        'reportlab.pdfbase',
        'reportlab.pdfbase.pdfmetrics',
        'reportlab.pdfbase.ttfonts',
        # PyMuPDF
        'fitz',
        # requests
        'requests',
        'urllib3',
        'certifi',
        'charset_normalizer',
        'idna',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    collect_all=['reportlab', 'pymupdf'],
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='RecipeAndCookbookCreator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,   # No console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,       # Set to an .ico file path to add a custom icon
    onefile=True,
)
