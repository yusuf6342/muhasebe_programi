"""Ortak XLSX yazıcı — rapor ve yeniden-alınabilir çıktılar.

Microsoft Excel'e bağımlı değildir (openpyxl). Geçici dosyaya yazar, sonra hedefe taşır.
"""

from __future__ import annotations

import shutil
import tempfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
SABLON_SURUM = "1.0"
EXCEL_MAX_SATIR = 1_048_575  # başlık hariç güvenli üst sınır
_HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
_HEADER_FONT = Font(color="FFFFFF", bold=True)
_THIN = Border(
    left=Side(style="thin", color="D0D7DE"),
    right=Side(style="thin", color="D0D7DE"),
    top=Side(style="thin", color="D0D7DE"),
    bottom=Side(style="thin", color="D0D7DE"),
)


def _sayi(deger: Any) -> Decimal | None:
    if deger is None or deger == "":
        return None
    if isinstance(deger, Decimal):
        return deger
    if isinstance(deger, (int, float)):
        return Decimal(str(deger))
    metin = str(deger).strip().replace(" ", "")
    if not metin:
        return None
    if "," in metin and "." in metin:
        if metin.rfind(",") > metin.rfind("."):
            metin = metin.replace(".", "").replace(",", ".")
        else:
            metin = metin.replace(",", "")
    elif "," in metin:
        metin = metin.replace(".", "").replace(",", ".")
    try:
        return Decimal(metin)
    except (InvalidOperation, ValueError):
        return None


def _hucre_yaz(ws, row: int, col: int, deger: Any, tip: str) -> None:
    cell = ws.cell(row, col)
    cell.border = _THIN
    if deger is None or deger == "":
        cell.value = None
        return
    tip = (tip or "metin").lower()
    if tip in ("kod", "barkod", "iban", "telefon", "vergi"):
        cell.value = str(deger)
        cell.number_format = "@"
        cell.alignment = Alignment(horizontal="left")
        return
    if tip == "tarih":
        if isinstance(deger, datetime):
            cell.value = deger
            cell.number_format = "DD.MM.YYYY HH:MM"
        elif isinstance(deger, date):
            cell.value = deger
            cell.number_format = "DD.MM.YYYY"
        else:
            cell.value = str(deger)
        return
    if tip in ("sayi", "para", "miktar", "fiyat", "yuzde", "oran", "gun", "gun1"):
        sayi = _sayi(deger)
        if sayi is None:
            cell.value = str(deger)
            return
        cell.value = float(sayi)
        if tip == "yuzde":
            cell.number_format = "0.00"
        elif tip in ("para", "fiyat"):
            cell.number_format = "#,##0.00"
        elif tip == "miktar":
            cell.number_format = "#,##0.####"
        elif tip == "gun1":
            cell.number_format = "0.0"
        else:
            cell.number_format = "#,##0.##"
        cell.alignment = Alignment(horizontal="right")
        return
    cell.value = str(deger)


def _sayfa_yaz(
    wb: Workbook,
    ad: str,
    basliklar: Sequence[str],
    satirlar: Sequence[Sequence[Any] | dict[str, Any]],
    kolon_tipleri: Sequence[str] | None = None,
    *,
    anahtarlar: Sequence[str] | None = None,
) -> None:
    ws = wb.create_sheet(title=(ad or "Veriler")[:31])
    tipler = list(kolon_tipleri or ["metin"] * len(basliklar))
    while len(tipler) < len(basliklar):
        tipler.append("metin")

    for col, baslik in enumerate(basliklar, start=1):
        cell = ws.cell(1, col, baslik)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
        cell.border = _THIN
        ws.column_dimensions[get_column_letter(col)].width = max(12, min(40, len(str(baslik)) + 4))

    for i, satir in enumerate(satirlar, start=2):
        if i - 1 > EXCEL_MAX_SATIR:
            break
        if isinstance(satir, dict):
            keys = anahtarlar or list(basliklar)
            degerler = [satir.get(k) for k in keys]
        else:
            degerler = list(satir)
        for col, deger in enumerate(degerler, start=1):
            if col > len(basliklar):
                break
            _hucre_yaz(ws, i, col, deger, tipler[col - 1])

    son = max(1, min(len(satirlar) + 1, EXCEL_MAX_SATIR + 1))
    ws.auto_filter.ref = f"A1:{get_column_letter(len(basliklar))}{son}"
    ws.freeze_panes = "A2"


