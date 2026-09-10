"""CLI: python -m entegrasyon.import_cari_acilis_cli --api
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="EvoBulut cari bakiyelerini açılış / devir fişi olarak aktar"
    )
    parser.add_argument("--api", action="store_true", help="evobulut.env ile API çek")
    parser.add_argument(
        "--tarih",
        default="",
        help="Açılış tarihi YYYY-MM-DD (varsayılan: bugün)",
    )
    args = parser.parse_args(argv)

    if not args.api:
        parser.error("--api gerekli")
        return 2

    fis_tarihi = date.today()
    if args.tarih.strip():
        fis_tarihi = datetime.strptime(args.tarih.strip(), "%Y-%m-%d").date()

    from entegrasyon.cari_acilis_import import aktar_api_den

    sonuc = aktar_api_den(tarih=fis_tarihi)
    print(
        f"Çekilen={sonuc.cekilen} Oluşturulan={sonuc.olusturulan} "
        f"Atlanan={sonuc.atlanan} SıfırBakiye={sonuc.sifir_bakiye} "
        f"Hata={len(sonuc.hatalar)}"
    )
    for h in sonuc.hatalar[:30]:
        print(h, file=sys.stderr)
    return 0 if not sonuc.hatalar else 1


if __name__ == "__main__":
    raise SystemExit(main())
