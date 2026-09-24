"""Kayıt sonrası ekranın açık kalması (destroy yok)."""

from __future__ import annotations

import inspect


def test_kayit_sonrasi_yazdir_sor_destroy_yok():
    """Kayıt sonrası yardımcı destroy çağırmaz; yazdır sorusu yok."""
    import app as app_mod

    kaynak = inspect.getsource(app_mod.SatisFaturasiDialog._kayit_sonrasi_yazdir_sor)
    assert "self.destroy()" not in kaynak
    kaynak2 = inspect.getsource(app_mod.SatisFaturasiDialog._kayit_sonrasi_forma_yukle)
    assert "self.destroy()" not in kaynak2
    assert "yazdırılsın mı" not in kaynak2
    assert "askyesno" not in kaynak2
    kaynak3 = inspect.getsource(app_mod.SatisFaturasiDialog.kaydet)
    assert "self.destroy()" not in kaynak3
    assert "Onayla ve Yeni" in inspect.getsource(app_mod.SatisFaturasiDialog)
    assert "onayla_ve_yeni" in inspect.getsource(app_mod.SatisFaturasiDialog)


def test_override_ui_kaldirildi():
    """Eski Yuvarla / manuel Net override komutları satış diyalogunda yok."""
    import app as app_mod

    src = inspect.getsource(app_mod.SatisFaturasiDialog)
    for yasak in (
        "Yuvarla",
        "_neti_fiyatlara_dagit",
        "_fatura_yuvarla",
        "_genel_toplam_uygula",
    ):
        assert yasak not in src
    # Yeni sistem: Uzlaşılan Net'e orantılı fiyat uydurma mevcut olmalı
    assert "_uzlasilan_fiyatlara_dagit" in src
    assert "Fiyatları Net'e Uydur" in src
