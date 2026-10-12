"""Giderlerin şirket kredi kartıyla tek çekim veya taksitle ödenmesi.

Kurallar
--------
* Kayıt tek işlemdir: gider fişi (kart hesabına, kasa/banka çıkışı yok) + kart ödemesi ve taksit planı (her taksit
  bankanın ekstre kesimine yazılır) + varsa ayrı ücret kaydı + sabit gider dönemi bağlantısı. Hata olursa hiçbiri
  kalmaz. Aynı istek anahtarıyla tekrar kayıt yeni satır üretmez.
* Gider borcu yalnız ``gider_tutari`` kadar kapanır. Kart borcu (``kart_toplami``) ekstre ödemesiyle kapanır; kasa/banka
  çıkışı yalnız ekstre ödemesinde oluşur.
* Finansman farkı (kart toplamı − gider tutarı) ana kart ödemesinin muhasebe fişinde bir kez işlenir (780).
* Hatalı kayıt iptali: taksit/ekstre ödenmemişse gider fişi, kart ödemesi ve bağlantı birlikte geri alınır; kayıtlar
  silinmez, iptal ve ters hareket görünür kalır.
* Kayıt düzeltmesi (hatalı tutar / kart / taksit bilgisi) iade değildir, iade kaydı üretmez. Hiçbir taksit ve ekstre
  ödemesi yoksa (TAM) eski kart kayıtları DÜZELTİLDİ olur, düzeltme gününe ters hareket ve düzeltilmiş kayıt yazılır.
  Ödenmiş dönem varsa (ACIK_DONEM) o dönemler yeniden yazılmaz: açık dönemlerin ters satırları ve kapanmış dönem
  farkları ilk açık döneme ayrı bir düzeltme kaydıyla yazılır. Eski / yeni değer, neden, kullanıcı ve zaman
  ``gider_kart_duzeltmeleri`` günlüğünde kalır.
* Banka iadesi yalnız gerçekleşmiş iade içindir: iade tarihinin ekstresine eksi tutar yazılır; gider (ana para), faiz
  ve ayrı ücret payı ayrı tutulur ve ilgili kart kayıtlarına bağlanır. Gider kalanı yalnız ana para iadesiyle açılır;
  iade edilen faiz / ücret 780 etkisini bir kez ters çevirir; iade edilmeyen masraf olduğu gibi kalır.
"""

from __future__ import annotations

import json
import weakref
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from database.access import yazma_zorunlu
from database.database import get_session
from database.models.finans import (
    KK_MAX_TAKSIT,
    FinansHareketi,
    FinansHesabi,
    GiderFisi,
    GiderKartDuzeltme,
    GiderKartIade,
    GiderKartOdeme,
    KrediKartiEkstre,
    KrediKartiEkstreOdeme,
    KrediKartiOdeme,
    KrediKartiOdemeTaksit,
    KrediKartiTanimi,
)

SIFIR = Decimal("0")
KURUS = Decimal("0.01")
KAYNAK_SABIT = "SABIT"
KAYNAK_GIDER_FISI = "GIDER_FISI"
FAIZSIZ = "FAIZSIZ"
FAIZ_GIRILDI = "GIRILDI"
YAZMA_YETKISI = ("finans_duzenleme",)
GUN_ADLARI = ("Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar")
GECIS_MODULU = "gider_kart_odeme"
GECIS_SURUMU = 2
DUZELTME_TAM = "TAM"
DUZELTME_ACIK_DONEM = "ACIK_DONEM"
DUZELTILDI = "DÜZELTİLDİ"
HAREKET_DUZELTME_AZALIS = "KK ÖDEME DÜZELTME"
HAREKET_DUZELTME_ARTIS = "KK ÖDEME DÜZELTME EK"
UCRET_AYNI = object()


def _d(v) -> Decimal:
    if v is None or v == "":
        return SIFIR
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v).strip().replace(",", "."))
    except InvalidOperation as hata:
        raise ValueError(f"Geçersiz tutar: {v}") from hata


def _q2(v) -> Decimal:
    return _d(v).quantize(KURUS, rounding=ROUND_HALF_UP)


def _kurus_tam(v, alan: str) -> Decimal:
    """Kullanıcının/bankanın tutarı yeniden yuvarlanmaz: kuruştan küçük basamak varsa hata."""
    d = _d(v)
    if d != d.quantize(KURUS):
        raise ValueError(f"{alan} en çok iki ondalık (kuruş) içerebilir: {v}")
    return d.quantize(KURUS)


def gun_adi(t: date) -> str:
    return GUN_ADLARI[t.weekday()]


def _kullanici() -> str:
    from database.session_manager import oturum

    return oturum.ad_soyad or oturum.kullanici_adi or ""


# ----------------------------------------------------------------------------- şema
_HAZIR: "weakref.WeakSet" = weakref.WeakSet()


def _motor():
    import database.database as veritabani

    return getattr(veritabani.company_db, "_engine", None) or veritabani.engine


def _eksik_var(motor) -> bool:
    ins = inspect(motor)
    for tablo in (GiderKartOdeme.__tablename__, GiderKartDuzeltme.__tablename__, GiderKartIade.__tablename__):
        if not ins.has_table(tablo):
            return True
    for tablo, kolon in (("kredi_karti_odemeleri", "kaynak_turu"), ("kredi_karti_odemeleri", "gider_kart_odeme_id"),
                         ("kredi_karti_odemeleri", "finansman_farki"), ("kredi_karti_odemeleri", "duzeltme_id"),
                         ("kredi_karti_odeme_taksitleri", "ekstre_kesim_tarihi")):
        if ins.has_table(tablo) and kolon not in {c["name"] for c in ins.get_columns(tablo)}:
            return True
    return False


def _gecis_v1(e) -> None:
    from sqlalchemy import text

    from database.modul_sema import eksik_kolonlari_ekle

    eksik_kolonlari_ekle(e, "kredi_karti_odemeleri", {
        "kaynak_turu": "VARCHAR(20) NOT NULL DEFAULT 'CARI'",
        "gider_kart_odeme_id": "INTEGER",
    })
    eksik_kolonlari_ekle(e, "kredi_karti_odeme_taksitleri", {"ekstre_kesim_tarihi": "DATE"})
    GiderKartOdeme.__table__.create(e, checkfirst=True)
    if inspect(e).has_table("kredi_karti_odemeleri"):
        with e.begin() as b:
            b.execute(text('CREATE INDEX IF NOT EXISTS "ix_kredi_karti_odemeleri_gider_kart_odeme_id" '
                           'ON "kredi_karti_odemeleri" ("gider_kart_odeme_id")'))


def _gecis_v2(e) -> None:
    """v1 + kayıt düzeltmesi günlüğü, iade kırılımı ve kart kaydına finansman farkı / düzeltme bağı (yalnız ekler)."""
    from sqlalchemy import text

    from database.modul_sema import eksik_kolonlari_ekle

    _gecis_v1(e)
    eksik_kolonlari_ekle(e, "kredi_karti_odemeleri", {"finansman_farki": "NUMERIC(18, 2)", "duzeltme_id": "INTEGER"})
    GiderKartDuzeltme.__table__.create(e, checkfirst=True)
    GiderKartIade.__table__.create(e, checkfirst=True)
    if inspect(e).has_table("kredi_karti_odemeleri"):
        with e.begin() as b:
            b.execute(text('CREATE INDEX IF NOT EXISTS "ix_kredi_karti_odemeleri_duzeltme_id" '
                           'ON "kredi_karti_odemeleri" ("duzeltme_id")'))


def schema_hazirla(motor=None) -> None:
    """Sürümlü, yalnız ekleyen geçiş: kart ödemesine kaynak türü ve gider bağlantısı, taksite ekstre kesimi,
    gider kart ödemesi tablosu (v1); düzeltme günlüğü, iade kırılımı, kart kaydında finansman farkı ve düzeltme bağı
    (v2). Mevcut satırlar değişmez (kaynak türü CARI, kesim / fark boş = eski kural).

    Veri içeren firmada geçiş gerekiyorsa önce doğrulanmış yedek alınır (açılış geçişinde alınmışsa yeniden alınmaz).
    """
    motor = motor or _motor()
    if motor is None or motor in _HAZIR:
        return
    from database.modul_sema import surum_uygula

    if not inspect(motor).has_table("kredi_karti_odemeleri"):
        _HAZIR.add(motor)
        return
    if _eksik_var(motor):
        import database.database as veritabani

        db_yolu = getattr(veritabani.company_db, "_db_path", None) if motor is _motor() else None
        if db_yolu:
            from database.gecis_guvenligi import guvenli_gecis, yedek_onayi

            if yedek_onayi(db_yolu) is None:
                guvenli_gecis(db_yolu, lambda: surum_uygula(motor, GECIS_MODULU, GECIS_SURUMU, _gecis_v2),
                              gerekli=True, etiket="gider_kart_gecis", baglantilari_kapat=lambda: motor.dispose())
                _HAZIR.add(motor)
                _kart_bakiye_semasi(motor)
                return
    surum_uygula(motor, GECIS_MODULU, GECIS_SURUMU, _gecis_v2)
    _HAZIR.add(motor)
    _kart_bakiye_semasi(motor)


