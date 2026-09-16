# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — Cin Muhasebe (CinMuhasebe.exe)."""

import sys
from pathlib import Path

block_cipher = None
ROOT = Path(SPECPATH).resolve()
BRANDING = ROOT / "assets" / "branding"
# EXE icon alanı yalnızca .ico kabul eder — PNG kullanma.
# Öncelik: CinLogo.ico (önerilen), yoksa eski cin_muhasebe.ico
ICO = BRANDING / "CinLogo.ico"
if not ICO.is_file():
    ICO = BRANDING / "cin_muhasebe.ico"

datas = []
if BRANDING.is_dir():
    # CinLogo.png dahil tüm branding dosyaları pakete girer
    datas.append((str(BRANDING), "assets/branding"))

a = Analysis(
    ["main.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "auth_ui",
        "firma_secim_theme",
        "branding",
        "sistem_ui",
        "silinen_kayitlar_ui",
        "servis_sistem_ui",
        "database",
        "database.database",
        "database.system.bootstrap",
        "database.system.auth_service",
        "database.servis_sistem",
        "database.servis_sistem.system_health_service",
        "database.servis_sistem.database_integrity_service",
        "database.servis_sistem.error_log_service",
        "database.servis_sistem.module_diagnostic_service",
        "database.servis_sistem.backup_service",
        "database.servis_sistem.models",
        "hizli_satis_ui",
        "hizli_satis_urun_panel_ui",
        "hizli_satis_urun_ekle_ui",
        "cari_kart_ui",
        "cari_kart_tema",
        "database.hizli_satis_service",
        "database.models.hizli_satis",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe_kwargs = dict(
    name="CinMuhasebe",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

if ICO.is_file():
    exe_kwargs["icon"] = str(ICO)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    **exe_kwargs,
)
