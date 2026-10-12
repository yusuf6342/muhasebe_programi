"""Stoklar → Raporlar ekranları (ortak rapor çerçevesi: filtre, tablo, sütun seçimi, Excel ve yazdırma)."""

from __future__ import annotations

from datetime import date, timedelta
from tkinter import messagebox
from typing import Callable

from satin_alma_rapor_ui import Filtre, Kolon, RaporEkrani, Tablo, bicimle


def _yetki_var() -> bool:
    try:
        from database.access import yetki_var

        return bool(yetki_var("stok_goruntuleme", "stok_duzenleme"))
    except Exception:  # noqa: BLE001
        return True


def _ust(app, baslik, alt):
    from stoklar_ui import _liste_ust, stoklar_raporlar_hub_goster

    return _liste_ust(app, baslik, alt, lambda: stoklar_raporlar_hub_goster(app), geri_metin="← Stok Raporları")


def _ekran(app, baslik: str, kur: Callable[[], RaporEkrani]) -> RaporEkrani | None:
    if not _yetki_var():
        messagebox.showwarning(baslik, "Stok raporlarını görüntüleme yetkiniz yok.", parent=app)
        return None
    ekran = kur()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: _ekran(app, baslik, kur))
    return ekran


def _depo_secenek() -> list[tuple[str, str]]:
    from database.stok_rapor_service import depo_adlari

    try:
        return [("", "(Tüm depolar)")] + [(a, a) for a in depo_adlari()]
    except Exception:  # noqa: BLE001
        return [("", "(Tüm depolar)")]


def _grup_secenek() -> list[tuple[str, str]]:
    from database.stok_rapor_service import grup_secenekleri

    try:
        return [("", "(Tüm gruplar)")] + grup_secenekleri()
    except Exception:  # noqa: BLE001
        return [("", "(Tüm gruplar)")]


def _ortak_filtreler() -> list[Filtre]:
    return [Filtre("combo", "depo", "Depo", "", _depo_secenek()),
            Filtre("combo", "grup_id", "Stok grubu", "", _grup_secenek()),
            Filtre("metin", "arama", "Ürün kodu / adı / barkod")]


def urun_ekstresi_ac(app, r: dict) -> None:
    """Satırdaki ürünün fiyatlı stok ekstresi (kaynak evraklara buradan geçilir)."""
    if r.get("_sabit"):
        return
    sid = r.get("stok_id")
    if not sid:
        from database.database import get_session
        from database.models.stok import StokKarti
        from sqlalchemy import select

        kod = str(r.get("urun_kodu") or r.get("urun") or "").split(" — ")[0].strip()
        if not kod:
            return
        with get_session() as s:
            sid = s.scalar(select(StokKarti.id).where(StokKarti.stok_kodu == kod))
    if not sid:
        return
    from fiyatli_stok_ekstresi_ui import FiyatliStokEkstreDialog

    FiyatliStokEkstreDialog(app, stok_id=int(sid))


def _durum_etiketi(r: dict) -> str | None:
    metin = str(r.get("durum") or r.get("aciklama") or "")
    if r.get("_sabit"):
        return None
    if metin.startswith(("Negatif", "Eksik", "Uyumsuz", "Düzeltme hareketi yok")) or "Negatif" in metin:
        return "uyari"
    if metin.startswith(("Kısmi", "Sıfır", "Minimum")):
        return "soluk"
    return None


# ---------------------------------------------------------------------------
# Stok durumu / kullanılabilir miktar
# ---------------------------------------------------------------------------

