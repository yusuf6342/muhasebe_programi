"""PDF fatura okuma — gömülü XML → tablo → koordinat → metin → OCR yedek."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from fatura_belge_aktarim.normalize import parse_decimal_tr
from fatura_belge_aktarim.pdf_embedded_xml import try_extract_ubl_from_pdf
from fatura_belge_aktarim.pdf_lines import (
    extract_tables_pdfplumber,
    text_heuristic_lines,
    words_to_lines_by_coordinates,
)
from fatura_belge_aktarim.ubl_extractor import ExtractedInvoice

_LOG = logging.getLogger("fatura_belge_aktarim.pdf_extractor")

SATIR_BULUNAMADI_MESAJI = (
    "Fatura başlık bilgileri okundu ancak ürün veya hizmet satırları\n"
    "belirlenemedi. Belgeyi farklı OCR ayarıyla yeniden deneyebilir,\n"
    "XML dosyası seçebilir veya satırları manuel ekleyebilirsiniz."
)


@dataclass
class PdfExtractResult:
    metin: str = ""
    sayfa_sayisi: int = 0
    guven: Decimal = Decimal("0")
    uyarilar: list[str] = field(default_factory=list)
    diag: dict[str, Any] = field(default_factory=dict)


def extract_pdf_text(yol: Path | bytes) -> PdfExtractResult:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError("PDF metin okuma için pypdf gerekli.") from exc

    if isinstance(yol, (bytes, bytearray)):
        import io

        reader = PdfReader(io.BytesIO(yol))
    else:
        reader = PdfReader(str(yol))

    if getattr(reader, "is_encrypted", False):
        try:
            reader.decrypt("")
        except Exception as exc:  # noqa: BLE001
            raise ValueError("Parola korumalı PDF açılamadı.") from exc

    sayfalar = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            txt = page.extract_text() or ""
        except Exception:
            txt = ""
        sayfalar.append(txt)
        _LOG.info("PDF sayfa=%s ham_metin_uzunluk=%s", i, len(txt))
        if txt:
            _LOG.debug("PDF sayfa=%s ham_metin:\n%s", i, txt[:4000])
    metin = "\n".join(sayfalar).strip()
    sonuc = PdfExtractResult(metin=metin, sayfa_sayisi=len(reader.pages))
    if not metin:
        sonuc.guven = Decimal("10")
        sonuc.uyarilar.append(
            "PDF'de metin katmanı yok (taranmış belge). OCR yedek yöntemi denenecek."
        )
    else:
        sonuc.guven = Decimal("55")
    return sonuc


def _header_from_text(metin: str, out: ExtractedInvoice) -> None:
    m = re.search(
        r"(?:Fatura\s*(?:No|Numarası|Numarasi)|Invoice\s*No|FATURA\s*NO|Belge\s*No)[:\s]*([A-Z0-9\-/]+)",
        metin,
        re.I,
    )
    if m and not out.belge_no:
        out.belge_no = m.group(1).strip()
    m = re.search(r"(\d{2}[./-]\d{2}[./-]\d{4})", metin)
    if m and not out.belge_tarihi:
        out.belge_tarihi = m.group(1).replace("/", ".").replace("-", ".")
    # Satıcı VKN öncelikli (etiketli)
    m = re.search(r"\bVKN\s*[:\s]*(\d{10,11})", metin, re.I)
    if m:
        out.satici = {
            **(out.satici or {}),
            "vkn": m.group(1),
            "guven": Decimal("70"),
            "kaynak": "pdf_text",
        }
    elif not (out.satici or {}).get("vkn"):
        m = re.search(r"(?:Vergi\s*(?:No|Kimlik)|TCKN)[:\s]*(\d{10,11})", metin, re.I)
        if m:
            out.satici = {
                "vkn": m.group(1),
                "unvan": (out.satici or {}).get("unvan"),
                "guven": Decimal("50"),
                "kaynak": "pdf_text",
            }
    # ETTN
    m = re.search(r"ETTN\s*[:\s]*([0-9A-Fa-f\-]{30,})", metin, re.I)
    if m and not out.ettn:
        out.ettn = m.group(1).strip()
    # Ünvan satırı (Satıcı / Seller)
    m = re.search(
        r"(?:Satıcı|Satici|Seller|Tedarikçi|Tedarikci)\s*[:\-]?\s*(.+)",
        metin,
        re.I,
    )
    if m and not (out.satici or {}).get("unvan"):
        unvan = m.group(1).strip().split("\n")[0][:200]
        satici = dict(out.satici or {})
        satici["unvan"] = unvan
        out.satici = satici
    m = re.search(
        r"(?:Genel\s*Toplam|Ödenecek\s*Tutar|Odenecek\s*Tutar|Payable|Vergiler\s*Dahil\s*Toplam)[:\s]*([\d.,]+)",
        metin,
        re.I,
    )
    if m:
        tutar = parse_decimal_tr(m.group(1))
        if tutar is not None:
            out.toplamlar = {**(out.toplamlar or {}), "genel_toplam": tutar, "odenecek": tutar}


def pdf_text_to_draft_fields(metin: str) -> ExtractedInvoice:
    """Geriye uyumluluk — yalnız başlık; satırlar pipeline'da doldurulur."""
    out = ExtractedInvoice(kaynak="pdf_text", guven=Decimal("45"))
    out.uyarılar.append("PDF metin katmanından kısmi okuma; alanları kontrol edin.")
    _header_from_text(metin, out)
    return out


