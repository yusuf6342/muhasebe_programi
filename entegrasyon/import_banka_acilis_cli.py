"""CLI: EvoBulut banka açılış bakiyelerini aktar.

  python -m entegrasyon.import_banka_acilis_cli --api
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EvoBulut banka açılış bakiyesi aktarımı")
    parser.add_argument("--api", action="store_true")
    args = parser.parse_args(argv)
    if not args.api:
        print("Kullanım: python -m entegrasyon.import_banka_acilis_cli --api", file=sys.stderr)
        return 2

    from database.database import sistem_altyapisini_baslat
    from database.session_manager import oturum
    from entegrasyon.banka_acilis_import import aktar_banka_acilis_api_den
    from entegrasyon.evobulut_client import EvobulutApiError, EvobulutConfigError

    sistem_altyapisini_baslat()
    oturum.set_user(
        user_id=1,
        kullanici_adi="admin",
        ad_soyad="CLI",
        role_kod="YONETICI",
        role_ad="Yönetici",
        permissions=set(),
    )

    try:
        sonuc = aktar_banka_acilis_api_den(progress=print)
    except (EvobulutConfigError, EvobulutApiError, ValueError) as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 1

    print(
        f"Çekilen={sonuc.cekilen} AçılışSatır={sonuc.acilis_satir} "
        f"HesapGüncellenen={sonuc.hesap_guncellenen} "
        f"HareketSilinen={sonuc.hareket_silinen} Hata={len(sonuc.hatalar)}"
    )
    for h in sonuc.hatalar[:20]:
        print(f"  ! {h}")
    return 0 if not sonuc.hatalar else 1


if __name__ == "__main__":
    raise SystemExit(main())
