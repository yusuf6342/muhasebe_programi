"""CLI: python -m entegrasyon.import_cari_cli --dosya path.xlsx
   veya: python -m entegrasyon.import_cari_cli --api
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EvoBulut cari aktarımı")
    parser.add_argument("--dosya", help="Excel/CSV yolu")
    parser.add_argument("--api", action="store_true", help="evobulut.env ile API çek")
    parser.add_argument("--tur", default="Müşteri", help="Varsayılan cari türü")
    args = parser.parse_args(argv)

    if args.api:
        from entegrasyon.cari_import import aktar_api_den

        sonuc = aktar_api_den(varsayilan_tur=args.tur)
    elif args.dosya:
        from entegrasyon.cari_import import aktar_dosyadan

        sonuc = aktar_dosyadan(args.dosya, varsayilan_tur=args.tur)
    else:
        parser.error("--dosya veya --api gerekli")
        return 2

    print(
        f"Çekilen={sonuc.cekilen} Eklenen={sonuc.eklenen} "
        f"Güncellenen={sonuc.guncellenen} Atlanan={sonuc.atlanan} "
        f"Hata={len(sonuc.hatalar)}"
    )
    for h in sonuc.hatalar[:20]:
        print(h, file=sys.stderr)
    return 0 if not sonuc.hatalar else 1


if __name__ == "__main__":
    raise SystemExit(main())
