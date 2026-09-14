"""Döviz kuru yönetimi, TCMB aktarımı ve TL/döviz dönüşüm yardımcıları."""

from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from database.database import get_session
from database.models.doviz import (
    BORC_ESASLARI,
    KUR_KAYNAKLARI,
    KUR_TURLERI,
    PARA_BIRIMLERI,
    DovizKuru,
)

KURUS = Decimal("0.01")
KUR_HASSASIYET = Decimal("0.000001")
TCMB_PARA_MAP = {"USD": "USD", "EUR": "EUR", "EURO": "EUR"}
TCMB_GERI_GUN = 14  # hafta sonu / tatil için geriye bakış


def _d(x, ad="Değer") -> Decimal:
    try:
        return Decimal(str(x or 0))
    except Exception as exc:
        raise ValueError(f"{ad} sayısal olmalıdır.") from exc


def kur_turu_etiket(anahtar: str) -> str:
    for k, etiket in KUR_TURLERI:
        if k == anahtar:
            return etiket
    return anahtar


def kur_turu_deger(kayit: DovizKuru | dict, kur_turu: str) -> Decimal:
    get = kayit.get if isinstance(kayit, dict) else lambda a, d=0: getattr(kayit, a, d)
    return _d(get(kur_turu, get("forex_selling", 0)))


def _ayar_dosyasi() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MuhasebeProgrami" / "ayarlar"
    base.mkdir(parents=True, exist_ok=True)
    return base / "doviz_ayarlar.json"


