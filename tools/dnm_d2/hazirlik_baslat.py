"""D2 çalışma kökü + manifest + açılış sözleşmesi + kontrol planı iskeleti.

Gerçek DB oluşturmaz; D2_BITIS seçilmeden hareket yazımı yok.

  .venv\\Scripts\\python.exe -m tools.dnm_d2.hazirlik_baslat
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from tools.dnm_d2.acilis_sozlesme import yaz as yaz_acilis
from tools.dnm_d2.devam_kayit import kaydet as kaydet_devam, yukle as yukle_devam
from tools.dnm_d2.donem_sabitleri import (
    CALISMA_KOK,
    CALISMA_MODU,
    D1_CALISMA_KOK,
    D1_KAPANIS,
    D2_ACILIS_YEREL,
    D2_BITIS_DAHIL,
    D2_HARIC_UST_SINIR,
    KAYNAK_FIRMA_ADI,
    KAYNAK_FIRMA_NO,
    ONERILEN_FIRMA_DB,
    ONERILEN_SISTEM_DB,
    PROFIL_ADI,
    TALIMAT_DOCX,
    bitis_secili_mi,
)
from tools.dnm_d2.kimlik_esleme import KimlikDefteri

KOK = Path(__file__).resolve().parents[2]
CALISMA = KOK / CALISMA_KOK


def _kontrol_plan() -> dict:
    kontroller = []
    for i in range(1, 45):
        kontroller.append(
            {
                "kod": f"D2 {i:02d}",
                "durum": "BEKLIYOR",
                "kanit": None,
                "aciklama": None,
            }
        )
    # Bilinen hazırlık durumları
    for c in kontroller:
        if c["kod"] == "D2 02":
            c["durum"] = "KISMI"
            c["aciklama"] = f"Firma {KAYNAK_FIRMA_NO} biliniyor; oturumda yeniden doğrulanacak"
        if c["kod"] == "D2 03":
            if bitis_secili_mi():
                c["durum"] = "GECTI_PARAMETRE"
                c["aciklama"] = (
                    "01.09.2026 00:00 dahil; D2_BITIS_DAHIL=2026-11-07; "
                    "D2_HARIC_UST_SINIR=2026-11-08T00:00:00+03:00 — aktarım kabulü değil"
                )
            else:
                c["durum"] = "BEKLIYOR"
                c["aciklama"] = "D2_BITIS_DAHIL henüz seçilmedi"
        if c["kod"] in {"D2 06", "D2 01"}:
            c["durum"] = "BEKLIYOR"
            c["aciklama"] = "K05/K06 ve gerçek boş hedef yok — mali yazım kapalı"
    return {
        "format": "d2-kontrol-plan-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "kontroller": kontroller,
        "gecen": 0,
        "bekleyen": sum(1 for c in kontroller if c["durum"] == "BEKLIYOR"),
    }


def main() -> int:
    for alt in ("kaynak", "plan", "esleme", "rapor", "yedek", "test"):
        (CALISMA / alt).mkdir(parents=True, exist_ok=True)

    yaz_acilis()
    d = yukle_devam()
    d["asama"] = "HAZIRLIK"
    kaydet_devam(d)
    KimlikDefteri().kaydet()

    plan = _kontrol_plan()
    (CALISMA / "plan" / "KONTROL_PLAN.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Talimat hash (OneDrive yolu varsa)
    talimat_aday = [
        Path.home()
        / "OneDrive"
        / "Masaüstü"
        / "kulanılmamış cursor talimatları"
        / TALIMAT_DOCX,
        CALISMA / TALIMAT_DOCX,
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
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "calisma_modu": CALISMA_MODU,
        "kaynak_firma": {"no": KAYNAK_FIRMA_NO, "adi": KAYNAK_FIRMA_ADI},
        "d1_kapanis": D1_KAPANIS.isoformat(),
        "d2_acilis": D2_ACILIS_YEREL.isoformat(),
        "D2_BITIS_DAHIL": D2_BITIS_DAHIL.isoformat() if D2_BITIS_DAHIL else None,
        "D2_HARIC_UST_SINIR": D2_HARIC_UST_SINIR.isoformat() if D2_HARIC_UST_SINIR else None,
        "bitis_kullanicidan_istenecek": not bitis_secili_mi(),
        "aktarim_kabulu_degil": True,
        "hedef_onerilen": {
            "sistem": ONERILEN_SISTEM_DB,
            "firma": ONERILEN_FIRMA_DB,
            "profil": PROFIL_ADI,
            "olusturuldu": False,
        },
        "d1_calisma": D1_CALISMA_KOK,
        "talimat": talimat_meta,
        "k05": False,
        "k06": False,
        "mali_yazim": False,
        "exe": False,
        "yedek_izolasyon": {
            "planlandi": True,
            "denendi": False,
            "not": "İzole pg_dump/pg_restore denemesi hedef DB oluşunca; D1 arşivine restore yok",
        },
    }
    ham = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    (CALISMA / "MANIFEST.json").write_bytes(ham)
    sha = hashlib.sha256(ham).hexdigest().upper()
    (CALISMA / "MANIFEST.json.sha256").write_text(
        f"{sha}  MANIFEST.json\n", encoding="ascii"
    )

    yedek_plan = {
        "format": "d2-yedek-plan-v1",
        "korunan": list(
            __import__("tools.dnm_d2.donem_sabitleri", fromlist=["KORUNAN_HEDEFLER"]).KORUNAN_HEDEFLER
        ),
        "hedef_sistem": ONERILEN_SISTEM_DB,
        "hedef_firma": ONERILEN_FIRMA_DB,
        "adimlar": [
            "Boş D2 sistem+firma DB oluştur (TEMPLATE kopyalama yok)",
            "Şema uygula",
            "pg_dump izole yedek",
            "Ayrı restore DB’ye geri yükle ve doğrula",
            "D1 / RAY001 / kabul DB’lerine dokunma",
        ],
        "denendi": False,
        "k06": False,
    }
    (CALISMA / "yedek" / "YEDEK_PLAN.json").write_text(
        json.dumps(yedek_plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    ozet = {
        "zaman": manifest["zaman"],
        "calisma": CALISMA_KOK,
        "bitis_secili": bitis_secili_mi(),
        "talimat_sha16": (talimat_meta.get("sha256") or "")[:16] or None,
        "kontrol_bekleyen": plan["bekleyen"],
        "k05": False,
        "k06": False,
        "mali_yazim": False,
    }
    (CALISMA / "HAZIRLIK_OZET.json").write_text(
        json.dumps(ozet, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(ozet, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
