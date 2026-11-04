"""SQLite → PostgreSQL geçiş aracı (iskelet).

- Kaynak: TEST kopyası (canlıya dokunmaz)
- Hedefte dolu DB varsa sessiz üzerine yazmaz
- Sequence/kimlik ayarı ve sayım doğrulaması sonraki adımda tamamlanır

Kullanım (örnek):
  set MUHASEBE_PG_PASSWORD=...
  .venv\\Scripts\\python.exe tools\\_sqlite_to_postgres_gecis.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    p = argparse.ArgumentParser(description="SQLite→PostgreSQL geçiş (iskelet)")
    p.add_argument(
        "--kaynak",
        type=Path,
        default=Path.home() / "AppData/Local/CinMuhasebeTest/yedekler_ag_hazirlik",
        help="Yedek/TEST kopya kökü (canlı yol vermeyin)",
    )
    p.add_argument("--dry-run", action="store_true", help="Yalnız plan yazdır")
    p.add_argument("--hedef-host", default="127.0.0.1")
    p.add_argument("--hedef-port", type=int, default=5432)
    p.add_argument("--sistem-db", default="cin_sistem_deneme")
    args = p.parse_args()

    print("Cin Muhasebe SQLite→PostgreSQL geçiş iskeleti")
    print(f"  kaynak: {args.kaynak}")
    print(f"  hedef: {args.hedef_host}:{args.hedef_port}/{args.sistem_db}")
    print("  NOT: Canlı GERÇEK veri yolu kullanılmaz; önce yedek kopya.")

    if not args.kaynak.exists():
        print("HATA: kaynak klasör yok. Önce TEST yedeği alın.")
        return 2

    from database.baglanti_modu import baglanti_sina, BaglantiAyari, CalismaKipi

    ayar = BaglantiAyari.from_dict(
        {
            "kipi": CalismaKipi.YEREL_AG_POSTGRES.value,
            "postgres": {
                "host": args.hedef_host,
                "port": args.hedef_port,
                "sistem_db": args.sistem_db,
                "ortam": "DENEME",
            },
        }
    )
    sina = baglanti_sina(ayar)
    if not sina.get("ok"):
        print("PostgreSQL henüz hazır değil / bağlantı yok:")
        print(" ", sina.get("hata"))
        print("Sunucu kurulumundan sonra tekrar çalıştırın (kurulum/SUNUCU_KURULUMU.txt).")
        if args.dry_run:
            print("dry-run: plan tamam (bağlantı olmadan).")
            return 0
        return 3

    print("Bağlantı OK:", sina.get("ozet"), sina.get("server_version"))
    print("Sonraki adımlar (henüz kodlanmadı):")
    print("  1) Boş hedef DB kontrolü (doluysa dur)")
    print("  2) Şema oluştur (SQLAlchemy metadata / migration)")
    print("  3) Tablo tablo kopya + sequence ayarı")
    print("  4) Kayıt sayısı / stok / cari / kasa karşılaştırma")
    if args.dry_run:
        print("dry-run bitti.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
