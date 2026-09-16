"""Yazıcı — tarayıcı yazdırma diyaloğu (önizleme zorunlu)."""

from __future__ import annotations

import logging
import webbrowser
from pathlib import Path

from invoice_print.pdf_service import html_dosyasi_yaz
from invoice_print.view_model import InvoicePrintViewModel

_LOG = logging.getLogger("invoice_print.printer")


def print_invoice(vm: InvoicePrintViewModel, *, printer_name: str | None = None) -> Path:
    """Belgeyi tarayıcıda açar; kullanıcı yazıcı seçer. printer_name bilgilendirme amaçlı."""
    try:
        yol = html_dosyasi_yaz(vm)
        webbrowser.open(yol.as_uri())
        return yol
    except Exception as exc:
        _LOG.exception(
            "Yazdırma açılamadı | fatura_id=%s yazici=%s hata=%s",
            vm.fatura_id,
            printer_name,
            exc,
        )
        raise ValueError(
            "Seçilen yazıcıya ulaşılamadı. Lütfen başka bir yazıcı seçin veya PDF olarak kaydedin."
        ) from exc
