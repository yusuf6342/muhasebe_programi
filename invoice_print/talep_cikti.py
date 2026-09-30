"""SATIN ALMA TALEP FORMU A4 çıktıları — PDF (Chromium) ve Word (.docx) aynı görünüm modelinden."""

from __future__ import annotations

import logging
import os
import re
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from database.talep_form_view import TalepFormViewModel, build_talep_form, render_talep_form_html
from invoice_print.irsaliye_cikti import _sayfa_bilgisi_bas

_LOG = logging.getLogger("invoice_print.talep")


def cikti_modeli(talep_id: int, fiyatli: bool = False) -> TalepFormViewModel:
    return build_talep_form(int(talep_id), fiyatli=fiyatli)


def varsayilan_dosya_adi(vm: TalepFormViewModel, uzanti: str) -> str:
    """«Satin_Alma_Talebi_<no>_<YYYY-AA-GG>.<uzantı>» — talep tarihi kullanılır."""
    no = re.sub(r"[^\w\-]+", "_", vm.talep_no or "Yeni").strip("_") or "Yeni"
    try:
        tarih = datetime.strptime(vm.talep_tarihi, "%d.%m.%Y").strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        tarih = datetime.now().strftime("%Y-%m-%d")
    return f"Satin_Alma_Talebi_{no}_{tarih}.{uzanti.lstrip('.')}"


def alt_bilgi_metni(vm: TalepFormViewModel) -> str:
    return f"Talep No: {vm.talep_no}"


def pdf_olustur(vm: TalepFormViewModel, hedef: Path) -> Path:
    from invoice_print.pdf_service import html_metnini_pdfe_cevir

    html_metin = render_talep_form_html(vm)
    hedef = Path(hedef)
    hedef.parent.mkdir(parents=True, exist_ok=True)
    gecici = hedef.with_name(f".{hedef.stem}_{uuid.uuid4().hex[:6]}.pdf")
    try:
        html_metnini_pdfe_cevir(html_metin, gecici, belge_adi="Satın alma talep formu")
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


def docx_olustur(vm: TalepFormViewModel, hedef: Path) -> Path:
    from invoice_print.talep_docx import render_talep_docx

    try:
        return render_talep_docx(vm, Path(hedef))
    except PermissionError as exc:
        raise ValueError(f"Word dosyası kaydedilemedi; dosya başka bir programda açık olabilir:\n{hedef}") from exc


def gecici_pdf(vm: TalepFormViewModel) -> Path:
    klasor = Path(tempfile.gettempdir()) / "muhasebe_talep"
    klasor.mkdir(parents=True, exist_ok=True)
    ad = varsayilan_dosya_adi(vm, "pdf").replace(".pdf", f"_{datetime.now():%H%M%S}_{uuid.uuid4().hex[:4]}.pdf")
    return pdf_olustur(vm, klasor / ad)
