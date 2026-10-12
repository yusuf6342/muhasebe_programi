"""Kart bakiyesi / limit düzeltmesi şema geçişi (modül ``kart_bakiye``, sürüm 1).

* ``kredi_karti_ekstreleri.son_odeme_tarihi`` boş olabilir (son ödeme günü tanımsız kartta tahmin yazılmaz) ve
  ``gider_kart_odemeleri.ilk_kesim`` boş olabilir (kesim günü tanımsız kartla gider). SQLite NOT NULL kaldıramadığı
  için bu iki tablo yeniden kurulur; satır sayısı ve tutar toplamları kopyadan önce/sonra karşılaştırılır, tutmazsa
  geçiş hata verir ve doğrulanmış yedekten geri yüklenir.
* Ekstre ödemesine istek anahtarı, giriş ekranı, kart hesabı ve iptal bilgileri; ödeme ↔ taksit bağlantı tablosu ve
  geçmiş kayıt onarım günlüğü eklenir.
"""

from __future__ import annotations

import weakref

from sqlalchemy import MetaData, inspect, text
from sqlalchemy.schema import CreateIndex, CreateTable

from database.models.finans import (
    GiderKartOdeme,
    KartBakiyeOnarimGunlugu,
    KrediKartiEkstre,
    KrediKartiEkstreOdeme,
    KrediKartiEkstreOdemeTaksit,
)

GECIS_MODULU = "kart_bakiye"
GECIS_SURUMU = 1

ODEME_KOLONLARI = {
    "istek_anahtari": "VARCHAR(64)",
    "kaynak": "VARCHAR(20)",
    "kart_hesap_id": "INTEGER",
    "iptal_islem_tarihi": "DATE",
    "iptal_nedeni": "VARCHAR(300)",
    "iptal_kullanici": "VARCHAR(120)",
}
# Yeniden kurulacak tablo → boş olabilmesi gereken kolon ve karşılaştırılacak tutar kolonları
YENIDEN_KURULACAK = {
    KrediKartiEkstre.__tablename__: ("son_odeme_tarihi", ("toplam_borc", "odenen", "kalan")),
    GiderKartOdeme.__tablename__: ("ilk_kesim", ("gider_tutari", "kart_toplami", "finansman_farki")),
}

_HAZIR: "weakref.WeakSet" = weakref.WeakSet()


def _motor():
    import database.database as veritabani

    return getattr(veritabani.company_db, "_engine", None) or veritabani.engine


def _zorunlu_mu(ins, tablo: str, kolon: str) -> bool:
    if not ins.has_table(tablo):
        return False
    return any(c["name"] == kolon and not c["nullable"] for c in ins.get_columns(tablo))


def _eksik_var(motor) -> bool:
    ins = inspect(motor)
    for model in (KrediKartiEkstreOdemeTaksit, KartBakiyeOnarimGunlugu):
        if not ins.has_table(model.__tablename__):
            return True
    if ins.has_table(KrediKartiEkstreOdeme.__tablename__):
        mevcut = {c["name"] for c in ins.get_columns(KrediKartiEkstreOdeme.__tablename__)}
        if set(ODEME_KOLONLARI) - mevcut:
            return True
    return any(_zorunlu_mu(ins, t, k) for t, (k, _) in YENIDEN_KURULACAK.items())


def _ozet(cur, tablo: str, tutarlar: tuple[str, ...]) -> tuple:
    alanlar = ", ".join(f'ROUND(COALESCE(SUM("{k}"), 0), 2)' for k in tutarlar)
    satir = cur.execute(f'SELECT COUNT(*), COALESCE(SUM(id), 0), {alanlar} FROM "{tablo}"').fetchone()
    return tuple(satir)


