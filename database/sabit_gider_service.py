"""Sabit gider ödeme planları: plan kaydı, aylık dönem üretimi, gerçek evrak bağlantısı ve kalan tutar.

Kurallar
--------
* Plan / dönem kaydı borç, tahsilat, muhasebe fişi veya kasa-banka hareketi oluşturmaz.
* Dönemler yalnız rapor tarihinin ayı ve sonraki iki ay için, etkin planlardan üretilir; anahtar
  plan + yıl + ay olduğundan her yenilemede mükerrer satır oluşmaz. Daha eski aylar otomatik
  üretilmez (geçmiş aylar ödenmemiş sayılmaz); yalnız önceden üretilmiş açık dönemler taşınır.
* Ödeme günü 31 olmayan ayda ayın son günü kabul edilir (yalnız planlama tarihi).
* Tutar değişikliği etkili olduğu aydan başlar; önceki dönemlerin tutarı değişmez.
* Dönem kalanı = tutar − geçerli ödeme bağlantıları − borç belgesine (faturaya) bağlanan kısım.
  Faturaya bağlanan kısım tedarikçi açık borcunda bir kez yer alır; burada yalnız alt kırılım olarak görünür.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from database.access import yazma_zorunlu, yetki_var
from database.database import get_session
from database.models.sabit_gider import (
    BAGLANTI_BORC,
    BAGLANTI_ODEME,
    DONEM_ACIK,
    DONEM_IPTAL,
    KATEGORI_ADLARI,
    PERIYOT_AYLIK,
    PERIYOT_TEK,
    PLAN_AKTIF,
    PLAN_DURDURULDU,
    PLAN_IPTAL,
    SabitGiderBaglanti,
    SabitGiderDonemi,
    SabitGiderPlani,
    SabitGiderTutarDegisikligi,
)
from database.session_manager import oturum

SIFIR = Decimal("0")
KURUS = Decimal("0.01")
URETILEN_AY_SAYISI = 3
TABLOLAR = (
    SabitGiderPlani.__table__,
    SabitGiderTutarDegisikligi.__table__,
    SabitGiderDonemi.__table__,
    SabitGiderBaglanti.__table__,
)
YAZMA_YETKISI = ("finans_duzenleme",)
OKUMA_YETKISI = ("finans_goruntuleme", "finans_duzenleme", "odeme_durumu_goruntuleme")


def _d(v) -> Decimal:
    if v is None or v == "":
        return SIFIR
    return v if isinstance(v, Decimal) else Decimal(str(v).replace(",", "."))


def _q2(v) -> Decimal:
    return _d(v).quantize(KURUS, rounding=ROUND_HALF_UP)


def ay_basi(t: date) -> date:
    return date(t.year, t.month, 1)


def ay_ekle(t: date, n: int) -> date:
    toplam = t.year * 12 + (t.month - 1) + n
    return date(toplam // 12, toplam % 12 + 1, 1)


def ay_sonu(t: date) -> date:
    return date(t.year, t.month, calendar.monthrange(t.year, t.month)[1])


def vade_hesapla(yil: int, ay: int, gun: int) -> date:
    """Ödeme günü ayda yoksa (ör. 31 Şubat) ayın son günü."""
    return date(yil, ay, min(max(int(gun), 1), calendar.monthrange(yil, ay)[1]))


def _kullanici() -> str:
    return oturum.ad_soyad or oturum.kullanici_adi or ""


def _motor():
    import database.database as veritabani

    return getattr(veritabani.company_db, "_engine", None) or veritabani.engine


def tablolar_var(session=None) -> bool:
    try:
        bag = session.connection() if session is not None else _motor()
        ins = inspect(bag)
        return all(ins.has_table(t.name) for t in TABLOLAR)
    except Exception:  # noqa: BLE001
        return False


def schema_hazirla() -> None:
    """Tablolar yoksa oluşturur (yalnız CREATE TABLE); mevcut veride önce doğrulanmış yedek alınır."""
    if tablolar_var():
        return
    import database.database as veritabani

    motor = _motor()

    def calistir() -> None:
        for t in TABLOLAR:
            t.create(bind=motor, checkfirst=True)

    db_yolu = getattr(veritabani.company_db, "_db_path", None)
    if not db_yolu:
        calistir()
        return
    from database.gecis_guvenligi import guvenli_gecis, yedek_onayi

    if yedek_onayi(db_yolu) is not None:
        calistir()
    else:
        guvenli_gecis(db_yolu, calistir, gerekli=True, etiket="sabit_gider_gecis",
                      baglantilari_kapat=lambda: motor.dispose())


def okuma_izni() -> bool:
    return yetki_var(*OKUMA_YETKISI)


# ----------------------------------------------------------------------------- plan
def _ay(deger, alan: str) -> date:
    if isinstance(deger, datetime):
        deger = deger.date()
    if isinstance(deger, date):
        return ay_basi(deger)
    metin = str(deger or "").strip()
    for bicim in ("%m.%Y", "%m/%Y", "%Y-%m", "%d.%m.%Y", "%Y-%m-%d"):
        try:
            return ay_basi(datetime.strptime(metin, bicim).date())
        except ValueError:
            continue
    raise ValueError(f"{alan} AA.YYYY biçiminde olmalıdır.")


def plan_dogrula(veri: dict) -> dict:
    kategori = (veri.get("kategori") or "").strip().upper()
    if kategori not in KATEGORI_ADLARI:
        raise ValueError("Gider türü seçin.")
    ad = (veri.get("ad") or "").strip()
    if not ad:
        raise ValueError("Açıklama / plan adı zorunludur.")
    periyot = (veri.get("periyot") or PERIYOT_AYLIK).strip().upper()
    if periyot not in (PERIYOT_AYLIK, PERIYOT_TEK):
        raise ValueError("Dönem türü Aylık veya Tek seferlik olmalıdır.")
    try:
        gun = int(str(veri.get("odeme_gunu") or "").strip())
    except ValueError as hata:
        raise ValueError("Ödeme günü 1-31 arasında bir sayı olmalıdır.") from hata
    if not 1 <= gun <= 31:
        raise ValueError("Ödeme günü 1-31 arasında olmalıdır.")
    try:
        tutar = _q2(veri.get("tutar"))
    except Exception as hata:  # noqa: BLE001
        raise ValueError("Tutar geçerli bir sayı olmalıdır.") from hata
    if tutar <= 0:
        raise ValueError("Tutar sıfırdan büyük olmalıdır.")
    bas = _ay(veri.get("baslangic_ay"), "Başlangıç ayı")
    bit_ham = veri.get("bitis_ay")
    bit = _ay(bit_ham, "Bitiş ayı") if bit_ham not in (None, "") else None
    if periyot == PERIYOT_TEK:
        bit = bas
    if bit is not None and bit < bas:
        raise ValueError("Bitiş ayı başlangıç ayından önce olamaz.")
    cari_id = veri.get("cari_id")
    return {
        "kategori": kategori, "ad": ad[:150], "periyot": periyot, "odeme_gunu": gun, "tutar": tutar,
        "baslangic_ay": bas, "bitis_ay": bit, "tahmini": bool(veri.get("tahmini")),
        "cari_id": int(cari_id) if cari_id not in (None, "") else None,
        "odeme_hesabi": (veri.get("odeme_hesabi") or "").strip()[:100] or None,
        "aciklama": (veri.get("aciklama") or "").strip()[:500] or None,
    }


def plan_tutari(plan: SabitGiderPlani, yil: int, ay: int) -> tuple[Decimal, bool]:
    """O ayda geçerli tutar ve tahmin işareti (son tutar değişikliği; yoksa planın ilk tutarı)."""
    hedef = date(yil, ay, 1)
    tutar, tahmini = _q2(plan.tutar), bool(plan.tahmini)
    for d in sorted(plan.tutar_gecmisi or [], key=lambda x: (x.gecerli_ay, x.id)):
        if d.gecerli_ay <= hedef:
            tutar, tahmini = _q2(d.tutar), bool(d.tahmini)
    return tutar, tahmini


def _plan_kapsar(plan: SabitGiderPlani, ay: date) -> bool:
    if plan.durum != PLAN_AKTIF:
        return False
    if ay < plan.baslangic_ay:
        return False
    if plan.bitis_ay is not None and ay > plan.bitis_ay:
        return False
    if plan.periyot == PERIYOT_TEK and ay != plan.baslangic_ay:
        return False
    return True


def plan_kaydet(veri: dict, plan_id: int | None = None, *, gecerli_ay=None, bugun: date | None = None) -> int:
    """Yeni plan veya düzenleme. Tutar değişikliği ``gecerli_ay``dan (varsayılan bu ay) itibaren uygulanır."""
    yazma_zorunlu(*YAZMA_YETKISI)
    schema_hazirla()
    v = plan_dogrula(veri)
    bugun = bugun or date.today()
    with get_session() as session:
        if plan_id is None:
            plan = SabitGiderPlani(**v, durum=PLAN_AKTIF, olusturan=_kullanici())
            session.add(plan)
            session.flush()
            return int(plan.id)
        plan = session.get(SabitGiderPlani, int(plan_id))
        if plan is None:
            raise ValueError("Plan bulunamadı.")
        if plan.durum == PLAN_IPTAL:
            raise ValueError("İptal edilmiş plan değiştirilemez.")
        etkin = _ay(gecerli_ay, "Geçerlilik ayı") if gecerli_ay else ay_basi(bugun)
        eski_tutar, eski_tahmin = plan_tutari(plan, etkin.year, etkin.month)
        tutar_degisti = v["tutar"] != eski_tutar or v["tahmini"] != eski_tahmin
        for alan in ("kategori", "ad", "periyot", "odeme_gunu", "baslangic_ay", "bitis_ay", "cari_id",
                     "odeme_hesabi", "aciklama"):
            setattr(plan, alan, v[alan])
        if not plan.tutar_gecmisi and etkin <= plan.baslangic_ay:
            plan.tutar, plan.tahmini = v["tutar"], v["tahmini"]
        elif tutar_degisti:
            session.add(SabitGiderTutarDegisikligi(plan_id=plan.id, gecerli_ay=etkin, tutar=v["tutar"],
                                                   tahmini=v["tahmini"], kullanici=_kullanici()))
        plan.guncelleyen, plan.guncelleme = _kullanici(), datetime.now()
        session.flush()
        session.refresh(plan)
        for donem in plan.donemler:
            if donem.durum != DONEM_ACIK:
                continue
            ay = date(donem.yil, donem.ay, 1)
            if not _plan_kapsar(plan, ay) and not _aktif_baglantilar(session, donem):
                donem.durum, donem.iptal_nedeni = DONEM_IPTAL, "Plan kapsamı değişti"
                continue
            if ay >= etkin:
                donem.tutar, donem.tahmini = plan_tutari(plan, donem.yil, donem.ay)
            if ay >= ay_basi(bugun):
                donem.vade_tarihi = vade_hesapla(donem.yil, donem.ay, plan.odeme_gunu)
        return int(plan.id)


def plan_durdur(plan_id: int, son_ay, neden: str = "") -> None:
    """Plan ``son_ay`` sonrasında üretilmez; o aydan sonraki bağlantısız açık dönemler iptal edilir."""
    yazma_zorunlu(*YAZMA_YETKISI)
    son = _ay(son_ay, "Son ödeme ayı")
    with get_session() as session:
        plan = session.get(SabitGiderPlani, int(plan_id))
        if plan is None:
            raise ValueError("Plan bulunamadı.")
        if son < plan.baslangic_ay:
            raise ValueError("Son ödeme ayı başlangıç ayından önce olamaz.")
        plan.durum, plan.bitis_ay = PLAN_DURDURULDU, son
        plan.guncelleyen, plan.guncelleme = _kullanici(), datetime.now()
        for donem in plan.donemler:
            if donem.durum == DONEM_ACIK and date(donem.yil, donem.ay, 1) > son \
                    and not _aktif_baglantilar(session, donem):
                donem.durum, donem.iptal_nedeni = DONEM_IPTAL, (neden or "Plan durduruldu")[:300]


def plan_iptal(plan_id: int, neden: str, *, bugun: date | None = None) -> None:
    """Plan iptal: bu ay ve sonrasındaki bağlantısız açık dönemler iptal; ödenmiş dönemler korunur."""
    yazma_zorunlu(*YAZMA_YETKISI)
    if not (neden or "").strip():
        raise ValueError("İptal nedeni yazın.")
    bas = ay_basi(bugun or date.today())
    with get_session() as session:
        plan = session.get(SabitGiderPlani, int(plan_id))
        if plan is None:
            raise ValueError("Plan bulunamadı.")
        plan.durum = PLAN_IPTAL
        plan.guncelleyen, plan.guncelleme = _kullanici(), datetime.now()
        for donem in plan.donemler:
            if donem.durum == DONEM_ACIK and date(donem.yil, donem.ay, 1) >= bas \
                    and not _aktif_baglantilar(session, donem):
                donem.durum, donem.iptal_nedeni = DONEM_IPTAL, neden.strip()[:300]


def plan_yeniden_baslat(plan_id: int) -> None:
    yazma_zorunlu(*YAZMA_YETKISI)
    with get_session() as session:
        plan = session.get(SabitGiderPlani, int(plan_id))
        if plan is None:
            raise ValueError("Plan bulunamadı.")
        if plan.durum != PLAN_DURDURULDU:
            raise ValueError("Yalnız durdurulmuş plan yeniden başlatılabilir.")
        plan.durum, plan.bitis_ay = PLAN_AKTIF, None
        plan.guncelleyen, plan.guncelleme = _kullanici(), datetime.now()


# ----------------------------------------------------------------------------- dönem üretimi
def donemleri_uret(bugun: date | None = None) -> int:
    """Etkin planlar için bu ay + sonraki iki ayın dönemlerini (yoksa) oluşturur. Yeni satır sayısı."""
    bugun = bugun or date.today()
    if not tablolar_var():
        return 0
    aylar = [ay_ekle(ay_basi(bugun), i) for i in range(URETILEN_AY_SAYISI)]
    yeni = 0
    with get_session() as session:
        planlar = session.scalars(select(SabitGiderPlani).where(SabitGiderPlani.durum == PLAN_AKTIF)).all()
        mevcut = {(int(p), int(y), int(a)) for p, y, a in session.execute(
            select(SabitGiderDonemi.plan_id, SabitGiderDonemi.yil, SabitGiderDonemi.ay)).all()}
        for plan in planlar:
            for ay in aylar:
                if not _plan_kapsar(plan, ay) or (int(plan.id), ay.year, ay.month) in mevcut:
                    continue
                tutar, tahmini = plan_tutari(plan, ay.year, ay.month)
                session.add(SabitGiderDonemi(
                    plan_id=plan.id, yil=ay.year, ay=ay.month, tutar=tutar, tahmini=tahmini,
                    vade_tarihi=vade_hesapla(ay.year, ay.month, plan.odeme_gunu), durum=DONEM_ACIK))
                yeni += 1
        try:
            session.flush()
        except IntegrityError:
            # Aynı anda başka bir yenileme aynı dönemi yazdıysa (benzersiz anahtar) bu tur boş geçer
            session.rollback()
            return 0
    return yeni


# ----------------------------------------------------------------------------- bağlantı
def _evrak_bilgisi(session, belge_no: str) -> dict | None:
    """Bağlanabilir gerçek evrak: geçerlilik, türü, tutarı, tarihi. Bulunamazsa None."""
    from database.models.alis_faturasi import AlisFaturasi
    from database.models.finans import FinansHareketi, GiderFisi, KasaMakbuzu
    from database.models.hizmet_faturasi import HizmetFaturasi

    bn = (belge_no or "").strip()
    if not bn:
        return None
    m = session.scalar(select(KasaMakbuzu).where(KasaMakbuzu.belge_no == bn))
    if m is not None:
        return {"tur": "Ödeme makbuzu" if m.makbuz_turu == "ODEME" else "Tahsilat makbuzu",
                "gecerli": (m.durum or "") != "IPTAL" and m.makbuz_turu == "ODEME",
                "tutar": _q2(m.tutar), "tarih": m.tarih, "odeme": True}
    g = session.scalar(select(GiderFisi).where(GiderFisi.belge_no == bn))
    if g is not None:
        return {"tur": "Gider fişi", "gecerli": (g.durum or "") != "IPTAL", "tutar": _q2(g.tutar),
                "tarih": g.tarih, "odeme": True}
    h = session.scalar(select(HizmetFaturasi).where(HizmetFaturasi.fatura_no == bn))
    if h is not None:
        return {"tur": "Hizmet (gider) faturası", "gecerli": (h.durum or "") != "İPTAL",
                "tutar": _q2(h.tl_genel_toplam), "tarih": h.fatura_tarihi, "odeme": False}
    a = session.scalar(select(AlisFaturasi).where(AlisFaturasi.fatura_no == bn))
    if a is not None:
        return {"tur": "Alış faturası", "gecerli": (a.durum or "") != "İPTAL" and bool(a.onaylandi),
                "tutar": _q2(a.tl_genel_toplam), "tarih": a.fatura_tarihi, "odeme": False}
    hareketler = session.scalars(select(FinansHareketi).where(FinansHareketi.belge_no == bn)).all()
    cikis = [h for h in hareketler if _finans_cikis_mi(h.hareket_turu)]
    if cikis:
        return {"tur": "Kasa / banka ödemesi", "gecerli": True,
                "tutar": _q2(sum((_d(h.tutar) for h in cikis), SIFIR)), "tarih": min(h.tarih for h in cikis),
                "odeme": True}
    return None


def _finans_cikis_mi(tur: str) -> bool:
    from database.finans_service import FinansService

    return FinansService.hareket_isareti(tur) < 0


def _aktif_baglantilar(session, donem: SabitGiderDonemi, *, tarih: date | None = None,
                       evrak_onbellek: dict | None = None) -> list[tuple[SabitGiderBaglanti, dict]]:
    sonuc = []
    for b in donem.baglantilar or []:
        if b.iptal or (tarih is not None and b.tarih > tarih):
            continue
        if evrak_onbellek is not None and b.belge_no in evrak_onbellek:
            bilgi = evrak_onbellek[b.belge_no]
        else:
            bilgi = _evrak_bilgisi(session, b.belge_no)
            if evrak_onbellek is not None:
                evrak_onbellek[b.belge_no] = bilgi
        if bilgi is None or not bilgi["gecerli"]:
            continue
        sonuc.append((b, bilgi))
    return sonuc


def baglanti_ekle(donem_id: int, belge_no: str, tutar, *, tarih: date | None = None, aciklama: str = "") -> int:
    """Dönemi gerçek evrakla karşılar. Ödeme evrakı kalanı azaltır; fatura bağlantısı planın yerini alır."""
    yazma_zorunlu(*YAZMA_YETKISI)
    tutar = _q2(tutar)
    if tutar <= 0:
        raise ValueError("Bağlantı tutarı sıfırdan büyük olmalıdır.")
    with get_session() as session:
        donem = session.get(SabitGiderDonemi, int(donem_id))
        if donem is None:
            raise ValueError("Dönem bulunamadı.")
        if donem.durum != DONEM_ACIK:
            raise ValueError("İptal edilmiş döneme bağlantı eklenemez.")
        bilgi = _evrak_bilgisi(session, belge_no)
        if bilgi is None:
            raise ValueError(f"Evrak bulunamadı: {belge_no}. Ödeme makbuzu, gider fişi, havale veya fatura no girin.")
        if not bilgi["gecerli"]:
            raise ValueError(f"{belge_no} ({bilgi['tur']}) iptal edilmiş veya ödeme evrakı değil.")
        tur = BAGLANTI_ODEME if bilgi["odeme"] else BAGLANTI_BORC
        ayni_tur = sum((_d(b.tutar) for b, _ in _aktif_baglantilar(session, donem) if b.tur == tur), SIFIR)
        if ayni_tur + tutar > _q2(donem.tutar):
            raise ValueError(
                f"Bağlantı toplamı dönem tutarını aşıyor (dönem {_q2(donem.tutar)} TL, bağlı {ayni_tur} TL). "
                "Tutar değiştiyse önce plan tutarını güncelleyin.")
        bn = (belge_no or "").strip()
        evrakta = sum((_d(b.tutar) for b in session.scalars(select(SabitGiderBaglanti).where(
            SabitGiderBaglanti.belge_no == bn, SabitGiderBaglanti.iptal.is_(False))).all()), SIFIR)
        if evrakta + tutar > bilgi["tutar"]:
            raise ValueError(
                f"{bn} evrakının tutarı {bilgi['tutar']} TL; daha önce {evrakta} TL dağıtılmış. "
                "Aynı evrak dağıtılabilir tutarından fazla bağlanamaz.")
        b = SabitGiderBaglanti(donem_id=donem.id, tur=tur, belge_no=bn, tutar=tutar,
                               tarih=tarih or bilgi["tarih"] or date.today(), aciklama=(aciklama or "")[:300] or None,
                               kullanici=_kullanici())
        session.add(b)
        session.flush()
        return int(b.id)


def baglanti_iptal(baglanti_id: int, neden: str) -> None:
    yazma_zorunlu(*YAZMA_YETKISI)
    if not (neden or "").strip():
        raise ValueError("İptal nedeni yazın.")
    with get_session() as session:
        b = session.get(SabitGiderBaglanti, int(baglanti_id))
        if b is None:
            raise ValueError("Bağlantı bulunamadı.")
        if b.iptal:
            return
        b.iptal, b.iptal_zamani, b.iptal_kullanici = True, datetime.now(), _kullanici()
        b.iptal_nedeni = neden.strip()[:300]


# ----------------------------------------------------------------------------- hesap
def donem_ozeti(session, donem: SabitGiderDonemi, tarih: date, evrak_onbellek: dict | None = None) -> dict:
    aktif = _aktif_baglantilar(session, donem, tarih=tarih, evrak_onbellek=evrak_onbellek)
    odenen = _q2(sum((_d(b.tutar) for b, _ in aktif if b.tur == BAGLANTI_ODEME), SIFIR))
    borca = _q2(sum((_d(b.tutar) for b, _ in aktif if b.tur == BAGLANTI_BORC), SIFIR))
    tutar = _q2(donem.tutar)
    kalan = max(SIFIR, tutar - odenen - borca) if donem.durum == DONEM_ACIK else SIFIR
    plan = donem.plan
    return {
        "donem_id": int(donem.id), "plan_id": int(plan.id), "plan_adi": plan.ad,
        "kategori": plan.kategori, "kategori_adi": KATEGORI_ADLARI.get(plan.kategori, plan.kategori),
        "cari_id": plan.cari_id, "yil": int(donem.yil), "ay": int(donem.ay), "vade": donem.vade_tarihi,
        "tutar": tutar, "odenen": odenen, "faturaya_bagli": borca, "kalan": _q2(kalan),
        "tahmini": bool(donem.tahmini), "durum": donem.durum,
        "baglantilar": [{"id": int(b.id), "tur": b.tur, "belge_no": b.belge_no, "tutar": _q2(b.tutar),
                         "tarih": b.tarih, "evrak_turu": bilgi["tur"]} for b, bilgi in aktif],
    }


def takvim_kalemleri(session, tarih: date) -> list[dict]:
    """Rapor tarihi itibarıyla açık dönemler (taşınan eski açık dönemler dahil). Tablo yoksa boş."""
    if not tablolar_var(session):
        return []
    from sqlalchemy.orm import selectinload

    donemler = session.scalars(
        select(SabitGiderDonemi).where(SabitGiderDonemi.durum == DONEM_ACIK)
        .options(selectinload(SabitGiderDonemi.baglantilar), selectinload(SabitGiderDonemi.plan))
        .order_by(SabitGiderDonemi.vade_tarihi, SabitGiderDonemi.id)).all()
    onbellek: dict = {}
    return [donem_ozeti(session, d, tarih, onbellek) for d in donemler
            if d.olusturma is None or d.olusturma.date() <= max(tarih, date.today())]


def plan_listesi() -> list[dict]:
    if not tablolar_var():
        return []
    with get_session() as session:
        planlar = session.scalars(select(SabitGiderPlani).order_by(SabitGiderPlani.durum,
                                                                   SabitGiderPlani.kategori,
                                                                   SabitGiderPlani.ad)).all()
        bugun = date.today()
        out = []
        for p in planlar:
            tutar, tahmini = plan_tutari(p, bugun.year, bugun.month)
            out.append({
                "id": int(p.id), "kategori": p.kategori, "kategori_adi": KATEGORI_ADLARI.get(p.kategori, p.kategori),
                "ad": p.ad, "periyot": p.periyot, "odeme_gunu": p.odeme_gunu, "baslangic_ay": p.baslangic_ay,
                "bitis_ay": p.bitis_ay, "tutar": tutar, "tahmini": tahmini, "durum": p.durum,
                "cari_id": p.cari_id, "odeme_hesabi": p.odeme_hesabi or "", "aciklama": p.aciklama or "",
                "ilk_tutar": _q2(p.tutar), "ilk_tahmini": bool(p.tahmini),
                "tutar_gecmisi": [(d.gecerli_ay, _q2(d.tutar), bool(d.tahmini)) for d in p.tutar_gecmisi],
            })
        return out


def plan_donemleri(plan_id: int, tarih: date | None = None) -> list[dict]:
    if not tablolar_var():
        return []
    tarih = tarih or date.today()
    with get_session() as session:
        donemler = session.scalars(select(SabitGiderDonemi).where(SabitGiderDonemi.plan_id == int(plan_id))
                                   .order_by(SabitGiderDonemi.yil, SabitGiderDonemi.ay)).all()
        onbellek: dict = {}
        out = []
        for d in donemler:
            oz = donem_ozeti(session, d, tarih, onbellek)
            oz["iptal_nedeni"] = d.iptal_nedeni or ""
            oz["tum_baglantilar"] = [
                {"id": int(b.id), "tur": b.tur, "belge_no": b.belge_no, "tutar": _q2(b.tutar), "tarih": b.tarih,
                 "iptal": bool(b.iptal), "iptal_nedeni": b.iptal_nedeni or "", "kullanici": b.kullanici or ""}
                for b in d.baglantilar]
            out.append(oz)
        return out
