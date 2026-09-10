"""CLI: python -m entegrasyon.import_stok_cli --api
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EvoBulut stok aktarımı")
    parser.add_argument("--api", action="store_true", help="evobulut.env ile API çek")
    parser.add_argument("--ara", default="", help="API arama filtresi (opsiyonel)")
    args = parser.parse_args(argv)

    if not args.api:
        parser.error("--api gerekli")
        return 2

    from entegrasyon.stok_import import aktar_api_den

    sonuc = aktar_api_den(ara=args.ara)
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