def tablo_yeniden_kur(motor, tablo_adi: str) -> dict:
    """Tabloyu güncel model tanımıyla yeniden kurar (veri birebir kopyalanır, doğrulanır)."""
    from database.database import Base

    tablo = Base.metadata.tables[tablo_adi]
    _kolon, tutarlar = YENIDEN_KURULACAK[tablo_adi]
    yeni_ad = f"{tablo_adi}__yeni"
    ham = motor.raw_connection()
    try:
        db = getattr(ham, "driver_connection", None) or ham.connection
        eski_seviye = db.isolation_level
        db.isolation_level = None
        cur = db.cursor()
        fk = cur.execute("PRAGMA foreign_keys").fetchone()[0]
        cur.execute("PRAGMA foreign_keys=OFF")
        try:
            cur.execute("BEGIN IMMEDIATE")
            try:
                once = _ozet(cur, tablo_adi, tutarlar)
                eski_kolonlar = [r[1] for r in cur.execute(f'PRAGMA table_info("{tablo_adi}")').fetchall()]
                for ad, _u, kaynak in [(r[1], r[2], r[3]) for r in
                                       cur.execute(f'PRAGMA index_list("{tablo_adi}")').fetchall()]:
                    if kaynak == "c":
                        cur.execute(f'DROP INDEX IF EXISTS "{ad}"')
                cur.execute(f'DROP TABLE IF EXISTS "{yeni_ad}"')
                md = MetaData()
                for fk in tablo.foreign_keys:
                    hedef = fk.column.table
                    if hedef.name not in md.tables:
                        hedef.to_metadata(md)
                kopya = tablo.to_metadata(md, name=yeni_ad)
                cur.execute(str(CreateTable(kopya).compile(dialect=motor.dialect)))
                ortak = [k.name for k in tablo.columns if k.name in eski_kolonlar]
                kolonlar = ", ".join(f'"{k}"' for k in ortak)
                cur.execute(f'INSERT INTO "{yeni_ad}" ({kolonlar}) SELECT {kolonlar} FROM "{tablo_adi}"')
                sonra = _ozet(cur, yeni_ad, tutarlar)
                if once != sonra:
                    raise RuntimeError(f"{tablo_adi} yeniden kurulumu doğrulanamadı: önce {once}, sonra {sonra}")
                cur.execute(f'DROP TABLE "{tablo_adi}"')
                cur.execute(f'ALTER TABLE "{yeni_ad}" RENAME TO "{tablo_adi}"')
                for idx in tablo.indexes:
                    cur.execute(str(CreateIndex(idx).compile(dialect=motor.dialect)))
                hatalar = cur.execute(f'PRAGMA foreign_key_check("{tablo_adi}")').fetchall()
                if hatalar:
                    raise RuntimeError(f"{tablo_adi} yabancı anahtar denetimi başarısız: {hatalar[:3]}")
                cur.execute("COMMIT")
            except Exception:
                cur.execute("ROLLBACK")
                raise
        finally:
            cur.execute(f"PRAGMA foreign_keys={'ON' if fk else 'OFF'}")
            db.isolation_level = eski_seviye
        return {"tablo": tablo_adi, "satir": once[0], "toplamlar": once[2:]}
    finally:
        ham.close()


def _gecis_v1(motor) -> None:
    from database.modul_sema import eksik_kolonlari_ekle

    KrediKartiEkstre.__table__.create(motor, checkfirst=True)
    KrediKartiEkstreOdeme.__table__.create(motor, checkfirst=True)
    eksik_kolonlari_ekle(motor, KrediKartiEkstreOdeme.__tablename__, ODEME_KOLONLARI)
    KrediKartiEkstreOdemeTaksit.__table__.create(motor, checkfirst=True)
    KartBakiyeOnarimGunlugu.__table__.create(motor, checkfirst=True)
    with motor.begin() as b:
        b.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS "ux_kk_ekstre_odeme_istek" '
                       'ON "kredi_karti_ekstre_odemeleri" ("istek_anahtari")'))
    for tablo, (kolon, _t) in YENIDEN_KURULACAK.items():
        if _zorunlu_mu(inspect(motor), tablo, kolon):
            tablo_yeniden_kur(motor, tablo)


def schema_hazirla(motor=None) -> None:
    """Sürümlü geçiş. Veri içeren firmada önce doğrulanmış yedek alınır; hata olursa yedekten geri yüklenir."""
    motor = motor or _motor()
    if motor is None or motor in _HAZIR:
        return
    from database.modul_sema import surum_uygula

    if not inspect(motor).has_table("kredi_karti_tanimlari"):
        _HAZIR.add(motor)
        return
    if _eksik_var(motor):
        import database.database as veritabani

        db_yolu = getattr(veritabani.company_db, "_db_path", None) if motor is _motor() else None
        if db_yolu:
            from database.gecis_guvenligi import guvenli_gecis, yedek_onayi

            if yedek_onayi(db_yolu) is None:
                guvenli_gecis(db_yolu, lambda: surum_uygula(motor, GECIS_MODULU, GECIS_SURUMU, _gecis_v1),
                              gerekli=True, etiket="kart_bakiye_gecis", baglantilari_kapat=lambda: motor.dispose())
                _HAZIR.add(motor)
                return
    surum_uygula(motor, GECIS_MODULU, GECIS_SURUMU, _gecis_v1)
    _HAZIR.add(motor)
