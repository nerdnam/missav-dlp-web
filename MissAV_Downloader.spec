# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['launcher.py'],  # Entry point - NOT app.py
    pathex=[],
    binaries=[],
    datas=[
        ('templates', 'templates'),
        ('app_files', 'app_files'),
        ('locales', 'locales'),
        ('spoofdpi.exe', '.'),
    ],
    hiddenimports=[
        'flask',
        'werkzeug',
        'jinja2',
        'yt_dlp',
        'curl_cffi',
        'waitress',
        'app_files.config_manager',
        'app_files.download_manager',
        'app_files.extractor',
        'app_files.language',
        'app_files.paths',
        'app_files.utils',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MissAV_Downloader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Set to False to hide console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',  # Optional: add your icon file
)