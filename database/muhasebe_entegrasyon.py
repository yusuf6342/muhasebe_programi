"""Operasyon belgelerinden muhasebe fişi üretimi (tek fiş üretim noktası).

Hesap kodları sabit yazılmaz; firma bazlı MuhasebeHesapEsleme kullanılır.
Fiş üreticileri ``session`` alır: evrak servisi kendi transaction'ını verirse fiş, ön muhasebe
hareketleriyle birlikte commit/rollback olur. Ne zaman fiş üretileceğine (otomatik / sonradan /
genel muhasebe kapalı) ``muhasebe_hook`` üzerinden ``MuhasebelestirmeService`` karar verir.
Aynı kaynak için ikinci fiş ``uq_mh_kaynak`` (firma, kaynak_turu, kaynak_id) ile engellenir.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Callable

from sqlalchemy import select

from database.database import get_session
from database.models.genel_muhasebe import (
    ESLEME_ANAHTARLARI,
    HesapPlani,
    MuhasebeFisi,
    MuhasebeHesapEsleme,
)
from database.muhasebe_service import (
    HesapPlanService,
    MuhasebeFisService,
    MuhasebeService,
    decimal,
    oturum_kullan,
)
from database.tdhp_hesap_plani import fis_icin_alt_hesap_mi

SIFIR = Decimal("0.00")

# Fiş kaynak türleri (çift kayıt engeli için)
KAYNAK_SATIS_FATURA = "satis_faturasi"
KAYNAK_SATIS_TAHSILAT = "satis_fatura_tahsilat"
KAYNAK_ALIS_FATURA = "alis_faturasi"
KAYNAK_ALIS_ODEME = "alis_fatura_odeme"
KAYNAK_SATIS_IADE = "satis_iade"
KAYNAK_ALIS_IADE = "alis_iade"
KAYNAK_ALIS_IADE_TAHSILAT = "alis_iade_tahsilat"
KAYNAK_HIZMET_FATURA = "hizmet_faturasi"
KAYNAK_GIDER_FISI = "gider_fisi"
# Cari tahsilat/ödeme fişi kalıcı evrak kimliğine (finans_evrak_kimlikleri.id) bağlanır. Eski
# sürümlerin "cari_tahsilat"/"cari_odeme" kaynaklı fişleri cari hareket id'sine bağlıydı.
KAYNAK_CARI_TAHSILAT = "cari_tahsilat_evrak"
KAYNAK_CARI_ODEME = "cari_odeme_evrak"
ESKI_KAYNAK_CARI_TAHSILAT = "cari_tahsilat"
ESKI_KAYNAK_CARI_ODEME = "cari_odeme"
KAYNAK_KASA_MAKBUZU = "kasa_makbuzu"
KAYNAK_KASA_BANKA_VIRMAN = "kasa_banka_virman"
KAYNAK_BANKA_HAVALE = "banka_havale"
KAYNAK_CARI_VIRMAN = "cari_virman"
KAYNAK_CARI_VIRMAN_MAKBUZU = "cari_virman_makbuzu"
KAYNAK_POS_TAHSILAT = "pos_tahsilat"
KAYNAK_KART_ODEME = "kart_odeme"
KAYNAK_POS_VALOR = "pos_valor_aktarimi"
KAYNAK_CEK_SENET = "cek_senet_hareketi"
KAYNAK_KREDI_KULLANDIRIM = "banka_kredi_kullandirim"
KAYNAK_KREDI_ODEME = "banka_kredi_odeme"
KAYNAK_KUR_FARKI = "kur_farki"

# Evrak türleri: muhasebeleştirme ayarı ve belge durumu bu anahtarlarla tutulur.
# "kesinlesme": evrakın muhasebe etkisinin doğduğu gerçek işlem (programın bugünkü işleyişi).
EVRAKLAR: dict[str, dict] = {
    "satis_faturasi": {
        "ad": "Satış faturası (hızlı satış dahil)",
        "fn": "satis_faturasi_fisi",
        "kaynaklar": (KAYNAK_SATIS_FATURA, KAYNAK_SATIS_TAHSILAT),
        "kesinlesme": "Onayla (Kaydet yalnız taslak oluşturur)",
    },
    "satis_iade": {
        "ad": "Satış iade faturası",
        "fn": "satis_iade_fisi",
        "kaynaklar": (KAYNAK_SATIS_IADE,),
        "kesinlesme": "Kaydet (cari ve stok hareketi kayıtta oluşur)",
    },
    "alis_faturasi": {
        "ad": "Alış faturası",
        "fn": "alis_faturasi_fisi",
        "kaynaklar": (KAYNAK_ALIS_FATURA, KAYNAK_ALIS_ODEME),
        "kesinlesme": "Kaydet (stok/cari kayıtta oluşur; Onayla yalnız kilitler)",
    },
    "alis_iade": {
        "ad": "Alış iade faturası",
        "fn": "alis_iade_fisi",
        "kaynaklar": (KAYNAK_ALIS_IADE, KAYNAK_ALIS_IADE_TAHSILAT),
        "kesinlesme": "Onayla (Kaydet yalnız taslak oluşturur; iade bedeli tahsilatı ayrı tahsil fişi)",
    },
    "hizmet_faturasi": {
        "ad": "Hizmet faturası (gelir/gider)",
        "fn": "hizmet_faturasi_fisi",
        "kaynaklar": (KAYNAK_HIZMET_FATURA,),
        "kesinlesme": "Kaydet",
    },
    "gider_fisi": {
        "ad": "Gider fişi (kasa/banka)",
        "fn": "gider_fisi_fisi",
        "kaynaklar": (KAYNAK_GIDER_FISI,),
        "kesinlesme": "Kaydet",
    },
    "cari_tahsilat": {
        "ad": "Cari tahsilat (cari kartındaki Tahsilat)",
        "fn": "cari_tahsilat_fisi",
        "kaynaklar": (KAYNAK_CARI_TAHSILAT,),
        "kesinlesme": "Kaydet (iptal: ters kayıt)",
    },
    "cari_odeme": {
        "ad": "Cari ödeme (cari kartındaki Ödeme)",
        "fn": "cari_odeme_fisi",
        "kaynaklar": (KAYNAK_CARI_ODEME,),
        "kesinlesme": "Kaydet (iptal: ters kayıt)",
    },
    "kasa_makbuzu": {
        "ad": "Kasa tahsilat / ödeme makbuzu (nakit ve havale satırları)",
        "fn": "kasa_makbuzu_fisi",
        "kaynaklar": (KAYNAK_KASA_MAKBUZU,),
        "kesinlesme": "Kaydet (düzenleme: yeniden; iptal: ters kayıt). POS / şirket kartı satırları "
                      "Finans İşlem Ayarları'ndaki hesaplarla",
    },
    "kasa_banka_virman": {
        "ad": "Kasa / banka virmanı (kasadan bankaya, bankadan kasaya, bankalar arası)",
        "fn": "kasa_banka_virman_fisi",
        "kaynaklar": (KAYNAK_KASA_BANKA_VIRMAN,),
        "kesinlesme": "Kaydet (düzenleme: yeniden). Yalnız kasa ve mevduat hesapları",
    },
    "banka_havale": {
        "ad": "Alınan / gönderilen havale (cari)",
        "fn": "banka_havale_fisi",
        "kaynaklar": (KAYNAK_BANKA_HAVALE,),
        "kesinlesme": "Kaydet (düzenleme: yeniden). Yalnız mevduat hesapları",
    },
    "cari_virman": {
        "ad": "Cari virman (cariden cariye)",
        "fn": "cari_virman_fisi",
        "kaynaklar": (KAYNAK_CARI_VIRMAN,),
        "kesinlesme": "Kaydet (iptal: ters kayıt)",
    },
    "cari_virman_makbuzu": {
        "ad": "Cari virman makbuzu (müşteri tahsilatı + tedarikçi ödemesi tek fiş)",
        "fn": "cari_virman_makbuzu_fisi",
        "kaynaklar": (KAYNAK_CARI_VIRMAN_MAKBUZU,),
        "kesinlesme": "Kaydet (düzenleme: yeniden; iptal: ters kayıt)",
    },
    "pos_tahsilat": {
        "ad": "POS tahsilatı (makbuzsuz kart tahsilatı)",
        "fn": "pos_tahsilat_fisi",
        "kaynaklar": (KAYNAK_POS_TAHSILAT,),
        "kesinlesme": "Kaydet (düzenleme: eski fiş ters kayıt). Valör alacağı + komisyon gideri / cari",
    },
    "kart_odeme": {
        "ad": "Şirket kredi kartıyla cari ödemesi (makbuzsuz)",
        "fn": "kart_odeme_fisi",
        "kaynaklar": (KAYNAK_KART_ODEME,),
        "kesinlesme": "Kaydet (düzenleme: eski fiş ters kayıt). Cari / şirket kartı borcu",
    },
    "pos_valor_aktarimi": {
        "ad": "POS valör aktarımı (POS → KMH)",
        "fn": "pos_valor_aktarimi_fisi",
        "kaynaklar": (KAYNAK_POS_VALOR,),
        "kesinlesme": "Valör aktarımı. KMH / POS valör alacağı",
    },
    "cek_senet": {
        "ad": "Çek / senet işlemi (aşama bazlı)",
        "fn": "cek_senet_fisi",
        "kaynaklar": (KAYNAK_CEK_SENET,),
        "kesinlesme": "Her aşama ayrı evrak (kayıt, bankaya verme, ciro, tahsil/ödeme, karşılıksız, iade); "
                      "fiş üretecek aşamalar Finans İşlem Ayarları'nda seçilir (iptal: ters kayıt)",
    },
    "banka_kredi_kullandirim": {
        "ad": "Banka kredisi kullandırımı",
        "fn": "banka_kredi_kullandirim_fisi",
        "kaynaklar": (KAYNAK_KREDI_KULLANDIRIM,),
        "kesinlesme": "Kullandır. Fiş yazılıp yazılmayacağı ve kısa/uzun vade ayrımı Finans İşlem Ayarları'nda",
    },
    "banka_kredi_odeme": {
        "ad": "Banka kredisi taksit / ara ödeme / erken kapama",
        "fn": "banka_kredi_odeme_fisi",
        "kaynaklar": (KAYNAK_KREDI_ODEME,),
        "kesinlesme": "Öde (iptal: ters kayıt). Anapara kredi hesabına, faiz/masraf gider hesaplarına",
    },
    "kur_farki": {
        "ad": "Kur farkı (dövizli borç/alacak kapatması)",
        "fn": "kur_farki_fisi",
        "kaynaklar": (KAYNAK_KUR_FARKI,),
        "kesinlesme": "Döviz sabit belgenin tahsilatı/ödemesi (kaynak kur ↔ ödeme kuru). Gelir: cari / kur farkı "
                      "geliri; gider: kur farkı gideri / cari (iptal: ters kayıt)",
    },
}

# Muhasebe etkisi olan ama fiş üreticisi bulunmayan evraklar (ayar ekranında "desteklenmiyor").
DESTEKLENMEYEN_EVRAKLAR: tuple[tuple[str, str], ...] = (
    ("Krediler alt hesabı ve türü belirsiz kart hesabı ('KREDİ KARTI' türlü, alt türü boş) tarafı olan "
     "virman / havale / makbuz",
     "Muhasebe karşılığı tanımlı değil: evrak kaydedilir, 'İnceleme gerekiyor' olarak bekler. Kredi "
     "hareketleri banka kredisi evraklarından muhasebeleşir."),
    ("Şirket kartı ekstre / taksit ödemesi (kart borcunun bankadan ödenmesi)",
     "Fiş üreticisi yok: kart borcu (şirket kartı borcu hesabı) bu ödemelerle kapanmaz; elle fiş gerekir."),
    ("Uzun vadeli kredinin kısa vadeye aktarılması (400 → 300 sınıflandırma virmanı)",
     "Otomatik yapılmaz; '12 ay' ayrımında her taksit ödemesi kullandırımdaki sınıfından (kısa/uzun) düşülür. "
     "Ödeme planı sonradan değişirse kullandırım fişi yeniden sınıflandırılmaz."),
    ("Masraf dağıtımı", "Onayda her zaman fiş yazar (maliyet aktarımının kendisi); ayar uygulanmaz."),
)

KAYNAK_EVRAK: dict[str, str] = {
    kaynak: evrak for evrak, t in EVRAKLAR.items() for kaynak in t["kaynaklar"]
}

# Önerilen alt hesaplar (eşleştirme kolaylığı)
ONERI_HESAPLAR = (
    ("100", "Kasa", "Aktif", "kasa"),
    ("102", "Bankalar", "Aktif", "banka"),
    ("120", "Alıcılar", "Aktif", "musteriler"),
    ("153", "Ticari Mallar", "Aktif", "ticari_mallar"),
    ("191", "İndirilecek KDV", "Aktif", "indirilecek_kdv"),
    ("300", "Banka Kredileri", "Pasif", "kredi_kisa_vadeli"),
    ("320", "Satıcılar", "Pasif", "tedarikciler"),
    ("391", "Hesaplanan KDV", "Pasif", "hesaplanan_kdv"),
    ("400", "Banka Kredileri", "Pasif", "kredi_uzun_vadeli"),
    ("600", "Yurtiçi Satışlar", "Gelir", "yurtici_satislar"),
    ("621", "Satılan Ticari Mallar Maliyeti", "Gider", "satilan_mal_maliyeti"),
    ("646", "Kambiyo Karları", "Gelir", "kur_farki_geliri"),
    ("656", "Kambiyo Zararları", "Gider", "kur_farki_gideri"),
    ("660", "Kısa Vadeli Borçlanma Giderleri", "Gider", "kredi_faiz_gideri"),
    ("770", "Genel Yönetim Giderleri", "Gider", "giderler"),
    ("780", "Finansman Giderleri", "Gider", "kredi_diger_finansman"),
)

ESLEME_YERI = "Genel Muhasebe → Hesap Eşleştirmeleri"
KART_HESAP_YERI = ("Finans → Banka kartı → Muhasebe Hesapları (kasa için Kasa kartı → Muhasebe Hesabı) "
                   "veya Ayarlar → Muhasebeleştirme Ayarları → Finans İşlem Ayarları → Kasa / Banka Kartları")
ONERI_ANA_KODLARI: dict[str, str] = {anahtar: kod for kod, _ad, _tur, anahtar in ONERI_HESAPLAR}

# Kasa/banka kartının alt türü → hesap eşleştirmesi (Finans İşlem Ayarları'nda kullanıcı bağlar)
FINANS_ALT_ANAHTARI = {"KMH": "kmh_hesabi", "POS": "pos_valor_alacagi", "KREDI_KARTI": "sirket_kart_borcu"}
KREDI_GIDER_ANAHTARLARI = {
    "faiz": "kredi_faiz_gideri", "bsmv": "kredi_bsmv_gideri", "kkdf": "kredi_kkdf_gideri",
    "komisyon": "kredi_komisyon_gideri", "sigorta": "kredi_sigorta_gideri",
    "dosya_masrafi": "kredi_dosya_masrafi", "diger_masraflar": "kredi_diger_finansman",
    "gecikme_faizi": "kredi_gecikme_faizi",
}


class AyarEksik(ValueError):
    """Finans işlem ayarı / hesabı tanımsız: evrak kaydedilir, 'İnceleme gerekiyor' kalır."""


class MuhasebeDisiAyar(Exception):
    """Ayar gereği bu işlem fiş üretmez (ör. çek/senet aşaması 'fiş üretmesin')."""


def _alt_hesabi_var_mi(session, h: HesapPlani) -> bool:
    return session.scalar(
        select(HesapPlani.id).where(
            HesapPlani.firma_id == h.firma_id,
            HesapPlani.id != h.id,
            (HesapPlani.ust_hesap_id == h.id) | HesapPlani.hesap_kodu.like(f"{h.hesap_kodu}.%"),
        ).limit(1)
    ) is not None


def hesap_uygunluk_sorunu(session, h: HesapPlani | None, firma_id: int) -> str | None:
    """Hesap fiş satırı kabul eder mi: aynı firma, aktif, alt hesap biçimi ve altında hesap yok.

    Hesap planında ayrı bir "kayıt kabul eder" alanı yok; kayıt kabul eden hesap, 120.01.0001
    biçimindeki ve altında başka hesap bulunmayan (yaprak) alt hesaptır.
    """
    if h is None or h.firma_id != firma_id:
        return "hesap bu firmada yok"
    if not h.aktif:
        return f"{h.hesap_kodu} pasif"
    if not fis_icin_alt_hesap_mi(h.hesap_kodu):
        return f"{h.hesap_kodu} ana/üst hesap (fiş yalnız 120.01.0001 biçimindeki alt hesaba yazılır)"
    if _alt_hesabi_var_mi(session, h):
        return f"{h.hesap_kodu} altında başka hesap var (kayıt kabul etmez)"
    if h.ust_hesap_id:
        ust = session.get(HesapPlani, h.ust_hesap_id)
        if ust is not None and not h.hesap_kodu.startswith(f"{ust.hesap_kodu}."):
            return f"{h.hesap_kodu} üst hesabı ({ust.hesap_kodu}) ile kod uyumsuz"
    return None


def uygun_alt_hesaplar(session, firma_id: int, ana_kod: str) -> list[HesapPlani]:
    """Ana hesabın altında fiş kaydı kabul eden (aktif, yaprak) alt hesaplar."""
    adaylar = session.scalars(
        select(HesapPlani).where(
            HesapPlani.firma_id == firma_id,
            HesapPlani.aktif.is_(True),
            HesapPlani.hesap_kodu.like(f"{ana_kod}.%"),
        ).order_by(HesapPlani.hesap_kodu)
    ).all()
    return [h for h in adaylar if hesap_uygunluk_sorunu(session, h, firma_id) is None]


class HesapEslemeService:
    @staticmethod
    def uygunluk_raporu(*, session=None) -> list[dict]:
        """Her eşleştirme için durum: uygun / uygunsuz / eksik, neden ve uygun aday alt hesaplar."""
        with oturum_kullan(session) as session:
            firma_id = MuhasebeService.yerel_firma_id(session)
            sonuc = []
            for e in session.scalars(
                select(MuhasebeHesapEsleme)
                .where(MuhasebeHesapEsleme.firma_id == firma_id)
                .order_by(MuhasebeHesapEsleme.anahtar)
            ).all():
                h = session.get(HesapPlani, e.hesap_id) if e.hesap_id else None
                ana = ONERI_ANA_KODLARI.get(e.anahtar)
                if h is None and e.hesap_id is None:
                    durum, neden = "eksik", "hesap bağlı değil"
                else:
                    neden = hesap_uygunluk_sorunu(session, h, firma_id)
                    durum = "uygunsuz" if neden else "uygun"
                    if not ana and h is not None:
                        ana = h.hesap_kodu.split(".")[0]
                adaylar = (
                    [x.hesap_kodu for x in uygun_alt_hesaplar(session, firma_id, ana)]
                    if ana and durum != "uygun" else []
                )
                sonuc.append({
                    "anahtar": e.anahtar, "aciklama": e.aciklama, "durum": durum, "neden": neden,
                    "hesap_kodu": h.hesap_kodu if h else None, "hesap_adi": h.hesap_adi if h else None,
                    "ana_kod": ana, "adaylar": adaylar,
                })
            return sonuc

    @staticmethod
    def listele() -> list[dict]:
        MuhasebeService.esleme_sablonlarini_doldur()
        with get_session() as session:
            firma_id = MuhasebeService.yerel_firma_id(session)
            rows = session.scalars(
                select(MuhasebeHesapEsleme)
                .where(MuhasebeHesapEsleme.firma_id == firma_id)
                .order_by(MuhasebeHesapEsleme.anahtar)
            ).all()
            sonuc = []
            for e in rows:
                kod = ad = None
                if e.hesap_id:
                    h = session.get(HesapPlani, e.hesap_id)
                    if h:
                        kod, ad = h.hesap_kodu, h.hesap_adi
                sonuc.append(
                    {
                        "id": e.id,
                        "anahtar": e.anahtar,
                        "aciklama": e.aciklama,
                        "hesap_id": e.hesap_id,
                        "hesap_kodu": kod,
                        "hesap_adi": ad,
                        "aktif": e.aktif,
                    }
                )
            return sonuc

    @staticmethod
    def kaydet(anahtar: str, hesap_id: int | None) -> None:
        from database.access import yazma_zorunlu

        yazma_zorunlu("muhasebe_fis_duzenleme", "duzenleme")
        with get_session() as session:
            firma_id = MuhasebeService.yerel_firma_id(session)
            e = session.scalar(
                select(MuhasebeHesapEsleme).where(
                    MuhasebeHesapEsleme.firma_id == firma_id,
                    MuhasebeHesapEsleme.anahtar == anahtar,
                )
            )
            if e is None:
                raise ValueError(f"Eşleştirme anahtarı yok: {anahtar}")
            onceki = session.get(HesapPlani, e.hesap_id) if e.hesap_id else None
            yeni = None
            if hesap_id:
                h = session.get(HesapPlani, int(hesap_id))
                if h is None or h.firma_id != firma_id:
                    raise ValueError("Hesap bulunamadı.")
                sorun = hesap_uygunluk_sorunu(session, h, firma_id)
                if sorun:
                    raise ValueError(f"Bu hesap eşleştirilemez: {sorun}.")
                e.hesap_id = h.id
                yeni = h
            else:
                e.hesap_id = None
            if (onceki.id if onceki else None) != (yeni.id if yeni else None):
                MuhasebeService._gecmis(
                    session, kayit_turu="esleme", kayit_id=int(e.id), islem="bagla" if yeni else "kaldir",
                    detay=f"{anahtar}: {onceki.hesap_kodu if onceki else '-'} → {yeni.hesap_kodu if yeni else '-'}")

    @staticmethod
    def oneri_hesaplari_olustur() -> dict:
        """TDHP ana hesaplarını yükler; boş eşleştirmeleri yalnız tek uygun alt hesap varsa bağlar.

        Ana/üst hesap bağlanmaz. Birden çok uygun alt hesap varsa seçim kullanıcıya bırakılır,
        uygun hesap yoksa eksik olarak raporlanır. Mevcut eşleştirmeler değiştirilmez (uygun
        değilse raporlanır).
        """
        from database.access import yazma_zorunlu

        yazma_zorunlu("muhasebe_fis_olusturma", "yeni_kayit", "duzenleme")
        eklenen = MuhasebeService.ana_hesaplari_doldur()
        MuhasebeService.esleme_sablonlarini_doldur()
        rapor = {"eklenen_ana_hesap": eklenen, "baglanan": [], "secim_gerekli": [], "eksik": [],
                 "uygunsuz_mevcut": [], "korunan": []}
        with get_session() as session:
            firma_id = MuhasebeService.yerel_firma_id(session)
            for kod, _ad, _tur, anahtar in ONERI_HESAPLAR:
                e = session.scalar(
                    select(MuhasebeHesapEsleme).where(
                        MuhasebeHesapEsleme.firma_id == firma_id,
                        MuhasebeHesapEsleme.anahtar == anahtar,
                    )
                )
                if e is None:
                    continue
                adaylar = uygun_alt_hesaplar(session, firma_id, kod)
                if e.hesap_id is not None:
                    h = session.get(HesapPlani, e.hesap_id)
                    sorun = hesap_uygunluk_sorunu(session, h, firma_id)
                    if sorun:
                        rapor["uygunsuz_mevcut"].append(
                            (anahtar, h.hesap_kodu if h else "?", sorun, [a.hesap_kodu for a in adaylar]))
                    else:
                        rapor["korunan"].append((anahtar, h.hesap_kodu))
                    continue
                if len(adaylar) == 1:
                    e.hesap_id = adaylar[0].id
                    rapor["baglanan"].append((anahtar, adaylar[0].hesap_kodu))
                elif adaylar:
                    rapor["secim_gerekli"].append((anahtar, [a.hesap_kodu for a in adaylar]))
                else:
                    rapor["eksik"].append((anahtar, kod))
        return rapor

    @staticmethod
    def oneri_raporu_metni(rapor: dict) -> str:
        satirlar = [f"Yeni eklenen ana hesap: {rapor['eklenen_ana_hesap']}"]
        if rapor["baglanan"]:
            satirlar.append("\nBağlanan (tek uygun alt hesap):")
            satirlar += [f"  {a} → {k}" for a, k in rapor["baglanan"]]
        if rapor["secim_gerekli"]:
            satirlar.append("\nSeçim gerekli (birden çok uygun alt hesap; otomatik seçilmedi):")
            satirlar += [f"  {a}: {', '.join(k)}" for a, k in rapor["secim_gerekli"]]
        if rapor["eksik"]:
            satirlar.append("\nEksik (uygun alt hesap yok; önce Hesap Planı'nda alt hesap açın):")
            satirlar += [f"  {a}: {k} altında kayıt kabul eden hesap yok" for a, k in rapor["eksik"]]
        if rapor["uygunsuz_mevcut"]:
            satirlar.append("\nMevcut eşleştirme uygun değil (değiştirilmedi; Hesap Bağla ile düzeltin):")
            for a, k, sorun, adaylar in rapor["uygunsuz_mevcut"]:
                oneri = f" — uygun: {', '.join(adaylar)}" if adaylar else " — uygun alt hesap yok"
                satirlar.append(f"  {a} → {k}: {sorun}{oneri}")
        return "\n".join(satirlar)


class MuhasebeEntegrasyonService:
    @staticmethod
    def _guvenli(fn: Callable, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as hata:
            print(f"[Muhasebe entegrasyon] {fn.__name__}: {hata}")
            return None

    @staticmethod
    def mevcut_fis_id(kaynak_turu: str, kaynak_id: int, *, session=None) -> int | None:
        with oturum_kullan(session) as session:
            firma_id = MuhasebeService.yerel_firma_id(session)
            fis = session.scalar(
                select(MuhasebeFisi).where(
                    MuhasebeFisi.firma_id == firma_id,
                    MuhasebeFisi.kaynak_turu == kaynak_turu,
                    MuhasebeFisi.kaynak_id == int(kaynak_id),
                    MuhasebeFisi.durum != "İptal",
                )
            )
            return fis.id if fis else None

    @staticmethod
    def evrak_fis_idleri(evrak_turu: str, kaynak_id: int, *, session=None) -> list[int]:
        """Evrakın etkin (iptal edilmemiş) fişleri: ana fiş + tahsilat/ödeme fişi."""
        sonuc = []
        for kaynak in EVRAKLAR[evrak_turu]["kaynaklar"]:
            fid = MuhasebeEntegrasyonService.mevcut_fis_id(kaynak, kaynak_id, session=session)
            if fid:
                sonuc.append(int(fid))
        return sonuc

    @staticmethod
    def iptal_kaynak(
        kaynak_turu: str, kaynak_id: int, neden: str = "", *, session=None
    ) -> int | None:
        """Kaynağın etkin fişini ters kayıtla bir kez iptal eder; etkin fiş yoksa etkisizdir."""
        with oturum_kullan(session) as session:
            fis_id = MuhasebeEntegrasyonService.mevcut_fis_id(
                kaynak_turu, kaynak_id, session=session
            )
            if not fis_id:
                return None
            return MuhasebeFisService.iptal(
                fis_id, neden or f"Kaynak iptal: {kaynak_turu}", otomatik=True, session=session
            )

    @staticmethod
    def _hesap(anahtar: str, *, session=None) -> dict:
        with oturum_kullan(session) as session:
            firma_id = MuhasebeService.yerel_firma_id(session)
            ad = dict(ESLEME_ANAHTARLARI).get(anahtar, anahtar)
            e = session.scalar(
                select(MuhasebeHesapEsleme).where(
                    MuhasebeHesapEsleme.firma_id == firma_id,
                    MuhasebeHesapEsleme.anahtar == anahtar,
                    MuhasebeHesapEsleme.aktif.is_(True),
                )
            )
            if e is None or not e.hesap_id:
                raise ValueError(f"Hesap eşleştirmesi eksik: {ad} ({anahtar}) — {ESLEME_YERI}")
            h = session.get(HesapPlani, e.hesap_id)
            if h is None or not h.aktif or h.firma_id != firma_id:
                raise ValueError(f"Eşleştirilen hesap pasif/yok: {ad} ({anahtar}) — {ESLEME_YERI}")
            if not fis_icin_alt_hesap_mi(h.hesap_kodu):
                raise ValueError(
                    f"Hesap eşleştirmesi ana hesaba bağlı: {ad} ({anahtar}) → {h.hesap_kodu}. "
                    f"Fiş yalnız alt hesaba yazılır (ör. {h.hesap_kodu}.01.0001) — {ESLEME_YERI}"
                )
            sorun = hesap_uygunluk_sorunu(session, h, firma_id)
            if sorun:
                raise ValueError(f"Hesap eşleştirmesi uygun değil: {ad} ({anahtar}) → {sorun} — {ESLEME_YERI}")
            return {"id": h.id, "kod": h.hesap_kodu, "ad": h.hesap_adi}

    @staticmethod
    def esleme_sorunu(anahtar: str, *, session=None) -> str | None:
        try:
            MuhasebeEntegrasyonService._hesap(anahtar, session=session)
        except ValueError as hata:
            return str(hata)
        return None

    @staticmethod
    def _kasa_veya_banka(odeme_sekli: str | None, hesap_adi: str | None, *, session=None) -> dict:
        """Fatura tahsilat/ödeme hesabı: kasa/banka kartı adı biliniyorsa kartın muhasebe karşılığı."""
        H = MuhasebeEntegrasyonService
        fh = H._finans_hesabi_adla(hesap_adi, session=session)
        if fh is not None:
            with oturum_kullan(session) as s:
                return H._finans_karsiligi_ayarli(fh, s)
        metin = f"{odeme_sekli or ''} {hesap_adi or ''}".casefold()
        if any(x in metin for x in ("banka", "havale", "eft", "pos", "kredi kart")):
            return MuhasebeEntegrasyonService._hesap("banka", session=session)
        return MuhasebeEntegrasyonService._hesap("kasa", session=session)

    @staticmethod
    def _satir(hesap: dict, *, borc=SIFIR, alacak=SIFIR, aciklama: str = "") -> dict:
        return {
            "hesap_id": hesap["id"],
            "borc": decimal(borc),
            "alacak": decimal(alacak),
            "aciklama": aciklama,
        }

    @staticmethod
    def _olustur(
        *,
        kaynak_turu: str,
        kaynak_id: int,
        fis_tarihi: date,
        fis_turu: str,
        aciklama: str,
        belge_no: str | None,
        satirlar: list[dict],
        yeniden: bool = False,
        session=None,
    ) -> int | None:
        with oturum_kullan(session) as session:
            mevcut = MuhasebeEntegrasyonService.mevcut_fis_id(kaynak_turu, kaynak_id, session=session)
            if mevcut and not yeniden:
                return mevcut
            if mevcut and yeniden:
                MuhasebeFisService.iptal(
                    mevcut, "Kaynak belge güncellendi", otomatik=True, session=session
                )
                session.flush()
            temiz = [s for s in satirlar if decimal(s.get("borc")) or decimal(s.get("alacak"))]
            if not temiz:
                return None
            return MuhasebeFisService.kaydet(
                {
                    "fis_tarihi": fis_tarihi,
                    "fis_turu": fis_turu,
                    "aciklama": aciklama,
                    "belge_no": belge_no,
                    "durum": "Kesinleşmiş",
                    "kaynak_turu": kaynak_turu,
                    "kaynak_id": int(kaynak_id),
                    "satirlar": temiz,
                },
                otomatik=True,
                session=session,
            )

    # ---- Satış faturası ----

    @staticmethod
    def satis_faturasi_fisi(fatura_id: int, *, yeniden: bool = False, session=None) -> int | None:
        from database.models.satis_faturasi import SatisFaturasi

        H = MuhasebeEntegrasyonService
        with oturum_kullan(session) as s:
            f = s.get(SatisFaturasi, int(fatura_id))
            if f is None or f.durum == "İPTAL" or not getattr(f, "onaylandi", False):
                return None
            matrah = decimal(getattr(f, "tl_matrah", None) or 0)
            kdv = decimal(getattr(f, "tl_kdv", None) or 0)
            genel = decimal(getattr(f, "tl_genel_toplam", None) or 0)
            if genel <= 0:
                from database.satis_faturasi_service import SatisFaturasiService

                t = SatisFaturasiService.toplam(f.satirlar)
                matrah = decimal(t["ara_toplam"] - t["iskonto"])
                kdv = decimal(t["kdv"])
                genel = decimal(t["genel_toplam"])
            elif genel != matrah + kdv:
                # Uzlaşma / genel indirim-masraf: fark satış hesabında netleşir, fiş dengeli kalır.
                matrah = genel - kdv
            tarih = f.fatura_tarihi
            no = f.fatura_no
            tahsilat = decimal(f.tahsilat_tutari or 0)
            sekil, tahsilat_hesabi = f.tahsilat_sekli, f.tahsilat_hesabi
            if f.tahsilatlar:
                th0 = f.tahsilatlar[0]
                sekil = th0.odeme_sekli or sekil
                tahsilat_hesabi = th0.hesap or tahsilat_hesabi
            # FIFO maliyet (varsa)
            maliyet = SIFIR
            from database.stok_service import StokService

            for satir in f.satirlar:
                mb = decimal(getattr(satir, "fifo_birim_maliyeti", None) or 0)
                if mb:
                    # FIFO maliyet temel birim başına; belge birimi katsayısıyla temel miktara çevrilir
                    maliyet += mb * decimal(satir.miktar) * StokService.satir_birim_carpani(s, satir)

            musteri = H._hesap("musteriler", session=s)
            satis = H._hesap("yurtici_satislar", session=s)
            satirlar = [
                H._satir(musteri, borc=genel, aciklama=f"Satış faturası {no}"),
                H._satir(satis, alacak=matrah, aciklama=f"Satış matrah {no}"),
            ]
            if kdv > 0:
                hesap_kdv = H._hesap("hesaplanan_kdv", session=s)
                satirlar.append(H._satir(hesap_kdv, alacak=kdv, aciklama=f"Hesaplanan KDV {no}"))
            if maliyet > 0:
                # SMM eşleştirmesi isteğe bağlıdır (mevcut davranış): yoksa maliyet satırı yazılmaz.
                try:
                    smm = H._hesap("satilan_mal_maliyeti", session=s)
                    stok = H._hesap("ticari_mallar", session=s)
                    satirlar.append(H._satir(smm, borc=maliyet, aciklama=f"SMM {no}"))
                    satirlar.append(H._satir(stok, alacak=maliyet, aciklama=f"Stok {no}"))
                except ValueError:
                    pass
            kasa = H._kasa_veya_banka(sekil, tahsilat_hesabi, session=s) if tahsilat > 0 else None

            fis_id = H._olustur(
                kaynak_turu=KAYNAK_SATIS_FATURA,
                kaynak_id=fatura_id,
                fis_tarihi=tarih,
                fis_turu="Mahsup Fişi",
                aciklama=f"Otomatik: Satış faturası {no}",
                belge_no=no,
                satirlar=satirlar,
                yeniden=yeniden,
                session=s,
            )
            if kasa is not None:
                H._olustur(
                    kaynak_turu=KAYNAK_SATIS_TAHSILAT,
                    kaynak_id=fatura_id,
                    fis_tarihi=tarih,
                    fis_turu="Tahsil Fişi",
                    aciklama=f"Otomatik: Satış tahsilatı {no}",
                    belge_no=no,
                    satirlar=[
                        H._satir(kasa, borc=tahsilat, aciklama=f"Tahsilat {no}"),
                        H._satir(musteri, alacak=tahsilat, aciklama=f"Tahsilat {no}"),
                    ],
                    yeniden=yeniden,
                    session=s,
                )
            return fis_id

    @staticmethod
    def satis_faturasi_iptal(fatura_id: int, neden: str = "", *, session=None) -> None:
        with oturum_kullan(session) as s:
            MuhasebeEntegrasyonService.iptal_kaynak(
                KAYNAK_SATIS_FATURA, fatura_id, neden or "Satış faturası iptal/onay kaldırma",
                session=s,
            )
            MuhasebeEntegrasyonService.iptal_kaynak(
                KAYNAK_SATIS_TAHSILAT, fatura_id, neden or "Satış tahsilat fişi iptal", session=s
            )

    # ---- Alış faturası ----

    @staticmethod
    def alis_faturasi_fisi(fatura_id: int, *, yeniden: bool = True, session=None) -> int | None:
        from database.models.alis_faturasi import AlisFaturasi

        H = MuhasebeEntegrasyonService
        with oturum_kullan(session) as s:
            f = s.get(AlisFaturasi, int(fatura_id))
            if f is None or f.durum == "İPTAL":
                return None
            matrah = decimal(getattr(f, "tl_matrah", None) or 0)
            kdv = decimal(getattr(f, "tl_kdv", None) or 0)
            genel = decimal(getattr(f, "tl_genel_toplam", None) or 0)
            if genel <= 0:
                from database.alis_faturasi_service import AlisFaturasiService

                t = AlisFaturasiService.toplam(f.satirlar)
                matrah = decimal(t["ara_toplam"] - t["iskonto"])
                kdv = decimal(t["kdv"])
                genel = decimal(t["genel_toplam"])
            tarih = f.fatura_tarihi
            no = f.fatura_no
            odeme = decimal(f.odeme_tutari or 0)
            odeme_sekli = f.odeme_sekli
            odeme_hesabi = f.odeme_hesabi

            stok = H._hesap("ticari_mallar", session=s)
            ted = H._hesap("tedarikciler", session=s)
            satirlar = [
                H._satir(stok, borc=matrah, aciklama=f"Alış {no}"),
                H._satir(ted, alacak=genel, aciklama=f"Alış {no}"),
            ]
            if kdv > 0:
                ikdv = H._hesap("indirilecek_kdv", session=s)
                satirlar.insert(1, H._satir(ikdv, borc=kdv, aciklama=f"İnd. KDV {no}"))
            kasa = H._kasa_veya_banka(odeme_sekli, odeme_hesabi, session=s) if odeme > 0 else None

            fis_id = H._olustur(
                kaynak_turu=KAYNAK_ALIS_FATURA,
                kaynak_id=fatura_id,
                fis_tarihi=tarih,
                fis_turu="Mahsup Fişi",
                aciklama=f"Otomatik: Alış faturası {no}",
                belge_no=no,
                satirlar=satirlar,
                yeniden=yeniden,
                session=s,
            )
            if kasa is not None:
                H._olustur(
                    kaynak_turu=KAYNAK_ALIS_ODEME,
                    kaynak_id=fatura_id,
                    fis_tarihi=tarih,
                    fis_turu="Tediye Fişi",
                    aciklama=f"Otomatik: Alış ödemesi {no}",
                    belge_no=no,
                    satirlar=[
                        H._satir(ted, borc=odeme, aciklama=f"Ödeme {no}"),
                        H._satir(kasa, alacak=odeme, aciklama=f"Ödeme {no}"),
                    ],
                    yeniden=yeniden,
                    session=s,
                )
            elif yeniden:
                # Düzenlemede ödeme kaldırıldıysa eski ödeme fişi de ters kayıtla kapanır
                H.iptal_kaynak(KAYNAK_ALIS_ODEME, fatura_id, "Alış ödemesi kaldırıldı", session=s)
            return fis_id

    @staticmethod
    def alis_faturasi_iptal(fatura_id: int, neden: str = "", *, session=None) -> None:
        with oturum_kullan(session) as s:
            MuhasebeEntegrasyonService.iptal_kaynak(
                KAYNAK_ALIS_FATURA, fatura_id, neden or "Alış iptal", session=s
            )
            MuhasebeEntegrasyonService.iptal_kaynak(
                KAYNAK_ALIS_ODEME, fatura_id, neden or "Alış ödeme iptal", session=s
            )

    # ---- İadeler ----

    @staticmethod
    def satis_iade_fisi(iade_id: int, *, yeniden: bool = True, session=None) -> int | None:
        from database.models.satis_iade_faturasi import SatisIadeFaturasi
        from database.satis_iade_faturasi_service import SatisIadeFaturasiService

        H = MuhasebeEntegrasyonService
        with oturum_kullan(session) as s:
            f = s.get(SatisIadeFaturasi, int(iade_id))
            if f is None or f.durum == "İPTAL":
                return None
            t = SatisIadeFaturasiService.toplam(f.satirlar)
            matrah = decimal(t["ara_toplam"] - t["iskonto"])
            kdv = decimal(t["kdv"])
            genel = decimal(t["genel_toplam"])
            tarih, no = f.iade_tarihi, f.iade_no

            musteri = H._hesap("musteriler", session=s)
            satis = H._hesap("yurtici_satislar", session=s)
            satirlar = [
                H._satir(satis, borc=matrah, aciklama=f"Satış iade {no}"),
                H._satir(musteri, alacak=genel, aciklama=f"Satış iade {no}"),
            ]
            if kdv > 0:
                hkdv = H._hesap("hesaplanan_kdv", session=s)
                satirlar.insert(1, H._satir(hkdv, borc=kdv, aciklama=f"KDV iade {no}"))
            return H._olustur(
                kaynak_turu=KAYNAK_SATIS_IADE,
                kaynak_id=iade_id,
                fis_tarihi=tarih,
                fis_turu="Mahsup Fişi",
                aciklama=f"Otomatik: Satış iadesi {no}",
                belge_no=no,
                satirlar=satirlar,
                yeniden=yeniden,
                session=s,
            )

    @staticmethod
    def alis_iade_fisi(iade_id: int, *, yeniden: bool = True, session=None) -> int | None:
        from database.alis_iade_faturasi_service import AlisIadeFaturasiService
        from database.models.alis_iade_faturasi import AlisIadeFaturasi

        H = MuhasebeEntegrasyonService
        with oturum_kullan(session) as s:
            f = s.get(AlisIadeFaturasi, int(iade_id))
            if f is None or f.durum in ("İPTAL", "TASLAK"):
                return None
            kdv_sorun = AlisIadeFaturasiService.kdv_kur_sorunu(s, f)
            if kdv_sorun:
                raise AyarEksik(kdv_sorun)
            if (f.para_birimi or "TRY").upper() != "TRY" and not f.kdv_kur_yontemi:
                from database.muhasebe_finans_ayarlari import KDV_KURU_IADE

                f.kdv_kur_yontemi = KDV_KURU_IADE
            t = AlisIadeFaturasiService.belge_toplami(f)
            matrah = decimal(t["ara_toplam"] - t["iskonto"])
            kdv = decimal(t["kdv"])
            genel = decimal(t["genel_toplam"])
            tarih, no = f.iade_tarihi, f.iade_no

            stok = H._hesap("ticari_mallar", session=s)
            ted = H._hesap("tedarikciler", session=s)
            # Stok gerçek FIFO maliyetiyle çıkar; bedel ile fark ayrı hesaba (maliyeti olmayan eski iadede bedelle)
            mf = AlisIadeFaturasiService.maliyet_farki(f)
            maliyet = mf["maliyet"] if mf else matrah
            fark = matrah - maliyet
            satirlar = [
                H._satir(ted, borc=genel, aciklama=f"Alış iade {no}"),
                H._satir(stok, alacak=maliyet, aciklama=f"Alış iade stok maliyeti {no}"),
            ]
            if fark:
                from database.muhasebe_finans_ayarlari import maliyet_farki_anahtari

                fh = H._ayarli_hesap(maliyet_farki_anahtari(fark), s)
                acik = f"Alış iade bedel–maliyet farkı {no}"
                satirlar.append(H._satir(fh, alacak=fark, aciklama=acik) if fark > 0
                                else H._satir(fh, borc=-fark, aciklama=acik))
            if kdv > 0:
                ikdv = H._hesap("indirilecek_kdv", session=s)
                satirlar.append(H._satir(ikdv, alacak=kdv, aciklama=f"KDV iade {no}"))
            fis_id = H._olustur(
                kaynak_turu=KAYNAK_ALIS_IADE,
                kaynak_id=iade_id,
                fis_tarihi=tarih,
                fis_turu="Mahsup Fişi",
                aciklama=f"Otomatik: Alış iadesi {no}",
                belge_no=no,
                satirlar=satirlar,
                yeniden=yeniden,
                session=s,
            )
            H._alis_iade_tahsilat_fisi(f, ted, session=s)
            return fis_id

    @staticmethod
    def _alis_iade_tahsilat_fisi(f, ted: dict, *, session) -> int | None:
        """İade bedelinin tedarikçiden tahsili: kasa/banka borç / satıcılar alacak.

        Tahsil edilen toplam değişmediyse mevcut fiş korunur; değiştiyse eski fiş ters kayıtla kapanıp
        yeni toplamla yazılır. Tahsilat yoksa varsa eski fiş kapatılır.
        """
        from database.models.finans import FinansHareketi

        H = MuhasebeEntegrasyonService
        hareketler = session.scalars(
            select(FinansHareketi).where(
                (FinansHareketi.belge_no == f.iade_no) | FinansHareketi.belge_no.like(f"{f.iade_no}-T%"),
                FinansHareketi.hareket_turu == "ALIŞ İADE TAHSİLATI",
            ).order_by(FinansHareketi.id)
        ).all()
        toplam = sum((decimal(h.tutar or 0) for h in hareketler), SIFIR)
        mevcut = H.mevcut_fis_id(KAYNAK_ALIS_IADE_TAHSILAT, int(f.id), session=session)
        if toplam <= 0:
            if mevcut:
                H.iptal_kaynak(KAYNAK_ALIS_IADE_TAHSILAT, int(f.id), "İade tahsilatı kaldırıldı", session=session)
            return None
        if mevcut:
            fis = session.get(MuhasebeFisi, mevcut)
            fis_toplam = sum((decimal(x.borc or 0) for x in getattr(fis, "satirlar", []) or []), SIFIR)
            if fis_toplam == toplam:
                return mevcut
        from database.models.finans import FinansHesabi

        satirlar = []
        for h in hareketler:
            fh = session.get(FinansHesabi, int(h.hesap_id))
            hesap = H._finans_karsiligi_ayarli(fh, session)
            satirlar.append(H._satir(hesap, borc=decimal(h.tutar), aciklama=f"İade tahsilatı {h.belge_no}"))
        satirlar.append(H._satir(ted, alacak=toplam, aciklama=f"İade tahsilatı {f.iade_no}"))
        return H._olustur(
            kaynak_turu=KAYNAK_ALIS_IADE_TAHSILAT,
            kaynak_id=int(f.id),
            fis_tarihi=max(h.tarih for h in hareketler),
            fis_turu="Tahsil Fişi",
            aciklama=f"Otomatik: Alış iade tahsilatı {f.iade_no}",
            belge_no=f.iade_no,
            satirlar=satirlar,
            yeniden=True,
            session=session,
        )

    # ---- Hizmet faturası ----

    @staticmethod
    def hizmet_faturasi_fisi(fatura_id: int, *, yeniden: bool = True, session=None) -> int | None:
        from database.models.hizmet_faturasi import HizmetFaturasi

        H = MuhasebeEntegrasyonService
        with oturum_kullan(session) as s:
            f = s.get(HizmetFaturasi, int(fatura_id))
            if f is None or f.durum == "İPTAL":
                return None
            kdv = decimal(f.tl_kdv or 0)
            genel = decimal(f.tl_genel_toplam or 0)
            # Kuruş yuvarlama farkı gelir/gider satırında netleşir; cari tutarı belgedeki genel toplamdır.
            matrah = genel - kdv
            tur = (f.fatura_turu or "GIDER").upper()
            tarih, no = f.fatura_tarihi, f.fatura_no

            if tur == "GELIR":
                musteri = H._hesap("musteriler", session=s)
                gelir = H._hesap("yurtici_satislar", session=s)
                satirlar = [
                    H._satir(musteri, borc=genel, aciklama=no),
                    H._satir(gelir, alacak=matrah, aciklama=no),
                ]
                if kdv > 0:
                    hkdv = H._hesap("hesaplanan_kdv", session=s)
                    satirlar.append(H._satir(hkdv, alacak=kdv, aciklama=no))
            else:
                gider = H._hesap("giderler", session=s)
                ted = H._hesap("tedarikciler", session=s)
                satirlar = [
                    H._satir(gider, borc=matrah, aciklama=no),
                    H._satir(ted, alacak=genel, aciklama=no),
                ]
                if kdv > 0:
                    ikdv = H._hesap("indirilecek_kdv", session=s)
                    satirlar.insert(1, H._satir(ikdv, borc=kdv, aciklama=no))

            return H._olustur(
                kaynak_turu=KAYNAK_HIZMET_FATURA,
                kaynak_id=fatura_id,
                fis_tarihi=tarih,
                fis_turu="Mahsup Fişi",
                aciklama=f"Otomatik: Hizmet faturası {no}",
                belge_no=no,
                satirlar=satirlar,
                yeniden=yeniden,
                session=s,
            )

    # ---- Gider fişi (kasa/banka) ----

    @staticmethod
    def gider_fisi_hesaplari(fis_id: int, *, session=None) -> list[str]:
        """Gider fişinin muhasebe kaydı için gereken eşleştirme anahtarları."""
        from database.models.finans import FinansHesabi, GiderFisi

        with oturum_kullan(session) as s:
            fis = s.get(GiderFisi, int(fis_id))
            if fis is None:
                return []
            hesap = s.get(FinansHesabi, int(fis.finans_hesap_id)) if fis.finans_hesap_id else None
            kasa_mi = hesap is not None and (hesap.hesap_turu or "").upper() == "KASA"
        return ["giderler", "kasa" if kasa_mi else "banka"]

    @staticmethod
    def gider_fisi_fisi(fis_id: int, *, yeniden: bool = False, session=None) -> int | None:
        """Gider hesabı borç / kasa-banka alacak. Gider fişinde KDV ayrıca kaydedilmez."""
        from database.models.finans import GiderFisi

        H = MuhasebeEntegrasyonService
        with oturum_kullan(session) as s:
            fis = s.get(GiderFisi, int(fis_id))
            if fis is None or (fis.durum or "").upper() in ("IPTAL", "İPTAL"):
                return None
            if (fis.gider_turu or "").upper() != "HIZMET":
                return None
            tutar = decimal(fis.tutar or 0)
            tarih, no = fis.tarih, fis.belge_no
            aciklama = fis.aciklama or no
            if tutar <= 0:
                return None
            from database.models.finans import FinansHesabi

            anahtarlar = H.gider_fisi_hesaplari(fis_id, session=s)
            gider = H._hesap(anahtarlar[0], session=s)
            fh = s.get(FinansHesabi, int(fis.finans_hesap_id)) if fis.finans_hesap_id else None
            odeme = H._finans_karsiligi_ayarli(fh, s) if fh is not None else H._hesap(anahtarlar[1], session=s)
            return H._olustur(
                kaynak_turu=KAYNAK_GIDER_FISI,
                kaynak_id=fis_id,
                fis_tarihi=tarih,
                fis_turu="Tediye Fişi",
                aciklama=f"Otomatik: Gider fişi {no}",
                belge_no=no,
                satirlar=[
                    H._satir(gider, borc=tutar, aciklama=aciklama),
                    H._satir(odeme, alacak=tutar, aciklama=aciklama),
                ],
                yeniden=yeniden,
                session=s,
            )

    @staticmethod
    def gider_fisi_iptal(fis_id: int, neden: str = "", *, session=None) -> None:
        MuhasebeEntegrasyonService.iptal_kaynak(
            KAYNAK_GIDER_FISI, fis_id, neden or "Gider fişi iptal", session=session
        )

    # ---- Cari tahsilat / ödeme ----

    @staticmethod
    def cari_hesabi(cari, *, session=None) -> dict:
        """Cari türüne göre alıcılar (müşteri) veya satıcılar (tedarikçi) eşleştirmesi."""
        from database.cari_virman_makbuz_service import musteri_mi, tedarikci_mi

        if cari is None:
            raise ValueError("Cari bulunamadı.")
        tur = cari.cari_turu or ""
        if tedarikci_mi(tur) and not musteri_mi(tur):
            return MuhasebeEntegrasyonService._hesap("tedarikciler", session=session)
        if musteri_mi(tur) and not tedarikci_mi(tur):
            return MuhasebeEntegrasyonService._hesap("musteriler", session=session)
        raise ValueError(
            f"{cari.cari_kodu} - {cari.unvan} carisinin türü ({tur or 'boş'}) alıcı/satıcı hesabını "
            "belirlemiyor; cari türünü düzeltin."
        )

    @staticmethod
    def finans_hesabi_anahtari(fh) -> str | None:
        """Kasa → kasa, mevduat / eski tek banka → banka, KMH / POS / şirket kartı → ayardaki hesap."""
        tur = (fh.hesap_turu or "").upper()
        alt = (fh.alt_hesap_turu or "").strip().upper()
        if tur == "KASA":
            return "kasa"
        if tur == "BANKA" and (alt in ("", "MEVDUAT") or alt.startswith("VADELI")):
            return "banka"
        return FINANS_ALT_ANAHTARI.get(alt)

    @staticmethod
    def _finans_hesabi_destek_disi(fh, *, session=None) -> str | None:
        """Kasa/banka kartının fiş hesabı belirlenemiyorsa nedeni ve nereden tanımlanacağı.

        ``session`` verilmezse KMH / POS / şirket kartı hesapları ayara bakılmadan desteklenmiyor sayılır
        (geçmiş evrak önizlemesi bu yolla temkinli kalır).
        """
        if fh is None:
            return None
        from database.muhasebe_finans_ayarlari import eksik_hesap_mesaji

        H = MuhasebeEntegrasyonService
        if getattr(fh, "muhasebe_hesap_id", None):
            with oturum_kullan(session) as s:
                try:
                    H._kart_hesabi(fh, s)
                except AyarEksik as hata:
                    return str(hata)
            return None
        anahtar = H.finans_hesabi_anahtari(fh)
        alt = (fh.alt_hesap_turu or "").strip().upper() or (fh.hesap_turu or "").upper()
        if anahtar in ("kasa", "banka"):
            if session is None:
                return None
            sorun = H.esleme_sorunu(anahtar, session=session)
            if sorun is None:
                return None
            return (f"'{fh.hesap_adi}' ({alt}) kartına muhasebe hesabı seçilmemiş ve firma varsayılanı "
                    f"('{anahtar}') kullanılamıyor: {sorun}. Tamamlamak için: {KART_HESAP_YERI}.")
        if anahtar is None:
            return (f"'{fh.hesap_adi}' ({alt}) hesap türünün muhasebe karşılığı tanımlı değil "
                    "(krediler hesabı ve alt türü belirsiz kart hesabı muhasebeleştirilmez).")
        if session is not None and MuhasebeEntegrasyonService.esleme_sorunu(anahtar, session=session) is None:
            return None
        return f"'{fh.hesap_adi}' ({alt}) hesabı için {eksik_hesap_mesaji(anahtar)}"

    @staticmethod
    def _kart_hesabi(fh, s, alan: str = "muhasebe_hesap_id") -> dict | None:
        """Kasa/banka kartında seçili muhasebe hesabı (yoksa None); fişe uygun değilse ``AyarEksik``."""
        hid = getattr(fh, alan, None)
        if not hid:
            return None
        firma_id = MuhasebeService.yerel_firma_id(s)
        h = s.get(HesapPlani, int(hid))
        sorun = hesap_uygunluk_sorunu(s, h, firma_id)
        if sorun:
            ne = "komisyon gideri hesabı" if alan == "muhasebe_komisyon_hesap_id" else "muhasebe hesabı"
            raise AyarEksik(f"'{fh.hesap_adi}' kartında seçili {ne} fişe uygun değil: {sorun}. "
                            f"Düzeltmek için: {KART_HESAP_YERI}.")
        return {"id": h.id, "kod": h.hesap_kodu, "ad": h.hesap_adi}

    @staticmethod
    def _finans_hesabi_adla(hesap_adi: str | None, *, session=None):
        if not hesap_adi:
            return None
        from database.models.finans import FinansHesabi

        with oturum_kullan(session) as s:
            return s.scalar(select(FinansHesabi).where(FinansHesabi.hesap_adi == hesap_adi))

    @staticmethod
    def _ayarli_hesap(anahtar: str, s) -> dict:
        """Finans İşlem Ayarları hesabı: tanımsız / fişe uygun değilse ``AyarEksik`` (evrak incelemeye düşer)."""
        from database.muhasebe_finans_ayarlari import eksik_hesap_mesaji

        sorun = MuhasebeEntegrasyonService.esleme_sorunu(anahtar, session=s)
        if sorun:
            raise AyarEksik(f"{eksik_hesap_mesaji(anahtar)} ({sorun})")
        return MuhasebeEntegrasyonService._hesap(anahtar, session=s)

    @staticmethod
    def _finans_karsiligi_ayarli(fh, s) -> dict:
        H = MuhasebeEntegrasyonService
        if fh is None:
            raise ValueError("Kasa/banka hesabı bulunamadı.")
        kart = H._kart_hesabi(fh, s)
        if kart is not None:
            return kart
        neden = H._finans_hesabi_destek_disi(fh, session=s)
        if neden:
            raise AyarEksik(neden)
        return H._hesap(H.finans_hesabi_anahtari(fh), session=s)

    @staticmethod
    def _planla(evrak: str, s, kaynak_id: int):
        return getattr(MuhasebeEntegrasyonService, PLANLAR[evrak])(s, int(kaynak_id))

    @staticmethod
    def muhasebe_disi_neden(evrak: str, kaynak_id: int, *, session=None) -> str | None:
        """Ayar gereği fiş üretmeyen işlem (ör. kapatılmış çek/senet aşaması) ise nedeni."""
        if evrak not in PLANLAR:
            return None
        with oturum_kullan(session) as s:
            try:
                MuhasebeEntegrasyonService._planla(evrak, s, kaynak_id)
            except MuhasebeDisiAyar as hata:
                return str(hata)
            except ValueError:
                return None
        return None

    @staticmethod
    def karar_bekleyen_neden(evrak: str, kaynak_id: int, *, session=None) -> str | None:
        """Evrakın fişi için gereken finans ayarı / hesabı tanımsızsa nedeni (fiş tahmine dayandırılmaz)."""
        from database.models.finans import (
            FinansHareketi,
            FinansHesabi,
            KasaMakbuzSatiri,
            KasaMakbuzu,
            PosValorKaydi,
        )

        H = MuhasebeEntegrasyonService
        with oturum_kullan(session) as s:
            if evrak == "alis_iade":
                return H._alis_iade_karar_neden(s, int(kaynak_id))
            if evrak in PLANLAR:
                try:
                    H._planla(evrak, s, kaynak_id)
                except AyarEksik as hata:
                    return str(hata)
                except (ValueError, MuhasebeDisiAyar):
                    return None
                return None
            hesaplar = []
            if evrak == "kasa_makbuzu":
                m = s.get(KasaMakbuzu, int(kaynak_id))
                if m is None:
                    return None
                s.flush()
                makbuz_satirlari = list(s.scalars(select(KasaMakbuzSatiri).where(
                    KasaMakbuzSatiri.makbuz_id == m.id)).all())
                for st in makbuz_satirlari:
                    if st.pos_valor_id:
                        try:
                            H._pos_hesaplari(s.get(PosValorKaydi, st.pos_valor_id), s)
                        except AyarEksik as hata:
                            return f"Makbuz satırı {st.sira_no} (POS): {hata}"
                        except ValueError:
                            pass
                    hesaplar.append(st.finans_hesap_id)
                if not makbuz_satirlari:
                    hesaplar.append(m.finans_hesap_id)
            elif evrak in ("kasa_banka_virman", "banka_havale", "cari_tahsilat", "cari_odeme"):
                from database.models.finans import FinansEvrakKimligi

                kimlik = s.get(FinansEvrakKimligi, int(kaynak_id))
                if kimlik is None:
                    return None
                hesaplar = list(s.scalars(select(FinansHareketi.hesap_id).where(
                    FinansHareketi.belge_no == kimlik.belge_no)).all())
            elif evrak == "gider_fisi":
                from database.models.finans import GiderFisi

                g = s.get(GiderFisi, int(kaynak_id))
                if g is not None and g.finans_hesap_id:
                    hesaplar.append(g.finans_hesap_id)
            elif evrak in ("satis_faturasi", "alis_faturasi"):
                fh = H._fatura_finans_hesabi(s, evrak, int(kaynak_id))
                if fh is not None:
                    hesaplar.append(fh.id)
            for hid in hesaplar:
                neden = H._finans_hesabi_destek_disi(s.get(FinansHesabi, hid) if hid else None, session=s)
                if neden:
                    return neden
        return None

    @staticmethod
    def _alis_iade_karar_neden(s, iade_id: int) -> str | None:
        """Dövizli iadede KDV kuru yöntemi seçilmemişse veya bedel ≠ stok maliyeti iken farkın yönüne ait
        (olumlu / olumsuz) hesap tanımsızsa neden (fiş yazılmış iade yeniden değerlendirilmez)."""
        from database.alis_iade_faturasi_service import AlisIadeFaturasiService
        from database.models.alis_iade_faturasi import AlisIadeFaturasi
        from database.muhasebe_finans_ayarlari import eksik_hesap_mesaji, maliyet_farki_anahtari

        H = MuhasebeEntegrasyonService
        f = s.get(AlisIadeFaturasi, int(iade_id))
        if f is None or H.mevcut_fis_id(KAYNAK_ALIS_IADE, int(iade_id), session=s):
            return None
        nedenler = []
        kdv_sorun = AlisIadeFaturasiService.kdv_kur_sorunu(s, f)
        if kdv_sorun:
            nedenler.append(kdv_sorun)
        mf = AlisIadeFaturasiService.maliyet_farki(f)
        anahtar = maliyet_farki_anahtari(mf["fark"]) if mf else None
        if anahtar and H.esleme_sorunu(anahtar, session=s):
            yon = "olumlu (bedel > maliyet)" if mf["fark"] > 0 else "olumsuz (bedel < maliyet)"
            nedenler.append(
                f"{f.iade_no}: iade bedeli {mf['bedel']} TL, gerçek stok maliyeti {mf['maliyet']} TL; "
                f"{abs(mf['fark'])} TL {yon} maliyet farkı için hesap tanımlı değil, fark tahmin edilmedi. "
                f"{eksik_hesap_mesaji(anahtar)}")
        return " | ".join(nedenler) or None

    @staticmethod
    def finans_hesabi_karsiligi(fh, *, session=None) -> dict:
        """Kasa → kasa, mevduat (veya eski tek banka hesabı) → banka eşleştirmesi; KMH / POS / şirket
        kartı → Finans İşlem Ayarları'nda bağlanan hesap. Tanımsızsa tahmin edilmez, fiş üretilmez."""
        if fh is None:
            raise ValueError("Kasa/banka hesabı bulunamadı.")
        if getattr(fh, "muhasebe_hesap_id", None):
            with oturum_kullan(session) as s:
                try:
                    return MuhasebeEntegrasyonService._kart_hesabi(fh, s)
                except AyarEksik as hata:
                    raise ValueError(f"{hata} Fiş oluşturulmadı.") from hata
        neden = MuhasebeEntegrasyonService._finans_hesabi_destek_disi(fh, session=session)
        if neden:
            raise ValueError(f"{neden} Fiş oluşturulmadı.")
        anahtar = MuhasebeEntegrasyonService.finans_hesabi_anahtari(fh)
        return MuhasebeEntegrasyonService._hesap(anahtar, session=session)

    # ---- POS / şirket kartı ----

    @staticmethod
    def _pos_hesaplari(pv, s) -> tuple[dict, dict | None, Decimal, Decimal]:
        """(valör alacağı hesabı, komisyon gideri hesabı|None, net, komisyon)."""
        H = MuhasebeEntegrasyonService
        if pv is None:
            raise ValueError("POS valör kaydı bulunamadı.")
        from database.models.finans import FinansHesabi

        net, komisyon = decimal(pv.net_tutar or 0), decimal(pv.komisyon_tutari or 0)
        if net + komisyon != decimal(pv.brut_tutar or 0):
            raise ValueError(f"{pv.belge_no}: POS net + komisyon brüt tutara eşit değil.")
        pos = s.get(FinansHesabi, pv.pos_hesap_id) if pv.pos_hesap_id else None
        alacak = (H._kart_hesabi(pos, s) if pos is not None else None) or H._ayarli_hesap("pos_valor_alacagi", s)
        gider = None
        if komisyon > 0:
            gider = ((H._kart_hesabi(pos, s, "muhasebe_komisyon_hesap_id") if pos is not None else None)
                     or H._ayarli_hesap("pos_komisyon_gideri", s))
        return alacak, gider, net, komisyon

    @staticmethod
    def _fatura_finans_hesabi(s, evrak: str, fatura_id: int):
        """Fatura içi tahsilat/ödemenin kasa/banka kartı (fişte kullanılan; yoksa None)."""
        H = MuhasebeEntegrasyonService
        if evrak == "satis_faturasi":
            from database.models.satis_faturasi import SatisFaturasi

            f = s.get(SatisFaturasi, fatura_id)
            if f is None or decimal(f.tahsilat_tutari or 0) <= 0:
                return None
            ad = (f.tahsilatlar[0].hesap if f.tahsilatlar else None) or f.tahsilat_hesabi
        else:
            from database.models.alis_faturasi import AlisFaturasi

            f = s.get(AlisFaturasi, fatura_id)
            if f is None or decimal(f.odeme_tutari or 0) <= 0:
                return None
            ad = f.odeme_hesabi
        return H._finans_hesabi_adla(ad, session=s)

    @staticmethod
    def _plan_pos_tahsilat(s, pv_id: int) -> dict | None:
        from database.models.cari import Cari
        from database.models.finans import PosValorKaydi

        H = MuhasebeEntegrasyonService
        pv = s.get(PosValorKaydi, pv_id)
        if pv is None or (pv.durum or "").upper() == "IPTAL":
            return None
        if not pv.cari_id:
            raise AyarEksik("Cari seçilmeden yapılan POS tahsilatının karşı hesabı belirlenemiyor; fiş tahmin "
                            "edilmez. Fişi elle kesin veya 'Muhasebe dışı bırak' ile işaretleyin.")
        alacak, gider, net, komisyon = H._pos_hesaplari(pv, s)
        cari = H.cari_hesabi(s.get(Cari, pv.cari_id), session=s)
        satirlar = [H._satir(alacak, borc=net, aciklama=f"{pv.belge_no} POS valör alacağı")]
        if gider is not None:
            satirlar.append(H._satir(gider, borc=komisyon, aciklama=f"{pv.belge_no} POS komisyonu"))
        satirlar.append(H._satir(cari, alacak=net + komisyon, aciklama=pv.belge_no))
        return {"kaynak_turu": KAYNAK_POS_TAHSILAT, "fis_tarihi": pv.tahsilat_tarihi, "fis_turu": "Tahsil Fişi",
                "aciklama": f"Otomatik: POS tahsilatı {pv.belge_no}", "belge_no": pv.belge_no,
                "satirlar": satirlar}

    @staticmethod
    def _plan_kart_odeme(s, ko_id: int) -> dict | None:
        from database.models.cari import Cari
        from database.models.finans import FinansHesabi, KrediKartiOdeme

        H = MuhasebeEntegrasyonService
        ko = s.get(KrediKartiOdeme, ko_id)
        if ko is None or (ko.durum or "").upper() in ("IPTAL", "İPTAL"):
            return None
        kk_hesap = s.scalar(select(FinansHesabi).where(
            FinansHesabi.banka_karti_id == ko.banka_karti_id, FinansHesabi.alt_hesap_turu == "KREDI_KARTI"))
        kart = H._finans_karsiligi_ayarli(kk_hesap, s)
        cari = H.cari_hesabi(s.get(Cari, ko.cari_id), session=s)
        tutar = decimal(ko.tutar or 0)
        return {"kaynak_turu": KAYNAK_KART_ODEME, "fis_tarihi": ko.tarih, "fis_turu": "Mahsup Fişi",
                "aciklama": f"Otomatik: Şirket kartıyla ödeme {ko.belge_no}", "belge_no": ko.belge_no,
                "satirlar": [H._satir(cari, borc=tutar, aciklama=ko.belge_no),
                             H._satir(kart, alacak=tutar, aciklama=ko.belge_no)]}

    @staticmethod
    def _plan_pos_valor_aktarimi(s, pv_id: int) -> dict | None:
        from database.models.finans import FinansHesabi, PosValorKaydi

        H = MuhasebeEntegrasyonService
        pv = s.get(PosValorKaydi, pv_id)
        if pv is None or (pv.durum or "").upper() != "AKTARILDI":
            return None
        net = decimal(pv.net_tutar or 0)
        borc = H._finans_karsiligi_ayarli(s.get(FinansHesabi, pv.kmh_hesap_id), s)
        alacak = H._finans_karsiligi_ayarli(s.get(FinansHesabi, pv.pos_hesap_id), s)
        tarih = pv.aktarim_zamani.date() if pv.aktarim_zamani else pv.valor_tarihi
        acik = f"{pv.belge_no} POS valör aktarımı"
        return {"kaynak_turu": KAYNAK_POS_VALOR, "fis_tarihi": tarih, "fis_turu": "Mahsup Fişi",
                "aciklama": f"Otomatik: {acik}", "belge_no": pv.belge_no,
                "satirlar": [H._satir(borc, borc=net, aciklama=acik), H._satir(alacak, alacak=net, aciklama=acik)]}

    # ---- Çek / senet ----

    CEK_ASAMA = {"BANKAYA_TAHSILE": "BANKAYA_TAHSILE", "BANKAYA_TEMINATA": "BANKAYA_TEMINATA", "CIRO": "CIRO",
                 "TAHSIL": "TAHSIL", "KISMI_TAHSIL": "TAHSIL", "ODEME": "ODEME", "KISMI_ODEME": "ODEME",
                 "KARSILIKSIZ": "KARSILIKSIZ", "PROTESTO": "KARSILIKSIZ", "IADE": "IADE"}

    @staticmethod
    def cek_senet_asamasi(islem_turu: str, islem_yonu: str) -> str | None:
        if islem_turu == "KAYIT":
            return "KAYIT_ALINAN" if islem_yonu == "ALINAN" else "KAYIT_VERILEN"
        return MuhasebeEntegrasyonService.CEK_ASAMA.get(islem_turu)

    @staticmethod
    def cek_senet_tarihi(s, h, e) -> date:
        from database.models.cari import CariIslem
        from database.models.finans import FinansHareketi

        if h.islem_turu == "KAYIT":
            return e.duzenleme_tarihi
        if h.finans_hareket_id:
            t = s.scalar(select(FinansHareketi.tarih).where(FinansHareketi.id == h.finans_hareket_id))
            if t:
                return t
        if h.cari_hareket_id:
            t = s.scalar(select(CariIslem.tarih).where(CariIslem.id == h.cari_hareket_id))
            if t:
                return t
        return h.tarih.date() if hasattr(h.tarih, "date") else h.tarih

    @staticmethod
    def _cek_konum_anahtari(s, h, e, cek: bool) -> str | None:
        """Evrakın bu işlemden önce bulunduğu muhasebe hesabı: fiş üretmiş/üretecek son konum aşaması.

        Konum aşaması (kayıt, tahsile/teminata verme) muhasebe dışı kaldıysa veya hiç durum kaydı yoksa
        (genel muhasebe kapalıyken) evrak cari hesapta sayılır.
        """
        from database.models.cek_senet import CekSenetHareket
        from database.models.genel_muhasebe import BELGE_IPTAL, BELGE_MUHASEBE_DISI, MuhasebeBelgeDurumu

        onceki = s.scalars(select(CekSenetHareket).where(
            CekSenetHareket.evrak_id == e.id, CekSenetHareket.id < h.id).order_by(CekSenetHareket.id)).all()
        if not onceki:
            return None
        firma_id = MuhasebeService.yerel_firma_id(s)
        durumlar = dict(s.execute(select(MuhasebeBelgeDurumu.kaynak_id, MuhasebeBelgeDurumu.durum).where(
            MuhasebeBelgeDurumu.firma_id == firma_id, MuhasebeBelgeDurumu.evrak_turu == "cek_senet",
            MuhasebeBelgeDurumu.kaynak_id.in_([o.id for o in onceki]))).all())
        tur = "cek" if cek else "senet"
        konum = None
        for o in onceki:
            if durumlar.get(o.id) in (None, BELGE_MUHASEBE_DISI, BELGE_IPTAL):
                continue
            if o.islem_turu == "KAYIT":
                konum = (f"{tur}_portfoy" if e.islem_yonu == "ALINAN"
                         else ("verilen_cekler" if cek else "borc_senetleri"))
            elif o.islem_turu == "BANKAYA_TAHSILE":
                konum = f"{tur}_tahsilde"
            elif o.islem_turu == "BANKAYA_TEMINATA":
                konum = f"{tur}_teminatta"
        return konum

    @staticmethod
    def _plan_cek_senet(s, hareket_id: int) -> dict | None:
        from database.models.cari import Cari
        from database.models.cek_senet import CekSenetEvrak, CekSenetHareket
        from database.models.finans import FinansHesabi
        from database.muhasebe_finans_ayarlari import (
            AYAR_YERI,
            CEK_SENET_ASAMA_ADI,
            HAYIR,
            ayar_oku,
            cek_senet_anahtari,
            eksik_secenek_mesaji,
        )

        H = MuhasebeEntegrasyonService
        h = s.get(CekSenetHareket, hareket_id)
        if h is None:
            return None
        e = s.get(CekSenetEvrak, h.evrak_id)
        asama = H.cek_senet_asamasi(h.islem_turu, e.islem_yonu)
        if asama is None:
            return None
        ad = CEK_SENET_ASAMA_ADI[asama]
        deger = ayar_oku(cek_senet_anahtari(asama), session=s)
        if deger is None:
            raise AyarEksik(eksik_secenek_mesaji(f"Çek/senet aşaması '{ad}'", "Çek / Senet"))
        if deger == HAYIR:
            raise MuhasebeDisiAyar(f"Ayar gereği '{ad}' aşaması fiş üretmez ({AYAR_YERI} → Çek / Senet).")
        tutar = decimal(e.tl_tutari or 0) if h.islem_turu == "KAYIT" else decimal(h.tutar or 0)
        if tutar <= 0:
            return None
        cek = "CEK" in (e.evrak_turu or "").upper()
        tur = "cek" if cek else "senet"
        verilen_anahtar = "verilen_cekler" if cek else "borc_senetleri"

        def cari(cid):
            if not cid:
                raise AyarEksik(f"{e.portfoy_no}: evrakın carisi yok; '{ad}' aşamasının karşı hesabı belirlenemiyor.")
            return H.cari_hesabi(s.get(Cari, cid), session=s)

        def konum():
            anahtar = H._cek_konum_anahtari(s, h, e, cek)
            return H._ayarli_hesap(anahtar, s) if anahtar else cari(e.cari_id)

        if asama == "KAYIT_ALINAN":
            borc, alacak = H._ayarli_hesap(f"{tur}_portfoy", s), cari(e.cari_id)
        elif asama == "KAYIT_VERILEN":
            borc, alacak = cari(e.cari_id), H._ayarli_hesap(verilen_anahtar, s)
        elif asama == "BANKAYA_TAHSILE":
            borc, alacak = H._ayarli_hesap(f"{tur}_tahsilde", s), konum()
        elif asama == "BANKAYA_TEMINATA":
            borc, alacak = H._ayarli_hesap(f"{tur}_teminatta", s), konum()
        elif asama == "CIRO":
            borc, alacak = cari(h.ilgili_cari_id), konum()
        elif asama == "TAHSIL":
            borc, alacak = H._finans_karsiligi_ayarli(s.get(FinansHesabi, h.ilgili_banka_kasa_id), s), konum()
        elif asama == "ODEME":
            borc, alacak = konum(), H._finans_karsiligi_ayarli(s.get(FinansHesabi, h.ilgili_banka_kasa_id), s)
        elif asama == "KARSILIKSIZ":
            borc, alacak = cari(e.cari_id), konum()
        elif e.islem_yonu == "ALINAN":  # IADE
            borc, alacak = cari(e.cari_id), konum()
        else:
            borc, alacak = konum(), cari(e.cari_id)
        if borc["id"] == alacak["id"]:
            return None  # evrak cari hesapta izleniyor: bu aşamanın muhasebe etkisi yok
        acik = f"{e.portfoy_no} {ad}"
        return {"kaynak_turu": KAYNAK_CEK_SENET, "fis_tarihi": H.cek_senet_tarihi(s, h, e),
                "fis_turu": {"TAHSIL": "Tahsil Fişi", "ODEME": "Tediye Fişi"}.get(asama, "Mahsup Fişi"),
                "aciklama": f"Otomatik: Çek/senet {acik}", "belge_no": e.portfoy_no,
                "satirlar": [H._satir(borc, borc=tutar, aciklama=acik), H._satir(alacak, alacak=tutar, aciklama=acik)]}

    # ---- Banka kredisi ----

    @staticmethod
    def _kredi_ayarlari(s) -> tuple[str, str]:
        from database.muhasebe_finans_ayarlari import (
            KREDI_FIS_ZAMANI,
            KREDI_VADE_AYRIMI,
            ayar_oku,
            eksik_secenek_mesaji,
        )

        zaman = ayar_oku(KREDI_FIS_ZAMANI, session=s)
        if zaman is None:
            raise AyarEksik(eksik_secenek_mesaji("Banka kredisi fiş zamanı (kullandırım / taksit)", "Banka Kredisi"))
        ayrim = ayar_oku(KREDI_VADE_AYRIMI, session=s)
        if ayrim is None:
            raise AyarEksik(eksik_secenek_mesaji("Banka kredisi kısa / uzun vade ayrımı", "Banka Kredisi"))
        return zaman, ayrim

    @staticmethod
    def _kredi_vade_siniri(kredi) -> date:
        t = kredi.kullandirim_tarihi
        try:
            return t.replace(year=t.year + 1)
        except ValueError:  # 29 Şubat
            return t.replace(year=t.year + 1, day=28)

    @staticmethod
    def _plan_banka_kredi_kullandirim(s, kredi_id: int) -> dict | None:
        from database.models.finans import BankaKredisi, BankaKrediTaksit, FinansHareketi, FinansHesabi
        from database.muhasebe_finans_ayarlari import AYAR_YERI

        H = MuhasebeEntegrasyonService
        k = s.get(BankaKredisi, kredi_id)
        if k is None:
            return None
        zaman, ayrim = H._kredi_ayarlari(s)
        if zaman == "yalniz_taksit":
            raise MuhasebeDisiAyar(f"Ayar gereği kredi kullandırımı fiş üretmez; fiş taksit ödemelerinde yazılır "
                                   f"({AYAR_YERI} → Banka Kredisi).")
        ana = decimal(k.ana_para or 0)
        if ana <= 0:
            return None
        kisa = ana
        if ayrim == "oniki_ay":
            sinir = H._kredi_vade_siniri(k)
            kisa = min(ana, sum((decimal(t.anapara or 0) for t in s.scalars(select(BankaKrediTaksit).where(
                BankaKrediTaksit.kredi_id == k.id,
                BankaKrediTaksit.durum.not_in(("IPTAL", "YAPILANDIRILDI")),
                BankaKrediTaksit.vade_tarihi <= sinir)).all()), SIFIR))
        uzun = ana - kisa
        nakit = s.scalar(select(FinansHesabi).join(FinansHareketi, FinansHareketi.hesap_id == FinansHesabi.id).where(
            FinansHareketi.belge_no == k.belge_no, FinansHareketi.hareket_turu == "KREDİ KULLANDIRIM (MEVDUAT)"))
        borc = H._finans_karsiligi_ayarli(nakit, s)
        acik = f"{k.belge_no} {k.kredi_adi}"
        satirlar = [H._satir(borc, borc=ana, aciklama=acik)]
        if kisa > 0:
            satirlar.append(H._satir(H._ayarli_hesap("kredi_kisa_vadeli", s), alacak=kisa, aciklama=acik))
        if uzun > 0:
            satirlar.append(H._satir(H._ayarli_hesap("kredi_uzun_vadeli", s), alacak=uzun, aciklama=acik))
        return {"kaynak_turu": KAYNAK_KREDI_KULLANDIRIM, "fis_tarihi": k.kullandirim_tarihi, "fis_turu": "Mahsup Fişi",
                "aciklama": f"Otomatik: Kredi kullandırımı {acik}", "belge_no": k.belge_no, "satirlar": satirlar}

    @staticmethod
    def _plan_banka_kredi_odeme(s, odeme_id: int) -> dict | None:
        from database.models.finans import BankaKredisi, BankaKrediOdeme, BankaKrediTaksit, FinansHesabi

        H = MuhasebeEntegrasyonService
        o = s.get(BankaKrediOdeme, odeme_id)
        if o is None or (o.durum or "").upper() == "IPTAL" or (o.odeme_turu or "").upper() == "IPTAL":
            return None
        _zaman, ayrim = H._kredi_ayarlari(s)
        k = s.get(BankaKredisi, o.kredi_id)
        anapara = decimal(o.anapara or 0)
        paylar = {"kredi_kisa_vadeli": SIFIR, "kredi_uzun_vadeli": SIFIR}
        if anapara > 0:
            if ayrim == "tumu_kisa":
                paylar["kredi_kisa_vadeli"] = anapara
            else:
                sinir = H._kredi_vade_siniri(k)
                if o.taksit_id:
                    t = s.get(BankaKrediTaksit, o.taksit_id)
                    paylar["kredi_kisa_vadeli" if t.vade_tarihi <= sinir else "kredi_uzun_vadeli"] = anapara
                elif (o.odeme_turu or "").upper() == "ERKEN_KAPAMA":
                    for t in s.scalars(select(BankaKrediTaksit).where(
                            BankaKrediTaksit.kredi_id == k.id, BankaKrediTaksit.odeme_belge_no == o.odeme_belge_no,
                            BankaKrediTaksit.durum == "ERKEN_KAPATILDI")).all():
                        kalan = decimal(t.anapara or 0) - decimal(t.odenen_anapara or 0)
                        if kalan > 0:
                            paylar["kredi_kisa_vadeli" if t.vade_tarihi <= sinir else "kredi_uzun_vadeli"] += kalan
                    if paylar["kredi_kisa_vadeli"] + paylar["kredi_uzun_vadeli"] != anapara:
                        raise ValueError(f"{o.odeme_belge_no}: erken kapama anaparası kapatılan taksitlerle uyuşmuyor; "
                                         "kısa/uzun vade payı belirlenemedi.")
                else:
                    raise AyarEksik(
                        "Taksite bağlı olmayan ara ödemede anaparanın kısa/uzun vade payı belirlenemiyor (vade ayrımı: "
                        "12 ay). Fişi elle kesin ya da vade ayrımını 'Tüm anapara kısa vadeli' yapın.")
        acik = f"{o.odeme_belge_no} {k.kredi_adi if k else ''}".strip()
        satirlar = [H._satir(H._ayarli_hesap(a, s), borc=t, aciklama=f"{acik} anapara")
                    for a, t in paylar.items() if t > 0]
        for alan, anahtar in KREDI_GIDER_ANAHTARLARI.items():
            tutar = decimal(getattr(o, alan, None) or 0)
            if tutar > 0:
                satirlar.append(H._satir(H._ayarli_hesap(anahtar, s), borc=tutar, aciklama=f"{acik} {alan}"))
        toplam = decimal(o.toplam or 0)
        if sum((x["borc"] for x in satirlar), SIFIR) != toplam:
            raise ValueError(f"{o.odeme_belge_no}: ödeme bileşenleri toplam tutara eşit değil.")
        odeme_hesap = H._finans_karsiligi_ayarli(s.get(FinansHesabi, o.banka_hesap_id), s)
        satirlar.append(H._satir(odeme_hesap, alacak=toplam, aciklama=acik))
        return {"kaynak_turu": KAYNAK_KREDI_ODEME, "fis_tarihi": o.odeme_tarihi, "fis_turu": "Tediye Fişi",
                "aciklama": f"Otomatik: Kredi ödemesi {acik}", "belge_no": o.odeme_belge_no, "satirlar": satirlar}

    @staticmethod
    def _planli_fis(evrak: str, kaynak_id: int, *, yeniden: bool, session) -> int | None:
        H = MuhasebeEntegrasyonService
        with oturum_kullan(session) as s:
            try:
                plan = H._planla(evrak, s, kaynak_id)
            except MuhasebeDisiAyar:
                plan = None
            if plan is None:
                if yeniden:
                    for kaynak in EVRAKLAR[evrak]["kaynaklar"]:
                        H.iptal_kaynak(kaynak, kaynak_id, "Evrak değişti; fiş gerekmiyor", session=s)
                return None
            return H._olustur(kaynak_id=int(kaynak_id), yeniden=yeniden, session=s, **plan)

    @staticmethod
    def pos_tahsilat_fisi(pv_id: int, *, yeniden: bool = False, session=None) -> int | None:
        """Borç POS valör alacağı (net) + POS komisyon gideri / Alacak cari (brüt)."""
        return MuhasebeEntegrasyonService._planli_fis("pos_tahsilat", pv_id, yeniden=yeniden, session=session)

    @staticmethod
    def kart_odeme_fisi(ko_id: int, *, yeniden: bool = False, session=None) -> int | None:
        """Borç cari / Alacak şirket kartı borcu."""
        return MuhasebeEntegrasyonService._planli_fis("kart_odeme", ko_id, yeniden=yeniden, session=session)

    @staticmethod
    def pos_valor_aktarimi_fisi(pv_id: int, *, yeniden: bool = False, session=None) -> int | None:
        """Borç KMH hesabı / Alacak POS valör alacağı (net)."""
        return MuhasebeEntegrasyonService._planli_fis("pos_valor_aktarimi", pv_id, yeniden=yeniden, session=session)

    @staticmethod
    def cek_senet_fisi(hareket_id: int, *, yeniden: bool = False, session=None) -> int | None:
        return MuhasebeEntegrasyonService._planli_fis("cek_senet", hareket_id, yeniden=yeniden, session=session)

    @staticmethod
    def banka_kredi_kullandirim_fisi(kredi_id: int, *, yeniden: bool = False, session=None) -> int | None:
        """Borç mevduat/KMH / Alacak kısa (ve 12 ay ayrımında uzun) vadeli banka kredisi."""
        return MuhasebeEntegrasyonService._planli_fis("banka_kredi_kullandirim", kredi_id, yeniden=yeniden,
                                                      session=session)

    @staticmethod
    def banka_kredi_odeme_fisi(odeme_id: int, *, yeniden: bool = False, session=None) -> int | None:
        """Borç kredi anaparası + faiz/masraf giderleri / Alacak ödeme hesabı."""
        return MuhasebeEntegrasyonService._planli_fis("banka_kredi_odeme", odeme_id, yeniden=yeniden,
                                                      session=session)

    @staticmethod
    def pos_tahsilat_iptal(pv_id: int, neden: str = "", *, session=None) -> None:
        MuhasebeEntegrasyonService.iptal_kaynak(KAYNAK_POS_TAHSILAT, pv_id, neden, session=session)

    @staticmethod
    def kart_odeme_iptal(ko_id: int, neden: str = "", *, session=None) -> None:
        MuhasebeEntegrasyonService.iptal_kaynak(KAYNAK_KART_ODEME, ko_id, neden, session=session)

    @staticmethod
    def cek_senet_iptal(hareket_id: int, neden: str = "", *, session=None) -> None:
        MuhasebeEntegrasyonService.iptal_kaynak(KAYNAK_CEK_SENET, hareket_id, neden, session=session)

    @staticmethod
    def banka_kredi_odeme_iptal(odeme_id: int, neden: str = "", *, session=None) -> None:
        MuhasebeEntegrasyonService.iptal_kaynak(KAYNAK_KREDI_ODEME, odeme_id, neden, session=session)

    @staticmethod
    def _plan_kur_farki(s, kayit_id: int) -> dict | None:
        return _plan_kur_farki(s, kayit_id)

    @staticmethod
    def kur_farki_fisi(kayit_id: int, *, yeniden: bool = False, session=None) -> int | None:
        """Kur farkı kaydının fişi (``KurFarkiKaydi`` başına tek fiş)."""
        return MuhasebeEntegrasyonService._planli_fis("kur_farki", kayit_id, yeniden=yeniden, session=session)

    @staticmethod
    def kur_farki_iptal(kayit_id: int, neden: str = "", *, session=None) -> None:
        MuhasebeEntegrasyonService.iptal_kaynak(KAYNAK_KUR_FARKI, kayit_id, neden, session=session)

    @staticmethod
    def _belge_finans_hesabi(s, belge_no: str, hareket_turleri: tuple[str, ...]):
        from database.models.finans import FinansHareketi, FinansHesabi

        hareketler = s.scalars(
            select(FinansHareketi).where(
                FinansHareketi.belge_no == belge_no, FinansHareketi.hareket_turu.in_(hareket_turleri)
            )
        ).all()
        if len(hareketler) != 1:
            raise ValueError(
                f"{belge_no}: kasa/banka hareketi {'bulunamadı' if not hareketler else 'birden fazla'}; "
                "fiş hesabı kesin belirlenemedi."
            )
        return s.get(FinansHesabi, hareketler[0].hesap_id), decimal(hareketler[0].tutar)

    @staticmethod
    def _cari_islem_fisi(kimlik_id: int, evrak_turu: str, *, yeniden: bool, session) -> int | None:
        from database.finans_evrak_kimligi import kimlik_getir
        from database.models.cari import Cari, CariIslem

        H = MuhasebeEntegrasyonService
        tahsilat = evrak_turu == "cari_tahsilat"
        with oturum_kullan(session) as s:
            kimlik = kimlik_getir(s, kimlik_id, evrak_turu)
            islem = s.get(CariIslem, kimlik.cari_islem_id) if kimlik and kimlik.cari_islem_id else None
            if islem is None:
                return None
            tutar = decimal(islem.alacak or 0) if tahsilat else (decimal(islem.borc or 0) or decimal(islem.alacak or 0))
            if tutar <= 0:
                return None
            fh, hareket_tutari = H._belge_finans_hesabi(
                s, islem.belge_no, ("CARİ TAHSİLAT",) if tahsilat else ("CARİ ÖDEME",))
            if hareket_tutari != tutar:
                raise ValueError(f"{islem.belge_no}: kasa/banka hareketi tutarı cari hareketle aynı değil.")
            para = H.finans_hesabi_karsiligi(fh, session=s)
            cari = H.cari_hesabi(s.get(Cari, islem.cari_id), session=s)
            no = islem.belge_no
            borc, alacak = (para, cari) if tahsilat else (cari, para)
            return H._olustur(
                kaynak_turu=KAYNAK_CARI_TAHSILAT if tahsilat else KAYNAK_CARI_ODEME,
                kaynak_id=kimlik_id,
                fis_tarihi=islem.tarih,
                fis_turu="Tahsil Fişi" if tahsilat else "Tediye Fişi",
                aciklama=f"Otomatik: Cari {'tahsilat' if tahsilat else 'ödeme'} {no}",
                belge_no=no,
                satirlar=[H._satir(borc, borc=tutar, aciklama=no), H._satir(alacak, alacak=tutar, aciklama=no)],
                yeniden=yeniden,
                session=s,
            )

    @staticmethod
    def cari_tahsilat_fisi(kimlik_id: int, *, yeniden: bool = False, session=None) -> int | None:
        """Kasa/banka borç / cari (türüne göre alıcılar veya satıcılar) alacak."""
        return MuhasebeEntegrasyonService._cari_islem_fisi(kimlik_id, "cari_tahsilat", yeniden=yeniden,
                                                           session=session)

    @staticmethod
    def cari_odeme_fisi(kimlik_id: int, *, yeniden: bool = False, session=None) -> int | None:
        """Cari (türüne göre satıcılar veya alıcılar) borç / kasa-banka alacak."""
        return MuhasebeEntegrasyonService._cari_islem_fisi(kimlik_id, "cari_odeme", yeniden=yeniden,
                                                           session=session)

    @staticmethod
    def cari_tahsilat_iptal(kimlik_id: int, neden: str = "", *, session=None) -> None:
        MuhasebeEntegrasyonService.iptal_kaynak(KAYNAK_CARI_TAHSILAT, kimlik_id, neden, session=session)

    @staticmethod
    def cari_odeme_iptal(kimlik_id: int, neden: str = "", *, session=None) -> None:
        MuhasebeEntegrasyonService.iptal_kaynak(KAYNAK_CARI_ODEME, kimlik_id, neden, session=session)

    # ---- Kasa makbuzu ----

    @staticmethod
    def kasa_makbuzu_fisi(makbuz_id: int, *, yeniden: bool = False, session=None) -> int | None:
        """Tahsilat: satır kasa/banka hesapları borç / cari alacak; ödeme tersine. Tek fiş, tüm satırlar."""
        from database.models.cari import Cari
        from database.models.finans import FinansHesabi, KasaMakbuzSatiri, KasaMakbuzu, PosValorKaydi

        H = MuhasebeEntegrasyonService
        with oturum_kullan(session) as s:
            m = s.get(KasaMakbuzu, int(makbuz_id))
            if m is None or (m.durum or "").upper() == "IPTAL":
                return None
            tahsilat = (m.makbuz_turu or "").upper() == "TAHSILAT"
            # Düzenlemede satırlar ilişki koleksiyonu temizlenip ayrıca eklendiği için aynı oturumda
            # m.satirlar boş kalır; satırlar her zaman tablodan okunur.
            s.flush()
            satirlar = list(s.scalars(select(KasaMakbuzSatiri).where(KasaMakbuzSatiri.makbuz_id == m.id)).all())
            parcalar: list[tuple[object, Decimal, str, object]] = []
            if satirlar:
                for st in sorted(satirlar, key=lambda x: x.sira_no or 0):
                    pv = s.get(PosValorKaydi, st.pos_valor_id) if st.pos_valor_id else None
                    parcalar.append((s.get(FinansHesabi, st.finans_hesap_id), decimal(st.tutar),
                                     st.odeme_sekli or "", pv))
            else:  # satır tablosu öncesi makbuz: tek hesap, makbuz tutarı
                parcalar.append((s.get(FinansHesabi, m.finans_hesap_id), decimal(m.tutar), "Makbuz", None))
            toplam = sum((p[1] for p in parcalar), SIFIR)
            if toplam <= 0:
                return None
            if toplam != decimal(m.tutar):
                raise ValueError(f"{m.belge_no}: satır toplamı makbuz tutarıyla aynı değil.")
            cari = H.cari_hesabi(s.get(Cari, m.cari_id), session=s)
            fis_satirlari = []
            for fh, tutar, sekil, pv in parcalar:
                acik = f"{m.belge_no} {sekil}".strip()
                if pv is not None:
                    if not tahsilat:
                        raise ValueError(f"{m.belge_no}: ödeme makbuzunda POS satırı olamaz.")
                    alacak, gider, net, komisyon = H._pos_hesaplari(pv, s)
                    if net + komisyon != tutar:
                        raise ValueError(f"{m.belge_no} {sekil}: POS brüt tutarı satır tutarıyla aynı değil.")
                    fis_satirlari.append(H._satir(alacak, borc=net, aciklama=f"{acik} valör alacağı"))
                    if gider is not None:
                        fis_satirlari.append(H._satir(gider, borc=komisyon, aciklama=f"{acik} komisyon"))
                    continue
                para = H.finans_hesabi_karsiligi(fh, session=s)
                fis_satirlari.append(H._satir(para, borc=tutar, aciklama=acik) if tahsilat
                                     else H._satir(para, alacak=tutar, aciklama=acik))
            fis_satirlari.append(H._satir(cari, alacak=toplam, aciklama=m.belge_no) if tahsilat
                                 else H._satir(cari, borc=toplam, aciklama=m.belge_no))
            return H._olustur(
                kaynak_turu=KAYNAK_KASA_MAKBUZU,
                kaynak_id=int(m.id),
                fis_tarihi=m.tarih,
                fis_turu="Tahsil Fişi" if tahsilat else "Tediye Fişi",
                aciklama=f"Otomatik: {'Tahsilat' if tahsilat else 'Ödeme'} makbuzu {m.makbuz_no or m.belge_no}",
                belge_no=m.belge_no,
                satirlar=fis_satirlari,
                yeniden=yeniden,
                session=s,
            )

    @staticmethod
    def kasa_makbuzu_iptal(makbuz_id: int, neden: str = "", *, session=None) -> None:
        MuhasebeEntegrasyonService.iptal_kaynak(KAYNAK_KASA_MAKBUZU, makbuz_id, neden, session=session)

    # ---- Kasa / banka virmanı ----

    VIRMAN_HAREKETLERI = {
        # önek: (çıkış hareket türü, giriş hareket türü)
        "KBY": ("KASADAN BANKAYA (KASA)", "KASADAN BANKAYA YATAN"),
        "BNC": ("BANKADAN NAKİT ÇEKİLEN", "BANKADAN NAKİT (KASA)"),
        "BVR": ("BANKA VİRMAN ÇIKIŞ", "BANKA VİRMAN GİRİŞ"),
    }

    @staticmethod
    def kasa_banka_virman_fisi(kimlik_id: int, *, yeniden: bool = False, session=None) -> int | None:
        """Giriş hesabı borç / çıkış hesabı alacak (aynı belge numaralı iki hareket tek fiş)."""
        from database.finans_evrak_kimligi import kimlik_getir

        H = MuhasebeEntegrasyonService
        with oturum_kullan(session) as s:
            kimlik = kimlik_getir(s, kimlik_id, "kasa_banka_virman")
            if kimlik is None:
                return None
            no = kimlik.belge_no
            turler = H.VIRMAN_HAREKETLERI.get(no.split("-", 1)[0])
            if turler is None:
                raise ValueError(f"{no}: virman türü tanınmadı.")
            try:
                cikis, c_tutar = H._belge_finans_hesabi(s, no, (turler[0],))
                giris, g_tutar = H._belge_finans_hesabi(s, no, (turler[1],))
            except ValueError:
                from database.models.finans import FinansHareketi

                if s.scalar(select(FinansHareketi.id).where(FinansHareketi.belge_no == no).limit(1)) is None:
                    return None  # hareketleri yok (silinmiş evrak)
                raise
            if c_tutar != g_tutar or c_tutar <= 0:
                raise ValueError(f"{no}: virman çıkış ve giriş tutarları farklı.")
            from database.models.finans import FinansHareketi

            tarih = s.scalar(select(FinansHareketi.tarih).where(FinansHareketi.belge_no == no).limit(1))
            borc = H.finans_hesabi_karsiligi(giris, session=s)
            alacak = H.finans_hesabi_karsiligi(cikis, session=s)
            acik = f"{no} {cikis.hesap_adi} → {giris.hesap_adi}"
            return H._olustur(
                kaynak_turu=KAYNAK_KASA_BANKA_VIRMAN,
                kaynak_id=kimlik_id,
                fis_tarihi=tarih,
                fis_turu="Mahsup Fişi",
                aciklama=f"Otomatik: Virman {no}",
                belge_no=no,
                satirlar=[H._satir(borc, borc=c_tutar, aciklama=acik), H._satir(alacak, alacak=c_tutar, aciklama=acik)],
                yeniden=yeniden,
                session=s,
            )

    # ---- Alınan / gönderilen havale ----

    @staticmethod
    def banka_havale_fisi(kimlik_id: int, *, yeniden: bool = False, session=None) -> int | None:
        """Alınan: banka borç / cari alacak. Gönderilen: cari borç / banka alacak."""
        from database.finans_evrak_kimligi import kimlik_getir
        from database.models.cari import Cari, CariIslem

        H = MuhasebeEntegrasyonService
        with oturum_kullan(session) as s:
            kimlik = kimlik_getir(s, kimlik_id, "banka_havale")
            if kimlik is None:
                return None
            no = kimlik.belge_no
            alinan = no.startswith("AHV")
            islemler = s.scalars(select(CariIslem).where(CariIslem.belge_no == no)).all()
            if not islemler:
                return None
            if len(islemler) != 1:
                raise ValueError(f"{no}: birden fazla cari hareket; fiş tarafı kesin belirlenemedi.")
            islem = islemler[0]
            fh, tutar = H._belge_finans_hesabi(s, no, ("ALINAN HAVALE",) if alinan else ("GÖNDERİLEN HAVALE",))
            if tutar != decimal(islem.alacak or 0) + decimal(islem.borc or 0):
                raise ValueError(f"{no}: banka hareketi tutarı cari hareketle aynı değil.")
            banka = H.finans_hesabi_karsiligi(fh, session=s)
            cari = H.cari_hesabi(s.get(Cari, islem.cari_id), session=s)
            borc, alacak = (banka, cari) if alinan else (cari, banka)
            return H._olustur(
                kaynak_turu=KAYNAK_BANKA_HAVALE,
                kaynak_id=kimlik_id,
                fis_tarihi=islem.tarih,
                fis_turu="Mahsup Fişi",
                aciklama=f"Otomatik: {'Alınan' if alinan else 'Gönderilen'} havale {no}",
                belge_no=no,
                satirlar=[H._satir(borc, borc=tutar, aciklama=no), H._satir(alacak, alacak=tutar, aciklama=no)],
                yeniden=yeniden,
                session=s,
            )

    # ---- Cari virman ----

    @staticmethod
    def cari_virman_fisi(kimlik_id: int, *, yeniden: bool = False, session=None) -> int | None:
        """Borçlanan (hedef) cari borç / alacaklanan (kaynak) cari alacak; hesaplar cari türüne göre."""
        from database.finans_evrak_kimligi import kimlik_getir
        from database.models.cari import Cari, CariIslem

        H = MuhasebeEntegrasyonService
        with oturum_kullan(session) as s:
            kimlik = kimlik_getir(s, kimlik_id, "cari_virman")
            if kimlik is None:
                return None
            no = kimlik.belge_no
            islemler = s.scalars(select(CariIslem).where(
                CariIslem.belge_no == no, CariIslem.islem_turu == "Cari Virman")).all()
            if not islemler:
                return None
            kaynak = [i for i in islemler if decimal(i.alacak or 0) > 0]
            hedef = [i for i in islemler if decimal(i.borc or 0) > 0]
            if len(kaynak) != 1 or len(hedef) != 1 or decimal(kaynak[0].alacak) != decimal(hedef[0].borc):
                raise ValueError(f"{no}: virmanın iki cari hareketi tutarlı değil; fiş oluşturulmadı.")
            tutar = decimal(kaynak[0].alacak)
            borc = H.cari_hesabi(s.get(Cari, hedef[0].cari_id), session=s)
            alacak = H.cari_hesabi(s.get(Cari, kaynak[0].cari_id), session=s)
            return H._olustur(
                kaynak_turu=KAYNAK_CARI_VIRMAN,
                kaynak_id=kimlik_id,
                fis_tarihi=kaynak[0].tarih,
                fis_turu="Mahsup Fişi",
                aciklama=f"Otomatik: Cari virman {no}",
                belge_no=no,
                satirlar=[H._satir(borc, borc=tutar, aciklama=no), H._satir(alacak, alacak=tutar, aciklama=no)],
                yeniden=yeniden,
                session=s,
            )

    @staticmethod
    def cari_virman_iptal(kimlik_id: int, neden: str = "", *, session=None) -> None:
        MuhasebeEntegrasyonService.iptal_kaynak(KAYNAK_CARI_VIRMAN, kimlik_id, neden, session=session)

    @staticmethod
    def cari_virman_makbuzu_fisi(virman_id: int, *, yeniden: bool = False, session=None) -> int | None:
        """Müşteri tahsilatı + tedarikçi ödemesi tek fiş: satıcılar borç / alıcılar alacak."""
        from database.models.cari import Cari
        from database.models.finans import CariVirmanMakbuzu

        H = MuhasebeEntegrasyonService
        with oturum_kullan(session) as s:
            k = s.get(CariVirmanMakbuzu, int(virman_id))
            if k is None or (k.durum or "").upper() == "IPTAL":
                return None
            tutar = decimal(k.tutar or 0)
            if tutar <= 0:
                return None
            borc = H.cari_hesabi(s.get(Cari, k.tedarikci_id), session=s)
            alacak = H.cari_hesabi(s.get(Cari, k.musteri_id), session=s)
            acik = k.makbuz_no or k.belge_no
            return H._olustur(
                kaynak_turu=KAYNAK_CARI_VIRMAN_MAKBUZU,
                kaynak_id=int(k.id),
                fis_tarihi=k.tarih,
                fis_turu="Mahsup Fişi",
                aciklama=f"Otomatik: Cari virman makbuzu {acik}",
                belge_no=k.belge_no,
                satirlar=[H._satir(borc, borc=tutar, aciklama=acik), H._satir(alacak, alacak=tutar, aciklama=acik)],
                yeniden=yeniden,
                session=s,
            )

    @staticmethod
    def cari_virman_makbuzu_iptal(virman_id: int, neden: str = "", *, session=None) -> None:
        MuhasebeEntegrasyonService.iptal_kaynak(KAYNAK_CARI_VIRMAN_MAKBUZU, virman_id, neden, session=session)