def stok_durumu_goster(app, **kw) -> RaporEkrani | None:
    from database import stok_rapor_service as srv

    miktar = [Kolon("mevcut", "Mevcut", 80, "miktar"), Kolon("rezervasyon", "Rezervasyon", 80, "miktar"),
              Kolon("bekleyen_satis", "Bekleyen Satış Sip.", 105, "miktar"),
              Kolon("kullanilabilir", "Kullanılabilir", 90, "miktar"),
              Kolon("bekleyen_alis", "Bekleyen Alış Sip.", 105, "miktar"),
              Kolon("ongorulen", "Öngörülen (alış gelince)", 130, "miktar"),
              Kolon("yoldaki", "Yoldaki (transfer)", 100, "miktar"), Kolon("deger", "Stok Değeri (FIFO)", 110, "para")]

    def kur():
        return RaporEkrani(
            app, baslik="STOK DURUMU / KULLANILABİLİR MİKTAR",
            alt="Depo bazında mevcut, rezervasyon, bekleyen sipariş ve kullanılabilir miktar",
            filtreler=[*_ortak_filtreler(), Filtre("check", "sifir_dahil", "Sıfır bakiyeleri de göster", False)],
            tablolar=[
                Tablo("satirlar", "Depo Bazında", [
                    Kolon("urun_kodu", "Ürün Kodu", 100), Kolon("urun_adi", "Ürün Adı", 210),
                    Kolon("birim", "Birim", 55), Kolon("depo", "Depo", 110), *miktar,
                    Kolon("aciklama", "Açıklama", 240)],
                    cift_tik=lambda r: urun_ekstresi_ac(app, r), etiket=lambda r: "uyari" if r.get("aciklama") else None),
                Tablo("urunler", "Ürün Bazında Firma Toplamı", [
                    Kolon("urun_kodu", "Ürün Kodu", 100), Kolon("urun_adi", "Ürün Adı", 210),
                    Kolon("birim", "Birim", 55), Kolon("depo_sayisi", "Depo Sayısı", 75, "gun"), *miktar],
                    cift_tik=lambda r: urun_ekstresi_ac(app, r),
                    etiket=lambda r: "uyari" if (r.get("kullanilabilir") or 0) < 0 else None),
                Tablo("depolar", "Depo Toplamları", [
                    Kolon("depo", "Depo", 140), Kolon("urun_sayisi", "Ürün", 70, "gun"),
                    Kolon("negatif", "Negatif Stoklu", 95, "gun"),
                    Kolon("kullanilabilir_eksi", "Kullanılabilir Eksi", 110, "gun"),
                    Kolon("bekleyen_alis_urun", "Bekleyen Alışlı Ürün", 120, "gun"),
                    Kolon("bekleyen_satis_urun", "Bekleyen Satışlı Ürün", 125, "gun"),
                    Kolon("deger", "Stok Değeri (FIFO)", 120, "para")]),
            ],
            hesapla=lambda f: srv.stok_durumu(depo=f.get("depo") or None, arama=f.get("arama") or "",
                                              grup_id=f.get("grup_id") or None, sifir_dahil=f.get("sifir_dahil")),
            toplam_metni=lambda s: (f"Depo satırı: {len(s.get('satirlar', []))}   Ürün: {len(s.get('urunler', []))}   "
                                    f"Negatif: {sum(1 for r in s.get('satirlar', []) if (r.get('mevcut') or 0) < 0)}"),
            ust=_ust, hafiza="stok_durumu", **kw)
    return _ekran(app, "Stok Durumu", kur)


# ---------------------------------------------------------------------------
# Değerleme / envanter
# ---------------------------------------------------------------------------

def degerleme_goster(app, sekme: str | None = None, **kw) -> RaporEkrani | None:
    from database import stok_rapor_service as srv

    ozet_kolon = [Kolon("satir", "Satır", 55, "gun"), Kolon("miktar", "Miktar", 85, "miktar"),
                  Kolon("toplam_maliyet", "Toplam Maliyet", 120, "para"), Kolon("durum", "Durum", 200),
                  Kolon("satis_degeri", "Satış Fiyatıyla Değer (maliyet değil)", 190, "para")]

    def kur():
        ekran = RaporEkrani(
            app, baslik="STOK DEĞERLEME / ENVANTER",
            alt="Seçilen tarihteki miktar ve maliyet; eksik maliyet ve negatif stok ayrı",
            filtreler=[Filtre("tarih", "tarih", "Değerleme tarihi", date.today()),
                       Filtre("combo", "yontem", "Yöntem", srv.FIFO, srv.degerleme_yontemleri()),
                       *_ortak_filtreler(),
                       Filtre("check", "satis_fiyati", "Satış fiyatıyla değeri ayrıca göster", False)],
            tablolar=[
                Tablo("satirlar", "Ürün × Depo", [
                    Kolon("urun_kodu", "Ürün Kodu", 100), Kolon("urun_adi", "Ürün Adı", 200),
                    Kolon("birim", "Birim", 55), Kolon("depo", "Depo", 100), Kolon("ana_grup", "Ana Grup", 110),
                    Kolon("tali_grup", "Tali Grup", 110), Kolon("alt_grup", "Alt Grup", 110),
                    Kolon("miktar", "Miktar", 80, "miktar"), Kolon("birim_maliyet", "Birim Maliyet", 100, "fiyat"),
                    Kolon("toplam_maliyet", "Toplam Maliyet", 115, "para"), Kolon("yontem", "Yöntem", 200),
                    Kolon("maliyet_kaynagi", "Maliyet Kaynağı", 220), Kolon("durum", "Durum", 200),
                    Kolon("pasif", "Kart", 70), Kolon("satis_fiyati", "Satış Fiyatı", 95, "fiyat"),
                    Kolon("satis_degeri", "Satış Fiyatıyla Değer (maliyet değil)", 190, "para")],
                    cift_tik=lambda r: urun_ekstresi_ac(app, r), etiket=_durum_etiketi),
                Tablo("urunler", "Ürün Özeti", [Kolon("urun_kodu", "Ürün Kodu", 100),
                                                Kolon("urun_adi", "Ürün Adı", 210), Kolon("birim", "Birim", 55),
                                                *ozet_kolon], cift_tik=lambda r: urun_ekstresi_ac(app, r)),
                Tablo("depolar", "Depo Özeti", [Kolon("depo", "Depo", 140), *ozet_kolon]),
                Tablo("gruplar", "Grup Özeti (Ana / Tali / Alt)", [
                    Kolon("ana_grup", "Ana Grup", 140), Kolon("tali_grup", "Tali Grup", 140),
                    Kolon("alt_grup", "Alt Grup", 140), *ozet_kolon]),
                Tablo("sorunlu", "Eksik / Negatif (toplama girmeyen)", [
                    Kolon("urun_kodu", "Ürün Kodu", 100), Kolon("urun_adi", "Ürün Adı", 200),
                    Kolon("depo", "Depo", 100), Kolon("miktar", "Miktar", 80, "miktar"),
                    Kolon("durum", "Durum", 230), Kolon("maliyet_kaynagi", "Açıklama", 280)],
                    cift_tik=lambda r: urun_ekstresi_ac(app, r), etiket=_durum_etiketi),
            ],
            hesapla=lambda f: srv.degerleme(tarih=f.get("tarih"), yontem=f.get("yontem") or srv.FIFO,
                                            depo=f.get("depo") or None, arama=f.get("arama") or "",
                                            grup_id=f.get("grup_id") or None, satis_fiyati=f.get("satis_fiyati")),
            toplam_metni=lambda s: (
                f"Toplam maliyet: {bicimle(s.get('toplam_maliyet'), 'para') or '— (yetki yok)'} TL   "
                f"Eksik maliyetli satır: {s.get('eksik_satir', 0)}   Negatif stok satırı: {s.get('negatif_satir', 0)}"),
            ust=_ust, hafiza="stok_degerleme", **kw)
        if sekme and ekran.defter is not None:
            anahtarlar = [t.anahtar for t in ekran.tablolar_tanim]
            if sekme in anahtarlar:
                ekran.defter.select(anahtarlar.index(sekme))
        return ekran
    return _ekran(app, "Stok Değerleme", kur)


