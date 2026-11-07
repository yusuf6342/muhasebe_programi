"""Ana makine D2 hazırlık kanıtını manifest / durum raporuna işler.

  .venv\\Scripts\\python.exe -m tools.dnm_d2.rapor_ana_makine_hazirlik
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from tools.dnm_d2.donem_sabitleri import CALISMA_KOK

KOK = Path(__file__).resolve().parents[2]
CALISMA = KOK / CALISMA_KOK
D1 = KOK / "kurulum" / "dnm_d1_20260831"


def _o(p: Path) -> dict:
    if p.is_file():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def main() -> int:
    dog = _o(CALISMA / "yedek" / "PG_ANA_MAKINE_DOGRULA.json")
    haz = _o(CALISMA / "yedek" / "PG_D2_HEDEF_HAZIRLA.json")
    ozet_dog = _o(CALISMA / "PG_ANA_MAKINE_DOGRULA_OZET.json")
    ozet_haz = _o(CALISMA / "PG_D2_HEDEF_HAZIRLA_OZET.json")

    rapor = {
        "format": "d2-ana-makine-hazirlik-rapor-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "karar": "Ana makine D2 hazırlığı sona bırakılmaz (erteleme yok)",
        "bu_pc": dog.get("bu_pc") or haz.get("bu_pc"),
        "dogrulanan": {
            "pg_host": (dog.get("baglanti_ayari") or {}).get("host"),
            "inet_server": (dog.get("canli_baglanti") or {}).get("inet_server_addr"),
            "pg_version": (dog.get("canli_baglanti") or {}).get("version"),
            "cin_app_yetki": dog.get("cin_app_yetki"),
            "mevcut_db_adet": len(dog.get("veritabanlari") or []),
            "mevcut_db_adlari": [d["datname"] for d in (dog.get("veritabanlari") or [])],
            "manifest_hedefler": dog.get("manifest_hedefler"),
            "hedef_durum": dog.get("hedef_durum"),
            "aktif_profil": (dog.get("baglanti_ayari") or {}),
            "aktif_kabul_baglanti_ok": True,
        },
        "yapilan_deneme": {
            "super_parola_yerel_gui": any(
                a.get("ad") == "super_baglanti" for a in (haz.get("adimlar") or [])
            ),
            "super_uzak_pg_hba": next(
                (
                    a
                    for a in (haz.get("adimlar") or [])
                    if a.get("ad") == "super_baglanti"
                ),
                None,
            ),
            "create_db": haz.get("db_durum"),
            "yedek_restore": haz.get("yedek_restore_ok"),
            "basarili": haz.get("basarili"),
        },
        "kalan_engel": {
            "kod": "PG_HBA_POSTGRES_UZAK_KAPALI",
            "aciklama": (
                "Terminal 192.168.1.133 → 192.168.1.114 user=postgres için "
                "pg_hba kaydı yok. cin_app CREATEDB=false. "
                "CREATE DATABASE yalnız ana makinede 127.0.0.1 superuser ile."
            ),
            "kullanici_islemi": haz.get("kullanici_islemi")
            or (
                "DESKTOP-CGSE5GK: .\\kurulum\\sunucu\\12_pg_dnm_d2_hedef_yedek_restore.ps1 "
                "-PgHost 127.0.0.1"
            ),
            "sonra_terminal": ".venv\\Scripts\\python.exe -m tools.dnm_d2.pg_d2_hedef_hazirla",
        },
        "korunan": {
            "kabul_profil": True,
            "cin_app_createdb_verilmedi": True,
            "mali_yazim": False,
            "k05": False,
            "k06_kanitsiz_basarili_isaretlenmedi": True,
            "exe": False,
        },
        "kanitlar": {
            "dogrula": "yedek/PG_ANA_MAKINE_DOGRULA.json",
            "hazirla_deneme": "yedek/PG_D2_HEDEF_HAZIRLA.json",
            "profil_sablon": "esleme/BAGLANTI_PROFIL_DNM_D2_20260901.json",
            "kullanici_adim": "KULLANICI_ANA_MAKINE_D2.md",
        },
    }
    yol = CALISMA / "ANA_MAKINE_HAZIRLIK_RAPORU.json"
    yol.write_text(json.dumps(rapor, ensure_ascii=False, indent=2), encoding="utf-8")

    # MANIFEST yedek alanı
    man_yol = CALISMA / "MANIFEST.json"
    if man_yol.is_file():
        man = json.loads(man_yol.read_text(encoding="utf-8"))
        man["zaman"] = rapor["zaman"]
        man["yedek_izolasyon"] = {
            "planlandi": True,
            "denendi": True,
            "basarili": bool(haz.get("basarili")),
            "durum": "PG_HBA_ENGEL_ANA_MAKINE_BETIK_BEKLIYOR",
            "betik": "kurulum/sunucu/12_pg_dnm_d2_hedef_yedek_restore.ps1",
            "cin_app_createdb": False,
            "dogrulama_kanit": "yedek/PG_ANA_MAKINE_DOGRULA.json",
            "deneme_kanit": "yedek/PG_D2_HEDEF_HAZIRLA.json",
            "erteleme": False,
            "not": rapor["kalan_engel"]["aciklama"],
        }
        man["hedef_onerilen"]["olusturuldu"] = bool(
            (dog.get("hedef_durum") or {}).get("cin_sistem_dnm_d2_20260901") == "VAR"
        )
        man["ana_makine_hazirlik"] = {
            "erteleme": False,
            "rapor": "ANA_MAKINE_HAZIRLIK_RAPORU.json",
            "basarili": bool(haz.get("basarili")),
        }
        ham = json.dumps(man, ensure_ascii=False, indent=2).encode("utf-8")
        man_yol.write_bytes(ham)
        sha = hashlib.sha256(ham).hexdigest().upper()
        (CALISMA / "MANIFEST.json.sha256").write_text(
            f"{sha}  MANIFEST.json\n", encoding="ascii"
        )

    # D2 durum
    d2r = CALISMA / "D2_HAZIRLIK_DURUM_RAPORU.json"
    if d2r.is_file():
        rep = json.loads(d2r.read_text(encoding="utf-8"))
        rep["zaman"] = rapor["zaman"]
        rep["ana_makine_hazirlik"] = rapor
        rep["yedek_izolasyon"] = ozet_haz or {
            "basarili": False,
            "durum": "PG_HBA_ENGEL",
        }
        engeller = [
            (
                "ANA MAKİNE ŞİMDİ: DESKTOP-CGSE5GK üzerinde "
                ".\\kurulum\\sunucu\\12_pg_dnm_d2_hedef_yedek_restore.ps1 -PgHost 127.0.0.1 "
                "(SecureString; cin_app CREATEDB yok)"
            ),
            "Sonra terminalde: python -m tools.dnm_d2.pg_d2_hedef_hazirla (şema+profil+doğrulama)",
            "Cari22: Cari Kart → Hesap Ekstresi Detay (21 cari); PDF Toplamı kullanma",
            "İş bitimi sonrası ön toplama kimlik+sürüm tamamla",
            "K05/K06 sonrası mali yazım — tarih ≠ kabul; EXE yok",
        ]
        rep["kullanicidan_somut"] = engeller
        if "talimat" in rep and isinstance(rep["talimat"], dict):
            rep["talimat"]["ana_makine_erteleme"] = False
        d2r.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    # Açık envanter K06 maddesini güncelle (hafif)
    acik = _o(D1 / "kaynak" / "D1_20260831_KAYNAK_DOGRULAMA_D1_D2_ACIK_ENVANTER.json")
    if acik:
        for a in acik.get("aciklar") or []:
            if a.get("madde", "").startswith("K06"):
                a["durum"] = "ANA_MAKINE_BETIK_BEKLIYOR"
                a["eksik_kaynak_belgesi"] = (
                    "pg_hba: uzak postgres kapalı; 12_*.ps1 127.0.0.1 bekliyor"
                )
                a["yapilacak"] = rapor["kalan_engel"]["kullanici_islemi"]
                a["kanit"] = "kurulum/dnm_d2_20260901/ANA_MAKINE_HAZIRLIK_RAPORU.json"
                a["deneme"] = ozet_haz
        acik["zaman"] = rapor["zaman"]
        acik["ana_makine_erteleme"] = False
        (D1 / "kaynak" / "D1_20260831_KAYNAK_DOGRULAMA_D1_D2_ACIK_ENVANTER.json").write_text(
            json.dumps(acik, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        ozet = _o(D1 / "D1_D2_ACIK_ENVANTER_OZET.json")
        ozet["zaman"] = rapor["zaman"]
        ozet["yedek_durum"] = "PG_HBA_ENGEL_ANA_MAKINE_BETIK_BEKLIYOR"
        ozet["ana_makine_erteleme"] = False
        (D1 / "D1_D2_ACIK_ENVANTER_OZET.json").write_text(
            json.dumps(ozet, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    print(
        json.dumps(
            {
                "zaman": rapor["zaman"],
                "basarili": haz.get("basarili"),
                "engel": rapor["kalan_engel"]["kod"],
                "islem": rapor["kalan_engel"]["kullanici_islemi"][:120],
                "kanit": "ANA_MAKINE_HAZIRLIK_RAPORU.json",
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
