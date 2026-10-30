"""Stok alternatif birimleri Excel importer (reçete değil — birim dönüşümü)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.database import get_session
from database.models.stok import StokBarkod, StokKarti
from database.stok_service import StokService, birim_anahtari
from excel_aktarim.importers.base import BaseImporter
from excel_aktarim.normalize import decimal_parse, temiz
from excel_aktarim.types import AlanTanimi, ImportTipi, kaydet
from excel_aktarim.validation import SatirSonuc

_BASLIKLAR = {
    "anaurunbarkodu": "ana_barkod",
    "urunbarkodu": "ana_barkod",
    "barkod": "ana_barkod",
    "stokkodu": "stok_kodu",
    "kod": "stok_kodu",
    "yenibirim": "yeni_birim",
    "birim": "yeni_birim",
    "birimadi": "yeni_birim",
    "icerikmiktari": "carpan",
    "carpan": "carpan",
    "katsayi": "carpan",
    "donusum": "carpan",
    "referansbirim": "referans_birim",
    "referans": "referans_birim",
    "birimbarkodu": "birim_barkodu",
    "birimbarkod": "birim_barkodu",
    "satisfiyati1": "satis_fiyati",
    "satisfiyati": "satis_fiyati",
    "fiyat": "satis_fiyati",
}


class StokBirimImporter(BaseImporter):
    tip: ImportTipi

    def __init__(self, tip: ImportTipi):
        self.tip = tip

    def _hazirla(self, eslenen: dict[str, Any]) -> dict[str, Any]:
        veriler: dict[str, Any] = {
            "ana_barkod": temiz(eslenen.get("ana_barkod")),
            "stok_kodu": temiz(eslenen.get("stok_kodu")),
            "yeni_birim": temiz(eslenen.get("yeni_birim")),
            "referans_birim": temiz(eslenen.get("referans_birim")),
            "birim_barkodu": temiz(eslenen.get("birim_barkodu")),
        }
        if "carpan" in eslenen and temiz(eslenen.get("carpan")):
            veriler["carpan"] = decimal_parse(eslenen["carpan"], alan="İçerik Miktarı")
        else:
            veriler["carpan"] = None
        if "satis_fiyati" in eslenen and temiz(eslenen.get("satis_fiyati")):
            veriler["satis_fiyati"] = decimal_parse(eslenen["satis_fiyati"], alan="Satış Fiyatı")
        return veriler

    def _stok_ozet(self, ana_barkod: str, stok_kodu: str) -> dict[str, Any] | None:
        with get_session() as session:
            stok = None
            if stok_kodu:
                stok = session.scalar(
                    select(StokKarti)
                    .where(StokKarti.stok_kodu == stok_kodu, StokKarti.is_deleted.is_(False))
                    .options(selectinload(StokKarti.birimler))
                )
            if stok is None and ana_barkod:
                br = session.scalar(select(StokBarkod).where(StokBarkod.barkod == ana_barkod))
                if br is not None:
                    stok = session.scalar(
                        select(StokKarti)
                        .where(StokKarti.id == br.stok_id, StokKarti.is_deleted.is_(False))
                        .options(selectinload(StokKarti.birimler))
                    )
            if stok is None:
                return None
            return {
                "id": int(stok.id),
                "stok_kodu": stok.stok_kodu,
                "ana_birim": (stok.birim or "Adet").strip() or "Adet",
                "birim_adlari": [b.birim_adi for b in (stok.birimler or [])],
            }

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

        if not veriler.get("ana_barkod") and not veriler.get("stok_kodu"):
            sonuc.hata_ekle("Ana ürün barkodu veya stok kodu zorunludur.")
        if not veriler.get("yeni_birim"):
            sonuc.hata_ekle("Yeni birim zorunludur.")
        carpan = veriler.get("carpan")
        if carpan is None:
            sonuc.hata_ekle("İçerik miktarı (dönüşüm katsayısı) zorunludur.")
        elif carpan <= 0:
            sonuc.hata_ekle("İçerik miktarı sıfırdan büyük olmalıdır.")
        if not sonuc.gecerli:
            return sonuc

        ozet = self._stok_ozet(veriler.get("ana_barkod") or "", veriler.get("stok_kodu") or "")
        if ozet is None:
            sonuc.hata_ekle(
                "Stok kartı bulunamadı (barkod/kod). Önce stok kartını aktarın veya seçin."
            )
            return sonuc

        ana = ozet["ana_birim"]
        ref = (veriler.get("referans_birim") or ana).strip() or ana
        veriler["referans_birim"] = ref
        veriler["stok_id"] = ozet["id"]
        veriler["stok_kodu"] = ozet["stok_kodu"]
        veriler["ana_birim"] = ana

        if birim_anahtari(veriler["yeni_birim"]) == birim_anahtari(ana):
            sonuc.hata_ekle("Yeni birim, stokun temel birimiyle aynı olamaz; temel birim karttan yönetilir.")
            return sonuc

        bb = veriler.get("birim_barkodu")
        if bb:
            with get_session() as session:
                from database.models.stok import StokBirim

                baska_br = session.scalar(
                    select(StokBarkod).where(
                        StokBarkod.barkod == bb,
                        StokBarkod.stok_id != int(ozet["id"]),
                    )
                )
                baska_birim = session.scalar(
                    select(StokBirim).where(
                        StokBirim.birim_barkod == bb,
                        StokBirim.stok_id != int(ozet["id"]),
                    )
                )
                if baska_br is not None or baska_birim is not None:
                    sonuc.hata_ekle(f"Birim barkodu başka stokta kayıtlı: {bb}")
                    return sonuc

        mevcut = {birim_anahtari(ad) for ad in ozet["birim_adlari"]}
        anahtar = birim_anahtari(veriler["yeni_birim"])
        sonuc.hedef_tablo = "stok_birimleri"
        sonuc.hedef_id = int(ozet["id"])
        if anahtar in mevcut:
            if guncelleme_modu == "atla":
                sonuc.islem = "skip"
                sonuc.ozet = f"Atlandı: {ozet['stok_kodu']} / {veriler['yeni_birim']}"
            elif guncelleme_modu == "hata":
                sonuc.hata_ekle(f"Birim zaten tanımlı: {veriler['yeni_birim']}")
            else:
                sonuc.islem = "update"
                sonuc.ozet = f"Güncelle birim: {ozet['stok_kodu']} / {veriler['yeni_birim']} = {carpan}"
        else:
            sonuc.islem = "insert"
            sonuc.ozet = f"Yeni birim: {ozet['stok_kodu']} / {veriler['yeni_birim']} = {carpan}"
        return sonuc

    def uygula_satir(self, sonuc: SatirSonuc) -> dict[str, Any]:
        veriler = dict(sonuc.eslenen)
        stok_id = int(veriler["stok_id"])
        yeni = veriler["yeni_birim"]
        carpan = Decimal(str(veriler["carpan"]))
        ref = veriler.get("referans_birim") or veriler.get("ana_birim") or "Adet"
        metin = f"{carpan.normalize():f}"
        bb = veriler.get("birim_barkodu") or None
        satis = veriler.get("satis_fiyati")

        with get_session() as session:
            stok = session.scalar(
                select(StokKarti)
                .where(StokKarti.id == stok_id)
                .options(selectinload(StokKarti.birimler))
            )
            if stok is None:
                raise ValueError("Stok kartı bulunamadı.")
            onceki = StokService.birimleri_dict_listesi(stok)
            liste = list(onceki)
            anahtar = birim_anahtari(yeni)
            mevcut = next(
                (b for b in liste if birim_anahtari(b.get("birim_adi")) == anahtar),
                None,
            )
            kayit = {
                "birim_adi": yeni,
                "carpan": metin,
                "referans_birim": ref,
                "referans_carpan": metin,
                "aktif": True,
                "alis_kullanilabilir": True,
                "satis_kullanilabilir": True,
                "birim_barkod": bb,
            }
            if satis is not None:
                kayit["satis_1"] = str(satis)
            if mevcut is not None:
                mevcut.update(kayit)
            else:
                liste.append(kayit)

        StokService.stok_birimleri_kaydet(stok_id, liste)

        return {
            "hedef_tablo": "stok_birimleri",
            "hedef_id": stok_id,
            "islem": sonuc.islem,
            "onceki": {"birimler": onceki},
            "sonraki": {
                "stok_kodu": veriler.get("stok_kodu"),
                "birim": yeni,
                "carpan": metin,
                "birim_barkod": bb,
            },
        }

    def geri_al_degisiklik(self, change: dict[str, Any]) -> None:
        hedef_id = change.get("hedef_id")
        onceki = (change.get("onceki") or {}).get("birimler")
        if not hedef_id or onceki is None:
            return
        StokService.stok_birimleri_kaydet(int(hedef_id), list(onceki))


def _factory():
    return StokBirimImporter(STOK_BIRIM_TIPI)


STOK_BIRIM_TIPI = kaydet(
    ImportTipi(
        kod="stok_birim",
        ad="Stok Alternatif Birimleri",
        modul="stok",
        alanlar=[
            AlanTanimi("ana_barkod", "Ana Ürün Barkodu", ornek="0000123400015"),
            AlanTanimi("stok_kodu", "Stok Kodu", ornek="STK001", aciklama="Barkod yoksa eşleştirme anahtarı"),
            AlanTanimi("yeni_birim", "Yeni Birim", zorunlu=True, ornek="Paket 1000"),
            AlanTanimi("carpan", "İçerik Miktarı", zorunlu=True, ornek="1000"),
            AlanTanimi("referans_birim", "Referans Birim", ornek="Adet"),
            AlanTanimi("birim_barkodu", "Birim Barkodu", ornek="PKT1000-001"),
            AlanTanimi("satis_fiyati", "Satış Fiyatı 1", ornek="1200,00"),
        ],
        importer_factory=_factory,
        aciklama="Aynı ürüne alternatif birim, katsayı ve birim barkodu ekler/günceller. Stok miktarı oluşturmaz.",
        eslesen_basliklar=dict(_BASLIKLAR),
        izinler=("excel_aktarim", "excel_pdf", "stok_duzenleme", "yeni_kayit"),
    )
)
