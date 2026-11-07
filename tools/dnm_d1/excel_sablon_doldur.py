"""Talimat Excel şablonuna gerçek kasa/banka kimliklerini doldurur.

Eksik ölçütlere sıfır yazmaz. Çıktı: mutabakat/D1_20260831_MUTABAKAT_DOLU.xlsx

  .venv\\Scripts\\python.exe -m tools.dnm_d1.excel_sablon_doldur
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

from tools.dnm_d1.donem_sabitleri import CALISMA_KOK, DONEM_SONU, TALIMAT_DOSYA

KOK = Path(__file__).resolve().parents[2]
CALISMA = KOK / CALISMA_KOK
KAYNAK = CALISMA / "kaynak"
CIKTI = CALISMA / "mutabakat" / "D1_20260831_MUTABAKAT_DOLU.xlsx"


def _hesaplar(ad: str) -> list[dict]:
    yol = KAYNAK / f"D1_20260831_KAYNAK_{ad}.json"
    if not yol.is_file():
        return []
    return json.loads(yol.read_text(encoding="utf-8")).get("hesaplar") or []


def main() -> int:
    kaynak_xlsx = KOK / TALIMAT_DOSYA
    if not kaynak_xlsx.is_file():
        print("TALIMAT_YOK", flush=True)
        return 2
    CIKTI.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(kaynak_xlsx, CIKTI)
    wb = load_workbook(CIKTI)
    ws = wb["Hesap Bakiyeleri"]

    # Şablon satır 6 başlık; örnek satırlar 7+ — gerçek kimlikleri alta ekle
    baslangic = ws.max_row + 2
    ws.cell(baslangic, 1, "— DOLDURULAN GERÇEK KİMLİKLER —")
    ws.cell(baslangic, 3, f"donem_sonu={DONEM_SONU.isoformat()} doldurma={datetime.now().isoformat(timespec='seconds')}")
    r = baslangic + 1
    for modul, dosya, olcut_alan in (
        ("Kasa", "KASA_KAPANIS", "kapanis_net"),
        ("Banka", "BANKA_KAPANIS", "kapanis_net"),
    ):
        for h in _hesaplar(dosya):
            for olcut, alan in (
                ("Brüt giriş", "brut_giris"),
                ("Brüt çıkış", "brut_cikis"),
                ("Kapanış net (hareket; açılış yok)", olcut_alan),
            ):
                ws.cell(r, 1, modul)
                ws.cell(r, 2, h.get("hesap_id"))
                ws.cell(r, 3, h.get("hesap_adi"))
                ws.cell(r, 5, h.get("para_birimi") or "TL")
                ws.cell(r, 6, olcut)
                ws.cell(r, 7, "Tutar")
                ws.cell(r, 9, h.get(alan))  # Evo kaynak
                ws.cell(r, 10, None)  # Cin hedef — henüz yok; sıfır yazılmaz
                ws.cell(r, 12, "VERİ BEKLENİYOR" if h.get(alan) is None else "KAYNAK_KISMI")
                ws.cell(r, 13, f"D1_20260831_KAYNAK_{dosya}.json")
                ws.cell(r, 16, h.get("uyari") or "")
                ws.cell(r, 17, f"{modul}|{h.get('hesap_id')}|{olcut}")
                r += 1

    # Cari kimlikleri (liste özeti) — kapanış_3108 boş bırakılır
    cari_yol = KAYNAK / "D1_20260831_KAYNAK_CARI_LISTE_OZET.json"
    if cari_yol.is_file():
        cariler = json.loads(cari_yol.read_text(encoding="utf-8")).get("cariler") or []
        for c in cariler:
            ws.cell(r, 1, "Cari")
            ws.cell(r, 2, c.get("kaynak_cari_id"))
            ws.cell(r, 3, c.get("cari_adi"))
            ws.cell(r, 4, c.get("grup_tip"))
            ws.cell(r, 5, c.get("para_birimi") or "TL")
            ws.cell(r, 6, "Güncel liste bakiyesi (31.08 DEĞİL)")
            ws.cell(r, 7, "Tutar")
            ws.cell(r, 9, c.get("guncel_liste_bakiyesi"))
            ws.cell(r, 10, None)
            ws.cell(r, 12, "VERİ BEKLENİYOR")
            ws.cell(r, 13, "D1_20260831_KAYNAK_CARI_LISTE_OZET.json")
            ws.cell(r, 16, c.get("uyari") or "")
            ws.cell(r, 17, f"Cari|{c.get('kaynak_cari_id')}|liste")
            r += 1

    wb.save(CIKTI)
    print("YAZILDI", CIKTI, "satir_son", r - 1, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
