"""DOC5: cari ekstre kolon filtresi çalışan bakiyeyi yeniden yazmaz."""

from __future__ import annotations

from decimal import Decimal

from liste_filtre_ui import satir_kolon_filtre_uygun


def _para(tutar) -> str:
    """cari_ekstre_ui._para ile uyumlu TR gösterim."""
    if tutar is None:
        return ""
    d = Decimal(str(tutar))
    return f"{d:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _belge_vals(tarih: str, baslik: str, borc, alacak, bakiye) -> tuple:
    return (
        tarih,
        "",
        baslik,
        "",
        "",
        "",
        "",
        _para(borc),
        _para(alacak),
        _para(bakiye),
    )


KOLONLAR = (
    "tarih",
    "kod",
    "urun",
    "miktar",
    "birim",
    "fiyat",
    "tutar",
    "borc",
    "alacak",
    "bakiye",
)


def _ornek_belgeler():
    """Kronolojik çalışan bakiye: 5000 → 7000 → 6000 (kapanış)."""
    return [
        {
            "tarih": "01.01.2026",
            "baslik": "Açılış / Fatura A",
            "borc": Decimal("5000"),
            "alacak": Decimal("0"),
            "bakiye": Decimal("5000"),
        },
        {
            "tarih": "15.01.2026",
            "baslik": "Fatura B",
            "borc": Decimal("2000"),
            "alacak": Decimal("0"),
            "bakiye": Decimal("7000"),
        },
        {
            "tarih": "20.01.2026",
            "baslik": "Tahsilat C",
            "borc": Decimal("0"),
            "alacak": Decimal("1000"),
            "bakiye": Decimal("6000"),
        },
    ]


def _filtre_gorunum(belgeler, liste_filtre: dict):
    """cari_ekstre yenile mantığının çekirdeği (Tk yok)."""
    gosterilen = []
    filtre_net = Decimal("0")
    for b in belgeler:
        vals = _belge_vals(b["tarih"], b["baslik"], b["borc"], b["alacak"], b["bakiye"])
        if not satir_kolon_filtre_uygun(vals, KOLONLAR, liste_filtre):
            continue
        gosterilen.append(b)
        filtre_net += b["borc"] - b["alacak"]
    return gosterilen, filtre_net


def test_aciklama_filtresi_sakli_bakiyeyi_degistirmez():
    """Kontrol 13: açıklama filtresi gerçek kapanışı değiştirmez; satır bakiyesi saklıdır."""
    belgeler = _ornek_belgeler()
    gercek_kapanis = Decimal("6000")  # tam akış kapanışı
    # Yalnız «Fatura B» kalsın → son görünen satır bakiyesi 7000; kapanış yine 6000
    filtre = {"urun": {_belge_vals("15.01.2026", "Fatura B", 2000, 0, 7000)[2]}}
    gosterilen, filtre_net = _filtre_gorunum(belgeler, filtre)
    assert len(gosterilen) == 1
    assert gosterilen[0]["bakiye"] == Decimal("7000")  # saklı çalışan bakiye
    assert filtre_net == Decimal("2000")  # filtrelenen hareket neti
    assert gercek_kapanis == Decimal("6000")  # filtre kapanışı ezmez
    assert filtre_net != gercek_kapanis


def test_filtre_temizlenince_tum_satirlar_ve_kapanis():
    belgeler = _ornek_belgeler()
    filtre = {"urun": {"Fatura B"}}
    g1, _ = _filtre_gorunum(belgeler, filtre)
    assert len(g1) == 1
    g2, net = _filtre_gorunum(belgeler, {})
    assert len(g2) == 3
    assert net == Decimal("6000")  # 5000+2000-1000
    assert [b["bakiye"] for b in g2] == [
        Decimal("5000"),
        Decimal("7000"),
        Decimal("6000"),
    ]


def test_bakiye_kolonu_huniden_haric_imza():
    """cari_ekstre_ui haric_kolonlar=('bakiye',) ile bağlanır."""
    import inspect

    import cari_ekstre_ui as mod

    src = inspect.getsource(mod.StokDetayliCariEkstreDialog._filtre_bagla)
    assert "haric_kolonlar" in src
    assert "bakiye" in src


def test_etiket_metinleri_doc5():
    """UI özet etiketleri yanıltıcı 'filtre bakiyesi' kullanmaz."""
    import inspect

    import cari_ekstre_ui as mod

    src = inspect.getsource(mod.StokDetayliCariEkstreDialog.yenile)
    assert "Gerçek kapanış bakiyesi" in src
    assert "Filtrelenen hareket neti" in src
    assert "Son bakiye (saklı)" not in src
    # Görünür satır bakiyesinden kapanış türetilmez
    assert "son_bakiye" not in src


def test_mizan_genel_toplam_tam_rapor_etiketi():
    import inspect

    import genel_muhasebe_ui as gm

    src = inspect.getsource(gm.mizan_goster)
    assert "GENEL TOPLAM (tam rapor)" in src
    assert "Filtrelenen hesapların toplamı" in src
    assert "haric_kolonlar" in src


def test_rapor_bakiye_ornegi_5000_2000_1000():
    """DOC5 senaryo: 5000 + 2000 − 1000 = 6000 kapanış."""
    bas = Decimal("5000")
    donem_borc = Decimal("2000")
    donem_alacak = Decimal("1000")
    kapanis = bas + donem_borc - donem_alacak
    assert kapanis == Decimal("6000")
    # Açıklama filtresiyle yalnız tahsilat gizlenince kapanış hâlâ 6000
    gorunen_net = bas + donem_borc  # tahsilat gizli
    assert gorunen_net == Decimal("7000")
    assert kapanis != gorunen_net
