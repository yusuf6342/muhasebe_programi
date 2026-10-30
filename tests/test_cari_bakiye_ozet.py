"""Müşteri listesi borçlu/alacaklı özet eşiği (10 TL) kabul kontrolü."""

from decimal import Decimal

from database.cari_bakiye_service import OZET_ESIK_TL, filtre_bakiye_ozeti


def test_esik_ornek_tablosu():
    """Talimat 5.1: A–H bakiyeleri → 2 / 110,01 ve 2 / 90,01."""
    # Müşteri modu: + borçlu, − alacaklı
    bakiyeler = {
        1: Decimal("100.00"),   # A borçlu
        2: Decimal("10.01"),    # B borçlu
        3: Decimal("10.00"),    # C hariç
        4: Decimal("5.00"),     # D hariç
        5: Decimal("0.00"),     # E hariç
        6: Decimal("-10.00"),   # F alacaklı hariç
        7: Decimal("-10.01"),   # G alacaklı
        8: Decimal("-80.00"),   # H alacaklı
    }
    o = filtre_bakiye_ozeti(bakiyeler, tedarikci_modu=False)
    assert o["borclu_sayisi"] == 2
    assert o["borclar_toplami"] == Decimal("110.01")
    assert o["alacakli_sayisi"] == 2
    assert o["alacaklar_toplami"] == Decimal("90.01")
    assert o["esik"] == OZET_ESIK_TL


def test_filtre_alt_kume():
    """Yalnız A ve G → 1/100 ve 1/10,01."""
    bakiyeler = {
        1: Decimal("100.00"),
        7: Decimal("-10.01"),
    }
    o = filtre_bakiye_ozeti(bakiyeler)
    assert o["borclu_sayisi"] == 1
    assert o["borclar_toplami"] == Decimal("100.00")
    assert o["alacakli_sayisi"] == 1
    assert o["alacaklar_toplami"] == Decimal("10.01")


def test_ayni_cari_tek_kez():
    o = filtre_bakiye_ozeti([(1, Decimal("50")), (1, Decimal("50"))])
    assert o["borclu_sayisi"] == 1
    assert o["borclar_toplami"] == Decimal("50.00")
    assert o["kapsam_sayisi"] == 1


def test_tam_on_tl_haric():
    o = filtre_bakiye_ozeti({1: Decimal("10.00"), 2: Decimal("-10.00")})
    assert o["borclu_sayisi"] == 0
    assert o["alacakli_sayisi"] == 0
    assert o["esik_alti_sayisi"] == 2


def test_yon_filtre_liste_eslesmesi():
    """Borçlar/Alacaklar tıklanınca listelenen id'ler özetle aynı eşiği kullanır."""
    from database.cari_bakiye_service import OZET_ESIK_TL, bakiye_yon_kisa

    bakiyeler = {
        1: Decimal("100.00"),
        2: Decimal("10.01"),
        3: Decimal("10.00"),
        7: Decimal("-10.01"),
        8: Decimal("-80.00"),
        9: Decimal("-5.00"),
    }

    def _yon_liste(yon: str):
        ids = []
        for cid, bak in bakiyeler.items():
            if abs(bak) <= OZET_ESIK_TL:
                continue
            if bakiye_yon_kisa(bak) != ("Borçlu" if yon == "borclu" else "Alacaklı"):
                continue
            ids.append(cid)
        return ids

    assert _yon_liste("borclu") == [1, 2]
    assert _yon_liste("alacakli") == [7, 8]
    o = filtre_bakiye_ozeti(bakiyeler)
    assert o["borclu_sayisi"] == len(_yon_liste("borclu"))
    assert o["alacakli_sayisi"] == len(_yon_liste("alacakli"))
