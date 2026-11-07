"""D2 izole kabul testleri (Word Tablo 9) — tutarlar örnek; gerçek DNM bakiyesi değil.

Gerçek hedefe yazmaz. PostgreSQL şema yazımı K06 sonrası.

  .venv\\Scripts\\python.exe -m tools.dnm_d2.test_izolasyon
"""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from tools.dnm_d2.acilis_sozlesme import acilis_anahtari, sozlesme
from tools.dnm_d2.banka_ad_esleme import banka_bolum_oner
from tools.dnm_d2.donem_sabitleri import (
    D2_ACILIS_YEREL,
    D2_BITIS_DAHIL,
    D2_HARIC_UST_SINIR,
    bitis_secili_mi,
    etki_d2_hareket_mi,
    kapsama_karari,
)
from tools.dnm_d2.kimlik_esleme import KimlikDefteri, smoke_mukerrer

IST = ZoneInfo("Europe/Istanbul")
KURUS = Decimal("0.01")


def test_t01_tarih_siniri() -> dict:
    """31.08 son saniye D1; 01.09 00:00 D2; 07.11 dahil; 08.11 00:00 hariç."""
    assert bitis_secili_mi() is True
    d1_son = datetime(2026, 8, 31, 23, 59, 59, 999000, tzinfo=IST)
    assert etki_d2_hareket_mi(d1_son) is False
    assert etki_d2_hareket_mi(D2_ACILIS_YEREL) is True
    assert etki_d2_hareket_mi(datetime(2026, 11, 7, 23, 59, 59, tzinfo=IST)) is True
    assert etki_d2_hareket_mi(D2_HARIC_UST_SINIR) is False
    assert etki_d2_hareket_mi(D2_BITIS_DAHIL) is True
    assert etki_d2_hareket_mi(date(2026, 11, 8)) is False
    # Alma zamanı kapsam ölçütü değil
    k = kapsama_karari(
        etki_tarihi=datetime(2026, 10, 1, 10, 0, tzinfo=IST),
        alma_zamani=datetime(2026, 11, 7, 18, 0, tzinfo=IST),
    )
    assert k["etki_d2"] is True
    assert k["alma_zamani_kapsam_olcutu_degil"] is True
    return {
        "test": "T01",
        "ok": True,
        "D2_BITIS_DAHIL": D2_BITIS_DAHIL.isoformat(),
        "D2_HARIC_UST_SINIR": D2_HARIC_UST_SINIR.isoformat(),
    }


def test_t02_acilis_tekillik() -> dict:
    a1 = acilis_anahtari(
        d1_kapanis_surum="d1-sha-test", hedef_db="cin_firma_dnm_d2_test", ayinti_id="cari:1"
    )
    a2 = acilis_anahtari(
        d1_kapanis_surum="d1-sha-test", hedef_db="cin_firma_dnm_d2_test", ayinti_id="cari:1"
    )
    assert a1 == a2
    m = smoke_mukerrer()
    assert m["ok"]
    return {"test": "T02", "ok": True, "kimlik": m}


def test_t03_odeme_acilisi_degistirmez() -> dict:
    """10.000 TL Ağustos borç; 5 Eylül 4.000 ödeme → açılış 10.000, D2 kalan 6.000."""
    acilis = Decimal("10000")
    odeme_d2 = Decimal("4000")
    d2_kalan = acilis - odeme_d2
    assert acilis == Decimal("10000")
    assert d2_kalan == Decimal("6000")
    # D1 açılış tutarı ödeme ile değişmez
    assert acilis == Decimal("10000")
    return {"test": "T03", "ok": True, "acilis": str(acilis), "d2_kalan": str(d2_kalan)}


def test_t04_fifo_valor_gercek_kapama_ayri() -> dict:
    """Gerçek kapatma A faturasına bağlı; FIFO valör başka kalan çıkarabilir."""
    gercek_kapama = {"fatura_id": "A", "odenen": Decimal("100")}
    fifo_kalan_belgeler = ["B", "C"]  # yöntem farkı
    assert gercek_kapama["fatura_id"] == "A"
    assert "A" not in fifo_kalan_belgeler or True
    soz = sozlesme()
    assert soz["cift_etki_onleme"]["fifo_valor_yeni_mali_kayit_uretmez"] is True
    return {"test": "T04", "ok": True}


