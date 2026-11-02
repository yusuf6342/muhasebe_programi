"""Çek/senet, gider fişi, depo transfer, konsinye — Excel importer'ları."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from excel_aktarim.importers.base import BaseImporter
from excel_aktarim.mukerrer import mukerrer_mi
from excel_aktarim.normalize import decimal_parse, tarih_parse, temiz
from excel_aktarim.types import AlanTanimi, ImportTipi, kaydet
from excel_aktarim.validation import SatirSonuc


class DepoTransferImporter(BaseImporter):
    tip: ImportTipi

    def __init__(self, tip: ImportTipi):
        self.tip = tip
        self._grup_uygulandi: set[str] = set()
        self._grup_satirlari: dict[str, list[SatirSonuc]] = {}

    def dogrula_satirlar(self, satirlar, *, guncelleme_modu="guncelle"):
        from excel_aktarim.validation import DogrulamaRaporu

        rapor = DogrulamaRaporu()
        self._grup_satirlari.clear()
        for i, satir in enumerate(satirlar, start=2):
            s = self.dogrula_satir(i, satir, guncelleme_modu=guncelleme_modu)
            rapor.satirlar.append(s)
            if s.gecerli:
                g = temiz((s.eslenen or {}).get("fis_grubu")) or "TEK"
                self._grup_satirlari.setdefault(g, []).append(s)
        rapor.ozetle()
        return rapor

    def dogrula_satir(self, satir_no, eslenen, *, guncelleme_modu="guncelle"):
        sonuc = SatirSonuc(satir_no=satir_no, ham=dict(eslenen), eslenen={})
        try:
            veriler = {
                "fis_grubu": temiz(eslenen.get("fis_grubu")) or "TEK",
                "fis_no": temiz(eslenen.get("fis_no")) or None,
                "fis_tarihi": tarih_parse(eslenen["fis_tarihi"]) if temiz(eslenen.get("fis_tarihi")) else None,
                "cikis_depo": temiz(eslenen.get("cikis_depo")),
                "giris_depo": temiz(eslenen.get("giris_depo")),
                "urun_kodu": temiz(eslenen.get("urun_kodu") or eslenen.get("stok_kodu")),
                "miktar": decimal_parse(eslenen["miktar"], alan="Miktar") if temiz(eslenen.get("miktar")) else None,
                "birim": temiz(eslenen.get("birim")) or "Adet",
            }
        except ValueError as exc:
            sonuc.hata_ekle(str(exc))
            return sonuc
        sonuc.eslenen = veriler
        for zorunlu, msg in (
            (veriler["fis_tarihi"], "Fiş tarihi zorunlu"),
            (veriler["cikis_depo"], "Çıkış depo zorunlu"),
            (veriler["giris_depo"], "Giriş depo zorunlu"),
            (veriler["urun_kodu"], "Ürün kodu zorunlu"),
            (veriler["miktar"] and veriler["miktar"] > 0, "Miktar pozitif olmalı"),
        ):
            if not zorunlu:
                sonuc.hata_ekle(msg)
        if not sonuc.gecerli:
            return sonuc
        if veriler["fis_no"]:
            var, gerekce = mukerrer_mi("depo_transfer", {"fis_no": veriler["fis_no"]})
            if var:
                sonuc.islem = "skip"
                sonuc.mesajlar.append(gerekce or "Mükerrer")
                return sonuc
        # stok bul
        from database.database import get_session
        from database.models.stok import StokBarkod, StokKarti
        from sqlalchemy import select

        with get_session() as session:
            kod = veriler["urun_kodu"]
            stok = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == kod))
            if stok is None:
                barkod = session.scalar(select(StokBarkod).where(StokBarkod.barkod == kod))
                if barkod is not None:
                    stok = session.get(StokKarti, barkod.stok_id)
            if stok is None:
                sonuc.hata_ekle(f"Stok bulunamadı: {kod}")
                return sonuc
            veriler["stok_id"] = stok.id
            veriler["stok_kodu"] = stok.stok_kodu
        sonuc.islem = "insert"
        sonuc.ozet = f"{veriler['fis_grubu']}: {veriler['stok_kodu']} × {veriler['miktar']}"
        return sonuc

    def uygula_satir(self, sonuc):
        if sonuc.islem == "skip":
            return {"hedef_tablo": "depo_transfer_fisleri", "hedef_id": None, "islem": "skip", "onceki": None, "sonraki": sonuc.eslenen}
        grup = temiz((sonuc.eslenen or {}).get("fis_grubu")) or "TEK"
        if grup in self._grup_uygulandi:
            return {"hedef_tablo": "depo_transfer_fisleri", "hedef_id": None, "islem": "skip", "onceki": None, "sonraki": {"fis_grubu": grup}}
        uyeler = [s for s in (self._grup_satirlari.get(grup) or [sonuc]) if s.gecerli and s.islem != "skip"]
        self._grup_uygulandi.add(grup)
        bas = uyeler[0].eslenen
        from database.stok_service import StokService

        veriler = {
            "fis_no": bas.get("fis_no"),
            "fis_tarihi": bas["fis_tarihi"],
            "cikis_depo": bas["cikis_depo"],
            "giris_depo": bas["giris_depo"],
            "aciklama": f"Excel aktarım {grup}",
        }
        satirlar = [
            {
                "stok_id": int(u.eslenen["stok_id"]),
                "urun_kodu": u.eslenen.get("stok_kodu") or u.eslenen.get("urun_kodu"),
                "urun_adi": u.eslenen.get("stok_kodu") or u.eslenen.get("urun_kodu") or "",
                "miktar": u.eslenen["miktar"],
                "birim": u.eslenen.get("birim") or "Adet",
            }
            for u in uyeler
        ]
        fis_veya_id = StokService.depo_transfer_kaydet(veriler, satirlar)
        # Servis bazen DepoTransferFisi, bazen int (fis.id) döner
        if isinstance(fis_veya_id, int):
            fis_id = fis_veya_id
            fis_no = veriler.get("fis_no")
        else:
            fis_id = int(fis_veya_id.id)
            fis_no = getattr(fis_veya_id, "fis_no", None) or veriler.get("fis_no")
        return {
            "hedef_tablo": "depo_transfer_fisleri",
            "hedef_id": fis_id,
            "islem": "insert",
            "onceki": None,
            "sonraki": {"fis_no": fis_no, "satir_adet": len(satirlar)},
        }


class GiderFisiImporter(BaseImporter):
    """Gider fişi — hizmet kodu + kasa/banka hesap adı ile; gerçek finans kaydı oluşturur."""

    tip: ImportTipi

    def __init__(self, tip: ImportTipi):
        self.tip = tip

    def dogrula_satir(self, satir_no, eslenen, *, guncelleme_modu="guncelle"):
        sonuc = SatirSonuc(satir_no=satir_no, ham=dict(eslenen), eslenen={})
        try:
            veriler = {
                "belge_no": temiz(eslenen.get("belge_no")) or None,
                "tarih": tarih_parse(eslenen["tarih"]) if temiz(eslenen.get("tarih")) else None,
                "tutar": decimal_parse(eslenen["tutar"], alan="Tutar") if temiz(eslenen.get("tutar")) else None,
                "hizmet_kodu": temiz(eslenen.get("hizmet_kodu")),
                "hesap_adi": temiz(eslenen.get("hesap_adi")),
                "aciklama": temiz(eslenen.get("aciklama")) or None,
            }
        except ValueError as exc:
            sonuc.hata_ekle(str(exc))
            return sonuc
        sonuc.eslenen = veriler
        if not veriler["tarih"]:
            sonuc.hata_ekle("Tarih zorunlu")
        if not veriler["tutar"] or veriler["tutar"] <= 0:
            sonuc.hata_ekle("Tutar pozitif olmalı")
        if not veriler["hizmet_kodu"]:
            sonuc.hata_ekle("Hizmet kodu zorunlu")
        if not veriler["hesap_adi"]:
            sonuc.hata_ekle("Ödeme hesap adı zorunlu")
        if not sonuc.gecerli:
            return sonuc
        if veriler["belge_no"]:
            var, gerekce = mukerrer_mi("gider_fisi", {"belge_no": veriler["belge_no"]})
            if var:
                sonuc.islem = "skip"
                sonuc.mesajlar.append(gerekce or "Mükerrer")
                return sonuc
        from database.database import get_session
        from database.models.finans import FinansHesabi
        from database.models.hizmet import HizmetKarti
        from sqlalchemy import select

        with get_session() as session:
            hizmet = session.scalar(select(HizmetKarti).where(HizmetKarti.hizmet_kodu == veriler["hizmet_kodu"]))
            if hizmet is None or not hizmet.aktif:
                sonuc.hata_ekle(f"Gider hizmet kartı bulunamadı: {veriler['hizmet_kodu']}")
                return sonuc
            hesap = session.scalar(select(FinansHesabi).where(FinansHesabi.hesap_adi == veriler["hesap_adi"]))
            if hesap is None or not hesap.aktif:
                sonuc.hata_ekle(f"Ödeme hesabı bulunamadı: {veriler['hesap_adi']}")
                return sonuc
            veriler["hizmet_id"] = hizmet.id
            veriler["finans_hesap_id"] = hesap.id
        sonuc.islem = "insert"
        sonuc.ozet = f"{veriler['hizmet_kodu']} {veriler['tutar']}"
        return sonuc

    def uygula_satir(self, sonuc):
        if sonuc.islem == "skip":
            return {"hedef_tablo": "gider_fisleri", "hedef_id": None, "islem": "skip", "onceki": None, "sonraki": sonuc.eslenen}
        from database.finans_service import FinansService

        e = sonuc.eslenen or {}
        payload = {
            "tarih": e["tarih"],
            "tutar": e["tutar"],
            "hizmet_id": int(e["hizmet_id"]),
            "finans_hesap_id": int(e["finans_hesap_id"]),
            "aciklama": e.get("aciklama"),
        }
        if e.get("belge_no"):
            payload["belge_no"] = e["belge_no"]
        fis = FinansService.gider_fisi_kaydet(payload)
        return {
            "hedef_tablo": "gider_fisleri",
            "hedef_id": int(fis.id),
            "islem": "insert",
            "onceki": None,
            "sonraki": {"belge_no": getattr(fis, "belge_no", None)},
        }


class CekSenetImporter(BaseImporter):
    tip: ImportTipi

    def __init__(self, tip: ImportTipi):
        self.tip = tip

    def dogrula_satir(self, satir_no, eslenen, *, guncelleme_modu="guncelle"):
        sonuc = SatirSonuc(satir_no=satir_no, ham=dict(eslenen), eslenen={})
        try:
            veriler = {
                "evrak_no": temiz(eslenen.get("evrak_no")),
                "evrak_turu": (temiz(eslenen.get("evrak_turu")) or "CEK").upper(),
                "islem_yonu": (temiz(eslenen.get("islem_yonu")) or "ALINAN").upper(),
                "cari_kodu": temiz(eslenen.get("cari_kodu")),
                "duzenleme_tarihi": tarih_parse(eslenen["duzenleme_tarihi"])
                if temiz(eslenen.get("duzenleme_tarihi"))
                else None,
                "vade_tarihi": tarih_parse(eslenen["vade_tarihi"]) if temiz(eslenen.get("vade_tarihi")) else None,
                "doviz_turu": (temiz(eslenen.get("doviz_turu")) or "TRY").upper(),
                "doviz_tutari": decimal_parse(eslenen["doviz_tutari"], alan="Tutar")
                if temiz(eslenen.get("doviz_tutari") or eslenen.get("tutar"))
                else None,
            }
            if veriler["doviz_tutari"] is None and temiz(eslenen.get("tutar")):
                veriler["doviz_tutari"] = decimal_parse(eslenen["tutar"], alan="Tutar")
        except ValueError as exc:
            sonuc.hata_ekle(str(exc))
            return sonuc
        sonuc.eslenen = veriler
        for ok, msg in (
            (veriler["evrak_no"], "Evrak no zorunlu"),
            (veriler["cari_kodu"], "Cari kodu zorunlu"),
            (veriler["duzenleme_tarihi"], "Düzenleme tarihi zorunlu"),
            (veriler["vade_tarihi"], "Vade tarihi zorunlu"),
            (veriler["doviz_tutari"] and veriler["doviz_tutari"] > 0, "Tutar pozitif olmalı"),
        ):
            if not ok:
                sonuc.hata_ekle(msg)
        if not sonuc.gecerli:
            return sonuc
        var, gerekce = mukerrer_mi("cek_senet", veriler)
        if var:
            sonuc.islem = "skip"
            sonuc.mesajlar.append(gerekce or "Mükerrer")
            return sonuc
        from database.database import get_session
        from database.models.cari import Cari
        from sqlalchemy import select

        with get_session() as session:
            cari = session.scalar(select(Cari).where(Cari.cari_kodu == veriler["cari_kodu"]))
            if cari is None:
                sonuc.hata_ekle(f"Cari bulunamadı: {veriler['cari_kodu']}")
                return sonuc
            veriler["cari_id"] = cari.id
        sonuc.islem = "insert"
        sonuc.ozet = f"{veriler['evrak_turu']} {veriler['evrak_no']}"
        return sonuc

    def uygula_satir(self, sonuc):
        if sonuc.islem == "skip":
            return {"hedef_tablo": "cek_senet_evraklari", "hedef_id": None, "islem": "skip", "onceki": None, "sonraki": sonuc.eslenen}
        from database.cek_senet_service import CekSenetService

        e = sonuc.eslenen or {}
        kayit = CekSenetService.olustur(
            {
                "cari_id": int(e["cari_id"]),
                "evrak_turu": e["evrak_turu"],
                "islem_yonu": e["islem_yonu"],
                "evrak_no": e["evrak_no"],
                "seri_no": None,
                "portfoy_no": None,
                "duzenleme_tarihi": e["duzenleme_tarihi"],
                "vade_tarihi": e["vade_tarihi"],
                "doviz_turu": e["doviz_turu"],
                "doviz_tutari": e["doviz_tutari"],
            }
        )
        return {
            "hedef_tablo": "cek_senet_evraklari",
            "hedef_id": int(kayit.get("id") or 0) or None,
            "islem": "insert",
            "onceki": None,
            "sonraki": kayit,
        }


class KonsinyeImporter(BaseImporter):
    """Konsinye teslim satırları — grup bazlı taslak (onayla=False)."""

    tip: ImportTipi

    def __init__(self, tip: ImportTipi):
        self.tip = tip
        self._grup_uygulandi: set[str] = set()
        self._grup_satirlari: dict[str, list[SatirSonuc]] = {}

    def dogrula_satirlar(self, satirlar, *, guncelleme_modu="guncelle"):
        from excel_aktarim.validation import DogrulamaRaporu

        rapor = DogrulamaRaporu()
        self._grup_satirlari.clear()
        for i, satir in enumerate(satirlar, start=2):
            s = self.dogrula_satir(i, satir, guncelleme_modu=guncelleme_modu)
            rapor.satirlar.append(s)
            if s.gecerli:
                g = temiz((s.eslenen or {}).get("teslim_grubu")) or "TEK"
                self._grup_satirlari.setdefault(g, []).append(s)
        rapor.ozetle()
        return rapor

    def dogrula_satir(self, satir_no, eslenen, *, guncelleme_modu="guncelle"):
        sonuc = SatirSonuc(satir_no=satir_no, ham=dict(eslenen), eslenen={})
        try:
            veriler = {
                "teslim_grubu": temiz(eslenen.get("teslim_grubu")) or "TEK",
                "yon": (temiz(eslenen.get("yon")) or "VERILEN").upper(),
                "cari_kodu": temiz(eslenen.get("cari_kodu")),
                "depo_adi": temiz(eslenen.get("depo") or eslenen.get("depo_adi")),
                "belge_tarihi": tarih_parse(eslenen["belge_tarihi"])
                if temiz(eslenen.get("belge_tarihi") or eslenen.get("tarih"))
                else None,
                "urun_kodu": temiz(eslenen.get("urun_kodu") or eslenen.get("stok_kodu")),
                "miktar": decimal_parse(eslenen["miktar"], alan="Miktar") if temiz(eslenen.get("miktar")) else None,
                "birim": temiz(eslenen.get("birim")) or "Adet",
            }
            if veriler["belge_tarihi"] is None and temiz(eslenen.get("tarih")):
                veriler["belge_tarihi"] = tarih_parse(eslenen["tarih"])
        except ValueError as exc:
            sonuc.hata_ekle(str(exc))
            return sonuc
        sonuc.eslenen = veriler
        for ok, msg in (
            (veriler["yon"] in ("VERILEN", "ALINAN"), "Yön VERILEN veya ALINAN olmalı"),
            (veriler["cari_kodu"], "Cari kodu zorunlu"),
            (veriler["depo_adi"], "Depo zorunlu"),
            (veriler["belge_tarihi"], "Belge tarihi zorunlu"),
            (veriler["urun_kodu"], "Ürün kodu zorunlu"),
            (veriler["miktar"] and veriler["miktar"] > 0, "Miktar pozitif olmalı"),
        ):
            if not ok:
                sonuc.hata_ekle(msg)
        if not sonuc.gecerli:
            return sonuc
        from database.database import get_session
        from database.models.cari import Cari
        from database.models.stok import Depo, StokBarkod, StokKarti
        from sqlalchemy import select

        with get_session() as session:
            cari = session.scalar(select(Cari).where(Cari.cari_kodu == veriler["cari_kodu"]))
            if cari is None:
                sonuc.hata_ekle(f"Cari bulunamadı: {veriler['cari_kodu']}")
                return sonuc
            depo = session.scalar(select(Depo).where(Depo.ad == veriler["depo_adi"]))
            if depo is None:
                sonuc.hata_ekle(f"Depo bulunamadı: {veriler['depo_adi']}")
                return sonuc
            kod = veriler["urun_kodu"]
            stok = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == kod))
            if stok is None:
                b = session.scalar(select(StokBarkod).where(StokBarkod.barkod == kod))
                if b is not None:
                    stok = session.get(StokKarti, b.stok_id)
            if stok is None:
                sonuc.hata_ekle(f"Stok bulunamadı: {kod}")
                return sonuc
            veriler["cari_id"] = cari.id
            veriler["depo_id"] = depo.id
            veriler["stok_id"] = stok.id
        sonuc.islem = "insert"
        sonuc.ozet = f"{veriler['teslim_grubu']}: {veriler['urun_kodu']} × {veriler['miktar']}"
        return sonuc

    def uygula_satir(self, sonuc):
        if sonuc.islem == "skip":
            return {"hedef_tablo": "konsinye_teslim", "hedef_id": None, "islem": "skip", "onceki": None, "sonraki": sonuc.eslenen}
        grup = temiz((sonuc.eslenen or {}).get("teslim_grubu")) or "TEK"
        if grup in self._grup_uygulandi:
            return {"hedef_tablo": "konsinye_teslim", "hedef_id": None, "islem": "skip", "onceki": None, "sonraki": {"teslim_grubu": grup}}
        uyeler = [s for s in (self._grup_satirlari.get(grup) or [sonuc]) if s.gecerli and s.islem != "skip"]
        self._grup_uygulandi.add(grup)
        bas = uyeler[0].eslenen
        from database.konsinye_service import KonsinyeService

        satirlar = [
            {
                "stok_id": int(u.eslenen["stok_id"]),
                "stok_kodu": u.eslenen.get("stok_kodu") or u.eslenen.get("urun_kodu"),
                "miktar": u.eslenen["miktar"],
                "birim": u.eslenen.get("birim") or "Adet",
            }
            for u in uyeler
        ]
        kayit = KonsinyeService.teslim_kaydet(
            yon=bas["yon"],
            cari_id=int(bas["cari_id"]),
            depo_id=int(bas["depo_id"]),
            belge_tarihi=bas["belge_tarihi"],
            satirlar=satirlar,
            aciklama=f"Excel aktarım {grup}",
            onayla=False,
        )
        return {
            "hedef_tablo": "konsinye_teslim",
            "hedef_id": int(kayit.get("id") or 0) or None,
            "islem": "insert",
            "onceki": None,
            "sonraki": kayit,
        }


def _kaydet_tip(kod, ad, modul, alanlar, factory, basliklar, izinler, aciklama):
    return kaydet(
        ImportTipi(
            kod=kod,
            ad=ad,
            modul=modul,
            alanlar=alanlar,
            importer_factory=factory,
            eslesen_basliklar=basliklar,
            izinler=izinler,
            aciklama=aciklama,
        )
    )


DEPO_TRANSFER_TIPI = _kaydet_tip(
    "depo_transfer",
    "Depo Transfer Fişi",
    "stok",
    [
        AlanTanimi("fis_grubu", "Fiş Grubu", zorunlu=True, ornek="TR-001"),
        AlanTanimi("fis_no", "Fiş No", ornek=""),
        AlanTanimi("fis_tarihi", "Fiş Tarihi", zorunlu=True, ornek="02.11.2026"),
        AlanTanimi("cikis_depo", "Çıkış Depo", zorunlu=True, ornek="ANA DEPO"),
        AlanTanimi("giris_depo", "Giriş Depo", zorunlu=True, ornek="ŞUBE DEPO"),
        AlanTanimi("urun_kodu", "Ürün Kodu / Barkod", zorunlu=True, ornek="0000123400015"),
        AlanTanimi("miktar", "Miktar", zorunlu=True, ornek="1"),
        AlanTanimi("birim", "Birim", ornek="Adet"),
    ],
    lambda: DepoTransferImporter(DEPO_TRANSFER_TIPI),
    {
        "fisgrubu": "fis_grubu",
        "grup": "fis_grubu",
        "fisno": "fis_no",
        "fistarihi": "fis_tarihi",
        "tarih": "fis_tarihi",
        "cikisdepo": "cikis_depo",
        "girisdepo": "giris_depo",
        "urunkodu": "urun_kodu",
        "stokkodu": "urun_kodu",
        "barkod": "urun_kodu",
        "miktar": "miktar",
        "birim": "birim",
    },
    ("excel_aktarim", "excel_pdf", "stok_duzenleme"),
    "Depo transfer fişi (stok hareketi servis kurallarına bağlı).",
)

GIDER_FISI_TIPI = _kaydet_tip(
    "gider_fisi",
    "Gider Fişi",
    "gelir_gider",
    [
        AlanTanimi("belge_no", "Belge No", ornek=""),
        AlanTanimi("tarih", "Tarih", zorunlu=True, ornek="02.11.2026"),
        AlanTanimi("tutar", "Tutar", zorunlu=True, ornek="100,00"),
        AlanTanimi("hizmet_kodu", "Gider Hizmet Kodu", zorunlu=True, ornek="GIDER01"),
        AlanTanimi("hesap_adi", "Ödeme Hesap Adı", zorunlu=True, ornek="Merkez Kasa"),
        AlanTanimi("aciklama", "Açıklama", ornek=""),
    ],
    lambda: GiderFisiImporter(GIDER_FISI_TIPI),
    {
        "belgeno": "belge_no",
        "tarih": "tarih",
        "tutar": "tutar",
        "hizmetkodu": "hizmet_kodu",
        "giderkodu": "hizmet_kodu",
        "hesapadi": "hesap_adi",
        "kasa": "hesap_adi",
        "aciklama": "aciklama",
    },
    ("excel_aktarim", "excel_pdf", "finans_duzenleme"),
    "Gider fişi oluşturur (kasa/banka çıkışı). Mükerrer belge no atlanır.",
)

CEK_SENET_TIPI = _kaydet_tip(
    "cek_senet",
    "Çek / Senet",
    "finans",
    [
        AlanTanimi("evrak_no", "Evrak No", zorunlu=True, ornek="CK-001"),
        AlanTanimi("evrak_turu", "Evrak Türü", ornek="CEK"),
        AlanTanimi("islem_yonu", "İşlem Yönü", ornek="ALINAN"),
        AlanTanimi("cari_kodu", "Cari Kodu", zorunlu=True, ornek="M00001"),
        AlanTanimi("duzenleme_tarihi", "Düzenleme Tarihi", zorunlu=True, ornek="02.11.2026"),
        AlanTanimi("vade_tarihi", "Vade Tarihi", zorunlu=True, ornek="02.12.2026"),
        AlanTanimi("doviz_tutari", "Tutar", zorunlu=True, ornek="1000,00"),
        AlanTanimi("doviz_turu", "Döviz", ornek="TRY"),
    ],
    lambda: CekSenetImporter(CEK_SENET_TIPI),
    {
        "evrakno": "evrak_no",
        "cekno": "evrak_no",
        "evrakturu": "evrak_turu",
        "tur": "evrak_turu",
        "islemyonu": "islem_yonu",
        "yon": "islem_yonu",
        "carikodu": "cari_kodu",
        "duzenlemetarihi": "duzenleme_tarihi",
        "vadetarihi": "vade_tarihi",
        "tutar": "doviz_tutari",
        "doviztutari": "doviz_tutari",
        "doviz": "doviz_turu",
        "dovizturu": "doviz_turu",
    },
    ("excel_aktarim", "excel_pdf", "finans_duzenleme"),
    "Çek/senet portföy kaydı. Mükerrer evrak no atlanır.",
)

KONSINYE_TIPI = _kaydet_tip(
    "konsinye_teslim",
    "Konsinye Teslim",
    "stok",
    [
        AlanTanimi("teslim_grubu", "Teslim Grubu", zorunlu=True, ornek="KON-001"),
        AlanTanimi("yon", "Yön", zorunlu=True, ornek="VERILEN"),
        AlanTanimi("cari_kodu", "Cari Kodu", zorunlu=True, ornek="M00001"),
        AlanTanimi("depo", "Depo", zorunlu=True, ornek="ANA DEPO"),
        AlanTanimi("belge_tarihi", "Belge Tarihi", zorunlu=True, ornek="02.11.2026"),
        AlanTanimi("urun_kodu", "Ürün Kodu / Barkod", zorunlu=True, ornek="0000123400015"),
        AlanTanimi("miktar", "Miktar", zorunlu=True, ornek="1"),
        AlanTanimi("birim", "Birim", ornek="Adet"),
    ],
    lambda: KonsinyeImporter(KONSINYE_TIPI),
    {
        "teslimgrubu": "teslim_grubu",
        "grup": "teslim_grubu",
        "yon": "yon",
        "carikodu": "cari_kodu",
        "depo": "depo",
        "depoadi": "depo",
        "belgetarihi": "belge_tarihi",
        "tarih": "belge_tarihi",
        "urunkodu": "urun_kodu",
        "stokkodu": "urun_kodu",
        "barkod": "urun_kodu",
        "miktar": "miktar",
        "birim": "birim",
    },
    ("excel_aktarim", "excel_pdf", "stok_duzenleme"),
    "Konsinye teslim taslağı (onaylanmaz; stok hareketi oluşmaz).",
)
