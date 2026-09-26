"""Operasyon modellerinin ortak kayit sirasi."""

# Evrak modelleri subeler.id FK'sini kullanir; fixture'lar tek tek model import
# etse bile Sube tablosu metadata'ya kayitli olsun.
from database.models.sube import Sube  # noqa: F401