def _kart_bakiye_semasi(motor) -> None:
    from database.kart_bakiye_gecis import schema_hazirla as kart_bakiye_schema_hazirla

    kart_bakiye_schema_hazirla(motor)


# ----------------------------------------------------------------------------- bağlantı sorguları
def fis_karta_bagli_mi(session, gider_fisi_id: int) -> bool:
    if not inspect(session.connection()).has_table(GiderKartOdeme.__tablename__):
        return False
    return session.scalar(select(GiderKartOdeme.id).where(
        GiderKartOdeme.gider_fisi_id == int(gider_fisi_id), GiderKartOdeme.durum == "AÇIK").limit(1)) is not None


def evrak_karta_bagli_mi(session, belge_no: str) -> bool:
    """Belge (gider fişi veya kart ödemesi) geçerli bir kartla gider ödemesine ait mi."""
    bn = (belge_no or "").strip()
    if not bn or not inspect(session.connection()).has_table(GiderKartOdeme.__tablename__):
        return False
    fis_id = session.scalar(select(GiderFisi.id).where(GiderFisi.belge_no == bn))
    if fis_id is not None and fis_karta_bagli_mi(session, int(fis_id)):
        return True
    gko_id = session.scalar(select(KrediKartiOdeme.gider_kart_odeme_id).where(KrediKartiOdeme.belge_no == bn))
    return bool(gko_id) and session.scalar(select(GiderKartOdeme.id).where(
        GiderKartOdeme.id == int(gko_id), GiderKartOdeme.durum == "AÇIK")) is not None


def kaynak_metinleri(session, ids) -> dict[int, str]:
    """Ekstre / takvim ayrıntısı için kaynak gider: gider fişi no + plan ve dönem veya hizmet."""
    from database.models.hizmet import HizmetKarti
    from database.models.sabit_gider import SabitGiderDonemi

    sonuc: dict[int, str] = {}
    ids = [int(i) for i in ids if i]
    if not ids:
        return sonuc
    for g in session.scalars(select(GiderKartOdeme).where(GiderKartOdeme.id.in_(ids))).all():
        fis = session.get(GiderFisi, int(g.gider_fisi_id))
        parca = [f"Gider {fis.belge_no}" if fis else "Gider"]
        donem = session.get(SabitGiderDonemi, int(g.sabit_donem_id)) if g.sabit_donem_id else None
        if donem is not None and donem.plan is not None:
            parca.append(f"{donem.plan.ad} {donem.ay:02d}.{donem.yil}")
        elif fis is not None and fis.hizmet_id:
            h = session.get(HizmetKarti, int(fis.hizmet_id))
            if h is not None:
                parca.append(h.hizmet_adi)
        if g.durum != "AÇIK":
            parca.append("iptal")
        sonuc[int(g.id)] = " · ".join(parca)
    return sonuc


# ----------------------------------------------------------------------------- kart ve plan
def kartlar() -> list[dict]:
    """Seçili firmanın aktif kredi kartları ve kesim / son ödeme bilgileri."""
    with get_session() as s:
        return [kart_ozeti(k) for k in s.scalars(
            select(KrediKartiTanimi).where(KrediKartiTanimi.aktif.is_(True)).order_by(KrediKartiTanimi.kart_adi)).all()]


def kart_ozeti(k: KrediKartiTanimi) -> dict:
    son_bilinir = k.son_odeme_gunu is not None or k.kesimden_sonra_odeme_gun not in (None, "")
    uyarilar = []
    if not k.hesap_kesim_gunu:
        uyarilar.append("Kartın hesap kesim günü tanımsız: kayıt yapılabilir, borç kart bakiyesine ve limite girer; "
                        "ekstre dönemi belirlenemediği için ödeme takviminde 'Eksik bilgiler' altında gösterilir. "
                        "Kesim günü kart tanımına girilince dönemler kendiliğinden belirlenir.")
    if not son_bilinir:
        uyarilar.append("Kartın son ödeme günü tanımsız: kayıt yapılabilir, ödeme takviminde 'Eksik bilgiler' "
                        "altında gösterilir ve gecikme belirlenemez.")
    ad = k.kart_adi + (f" •••• {k.son_dort_hane}" if k.son_dort_hane else "")
    return {"id": int(k.id), "ad": ad, "kesim_gunu": k.hesap_kesim_gunu, "son_odeme_gunu": k.son_odeme_gunu,
            "kesimden_sonra_odeme_gun": k.kesimden_sonra_odeme_gun, "son_odeme_bilinir": son_bilinir,
            "kesim_tanimli": bool(k.hesap_kesim_gunu), "uyarilar": uyarilar,
            "limit": _q2(k.kart_limiti or 0), "para_birimi": (k.para_birimi or "TRY").upper()}


def _kart_al(session, kredi_karti_id) -> KrediKartiTanimi:
    kart = session.get(KrediKartiTanimi, int(kredi_karti_id)) if kredi_karti_id else None
    if kart is None or not kart.aktif:
        raise ValueError("Kredi kartı seçin (firmanın geçerli kartlarından).")
    if (kart.para_birimi or "TRY").upper() not in ("TRY", "TL"):
        raise ValueError(f"{kart.kart_adi} {kart.para_birimi} kartıdır; gider kart ödemesi yalnız TL kartla yapılır.")
    return kart


def donem_satiri(kart, kesim: date | None) -> dict:
    from database.kredi_karti_ekstre_service import KrediKartiEkstreService as E

    if kesim is None:
        return {"kesim": None, "gun": "", "donem_baslangic": None, "son_odeme": None}
    d = E.kesim_donemi(kesim, kart)
    return {"kesim": kesim, "gun": gun_adi(kesim), "donem_baslangic": d["donem_baslangic"],
            "son_odeme": d["son_odeme_tarihi"]}


def ilk_kesim_secenekleri(kredi_karti_id: int, islem_tarihi: date, adet: int = 4) -> list[dict]:
    from database.kredi_karti_ekstre_service import KrediKartiEkstreService as E

    with get_session() as s:
        kart = _kart_al(s, kredi_karti_id)
        return [donem_satiri(kart, k) for k in E.ilk_kesim_secenekleri(kart, islem_tarihi, adet)]


def esit_taslak(kredi_karti_id: int, ilk_kesim: date | None, taksit_sayisi: int, toplam) -> list[dict]:
    """Eşit taksit taslağı: her taksit sonraki kesime; kuruş farkı son taksitte. Kullanıcı kayıttan önce doğrular.

    Kartın kesim günü tanımsızsa kesimler boş kalır (dönem, gün girilince çekim tarihi + taksit sırasından bulunur).
    """
    from database.kredi_karti_ekstre_service import KrediKartiEkstreService as E

    n = int(taksit_sayisi)
    if n < 1 or n > KK_MAX_TAKSIT:
        raise ValueError(f"Taksit sayısı 1-{KK_MAX_TAKSIT} arasında olmalıdır.")
    toplam = _kurus_tam(toplam, "Karta yansıyacak toplam")
    if toplam <= 0:
        raise ValueError("Karta yansıyacak toplam sıfırdan büyük olmalıdır.")
    birim = (toplam / n).quantize(KURUS, rounding=ROUND_HALF_UP)
    with get_session() as s:
        kart = _kart_al(s, kredi_karti_id)
        satirlar, biriken = [], SIFIR
        for i in range(1, n + 1):
            tutar = toplam - biriken if i == n else birim
            biriken += tutar
            kesim = (E.kesim_ay_sonra(ilk_kesim, i - 1, kart)
                     if ilk_kesim is not None and E.kesim_gunu(kart) is not None else None)
            satir = donem_satiri(kart, kesim)
            satir.update({"taksit_no": i, "tutar": tutar})
            satirlar.append(satir)
        return satirlar


