"""Finans evraklarının (tahsilat, ödeme, makbuz, virman, havale) muhasebeleştirme süre ölçümü.

Geçici veritabanında çalışır (gerçek veriye dokunmaz). Her tür için evrak kaydı süresi:
genel muhasebe kapalı (taban) / otomatik / sonradan; ardından bekleyenlerin toplu muhasebeleştirmesi.

Kullanım: python tools/muhasebelestirme_performans_finans.py [adet]
"""

from __future__ import annotations

import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

KOK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KOK))
sys.path.insert(0, str(KOK / "tests"))
os.environ.setdefault("MUHASEBE_DB_DIR", tempfile.mkdtemp(prefix="cin_perf_"))

import test_muhasebelestirme_eksikleri as tme  # noqa: E402


def main() -> int:
    adet = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    t = tme.MuhasebelestirmeEksikleriTest("test_gecmis_finans_ekle_yetki_ister")
    t.setUp()
    try:
        from decimal import Decimal

        from database.database import get_session
        from database.models.finans import FinansHesabi

        with get_session() as s:  # ölçüm boyunca kasa bakiyesi yetsin
            s.get(FinansHesabi, t._kasa()).acilis_bakiyesi = Decimal("10000000")
        for tur in t.YENI_TURLER:  # ısınma
            t._evrak_olustur(tur)
        print(f"Ölçüm: {time.strftime('%Y-%m-%d %H:%M:%S')}  (geçici DB, tür başına {adet} evrak, medyan ms)")
        print(f"{'tür':<22}{'kapalı':>9}{'otomatik':>10}{'sonradan':>10}")
        for tur in t.YENI_TURLER:
            satir = {}
            for yontem, gm in (("kapali", False), ("otomatik", True), ("sonradan", True)):
                t._ayar("sonradan" if yontem == "sonradan" else "otomatik", gm=gm)
                sureler = []
                for _ in range(adet):
                    bas = time.perf_counter()
                    t._evrak_olustur(tur)
                    sureler.append(time.perf_counter() - bas)
                satir[yontem] = statistics.median(sureler) * 1000
            print(f"{tur:<22}{satir['kapali']:>9.1f}{satir['otomatik']:>10.1f}{satir['sonradan']:>10.1f}")
        bekleyen = t._servis().listele(durumlar=("Bekliyor",))
        bas = time.perf_counter()
        r = t._servis().muhasebelestir([b["id"] for b in bekleyen])
        toplu = time.perf_counter() - bas
        print(f"Toplu muhasebeleştirme: {len(bekleyen)} evrak, {toplu:.2f} s "
              f"({toplu / max(len(bekleyen), 1) * 1000:.1f} ms/evrak) — başarılı {r['basarili']}, "
              f"başarısız {r['basarisiz']}, atlanan {r['atlanan']}")
        t._tutarli()
        bas = time.perf_counter()
        oz = t._servis().gecmis_finans_onizle()
        print(f"Geçmiş önizleme: {time.perf_counter() - bas:.2f} s "
              f"({sum(len(v) for k in oz.values() for v in k.values())} kayıt)")
    finally:
        t.tearDown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