# Finans İşlem Ayarları'na bağlı evraklar: plan (``_olustur`` argümanları) ayrı üretilir; karar / muhasebe
# dışı kontrolleri fiş yazmadan aynı planı kullanır.
def _kur_farki_baska_fiste(s, k, hesap_idleri: set[int]) -> str | None:
    """Aynı kaynak/kapatma belgesinin başka (kur farkı kaynaklı olmayan) etkin fişinde kur farkı satırı var mı."""
    from sqlalchemy import exists
    from sqlalchemy.orm import aliased

    from database.models.genel_muhasebe import MuhasebeFisiSatiri

    belgeler = {b for b in (k.kaynak_belge_no, k.kapatma_belge_no) if b}
    if not belgeler or not hesap_idleri:
        return None
    asil = aliased(MuhasebeFisi)
    ters_kayit_mi = exists().where(asil.ters_fis_id == MuhasebeFisi.id)
    return s.scalar(
        select(MuhasebeFisi.fis_no)
        .join(MuhasebeFisiSatiri, MuhasebeFisiSatiri.fis_id == MuhasebeFisi.id)
        .where(MuhasebeFisi.firma_id == k.firma_id, MuhasebeFisi.durum != "İptal", ~ters_kayit_mi,
               MuhasebeFisi.belge_no.in_(belgeler),
               (MuhasebeFisi.kaynak_turu.is_(None)) | (MuhasebeFisi.kaynak_turu != KAYNAK_KUR_FARKI),
               MuhasebeFisiSatiri.hesap_id.in_(hesap_idleri))
        .limit(1)
    )


