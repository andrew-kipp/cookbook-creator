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

# ── Optional LLM packages ─────────────────────────────────────────────────────
# Each package is only bundled if it is already installed in the build environment.
# Install whichever you want before running pyinstaller:
#   pip install anthropic                        (Claude / Anthropic)
#   pip install openai                           (GPT-4o / OpenAI)
#   pip install google-generativeai Pillow       (Gemini / Google)

_llm_hidden = []
_llm_collect_all = []

try:
    import anthropic        # noqa: F401
    _llm_hidden += [
        'anthropic', 'anthropic.resources', 'anthropic._streaming',
        'httpx', 'httpcore', 'anyio', 'sniffio',
    ]
    _llm_collect_all.append('anthropic')
    print('[spec] anthropic detected — will be bundled')
except ImportError:
    print('[spec] anthropic NOT installed — Claude provider will be unavailable in exe')

try:
    import openai           # noqa: F401
    _llm_hidden += [
        'openai', 'openai.resources', 'openai._streaming',
        'httpx', 'httpcore', 'anyio', 'sniffio',
    ]
    _llm_collect_all.append('openai')
    print('[spec] openai detected — will be bundled')
except ImportError:
    print('[spec] openai NOT installed — GPT-4o provider will be unavailable in exe')

try:
    import google.generativeai  # noqa: F401
    _llm_hidden += [
        'google.generativeai', 'google.ai.generativelanguage_v1beta',
        'google.auth', 'google.oauth2', 'grpc',
    ]
    _llm_collect_all += ['google.generativeai', 'grpc']
    print('[spec] google-generativeai detected — will be bundled')
except ImportError:
    print('[spec] google-generativeai NOT installed — Gemini provider will be unavailable in exe')

try:
    import PIL              # noqa: F401
    _llm_collect_all.append('PIL')
    print('[spec] Pillow detected — will be bundled')
except ImportError:
    print('[spec] Pillow NOT installed — BMP support and Gemini provider will be unavailable in exe')

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
        'ImageToRecipeJSON',
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
        # LLM packages (populated above based on what's installed)
        *_llm_hidden,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    collect_all=['reportlab', 'pymupdf', *_llm_collect_all],
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
