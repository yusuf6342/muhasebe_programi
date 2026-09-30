"""SATIŞ SİPARİŞ FORMU A4 çıktıları — PDF (Chromium) ve Word (.docx) aynı görünüm modelinden."""

from __future__ import annotations

import logging
import os
import re
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from database.siparis_form_view import (
    SiparisFormViewModel,
    assert_siparis_form_safe,
    build_siparis_form_from_record,
    render_siparis_form_html,
)
from invoice_print.irsaliye_cikti import _sayfa_bilgisi_bas

_LOG = logging.getLogger("invoice_print.siparis")


def cikti_modeli(siparis_id: int) -> SiparisFormViewModel:
    return build_siparis_form_from_record(int(siparis_id))


def varsayilan_dosya_adi(vm: SiparisFormViewModel, uzanti: str) -> str:
    """«Satis_Siparisi_<no>_<YYYY-AA-GG>.<uzantı>» — sipariş tarihi kullanılır."""
    no = re.sub(r"[^\w\-]+", "_", vm.siparis_no or "Yeni").strip("_") or "Yeni"
    try:
        tarih = datetime.strptime(vm.siparis_tarihi, "%d.%m.%Y").strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        tarih = datetime.now().strftime("%Y-%m-%d")
    return f"Satis_Siparisi_{no}_{tarih}.{uzanti.lstrip('.')}"


def alt_bilgi_metni(vm: SiparisFormViewModel) -> str:
    return f"Sipariş No: {vm.siparis_no}"


def pdf_olustur(vm: SiparisFormViewModel, hedef: Path) -> Path:
    """A4 PDF üretir. Başarısızlıkta ValueError (anlaşılır mesaj)."""
    from invoice_print.pdf_service import html_metnini_pdfe_cevir

    html_metin = render_siparis_form_html(vm)
    assert_siparis_form_safe(vm, html_metin)
    hedef = Path(hedef)
    hedef.parent.mkdir(parents=True, exist_ok=True)
    gecici = hedef.with_name(f".{hedef.stem}_{uuid.uuid4().hex[:6]}.pdf")
    try:
        html_metnini_pdfe_cevir(html_metin, gecici, belge_adi="Sipariş formu")
        try:
            _sayfa_bilgisi_bas(gecici, alt_bilgi_metni(vm))
        except ImportError:
            _LOG.warning("pymupdf yok; sayfa numarası basılamadı: %s", hedef)
        os.replace(gecici, hedef)
    except PermissionError as exc:
        raise ValueError(f"PDF kaydedilemedi; dosya başka bir programda açık olabilir:\n{hedef}") from exc
    finally:
        if gecici.exists():
            try:
                gecici.unlink()
            except OSError:
                pass
    return hedef


def docx_olustur(vm: SiparisFormViewModel, hedef: Path) -> Path:
    from invoice_print.siparis_docx import render_siparis_docx

    hedef = Path(hedef)
    try:
        return render_siparis_docx(vm, hedef)
    except PermissionError as exc:
        raise ValueError(f"Word dosyası kaydedilemedi; dosya başka bir programda açık olabilir:\n{hedef}") from exc


def gecici_pdf(vm: SiparisFormViewModel) -> Path:
    klasor = Path(tempfile.gettempdir()) / "muhasebe_siparis"
    klasor.mkdir(parents=True, exist_ok=True)
    ad = varsayilan_dosya_adi(vm, "pdf").replace(".pdf", f"_{datetime.now():%H%M%S}_{uuid.uuid4().hex[:4]}.pdf")
    return pdf_olustur(vm, klasor / ad)
