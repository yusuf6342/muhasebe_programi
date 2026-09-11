"""EvoBulut kalan belgeleri mantık sırasıyla aktarır.

Sıra:
  1) tur=35 Alış fişi
  2) tur=31 Satış fatura
  3) tur=32 Alış iade
  4) tur=33 Satış iade
  5) tur=34 Satış fişi
  6) Sipariş 50, 51
  7) İrsaliye 70, 71
  8) Kasa, Banka

  python -m entegrasyon.import_all_remaining_cli --api
  python -m entegrasyon.import_all_remaining_cli --api --max 1
  python -m entegrasyon.import_all_remaining_cli --api --skip-finans
"""

from __future__ import annotations

import argparse
import sys
import traceback
from collections.abc import Callable

from entegrasyon.evb_import_common import ImportSonuc, progress_log


def _ozet(ad: str, s: ImportSonuc) -> str:
    return (
        f"[{ad}] çekilen={s.cekilen} oluşturulan={s.olusturulan} "
        f"atlanan={s.atlanan} oto={s.oto_giris} stok+={s.stok_eklenen} "
        f"hata={len(s.hatalar)}"
    )


def calistir(
    *,
    max_adet: int | None = None,
    skip_finans: bool = False,
    only: str | None = None,
    progress=None,
) -> dict[str, ImportSonuc]:
    from entegrasyon.fatura_import import aktar_api_den as fatura_aktar
    from entegrasyon.irsaliye_import import aktar_api_den as irsaliye_aktar
    from entegrasyon.kasa_banka_import import aktar_banka_api_den, aktar_kasa_api_den
    from entegrasyon.siparis_import import aktar_api_den as siparis_aktar

    adimlar: list[tuple[str, Callable[[], ImportSonuc]]] = [
        ("fatura_35_alis_fis", lambda: fatura_aktar(tur="35", max_adet=max_adet, progress=progress)),
        ("fatura_31_satis", lambda: fatura_aktar(tur="31", max_adet=max_adet, progress=progress)),
        ("fatura_32_alis_iade", lambda: fatura_aktar(tur="32", max_adet=max_adet, progress=progress)),
        ("fatura_33_satis_iade", lambda: fatura_aktar(tur="33", max_adet=max_adet, progress=progress)),
        ("fatura_34_satis_fis", lambda: fatura_aktar(tur="34", max_adet=max_adet, progress=progress)),
        ("siparis_50", lambda: siparis_aktar(a_tur="50", max_adet=max_adet, progress=progress)),
        ("siparis_51", lambda: siparis_aktar(a_tur="51", max_adet=max_adet, progress=progress)),
        ("irsaliye_70", lambda: irsaliye_aktar(a_tur="70", max_adet=max_adet, progress=progress)),
        ("irsaliye_71", lambda: irsaliye_aktar(a_tur="71", max_adet=max_adet, progress=progress)),
    ]
    if not skip_finans:
        adimlar.extend(
            [
                ("kasa", lambda: aktar_kasa_api_den(max_adet=max_adet, progress=progress)),
                ("banka", lambda: aktar_banka_api_den(max_adet=max_adet, progress=progress)),
            ]
        )

    if only:
        adimlar = [a for a in adimlar if a[0] == only or only in a[0]]
        if not adimlar:
            raise ValueError(f"Bilinmeyen --only={only}")

    sonuclar: dict[str, ImportSonuc] = {}
    for ad, fn in adimlar:
        progress_log(progress, f"\n=== ADIM: {ad} ===")
        try:
            s = fn()
        except Exception as exc:  # noqa: BLE001
            s = ImportSonuc(hatalar=[f"ADIM_HATA: {exc}"])
            progress_log(progress, f"ADIM BAŞARISIZ: {exc}")
            traceback.print_exc()
        sonuclar[ad] = s
        progress_log(progress, _ozet(ad, s))
        for h in s.hatalar[:5]:
            progress_log(progress, f"  ! {h}")
        if len(s.hatalar) > 5:
            progress_log(progress, f"  … +{len(s.hatalar) - 5} hata")
    return sonuclar


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EvoBulut kalan belge aktarım orkestratörü")
    parser.add_argument("--api", action="store_true", help="API'den çek (zorunlu)")
    parser.add_argument("--max", type=int, default=None, help="Her adımda en fazla N belge")
    parser.add_argument("--skip-finans", action="store_true", help="Kasa/banka atla")
    parser.add_argument("--only", default=None, help="Tek adım adı (ör. fatura_31_satis)")
    args = parser.parse_args(argv)
    if not args.api:
        print(
            "Kullanım: python -m entegrasyon.import_all_remaining_cli --api",
            file=sys.stderr,
        )
        return 2

    from entegrasyon.evobulut_client import EvobulutApiError, EvobulutConfigError

    try:
        sonuclar = calistir(
            max_adet=args.max,
            skip_finans=args.skip_finans,
            only=args.only,
        )
    except (EvobulutConfigError, EvobulutApiError, ValueError) as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 1

    print("\n=== ÖZET ===")
    toplam_hata = 0
    for ad, s in sonuclar.items():
        print(_ozet(ad, s))
        toplam_hata += len(s.hatalar)
    print(f"Toplam hata satırı: {toplam_hata}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
