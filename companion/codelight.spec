# -*- mode: python ; coding: utf-8 -*-
# Cross-platform PyInstaller build for the Codelight companion app.
# macOS  → dist/Codelight.app   |   Windows → dist/Codelight/Codelight.exe
import sys

a = Analysis(
    ['codelight_gui.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['claude_monitor'],   # imported via sys.path trick; pin it
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Codelight',
    debug=False,
    strip=False,
    upx=False,
    console=False,            # windowed app, no terminal popup
    argv_emulation=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='Codelight',
)

if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='Codelight.app',
        icon=None,
        bundle_identifier='com.codelight.app',
        info_plist={
            'CFBundleShortVersionString': '1.0.0',
            'NSHighResolutionCapable': True,
        },
    )
