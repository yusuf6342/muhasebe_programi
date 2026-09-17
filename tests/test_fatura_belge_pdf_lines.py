"""PDF satır çıkarma — tablo/koordinat/metin/UBL gömülü testleri."""

from __future__ import annotations

import io
import unittest
from decimal import Decimal

from fatura_belge_aktarim.json_codec import dumps_accounting, to_decimal
from fatura_belge_aktarim.normalize import normalize_header, parse_decimal_tr
from fatura_belge_aktarim.pdf_lines import (
    build_column_map,
    finalize_line,
    line_acceptable,
    tables_to_lines,
    text_heuristic_lines,
)
from fatura_belge_aktarim.pdf_extractor import extract_pdf_invoice
from fatura_belge_aktarim.ubl_extractor import extract_ubl_xml


_SAMPLE_UBL = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
 xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
 xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>PDF-EMB-001</cbc:ID>
  <cbc:UUID>bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb</cbc:UUID>
  <cbc:IssueDate>2026-09-17</cbc:IssueDate>
  <cbc:DocumentCurrencyCode>TRY</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PartyIdentification><cbc:ID schemeID="VKN">3333333333</cbc:ID></cac:PartyIdentification>
      <cac:PartyName><cbc:Name>Gömülü Satıcı</cbc:Name></cac:PartyName>
    </cac:Party>
  </cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty>
    <cac:Party>
      <cac:PartyIdentification><cbc:ID schemeID="VKN">4444444444</cbc:ID></cac:PartyIdentification>
      <cac:PartyName><cbc:Name>Alıcı</cbc:Name></cac:PartyName>
    </cac:Party>
  </cac:AccountingCustomerParty>
  <cac:InvoiceLine>
    <cbc:ID>1</cbc:ID>
    <cbc:InvoicedQuantity unitCode="C62">3</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount>300.00</cbc:LineExtensionAmount>
    <cac:Item><cbc:Name>Kalem X</cbc:Name></cac:Item>
    <cac:Price><cbc:PriceAmount>100.00</cbc:PriceAmount></cac:Price>
    <cac:TaxTotal><cac:TaxSubtotal><cbc:Percent>20</cbc:Percent></cac:TaxSubtotal></cac:TaxTotal>
  </cac:InvoiceLine>
  <cac:InvoiceLine>
    <cbc:ID>2</cbc:ID>
    <cbc:InvoicedQuantity unitCode="C62">1</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount>50.00</cbc:LineExtensionAmount>
    <cac:Item><cbc:Name>Kalem Y</cbc:Name></cac:Item>
    <cac:Price><cbc:PriceAmount>50.00</cbc:PriceAmount></cac:Price>
    <cac:TaxTotal><cac:TaxSubtotal><cbc:Percent>10</cbc:Percent></cac:TaxSubtotal></cac:TaxTotal>
  </cac:InvoiceLine>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount>350.00</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount>350.00</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount>410.00</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount>410.00</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