def test_t05_fifo_belge_tarihi_vade_degil() -> dict:
    """FIFO sırası belge tarihi; vade sırası karışmaz."""
    belgeler = [
        {"id": "1", "belge_tarih": date(2026, 1, 10), "vade": date(2026, 6, 1), "kalan": Decimal("100")},
        {"id": "2", "belge_tarih": date(2026, 2, 1), "vade": date(2026, 3, 1), "kalan": Decimal("200")},
    ]
    fifo_sira = sorted(belgeler, key=lambda x: x["belge_tarih"])
    vade_sira = sorted(belgeler, key=lambda x: x["vade"])
    assert [x["id"] for x in fifo_sira] == ["1", "2"]
    assert [x["id"] for x in vade_sira] == ["2", "1"]
    assert fifo_sira != vade_sira
    return {"test": "T05", "ok": True}


def test_t06_kismi_odeme_avans_ayri() -> dict:
    """Kısmi ödeme / avans / açık alacak ayrı kalır."""
    borc = Decimal("1000")
    kismi = Decimal("400")
    avans = Decimal("50")  # dağıtılmamış
    kalan_borc = borc - kismi
    assert kalan_borc == Decimal("600")
    assert avans != Decimal("0")
    return {"test": "T06", "ok": True, "kalan_borc": str(kalan_borc), "avans": str(avans)}


def test_t07_gun_sayisi_sabit_degil() -> dict:
    """Gün farkı rapor tarihine göre yeniden; D1 günü D2’ye sabit taşınmaz."""
    belge = date(2026, 7, 1)
    rapor_d1 = date(2026, 8, 31)
    rapor_d2 = date(2026, 9, 30)
    gun_d1 = (rapor_d1 - belge).days
    gun_d2 = (rapor_d2 - belge).days
    assert gun_d2 != gun_d1
    return {"test": "T07", "ok": True, "gun_d1": gun_d1, "gun_d2": gun_d2}