def _try_ocr_fallback(pdf_bytes: bytes, header: ExtractedInvoice) -> list[dict[str, Any]]:
    """Tesseract OCR yedek — PyMuPDF 300 DPI + ön işleme + çoklu PSM."""
    from fatura_belge_aktarim.ocr_engine import extract_with_ocr

    _LOG.info("OCR yedek yöntemi deneniyor (satır sayısı 0)")
    try:
        inv, diag = extract_with_ocr(pdf_bytes, is_pdf=True, header=header)
        # başlık alanlarını geri yaz
        if inv.belge_no:
            header.belge_no = inv.belge_no
        if inv.belge_tarihi:
            header.belge_tarihi = inv.belge_tarihi
        if inv.ettn:
            header.ettn = inv.ettn
        if inv.satici:
            header.satici = {**(header.satici or {}), **inv.satici}
        if inv.toplamlar:
            header.toplamlar = {**(header.toplamlar or {}), **inv.toplamlar}
        header.uyarılar.extend([u for u in inv.uyarılar if u not in header.uyarılar])
        _LOG.info(
            "OCR diag path=%s ver=%s lines=%s psm=%s",
            diag.get("tesseract_path"),
            diag.get("tesseract_version"),
            diag.get("line_count"),
            diag.get("best_psms"),
        )
        return list(inv.satirlar or [])
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001
        _LOG.exception("OCR fallback hata: %s", exc)
        header.uyarılar.append(
            "OCR işlemi tamamlanamadı. Servis ekranından Tesseract ayarını kontrol edin."
        )
        return []


