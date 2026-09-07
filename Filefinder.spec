# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[('resources/djvulibre/libdjvulibre.dll', '.'), ('resources/djvulibre/libdjvulibre-21.dll', '.'), ('resources/djvulibre/libgcc_s_seh-1.dll', '.'), ('resources/djvulibre/libjpeg.dll', '.'), ('resources/djvulibre/libstdc++-6.dll', '.'), ('resources/djvulibre/libtiff.dll', '.'), ('resources/djvulibre/libwinpthread-1.dll', '.'), ('resources/djvulibre/libz.dll', '.'), ('resources/djvulibre/ddjvu.exe', '.'), ('resources/djvulibre/djvused.exe', '.'), ('resources/djvulibre/djvutxt.exe', '.')],
    datas=[('resources', 'resources')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Filefinder',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['resources/icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Filefinder',
)