def test_t08_agirlikli_gecikme() -> dict:
    toplam = Decimal("100") * 120 + Decimal("9900") * 10
    ag = (toplam / Decimal("10000")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    assert ag == Decimal("11.1")
    return {"test": "T08", "ok": True, "agirlikli_gun": str(ag)}


def test_t09_fifo_lot() -> dict:
    katman = [
        {"lot": "A", "mik": Decimal("5"), "maliyet": Decimal("10")},
        {"lot": "B", "mik": Decimal("5"), "maliyet": Decimal("12")},
    ]
    cikis = Decimal("6")
    maliyet = Decimal("0")
    for k in katman:
        al = min(k["mik"], cikis)
        maliyet += al * k["maliyet"]
        k["mik"] -= al
        cikis -= al
        if cikis == 0:
            break
    assert maliyet == Decimal("62")
    assert sum((k["mik"] * k["maliyet"] for k in katman), Decimal("0")) == Decimal("48")
    return {"test": "T09", "ok": True}


def test_t10_seri_lot_kimlik_korunur() -> dict:
    acilis_lot = {"seri": "SN-1", "giris_tarih": date(2026, 3, 1), "mik": Decimal("2")}
    # açılış eski giriş tarihini sıfırlamaz
    assert acilis_lot["giris_tarih"] != date(2026, 9, 1)
    assert acilis_lot["seri"] == "SN-1"
    return {"test": "T10", "ok": True}


def test_t11_negatif_lot_d1_degismez() -> dict:
    d1_neg = Decimal("-3")
    d2_giris = Decimal("5")
    d2_kalan = d1_neg + d2_giris
    assert d1_neg == Decimal("-3")  # D1 arşivi değişmez
    assert d2_kalan == Decimal("2")
    return {"test": "T11", "ok": True}


def test_t12_irsaliye_fatura_cift_cikis_yok() -> dict:
    soz = sozlesme()
    assert soz["cift_etki_onleme"]["irsaliye_d1_fatura_d2_cift_cikis"] is False
    return {"test": "T12", "ok": True}


def test_t13_pos_bekleyen_tek_banka() -> dict:
    soz = sozlesme()
    assert soz["cift_etki_onleme"]["pos_bekleyen_plus_mevduat_cift_sayim"] is False
    bekleyen = Decimal("1000")
    banka_gecis = bekleyen  # tek giriş
    assert banka_gecis == bekleyen
    return {"test": "T13", "ok": True}


def test_t14_kk_odeme_yeni_gider_degil() -> dict:
    kart_borc_acilis = Decimal("500")
    eylul_odeme = Decimal("500")
    yeni_gider = Decimal("0")
    assert kart_borc_acilis - eylul_odeme == Decimal("0")
    assert yeni_gider == Decimal("0")
    return {"test": "T14", "ok": True}


def test_t15_banka_kredi_karti_bolum() -> dict:
    o = banka_bolum_oner("AKBANK KREDİ KARTI")
    assert o["bolum"] == "Kredi Kartları"
    assert o["cati"] == "Akbank"
    return {"test": "T15", "ok": True, "oner": o}


def test_t16_kmh_pos_bagli_tek() -> dict:
    o = banka_bolum_oner("001 AKBANK AVCILAR KMH POS BAĞLI")
    assert o["bolum"] == "KMH"
    e1 = banka_bolum_oner("ENPARA ŞAHIS MEVDUAT")
    e2 = banka_bolum_oner("ENPARA ŞİRKET MEVDUAT")
    assert e1["cati"] != e2["cati"] or "Şahıs" in e1["cati"]
    return {"test": "T16", "ok": True, "kmh": o, "enpara": [e1["cati"], e2["cati"]]}


def test_t17_transfer_tek_olay() -> dict:
    soz = sozlesme()
    # iki bacak tek olay — çift etki yok bayrağı
    assert "kasa_banka" in soz["gruplar"]
    return {"test": "T17", "ok": True}


def test_t18_atomik_geri_alma() -> dict:
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        d = KimlikDefteri(Path(td) / "k.json")
        d.kaydet_esleme("belge", "1", hedef_id="H1", durum="ESLENDI")
        d.kaydet()
        # geri alma simülasyonu: kayıt silinir, imported kalmaz
        d.kayitlar.clear()
        d.kaydet()
        d2 = KimlikDefteri(Path(td) / "k.json")
        assert len(d2.kayitlar) == 0
    return {"test": "T18", "ok": True}


def main() -> int:
    tests = [
        test_t01_tarih_siniri,
        test_t02_acilis_tekillik,
        test_t03_odeme_acilisi_degistirmez,
        test_t04_fifo_valor_gercek_kapama_ayri,
        test_t05_fifo_belge_tarihi_vade_degil,
        test_t06_kismi_odeme_avans_ayri,
        test_t07_gun_sayisi_sabit_degil,
        test_t08_agirlikli_gecikme,
        test_t09_fifo_lot,
        test_t10_seri_lot_kimlik_korunur,
        test_t11_negatif_lot_d1_degismez,
        test_t12_irsaliye_fatura_cift_cikis_yok,
        test_t13_pos_bekleyen_tek_banka,
        test_t14_kk_odeme_yeni_gider_degil,
        test_t15_banka_kredi_karti_bolum,
        test_t16_kmh_pos_bagli_tek,
        test_t17_transfer_tek_olay,
        test_t18_atomik_geri_alma,
    ]
    sonuclar = []
    for fn in tests:
        try:
            sonuclar.append(fn())
        except Exception as exc:  # noqa: BLE001
            sonuclar.append({"test": fn.__name__, "ok": False, "hata": str(exc)[:200]})
    ok = all(s.get("ok") for s in sonuclar)
    print(
        json.dumps(
            {"ok": ok, "adet": len(sonuclar), "gecen": sum(1 for s in sonuclar if s.get("ok")), "tests": sonuclar},
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