def plan_dogrula(kart, islem_tarihi: date, plan: list[dict]) -> list[dict]:
    """Banka planı satırları: geçerli kesim tarihleri, ilk dönem işlemin döneminden önce değil, artan sıra, tutar > 0.

    Kartın kesim günü tanımsızsa kesim girilmez (boş kalır); yalnız tutarlar denetlenir.
    """
    from database.kredi_karti_ekstre_service import KrediKartiEkstreService as E

    if not plan:
        raise ValueError("Taksit planı boş.")
    if len(plan) > KK_MAX_TAKSIT:
        raise ValueError(f"Taksit sayısı en çok {KK_MAX_TAKSIT} olabilir.")
    if E.kesim_gunu(kart) is None:
        sonuc = []
        for i, satir in enumerate(plan, 1):
            if satir.get("kesim") is not None:
                raise ValueError(f"{kart.kart_adi}: hesap kesim günü tanımsız; taksitlere kesim tarihi girilemez. "
                                 "Kesim günü kart tanımına girilince dönemler kendiliğinden belirlenir.")
            tutar = _kurus_tam(satir.get("tutar"), f"{i}. taksit tutarı")
            if tutar <= 0:
                raise ValueError(f"{i}. taksit tutarı eksik veya sıfır.")
            sonuc.append({"taksit_no": i, "kesim": None, "tutar": tutar})
        return sonuc
    ilk_olasi = E.donem_bilgisi(islem_tarihi, kart)["kesim_tarihi"]
    sonuc, onceki = [], None
    for i, satir in enumerate(plan, 1):
        kesim = satir.get("kesim")
        if not isinstance(kesim, date):
            raise ValueError(f"{i}. taksitin ekstre kesim tarihi eksik.")
        if not E.kesim_gecerli_mi(kesim, kart):
            raise ValueError(f"{i}. taksit: {kesim:%d.%m.%Y} kartın hesap kesim günü değil "
                             f"(kesim günü {kart.hesap_kesim_gunu}).")
        if kesim < ilk_olasi:
            raise ValueError(f"{i}. taksit: {kesim:%d.%m.%Y} ekstresi işlem tarihinden önce kesilmiş; işlem en erken "
                             f"{ilk_olasi:%d.%m.%Y} ekstresine girer.")
        if onceki is not None and kesim <= onceki:
            raise ValueError(f"{i}. taksitin ekstre dönemi bir öncekinden sonra olmalıdır.")
        tutar = _kurus_tam(satir.get("tutar"), f"{i}. taksit tutarı")
        if tutar <= 0:
            raise ValueError(f"{i}. taksit tutarı eksik veya sıfır.")
        sonuc.append({"taksit_no": i, "kesim": kesim, "tutar": tutar})
        onceki = kesim
    return sonuc


def _limit_kontrol(session, kart: KrediKartiTanimi, ek: Decimal) -> None:
    """Ortak limit kuralı: kullanılan = toplam kart borcu (ödenen ekstreler düşülmüş); limit tanımsızsa kontrol yok."""
    from database.kredi_karti_ekstre_service import KrediKartiEkstreService as E

    try:
        E.limit_kontrol(session, kart, ek)
    except ValueError as hata:
        raise ValueError(f"{kart.kart_adi}: {hata}") from hata


def _kk_hesabi(session, kart: KrediKartiTanimi) -> FinansHesabi:
    h = session.scalar(select(FinansHesabi).where(FinansHesabi.banka_karti_id == kart.banka_karti_id,
                                                  FinansHesabi.alt_hesap_turu == "KREDI_KARTI"))
    if h is None or not h.aktif:
        raise ValueError(f"{kart.kart_adi}: bankanın kredi kartı hesabı yok veya pasif — banka kartını kaydedin.")
    return h


def _kart_odemesi_yaz(session, *, kart, kk_hesap, gko_id, tarih: date, satirlar: list[dict], cekim_turu: str,
                      aciklama: str, durum_taksit: str = "BEKLIYOR", hareket_turu: str | None = None,
                      referans_no: str | None = None, hareket_tarihi: date | None = None,
                      finansman_farki=None, duzeltme_id: int | None = None) -> KrediKartiOdeme:
    """Kart kaydı + taksitler + kart hesabı hareketi. ``tarih`` çekim tarihidir (dönem / limit); hareket
    ``hareket_tarihi`` gününe yazılır (düzeltmede düzeltme günü). Satırsız kayıt yalnız muhasebe farkı taşır."""
    from database.finans_service import FinansService
    from database.kredi_karti_ekstre_service import KrediKartiEkstreService as E, _ay_kaydir, ay_gunu

    def vade(s: dict) -> date:
        # Vade kolonu boş olamaz: son ödeme bilinmiyorsa kesim, kesim de bilinmiyorsa çekim + taksit sırası ayı
        if s["kesim"] is not None:
            return E.kesim_donemi(s["kesim"], kart)["son_odeme_tarihi"] or s["kesim"]
        y, a = _ay_kaydir(tarih.year, tarih.month, int(s["taksit_no"]) - 1)
        return ay_gunu(y, a, tarih.day)

    belge_no = FinansService._finans_belge_no(session, "KKO")
    toplam = sum((s["tutar"] for s in satirlar), SIFIR)
    odeme = KrediKartiOdeme(
        belge_no=belge_no, tarih=tarih, vade_tarihi=vade(satirlar[0]) if satirlar else tarih,
        banka_karti_id=kart.banka_karti_id, kredi_karti_id=kart.id, cari_id=0, cekim_turu=cekim_turu,
        taksit_sayisi=len(satirlar), tutar=toplam, referans_no=referans_no,
        aciklama=(aciklama or "")[:500] or None, durum="AÇIK", kaynak_turu="GIDER", gider_kart_odeme_id=gko_id,
        finansman_farki=finansman_farki, duzeltme_id=duzeltme_id)
    session.add(odeme)
    session.flush()
    for s in satirlar:
        session.add(KrediKartiOdemeTaksit(
            odeme_id=odeme.id, taksit_no=s["taksit_no"], tutar=s["tutar"], durum=durum_taksit,
            vade_tarihi=vade(s), ekstre_kesim_tarihi=s["kesim"]))
    if toplam != 0:
        tur = hareket_turu or ("KK ÖDEME" if toplam > 0 else HAREKET_DUZELTME_AZALIS)
        session.add(FinansHareketi(hesap_id=kk_hesap.id, tarih=hareket_tarihi or tarih, hareket_turu=tur,
                                   belge_no=belge_no, tutar=abs(toplam), aciklama=(aciklama or belge_no)[:500]))
    session.flush()
    return odeme


def _tutarlari_dogrula(kart, islem_tarihi: date, plan: list[dict], ucret: dict | None, gider_tutari: Decimal,
                       faiz_durumu: str) -> tuple[list[dict], dict | None, Decimal, Decimal]:
    """Plan, ayrı ücret ve faiz onayı: (taksit satırları, ücret satırı, kart toplamı, finansman farkı)."""
    if faiz_durumu not in (FAIZSIZ, FAIZ_GIRILDI):
        raise ValueError("Faiz ve ücret durumunu doğrulayın: banka planı faizsiz mi, yoksa bankanın gerçek faiz / "
                         "ücret tutarı mı girildi? Bilinmeyen faiz sıfır sayılmaz.")
    satirlar = plan_dogrula(kart, islem_tarihi, plan)
    ucret_satiri = None
    if ucret and _d(ucret.get("tutar")) > 0:
        ucret_satiri = plan_dogrula(kart, islem_tarihi, [{"kesim": ucret.get("kesim"), "tutar": ucret.get("tutar")}])[0]
    plan_toplami = sum((x["tutar"] for x in satirlar), SIFIR)
    kart_toplami = plan_toplami + (ucret_satiri["tutar"] if ucret_satiri else SIFIR)
    fark = kart_toplami - gider_tutari
    if plan_toplami < gider_tutari:
        raise ValueError(f"Taksit toplamı ({plan_toplami} TL) ödenen gider tutarından ({gider_tutari} TL) az. "
                         "Taksit tutarlarını banka planına göre düzeltin.")
    if faiz_durumu == FAIZSIZ and fark != 0:
        raise ValueError(f"'Faizsiz' onaylandı ancak karta yansıyacak toplam ({kart_toplami} TL) gider "
                         f"tutarından ({gider_tutari} TL) farklı. Faiz / ücret varsa tutarını girin.")
    if faiz_durumu == FAIZ_GIRILDI and fark <= 0:
        raise ValueError("Faiz / ücret girildi seçildi ama karta yansıyacak toplam gider tutarından büyük "
                         "değil. Plan faizsizse 'Faizsiz' onayını işaretleyin.")
    return satirlar, ucret_satiri, kart_toplami, fark


# ----------------------------------------------------------------------------- kayıt
def _ozet(session, g: GiderKartOdeme, *, mevcut: bool = False) -> dict:
    ko = session.get(KrediKartiOdeme, int(g.kk_odeme_id))
    fis = session.get(GiderFisi, int(g.gider_fisi_id))
    ucret = session.get(KrediKartiOdeme, int(g.ucret_kk_odeme_id)) if g.ucret_kk_odeme_id else None
    return {"id": int(g.id), "gider_fisi": fis.belge_no if fis else "", "kart_odeme": ko.belge_no if ko else "",
            "ucret_kart_odeme": ucret.belge_no if ucret else "", "gider_tutari": _q2(g.gider_tutari),
            "kart_toplami": _q2(g.kart_toplami), "finansman_farki": _q2(g.finansman_farki),
            "taksit_sayisi": int(ko.taksit_sayisi) if ko else 0, "durum": g.durum, "mevcut": mevcut}


