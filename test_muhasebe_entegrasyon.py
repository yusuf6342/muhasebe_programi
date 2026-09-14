"""Muhasebe entegrasyon duman testi — eşleştirme + otomatik fiş."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from database.database import sistem_altyapisini_baslat, get_session
from database.muhasebe_entegrasyon import (
    HesapEslemeService,
    MuhasebeEntegrasyonService,
    KAYNAK_SATIS_FATURA,
)
from database.muhasebe_service import MuhasebeFisService, MuhasebeService
from database.session_manager import oturum
from database.models.genel_muhasebe import MuhasebeFisi
from sqlalchemy import select, func


def main() -> int:
    print("=== ENTEGRASYON DUMAN TESTİ ===")
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
    n = HesapEslemeService.oneri_hesaplari_olustur()
    print("Önerilen hesap eklenen:", n)
    eslemeler = HesapEslemeService.listele()
    eksik = [e["anahtar"] for e in eslemeler if not e["hesap_id"]]
    print("Eşleştirme sayısı:", len(eslemeler), "eksik:", eksik)
    assert not eksik, f"Eşleştirme eksik: {eksik}"

    # Sahte satış faturası benzeri satırlarla doğrudan entegrasyon _olustur yolu
    m = MuhasebeEntegrasyonService._hesap("musteriler")
    s = MuhasebeEntegrasyonService._hesap("yurtici_satislar")
    k = MuhasebeEntegrasyonService._hesap("hesaplanan_kdv")
    fis_id = MuhasebeEntegrasyonService._olustur(
        kaynak_turu="test_ent_satis",
        kaynak_id=999001,
        fis_tarihi=date.today(),
        fis_turu="Mahsup Fişi",
        aciklama="Test otomatik fiş",
        belge_no="TEST-ENT-1",
        satirlar=[
            {"hesap_id": m["id"], "borc": "1200", "alacak": "0", "aciklama": "borc"},
            {"hesap_id": s["id"], "borc": "0", "alacak": "1000", "aciklama": "satis"},
            {"hesap_id": k["id"], "borc": "0", "alacak": "200", "aciklama": "kdv"},
        ],
    )
    print("Otomatik fiş id:", fis_id)
    assert fis_id

    # Çift kayıt engeli
    fis2 = MuhasebeEntegrasyonService._olustur(
        kaynak_turu="test_ent_satis",
        kaynak_id=999001,
        fis_tarihi=date.today(),
        fis_turu="Mahsup Fişi",
        aciklama="tekrar",
        belge_no="TEST-ENT-1",
        satirlar=[
            {"hesap_id": m["id"], "borc": "1200", "alacak": "0"},
            {"hesap_id": s["id"], "borc": "0", "alacak": "1000"},
            {"hesap_id": k["id"], "borc": "0", "alacak": "200"},
        ],
        yeniden=False,
    )
    print("Çift kayıt aynı id:", fis2, "(beklenen", fis_id, ")")
    assert fis2 == fis_id

    # Yeniden: iptal + yeni
    fis3 = MuhasebeEntegrasyonService._olustur(
        kaynak_turu="test_ent_satis",
        kaynak_id=999001,
        fis_tarihi=date.today(),
        fis_turu="Mahsup Fişi",
        aciklama="yeniden",
        belge_no="TEST-ENT-1",
        satirlar=[
            {"hesap_id": m["id"], "borc": "1200", "alacak": "0"},
            {"hesap_id": s["id"], "borc": "0", "alacak": "1000"},
            {"hesap_id": k["id"], "borc": "0", "alacak": "200"},
        ],
        yeniden=True,
    )
    print("Yeniden fiş id:", fis3)
    assert fis3 and fis3 != fis_id

    MuhasebeEntegrasyonService.iptal_kaynak("test_ent_satis", 999001, "test temizliği")
    print("=== OK ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
