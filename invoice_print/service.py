"""InvoicePrintService — fatura A4 önizleme / PDF / yazdır facade."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from invoice_print.builder import build_from_kart, build_invoice_print_model
from invoice_print.pdf_service import html_dosyasi_yaz, render_invoice_to_pdf, safe_pdf_filename
from invoice_print.printer_service import print_invoice
from invoice_print.settings import load_print_settings
from invoice_print.view_model import InvoicePrintViewModel

_LOG = logging.getLogger("invoice_print")


class InvoicePrintService:
    @staticmethod
    def build_invoice_print_model(
        invoice_id: int, template_id: str | None = None
    ) -> InvoicePrintViewModel:
        return build_invoice_print_model(invoice_id, template_id=template_id)

    @staticmethod
    def build_from_kart(kart, template_id: str | None = None) -> InvoicePrintViewModel:
        return build_from_kart(kart, template_id=template_id)

    @staticmethod
    def preview_invoice(
        invoice_id: int | None = None,
        template_id: str | None = None,
        *,
        kart=None,
    ) -> InvoicePrintViewModel:
        if kart is not None:
            return build_from_kart(kart, template_id=template_id)
        if invoice_id is None:
            raise ValueError("Fatura bulunamadı.")
        return build_invoice_print_model(int(invoice_id), template_id=template_id)

    @staticmethod
    def render_html(vm: InvoicePrintViewModel, **kwargs) -> str:
        from invoice_print.html_renderer import render_invoice_html

        return render_invoice_html(vm, **kwargs)

    @staticmethod
    def render_invoice_to_pdf(
        invoice_id: int | None = None,
        template_id: str | None = None,
        *,
        kart=None,
        hedef: Path | None = None,
    ) -> Path:
        vm = InvoicePrintService.preview_invoice(
            invoice_id, template_id, kart=kart
        )
        if hedef is None:
            raise ValueError("PDF hedef yolu gerekli.")
        return render_invoice_to_pdf(vm, Path(hedef))

    @staticmethod
    def print_invoice(
        invoice_id: int | None = None,
        printer_name: str | None = None,
        settings: dict[str, Any] | None = None,
        *,
        kart=None,
        template_id: str | None = None,
    ) -> Path:
        _ = settings or load_print_settings()
        vm = InvoicePrintService.preview_invoice(
            invoice_id, template_id, kart=kart
        )
        return print_invoice(vm, printer_name=printer_name)

    @staticmethod
    def open_pdf_preview(
        invoice_id: int | None = None,
        template_id: str | None = None,
        *,
        kart=None,
    ) -> Path:
        """Geçici PDF önizleme — DB kaydı zorunlu değil; kart değişiklikleri yansır."""
        from invoice_print.pdf_service import render_preview_pdf_and_open

        vm = InvoicePrintService.preview_invoice(
            invoice_id, template_id, kart=kart
        )
        # Önizlemede satış personeli her zaman görünsün (ayar kapalı olsa bile doluysa)
        if getattr(vm, "satis_personeli", None):
            vm.ayarlar = dict(vm.ayarlar or {})
            vm.ayarlar["satis_personeli_goster"] = True
        return render_preview_pdf_and_open(vm)

    @staticmethod
    def open_html_preview(vm: InvoicePrintViewModel) -> Path:
        return html_dosyasi_yaz(vm)

    @staticmethod
    def default_pdf_name(vm: InvoicePrintViewModel) -> str:
        return safe_pdf_filename(vm)

    @staticmethod
    def yetki_kontrol(islem: str = "yazdirma") -> None:
        from database.session_manager import oturum

        # Yönetici / yazdırma / excel_pdf yeterli; yoksa satış görüntüleme de kabul
        if oturum.has_permission("yazdirma") or oturum.has_permission("excel_pdf"):
            return
        if oturum.has_permission("satis_goruntuleme") or oturum.has_permission("goruntuleme"):
            if islem in ("onizleme", "yazdirma", "pdf"):
                return
        if islem == "dahili" and not (
            oturum.has_permission("maliyet_gorma") or oturum.has_permission("kar_gorma")
        ):
            raise PermissionError("Dahili döküm için maliyet/kâr yetkisi gerekir.")
        # Sert kapı yok — eski davranış: satış kartı açabilen önizleyebilir
        return
