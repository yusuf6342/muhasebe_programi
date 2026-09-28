"""SQLite özel fonksiyonları ve Türkçe duyarsız arama koşulları.

SQLite'ın lower()/LIKE'ı yalnız ASCII harflerde büyük/küçük katlar; 'İ', 'ı', 'Ş'
gibi harfler eşleşmez. Bu modül her yeni SQLite bağlantısına ``tr_norm(metin)``
fonksiyonunu (turkce_normalize) kaydeder; arama koşulları
``tr_norm(kolon) LIKE '%<normalize sorgu>%'`` biçiminde kurulur.

Kayıt, ``Engine`` sınıfı düzeyinde "connect" olayıyla yapılır: bu modül içe
aktarıldıktan sonra açılan tüm motorların (şirket, sistem, test) bağlantıları
fonksiyona sahip olur.
"""

from __future__ import annotations

import sqlite3

from sqlalchemy import event, func, or_
from sqlalchemy.engine import Engine

from database.turkce_normalize import turkce_normalize

TR_NORM_SQL_ADI = "tr_norm"


def _tr_norm_sql(deger):
    if deger is None:
        return None
    try:
        return turkce_normalize(deger if isinstance(deger, str) else str(deger))
    except Exception:
        return None


def sqlite_fonksiyonlarini_kaydet(dbapi_connection) -> None:
    """DBAPI bağlantısına tr_norm() kaydeder (SQLite değilse sessizce geçer)."""
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    try:
        dbapi_connection.create_function(
            TR_NORM_SQL_ADI, 1, _tr_norm_sql, deterministic=True
        )
    except (TypeError, sqlite3.NotSupportedError):
        dbapi_connection.create_function(TR_NORM_SQL_ADI, 1, _tr_norm_sql)


@event.listens_for(Engine, "connect")
def _engine_connect(dbapi_connection, _connection_record) -> None:
    sqlite_fonksiyonlarini_kaydet(dbapi_connection)


def tr_icerir(kolon, metin: str | None):
    """Türkçe duyarsız 'içerir' koşulu (İ/I/ı/i, Ş/ş/s ... eşdeğer)."""
    anahtar = turkce_normalize((metin or "").strip())
    return func.tr_norm(kolon).contains(anahtar, autoescape=True)


def tr_baslar(kolon, metin: str | None):
    """Türkçe duyarsız 'ile başlar' koşulu."""
    anahtar = turkce_normalize((metin or "").strip())
    return func.tr_norm(kolon).startswith(anahtar, autoescape=True)


def tr_esit(kolon, metin: str | None):
    """Türkçe duyarsız tam eşitlik (büyük/küçük ve ı/i farkı yok sayılır)."""
    return func.tr_norm(kolon) == turkce_normalize((metin or "").strip())


_ALAN_AYRACI = "\x01"


def tr_herhangi_icerir(kolonlar, metin: str | None):
    """Kolonlardan herhangi biri metni içerir.

    Satır başına tek tr_norm() çağrısı için kolonlar ayraçla birleştirilir; ayraç
    arama metninde bulunamayacağından eşleşme iki alanı aşamaz.
    """
    kolonlar = list(kolonlar)
    anahtar = turkce_normalize((metin or "").strip())
    if _ALAN_AYRACI in anahtar or len(kolonlar) == 1:
        return or_(*[tr_icerir(k, metin) for k in kolonlar])
    birlesik = func.coalesce(kolonlar[0], "")
    for k in kolonlar[1:]:
        birlesik = birlesik.concat(_ALAN_AYRACI).concat(func.coalesce(k, ""))
    return func.tr_norm(birlesik).contains(anahtar, autoescape=True)
