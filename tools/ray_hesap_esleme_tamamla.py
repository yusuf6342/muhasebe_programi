"""Ray Mobilya: ana hesaba bağlı / boş muhasebe eşleştirmelerini fişe açık alt hesaplarla tamamlar.

Kullanıcı onayıyla gerçek veritabanında alt hesap açar ve eşleştirme bağlar. Kurallar:

- Hesaplar ilgili TDHP ana hesabın altında, mevcut düzende (``ana.01`` tali grup → ``ana.01.0001``
  yaprak) ve sıfır bakiyeyle açılır. Tali grup fişe kapalıdır (altında hesap var), yaprak fişe açıktır.
- Eşleştirme yalnız fişe uygun (``hesap_uygunluk_sorunu`` boş) hesaba bağlanır; zaten uygun bir
  hesaba bağlı eşleştirme korunur (kullanıcı seçimi değiştirilmez).
- Ana hesabın altında planda olmayan fişe uygun alt hesap varsa mükerrer hesap açılmaz, seçim
  kullanıcıya bırakılır. Kesin olmayan eşleştirmeler (``BELIRSIZ``) bağlanmaz, raporlanır.
- Fiş, fiş satırı, hesap bakiyesi, cari/stok ve geçmiş belgeler değişmez; hiçbir belge
  muhasebeleştirilmez. Değişen tablolar: hesap planı, hesap eşleştirmeleri, muhasebe işlem geçmişi.

    python tools/ray_hesap_esleme_tamamla.py              # kuru çalıştırma (TEMP kopyada simülasyon)
    python tools/ray_hesap_esleme_tamamla.py --uygula     # yedek + doğrulama + tek transaction
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event, select, text  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import database.models.firma  # noqa: E402,F401
import database.models.cari  # noqa: E402,F401
import database.models.stok  # noqa: E402,F401
import database.models.finans  # noqa: E402,F401
from database.models.genel_muhasebe import (  # noqa: E402
    ESLEME_ANAHTARLARI,
    HESAP_TURLERI,
    HesapPlani,
    MuhasebeHesapEsleme,
    MuhasebeIslemGecmisi,
)
from database.muhasebe_entegrasyon import hesap_uygunluk_sorunu, uygun_alt_hesaplar  # noqa: E402

VARSAYILAN_DB = Path(r"C:\Users\cigde\AppData\Local\MuhasebeProgrami\data\muhasebe.db")
CIKTI_KLASORU = ROOT / "inceleme" / "muhasebelestirme"
ISLEM_YAPAN = "ray_hesap_esleme_tamamla (kullanıcı onaylı)"
DEGISEBILIR_TABLOLAR = {"muhasebe_hesap_plani", "muhasebe_hesap_eslemeleri", "muhasebe_islem_gecmisi"}

# (anahtar, ana kod, (tali grup kodu, adı), (yaprak kodu, adı), seçim gerekçesi)
HEDEFLER: tuple[tuple[str, str, tuple[str, str], tuple[str, str], str], ...] = (
    ("musteriler", "120", ("120.01", "ALICILAR TALİ HESABI"), ("120.01.0001", "ALICILAR ALT HESABI"),
     "Cari ayrıntısı cari modülünde; TDHP 120 Alıcılar altında tek fişe açık hesap. Mevcut eşleme 120 korunarak alta indirildi."),
    ("tedarikciler", "320", ("320.01", "SATICILAR TALİ HESABI"), ("320.01.0001", "SATICILAR ALT HESABI"),
     "TDHP 320 Satıcılar; mevcut eşleme 320 alt hesaba indirildi."),
    ("yurtici_satislar", "600", ("600.01", "YURTİÇİ SATIŞLAR TALİ HESABI"),
     ("600.01.0001", "YURTİÇİ SATIŞLAR ALT HESABI"), "TDHP 600; mevcut eşleme 600 alt hesaba indirildi."),
    ("satilan_mal_maliyeti", "621", ("621.01", "SATILAN TİCARİ MALLAR MALİYETİ TALİ HESABI"),
     ("621.01.0001", "SATILAN TİCARİ MALLAR MALİYETİ ALT HESABI"), "TDHP 621; mevcut eşleme 621 alt hesaba indirildi."),
    ("ticari_mallar", "153", ("153.01", "TİCARİ MALLAR TALİ HESABI"), ("153.01.0001", "TİCARİ MALLAR ALT HESABI"),
     "153 altındaki tek fişe uygun hesap (mevcut, 0 kullanım, adı amaçla aynı); yeni hesap açılmadı."),
    ("hesaplanan_kdv", "391", ("391.01", "HESAPLANAN KDV TALİ HESABI"), ("391.01.0001", "HESAPLANAN KDV ALT HESABI"),
     "TDHP 391; program tek hesaplanan KDV anahtarı kullanır (oran ayrımı yok)."),
    ("indirilecek_kdv", "191", ("191.01", "İNDİRİLECEK KDV TALİ HESABI"), ("191.01.0001", "İNDİRİLECEK KDV ALT HESABI"),
     "TDHP 191; program tek indirilecek KDV anahtarı kullanır."),
    ("giderler", "770", ("770.01", "GENEL YÖNETİM GİDERLERİ TALİ HESABI"),
     ("770.01.0001", "GENEL YÖNETİM GİDERLERİ ALT HESABI"),
     "Kullanıcının seçtiği 770 (7/A gider düzeni) alt hesaba indirildi."),
    ("pos_komisyon_gideri", "653", ("653.01", "KOMİSYON GİDERLERİ TALİ HESABI"), ("653.01.0001", "POS KOMİSYON GİDERLERİ"),
     "TDHP 653 Komisyon Giderleri; banka ayrımı gerektirmeyen gider hesabı."),
    ("cek_portfoy", "101", ("101.01", "MÜŞTERİ ÇEKLERİ TALİ HESABI"), ("101.01.0001", "MÜŞTERİ ÇEKLERİ ALT HESABI"),
     "101 altındaki mevcut tek fişe uygun hesap (müşteri çekleri = portföydeki alınan çekler, 0 kullanım)."),
    ("cek_tahsilde", "101", ("101.02", "TAHSİLE VERİLEN ÇEKLER TALİ HESABI"), ("101.02.0001", "TAHSİLE VERİLEN ÇEKLER"),
     "TDHP 101 altında aşama ayrımı (portföy / tahsil / teminat); hangi bankada olduğu çek modülünde."),
    ("cek_teminatta", "101", ("101.03", "TEMİNATA VERİLEN ÇEKLER TALİ HESABI"), ("101.03.0001", "TEMİNATA VERİLEN ÇEKLER"),
     "TDHP 101 altında teminat aşaması."),
    ("senet_portfoy", "121", ("121.01", "PORTFÖYDEKİ SENETLER TALİ HESABI"), ("121.01.0001", "PORTFÖYDEKİ ALACAK SENETLERİ"),
     "TDHP 121 Alacak Senetleri, portföy aşaması."),
    ("senet_tahsilde", "121", ("121.02", "TAHSİLE VERİLEN SENETLER TALİ HESABI"), ("121.02.0001", "TAHSİLE VERİLEN SENETLER"),
     "TDHP 121, tahsil aşaması."),
    ("senet_teminatta", "121", ("121.03", "TEMİNATA VERİLEN SENETLER TALİ HESABI"), ("121.03.0001", "TEMİNATA VERİLEN SENETLER"),
     "TDHP 121, teminat aşaması."),
    ("verilen_cekler", "103", ("103.01", "VERİLEN ÇEKLER TALİ HESABI"), ("103.01.0001", "VERİLEN ÇEKLER VE ÖDEME EMİRLERİ"),
     "TDHP 103 Verilen Çekler ve Ödeme Emirleri (-)."),
    ("borc_senetleri", "321", ("321.01", "BORÇ SENETLERİ TALİ HESABI"), ("321.01.0001", "BORÇ SENETLERİ ALT HESABI"),
     "TDHP 321 Borç Senetleri."),
    ("kredi_kisa_vadeli", "300", ("300.01", "BANKA KREDİLERİ TALİ HESABI"), ("300.01.0001", "KISA VADELİ BANKA KREDİLERİ"),
     "TDHP 300; mevcut 3 kredinin tamamı tek banka kartında (AKBANK A.Ş), kredi ayrıntısı kredi modülünde."),
    ("kredi_uzun_vadeli", "400", ("400.01", "BANKA KREDİLERİ TALİ HESABI"), ("400.01.0001", "UZUN VADELİ BANKA KREDİLERİ"),
     "TDHP 400 uzun vadeli banka kredileri."),
    ("kredi_faiz_gideri", "780", ("780.01", "KREDİ FİNANSMAN GİDERLERİ TALİ HESABI"), ("780.01.0001", "KREDİ FAİZ GİDERLERİ"),
     "Firma 7/A düzeninde (giderler=770); finansman giderleri 780'de toplanır (660'a dönem sonu aktarılır)."),
    ("kredi_bsmv_gideri", "780", ("780.01", "KREDİ FİNANSMAN GİDERLERİ TALİ HESABI"), ("780.01.0002", "KREDİ BSMV GİDERLERİ"),
     "Kredi faizine bağlı BSMV finansman gideridir (780)."),
    ("kredi_kkdf_gideri", "780", ("780.01", "KREDİ FİNANSMAN GİDERLERİ TALİ HESABI"), ("780.01.0003", "KREDİ KKDF GİDERLERİ"),
     "Kredi faizine bağlı KKDF finansman gideridir (780)."),
    ("kredi_komisyon_gideri", "780", ("780.01", "KREDİ FİNANSMAN GİDERLERİ TALİ HESABI"),
     ("780.01.0004", "KREDİ KOMİSYON GİDERLERİ"), "Kredi kullandırım komisyonu finansman gideridir (780)."),
    ("kredi_sigorta_gideri", "780", ("780.01", "KREDİ FİNANSMAN GİDERLERİ TALİ HESABI"),
     ("780.01.0005", "KREDİ SİGORTA GİDERLERİ"), "Krediye bağlı sigorta (kredi taksidiyle tahsil edilen) finansman maliyeti (780)."),
    ("kredi_dosya_masrafi", "780", ("780.01", "KREDİ FİNANSMAN GİDERLERİ TALİ HESABI"),
     ("780.01.0006", "KREDİ DOSYA / İŞLEM MASRAFLARI"), "Kredi dosya masrafı finansman gideridir (780)."),
    ("kredi_gecikme_faizi", "780", ("780.01", "KREDİ FİNANSMAN GİDERLERİ TALİ HESABI"),
     ("780.01.0007", "KREDİ GECİKME FAİZLERİ"), "Kredi taksit gecikme faizi finansman gideridir (780)."),
    ("kredi_diger_finansman", "780", ("780.01", "KREDİ FİNANSMAN GİDERLERİ TALİ HESABI"),
     ("780.01.0008", "DİĞER FİNANSMAN GİDERLERİ"), "TDHP 780 Finansman Giderleri."),
    ("kur_farki_geliri", "646", ("646.01", "KAMBİYO KARLARI TALİ HESABI"), ("646.01.0001", "KUR FARKI GELİRLERİ"),
     "TDHP 646 Kambiyo Kârları (programın önerdiği ana hesap)."),
    ("kur_farki_gideri", "656", ("656.01", "KAMBİYO ZARARLARI TALİ HESABI"), ("656.01.0001", "KUR FARKI GİDERLERİ"),
     "TDHP 656 Kambiyo Zararları (programın önerdiği ana hesap)."),
)
PLANLI_YAPRAKLAR = {y[0] for _a, _k, _g, y, _n in HEDEFLER}

# Kesin olarak belirlenemeyen eşleştirmeler: bağlanmaz, kanıtla raporlanır.
BELIRSIZ: dict[str, str] = {
    "kasa": "100 altında iki fişe uygun hesap (100.01.0001 NAKİT TL KASA, 100.01.0002 MERKEZ KASA), ikisi de "
            "kullanılmamış; tek kasa kartı (ANA KASA) ve kasa kartında muhasebe hesabı alanı yok.",
    "banka": "Program tüm mevduat kartlarını tek 'banka' eşleştirmesine yazar; birden çok bankada hareketli "
             "mevduat kartı var. Tek 102 alt hesabına bağlamak banka ayrımını kaybettirir.",
    "kmh_hesabi": "Birden çok bankada hareketli KMH kartı var, eşleştirme tek hesap; ayrıca KMH'nin 300 (kredi) mi "
                  "102 (eksi bakiye) mi izleneceği firma tercihi.",
    "pos_valor_alacagi": "Birden çok bankada hareketli POS kartı var, eşleştirme tek hesap (banka ayrımı kaybolur).",
    "sirket_kart_borcu": "Birden çok bankada şirket kredi kartı hareketli, eşleştirme tek hesap; Ray planında 309 "
                         "adı 'Diğer Mali Borçlar Faiz Tahakkuku' (standart dışı ad).",
    "kredi_ara_hesap": "Programda kullanılmıyor; amacı tanımsız.",
}


# ====================================================================== plan / uygulama (oturum içinde)
def planla(s: Session, firma_id: int) -> dict:
    """Yazmadan yapılacakları çıkarır."""
    hesaplar = {h.hesap_kodu: h for h in s.scalars(select(HesapPlani).where(HesapPlani.firma_id == firma_id))}
    eslemeler = {e.anahtar: e for e in s.scalars(
        select(MuhasebeHesapEsleme).where(MuhasebeHesapEsleme.firma_id == firma_id))}
    id_kod = {h.id: h for h in hesaplar.values()}
    plan: dict = {"esleme_satiri_ekle": [], "hesap_ekle": [], "bagla": [], "korunan": [], "kullanici_karari": []}
    eklenecek: set[str] = set()

    plan["esleme_satiri_ekle"] = [a for a, _ in ESLEME_ANAHTARLARI if a not in eslemeler]
    for anahtar, ana_kod, (grup_kod, grup_ad), (yaprak_kod, yaprak_ad), gerekce in HEDEFLER:
        e = eslemeler.get(anahtar)
        mevcut = id_kod.get(e.hesap_id) if e is not None and e.hesap_id else None
        onceki = mevcut.hesap_kodu if mevcut else None
        if mevcut is not None and hesap_uygunluk_sorunu(s, mevcut, firma_id) is None:
            plan["korunan"].append({"anahtar": anahtar, "hesap": onceki, "ad": mevcut.hesap_adi})
            continue
        ana = hesaplar.get(ana_kod)
        if ana is None or not ana.aktif:
            plan["kullanici_karari"].append({"anahtar": anahtar, "onceki": onceki,
                                             "neden": f"{ana_kod} ana hesabı hesap planında yok/pasif"})
            continue
        digerleri = [h.hesap_kodu for h in uygun_alt_hesaplar(s, firma_id, ana_kod)
                     if h.hesap_kodu not in PLANLI_YAPRAKLAR]
        if digerleri:
            plan["kullanici_karari"].append({
                "anahtar": anahtar, "onceki": onceki,
                "neden": f"{ana_kod} altında planda olmayan fişe uygun hesap var ({', '.join(digerleri)}); "
                         "mükerrer hesap açılmadı"})
            continue
        grup = hesaplar.get(grup_kod)
        if grup is None:
            if grup_kod not in eklenecek:
                plan["hesap_ekle"].append({"kod": grup_kod, "ad": grup_ad, "ust": ana_kod, "tur": ana.hesap_turu,
                                           "fise_acik": False})
                eklenecek.add(grup_kod)
        elif not grup.aktif or not grup_kod.startswith(f"{ana_kod}."):
            plan["kullanici_karari"].append({"anahtar": anahtar, "onceki": onceki,
                                             "neden": f"{grup_kod} tali hesabı pasif / kodu uyumsuz"})
            continue
        yaprak = hesaplar.get(yaprak_kod)
        if yaprak is None:
            if yaprak_kod in eklenecek:
                plan["kullanici_karari"].append({"anahtar": anahtar, "onceki": onceki,
                                                 "neden": f"{yaprak_kod} başka anahtar için planlandı"})
                continue
            plan["hesap_ekle"].append({"kod": yaprak_kod, "ad": yaprak_ad, "ust": grup_kod, "tur": ana.hesap_turu,
                                       "fise_acik": True})
            eklenecek.add(yaprak_kod)
            yeni = True
        else:
            sorun = hesap_uygunluk_sorunu(s, yaprak, firma_id)
            if sorun:
                plan["kullanici_karari"].append({"anahtar": anahtar, "onceki": onceki, "neden": sorun})
                continue
            yaprak_ad, yeni = yaprak.hesap_adi, False
        plan["bagla"].append({"anahtar": anahtar, "onceki": onceki, "hesap": yaprak_kod, "ad": yaprak_ad,
                              "yeni_hesap": yeni, "gerekce": gerekce})

    for anahtar, neden in BELIRSIZ.items():
        e = eslemeler.get(anahtar)
        mevcut = id_kod.get(e.hesap_id) if e is not None and e.hesap_id else None
        if mevcut is not None and hesap_uygunluk_sorunu(s, mevcut, firma_id) is None:
            plan["korunan"].append({"anahtar": anahtar, "hesap": mevcut.hesap_kodu, "ad": mevcut.hesap_adi})
            continue
        plan["kullanici_karari"].append({"anahtar": anahtar, "onceki": mevcut.hesap_kodu if mevcut else None,
                                         "neden": neden})
    plan["kanit"] = finans_kanit(s)
    return plan


def finans_kanit(s: Session) -> dict:
    """Belirsiz finans eşleştirmeleri için kayıtlı kullanım: alt türe göre hareketli kartlar."""
    c = s.connection()
    if not c.execute(text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='finans_hesaplari'")).first():
        return {}
    satirlar = c.execute(text(
        "SELECT h.id, h.hesap_adi, h.hesap_turu, COALESCE(h.alt_hesap_turu,''), "
        "(SELECT COUNT(*) FROM finans_hareketleri f WHERE f.hesap_id = h.id) "
        "FROM finans_hesaplari h WHERE h.aktif = 1 ORDER BY h.id")).all()
    kanit: dict[str, list] = {}
    for hid, ad, tur, alt, adet in satirlar:
        if not adet:
            continue
        anahtar = "kasa" if (tur or "").upper() == "KASA" else (alt or tur or "").upper()
        kanit.setdefault(anahtar, []).append({"id": hid, "ad": ad, "hareket": int(adet)})
    return kanit


def uygula(s: Session, firma_id: int, plan: dict, *, islem_yapan: str = ISLEM_YAPAN) -> dict:
    """Planı verilen oturumda yazar (commit çağırana aittir); her bağlamayı fişe uygunlukla doğrular."""
    hesaplar = {h.hesap_kodu: h for h in s.scalars(select(HesapPlani).where(HesapPlani.firma_id == firma_id))}
    adlar = dict(ESLEME_ANAHTARLARI)

    def gecmis(kayit_turu: str, kayit_id: int, islem: str, detay: str) -> None:
        s.add(MuhasebeIslemGecmisi(firma_id=firma_id, kayit_turu=kayit_turu, kayit_id=kayit_id, islem=islem,
                                   detay=detay, kullanici_id=None, kullanici_adi=islem_yapan[:80]))

    for anahtar in plan["esleme_satiri_ekle"]:
        s.add(MuhasebeHesapEsleme(firma_id=firma_id, anahtar=anahtar, aciklama=adlar[anahtar], hesap_id=None,
                                  aktif=True))
    eklenen = []
    for h in plan["hesap_ekle"]:
        if h["kod"] in hesaplar:
            raise ValueError(f"Bu hesap kodu zaten var: {h['kod']}")
        if h["tur"] not in HESAP_TURLERI:
            raise ValueError(f"Geçersiz hesap türü: {h['tur']}")
        ust = hesaplar[h["ust"]]
        yeni = HesapPlani(firma_id=firma_id, hesap_kodu=h["kod"], hesap_adi=h["ad"], ust_hesap_id=ust.id,
                          hesap_seviyesi=int(ust.hesap_seviyesi) + 1, hesap_turu=h["tur"], aktif=True,
                          borc_toplam=0, alacak_toplam=0)
        s.add(yeni)
        s.flush()
        hesaplar[h["kod"]] = yeni
        gecmis("hesap", yeni.id, "ekle", f"{h['kod']} {h['ad']} (üst {h['ust']}, sıfır bakiye)")
        eklenen.append(h["kod"])
    s.flush()

    eslemeler = {e.anahtar: e for e in s.scalars(
        select(MuhasebeHesapEsleme).where(MuhasebeHesapEsleme.firma_id == firma_id))}
    for b in plan["bagla"]:
        h = hesaplar[b["hesap"]]
        sorun = hesap_uygunluk_sorunu(s, h, firma_id)
        if sorun:
            raise ValueError(f"{b['anahtar']} → {b['hesap']} fişe uygun değil: {sorun}")
        e = eslemeler[b["anahtar"]]
        e.hesap_id = h.id
        gecmis("esleme", e.id, "bagla", f"{b['anahtar']}: {b['onceki'] or '-'} → {b['hesap']}")
    s.flush()

    for h in plan["hesap_ekle"]:
        yeni = hesaplar[h["kod"]]
        acik = hesap_uygunluk_sorunu(s, yeni, firma_id) is None
        if acik != h["fise_acik"]:
            raise ValueError(f"{h['kod']} fişe {'açık' if acik else 'kapalı'} oldu, beklenen tersiydi")
    return {"eklenen_hesap": eklenen, "baglanan": [b["anahtar"] for b in plan["bagla"]]}


# ====================================================================== gerçek DB işlemleri
def olcum(baglanti) -> dict:
    """Öncesi/sonrası karşılaştırması: tablo satır sayıları, fiş toplamları, hesap bakiyeleri."""
    tablolar = [r[0] for r in baglanti.execute(text(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"))]
    sayilar = {t: baglanti.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar() for t in tablolar}
    fis = baglanti.execute(text(
        "SELECT COUNT(*), COALESCE(SUM(toplam_borc),0), COALESCE(SUM(toplam_alacak),0) FROM muhasebe_fisleri")).one()
    satir = baglanti.execute(text(
        "SELECT COUNT(*), COALESCE(SUM(borc),0), COALESCE(SUM(alacak),0) FROM muhasebe_fis_satirlari")).one()
    bakiye = baglanti.execute(text(
        "SELECT COALESCE(SUM(borc_toplam),0), COALESCE(SUM(alacak_toplam),0) FROM muhasebe_hesap_plani")).one()
    hesap_bakiyeleri = {k: [float(b), float(a)] for k, b, a in baglanti.execute(text(
        "SELECT hesap_kodu, borc_toplam, alacak_toplam FROM muhasebe_hesap_plani"))}
    eslemeler = dict(baglanti.execute(text(
        "SELECT e.anahtar, h.hesap_kodu FROM muhasebe_hesap_eslemeleri e "
        "LEFT JOIN muhasebe_hesap_plani h ON h.id = e.hesap_id")).all())
    return {
        "tablo_sayilari": sayilar,
        "fis": {"sayi": fis[0], "toplam_borc": float(fis[1]), "toplam_alacak": float(fis[2])},
        "fis_satiri": {"sayi": satir[0], "borc": float(satir[1]), "alacak": float(satir[2])},
        "hesap_plani_bakiye": {"borc_toplam": float(bakiye[0]), "alacak_toplam": float(bakiye[1])},
        "hesap_bakiyeleri": hesap_bakiyeleri,
        "eslemeler": eslemeler,
    }


def karsilastir(once: dict, sonra: dict, sonuc: dict, plan: dict) -> list[str]:
    """Yalnız hesap planı / eşleştirme / işlem geçmişi değişmiş olmalı; sorunlar listesi döner."""
    sorunlar = []
    for t in sorted(set(once["tablo_sayilari"]) | set(sonra["tablo_sayilari"])):
        a, b = once["tablo_sayilari"].get(t), sonra["tablo_sayilari"].get(t)
        if a != b and t not in DEGISEBILIR_TABLOLAR:
            sorunlar.append(f"{t}: {a} → {b}")
    for k in ("fis", "fis_satiri", "hesap_plani_bakiye"):
        if once[k] != sonra[k]:
            sorunlar.append(f"{k} değişti: {once[k]} → {sonra[k]}")
    for kod, deger in once["hesap_bakiyeleri"].items():
        if sonra["hesap_bakiyeleri"].get(kod) != deger:
            sorunlar.append(f"hesap bakiyesi değişti: {kod}")
    for kod in set(sonra["hesap_bakiyeleri"]) - set(once["hesap_bakiyeleri"]):
        if sonra["hesap_bakiyeleri"][kod] != [0.0, 0.0]:
            sorunlar.append(f"yeni hesap sıfır bakiyeli değil: {kod}")
    beklenen_hesap = len(sonuc["eklenen_hesap"])
    if sonra["tablo_sayilari"]["muhasebe_hesap_plani"] - once["tablo_sayilari"]["muhasebe_hesap_plani"] != beklenen_hesap:
        sorunlar.append("hesap planı satır artışı eklenen hesap sayısıyla eşleşmiyor")
    if (sonra["tablo_sayilari"]["muhasebe_hesap_eslemeleri"] - once["tablo_sayilari"]["muhasebe_hesap_eslemeleri"]
            != len(plan["esleme_satiri_ekle"])):
        sorunlar.append("eşleştirme satır artışı beklenenle eşleşmiyor")
    return sorunlar


def motor(db: Path):
    eng = create_engine(f"sqlite:///{db.as_posix()}", connect_args={"timeout": 30})

    @event.listens_for(eng, "connect")
    def _baglan(dbapi, _kayit):
        dbapi.isolation_level = None
        dbapi.execute("PRAGMA foreign_keys=ON")

    @event.listens_for(eng, "begin")
    def _basla(conn):
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    return eng


def firma_bul(baglanti, firma_id: int | None) -> int:
    firmalar = baglanti.execute(text("SELECT id, firma_kodu, unvan FROM firmalar ORDER BY id")).all()
    if firma_id is not None:
        if not any(f[0] == firma_id for f in firmalar):
            raise SystemExit(f"Firma bulunamadı: {firma_id}")
        return firma_id
    if len(firmalar) != 1:
        raise SystemExit(f"Birden çok firma var, --firma-id verin: {firmalar}")
    return int(firmalar[0][0])


def program_acik_mi() -> bool:
    try:
        cikti = subprocess.run(["tasklist", "/FI", "IMAGENAME eq CinMuhasebe.exe"], capture_output=True,
                               text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "CinMuhasebe.exe" in cikti


def calistir(db: Path, firma_id: int | None, *, yaz: bool) -> dict:
    """Tek transaction: öncesi ölçüm → plan → uygula → sonrası ölçüm → karşılaştır → commit/rollback."""
    eng = motor(db)
    try:
        for deneme in range(1, 7):
            try:
                with Session(eng, autoflush=False, expire_on_commit=False) as s:
                    baglanti = s.connection()
                    fid = firma_bul(baglanti, firma_id)
                    once = olcum(baglanti)
                    plan = planla(s, fid)
                    sonuc = uygula(s, fid, plan)
                    sonra = olcum(s.connection())
                    sorunlar = karsilastir(once, sonra, sonuc, plan)
                    if sorunlar or not yaz:
                        s.rollback()
                    else:
                        s.commit()
                    return {"firma_id": fid, "plan": plan, "sonuc": sonuc, "once": once, "sonra": sonra,
                            "sorunlar": sorunlar, "yazildi": bool(yaz and not sorunlar), "deneme": deneme}
            except OperationalError as hata:
                if "locked" not in str(hata) and "busy" not in str(hata):
                    raise
                print(f"Veritabanı kilitli, bekleniyor (deneme {deneme})...")
                time.sleep(5)
        raise SystemExit("Veritabanı kilidi açılmadı; işlem yapılmadı.")
    finally:
        eng.dispose()


def kopya_al(kaynak: Path) -> Path:
    hedef = Path(tempfile.mkdtemp(prefix="ray_esleme_kuru_")) / "muhasebe.db"
    src = sqlite3.connect(f"file:{kaynak.as_posix()}?mode=ro", uri=True, timeout=30)
    dst = sqlite3.connect(hedef)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()
    return hedef


def butunluk(db: Path) -> str:
    c = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=30)
    try:
        return c.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        c.close()


def yedek_al(db: Path):
    from database.gecis_guvenligi import GecisYedekHatasi, dogrulanmis_yedek

    for deneme in range(1, 4):
        try:
            return dogrulanmis_yedek(db, "ray_hesap_esleme_oncesi")
        except GecisYedekHatasi as hata:
            print(f"Yedek doğrulanamadı (deneme {deneme}): {hata}")
            time.sleep(5)
    raise SystemExit("Doğrulanmış yedek alınamadı; işlem yapılmadı.")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", type=Path, default=VARSAYILAN_DB)
    p.add_argument("--firma-id", type=int)
    p.add_argument("--uygula", action="store_true", help="gerçek veritabanına yaz (varsayılan: kuru çalıştırma)")
    a = p.parse_args()
    if program_acik_mi():
        raise SystemExit("CinMuhasebe.exe açık; programı kapatıp tekrar çalıştırın. İşlem yapılmadı.")

    rapor: dict = {"zaman": datetime.now().isoformat(timespec="seconds"), "kaynak_db": str(a.db),
                   "mod": "uygula" if a.uygula else "kuru"}
    if a.uygula:
        yedek = yedek_al(a.db)
        rapor["yedek"] = {"yol": str(yedek.yol), "tablo": len(yedek.tablo_sayilari),
                          "satir": sum(yedek.tablo_sayilari.values()),
                          "dogrulama": "integrity_check ok, tablo satır sayıları kaynakla eşit"}
        print("Yedek:", yedek.yol)
        hedef = a.db
    else:
        hedef = kopya_al(a.db)
        rapor["kopya_db"] = str(hedef)
    rapor["butunluk_once"] = butunluk(hedef)
    if rapor["butunluk_once"] != "ok":
        raise SystemExit(f"integrity_check başarısız: {rapor['butunluk_once']}")
    rapor.update(calistir(hedef, a.firma_id, yaz=True))
    rapor["butunluk_sonra"] = butunluk(hedef)

    CIKTI_KLASORU.mkdir(parents=True, exist_ok=True)
    yol = CIKTI_KLASORU / f"ray_hesap_esleme_tamamla_{'uygulama' if a.uygula else 'kuru'}.json"
    yol.write_text(json.dumps(rapor, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    plan = rapor["plan"]
    print(f"Mod: {rapor['mod']} | hedef: {hedef}")
    print(f"Eklenecek/eklenen hesap: {len(plan['hesap_ekle'])} | bağlanan eşleme: {len(plan['bagla'])} | "
          f"korunan: {len(plan['korunan'])} | kullanıcı kararı: {len(plan['kullanici_karari'])} | "
          f"yeni eşleme satırı: {len(plan['esleme_satiri_ekle'])}")
    for b in plan["bagla"]:
        print(f"  {b['anahtar']}: {b['onceki'] or '-'} → {b['hesap']} {b['ad']}{' (yeni)' if b['yeni_hesap'] else ''}")
    for k in plan["kullanici_karari"]:
        print(f"  KARAR: {k['anahtar']} — {k['neden']}")
    print("Karşılaştırma sorunları:", rapor["sorunlar"] or "yok")
    print("integrity_check:", rapor["butunluk_once"], "→", rapor["butunluk_sonra"])
    print("Yazıldı:", rapor["yazildi"], "| rapor:", yol)
    if rapor["sorunlar"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
