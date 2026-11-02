"""Sipariş / irsaliye / teklif Excel importer — fatura satır doğrulamasını yeniden kullanır.

Taslak kayıt üretir; stok/cari hareketi onay aşamasına bırakılır.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from excel_aktarim.importers.fatura_excel import (
    FaturaExcelImporter,
    _ALANLAR,
    _BASLIKLAR,
)
from excel_aktarim.normalize import temiz
from excel_aktarim.types import AlanTanimi, ImportTipi, kaydet
from excel_aktarim.validation import SatirSonuc


class EvrakExcelImporter(FaturaExcelImporter):
    """yon: SATIS | ALIS; evrak: siparis | irsaliye | teklif"""

    def __init__(self, tip: ImportTipi, yon: str, evrak: str):
        super().__init__(tip, yon)
        self.evrak = (evrak or "").lower()

    def uygula_satir(self, sonuc: SatirSonuc) -> dict[str, Any]:
        grup = temiz((sonuc.eslenen or {}).get("fatura_grubu")) or "TEK"
        if grup in self._grup_uygulandi:
            return {
                "hedef_tablo": self._tablo_adi(),
                "hedef_id": None,
                "islem": "skip",
                "onceki": None,
                "sonraki": {"evrak_grubu": grup, "not": "grup zaten oluşturuldu"},
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
        tarih: date = bas["tarih"] if isinstance(bas["tarih"], date) else bas["tarih"]
        satirlar = []
        for u in uyeler:
            e = u.eslenen
            fiyat = e["birim_fiyat"]
            satir = {
                "stok_id": int(e["stok_id"]),
                "urun_kodu": e.get("stok_kodu") or e.get("urun_kodu"),
                "urun_adi": e.get("aciklama") or "",
                "aciklama": e.get("aciklama") or "",
                "miktar": e["miktar"],
                "birim": e.get("birim") or "Adet",
                "birim_fiyat": fiyat,
                "birim_satis_fiyati": fiyat,
                "birim_alis_fiyati": fiyat,
                "iskonto_orani": e.get("iskonto_1") or 0,
                "kdv_orani": e.get("kdv_orani") if e.get("kdv_orani") is not None else 20,
                "lot_no": e.get("lot") or None,
            }
            satirlar.append(satir)

        belge = self._kaydet(bas, tarih, satirlar, grup)
        return {
            "hedef_tablo": self._tablo_adi(),
            "hedef_id": int(getattr(belge, "id")),
            "islem": "insert",
            "onceki": None,
            "sonraki": {
                "evrak_grubu": grup,
                "belge_no": self._belge_no(belge),
                "satir_adet": len(satirlar),
                "onaylandi": False,
                "evrak": self.evrak,
            },
        }

    def _tablo_adi(self) -> str:
        if self.evrak == "siparis":
            return "satis_siparisleri" if self.yon == "SATIS" else "alis_siparisleri"
        if self.evrak == "irsaliye":
            return "satis_irsaliyeleri" if self.yon == "SATIS" else "alis_irsaliyeleri"
        return "satis_teklifleri"

    def _belge_no(self, belge: Any) -> str | None:
        for attr in ("siparis_no", "irsaliye_no", "teklif_no", "fatura_no", "belge_no"):
            v = getattr(belge, attr, None)
            if v:
                return str(v)
        return None

    def _kaydet(self, bas: dict, tarih: date, satirlar: list[dict], grup: str) -> Any:
        depo = bas.get("depo") or "ANA DEPO"
        pb = bas.get("para_birimi") or "TRY"
        cari_id = int(bas["cari_id"])
        belge_no = bas.get("belge_no") or None
        aciklama = f"Excel aktarım grup {grup}"

        if self.evrak == "siparis" and self.yon == "SATIS":
            from database.satis_siparisi_service import SatisSiparisiService

            veriler = {
                "siparis_tarihi": tarih,
                "termin_tarihi": tarih + timedelta(days=7),
                "cari_id": cari_id,
                "depo": depo,
                "aciklama": aciklama,
                "para_birimi": pb,
                "kur": 1,
                "onayla": False,
            }
            if belge_no:
                veriler["siparis_no"] = belge_no
            return SatisSiparisiService.kaydet(veriler, satirlar, [])

        if self.evrak == "siparis" and self.yon == "ALIS":
            from database.alis_siparisi_service import AlisSiparisiService, DURUM_TASLAK

            veriler = {
                "siparis_tarihi": tarih,
                "termin_tarihi": tarih + timedelta(days=7),
                "cari_id": cari_id,
                "depo": depo,
                "aciklama": aciklama,
                "para_birimi": pb,
                "durum": DURUM_TASLAK,
            }
            if belge_no:
                veriler["siparis_no"] = belge_no
            return AlisSiparisiService.kaydet(veriler, satirlar, [])

        if self.evrak == "irsaliye" and self.yon == "SATIS":
            from database.satis_irsaliyesi_service import SatisIrsaliyesiService

            veriler = {
                "irsaliye_tarihi": tarih,
                "cari_id": cari_id,
                "depo": depo,
                "aciklama": aciklama,
                "para_birimi": pb,
            }
            if belge_no:
                veriler["irsaliye_no"] = belge_no
            return SatisIrsaliyesiService.kaydet(veriler, satirlar)

        if self.evrak == "irsaliye" and self.yon == "ALIS":
            from database.alis_irsaliyesi_service import AlisIrsaliyesiService

            veriler = {
                "irsaliye_tarihi": tarih,
                "cari_id": cari_id,
                "depo": depo,
                "aciklama": aciklama,
                "para_birimi": pb,
            }
            if belge_no:
                veriler["irsaliye_no"] = belge_no
            return AlisIrsaliyesiService.kaydet(veriler, satirlar)

        if self.evrak == "teklif":
            from database.teklif_service import QuoteService

            veriler = {
                "teklif_tarihi": tarih,
                "gecerlilik_tarihi": tarih + timedelta(days=30),
                "cari_id": cari_id,
                "depo": depo,
                "aciklama": aciklama,
                "para_birimi": pb,
                "durum": "TASLAK",
            }
            if belge_no:
                veriler["teklif_no"] = belge_no
            return QuoteService.kaydet(veriler, satirlar)

        raise ValueError(f"Desteklenmeyen evrak: {self.evrak}/{self.yon}")


def _alanlar() -> list[AlanTanimi]:
    # fatura_grubu etiketi evrak grubu olarak kullanılır
    return list(_ALANLAR)


def _kayit(kod: str, ad: str, modul: str, yon: str, evrak: str, izinler: tuple[str, ...], aciklama: str):
    tip_holder: dict[str, ImportTipi] = {}

    def _factory():
        return EvrakExcelImporter(tip_holder["tip"], yon, evrak)

    tip = kaydet(
        ImportTipi(
            kod=kod,
            ad=ad,
            modul=modul,
            alanlar=_alanlar(),
            importer_factory=_factory,
            aciklama=aciklama,
            eslesen_basliklar=dict(_BASLIKLAR),
            izinler=izinler,
        )
    )
    tip_holder["tip"] = tip
    return tip


SATIS_SIPARIS_TIPI = _kayit(
    "satis_siparis_excel",
    "Satış Siparişi (Excel)",
    "satis",
    "SATIS",
    "siparis",
    ("excel_aktarim", "excel_pdf", "satis_duzenleme", "yeni_kayit"),
    "Sipariş grubu satırlarından onaysız satış siparişi taslağı.",
)
ALIS_SIPARIS_TIPI = _kayit(
    "alis_siparis_excel",
    "Alış Siparişi (Excel)",
    "satin_alma",
    "ALIS",
    "siparis",
    ("excel_aktarim", "excel_pdf", "alis_duzenleme", "yeni_kayit"),
    "Sipariş grubu satırlarından onaysız alış siparişi taslağı.",
)
SATIS_IRSALIYE_TIPI = _kayit(
    "satis_irsaliye_excel",
    "Satış İrsaliyesi (Excel)",
    "satis",
    "SATIS",
    "irsaliye",
    ("excel_aktarim", "excel_pdf", "satis_duzenleme", "yeni_kayit"),
    "İrsaliye grubu satırlarından onaysız satış irsaliyesi taslağı.",
)
ALIS_IRSALIYE_TIPI = _kayit(
    "alis_irsaliye_excel",
    "Alış İrsaliyesi (Excel)",
    "satin_alma",
    "ALIS",
    "irsaliye",
    ("excel_aktarim", "excel_pdf", "alis_duzenleme", "alis_irsaliye_duzenleme", "yeni_kayit"),
    "İrsaliye grubu satırlarından onaysız alış irsaliyesi taslağı.",
)
TEKLIF_TIPI = _kayit(
    "teklif_excel",
    "Satış Teklifi (Excel)",
    "satis",
    "SATIS",
    "teklif",
    ("excel_aktarim", "excel_pdf", "satis_duzenleme", "yeni_kayit"),
    "Teklif grubu satırlarından taslak teklif.",
)
