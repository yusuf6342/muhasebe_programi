"""Muhasebe JSON codec — Decimal metin olarak, float yok."""

from __future__ import annotations

import json
import unittest
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from fatura_belge_aktarim.json_codec import (
    AccountingJSONEncoder,
    dumps_accounting,
    make_json_safe,
    to_decimal,
)
from fatura_belge_aktarim.ubl_extractor import extract_ubl_xml


class _Durum(Enum):
    BEKLIYOR = "kontrol_bekliyor"


_SAMPLE_UBL = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
 xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
 xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>TST2026000000999</cbc:ID>
  <cbc:UUID>aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee</cbc:UUID>
  <cbc:IssueDate>2026-09-17</cbc:IssueDate>
  <cbc:InvoiceTypeCode>SATIS</cbc:InvoiceTypeCode>
  <cbc:DocumentCurrencyCode>TRY</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PartyIdentification><cbc:ID schemeID="VKN">1111111111</cbc:ID></cac:PartyIdentification>
      <cac:PartyName><cbc:Name>Önder Tedarikçi</cbc:Name></cac:PartyName>
    </cac:Party>
  </cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty>
    <cac:Party>
      <cac:PartyIdentification><cbc:ID schemeID="VKN">2222222222</cbc:ID></cac:PartyIdentification>
      <cac:PartyName><cbc:Name>Alıcı Firma</cbc:Name></cac:PartyName>
    </cac:Party>
  </cac:AccountingCustomerParty>
  <cac:InvoiceLine>
    <cbc:ID>1</cbc:ID>
    <cbc:InvoicedQuantity unitCode="C62">10</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount>12500.00</cbc:LineExtensionAmount>
    <cac:Item><cbc:Name>Ürün A</cbc:Name>
      <cac:SellersItemIdentification><cbc:ID>T-1</cbc:ID></cac:SellersItemIdentification>
    </cac:Item>
    <cac:Price><cbc:PriceAmount>1250.00</cbc:PriceAmount></cac:Price>
    <cac:TaxTotal><cac:TaxSubtotal><cbc:Percent>20</cbc:Percent></cac:TaxSubtotal></cac:TaxTotal>
  </cac:InvoiceLine>
  <cac:InvoiceLine>
    <cbc:ID>2</cbc:ID>
    <cbc:InvoicedQuantity unitCode="C62">2</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount>2500.10</cbc:LineExtensionAmount>
    <cac:Item><cbc:Name>Ürün B</cbc:Name></cac:Item>
    <cac:Price><cbc:PriceAmount>1250.05</cbc:PriceAmount></cac:Price>
    <cac:TaxTotal><cac:TaxSubtotal><cbc:Percent>20</cbc:Percent></cac:TaxSubtotal></cac:TaxTotal>
  </cac:InvoiceLine>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount>15000.10</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount>15000.10</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount>18000.12</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount>18000.12</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
