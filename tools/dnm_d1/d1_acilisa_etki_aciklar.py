"""D1 açılışa etki eden kalan işler — güncel ozet/kanıt dosyalarından.

Eski rapor sayılarını tekrarlamaz; her açık için eksik kanıt, D2 etkisi, yapılacak iş.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.d1_acilisa_etki_aciklar
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from typing import Any

from tools.dnm_d1._ortak import CALISMA, yaz_json

OZET = CALISMA / "D1_ACILISA_ETKI_ACIKLAR_OZET.json"
OUT = CALISMA / "kaynak" / "D1_20260831_KAYNAK_DOGRULAMA_D1_ACILISA_ETKI_ACIKLAR.json"


def _oku(ad: str) -> dict[str, Any] | None:
    p = CALISMA / ad
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> int:
    aciklar: list[dict] = []

    def ekle(
        madde: str,
        durum: str,
        *,
        kanit: str | None,
        eksik: str,
        d2_etki: str,
        yapilacak: str,
        korunan: str | None = None,
    ) -> None:
        aciklar.append(
            {
                "madde": madde,
                "durum": durum,
                "kanit_ozet": kanit,
                "eksik_kanit": eksik,
                "devir2_etki": d2_etki,
                "yapilacak": yapilacak,
                "korunan": korunan,
            }
        )

    # Kasa — tamam
    kasa = _oku("IKI_KASA_KAPANIS_OZET.json") or {}
    if kasa.get("iki_kasa_tamam"):
        ekle(
            "Kasa (nakit+YC) 31.08 kapanış",
            "TAMAM",
            kanit=kasa.get("kanit_nakit"),
            eksik="—",
            d2_etki="Açılış bakiyesi hazır; koru",
            yapilacak="Yeniden başlatma",
            korunan=f"nakit={kasa.get('nakit_kapanis')} yc={kasa.get('yc_kapanis')}",
        )
    else:
        ekle("Kasa kapanış", "AÇIK", kanit=None, eksik="iki_kasa_tamam değil", d2_etki="Açılış engeli", yapilacak="Kasa mutabakat")

    # Banka
    banka = _oku("BANKA_KAPSAM_KASA_KAPANIS_OZET.json") or {}
    ekle(
        "Banka kapsam / 2030 net",
        "KISMI" if banka.get("2030_excel_esit") else "AÇIK",
        kanit=banka.get("kanit"),
        eksik="Halkbank sıfır sayılmaz notu var; kasa_durum=" + str(banka.get("kasa_durum")),
        d2_etki="Banka açılış + bölüm eşlemesi D2 17–19",
        yapilacak="Banka ad→bölüm Excel; kalan hesap kanıtları",
        korunan="2030_net=" + str(banka.get("2030_net")),
    )

    # POS — çift sayma uyarısı
    pos = _oku("AKBANK_4355_POS_VALOR_D2_OZET.json") or {}
    ekle(
        "Akbank 4355 POS valör",
        "KISMI" if pos.get("valor_excel_esit") else "AÇIK",
        kanit=pos.get("kanit"),
        eksik="Diğer POS hesapları / bekleyen valör tam envanter",
        d2_etki="D2 açılış bekleyen POS; banka bakiyesiyle çift sayma yasak",
        yapilacak="Bekleyen POS tutarını mevduat bakiyesinden ayrı tut; Eylül geçişinde tek banka girişi",
        korunan=f"valor_giren={pos.get('valor_giren')} bes_toplam_esit={pos.get('bes_toplam_esit')}",
    )

    # Cari
    cari22 = _oku("CARI22_KAPANIS_KANIT_OZET.json") or {}
    ekle(
        "Cari22 kapanış kanıtı",
        "AÇIK",
        kanit=cari22.get("kanit"),
        eksik=f"kanitli={cari22.get('kanitli')} kanitsiz={cari22.get('kanitsiz')} (21); rapor yazdır otomasyon boş",
        d2_etki="D2 08–11 açılış açık kalem / FIFO valör engeli",
        yapilacak="Kullanıcı Yazdır ile resmi ekstre; kalan 21 cari kapanış kanıtı",
    )

    devam = _oku("DEVIR1_DEVAM_OZET.json") or {}
    ekle(
        "Devirli cari / risk eşleme",
        "AÇIK",
        kanit="DEVIR1_DEVAM_OZET",
        eksik=f"risk21={devam.get('risk21_adet')} eslesmedi/aday açık; detay_var={devam.get('risk21_detay_var')}",
        d2_etki="Açık fatura/vade/kapama bağları açılışa taşınamaz",
        yapilacak="PDF/devralınan eşleme + finans_jq_listesi açık kalem",
    )

    # Stok
    st3252 = _oku("STOK_3252_HESAPLANABILIR_OZET.json") or {}
    st49 = _oku("STOK_49_PASIF_DAHIL_ESLEME_OZET.json") or {}
    fifo = _oku("STOK_FIFO_KATMAN_IZOLE_OZET.json") or {}
    ekle(
        "Stok envanter 3252 kimlik",
        "KISMI" if st3252.get("eslesen") else "AÇIK",
        kanit=st3252.get("kanit_3252") or st49.get("kanit_esleme"),
        eksik=(
            f"kimlik_yok={st3252.get('kimlik_yok', st49.get('kimlik_yok'))}; "
            f"FIFO katman dogrulanmis 49=0; LOT BEKLIYOR; "
            f"fifo_izole_tam={fifo.get('fifo_izole_tam')} cikisli_bekleyen={fifo.get('cikisli_bekleyen')}"
        ),
        d2_etki="D2 12–16 stok/LOT açılış; maliyet köprüsü",
        yapilacak="6 önceki kimliği taşı (yapıldıysa doğrula); FIFO/LOT katman; sıfır maliyet sınıfları koru",
        korunan="pasif 49 miktar; negatifler; kasa/banka",
    )

    ekle(
        "K05 kaynak kontrolü",
        "KAPALI",
        kanit="KAYNAK_DOGRULAMA_* k05=false",
        eksik="Kaynak tamlığı + kritik fark çözümü yok",
        d2_etki="D2 01; gerçek aktarım ön koşulu",
        yapilacak="K05 kabul koşulları sağlanana kadar mali yazım yok",
    )
    ekle(
        "K06 hedef izolasyonu",
        "KAPALI",
        kanit=None,
        eksik="Gerçek boş D2 hedef + izole yedek/geri yükleme yok",
        d2_etki="D2 06",
        yapilacak="Hazırlıkta şema/betik; ana makinede oluşturma sonra",
    )

    out = {
        "format": "d1-acilisa-etki-aciklar-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "kasa_banka_korundu": True,
        "pos_mevduat_cift_sayim_yasak": True,
        "k05": False,
        "k06": False,
        "mali_yazim": False,
        "exe": False,
        "aciklar": aciklar,
        "ozet_durum": dict(Counter(a["durum"] for a in aciklar)),
    }
    yaz_json(OUT, out)
    ozet = {
        "zaman": out["zaman"],
        "adet": len(aciklar),
        "durum": out["ozet_durum"],
        "k05": False,
        "k06": False,
        "kanit": str(OUT.relative_to(CALISMA)).replace("\\", "/"),
    }
    yaz_json(OZET, ozet)
    print(json.dumps(ozet, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
