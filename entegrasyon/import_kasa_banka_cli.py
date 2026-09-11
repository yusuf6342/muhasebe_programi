"""CLI: EvoBulut kasa/banka aktarımı.

  python -m entegrasyon.import_kasa_banka_cli --api --mod kasa --max 2
  python -m entegrasyon.import_kasa_banka_cli --api --mod banka --max 2
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EvoBulut kasa/banka aktarımı")
    parser.add_argument("--api", action="store_true")
    parser.add_argument("--mod", required=True, choices=("kasa", "banka"))
    parser.add_argument("--max", type=int, default=None)
    parser.add_argument("--bas", default="")
    parser.add_argument("--bit", default="")
    args = parser.parse_args(argv)
    if not args.api:
        print(
            "Kullanım: python -m entegrasyon.import_kasa_banka_cli --api --mod kasa",
            file=sys.stderr,
        )
        return 2

    from entegrasyon.evobulut_client import EvobulutApiError, EvobulutConfigError
    from entegrasyon.kasa_banka_import import aktar_banka_api_den, aktar_kasa_api_den

    try:
        if args.mod == "kasa":
            sonuc = aktar_kasa_api_den(
                bas_tar=args.bas, son_tar=args.bit, max_adet=args.max
            )
        else:
            sonuc = aktar_banka_api_den(
                bas_tar=args.bas, son_tar=args.bit, max_adet=args.max
            )
    except (EvobulutConfigError, EvobulutApiError, ValueError) as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 1

    print(
        f"{args.mod} Çekilen={sonuc.cekilen} Oluşturulan={sonuc.olusturulan} "
        f"Atlanan={sonuc.atlanan} Hata={len(sonuc.hatalar)}"
    )
    for h in sonuc.hatalar[:20]:
        print(f"  ! {h}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