def _plan_kur_farki(s, kayit_id: int) -> dict | None:
    """Satış (alacak): gelir → Borç alıcılar / Alacak kur farkı geliri; gider → Borç kur farkı gideri /
    Alacak alıcılar. Alış (borç): gider → Borç kur farkı gideri / Alacak satıcılar; gelir → Borç satıcılar /
    Alacak kur farkı geliri. Kur/kaynak eksik kayıt ve başka fişte işlenmiş kur farkı incelemeye düşer."""
    from database.models.genel_muhasebe import KUR_FARKI_INCELEME, KUR_FARKI_IPTAL, KurFarkiKaydi

    H = MuhasebeEntegrasyonService
    k = s.get(KurFarkiKaydi, int(kayit_id))
    if k is None or k.durum == KUR_FARKI_IPTAL:
        return None
    if k.durum == KUR_FARKI_INCELEME:
        raise AyarEksik(f"Kur farkı hesaplanmadı: {k.aciklama or 'kur veya kaynak bilgisi eksik'}")
    from database.kur_farki_service import ALIS_IADE_KAPATMALARI

    if k.kapatma_turu in ALIS_IADE_KAPATMALARI:
        from database.muhasebe_finans_ayarlari import ALIS_IADE_KUR_FARKI, ayar_oku, eksik_secenek_mesaji

        secim = ayar_oku(ALIS_IADE_KUR_FARKI, session=s)
        if secim == "hesaplanmasin":
            raise MuhasebeDisiAyar("Alış iadesi kur farkı ayar gereği fişe yazılmaz (Finans İşlem Ayarları).")
        if secim != "gelir_gider":
            raise AyarEksik(eksik_secenek_mesaji("Alış iadesi kur farkı", "Alış iadesi"))
        from database.alis_iade_faturasi_service import AlisIadeFaturasiService
        from database.models.alis_iade_faturasi import AlisIadeFaturasi

        iade = s.scalar(select(AlisIadeFaturasi).where(AlisIadeFaturasi.iade_no == k.kapatma_belge_no))
        kdv_sorun = AlisIadeFaturasiService.kdv_kur_sorunu(s, iade) if iade is not None else None
        if kdv_sorun:
            raise AyarEksik(kdv_sorun)
    fark = decimal(k.kur_farki or 0)
    if fark == 0:
        return None
    cari = H._ayarli_hesap("musteriler" if k.yon == "SATIS" else "tedarikciler", s)
    kf = H._ayarli_hesap("kur_farki_geliri" if fark > 0 else "kur_farki_gideri", s)
    kf_hesaplari = {H._hesap(a, session=s)["id"] for a in ("kur_farki_geliri", "kur_farki_gideri")
                    if H.esleme_sorunu(a, session=s) is None}
    onceki = _kur_farki_baska_fiste(s, k, kf_hesaplari)
    if onceki:
        raise AyarEksik(f"{k.kaynak_belge_no} için kur farkı başka bir fişte ({onceki}) zaten kayıtlı; "
                        "mükerrer kayıt önlendi. Fişleri inceleyip gerekirse 'Muhasebe dışı bırak' ile işaretleyin.")
    tutar = abs(fark)
    acik = (f"Kur farkı {k.kaynak_belge_no} / {k.kapatma_belge_no or '-'}: {decimal(k.doviz_tutar)} {k.para_birimi} "
            f"× ({k.odeme_kuru} − {k.kaynak_kur})")[:200]
    if fark > 0:
        satirlar = [H._satir(cari, borc=tutar, aciklama=acik), H._satir(kf, alacak=tutar, aciklama=acik)]
    else:
        satirlar = [H._satir(kf, borc=tutar, aciklama=acik), H._satir(cari, alacak=tutar, aciklama=acik)]
    return {"kaynak_turu": KAYNAK_KUR_FARKI, "fis_tarihi": k.tarih, "fis_turu": "Mahsup Fişi",
            "aciklama": f"Otomatik: {acik}", "belge_no": k.kapatma_belge_no or k.kaynak_belge_no,
            "satirlar": satirlar}


