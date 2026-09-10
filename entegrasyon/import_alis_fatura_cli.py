"""CLI: EvoBulut alış faturalarını aktar.

  python -m entegrasyon.import_alis_fatura_cli --api
  python -m entegrasyon.import_alis_fatura_cli --api --max 5
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EvoBulut alış fatura aktarımı")
    parser.add_argument("--api", action="store_true", help="API'den çek (zorunlu)")
    parser.add_argument("--max", type=int, default=None, help="En fazla N fatura (test)")
    parser.add_argument("--bas", default="", help="Başlangıç tarihi gg.aa.yyyy")
    parser.add_argument("--bit", default="", help="Bitiş tarihi gg.aa.yyyy")
    args = parser.parse_args(argv)
    if not args.api:
        print("Kullanım: python -m entegrasyon.import_alis_fatura_cli --api", file=sys.stderr)
        return 2

    from entegrasyon.alis_fatura_import import aktar_api_den
    from entegrasyon.evobulut_client import EvobulutApiError, EvobulutConfigError

    try:
        sonuc = aktar_api_den(
            tarih_bas=args.bas,
            tarih_son=args.bit,
            max_adet=args.max,
        )
    except (EvobulutConfigError, EvobulutApiError) as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 1

    print(
        f"Çekilen={sonuc.cekilen} Oluşturulan={sonuc.olusturulan} "
        f"Atlanan={sonuc.atlanan} StokEklenen={sonuc.stok_eklenen} "
        f"Hata={len(sonuc.hatalar)}"
    )
    for h in sonuc.hatalar[:20]:
        print(f"  ! {h}")
    if len(sonuc.hatalar) > 20:
        print(f"  … +{len(sonuc.hatalar) - 20} hata daha")
    return 0 if not sonuc.hatalar else 0


if __name__ == "__main__":
    raise SystemExit(main())