def kart_ile_ode(*, istek_anahtari: str, kredi_karti_id: int, islem_tarihi: date, gider_tutari, plan: list[dict],
                 faiz_durumu: str, hizmet_id: int, kaynak: dict | None = None, ucret: dict | None = None,
                 aciklama: str = "", sube_id=None) -> dict:
    """Gideri kartla öder. ``plan``: [{kesim, tutar}] (tek çekimde tek satır). ``ucret``: ayrı tahsil edilen
    banka ücreti {tutar, kesim}. ``kaynak``: {"tur": "SABIT", plan_id, yil, ay} veya doğrudan gider fişi."""
    from database.finans_service import FinansService
    from database import sabit_gider_service as sg
    from database.muhasebe_entegrasyon import muhasebe_hook

    yazma_zorunlu(*YAZMA_YETKISI)
    schema_hazirla()
    anahtar = (istek_anahtari or "").strip()
    if not anahtar:
        raise ValueError("İstek anahtarı eksik.")
    if not isinstance(islem_tarihi, date):
        raise ValueError("İşlem tarihi geçersiz.")
    if islem_tarihi > date.today():
        raise ValueError("İşlem tarihi gelecek olamaz (gerçekleşmiş kart ödemesi kaydedilir).")
    gider_tutari = _kurus_tam(gider_tutari, "Ödenen gider tutarı")
    if gider_tutari <= 0:
        raise ValueError("Ödenen gider tutarı sıfırdan büyük olmalıdır.")
    if faiz_durumu not in (FAIZSIZ, FAIZ_GIRILDI):
        raise ValueError("Faiz ve ücret durumunu doğrulayın: banka planı faizsiz mi, yoksa bankanın gerçek faiz / "
                         "ücret tutarı mı girildi? Bilinmeyen faiz sıfır sayılmaz.")
    kaynak = kaynak or {"tur": KAYNAK_GIDER_FISI}
    kaynak_tur = kaynak.get("tur") or KAYNAK_GIDER_FISI
    if kaynak_tur not in (KAYNAK_SABIT, KAYNAK_GIDER_FISI):
        raise ValueError("Gider kaynağı geçersiz.")

    try:
        with get_session() as s:
            onceki = s.scalar(select(GiderKartOdeme).where(GiderKartOdeme.istek_anahtari == anahtar))
            if onceki is not None:
                return _ozet(s, onceki, mevcut=True)
            kart = _kart_al(s, kredi_karti_id)
            kk_hesap = _kk_hesabi(s, kart)
            satirlar, ucret_satiri, kart_toplami, fark = _tutarlari_dogrula(
                kart, islem_tarihi, plan, ucret, gider_tutari, faiz_durumu)

            donem = None
            if kaynak_tur == KAYNAK_SABIT:
                donem = sg._donem_al(s, kaynak["plan_id"], kaynak["yil"], kaynak["ay"])
                kalan = sg.donem_ozeti(s, donem, date.max)["kalan"]
                if gider_tutari > kalan:
                    raise ValueError(f"Ödenen gider tutarı ({gider_tutari} TL) giderin kalanını ({kalan} TL) aşıyor.")
            _limit_kontrol(s, kart, kart_toplami)

            fis = FinansService._gider_fisi_yaz(s, {
                "tarih": islem_tarihi, "tutar": gider_tutari, "hizmet_id": hizmet_id, "sube_id": sube_id,
                "aciklama": aciklama or None}, kart_hesabi=kk_hesap)
            g = GiderKartOdeme(
                istek_anahtari=anahtar, kaynak_turu=kaynak_tur, kredi_karti_id=kart.id, kk_odeme_id=0,
                gider_fisi_id=fis.id, sabit_donem_id=donem.id if donem is not None else None,
                islem_tarihi=islem_tarihi, gider_tutari=gider_tutari, kart_toplami=kart_toplami,
                finansman_farki=fark, faiz_durumu=faiz_durumu, ilk_kesim=satirlar[0]["kesim"],
                aciklama=(aciklama or "")[:500] or None, durum="AÇIK", olusturan=_kullanici())
            s.add(g)
            s.flush()
            taksit_metin = "tek çekim" if len(satirlar) == 1 else f"{len(satirlar)} taksit"
            ko = _kart_odemesi_yaz(
                s, kart=kart, kk_hesap=kk_hesap, gko_id=g.id, tarih=islem_tarihi, satirlar=satirlar,
                cekim_turu="TEK_CEKIM" if len(satirlar) == 1 else "TAKSITLI",
                aciklama=f"Kartla gider ödemesi {fis.belge_no} ({taksit_metin})"
                         + (f" — {aciklama}" if aciklama else ""), finansman_farki=fark)
            g.kk_odeme_id = ko.id
            fis.bagli_belge_no = ko.belge_no
            if ucret_satiri is not None:
                uk = _kart_odemesi_yaz(
                    s, kart=kart, kk_hesap=kk_hesap, gko_id=g.id, tarih=islem_tarihi,
                    satirlar=[{**ucret_satiri, "taksit_no": 1}], cekim_turu="TEK_CEKIM",
                    aciklama=f"Banka ücreti — kartla gider ödemesi {fis.belge_no}", finansman_farki=SIFIR)
                g.ucret_kk_odeme_id = uk.id
            if donem is not None:
                b = sg._baglanti_yaz(s, donem, fis.belge_no, gider_tutari, tarih=islem_tarihi,
                                     aciklama=f"Kredi kartıyla ödendi ({ko.belge_no})")
                g.baglanti_id = b.id
            s.flush()
            muhasebe_hook("gider_fisi_fisi", int(fis.id), session=s)
            muhasebe_hook("kart_odeme_fisi", int(ko.id), session=s)
            if g.ucret_kk_odeme_id:
                muhasebe_hook("kart_odeme_fisi", int(g.ucret_kk_odeme_id), session=s)
            return _ozet(s, g)
    except IntegrityError:
        # Aynı anahtarla eşzamanlı ikinci kayıt: ilk kayıt geçerli, ikinci hiçbir satır bırakmadan geri alındı
        with get_session() as s:
            onceki = s.scalar(select(GiderKartOdeme).where(GiderKartOdeme.istek_anahtari == anahtar))
            if onceki is None:
                raise
            return _ozet(s, onceki, mevcut=True)


# ----------------------------------------------------------------------------- iptal / iade
def _kart_odemeleri(session, g: GiderKartOdeme) -> list[KrediKartiOdeme]:
    return list(session.scalars(select(KrediKartiOdeme).where(KrediKartiOdeme.gider_kart_odeme_id == g.id)
                                .order_by(KrediKartiOdeme.id)).all())


def _iade_toplami(odemeler) -> Decimal:
    return sum((abs(_d(o.tutar)) for o in odemeler if o.cekim_turu == "IADE" and o.durum == "AÇIK"), SIFIR)


def _kesim_odendi_mi(session, kredi_karti_id: int, kesim: date) -> bool:
    """Ekstreye geçerli (iptal edilmemiş) ödeme yapılmış mı — yapılmışsa dönem kapanmış sayılır."""
    return session.scalar(
        select(KrediKartiEkstreOdeme.id).join(KrediKartiEkstre, KrediKartiEkstre.id == KrediKartiEkstreOdeme.ekstre_id)
        .where(KrediKartiEkstre.kredi_karti_id == int(kredi_karti_id), KrediKartiEkstre.kesim_tarihi == kesim,
               KrediKartiEkstreOdeme.iptal.is_(False)).limit(1)) is not None


def kilit_nedeni(session, g: GiderKartOdeme) -> str | None:
    """Hatalı kayıt iptali engeli: ödenmiş taksit, ödeme yapılmış ekstre veya banka iadesi."""
    from database.kredi_karti_ekstre_service import KrediKartiEkstreService as E

    if g.durum != "AÇIK":
        return "Kayıt zaten iptal."
    odemeler = _kart_odemeleri(session, g)
    if _iade_toplami(odemeler) > 0:
        return "Bu ödemeye banka iadesi kaydedilmiş; program kaydı iptal edilemez."
    kart = session.get(KrediKartiTanimi, int(g.kredi_karti_id))
    for o in odemeler:
        if o.durum != "AÇIK":
            continue
        for t in o.taksitler or []:
            if t.durum == "ODENDI":
                return f"{o.belge_no} taksiti ekstrede ödendi; geçmiş silinmez. Bankanın iptal / iadesini kaydedin."
            donem = E.taksit_kesimi(o, t, kart)
            if donem is None:
                continue
            kesim = donem["kesim_tarihi"]
            if _kesim_odendi_mi(session, kart.id, kesim):
                return (f"{kesim:%d.%m.%Y} ekstresine ödeme yapılmış; kapanmış dönem yeniden yazılmaz. Bankanın iptal "
                        "/ iadesini 'Banka iadesi' ile kaydedin.")
    return None


