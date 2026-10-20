"""Puantaj ve izin — yıllık izin asgari süreleri sürümlü mevzuat parametresinden."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, or_, select

from database.access import yetki_zorunlu, yazma_zorunlu
from database.database import get_session
from database.models.personel import (
    IZIN_IPTAL,
    IZIN_KULLANIM,
    IZIN_ONAYLI,
    IZIN_TALEP,
    IZIN_YILLIK,
    Personel,
    PersonelIzin,
    PersonelIzinHakedis,
    PersonelMevzuatParametre,
    PersonelPuantaj,
)
from database.personel_sema import schema_hazirla
from database.personel_service import _kullanici, _para, _tarih

YAZ = ("personel_duzenleme", "duzenleme")
OKU = ("personel_goruntuleme", "personel_duzenleme", "goruntuleme")


def _aktif_parametre(session, kod: str, referans: date | None = None) -> PersonelMevzuatParametre | None:
    referans = referans or date.today()
    return session.scalar(
        select(PersonelMevzuatParametre)
        .where(
            PersonelMevzuatParametre.kod == kod,
            PersonelMevzuatParametre.aktif.is_(True),
            PersonelMevzuatParametre.yururluk_baslangic <= referans,
            or_(
                PersonelMevzuatParametre.yururluk_bitis.is_(None),
                PersonelMevzuatParametre.yururluk_bitis >= referans,
            ),
        )
        .order_by(PersonelMevzuatParametre.yururluk_baslangic.desc())
    )


def yillik_izin_asgari_gun(
    hizmet_yil: float,
    yas: int | None,
    *,
    referans: date | None = None,
) -> dict[str, Any]:
    """Asgari gün — kaynaklı parametre; yoksa hesap yapılmaz (uydurma yok)."""
    schema_hazirla()
    with get_session() as session:
        p = _aktif_parametre(session, "YILLIK_IZIN_ASGARI", referans)
        if p is None:
            raise ValueError(
                "Yıllık izin asgari parametresi tanımlı değil. "
                "Personel Ayarları'ndan kaynaklı kural ekleyin [5]."
            )
        deger = json.loads(p.deger_json)
        gun = None
        for esik in deger.get("hizmet_yil_esikleri") or []:
            max_yil = esik.get("max_yil")
            if max_yil is None or hizmet_yil < float(max_yil):
                gun = int(esik["gun"])
                break
        if gun is None:
            gun = 14
        yas_min = deger.get("yas_18_alti_veya_50_ustu_min")
        if yas is not None and yas_min is not None and (yas <= 18 or yas >= 50):
            gun = max(gun, int(yas_min))
        return {
            "gun": gun,
            "kural_surum": p.surum,
            "kural_kaynak": p.resmi_kaynak,
            "kontrol_tarihi": p.kontrol_tarihi.isoformat(),
            "min_hizmet_yil": deger.get("min_hizmet_yil", 1),
        }


class PersonelPuantajService:
    @staticmethod
    def kaydet(veri: dict) -> dict:
        yazma_zorunlu(*YAZ)
        schema_hazirla()
        personel_id = int(veri["personel_id"])
        tarih = _tarih(veri["tarih"])
        if tarih is None:
            raise ValueError("Tarih zorunlu.")
        tur = (veri.get("tur") or "CALISMA").upper()
        saat = _para(veri.get("saat") or 0)
        with get_session() as session:
            if session.get(Personel, personel_id) is None:
                raise ValueError("Personel bulunamadı.")
            # Çakışma kontrolü
            cakisan = session.scalars(
                select(PersonelPuantaj).where(
                    PersonelPuantaj.personel_id == personel_id,
                    PersonelPuantaj.tarih == tarih,
                )
            ).all()
            for c in cakisan:
                if c.tur == tur and not veri.get("id"):
                    raise ValueError(f"Aynı tarihte çakışan {tur} kaydı var (id={c.id}).")
            if veri.get("id"):
                k = session.get(PersonelPuantaj, int(veri["id"]))
                if k is None:
                    raise ValueError("Puantaj bulunamadı.")
            else:
                k = PersonelPuantaj(personel_id=personel_id, tarih=tarih, olusturan=_kullanici())
                session.add(k)
            k.tur = tur
            k.saat = saat
            k.aciklama = veri.get("aciklama")
            k.donem_id = veri.get("donem_id")
            k.izin_id = veri.get("izin_id")
            session.flush()
            return {"id": k.id, "tarih": k.tarih.isoformat(), "tur": k.tur, "saat": float(k.saat)}

    @staticmethod
    def listele(personel_id: int, bas: date | str, bit: date | str) -> list[dict]:
        yetki_zorunlu(*OKU)
        schema_hazirla()
        b1, b2 = _tarih(bas), _tarih(bit)
        with get_session() as session:
            satirlar = session.scalars(
                select(PersonelPuantaj)
                .where(
                    PersonelPuantaj.personel_id == int(personel_id),
                    PersonelPuantaj.tarih >= b1,
                    PersonelPuantaj.tarih <= b2,
                )
                .order_by(PersonelPuantaj.tarih)
            ).all()
            return [
                {
                    "id": s.id,
                    "tarih": s.tarih.isoformat(),
                    "tur": s.tur,
                    "saat": float(s.saat),
                    "aciklama": s.aciklama,
                }
                for s in satirlar
            ]


class PersonelIzinService:
    @staticmethod
    def talep(veri: dict) -> dict:
        yazma_zorunlu(*YAZ)
        schema_hazirla()
        bas = _tarih(veri["baslangic"])
        bit = _tarih(veri["bitis"])
        if not bas or not bit or bit < bas:
            raise ValueError("Geçersiz izin tarih aralığı.")
        gun = _para(veri.get("gun") or ((bit - bas).days + 1))
        with get_session() as session:
            if session.get(Personel, int(veri["personel_id"])) is None:
                raise ValueError("Personel bulunamadı.")
            # Çakışan onaylı/kullanım
            cakisan = session.scalar(
                select(PersonelIzin).where(
                    PersonelIzin.personel_id == int(veri["personel_id"]),
                    PersonelIzin.durum.in_((IZIN_ONAYLI, IZIN_KULLANIM, IZIN_TALEP)),
                    PersonelIzin.baslangic <= bit,
                    PersonelIzin.bitis >= bas,
                )
            )
            if cakisan is not None:
                raise ValueError(f"Çakışan izin kaydı var (id={cakisan.id}).")
            iz = PersonelIzin(
                personel_id=int(veri["personel_id"]),
                donem_id=veri.get("donem_id"),
                izin_turu=(veri.get("izin_turu") or IZIN_YILLIK).upper(),
                durum=IZIN_TALEP,
                baslangic=bas,
                bitis=bit,
                gun=gun,
                aciklama=veri.get("aciklama"),
                kural_surum=veri.get("kural_surum"),
                olusturan=_kullanici(),
            )
            session.add(iz)
            session.flush()
            return {"id": iz.id, "durum": iz.durum, "gun": float(iz.gun)}

    @staticmethod
    def onayla(izin_id: int) -> dict:
        yazma_zorunlu(*YAZ)
        schema_hazirla()
        with get_session() as session:
            iz = session.get(PersonelIzin, int(izin_id))
            if iz is None:
                raise ValueError("İzin bulunamadı.")
            if iz.durum == IZIN_IPTAL:
                raise ValueError("İptal edilmiş izin onaylanamaz.")
            iz.durum = IZIN_ONAYLI
            iz.onaylayan = _kullanici()
            iz.onay_tarihi = datetime.now()
            session.flush()
            return {"id": iz.id, "durum": iz.durum}

    @staticmethod
    def kullanima_al(izin_id: int) -> dict:
        yazma_zorunlu(*YAZ)
        schema_hazirla()
        with get_session() as session:
            iz = session.get(PersonelIzin, int(izin_id))
            if iz is None:
                raise ValueError("İzin bulunamadı.")
            if iz.durum not in (IZIN_ONAYLI, IZIN_TALEP):
                raise ValueError("Yalnız talep/onaylı izin kullanıma alınabilir.")
            iz.durum = IZIN_KULLANIM
            if iz.izin_turu == IZIN_YILLIK:
                PersonelIzinService._kullanim_yansit(session, iz)
            session.flush()
            return {"id": iz.id, "durum": iz.durum}

    @staticmethod
    def iptal(izin_id: int) -> dict:
        yazma_zorunlu(*YAZ)
        schema_hazirla()
        with get_session() as session:
            iz = session.get(PersonelIzin, int(izin_id))
            if iz is None:
                raise ValueError("İzin bulunamadı.")
            onceki = iz.durum
            iz.durum = IZIN_IPTAL
            if onceki == IZIN_KULLANIM and iz.izin_turu == IZIN_YILLIK:
                PersonelIzinService._kullanim_geri_al(session, iz)
            session.flush()
            return {"id": iz.id, "durum": iz.durum}

    @staticmethod
    def _kullanim_yansit(session, iz: PersonelIzin) -> None:
        yil = iz.baslangic.year
        h = session.scalar(
            select(PersonelIzinHakedis).where(
                PersonelIzinHakedis.personel_id == iz.personel_id,
                PersonelIzinHakedis.yil == yil,
            )
        )
        if h is None:
            h = PersonelIzinHakedis(personel_id=iz.personel_id, yil=yil)
            session.add(h)
            session.flush()
        h.kullanilan = Decimal(h.kullanilan) + Decimal(iz.gun)
        h.kalan = Decimal(h.hak_edilen) + Decimal(h.onceki_devir) - Decimal(h.kullanilan)

    @staticmethod
    def _kullanim_geri_al(session, iz: PersonelIzin) -> None:
        yil = iz.baslangic.year
        h = session.scalar(
            select(PersonelIzinHakedis).where(
                PersonelIzinHakedis.personel_id == iz.personel_id,
                PersonelIzinHakedis.yil == yil,
            )
        )
        if h is None:
            return
        h.kullanilan = max(Decimal("0"), Decimal(h.kullanilan) - Decimal(iz.gun))
        h.kalan = Decimal(h.hak_edilen) + Decimal(h.onceki_devir) - Decimal(h.kullanilan)

    @staticmethod
    def hakedis_ayarla(veri: dict) -> dict:
        """Hakediş / devir — takvim yılı başında otomatik sıfırlanmaz."""
        yazma_zorunlu(*YAZ)
        schema_hazirla()
        with get_session() as session:
            h = session.scalar(
                select(PersonelIzinHakedis).where(
                    PersonelIzinHakedis.personel_id == int(veri["personel_id"]),
                    PersonelIzinHakedis.yil == int(veri["yil"]),
                )
            )
            if h is None:
                h = PersonelIzinHakedis(
                    personel_id=int(veri["personel_id"]), yil=int(veri["yil"])
                )
                session.add(h)
            h.hak_edilen = _para(veri.get("hak_edilen") or 0)
            h.onceki_devir = _para(veri.get("onceki_devir") or 0)
            if "kullanilan" in veri:
                h.kullanilan = _para(veri.get("kullanilan") or 0)
            h.kalan = Decimal(h.hak_edilen) + Decimal(h.onceki_devir) - Decimal(h.kullanilan)
            h.esas_tarih = _tarih(veri.get("esas_tarih"))
            h.yas = veri.get("yas")
            h.kural_surum = veri.get("kural_surum")
            h.kural_kaynak = veri.get("kural_kaynak")
            h.aciklama = veri.get("aciklama")
            session.flush()
            return {
                "id": h.id,
                "hak_edilen": float(h.hak_edilen),
                "onceki_devir": float(h.onceki_devir),
                "kullanilan": float(h.kullanilan),
                "kalan": float(h.kalan),
                "kural_surum": h.kural_surum,
                "kural_kaynak": h.kural_kaynak,
            }

    @staticmethod
    def ozet(personel_id: int, yil: int | None = None) -> dict:
        yetki_zorunlu(*OKU)
        schema_hazirla()
        yil = int(yil or date.today().year)
        with get_session() as session:
            h = session.scalar(
                select(PersonelIzinHakedis).where(
                    PersonelIzinHakedis.personel_id == int(personel_id),
                    PersonelIzinHakedis.yil == yil,
                )
            )
            izinler = session.scalars(
                select(PersonelIzin)
                .where(
                    PersonelIzin.personel_id == int(personel_id),
                    PersonelIzin.baslangic >= date(yil, 1, 1),
                    PersonelIzin.baslangic <= date(yil, 12, 31),
                )
                .order_by(PersonelIzin.baslangic.desc())
            ).all()
            return {
                "yil": yil,
                "hak_edilen": float(h.hak_edilen) if h else 0,
                "onceki_devir": float(h.onceki_devir) if h else 0,
                "kullanilan": float(h.kullanilan) if h else 0,
                "kalan": float(h.kalan) if h else 0,
                "esas_tarih": h.esas_tarih.isoformat() if h and h.esas_tarih else None,
                "yas": h.yas if h else None,
                "kural_surum": h.kural_surum if h else None,
                "kural_kaynak": h.kural_kaynak if h else None,
                "izinler": [
                    {
                        "id": i.id,
                        "izin_turu": i.izin_turu,
                        "durum": i.durum,
                        "baslangic": i.baslangic.isoformat(),
                        "bitis": i.bitis.isoformat(),
                        "gun": float(i.gun),
                        "aciklama": i.aciklama,
                    }
                    for i in izinler
                ],
            }
