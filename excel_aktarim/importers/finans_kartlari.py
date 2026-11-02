"""Finans / personel kart Excel importer'ları — banka, kasa, personel."""

from __future__ import annotations

from typing import Any

from excel_aktarim.importers.base import BaseImporter
from excel_aktarim.mukerrer import mukerrer_mi
from excel_aktarim.normalize import temiz
from excel_aktarim.types import AlanTanimi, ImportTipi, kaydet
from excel_aktarim.validation import SatirSonuc


class _KartImporter(BaseImporter):
    tip: ImportTipi
    mukerrer_tip: str

    def __init__(self, tip: ImportTipi):
        self.tip = tip
        self.mukerrer_tip = tip.kod

    def dogrula_satir(
        self,
        satir_no: int,
        eslenen: dict[str, Any],
        *,
        guncelleme_modu: str = "guncelle",
    ) -> SatirSonuc:
        raise NotImplementedError

    def uygula_satir(self, sonuc: SatirSonuc) -> dict[str, Any]:
        raise NotImplementedError


class PersonelKartImporter(_KartImporter):
    def dogrula_satir(self, satir_no, eslenen, *, guncelleme_modu="guncelle"):
        sonuc = SatirSonuc(satir_no=satir_no, ham=dict(eslenen), eslenen={})
        kod = temiz(eslenen.get("kod") or eslenen.get("personel_kodu"))
        ad = temiz(eslenen.get("ad"))
        soyad = temiz(eslenen.get("soyad"))
        if not kod:
            sonuc.hata_ekle("Personel kodu zorunludur.")
        if not ad or not soyad:
            sonuc.hata_ekle("Ad ve soyad zorunludur.")
        if not sonuc.gecerli:
            return sonuc
        kimlik_no = temiz(eslenen.get("kimlik_no") or eslenen.get("tc_kimlik")) or None
        kimlik_turu = temiz(eslenen.get("kimlik_turu")) or ("DIGER" if not kimlik_no else "TCKN")
        veriler = {
            "kod": kod.upper(),
            "ad": ad,
            "soyad": soyad,
            "kimlik_turu": kimlik_turu,
            "kimlik_no": kimlik_no,
            "calisma_durumu": temiz(eslenen.get("calisma_durumu")) or "AKTIF",
        }
        sonuc.eslenen = veriler
        var, gerekce = mukerrer_mi(self.mukerrer_tip, veriler)
        if var:
            if guncelleme_modu == "atla":
                sonuc.islem = "skip"
                sonuc.mesajlar.append(gerekce or "Mükerrer")
                return sonuc
            if guncelleme_modu == "hata":
                sonuc.hata_ekle(gerekce or "Mükerrer")
                return sonuc
            # guncelle — mevcut id ile güncelleme; basitçe skip (kart güncelleme seçimi UI'da)
            sonuc.islem = "skip"
            sonuc.mesajlar.append((gerekce or "Mükerrer") + " — atlandı")
            return sonuc
        sonuc.islem = "insert"
        sonuc.ozet = f"{veriler['kod']} {veriler['ad']} {veriler['soyad']}"
        return sonuc

    def uygula_satir(self, sonuc):
        if sonuc.islem == "skip":
            return {"hedef_tablo": "personel", "hedef_id": None, "islem": "skip", "onceki": None, "sonraki": sonuc.eslenen}
        from database.personel_service import PersonelService

        kayit = PersonelService.kaydet(sonuc.eslenen or {})
        return {
            "hedef_tablo": "personel",
            "hedef_id": int(kayit.get("id") or 0) or None,
            "islem": "insert",
            "onceki": None,
            "sonraki": kayit,
        }


class BankaKartImporter(_KartImporter):
    def dogrula_satir(self, satir_no, eslenen, *, guncelleme_modu="guncelle"):
        sonuc = SatirSonuc(satir_no=satir_no, ham=dict(eslenen), eslenen={})
        ad = temiz(eslenen.get("banka_adi"))
        if not ad:
            sonuc.hata_ekle("Banka adı zorunludur.")
            return sonuc
        veriler = {"banka_adi": ad, "aciklama": temiz(eslenen.get("aciklama")) or None}
        sonuc.eslenen = veriler
        var, gerekce = mukerrer_mi(self.mukerrer_tip, veriler)
        if var:
            sonuc.islem = "skip"
            sonuc.mesajlar.append(gerekce or "Mükerrer")
            return sonuc
        sonuc.islem = "insert"
        sonuc.ozet = ad
        return sonuc

    def uygula_satir(self, sonuc):
        if sonuc.islem == "skip":
            return {"hedef_tablo": "banka_kartlari", "hedef_id": None, "islem": "skip", "onceki": None, "sonraki": sonuc.eslenen}
        from database.finans_service import FinansService

        kart = FinansService.banka_karti_kaydet(sonuc.eslenen or {})
        return {
            "hedef_tablo": "banka_kartlari",
            "hedef_id": int(kart.id),
            "islem": "insert",
            "onceki": None,
            "sonraki": {"banka_adi": kart.banka_adi},
        }


