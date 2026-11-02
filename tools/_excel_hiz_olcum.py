"""Excel aktarım hız ölçümü — 1k / 10k / 50k satır (yazma + okuma + doğrulama).

TEST DB ortam değişkeni ile çalışır; DB'ye kayıt yazmaz (yalnız doğrulama).
"""
from __future__ import annotations

import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault(
    "MUHASEBE_DB_DIR",
    str(Path(os.environ.get("LOCALAPPDATA", "")) / "CinMuhasebeTest" / "data"),
)

from excel_aktarim.importers.fatura_excel import FaturaExcelImporter, SATIS_FATURA_TIPI
from excel_aktarim.reader import ExcelReaderService
from excel_aktarim.writer import excel_yaz


def _satirlar(n: int) -> list[list]:
    # Yeniden alınabilir fatura satır şeması (doğrulama stok/cari bulamayabilir — süre ölçülür)
    rows = []
    for i in range(n):
        rows.append(
            [
                f"G{i // 10:05d}",
                "SATIS",
                f"HIZ-{i:06d}",
                "02.11.2026",
                "M00001",
                "TRY",
                "ANA DEPO",
                f"{i:013d}",
                f"Urun {i}",
                "1",
                "Adet",
                "10,00",
                "0",
                "20",
                "Hariç",
                "",
            ]
        )
    return rows


BASLIKLAR = [
    "Fatura Grubu",
    "Belge Türü",
    "Belge No",
    "Tarih",
    "Cari Kodu",
    "Para Birimi",
    "Depo",
    "Ürün Barkodu veya Kodu",
    "Ürün Açıklaması",
    "Miktar",
    "Birim",
    "Birim Fiyat",
    "İskonto %",
    "KDV %",
    "Fiyat Esası",
    "Lot",
]
TIPLER = ["metin", "metin", "kod", "tarih", "kod", "metin", "metin", "kod", "metin", "miktar", "metin", "para", "yuzde", "yuzde", "metin", "metin"]


def olc(n: int, tekrar: int = 3) -> dict:
    yazmalar, okumalar, dogrulamalar = [], [], []
    with tempfile.TemporaryDirectory() as tmp:
        for t in range(tekrar):
            yol = Path(tmp) / f"hiz_{n}_{t}.xlsx"
            data = _satirlar(n)
            t0 = time.perf_counter()
            excel_yaz(
                yol,
                basliklar=BASLIKLAR,
                satirlar=data,
                kolon_tipleri=TIPLER,
                amac="yeniden_al",
                meta={"sablon_turu": "satis_fatura_excel", "kayit_sayisi": n},
            )
            yazmalar.append((time.perf_counter() - t0) * 1000)

            t0 = time.perf_counter()
            okuma = ExcelReaderService.oku(yol, max_satir=max(n + 10, 60_000))
            okumalar.append((time.perf_counter() - t0) * 1000)

            # Basit eşleme: başlık → alan (otomatik)
            from excel_aktarim.mapping import ColumnMappingService
            from excel_aktarim.types import getir

            tip = getir("satis_fatura_excel")
            esleme = ColumnMappingService.otomatik_esle(tip, okuma.basliklar)
            mapped = []
            for ham in okuma.satirlar:
                kayit = {}
                for baslik, deger in ham.items():
                    alan = esleme.esleme.get(baslik)
                    if alan:
                        kayit[alan] = deger
                mapped.append(kayit)
            imp = FaturaExcelImporter(SATIS_FATURA_TIPI, "SATIS")
            t0 = time.perf_counter()
            # Büyük dosyada DB lookup yavaş olabilir — yine de gerçek doğrulama
            rapor = imp.dogrula_satirlar(mapped[: min(len(mapped), n)])
            dogrulamalar.append((time.perf_counter() - t0) * 1000)
            _ = rapor.hatali
    return {
        "n": n,
        "yaz_medyan_ms": statistics.median(yazmalar),
        "yaz_max_ms": max(yazmalar),
        "oku_medyan_ms": statistics.median(okumalar),
        "oku_max_ms": max(okumalar),
        "dogrula_medyan_ms": statistics.median(dogrulamalar),
        "dogrula_max_ms": max(dogrulamalar),
        "tekrar": tekrar,
    }


def main():
    print("Excel hız ölçümü (TEST veri yolu env)", flush=True)
    # Önce küçük ısınma
    olc(100, tekrar=1)
    for n in (1000, 10000, 50000):
        print(f"--- {n} satır ---", flush=True)
        r = olc(n, tekrar=3 if n <= 10000 else 2)
        print(
            f"n={r['n']} yaz medyan={r['yaz_medyan_ms']:.0f} max={r['yaz_max_ms']:.0f} | "
            f"oku medyan={r['oku_medyan_ms']:.0f} max={r['oku_max_ms']:.0f} | "
            f"dogrula medyan={r['dogrula_medyan_ms']:.0f} max={r['dogrula_max_ms']:.0f}",
            flush=True,
        )


if __name__ == "__main__":
    main()
