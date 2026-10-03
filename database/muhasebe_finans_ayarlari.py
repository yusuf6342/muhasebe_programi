"""Finans işlemlerinin muhasebeleştirme seçenekleri (firma bazlı, kullanıcı seçer).

Hesaplar firma hesap eşleştirmesinde (``MuhasebeHesapEsleme``) tutulur ve bağlanırken fişe uygunluk
denetiminden geçer; burada yalnız seçenekler (çek/senet aşamasının fiş üretip üretmeyeceği, banka
kredisi fiş zamanı ve vade ayrımı) saklanır. Seçenek tanımsızsa ilgili evrak "İnceleme gerekiyor"
kalır; hiçbir seçenek veya hesap varsayılan olarak tahmin edilmez.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select

from database.models.genel_muhasebe import ESLEME_ANAHTARLARI, MuhasebeFinansAyari
from database.muhasebe_service import MuhasebeService, oturum_kullan
from database.session_manager import oturum

AYAR_YERI = "Ayarlar → Muhasebeleştirme Ayarları → Finans İşlem Ayarları"

EVET, HAYIR = "evet", "hayir"

# Çek/senet aşamaları: (kod, ad, fiş satırları açıklaması)
CEK_SENET_ASAMALARI: tuple[tuple[str, str, str], ...] = (
    ("KAYIT_ALINAN", "Portföye giriş (alınan çek/senet kaydı)",
     "Borç: portföy hesabı (çek/senet) — Alacak: müşteri cari hesabı"),
    ("BANKAYA_TAHSILE", "Bankaya tahsile verme",
     "Borç: tahsile verilen hesabı — Alacak: evrakın bulunduğu hesap (portföy)"),
    ("BANKAYA_TEMINATA", "Bankaya teminata verme",
     "Borç: teminata verilen hesabı — Alacak: evrakın bulunduğu hesap (portföy)"),
    ("CIRO", "Ciro (tedarikçiye / başka cariye)",
     "Borç: ciro edilen cari hesabı — Alacak: evrakın bulunduğu hesap"),
    ("TAHSIL", "Tahsil (tam / kısmi)",
     "Borç: kasa / banka — Alacak: evrakın bulunduğu hesap (portföy veya tahsile verilen)"),
    ("KARSILIKSIZ", "Karşılıksız / protesto",
     "Borç: müşteri cari hesabı (cari yeniden borçlanır) — Alacak: evrakın bulunduğu hesap"),
    ("IADE", "İade",
     "Alınan: Borç cari — Alacak bulunduğu hesap. Verilen: Borç verilen çek/borç senedi — Alacak cari"),
    ("KAYIT_VERILEN", "Verilen çek/senet kaydı",
     "Borç: tedarikçi cari hesabı — Alacak: verilen çekler / borç senetleri"),
    ("ODEME", "Verilen çek/senet ödemesi (tam / kısmi)",
     "Borç: verilen çekler / borç senetleri — Alacak: kasa / banka"),
)
CEK_SENET_ASAMA_ADI = {k: ad for k, ad, _ in CEK_SENET_ASAMALARI}

KREDI_FIS_ZAMANI = "kredi.fis_zamani"
KREDI_VADE_AYRIMI = "kredi.vade_ayrimi"
KREDI_FIS_ZAMANLARI = (
    ("kullandirim_ve_taksit", "Kullandırımda ve her taksit ödemesinde fiş"),
    ("yalniz_taksit", "Yalnız taksit ödemesinde fiş (kullandırım fişi yazılmaz)"),
)
KREDI_VADE_AYRIMLARI = (
    ("tumu_kisa", "Tüm anapara kısa vadeli kredi hesabında"),
    ("oniki_ay", "Vadesi kullandırımdan itibaren 12 ay içindeki taksitler kısa, sonrakiler uzun vadeli"),
)

ALIS_IADE_KUR_FARKI = "alis_iade.kur_farki"
ALIS_IADE_KUR_FARKI_SECENEKLERI = (
    ("gelir_gider", "Kur farkı ayrı fişle kur farkı geliri / gideri (646 / 656) hesabına yazılsın"),
    ("hesaplanmasin", "Kur farkı fişi yazılmasın (tedarikçi TL izlenir; bedel–maliyet farkının tamamı "
                      "alış iade maliyet farkı hesabında kalır)"),
)

ALIS_IADE_KDV_KURU = "alis_iade.kdv_kuru"
KDV_KURU_KAYNAK, KDV_KURU_IADE = "kaynak_kuru", "iade_kuru"
ALIS_IADE_KDV_KURU_SECENEKLERI = (
    (KDV_KURU_KAYNAK, "Kaynak alış kuru"),
    (KDV_KURU_IADE, "İade tarihi kuru"),
)
ALIS_IADE_KDV_KURU_ACIKLAMALARI = {
    KDV_KURU_KAYNAK: (
        "İade KDV'si, malın alındığı faturanın kuruyla TL'ye çevrilir. 191 İndirilecek KDV alışta indirilen "
        "tutar kadar (aynı kurla) ters çevrilir. Kur farkı yalnız KDV hariç tutar üzerinden hesaplanır; KDV "
        "kısmında kur farkı oluşmaz. Tedarikçiye yansıyan iade toplamı = matrah (iade kuru) + KDV (alış kuru). "
        "Kaynak alışı olmayan (devir/kaynaksız) satırlı iade bu yöntemle onaylanamaz."),
    KDV_KURU_IADE: (
        "İade KDV'si, iade belgesinin kuruyla TL'ye çevrilir. 191 İndirilecek KDV alıştakinden farklı (iade "
        "kuruyla) ters çevrilir. KDV dahil tutarın tamamı kur farkı hesabına girer; KDV'nin kur farkı da kur "
        "farkı kaydına (646/656) yansır."),
}
KDV_KURU_EKSIK_MESAJI = ("Dövizli alış iadesi KDV kuru yöntemi seçilmedi: Ayarlar → Muhasebeleştirme Ayarları → "
                         "Finans İşlem Ayarları → Alış iadesi")

SECENEKLER: dict[str, tuple[str, ...]] = {
    **{f"cek_senet.{k}": (EVET, HAYIR) for k, _ad, _a in CEK_SENET_ASAMALARI},
    KREDI_FIS_ZAMANI: tuple(k for k, _ in KREDI_FIS_ZAMANLARI),
    KREDI_VADE_AYRIMI: tuple(k for k, _ in KREDI_VADE_AYRIMLARI),
    ALIS_IADE_KUR_FARKI: tuple(k for k, _ in ALIS_IADE_KUR_FARKI_SECENEKLERI),
    ALIS_IADE_KDV_KURU: tuple(k for k, _ in ALIS_IADE_KDV_KURU_SECENEKLERI),
}

# Ekranda gösterilen hesap grupları (anahtarlar ESLEME_ANAHTARLARI'nda)
HESAP_GRUPLARI: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("KMH / POS / Şirket kartı", ("kmh_hesabi", "pos_valor_alacagi", "pos_komisyon_gideri", "sirket_kart_borcu")),
    ("Çek / Senet", ("cek_portfoy", "cek_tahsilde", "cek_teminatta", "senet_portfoy", "senet_tahsilde",
                     "senet_teminatta", "verilen_cekler", "borc_senetleri")),
    ("Banka kredisi", ("kredi_kisa_vadeli", "kredi_uzun_vadeli", "kredi_faiz_gideri", "kredi_bsmv_gideri",
                       "kredi_kkdf_gideri", "kredi_komisyon_gideri", "kredi_sigorta_gideri",
                       "kredi_dosya_masrafi", "kredi_gecikme_faizi", "kredi_diger_finansman")),
    ("Kasa (firma varsayılanı)", ("kasa",)),
    ("Kur farkı", ("kur_farki_geliri", "kur_farki_gideri")),
    ("Alış iadesi", ("alis_iade_maliyet_farki_olumlu", "alis_iade_maliyet_farki_olumsuz")),
)
MALIYET_FARKI_OLUMLU, MALIYET_FARKI_OLUMSUZ = "alis_iade_maliyet_farki_olumlu", "alis_iade_maliyet_farki_olumsuz"
MALIYET_FARKI_ACIKLAMALARI = {
    MALIYET_FARKI_OLUMLU: ("İade bedeli (KDV hariç) iade edilen malın FIFO stok maliyetinden büyükse fark bu "
                           "hesabın ALACAĞINA yazılır."),
    MALIYET_FARKI_OLUMSUZ: ("İade bedeli (KDV hariç) FIFO stok maliyetinden küçükse fark bu hesabın BORCUNA "
                            "yazılır."),
}
ESLEME_ADI = dict(ESLEME_ANAHTARLARI)

# Kart alt türü → kartta seçilebilecek muhasebe hesabının ana hesap sınıfı (TDHP). Kasa ve mevduat için
# hesap türü kesindir; KMH / POS / şirket kartı / krediler firmanın sınıflandırma tercihine bağlıdır
# (ör. KMH 300 veya 102), bu yüzden yalnız bilanço hesabı (1–4) olması istenir.
KART_HESAP_SINIFI: dict[str, tuple[str, ...]] = {
    "KASA": ("100",),
    "MEVDUAT": ("102",),
}
BILANCO_SINIFLARI = ("1", "2", "3", "4")
GIDER_SINIFLARI = ("6", "7")


def kart_alt_turu(fh) -> str:
    tur = (fh.hesap_turu or "").upper()
    if tur == "KASA":
        return "KASA"
    alt = (fh.alt_hesap_turu or "").strip().upper()
    if tur == "BANKA" and alt in ("", "MEVDUAT"):
        return "MEVDUAT"
    return alt or tur


def kart_hesap_uyumsuzlugu(fh, hesap_kodu: str, *, komisyon: bool = False) -> str | None:
    """Kart türü ile seçilen hesabın ana sınıfı uyumlu mu (uyumsuzsa neden)."""
    if komisyon:
        if kart_alt_turu(fh) != "POS":
            return "Komisyon gideri hesabı yalnız POS hesabında seçilir."
        return None if hesap_kodu[:1] in GIDER_SINIFLARI else (
            f"{hesap_kodu}: komisyon gideri 6 veya 7 ile başlayan gider hesabı olmalı.")
    alt = kart_alt_turu(fh)
    kesin = KART_HESAP_SINIFI.get(alt)
    if kesin:
        return None if hesap_kodu.split(".")[0] in kesin else (
            f"{hesap_kodu}: {alt.lower()} kartı yalnız {'/'.join(kesin)} altındaki hesaba bağlanır.")
    return None if hesap_kodu[:1] in BILANCO_SINIFLARI else (
        f"{hesap_kodu}: kart hesabı bilanço hesabı (1–4 ile başlayan) olmalı.")


def cek_senet_anahtari(asama: str) -> str:
    return f"cek_senet.{asama}"


def ayar_oku(anahtar: str, *, session=None) -> str | None:
    with oturum_kullan(session) as s:
        firma_id = MuhasebeService.yerel_firma_id(s)
        return s.scalar(select(MuhasebeFinansAyari.deger).where(
            MuhasebeFinansAyari.firma_id == firma_id, MuhasebeFinansAyari.anahtar == anahtar))


def ayarlar_oku(*, session=None) -> dict[str, str]:
    with oturum_kullan(session) as s:
        firma_id = MuhasebeService.yerel_firma_id(s)
        return dict(s.execute(select(MuhasebeFinansAyari.anahtar, MuhasebeFinansAyari.deger).where(
            MuhasebeFinansAyari.firma_id == firma_id)).all())


def eksik_secenek_mesaji(ad: str, bolum: str) -> str:
    return f"{ad} için muhasebe seçeneği tanımlı değil. Tanımlamak için: {AYAR_YERI} → {bolum}."


def eksik_hesap_mesaji(anahtar: str) -> str:
    return (f"'{ESLEME_ADI.get(anahtar, anahtar)}' hesabı bağlı değil veya fişe uygun değil. "
            f"Tanımlamak için: {AYAR_YERI} (veya Genel Muhasebe → Hesap Eşleştirmeleri, anahtar: {anahtar}).")


def kaydet(degerler: dict[str, str | None]) -> dict[str, str]:
    """Seçili firmanın seçeneklerini yazar; ``None``/boş değer seçeneği tanımsız yapar (satır silinir)."""
    from database.access import yazma_zorunlu
    from database.database import get_session

    yazma_zorunlu("muhasebelestirme_ayar", mesaj="Muhasebeleştirme ayarlarını değiştirme yetkiniz yok.")
    for anahtar, deger in degerler.items():
        if anahtar not in SECENEKLER:
            raise ValueError(f"Bilinmeyen finans ayarı: {anahtar}")
        if deger not in (None, "") and deger not in SECENEKLER[anahtar]:
            raise ValueError(f"{anahtar}: geçersiz değer ({deger})")
    with get_session() as s:
        from database.muhasebelestirme_service import MuhasebelestirmeService

        MuhasebelestirmeService.hazirla(s)
        firma_id = MuhasebeService.yerel_firma_id(s)
        mevcut = {a.anahtar: a for a in s.scalars(select(MuhasebeFinansAyari).where(
            MuhasebeFinansAyari.firma_id == firma_id))}
        once = {k: a.deger for k, a in mevcut.items()}
        for anahtar, deger in degerler.items():
            satir = mevcut.get(anahtar)
            if deger in (None, ""):
                if satir is not None:
                    s.delete(satir)
                continue
            if satir is None:
                satir = MuhasebeFinansAyari(firma_id=firma_id, anahtar=anahtar, deger=deger)
                s.add(satir)
            satir.deger = deger
            satir.guncelleyen_kullanici_id = oturum.user_id
            satir.guncelleyen_kullanici_adi = oturum.kullanici_adi or oturum.ad_soyad
            satir.guncelleme_tarihi = datetime.now()
        s.flush()
        sonra = dict(s.execute(select(MuhasebeFinansAyari.anahtar, MuhasebeFinansAyari.deger).where(
            MuhasebeFinansAyari.firma_id == firma_id)).all())
        MuhasebeService._gecmis(s, kayit_turu="muhasebe_finans_ayari", kayit_id=0, islem="ayar_degistir",
                                detay=f"önce={once} → sonra={sonra}")
        return sonra


def ekran_verisi() -> dict:
    """Finans İşlem Ayarları ekranı: seçenekler, hesap grupları (bağlı hesap + fişe uygunluk) ve aday hesaplar."""
    from database.access import yetki_zorunlu
    from database.database import get_session
    from database.models.genel_muhasebe import HesapPlani, MuhasebeHesapEsleme
    from database.muhasebe_entegrasyon import hesap_uygunluk_sorunu

    yetki_zorunlu("muhasebe_goruntuleme", "muhasebelestirme_ayar", "goruntuleme")
    MuhasebeService.esleme_sablonlarini_doldur()
    with get_session() as s:
        from database.muhasebelestirme_service import MuhasebelestirmeService

        MuhasebelestirmeService.hazirla(s)
        firma_id = MuhasebeService.yerel_firma_id(s)
        eslemeler = {e.anahtar: e for e in s.scalars(select(MuhasebeHesapEsleme).where(
            MuhasebeHesapEsleme.firma_id == firma_id))}
        gruplar = []
        for baslik, anahtarlar in HESAP_GRUPLARI:
            satirlar = []
            for a in anahtarlar:
                e = eslemeler.get(a)
                h = s.get(HesapPlani, e.hesap_id) if e is not None and e.hesap_id else None
                sorun = hesap_uygunluk_sorunu(s, h, firma_id) if h is not None else "hesap bağlı değil"
                satirlar.append({"anahtar": a, "ad": ESLEME_ADI.get(a, a),
                                 "hesap_kodu": h.hesap_kodu if h else None, "hesap_adi": h.hesap_adi if h else None,
                                 "sorun": sorun})
            gruplar.append({"baslik": baslik, "satirlar": satirlar})
        adaylar = [
            {"id": h.id, "kod": h.hesap_kodu, "ad": h.hesap_adi}
            for h in s.scalars(select(HesapPlani).where(
                HesapPlani.firma_id == firma_id, HesapPlani.aktif.is_(True)).order_by(HesapPlani.hesap_kodu))
            if hesap_uygunluk_sorunu(s, h, firma_id) is None
        ]
        return {"secenekler": ayarlar_oku(session=s), "gruplar": gruplar, "adaylar": adaylar}


def _hesap_ozet(s, hid):
    from database.models.genel_muhasebe import HesapPlani

    h = s.get(HesapPlani, int(hid)) if hid else None
    return h


def kart_hesaplari(*, banka_karti_id: int | None = None, session=None) -> list[dict]:
    """Kasa/banka kartlarının muhasebe karşılığı: kart hesabı, yoksa firma varsayılanı, eksikse neden."""
    from database.models.finans import FinansHareketi, FinansHesabi
    from database.muhasebe_entegrasyon import MuhasebeEntegrasyonService as H
    from sqlalchemy import func

    with oturum_kullan(session) as s:
        q = select(FinansHesabi).where(FinansHesabi.aktif.is_(True))
        if banka_karti_id is not None:
            q = q.where(FinansHesabi.banka_karti_id == int(banka_karti_id))
        hareket = dict(s.execute(select(FinansHareketi.hesap_id, func.count()).group_by(
            FinansHareketi.hesap_id)).all())
        sonuc = []
        for fh in s.scalars(q.order_by(FinansHesabi.banka_karti_id, FinansHesabi.id)):
            h = _hesap_ozet(s, fh.muhasebe_hesap_id)
            k = _hesap_ozet(s, fh.muhasebe_komisyon_hesap_id)
            neden = H._finans_hesabi_destek_disi(fh, session=s)
            if neden is None and not fh.muhasebe_hesap_id:
                anahtar = H.finans_hesabi_anahtari(fh)
                durum = f"Firma varsayılanı ({anahtar}: {H._hesap(anahtar, session=s)['kod']})"
            elif neden is None:
                durum = "Kart hesabı"
            else:
                durum = "İnceleme gerekiyor"
            sonuc.append({
                "id": fh.id, "hesap_adi": fh.hesap_adi, "alt_tur": kart_alt_turu(fh),
                "banka_karti_id": fh.banka_karti_id, "hareket": int(hareket.get(fh.id, 0)),
                "muhasebe_hesap_id": fh.muhasebe_hesap_id,
                "muhasebe_hesap": f"{h.hesap_kodu} — {h.hesap_adi}" if h else None,
                "komisyon_hesap_id": fh.muhasebe_komisyon_hesap_id,
                "komisyon_hesap": f"{k.hesap_kodu} — {k.hesap_adi}" if k else None,
                "durum": durum, "neden": neden,
            })
        return sonuc


def kart_hesabi_kaydet(finans_hesap_id: int, muhasebe_hesap_id: int | None, *,
                       komisyon_hesap_id: int | None | bool = False) -> dict:
    """Kartın muhasebe hesabını (ve POS ise komisyon gideri hesabını) yazar; değişiklik denetim kaydına girer.

    ``komisyon_hesap_id=False`` komisyon hesabına dokunmaz; ``None`` kaldırır.
    """
    from database.access import yazma_zorunlu
    from database.database import get_session
    from database.models.finans import FinansHesabi
    from database.muhasebe_entegrasyon import hesap_uygunluk_sorunu

    yazma_zorunlu("muhasebelestirme_ayar", mesaj="Muhasebeleştirme ayarlarını değiştirme yetkiniz yok.")
    with get_session() as s:
        firma_id = MuhasebeService.yerel_firma_id(s)
        fh = s.get(FinansHesabi, int(finans_hesap_id))
        if fh is None:
            raise ValueError("Kasa/banka kartı bulunamadı.")
        degisen = []
        alanlar = [("muhasebe_hesap_id", muhasebe_hesap_id, False)]
        if komisyon_hesap_id is not False:
            alanlar.append(("muhasebe_komisyon_hesap_id", komisyon_hesap_id, True))
        for alan, yeni_id, komisyon in alanlar:
            yeni = _hesap_ozet(s, yeni_id)
            if yeni_id and yeni is None:
                raise ValueError("Hesap bulunamadı.")
            if yeni is not None:
                sorun = hesap_uygunluk_sorunu(s, yeni, firma_id) or kart_hesap_uyumsuzlugu(
                    fh, yeni.hesap_kodu, komisyon=komisyon)
                if sorun:
                    raise ValueError(f"'{fh.hesap_adi}' için hesap seçilemez: {sorun}")
            onceki = _hesap_ozet(s, getattr(fh, alan))
            if (onceki.id if onceki else None) == (yeni.id if yeni else None):
                continue
            setattr(fh, alan, yeni.id if yeni else None)
            degisen.append(alan)
            MuhasebeService._gecmis(
                s, kayit_turu="finans_kart_hesabi", kayit_id=int(fh.id), islem="bagla" if yeni else "kaldir",
                detay=(f"{fh.hesap_adi} [{alan}]: {onceki.hesap_kodu if onceki else '-'} → "
                       f"{yeni.hesap_kodu if yeni else '-'}"))
        s.flush()
        return {"id": fh.id, "degisen": degisen}


def finans_muhasebe_mutabakati(*, session=None) -> list[dict]:
    """Muhasebe hesabı başına: bağlı kartların finans bakiyesi ↔ hesabın muhasebe bakiyesi (borç − alacak).

    Açılış bakiyesi ve genel muhasebe öncesi / muhasebeleştirilmemiş hareketler farkı açıklar; fark
    kendiliğinden düzeltilmez.
    """
    from database.finans_service import FinansService
    from database.models.finans import FinansHesabi
    from database.models.genel_muhasebe import HesapPlani
    from database.muhasebe_entegrasyon import MuhasebeEntegrasyonService as H

    with oturum_kullan(session) as s:
        gruplar: dict[int, dict] = {}
        for fh in s.scalars(select(FinansHesabi).where(FinansHesabi.aktif.is_(True))):
            try:
                hesap = H._finans_karsiligi_ayarli(fh, s)
            except ValueError:
                continue
            g = gruplar.setdefault(hesap["id"], {"hesap_kodu": hesap["kod"], "hesap_adi": hesap["ad"],
                                                 "kartlar": [], "finans_bakiye": Decimal("0")})
            g["kartlar"].append(fh.hesap_adi)
            g["finans_bakiye"] += FinansService.bakiye(fh)
        for hid, g in gruplar.items():
            h = s.get(HesapPlani, hid)
            g["muhasebe_bakiye"] = Decimal(str(h.borc_toplam or 0)) - Decimal(str(h.alacak_toplam or 0))
            g["fark"] = g["finans_bakiye"] - g["muhasebe_bakiye"]
        return sorted(gruplar.values(), key=lambda g: g["hesap_kodu"])


def maliyet_farki_anahtari(fark) -> str | None:
    """Bedel − maliyet farkının işaretine göre eşleme anahtarı (fark sıfırsa None: hesap aranmaz)."""
    if not fark:
        return None
    return MALIYET_FARKI_OLUMLU if fark > 0 else MALIYET_FARKI_OLUMSUZ


__all__ = [
    "ALIS_IADE_KDV_KURU",
    "ALIS_IADE_KDV_KURU_SECENEKLERI",
    "ALIS_IADE_KUR_FARKI",
    "ALIS_IADE_KUR_FARKI_SECENEKLERI",
    "maliyet_farki_anahtari",
    "finans_muhasebe_mutabakati",
    "kart_hesaplari",
    "kart_hesabi_kaydet",
    "kart_hesap_uyumsuzlugu",
    "AYAR_YERI",
    "CEK_SENET_ASAMALARI",
    "HESAP_GRUPLARI",
    "KREDI_FIS_ZAMANI",
    "KREDI_VADE_AYRIMI",
    "ayar_oku",
    "ayarlar_oku",
    "cek_senet_anahtari",
    "ekran_verisi",
    "kaydet",
]
