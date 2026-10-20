"""Maaş hakediş, avans, ödeme ve masraf — resmî bordro motoru değildir."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from database.access import yetki_zorunlu, yazma_zorunlu
from database.database import get_session
from database.models.personel import (
    HAKEDIS_IPTAL,
    HAKEDIS_ONAYLI,
    HAKEDIS_TASLAK,
    HAREKET_AVANS,
    HAREKET_IPTAL,
    HAREKET_MAAS_ODEME,
    HAREKET_MAHSUP,
    HAREKET_MASRAF,
    HAREKET_MASRAF_IADE,
    Personel,
    PersonelCalismaDonemi,
    PersonelHakedis,
    PersonelHesapHareketi,
)
from database.personel_sema import schema_hazirla
from database.personel_service import _kullanici, _para, _tarih, finans_gorur

FINANS_YAZ = ("personel_finans_duzenleme", "finans_duzenleme")
FINANS_OKU = ("personel_finans_goruntuleme", "personel_finans_duzenleme", "finans_goruntuleme")


class PersonelFinansService:
    @staticmethod
    def ay_ozeti(personel_id: int, yil: int | None = None, ay: int | None = None) -> dict[str, Any]:
        """Kart üst özeti: onaylı net, mahsup edilecek avans, ödenen, kalan."""
        yetki_zorunlu(*FINANS_OKU)
        if not finans_gorur():
            return {"finans_gorur": False}
        schema_hazirla()
        bugun = date.today()
        yil = int(yil or bugun.year)
        ay = int(ay or bugun.month)
        with get_session() as session:
            hakedis = session.scalar(
                select(PersonelHakedis).where(
                    PersonelHakedis.personel_id == int(personel_id),
                    PersonelHakedis.yil == yil,
                    PersonelHakedis.ay == ay,
                    PersonelHakedis.kayit_turu == "NORMAL",
                    PersonelHakedis.durum == HAKEDIS_ONAYLI,
                )
            )
            net = Decimal(hakedis.net_hakedis) if hakedis else Decimal("0")
            hareketler = session.scalars(
                select(PersonelHesapHareketi).where(
                    PersonelHesapHareketi.personel_id == int(personel_id),
                    PersonelHesapHareketi.iptal.is_(False),
                )
            ).all()
            avans_bakiye = Decimal("0")
            maas_odenen = Decimal("0")
            bu_ay_mahsup = Decimal("0")
            masraf_alacak = Decimal("0")
            hid = hakedis.id if hakedis else None
            for h in hareketler:
                t = Decimal(h.tutar)
                if h.hareket_turu == HAREKET_AVANS:
                    avans_bakiye += t
                elif h.hareket_turu == HAREKET_MAHSUP:
                    avans_bakiye -= t
                    if hid is not None and h.hakedis_id == hid:
                        bu_ay_mahsup += t
                elif h.hareket_turu == HAREKET_MAAS_ODEME and h.hakedis_id == hid:
                    maas_odenen += t
                elif h.hareket_turu == HAREKET_MASRAF:
                    masraf_alacak += t
                elif h.hareket_turu == HAREKET_MASRAF_IADE:
                    masraf_alacak -= t
            # Henüz mahsup edilmemiş avans (bu ay için önerilen)
            mahsup_onerilen = min(max(avans_bakiye, Decimal("0")), net - bu_ay_mahsup - maas_odenen)
            if mahsup_onerilen < 0:
                mahsup_onerilen = Decimal("0")
            kalan = net - bu_ay_mahsup - maas_odenen
            return {
                "finans_gorur": True,
                "yil": yil,
                "ay": ay,
                "onayli_net_hakedis": float(net),
                "mahsup_edilecek_avans": float(bu_ay_mahsup if bu_ay_mahsup else mahsup_onerilen),
                "yapilan_maas_odemesi": float(maas_odenen),
                "kalan_odeme": float(kalan),
                "avans_bakiyesi": float(avans_bakiye),
                "masraf_alacagi": float(masraf_alacak),
                "hakedis_id": hakedis.id if hakedis else None,
                "hakedis_durum": hakedis.durum if hakedis else None,
                "bordro_motoru": False,
                "aciklama": "Net maaş takibi — resmî bordro hesabı değildir.",
            }

    @staticmethod
    def hakedis_kaydet(veri: dict) -> dict:
        yazma_zorunlu(*FINANS_YAZ)
        schema_hazirla()
        personel_id = int(veri["personel_id"])
        donem_id = int(veri["donem_id"])
        yil, ay = int(veri["yil"]), int(veri["ay"])
        if not 1 <= ay <= 12:
            raise ValueError("Ay 1-12 olmalı.")
        kayit_turu = (veri.get("kayit_turu") or "NORMAL").upper()
        temel = _para(veri.get("temel_ucret"))
        ek = _para(veri.get("ek_odeme"))
        fm = _para(veri.get("fazla_mesai"))
        kes = _para(veri.get("kesinti"))
        net = _para(veri.get("net_hakedis"))
        if net == 0:
            net = temel + ek + fm - kes

        with get_session() as session:
            if session.get(Personel, personel_id) is None:
                raise ValueError("Personel bulunamadı.")
            if session.get(PersonelCalismaDonemi, donem_id) is None:
                raise ValueError("Çalışma dönemi bulunamadı.")
            if kayit_turu == "NORMAL":
                mevcut = session.scalar(
                    select(PersonelHakedis).where(
                        PersonelHakedis.personel_id == personel_id,
                        PersonelHakedis.donem_id == donem_id,
                        PersonelHakedis.yil == yil,
                        PersonelHakedis.ay == ay,
                        PersonelHakedis.kayit_turu == "NORMAL",
                        PersonelHakedis.durum != HAKEDIS_IPTAL,
                    )
                )
                if mevcut is not None and not veri.get("id"):
                    raise ValueError(
                        "Bu personel/dönem/ay için normal hakediş zaten var. "
                        "Düzeltme için fark kaydı kullanın."
                    )
                h = mevcut or PersonelHakedis(
                    personel_id=personel_id, donem_id=donem_id, yil=yil, ay=ay
                )
            else:
                h = PersonelHakedis(
                    personel_id=personel_id,
                    donem_id=donem_id,
                    yil=yil,
                    ay=ay,
                    kayit_turu=kayit_turu,
                    kaynak_hakedis_id=veri.get("kaynak_hakedis_id"),
                )
            if veri.get("id"):
                h = session.get(PersonelHakedis, int(veri["id"]))
                if h is None:
                    raise ValueError("Hakediş bulunamadı.")
                if h.durum == HAKEDIS_ONAYLI and kayit_turu == "NORMAL":
                    raise ValueError("Onaylı hakediş değiştirilemez; fark/düzeltme kaydı açın.")
            else:
                session.add(h)
            h.temel_ucret = temel
            h.ek_odeme = ek
            h.fazla_mesai = fm
            h.kesinti = kes
            h.net_hakedis = net
            h.bordro_kaynagi = veri.get("bordro_kaynagi")
            h.aciklama = veri.get("aciklama")
            h.durum = HAKEDIS_TASLAK
            h.olusturan = h.olusturan or _kullanici()
            session.flush()
            return {"id": h.id, "durum": h.durum, "net_hakedis": float(h.net_hakedis)}

    @staticmethod
    def hakedis_onayla(hakedis_id: int) -> dict:
        yazma_zorunlu(*FINANS_YAZ)
        schema_hazirla()
        with get_session() as session:
            h = session.get(PersonelHakedis, int(hakedis_id))
            if h is None:
                raise ValueError("Hakediş bulunamadı.")
            if h.durum == HAKEDIS_ONAYLI:
                return {"id": h.id, "durum": h.durum}
            h.durum = HAKEDIS_ONAYLI
            h.onaylayan = _kullanici()
            h.onay_tarihi = datetime.now()
            session.flush()
            return {"id": h.id, "durum": h.durum, "net_hakedis": float(h.net_hakedis)}

    @staticmethod
    def avans_kaydet(veri: dict) -> dict:
        """Avans tek başına maaş gideri yaratmaz."""
        yazma_zorunlu(*FINANS_YAZ)
        schema_hazirla()
        return PersonelFinansService._hareket(
            personel_id=int(veri["personel_id"]),
            hareket_turu=HAREKET_AVANS,
            tutar=_para(veri["tutar"]),
            tarih=_tarih(veri.get("tarih")) or date.today(),
            aciklama=veri.get("aciklama"),
            belge_turu=veri.get("belge_turu"),
            belge_id=veri.get("belge_id"),
            belge_no=veri.get("belge_no"),
            donem_id=veri.get("donem_id"),
        )

    @staticmethod
    def maas_odeme_kaydet(veri: dict) -> dict:
        """Kısmi ödeme; mevcut kasa/banka belgesine bağlanır — ikinci belge üretilmez."""
        yazma_zorunlu(*FINANS_YAZ)
        schema_hazirla()
        if not veri.get("belge_turu") or not veri.get("belge_id"):
            raise ValueError("Maaş ödemesi mevcut kasa/banka belgesine bağlanmalıdır.")
        hakedis_id = int(veri["hakedis_id"])
        with get_session() as session:
            h = session.get(PersonelHakedis, hakedis_id)
            if h is None or h.durum != HAKEDIS_ONAYLI:
                raise ValueError("Ödeme için onaylı hakediş gerekli.")
        return PersonelFinansService._hareket(
            personel_id=int(veri["personel_id"]),
            hareket_turu=HAREKET_MAAS_ODEME,
            tutar=_para(veri["tutar"]),
            tarih=_tarih(veri.get("tarih")) or date.today(),
            aciklama=veri.get("aciklama"),
            belge_turu=veri["belge_turu"],
            belge_id=int(veri["belge_id"]),
            belge_no=veri.get("belge_no"),
            donem_id=veri.get("donem_id"),
            hakedis_id=hakedis_id,
        )

    @staticmethod
    def avans_mahsup(veri: dict) -> dict:
        """Mahsup yeni kasa çıkışı üretmez."""
        yazma_zorunlu(*FINANS_YAZ)
        schema_hazirla()
        return PersonelFinansService._hareket(
            personel_id=int(veri["personel_id"]),
            hareket_turu=HAREKET_MAHSUP,
            tutar=_para(veri["tutar"]),
            tarih=_tarih(veri.get("tarih")) or date.today(),
            aciklama=veri.get("aciklama") or "Avans mahsubu",
            hakedis_id=veri.get("hakedis_id"),
            donem_id=veri.get("donem_id"),
        )

    @staticmethod
    def masraf_kaydet(veri: dict) -> dict:
        yazma_zorunlu(*FINANS_YAZ)
        schema_hazirla()
        return PersonelFinansService._hareket(
            personel_id=int(veri["personel_id"]),
            hareket_turu=HAREKET_MASRAF,
            tutar=_para(veri["tutar"]),
            tarih=_tarih(veri.get("tarih")) or date.today(),
            aciklama=veri.get("aciklama"),
            belge_turu=veri.get("belge_turu"),
            belge_id=veri.get("belge_id"),
            belge_no=veri.get("belge_no"),
        )

    @staticmethod
    def masraf_iade(veri: dict) -> dict:
        """Masraf geri ödemesini ikinci gider veya maaş sayma."""
        yazma_zorunlu(*FINANS_YAZ)
        schema_hazirla()
        return PersonelFinansService._hareket(
            personel_id=int(veri["personel_id"]),
            hareket_turu=HAREKET_MASRAF_IADE,
            tutar=_para(veri["tutar"]),
            tarih=_tarih(veri.get("tarih")) or date.today(),
            aciklama=veri.get("aciklama") or "Masraf geri ödeme",
            belge_turu=veri.get("belge_turu"),
            belge_id=veri.get("belge_id"),
            belge_no=veri.get("belge_no"),
            kaynak_hareket_id=veri.get("kaynak_hareket_id"),
        )

    @staticmethod
    def iptal(hareket_id: int) -> dict:
        """İptal eski dağıtımı geri alır; bakiyeyi bir kez açar."""
        yazma_zorunlu(*FINANS_YAZ)
        schema_hazirla()
        with get_session() as session:
            h = session.get(PersonelHesapHareketi, int(hareket_id))
            if h is None:
                raise ValueError("Hareket bulunamadı.")
            if h.iptal:
                raise ValueError("Hareket zaten iptal.")
            h.iptal = True
            h.iptal_tarihi = datetime.now()
            h.iptal_eden = _kullanici()
            # İptal kaydı (bakiye bir kez açılır)
            ters = PersonelHesapHareketi(
                personel_id=h.personel_id,
                donem_id=h.donem_id,
                hakedis_id=h.hakedis_id,
                hareket_turu=HAREKET_IPTAL,
                tarih=date.today(),
                tutar=h.tutar,
                aciklama=f"İptal: hareket #{h.id}",
                kaynak_hareket_id=h.id,
                olusturan=_kullanici(),
            )
            session.add(ters)
            session.flush()
            return {"iptal_edilen": h.id, "ters_kayit": ters.id}

    @staticmethod
    def hareketler(personel_id: int) -> list[dict]:
        yetki_zorunlu(*FINANS_OKU)
        schema_hazirla()
        with get_session() as session:
            satirlar = session.scalars(
                select(PersonelHesapHareketi)
                .where(PersonelHesapHareketi.personel_id == int(personel_id))
                .order_by(PersonelHesapHareketi.tarih.desc(), PersonelHesapHareketi.id.desc())
            ).all()
            return [
                {
                    "id": h.id,
                    "hareket_turu": h.hareket_turu,
                    "tarih": h.tarih.isoformat(),
                    "tutar": float(h.tutar),
                    "aciklama": h.aciklama,
                    "belge_turu": h.belge_turu,
                    "belge_id": h.belge_id,
                    "belge_no": h.belge_no,
                    "hakedis_id": h.hakedis_id,
                    "iptal": h.iptal,
                }
                for h in satirlar
            ]

    @staticmethod
    def _hareket(**kw) -> dict:
        tutar = kw["tutar"]
        if tutar <= 0:
            raise ValueError("Tutar pozitif olmalı.")
        with get_session() as session:
            if session.get(Personel, int(kw["personel_id"])) is None:
                raise ValueError("Personel bulunamadı.")
            h = PersonelHesapHareketi(
                personel_id=int(kw["personel_id"]),
                donem_id=kw.get("donem_id"),
                hakedis_id=kw.get("hakedis_id"),
                hareket_turu=kw["hareket_turu"],
                tarih=kw["tarih"],
                tutar=tutar,
                aciklama=kw.get("aciklama"),
                belge_turu=kw.get("belge_turu"),
                belge_id=int(kw["belge_id"]) if kw.get("belge_id") else None,
                belge_no=kw.get("belge_no"),
                kaynak_hareket_id=kw.get("kaynak_hareket_id"),
                olusturan=_kullanici(),
            )
            session.add(h)
            session.flush()
            return {"id": h.id, "hareket_turu": h.hareket_turu, "tutar": float(h.tutar)}