</Invoice>
""".encode("utf-8")


class ParseDecimalTrTest(unittest.TestCase):
    def test_turkce_bicimler(self):
        self.assertEqual(parse_decimal_tr("1.250,00"), Decimal("1250.00"))
        self.assertEqual(parse_decimal_tr("1250,00"), Decimal("1250.00"))
        self.assertEqual(parse_decimal_tr("1,250.00"), Decimal("1250.00"))
        self.assertEqual(parse_decimal_tr("1250.00"), Decimal("1250.00"))
        self.assertEqual(parse_decimal_tr("%20"), Decimal("20"))
        self.assertEqual(parse_decimal_tr("20,00"), Decimal("20.00"))
        self.assertEqual(parse_decimal_tr("1.250,00 TL"), Decimal("1250.00"))


class HeaderNormalizeTest(unittest.TestCase):
    def test_es_anlam(self):
        self.assertEqual(build_column_map(["Mal/Hizmet", "Miktar", "Birim Fiyat", "Tutar"])[0], "aciklama")
        self.assertIn(1, build_column_map(["Açıklama", "Adet", "Fiyat", "KDV %"]))
        m = build_column_map(["Ürün Kodu", "Ürün Açıklaması", "Qty", "Unit Price", "Net Tutar"])
        self.assertEqual(m[0], "urun_kodu")
        self.assertEqual(m[1], "aciklama")


class TableLinesTest(unittest.TestCase):
    def test_tek_satirli_tablo(self):
        table = [
            ["Mal/Hizmet", "Miktar", "Birim", "Birim Fiyat", "KDV", "Tutar"],
            ["Kalem A", "10", "Adet", "1.250,00", "20", "12.500,00"],
        ]
        lines = tables_to_lines([table], method="pdf_table", page=1, guven=Decimal("70"))
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["aciklama"], "Kalem A")
        self.assertEqual(lines[0]["miktar"], Decimal("10"))
        self.assertEqual(lines[0]["birim_fiyat"], Decimal("1250.00"))

    def test_cok_satirli_tablo(self):
        table = [
            ["Açıklama", "Miktar", "Birim Fiyat", "Satır Toplamı"],
            ["Ürün 1", "2", "100,00", "200,00"],
            ["Ürün 2", "3", "50,00", "150,00"],
            ["Genel Toplam", "", "", "350,00"],
        ]
        lines = tables_to_lines([table], method="pdf_table", page=1, guven=Decimal("70"))
        self.assertEqual(len(lines), 2)

    def test_cizgisiz_baslik_esnek(self):
        table = [
            ["Malzeme", "Adet", "Fiyat", "Mal/Hizmet Tutarı"],
            ["Vida M6", "100", "0,50", "50,00"],
        ]
        lines = tables_to_lines([table], method="pdf_table:text", page=1, guven=Decimal("70"))
        self.assertEqual(len(lines), 1)

    def test_kod_yok_aciklama_var(self):
        data = {
            "aciklama": "Hizmet bedeli",
            "miktar": Decimal("1"),
            "birim_fiyat": Decimal("500"),
        }
        ok, _ = line_acceptable(data)
        self.assertTrue(ok)

    def test_iskontolu(self):
        data = {
            "aciklama": "İskontolu ürün",
            "miktar": Decimal("2"),
            "birim_fiyat": Decimal("100"),
            "iskonto_orani": Decimal("10"),
            "satir_toplam": Decimal("180"),
        }
        line = finalize_line(data, sira=1, method="pdf_table", page=1, guven=Decimal("70"))
        self.assertEqual(line["iskonto_orani"], Decimal("10"))

    def test_coklu_kdv(self):
        table = [
            ["Açıklama", "Miktar", "Birim Fiyat", "KDV", "Tutar"],
            ["A", "1", "100,00", "20", "100,00"],
            ["B", "1", "100,00", "10", "100,00"],
        ]
        lines = tables_to_lines([table], method="pdf_table", page=1, guven=Decimal("70"))
        self.assertEqual(lines[0]["kdv_orani"], Decimal("20"))
        self.assertEqual(lines[1]["kdv_orani"], Decimal("10"))

    def test_fiyat_hesaplandi(self):
        data = {"aciklama": "X", "miktar": Decimal("4"), "satir_toplam": Decimal("200")}
        line = finalize_line(data, sira=1, method="pdf_table", page=1, guven=Decimal("70"))
        self.assertTrue(line["hesaplandi"])
        self.assertEqual(line["birim_fiyat"], Decimal("50.000000"))

    def test_json_decimal(self):
        table = [
            ["Açıklama", "Miktar", "Birim Fiyat", "Tutar"],
            ["Z", "1", "15000.10", "15000.10"],
        ]
        lines = tables_to_lines([table], method="pdf_table", page=1, guven=Decimal("70"))
        text = dumps_accounting(lines)
        self.assertIn("15000.10", text)
        self.assertEqual(to_decimal(__import__("json").loads(text)[0]["birim_fiyat"]), Decimal("15000.10"))


class TextHeuristicTest(unittest.TestCase):
    def test_metin_satirlari(self):
        metin = """
