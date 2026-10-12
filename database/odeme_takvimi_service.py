"""Finans → Ödeme Takvimi: bu ay + sonraki üç ayın ödenmemiş kart, kredi taksiti ve ileri tarihli gider borçları.

Kaynaklar (yalnız okunur; ekranı açmak kayıt, ekstre, dönem, hareket veya fiş üretmez)
---------------------------------------------------------------------------------------
* Kredi kartı: her kartın her ekstre dönemi (kart + hesap kesim tarihi) tek satırdır. Tutar = o döneme düşen
  kart harcaması taksitleri − o ekstreye yapılmış geçerli (iptal edilmemiş) ödemeler. Kesim tarihi bugünden
  sonraysa ekstre henüz kesilmemiştir ve satır "Tahmini" etiketlidir; kesilince aynı anahtarla gerçek borç olur.
  Takvim tarihi hesap kesimidir; gecikme son ödeme tarihine göre belirlenir.
* Kredi taksiti: kullandırılmış kredilerin geçerli plan taksitleri; kalan = plan bileşenleri (anapara, faiz,
  BSMV, KKDF, masraflar) − taksite yapılmış geçerli ödemeler. Kapanmış kredi / ödenmiş taksit gelmez.
* Sabit gider, Vergi / SGK: aktif sabit gider planlarının dönemleri. Üretilmiş dönemin kalanı bağlı geçerli
  evraklardan hesaplanır (faturaya bağlanan kısım tedarikçi borcunda izlenir, burada sayılmaz); henüz
  üretilmemiş aylar plan kuralından (ödeme günü, ay sonu kuralı, geçerli tutar) okunur, kayıt açılmaz.
* Borç Çeki, Borç Senedi: çek / senet modülünde verilen (firma) çek ve senetleri; her evrak vade tarihinde ayrı
  satırdır (anahtar evrak kimliği). Kalan = evrakın kalan tutarı (iptal edilmiş ödemeler sayılmaz). Ödenmiş,
  iptal, iade edilmiş evrak gelmez; yön / tür çelişkisi veya tutarsız kalan "Eksik bilgiler"e yazılır.

Tedarikçi açık cari borcu, alacak çek / senetleri, KMH ve müşteri ödeme sözleri kapsam dışıdır.
"""

from __future__ import annotations

import calendar
import weakref
from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import selectinload

from database.database import get_session

SIFIR = Decimal("0")
KURUS = Decimal("0.01")
AY_SAYISI = 4

KAYNAK_KART = "KART"
KAYNAK_KREDI = "KREDI"
KAYNAK_SABIT = "SABIT"

TUR_KART = "Kredi Kartı"
TUR_KREDI = "Kredi Taksiti"
TUR_SABIT = "Sabit Gider"
TUR_VERGI = "Vergi / SGK"
TUR_SIRASI = {TUR_KART: 0, TUR_KREDI: 1, TUR_SABIT: 2, TUR_VERGI: 3}

KAYNAK_CEK_SENET = "CEKSENET"
TUR_BORC_CEKI = "Borç Çeki"
TUR_BORC_SENEDI = "Borç Senedi"
TUR_SIRASI.update({TUR_BORC_CEKI: 4, TUR_BORC_SENEDI: 5})
# Verilen firma evrakı: ödeme yükümlülüğü sürenler / kapananlar (IADE: borç açık hesaba döner, takvim dışı)
CEK_SENET_ACIK = frozenset({"PORTFOYDE", "TEDARIKCIYE_VERILDI", "KISMI_ODENDI", "VADESI_GECTI", "KARSILIKSIZ",
                            "PROTESTO", "HUKUKI_TAKIP"})
CEK_SENET_KAPALI = frozenset({"ODENDI", "IPTAL", "KAPANDI", "YENILENDI", "GERI_ALINDI", "IADE"})

GUN_ADLARI = ("Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar")
AY_ADLARI = ("Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim",
             "Kasım", "Aralık")


def _d(v) -> Decimal:
    if v is None or v == "":
        return SIFIR
    return v if isinstance(v, Decimal) else Decimal(str(v))


def _q2(v) -> Decimal:
    return _d(v).quantize(KURUS, rounding=ROUND_HALF_UP)


def gun_adi(t: date) -> str:
    return GUN_ADLARI[t.weekday()]