def iptal(gider_kart_odeme_id: int, neden: str) -> None:
    """Hatalı program kaydının iptali: gider kapanışı ve kart borcu birlikte geri alınır (kayıtlar silinmez)."""
    from database import sabit_gider_service as sg
    from database.finans_service import FinansService
    from database.masraf_dagitim_service import KAYNAK_GIDER_FISI as MD_GIDER_FISI, MasrafDagitimService
    from database.models.sabit_gider import SabitGiderBaglanti
    from database.muhasebe_entegrasyon import muhasebe_hook

    yazma_zorunlu(*YAZMA_YETKISI)
    schema_hazirla()
    if not (neden or "").strip():
        raise ValueError("İptal nedeni yazın.")
    with get_session() as s:
        g = s.get(GiderKartOdeme, int(gider_kart_odeme_id))
        if g is None:
            raise ValueError("Kartla gider ödemesi bulunamadı.")
        engel = kilit_nedeni(s, g)
        if engel:
            raise ValueError(engel)
        gider_fisi_id = int(g.gider_fisi_id)
    MasrafDagitimService.kilit_kontrol(kaynak_id=gider_fisi_id, kaynak_turu=MD_GIDER_FISI)
    with get_session() as s:
        g = s.get(GiderKartOdeme, int(gider_kart_odeme_id))
        engel = kilit_nedeni(s, g)
        if engel:
            raise ValueError(engel)
        kart = s.get(KrediKartiTanimi, int(g.kredi_karti_id))
        kk_hesap = _kk_hesabi(s, kart)
        for o in _kart_odemeleri(s, g):
            if o.durum != "AÇIK":
                continue
            o.durum = "İPTAL"
            if _d(o.tutar) != 0:
                s.add(FinansHareketi(hesap_id=kk_hesap.id, tarih=date.today(),
                                     hareket_turu="KK ÖDEME İPTAL" if _d(o.tutar) > 0 else HAREKET_DUZELTME_ARTIS,
                                     belge_no=o.belge_no, tutar=abs(_d(o.tutar)),
                                     aciklama=f"İptal: {o.belge_no} — {neden.strip()}"[:500]))
            s.flush()
            muhasebe_hook("kart_odeme_iptal", int(o.id), f"Kartla gider ödemesi iptal {o.belge_no}", session=s)
        fis = s.get(GiderFisi, gider_fisi_id)
        if fis is not None and fis.durum != "IPTAL":
            FinansService._gider_fisi_iptal_yaz(s, fis)
        if g.baglanti_id:
            b = s.get(SabitGiderBaglanti, int(g.baglanti_id))
            if b is not None:
                sg._baglanti_iptal_yaz(b, f"Kartla gider ödemesi iptal: {neden.strip()}")
        g.durum = "IPTAL"
        g.iptal_zamani, g.iptal_kullanici, g.iptal_nedeni = datetime.now(), _kullanici(), neden.strip()[:300]
        s.flush()
    MasrafDagitimService.sahipsiz_taslaklari_kapat()


def _ucret_kaydi(session, g: GiderKartOdeme) -> KrediKartiOdeme | None:
    if not g.ucret_kk_odeme_id:
        return None
    uk = session.get(KrediKartiOdeme, int(g.ucret_kk_odeme_id))
    return uk if uk is not None and uk.durum == "AÇIK" else None


def _iade_kirilimi(session, g: GiderKartOdeme) -> dict:
    """Geçerli iadelerin gider (ana para) / faiz / ücret payı. Kırılımı olmayan eski iade ana para sayılır."""
    detay = {int(i.kk_odeme_id): i for i in session.scalars(
        select(GiderKartIade).where(GiderKartIade.gider_kart_odeme_id == g.id)).all()}
    k = {"gider": SIFIR, "faiz": SIFIR, "ucret": SIFIR}
    for o in _kart_odemeleri(session, g):
        if o.cekim_turu != "IADE" or o.durum != "AÇIK":
            continue
        i = detay.get(int(o.id))
        if i is None:
            k["gider"] += abs(_q2(o.tutar))
        else:
            k["gider"] += _q2(i.gider_tutari)
            k["faiz"] += _q2(i.faiz_tutari)
            k["ucret"] += _q2(i.ucret_tutari)
    return k


def iade_siniri(session, g: GiderKartOdeme) -> dict:
    """İade edilebilir kalanlar: gider tutarı, faiz payı (finansman farkı − ayrı ücret) ve ayrı ücret kaydı."""
    k = _iade_kirilimi(session, g)
    uk = _ucret_kaydi(session, g)
    ucret = _q2(uk.tutar) if uk is not None else SIFIR
    faiz = max(_q2(g.finansman_farki) - ucret, SIFIR)
    return {"gider": _q2(g.gider_tutari) - k["gider"], "faiz": faiz - k["faiz"], "ucret": ucret - k["ucret"],
            "faiz_toplami": faiz, "ucret_toplami": ucret, "iade_edilen": k}


def iade_kaydet(gider_kart_odeme_id: int, *, tarih: date, tutar, istek_anahtari: str, aciklama: str = "",
                faiz_tutari=0, ucret_tutari=0) -> dict:
    """Bankanın gerçekleşmiş iadesi (kayıt düzeltmesi değildir; banka iade etmediyse kullanılmaz).

    ``tutar`` giderin (ana para) iadesi; ``faiz_tutari`` ve ``ucret_tutari`` bankanın iade ettiği faiz ve ayrı ücret
    payıdır. Toplam, iade tarihinin ekstresine tek eksi satır olarak yazılır; önceki ekstreler değişmez. Gider kalanı
    yalnız ana para kadar açılır; iade edilen faiz / ücret 780 etkisini bir kez ters çevirir; iade edilmeyen masraf
    kendiliğinden kapanmaz."""
    from database import sabit_gider_service as sg
    from database.kredi_karti_ekstre_service import KrediKartiEkstreService as E
    from database.models.sabit_gider import SabitGiderBaglanti, SabitGiderDonemi
    from database.muhasebe_entegrasyon import muhasebe_hook

    yazma_zorunlu(*YAZMA_YETKISI)
    schema_hazirla()
    anahtar = (istek_anahtari or "").strip()
    if not anahtar:
        raise ValueError("İstek anahtarı eksik.")
    referans = f"IADE:{anahtar}"[:50]
    if not isinstance(tarih, date) or tarih > date.today():
        raise ValueError("İade tarihi geçersiz veya gelecekte.")
    gider = _kurus_tam(tutar or 0, "Gider (ana para) iadesi")
    faiz = _kurus_tam(faiz_tutari or 0, "Faiz iadesi")
    ucret = _kurus_tam(ucret_tutari or 0, "Ücret iadesi")
    if min(gider, faiz, ucret) < 0:
        raise ValueError("İade tutarları eksi olamaz.")
    toplam = gider + faiz + ucret
    if toplam <= 0:
        raise ValueError("İade tutarı sıfırdan büyük olmalıdır.")
    with get_session() as s:
        mevcut = s.scalar(select(KrediKartiOdeme).where(KrediKartiOdeme.referans_no == referans))
        if mevcut is not None:
            d = s.scalar(select(GiderKartIade).where(GiderKartIade.kk_odeme_id == mevcut.id))
            return {"belge_no": mevcut.belge_no, "tutar": abs(_q2(mevcut.tutar)),
                    "gider": _q2(d.gider_tutari) if d else abs(_q2(mevcut.tutar)),
                    "faiz": _q2(d.faiz_tutari) if d else SIFIR, "ucret": _q2(d.ucret_tutari) if d else SIFIR,
                    "kesim": d.kesim if d else None, "mevcut": True}
        g = s.get(GiderKartOdeme, int(gider_kart_odeme_id))
        if g is None or g.durum != "AÇIK":
            raise ValueError("Kartla gider ödemesi bulunamadı veya iptal edilmiş.")
        if tarih < g.islem_tarihi:
            raise ValueError("İade tarihi kart ödemesinden önce olamaz.")
        sinir = iade_siniri(s, g)
        if gider > sinir["gider"]:
            raise ValueError(f"Gider (ana para) iadesi iade edilebilir gider tutarını ({sinir['gider']} TL) aşıyor.")
        if faiz > sinir["faiz"]:
            raise ValueError(f"Faiz iadesi bu ödemenin iade edilmemiş faiz payını ({sinir['faiz']} TL) aşıyor.")
        if ucret > sinir["ucret"]:
            raise ValueError("Bu ödemede ayrı ücret kaydı yok; ücret iadesi girilemez." if sinir["ucret_toplami"] <= 0
                             else f"Ücret iadesi ayrı ücret kaydının iade edilmemiş kısmını ({sinir['ucret']} TL) "
                                  "aşıyor.")
        kart = _kart_al(s, g.kredi_karti_id)
        kk_hesap = _kk_hesabi(s, kart)
        kesim = E.donem_bilgisi(tarih, kart)["kesim_tarihi"] if E.kesim_gunu(kart) is not None else None
        fis = s.get(GiderFisi, int(g.gider_fisi_id))
        parca = [f"gider {gider}"] + ([f"faiz {faiz}"] if faiz else []) + ([f"ücret {ucret}"] if ucret else [])
        ko = _kart_odemesi_yaz(
            s, kart=kart, kk_hesap=kk_hesap, gko_id=g.id, tarih=tarih,
            satirlar=[{"taksit_no": 1, "kesim": kesim, "tutar": -toplam}], cekim_turu="IADE",
            aciklama=f"Kart iadesi — kartla gider ödemesi {fis.belge_no if fis else ''} ({', '.join(parca)} TL)"
                     + (f" — {aciklama}" if aciklama else ""),
            durum_taksit="IADE", hareket_turu="KK İADE", referans_no=referans)
        uk = _ucret_kaydi(s, g)
        s.add(GiderKartIade(
            gider_kart_odeme_id=g.id, kk_odeme_id=ko.id, istek_anahtari=anahtar[:64], tarih=tarih, kesim=kesim,
            gider_tutari=gider, faiz_tutari=faiz, ucret_tutari=ucret,
            faiz_kk_odeme_id=int(g.kk_odeme_id) if faiz > 0 else None,
            ucret_kk_odeme_id=int(uk.id) if ucret > 0 and uk is not None else None,
            aciklama=(aciklama or "")[:500] or None, olusturan=_kullanici()))
        if gider > 0 and g.baglanti_id:
            b = s.get(SabitGiderBaglanti, int(g.baglanti_id))
            if b is not None and not b.iptal:
                yeni = _q2(b.tutar) - gider
                sg._baglanti_iptal_yaz(b, f"Kart iadesi {ko.belge_no}: gider kalanı {gider} TL yeniden açıldı")
                s.flush()
                g.baglanti_id = None
                if yeni > 0:
                    donem = s.get(SabitGiderDonemi, int(b.donem_id))
                    nb = sg._baglanti_yaz(s, donem, b.belge_no, yeni, tarih=b.tarih,
                                          aciklama=f"Kart iadesi {ko.belge_no} sonrası kalan bağlantı")
                    g.baglanti_id = nb.id
        s.flush()
        muhasebe_hook("kart_odeme_fisi", int(ko.id), session=s)
        return {"belge_no": ko.belge_no, "tutar": toplam, "gider": gider, "faiz": faiz, "ucret": ucret,
                "kesim": kesim, "mevcut": False}