</Invoice>
""".encode("utf-8")


class JsonCodecTest(unittest.TestCase):
    def test_baslik_decimal(self):
        data = {
            "currency": "TRY",
            "payable_total": Decimal("15000.00"),
            "tax_total": Decimal("2500.00"),
        }
        text = dumps_accounting(data)
        parsed = json.loads(text)
        self.assertEqual(parsed["payable_total"], "15000.00")
        self.assertEqual(to_decimal(parsed["payable_total"]), Decimal("15000.00"))

    def test_satir_miktar_fiyat(self):
        line = {"quantity": Decimal("10.000"), "unit_price": Decimal("1250.00"), "tax_rate": Decimal("20.00")}
        parsed = json.loads(dumps_accounting(line))
        self.assertEqual(parsed["quantity"], "10.000")
        self.assertEqual(parsed["unit_price"], "1250.00")
        self.assertEqual(to_decimal(parsed["unit_price"]), Decimal("1250.00"))

    def test_ic_ice_yapilar(self):
        data = {
            "header": {"total": Decimal("100.50")},
            "lines": [{"qty": Decimal("1.5"), "nested": {"p": Decimal("2.25")}}],
        }
        safe = make_json_safe(data)
        self.assertEqual(safe["header"]["total"], "100.50")
        self.assertEqual(safe["lines"][0]["nested"]["p"], "2.25")

    def test_tarih_uuid_enum(self):
        uid = UUID("11111111-2222-3333-4444-555555555555")
        data = {
            "d": date(2026, 9, 17),
            "dt": datetime(2026, 9, 17, 14, 30, 0),
            "u": uid,
            "e": _Durum.BEKLIYOR,
        }
        parsed = json.loads(dumps_accounting(data))
        self.assertEqual(parsed["d"], "2026-09-17")
        self.assertTrue(parsed["dt"].startswith("2026-09-17T14:30:00"))
        self.assertEqual(parsed["u"], str(uid))
        self.assertEqual(parsed["e"], "kontrol_bekliyor")

    def test_turkce_karakter(self):
        text = dumps_accounting({"unvan": "Öğrenci Şirketi — İğdır"})
        self.assertIn("Öğrenci", text)
        self.assertIn("İğdır", text)

    def test_yuvarlama_korunur(self):
        text = dumps_accounting({"v": Decimal("15000.10")})
        parsed = json.loads(text)
        self.assertEqual(parsed["v"], "15000.10")
        self.assertNotEqual(parsed["v"], "15000.1")
        self.assertEqual(to_decimal(parsed["v"]), Decimal("15000.10"))

    def test_encoder_cls(self):
        text = json.dumps({"x": Decimal("1.00")}, cls=AccountingJSONEncoder, ensure_ascii=False)
        self.assertEqual(json.loads(text)["x"], "1.00")

    def test_float_kullanilmaz(self):
        raw = dumps_accounting({"a": Decimal("10.10"), "b": Decimal("20.00")})
        # JSON içinde sayısal float yok; tırnaklı metin var
        self.assertIn('"10.10"', raw)
        self.assertNotRegex(raw, r'"a":\s*10\.1[^0]')

    def test_ubl_payload_serialize(self):
        inv = extract_ubl_xml(_SAMPLE_UBL)
        payload = {
            "satici": inv.satici,
            "alici": inv.alici,
            "toplamlar": inv.toplamlar,
            "satirlar": inv.satirlar,
            "guven": inv.guven,
        }
        # Eski hata: guven Decimal satici içinde — artık dumps_accounting ile geçer
        text = dumps_accounting(payload)
        parsed = json.loads(text)
        self.assertEqual(len(parsed["satirlar"]), 2)
        self.assertEqual(to_decimal(parsed["toplamlar"]["odenecek"]), Decimal("18000.12"))
        self.assertEqual(to_decimal(parsed["satirlar"][0]["birim_fiyat"]), Decimal("1250.00"))
        self.assertIn("Önder", parsed["satici"].get("unvan") or "")

    def test_kdv_toplam_korunur(self):
        inv = extract_ubl_xml(_SAMPLE_UBL)
        once = inv.toplamlar.get("odenecek")
        text = dumps_accounting({"toplamlar": inv.toplamlar, "satirlar": inv.satirlar})
        parsed = json.loads(text)
        self.assertEqual(to_decimal(parsed["toplamlar"]["odenecek"]), once)
        satir_toplam = sum(
            (to_decimal(s["miktar"]) * to_decimal(s["birim_fiyat"]) for s in parsed["satirlar"]),
            Decimal("0"),
        )
        self.assertEqual(satir_toplam, Decimal("15000.10"))

    def test_eslestirme_ve_denetim_json(self):
        # Cari/stok eşleştirme ve denetim before/after JSON
        eslesme = {
            "modu": "bulunamadi",
            "guven": Decimal("0"),
            "birim_carpan": Decimal("1.000"),
            "adaylar": [{"guven": Decimal("55.50")}],
        }
        onceki = {"genel_toplam": Decimal("15000.10"), "durum": "kontrol_bekliyor"}
        sonraki = {"fatura_id": 42, "tur": "ALIS", "kur": Decimal("1.0000")}
        text = dumps_accounting(
            {"eslesme": eslesme, "onceki_json": onceki, "sonraki_json": sonraki}
        )
        parsed = json.loads(text)
        self.assertEqual(parsed["eslesme"]["guven"], "0")
        self.assertEqual(parsed["eslesme"]["birim_carpan"], "1.000")
        self.assertEqual(to_decimal(parsed["onceki_json"]["genel_toplam"]), Decimal("15000.10"))
        self.assertEqual(parsed["sonraki_json"]["kur"], "1.0000")


if __name__ == "__main__":
    unittest.main()