Fatura No: ABC-1
Mal/Hizmet Bilgileri
Kalem Alfa 10 Adet 1.250,00 20 12.500,00
Kalem Beta 2 Adet 500,00 20 1.000,00
Genel Toplam 13.500,00
"""
        lines = text_heuristic_lines(metin)
        self.assertGreaterEqual(len(lines), 2)
        self.assertIn("Alfa", lines[0]["aciklama"])


class EmbeddedUblPdfTest(unittest.TestCase):
    def test_gomulu_xml_pdf(self):
        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.add_attachment("fatura.xml", _SAMPLE_UBL)
        buf = io.BytesIO()
        writer.write(buf)
        pdf_bytes = buf.getvalue()
        inv, kaynak, diag = extract_pdf_invoice(pdf_bytes)
        self.assertEqual(kaynak, "ubl_xml")
        self.assertEqual(len(inv.satirlar), 2)
        self.assertEqual(diag.get("winning_method"), "ubl_xml")
        self.assertEqual(inv.belge_no, "PDF-EMB-001")

    def test_namespace_invoice_line(self):
        inv = extract_ubl_xml(_SAMPLE_UBL)
        self.assertEqual(len(inv.satirlar), 2)
        self.assertEqual(inv.satirlar[0]["aciklama"], "Kalem X")


class MutabakatTest(unittest.TestCase):
    def test_satir_toplam_mutabakati(self):
        table = [
            ["Açıklama", "Miktar", "Birim Fiyat", "Tutar"],
            ["A", "2", "100,00", "200,00"],
            ["B", "1", "50,00", "50,00"],
        ]
        lines = tables_to_lines([table], method="pdf_table", page=1, guven=Decimal("70"))
        brut = sum((ln["miktar"] * ln["birim_fiyat"] for ln in lines), Decimal("0"))
        self.assertEqual(brut, Decimal("250.00"))


class HeaderOnlyNotSuccessTest(unittest.TestCase):
    def test_bos_satir_baslik_var(self):
        # Metin başlığı var ama tablo yok → satır 0 olmalı (OCR yoksa)
        from fatura_belge_aktarim.pdf_extractor import pdf_text_to_draft_fields

        out = pdf_text_to_draft_fields("Fatura No: X1\nVKN: 1234567890\nGenel Toplam: 100,00")
        self.assertEqual(out.belge_no, "X1")
        self.assertEqual(len(out.satirlar), 0)


class RealTesayPdfTest(unittest.TestCase):
    def test_tesay_fatura_satirlari(self):
        from pathlib import Path

        candidates = list(
            Path(r"C:\Users\cigde\AppData\Local\MuhasebeProgrami\data\invoice_imports").glob(
                "*tesay fatura.pdf"
            )
        )
        if not candidates:
            self.skipTest("Tesay örnek PDF yok")
        inv, kaynak, diag = extract_pdf_invoice(candidates[0].read_bytes())
        self.assertGreaterEqual(len(inv.satirlar), 1)
        self.assertEqual(diag.get("winning_method"), "pdf_table")
        self.assertEqual(inv.belge_no, "TSY2026000009245")
        line = inv.satirlar[0]
        self.assertEqual(line["miktar"], Decimal("120"))
        self.assertEqual(line["birim_fiyat"], Decimal("110"))
        self.assertEqual(line["satir_toplam"], Decimal("13200.00"))
        # iskontolu ödenecek ≈ 7920
        net = line["miktar"] * line["birim_fiyat"] * (
            Decimal("1") - (line.get("iskonto_orani") or 0) / Decimal("100")
        )
        odenecek = net * (Decimal("1") + (line.get("kdv_orani") or 0) / Decimal("100"))
        self.assertEqual(odenecek.quantize(Decimal("0.01")), Decimal("7920.00"))


if __name__ == "__main__":
    unittest.main()
