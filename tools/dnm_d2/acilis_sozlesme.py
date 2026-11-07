"""D2 açılış sözleşmesi — 31.08 kabul → 01.09 tek açılış; çift etki yok.

Salt hazırlık: gerçek hedefe yazmaz. K05/K06 kapalıyken mali yazım yok.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.dnm_d2.donem_sabitleri import (
    CALISMA_KOK,
    D1_CALISMA_KOK,
    D1_KAPANIS,
    D2_ACILIS_YEREL,
    D2_BITIS_DAHIL,
    D2_BITIS_KARAR,
    D2_HARIC_UST_SINIR,
    KAYNAK_FIRMA_NO,
    ONERILEN_FIRMA_DB,
    ONERILEN_SISTEM_DB,
    PROFIL_ADI,
    bitis_secili_mi,
)

KOK = Path(__file__).resolve().parents[2]
CALISMA = KOK / CALISMA_KOK
D1 = KOK / D1_CALISMA_KOK


def acilis_anahtari(
    *,
    d1_kapanis_surum: str,
    hedef_db: str,
    ayinti_id: str,
) -> str:
    """Kaynak firma + D1 sürüm + D2 hedef + ayrıntı → tek açılış anahtarı."""
    return f"D2AC|{KAYNAK_FIRMA_NO}|{d1_kapanis_surum}|{hedef_db}|{ayinti_id}"


def sozlesme() -> dict[str, Any]:
    return {
        "format": "d2-acilis-sozlesme-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "calisma_modu": "HAZIRLIK",
        "kaynak_firma_no": KAYNAK_FIRMA_NO,
        "d1_kapanis": D1_KAPANIS.isoformat(),
        "d2_acilis": D2_ACILIS_YEREL.isoformat(),
        "d2_bitis_secili": bitis_secili_mi(),
        "D2_BITIS_DAHIL": D2_BITIS_DAHIL.isoformat() if D2_BITIS_DAHIL else None,
        "D2_HARIC_UST_SINIR": D2_HARIC_UST_SINIR.isoformat() if D2_HARIC_UST_SINIR else None,
        "bitis_karari": D2_BITIS_KARAR,
        "aktarim_kabulu_degil": True,
        "tek_kez_kural": (
            "Kabul edilmiş 31.08.2026 kapanışı 01.09.2026 açılışı olarak yalnız bir kez; "
            "çalışma/dosya yeniden çalıştı diye yeni açılış üretilmez."
        ),
        "cift_etki_onleme": {
            "d1_gecmis_yeniden_yukleme": False,
            "acilis_plus_donem_hareketi_ayri": True,
            "irsaliye_d1_fatura_d2_cift_cikis": False,
            "pos_bekleyen_plus_mevduat_cift_sayim": False,
            "toplu_acilis_plus_lot_ayrintisi_cift_giris": False,
            "fifo_valor_yeni_mali_kayit_uretmez": True,
        },
        "gruplar": [
            "cari",
            "fifo_valor",
            "stok_depo_lot",
            "kasa_banka",
            "pos",
            "kart_kredi",
            "diger",
            "bekleyen_belge",
        ],
        "hedef_onerilen": {
            "sistem_db": ONERILEN_SISTEM_DB,
            "firma_db": ONERILEN_FIRMA_DB,
            "profil": PROFIL_ADI,
            "olusturuldu": False,
            "k06": False,
        },
        "d1_calisma": str(D1).replace("\\", "/"),
        "k05": False,
        "mali_yazim": False,
    }


def yaz() -> Path:
    CALISMA.mkdir(parents=True, exist_ok=True)
    (CALISMA / "plan").mkdir(parents=True, exist_ok=True)
    yol = CALISMA / "plan" / "ACILIS_SOZLESME.json"
    veri = sozlesme()
    yol.write_text(json.dumps(veri, ensure_ascii=False, indent=2), encoding="utf-8")
    return yol


if __name__ == "__main__":
    p = yaz()
    print(p)
