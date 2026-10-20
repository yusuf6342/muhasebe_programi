"""Testlerde ``get_session``'ı geçici test veritabanına yönlendirme.

``get_session`` modül özniteliği atamayla değiştirilmemeli: yama açıkken ilk kez içe aktarılan
bir modül (ör. ``from database.database import get_session``) sahte fonksiyonu kalıcı bağlar,
tearDown onu geri yüklemez ve sonraki test dosyaları kapanmış bellek içi oturumu kullanır
("no such table"). Gerçek ``database.database.get_session`` her çağrıda ``company_db``'ye
baktığı için yalnız o nesne geçici olarak değiştirilir.
"""

from __future__ import annotations

from unittest.mock import patch

import database.database as db


class _SahteFirmaDb:
    acik = True

    def __init__(self, baglam_fabrikasi):
        self._baglam_fabrikasi = baglam_fabrikasi

    def get_session(self):
        return self._baglam_fabrikasi()


def oturum_yamasi(baglam_fabrikasi):
    """``with``/``start()`` ile kullanılır; ``baglam_fabrikasi()`` bir context manager döndürmelidir."""
    return patch.object(db, "company_db", _SahteFirmaDb(baglam_fabrikasi))