PLANLAR: dict[str, str] = {
    "pos_tahsilat": "_plan_pos_tahsilat",
    "kart_odeme": "_plan_kart_odeme",
    "pos_valor_aktarimi": "_plan_pos_valor_aktarimi",
    "cek_senet": "_plan_cek_senet",
    "banka_kredi_kullandirim": "_plan_banka_kredi_kullandirim",
    "banka_kredi_odeme": "_plan_banka_kredi_odeme",
    "kur_farki": "_plan_kur_farki",
}


def muhasebe_hook(fn_name: str, *args, session=None, **kwargs):
    """Operasyon servislerinden çağrı.

    ``session`` ile çağrılırsa (evrak transaction'ı) firma/evrak türü ayarına göre karar verilir:
    otomatik yöntemde fiş aynı transaction'da yazılır, hata evrakı da geri alır; sonradan yöntemde
    evrak bekleyenler listesine alınır. ``session`` yoksa eski davranış (ayrı transaction, hata
    yutulur) korunur.
    """
    fn = getattr(MuhasebeEntegrasyonService, fn_name, None)
    if fn is None:
        return None
    if session is None:
        return MuhasebeEntegrasyonService._guvenli(fn, *args, **kwargs)
    from database.muhasebelestirme_service import MuhasebelestirmeService

    return MuhasebelestirmeService.olay(fn_name, args, kwargs, session=session)


__all__ = [
    "EVRAKLAR",
    "DESTEKLENMEYEN_EVRAKLAR",
    "HesapEslemeService",
    "HesapPlanService",
    "KAYNAK_EVRAK",
    "MuhasebeEntegrasyonService",
    "muhasebe_hook",
]