def ay_adi(yil: int, ay: int) -> str:
    return f"{AY_ADLARI[ay - 1]} {yil}"


def ay_basi(t: date) -> date:
    return date(t.year, t.month, 1)


def ay_ekle(t: date, n: int) -> date:
    toplam = t.year * 12 + (t.month - 1) + n
    return date(toplam // 12, toplam % 12 + 1, 1)


def ay_sonu(t: date) -> date:
    return date(t.year, t.month, calendar.monthrange(t.year, t.month)[1])


def donem(bugun: date) -> tuple[date, date]:
    """Bugünün ayının ilk günü .. üç ay sonrasının son günü (dört takvim ayı)."""
    bas = ay_basi(bugun)
    return bas, ay_sonu(ay_ekle(bas, AY_SAYISI - 1))


def tutar_metni(v) -> str:
    return f"{_q2(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _kalem(kaynak: str, anahtar: str, tarih: date, tur: str, hesap: str, aciklama: str, kalan: Decimal, *,
           tahmini: bool = False, vade: date | None = None, gecikmis: bool | None = None, **ek) -> dict:
    return {"kaynak": kaynak, "anahtar": anahtar, "tarih": tarih, "gun": gun_adi(tarih), "tur": tur,
            "hesap": hesap, "aciklama": aciklama, "kalan": _q2(kalan), "tahmini": tahmini, "vade": vade,
            "gecikmis": gecikmis, **ek}


def _satir_var(s, tablo: str) -> bool:
    """Tablo yoksa veya boşsa False (eski firma şemasında olmayan kolonlar sorgulanmaz)."""
    if not inspect(s.connection()).has_table(tablo):
        return False
    return bool(s.execute(text(f'SELECT 1 FROM "{tablo}" LIMIT 1')).first())


# ----------------------------------------------------------------------------- kredi kartı
def _kart_kalemleri(s, bugun: date, eksikler: list[dict]) -> list[dict]:
    from database.kredi_karti_ekstre_service import KrediKartiEkstreService as E

    if not _satir_var(s, "kredi_karti_odemeleri"):
        return []
    kalemler = []
    for kid, kv in E.donem_borclari(s).items():
        kart = kv["kart"]
        ad = kart.kart_adi + (f" •••• {kart.son_dort_hane}" if kart.son_dort_hane else "")
        pb = (kart.para_birimi or "TRY").upper()
        for kesim, g in kv["donemler"].items():
            kalan = _q2(g["kalan"])
            if kalan <= 0:
                continue
            if pb not in ("TRY", "TL"):
                eksikler.append({"tur": TUR_KART, "ad": ad, "tutar": kalan,
                                 "neden": f"{pb} kart ekstresi için kur kaydı yok; TL toplamına katılmadı."})
                continue
            son_odeme = g["son_odeme_tarihi"]
            kesin = kesim <= bugun
            if son_odeme is None:
                eksikler.append({"tur": TUR_KART, "ad": ad, "tutar": None, "neden":
                                 f"Son ödeme günü tanımsız; {kesim:%d.%m.%Y} ekstresi takvimde, gecikme belirlenemiyor."})
            detay = [{"belge_no": d["belge_no"], "islem_tarihi": d["islem_tarihi"],
                      "aciklama": ("Kart iadesi" if d["islem_turu"] == "IADE" else d["tek_cekim_taksit"])
                      + (f" — {d['kaynak_gider'] or 'gider'}" if d["gider_kart_odeme_id"] else ""),
                      "tutar": _q2(d["tutar"]), "gider_kart_odeme_id": d["gider_kart_odeme_id"]}
                     for d in g["satirlar"]]
            aciklama = f"{ad} ekstre" + (" — Tahmini" if not kesin else "")
            kalemler.append(_kalem(
                KAYNAK_KART, f"{KAYNAK_KART}:{kid}:{kesim.isoformat()}", kesim, TUR_KART, ad, aciklama, kalan,
                tahmini=not kesin, vade=son_odeme,
                gecikmis=(kesin and son_odeme < bugun) if son_odeme else None,
                kart_id=kid, kesim=kesim, son_odeme=son_odeme, ekstre_id=g["ekstre_id"],
                donem_baslangic=g["donem_baslangic"], toplam=_q2(g["toplam"]),
                odenen=_q2(g["odenen"]), detay=sorted(detay, key=lambda x: x["islem_tarihi"])))
        if kv["belirsiz"] != 0:
            eksikler.append({"tur": TUR_KART, "ad": ad, "tutar": _q2(kv["belirsiz"]),
                             "neden": "Hesap kesim günü tanımsız; ekstre dönemi belirlenemedi. Tutar kart borcunda "
                                      "ve kullanılan limitte sayılır; kesim günü girilince dönemine yerleşir."})
    return kalemler


