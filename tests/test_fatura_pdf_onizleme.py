"""PDF önizleme — geçici dosya yolu ve servis."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

from invoice_print.pdf_service import gecici_onizleme_pdf_yolu, safe_pdf_filename
from invoice_print.view_model import InvoicePrintViewModel


def test_gecici_onizleme_yolu_benzersiz():
    vm = InvoicePrintViewModel(fatura_no="SF-1", belge_turu="SATIŞ FATURASI")
    a = gecici_onizleme_pdf_yolu(vm)
    b = gecici_onizleme_pdf_yolu(vm)
    assert a != b
    assert a.suffix == ".pdf"
    assert "onizleme_" in a.name
    assert a.parent.name == "muhasebe_fatura_onizleme"


def test_safe_pdf_filename_alis():
    vm = InvoicePrintViewModel(
        fatura_no="AF-9",
        belge_turu="ALIŞ FATURASI",
        musteri={"unvan": "Tedarik A"},
    )
    ad = safe_pdf_filename(vm)
    assert ad.startswith("Alis_Faturasi_")
    assert ad.endswith(".pdf")


def test_open_pdf_preview_kart_yeniden_hesap():
    from invoice_print.service import InvoicePrintService

    kart = MagicMock()
    with patch.object(InvoicePrintService, "preview_invoice") as prev, patch(
        "invoice_print.pdf_service.render_preview_pdf_and_open"
    ) as ac:
        vm = InvoicePrintViewModel(
            fatura_no="X",
            genel_toplam=Decimal("100"),
            fatura_brut_toplam=Decimal("110"),
            fatura_brut_goster="110,00 TL",
            satis_personeli="Ali Veli",
            ayarlar={},
        )
        prev.return_value = vm
        ac.return_value = MagicMock()
        InvoicePrintService.open_pdf_preview(kart=kart)
        prev.assert_called_once()
        assert vm.ayarlar.get("satis_personeli_goster") is True
        ac.assert_called_once_with(vm)
