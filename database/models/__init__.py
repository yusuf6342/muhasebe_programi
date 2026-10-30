"""Operasyon modellerinin ortak kayit sirasi."""

# Evrak modelleri subeler.id FK'sini kullanir; fixture'lar tek tek model import
# etse bile Sube tablosu metadata'ya kayitli olsun.
from database.models.sube import Sube  # noqa: F401
from database.models import uretim as _uretim  # noqa: F401
from database.models import aktivite as _aktivite  # noqa: F401
from database.models import butce as _butce  # noqa: F401
from database.models import devir as _devir  # noqa: F401
from database.models import proje as _proje  # noqa: F401
