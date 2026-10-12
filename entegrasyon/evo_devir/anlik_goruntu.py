"""Evo Bulut son durum anlık görüntüsü (salt okuma).

Cari, stok, kasa ve banka kartlarını; bakiye hesabı için banka ve kasa hareketlerini
tek bir JSON dosyasına yazar. Hiçbir veritabanına yazmaz. UID/şifre dosyaya girmez.

Kullanım:
    python -m entegrasyon.evo_devir.anlik_goruntu --cikti C:\\CinMuhasebeEvoDevir\\kaynak
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

from entegrasyon.evobulut_client import EvobulutClient, load_credentials


def _yillik(fn, bugun: date, ilk_yil: int = 2015) -> list[dict]:
    tum: list[dict] = []
    gorulen: set[str] = set()
    for yil in range(ilk_yil, bugun.year + 1):
        bas = f"01.01.{yil}"
        son = bugun.strftime("%d.%m.%Y") if yil == bugun.year else f"31.12.{yil}"
        dilim = fn(bas, son)
        for s in dilim:
            aid = str(s.get("G.a_id") or s.get("a_id") or s.get("R.a_id") or "").strip()
            if aid and aid in gorulen:
                continue
            if aid:
                gorulen.add(aid)
            tum.append(s)
        print(f"  {yil}: {len(dilim)} satir", flush=True)
    return tum


def cek(cikti_klasoru: Path) -> Path:
    t0 = time.time()
    bugun = date.today()
    istemci = EvobulutClient(load_credentials())
    istemci.login()

    def adim(ad: str, fn):
        t = time.time()
        veri = fn()
        print(f"{ad}: {len(veri)} kayit ({time.time() - t:.0f} sn)", flush=True)
        return veri

    goruntu = {
        "kaynak": "Evo Bulut API (ws.evobulut.com)",
        "cekilme_zamani": datetime.now().isoformat(timespec="seconds"),
        "devir_tarihi": bugun.isoformat(),
        "cariler": adim("cari", istemci.tum_carileri_cek),
        "stoklar": adim("stok", istemci.tum_stoklari_cek),
        "stok_kart_turleri": adim("stok kart turu", istemci.stok_kart_turleri),
        "kasalar": adim("kasa karti", istemci.kasa_kart_listesi),
        "bankalar": adim("banka karti", istemci.banka_kart_listesi),
    }
    print("banka hareketleri (yalniz bakiye hesabi icin):", flush=True)
    goruntu["banka_hareketleri"] = _yillik(
        lambda b, s: istemci.tum_banka_islemlerini_cek(bas_tar=b, son_tar=s), bugun
    )
    print("kasa hareketleri (yalniz bakiye hesabi icin):", flush=True)
    goruntu["kasa_hareketleri"] = _yillik(
        lambda b, s: istemci.tum_kasa_islemlerini_cek(bas_tar=b, son_tar=s), bugun
    )

    cikti_klasoru.mkdir(parents=True, exist_ok=True)
    yol = cikti_klasoru / f"evo_anlik_{datetime.now():%Y%m%d_%H%M%S}.json"
    ham = json.dumps(goruntu, ensure_ascii=False, indent=0, default=str).encode("utf-8")
    yol.write_bytes(ham)
    ozet = hashlib.sha256(ham).hexdigest()
    yol.with_suffix(".sha256").write_text(f"{ozet}  {yol.name}\n", encoding="ascii")
    print(f"yazildi: {yol} sha256={ozet[:16]}... toplam {time.time() - t0:.0f} sn", flush=True)
    return yol


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--cikti", default=r"C:\CinMuhasebeEvoDevir\kaynak")
    args = p.parse_args()
    cek(Path(args.cikti))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