# ---------------------------------------------------------------------------
# Kritik / tükenen
# ---------------------------------------------------------------------------

def kritik_tukenen_goster(app, **kw) -> RaporEkrani | None:
    from database import stok_rapor_service as srv

    temel = [Kolon("urun_kodu", "Ürün Kodu", 100), Kolon("urun_adi", "Ürün Adı", 200), Kolon("birim", "Birim", 55)]
    olcu = [Kolon("mevcut", "Mevcut", 75, "miktar"), Kolon("kullanilabilir", "Kullanılabilir", 85, "miktar"),
            Kolon("donem_satis", "Dönem Net Satış", 95, "miktar"), Kolon("gunluk_hiz", "Günlük Hız", 75, "fiyat"),
            Kolon("son_alis", "Son Alış", 80, "tarih"), Kolon("son_satis", "Son Satış", 80, "tarih"),
            Kolon("son_tedarikci", "Son Tedarikçi", 150), Kolon("bekleyen_alis", "Bekleyen Alış", 85, "miktar")]

    def kur():
        return RaporEkrani(
            app, baslik="KRİTİK VE TÜKENEN STOK",
            alt="Minimum altı, sıfır ve negatif stok ayrı durumlar; satış hızı ve stoksuz kalma geçmişi",
            filtreler=[Filtre("sayi", "donem_gun", "Satış hızı dönemi (gün)", 90), *_ortak_filtreler()],
            tablolar=[
                Tablo("satirlar", "Kritik / Tükenen", [
                    *temel, Kolon("durum", "Durum", 170), *olcu[:2], Kolon("minimum", "Minimum", 70, "miktar"),
                    Kolon("minimum_kaynagi", "Minimum Kaynağı", 100), *olcu[2:], Kolon("aciklama", "Açıklama", 200)],
                    cift_tik=lambda r: urun_ekstresi_ac(app, r), etiket=_durum_etiketi),
                Tablo("minimumsuz", "Minimum Tanımsız", [*temel, Kolon("durum", "Durum", 170), *olcu],
                      cift_tik=lambda r: urun_ekstresi_ac(app, r)),
                Tablo("gecmis", "Stoksuz Kalma Geçmişi", [
                    *temel[:2], Kolon("bas", "Stok Bitti", 85, "tarih"), Kolon("bit", "Yeniden Girdi", 90, "tarih"),
                    Kolon("gun", "Stoksuz Gün", 80, "gun"), Kolon("durum", "Durum", 140),
                    Kolon("son_satis", "Son Satış", 85, "tarih")], cift_tik=lambda r: urun_ekstresi_ac(app, r)),
            ],
            hesapla=lambda f: srv.kritik_tukenen(donem_gun=f.get("donem_gun") or 90, depo=f.get("depo") or None,
                                                 arama=f.get("arama") or "", grup_id=f.get("grup_id") or None),
            toplam_metni=lambda s: "   ".join(f"{k}: {v}" for k, v in sorted((s.get("sayac") or {}).items())),
            ust=_ust, hafiza="stok_kritik", **kw)
    return _ekran(app, "Kritik ve Tükenen Stok", kur)


