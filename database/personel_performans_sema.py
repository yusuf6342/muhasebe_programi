"""Performans / kariyer / prim şema + örnek politika tohumu."""

from __future__ import annotations

import weakref
from datetime import date
from decimal import Decimal

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import sessionmaker

_HAZIR: "weakref.WeakSet" = weakref.WeakSet()


def schema_hazirla(motor=None) -> None:
    import database.database as vt

    motor = motor or vt.engine
    if motor is None:
        return
    from database.personel_sema import schema_hazirla as personel_schema

    personel_schema(motor)

    from database.modul_sema import surum_uygula
    from database.models import personel_performans as m

    tablolar = [
        m.PersonelGorevAtama.__table__,
        m.PersonelIsKaydi.__table__,
        m.PersonelIsGecmis.__table__,
        m.PersonelKatkiOlay.__table__,
        m.PersonelOlcutSurumu.__table__,
        m.PersonelDegerlendirme.__table__,
        m.PersonelGelisimPlani.__table__,
        m.PersonelKariyerKarari.__table__,
        m.PersonelPrimPolitika.__table__,
        m.PersonelPrimDonemi.__table__,
        m.PersonelPrimPay.__table__,
        m.PersonelFaturaHDonuk.__table__,
    ]

    def _v1(e) -> None:
        for t in tablolar:
            if t.name == "personel_is_gecmis":
                continue  # v2
            t.create(e, checkfirst=True)
        _tohum(e)

    def _v2(e) -> None:
        """İş panosu: hedef_saat, donem, güncelleme + geçmiş tablosu. Mevcut satırlar korunur."""
        m.PersonelIsGecmis.__table__.create(e, checkfirst=True)
        _sutun_ekle(
            e,
            "personel_is_kayitlari",
            {
                "donem_id": "INTEGER",
                "hedef_saat": "VARCHAR(8)",
                "guncelleyen": "VARCHAR(120)",
                "guncelleme": "DATETIME",
            },
        )
        # aciklama / dis_engel genişletme SQLite'ta tip değişimi gerektirmez; mevcut veri kalır

    surum_uygula(motor, "personel_performans", 1, _v1)
    surum_uygula(motor, "personel_performans", 2, _v2)
    _HAZIR.add(motor)


def _sutun_ekle(motor, tablo: str, sutunlar: dict[str, str]) -> None:
    insp = inspect(motor)
    if not insp.has_table(tablo):
        return
    mevcut = {c["name"] for c in insp.get_columns(tablo)}
    with motor.begin() as conn:
        for ad, tip in sutunlar.items():
            if ad in mevcut:
                continue
            conn.execute(text(f'ALTER TABLE "{tablo}" ADD COLUMN "{ad}" {tip}'))


def _tohum(motor) -> None:
    from database.models.personel_performans import PersonelOlcutSurumu, PersonelPrimPolitika

    Session = sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)
    with Session() as s:
        if s.scalar(select(PersonelPrimPolitika).limit(1)) is None:
            s.add(
                PersonelPrimPolitika(
                    kod="ORNEK",
                    surum="2026-10-16",
                    gecerli_baslangic=date(2026, 10, 1),
                    prim_orani=Decimal("0.10"),
                    guvence_tutari=Decimal("20000"),
                    agirlik_ekip=Decimal("0.50"),
                    agirlik_katki=Decimal("0.30"),
                    agirlik_kidem=Decimal("0.20"),
                    canli_politika=False,
                    aciklama="Başlangıç önerisi — canlı ücret politikası olarak yürürlüğe girmez.",
                )
            )
        olcutler = (
            ("GOREV_SONUCU", "SATIS", "Görev sonucu", "0.40"),
            ("KALITE", "SATIS", "Kalite", "0.30"),
            ("EKIP", "SATIS", "İş takibi ve ekip katkısı", "0.20"),
            ("GELISIM", "SATIS", "Gelişim", "0.10"),
        )
        for kod, alan, ad, ag in olcutler:
            if s.scalar(
                select(PersonelOlcutSurumu).where(
                    PersonelOlcutSurumu.kod == kod, PersonelOlcutSurumu.surum == "2026-10-16"
                )
            ) is None:
                s.add(
                    PersonelOlcutSurumu(
                        kod=kod,
                        surum="2026-10-16",
                        gorev_alani=alan,
                        ad=ad,
                        agirlik=Decimal(ag),
                        hedef=Decimal("100"),
                        ornek_alt_sinir=5,
                        yuksek_iyi=True,
                    )
                )
        s.commit()
