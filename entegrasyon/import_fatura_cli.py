"""CLI: EvoBulut fatura/fiş/iade aktarımı (tur=31..35).

  python -m entegrasyon.import_fatura_cli --api --tur 31 --max 2
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EvoBulut fatura/fiş/iade aktarımı")
    parser.add_argument("--api", action="store_true", help="API'den çek (zorunlu)")
    parser.add_argument(
        "--tur",
        required=True,
        help="35=alış fiş, 31=satış, 32=alış iade, 33=satış iade, 34=satış fiş",
    )
    parser.add_argument("--max", type=int, default=None, help="En fazla N belge (test)")
    parser.add_argument("--bas", default="", help="Başlangıç tarihi gg.aa.yyyy")
    parser.add_argument("--bit", default="", help="Bitiş tarihi gg.aa.yyyy")
    args = parser.parse_args(argv)
    if not args.api:
        print("Kullanım: python -m entegrasyon.import_fatura_cli --api --tur 31", file=sys.stderr)
        return 2

    from entegrasyon.evobulut_client import EvobulutApiError, EvobulutConfigError
    from entegrasyon.fatura_import import aktar_api_den

    try:
        sonuc = aktar_api_den(
            tur=args.tur,
            tarih_bas=args.bas,
            tarih_son=args.bit,
            max_adet=args.max,
        )
    except (EvobulutConfigError, EvobulutApiError, ValueError) as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 1

    print(
        f"tur={args.tur} Çekilen={sonuc.cekilen} Oluşturulan={sonuc.olusturulan} "
        f"Atlanan={sonuc.atlanan} StokEklenen={sonuc.stok_eklenen} "
        f"OtoGiris={sonuc.oto_giris} Hata={len(sonuc.hatalar)}"
    )
    for h in sonuc.hatalar[:20]:
        print(f"  ! {h}")
    if len(sonuc.hatalar) > 20:
        print(f"  … +{len(sonuc.hatalar) - 20} hata daha")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