class KasaHesapImporter(_KartImporter):
    def dogrula_satir(self, satir_no, eslenen, *, guncelleme_modu="guncelle"):
        sonuc = SatirSonuc(satir_no=satir_no, ham=dict(eslenen), eslenen={})
        ad = temiz(eslenen.get("hesap_adi"))
        if not ad:
            sonuc.hata_ekle("Hesap adı zorunludur.")
            return sonuc
        veriler = {
            "hesap_adi": ad,
            "hesap_turu": "KASA",
            "para_birimi": (temiz(eslenen.get("para_birimi")) or "TRY").upper(),
            "acilis_bakiyesi": eslenen.get("acilis_bakiyesi") or 0,
        }
        sonuc.eslenen = veriler
        var, gerekce = mukerrer_mi(self.mukerrer_tip, veriler)
        if var:
            sonuc.islem = "skip"
            sonuc.mesajlar.append(gerekce or "Mükerrer")
            return sonuc
        sonuc.islem = "insert"
        sonuc.ozet = ad
        return sonuc

    def uygula_satir(self, sonuc):
        if sonuc.islem == "skip":
            return {"hedef_tablo": "finans_hesaplari", "hedef_id": None, "islem": "skip", "onceki": None, "sonraki": sonuc.eslenen}
        from database.finans_service import FinansService

        hesap = FinansService.hesap_kaydet(sonuc.eslenen or {})
        return {
            "hedef_tablo": "finans_hesaplari",
            "hedef_id": int(hesap.id),
            "islem": "insert",
            "onceki": None,
            "sonraki": {"hesap_adi": hesap.hesap_adi},
        }


def _reg(kod, ad, modul, alanlar, factory, basliklar, izinler, aciklama):
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


PERSONEL_TIPI = _reg(
    "personel_kart",
    "Personel Kartı",
    "finans",
    [
        AlanTanimi("kod", "Personel Kodu", zorunlu=True, ornek="P001"),
        AlanTanimi("ad", "Ad", zorunlu=True, ornek="Ayşe"),
        AlanTanimi("soyad", "Soyad", zorunlu=True, ornek="Yılmaz"),
        AlanTanimi("kimlik_no", "TC / Kimlik No", ornek=""),
        AlanTanimi("calisma_durumu", "Çalışma Durumu", ornek="AKTIF"),
    ],
    lambda: PersonelKartImporter(PERSONEL_TIPI),
    {
        "personelkodu": "kod",
        "kod": "kod",
        "ad": "ad",
        "soyad": "soyad",
        "tckimlik": "kimlik_no",
        "tc": "kimlik_no",
        "kimlikno": "kimlik_no",
        "calismadurumu": "calisma_durumu",
        "durum": "calisma_durumu",
    },
    ("excel_aktarim", "excel_pdf", "personel_duzenleme", "finans_duzenleme"),
    "Personel kartı ekler; mükerrer kod atlanır.",
)

BANKA_TIPI = _reg(
    "banka_kart",
    "Banka Ana Kartı",
    "finans",
    [
        AlanTanimi("banka_adi", "Banka Adı", zorunlu=True, ornek="Örnek Bankası"),
        AlanTanimi("aciklama", "Açıklama", ornek=""),
    ],
    lambda: BankaKartImporter(BANKA_TIPI),
    {"bankaadi": "banka_adi", "banka": "banka_adi", "aciklama": "aciklama"},
    ("excel_aktarim", "excel_pdf", "finans_duzenleme"),
    "Banka ana kartı ekler; aynı ad mükerrer atlanır.",
)

KASA_TIPI = _reg(
    "kasa_hesap",
    "Kasa Hesabı",
    "finans",
    [
        AlanTanimi("hesap_adi", "Hesap Adı", zorunlu=True, ornek="Merkez Kasa"),
        AlanTanimi("para_birimi", "Para Birimi", ornek="TRY"),
        AlanTanimi("acilis_bakiyesi", "Açılış Bakiyesi", ornek="0"),
    ],
    lambda: KasaHesapImporter(KASA_TIPI),
    {
        "hesapadi": "hesap_adi",
        "kasa": "hesap_adi",
        "paribirimi": "para_birimi",
        "acilisbakiyesi": "acilis_bakiyesi",
        "acilis": "acilis_bakiyesi",
    },
    ("excel_aktarim", "excel_pdf", "finans_duzenleme"),
    "Kasa hesabı ekler; aynı ad mükerrer atlanır.",
)