def doviz_ayarlari_yukle() -> dict[str, Any]:
    yol = _ayar_dosyasi()
    varsayilan = {"otomatik_tcmb_cek": True}
    if not yol.exists():
        return dict(varsayilan)
    try:
        veri = json.loads(yol.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(varsayilan)
    if not isinstance(veri, dict):
        return dict(varsayilan)
    return {
        "otomatik_tcmb_cek": bool(veri.get("otomatik_tcmb_cek", True)),
    }


def doviz_ayarlari_kaydet(ayarlar: dict[str, Any]) -> None:
    mevcut = doviz_ayarlari_yukle()
    mevcut.update(ayarlar or {})
    _ayar_dosyasi().write_text(
        json.dumps(
            {"otomatik_tcmb_cek": bool(mevcut.get("otomatik_tcmb_cek", True))},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


class DovizService:
    @staticmethod
    def para_birimleri() -> tuple[str, ...]:
        return PARA_BIRIMLERI

    @staticmethod
    def kur_getir(kur_tarihi: date, currency_code: str) -> DovizKuru | None:
        if (currency_code or "TRY").upper() == "TRY":
            return None
        with get_session() as session:
            return session.scalar(
                select(DovizKuru).where(
                    DovizKuru.rate_date == kur_tarihi,
                    DovizKuru.currency_code == currency_code.upper(),
                )
            )

    @staticmethod
    def bugun_kurlar_hazir_mi(kur_tarihi: date | None = None) -> bool:
        """Hedef günde (veya en yakın iş gününde) USD ve EUR TCMB/manuel kur var mı."""
        hedef = kur_tarihi or date.today()
        for kod in ("USD", "EUR"):
            if DovizService.en_yakin_kur_tarihi(kod, hedef, geri=TCMB_GERI_GUN) is None:
                return False
        return True

    @staticmethod
    def kur_degeri(
        kur_tarihi: date,
        currency_code: str,
        kur_turu: str = "forex_selling",
        varsayilan: Decimal | None = None,
    ) -> Decimal:
        code = (currency_code or "TRY").upper()
        if code == "TRY":
            return Decimal("1")
        kayit = DovizService.kur_getir(kur_tarihi, code)
        if not kayit:
            yakin = DovizService.en_yakin_kur_tarihi(code, kur_tarihi, geri=TCMB_GERI_GUN)
            if yakin:
                kayit = DovizService.kur_getir(yakin, code)
        if kayit:
            deger = kur_turu_deger(kayit, kur_turu)
            if deger > 0:
                return deger
        if varsayilan is not None and varsayilan > 0:
            return _d(varsayilan)
        raise ValueError(f"{code} için {kur_tarihi:%d.%m.%Y} tarihli kur bulunamadı.")

    @staticmethod
    def kur_kaydet(
        kur_tarihi: date,
        currency_code: str,
        forex_buying: Decimal,
        forex_selling: Decimal,
        effective_buying: Decimal,
        effective_selling: Decimal,
        source: str = "MANUEL",
        *,
        manuel_koru: bool = True,
    ) -> DovizKuru | None:
        """Kur kaydı upsert. manuel_koru=True iken mevcut MANUEL/OZEL kayda TCMB yazılmaz."""
        code = (currency_code or "").upper()
        if code not in ("USD", "EUR"):
            raise ValueError("Yalnızca USD ve EUR kurları kaydedilebilir.")
        if source not in KUR_KAYNAKLARI:
            raise ValueError("Geçersiz kur kaynağı.")
        with get_session() as session:
            kayit = session.scalar(
                select(DovizKuru).where(
                    DovizKuru.rate_date == kur_tarihi,
                    DovizKuru.currency_code == code,
                )
            )
            if kayit and manuel_koru and source == "TCMB" and kayit.source in ("MANUEL", "OZEL"):
                return kayit
            if not kayit:
                kayit = DovizKuru(rate_date=kur_tarihi, currency_code=code)
                session.add(kayit)
            kayit.forex_buying = _d(forex_buying).quantize(KUR_HASSASIYET, rounding=ROUND_HALF_UP)
            kayit.forex_selling = _d(forex_selling).quantize(KUR_HASSASIYET, rounding=ROUND_HALF_UP)
            kayit.effective_buying = _d(effective_buying).quantize(KUR_HASSASIYET, rounding=ROUND_HALF_UP)
            kayit.effective_selling = _d(effective_selling).quantize(KUR_HASSASIYET, rounding=ROUND_HALF_UP)
            kayit.source = source
            try:
                session.flush()
            except IntegrityError as hata:
                raise ValueError("Kur kaydedilemedi.") from hata
            return kayit

    @staticmethod
    def kur_listele(baslangic: date | None = None, bitis: date | None = None) -> list[DovizKuru]:
        with get_session() as session:
            stmt = select(DovizKuru).order_by(DovizKuru.rate_date.desc(), DovizKuru.currency_code)
            if baslangic:
                stmt = stmt.where(DovizKuru.rate_date >= baslangic)
            if bitis:
                stmt = stmt.where(DovizKuru.rate_date <= bitis)
            return list(session.scalars(stmt).all())

    @staticmethod
    def _tcmb_url(kur_tarihi: date) -> str:
        if kur_tarihi >= date.today():
            return "https://www.tcmb.gov.tr/kurlar/today.xml"
        yil_ay = kur_tarihi.strftime("%Y%m")
        gun_ay_yil = kur_tarihi.strftime("%d%m%Y")
        return f"https://www.tcmb.gov.tr/kurlar/{yil_ay}/{gun_ay_yil}.xml"

    @staticmethod
    def _tcmb_xml_indir(url: str) -> ET.Element:
        try:
            istek = Request(url, headers={"User-Agent": "MuhasebeProgrami/1.0"})
            with urlopen(istek, timeout=20) as yanit:
                return ET.fromstring(yanit.read())
        except HTTPError as hata:
            if hata.code == 404:
                raise ValueError(
                    "Bu tarih için TCMB kur yayınlamamış (hafta sonu veya resmi tatil olabilir)."
                ) from hata
            raise ValueError(
                f"TCMB sunucusuna erişilemedi (HTTP {hata.code}). Lütfen internet bağlantınızı kontrol edin."
            ) from hata
        except URLError as hata:
            raise ValueError(
                "TCMB kurları alınamadı. İnternet bağlantınızı kontrol edip tekrar deneyin."
            ) from hata
        except ET.ParseError as hata:
            raise ValueError("TCMB XML yanıtı okunamadı.") from hata
        except TimeoutError as hata:
            raise ValueError("TCMB yanıt vermedi (zaman aşımı). Daha sonra tekrar deneyin.") from hata

    @staticmethod
    def _tcmb_xml_parse(kok: ET.Element) -> tuple[date | None, list[dict[str, Any]]]:
        """XML'den tarih + USD/EUR kur satırlarını çıkarır.

        TCMB alanları:
        - ForexBuying / ForexSelling → döviz alış / satış
        - BanknoteBuying / BanknoteSelling → efektif alış / satış
        """
        tarih_attr = (kok.attrib.get("Tarih") or "").strip()
        tcmb_tarih: date | None = None
        if tarih_attr:
            try:
                gun, ay, yil = tarih_attr.split(".")
                tcmb_tarih = date(int(yil), int(ay), int(gun))
            except (ValueError, IndexError):
                tcmb_tarih = None

        satirlar: list[dict[str, Any]] = []
        for para in kok.findall("Currency"):
            kod = (para.attrib.get("CurrencyCode") or para.attrib.get("Kod") or "").upper()
            if kod not in TCMB_PARA_MAP:
                continue
            code = TCMB_PARA_MAP[kod]

            def _oku(tag: str) -> Decimal:
                el = para.find(tag)
                if el is None or not (el.text or "").strip():
                    return Decimal("0")
                return _d(el.text.replace(",", "."))

            fb = _oku("ForexBuying")
            fs = _oku("ForexSelling")
            # Efektif = banknot (Banknote*); yoksa döviz kuruna düş
            eb = _oku("BanknoteBuying") or fb
            es = _oku("BanknoteSelling") or fs
            if fs <= 0 and fb <= 0 and es <= 0 and eb <= 0:
                continue
            satirlar.append(
                {
                    "currency_code": code,
                    "forex_buying": fb,
                    "forex_selling": fs if fs > 0 else fb,
                    "effective_buying": eb,
                    "effective_selling": es if es > 0 else eb,
                }
            )
        return tcmb_tarih, satirlar

    @staticmethod
    def tcmb_kurlari_cek(
        kur_tarihi: date | None = None,
        *,
        hedefe_kopyala: bool = True,
    ) -> list[dict[str, Any]]:
        """TCMB'den USD/EUR döviz + efektif kurları çeker ve kaydeder.

        Hafta sonu/tatilde yayın yoksa önceki iş günlerine bakılır.
        today.xml kullanılırken XML'deki resmi tarih kaydedilir; hedefe_kopyala
        ile (manuel/özel yoksa) istenen güne de kopyalanır.
        """
        hedef = kur_tarihi or date.today()
        son_hata: Exception | None = None
        kok = None
        kullanilan_tarih = hedef

        for geri in range(TCMB_GERI_GUN + 1):
            aday = hedef - timedelta(days=geri)
            # Bugün veya gelecek → önce today.xml; geçmiş günler → tarihli URL
            if aday >= date.today() and geri == 0:
                url = "https://www.tcmb.gov.tr/kurlar/today.xml"
            else:
                url = DovizService._tcmb_url(aday)
            try:
                kok = DovizService._tcmb_xml_indir(url)
                kullanilan_tarih = aday
                break
            except ValueError as hata:
                son_hata = hata
                # today.xml başarısızsa tarihli URL dene
                if geri == 0 and aday >= date.today():
                    try:
                        kok = DovizService._tcmb_xml_indir(DovizService._tcmb_url(aday))
                        kullanilan_tarih = aday
                        break
                    except ValueError as hata2:
                        son_hata = hata2
                continue

        if kok is None:
            raise ValueError(
                str(son_hata)
                if son_hata
                else f"{hedef:%d.%m.%Y} ve önceki {TCMB_GERI_GUN} gün için TCMB kuru bulunamadı."
            )

        tcmb_tarih, ham = DovizService._tcmb_xml_parse(kok)
        kayit_tarihi = tcmb_tarih or kullanilan_tarih
        if not ham:
            raise ValueError(f"{kayit_tarihi:%d.%m.%Y} için TCMB'de USD/EUR kuru bulunamadı.")

        sonuc: list[dict[str, Any]] = []
        tarihler = {kayit_tarihi}
        if hedefe_kopyala and hedef != kayit_tarihi:
            tarihler.add(hedef)

        for tarih in sorted(tarihler):
            for sat in ham:
                kayit = DovizService.kur_kaydet(
                    tarih,
                    sat["currency_code"],
                    sat["forex_buying"],
                    sat["forex_selling"],
                    sat["effective_buying"],
                    sat["effective_selling"],
                    source="TCMB",
                    manuel_koru=True,
                )
                if kayit is None:
                    continue
                sonuc.append(
                    {
                        "rate_date": kayit.rate_date,
                        "currency_code": kayit.currency_code,
                        "forex_buying": kayit.forex_buying,
                        "forex_selling": kayit.forex_selling,
                        "effective_buying": kayit.effective_buying,
                        "effective_selling": kayit.effective_selling,
                        "source": kayit.source,
                        "tcmb_tarih": kayit_tarihi,
                        "hedef_tarih": hedef,
                    }
                )

        if not sonuc:
            raise ValueError(f"{hedef:%d.%m.%Y} için kaydedilecek TCMB kuru yok.")
        return sonuc

    @staticmethod
    def otomatik_gunluk_cek(sessiz: bool = True) -> dict[str, Any]:
        """Ayar açıksa ve bugün için kur yoksa TCMB'den çeker (açılış için)."""
        ayar = doviz_ayarlari_yukle()
        if not ayar.get("otomatik_tcmb_cek", True):
            return {"yapildi": False, "neden": "kapali"}
        bugun = date.today()
        if DovizService.bugun_kurlar_hazir_mi(bugun):
            return {"yapildi": False, "neden": "zaten_var"}
        try:
            kayitlar = DovizService.tcmb_kurlari_cek(bugun)
            return {
                "yapildi": True,
                "adet": len(kayitlar),
                "tcmb_tarih": kayitlar[0].get("tcmb_tarih") if kayitlar else bugun,
            }
        except ValueError as hata:
            if sessiz:
                return {"yapildi": False, "neden": "hata", "mesaj": str(hata)}
            raise

    @staticmethod
    def tl_den_dovize(
        tl_tutar: Decimal,
        kur: Decimal,
        kur_hassasiyet: Decimal = Decimal("0.01"),
    ) -> Decimal:
        kur = _d(kur)
        if kur <= 0:
            raise ValueError("Kur sıfırdan büyük olmalıdır.")
        return (_d(tl_tutar) / kur).quantize(kur_hassasiyet, rounding=ROUND_HALF_UP)

    @staticmethod
    def dovizden_tle(
        doviz_tutar: Decimal,
        kur: Decimal,
        kur_hassasiyet: Decimal = KURUS,
    ) -> Decimal:
        return (_d(doviz_tutar) * _d(kur)).quantize(kur_hassasiyet, rounding=ROUND_HALF_UP)

    @staticmethod
    def fatura_kur_bilgisi(
        para_birimi: str,
        kur_tarihi: date,
        kur_turu: str = "forex_selling",
        ozel_kur: Decimal | None = None,
        kaynak: str = "TCMB",
    ) -> dict[str, Any]:
        code = (para_birimi or "TRY").upper()
        if code == "TRY":
            return {
                "para_birimi": "TRY",
                "kur": Decimal("1"),
                "kur_tarihi": kur_tarihi,
                "kur_turu": kur_turu,
                "kur_kaynagi": "MANUEL",
                "kur_sabitlendi": True,
            }
        if ozel_kur is not None and _d(ozel_kur) > 0:
            return {
                "para_birimi": code,
                "kur": _d(ozel_kur).quantize(KUR_HASSASIYET, rounding=ROUND_HALF_UP),
                "kur_tarihi": kur_tarihi,
                "kur_turu": kur_turu,
                "kur_kaynagi": "OZEL" if kaynak == "OZEL" else "MANUEL",
                "kur_sabitlendi": True,
            }
        try:
            kur = DovizService.kur_degeri(kur_tarihi, code, kur_turu)
        except ValueError as hata:
            raise ValueError(
                f"{code} için {kur_tarihi:%d.%m.%Y} tarihli kur yok. "
                "TCMB'den kur getirin veya manuel kur girin."
            ) from hata
        kayit = DovizService.kur_getir(kur_tarihi, code)
        if not kayit:
            yakin = DovizService.en_yakin_kur_tarihi(code, kur_tarihi, geri=TCMB_GERI_GUN)
            if yakin:
                kayit = DovizService.kur_getir(yakin, code)
        return {
            "para_birimi": code,
            "kur": kur.quantize(KUR_HASSASIYET, rounding=ROUND_HALF_UP),
            "kur_tarihi": kur_tarihi,
            "kur_turu": kur_turu,
            "kur_kaynagi": (kayit.source if kayit else "TCMB"),
            "kur_sabitlendi": True,
        }

    @staticmethod
    def en_yakin_kur_tarihi(currency_code: str, hedef: date, geri: int = 7) -> date | None:
        code = (currency_code or "").upper()
        if code == "TRY":
            return hedef
        for gun in range(geri + 1):
            aday = hedef - timedelta(days=gun)
            if DovizService.kur_getir(aday, code):
                return aday
        return None

    @staticmethod
    def kur_farki_hesapla(
        doviz_tutar: Decimal,
        fatura_kuru: Decimal,
        odeme_kuru: Decimal,
    ) -> Decimal:
        """Döviz sabit borçta tahsilat kur farkı (TL)."""
        doviz = _d(doviz_tutar)
        fark = doviz * (_d(odeme_kuru) - _d(fatura_kuru))
        return fark.quantize(KURUS, rounding=ROUND_HALF_UP)

    @staticmethod
    def kur_farki_fisi_olustur(
        session,
        *,
        cari_id: int,
        fatura_no: str,
        tarih: date,
        kur_farki: Decimal,
        para_birimi: str,
        fatura_kuru: Decimal,
        odeme_kuru: Decimal,
        sira: int = 1,
        finans_hesap_adi: str | None = None,
    ) -> Any | None:
        """Kur farkını hizmet hareketi (+ gider ise gider fişi) olarak kaydeder.

        Cari bakiyeyi bozmaz; gelir tablosu / hizmet hareketlerinden izlenir.
        Belge no: KF-{fatura_no}-{sira} (idempotent).
        """
        from database.models.hizmet import HizmetHareketi, HizmetKarti

        fark = _d(kur_farki).quantize(KURUS, rounding=ROUND_HALF_UP)
        if fark == 0:
            return None
        belge = f"KF-{fatura_no}-{sira}"
        if len(belge) > 50:
            belge = belge[:50]
        mevcut = session.scalar(
            select(HizmetHareketi).where(
                HizmetHareketi.belge_no == belge,
                HizmetHareketi.hareket_turu == "KUR FARKI",
            )
        )
        if mevcut is not None:
            return mevcut

        tutar = abs(fark)
        pb = (para_birimi or "TRY").upper()
        aciklama = (
            f"Kur farkı ({pb}): fatura kuru {fatura_kuru}, ödeme kuru {odeme_kuru} — {fatura_no}"
        )[:500]
        kod = "KURF-GELIR" if fark > 0 else "KURF-GIDER"
        ad = "Kur Farkı Geliri" if fark > 0 else "Kur Farkı Gideri"
        tur = "GELIR" if fark > 0 else "GIDER"
        hizmet = session.scalar(select(HizmetKarti).where(HizmetKarti.hizmet_kodu == kod))
        if hizmet is None:
            hizmet = HizmetKarti(
                hizmet_kodu=kod,
                hizmet_adi=ad,
                hizmet_turu=tur,
                gider_sinifi="FINANS_MALI" if tur == "GIDER" else None,
                birim="Adet",
                kdv_orani=Decimal("0"),
                aktif=True,
            )
            session.add(hizmet)
            session.flush()

        hareket = HizmetHareketi(
            hizmet_id=hizmet.id,
            tarih=tarih,
            belge_no=belge,
            hareket_turu="KUR FARKI",
            miktar=Decimal("1"),
            birim_fiyat=tutar,
            kdv_orani=Decimal("0"),
            tutar=tutar,
            isaret=1 if fark > 0 else -1,
            cari_id=cari_id,
            aciklama=aciklama,
        )
        session.add(hareket)
        return hareket

    @staticmethod
    def kur_farki_fislerini_sil(session, fatura_no: str) -> None:
        from sqlalchemy import delete

        like = f"KF-{fatura_no}-%"
        try:
            from database.models.hizmet import HizmetHareketi

            session.execute(
                delete(HizmetHareketi).where(
                    HizmetHareketi.belge_no.like(like),
                    HizmetHareketi.hareket_turu == "KUR FARKI",
                )
            )
        except Exception:
            pass
