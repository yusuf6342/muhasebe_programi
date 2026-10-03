"""Salt okunur: firma DB'sinde muhasebeleştirme ile ilgili özet (eşleştirmeler, evrak ve fiş sayıları).

    python tools/muhasebelestirme_durum_raporu.py "%LOCALAPPDATA%\\MuhasebeProgrami\\data\\muhasebe.db"
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


def main() -> None:
    yol = Path(sys.argv[1]).expanduser().resolve()
    c = sqlite3.connect(f"file:{yol.as_posix()}?mode=ro", uri=True)
    tablolar = {r[0] for r in c.execute("select name from sqlite_master where type='table'")}
    print("Eşleştirmeler:")
    for anahtar, hid in c.execute(
        "select e.anahtar, h.hesap_kodu from muhasebe_hesap_eslemeleri e "
        "left join muhasebe_hesap_plani h on h.id=e.hesap_id order by e.anahtar"
    ):
        print(f"  {anahtar:<26} {hid}")
    print("Fiş (kaynak_turu, durum):")
    for kt, d, n in c.execute(
        "select coalesce(kaynak_turu,'-'), durum, count(*) from muhasebe_fisleri group by 1,2 order by 1,2"
    ):
        print(f"  {kt:<24} {d:<12} {n}")
    for tablo, kosul in (
        ("satis_faturalari", "1=1"),
        ("alis_faturalari", "1=1"),
        ("satis_iade_faturalari", "1=1"),
        ("alis_iade_faturalari", "1=1"),
        ("hizmet_faturalari", "1=1"),
        ("gider_fisleri", "1=1"),
        ("kasa_makbuzlari", "1=1"),
        ("cari_islemleri", "islem_turu in ('Tahsilat','Ödeme')"),
    ):
        if tablo not in tablolar:
            print(f"{tablo}: tablo yok")
            continue
        sutunlar = {r[1] for r in c.execute(f'pragma table_info("{tablo}")')}
        grup = "durum" if "durum" in sutunlar else "'-'"
        satir = c.execute(f'select {grup}, count(*) from "{tablo}" where {kosul} group by 1').fetchall()
        print(f"{tablo}: {satir}")
    for t in sorted(x for x in tablolar if "muhasebeles" in x or "muhasebe_belge" in x):
        print(t, c.execute(f'select count(*) from "{t}"').fetchone()[0])
    c.close()


if __name__ == "__main__":
    main()
