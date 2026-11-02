# -*- mode: python ; coding: utf-8 -*-
"""TEST paketi için giriş noktası — CinMuhasebe.spec'i CIN_TEST_BUILD=1 ile çalıştırır.

Tercihen: scripts/build_test_paket.ps1
veya:
  set CIN_TEST_BUILD=1
  .venv\\Scripts\\python.exe -m PyInstaller --noconfirm CinMuhasebe.spec
"""

import os

os.environ["CIN_TEST_BUILD"] = "1"

# Ana spec'i aynı süreçte yükle (PyInstaller SPECPATH bu dosyaya işaret eder;
# Analysis yolları için CinMuhasebe.spec dosyasını doğrudan kullanın + env).
raise SystemExit(
    "CinMuhasebe_TEST.spec doğrudan çalıştırılmamalı. "
    "scripts\\build_test_paket.ps1 kullanın veya CIN_TEST_BUILD=1 ile CinMuhasebe.spec derleyin."
)
