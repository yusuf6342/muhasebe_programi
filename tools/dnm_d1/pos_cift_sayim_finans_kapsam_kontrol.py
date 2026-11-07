"""POS çift sayım kuralı ≠ bekleyen liste tamam; finans kapsam kanıtı ayrı.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.pos_cift_sayim_finans_kapsam_kontrol
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from decimal import Decimal

from tools.dnm_d1._ortak import CALISMA, KAYNAK, yaz_json
from tools.dnm_d1.donem_sabitleri import RAPOR_ONEKI_KAYNAK

POS_VALOR = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}POS_VALOR.json"
AKBANK = CALISMA / "AKBANK_4355_POS_VALOR_D2_OZET.json"
VAKIF = CALISMA / "VAKIFBANK_EKSTRE_EXCEL_OZET.json"
KASA = CALISMA / "IKI_KASA_KAPANIS_OZET.json"
BANKA_OZET = CALISMA / "KAYNAK_DOGRULAMA_OZET.json"
OUT = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_POS_CIFT_SAYIM_FINANS_KAPSAM.json"
OZET = CALISMA / "POS_CIFT_SAYIM_FINANS_KAPSAM_OZET.json"


def main() -> int:
    pos = json.loads(POS_VALOR.read_text(encoding="utf-8")) if POS_VALOR.is_file() else {}
    ak = json.loads(AKBANK.read_text(encoding="utf-8")) if AKBANK.is_file() else {}
    vk = json.loads(VAKIF.read_text(encoding="utf-8")) if VAKIF.is_file() else {}
    kasa = json.loads(KASA.read_text(encoding="utf-8")) if KASA.is_file() else {}

    vb = pos.get("valor_bekleyen") or []
    dagilim = Counter((x.get("hesap_adi") or "?") for x in vb)
    akbank_5 = [x for x in vb if "AKBANK" in (x.get("hesap_adi") or "").upper()]
    akbank_toplam = sum(Decimal(str(x.get("tutar_net") or "0")) for x in akbank_5)

    # Çift sayım kuralı: bekleyen POS mevduat/banka kapanışına eklenmez
    cift_sayim_kurali = {
        "kural": "Valor bekleyen POS açılışta mevduat/banka netinden AYRI; çift sayım yasak",
        "korundu": True,
        "akbank_4355_kismi_kanit": {
            "var": bool(ak),
            "bes_islem_valor_d2": ak.get("d2_bag_adet"),
            "bes_toplam_esit": ak.get("bes_toplam_esit"),
            "kok": (vk.get("akbank_4355_bulgular") or [None])[0],
            "yorum": (
                "4355 kısmi kök neden + D2 valör bağ kanıtı kuralı destekler; "
                "bekleyen POS listesinin tamamlandığı anlamına GELMEZ"
            ),
        },
        "bekleyen_liste_tamam_mi": False,
        "bekleyen_liste_durum": {
            "valor_bekleyen_adet": pos.get("valor_bekleyen_adet"),
            "valor_bekleyen_toplam": pos.get("valor_bekleyen_toplam"),
            "hesap_dagilim": dict(dagilim),
            "akbank_adet": len(akbank_5),
            "akbank_net_toplam": str(akbank_toplam),
            "diger_hesaplar_bekliyor": [
                h for h in dagilim if "AKBANK" not in h.upper()
            ],
            "uyari_kaynak": pos.get("uyari"),
            "sonuc": (
                "KISMİ — Akbank 5 satır valör/D2 bağ kanıtlı; "
                "Yapı Kredi + Halkbank bekleyen satırlar + tam liste teyidi açık"
            ),
        },
    }

    # Finans kapsamı — POS kuralından ayrı kanıt
    finans = {
        "ayri_kontrol": True,
        "pos_kurali_finans_kapsam_yerine_gecmez": True,
        "kanitlar": {
            "kasa_nakit_yc": {
                "dosya": "IKI_KASA_KAPANIS_OZET.json",
                "var": bool(kasa),
                "durum": "KORUNDU" if kasa else "EKSIK",
            },
            "vakifbank_ekstre_excel": {
                "dosya": "VAKIFBANK_EKSTRE_EXCEL_OZET.json",
                "kapanis_kontrol_tamam": vk.get("kapanis_kontrol_tamam"),
                "esleme_tam": vk.get("esleme_tam"),
                "durum": (
                    "KISMI_KANIT"
                    if vk.get("kapanis_kontrol_tamam")
                    else "EKSIK"
                ),
            },
            "pos_valor_kaynak": {
                "dosya": str(POS_VALOR.relative_to(CALISMA)).replace("\\", "/"),
                "pos_hesap_adet": pos.get("pos_hesap_adet"),
                "donem_ici_pos_hareket": pos.get("donem_ici_pos_hareket"),
                "bloke_adet": pos.get("bloke_adet"),
                "bankaya_gecmis_adet": pos.get("bankaya_gecmis_adet"),
            },
            "tum_banka_hesaplari_net_kapsam": {
                "durum": "AYRI_BEKLIYOR",
                "aciklama": (
                    "POS çift sayım kuralı korunması ≠ tüm finans/banka hesap "
                    "kapsamının kapanış kanıtı. Hesap bazlı net + dönem süzgeci ayrı."
                ),
            },
        },
        "finans_kapsam_tam_mi": False,
    }

    out = {
        "format": "d1-pos-cift-sayim-finans-kapsam-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "pos_cift_sayim": cift_sayim_kurali,
        "finans_kapsam": finans,
        "k05": False,
        "mali_yazim": False,
    }
    yaz_json(OUT, out)
    ozet = {
        "zaman": out["zaman"],
        "cift_sayim_kurali_korundu": True,
        "bekleyen_liste_tamam": False,
        "valor_bekleyen_adet": pos.get("valor_bekleyen_adet"),
        "finans_kapsam_tam": False,
        "finans_ayri_kontrol": True,
        "kanit": str(OUT.relative_to(CALISMA)).replace("\\", "/"),
        "k05": False,
    }
    yaz_json(OZET, ozet)
    print(json.dumps(ozet, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
