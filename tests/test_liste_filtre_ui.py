"""liste_filtre_ui ortak yardımcılar."""

from decimal import Decimal
import inspect

from liste_filtre_ui import (
    baslik_filtre_metni,
    filtre_ozet_metni,
    sayfa_bilgi_metni,
    sayfa_dilim,
    satir_kolon_filtre_uygun,
    treeview_filtre_bagla,
    tutar_aralik_uygun,
    tutar_oku,
)


def test_tutar_oku_tr():
    assert tutar_oku("1.250,75") == Decimal("1250.75")
    assert tutar_oku("") is None
    assert tutar_oku(None) is None


def test_tutar_aralik():
    assert tutar_aralik_uygun(100, Decimal("50"), Decimal("150"))
    assert not tutar_aralik_uygun(40, Decimal("50"), None)
    assert not tutar_aralik_uygun(200, None, Decimal("150"))


def test_satir_kolon_filtre():
    kolonlar = ("a", "b")
    values = ("x", "y")
    assert satir_kolon_filtre_uygun(values, kolonlar, {})
    assert satir_kolon_filtre_uygun(values, kolonlar, {"a": {"x"}})
    assert not satir_kolon_filtre_uygun(values, kolonlar, {"a": {"z"}})


def test_baslik_ve_sayfa():
    assert "▾" in baslik_filtre_metni("Müşteri")
    assert "▼" in baslik_filtre_metni("Müşteri", filtre_aktif=True)
    assert "↑" in baslik_filtre_metni("Müşteri", siralama=("a", False), kolon="a")
    assert sayfa_bilgi_metni(0, 0, 100) == "0 kayıt"
    assert "1/3" in sayfa_bilgi_metni(250, 0, 100)
    assert len(sayfa_dilim(list(range(25)), 1, 10)) == 10


def test_filtre_ozet():
    assert "Toplam: 5" in filtre_ozet_metni(gorunen=5, toplam=5)
    assert "Gösterilen: 2 / 5" in filtre_ozet_metni(gorunen=2, toplam=5, aktif_filtre=1)


def test_treeview_filtre_bagla_imza():
    """DOC5 yardımcısı geriye uyumlu konumsal imza ile import edilir."""
    sig = inspect.signature(treeview_filtre_bagla)
    params = list(sig.parameters)
    assert params[:6] == [
        "tablo",
        "basliklar",
        "get_filtre_dict",
        "set_filtre_dict",
        "yenile_cb",
        "deger_listesi_cb",
    ]
    assert "haric_kolonlar" in sig.parameters
    assert "sag_tik_filtre" in sig.parameters


def test_rapor_modulleri_import():
    """DOC5 rapor UI modülleri kırılmadan yüklenir."""
    import cari_ekstre_ui  # noqa: F401
    import cari_usd_rapor_ui  # noqa: F401
    import doviz_kur_ui  # noqa: F401
    import doviz_rapor_ui  # noqa: F401
    import fon_ui  # noqa: F401
    import gider_rapor_ui  # noqa: F401
    import kk_ekstre_ui  # noqa: F401
    import satin_alma_rapor_ui  # noqa: F401
    import stok_rapor_ui  # noqa: F401
    from satin_alma_rapor_ui import RaporEkrani

    assert hasattr(RaporEkrani, "_filtre_bagla")
    assert hasattr(stok_rapor_ui, "_tablo_filtreli_doldur")
    assert callable(treeview_filtre_bagla)


def test_app_rapor_tablo_filtre_imza():
    """app.py gömülü rapor yardımcısı DOC5 haric_kolonlar / ham doldur içerir (canlı DB yok)."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1].joinpath("app.py").read_text(encoding="utf-8")
    assert "def _rapor_tablo(" in src
    assert "haric_kolonlar" in src
    assert "def _rapor_tablo_ham_doldur(" in src
    assert "def _treeview_filtre_bagla_hizli(" in src
    assert 'haric_kolonlar=("bakiye",)' in src
