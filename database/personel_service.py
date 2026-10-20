"""Personel kartı, çalışma dönemi, ücret ve liste servisleri."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import and_, func, or_, select

from database.access import yetki_var, yetki_zorunlu, yazma_zorunlu
from database.database import get_session
from database.models.personel import (
    CALISMA_DURUMLARI,
    DURUM_AKTIF,
    DURUM_AYRILDI,
    KIMLIK_DIGER,
    KIMLIK_TCKN,
    KIMLIK_YABANCI,
    UCRET_NET,
    Personel,
    PersonelCalismaDonemi,
    PersonelGecmis,
    PersonelUcret,
)
from database.personel_sema import schema_hazirla
from database.session_manager import oturum
from database.user_audit import current_actor

GORUNTULEME = ("personel_goruntuleme", "personel_duzenleme", "goruntuleme")
DUZENLEME = ("personel_duzenleme", "duzenleme")
FINANS_GOR = ("personel_finans_goruntuleme", "personel_finans_duzenleme", "finans_goruntuleme")


def _kullanici() -> str:
    """Aktif oturumdaki gerçek kullanıcı kimliği; boş / admin varsayılanı yok."""
    actor = current_actor()
    return str(actor["username"])[:120]


def _para(v) -> Decimal:
    if v is None or v == "":
        return Decimal("0")
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v).replace(".", "").replace(",", ".") if isinstance(v, str) and "," in str(v) else str(v))
    except (InvalidOperation, ValueError) as e:
        raise ValueError("Geçersiz tutar.") from e


def kimlik_dogrula(tur: str, no: str | None) -> str | None:
    """Statüye göre doğrula; her personele zorunlu TCKN şartı koyma."""
    no = (no or "").strip() or None
    if no is None:
        return None
    only = re.sub(r"\D", "", no)
    if tur == KIMLIK_TCKN:
        if len(only) != 11 or only[0] == "0":
            raise ValueError("T.C. kimlik numarası 11 haneli olmalı.")
        # Algoritma kontrolü
        d = [int(c) for c in only]
        if (sum(d[0:9:2]) * 7 - sum(d[1:8:2])) % 10 != d[9]:
            raise ValueError("T.C. kimlik numarası geçersiz.")
        if sum(d[:10]) % 10 != d[10]:
            raise ValueError("T.C. kimlik numarası geçersiz.")
        return only
    if tur == KIMLIK_YABANCI:
        if len(only) < 5:
            raise ValueError("Yabancı kimlik numarası çok kısa.")
        return only
    return no[:30]


def maskele_kimlik(no: str | None) -> str:
    if not no:
        return ""
    s = str(no)
    if len(s) <= 4:
        return "*" * len(s)
    return s[:2] + "*" * (len(s) - 4) + s[-2:]


def maskele_iban(iban: str | None) -> str:
    if not iban:
        return ""
    s = re.sub(r"\s+", "", iban)
    if len(s) <= 8:
        return "*" * len(s)
    return s[:4] + "*" * (len(s) - 8) + s[-4:]


def finans_gorur() -> bool:
    return yetki_var(*FINANS_GOR) or oturum.role_kod == "YONETICI"


class PersonelService:
    @staticmethod
    def hazirla() -> None:
        schema_hazirla()

    @staticmethod
    def sonraki_kod() -> str:
        yetki_zorunlu(*GORUNTULEME)
        PersonelService.hazirla()
        with get_session() as session:
            son = session.scalar(select(func.max(Personel.kod)))
        if not son:
            return "P0001"
        m = re.search(r"(\d+)$", son)
        if not m:
            return f"P{datetime.now():%Y%m%d%H%M%S}"
        return f"P{int(m.group(1)) + 1:04d}"

    @staticmethod
    def listele(
        *,
        arama: str = "",
        durum: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        yetki_zorunlu(*GORUNTULEME)
        PersonelService.hazirla()
        maske = not finans_gorur() and not yetki_var("personel_duzenleme")
        # Yetkisiz listelerde kimlik/banka maskele — finans yoksa kimliği de maskele
        kimlik_maske = not yetki_var("personel_duzenleme") and oturum.role_kod != "YONETICI"
        with get_session() as session:
            q = select(Personel).order_by(Personel.kod)
            if durum:
                q = q.where(Personel.calisma_durumu == durum)
            a = (arama or "").strip()
            if a:
                like = f"%{a}%"
                q = q.where(
                    or_(
                        Personel.kod.ilike(like),
                        Personel.ad.ilike(like),
                        Personel.soyad.ilike(like),
                        func.concat(Personel.ad, " ", Personel.soyad).ilike(like),
                    )
                )
            satirlar = session.scalars(q.limit(limit)).all()
            sonuc = []
            for p in satirlar:
                donem = next((d for d in p.donemler if d.aktif), p.donemler[0] if p.donemler else None)
                kimlik = p.kimlik_no
                if kimlik_maske:
                    kimlik = maskele_kimlik(kimlik)
                sonuc.append(
                    {
                        "id": p.id,
                        "kod": p.kod,
                        "ad": p.ad,
                        "soyad": p.soyad,
                        "ad_soyad": f"{p.ad} {p.soyad}".strip(),
                        "kimlik_turu": p.kimlik_turu,
                        "kimlik_no": kimlik,
                        "calisma_durumu": p.calisma_durumu,
                        "gorev": donem.gorev if donem else None,
                        "sube": donem.sube if donem else None,
                        "bolum": donem.bolum if donem else None,
                        "giris_tarihi": donem.giris_tarihi.isoformat() if donem and donem.giris_tarihi else None,
                        "cikis_tarihi": donem.cikis_tarihi.isoformat() if donem and donem.cikis_tarihi else None,
                        "foto_var": p.foto is not None,
                        "_maske": maske,
                    }
                )
            return sonuc

    @staticmethod
    def getir(personel_id: int) -> dict[str, Any]:
        yetki_zorunlu(*GORUNTULEME)
        PersonelService.hazirla()
        with get_session() as session:
            p = session.get(Personel, int(personel_id))
            if p is None:
                raise ValueError("Personel bulunamadı.")
            return PersonelService._kart_dict(p, finans=finans_gorur())

    @staticmethod
    def _kart_dict(p: Personel, *, finans: bool) -> dict[str, Any]:
        donemler = []
        for d in p.donemler:
            ucretler = []
            for u in d.ucretler:
                iban = u.iban
                if not finans and not yetki_var("personel_duzenleme"):
                    iban = maskele_iban(iban)
                ucretler.append(
                    {
                        "id": u.id,
                        "ucret_turu": u.ucret_turu,
                        "tutar": float(u.tutar) if finans else None,
                        "gecerli_baslangic": u.gecerli_baslangic.isoformat() if u.gecerli_baslangic else None,
                        "odeme_gunu": u.odeme_gunu,
                        "iban": iban,
                        "banka_adi": u.banka_adi if finans or yetki_var("personel_duzenleme") else None,
                        "aciklama": u.aciklama,
                    }
                )
            donemler.append(
                {
                    "id": d.id,
                    "giris_tarihi": d.giris_tarihi.isoformat() if d.giris_tarihi else None,
                    "cikis_tarihi": d.cikis_tarihi.isoformat() if d.cikis_tarihi else None,
                    "gorev": d.gorev,
                    "bolum": d.bolum,
                    "sube": d.sube,
                    "isyeri_kodu": d.isyeri_kodu,
                    "isyeri_sicil": d.isyeri_sicil,
                    "sozlesme_turu": d.sozlesme_turu,
                    "calisma_duzeni": d.calisma_duzeni,
                    "sgk_kapsam": d.sgk_kapsam,
                    "meslek_kodu": d.meslek_kodu,
                    "aktif": d.aktif,
                    "aciklama": d.aciklama,
                    "ucretler": ucretler,
                }
            )
        kimlik = p.kimlik_no
        if not yetki_var("personel_duzenleme") and oturum.role_kod != "YONETICI":
            kimlik = maskele_kimlik(kimlik)
        return {
            "id": p.id,
            "kod": p.kod,
            "ad": p.ad,
            "soyad": p.soyad,
            "ad_soyad": f"{p.ad} {p.soyad}".strip(),
            "kimlik_turu": p.kimlik_turu,
            "kimlik_no": kimlik,
            "dogum_tarihi": p.dogum_tarihi.isoformat() if p.dogum_tarihi else None,
            "telefon": p.telefon,
            "eposta": p.eposta,
            "adres": p.adres,
            "il": p.il,
            "ilce": p.ilce,
            "calisma_durumu": p.calisma_durumu,
            "notlar": p.notlar,
            "foto_var": p.foto is not None,
            "olusturan": p.olusturan,
            "guncelleyen": p.guncelleyen,
            "donemler": donemler,
            "finans_gorur": finans,
        }

    @staticmethod
    def kaydet(veri: dict[str, Any], personel_id: int | None = None) -> dict[str, Any]:
        yazma_zorunlu(*DUZENLEME)
        PersonelService.hazirla()
        kod = (veri.get("kod") or "").strip().upper()
        ad = (veri.get("ad") or "").strip()
        soyad = (veri.get("soyad") or "").strip()
        if not kod:
            raise ValueError("Personel kodu zorunludur.")
        if not ad or not soyad:
            raise ValueError("Ad ve soyad zorunludur.")
        kimlik_turu = (veri.get("kimlik_turu") or KIMLIK_TCKN).strip()
        if kimlik_turu not in {KIMLIK_TCKN, KIMLIK_YABANCI, KIMLIK_DIGER}:
            raise ValueError("Geçersiz kimlik türü.")
        kimlik_no = kimlik_dogrula(kimlik_turu, veri.get("kimlik_no"))
        durum = (veri.get("calisma_durumu") or DURUM_AKTIF).strip()
        if durum not in dict(CALISMA_DURUMLARI):
            raise ValueError("Geçersiz çalışma durumu.")

        dogum = _tarih(veri.get("dogum_tarihi"))
        # Oturum yoksa DB yazmadan önce fail — kısmi kayıt / sahte kullanıcı yok
        aktor = _kullanici()

        with get_session() as session:
            cakisma = session.scalar(
                select(Personel).where(
                    Personel.kod == kod,
                    Personel.id != int(personel_id or 0),
                )
            )
            if cakisma is not None:
                raise ValueError(f"Personel kodu firma içinde benzersiz olmalı: {kod}")

            if personel_id:
                p = session.get(Personel, int(personel_id))
                if p is None:
                    raise ValueError("Personel bulunamadı.")
                PersonelService._gecmis_yaz(
                    session, p, veri, kimlik_no, durum, dogum, aktor=aktor
                )
            else:
                p = Personel(kod=kod, ad=ad, soyad=soyad, olusturan=aktor)
                session.add(p)
                session.flush()
                session.add(
                    PersonelGecmis(
                        personel_id=p.id,
                        alan="olusturma",
                        eski_deger=None,
                        yeni_deger=f"{kod}|{ad}|{soyad}",
                        kullanici=aktor,
                    )
                )

            p.kod = kod
            p.ad = ad
            p.soyad = soyad
            p.kimlik_turu = kimlik_turu
            p.kimlik_no = kimlik_no
            p.dogum_tarihi = dogum
            p.telefon = (veri.get("telefon") or None)
            p.eposta = (veri.get("eposta") or None)
            p.adres = (veri.get("adres") or None)
            p.il = (veri.get("il") or None)
            p.ilce = (veri.get("ilce") or None)
            p.calisma_durumu = durum
            p.notlar = (veri.get("notlar") or None)
            p.guncelleyen = aktor
            p.guncelleme = datetime.now()

            donem_veri = veri.get("donem") or {}
            if donem_veri or not p.donemler:
                PersonelService._donem_kaydet(session, p, donem_veri, aktor=aktor)

            session.flush()
            return PersonelService._kart_dict(p, finans=finans_gorur())

    @staticmethod
    def _gecmis_yaz(session, p: Personel, veri, kimlik_no, durum, dogum, *, aktor: str) -> None:
        alanlar = {
            "kod": (p.kod, (veri.get("kod") or "").strip().upper()),
            "ad": (p.ad, (veri.get("ad") or "").strip()),
            "soyad": (p.soyad, (veri.get("soyad") or "").strip()),
            "kimlik_no": (p.kimlik_no, kimlik_no),
            "calisma_durumu": (p.calisma_durumu, durum),
            "dogum_tarihi": (
                p.dogum_tarihi.isoformat() if p.dogum_tarihi else None,
                dogum.isoformat() if dogum else None,
            ),
        }
        for alan, (eski, yeni) in alanlar.items():
            if str(eski or "") != str(yeni or ""):
                session.add(
                    PersonelGecmis(
                        personel_id=p.id,
                        alan=alan,
                        eski_deger=str(eski) if eski is not None else None,
                        yeni_deger=str(yeni) if yeni is not None else None,
                        kullanici=aktor,
                    )
                )

    @staticmethod
    def _donem_kaydet(
        session, p: Personel, donem_veri: dict, *, aktor: str | None = None
    ) -> PersonelCalismaDonemi:
        aktor = aktor or _kullanici()
        donem_id = donem_veri.get("id")
        giris = _tarih(donem_veri.get("giris_tarihi")) or date.today()
        if donem_id:
            d = session.get(PersonelCalismaDonemi, int(donem_id))
            if d is None or d.personel_id != p.id:
                raise ValueError("Çalışma dönemi bulunamadı.")
        else:
            # Yeni dönem: önceki aktif dönemleri kapat (yeniden işe giriş)
            if donem_veri.get("yeni_donem"):
                for eski in p.donemler:
                    if eski.aktif:
                        eski.aktif = False
                        if eski.cikis_tarihi is None:
                            eski.cikis_tarihi = giris
            d = PersonelCalismaDonemi(personel_id=p.id, giris_tarihi=giris)
            session.add(d)
            session.flush()

        d.giris_tarihi = giris
        d.cikis_tarihi = _tarih(donem_veri.get("cikis_tarihi"))
        d.gorev = donem_veri.get("gorev") or None
        d.bolum = donem_veri.get("bolum") or None
        d.sube = donem_veri.get("sube") or None
        d.isyeri_kodu = donem_veri.get("isyeri_kodu") or None
        d.isyeri_sicil = donem_veri.get("isyeri_sicil") or None
        d.sozlesme_turu = donem_veri.get("sozlesme_turu") or None
        d.calisma_duzeni = donem_veri.get("calisma_duzeni") or None
        d.sgk_kapsam = donem_veri.get("sgk_kapsam") or "4/a"
        d.meslek_kodu = donem_veri.get("meslek_kodu") or None
        d.aktif = bool(donem_veri.get("aktif", True))
        d.aciklama = donem_veri.get("aciklama") or None

        if d.cikis_tarihi and d.aktif and p.calisma_durumu == DURUM_AYRILDI:
            d.aktif = False

        ucret_veri = donem_veri.get("ucret") or {}
        if ucret_veri.get("tutar") not in (None, ""):
            if not finans_gorur() and not yetki_var("personel_finans_duzenleme"):
                yazma_zorunlu("personel_finans_duzenleme", "finans_duzenleme")
            PersonelService._ucret_ekle(session, d, ucret_veri, aktor=aktor)
        return d

    @staticmethod
    def _ucret_ekle(
        session, d: PersonelCalismaDonemi, ucret_veri: dict, *, aktor: str | None = None
    ) -> PersonelUcret:
        aktor = aktor or _kullanici()
        tutar = _para(ucret_veri.get("tutar"))
        if tutar <= 0:
            raise ValueError("Ücret tutarı pozitif olmalı.")
        gecerli = _tarih(ucret_veri.get("gecerli_baslangic")) or date.today()
        # Aynı başlangıçta mükerrer yazma
        ayni = session.scalar(
            select(PersonelUcret).where(
                PersonelUcret.donem_id == d.id,
                PersonelUcret.gecerli_baslangic == gecerli,
            )
        )
        if ayni is not None:
            ayni.ucret_turu = ucret_veri.get("ucret_turu") or UCRET_NET
            ayni.tutar = tutar
            ayni.odeme_gunu = _int_veya_none(ucret_veri.get("odeme_gunu"))
            ayni.iban = (ucret_veri.get("iban") or None)
            ayni.banka_adi = (ucret_veri.get("banka_adi") or None)
            ayni.aciklama = (ucret_veri.get("aciklama") or None)
            return ayni
        u = PersonelUcret(
            donem_id=d.id,
            ucret_turu=ucret_veri.get("ucret_turu") or UCRET_NET,
            tutar=tutar,
            gecerli_baslangic=gecerli,
            odeme_gunu=_int_veya_none(ucret_veri.get("odeme_gunu")),
            iban=(ucret_veri.get("iban") or None),
            banka_adi=(ucret_veri.get("banka_adi") or None),
            aciklama=(ucret_veri.get("aciklama") or None),
            olusturan=aktor,
        )
        session.add(u)
        session.add(
            PersonelGecmis(
                personel_id=d.personel_id,
                alan="ucret",
                eski_deger=None,
                yeni_deger=f"{u.ucret_turu}:{tutar}@{gecerli.isoformat()}",
                kullanici=aktor,
            )
        )
        return u

    @staticmethod
    def yeni_calisma_donemi(personel_id: int, giris_tarihi: date | str, **kwargs) -> dict:
        """Ayrılıp yeniden başlayan kişi için yeni dönem; eski ücret/bildirge taşınmaz."""
        yazma_zorunlu(*DUZENLEME)
        PersonelService.hazirla()
        giris = _tarih(giris_tarihi) or date.today()
        aktor = _kullanici()
        with get_session() as session:
            p = session.get(Personel, int(personel_id))
            if p is None:
                raise ValueError("Personel bulunamadı.")
            for eski in p.donemler:
                if eski.aktif:
                    eski.aktif = False
                    if eski.cikis_tarihi is None:
                        eski.cikis_tarihi = giris
            d = PersonelCalismaDonemi(
                personel_id=p.id,
                giris_tarihi=giris,
                gorev=kwargs.get("gorev"),
                bolum=kwargs.get("bolum"),
                sube=kwargs.get("sube"),
                isyeri_kodu=kwargs.get("isyeri_kodu"),
                isyeri_sicil=kwargs.get("isyeri_sicil"),
                aktif=True,
            )
            session.add(d)
            p.calisma_durumu = DURUM_AKTIF
            p.guncelleyen = aktor
            p.guncelleme = datetime.now()
            session.add(
                PersonelGecmis(
                    personel_id=p.id,
                    alan="yeni_calisma_donemi",
                    eski_deger=None,
                    yeni_deger=giris.isoformat(),
                    kullanici=aktor,
                )
            )
            session.flush()
            return {"donem_id": d.id, "personel_id": p.id}

    @staticmethod
    def silinemez(personel_id: int) -> None:
        """Gerçek geçmişi olan personel fiziksel silinmez."""
        raise ValueError(
            "Geçmişi bulunan personel fiziksel olarak silinemez. "
            "Çalışma durumunu 'Ayrıldı' veya 'Pasif' yapın."
        )


def _tarih(v) -> date | None:
    if v in (None, ""):
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:10] if fmt == "%Y-%m-%d" else s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Geçersiz tarih: {v}")


def _int_veya_none(v) -> int | None:
    if v in (None, ""):
        return None
    return int(v)
