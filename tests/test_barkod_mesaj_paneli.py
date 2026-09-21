"""Barkod bulunamadı — kalıcı mesaj paneli / servis testleri."""

from datetime import datetime
from unittest.mock import MagicMock, patch

from fatura_satir_birim_service import miktar_metnini_coz
from database.models.invoice_scan_message import (
    MSG_BARCODE_NOT_FOUND,
    STATUS_OPEN,
)


def test_miktar_barkod_benzeri_reddedilir():
    try:
        miktar_metnini_coz("1031109304")
        assert False, "barkod miktar olmamalı"
    except ValueError as exc:
        assert "barkod" in str(exc).casefold()


def test_miktar_normal_kabul():
    assert miktar_metnini_coz("5") == __import__("decimal").Decimal("5")
    assert miktar_metnini_coz("1,5") == __import__("decimal").Decimal("1.500000")


def test_barkod_bulunamadi_metin_sifir_korunur():
    from database.invoice_scan_message_service import barkod_bulunamadi_kaydet

    kayit = {
        "id": 1,
        "barcode": "001234567890",
        "message_text": "001234567890 nolu barkod bulunamadı.",
        "scan_count": 1,
        "status": STATUS_OPEN,
        "message_type": MSG_BARCODE_NOT_FOUND,
        "last_seen_at": datetime.now(),
        "created_at": datetime.now(),
    }
    with patch(
        "database.invoice_scan_message_service.get_session"
    ) as gs, patch(
        "database.invoice_scan_message_service.oturum"
    ) as ot:
        ot.company_id = 1
        ot.user_id = 1
        # Boş DB yolu: mock session
        sess = MagicMock()
        sess.scalar.return_value = None
        sess.__enter__ = MagicMock(return_value=sess)
        sess.__exit__ = MagicMock(return_value=False)

        def _flush():
            # flush sonrası id
            pass

        def _add(obj):
            obj.id = 99
            obj.company_id = 1
            obj.invoice_id = None
            obj.invoice_no = None
            obj.session_key = "abc"
            obj.user_id = 1
            obj.barcode = "001234567890"
            obj.message_type = MSG_BARCODE_NOT_FOUND
            obj.message_text = "001234567890 nolu barkod bulunamadı."
            obj.scan_count = 1
            obj.status = STATUS_OPEN
            obj.created_at = datetime.now()
            obj.last_seen_at = datetime.now()
            obj.closed_at = None
            obj.closed_by = None

        sess.add.side_effect = _add
        sess.flush.side_effect = _flush
        gs.return_value = sess
        sonuc = barkod_bulunamadi_kaydet(
            barcode="001234567890", session_key="abc"
        )
        assert sonuc is not None
        assert sonuc["barcode"] == "001234567890"
        assert "001234567890" in sonuc["message_text"]
        assert sonuc["scan_count"] == 1


def test_ayni_barkod_sayac_artar():
    from database.invoice_scan_message_service import barkod_bulunamadi_kaydet
    from database.models.invoice_scan_message import InvoiceScanMessage

    mevcut = InvoiceScanMessage(
        company_id=1,
        barcode="2601031109304",
        message_type=MSG_BARCODE_NOT_FOUND,
        message_text="2601031109304 nolu barkod bulunamadı.",
        scan_count=2,
        status=STATUS_OPEN,
        created_at=datetime.now(),
        last_seen_at=datetime.now(),
        session_key="s1",
    )
    mevcut.id = 7
    with patch(
        "database.invoice_scan_message_service.get_session"
    ) as gs, patch(
        "database.invoice_scan_message_service.oturum"
    ) as ot:
        ot.company_id = 1
        ot.user_id = 1
        sess = MagicMock()
        sess.scalar.return_value = mevcut
        sess.__enter__ = MagicMock(return_value=sess)
        sess.__exit__ = MagicMock(return_value=False)
        gs.return_value = sess
        sonuc = barkod_bulunamadi_kaydet(
            barcode="2601031109304", session_key="s1"
        )
        assert sonuc["scan_count"] == 3
