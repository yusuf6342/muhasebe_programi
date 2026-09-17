"""CLI: EvoBulut banka kartlarını Cin Muhasebe'ye aktar.

  python -m entegrasyon.import_banka_kart_cli --api
  python -m entegrasyon.import_banka_kart_cli --api --karsilastir
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EvoBulut banka kart aktarımı")
    parser.add_argument("--api", action="store_true", help="evobulut.env ile API çek")
    parser.add_argument(
        "--karsilastir",
        action="store_true",
        help="Yalnız karşılaştır; yazma yapma",
    )
    parser.add_argument(
        "--guncelleme-yok",
        action="store_true",
        help="Mevcut kartları güncelleme; yalnız yeni + eşleştirme",
    )
    args = parser.parse_args(argv)
    if not args.api:
        print("Kullanım: python -m entegrasyon.import_banka_kart_cli --api", file=sys.stderr)
        return 2

    from entegrasyon.evobulut_client import EvobulutApiError, EvobulutConfigError, EvobulutClient, load_credentials
    from entegrasyon.banka_kart_import import aktar_api_den, aktar_satirlari, karsilastir

    try:
        client = EvobulutClient(load_credentials())
        client.login()
        satirlar = client.banka_kart_listesi()
    except (EvobulutConfigError, EvobulutApiError, ValueError) as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 1

    rapor = karsilastir(satirlar)
    print(
        f"Evo={rapor.evo_adet} Yerel={rapor.yerel_adet} "
        f"Eşleşen={len(rapor.eslesen)} "
        f"Sadece Evo={len(rapor.sadece_evo)} "
        f"Sadece Yerel={len(rapor.sadece_yerel)}"
    )
    for e in rapor.eslesen[:30]:
        print(f"  = [{e['yontem']}] Evo#{e['evo_id']} {e['evo_adi']} ↔ Yerel#{e['yerel_id']} {e['yerel_adi']}")
    for e in rapor.sadece_evo[:30]:
        print(f"  + Evo#{e['evo_id']} {e['evo_adi']}")
    for e in rapor.sadece_yerel[:30]:
        print(f"  · Yerel#{e['yerel_id']} {e['yerel_adi']}")

    if args.karsilastir:
        return 0

    sonuc = aktar_satirlari(satirlar, guncelle=not args.guncelleme_yok)
    print(
        f"Aktarım: Oluşturulan={sonuc.olusturulan} Güncellenen/Atlanan={sonuc.atlanan} "
        f"Hata={len(sonuc.hatalar)}"
    )
    for h in sonuc.hatalar[:20]:
        print(f"  ! {h}")
    return 0 if not sonuc.hatalar else 1


if __name__ == "__main__":
    raise SystemExit(main())
