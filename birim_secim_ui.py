"""Evrak satırında birim seçimi: kart birimleri + genel birim listesi.

Kartta tanımlı olmayan bir birim seçilirse dönüşüm katsayısı kullanıcıya sorulur ve birim karta
eklenir; katsayı tahmin edilmez, vazgeçilirse birim değişmez.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from tkinter import messagebox, simpledialog

from database.stok_service import StokService, birim_anahtari
from fatura_satir_birim_service import _stok_yukle, stok_aktif_birimleri

GENEL_BIRIMLER = ("Adet", "Kg", "Metre", "Koli", "Paket", "Torba", "Boy", "Top", "Küçük Torba")


def evrak_birim_secenekleri(urun_kodu: str) -> list[str]:
    """Önce kartın aktif birimleri, ardından genel ve firmada tanımlı birimler (tekrarsız)."""
    sonuc = list(stok_aktif_birimleri(urun_kodu) or ["Adet"])
    gorulen = {birim_anahtari(b) for b in sonuc}
    try:
        genel = StokService.birim_listesi(GENEL_BIRIMLER)
    except Exception:
        genel = list(GENEL_BIRIMLER)
    for ad in genel:
        anahtar = birim_anahtari(ad)
        if anahtar and anahtar not in gorulen:
            gorulen.add(anahtar)
            sonuc.append(ad)
    return sonuc


def _katsayi_coz(metin: str) -> Decimal:
    ham = (metin or "").strip().replace(" ", "")
    if "," in ham and "." in ham:
        ham = ham.replace(".", "").replace(",", ".") if ham.rfind(",") > ham.rfind(".") else ham.replace(",", "")
    elif "," in ham:
        ham = ham.replace(",", ".")
    try:
        deger = Decimal(ham)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Geçerli bir katsayı girin (örn. 12 veya 0,5).") from exc
    if deger <= 0:
        raise ValueError("Katsayı sıfırdan büyük olmalıdır.")
    return deger


def kart_birimini_hazirla(parent, urun_kodu: str, birim: str) -> bool:
    """Seçilen birim kartta kullanılabilir mi; değilse katsayıyı sorup karta ekler.

    Kartsız serbest satırda dönüşüm yoktur (True). Kullanıcı vazgeçerse veya kayıt yapılamazsa False.
    """
    kod = (urun_kodu or "").strip()
    birim = (birim or "").strip()
    if not kod or not birim:
        return True
    stok = _stok_yukle(kod)
    if stok is None:
        return True
    ana = (getattr(stok, "birim", None) or "Adet").strip() or "Adet"
    if StokService.birim_carpani_bul(stok, birim, ana) is not None:
        return True
    etiket = f"{getattr(stok, 'stok_kodu', kod)} — {getattr(stok, 'stok_adi', '') or ''}".rstrip(" —")
    while True:
        cevap = simpledialog.askstring(
            "Birim katsayısı",
            f"«{etiket}» kartında «{birim}» birimi tanımlı değil.\n\n"
            f"1 {birim} kaç {ana} eder?\n"
            "Girilen katsayı stok kartına kaydedilir.",
            parent=parent,
        )
        if cevap is None:
            return False
        try:
            katsayi = _katsayi_coz(cevap)
        except ValueError as hata:
            messagebox.showwarning("Birim katsayısı", str(hata), parent=parent)
            continue
        break
    try:
        StokService.kart_birimi_ekle(kod, birim, katsayi)
    except Exception as hata:  # noqa: BLE001 — yetki / doğrulama mesajı kullanıcıya gösterilir
        messagebox.showwarning("Birim katsayısı", f"Birim karta eklenemedi:\n{hata}", parent=parent)
        return False
    return True