def _aktarim_bilgisi_yaz(wb: Workbook, meta: dict[str, Any], amac: str) -> None:
    ws = wb.create_sheet("Aktarım Bilgisi", 0)
    satirlar = [
        ("Şablon Sürümü", meta.get("sablon_surum") or SABLON_SURUM),
        ("Kullanım Amacı", amac),
        ("Şablon Türü", meta.get("sablon_turu") or meta.get("tip") or ""),
        ("Firma", meta.get("firma") or ""),
        ("Dönem", meta.get("donem") or ""),
        ("Şube", meta.get("sube") or ""),
        ("Filtreler", meta.get("filtreler") or meta.get("filtre") or ""),
        ("Hazırlama Zamanı", meta.get("hazirlama_zamani") or datetime.now().strftime("%d.%m.%Y %H:%M:%S")),
        ("Kayıt Sayısı", meta.get("kayit_sayisi") if meta.get("kayit_sayisi") is not None else ""),
        ("Taslak / Kaydedilmemiş", "Evet" if meta.get("taslak") else "Hayır"),
        ("Açıklama", meta.get("aciklama") or ""),
    ]
    ws["A1"] = "Alan"
    ws["B1"] = "Değer"
    ws["A1"].font = Font(bold=True)
    ws["B1"].font = Font(bold=True)
    for i, (k, v) in enumerate(satirlar, start=2):
        ws.cell(i, 1, k)
        ws.cell(i, 2, v)
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 60


def excel_yaz(
    hedef: str | Path,
    *,
    sayfalar: Sequence[tuple[str, Sequence[str], Sequence[Any], Sequence[str] | None]] | None = None,
    basliklar: Sequence[str] | None = None,
    satirlar: Sequence[Any] | None = None,
    kolon_tipleri: Sequence[str] | None = None,
    anahtarlar: Sequence[str] | None = None,
    meta: dict[str, Any] | None = None,
    amac: str = "rapor",
    sayfa_adi: str = "Veriler",
) -> Path:
    """XLSX yaz. ``sayfalar`` = [(ad, basliklar, satirlar, kolon_tipleri), ...].

    Tek sayfa için basliklar+satirlar da kabul edilir.
    """
    path = Path(hedef)
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = dict(meta or {})
    amac = (amac or "rapor").strip().lower()
    if amac not in ("rapor", "yeniden_al"):
        amac = "rapor"

    wb = Workbook()
    # varsayılan boş sayfayı sonra sil
    default = wb.active
    wb.remove(default)

    _aktarim_bilgisi_yaz(wb, meta, amac)

    pages: list[tuple[str, Sequence[str], Sequence[Any], Sequence[str] | None]] = []
    if sayfalar:
        pages.extend(sayfalar)
    elif basliklar is not None:
        pages.append((sayfa_adi, basliklar, list(satirlar or []), kolon_tipleri))

    toplam = 0
    for ad, bas, sat, tip in pages:
        # Excel satır limitini aşarsa parçala
        sat_list = list(sat or [])
        if len(sat_list) <= EXCEL_MAX_SATIR:
            _sayfa_yaz(wb, ad, bas, sat_list, tip, anahtarlar=anahtarlar)
            toplam += len(sat_list)
        else:
            parca = 1
            for baslangic in range(0, len(sat_list), EXCEL_MAX_SATIR):
                dilim = sat_list[baslangic : baslangic + EXCEL_MAX_SATIR]
                _sayfa_yaz(
                    wb,
                    f"{ad[:24]}_{parca}",
                    bas,
                    dilim,
                    tip,
                    anahtarlar=anahtarlar,
                )
                toplam += len(dilim)
                parca += 1

    if meta.get("kayit_sayisi") is None:
        # Aktarım Bilgisi'ni güncelle
        try:
            bilgi = wb["Aktarım Bilgisi"]
            for row in bilgi.iter_rows(min_row=2, max_col=2):
                if row[0].value == "Kayıt Sayısı":
                    row[1].value = toplam
                    break
        except KeyError:
            pass

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        wb.save(tmp_path)
        wb.close()
        shutil.move(str(tmp_path), str(path))
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise
    return path
