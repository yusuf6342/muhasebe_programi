"""CLI: Cari virman Excel/CSV aktarımı (EvoBulut REST yok).

  python -m entegrasyon.import_cari_virman_cli --dosya virman.xlsx
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cari virman Excel/CSV aktarımı")
    parser.add_argument("--dosya", required=True, help="xlsx/xlsm/csv yolu")
    args = parser.parse_args(argv)

    from entegrasyon.cari_virman_import import aktar_dosyadan

    try:
        sonuc = aktar_dosyadan(args.dosya)
    except Exception as exc:  # noqa: BLE001
        print(f"Hata: {exc}", file=sys.stderr)
        return 1

    print(
        f"Çekilen={sonuc.cekilen} Oluşturulan={sonuc.olusturulan} "
        f"Atlanan={sonuc.atlanan} Hata={len(sonuc.hatalar)}"
    )
    for h in sonuc.hatalar[:20]:
        print(f"  ! {h}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
