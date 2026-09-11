"""CLI: EvoBulut irsaliye aktarımı.

  python -m entegrasyon.import_irsaliye_cli --api --tur 70 --max 2
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EvoBulut irsaliye aktarımı")
    parser.add_argument("--api", action="store_true")
    parser.add_argument("--tur", required=True, help="70=alış, 71=satış")
    parser.add_argument("--max", type=int, default=None)
    parser.add_argument("--bas", default="")
    parser.add_argument("--bit", default="")
    args = parser.parse_args(argv)
    if not args.api:
        print("Kullanım: python -m entegrasyon.import_irsaliye_cli --api --tur 70", file=sys.stderr)
        return 2

    from entegrasyon.evobulut_client import EvobulutApiError, EvobulutConfigError
    from entegrasyon.irsaliye_import import aktar_api_den

    try:
        sonuc = aktar_api_den(
            a_tur=args.tur,
            tarih_bas=args.bas,
            tarih_son=args.bit,
            max_adet=args.max,
        )
    except (EvobulutConfigError, EvobulutApiError, ValueError) as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 1

    print(
        f"a_tur={args.tur} Çekilen={sonuc.cekilen} Oluşturulan={sonuc.olusturulan} "
        f"Atlanan={sonuc.atlanan} Hata={len(sonuc.hatalar)}"
    )
    for h in sonuc.hatalar[:20]:
        print(f"  ! {h}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
