"""Ana makine CALISTIR sonucu + terminal salt okuma → manifest/durum güncelle.

K05/K06/mali/exe bayraklarını true yapmaz. D1 DB yeniden oluşturmaz.

  .venv\\Scripts\\python.exe -m tools.dnm_d2.rapor_ana_makine_sonuc_isle
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from tools.dnm_d2.donem_sabitleri import CALISMA_KOK, D1_CALISMA_KOK

KOK = Path(__file__).resolve().parents[2]
CALISMA = KOK / CALISMA_KOK
D1 = KOK / D1_CALISMA_KOK


def _o(p: Path) -> dict:
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8-sig"))


def main() -> int:
    ana = _o(CALISMA / "yedek" / "CALISTIR_SONUC_ANA_MAKINE_20261107_160153.json")
    term = _o(CALISMA / "yedek" / "PG_D2_TERMINAL_SALT_OKUMA.json")
    devam = _o(D1 / "DEVIR1_DEVAM_NOTU_OZET.json")

    zaman = datetime.now().astimezone().isoformat(timespec="seconds")
    paket_duzeltme = {
        "kaynak": "kurulum/paket_d2_ana (00_ON_KONTROL / 01_CALISTIR / ON_KONTROL.cmd)",
        "duzeltme_notu": "kurulum/paket_d2_ana/DUZELTME_NOTU.txt",
        "referans_zip": "paket/CIN_D2_HAZIRLIK_DUZELTILMIS_20261107.zip",
        "yeniden_kurulum_yapilmadi": True,
        "mevcut_d2_hedefler_dokunulmadi": True,
    }

    hazirlik = {
        "format": "d2-ana-makine-hazirlik-sonuc-v1",
        "zaman": zaman,
        "ana_makine_calistir_basarili": bool(ana.get("basarili")),
        "ana_makine_rapor": "yedek/CALISTIR_SONUC_ANA_MAKINE_20261107_160153.json",
        "computername": ana.get("computername"),
        "pg_host_calistir": ana.get("pg_host"),
        "db_durum": ana.get("db_durum"),
        "sema_tablo": {
            k: (v or {}).get("tablo") for k, v in (ana.get("sema") or {}).items()
        },
        "restore": ana.get("restore"),
        "cin_app_yetki": {
            "once": ana.get("cin_app_yetkileri_once"),
            "sonra": ana.get("cin_app_yetkileri_sonra"),
            "createdb_verilmedi": True,
        },
        "yedek_klasor_ana_makine": ana.get("yedek_klasor"),
        "terminal_salt_okuma": {
            "ok": term.get("ok"),
            "host": (term.get("baglanti") or {}).get("host"),
            "kanit": "yedek/PG_D2_TERMINAL_SALT_OKUMA.json",
            "engel": (
                None
                if term.get("ok")
                else "pg_hba: terminal 192.168.1.133 → cin_app + D2 DB adları yok"
            ),
            "kullanici_islemi": (
                None
                if term.get("ok")
                else "DESKTOP-CGSE5GK: .\\kurulum\\sunucu\\13_pg_hba_d2_db_izin.ps1 sonra reload"
            ),
            "hedefler": term.get("hedefler"),
        },
        "paket_duzeltmeleri_kaynakta": paket_duzeltme,
        "d1_devam_karari": devam.get("karar"),
        "k05": False,
        "k06": False,
        "mali_yazim": False,
        "exe": False,
        "sinir": (
            "Altyapı/şema + izole yedek-restore hazırlığı. "
            "Kaynak bakiye mutabakatı / mali aktarım kabulü değildir."
        ),
    }
    (CALISMA / "ANA_MAKINE_HAZIRLIK_RAPORU.json").write_text(
        json.dumps(hazirlik, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # MANIFEST — yalnız hazırlık alanları
    man_yol = CALISMA / "MANIFEST.json"
    if man_yol.is_file():
        man = _o(man_yol)
        man["zaman"] = zaman
        man["hedef_onerilen"]["olusturuldu"] = bool(ana.get("basarili"))
        man["yedek_izolasyon"] = {
            "planlandi": True,
            "denendi": True,
            "basarili": bool(ana.get("basarili")),
            "durum": (
                "ANA_MAKINE_OK_TERMINAL_HBA_BEKLIYOR"
                if ana.get("basarili") and not term.get("ok")
                else ("ANA_MAKINE_VE_TERMINAL_OK" if term.get("ok") else "KISMI")
            ),
            "betik": "kurulum/paket_d2_ana/01_CALISTIR.ps1",
            "cin_app_createdb": False,
            "ana_makine_kanit": "yedek/CALISTIR_SONUC_ANA_MAKINE_20261107_160153.json",
            "terminal_kanit": "yedek/PG_D2_TERMINAL_SALT_OKUMA.json",
            "erteleme": False,
            "not": hazirlik["sinir"],
        }
        man["ana_makine_hazirlik"] = {
            "erteleme": False,
            "basarili": bool(ana.get("basarili")),
            "rapor": "ANA_MAKINE_HAZIRLIK_RAPORU.json",
            "k05": False,
            "k06": False,
        }
        # bayrakları koru
        man["k05"] = False
        man["k06"] = False
        man["mali_yazim"] = False
        man["exe"] = False
        ham = json.dumps(man, ensure_ascii=False, indent=2).encode("utf-8")
        man_yol.write_bytes(ham)
        sha = hashlib.sha256(ham).hexdigest().upper()
        (CALISMA / "MANIFEST.json.sha256").write_text(
            f"{sha}  MANIFEST.json\n", encoding="ascii"
        )

    d2r = CALISMA / "D2_HAZIRLIK_DURUM_RAPORU.json"
    if d2r.is_file():
        rep = _o(d2r)
        rep["zaman"] = zaman
        rep["ana_makine_hazirlik"] = hazirlik
        rep["yedek_izolasyon"] = {
            "zaman": zaman,
            "basarili": bool(ana.get("basarili")),
            "k06": False,
            "durum": man["yedek_izolasyon"]["durum"] if man_yol.is_file() else None,
            "kanit": "yedek/CALISTIR_SONUC_ANA_MAKINE_20261107_160153.json",
        }
        eng = [
            (
                "Terminal D2 erişimi: ana makinede "
                ".\\kurulum\\sunucu\\13_pg_hba_d2_db_izin.ps1 (pg_hba D2 DB adları)"
            ),
            (
                "D2 açılışı öncesi zorunlu D1: Cari22 Detay, FIFO/LOT, K05 — "
                "diğer D1 işleri D2 sonrası DEVIR1_DEVAM_NOTU listesinden"
            ),
            "Cari22: Cari Kart → Hesap Ekstresi Detay (21 cari)",
            "İş bitimi sonrası ön toplama kimlik+sürüm tamamla",
            "K05/K06 sonrası mali yazım — EXE yok",
        ]
        rep["kullanicidan_somut"] = eng
        rep["d1_devam_karari"] = {
            "kesin": True,
            "metin": devam.get("karar")
            or "Devir 2 sonrasında Devir 1 çalışmasına devam edilecek",
            "notu": "kurulum/dnm_d1_20260831/DEVIR1_DEVAM_NOTU.json",
        }
        d2r.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    # YEDEK özet
    (CALISMA / "YEDEK_IZOLASYON_DENEME_OZET.json").write_text(
        json.dumps(
            {
                "zaman": zaman,
                "basarili": bool(ana.get("basarili")),
                "k06": False,
                "aktarim_engeli": True,  # K05/kaynak kabul yok
                "durum": "ANA_MAKINE_OK_TERMINAL_HBA_BEKLIYOR",
                "terminal_salt_okuma_ok": bool(term.get("ok")),
                "erteleme": False,
                "kanit": "yedek/CALISTIR_SONUC_ANA_MAKINE_20261107_160153.json",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # D1 referans
    ref = {
        "zaman": zaman,
        "d1_devam_karari": {
            "kesin": True,
            "metin": "Devir 2 sonrasında Devir 1 çalışmasına devam edilecek",
        },
        "d1_notu": "kurulum/dnm_d1_20260831/DEVIR1_DEVAM_NOTU.json",
        "d1_koruma": True,
        "d1_db_uzerine_yazma_yok": True,
        "ana_makine_d2_hazirlik": bool(ana.get("basarili")),
        "d2_acilisi_oncesi_zorunlu_d1": [
            "Cari22 Detay",
            "FIFO/LOT",
            "sıfır maliyet sınıfı",
            "K05",
            "K06 (kanıtlı; hazırlık ≠ kabul)",
        ],
        "k05": False,
        "mali_yazim": False,
    }
    (CALISMA / "D1_DEVAM_REFERANS.json").write_text(
        json.dumps(ref, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(
        json.dumps(
            {
                "zaman": zaman,
                "ana_makine_ok": bool(ana.get("basarili")),
                "terminal_ok": bool(term.get("ok")),
                "k05": False,
                "k06": False,
                "sonraki": hazirlik["terminal_salt_okuma"].get("kullanici_islemi"),
                "rapor": "ANA_MAKINE_HAZIRLIK_RAPORU.json",
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