# ---------------------------------------------------------------------------
# Yavaş / satılmayan
# ---------------------------------------------------------------------------

def yavas_satilmayan_goster(app, **kw) -> RaporEkrani | None:
    from database import stok_rapor_service as srv

    def kur():
        return RaporEkrani(
            app, baslik="YAVAŞ HAREKET EDEN / SATILMAYAN STOK",
            alt="Stokta bekleyen, uzun süredir satılmayan veya hiç satılmamış ürünler",
            filtreler=[Filtre("tarih", "bas", "Satış dönemi başı", date.today() - timedelta(days=364)),
                       Filtre("tarih", "bit", "Bitiş", date.today()),
                       Filtre("sayi", "esik_gun", "Satışsız gün eşiği", 90),
                       Filtre("sayi", "yeni_gun", "Yeni alım sayılacak gün", 30),
                       Filtre("combo", "tur", "Göster", "tumu",
                              [("tumu", "Tümü"), ("yavas", "Yavaş satılanlar"),
                               ("hic_satilmayan", "Hiç satılmamış (uzun süredir)"), ("yeni", "Yeni alım")]),
                       *_ortak_filtreler()],
            tablolar=[Tablo("satirlar", "Yavaş / Satılmayan", [
                Kolon("urun_kodu", "Ürün Kodu", 100), Kolon("urun_adi", "Ürün Adı", 200), Kolon("birim", "Birim", 55),
                Kolon("ana_grup", "Ana Grup", 110), Kolon("miktar", "Miktar", 75, "miktar"),
                Kolon("maliyet_degeri", "Maliyet Değeri", 105, "para"), Kolon("son_satis", "Son Satış", 85, "tarih"),
                Kolon("son_satis_gun", "Son Satıştan Beri (gün)", 125, "gun"),
                Kolon("donem_net_satis", "Dönem Net Satış (TL)", 120, "para"),
                Kolon("donem_net_miktar", "Dönem Net Miktar", 100, "miktar"),
                Kolon("ilk_giris", "İlk Giriş", 85, "tarih"), Kolon("son_giris", "Son Giriş", 85, "tarih"),
                Kolon("sinif", "Durum", 300)],
                cift_tik=lambda r: urun_ekstresi_ac(app, r),
                etiket=lambda r: "soluk" if r.get("tur") == "yeni" else ("uyari" if r.get("tur") == "hic_satilmayan"
                                                                        else None))],
            hesapla=lambda f: srv.yavas_satilmayan(bas=f["bas"] or date.today() - timedelta(days=364),
                                                   bit=f["bit"] or date.today(), esik_gun=f.get("esik_gun") or 0,
                                                   yeni_gun=f.get("yeni_gun") or 0, tur=f.get("tur") or "tumu",
                                                   depo=f.get("depo") or None, arama=f.get("arama") or "",
                                                   grup_id=f.get("grup_id") or None),
            toplam_metni=lambda s: (f"Ürün: {len(s.get('satirlar', []))}   Bekleyen maliyet değeri: "
                                    f"{bicimle(s.get('toplam_deger'), 'para') or '— (yetki yok)'} TL"),
            ust=_ust, hafiza="stok_yavas", **kw)
    return _ekran(app, "Yavaş / Satılmayan Stok", kur)


# ---------------------------------------------------------------------------
# Yaşlandırma
# ---------------------------------------------------------------------------

def yaslandirma_goster(app, **kw) -> RaporEkrani | None:
    from database import stok_rapor_service as srv

    kovalar = []
    for *_x, k, etiket in srv.YAS_KOVALARI:
        kovalar += [Kolon(f"m_{k}", f"{etiket} gün Miktar", 95, "miktar"),
                    Kolon(f"d_{k}", f"{etiket} gün Değer", 100, "para")]

    def kur():
        return RaporEkrani(
            app, baslik="STOK YAŞLANDIRMA",
            alt="Stok katmanlarının giriş tarihine göre yaş ve değer dağılımı",
            filtreler=[Filtre("tarih", "tarih", "Yaş tarihi", date.today()), *_ortak_filtreler()],
            tablolar=[Tablo("satirlar", "Yaşlandırma", [
                Kolon("urun_kodu", "Ürün Kodu", 100), Kolon("urun_adi", "Ürün Adı", 200), Kolon("birim", "Birim", 55),
                Kolon("miktar", "Toplam Miktar", 90, "miktar"), Kolon("deger", "Toplam Değer", 105, "para"),
                Kolon("ort_yas", "Ort. Yaş (gün)", 85, "gun1"), Kolon("en_eski", "En Eski Giriş", 90, "tarih"),
                *kovalar, Kolon("devir_miktar", "Devir (geçmişi bilinmiyor) Miktar", 175, "miktar"),
                Kolon("devir_deger", "Devir Değer", 100, "para"), Kolon("aciklama", "Açıklama", 260)],
                cift_tik=lambda r: urun_ekstresi_ac(app, r))],
            hesapla=lambda f: srv.yaslandirma(tarih=f.get("tarih"), depo=f.get("depo") or None,
                                              arama=f.get("arama") or "", grup_id=f.get("grup_id") or None),
            toplam_metni=lambda s: f"Ürün: {sum(1 for r in s.get('satirlar', []) if not r.get('_sabit'))}",
            ust=_ust, hafiza="stok_yaslandirma", **kw)
    return _ekran(app, "Stok Yaşlandırma", kur)


