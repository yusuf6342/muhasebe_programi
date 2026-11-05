"""İzole DENEME profilini cin_*_kabul_20261105 çiftine yazar (günlük ayarı değiştirmez)."""
from __future__ import annotations

import json
import os
import socket
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.baglanti_modu import (  # noqa: E402
    BaglantiAyari,
    CalismaKipi,
    PostgresBaglanti,
    ayari_kaydet,
)

STAMP = "20261105"
HOST = "192.168.1.114"
SYS = "cin_sistem_kabul_20261105"
FR = "cin_firma_kabul_20261105"


def main() -> int:
    local = Path(os.environ["LOCALAPPDATA"])
    profil = local / f"CinMuhasebeKabulDeneme_{STAMP}"
    program = profil / "program"
    data = profil / "data"
    program.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)

    # EXE yoksa dist'ten kopyala uyarısı
    exe = program / "CinMuhasebe.exe"
    dist = ROOT / "dist" / "CinMuhasebe" / "CinMuhasebe.exe"
    exe_sha = None
    if dist.is_file():
        import hashlib

        h = hashlib.sha256()
        with dist.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        exe_sha = h.hexdigest().upper()

    ayar = BaglantiAyari(
        kipi=CalismaKipi.YEREL_AG_POSTGRES.value,
        postgres=PostgresBaglanti(
            host=HOST,
            port=5432,
            sistem_db=SYS,
            kullanici="cin_app",
            sslmode="verify-full",
            ortam="DENEME",
            firma_db=FR,
            terminal_kimligi=f"KABUL-{STAMP}-{socket.gethostname()}",
        ),
    )
    yol = ayari_kaydet(ayar, program_dir=program)
    (program / "veri_konumu.txt").write_text(str(data) + "\n", encoding="utf-8")
    (program / "DENEME_ORTAMI.txt").write_text(
        f"KABUL DENEME {STAMP}\n{SYS} / {FR}\nverify-full\n"
        f"makine={socket.gethostname()}\n{datetime.now().isoformat()}\n",
        encoding="utf-8",
    )

    # Kısayol: yalnızca DENEME bat (günlük kısayola dokunma)
    bat = profil / "CinMuhasebe_AG_DENEME.bat"
    bat.write_text(
        "@echo off\r\n"
        "title Cin Muhasebe - AG DENEME - 05.11.2026\r\n"
        "set MUHASEBE_BAGLANTI_KIPI=yerel_ag_postgres\r\n"
        f"set MUHASEBE_DB_DIR={data}\r\n"
        f"cd /d \"{program}\"\r\n"
        f"start \"\" \"{program}\\CinMuhasebe.exe\"\r\n",
        encoding="ascii",
        newline="\r\n",
    )

    # Masaüstü DENEME kısayolu (yoksa oluştur / hedefi güncelle)
    desktop = Path.home() / "OneDrive" / "Masaüstü"
    if not desktop.is_dir():
        desktop = Path.home() / "Desktop"
    lnk = desktop / "Cin Muhasebe - Ag Deneme - 05.11.2026.lnk"
    try:
        import win32com.client  # type: ignore

        shell = win32com.client.Dispatch("WScript.Shell")
        s = shell.CreateShortcut(str(lnk))
        s.TargetPath = str(bat)
        s.WorkingDirectory = str(program)
        s.Description = "DENEME kabul - gunluk kisayolu degistirmez"
        s.Save()
        lnk_ok = True
    except Exception as exc:
        lnk_ok = False
        lnk_err = str(exc)[:200]

    out = {
        "zaman": datetime.now().isoformat(timespec="seconds"),
        "makine": socket.gethostname(),
        "profil": str(profil),
        "baglanti_ayari": str(yol),
        "ayar": ayar.to_dict(),
        "exe_programda": exe.is_file(),
        "dist_sha256": exe_sha,
        "kisayol": str(lnk),
        "kisayol_ok": lnk_ok,
        "not": "Baglantı pg_hba kabul DB izinlerinden sonra çalışır",
    }
    if not lnk_ok:
        out["kisayol_hata"] = lnk_err
    yol_rapor = ROOT / "kurulum" / "_kabul_deneme_profil.json"
    yol_rapor.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print("YAZILDI:", yol_rapor)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
