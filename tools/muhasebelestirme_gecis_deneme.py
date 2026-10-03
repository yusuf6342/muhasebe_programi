"""Muhasebeleştirme geçişini gerçek verinin KOPYASINDA dener (gerçek veritabanına yazmaz).

muhasebe.db ve system.db, SQLite backup API ile geçici klasöre kopyalanır; geçiş kopyada çalışır.
Rapor: geçiş süresi, oluşan ayarlar, evrak durum sayıları, fiş sayısı ve hesap bakiyelerinin
değişmediği, tablo satır sayısı farkları.

    python tools/muhasebelestirme_gecis_deneme.py --veri "%LOCALAPPDATA%\\MuhasebeProgrami\\data"
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))


def kopyala(kaynak: Path, hedef: Path) -> None:
    k = sqlite3.connect(f"file:{kaynak.as_posix()}?mode=ro", uri=True, timeout=30)
    h = sqlite3.connect(str(hedef))
    try:
        k.backup(h)
    finally:
        h.close()
        k.close()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--veri", required=True, type=Path)
    p.add_argument("--firma", type=int, default=1)
    p.add_argument("--kullanici", type=int, default=1)
    a = p.parse_args()
    veri = a.veri.expanduser().resolve()
    kopya = Path(tempfile.mkdtemp(prefix="cin_gecis_deneme_"))
    for ad in ("muhasebe.db", "system.db"):
        kopyala(veri / ad, kopya / ad)
    print(f"Kopya: {kopya}")

    from hesap_bakiye_duzelt import oturum_ac, plan_ve_mizan, tablo_sayilari

    once_sayilar = tablo_sayilari(kopya / "muhasebe.db")
    oturum_ac(kopya, a.firma, a.kullanici)
    plan_once, _m, _d = plan_ve_mizan()
    from database.muhasebelestirme_service import MuhasebelestirmeService

    print("Geçiş gerekli mi:", MuhasebelestirmeService.gecis_gerekli_mi())
    bas = time.perf_counter()
    yedek = MuhasebelestirmeService.schema_hazirla()
    sure = time.perf_counter() - bas
    print(f"Geçiş (yedek dahil) süresi: {sure:.2f} s — yedek: {yedek}")
    bas = time.perf_counter()
    print("İkinci çağrı yedek:", MuhasebelestirmeService.schema_hazirla(),
          f"({time.perf_counter() - bas:.2f} s)")

    ayar = MuhasebelestirmeService.ayarlar()
    print(f"GM kullan: {ayar['gm_kullan']} varsayılan: {ayar['varsayilan']} — {ayar['aciklama']}")
    for t in ayar["turler"]:
        print(f"  {t['ad']:<32} seçim={t['secim']:<10} etkin={t['etkin']:<9} "
              f"sorun={len(t['eslesme_sorunlari'])}")
        for m in t["eslesme_sorunlari"][:1]:
            print(f"      {m}")
    print("Durum sayıları:", MuhasebelestirmeService.durum_sayilari())
    plan_sonra, mizan, dengeli = plan_ve_mizan()
    print("Hesap bakiyeleri değişmedi:", plan_once == plan_sonra, "| plan == mizan:", plan_sonra == mizan)
    sonra_sayilar = tablo_sayilari(kopya / "muhasebe.db")
    print("Satır sayısı değişen tablolar:",
          {t: (once_sayilar.get(t), n) for t, n in sonra_sayilar.items() if once_sayilar.get(t) != n})
    bas = time.perf_counter()
    liste = MuhasebelestirmeService.listele(limit=5000)
    print(f"Liste (5000 sınır) süresi: {time.perf_counter() - bas:.2f} s, satır {len(liste)}")


if __name__ == "__main__":
    main()
