"""CLI: EvoBulut Gelir/Gider aktarımı.

  python -m entegrasyon.import_gelir_gider_cli --api
  python -m entegrasyon.import_gelir_gider_cli --api --max 20
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EvoBulut Gelir/Gider aktarımı")
    parser.add_argument("--api", action="store_true", help="API'den çek (zorunlu)")
    parser.add_argument("--max", type=int, default=None, help="En fazla N kayıt")
    parser.add_argument("--ara", default="", help="API ara filtresi")
    args = parser.parse_args(argv)
    if not args.api:
        print("Kullanım: python -m entegrasyon.import_gelir_gider_cli --api", file=sys.stderr)
        return 2

    from entegrasyon.evobulut_client import EvobulutApiError, EvobulutConfigError
    from entegrasyon.gelir_gider_import import aktar_api_den

    try:
        sonuc = aktar_api_den(max_adet=args.max, ara=args.ara, progress=print)
    except (EvobulutConfigError, EvobulutApiError, ValueError) as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 1

    print(
        f"Çekilen={sonuc.cekilen} Oluşturulan={sonuc.olusturulan} "
        f"Atlanan={sonuc.atlanan} Hata={len(sonuc.hatalar)}"
    )
    for h in sonuc.hatalar[:15]:
        print(f"  ! {h}")
    if len(sonuc.hatalar) > 15:
        print(f"  … +{len(sonuc.hatalar) - 15} hata")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