# ----------------------------------------------------------------------------- kayıt düzeltmesi
def _plan_satirlari(session, g: GiderKartOdeme, kart) -> list[dict]:
    """Etkin taksit planı (ana kayıt + önceki düzeltmeler; ayrı ücret ve iade hariç), dönem bazında toplanmış.
    ``kapali``: dönemin ekstresine ödeme yapılmış ya da taksit ödenmiş — bu dönem yeniden yazılmaz."""
    from database.kredi_karti_ekstre_service import KrediKartiEkstreService as E

    ucret_id = int(g.ucret_kk_odeme_id or 0)
    toplam: dict[date, Decimal] = {}
    odendi: set[date] = set()
    belirsiz = []
    for o in _kart_odemeleri(session, g):
        if o.durum != "AÇIK" or o.cekim_turu == "IADE" or int(o.id) == ucret_id:
            continue
        for t in o.taksitler or []:
            donem = E.taksit_kesimi(o, t, kart)
            if donem is None:
                belirsiz.append({"kesim": None, "tutar": _q2(t.tutar), "kapali": t.durum == "ODENDI"})
                continue
            k = donem["kesim_tarihi"]
            toplam[k] = toplam.get(k, SIFIR) + _q2(t.tutar)
            if t.durum == "ODENDI" and _d(t.tutar) > 0:
                odendi.add(k)
    satirlar = []
    for k in sorted(toplam):
        kapali = k in odendi or _kesim_odendi_mi(session, kart.id, k)
        if toplam[k] != 0 or kapali:
            satirlar.append({"kesim": k, "tutar": toplam[k], "kapali": kapali})
    return satirlar + belirsiz


def _ucret_bilgisi(session, g: GiderKartOdeme, kart) -> dict | None:
    from database.kredi_karti_ekstre_service import KrediKartiEkstreService as E

    uk = _ucret_kaydi(session, g)
    if uk is None or not uk.taksitler:
        return None
    donem = E.taksit_kesimi(uk, uk.taksitler[0], kart)
    return {"kesim": donem["kesim_tarihi"] if donem else None, "tutar": _q2(uk.tutar)}


def _duzeltme_turu(session, g: GiderKartOdeme) -> tuple[str | None, str | None]:
    """(TAM | ACIK_DONEM, None) veya (None, engel nedeni)."""
    from database.kredi_karti_ekstre_service import KrediKartiEkstreService as E

    if g.durum != "AÇIK":
        return None, "Kayıt iptal edilmiş; düzeltilemez."
    if sum(_iade_kirilimi(session, g).values(), SIFIR) > 0:
        return None, ("Bu ödemeye bankanın gerçek iadesi kaydedilmiş; kayıt düzeltmesi yapılamaz. Hata iadeden önceki "
                      "kayıttaysa iade tutarları zaten bankanın belgesine göre girilmiştir.")
    if kilit_nedeni(session, g) is None:
        return DUZELTME_TAM, None
    kart = session.get(KrediKartiTanimi, int(g.kredi_karti_id))
    if E.kesim_gunu(kart) is None:
        return None, ("Ödenmiş taksit var ve kartın hesap kesim günü tanımsız: kapanmış / açık dönem ayrılamadığı için "
                      "düzeltme yapılamaz. Önce kart tanımına kesim gününü girin.")
    return DUZELTME_ACIK_DONEM, None


def _anlik(session, g: GiderKartOdeme, kart) -> dict:
    fis = session.get(GiderFisi, int(g.gider_fisi_id))
    u = _ucret_bilgisi(session, g, kart)
    return {
        "kredi_karti_id": int(g.kredi_karti_id), "kart": kart.kart_adi if kart else "",
        "gider_tutari": str(_q2(g.gider_tutari)), "kart_toplami": str(_q2(g.kart_toplami)),
        "finansman_farki": str(_q2(g.finansman_farki)), "faiz_durumu": g.faiz_durumu,
        "gider_fisi": fis.belge_no if fis else "", "baglanti_id": g.baglanti_id,
        "plan": [[r["kesim"].isoformat() if r["kesim"] else None, str(r["tutar"]), r["kapali"]]
                 for r in _plan_satirlari(session, g, kart)],
        "ucret": [u["kesim"].isoformat() if u["kesim"] else None, str(u["tutar"])] if u else None,
        "kart_kayitlari": [o.belge_no for o in _kart_odemeleri(session, g) if o.durum == "AÇIK"],
    }


def duzeltme_gecmisi(session, gider_kart_odeme_id: int) -> list[dict]:
    return [{"id": int(d.id), "tur": d.tur, "tarih": d.duzeltme_tarihi, "neden": d.neden, "kullanici": d.kullanici,
             "zaman": d.zaman, "eski": json.loads(d.eski_degerler or "{}"), "yeni": json.loads(d.yeni_degerler or "{}"),
             "duzeltilen_kayitlar": d.eski_odemeler or "", "yeni_kayitlar": d.yeni_odemeler or ""}
            for d in session.scalars(select(GiderKartDuzeltme).where(
                GiderKartDuzeltme.gider_kart_odeme_id == int(gider_kart_odeme_id)).order_by(GiderKartDuzeltme.id))]


