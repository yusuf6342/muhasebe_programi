"""Satış irsaliyesi A4 çıktıları — PDF (Chromium) ve Word (.docx) aynı görünüm modelinden."""

from __future__ import annotations

import logging
import os
import re
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from database.irsaliye_customer_view import (
    CustomerDispatchViewModel,
    assert_customer_dispatch_safe,
    build_customer_dispatch_from_record,
    render_customer_dispatch_html,
)

_LOG = logging.getLogger("invoice_print.irsaliye")

_MM = 72 / 25.4
_ALT_BILGI_Y_MM = 9.0
_KENAR_MM = 12.0
_FONT_ADAYLARI = (
    Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "segoeui.ttf",
    Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "arial.ttf",
)


def cikti_modeli(irsaliye_id: int, *, fiyatli: bool = False) -> CustomerDispatchViewModel:
    return build_customer_dispatch_from_record(int(irsaliye_id), fiyatli=fiyatli)


def varsayilan_dosya_adi(vm: CustomerDispatchViewModel, uzanti: str) -> str:
    """«Satis_Irsaliyesi_<no>_<YYYY-AA-GG>.<uzantı>» — evrak tarihi kullanılır."""
    no = re.sub(r"[^\w\-]+", "_", vm.irsaliye_no or "Yeni").strip("_") or "Yeni"
    try:
        tarih = datetime.strptime(vm.irsaliye_tarihi, "%d.%m.%Y").strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        tarih = datetime.now().strftime("%Y-%m-%d")
    return f"Satis_Irsaliyesi_{no}_{tarih}.{uzanti.lstrip('.')}"


def alt_bilgi_metni(vm: CustomerDispatchViewModel) -> str:
    return f"Evrak No: {vm.irsaliye_no}"


def _sayfa_bilgisi_bas(pdf: Path, sol_metin: str) -> int:
    """Her sayfanın altına «<evrak> … Sayfa X / Y» basar; sayfa sayısını döndürür."""
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz

    # Base14 Helvetica metni birebir kopyalanır/aranır; gömülü TTF'de «-» U+2010'a dönüşür.
    font_yolu = next((p for p in _FONT_ADAYLARI if p.is_file()), None)
    if sol_metin.isascii() or font_yolu is None:
        font = fitz.Font("helv")
    else:
        font = fitz.Font(fontfile=str(font_yolu))
    doc = fitz.open(str(pdf))
    try:
        toplam = doc.page_count
        for no, sayfa in enumerate(doc, start=1):
            en, boy = sayfa.rect.width, sayfa.rect.height
            y = boy - _ALT_BILGI_Y_MM * _MM
            sol_x = _KENAR_MM * _MM
            sag_metin = f"Sayfa {no} / {toplam}"
            boyut = 7.5
            sag_x = en - _KENAR_MM * _MM - font.text_length(sag_metin, fontsize=boyut)
            sayfa.draw_line(
                (sol_x, y - 3.2 * _MM), (en - _KENAR_MM * _MM, y - 3.2 * _MM),
                color=(0.957, 0.773, 0.259), width=0.8,
            )
            yazici = fitz.TextWriter(sayfa.rect)
            yazici.append((sol_x, y), sol_metin, font=font, fontsize=boyut)
            yazici.append((sag_x, y), sag_metin, font=font, fontsize=boyut)
            yazici.write_text(sayfa, color=(0.063, 0.165, 0.263))
        gecici = pdf.with_name(f".{pdf.stem}_{uuid.uuid4().hex[:6]}.pdf")
        doc.save(str(gecici), garbage=3, deflate=True)
    finally:
        doc.close()
    os.replace(gecici, pdf)
    return toplam


def pdf_olustur(vm: CustomerDispatchViewModel, hedef: Path) -> Path:
    """A4 PDF üretir. Başarısızlıkta ValueError (anlaşılır mesaj)."""
    from invoice_print.pdf_service import html_metnini_pdfe_cevir

    html_metin = render_customer_dispatch_html(vm)
    assert_customer_dispatch_safe(vm, html_metin)
    hedef = Path(hedef)
    hedef.parent.mkdir(parents=True, exist_ok=True)
    gecici = hedef.with_name(f".{hedef.stem}_{uuid.uuid4().hex[:6]}.pdf")
    try:
        html_metnini_pdfe_cevir(html_metin, gecici, belge_adi="İrsaliye")
        try:
            _sayfa_bilgisi_bas(gecici, alt_bilgi_metni(vm))
        except ImportError:
            _LOG.warning("pymupdf yok; sayfa numarası basılamadı: %s", hedef)
        os.replace(gecici, hedef)
    except PermissionError as exc:
        raise ValueError(
            f"PDF kaydedilemedi; dosya başka bir programda açık olabilir:\n{hedef}"
        ) from exc
    finally:
        if gecici.exists():
            try:
                gecici.unlink()
            except OSError:
                pass
    return hedef


def docx_olustur(vm: CustomerDispatchViewModel, hedef: Path) -> Path:
    from invoice_print.irsaliye_docx import render_dispatch_docx

    hedef = Path(hedef)
    try:
        return render_dispatch_docx(vm, hedef)
    except PermissionError as exc:
        raise ValueError(
            f"Word dosyası kaydedilemedi; dosya başka bir programda açık olabilir:\n{hedef}"
        ) from exc


def gecici_pdf(vm: CustomerDispatchViewModel) -> Path:
    klasor = Path(tempfile.gettempdir()) / "muhasebe_irsaliye"
    klasor.mkdir(parents=True, exist_ok=True)
    ad = varsayilan_dosya_adi(vm, "pdf").replace(".pdf", f"_{datetime.now():%H%M%S}_{uuid.uuid4().hex[:4]}.pdf")
    return pdf_olustur(vm, klasor / ad)