# ---------------------------------------------------------------------------
# Devir hızı / yeterlilik
# ---------------------------------------------------------------------------

def devir_yeterlilik_goster(app, **kw) -> RaporEkrani | None:
    from database import stok_rapor_service as srv

    def kur():
        return RaporEkrani(
            app, baslik="STOK DEVİR HIZI / YETERLİLİK GÜNÜ",
            alt="Net satış hızı, kullanılabilir stokla kaç gün yeteceği ve devir oranı",
            filtreler=[Filtre("tarih", "bas", "Başlangıç", date(date.today().year, 1, 1)),
                       Filtre("tarih", "bit", "Bitiş", date.today()), *_ortak_filtreler()],
            tablolar=[Tablo("satirlar", "Devir / Yeterlilik", [
                Kolon("urun_kodu", "Ürün Kodu", 100), Kolon("urun_adi", "Ürün Adı", 200), Kolon("birim", "Birim", 55),
                Kolon("net_satis_miktari", "Net Satış Miktarı", 105, "miktar"),
                Kolon("gunluk_hiz", "Günlük Hız", 80, "fiyat"), Kolon("mevcut", "Mevcut", 75, "miktar"),
                Kolon("kullanilabilir", "Kullanılabilir", 85, "miktar"),
                Kolon("yeterlilik_gun", "Yeterlilik (gün)", 95, "gun"),
                Kolon("satis_maliyeti", "Satış Maliyeti", 105, "para"),
                Kolon("ort_stok_degeri", "Ort. Stok Değeri", 110, "para"),
                Kolon("devir_orani", "Devir Oranı", 80, "fiyat"),
                Kolon("stokta_kalma_gun", "Stokta Kalma (gün)", 110, "gun1"), Kolon("aciklama", "Açıklama", 300)],
                cift_tik=lambda r: urun_ekstresi_ac(app, r),
                etiket=lambda r: "soluk" if str(r.get("aciklama", "")).startswith("Veri yetersiz") else None)],
            hesapla=lambda f: srv.devir_yeterlilik(bas=f["bas"] or date(date.today().year, 1, 1),
                                                   bit=f["bit"] or date.today(), depo=f.get("depo") or None,
                                                   arama=f.get("arama") or "", grup_id=f.get("grup_id") or None),
            toplam_metni=lambda s: (f"Ürün: {len(s.get('satirlar', []))}   Dönem günü: {s.get('gun', '')}   "
                                    "Ortalama stok: günlük kapanış ortalaması"),
            ust=_ust, hafiza="stok_devir", **kw)
    return _ekran(app, "Stok Devir Hızı", kur)


# ---------------------------------------------------------------------------
# Stok yatırım verimliliği (GMROI)
# ---------------------------------------------------------------------------

def _seviye_secenek(seviye: int, bos: str) -> list[tuple[str, str]]:
    from database.stok_rapor_service import grup_secenekleri

    try:
        return [("", bos)] + grup_secenekleri(seviye)
    except Exception:  # noqa: BLE001
        return [("", bos)]


def _verimlilik_etiketi(r: dict) -> str | None:
    if r.get("_sabit"):
        return None
    if str(r.get("hesap_notu") or "").startswith(("Maliyeti olmayan", "Eksik", "Negatif", "Stok kartı")):
        return "uyari"
    g = r.get("gmroi")
    return "iyi" if not isinstance(g, str) and g is not None and g >= 1 else None


def stok_karti_ac(app, r: dict) -> None:
    if r.get("_sabit") or not r.get("stok_id"):
        return
    from database.stok_service import StokService
    from stok_ui import StokKartiDialog

    stok = StokService.stok_getir(int(r["stok_id"]))
    if stok is None:
        messagebox.showwarning("Stok kartı", "Stok kartı bulunamadı.", parent=app)
        return
    StokKartiDialog(app, stok=stok)


