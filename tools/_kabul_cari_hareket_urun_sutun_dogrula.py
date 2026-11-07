"""M00700 ABERRA — SAF04886 / SAF04881 fatura ürün detayı sütun doğrulaması.

PG DENEME'ye bağlanır; GUI/EXE üretmez. Parola Credential Manager'dan.
"""
from __future__ import annotations

import json
import os
import socket
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.baglanti_modu import (  # noqa: E402
    BaglantiAyari,
    CalismaKipi,
    PostgresBaglanti,
)
import database.baglanti_modu as bm  # noqa: E402

HOST = "192.168.1.114"
SYS = "cin_sistem_kabul_20261105"
FR = "cin_firma_kabul_20261105"
CARI_KOD = "M00700"
BELGELER = ("SAF04886", "SAF04881")

_AYAR = BaglantiAyari(
    kipi=CalismaKipi.YEREL_AG_POSTGRES.value,
    postgres=PostgresBaglanti(
        host=HOST,
        port=5432,
        sistem_db=SYS,
        kullanici="cin_app",
        sslmode="verify-full",
        ortam="DENEME",
        firma_db=FR,
        terminal_kimligi="KABUL-URUN-SUTUN",
    ),
)
bm.ayari_yukle = lambda program_dir=None: _AYAR  # type: ignore
os.environ["MUHASEBE_DB_DIR"] = str(
    Path(os.environ.get("LOCALAPPDATA", "")) / "CinMuhasebeKabulDeneme_20261105" / "data"
)


def main() -> int:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from auth_ui import firma_oturumu_ac, firma_ozet
    from database.cari_fatura_detay_service import CariFaturaDetayService
    from database.database import (
        get_session,
        get_system_session,
        pg_firma_tanimi_mi,
        sistem_altyapisini_baslat,
    )
    from database.models.cari import Cari
    from database.models.satis_faturasi import SatisFaturasi
    from database.session_manager import oturum
    from database.system.models import Company, Role, User

    rapor: dict = {
        "zaman": datetime.now().isoformat(timespec="seconds"),
        "makine": socket.gethostname(),
        "cari_kod": CARI_KOD,
        "belgeler": {},
        "sonuc": "BEKLEMEDE",
    }
    try:
        sistem_altyapisini_baslat()
        with get_system_session() as s:
            ray = s.query(Company).filter(Company.firma_kodu == "RAY001").one()
            admin = (
                s.query(User)
                .options(selectinload(User.role))
                .join(Role, User.role_id == Role.id)
                .filter(Role.kod == "YONETICI")
                .order_by(User.id)
                .first()
            )
            if not admin:
                raise RuntimeError("YONETICI yok")
            oturum.user_id = admin.id
            oturum.role_kod = "YONETICI"
            oturum.kullanici_adi = getattr(admin, "kullanici_adi", None) or "admin"
            if not pg_firma_tanimi_mi(ray.db_path):
                raise RuntimeError(f"RAY001 pg değil: {ray.db_path}")
            ozet = firma_ozet(ray, donem_yukle=True)
            firma_oturumu_ac(ozet)

        with get_session() as s:
            cari = s.scalar(select(Cari).where(Cari.cari_kodu == CARI_KOD))
            if cari is None:
                raise RuntimeError(f"{CARI_KOD} bulunamadı")
            rapor["cari"] = {
                "id": int(cari.id),
                "unvan": cari.unvan,
                "kod": cari.cari_kodu,
            }
            for belge in BELGELER:
                fat = s.scalar(
                    select(SatisFaturasi).where(SatisFaturasi.fatura_no == belge)
                )
                if fat is None:
                    rapor["belgeler"][belge] = {"ok": False, "hata": "fatura yok"}
                    continue
                detay = CariFaturaDetayService.load_invoice_details(
                    int(fat.id),
                    "satis_faturasi",
                    cari_id=int(cari.id),
                )
                satirlar = detay.get("satirlar") or []
                ornek = []
                for sat in satirlar[:5]:
                    ornek.append(
                        {
                            "kod_barkod": (sat.get("urun_kodu") or sat.get("barkod") or ""),
                            "urun_adi": sat.get("urun_adi") or "",
                            "miktar": sat.get("miktar_goster") or "",
                            "birim": sat.get("birim") or "",
                            "fiyat": sat.get("net_birim_fiyat_goster")
                            or sat.get("birim_fiyat_goster")
                            or "",
                            "tutar": sat.get("net_goster") or "",
                        }
                    )
                rapor["belgeler"][belge] = {
                    "ok": bool(satirlar),
                    "fatura_id": int(fat.id),
                    "satir_sayisi": len(satirlar),
                    "ornek": ornek,
                    "sutunlar": [
                        "Kod/Barkod",
                        "Ürün Adı",
                        "Miktar",
                        "Birim",
                        "Fiyat",
                        "Tutar",
                    ],
                }

        ok = all(v.get("ok") for v in rapor["belgeler"].values()) and len(
            rapor["belgeler"]
        ) == len(BELGELER)
        rapor["sonuc"] = "GECTI" if ok else "KISMI"
        rapor["ui_not"] = (
            "Ürün alanları sütunlara yazılır; Açıklama'ya yığılmaz "
            "(tests/test_cari_hareket_urun_sutun.py)."
        )
    except Exception as exc:
        rapor["sonuc"] = "HATA"
        rapor["hata"] = str(exc)

    out = ROOT / "kurulum" / "GECIS_KABUL_CARI_HAREKET_URUN_SUTUN.json"
    out.write_text(json.dumps(rapor, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(rapor, ensure_ascii=False, indent=2))
    print("RAPOR", out)
    return 0 if rapor.get("sonuc") == "GECTI" else 1


if __name__ == "__main__":
    raise SystemExit(main())