def duzeltme_bilgisi(gider_kart_odeme_id: int) -> dict:
    """Düzeltme ekranı için mevcut değerler, düzeltme türü / engeli ve geçmiş."""
    schema_hazirla()
    with get_session() as s:
        g = s.get(GiderKartOdeme, int(gider_kart_odeme_id))
        if g is None:
            raise ValueError("Kartla gider ödemesi bulunamadı.")
        kart = s.get(KrediKartiTanimi, int(g.kredi_karti_id))
        tur, engel = _duzeltme_turu(s, g)
        fis = s.get(GiderFisi, int(g.gider_fisi_id))
        return {"id": int(g.id), "tur": tur, "engel": engel, "kredi_karti_id": int(g.kredi_karti_id),
                "islem_tarihi": g.islem_tarihi, "gider_tutari": _q2(g.gider_tutari),
                "kart_toplami": _q2(g.kart_toplami), "finansman_farki": _q2(g.finansman_farki),
                "faiz_durumu": g.faiz_durumu, "plan": _plan_satirlari(s, g, kart),
                "ucret": _ucret_bilgisi(s, g, kart), "gider_fisi": fis.belge_no if fis else "",
                "gecmis": duzeltme_gecmisi(s, g.id)}


def _duzeltme_sonucu(session, d: GiderKartDuzeltme, *, mevcut: bool = False) -> dict:
    return {"id": int(d.gider_kart_odeme_id), "duzeltme_id": int(d.id), "tur": d.tur,
            "eski": json.loads(d.eski_degerler or "{}"), "yeni": json.loads(d.yeni_degerler or "{}"),
            "duzeltilen_kayitlar": d.eski_odemeler or "", "yeni_kayitlar": d.yeni_odemeler or "", "mevcut": mevcut}


def duzelt(gider_kart_odeme_id: int, *, istek_anahtari: str, neden: str, gider_tutari, plan: list[dict],
           faiz_durumu: str, kredi_karti_id: int | None = None, ucret=UCRET_AYNI, tarih: date | None = None) -> dict:
    """Hatalı tutar, kart veya taksit bilgisinin kontrollü düzeltmesi (iade kaydı üretmez; kayıt silinmez).

    ``plan`` düzeltilmiş tam plandır [{kesim, tutar}]; ödenmiş dönemler aynı kesimle planda kalmalıdır.
    ``ucret``: {tutar, kesim}, None (ücret yok) veya UCRET_AYNI. Tümü tek işlemdir; aynı anahtarla tekrar
    çağrı yeni kayıt üretmez.
    """
    from database import sabit_gider_service as sg
    from database.finans_service import FinansService
    from database.masraf_dagitim_service import KAYNAK_GIDER_FISI as MD_GIDER_FISI, MasrafDagitimService
    from database.models.sabit_gider import SabitGiderBaglanti, SabitGiderDonemi
    from database.muhasebe_entegrasyon import muhasebe_hook

    yazma_zorunlu(*YAZMA_YETKISI)
    schema_hazirla()
    anahtar = (istek_anahtari or "").strip()[:64]
    if not anahtar:
        raise ValueError("İstek anahtarı eksik.")
    neden = (neden or "").strip()
    if not neden:
        raise ValueError("Düzeltme nedeni yazın (eski / yeni değerle birlikte saklanır).")
    tarih = tarih or date.today()
    if not isinstance(tarih, date) or tarih > date.today():
        raise ValueError("Düzeltme tarihi geçersiz veya gelecekte.")
    gider_yeni = _kurus_tam(gider_tutari, "Ödenen gider tutarı")
    if gider_yeni <= 0:
        raise ValueError("Ödenen gider tutarı sıfırdan büyük olmalıdır.")

    with get_session() as s:
        d = s.scalar(select(GiderKartDuzeltme).where(GiderKartDuzeltme.istek_anahtari == anahtar))
        if d is not None:
            return _duzeltme_sonucu(s, d, mevcut=True)
        g = s.get(GiderKartOdeme, int(gider_kart_odeme_id))
        if g is None:
            raise ValueError("Kartla gider ödemesi bulunamadı.")
        fis_degisir = gider_yeni != _q2(g.gider_tutari) or (
            kredi_karti_id is not None and int(kredi_karti_id) != int(g.kredi_karti_id))
        gider_fisi_id = int(g.gider_fisi_id)
    if fis_degisir:
        MasrafDagitimService.kilit_kontrol(kaynak_id=gider_fisi_id, kaynak_turu=MD_GIDER_FISI)

    try:
        with get_session() as s:
            g = s.get(GiderKartOdeme, int(gider_kart_odeme_id))
            tur, engel = _duzeltme_turu(s, g)
            if engel:
                raise ValueError(engel)
            if tarih < g.islem_tarihi:
                raise ValueError("Düzeltme tarihi kart işlem tarihinden önce olamaz.")
            eski_kart = s.get(KrediKartiTanimi, int(g.kredi_karti_id))
            kart = _kart_al(s, kredi_karti_id or g.kredi_karti_id)
            kart_degisir = int(kart.id) != int(eski_kart.id)
            if tur == DUZELTME_ACIK_DONEM and kart_degisir:
                raise ValueError("Ekstresi ödenmiş dönemi olan kayıtta kart değiştirilemez: ödenmiş dönem bu kartın "
                                 "ekstresinde kalır. Kart hatası yalnız hiçbir dönem ödenmeden düzeltilebilir.")
            eski_ucret = _ucret_bilgisi(s, g, eski_kart)
            if ucret is UCRET_AYNI:
                ucret = eski_ucret
            satirlar, ucret_satiri, kart_toplami, fark = _tutarlari_dogrula(
                kart, g.islem_tarihi, plan, ucret, gider_yeni, faiz_durumu)
            eski_plan = _plan_satirlari(s, g, eski_kart)
            yeni_ucret = (ucret_satiri["kesim"], ucret_satiri["tutar"]) if ucret_satiri else None
            eski_ucret_t = (eski_ucret["kesim"], eski_ucret["tutar"]) if eski_ucret else None
            plan_degisir = [(r["kesim"], r["tutar"]) for r in satirlar] != [(r["kesim"], r["tutar"]) for r in eski_plan]
            if not (kart_degisir or fis_degisir or plan_degisir or yeni_ucret != eski_ucret_t
                    or faiz_durumu != g.faiz_durumu):
                raise ValueError("Düzeltilecek bir değişiklik yok.")
            if tur == DUZELTME_ACIK_DONEM and yeni_ucret != eski_ucret_t:
                raise ValueError("Ekstresi ödenmiş dönemi olan kayıtta ayrı ücret kaydı değiştirilemez. Banka ücreti "
                                 "iade ettiyse 'Banka iadesi' ile ücret iadesi olarak kaydedin.")

            log = GiderKartDuzeltme(
                gider_kart_odeme_id=g.id, istek_anahtari=anahtar, tur=tur, duzeltme_tarihi=tarih, neden=neden[:300],
                kullanici=_kullanici(), eski_degerler=json.dumps(_anlik(s, g, eski_kart), ensure_ascii=False),
                yeni_degerler="{}")
            s.add(log)
            s.flush()
            etiket = f"Kayıt düzeltmesi #{log.id}"
            kk_hesap = _kk_hesabi(s, kart)

            fis = s.get(GiderFisi, int(g.gider_fisi_id))
            if fis_degisir:
                donem = s.get(SabitGiderDonemi, int(g.sabit_donem_id)) if g.sabit_donem_id else None
                if g.baglanti_id:
                    b = s.get(SabitGiderBaglanti, int(g.baglanti_id))
                    if b is not None and not b.iptal:
                        sg._baglanti_iptal_yaz(b, f"{etiket}: {neden}")
                    s.flush()
                    g.baglanti_id = None
                if donem is not None:
                    kalan = sg.donem_ozeti(s, donem, date.max)["kalan"]
                    if gider_yeni > kalan:
                        raise ValueError(f"Düzeltilmiş gider tutarı ({gider_yeni} TL) giderin kalanını ({kalan} TL) "
                                         "aşıyor.")
                hizmet_id, sube_id, acik = fis.hizmet_id, fis.sube_id, fis.aciklama
                FinansService._gider_fisi_iptal_yaz(s, fis)
                fis = FinansService._gider_fisi_yaz(s, {
                    "tarih": g.islem_tarihi, "tutar": gider_yeni, "hizmet_id": hizmet_id, "sube_id": sube_id,
                    "aciklama": acik}, kart_hesabi=kk_hesap)
                g.gider_fisi_id = fis.id
                if donem is not None:
                    b = sg._baglanti_yaz(s, donem, fis.belge_no, gider_yeni, tarih=g.islem_tarihi,
                                         aciklama=f"Kredi kartıyla ödendi — {etiket}")
                    g.baglanti_id = b.id

            yeni_kayitlar: list[KrediKartiOdeme] = []
            eski_kayitlar: list[str] = []
            if tur == DUZELTME_TAM:
                for o in _kart_odemeleri(s, g):
                    if o.durum != "AÇIK":
                        continue
                    o.durum = DUZELTILDI
                    eski_kayitlar.append(o.belge_no)
                    t = _d(o.tutar)
                    if t != 0:
                        hesap = _kk_hesabi(s, s.get(KrediKartiTanimi, int(o.kredi_karti_id)))
                        s.add(FinansHareketi(
                            hesap_id=hesap.id, tarih=tarih,
                            hareket_turu=HAREKET_DUZELTME_AZALIS if t > 0 else HAREKET_DUZELTME_ARTIS,
                            belge_no=o.belge_no, tutar=abs(t),
                            aciklama=f"{etiket}: {o.belge_no} düzeltildi — {neden}"[:500]))
                    s.flush()
                    muhasebe_hook("kart_odeme_iptal", int(o.id), f"{etiket} {o.belge_no}", session=s)
                s.flush()
                _limit_kontrol(s, kart, kart_toplami)
                taksit_metin = "tek çekim" if len(satirlar) == 1 else f"{len(satirlar)} taksit"
                ko = _kart_odemesi_yaz(
                    s, kart=kart, kk_hesap=kk_hesap, gko_id=g.id, tarih=g.islem_tarihi, hareket_tarihi=tarih,
                    satirlar=satirlar, cekim_turu="TEK_CEKIM" if len(satirlar) == 1 else "TAKSITLI",
                    aciklama=f"Kartla gider ödemesi {fis.belge_no} ({taksit_metin}) — {etiket}",
                    finansman_farki=fark, duzeltme_id=log.id)
                yeni_kayitlar.append(ko)
                g.kk_odeme_id, g.ucret_kk_odeme_id = ko.id, None
                if ucret_satiri is not None:
                    uk = _kart_odemesi_yaz(
                        s, kart=kart, kk_hesap=kk_hesap, gko_id=g.id, tarih=g.islem_tarihi, hareket_tarihi=tarih,
                        satirlar=[{**ucret_satiri, "taksit_no": 1}], cekim_turu="TEK_CEKIM",
                        aciklama=f"Banka ücreti — kartla gider ödemesi {fis.belge_no} — {etiket}",
                        finansman_farki=SIFIR, duzeltme_id=log.id)
                    g.ucret_kk_odeme_id = uk.id
                    yeni_kayitlar.append(uk)
                g.kredi_karti_id, g.ilk_kesim = kart.id, satirlar[0]["kesim"]
            else:
                ana = s.get(KrediKartiOdeme, int(g.kk_odeme_id))
                if ana is not None and ana.finansman_farki is None:
                    ana.finansman_farki = _q2(g.finansman_farki)  # eski kayıt: ana kaydın farkı sabitlenir
                kapali = {r["kesim"]: r["tutar"] for r in eski_plan if r["kapali"]}
                yeni_harita = {r["kesim"]: r["tutar"] for r in satirlar}
                for k in kapali:
                    if k not in yeni_harita:
                        raise ValueError(f"{k:%d.%m.%Y} ekstresi ödenmiş (kapanmış); bu dönemin satırı planda kalmalıdır. "
                                         "Kapanmış dönem yeniden yazılmaz.")
                acik_yeni = [r for r in satirlar if r["kesim"] not in kapali]
                dz_satirlar = [{"kesim": r["kesim"], "tutar": -r["tutar"]}
                               for r in eski_plan if not r["kapali"] and r["tutar"] != 0]
                farklar = [(k, yeni_harita[k] - v) for k, v in sorted(kapali.items()) if yeni_harita[k] != v]
                if farklar:
                    son_kapali = max(kapali)
                    hedef = next((r["kesim"] for r in acik_yeni if r["kesim"] > son_kapali), None)
                    if hedef is None:
                        raise ValueError("Kapanmış dönem farkı aktarılacak açık dönem yok: son ödenmiş ekstreden sonra "
                                         "planda en az bir açık dönem olmalıdır. Kapanmış dönem yeniden yazılmaz.")
                    dz_satirlar += [{"kesim": hedef, "tutar": f} for _k, f in farklar]
                for i, r in enumerate(dz_satirlar, 1):
                    r["taksit_no"] = i
                net = kart_toplami - _q2(g.kart_toplami)
                if net > 0:
                    _limit_kontrol(s, kart, net)
                fark_degisimi = fark - _q2(g.finansman_farki)
                if dz_satirlar or fark_degisimi != 0:
                    fark_metin = "; ".join(f"{k:%d.%m.%Y} farkı {f} TL" for k, f in farklar)
                    dz = _kart_odemesi_yaz(
                        s, kart=kart, kk_hesap=kk_hesap, gko_id=g.id, tarih=g.islem_tarihi, hareket_tarihi=tarih,
                        satirlar=dz_satirlar, cekim_turu="DUZELTME",
                        aciklama=f"{etiket}: açık dönem ters satırları" + (f"; kapanmış dönem {fark_metin}"
                                                                          if fark_metin else "") + f" — {neden}",
                        hareket_turu=None if sum((r["tutar"] for r in dz_satirlar), SIFIR) <= 0
                        else HAREKET_DUZELTME_ARTIS,
                        finansman_farki=fark_degisimi, duzeltme_id=log.id)
                    log.duzeltme_odeme_id = dz.id
                    yeni_kayitlar.append(dz)
                if acik_yeni:
                    ys = [{**r, "taksit_no": i} for i, r in enumerate(acik_yeni, 1)]
                    yk = _kart_odemesi_yaz(
                        s, kart=kart, kk_hesap=kk_hesap, gko_id=g.id, tarih=g.islem_tarihi, hareket_tarihi=tarih,
                        satirlar=ys, cekim_turu="TEK_CEKIM" if len(ys) == 1 else "TAKSITLI",
                        aciklama=f"Kartla gider ödemesi {fis.belge_no} açık dönemler ({len(ys)} taksit) — {etiket}",
                        finansman_farki=SIFIR, duzeltme_id=log.id)
                    yeni_kayitlar.append(yk)
            ana = s.get(KrediKartiOdeme, int(g.kk_odeme_id))
            fis.bagli_belge_no = ana.belge_no if ana is not None else fis.bagli_belge_no
            g.gider_tutari, g.kart_toplami, g.finansman_farki, g.faiz_durumu = gider_yeni, kart_toplami, fark, faiz_durumu
            s.flush()
            log.eski_odemeler = ", ".join(eski_kayitlar)[:500] or None
            log.yeni_odemeler = ", ".join(o.belge_no for o in yeni_kayitlar)[:500] or None
            log.yeni_degerler = json.dumps(_anlik(s, g, kart), ensure_ascii=False)
            s.flush()
            if fis_degisir:
                muhasebe_hook("gider_fisi_fisi", int(fis.id), session=s)
            for o in yeni_kayitlar:
                muhasebe_hook("kart_odeme_fisi", int(o.id), session=s)
            return _duzeltme_sonucu(s, log)
    except IntegrityError:
        with get_session() as s:
            d = s.scalar(select(GiderKartDuzeltme).where(GiderKartDuzeltme.istek_anahtari == anahtar))
            if d is None:
                raise
            return _duzeltme_sonucu(s, d, mevcut=True)


