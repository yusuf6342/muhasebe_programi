"""Kredi kartı ekstre hesaplama ve ödeme — Aylara Göre Ödeme Durumu kaynağı.

Her kart için hesap kesim gününe göre dönem belirlenir; harcamalar tek ekstre
borcuna toplanır ve son ödeme tarihinde tek satır olarak raporlanır.

``donem_borclari`` kart borcunun tek hesap kaynağıdır: ekstre ekranı, ödeme takvimi,
giriş özeti ve limit kontrolleri aynı sonucu kullanır.

* Toplam kart borcu = açık kart harcamaları (iade eksi) − geçerli ekstre ödemeleri.
* Kullanılan limit = toplam kart borcu (ödenmiş taksit düşülür, gelecek taksit dahil).
* Kullanılabilir limit = limit − kullanılan (kırpılmaz; aşımda eksi). Limit 0/boş → tanımsız.
* Kesim günü tanımsız kartın taksitleri dönemi belirsiz kalır ama borca ve limite girer.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from database.access import yazma_zorunlu, yetki_var
from database.database import get_session
from database.models.finans import (
    FinansHareketi,
    FinansHesabi,
    KrediKartiEkstre,
    KrediKartiEkstreOdeme,
    KrediKartiEkstreOdemeTaksit,
    KrediKartiOdeme,
    KrediKartiOdemeTaksit,
    KrediKartiTanimi,
)

SIFIR = Decimal("0.00")
KURUS = Decimal("0.01")

DURUM_KESILMEMIS = "KESILMEMIS"
DURUM_KESILMIS = "KESILMIS"
DURUM_KISMI = "KISMI"
DURUM_ODENDI = "ODENDI"
DURUM_GECIKMIS = "GECIKMIS"
DURUM_FAZLA = "FAZLA"
DURUM_EKSIK = "EKSIK_BILGI"

KAYNAK_KK_EKSTRE = "KREDI_KARTI_EKSTRE"
HAREKET_EKSTRE_ODEME = "KK EKSTRE ÖDEME"
HAREKET_EKSTRE_ODEME_IPTAL = "KK EKSTRE ÖDEME İPTAL"
ODEME_KAYNAKLARI = ("EKSTRE", "KASADAN_BANKAYA", "VIRMAN")


def _d(val, minimum=None) -> Decimal:
    try:
        t = Decimal(str(val if val is not None else 0)).quantize(KURUS, rounding=ROUND_HALF_UP)
    except Exception:
        t = SIFIR
    if minimum is not None and t < minimum:
        return Decimal(str(minimum)).quantize(KURUS, rounding=ROUND_HALF_UP)
    return t


def ay_gunu(yil: int, ay: int, gun: int) -> date:
    """Ayda olmayan gün → ayın son günü (28/29/30/31)."""
    son = calendar.monthrange(int(yil), int(ay))[1]
    return date(int(yil), int(ay), min(max(int(gun), 1), son))


def _ay_kaydir(yil: int, ay: int, n: int) -> tuple[int, int]:
    idx = (yil * 12 + (ay - 1)) + n
    return idx // 12, idx % 12 + 1


def _alan(kart, ad):
    return kart.get(ad) if isinstance(kart, dict) else getattr(kart, ad, None)


def _gun(deger) -> int | None:
    try:
        g = int(deger)
    except (TypeError, ValueError):
        return None
    return max(1, min(31, g)) if g > 0 else None


class KesimGunuTanimsiz(ValueError):
    """Kartın hesap kesim günü girilmemiş; ekstre dönemi belirlenemez."""


def limit_tanimli(limit) -> bool:
    return _d(limit) > 0


class KrediKartiEkstreService:
    """Merkezi ekstre dönem / toplam / ödeme servisi."""

    @staticmethod
    def schema_hazirla() -> None:
        from sqlalchemy import inspect, text
        from database.database import engine
        import database.models.finans  # noqa: F401

        if engine is None:
            return
        from database.gider_kart_odeme_service import schema_hazirla as gider_kart_schema_hazirla

        gider_kart_schema_hazirla()
        KrediKartiEkstre.__table__.create(engine, checkfirst=True)
        KrediKartiEkstreOdeme.__table__.create(engine, checkfirst=True)
        from database.kart_bakiye_gecis import schema_hazirla as kart_bakiye_schema_hazirla

        kart_bakiye_schema_hazirla()
        insp = inspect(engine)
        if not insp.has_table("kredi_karti_tanimlari"):
            return
        mevcut = {c["name"] for c in insp.get_columns("kredi_karti_tanimlari")}
        ekstra = {
            "kesimden_sonra_odeme_gun": "INTEGER",
            "para_birimi": "VARCHAR(10)",
            "bagli_hesap_id": "INTEGER",
            "odeme_hesap_id": "INTEGER",
            "tatil_odeme_kurali": "VARCHAR(20)",
        }
        eksik = {a: t for a, t in ekstra.items() if a not in mevcut}
        if not eksik:
            return
        with engine.begin() as conn:
            for alan, tip in eksik.items():
                conn.execute(text(f'ALTER TABLE "kredi_karti_tanimlari" ADD COLUMN "{alan}" {tip}'))

    # --- Dönem kuralları (gün tanımsızsa tahmin yapılmaz) ---

    @staticmethod
    def kesim_gunu(kart: KrediKartiTanimi | dict) -> int | None:
        return _gun(_alan(kart, "hesap_kesim_gunu"))

    @staticmethod
    def kart_gunleri(kart: KrediKartiTanimi | dict) -> tuple[int | None, int | None]:
        """(kesim günü, son ödeme günü); girilmemiş gün None döner."""
        return _gun(_alan(kart, "hesap_kesim_gunu")), _gun(_alan(kart, "son_odeme_gunu"))

    @staticmethod
    def _kesim_gunu_zorunlu(kart) -> int:
        g = KrediKartiEkstreService.kesim_gunu(kart)
        if g is None:
            raise KesimGunuTanimsiz(
                f"{_alan(kart, 'kart_adi') or 'Kart'} için hesap kesim günü tanımlı değil; ekstre dönemi belirlenemez."
            )
        return g

    @staticmethod
    def son_odeme_bilinir(kart: KrediKartiTanimi | dict) -> bool:
        sonra = _alan(kart, "kesimden_sonra_odeme_gun")
        if sonra is not None and str(sonra).strip() != "":
            try:
                int(sonra)
                return True
            except (TypeError, ValueError):
                pass
        return _gun(_alan(kart, "son_odeme_gunu")) is not None

    @staticmethod
    def son_odeme_hesapla(kesim_tarihi: date, kart: KrediKartiTanimi | dict) -> date | None:
        """Kartın kuralına göre son ödeme tarihi; son ödeme günü girilmemişse None (tahmin edilmez)."""
        sonra = _alan(kart, "kesimden_sonra_odeme_gun")
        if sonra is not None and str(sonra).strip() != "":
            try:
                return kesim_tarihi + timedelta(days=int(sonra))
            except (TypeError, ValueError):
                pass
        odeme_gunu = _gun(_alan(kart, "son_odeme_gunu"))
        if odeme_gunu is None:
            return None
        kesim_gunu = KrediKartiEkstreService.kesim_gunu(kart) or kesim_tarihi.day
        if odeme_gunu >= kesim_gunu:
            return ay_gunu(kesim_tarihi.year, kesim_tarihi.month, odeme_gunu)
        y, a = _ay_kaydir(kesim_tarihi.year, kesim_tarihi.month, 1)
        return ay_gunu(y, a, odeme_gunu)

    @staticmethod
    def _donem(kesim: date, kesim_gunu: int, kart) -> dict:
        oy, oa = _ay_kaydir(kesim.year, kesim.month, -1)
        onceki = ay_gunu(oy, oa, kesim_gunu)
        return {
            "kesim_tarihi": kesim,
            "donem_baslangic": onceki + timedelta(days=1),
            "donem_bitis": kesim,
            "son_odeme_tarihi": KrediKartiEkstreService.son_odeme_hesapla(kesim, kart),
        }

    @staticmethod
    def donem_bilgisi(
        islem_tarihi: date,
        kart: KrediKartiTanimi | dict,
    ) -> dict[str, date]:
        """İşlem tarihinin dahil olduğu ekstre dönemi.

        Kesim günü döneme DAHİL. Dönem: (önceki_kesim+1) .. kesim. Kesim günü yoksa KesimGunuTanimsiz.
        """
        kesim_gunu = KrediKartiEkstreService._kesim_gunu_zorunlu(kart)
        kesim = ay_gunu(islem_tarihi.year, islem_tarihi.month, kesim_gunu)
        if islem_tarihi > kesim:
            y, m = _ay_kaydir(islem_tarihi.year, islem_tarihi.month, 1)
            kesim = ay_gunu(y, m, kesim_gunu)
        return KrediKartiEkstreService._donem(kesim, kesim_gunu, kart)

    @staticmethod
    def taksit_donem_bilgisi(
        cekim_tarihi: date,
        taksit_no: int,
        kart: KrediKartiTanimi | dict,
    ) -> dict[str, date]:
        """Taksit n → çekim döneminden (n-1) ay sonraki ekstre."""
        base = KrediKartiEkstreService.donem_bilgisi(cekim_tarihi, kart)
        n = max(1, int(taksit_no or 1))
        if n == 1:
            return base
        kesim_gunu = KrediKartiEkstreService._kesim_gunu_zorunlu(kart)
        y, a = _ay_kaydir(base["kesim_tarihi"].year, base["kesim_tarihi"].month, n - 1)
        return KrediKartiEkstreService._donem(ay_gunu(y, a, kesim_gunu), kesim_gunu, kart)

    @staticmethod
    def kesim_donemi(kesim_tarihi: date, kart: KrediKartiTanimi | dict) -> dict[str, date]:
        """Verilen hesap kesim tarihinin ekstre dönemi (önceki kesim + 1 .. kesim) ve son ödeme tarihi."""
        kesim_gunu = KrediKartiEkstreService.kesim_gunu(kart) or kesim_tarihi.day
        return KrediKartiEkstreService._donem(kesim_tarihi, kesim_gunu, kart)

    @staticmethod
    def taksit_kesimi(odeme: KrediKartiOdeme, taksit: KrediKartiOdemeTaksit,
                      kart: KrediKartiTanimi | dict) -> dict[str, date] | None:
        """Taksitin ekstre dönemi: banka planında kayıtlı kesim varsa o, yoksa çekim tarihi + taksit no kuralı.

        Kayıtlı kesim yok ve kartın kesim günü tanımsızsa None (dönem belirsiz; borca yine girer).
        """
        kesim = getattr(taksit, "ekstre_kesim_tarihi", None)
        if kesim is not None:
            return KrediKartiEkstreService.kesim_donemi(kesim, kart)
        if KrediKartiEkstreService.kesim_gunu(kart) is None:
            return None
        return KrediKartiEkstreService.taksit_donem_bilgisi(odeme.tarih, taksit.taksit_no, kart)

    @staticmethod
    def kesim_gecerli_mi(kesim_tarihi: date, kart: KrediKartiTanimi | dict) -> bool:
        kesim_gunu = KrediKartiEkstreService.kesim_gunu(kart)
        if kesim_gunu is None:
            return False
        return kesim_tarihi == ay_gunu(kesim_tarihi.year, kesim_tarihi.month, kesim_gunu)

    @staticmethod
    def kesim_ay_sonra(kesim_tarihi: date, n: int, kart: KrediKartiTanimi | dict) -> date:
        """Kartın kesim gününe göre n ay sonraki kesim (ayda olmayan gün → ay sonu)."""
        kesim_gunu = KrediKartiEkstreService.kesim_gunu(kart) or kesim_tarihi.day
        y, a = _ay_kaydir(kesim_tarihi.year, kesim_tarihi.month, n)
        return ay_gunu(y, a, kesim_gunu)

    @staticmethod
    def ilk_kesim_secenekleri(kart: KrediKartiTanimi | dict, islem_tarihi: date, adet: int = 4) -> list[date]:
        """İşlemin girdiği ekstre kesimi ve sonraki dönemler (banka ilk taksiti erteleyebilir).

        Kesim günü tanımsızsa boş liste.
        """
        if KrediKartiEkstreService.kesim_gunu(kart) is None:
            return []
        ilk = KrediKartiEkstreService.donem_bilgisi(islem_tarihi, kart)["kesim_tarihi"]
        return [KrediKartiEkstreService.kesim_ay_sonra(ilk, i, kart) for i in range(max(1, adet))]

    @staticmethod
    def obligation_key(kredi_karti_id: int, kesim_tarihi: date) -> str:
        return f"{KAYNAK_KK_EKSTRE}:{int(kredi_karti_id)}:{kesim_tarihi.isoformat()}"

    @staticmethod
    def _durum_hesapla(
        toplam: Decimal,
        odenen: Decimal,
        son_odeme: date | None,
        *,
        bugun: date | None = None,
        kesin: bool = True,
    ) -> str:
        bugun = bugun or date.today()
        kalan = (toplam - odenen).quantize(KURUS, rounding=ROUND_HALF_UP)
        if odenen > toplam and toplam >= 0:
            return DURUM_FAZLA
        if kalan <= 0 and odenen > 0:
            return DURUM_ODENDI
        if son_odeme is None:
            # Son ödeme günü bilinmeden gecikmiş / zamanında denemez
            return DURUM_EKSIK
        if odenen > 0 and kalan > 0:
            if kesin and son_odeme < bugun:
                return DURUM_GECIKMIS
            return DURUM_KISMI
        if not kesin:
            return DURUM_KESILMEMIS
        if son_odeme < bugun and kalan > 0:
            return DURUM_GECIKMIS
        return DURUM_KESILMIS

    # --- Ortak borç hesabı ---

    @staticmethod
    def _odeme_gecerli(o: KrediKartiEkstreOdeme, tarih: date | None) -> bool:
        """Ödeme ``tarih`` itibarıyla geçerli mi (iptal edilen ödeme iptal tarihine kadar geçerli)."""
        if tarih is None:
            return not o.iptal
        if o.tarih and o.tarih > tarih:
            return False
        if not o.iptal:
            return True
        iptal_gunu = o.iptal_islem_tarihi or (o.iptal_tarihi.date() if o.iptal_tarihi else None)
        return iptal_gunu is not None and iptal_gunu > tarih

    @staticmethod
    def donem_borclari(session, *, tarih: date | None = None,
                       kart_ids: list[int] | None = None, sadece_aktif: bool = False) -> dict[int, dict]:
        """Kart bazında dönem borçları (salt okunur, verilen oturumda).

        ``tarih`` verilirse o güne kadar kaydedilmiş harcama ve ödemeler; iptal edilmiş ekstre ödemesi
        ödeme tarihi ile iptal tarihi arasında geçerli sayılır.
        Dönüş: {kart_id: {"kart", "donemler": {kesim: {...}}, "belirsiz": Decimal, "belirsiz_satirlar",
        "harcama", "odenen", "toplam_borc"}}
        """
        q = select(KrediKartiTanimi)
        if kart_ids is not None:
            q = q.where(KrediKartiTanimi.id.in_([int(k) for k in kart_ids]))
        if sadece_aktif:
            q = q.where(KrediKartiTanimi.aktif.is_(True))
        kartlar = {int(k.id): k for k in session.scalars(q).all()}
        sonuc: dict[int, dict] = {
            kid: {"kart": k, "donemler": {}, "belirsiz": SIFIR, "belirsiz_satirlar": [],
                  "harcama": SIFIR, "odenen": SIFIR, "toplam_borc": SIFIR}
            for kid, k in kartlar.items()
        }
        if not kartlar:
            return sonuc

        def donem_al(kid: int, donem: dict) -> dict:
            g = sonuc[kid]["donemler"].get(donem["kesim_tarihi"])
            if g is None:
                g = {**donem, "kart_id": kid, "toplam": SIFIR, "odenen": SIFIR, "satirlar": [],
                     "ekstre_id": None, "odemeler": []}
                sonuc[kid]["donemler"][donem["kesim_tarihi"]] = g
            return g

        q = (select(KrediKartiOdemeTaksit).join(KrediKartiOdeme)
             .where(KrediKartiOdeme.kredi_karti_id.in_(list(kartlar)), KrediKartiOdeme.durum == "AÇIK")
             .options(selectinload(KrediKartiOdemeTaksit.odeme))
             .order_by(KrediKartiOdemeTaksit.vade_tarihi, KrediKartiOdemeTaksit.id))
        if tarih is not None:
            q = q.where(KrediKartiOdeme.tarih <= tarih)
        for t in session.scalars(q).all():
            o = t.odeme
            kid = int(o.kredi_karti_id)
            kart = kartlar[kid]
            tutar = _d(t.tutar)
            satir = {
                "taksit_id": t.id,
                "odeme_id": o.id,
                "belge_no": o.belge_no,
                "islem_tarihi": o.tarih,
                "aciklama": o.aciklama or f"KK ödeme {o.belge_no}",
                "is_yeri": "",
                "islem_turu": o.cekim_turu,
                "tek_cekim_taksit": (
                    "Tek çekim" if o.cekim_turu == "TEK_CEKIM"
                    else "İade" if o.cekim_turu == "IADE"
                    else "Kayıt düzeltmesi" if o.cekim_turu == "DUZELTME"
                    else f"Taksit {t.taksit_no}/{o.taksit_sayisi}"
                ),
                "taksit_no": t.taksit_no,
                "taksit_sayisi": o.taksit_sayisi,
                "tutar": tutar,
                "borc": tutar if tutar > 0 else SIFIR,
                "alacak": -tutar if tutar < 0 else SIFIR,
                "etki": tutar,
                "kaynak_evrak": o.belge_no,
                "taksit_durum": t.durum,
                "gider_kart_odeme_id": getattr(o, "gider_kart_odeme_id", None),
                "kaynak_gider": "",
            }
            sonuc[kid]["harcama"] += tutar
            donem = KrediKartiEkstreService.taksit_kesimi(o, t, kart)
            if donem is None:
                sonuc[kid]["belirsiz"] += tutar
                sonuc[kid]["belirsiz_satirlar"].append(satir)
                continue
            g = donem_al(kid, donem)
            g["toplam"] += tutar
            g["satirlar"].append(satir)

        eq = (select(KrediKartiEkstre, KrediKartiEkstreOdeme)
              .join(KrediKartiEkstreOdeme, KrediKartiEkstreOdeme.ekstre_id == KrediKartiEkstre.id)
              .where(KrediKartiEkstre.kredi_karti_id.in_(list(kartlar)))
              .order_by(KrediKartiEkstreOdeme.tarih, KrediKartiEkstreOdeme.id))
        for e, od in session.execute(eq).all():
            kid = int(e.kredi_karti_id)
            gecerli = KrediKartiEkstreService._odeme_gecerli(od, tarih)
            if tarih is not None and od.tarih and od.tarih > tarih:
                continue
            g = sonuc[kid]["donemler"].get(e.kesim_tarihi)
            if g is None:
                g = donem_al(kid, KrediKartiEkstreService.kesim_donemi(e.kesim_tarihi, kartlar[kid]))
            g["odemeler"].append(od)
            if gecerli:
                g["odenen"] += _d(od.tutar)
                sonuc[kid]["odenen"] += _d(od.tutar)
        for e in session.scalars(select(KrediKartiEkstre)
                                 .where(KrediKartiEkstre.kredi_karti_id.in_(list(kartlar)))).all():
            g = sonuc[int(e.kredi_karti_id)]["donemler"].get(e.kesim_tarihi)
            if g is not None:
                g["ekstre_id"] = e.id

        gko_ids = {s["gider_kart_odeme_id"] for k in sonuc.values()
                   for s in [x for g in k["donemler"].values() for x in g["satirlar"]] + k["belirsiz_satirlar"]
                   if s["gider_kart_odeme_id"]}
        metin = {}
        if gko_ids:
            from database.gider_kart_odeme_service import kaynak_metinleri

            metin = kaynak_metinleri(session, gko_ids)
        for k in sonuc.values():
            for g in k["donemler"].values():
                g["toplam"] = _d(g["toplam"])
                g["odenen"] = _d(g["odenen"])
                g["net"] = _d(g["toplam"] - g["odenen"])
                g["kalan"] = max(g["net"], SIFIR)
            k["toplam_borc"] = _d(k["harcama"] - k["odenen"])
            for s in [x for g in k["donemler"].values() for x in g["satirlar"]] + k["belirsiz_satirlar"]:
                if s["gider_kart_odeme_id"]:
                    s["kaynak_gider"] = metin.get(int(s["gider_kart_odeme_id"]), "")
        return sonuc

    @staticmethod
    def borc_ozeti_hesapla(veri: dict, *, bugun: date | None = None, kesim: date | None = None) -> dict:
        """``donem_borclari`` kart kaydından ekranlarda gösterilen dört tutar ve limit bilgisi."""
        bugun = bugun or date.today()
        kart = veri["kart"]
        limit = _d(getattr(kart, "kart_limiti", None))
        tanimli = limit_tanimli(limit)
        kullanilan = veri["toplam_borc"]
        kesilmis = sum((g["kalan"] for k, g in veri["donemler"].items() if k <= bugun), SIFIR)
        return {
            "kredi_karti_id": int(kart.id),
            "kart_adi": kart.kart_adi,
            "toplam_borc": kullanilan,
            "kesilmis_kalan": _d(kesilmis),
            "bu_ekstrede_kalan": (veri["donemler"][kesim]["kalan"]
                                  if kesim is not None and kesim in veri["donemler"] else None),
            "kesilmemis": _d(sum((g["kalan"] for k, g in veri["donemler"].items() if k > bugun), SIFIR)),
            "belirsiz": _d(veri["belirsiz"]),
            "kullanilan": kullanilan,
            "limit": limit if tanimli else None,
            "limit_tanimli": tanimli,
            "kullanilabilir": _d(limit - kullanilan) if tanimli else None,
            "kesim_gunu_tanimli": KrediKartiEkstreService.kesim_gunu(kart) is not None,
            "son_odeme_tanimli": KrediKartiEkstreService.son_odeme_bilinir(kart),
        }

    @staticmethod
    def kart_borc_ozeti(kredi_karti_id: int, *, tarih: date | None = None, kesim: date | None = None,
                        session=None) -> dict:
        """Tek kartın toplam borcu, kullanılan / kullanılabilir limiti (limit 0/boş → tanımsız)."""
        if session is None:
            KrediKartiEkstreService.schema_hazirla()
            with get_session() as s:
                return KrediKartiEkstreService.kart_borc_ozeti(kredi_karti_id, tarih=tarih, kesim=kesim, session=s)
        veri = KrediKartiEkstreService.donem_borclari(session, tarih=tarih, kart_ids=[int(kredi_karti_id)])
        if int(kredi_karti_id) not in veri:
            raise ValueError("Kredi kartı bulunamadı.")
        return KrediKartiEkstreService.borc_ozeti_hesapla(veri[int(kredi_karti_id)], bugun=tarih, kesim=kesim)

    @staticmethod
    def limit_kontrol(session, kart: KrediKartiTanimi, ek_tutar) -> None:
        """Yeni harcama (``ek_tutar``, henüz kaydedilmemiş) limiti aşarsa hata; limit tanımsızsa kontrol yapılmaz."""
        ek = _d(ek_tutar)
        if ek <= 0:
            return
        oz = KrediKartiEkstreService.kart_borc_ozeti(int(kart.id), session=session)
        if not oz["limit_tanimli"]:
            return
        if oz["kullanilan"] + ek > oz["limit"] + Decimal("0.001"):
            from database.finans_service import _fmt

            raise ValueError(
                f"Kart limiti yetersiz. Limit {_fmt(oz['limit'])}, kullanılan {_fmt(oz['kullanilan'])}, "
                f"kullanılabilir {_fmt(oz['kullanilabilir'])}, tutar {_fmt(ek)}."
            )

    @staticmethod
    def kart_hesabi(session, kart: KrediKartiTanimi) -> FinansHesabi | None:
        """Kartın bankasındaki kredi kartı finans hesabı (borç bakiyesi tutan hesap)."""
        return session.scalar(select(FinansHesabi).where(
            FinansHesabi.banka_karti_id == kart.banka_karti_id,
            FinansHesabi.alt_hesap_turu == "KREDI_KARTI").order_by(FinansHesabi.id))

    # --- Ekstre satırları ---

    @staticmethod
    def ekstreleri_hesapla(
        *,
        bugun: date | None = None,
        kredi_karti_id: int | None = None,
        odenenleri_dahil: bool = True,
    ) -> list[dict[str, Any]]:
        """Tüm (veya tek) kart için ekstre ana satırları — mükerrersiz."""
        KrediKartiEkstreService.schema_hazirla()
        bugun = bugun or date.today()
        sonuc: list[dict[str, Any]] = []
        with get_session() as session:
            from database.models.finans import BankaKarti

            veri = KrediKartiEkstreService.donem_borclari(
                session, kart_ids=[int(kredi_karti_id)] if kredi_karti_id else None, sadece_aktif=True)
            for kid, kv in veri.items():
                kart = kv["kart"]
                ozet = KrediKartiEkstreService.borc_ozeti_hesapla(kv, bugun=bugun)
                bk = session.get(BankaKarti, kart.banka_karti_id) if kart.banka_karti_id else None
                banka_adi = getattr(kart, "kart_bankasi", None) or (bk.banka_adi if bk else "") or ""
                for kesim, g in sorted(kv["donemler"].items()):
                    toplam, odenen, kalan = g["toplam"], g["odenen"], g["net"]
                    son_odeme = g["son_odeme_tarihi"]
                    kesin = kesim <= bugun
                    durum = KrediKartiEkstreService._durum_hesapla(
                        toplam, odenen, son_odeme, bugun=bugun, kesin=kesin)
                    ekstre = session.get(KrediKartiEkstre, g["ekstre_id"]) if g["ekstre_id"] else None
                    if ekstre is None:
                        ekstre = KrediKartiEkstre(
                            kredi_karti_id=kid, kesim_tarihi=kesim, donem_baslangic=g["donem_baslangic"],
                            donem_bitis=g["donem_bitis"], son_odeme_tarihi=son_odeme,
                            para_birimi=getattr(kart, "para_birimi", None) or "TRY")
                        session.add(ekstre)
                        session.flush()
                    ekstre.donem_baslangic = g["donem_baslangic"]
                    ekstre.donem_bitis = g["donem_bitis"]
                    ekstre.son_odeme_tarihi = son_odeme
                    ekstre.toplam_borc = toplam
                    ekstre.odenen = odenen
                    ekstre.kalan = max(kalan, SIFIR)
                    ekstre.durum = durum
                    ekstre.kesin = kesin
                    ekstre.guncelleme = datetime.now()
                    if not odenenleri_dahil and (durum == DURUM_ODENDI or kalan <= 0):
                        continue
                    vade = son_odeme or kesim
                    etiket = "Kredi Kartı Ekstresi" if kesin else "Bekleyen Ekstre"
                    sonuc.append({
                        "ekstre_id": ekstre.id,
                        "obligation_key": KrediKartiEkstreService.obligation_key(kid, kesim),
                        "source_type": KAYNAK_KK_EKSTRE,
                        "source_id": f"{kid}:{kesim.isoformat()}",
                        "kredi_karti_id": kid,
                        "due_date": vade,
                        "payment_month": (vade.year, vade.month),
                        "kesim_tarihi": kesim,
                        "donem_baslangic": g["donem_baslangic"],
                        "donem_bitis": g["donem_bitis"],
                        "son_odeme_tarihi": son_odeme,
                        "son_odeme_bilinir": son_odeme is not None,
                        "aciklama": (
                            f"{kart.kart_adi}"
                            f"{(' •••• ' + kart.son_dort_hane) if kart.son_dort_hane else ''} "
                            f"— {g['donem_baslangic'].strftime('%d.%m.%Y')}–"
                            f"{g['donem_bitis'].strftime('%d.%m.%Y')}"
                        ).strip(),
                        "kaynak_etiket": etiket,
                        "banka_adi": banka_adi,
                        "kart_adi": kart.kart_adi,
                        "son_dort_hane": kart.son_dort_hane or "",
                        "belge_no": f"EKSTRE-{kid}-{kesim.isoformat()}",
                        "kategori": "Kredi kartı ekstresi",
                        "para_birimi": getattr(kart, "para_birimi", None) or "TRY",
                        "orijinal_tutar": toplam,
                        "tl_tutar": toplam,
                        "odenen": odenen,
                        "kalan": max(kalan, SIFIR),
                        "anapara": SIFIR,
                        "faiz": SIFIR,
                        "masraf": SIFIR,
                        "certainty": "KESIN" if kesin else "TAHMINI",
                        "oncelik": "YUKSEK",
                        "durum": (
                            "ODENDI" if durum == DURUM_ODENDI
                            else "KISMEN_ODENDI" if durum == DURUM_KISMI
                            else "GECIKMIS" if durum == DURUM_GECIKMIS
                            else DURUM_EKSIK if durum == DURUM_EKSIK
                            else "PLANLANDI"
                        ),
                        "ekstre_durum": durum,
                        "kesin": kesin,
                        "detay_satirlari": list(g["satirlar"]),
                        "kart_limiti": _d(getattr(kart, "kart_limiti", 0) or 0),
                        "kart_ozeti": {**ozet, "bu_ekstrede_kalan": max(kalan, SIFIR)},
                        "odemeler": [KrediKartiEkstreService._odeme_sozlugu(o) for o in g["odemeler"]],
                    })
            session.flush()
        sonuc.sort(key=lambda s: (s["due_date"], s.get("kart_adi") or ""))
        return sonuc

    @staticmethod
    def _odeme_sozlugu(o: KrediKartiEkstreOdeme) -> dict:
        return {
            "id": o.id, "belge_no": o.belge_no, "tarih": o.tarih, "tutar": _d(o.tutar),
            "finans_hesap_id": o.finans_hesap_id, "dekont_no": o.dekont_no, "aciklama": o.aciklama,
            "kaynak": o.kaynak or "EKSTRE", "iptal": bool(o.iptal),
            "iptal_tarihi": o.iptal_islem_tarihi, "iptal_nedeni": o.iptal_nedeni,
            "iptal_kullanici": o.iptal_kullanici,
        }

    @staticmethod
    def ekstre_detay(ekstre_id: int | None = None, *, source_id: str | None = None) -> dict:
        KrediKartiEkstreService.schema_hazirla()
        with get_session() as session:
            ekstre = None
            if ekstre_id:
                ekstre = session.get(KrediKartiEkstre, int(ekstre_id))
            elif source_id and ":" in source_id:
                kid_s, kesim_s = source_id.split(":", 1)
                ekstre = session.scalar(
                    select(KrediKartiEkstre).where(
                        KrediKartiEkstre.kredi_karti_id == int(kid_s),
                        KrediKartiEkstre.kesim_tarihi == date.fromisoformat(kesim_s),
                    )
                )
            if not ekstre:
                raise ValueError("Ekstre bulunamadı.")
            kart_id, kesim = ekstre.kredi_karti_id, ekstre.kesim_tarihi
        for h in KrediKartiEkstreService.ekstreleri_hesapla(kredi_karti_id=kart_id, odenenleri_dahil=True):
            if h.get("kesim_tarihi") == kesim:
                return h
        raise ValueError("Ekstre detayı hesaplanamadı.")

    @staticmethod
    def acik_ekstreler(kredi_karti_id: int) -> list[dict]:
        """Ödeme yapılabilecek (kalanı olan) ekstreler; virman / kasadan yatırma seçim listesi için."""
        return [h for h in KrediKartiEkstreService.ekstreleri_hesapla(
            kredi_karti_id=int(kredi_karti_id), odenenleri_dahil=False) if h["kalan"] > 0]

    @staticmethod
    def kart_hesabindan_kart(session, finans_hesap_id: int) -> KrediKartiTanimi | None:
        """Kredi kartı finans hesabına bağlı (aynı bankadaki) ilk aktif kart."""
        fh = session.get(FinansHesabi, int(finans_hesap_id))
        if fh is None or (fh.alt_hesap_turu or "").upper() != "KREDI_KARTI" or not fh.banka_karti_id:
            return None
        return session.scalar(select(KrediKartiTanimi).where(
            KrediKartiTanimi.banka_karti_id == fh.banka_karti_id).order_by(
            KrediKartiTanimi.aktif.desc(), KrediKartiTanimi.id))

    # --- Ödeme / iptal ---

    @staticmethod
    def _taksit_durumlarini_esitle(session, ekstre: KrediKartiEkstre, kart: KrediKartiTanimi) -> None:
        """Ekstre dönemindeki taksitlerin ödenme durumunu geçerli ödemelerden yeniden kurar.

        İade (eksi) satırları dönem borcunu azaltır; ödemeler ve iade alacağı taksitlere sırayla dağıtılır,
        kısmi paylar bağlantı tablosunda tutulur. Taksit yalnız tamamı karşılanınca ÖDENDİ olur.
        """
        session.flush()
        q = (select(KrediKartiOdemeTaksit).join(KrediKartiOdeme)
             .where(KrediKartiOdeme.kredi_karti_id == int(kart.id), KrediKartiOdeme.durum == "AÇIK",
                    KrediKartiOdemeTaksit.durum.in_(("BEKLIYOR", "ODENDI")))
             .options(selectinload(KrediKartiOdemeTaksit.odeme))
             .order_by(KrediKartiOdeme.tarih, KrediKartiOdeme.id, KrediKartiOdemeTaksit.taksit_no,
                       KrediKartiOdemeTaksit.id))
        taksitler, alacak = [], SIFIR
        for t in session.scalars(q).all():
            donem = KrediKartiEkstreService.taksit_kesimi(t.odeme, t, kart)
            if donem is None or donem["kesim_tarihi"] != ekstre.kesim_tarihi:
                continue
            if _d(t.tutar) < 0:
                alacak += -_d(t.tutar)
            else:
                taksitler.append(t)
        kalan = {t.id: _d(t.tutar) for t in taksitler}

        def dagit(tutar: Decimal, odeme_id: int | None) -> None:
            for t in taksitler:
                if tutar <= 0:
                    break
                pay = min(kalan[t.id], tutar)
                if pay <= 0:
                    continue
                kalan[t.id] -= pay
                tutar -= pay
                if odeme_id is not None:
                    session.add(KrediKartiEkstreOdemeTaksit(ekstre_odeme_id=odeme_id, taksit_id=t.id, tutar=pay))

        odemeler = list(session.scalars(select(KrediKartiEkstreOdeme).where(
            KrediKartiEkstreOdeme.ekstre_id == ekstre.id).order_by(
            KrediKartiEkstreOdeme.tarih, KrediKartiEkstreOdeme.id)).all())
        gecerli = [o for o in odemeler if not o.iptal]
        if gecerli:
            for bag in session.scalars(select(KrediKartiEkstreOdemeTaksit).where(
                    KrediKartiEkstreOdemeTaksit.ekstre_odeme_id.in_([o.id for o in gecerli]),
                    KrediKartiEkstreOdemeTaksit.iptal.is_(False))).all():
                session.delete(bag)
            session.flush()
        dagit(alacak, None)
        for o in gecerli:
            dagit(_d(o.tutar), o.id)
        for t in taksitler:
            t.durum = "ODENDI" if kalan[t.id] <= Decimal("0.001") else "BEKLIYOR"
        session.flush()

    @staticmethod
    def odeme_yap(
        *,
        ekstre_id: int,
        tutar,
        tarih: date | None = None,
        hesap_adi: str | None = None,
        finans_hesap_id: int | None = None,
        dekont_no: str | None = None,
        aciklama: str | None = None,
        tamami: bool = False,
        istek_anahtari: str | None = None,
        kaynak: str = "EKSTRE",
        bakiye_kontrol: bool = False,
        session=None,
        belge_no: str | None = None,
    ) -> dict:
        """Ekstre ödemesi: ödeme hesabından çıkış + kart hesabındaki borcu azaltan hareket (aynı belge),
        ekstre ödemesi kaydı, taksit eşleştirmesi ve muhasebe fişi tek işlemde.

        ``istek_anahtari`` ile tekrarlanan istek yeni kayıt üretmez. ``session`` verilirse (virman /
        kasadan yatırma) çağıranın işlemi içinde yazılır ve detay yeniden hesaplanmaz.
        """
        yazma_zorunlu("finans_duzenleme")
        if not (
            yetki_var("finans_duzenleme")
            or yetki_var("odeme_durumu_goruntuleme")
            or yetki_var("finans_goruntuleme")
        ):
            raise PermissionError("Ekstre ödeme yetkiniz yok.")
        if kaynak not in ODEME_KAYNAKLARI:
            raise ValueError("Geçersiz ödeme kaynağı.")
        if session is None:
            KrediKartiEkstreService.schema_hazirla()
        tarih = tarih or date.today()
        if tarih > date.today():
            raise ValueError("Ödeme tarihi gelecek olamaz.")
        if not finans_hesap_id and not (hesap_adi or "").strip():
            raise ValueError("Ödemenin yapılacağı kasa veya banka hesabını seçin.")
        anahtar = (istek_anahtari or "").strip() or None

        def yaz(s) -> dict:
            if anahtar:
                onceki = s.scalar(select(KrediKartiEkstreOdeme).where(
                    KrediKartiEkstreOdeme.istek_anahtari == anahtar))
                if onceki is not None:
                    return {"belge_no": onceki.belge_no, "tutar": _d(onceki.tutar), "mevcut": True,
                            "odeme_id": onceki.id}
            ekstre = s.get(KrediKartiEkstre, int(ekstre_id))
            if not ekstre:
                raise ValueError("Ekstre bulunamadı.")
            kart = s.get(KrediKartiTanimi, ekstre.kredi_karti_id)
            if not kart:
                raise ValueError("Kart bulunamadı.")
            if finans_hesap_id:
                hesap = s.get(FinansHesabi, int(finans_hesap_id))
            else:
                adaylar = list(s.scalars(select(FinansHesabi).where(
                    FinansHesabi.hesap_adi == hesap_adi.strip())).all())
                if len(adaylar) > 1:
                    raise ValueError("Aynı adda birden çok hesap var; hesabı listeden seçin.")
                hesap = adaylar[0] if adaylar else None
            if hesap is None:
                raise ValueError("Geçerli bir kasa veya banka hesabı seçin.")
            tur, alt = (hesap.hesap_turu or "").upper(), (hesap.alt_hesap_turu or "").upper()
            if tur != "KASA" and alt not in ("MEVDUAT", "KMH", "VADELI"):
                raise ValueError("Ekstre ödemesi yalnız kasa veya vadesiz / KMH banka hesabından yapılır.")
            kart_hesap = KrediKartiEkstreService.kart_hesabi(s, kart)
            if kart_hesap is None:
                raise ValueError(f"{kart.kart_adi} bankasında kredi kartı hesabı bulunamadı.")

            veri = KrediKartiEkstreService.donem_borclari(s, kart_ids=[int(kart.id)])[int(kart.id)]
            g = veri["donemler"].get(ekstre.kesim_tarihi)
            kalan = g["kalan"] if g else SIFIR
            odeme_tutari = kalan if tamami else _d(tutar, minimum=Decimal("0.01"))
            if odeme_tutari <= 0:
                raise ValueError("Bu ekstrenin ödenecek kalanı yok.")
            if odeme_tutari > kalan + Decimal("0.01"):
                from database.finans_service import _fmt

                raise ValueError(
                    f"Ödeme tutarı ekstrede kalan borçtan ({_fmt(kalan)}) büyük olamaz. "
                    "Fazla ödeme için kalan kadar ödeyin."
                )
            if bakiye_kontrol:
                from database.finans_service import FinansService

                FinansService.cikis_kontrol(hesap, odeme_tutari, hesap_etiket=hesap.hesap_adi)

            from database.finans_service import FinansService

            bno = belge_no or FinansService._finans_belge_no(s, "KKE")
            metin = (aciklama or "").strip() or (
                f"{kart.kart_adi} ekstre {ekstre.kesim_tarihi.strftime('%d.%m.%Y')}")
            for hid in (hesap.id, kart_hesap.id):
                s.add(FinansHareketi(hesap_id=hid, tarih=tarih, hareket_turu=HAREKET_EKSTRE_ODEME,
                                     belge_no=bno, tutar=odeme_tutari, aciklama=metin))
            kayit = KrediKartiEkstreOdeme(
                ekstre_id=ekstre.id,
                belge_no=bno,
                tarih=tarih,
                tutar=odeme_tutari,
                hesap_turu="KASA" if tur == "KASA" else (alt or "MEVDUAT"),
                finans_hesap_id=hesap.id,
                kart_hesap_id=kart_hesap.id,
                dekont_no=(dekont_no or "").strip() or None,
                aciklama=(aciklama or "").strip() or None,
                finans_belge_no=bno,
                istek_anahtari=anahtar,
                kaynak=kaynak,
            )
            s.add(kayit)
            s.flush()
            KrediKartiEkstreService._taksit_durumlarini_esitle(s, ekstre, kart)
            from database.muhasebe_entegrasyon import muhasebe_hook

            muhasebe_hook("kk_ekstre_odeme_fisi", kayit.id, session=s)
            return {"belge_no": bno, "tutar": odeme_tutari, "mevcut": False, "odeme_id": kayit.id}

        if session is not None:
            return yaz(session)
        try:
            with get_session() as s:
                sonuc = yaz(s)
        except IntegrityError:
            if not anahtar:
                raise
            with get_session() as s:
                onceki = s.scalar(select(KrediKartiEkstreOdeme).where(
                    KrediKartiEkstreOdeme.istek_anahtari == anahtar))
                if onceki is None:
                    raise
                sonuc = {"belge_no": onceki.belge_no, "tutar": _d(onceki.tutar), "mevcut": True,
                         "odeme_id": onceki.id}
        sonuc["ekstre"] = KrediKartiEkstreService.ekstre_detay(int(ekstre_id))
        return sonuc

    @staticmethod
    def odeme_iptal(belge_no: str, neden: str | None = None, *, tarih: date | None = None) -> dict:
        """Ekstre ödemesini iptal eder: orijinal hareketler korunur, iptal tarihli ters hareketler eklenir
        (ödeme hesabına giriş, kart hesabına borç), taksit durumları ve muhasebe fişi geri alınır."""
        yazma_zorunlu("finans_duzenleme")
        neden = (neden or "").strip()
        if not neden:
            raise ValueError("İptal nedeni yazın.")
        KrediKartiEkstreService.schema_hazirla()
        tarih = tarih or date.today()
        if tarih > date.today():
            raise ValueError("İptal tarihi gelecek olamaz.")
        with get_session() as session:
            kayit = session.scalar(
                select(KrediKartiEkstreOdeme).where(KrediKartiEkstreOdeme.belge_no == belge_no)
            )
            if not kayit:
                raise ValueError("Ödeme kaydı bulunamadı.")
            if kayit.iptal:
                raise ValueError("Bu ödeme zaten iptal edilmiş.")
            if tarih < kayit.tarih:
                raise ValueError("İptal tarihi ödeme tarihinden önce olamaz.")
            from database.session_manager import oturum

            kullanici = oturum.ad_soyad or oturum.kullanici_adi or ""
            orijinal = list(session.scalars(select(FinansHareketi).where(
                FinansHareketi.belge_no == (kayit.finans_belge_no or kayit.belge_no),
                FinansHareketi.hareket_turu == HAREKET_EKSTRE_ODEME)).all())
            for h in orijinal:
                session.add(FinansHareketi(
                    hesap_id=h.hesap_id, tarih=tarih, hareket_turu=HAREKET_EKSTRE_ODEME_IPTAL,
                    belge_no=h.belge_no, tutar=h.tutar,
                    aciklama=f"İptal: {h.aciklama or ''} — {neden}"[:500]))
            kayit.iptal = True
            kayit.iptal_tarihi = datetime.now()
            kayit.iptal_islem_tarihi = tarih
            kayit.iptal_nedeni = neden[:300]
            kayit.iptal_kullanici = kullanici[:120] or None
            for bag in session.scalars(select(KrediKartiEkstreOdemeTaksit).where(
                    KrediKartiEkstreOdemeTaksit.ekstre_odeme_id == kayit.id)).all():
                bag.iptal = True
            ekstre = session.get(KrediKartiEkstre, kayit.ekstre_id)
            kart = session.get(KrediKartiTanimi, ekstre.kredi_karti_id) if ekstre else None
            if ekstre and kart:
                KrediKartiEkstreService._taksit_durumlarini_esitle(session, ekstre, kart)
            from database.muhasebe_entegrasyon import muhasebe_hook

            muhasebe_hook("kk_ekstre_odeme_iptal", kayit.id, neden, session=session)
            session.flush()
            return {"belge_no": kayit.belge_no, "tutar": _d(kayit.tutar), "iptal_tarihi": tarih}