class PosHesapImporter(_KartImporter):
    """POS hesabı — banka ana kartına bağlı alt hesap adı ile; yoksa banka kartı üzerinden oluşur.

    Bağımsız POS satırı: banka_adi + hesap_adi; banka yoksa önce banka kartı oluşturulur
    (POS alt hesabı banka_karti_kaydet ile gelir).
    """

    def dogrula_satir(self, satir_no, eslenen, *, guncelleme_modu="guncelle"):
        sonuc = SatirSonuc(satir_no=satir_no, ham=dict(eslenen), eslenen={})
        banka = temiz(eslenen.get("banka_adi"))
        ad = temiz(eslenen.get("hesap_adi"))
        if not banka:
            sonuc.hata_ekle("Banka adı zorunludur.")
        if not ad:
            # Varsayılan: Banka — POS Hesabı
            ad = f"{banka} — POS Hesabı" if banka else ""
        if not ad:
            sonuc.hata_ekle("POS hesap adı zorunludur.")
        if not sonuc.gecerli:
            return sonuc
        veriler = {
            "banka_adi": banka,
            "hesap_adi": ad,
            "para_birimi": (temiz(eslenen.get("para_birimi")) or "TRY").upper(),
        }
        sonuc.eslenen = veriler
        var, gerekce = mukerrer_mi(self.mukerrer_tip, veriler)
        if var:
            sonuc.islem = "skip"
            sonuc.mesajlar.append(gerekce or "Mükerrer")
            return sonuc
        # Banka kartı yoksa da insert (uygula bankayı oluşturur)
        sonuc.islem = "insert"
        sonuc.ozet = ad
        return sonuc

    def uygula_satir(self, sonuc):
        if sonuc.islem == "skip":
            return {
                "hedef_tablo": "finans_hesaplari",
                "hedef_id": None,
                "islem": "skip",
                "onceki": None,
                "sonraki": sonuc.eslenen,
            }
        from database.database import get_session
        from database.finans_service import FinansService
        from database.models.finans import BankaKarti, FinansHesabi
        from sqlalchemy import select

        banka_adi = (sonuc.eslenen or {}).get("banka_adi")
        hesap_adi = (sonuc.eslenen or {}).get("hesap_adi")
        with get_session() as session:
            kart = session.scalar(select(BankaKarti).where(BankaKarti.banka_adi == banka_adi))
        if kart is None:
            kart = FinansService.banka_karti_kaydet({"banka_adi": banka_adi})
        # banka_karti_kaydet POS alt hesabını oluşturur; adı kontrol et
        with get_session() as session:
            pos = session.scalar(
                select(FinansHesabi).where(
                    FinansHesabi.banka_karti_id == int(kart.id),
                    FinansHesabi.alt_hesap_turu == "POS",
                )
            )
            if pos is None:
                raise ValueError("POS alt hesabı oluşturulamadı.")
            # Kullanıcı özel ad verdiyse ve boşsa güncelle
            if hesap_adi and pos.hesap_adi != hesap_adi:
                cakisma = session.scalar(
                    select(FinansHesabi.id).where(
                        FinansHesabi.hesap_adi == hesap_adi,
                        FinansHesabi.id != pos.id,
                    )
                )
                if not cakisma:
                    pos.hesap_adi = hesap_adi
                    session.flush()
            hid = int(pos.id)
            had = pos.hesap_adi
        return {
            "hedef_tablo": "finans_hesaplari",
            "hedef_id": hid,
            "islem": "insert",
            "onceki": None,
            "sonraki": {"hesap_adi": had, "banka_adi": banka_adi, "alt_hesap_turu": "POS"},
        }


POS_TIPI = _reg(
    "pos_hesap",
    "POS Hesabı",
    "finans",
    [
        AlanTanimi("banka_adi", "Banka Adı", zorunlu=True, ornek="Örnek Bankası"),
        AlanTanimi("hesap_adi", "POS Hesap Adı", ornek="Örnek Bankası — POS Hesabı"),
        AlanTanimi("para_birimi", "Para Birimi", ornek="TRY"),
    ],
    lambda: PosHesapImporter(POS_TIPI),
    {
        "bankaadi": "banka_adi",
        "banka": "banka_adi",
        "hesapadi": "hesap_adi",
        "pos": "hesap_adi",
        "paribirimi": "para_birimi",
    },
    ("excel_aktarim", "excel_pdf", "finans_duzenleme"),
    "POS alt hesabı; banka kartı yoksa oluşturur. Aynı hesap adı mükerrer atlanır.",
)