# ----------------------------------------------------------------------------- kredi taksitleri
def _kredi_kalemleri(s, bugun: date, eksikler: list[dict]) -> list[dict]:
    from database.banka_kredi_service import BILESEN_ALANLARI, BankaKrediService as K
    from database.models.finans import BankaKarti, BankaKredisi

    if not _satir_var(s, "banka_kredileri"):
        return []
    kalemler = []
    for k in s.scalars(select(BankaKredisi).options(selectinload(BankaKredisi.taksitler))
                       .where(BankaKredisi.durum == "KULLANDIRILDI")).all():
        pb = (k.para_birimi or "TRY").upper()
        kur = Decimal("1")
        if pb not in ("TRY", "TL"):
            kur = _d(k.kur)
            if kur <= 0:
                acik = sum((K._taksit_kalan(t) for t in k.taksitler or []), SIFIR)
                eksikler.append({"tur": TUR_KREDI, "ad": k.kredi_adi, "tutar": None,
                                 "neden": f"{pb} kredi için kur kaydı yok; {tutar_metni(acik)} {pb} kalan "
                                          "taksit TL toplamına katılmadı."})
                continue
        banka = s.get(BankaKarti, k.banka_karti_id)
        ad = k.kredi_adi + (f" ({banka.banka_adi})" if banka and banka.banka_adi else "")
        for t in k.taksitler or []:
            kalan = K._taksit_kalan(t)
            if kalan <= 0:
                continue
            if t.vade_tarihi is None:
                eksikler.append({"tur": TUR_KREDI, "ad": f"{ad} taksit {t.taksit_no}", "tutar": _q2(kalan * kur),
                                 "neden": "Taksit vadesi yok."})
                continue
            plan = K.taksit_bilesenleri(t)
            odenmis = K._odenen_bilesenler(s, t.id)
            bilesen = {a: _q2(max(SIFIR, plan.get(a, SIFIR) - odenmis[a]) * kur) for a in BILESEN_ALANLARI}
            aciklama = f"{ad} — taksit {t.taksit_no}/{k.taksit_sayisi}"
            if pb not in ("TRY", "TL"):
                aciklama += f" ({pb}, kayıtlı kur {kur})"
            kalemler.append(_kalem(
                KAYNAK_KREDI, f"{KAYNAK_KREDI}:{int(t.id)}", t.vade_tarihi, TUR_KREDI, ad, aciklama, kalan * kur,
                vade=t.vade_tarihi, gecikmis=t.vade_tarihi < bugun, taksit_id=int(t.id), kredi_id=int(k.id),
                bilesen=bilesen, odenen=_q2(_d(t.odenen_tutar) * kur)))
    return kalemler


