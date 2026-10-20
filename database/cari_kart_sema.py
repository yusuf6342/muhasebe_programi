"""Cari kart / yetkili / fotoğraf / Genel Risk alanları ve grup rol ayarları için sürümlü geçiş.

Tekrar çalıştırılabilir: eksik kolon ve tabloları ekler, yetkili doğum tarihini gün/ay/yıl
parçalarına ve serbest departman/görev metinlerini tanım kayıtlarına bağlar. Finansal tutarlara
dokunmaz; mevcut müşteri grubu boş kartlara grup atamaz.
"""

from __future__ import annotations

import weakref

from sqlalchemy import inspect, text

_HAZIR_MOTORLAR: "weakref.WeakSet" = weakref.WeakSet()

RISK_ORANI_KOLONLARI = {
    "risk_orani_ciro_cek": "NUMERIC(5, 2) NOT NULL DEFAULT 100",
    "risk_orani_diger_cek": "NUMERIC(5, 2) NOT NULL DEFAULT 100",
    "risk_orani_senet": "NUMERIC(5, 2) NOT NULL DEFAULT 100",
}
YETKILI_KOLONLARI = {
    "dogum_gun": "INTEGER",
    "dogum_ay": "INTEGER",
    "dogum_yili": "INTEGER",
    "departman_id": "INTEGER",
    "gorev_id": "INTEGER",
}


def _tanim_id(baglanti, tablo: str, ad: str, onbellek: dict[str, int]) -> int:
    from database.turkce_normalize import turkce_normalize

    ad = " ".join(ad.split())[:100]
    anahtar = turkce_normalize(ad)[:100]
    if anahtar in onbellek:
        return onbellek[anahtar]
    satir = baglanti.execute(
        text(f'SELECT id FROM "{tablo}" WHERE ad_norm = :n'), {"n": anahtar}
    ).first()
    if satir is None:
        baglanti.execute(
            text(f'INSERT INTO "{tablo}" (ad, ad_norm, aktif) VALUES (:a, :n, 1)'),
            {"a": ad, "n": anahtar},
        )
        satir = baglanti.execute(
            text(f'SELECT id FROM "{tablo}" WHERE ad_norm = :n'), {"n": anahtar}
        ).first()
    onbellek[anahtar] = int(satir[0])
    return onbellek[anahtar]


def _yetkili_verisini_bagla(motor) -> None:
    """Doğum tarihini parçalara ayırır; departman/görev metnini tanım kaydına bağlar."""
    if not inspect(motor).has_table("cari_yetkililer"):
        return
    with motor.begin() as b:
        for yid, dogum in b.execute(text(
            "SELECT id, dogum_tarihi FROM cari_yetkililer "
            "WHERE dogum_tarihi IS NOT NULL AND dogum_gun IS NULL"
        )).all():
            parca = str(dogum)[:10].split("-")
            if len(parca) != 3:
                continue
            try:
                yil, ay, gun = (int(p) for p in parca)
            except ValueError:
                continue
            b.execute(
                text("UPDATE cari_yetkililer SET dogum_gun=:g, dogum_ay=:a, dogum_yili=:y WHERE id=:i"),
                {"g": gun, "a": ay, "y": yil, "i": int(yid)},
            )
        dep_onbellek: dict[str, int] = {}
        gor_onbellek: dict[str, int] = {}
        for yid, dep, gor, dep_id, gor_id in b.execute(text(
            "SELECT id, departman, gorev, departman_id, gorev_id FROM cari_yetkililer"
        )).all():
            guncel = {}
            if dep_id is None and (dep or "").strip():
                guncel["departman_id"] = _tanim_id(b, "cari_yetkili_departmanlari", dep, dep_onbellek)
            if gor_id is None and (gor or "").strip():
                guncel["gorev_id"] = _tanim_id(b, "cari_yetkili_gorevleri", gor, gor_onbellek)
            if guncel:
                atama = ", ".join(f"{k}=:{k}" for k in guncel)
                b.execute(text(f"UPDATE cari_yetkililer SET {atama} WHERE id=:i"), {**guncel, "i": int(yid)})


def schema_hazirla(motor=None) -> None:
    import database.database as veritabani

    motor = motor or veritabani.engine
    if motor is None or motor in _HAZIR_MOTORLAR:
        return
    from database.modul_sema import eksik_kolonlari_ekle, surum_uygula
    from database.models.cari import (
        CariFotograf,
        CariYetkili,
        CariYetkiliDepartman,
        CariYetkiliGorev,
    )

    def _v1(e) -> None:
        eksik_kolonlari_ekle(e, "cari_kartlar", RISK_ORANI_KOLONLARI)
        for tablo in (CariYetkiliDepartman.__table__, CariYetkiliGorev.__table__, CariFotograf.__table__):
            tablo.create(e, checkfirst=True)
        if inspect(e).has_table(CariYetkili.__tablename__):
            eksik_kolonlari_ekle(e, CariYetkili.__tablename__, YETKILI_KOLONLARI)
            _yetkili_verisini_bagla(e)

    def _v2(e) -> None:
        from database.models.cari import MusteriGrubuAyari

        MusteriGrubuAyari.__table__.create(e, checkfirst=True)

    if inspect(motor).has_table("cari_kartlar"):
        surum_uygula(motor, "cari_kart", 1, _v1)
        surum_uygula(motor, "cari_kart", 2, _v2)
    _HAZIR_MOTORLAR.add(motor)
