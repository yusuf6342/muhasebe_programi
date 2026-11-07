"""Yedek izolasyon durum notu — ana makine ertelemesiz; CREATEDB verme.

  .venv\\Scripts\\python.exe -m tools.dnm_d2.yedek_izolasyon_durum_guncelle
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from tools.dnm_d2.donem_sabitleri import (
    CALISMA_KOK,
    ONERILEN_FIRMA_DB,
    ONERILEN_SISTEM_DB,
)

KOK = Path(__file__).resolve().parents[2]
CALISMA = KOK / CALISMA_KOK


def main() -> int:
    onceki = {}
    yol_once = CALISMA / "yedek" / "YEDEK_IZOLASYON_DENEME.json"
    if yol_once.is_file():
        onceki = json.loads(yol_once.read_text(encoding="utf-8"))
    haz = {}
    yol_haz = CALISMA / "yedek" / "PG_D2_HEDEF_HAZIRLA.json"
    if yol_haz.is_file():
        haz = json.loads(yol_haz.read_text(encoding="utf-8"))
    dog = {}
    yol_dog = CALISMA / "yedek" / "PG_ANA_MAKINE_DOGRULA.json"
    if yol_dog.is_file():
        dog = json.loads(yol_dog.read_text(encoding="utf-8"))

    basarili = bool(haz.get("basarili"))
    out = {
        "format": "d2-yedek-izolasyon-durum-v3",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "cin_app_createdb_verilmedi": True,
        "cin_app_superuser_verilmedi": True,
        "parola_sohbet_log_yok": True,
        "erteleme": False,
        "izolasyon_hedef_arastirma": {
            "mevcut_yonetim_akisi": [
                "kurulum/sunucu/11_pg_dnm_d2_bos_hedef.ps1",
                "kurulum/sunucu/12_pg_dnm_d2_hedef_yedek_restore.ps1",
                "tools.dnm_d2.pg_d2_hedef_hazirla",
            ],
            "cin_app_ile_create_db": False,
            "neden": "cin_app rolcreatedb=false; genel CREATEDB/SUPERUSER verilmeyecek",
            "uzak_postgres_pg_hba": "KAPALI (192.168.1.133 → postgres)",
            "dar_kapsamli_kurulum_betigi": "kurulum/sunucu/12_pg_dnm_d2_hedef_yedek_restore.ps1",
            "hedefler": {
                "sistem": ONERILEN_SISTEM_DB,
                "firma": ONERILEN_FIRMA_DB,
                "restore_test_onerilen": {
                    "sistem": "cin_sistem_dnm_d2_restore_test",
                    "firma": "cin_firma_dnm_d2_restore_test",
                },
            },
            "deneme": "YAPILDI_PG_HBA_ENGEL" if haz else "BEKLIYOR",
            "ana_makine_gercek_d2": "ERTELEME_YOK_ONE_AL",
            "aciklama": (
                "Ana makine D2 hazırlığı öne alındı. Terminalden superuser CREATE "
                "pg_hba engelli; DESKTOP-CGSE5GK 127.0.0.1 ile 12_*.ps1 gerekli. "
                "K05/mali yazım ayrı; K06 kanıtsız başarılı değil."
            ),
        },
        "dogrulama_ozet": {
            "host": (dog.get("baglanti_ayari") or {}).get("host"),
            "hedef_durum": dog.get("hedef_durum"),
            "cin_app_yetki": dog.get("cin_app_yetki"),
        },
        "hazirla_deneme": {
            "zaman": haz.get("zaman"),
            "basarili": haz.get("basarili"),
            "kullanici_islemi": haz.get("kullanici_islemi"),
            "adim_ozet": [
                {"ad": a.get("ad"), "ok": a.get("ok")} for a in (haz.get("adimlar") or [])
            ],
        },
        "onceki_deneme": {
            "zaman": onceki.get("zaman"),
            "basarili": onceki.get("basarili"),
            "eksik": onceki.get("eksik"),
        },
        "denendi": True,
        "basarili": basarili,
        "k06": False,
        "k06_izolasyon_yedek_kaniti": bool(haz.get("k06_izolasyon_yedek_kaniti")),
        "mali_yazim": False,
        "aktarim_engeli": not basarili,
        "durum": (
            "BASARILI_KANIT"
            if basarili
            else "PG_HBA_ENGEL_ANA_MAKINE_12_BETIK_BEKLIYOR"
        ),
    }
    (CALISMA / "yedek").mkdir(parents=True, exist_ok=True)
    (CALISMA / "yedek" / "YEDEK_IZOLASYON_DURUM.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    ozet = {
        "zaman": out["zaman"],
        "basarili": basarili,
        "k06": False,
        "aktarim_engeli": not basarili,
        "durum": out["durum"],
        "betik": "kurulum/sunucu/12_pg_dnm_d2_hedef_yedek_restore.ps1",
        "createdb_cin_app": False,
        "erteleme": False,
        "deneme": out["izolasyon_hedef_arastirma"]["deneme"],
        "kanit": "yedek/YEDEK_IZOLASYON_DURUM.json",
    }
    (CALISMA / "YEDEK_IZOLASYON_DENEME_OZET.json").write_text(
        json.dumps(ozet, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(ozet, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
