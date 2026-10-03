"""Kendi tablosu olmayan finans evrakları için kalıcı kimlik (``finans_evrak_kimlikleri``)."""

from __future__ import annotations

from sqlalchemy import select

from database.models.finans import FinansEvrakKimligi

EVRAK_CARI_TAHSILAT = "cari_tahsilat"
EVRAK_CARI_ODEME = "cari_odeme"
EVRAK_KASA_BANKA_VIRMAN = "kasa_banka_virman"
EVRAK_BANKA_HAVALE = "banka_havale"
EVRAK_CARI_VIRMAN = "cari_virman"

_hazir: set[str] = set()


def tablo_hazirla(session) -> None:
    bind = session.get_bind()
    anahtar = f"{id(bind)}|{bind.url}"
    if anahtar in _hazir:
        return
    FinansEvrakKimligi.__table__.create(bind=session.connection(), checkfirst=True)
    _hazir.add(anahtar)


def kimlik_al(session, evrak_turu: str, belge_no: str, *, cari_islem_id: int | None = None,
              kaynak: str = "evrak") -> int:
    """Evrak türü + belge no için kalıcı id (yoksa oluşturur). Düzenlemede aynı id döner."""
    tablo_hazirla(session)
    kayit = kimlik_bul(session, evrak_turu, belge_no)
    if kayit is None:
        kayit = FinansEvrakKimligi(evrak_turu=evrak_turu, belge_no=belge_no,
                                   cari_islem_id=cari_islem_id, kaynak=kaynak)
        session.add(kayit)
        session.flush()
    elif cari_islem_id is not None and kayit.cari_islem_id != cari_islem_id:
        kayit.cari_islem_id = cari_islem_id
        session.flush()
    return int(kayit.id)


def kimlik_bul(session, evrak_turu: str, belge_no: str) -> FinansEvrakKimligi | None:
    tablo_hazirla(session)
    return session.scalar(
        select(FinansEvrakKimligi).where(
            FinansEvrakKimligi.evrak_turu == evrak_turu, FinansEvrakKimligi.belge_no == belge_no
        )
    )


def cari_islem_kimligi(session, evrak_turu: str, cari_islem_id: int) -> FinansEvrakKimligi | None:
    tablo_hazirla(session)
    return session.scalar(
        select(FinansEvrakKimligi).where(
            FinansEvrakKimligi.evrak_turu == evrak_turu,
            FinansEvrakKimligi.cari_islem_id == int(cari_islem_id),
        )
    )


def kimlik_getir(session, kimlik_id: int, evrak_turu: str) -> FinansEvrakKimligi | None:
    tablo_hazirla(session)
    kayit = session.get(FinansEvrakKimligi, int(kimlik_id))
    return kayit if kayit is not None and kayit.evrak_turu == evrak_turu else None
