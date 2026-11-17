"""Yeni satış faturasında müşteri seçimi tek açık siparişi otomatik satır yapmamalı."""
from __future__ import annotations

from pathlib import Path


def test_fatura_cari_degisti_otomatik_sec_false():
    metin = Path("app.py").read_text(encoding="utf-8")
    assert "def _fatura_cari_degisti" in metin
    # Müşteri değişiminde otomatik satır yükleme kapalı
    assert "_fatura_baglanti_listelerini_yenile(otomatik_sec=False)" in metin
    assert "_fatura_baglanti_listelerini_yenile(otomatik_sec=True)" not in metin


def test_baglanti_yenile_tek_kayit_otomatik_yukleme_yok():
    """Tek açık sipariş/irsaliye sessizce satır yüklenmez."""
    metin = Path("app.py").read_text(encoding="utf-8")
    assert "Tek kayıt varsa otomatik bağla" not in metin
    # Müşteri/açılış yolundan gelen otomatik sipariş seçimi kaldırıldı
    assert "_fatura_siparis_secildi(otomatik=True)" not in metin
    # Sipariş seçildikten sonra tek ilgili irsaliye cascade'i bilinçli kalabilir
    assert "def _fatura_siparis_secildi" in metin
    assert "def _fatura_irsaliye_secildi" in metin


def test_yeni_fatura_acilista_otomatik_sec_false():
    metin = Path("app.py").read_text(encoding="utf-8")
    assert (
        "otomatik_sec=not bool(self.kaynak_siparis or self.kaynak_irsaliye or self.fatura)"
        not in metin
    )