# ----------------------------------------------------------------------------- sabit gider / vergi-SGK
def _sabit_kalemleri(s, bugun: date, bas: date, bit: date, eksikler: list[dict], notlar: list[str]) -> list[dict]:
    from database import sabit_gider_service as sg
    from database.models.sabit_gider import (
        DONEM_ACIK,
        PLAN_AKTIF,
        SabitGiderDonemi,
        SabitGiderPlani,
    )

    if not sg.tablolar_var(s):
        return []
    if not sg.okuma_izni():
        notlar.append("Sabit gider planlarını görüntüleme yetkiniz olmadığı için sabit gider / vergi satırları "
                      "gösterilmedi.")
        return []

    def tur(kategori: str) -> str:
        return TUR_VERGI if kategori == "SGK_VERGI" else TUR_SABIT

    kalemler = []
    mevcut: set[tuple[int, int, int]] = set()
    onbellek: dict = {}
    for d in s.scalars(select(SabitGiderDonemi).options(selectinload(SabitGiderDonemi.baglantilar),
                                                        selectinload(SabitGiderDonemi.plan))).all():
        mevcut.add((int(d.plan_id), int(d.yil), int(d.ay)))
        if d.durum != DONEM_ACIK:
            continue
        oz = sg.donem_ozeti(s, d, date.max, onbellek)
        if oz["kalan"] <= 0:
            continue
        plan = d.plan
        kalemler.append(_kalem(
            KAYNAK_SABIT, f"{KAYNAK_SABIT}:{plan.id}:{d.yil}-{d.ay:02d}", d.vade_tarihi, tur(plan.kategori),
            plan.ad, f"{plan.ad} — {oz['kategori_adi']} {d.ay:02d}.{d.yil}" + (" — Tahmini tutar" if d.tahmini else ""),
            oz["kalan"], tahmini=bool(d.tahmini), vade=d.vade_tarihi, gecikmis=d.vade_tarihi < bugun,
            plan_id=int(plan.id), yil=int(d.yil), ay=int(d.ay), donem_id=int(d.id), toplam=oz["tutar"],
            odenen=oz["odenen"], faturaya_bagli=oz["faturaya_bagli"], kategori_adi=oz["kategori_adi"]))
    aylar = [ay_ekle(bas, i) for i in range(AY_SAYISI)]
    for plan in s.scalars(select(SabitGiderPlani).options(selectinload(SabitGiderPlani.tutar_gecmisi))
                          .where(SabitGiderPlani.durum == PLAN_AKTIF)).all():
        for ay in aylar:
            if not sg._plan_kapsar(plan, ay) or (int(plan.id), ay.year, ay.month) in mevcut:
                continue
            tutar, tahmini = sg.plan_tutari(plan, ay.year, ay.month)
            vade = sg.vade_hesapla(ay.year, ay.month, plan.odeme_gunu)
            kategori_adi = sg.KATEGORI_ADLARI.get(plan.kategori, plan.kategori)
            if tutar <= 0:
                eksikler.append({"tur": tur(plan.kategori), "ad": f"{plan.ad} {ay.month:02d}.{ay.year}",
                                 "tutar": None, "neden": "Planda bu ay için tutar yok."})
                continue
            kalemler.append(_kalem(
                KAYNAK_SABIT, f"{KAYNAK_SABIT}:{plan.id}:{ay.year}-{ay.month:02d}", vade, tur(plan.kategori),
                plan.ad, f"{plan.ad} — {kategori_adi} {ay.month:02d}.{ay.year}"
                + (" — Tahmini tutar" if tahmini else ""), tutar, tahmini=tahmini, vade=vade,
                gecikmis=vade < bugun, plan_id=int(plan.id), yil=ay.year, ay=ay.month, donem_id=None,
                toplam=tutar, odenen=SIFIR, faturaya_bagli=SIFIR, kategori_adi=kategori_adi))
    return [k for k in kalemler if k["tarih"] <= bit]


