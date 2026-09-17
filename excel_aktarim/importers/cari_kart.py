"""Müşteri / tedarikçi cari Excel importer."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from database.cari_service import CariService
from database.database import get_session
from database.models.cari import Cari
from excel_aktarim.importers.base import BaseImporter
from excel_aktarim.normalize import temiz
from excel_aktarim.types import AlanTanimi, ImportTipi, kaydet
from excel_aktarim.validation import SatirSonuc

_CARI_BASLIKLAR = {
    "carikodu": "cari_kodu",
    "musterikodu": "cari_kodu",
    "tedarikcikodu": "cari_kodu",
    "kod": "cari_kodu",
    "unvan": "unvan",
    "firmaadi": "unvan",
    "musteriadi": "unvan",
    "adi": "unvan",
    "ad": "unvan",
    "vergidairesi": "vergi_dairesi",
    "verginumarasi": "vergi_numarasi",
    "vergino": "vergi_numarasi",
    "vkn": "vergi_numarasi",
    "tckimlik": "tc_kimlik",
    "tckn": "tc_kimlik",
    "tc": "tc_kimlik",
    "telefon": "telefon",
    "tel": "telefon",
    "gsm": "telefon",
    "email": "email",
    "eposta": "email",
    "musterigrubu": "musteri_grubu",
    "grup": "musteri_grubu",
    "adres": "adres",
    "il": "il",
    "sehir": "il",
    "ilce": "ilce",
    "ozelnotlar": "ozel_notlar",
    "not": "ozel_notlar",
}

_ALANLAR = [
    AlanTanimi("cari_kodu", "Cari Kodu", zorunlu=False, ornek="M00001", aciklama="Boşsa otomatik üretilir"),
    AlanTanimi("unvan", "Ünvan", zorunlu=True, ornek="Örnek A.Ş."),
    AlanTanimi("vergi_dairesi", "Vergi Dairesi", ornek="Kadıköy"),
    AlanTanimi("vergi_numarasi", "Vergi No", ornek="1234567890"),
    AlanTanimi("tc_kimlik", "TC Kimlik", ornek=""),
    AlanTanimi("telefon", "Telefon", ornek="05321234567"),
    AlanTanimi("email", "E-posta", ornek="info@ornek.com"),
    AlanTanimi("musteri_grubu", "Grup", ornek="Perakende"),
    AlanTanimi("adres", "Adres", ornek=""),
    AlanTanimi("il", "İl", ornek="İstanbul"),
    AlanTanimi("ilce", "İlçe", ornek="Kadıköy"),
    AlanTanimi("ozel_notlar", "Notlar", ornek=""),
]


def _cari_snapshot(cari: Cari) -> dict[str, Any]:
    return {
        "id": cari.id,
        "cari_kodu": cari.cari_kodu,
        "unvan": cari.unvan,
        "cari_turu": cari.cari_turu,
        "vergi_dairesi": cari.vergi_dairesi,
        "vergi_numarasi": cari.vergi_numarasi,
        "tc_kimlik": cari.tc_kimlik,
        "telefon": cari.telefon,
        "email": cari.email,
        "musteri_grubu": cari.musteri_grubu,
        "adres": cari.adres,
        "il": cari.il,
        "ilce": cari.ilce,
        "ozel_notlar": cari.ozel_notlar,
        "aktif": cari.aktif,
        "is_deleted": cari.is_deleted,
    }


class CariKartImporter(BaseImporter):
    def __init__(self, tip: ImportTipi, varsayilan_tur: str):
        self.tip = tip
        self.varsayilan_tur = varsayilan_tur

    def _veri_hazirla(self, eslenen: dict[str, Any]) -> dict[str, Any]:
        veriler: dict[str, Any] = {"cari_turu": self.varsayilan_tur, "aktif": True}
        for alan in (
            "cari_kodu",
            "unvan",
            "vergi_dairesi",
            "vergi_numarasi",
            "tc_kimlik",
            "telefon",
            "email",
            "musteri_grubu",
            "adres",
            "il",
            "ilce",
            "ozel_notlar",
        ):
            if alan not in eslenen:
                continue
            deger = temiz(eslenen[alan])
            if not deger:
                continue
            if alan == "unvan":
                deger = deger[:200]
            elif alan == "cari_kodu":
                deger = deger[:20]
            elif alan == "email":
                deger = deger[:150]
            veriler[alan] = deger
        return veriler

    def dogrula_satir(
        self,
        satir_no: int,
        eslenen: dict[str, Any],
        *,
        guncelleme_modu: str = "guncelle",
    ) -> SatirSonuc:
        sonuc = SatirSonuc(satir_no=satir_no, ham=dict(eslenen), eslenen=dict(eslenen))
        veriler = self._veri_hazirla(eslenen)
        sonuc.eslenen = veriler
        unvan = temiz(veriler.get("unvan"))
        if not unvan:
            sonuc.hata_ekle("Ünvan zorunludur.")
            return sonuc

        kod = temiz(veriler.get("cari_kodu"))
        mevcut = CariService.kod_ile_getir(kod) if kod else None
        if mevcut is None and not kod:
            # ünvan ile yumuşak eşleşme yok — yeni kayıt
            sonuc.islem = "insert"
            sonuc.ozet = f"Yeni {self.varsayilan_tur}: {unvan}"
            sonuc.hedef_tablo = "cari_kartlar"
            return sonuc

        if mevcut is None:
            sonuc.islem = "insert"
            sonuc.ozet = f"Yeni ({kod}): {unvan}"
            sonuc.hedef_tablo = "cari_kartlar"
            return sonuc

        sonuc.hedef_tablo = "cari_kartlar"
        sonuc.hedef_id = mevcut.id
        if guncelleme_modu == "atla":
            sonuc.islem = "skip"
            sonuc.ozet = f"Atlandı (mevcut): {kod}"
        elif guncelleme_modu == "hata":
            sonuc.hata_ekle(f"Cari kodu zaten var: {kod}")
        else:
            sonuc.islem = "update"
            sonuc.ozet = f"Güncelle: {kod} — {unvan}"
        return sonuc

    def uygula_satir(self, sonuc: SatirSonuc) -> dict[str, Any]:
        veriler = dict(sonuc.eslenen)
        if sonuc.islem == "update" and sonuc.hedef_id:
            onceki = None
            with get_session() as session:
                cari = session.get(Cari, sonuc.hedef_id)
                if cari is None:
                    raise ValueError("Cari bulunamadı.")
                onceki = _cari_snapshot(cari)
            guncel = {k: v for k, v in veriler.items() if k != "cari_turu"}
            cari = CariService.guncelle(sonuc.hedef_id, guncel)
            return {
                "hedef_tablo": "cari_kartlar",
                "hedef_id": cari.id,
                "islem": "update",
                "onceki": onceki,
                "sonraki": _cari_snapshot(cari),
            }

        cari = CariService.ekle(veriler)
        return {
            "hedef_tablo": "cari_kartlar",
            "hedef_id": cari.id,
            "islem": "insert",
            "onceki": None,
            "sonraki": _cari_snapshot(cari),
        }

    def geri_al_degisiklik(self, change: dict[str, Any]) -> None:
        hedef_id = change.get("hedef_id")
        if not hedef_id:
            return
        with get_session() as session:
            cari = session.get(Cari, int(hedef_id))
            if cari is None:
                return
            if change.get("islem") == "insert":
                cari.is_deleted = True
                cari.aktif = False
                cari.deleted_at = datetime.now()
            elif change.get("islem") == "update" and change.get("onceki"):
                onceki = change["onceki"]
                for alan in (
                    "unvan",
                    "vergi_dairesi",
                    "vergi_numarasi",
                    "tc_kimlik",
                    "telefon",
                    "email",
                    "musteri_grubu",
                    "adres",
                    "il",
                    "ilce",
                    "ozel_notlar",
                    "aktif",
                ):
                    if alan in onceki:
                        setattr(cari, alan, onceki[alan])
            session.flush()


def _factory_musteri():
    return CariKartImporter(MUSTERI_TIPI, "Müşteri")


def _factory_tedarikci():
    return CariKartImporter(TEDARIKCI_TIPI, "Tedarikçi")


MUSTERI_TIPI = kaydet(
    ImportTipi(
        kod="musteri_cari",
        ad="Müşteri Cari Kartları",
        modul="satis",
        alanlar=list(_ALANLAR),
        importer_factory=_factory_musteri,
        aciklama="Satış müşteri carilerini Excel'den ekler veya günceller.",
        eslesen_basliklar=dict(_CARI_BASLIKLAR),
        izinler=("excel_aktarim", "excel_pdf", "cari_duzenleme", "yeni_kayit"),
    )
)

TEDARIKCI_TIPI = kaydet(
    ImportTipi(
        kod="tedarikci_cari",
        ad="Tedarikçi Cari Kartları",
        modul="satin_alma",
        alanlar=list(_ALANLAR),
        importer_factory=_factory_tedarikci,
        aciklama="Satın alma tedarikçi carilerini Excel'den ekler veya günceller.",
        eslesen_basliklar=dict(_CARI_BASLIKLAR),
        izinler=("excel_aktarim", "excel_pdf", "cari_duzenleme", "yeni_kayit"),
    )
)
