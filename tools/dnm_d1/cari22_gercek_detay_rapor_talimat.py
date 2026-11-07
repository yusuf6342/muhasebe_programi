"""Cari22 — gerçek detay rapor talimatı (PDF toplam ≠ ekstre).

Boş finans_jq dilimlerini yeniden çalıştırmaz.
Önceden incelenen «Müşteri Hesap Toplamı Tarih (Devirli)» PDF’yi detay yerine kullanmaz.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.cari22_gercek_detay_rapor_talimat
"""
from __future__ import annotations

import json
from datetime import datetime

from tools.dnm_d1._ortak import CALISMA, KAYNAK, yaz_json

OZET_IN = CALISMA / "CARI22_KAPANIS_KANIT_OZET.json"
OUT = KAYNAK / "D1_20260831_KAYNAK_DOGRULAMA_CARI22_GERCEK_DETAY_RAPOR_TALIMAT.json"
OZET = CALISMA / "CARI22_GERCEK_DETAY_RAPOR_TALIMAT_OZET.json"


def main() -> int:
    ham = json.loads(OZET_IN.read_text(encoding="utf-8")) if OZET_IN.is_file() else {}
    tablo = ham.get("tablo") or []
    kanitsiz = [
        {
            "kaynak_cari_id": str(r["id"]),
            "kod": r.get("kod"),
            "unvan": r.get("unvan"),
            "grup": r.get("grup"),
            "dogrulanmamis_ozet_bakiye": r.get("dogrulanmamis_ozet_bakiye"),
        }
        for r in tablo
        if r.get("kanit") == "KANIT_YOK"
    ]
    kanitli = [
        {
            "kaynak_cari_id": str(r["id"]),
            "kod": r.get("kod"),
            "unvan": r.get("unvan"),
            "kapanis_3108": r.get("kapanis_3108"),
            "kanit": r.get("kanit"),
        }
        for r in tablo
        if r.get("kanit") != "KANIT_YOK"
    ]

    out = {
        "format": "d1-cari22-gercek-detay-rapor-talimat-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "yasak": {
            "pdf_toplam_detay_yerine_kullanilmaz": {
                "rapor": "Müşteri Hesap Toplamı Tarih (Devirli)",
                "rap_uid": "RAP_MUS002 / mushestop.repx",
                "neden": "Özet/devirli toplam; satır satır borç-alacak-vade Detay değildir",
                "kanit_onceki": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_PDF_DEVIRLI_RAPOR.json",
                "yeniden_incelenmeyecek": True,
            },
            "bos_finans_jq_yeniden_sorgu_yok": {
                "api": "Musteri/base cmd=finans_jq_listesi",
                "neden": "21 caride yıllık dilimler Detay=0 zaten kanıtlandı; aynı boş sorgular tekrarlanmaz",
                "kanit": "CARI22_KAPANIS_KANIT_OZET.json",
            },
        },
        "gerekli_gercek_detay_rapor": {
            "ad": "Cari Hesap Ekstresi (finans grid / satır satır Detay)",
            "menu_birincil": "Müşteri Yönetimi → Cari Kart → Hesap Ekstresi (finans)",
            "menu_alternatif": (
                "Raporlar → Finans Raporları → Müşteri Hesap Raporları → "
                "tek cari için satır satır Hesap Ekstresi (Toplamı/Devirli değil)"
            ),
            "api_eslesme": "Musteri/base cmd=finans_jq_listesi → Detay[] dolu olmalı",
            "excel_disa_aktarim": "Cari Hesap Ekstresi dışa aktarım (aynı filtreler)",
            "filtreler": {
                "bitis_dahil": "31.08.2026",
                "baslangic": "İlgili açılış veya en eski hareket; yoksa 01.01.2015",
                "tur": "Tümü",
                "doviz": "TL zorunlu; dövizli cari varsa ayrı Dövizli Cari Ekstre",
                "cari_secimi": "Aşağıdaki 21 kanıtsız cari — tek tek veya çoklu seçim",
                "hareket_gorenler_checkbox": (
                    "Sadece Tarih Aralığında Hareket Görenleri Listele — KAPALI "
                    "(devir/açılış satırı kaçmasın)"
                ),
            },
            "gerekli_sutunlar": [
                "Tarih",
                "Belge/Tür",
                "Belge no / id",
                "Borç",
                "Alacak",
                "Bakiye",
                "Vade (varsa)",
            ],
            "olcut": (
                "≤31.08.2026 son Detay bakiyesi = kapanış kanıtı; "
                "Özet bakiyesi yalnız başına 31.08 sayılmaz; PDF Toplamı Detay yerine geçmez"
            ),
        },
        "hangi_cariler": {
            "kanitsiz_21": kanitsiz,
            "kanitli_1_tekrar_gerekmez": kanitli,
            "oncelik_15_risk": [
                c["kaynak_cari_id"]
                for c in kanitsiz
                if c.get("grup") == "15_kanitsiz"
            ],
            "kalan_6": [
                c["kaynak_cari_id"]
                for c in kanitsiz
                if c.get("grup") != "15_kanitsiz"
            ],
        },
        "durum": "BEKLIYOR_KULLANICI_GERCEK_DETAY",
        "finans_jq_tekrar": False,
        "pdf_toplam_tekrar": False,
        "k05": False,
    }
    yaz_json(OUT, out)
    ozet = {
        "zaman": out["zaman"],
        "gerekli_rapor": out["gerekli_gercek_detay_rapor"]["ad"],
        "menu": out["gerekli_gercek_detay_rapor"]["menu_birincil"],
        "filtre_bitis": "31.08.2026",
        "kanitsiz_cari_adet": len(kanitsiz),
        "kanitsiz_ids": [c["kaynak_cari_id"] for c in kanitsiz],
        "yasak_pdf_toplam": True,
        "yasak_bos_finans_jq_tekrar": True,
        "durum": out["durum"],
        "kanit": str(OUT.relative_to(CALISMA)).replace("\\", "/"),
        "k05": False,
    }
    yaz_json(OZET, ozet)
    print(json.dumps(ozet, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