# ----------------------------------------------------------------------------- borç çek / senet
def _cek_senet_kalemleri(s, bugun: date, eksikler: list[dict]) -> list[dict]:
    """Verilen firma çek / senetleri; yön + evrak türü + durumdan sınıflanır (açıklama veya cariden tahmin yok)."""
    from database.donen_sermaye_service import _odeme_iptal_gunleri
    from database.models.cek_senet import DURUM_ETIKETLERI, CekSenetEvrak

    if not _satir_var(s, CekSenetEvrak.__tablename__):
        return []
    odeme_gunu, iptal_gunu = _odeme_iptal_gunleri(s)
    kalemler = []
    for e in s.scalars(select(CekSenetEvrak).options(selectinload(CekSenetEvrak.cari),
                                                     selectinload(CekSenetEvrak.hareketler))
                       .where(CekSenetEvrak.aktif.is_(True))).all():
        yon, tur, durum = (e.islem_yonu or "").upper(), (e.evrak_turu or "").upper(), (e.durum or "").upper()
        cek = tur.endswith("CEKI")
        kalan = _q2(e.kalan_tutar)
        ad = f"#{e.id} {e.portfoy_no or ''} / {e.evrak_no or ''}".strip()
        if yon == "ALINAN" and tur.startswith("MUSTERI"):
            continue
        if durum in CEK_SENET_KAPALI or kalan <= 0:
            continue
        tur_adi = TUR_BORC_CEKI if cek else TUR_BORC_SENEDI
        if yon == "VERILEN" and tur.startswith("MUSTERI"):
            eksikler.append({"tur": "Çek / senet", "ad": ad, "tutar": kalan, "neden":
                             "Verilen olarak kayıtlı müşteri evrakı (ciro olabilir); firmanın borç evrakı olup "
                             "olmadığı belirsiz, toplama katılmadı."})
            continue
        if yon == "ALINAN" and tur.startswith("FIRMA"):
            if durum in ("TAHSIL_EDILDI",):
                continue
            eksikler.append({"tur": "Çek / senet", "ad": ad, "tutar": kalan, "neden":
                             "Alınan olarak kayıtlı firma evrakı; borç mu alacak mı belirsiz, toplama katılmadı."})
            continue
        if yon != "VERILEN" or not tur.startswith("FIRMA"):
            eksikler.append({"tur": "Çek / senet", "ad": ad, "tutar": kalan,
                             "neden": f"Evrak yönü / türü tanımsız ({yon or '—'} / {tur or '—'})."})
            continue
        if durum not in CEK_SENET_ACIK:
            eksikler.append({"tur": tur_adi, "ad": ad, "tutar": kalan, "neden":
                             f"Evrak durumu ({DURUM_ETIKETLERI.get(durum, durum or '—')}) borç için belirsiz; "
                             "toplama katılmadı."})
            continue
        toplam = _q2(e.tl_tutari)
        if toplam <= 0 or e.vade_tarihi is None:
            eksikler.append({"tur": tur_adi, "ad": ad, "tutar": kalan if toplam > 0 else None,
                             "neden": "Evrak tutarı yok." if toplam <= 0 else "Vade tarihi yok."})
            continue
        odemeler = [h for h in e.hareketler or [] if (h.islem_turu or "").upper() in ("ODEME", "KISMI_ODEME")]
        gecerli = [h for h in odemeler if h.id not in iptal_gunu]
        odenen = _q2(sum((_d(h.tutar) for h in gecerli), SIFIR))
        if _q2(toplam - odenen) != kalan:
            eksikler.append({"tur": tur_adi, "ad": ad, "tutar": kalan, "neden":
                             f"Kalan tutar ({tutar_metni(kalan)}) evrak tutarı − geçerli ödemelerle "
                             f"({tutar_metni(toplam - odenen)}) uyuşmuyor; toplama katılmadı."})
            continue
        unvan = (e.cari.unvan if e.cari is not None else "") or "Alacaklı tanımsız"
        banka = " ".join(p for p in (e.banka_adi, e.banka_subesi, e.hesap_no or e.iban) if p) if cek else ""
        aciklama = f"{e.evrak_no} • {unvan}" + (f" • {banka}" if banka else "")
        doviz = (e.doviz_turu or "TL").upper()
        kalemler.append(_kalem(
            KAYNAK_CEK_SENET, f"{KAYNAK_CEK_SENET}:{int(e.id)}", e.vade_tarihi, tur_adi, unvan, aciklama, kalan,
            vade=e.vade_tarihi, gecikmis=e.vade_tarihi < bugun, evrak_id=int(e.id), portfoy_no=e.portfoy_no,
            evrak_no=e.evrak_no, durum=durum, durum_etiket=DURUM_ETIKETLERI.get(durum, durum),
            duzenleme=e.duzenleme_tarihi, toplam=toplam, odenen=odenen, banka=banka, iban=e.iban,
            banka_hesabi_id=e.banka_hesabi_id,
            doviz=None if doviz in ("TL", "TRY") else f"{tutar_metni(e.doviz_tutari)} {doviz} (kur {e.kur})",
            odemeler=[{"tarih": odeme_gunu.get(h.id) or h.tarih.date(), "tutar": _q2(h.tutar),
                       "iptal": h.id in iptal_gunu} for h in sorted(odemeler, key=lambda h: h.id)]))
    return kalemler


# ----------------------------------------------------------------------------- ana hesap
def sirala(kalemler: list[dict]) -> list[dict]:
    return sorted(kalemler, key=lambda k: (k["tarih"], TUR_SIRASI.get(k["tur"], 9), k["hesap"], k["anahtar"]))


_SEMA_HAZIR: "weakref.WeakSet" = weakref.WeakSet()