def extract_pdf_invoice(
    data: bytes,
    *,
    force_method: str | None = None,
) -> tuple[ExtractedInvoice, str, dict[str, Any]]:
    """
    Kademeli PDF okuma.
    force_method: ubl_xml | pdf_table | pdf_coordinates | ocr | None (otomatik)
    Dönüş: (invoice, kaynak_turu, diag)
    """
    diag: dict[str, Any] = {"methods_tried": [], "ocr_used": False}

    # 1) Gömülü UBL
    if force_method in (None, "ubl_xml"):
        diag["methods_tried"].append("ubl_xml")
        embedded = try_extract_ubl_from_pdf(data)
        if embedded and embedded.satirlar:
            diag["winning_method"] = "ubl_xml"
            diag["line_count"] = len(embedded.satirlar)
            _LOG.info("Kazanan yöntem=ubl_xml satir=%s", len(embedded.satirlar))
            return embedded, "ubl_xml", diag
        if force_method == "ubl_xml":
            out = ExtractedInvoice(kaynak="ubl_xml", guven=Decimal("20"))
            out.uyarılar.append("PDF içinde UBL-TR XML bulunamadı.")
            return out, "ubl_xml", diag

    # Metin katmanı + başlık
    pdf = extract_pdf_text(data)
    diag["page_count"] = pdf.sayfa_sayisi
    diag["text_len"] = len(pdf.metin or "")
    out = ExtractedInvoice(kaynak="pdf_text", guven=Decimal("45"))
    if pdf.metin:
        out.uyarılar.append("PDF metin katmanından kısmi okuma; alanları kontrol edin.")
        _header_from_text(pdf.metin, out)
    out.uyarılar.extend(pdf.uyarilar)

    def _accept(
        lines: list[dict[str, Any]], method: str, kaynak: str, guven: Decimal
    ) -> tuple[ExtractedInvoice, str, dict[str, Any]] | None:
        if not lines:
            return None
        out.satirlar = lines
        out.kaynak = method
        out.guven = guven
        diag["winning_method"] = method
        diag["line_count"] = len(lines)
        _LOG.info("Kazanan yöntem=%s satir=%s", method, len(lines))
        return out, kaynak, diag

    # force OCR: diğer adımları atla
    if force_method == "ocr":
        diag["methods_tried"].append("ocr")
        diag["ocr_used"] = True
        lines = _try_ocr_fallback(data, out)
        hit = _accept(lines, "tesseract_ocr", "pdf_ocr", Decimal("50"))
        if hit:
            return hit
        out.uyarılar.append(SATIR_BULUNAMADI_MESAJI)
        return out, "pdf_ocr", diag

    # 2) Tablo
    if force_method in (None, "pdf_table"):
        diag["methods_tried"].append("pdf_table")
        lines, tdiag = extract_tables_pdfplumber(data)
        diag["table"] = tdiag
        hit = _accept(lines, "pdf_table", "pdf_table", Decimal("72"))
        if hit:
            return hit
        if force_method == "pdf_table":
            out.uyarılar.append("PDF tablosundan satır çıkarılamadı.")
            out.uyarılar.append(SATIR_BULUNAMADI_MESAJI)
            return out, "pdf_table", diag

    # 3) Koordinat
    if force_method in (None, "pdf_coordinates"):
        diag["methods_tried"].append("pdf_coordinates")
        lines, cdiag = words_to_lines_by_coordinates(data)
        diag["coordinates"] = cdiag
        hit = _accept(lines, "pdf_coordinates", "pdf_coordinates", Decimal("62"))
        if hit:
            return hit
        if force_method == "pdf_coordinates":
            out.uyarılar.append("Koordinat tabanlı satır okuma başarısız.")
            out.uyarılar.append(SATIR_BULUNAMADI_MESAJI)
            return out, "pdf_coordinates", diag

    # Metin sezgisel
    if force_method is None and pdf.metin:
        diag["methods_tried"].append("pdf_text_heuristic")
        lines = text_heuristic_lines(pdf.metin)
        hit = _accept(lines, "pdf_text_heuristic", "pdf_text", Decimal("48"))
        if hit:
            return hit

    # 4) OCR — metin yoksa veya satır yoksa
    need_ocr = force_method is None and (not pdf.metin or not out.satirlar)
    if need_ocr:
        diag["methods_tried"].append("ocr")
        diag["ocr_used"] = True
        lines = _try_ocr_fallback(data, out)
        hit = _accept(lines, "tesseract_ocr", "pdf_ocr", Decimal("50"))
        if hit:
            return hit

    if not out.satirlar:
        out.uyarılar.append(SATIR_BULUNAMADI_MESAJI)
        _LOG.warning(
            "Satır çıkarılamadı page_count=%s text_len=%s methods=%s",
            diag.get("page_count"),
            diag.get("text_len"),
            diag.get("methods_tried"),
        )
    diag["line_count"] = 0
    diag["winning_method"] = None
    return out, ("pdf_scan" if not pdf.metin else "pdf_text"), diag


def extract_image_invoice(data: bytes, *, yol: Path | None = None) -> tuple[ExtractedInvoice, str, dict]:
    """JPG/PNG/WebP — doğrudan Tesseract OCR."""
    from fatura_belge_aktarim.ocr_engine import extract_with_ocr

    try:
        inv, diag = extract_with_ocr(
            data, is_pdf=False, dosya_adi=str(yol.name if yol else "image")
        )
        kaynak = "image_ocr" if inv.satirlar else "image"
        return inv, kaynak, diag
    except ValueError as exc:
        stub = ExtractedInvoice(kaynak="image_ocr", guven=Decimal("5"))
        stub.uyarılar.append(str(exc))
        stub.uyarılar.append(SATIR_BULUNAMADI_MESAJI)
        return stub, "image", {"error": "ocr_failed", "ocr_used": True}


def image_ocr_stub(_yol: Path) -> ExtractedInvoice:
    """Geriye uyumluluk — mümkünse gerçek OCR dene."""
    try:
        data = _yol.read_bytes() if _yol.is_file() else b""
        if data:
            inv, _kaynak, _diag = extract_image_invoice(data, yol=_yol)
            return inv
    except Exception:  # noqa: BLE001
        pass
    out = ExtractedInvoice(kaynak="image_ocr", guven=Decimal("5"))
    out.uyarılar.append(
        "Görsel OCR çalıştırılamadı. Tesseract yolunu Servis ekranından kontrol edin "
        "veya UBL XML yükleyin / manuel satır ekleyin."
    )
    out.uyarılar.append(SATIR_BULUNAMADI_MESAJI)
    return out