def yatirim_verimliligi_goster(app, **kw) -> RaporEkrani | None:
    from database import stok_rapor_service as srv

    if not _yetki_var():
        messagebox.showwarning("Stok Yatırım Verimliliği", "Stok raporlarını görüntüleme yetkiniz yok.", parent=app)
        return None
    try:
        from database.access import maliyet_izinli

        if not maliyet_izinli():
            messagebox.showwarning("Stok Yatırım Verimliliği",
                                   "Bu rapor maliyet içerir; maliyet görme yetkiniz yok.", parent=app)
            return None
    except Exception:  # noqa: BLE001
        pass

    olcu = [Kolon("bas_miktar", "Dönem Başı Miktar", 105, "miktar"),
            Kolon("bas_deger", "Dönem Başı Değer", 110, "para"),
            Kolon("son_miktar", "Dönem Sonu Miktar", 105, "miktar"),
            Kolon("son_deger", "Dönem Sonu Değer", 110, "para"),
            Kolon("ort_stok", "Ort. Stok Maliyet Değeri", 140, "para"),
            Kolon("net_satis", "Net Satış (KDV hariç)", 125, "para"),
            Kolon("net_miktar", "Net Satılan Miktar", 110, "miktar"),
            Kolon("smm", "Satılan Malın Maliyeti", 130, "para"),
            Kolon("brut_kar", "Brüt Kâr", 105, "para"), Kolon("marj", "Brüt Kâr Marjı", 95, "yuzde"),
            Kolon("devir", "Stok Devir Hızı", 95, "oran"), Kolon("kalma_gun", "Ort. Stokta Kalma (gün)", 130, "gun1"),
            Kolon("gmroi", "GMROI", 70, "oran"), Kolon("son_alis", "Son Alış", 85, "tarih"),
            Kolon("son_satis", "Son Satış", 85, "tarih")]
    gruplar = [Kolon("ana_grup", "Ana Grup", 120), Kolon("tali_grup", "Tali Grup", 120),
               Kolon("alt_grup", "Alt Grup", 120)]
    urun = [Kolon("urun_kodu", "Ürün Kodu", 100), Kolon("urun_adi", "Ürün Adı", 200), Kolon("birim", "Birim", 55)]
    filtre_cache: dict = {}

    def hesapla(f):
        filtre_cache.clear()
        filtre_cache.update(f)
        return srv.yatirim_verimliligi(
            bas=f["bas"] or date(date.today().year, 1, 1), bit=f["bit"] or date.today(),
            yontem=f.get("yontem") or srv.FIFO, depo=f.get("depo") or None, arama=f.get("arama") or "",
            ana_grup_id=f.get("ana_grup_id") or None, tali_grup_id=f.get("tali_grup_id") or None,
            alt_grup_id=f.get("alt_grup_id") or None, grup_seviyesi=f.get("grup_seviyesi") or "ana",
            siralama=f.get("siralama") or "brut_kar")

    def secili(e: RaporEkrani) -> dict | None:
        t = e._etkin_tablo()
        r = e.secili(t.anahtar)
        if not r or r[0].get("_sabit") or not r[0].get("urun_kodu") or t.anahtar == "gruplar":
            messagebox.showinfo("Stok Yatırım Verimliliği", "Önce ürün satırı seçin.", parent=app)
            return None
        return r[0]

    def satis_satirlari(e: RaporEkrani) -> None:
        from satis_yonetici_rapor_ui import karlilik_detay_goster

        r = secili(e)
        if r:
            s = e.sonuc
            karlilik_detay_goster(app, "urun", r["urun_kodu"], f"{r['urun_kodu']} {r.get('urun_adi') or ''}",
                                  s.get("bas"), s.get("son"),
                                  {"depo": filtre_cache.get("depo") or None,
                                   "maliyet_yontemi": filtre_cache.get("yontem") or srv.FIFO})

    def stok_hareketleri(e: RaporEkrani) -> None:
        r = secili(e)
        if r:
            urun_ekstresi_ac(app, r)

    def kart(e: RaporEkrani) -> None:
        r = secili(e)
        if r:
            stok_karti_ac(app, r)

    def toplam(s):
        t = s.get("toplam") or {}
        if not t:
            return ""
        return (f"Yöntem: {s.get('yontem', '')}   Ürün: {t.get('urun_sayisi', 0)}   "
                f"Ort. stok: {bicimle(t.get('ort_stok'), 'para')}   Net satış: {bicimle(t.get('net_satis'), 'para')}   "
                f"Brüt kâr: {bicimle(t.get('brut_kar'), 'para')}   GMROI: {bicimle(t.get('gmroi'), 'oran')}   "
                f"Devir: {bicimle(t.get('devir'), 'oran')}   Kapsam: {t.get('kapsam', '')}")

    def kur():
        return RaporEkrani(
            app, baslik="STOK YATIRIM VERİMLİLİĞİ",
            alt="Stokta bağlı sermayenin ürettiği brüt kâr (GMROI), devir hızı ve stokta kalma süresi",
            filtreler=[Filtre("tarih", "bas", "Başlangıç", date(date.today().year, 1, 1)),
                       Filtre("tarih", "bit", "Bitiş", date.today()),
                       Filtre("combo", "yontem", "Maliyet yöntemi", srv.FIFO, srv.verimlilik_yontemleri()),
                       Filtre("combo", "depo", "Depo", "", _depo_secenek()),
                       Filtre("metin", "arama", "Ürün kodu / adı / barkod"),
                       Filtre("combo", "ana_grup_id", "Ana grup", "", _seviye_secenek(1, "(Tüm ana gruplar)")),
                       Filtre("combo", "tali_grup_id", "Tali grup", "", _seviye_secenek(2, "(Tüm tali gruplar)")),
                       Filtre("combo", "alt_grup_id", "Alt grup", "", _seviye_secenek(3, "(Tüm alt gruplar)")),
                       Filtre("combo", "grup_seviyesi", "Grup görünümü", "ana", list(srv.GRUP_SEVIYELERI)),
                       Filtre("combo", "siralama", "Sıralama", "brut_kar", list(srv.VERIMLILIK_SIRALAMA))],
            tablolar=[
                Tablo("urunler", "Ürün Bazında", [*urun, *gruplar, *olcu, Kolon("pasif", "Kart", 70),
                                                  Kolon("hesap_notu", "Hesap Notu", 360)],
                      cift_tik=lambda r: urun_ekstresi_ac(app, r), etiket=_verimlilik_etiketi),
                Tablo("gruplar", "Grup Bazında", [*gruplar, Kolon("urun_sayisi", "Ürün", 55, "gun"),
                                                  Kolon("kapsam", "Kapsam (oranlara giren)", 140),
                                                  Kolon("birim", "Birim", 60), *olcu,
                                                  Kolon("hesap_notu", "Hesap Notu", 360)]),
                Tablo("hesaplanamayan", "Hesaplanamayan / Notlu", [*urun, Kolon("hesap_notu", "Neden", 480),
                                                                   *olcu[:5], Kolon("net_satis", "Net Satış", 110,
                                                                                    "para")],
                      cift_tik=lambda r: urun_ekstresi_ac(app, r), etiket=_verimlilik_etiketi),
            ],
            hesapla=hesapla, toplam_metni=toplam,
            ek_butonlar=[("Stok Kartı", kart, "duzenle"), ("Satış Satırları", satis_satirlari, "duzenle"),
                         ("Stok Hareketleri", stok_hareketleri, "duzenle")],
            ust=_ust, hafiza="stok_yatirim_verimliligi", **kw)
    return _ekran(app, "Stok Yatırım Verimliliği", kur)