def _sema_hazirla(eksikler: list[dict]) -> None:
    """Kaynak modüllerin sürümlü geçişleri (yedekli). Firma açılışında yapılmamış olsa da takvim eski şemayı okumaz."""
    import database.database as vt

    motor = getattr(vt.company_db, "_engine", None) or vt.engine
    if motor is None or motor in _SEMA_HAZIR:
        return
    from database.banka_kredi_service import BankaKrediService
    from database.cek_senet_service import CekSenetService
    from database.kredi_karti_ekstre_service import KrediKartiEkstreService

    tamam = True
    for ad, fn in (("Kredi kartı", KrediKartiEkstreService.schema_hazirla),
                   ("Kredi taksitleri", BankaKrediService.schema_hazirla),
                   ("Borç çek / senet", CekSenetService.schema_hazirla)):
        try:
            fn()
        except Exception as hata:  # noqa: BLE001
            tamam = False
            eksikler.append({"tur": ad, "ad": ad, "tutar": None,
                             "neden": f"Veritabanı güncellemesi tamamlanamadı; programı yeniden açın: {hata}"})
    if tamam:
        _SEMA_HAZIR.add(motor)


def hesapla(bugun: date | None = None) -> dict:
    """Dört aylık takvim: aylar (satırlar + ara toplam), geçmişten kalanlar, eksik bilgiler, notlar."""
    from database.donen_sermaye_service import degisim_sayaci

    bugun = bugun or date.today()
    bas, bit = donem(bugun)
    eksikler: list[dict] = []
    _sema_hazirla(eksikler)
    sayac = degisim_sayaci()
    notlar: list[str] = []
    uyarilar: list[str] = []
    kalemler: list[dict] = []
    with get_session() as s:
        for ad, fn in (("Kredi kartı", lambda: _kart_kalemleri(s, bugun, eksikler)),
                       ("Kredi taksitleri", lambda: _kredi_kalemleri(s, bugun, eksikler)),
                       ("Sabit gider / vergi", lambda: _sabit_kalemleri(s, bugun, bas, bit, eksikler, notlar)),
                       ("Borç çek / senet", lambda: _cek_senet_kalemleri(s, bugun, eksikler))):
            try:
                kalemler += fn()
            except Exception as hata:  # noqa: BLE001
                eksikler.append({"tur": ad, "ad": ad, "tutar": None, "neden": f"Kaynak okunamadı: {hata}"})
    gecmis = sirala([k for k in kalemler if k["tarih"] < bas])
    aylar = []
    for i in range(AY_SAYISI):
        a = ay_ekle(bas, i)
        sec = sirala([k for k in kalemler if a <= k["tarih"] <= ay_sonu(a)])
        aylar.append({"yil": a.year, "ay": a.month, "ad": ay_adi(a.year, a.month), "kalemler": sec,
                      "toplam": _q2(sum((k["kalan"] for k in sec), SIFIR)),
                      "tahmini_var": any(k["tahmini"] for k in sec)})
    if any(k["tahmini"] for k in kalemler if k["kaynak"] == KAYNAK_KART and bas <= k["tarih"] <= bit):
        notlar.append("Ay toplamları henüz kesilmemiş kart ekstrelerinin tahmini tutarlarını içerir (mevcut kart "
                      "harcamaları ve taksitleri; gelecek harcama veya faiz eklenmez).")
    if any(k["tahmini"] for k in kalemler if k["kaynak"] == KAYNAK_SABIT):
        notlar.append("Bazı sabit gider tutarları planda 'tahmini' işaretli.")
    notlar.append("Tedarikçi açık cari borcu, alacak çek / senetleri, KMH ve müşteri ödeme sözleri bu takvime "
                  "alınmaz.")
    if eksikler:
        uyarilar.append(f"{len(eksikler)} kayıtta eksik bilgi var; toplamlar bu kayıtları içermediği için eksiktir.")
    return {
        "bugun": bugun, "baslangic": bas, "bitis": bit, "aylar": aylar,
        "genel_toplam": _q2(sum((a["toplam"] for a in aylar), SIFIR)),
        "gecmis": gecmis, "gecmis_toplam": _q2(sum((k["kalan"] for k in gecmis), SIFIR)),
        "eksikler": eksikler, "notlar": notlar, "uyarilar": uyarilar, "sayac": sayac,
        "toplam_eksik": bool(eksikler),
    }
