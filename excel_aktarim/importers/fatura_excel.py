"""Satış / alış fatura Excel importer — satırlar fatura grubuna göre taslak oluşturur.

Kesinleştirme / stok hareketi yok; SatisFaturasiService.kaydet / AlisFaturasiService.kaydet
(onaysız). Aynı gruptaki bir satır hatalıysa grubun tamamı engellenir.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.database import get_session
from database.models.cari import Cari
from database.models.stok import StokBarkod, StokKarti
from excel_aktarim.importers.base import BaseImporter
from excel_aktarim.normalize import decimal_parse, tarih_parse, temiz
from excel_aktarim.types import AlanTanimi, ImportTipi, kaydet
from excel_aktarim.validation import DogrulamaRaporu, SatirSonuc

_BASLIKLAR = {
    "faturagrubu": "fatura_grubu",
    "grup": "fatura_grubu",
    "belgeturu": "belge_turu",
    "tur": "belge_turu",
    "belgeno": "belge_no",
    "faturano": "belge_no",
    "evrakno": "belge_no",
    "tarih": "tarih",
    "faturatarihi": "tarih",
    "carikodu": "cari_kodu",
    "musterikodu": "cari_kodu",
    "tedarikcikodu": "cari_kodu",
    "paribirimi": "para_birimi",
    "doviz": "para_birimi",
    "depo": "depo",
    "urunbarkodu": "urun_kodu",
    "barkod": "urun_kodu",
    "urunkodu": "urun_kodu",
    "stokkodu": "urun_kodu",
    "kod": "urun_kodu",
    "urunaciklamasi": "aciklama",
    "aciklama": "aciklama",
    "urunadi": "aciklama",
    "miktar": "miktar",
    "birim": "birim",
    "birimfiyat": "birim_fiyat",
    "fiyat": "birim_fiyat",
    "iskonto": "iskonto_1",
    "iskonto1": "iskonto_1",
    "iskontooranı": "iskonto_1",
    "iskontoorani": "iskonto_1",
    "kdvorani": "kdv_orani",
    "kdv": "kdv_orani",
    "fiyatesasi": "fiyat_esasi",
    "kdvdahil": "fiyat_esasi",
    "lot": "lot",
    "kaynaklot": "lot",
}

_ALANLAR = [
    AlanTanimi("fatura_grubu", "Fatura Grubu", zorunlu=True, ornek="SATIS-001"),
    AlanTanimi("belge_turu", "Belge Türü", ornek="SATIS", aciklama="SATIS veya ALIS"),
    AlanTanimi("belge_no", "Belge No", ornek="ORNEK-SF-001"),
    AlanTanimi("tarih", "Tarih", zorunlu=True, ornek="19.10.2026"),
    AlanTanimi("cari_kodu", "Cari Kodu", zorunlu=True, ornek="ORNEK-M001"),
    AlanTanimi("para_birimi", "Para Birimi", ornek="TRY"),
    AlanTanimi("depo", "Depo", ornek="ANA DEPO"),
    AlanTanimi("urun_kodu", "Ürün Barkodu veya Kodu", zorunlu=True, ornek="0000123400015"),
    AlanTanimi("aciklama", "Ürün Açıklaması", ornek=""),
    AlanTanimi("miktar", "Miktar", zorunlu=True, ornek="2"),
    AlanTanimi("birim", "Birim", zorunlu=True, ornek="Paket 1000"),
    AlanTanimi("birim_fiyat", "Birim Fiyat", zorunlu=True, ornek="1200,00"),
    AlanTanimi("iskonto_1", "İskonto %", ornek="0"),
    AlanTanimi("kdv_orani", "KDV %", zorunlu=True, ornek="20"),
    AlanTanimi("fiyat_esasi", "Fiyat Esası", ornek="Hariç"),
    AlanTanimi("lot", "Lot", ornek=""),
]


class FaturaExcelImporter(BaseImporter):
    tip: ImportTipi
    yon: str  # SATIS | ALIS

    def __init__(self, tip: ImportTipi, yon: str):
        self.tip = tip
        self.yon = yon.upper()
        self._grup_uygulandi: set[str] = set()
        self._grup_satirlari: dict[str, list[SatirSonuc]] = {}

    def dogrula_satirlar(
        self,
        satirlar: list[dict[str, Any]],
        *,
        guncelleme_modu: str = "guncelle",
    ) -> DogrulamaRaporu:
        rapor = DogrulamaRaporu()
        for i, satir in enumerate(satirlar, start=2):
            rapor.satirlar.append(self.dogrula_satir(i, satir, guncelleme_modu=guncelleme_modu))
        # Grup tutarlılığı: bir satır hatalıysa grubun hepsi engellenir
        gruplar: dict[str, list[SatirSonuc]] = defaultdict(list)
        for s in rapor.satirlar:
            g = temiz((s.eslenen or {}).get("fatura_grubu")) or f"__satir_{s.satir_no}"
            gruplar[g].append(s)
        for _g, uyeler in gruplar.items():
            if any(not u.gecerli for u in uyeler):
                for u in uyeler:
                    if u.gecerli:
                        u.hata_ekle("Aynı fatura grubunda başka satırda kritik hata var; grup aktarılamaz.")
            else:
                # Üst bilgi tutarlılığı
                anahtarlar = ("belge_no", "tarih", "cari_kodu", "para_birimi", "depo", "fiyat_esasi")
                ref = uyeler[0].eslenen
                for u in uyeler[1:]:
                    for a in anahtarlar:
                        v0 = str(ref.get(a) or "")
                        v1 = str(u.eslenen.get(a) or "")
                        if v0 != v1:
                            u.hata_ekle(f"Grup içi «{a}» tutarsız: «{v0}» ≠ «{v1}»")
                            uyeler[0].hata_ekle(f"Grup içi «{a}» tutarsız (satır {u.satir_no}).")
        self._grup_satirlari = dict(gruplar)
        for s in rapor.satirlar:
            if s.gecerli and s.islem != "skip":
                s.islem = "insert"
                s.hedef_tablo = "satis_faturalari" if self.yon == "SATIS" else "alis_faturalari"
                s.ozet = s.ozet or f"Taslak satır: {s.eslenen.get('urun_kodu')}"
        rapor.ozetle()
        return rapor

    def _stok_bul(self, kod: str) -> dict[str, Any] | None:
        kod = temiz(kod)
        if not kod:
            return None
        with get_session() as session:
            stok = session.scalar(
                select(StokKarti)
                .where(StokKarti.stok_kodu == kod, StokKarti.is_deleted.is_(False))
                .options(selectinload(StokKarti.birimler))
            )
            if stok is None:
                br = session.scalar(select(StokBarkod).where(StokBarkod.barkod == kod))
                if br is not None:
                    stok = session.scalar(
                        select(StokKarti)
                        .where(StokKarti.id == br.stok_id, StokKarti.is_deleted.is_(False))
                        .options(selectinload(StokKarti.birimler))
                    )
                    birim_br = br.birim
                else:
                    birim_br = None
            else:
                birim_br = None
            if stok is None:
                return None
            return {
                "id": int(stok.id),
                "stok_kodu": stok.stok_kodu,
                "stok_adi": stok.stok_adi,
                "birim": (stok.birim or "Adet"),
                "barkod_birim": birim_br,
                "birimler": [b.birim_adi for b in (stok.birimler or [])],
            }

    def _cari_bul(self, kod: str) -> dict[str, Any] | None:
        kod = temiz(kod)
        if not kod:
            return None
        with get_session() as session:
            cari = session.scalar(
                select(Cari).where(Cari.cari_kodu == kod, Cari.is_deleted.is_(False))
            )
            if cari is None:
                return None
            return {"id": int(cari.id), "cari_kodu": cari.cari_kodu, "unvan": cari.unvan}

    def dogrula_satir(
        self,
        satir_no: int,
        eslenen: dict[str, Any],
        *,
        guncelleme_modu: str = "guncelle",
    ) -> SatirSonuc:
        sonuc = SatirSonuc(satir_no=satir_no, ham=dict(eslenen), eslenen={})
        try:
            veriler: dict[str, Any] = {
                "fatura_grubu": temiz(eslenen.get("fatura_grubu")) or temiz(eslenen.get("belge_no")) or "TEK",
                "belge_turu": temiz(eslenen.get("belge_turu")) or self.yon,
                "belge_no": temiz(eslenen.get("belge_no")),
                "cari_kodu": temiz(eslenen.get("cari_kodu")),
                "para_birimi": temiz(eslenen.get("para_birimi")) or "TRY",
                "depo": temiz(eslenen.get("depo")) or "ANA DEPO",
                "urun_kodu": temiz(eslenen.get("urun_kodu")),
                "aciklama": temiz(eslenen.get("aciklama")),
                "birim": temiz(eslenen.get("birim")) or "Adet",
                "fiyat_esasi": temiz(eslenen.get("fiyat_esasi")) or "Hariç",
                "lot": temiz(eslenen.get("lot")),
            }
            if temiz(eslenen.get("tarih")):
                veriler["tarih"] = tarih_parse(eslenen["tarih"])
            else:
                veriler["tarih"] = None
            veriler["miktar"] = (
                decimal_parse(eslenen["miktar"], alan="Miktar")
                if temiz(eslenen.get("miktar"))
                else None
            )
            bf_ham = eslenen.get("birim_fiyat")
            bf_metin = str(bf_ham).strip() if bf_ham is not None else ""
            if bf_metin == "":
                veriler["birim_fiyat"] = None
            elif bf_metin in ("0", "0,0", "0.0", "0,00"):
                veriler["birim_fiyat"] = Decimal("0")
            else:
                veriler["birim_fiyat"] = decimal_parse(bf_ham, alan="Birim Fiyat")
            veriler["iskonto_1"] = (
                decimal_parse(eslenen["iskonto_1"], alan="İskonto")
                if temiz(eslenen.get("iskonto_1"))
                else Decimal("0")
            )
            kdv_ham = eslenen.get("kdv_orani")
            if kdv_ham is None or str(kdv_ham).strip() == "":
                veriler["kdv_orani"] = None
            else:
                veriler["kdv_orani"] = decimal_parse(kdv_ham, alan="KDV")
        except ValueError as exc:
            sonuc.hata_ekle(str(exc))
            return sonuc

        sonuc.eslenen = veriler
        if not veriler.get("tarih"):
            sonuc.hata_ekle("Tarih zorunludur.")
        if not veriler.get("cari_kodu"):
            sonuc.hata_ekle("Cari kodu zorunludur.")
        if not veriler.get("urun_kodu"):
            sonuc.hata_ekle("Ürün barkodu veya kodu zorunludur.")
        if veriler.get("miktar") is None or veriler["miktar"] <= 0:
            sonuc.hata_ekle("Miktar pozitif olmalıdır.")
        if veriler.get("birim_fiyat") is None:
            sonuc.hata_ekle("Birim fiyat zorunludur (açık sıfır kabul edilir).")
        if veriler.get("kdv_orani") is None:
            sonuc.hata_ekle("KDV % zorunludur (açık sıfır kabul edilir).")
        if not sonuc.gecerli:
            return sonuc

        cari = self._cari_bul(veriler["cari_kodu"])
        if cari is None:
            sonuc.hata_ekle(f"Cari bulunamadı: {veriler['cari_kodu']}")
            return sonuc
        veriler["cari_id"] = cari["id"]

        stok = self._stok_bul(veriler["urun_kodu"])
        if stok is None:
            sonuc.hata_ekle(
                f"Stok bulunamadı: {veriler['urun_kodu']}. Ad benzerliği otomatik bağlanmaz."
            )
            return sonuc
        veriler["stok_id"] = stok["id"]
        veriler["stok_kodu"] = stok["stok_kodu"]
        if not veriler.get("aciklama"):
            veriler["aciklama"] = stok["stok_adi"]
        # Birim: barkod birimi veya verilen birim
        if stok.get("barkod_birim") and not temiz(eslenen.get("birim")):
            veriler["birim"] = stok["barkod_birim"]

        tur = (veriler.get("belge_turu") or self.yon).upper()
        if "ALIS" in tur or tur in ("A", "ALIŞ", "ALİŞ"):
            beklenen = "ALIS"
        else:
            beklenen = "SATIS"
        if beklenen != self.yon:
            sonuc.hata_ekle(
                f"Belge türü «{tur}» bu aktarım yönüyle ({self.yon}) uyuşmuyor."
            )
            return sonuc

        sonuc.islem = "insert"
        sonuc.ozet = (
            f"{veriler['fatura_grubu']}: {stok['stok_kodu']} "
            f"× {veriler['miktar']} {veriler['birim']}"
        )
        return sonuc

    def uygula_satir(self, sonuc: SatirSonuc) -> dict[str, Any]:
        grup = temiz((sonuc.eslenen or {}).get("fatura_grubu")) or "TEK"
        if grup in self._grup_uygulandi:
            return {
                "hedef_tablo": "satis_faturalari" if self.yon == "SATIS" else "alis_faturalari",
                "hedef_id": None,
                "islem": "skip",
                "onceki": None,
                "sonraki": {"fatura_grubu": grup, "not": "grup zaten oluşturuldu"},
            }

        uyeler = [
            s
            for s in (self._grup_satirlari.get(grup) or [sonuc])
            if s.gecerli and s.islem != "skip"
        ]
        if not uyeler:
            uyeler = [sonuc]
        self._grup_uygulandi.add(grup)

        bas = uyeler[0].eslenen
        tarih: date = bas["tarih"] if isinstance(bas["tarih"], date) else tarih_parse(bas["tarih"])
        vade = tarih + timedelta(days=0)
        veriler = {
            "fatura_no": bas.get("belge_no") or None,
            "fatura_tarihi": tarih,
            "vade_tarihi": vade,
            "cari_id": int(bas["cari_id"]),
            "depo": bas.get("depo") or "ANA DEPO",
            "aciklama": f"Excel aktarım grup {grup}",
            "para_birimi": bas.get("para_birimi") or "TRY",
        }
        satirlar = []
        for u in uyeler:
            e = u.eslenen
            satirlar.append(
                {
                    "stok_id": int(e["stok_id"]),
                    "urun_kodu": e.get("stok_kodu") or e.get("urun_kodu"),
                    "urun_adi": e.get("aciklama") or "",
                    "aciklama": e.get("aciklama") or "",
                    "miktar": e["miktar"],
                    "birim": e.get("birim") or "Adet",
                    "birim_fiyat": e["birim_fiyat"],
                    "birim_satis_fiyati": e["birim_fiyat"],
                    "iskonto_orani": e.get("iskonto_1") or 0,
                    "kdv_orani": e.get("kdv_orani") if e.get("kdv_orani") is not None else 20,
                    "lot_no": e.get("lot") or None,
                }
            )

        if self.yon == "SATIS":
            from database.satis_faturasi_service import SatisFaturasiService

            fatura = SatisFaturasiService.kaydet(veriler, satirlar)
            tablo = "satis_faturalari"
        else:
            from database.alis_faturasi_service import AlisFaturasiService

            # Stok/cari Onayla ile; dosya aktarımı yalnız onaysız taslak üretir.
            veriler["hareket_yaz"] = False
            fatura = AlisFaturasiService.kaydet(veriler, satirlar)
            tablo = "alis_faturalari"

        fid = int(getattr(fatura, "id"))
        return {
            "hedef_tablo": tablo,
            "hedef_id": fid,
            "islem": "insert",
            "onceki": None,
            "sonraki": {
                "fatura_grubu": grup,
                "fatura_no": getattr(fatura, "fatura_no", None),
                "satir_adet": len(satirlar),
                "onaylandi": False,
            },
        }

    def geri_al_degisiklik(self, change: dict[str, Any]) -> None:
        # Taslak soft iptal — onaylı değilse
        hedef_id = change.get("hedef_id")
        if not hedef_id:
            return
        if change.get("hedef_tablo") == "satis_faturalari":
            from database.satis_faturasi_service import SatisFaturasiService

            try:
                SatisFaturasiService.iptal_et(int(hedef_id), sebep="Excel aktarım geri alma")
            except Exception:
                pass
        else:
            from database.alis_faturasi_service import AlisFaturasiService

            try:
                AlisFaturasiService.iptal_et(int(hedef_id))
            except Exception:
                pass


def _factory_satis():
    return FaturaExcelImporter(SATIS_FATURA_TIPI, "SATIS")


def _factory_alis():
    return FaturaExcelImporter(ALIS_FATURA_TIPI, "ALIS")


SATIS_FATURA_TIPI = kaydet(
    ImportTipi(
        kod="satis_fatura_excel",
        ad="Satış Faturası (Excel)",
        modul="satis",
        alanlar=list(_ALANLAR),
        importer_factory=_factory_satis,
        aciklama="Fatura grubu satırlarından onaysız satış faturası taslağı. Stok çıkışı oluşmaz.",
        eslesen_basliklar=dict(_BASLIKLAR),
        izinler=("excel_aktarim", "excel_pdf", "satis_duzenleme", "yeni_kayit"),
    )
)

ALIS_FATURA_TIPI = kaydet(
    ImportTipi(
        kod="alis_fatura_excel",
        ad="Alış Faturası (Excel)",
        modul="satin_alma",
        alanlar=list(_ALANLAR),
        importer_factory=_factory_alis,
        aciklama="Fatura grubu satırlarından onaysız alış faturası taslağı.",
        eslesen_basliklar=dict(_BASLIKLAR),
        izinler=("excel_aktarim", "excel_pdf", "alis_duzenleme", "alis_fatura_duzenleme", "yeni_kayit"),
    )
)
