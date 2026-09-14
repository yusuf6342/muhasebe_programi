"""Genel muhasebe temel duman testi."""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from database.database import sistem_altyapisini_baslat, get_session
from database.muhasebe_service import (
    HesapPlanService,
    MuhasebeFisService,
    MuhasebeRaporService,
    MuhasebeService,
    para_goster,
)
from database.session_manager import oturum
from database.models.genel_muhasebe import HesapPlani
from sqlalchemy import select, func


def main() -> int:
    print("=== GENEL MUHASEBE DUMAN TESTİ ===")
    sistem_altyapisini_baslat()
    oturum.set_user(
        user_id=1,
        kullanici_adi="admin",
        ad_soyad="Admin",
        role_kod="YONETICI",
        role_ad="Yonetici",
        permissions=set(),
        sifre_degistirmeli=False,
    )
    MuhasebeService.schema_hazirla()

    with get_session() as session:
        n = session.scalar(select(func.count()).select_from(HesapPlani))
    print(f"Hesap sayısı: {n}")
    assert (n or 0) >= 8, "Ana hesap sınıfları yok"

    # Dengeli mahsup fişi
    hesaplar = HesapPlanService.listele(sadece_aktif=True)
    h1 = next(h for h in hesaplar if h["hesap_kodu"] == "1")
    h3 = next(h for h in hesaplar if h["hesap_kodu"] == "3")
    fis_id = MuhasebeFisService.kaydet(
        {
            "fis_tarihi": date.today(),
            "fis_turu": "Mahsup Fişi",
            "aciklama": "Duman test fişi",
            "durum": "Kesinleşmiş",
            "satirlar": [
                {"hesap_id": h1["id"], "borc": "1000,00", "alacak": "0"},
                {"hesap_id": h3["id"], "borc": "0", "alacak": "1000,00"},
            ],
        }
    )
    print(f"Kesinleşmiş fiş id={fis_id}")

    # Dengesiz kesinleştirme reddedilmeli
    try:
        MuhasebeFisService.kaydet(
            {
                "fis_tarihi": date.today(),
                "fis_turu": "Mahsup Fişi",
                "aciklama": "dengesiz",
                "durum": "Kesinleşmiş",
                "satirlar": [
                    {"hesap_id": h1["id"], "borc": "50", "alacak": "0"},
                ],
            }
        )
        print("FAIL: dengesiz fiş kesinleşti")
        return 1
    except ValueError as e:
        print("OK dengesiz reddedildi:", e)

    mizan = MuhasebeRaporService.mizan(date(date.today().year, 1, 1), date.today())
    print("Mizan dengeli:", mizan["dengeli"], "satır:", len(mizan["satirlar"]))
    bil = MuhasebeRaporService.bilanco(date.today())
    print(
        "Bilanço aktif/pasif:",
        para_goster(bil["aktif_toplam"]),
        para_goster(bil["pasif_toplam"]),
        "dengeli=",
        bil["dengeli"],
    )
    gt = MuhasebeRaporService.gelir_tablosu(date(date.today().year, 1, 1), date.today())
    print("Gelir tablosu net:", para_goster(gt["net_kar"]))
    print("=== OK ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