# ---------------------------------------------------------------------------
# Sayım farkları
# ---------------------------------------------------------------------------

def sayim_farklari_goster(app, **kw) -> RaporEkrani | None:
    from database import stok_rapor_service as srv

    def kur():
        return RaporEkrani(
            app, baslik="SAYIM FARKLARI",
            alt="Sayım fişlerindeki sistem / sayılan farkları, maliyet etkisi ve bağlı düzeltme hareketi",
            filtreler=[Filtre("tarih", "bas", "Başlangıç", date(date.today().year, 1, 1)),
                       Filtre("tarih", "bit", "Bitiş", date.today()),
                       Filtre("combo", "depo", "Depo", "", _depo_secenek()), Filtre("metin", "arama", "Ürün"),
                       Filtre("check", "sadece_farkli", "Yalnız farklı satırlar", True)],
            tablolar=[Tablo("satirlar", "Sayım Farkları", [
                Kolon("tarih", "Tarih", 85, "tarih"), Kolon("fis_no", "Fiş No", 95), Kolon("depo", "Depo", 100),
                Kolon("urun_kodu", "Ürün Kodu", 100), Kolon("urun_adi", "Ürün Adı", 190), Kolon("birim", "Birim", 55),
                Kolon("sistem", "Sistem", 75, "miktar"), Kolon("sayilan", "Sayılan", 75, "miktar"),
                Kolon("fark", "Fark", 70, "miktar"), Kolon("eksik_fazla", "Eksik / Fazla", 85),
                Kolon("maliyet_farki", "Maliyet Farkı", 100, "para"), Kolon("durum", "Durum", 85),
                Kolon("onaylayan", "Onaylayan", 90), Kolon("bagli_evrak", "Bağlı Düzeltme Evrakı", 200),
                Kolon("sonraki", "Sonraki Hareketler", 220), Kolon("neden", "Fark Nedeni / Not", 260)],
                cift_tik=lambda r: urun_ekstresi_ac(app, r),
                etiket=lambda r: "uyari" if r.get("bagli_evrak") == "Düzeltme hareketi yok" else None)],
            hesapla=lambda f: srv.sayim_farklari(bas=f.get("bas"), bit=f.get("bit"), depo=f.get("depo") or None,
                                                 arama=f.get("arama") or "", sadece_farkli=f.get("sadece_farkli")),
            toplam_metni=lambda s: (f"Fazla maliyet: {bicimle(s.get('fazla_tutar'), 'para') or '—'} TL   "
                                    f"Eksik maliyet: {bicimle(s.get('eksik_tutar'), 'para') or '—'} TL"),
            ust=_ust, hafiza="stok_sayim_fark", **kw)
    return _ekran(app, "Sayım Farkları", kur)


