"""D2 bitiş tarihini kullanıcı kararıyla sabitle — manifest / sözleşme / kontrol.

Aktarım kabulü sayılmaz. K05/K06 false kalır.

  .venv\\Scripts\\python.exe -m tools.dnm_d2.bitis_sabitle
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from tools.dnm_d2.acilis_sozlesme import yaz as yaz_acilis
from tools.dnm_d2.donem_sabitleri import (
    CALISMA_KOK,
    CALISMA_MODU,
    D1_CALISMA_KOK,
    D1_KAPANIS,
    D2_ACILIS_YEREL,
    D2_BITIS_DAHIL,
    D2_BITIS_KARAR,
    D2_HARIC_UST_SINIR,
    D2_HARIC_UST_SINIR_UTC,
    KAYNAK_FIRMA_ADI,
    KAYNAK_FIRMA_NO,
    ONERILEN_FIRMA_DB,
    ONERILEN_SISTEM_DB,
    PROFIL_ADI,
    TALIMAT_DOCX,
    bitis_secili_mi,
    etki_d2_hareket_mi,
    kapsama_karari,
)

KOK = Path(__file__).resolve().parents[2]
CALISMA = KOK / CALISMA_KOK


def main() -> int:
    assert bitis_secili_mi()
    assert D2_BITIS_DAHIL.isoformat() == "2026-11-07"
    assert D2_HARIC_UST_SINIR.isoformat() == "2026-11-08T00:00:00+03:00"

    now = datetime.now().astimezone()
    yaz_acilis()

    # Kontrol plan D2 03
    plan_yol = CALISMA / "plan" / "KONTROL_PLAN.json"
    if plan_yol.is_file():
        plan = json.loads(plan_yol.read_text(encoding="utf-8"))
    else:
        plan = {"kontroller": []}
    for c in plan.get("kontroller") or []:
        if c.get("kod") == "D2 03":
            c["durum"] = "GECTI_PARAMETRE"
            c["aciklama"] = (
                "01.09.2026 00:00 dahil; D2_BITIS_DAHIL=2026-11-07; "
                "D2_HARIC_UST_SINIR=2026-11-08T00:00:00+03:00; Europe/Istanbul. "
                "Tarih sabiti ≠ aktarım kabulü."
            )
            c["kanit"] = "tools/dnm_d2/donem_sabitleri.py + MANIFEST.json"
    plan["zaman"] = now.isoformat(timespec="seconds")
    plan_yol.parent.mkdir(parents=True, exist_ok=True)
    plan_yol.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    # Sınır smoke (kod içi)
    sinir_test = {
        "d1_son_saniye": etki_d2_hareket_mi(
            datetime(2026, 8, 31, 23, 59, 59, 999000, tzinfo=D2_ACILIS_YEREL.tzinfo)
        ),
        "d2_ilk": etki_d2_hareket_mi(D2_ACILIS_YEREL),
        "bitis_dahil_gece_yarisi": etki_d2_hareket_mi(
            datetime(2026, 11, 7, 0, 0, 0, tzinfo=D2_ACILIS_YEREL.tzinfo)
        ),
        "bitis_son_saniye": etki_d2_hareket_mi(
            datetime(2026, 11, 7, 23, 59, 59, 999000, tzinfo=D2_ACILIS_YEREL.tzinfo)
        ),
        "haric_ust": etki_d2_hareket_mi(D2_HARIC_UST_SINIR),
        "tarih_yalniz_07": etki_d2_hareket_mi(D2_BITIS_DAHIL),
        "tarih_yalniz_08": etki_d2_hareket_mi(
            __import__("datetime").date(2026, 11, 8)
        ),
        "ornek_kapsama": kapsama_karari(
            etki_tarihi=datetime(2026, 10, 1, 12, 0, tzinfo=D2_ACILIS_YEREL.tzinfo),
            alma_zamani=now,
        ),
    }
    assert sinir_test["d1_son_saniye"] is False
    assert sinir_test["d2_ilk"] is True
    assert sinir_test["bitis_dahil_gece_yarisi"] is True
    assert sinir_test["bitis_son_saniye"] is True
    assert sinir_test["haric_ust"] is False
    assert sinir_test["tarih_yalniz_07"] is True
    assert sinir_test["tarih_yalniz_08"] is False

    (CALISMA / "plan" / "SINIR_TEST_SMOKE.json").write_text(
        json.dumps(
            {
                "format": "d2-sinir-test-smoke-v1",
                "zaman": now.isoformat(timespec="seconds"),
                "sonuclar": sinir_test,
                "ok": True,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # Ön toplama notu — bugün iş bitimi öncesi alınanlar; paket EOD sonrası tamamlanır
    on_toplama = {
        "format": "d2-on-toplama-v1",
        "zaman": now.isoformat(timespec="seconds"),
        "anlam": (
            "07.11.2026 iş bitiminden önce alınan D2 kapsamı verileri ön toplama sayılır. "
            "İş bitimi sonrası yeni/değişmiş kapsam içi kayıtlar kimlik+sürüm ile tamamlanır; "
            "mükerrer mali/stok etki üretilmez."
        ),
        "paket_durumu": "ON_TOPLAMA_PAKETI_ACIK",
        "tamamlama_kosulu": {
            "is_bitimi_sonrasi_degisiklik_kontrolu": True,
            "yontem": "kimlik + sürüm karşılaştırma",
            "mukerrer_etki_uretme": False,
            "tamamlandi": False,
            "not": (
                "Bugünkü ön toplama, iş bitimi sonrası değişiklik kontrolüyle "
                "tamamlanacak paket olarak işaretlendi"
            ),
        },
        "donem": {
            "baslangic": D2_ACILIS_YEREL.isoformat(),
            "D2_BITIS_DAHIL": D2_BITIS_DAHIL.isoformat(),
            "D2_HARIC_UST_SINIR": D2_HARIC_UST_SINIR.isoformat(),
            "saat_dilimi": "Europe/Istanbul",
        },
        "olcut": {
            "doneme_alma": "dogrulanmis_mali_veya_stok_etki_tarihi",
            "alma_zamani": "ayri_alan",
            "alma_zamani_kapsam_degil": True,
        },
        "bitis_kullanicidan_istenecek": False,
        "bitis_sabitlendi": True,
        "k05": False,
        "k06": False,
        "aktarim_kabulu": False,
    }
    (CALISMA / "plan" / "ON_TOPLAMA.json").write_text(
        json.dumps(on_toplama, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    talimat_aday = [
        Path.home()
        / "OneDrive"
        / "Masaüstü"
        / "kulanılmamış cursor talimatları"
        / TALIMAT_DOCX,
    ]
    talimat_meta = {"dosya": TALIMAT_DOCX, "sha256": None, "bulundu": False}
    for p in talimat_aday:
        if p.is_file():
            sha = hashlib.sha256(p.read_bytes()).hexdigest().upper()
            talimat_meta = {
                "dosya": str(p),
                "sha256": sha,
                "bulundu": True,
                "boyut": p.stat().st_size,
            }
            break

    manifest = {
        "format": "d2-hazirlik-manifest-v1",
        "zaman": now.isoformat(timespec="seconds"),
        "calisma_modu": CALISMA_MODU,
        "kaynak_firma": {"no": KAYNAK_FIRMA_NO, "adi": KAYNAK_FIRMA_ADI},
        "d1_kapanis": D1_KAPANIS.isoformat(),
        "d2_acilis": D2_ACILIS_YEREL.isoformat(),
        "D2_BITIS_DAHIL": D2_BITIS_DAHIL.isoformat(),
        "D2_HARIC_UST_SINIR": D2_HARIC_UST_SINIR.isoformat(),
        "D2_HARIC_UST_SINIR_UTC": D2_HARIC_UST_SINIR_UTC.isoformat(),
        "saat_dilimi": "Europe/Istanbul",
        "bitis_karari": D2_BITIS_KARAR,
        "bitis_kullanicidan_istenecek": False,
        "bitis_sabitlendi": True,
        "aktarim_kabulu_degil": True,
        "on_toplama": on_toplama,
        "kapsam_olcut": {
            "doneme_alma": "dogrulanmis_mali_stok_etki_tarihi",
            "alma_zamani_ayri": True,
        },
        "hedef_onerilen": {
            "sistem": ONERILEN_SISTEM_DB,
            "firma": ONERILEN_FIRMA_DB,
            "profil": PROFIL_ADI,
            "olusturuldu": False,
        },
        "d1_calisma": D1_CALISMA_KOK,
        "talimat": talimat_meta,
        "sinir_test_smoke": sinir_test,
        "k05": False,
        "k06": False,
        "mali_yazim": False,
        "exe": False,
        "yedek_izolasyon": {
            "planlandi": True,
            "denendi": True,
            "basarili": False,
            "durum": "BETIK_HAZIR_DENEME_BEKLIYOR",
            "betik": "kurulum/sunucu/11_pg_dnm_d2_bos_hedef.ps1",
            "cin_app_createdb": False,
            "not": (
                "cin_app CREATEDB/SUPERUSER verilmez; dar betik hazır; "
                "ana makinede superuser denemesi bekliyor"
            ),
        },
        "test_izolasyon": {
            "T01_T18": "18/18 OK",
            "T19_T22_izolasyon": "4/4 OK",
            "T19_T22_canli_kaynak": "AYRI_BEKLIYOR",
        },
    }
    ham = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    (CALISMA / "MANIFEST.json").write_bytes(ham)
    sha = hashlib.sha256(ham).hexdigest().upper()
    (CALISMA / "MANIFEST.json.sha256").write_text(
        f"{sha}  MANIFEST.json\n", encoding="ascii"
    )

    ozet = {
        "zaman": manifest["zaman"],
        "D2_BITIS_DAHIL": D2_BITIS_DAHIL.isoformat(),
        "D2_HARIC_UST_SINIR": D2_HARIC_UST_SINIR.isoformat(),
        "bitis_sabitlendi": True,
        "aktarim_kabulu": False,
        "sinir_test_ok": True,
        "k05": False,
        "k06": False,
        "mali_yazim": False,
        "manifest_sha16": sha[:16],
    }
    (CALISMA / "HAZIRLIK_OZET.json").write_text(
        json.dumps(ozet, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (CALISMA / "BITIS_SABITLE_OZET.json").write_text(
        json.dumps(ozet, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(ozet, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
