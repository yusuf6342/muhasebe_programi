"""UBL-TR e-Fatura / e-Arşiv XML çıkarıcı."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from fatura_belge_aktarim.normalize import birim_normalize, decimal_tr, normalize_vkn, tarih_tr

# Yaygın UBL-TR ad alanları — local-name ile arama daha dayanıklı
_NS_CANDIDATES = (
    "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
)


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _find_text(el: ET.Element | None, *names: str) -> str | None:
    if el is None:
        return None
    hedef = set(names)
    for child in el.iter():
        if _local(child.tag) in hedef and (child.text or "").strip():
            return (child.text or "").strip()
    return None


def _find_child(el: ET.Element | None, name: str) -> ET.Element | None:
    if el is None:
        return None
    for child in el:
        if _local(child.tag) == name:
            return child
    return None


def _find_children(el: ET.Element | None, name: str) -> list[ET.Element]:
    if el is None:
        return []
    return [c for c in el if _local(c.tag) == name]


def _party_info(party_el: ET.Element | None) -> dict[str, Any]:
    if party_el is None:
        return {}
    party_child = _find_child(party_el, "Party")
    party = party_child if party_child is not None else party_el
    vkn = None
    for id_el in party.iter():
        if _local(id_el.tag) == "ID":
            scheme = (id_el.attrib.get("schemeID") or id_el.attrib.get("{*}schemeID") or "").upper()
            val = (id_el.text or "").strip()
            if scheme in {"VKN", "TCKN", "TAX"} or (val.isdigit() and len(val) in (10, 11)):
                vkn = normalize_vkn(val)
                if scheme in {"VKN", "TCKN"}:
                    break
    unvan = _find_text(party, "Name") or _find_text(party, "RegistrationName")
    # PartyName/Name öncelikli
    for pn in party.iter():
        if _local(pn.tag) == "PartyName":
            unvan = _find_text(pn, "Name") or unvan
            break
    vergi_dairesi = None
    for ts in party.iter():
        if _local(ts.tag) == "TaxScheme":
            vergi_dairesi = _find_text(ts, "Name")
            break
    adres = _find_text(party, "StreetName") or _find_text(party, "CitySubdivisionName")
    il = _find_text(party, "CityName")
    tel = _find_text(party, "Telephone")
    email = _find_text(party, "ElectronicMail")
    return {
        "unvan": unvan,
        "vkn": vkn,
        "vergi_dairesi": vergi_dairesi,
        "adres": adres,
        "il": il,
        "telefon": tel,
        "email": email,
        "guven": Decimal("95") if vkn else Decimal("40"),
        "kaynak": "ubl_xml",
    }


@dataclass
class ExtractedInvoice:
    kaynak: str = "ubl_xml"
    belge_no: str | None = None
    ettn: str | None = None
    belge_tarihi: str | None = None
    senaryo: str | None = None
    fatura_tipi: str | None = None
    para_birimi: str | None = None
    kur: Decimal | None = None
    satici: dict[str, Any] = field(default_factory=dict)
    alici: dict[str, Any] = field(default_factory=dict)
    satirlar: list[dict[str, Any]] = field(default_factory=list)
    toplamlar: dict[str, Any] = field(default_factory=dict)
    uyarılar: list[str] = field(default_factory=list)
    guven: Decimal = Decimal("90")
    raw_notes: list[str] = field(default_factory=list)


def extract_ubl_xml(xml_bytes: bytes) -> ExtractedInvoice:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ValueError(f"XML doğrulama hatalı: {exc}") from exc

    if _local(root.tag) not in {"Invoice", "CreditNote", "ApplicationResponse"}:
        # Bazı zarflar Invoice'i içte taşır
        inv = None
        for el in root.iter():
            if _local(el.tag) == "Invoice":
                inv = el
                break
        if inv is None:
            raise ValueError("UBL Invoice kökü bulunamadı. Dosya e-Fatura XML olmalı.")
        root = inv

    out = ExtractedInvoice()
    out.belge_no = _find_text(root, "ID")
    # UUID = ETTN
    for el in root:
        if _local(el.tag) == "UUID":
            out.ettn = (el.text or "").strip()
            break
    issue = _find_text(root, "IssueDate")
    out.belge_tarihi = issue
    out.fatura_tipi = _find_text(root, "InvoiceTypeCode")
    out.para_birimi = _find_text(root, "DocumentCurrencyCode") or "TRY"

    for el in root.iter():
        if _local(el.tag) == "ProfileID":
            out.senaryo = (el.text or "").strip()
            break

    # Kur
    for el in root.iter():
        if _local(el.tag) == "PricingExchangeRate":
            out.kur = decimal_tr(_find_text(el, "CalculationRate"))
            break

    out.satici = _party_info(_find_child(root, "AccountingSupplierParty"))
    out.alici = _party_info(_find_child(root, "AccountingCustomerParty"))

    for i, line in enumerate(_find_children(root, "InvoiceLine"), start=1):
        miktar = decimal_tr(_find_text(line, "InvoicedQuantity"))
        birim_el = None
        for c in line.iter():
            if _local(c.tag) == "InvoicedQuantity":
                birim_el = c
                break
        birim_kod = None
        if birim_el is not None:
            birim_kod = birim_el.attrib.get("unitCode") or birim_el.attrib.get(
                "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}unitCode"
            )
        fiyat = None
        for c in line.iter():
            if _local(c.tag) == "PriceAmount":
                fiyat = decimal_tr(c.text)
                break
        satir_toplam = decimal_tr(_find_text(line, "LineExtensionAmount"))
        kdv = None
        for c in line.iter():
            if _local(c.tag) == "Percent":
                kdv = decimal_tr(c.text)
                break
        aciklama = None
        satici_kod = alici_kod = barkod = None
        for c in line.iter():
            loc = _local(c.tag)
            if loc == "Name" and aciklama is None:
                aciklama = (c.text or "").strip()
            if loc == "SellersItemIdentification":
                satici_kod = _find_text(c, "ID")
            if loc == "BuyersItemIdentification":
                alici_kod = _find_text(c, "ID")
            if loc == "StandardItemIdentification":
                barkod = _find_text(c, "ID")
        out.satirlar.append(
            {
                "sira": i,
                "aciklama": aciklama,
                "satici_urun_kodu": satici_kod,
                "alici_urun_kodu": alici_kod,
                "barkod": barkod,
                "miktar": miktar,
                "birim": birim_normalize(birim_kod),
                "birim_fiyat": fiyat,
                "iskonto_orani": Decimal("0"),
                "kdv_orani": kdv or Decimal("20"),
                "satir_toplam": satir_toplam,
                "guven": Decimal("92"),
                "kaynak": "ubl_xml",
            }
        )

    # Toplamlar
    tax_inclusive = decimal_tr(_find_text(root, "TaxInclusiveAmount"))
    tax_exclusive = decimal_tr(_find_text(root, "TaxExclusiveAmount"))
    payable = decimal_tr(_find_text(root, "PayableAmount"))
    line_ext = decimal_tr(_find_text(root, "LineExtensionAmount"))
    out.toplamlar = {
        "mal_hizmet": line_ext or tax_exclusive,
        "matrah": tax_exclusive,
        "genel_toplam": payable or tax_inclusive,
        "kdv_dahil": tax_inclusive,
        "odenecek": payable or tax_inclusive,
    }
    if not out.belge_no or not out.belge_tarihi:
        out.uyarılar.append("Fatura numarası veya tarihi eksik.")
        out.guven = Decimal("50")
    return out


def extract_from_zip_or_xml(data: bytes, filename: str) -> ExtractedInvoice:
    name = (filename or "").lower()
    if name.endswith(".zip"):
        import io
        import zipfile

        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            xml_names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
            if not xml_names:
                raise ValueError("ZIP içinde XML bulunamadı.")
            # İlk Invoice XML
            for n in xml_names:
                content = zf.read(n)
                try:
                    return extract_ubl_xml(content)
                except ValueError:
                    continue
            raise ValueError("ZIP içindeki XML'ler UBL Invoice olarak okunamadı.")
    return extract_ubl_xml(data)
