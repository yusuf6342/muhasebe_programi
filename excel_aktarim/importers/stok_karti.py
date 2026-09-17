"""Stok kartı Excel importer."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from database.database import get_session
from database.models.stok import StokKarti
from database.stok_service import StokService
from excel_aktarim.importers.base import BaseImporter
from excel_aktarim.normalize import decimal_parse, temiz
from excel_aktarim.types import AlanTanimi, ImportTipi, kaydet
from excel_aktarim.validation import SatirSonuc

_BASLIKLAR = {
    "stokkodu": "stok_kodu",
    "kod": "stok_kodu",
    "stokadi": "stok_adi",
    "urunadi": "stok_adi",
    "ad": "stok_adi",
    "barkod": "barkod",
    "birim": "birim",
    "kdvorani": "kdv_orani",
    "kdv": "kdv_orani",
    "kartturu": "kart_turu",
    "marka": "marka",
    "model": "model",
    "raporgrubu": "rapor_grubu",
    "rafyeri": "raf_yeri",
    "aciklama": "aciklama",
    "satisfiyati": "satis_fiyati",
    "alisfiyati": "alis_fiyati",
}


class StokKartiImporter(BaseImporter):
    tip: ImportTipi

    def __init__(self, tip: ImportTipi):
        self.tip = tip

    def _hazirla(self, eslenen: dict[str, Any]) -> dict[str, Any]:
        veriler: dict[str, Any] = {}
        for alan in (
            "stok_kodu",
            "stok_adi",
            "barkod",
            "birim",
            "kart_turu",
            "marka",
            "model",
            "rapor_grubu",
            "raf_yeri",
            "aciklama",
        ):
            if alan in eslenen and temiz(eslenen[alan]):
                veriler[alan] = temiz(eslenen[alan])
        if "kdv_orani" in eslenen and temiz(eslenen["kdv_orani"]):
            veriler["kdv_orani"] = decimal_parse(eslenen["kdv_orani"], alan="KDV")
        for fiyat_alan in ("satis_fiyati", "alis_fiyati"):
            if fiyat_alan in eslenen and temiz(eslenen[fiyat_alan]):
                veriler[fiyat_alan] = decimal_parse(eslenen[fiyat_alan], alan=fiyat_alan)
        veriler.setdefault("birim", "Adet")
        veriler.setdefault("kart_turu", "Ticari Mal")
        veriler.setdefault("kdv_orani", Decimal("20"))
        return veriler

    def dogrula_satir(
        self,
        satir_no: int,
        eslenen: dict[str, Any],
        *,
        guncelleme_modu: str = "guncelle",
    ) -> SatirSonuc:
        sonuc = SatirSonuc(satir_no=satir_no, ham=dict(eslenen), eslenen={})
        try:
            veriler = self._hazirla(eslenen)
        except ValueError as exc:
            sonuc.hata_ekle(str(exc))
            return sonuc
        sonuc.eslenen = veriler
        kod = temiz(veriler.get("stok_kodu"))
        ad = temiz(veriler.get("stok_adi"))
        if not kod:
            sonuc.hata_ekle("Stok kodu zorunludur.")
        if not ad:
            sonuc.hata_ekle("Stok adı zorunludur.")
        if not sonuc.gecerli:
            return sonuc

        with get_session() as session:
            mevcut = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == kod))

        sonuc.hedef_tablo = "stok_kartlari"
        if mevcut is None:
            sonuc.islem = "insert"
            sonuc.ozet = f"Yeni stok: {kod} — {ad}"
            return sonuc

        sonuc.hedef_id = mevcut.id
        if guncelleme_modu == "atla":
            sonuc.islem = "skip"
            sonuc.ozet = f"Atlandı: {kod}"
        elif guncelleme_modu == "hata":
            sonuc.hata_ekle(f"Stok kodu zaten var: {kod}")
        else:
            sonuc.islem = "update"
            sonuc.ozet = f"Güncelle: {kod} — {ad}"
        return sonuc

    def uygula_satir(self, sonuc: SatirSonuc) -> dict[str, Any]:
        veriler = dict(sonuc.eslenen)
        onceki = None
        if sonuc.hedef_id:
            with get_session() as session:
                stok = session.get(StokKarti, sonuc.hedef_id)
                if stok:
                    onceki = {
                        "id": stok.id,
                        "stok_kodu": stok.stok_kodu,
                        "stok_adi": stok.stok_adi,
                        "barkod": stok.barkod,
                        "birim": stok.birim,
                        "kdv_orani": str(stok.kdv_orani),
                        "is_deleted": stok.is_deleted,
                        "aktif": stok.aktif,
                    }
                    veriler["stok_id"] = stok.id

        satis = veriler.pop("satis_fiyati", None)
        alis = veriler.pop("alis_fiyati", None)
        fiyatlar = []
        if satis is not None:
            fiyatlar.append(("Satış Fiyatı", satis))
        if alis is not None:
            fiyatlar.append(("Alış Fiyatı", alis))

        barkod = veriler.get("barkod")
        barkodlar = [{"barkod": barkod}] if barkod else None

        stok = StokService.stok_kaydi(veriler, fiyatlar, barkodlar=barkodlar)
        return {
            "hedef_tablo": "stok_kartlari",
            "hedef_id": getattr(stok, "id", None) or sonuc.hedef_id,
            "islem": "update" if onceki else "insert",
            "onceki": onceki,
            "sonraki": {
                "stok_kodu": veriler.get("stok_kodu"),
                "stok_adi": veriler.get("stok_adi"),
            },
        }

    def geri_al_degisiklik(self, change: dict[str, Any]) -> None:
        hedef_id = change.get("hedef_id")
        if not hedef_id:
            return
        with get_session() as session:
            stok = session.get(StokKarti, int(hedef_id))
            if stok is None:
                return
            if change.get("islem") == "insert":
                stok.is_deleted = True
                stok.aktif = False
                stok.deleted_at = datetime.now()
            elif change.get("islem") == "update" and change.get("onceki"):
                onceki = change["onceki"]
                for alan in ("stok_adi", "barkod", "birim", "aktif"):
                    if alan in onceki:
                        setattr(stok, alan, onceki[alan])
                if "kdv_orani" in onceki and onceki["kdv_orani"] is not None:
                    stok.kdv_orani = Decimal(str(onceki["kdv_orani"]))
            session.flush()


def _factory():
    return StokKartiImporter(STOK_TIPI)


STOK_TIPI = kaydet(
    ImportTipi(
        kod="stok_karti",
        ad="Stok Kartları",
        modul="stok",
        alanlar=[
            AlanTanimi("stok_kodu", "Stok Kodu", zorunlu=True, ornek="STK001"),
            AlanTanimi("stok_adi", "Stok Adı", zorunlu=True, ornek="Örnek Ürün"),
            AlanTanimi("barkod", "Barkod", ornek="8690000000001"),
            AlanTanimi("birim", "Birim", ornek="Adet"),
            AlanTanimi("kdv_orani", "KDV Oranı", ornek="20"),
            AlanTanimi("kart_turu", "Kart Türü", ornek="Ticari Mal"),
            AlanTanimi("marka", "Marka", ornek=""),
            AlanTanimi("model", "Model", ornek=""),
            AlanTanimi("rapor_grubu", "Rapor Grubu", ornek=""),
            AlanTanimi("raf_yeri", "Raf Yeri", ornek=""),
            AlanTanimi("satis_fiyati", "Satış Fiyatı", ornek="100,00"),
            AlanTanimi("alis_fiyati", "Alış Fiyatı", ornek="70,00"),
            AlanTanimi("aciklama", "Açıklama", ornek=""),
        ],
        importer_factory=_factory,
        aciklama="Stok kartlarını Excel'den ekler veya günceller.",
        eslesen_basliklar=dict(_BASLIKLAR),
        izinler=("excel_aktarim", "excel_pdf", "stok_duzenleme", "yeni_kayit"),
    )
)