# ---------------------------------------------------------------------------
# Depo transfer takibi
# ---------------------------------------------------------------------------

def transfer_takibi_goster(app, **kw) -> RaporEkrani | None:
    from database import stok_rapor_service as srv

    def kur():
        return RaporEkrani(
            app, baslik="DEPO TRANSFER TAKİBİ",
            alt="Transfer fişlerinde gönderilen, alınan ve yoldaki miktar",
            filtreler=[Filtre("tarih", "bas", "Başlangıç", date(date.today().year, 1, 1)),
                       Filtre("tarih", "bit", "Bitiş", date.today()),
                       Filtre("combo", "depo", "Depo (kaynak veya hedef)", "", _depo_secenek()),
                       Filtre("metin", "arama", "Ürün")],
            tablolar=[Tablo("satirlar", "Transferler", [
                Kolon("tarih", "Tarih", 85, "tarih"), Kolon("fis_no", "Fiş No", 95), Kolon("kaynak", "Kaynak", 110),
                Kolon("hedef", "Hedef", 110), Kolon("urun_kodu", "Ürün Kodu", 100), Kolon("urun_adi", "Ürün Adı", 190),
                Kolon("birim", "Birim", 55), Kolon("fis_miktari", "Fiş Miktarı", 80, "miktar"),
                Kolon("gonderilen", "Gönderilen", 80, "miktar"), Kolon("alinan", "Alınan", 75, "miktar"),
                Kolon("yoldaki", "Yoldaki", 70, "miktar"), Kolon("bekleme_gun", "Bekleme (gün)", 85, "gun"),
                Kolon("durum", "Durum", 190), Kolon("aciklama", "Açıklama", 200)],
                cift_tik=lambda r: urun_ekstresi_ac(app, r), etiket=_durum_etiketi)],
            hesapla=lambda f: srv.transfer_takibi(bas=f.get("bas"), bit=f.get("bit"), depo=f.get("depo") or None,
                                                  arama=f.get("arama") or ""),
            toplam_metni=lambda s: (f"Satır: {len(s.get('satirlar', []))}   Yolda: "
                                    f"{sum(1 for r in s.get('satirlar', []) if (r.get('yoldaki') or 0) > 0)}   "
                                    f"Uyumsuz/iptal: {sum(1 for r in s.get('satirlar', []) if r.get('durum') != 'Tamamlandı')}"),
            ust=_ust, hafiza="stok_transfer", **kw)
    return _ekran(app, "Depo Transfer Takibi", kur)


# ---------------------------------------------------------------------------
# Tutarlılık kontrolü
# ---------------------------------------------------------------------------

def tutarlilik_kontrolu_goster(app, **kw) -> RaporEkrani | None:
    from database import stok_rapor_service as srv

    def kur():
        return RaporEkrani(
            app, baslik="STOK TUTARLILIK KONTROLÜ",
            alt="Salt okunur kontrol: hiçbir kaydı silmez, düzeltmez veya yeniden hesaplamaz",
            filtreler=[Filtre("combo", "onem", "Önem", "", [("", "(Tümü)"), ("Yüksek", "Yüksek"), ("Orta", "Orta"),
                                                            ("Düşük", "Düşük")]),
                       Filtre("combo", "hata_turu", "Hata türü", "", [("", "(Tümü)")] + [(h, h) for h in
                                                                                       srv.hata_turleri()])],
            tablolar=[
                Tablo("satirlar", "Bulgular", [
                    Kolon("hata_turu", "Hata Türü", 190), Kolon("onem", "Önem", 65), Kolon("urun", "Ürün", 230),
                    Kolon("depo", "Depo", 100), Kolon("belge", "Belge", 140), Kolon("aciklama", "Açıklama", 330),
                    Kolon("oneri", "Önerilen İnceleme Adımı", 330)],
                    cift_tik=lambda r: urun_ekstresi_ac(app, r),
                    etiket=lambda r: "uyari" if r.get("onem") == "Yüksek" else (
                        "soluk" if r.get("onem") == "Düşük" else None)),
                Tablo("ozet", "Özet", [Kolon("hata_turu", "Hata Türü", 260), Kolon("adet", "Adet", 70, "gun")]),
            ],
            hesapla=lambda f: srv.tutarlilik_kontrolu(onem=f.get("onem") or None, hata_turu=f.get("hata_turu") or None),
            toplam_metni=lambda s: f"Bulgu: {len(s.get('satirlar', []))}",
            ust=_ust, hafiza="stok_tutarlilik", **kw)
    return _ekran(app, "Stok Tutarlılık Kontrolü", kur)
