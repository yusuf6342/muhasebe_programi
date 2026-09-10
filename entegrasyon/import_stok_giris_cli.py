"""CLI: python -m entegrasyon.import_stok_giris_cli --api
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "EvoBulut a_kalan miktarlarını stok GİRİŞ (açılış) hareketi olarak aktar. "
            "Belge öneki EVB-SG-; ayrı stok giriş fişi listesi API'de yok."
        )
    )
    parser.add_argument("--api", action="store_true", help="evobulut.env ile API çek")
    parser.add_argument(
        "--tarih",
        default="",
        help="Giriş tarihi YYYY-MM-DD (varsayılan: bugün)",
    )
    parser.add_argument("--ara", default="", help="API stok arama filtresi (opsiyonel)")
    parser.add_argument(
        "--depo",
        default="ANA DEPO",
        help="Hedef depo adı (varsayılan: ANA DEPO)",
    )
    args = parser.parse_args(argv)

    if not args.api:
        parser.error("--api gerekli")
        return 2

    fis_tarihi = date.today()
    if args.tarih.strip():
        fis_tarihi = datetime.strptime(args.tarih.strip(), "%Y-%m-%d").date()

    from entegrasyon.stok_giris_import import aktar_api_den

    sonuc = aktar_api_den(tarih=fis_tarihi, depo_adi=args.depo, ara=args.ara)
    print(
        f"Çekilen={sonuc.cekilen} Oluşturulan={sonuc.olusturulan} "
        f"Atlanan={sonuc.atlanan} SıfırKalan={sonuc.sifir_kalan} "
        f"Hata={len(sonuc.hatalar)}"
    )
    for h in sonuc.hatalar[:30]:
        print(h, file=sys.stderr)
    return 0 if not sonuc.hatalar else 1


if __name__ == "__main__":
    raise SystemExit(main())
