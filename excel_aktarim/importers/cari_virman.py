"""Cari virman Excel importer — mevcut CariService.virman_yap kullanır."""

from __future__ import annotations

from typing import Any

from database.cari_service import CariService
from excel_aktarim.importers.base import BaseImporter
from excel_aktarim.normalize import decimal_parse, tarih_parse, temiz
from excel_aktarim.types import AlanTanimi, ImportTipi, kaydet
from excel_aktarim.validation import SatirSonuc

_BASLIKLAR = {
    "kaynakkodu": "kaynak_kodu",
    "kaynak": "kaynak_kodu",
    "from": "kaynak_kodu",
    "hedefkodu": "hedef_kodu",
    "hedef": "hedef_kodu",
    "to": "hedef_kodu",
    "tarih": "tarih",
    "islemtarihi": "tarih",
    "tutar": "tutar",
    "miktar": "tutar",
    "aciklama": "aciklama",
    "belgeno": "belge_no",
    "belge": "belge_no",
}


class CariVirmanImporter(BaseImporter):
    def __init__(self, tip: ImportTipi):
        self.tip = tip

    def dogrula_satir(
        self,
        satir_no: int,
        eslenen: dict[str, Any],
        *,
        guncelleme_modu: str = "guncelle",
    ) -> SatirSonuc:
        sonuc = SatirSonuc(satir_no=satir_no, ham=dict(eslenen), eslenen={})
        kaynak = temiz(eslenen.get("kaynak_kodu"))
        hedef = temiz(eslenen.get("hedef_kodu"))
        if not kaynak:
            sonuc.hata_ekle("Kaynak cari kodu zorunludur.")
        if not hedef:
            sonuc.hata_ekle("Hedef cari kodu zorunludur.")
        if kaynak and hedef and kaynak == hedef:
            sonuc.hata_ekle("Kaynak ve hedef aynı olamaz.")

        try:
            tarih = tarih_parse(eslenen.get("tarih"))
        except ValueError as exc:
            sonuc.hata_ekle(str(exc))
            tarih = None
        if tarih is None and sonuc.gecerli:
            sonuc.hata_ekle("Tarih zorunludur.")
        try:
            tutar = decimal_parse(eslenen.get("tutar"), alan="Tutar")
        except ValueError as exc:
            sonuc.hata_ekle(str(exc))
            tutar = None
        if tutar is None and "Tutar" not in " ".join(sonuc.mesajlar):
            sonuc.hata_ekle("Tutar zorunludur.")
        elif tutar is not None and tutar <= 0:
            sonuc.hata_ekle("Tutar pozitif olmalıdır.")

        if kaynak and CariService.kod_ile_getir(kaynak) is None:
            sonuc.hata_ekle(f"Kaynak cari bulunamadı: {kaynak}")
        if hedef and CariService.kod_ile_getir(hedef) is None:
            sonuc.hata_ekle(f"Hedef cari bulunamadı: {hedef}")

        if not sonuc.gecerli:
            return sonuc

        sonuc.eslenen = {
            "kaynak_kodu": kaynak,
            "hedef_kodu": hedef,
            "tarih": tarih,
            "tutar": tutar,
            "aciklama": temiz(eslenen.get("aciklama")) or None,
            "belge_no": temiz(eslenen.get("belge_no")) or None,
        }
        sonuc.islem = "insert"
        sonuc.hedef_tablo = "cari_islemleri"
        sonuc.ozet = f"Virman {kaynak} → {hedef}: {tutar}"
        return sonuc

    def uygula_satir(self, sonuc: SatirSonuc) -> dict[str, Any]:
        v = sonuc.eslenen
        kaynak = CariService.kod_ile_getir(v["kaynak_kodu"])
        hedef = CariService.kod_ile_getir(v["hedef_kodu"])
        if kaynak is None or hedef is None:
            raise ValueError("Cari bulunamadı.")

        # CariService.virman_yap imzasını kontrol et
        tarih = v.get("tarih")
        if tarih is None:
            raise ValueError("Tarih zorunludur.")
        sonuc_v = CariService.virman_yap(
            kaynak.id,
            hedef.id,
            tarih,
            v["tutar"],
            aciklama=v.get("aciklama"),
            belge_no=v.get("belge_no"),
        )
        hedef_id = None
        if isinstance(sonuc_v, tuple) and sonuc_v:
            hedef_id = getattr(sonuc_v[0], "id", None)
        elif hasattr(sonuc_v, "id"):
            hedef_id = sonuc_v.id

        return {
            "hedef_tablo": "cari_islemleri",
            "hedef_id": hedef_id,
            "islem": "insert",
            "onceki": None,
            "sonraki": {
                "kaynak_kodu": v["kaynak_kodu"],
                "hedef_kodu": v["hedef_kodu"],
                "tutar": str(v["tutar"]),
            },
            "tutar": v["tutar"],
        }

    def geri_al_degisiklik(self, change: dict[str, Any]) -> None:
        # Virman geri alma karmaşık; güvenlik için bilinçli olarak desteklenmez
        raise ValueError(
            "Cari virman aktarımları otomatik geri alınamaz. "
            "Gerekirse karşı virman fişi oluşturun."
        )


def _factory():
    return CariVirmanImporter(VIRMAN_TIPI)


VIRMAN_TIPI = kaydet(
    ImportTipi(
        kod="cari_virman",
        ad="Cari Virman Fişleri",
        modul="satin_alma",
        alanlar=[
            AlanTanimi("kaynak_kodu", "Kaynak Cari Kodu", zorunlu=True, ornek="M00001"),
            AlanTanimi("hedef_kodu", "Hedef Cari Kodu", zorunlu=True, ornek="T00001"),
            AlanTanimi("tarih", "Tarih", zorunlu=True, ornek="17.09.2026"),
            AlanTanimi("tutar", "Tutar", zorunlu=True, ornek="1500,00"),
            AlanTanimi("aciklama", "Açıklama", ornek="Borç devri"),
            AlanTanimi("belge_no", "Belge No", ornek="VRM-001"),
        ],
        importer_factory=_factory,
        aciklama="Cari virman fişlerini Excel'den oluşturur.",
        eslesen_basliklar=dict(_BASLIKLAR),
        izinler=("excel_aktarim", "excel_pdf", "cari_duzenleme"),
    )
)

# Satış menüsünden de erişilebilir kopya (aynı kod, farklı menü listesi için ikinci tip)
kaydet(
    ImportTipi(
        kod="cari_virman_satis",
        ad="Cari Virman Fişleri",
        modul="satis",
        alanlar=list(VIRMAN_TIPI.alanlar),
        importer_factory=_factory,
        aciklama=VIRMAN_TIPI.aciklama,
        eslesen_basliklar=dict(_BASLIKLAR),
        izinler=VIRMAN_TIPI.izinler,
    )
)