# ----------------------------------------------------------------------------- liste
def liste(limit: int = 300) -> list[dict]:
    schema_hazirla()
    with get_session() as s:
        kayitlar = s.scalars(select(GiderKartOdeme).order_by(GiderKartOdeme.id.desc()).limit(limit)).all()
        metin = kaynak_metinleri(s, [g.id for g in kayitlar])
        sonuc = []
        for g in kayitlar:
            kart = s.get(KrediKartiTanimi, int(g.kredi_karti_id))
            odemeler = _kart_odemeleri(s, g)
            iade = _iade_toplami(odemeler)
            sinir = iade_siniri(s, g)
            duz_tur, duz_engel = _duzeltme_turu(s, g)
            oz = _ozet(s, g)
            oz.update({"islem_tarihi": g.islem_tarihi, "kart": kart.kart_adi if kart else "",
                       "kaynak": metin.get(int(g.id), ""), "ilk_kesim": g.ilk_kesim, "iade_toplami": iade,
                       "iade_edilebilir": sinir["gider"], "faiz_iade_edilebilir": sinir["faiz"],
                       "ucret_iade_edilebilir": sinir["ucret"], "iade_kirilimi": sinir["iade_edilen"],
                       "kilit": kilit_nedeni(s, g), "duzeltme_turu": duz_tur, "duzeltme_engeli": duz_engel,
                       "duzeltme_sayisi": len(s.scalars(select(GiderKartDuzeltme.id).where(
                           GiderKartDuzeltme.gider_kart_odeme_id == g.id)).all()),
                       "iptal_nedeni": g.iptal_nedeni or "",
                       "iadeler": [o.belge_no for o in odemeler if o.cekim_turu == "IADE"]})
            sonuc.append(oz)
        return sonuc
