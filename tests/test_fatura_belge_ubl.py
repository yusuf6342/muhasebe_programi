"""UBL XML çıkarıcı birim testleri."""

from __future__ import annotations

import unittest
from decimal import Decimal

from fatura_belge_aktarim.normalize import birim_normalize, normalize_vkn, safe_filename
from fatura_belge_aktarim.ubl_extractor import extract_ubl_xml

_SAMPLE_UBL = b"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
 xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
 xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:UBLVersionID>2.1</cbc:UBLVersionID>
  <cbc:ProfileID>TICARIFATURA</cbc:ProfileID>
  <cbc:ID>ABC2026000000123</cbc:ID>
  <cbc:UUID>11111111-2222-3333-4444-555555555555</cbc:UUID>
  <cbc:IssueDate>2026-09-17</cbc:IssueDate>
  <cbc:InvoiceTypeCode>SATIS</cbc:InvoiceTypeCode>
  <cbc:DocumentCurrencyCode>TRY</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PartyIdentification><cbc:ID schemeID="VKN">1234567890</cbc:ID></cac:PartyIdentification>
      <cac:PartyName><cbc:Name>Ornek Tedarikci A.S.</cbc:Name></cac:PartyName>
      <cac:PartyTaxScheme><cac:TaxScheme><cbc:Name>Kadikoy</cbc:Name></cac:TaxScheme></cac:PartyTaxScheme>
    </cac:Party>
  </cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty>
    <cac:Party>
      <cac:PartyIdentification><cbc:ID schemeID="VKN">0987654321</cbc:ID></cac:PartyIdentification>
      <cac:PartyName><cbc:Name>Bizim Firma Ltd.</cbc:Name></cac:PartyName>
    </cac:Party>
  </cac:AccountingCustomerParty>
  <cac:InvoiceLine>
    <cbc:ID>1</cbc:ID>
    <cbc:InvoicedQuantity unitCode="C62">10</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount>1000.00</cbc:LineExtensionAmount>
    <cac:Item>
      <cbc:Name>Test Urun</cbc:Name>
      <cac:SellersItemIdentification><cbc:ID>TED-001</cbc:ID></cac:SellersItemIdentification>
      <cac:StandardItemIdentification><cbc:ID>8690000000001</cbc:ID></cac:StandardItemIdentification>
    </cac:Item>
    <cac:Price><cbc:PriceAmount>100.00</cbc:PriceAmount></cac:Price>
    <cac:TaxTotal>
      <cac:TaxSubtotal><cbc:Percent>20</cbc:Percent></cac:TaxSubtotal>
    </cac:TaxTotal>
  </cac:InvoiceLine>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount>1000.00</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount>1000.00</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount>1200.00</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount>1200.00</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
</Invoice>
"""


class UblExtractorTest(unittest.TestCase):
    def test_extract_fields(self):
        inv = extract_ubl_xml(_SAMPLE_UBL)
        self.assertEqual(inv.belge_no, "ABC2026000000123")
        self.assertEqual(inv.ettn, "11111111-2222-3333-4444-555555555555")
        self.assertEqual(inv.belge_tarihi, "2026-09-17")
        self.assertEqual(inv.satici.get("vkn"), "1234567890")
        self.assertEqual(inv.alici.get("vkn"), "0987654321")
        self.assertEqual(len(inv.satirlar), 1)
        self.assertEqual(inv.satirlar[0]["satici_urun_kodu"], "TED-001")
        self.assertEqual(inv.satirlar[0]["barkod"], "8690000000001")
        self.assertEqual(inv.satirlar[0]["miktar"], Decimal("10"))
        self.assertEqual(inv.toplamlar.get("odenecek"), Decimal("1200.00"))

    def test_normalize(self):
        self.assertEqual(normalize_vkn("123-456-7890"), "1234567890")
        self.assertEqual(birim_normalize("C62"), "ADET")
        self.assertEqual(safe_filename("../../x.pdf"), "x.pdf")


if __name__ == "__main__":
    unittest.main()
