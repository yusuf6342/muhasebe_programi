"""Şablon Excel üretimi."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from excel_aktarim.types import ImportTipi, getir
from excel_aktarim.writer import SABLON_SURUM

_HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
_HEADER_FONT = Font(color="FFFFFF", bold=True)
_THIN = Border(
    left=Side(style="thin", color="D0D7DE"),
    right=Side(style="thin", color="D0D7DE"),
    top=Side(style="thin", color="D0D7DE"),
    bottom=Side(style="thin", color="D0D7DE"),
)


class ImportTemplateService:
    @staticmethod
    def olustur(import_tipi: str | ImportTipi, hedef: str | Path) -> Path:
        tip = getir(import_tipi) if isinstance(import_tipi, str) else import_tipi
        path = Path(hedef)
        path.parent.mkdir(parents=True, exist_ok=True)

        wb = Workbook()
        # Aktarım Bilgisi
        bilgi_meta = wb.active
        bilgi_meta.title = "Aktarım Bilgisi"
        bilgi_meta["A1"] = "Alan"
        bilgi_meta["B1"] = "Değer"
        bilgi_meta["A1"].font = Font(bold=True)
        bilgi_meta["B1"].font = Font(bold=True)
        meta_satirlar = [
            ("Şablon Sürümü", SABLON_SURUM),
            ("Şablon Türü", tip.kod),
            ("Şablon Adı", tip.ad),
            ("Modül", tip.modul),
            ("Kullanım", "yeniden_al"),
            ("Açıklama", tip.aciklama or ""),
        ]
        for i, (k, v) in enumerate(meta_satirlar, start=2):
            bilgi_meta.cell(i, 1, k)
            bilgi_meta.cell(i, 2, v)
        bilgi_meta.column_dimensions["A"].width = 22
        bilgi_meta.column_dimensions["B"].width = 56

        # Veriler — yalnız başlık (gerçek veri ile karışmasın)
        ws = wb.create_sheet(tip.sablon_sayfa[:31] or "Veriler")
        for col, alan in enumerate(tip.alanlar, start=1):
            cell = ws.cell(1, col, alan.baslik)
            cell.fill = _HEADER_FILL
            cell.font = _HEADER_FONT
            cell.alignment = Alignment(horizontal="center", wrap_text=True)
            cell.border = _THIN
            ws.column_dimensions[get_column_letter(col)].width = max(14, len(alan.baslik) + 4)
        ws.auto_filter.ref = f"A1:{get_column_letter(max(1, len(tip.alanlar)))}1"
        ws.freeze_panes = "A2"

        # Örnekler — örnek satır ayrı sayfada
        ornekler = wb.create_sheet("Örnekler")
        for col, alan in enumerate(tip.alanlar, start=1):
            cell = ornekler.cell(1, col, alan.baslik)
            cell.fill = _HEADER_FILL
            cell.font = _HEADER_FONT
            cell.border = _THIN
            ornek = alan.ornek or ("" if not alan.zorunlu else "zorunlu")
            ornek_cell = ornekler.cell(2, col, ornek)
            ornek_cell.border = _THIN
            ornek_cell.font = Font(italic=True, color="666666")
            ornekler.column_dimensions[get_column_letter(col)].width = max(14, len(alan.baslik) + 4)

        # Aciklama
        bilgi = wb.create_sheet("Aciklama")
        bilgi["A1"] = tip.ad
        bilgi["A1"].font = Font(bold=True, size=14)
        bilgi["A2"] = tip.aciklama or "Şablonu doldurup sihirbazda seçin."
        bilgi["A3"] = (
            "Veriler sayfasına gerçek kayıtları yazın. Örnekler sayfası yalnızca doldurma örneğidir."
        )
        bilgi["A5"] = "Alan"
        bilgi["B5"] = "Zorunlu"
        bilgi["C5"] = "Açıklama"
        for i, alan in enumerate(tip.alanlar, start=6):
            bilgi.cell(i, 1, alan.baslik)
            bilgi.cell(i, 2, "Evet" if alan.zorunlu else "Hayır")
            bilgi.cell(i, 3, alan.aciklama or "")
        bilgi.column_dimensions["A"].width = 28
        bilgi.column_dimensions["B"].width = 12
        bilgi.column_dimensions["C"].width = 50

        # Veriler sayfasını Aktarım Bilgisi'nden hemen sonra getir
        wb.move_sheet(ws, offset=-len(wb.sheetnames) + 2)
        wb.active = ws

        wb.save(path)
        return path
