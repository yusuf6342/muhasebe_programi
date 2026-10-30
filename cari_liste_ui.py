"""Cari listesi kolon ayarları (müşteri / tedarikçi ortak)."""

from __future__ import annotations

import json
import math
import os
import tkinter as tk
from copy import deepcopy
from pathlib import Path
from tkinter import ttk
from typing import Callable

from database.session_manager import oturum
from satis_tema import BEYAZ, LACIVERT, METIN, font

EKRAN_KODU = "cari_kartlari_listesi"


def gecen_gun_sayi(deger) -> float | None:
    """Geçen gün ham değeri (sıralama / hesap). Boş → None; hatalı → None."""
    if deger is None or deger == "":
        return None
    try:
        if isinstance(deger, str):
            s = deger.strip().replace(" ", "").replace(",", ".")
            # Görüntüdeki "38 gün" / "38,2 gün" geri çöz
            if s.lower().endswith("gün"):
                s = s[:-3].strip()
            if not s:
                return None
            return float(s)
        return float(deger)
    except (TypeError, ValueError):
        return None


def gecen_gun_goster(deger) -> str:
    """Liste görüntüsü: valör gün birimiyle (ör. «38 gün», «38,2 gün»).

    Boş/hesaplanamayan → boş (sahte 0 gün yok). Gerçek sıfır → «0 gün».
    Negatif işaret korunur. Ondalık anlamlıysa bir hane; değilse tam gün.
    """
    if deger is None or deger == "":
        return ""
    x = gecen_gun_sayi(deger)
    if x is None:
        return ""
    # Tam sayıya yakınsa tam gün; aksi halde 1 ondalık (TR virgül)
    if abs(x - round(x)) < 1e-9:
        return f"{int(round(x))} gün"
    metin = f"{x:.1f}".replace(".", ",")
    return f"{metin} gün"

# anahtar, baslik, varsayilan_genislik, varsayilan_gorunur
# Cari kart + liste özet alanları; görünürlük Kolon Ayarları ile yönetilir.
CARI_LISTE_KOLONLARI = (
    ("kod", "Cari Kodu", 110, True),
    ("unvan", "Cari Adı", 220, True),
    ("cari_turu", "Muhasebe Rolü", 120, True),
    ("ana_tur", "Ana Kart Türü", 120, False),
    ("musteri_alt_tur", "Müşteri Alt Tür", 120, False),
    ("tedarikci_alt_tur", "Tedarikçi Alt Tür", 120, False),
    ("grup", "Sektör Grubu", 135, True),
    ("vergi_dairesi", "Vergi Dairesi", 120, False),
    ("vergi_numarasi", "VKN", 100, False),
    ("tc_kimlik", "TCKN", 100, False),
    ("telefon", "GSM", 115, True),
    ("telefon2", "GSM 2", 110, False),
    ("telefon3", "Sabit", 110, False),
    ("whatsapp", "WhatsApp", 115, False),
    ("email", "E-posta", 180, True),
    ("adres_tipi", "Adres 1 Tür", 90, False),
    ("adres", "Adres 1", 180, False),
    ("il", "İl", 90, False),
    ("ilce", "İlçe", 90, False),
    ("adres_tipi2", "Adres 2 Tür", 90, False),
    ("adres2", "Adres 2", 160, False),
    ("il2", "İl 2", 80, False),
    ("ilce2", "İlçe 2", 80, False),
    ("adres_tipi3", "Adres 3 Tür", 90, False),
    ("adres3", "Adres 3", 160, False),
    ("il3", "İl 3", 80, False),
    ("ilce3", "İlçe 3", 80, False),
    ("ana_yetkili", "Ana Yetkili", 140, False),
    ("yetkili_telefon", "Yetkili Telefonu", 120, False),
    ("yaklasan_dogum", "Yaklaşan Doğum Günü", 130, False),
    ("satis_fiyat_listesi", "Satış Fiyat Listesi", 130, False),
    ("alis_fiyat_listesi", "Alış Fiyat Listesi", 130, False),
    ("satis_vade_gunu", "Satış Vade (gün)", 100, False),
    ("alis_vade_gunu", "Alış Vade (gün)", 100, False),
    ("acik_hesap_risk_limiti", "Açık Hesap Limit", 120, False),
    ("acik_hesap_limit_uygula", "Açık Hesap Limit Uygula", 130, False),
    ("cek_risk_limiti", "Çek Limit", 100, False),
    ("cek_limit_uygula", "Çek Limit Uygula", 110, False),
    ("senet_risk_limiti", "Senet Limit", 100, False),
    ("senet_limit_uygula", "Senet Limit Uygula", 110, False),
    ("toplam_risk_limiti", "Toplam Risk Limit", 120, False),
    ("toplam_limit_uygula", "Toplam Limit Uygula", 120, False),
    ("risk_orani_ciro_cek", "Risk % Ciro Çek", 110, False),
    ("risk_orani_diger_cek", "Risk % Diğer Çek", 110, False),
    ("risk_orani_senet", "Risk % Senet", 100, False),
    ("vade_farki_aylik_oran", "Vade Farkı Aylık %", 110, False),
    ("vade_farki_yillik_oran", "Vade Farkı Yıllık %", 110, False),
    ("vade_farki_donem", "Vade Farkı Dönem", 100, False),
    ("vade_farki_aciklama", "Vade Farkı Açıklama", 140, False),
    ("muhasebe_borclu_kodu", "Muh. Borçlu Kod", 110, False),
    ("muhasebe_alacakli_kodu", "Muh. Alacaklı Kod", 110, False),
    ("muhasebe_satis_kodu", "Muh. Satış Kod", 110, False),
    ("muhasebe_alis_kodu", "Muh. Alış Kod", 110, False),
    ("muhasebe_kdv_satis_kodu", "Muh. KDV Satış", 110, False),
    ("muhasebe_kdv_alis_kodu", "Muh. KDV Alış", 110, False),
    ("toplam_borc", "Toplam Borç", 120, False),
    ("toplam_alacak", "Toplam Alacak", 120, False),
    ("bakiye", "Yekûn Bakiye", 140, True),
    ("agirlikli", "Kalan Bakiye Gün", 120, True),
    ("kapatilan_gun", "Kapatılan Bakiye Gün", 120, False),
    ("ozel_notlar", "Özel Notlar", 160, False),
    ("uyari_notu", "Uyarı Notu", 160, False),
    ("durum", "Durum", 75, True),
)

CARI_LISTE_SAG = frozenset(
    {
        "bakiye",
        "agirlikli",
        "kapatilan_gun",
        "toplam_borc",
        "toplam_alacak",
        "acik_hesap_risk_limiti",
        "cek_risk_limiti",
        "senet_risk_limiti",
        "toplam_risk_limiti",
        "satis_vade_gunu",
        "alis_vade_gunu",
        "vade_farki_aylik_oran",
        "vade_farki_yillik_oran",
        "risk_orani_ciro_cek",
        "risk_orani_diger_cek",
        "risk_orani_senet",
    }
)
CARI_LISTE_ZORUNLU = frozenset({"kod", "unvan"})


def cari_liste_varsayilan_ayarlari() -> dict:
    sira = [k for k, _, _, _ in CARI_LISTE_KOLONLARI]
    kolonlar = {
        anahtar: {"baslik": baslik, "genislik": genislik, "gorunur": gorunur}
        for anahtar, baslik, genislik, gorunur in CARI_LISTE_KOLONLARI
    }
    return {"sira": sira, "kolonlar": kolonlar, "profil": "Standart"}


def _ayar_kimlik() -> tuple[str, str]:
    firma = str(oturum.company_id or oturum.firma_kodu or "0")
    kullanici = str(oturum.user_id or oturum.kullanici_adi or "0")
    return firma, kullanici


def cari_liste_ayar_dosyasi() -> Path:
    firma, kullanici = _ayar_kimlik()
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MuhasebeProgrami" / "ayarlar"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"cari_liste_kolon_{firma}_{kullanici}.json"


def cari_liste_ayarlari_yukle() -> dict:
    varsayilan = cari_liste_varsayilan_ayarlari()
    yol = cari_liste_ayar_dosyasi()
    if not yol.exists():
        return deepcopy(varsayilan)
    try:
        kayit = json.loads(yol.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return deepcopy(varsayilan)

    bilinen = {k for k, _, _, _ in CARI_LISTE_KOLONLARI}
    sira = [k for k in (kayit.get("sira") or []) if k in bilinen]
    for k, _, _, _ in CARI_LISTE_KOLONLARI:
        if k not in sira:
            sira.append(k)

    kolonlar = {}
    gelen_kol = kayit.get("kolonlar") or {}
    for anahtar, baslik, genislik, gorunur in CARI_LISTE_KOLONLARI:
        gelen = gelen_kol.get(anahtar) or {}
        try:
            w = int(gelen.get("genislik", genislik))
        except (TypeError, ValueError):
            w = genislik
        g = bool(gelen.get("gorunur", gorunur))
        if anahtar in CARI_LISTE_ZORUNLU:
            g = True
        kolonlar[anahtar] = {
            "baslik": baslik,
            "genislik": max(40, min(w, 600)),
            "gorunur": g,
        }
    return {
        "sira": sira,
        "kolonlar": kolonlar,
        "profil": kayit.get("profil") or "Standart",
    }


def cari_liste_ayarlari_kaydet(ayarlar: dict) -> None:
    bilinen = {k for k, _, _, _ in CARI_LISTE_KOLONLARI}
    sira = [k for k in (ayarlar.get("sira") or []) if k in bilinen]
    for k, _, _, _ in CARI_LISTE_KOLONLARI:
        if k not in sira:
            sira.append(k)
    temiz_kol = {}
    for anahtar, _baslik, genislik, gorunur in CARI_LISTE_KOLONLARI:
        cfg = (ayarlar.get("kolonlar") or {}).get(anahtar) or {}
        g = bool(cfg.get("gorunur", gorunur))
        if anahtar in CARI_LISTE_ZORUNLU:
            g = True
        try:
            w = int(cfg.get("genislik", genislik))
        except (TypeError, ValueError):
            w = genislik
        temiz_kol[anahtar] = {"genislik": max(40, min(w, 600)), "gorunur": g}
    yol = cari_liste_ayar_dosyasi()
    yol.write_text(
        json.dumps(
            {
                "ekran": EKRAN_KODU,
                "firma_id": _ayar_kimlik()[0],
                "kullanici_id": _ayar_kimlik()[1],
                "sira": sira,
                "kolonlar": temiz_kol,
                "profil": ayarlar.get("profil") or "Standart",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def gorunur_kolonlar(ayarlar: dict | None = None) -> list[str]:
    ayar = ayarlar or cari_liste_ayarlari_yukle()
    sira = ayar.get("sira") or []
    kolonlar = ayar.get("kolonlar") or {}
    return [k for k in sira if (kolonlar.get(k) or {}).get("gorunur", True)]


def baslik_metni(anahtar: str, *, etiket: str = "Cari") -> str:
    ozel = {
        "kod": f"{etiket} Kodu",
        "unvan": f"{etiket} Adı",
        "grup": "Sektör Grubu",
        "agirlikli": "Kalan Bakiye Gün",
    }
    if anahtar in ozel:
        return ozel[anahtar]
    for k, baslik, _, _ in CARI_LISTE_KOLONLARI:
        if k == anahtar:
            return baslik
    return anahtar


def grup_hucresi(musteri_grubu: str | None) -> str:
    """Sektör grubu sütunu: boşsa «Grup Atanmamış»."""
    ad = (musteri_grubu or "").strip()
    return ad if ad else "Grup Atanmamış"


def _telefon_hucre(deger) -> str:
    if not deger:
        return ""
    try:
        from telefon_bicim import telefon_bicimle

        return telefon_bicimle(str(deger))
    except Exception:
        return str(deger)


def _metin_kisalt(deger, *, azami: int = 80) -> str:
    metin = (deger or "").strip() if isinstance(deger, str) else ("" if deger is None else str(deger))
    if len(metin) <= azami:
        return metin
    return metin[: max(0, azami - 1)] + "…"


def _para_hucre(deger) -> str:
    if deger is None or deger == "":
        return ""
    try:
        from database.muhasebe_service import para_goster

        return para_goster(deger)
    except Exception:
        try:
            from decimal import Decimal

            d = Decimal(str(deger))
            return f"{d:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except Exception:
            return str(deger)


def cari_tur_ad_haritalari() -> tuple[dict[int, str], dict[int, str]]:
    """Ana / alt kart türü id → ad (liste satırları için)."""
    try:
        from database.kart_turu_service import KAPSAM_CARI, KartTuruService

        analar = KartTuruService.ana_turleri_listele(KAPSAM_CARI, sadece_aktif=False)
        ana_map = {int(a.id): a.ad for a in analar}
        alt_map: dict[int, str] = {}
        for a in analar:
            for alt in KartTuruService.alt_turleri_listele(a.id, sadece_aktif=False):
                alt_map[int(alt.id)] = alt.ad
        return ana_map, alt_map
    except Exception:
        return {}, {}


def satir_deger_haritasi(
    ozet: dict,
    *,
    ana_tur_adlari: dict[int, str] | None = None,
    alt_tur_adlari: dict[int, str] | None = None,
) -> dict[str, str]:
    """Liste satırı için tüm bilinen kolon anahtarları → görünen metin."""
    cari = ozet["cari"]
    ana_map = ana_tur_adlari or {}
    alt_map = alt_tur_adlari or {}
    ana_id = getattr(cari, "ana_kart_turu_id", None)
    m_alt = getattr(cari, "musteri_alt_tur_id", None)
    t_alt = getattr(cari, "tedarikci_alt_tur_id", None)

    def _id_ad(mid, harita):
        if mid is None:
            return ""
        try:
            return harita.get(int(mid), "")
        except (TypeError, ValueError):
            return ""

    return {
        "kod": cari.cari_kodu or "",
        "unvan": cari.unvan or "",
        "cari_turu": (cari.cari_turu or "").strip(),
        "ana_tur": _id_ad(ana_id, ana_map),
        "musteri_alt_tur": _id_ad(m_alt, alt_map),
        "tedarikci_alt_tur": _id_ad(t_alt, alt_map),
        "grup": grup_hucresi(cari.musteri_grubu),
        "vergi_dairesi": cari.vergi_dairesi or "",
        "vergi_numarasi": cari.vergi_numarasi or "",
        "tc_kimlik": cari.tc_kimlik or "",
        "telefon": _telefon_hucre(cari.telefon),
        "telefon2": _telefon_hucre(cari.telefon2),
        "telefon3": _telefon_hucre(cari.telefon3),
        "whatsapp": _telefon_hucre(getattr(cari, "whatsapp", None)),
        "email": cari.email or "",
        "adres_tipi": cari.adres_tipi or "",
        "adres": _metin_kisalt(cari.adres, azami=100),
        "il": cari.il or "",
        "ilce": cari.ilce or "",
        "adres_tipi2": cari.adres_tipi2 or "",
        "adres2": _metin_kisalt(cari.adres2, azami=100),
        "il2": cari.il2 or "",
        "ilce2": cari.ilce2 or "",
        "adres_tipi3": cari.adres_tipi3 or "",
        "adres3": _metin_kisalt(cari.adres3, azami=100),
        "il3": cari.il3 or "",
        "ilce3": cari.ilce3 or "",
        "ana_yetkili": ozet.get("ana_yetkili") or "",
        "yetkili_telefon": ozet.get("yetkili_telefon") or "",
        "yaklasan_dogum": ozet.get("yaklasan_dogum") or "",
        "satis_fiyat_listesi": cari.satis_fiyat_listesi or "",
        "alis_fiyat_listesi": cari.alis_fiyat_listesi or "",
        "satis_vade_gunu": "" if cari.satis_vade_gunu is None else str(cari.satis_vade_gunu),
        "alis_vade_gunu": "" if cari.alis_vade_gunu is None else str(cari.alis_vade_gunu),
        "acik_hesap_risk_limiti": _para_hucre(cari.acik_hesap_risk_limiti),
        "acik_hesap_limit_uygula": "Evet" if getattr(cari, "acik_hesap_limit_uygula", False) else "Hayır",
        "cek_risk_limiti": _para_hucre(cari.cek_risk_limiti),
        "cek_limit_uygula": "Evet" if getattr(cari, "cek_limit_uygula", False) else "Hayır",
        "senet_risk_limiti": _para_hucre(cari.senet_risk_limiti),
        "senet_limit_uygula": "Evet" if getattr(cari, "senet_limit_uygula", False) else "Hayır",
        "toplam_risk_limiti": _para_hucre(cari.toplam_risk_limiti),
        "toplam_limit_uygula": "Evet" if getattr(cari, "toplam_limit_uygula", False) else "Hayır",
        "risk_orani_ciro_cek": _para_hucre(getattr(cari, "risk_orani_ciro_cek", None)),
        "risk_orani_diger_cek": _para_hucre(getattr(cari, "risk_orani_diger_cek", None)),
        "risk_orani_senet": _para_hucre(getattr(cari, "risk_orani_senet", None)),
        "vade_farki_aylik_oran": _para_hucre(cari.vade_farki_aylik_oran),
        "vade_farki_yillik_oran": _para_hucre(cari.vade_farki_yillik_oran),
        "vade_farki_donem": getattr(cari, "vade_farki_donem", None) or "",
        "vade_farki_aciklama": _metin_kisalt(getattr(cari, "vade_farki_aciklama", None)),
        "muhasebe_borclu_kodu": cari.muhasebe_borclu_kodu or "",
        "muhasebe_alacakli_kodu": cari.muhasebe_alacakli_kodu or "",
        "muhasebe_satis_kodu": cari.muhasebe_satis_kodu or "",
        "muhasebe_alis_kodu": cari.muhasebe_alis_kodu or "",
        "muhasebe_kdv_satis_kodu": cari.muhasebe_kdv_satis_kodu or "",
        "muhasebe_kdv_alis_kodu": cari.muhasebe_kdv_alis_kodu or "",
        "toplam_borc": _para_hucre(ozet.get("toplam_borc")),
        "toplam_alacak": _para_hucre(ozet.get("toplam_alacak")),
        "bakiye": _para_hucre(ozet.get("bakiye")),
        # None = henüz hesaplanmadı → «Yükleniyor…» (sahte «0 gün» yok)
        "agirlikli": (
            "Yükleniyor…"
            if ozet.get("agirlikli_ortalama_gun") is None
            and ozet.get("valor_yukleniyor")
            else gecen_gun_goster(ozet.get("agirlikli_ortalama_gun"))
        ),
        "kapatilan_gun": gecen_gun_goster(ozet.get("odenen_ortalama_valor_gun")),
        "ozel_notlar": _metin_kisalt(cari.ozel_notlar),
        "uyari_notu": _metin_kisalt(cari.uyari_notu),
        "durum": "Aktif" if cari.aktif else "Pasif",
    }


def ozet_etiketleri(*, tedarikci_modu: bool = False) -> dict[str, str]:
    if tedarikci_modu:
        return {
            "borclu_sayisi": "Borçlu Cari Sayısı",
            "borclar_toplami": "Borçlar Toplamı",
            "alacakli_sayisi": "Alacaklı Cari Sayısı",
            "alacaklar_toplami": "Alacaklar Toplamı",
        }
    return {
        "borclu_sayisi": "Borçlu Müşteri Sayısı",
        "borclar_toplami": "Borçlar Toplamı",
        "alacakli_sayisi": "Alacaklı Müşteri Sayısı",
        "alacaklar_toplami": "Alacaklar Toplamı",
    }


def tablo_genisliklerini_kaydet(tablo: ttk.Treeview, ayarlar: dict) -> dict:
    """Kullanıcının başlıktan sürüklediği kolon genişliklerini ayara yazar ve kaydeder."""
    kolonlar = ayarlar.setdefault("kolonlar", {})
    degisti = False
    for anahtar in tablo["columns"]:
        try:
            w = int(tablo.column(anahtar, "width"))
        except (tk.TclError, TypeError, ValueError):
            continue
        cfg = kolonlar.setdefault(anahtar, {})
        if int(cfg.get("genislik") or 0) != w:
            cfg["genislik"] = max(40, min(w, 600))
            degisti = True
    if degisti:
        cari_liste_ayarlari_kaydet(ayarlar)
    return ayarlar


class CariListeKolonAyarDialog(tk.Toplevel):
    """Kolon göster/gizle, genişlik ve sıra."""

    def __init__(self, parent, ayarlar: dict, *, on_uygula: Callable[[dict], None] | None = None):
        super().__init__(parent)
        self.title("Cari Liste Kolon Ayarları")
        self.geometry("620x560")
        self.minsize(520, 400)
        self.transient(parent)
        self._on_uygula = on_uygula
        self.ayarlar = deepcopy(ayarlar or cari_liste_varsayilan_ayarlari())
        self._vars: dict[str, tk.BooleanVar] = {}
        self._genislik: dict[str, tk.StringVar] = {}
        self._sira: list[str] = list(self.ayarlar.get("sira") or [])
        for k, _b, _w, _g in CARI_LISTE_KOLONLARI:
            if k not in self._sira:
                self._sira.append(k)

        govde = ttk.Frame(self, padding=10)
        govde.pack(fill="both", expand=True)
        ttk.Label(
            govde,
            text="Cari kart alanları — görünürlük, genişlik (px) ve sıra (▲▼)",
            font=font(10, "bold", self),
        ).pack(anchor="w", pady=(0, 4))
        hizli = ttk.Frame(govde)
        hizli.pack(fill="x", pady=(0, 6))
        ttk.Button(hizli, text="Tümünü göster", command=self._hepsini_goster).pack(side="left")
        ttk.Button(hizli, text="Tümünü gizle*", command=self._hepsini_gizle).pack(side="left", padx=6)
        ttk.Label(hizli, text="* Kod / Ünvan zorunlu kalır", foreground="#666666").pack(side="left")

        canvas = tk.Canvas(govde, highlightthickness=0)
        scroll = ttk.Scrollbar(govde, orient="vertical", command=canvas.yview)
        self._ic = ttk.Frame(canvas)
        self._ic.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self._ic, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        basliklar = {k: b for k, b, _w, _g in CARI_LISTE_KOLONLARI}
        for anahtar, _baslik, varsayilan_w, _g in CARI_LISTE_KOLONLARI:
            cfg = (self.ayarlar.get("kolonlar") or {}).get(anahtar) or {}
            var = tk.BooleanVar(value=bool(cfg.get("gorunur", True)))
            if anahtar in CARI_LISTE_ZORUNLU:
                var.set(True)
            self._vars[anahtar] = var
            self._genislik[anahtar] = tk.StringVar(value=str(cfg.get("genislik") or varsayilan_w))
        self._basliklar = basliklar
        self._satirlari_ciz()

        alt = ttk.Frame(self, padding=10)
        alt.pack(fill="x")
        ttk.Button(alt, text="Varsayılan", command=self._varsayilan).pack(side="left")
        ttk.Button(alt, text="Uygula", command=self._uygula).pack(side="right", padx=(6, 0))
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")
        self.grab_set()

    def _satirlari_ciz(self):
        for w in self._ic.winfo_children():
            w.destroy()
        for i, anahtar in enumerate(self._sira):
            satir = ttk.Frame(self._ic)
            satir.pack(fill="x", pady=2)
            cb = ttk.Checkbutton(
                satir, text=self._basliklar[anahtar], variable=self._vars[anahtar], width=32
            )
            cb.pack(side="left")
            if anahtar in CARI_LISTE_ZORUNLU:
                cb.state(["disabled"])
            ttk.Spinbox(
                satir,
                from_=40,
                to=600,
                increment=10,
                width=6,
                textvariable=self._genislik[anahtar],
            ).pack(side="left", padx=(6, 6))
            yukari = ttk.Button(satir, text="▲", width=3, command=lambda a=anahtar: self._tasi(a, -1))
            yukari.pack(side="left")
            asagi = ttk.Button(satir, text="▼", width=3, command=lambda a=anahtar: self._tasi(a, 1))
            asagi.pack(side="left", padx=(2, 0))
            if i == 0:
                yukari.state(["disabled"])
            if i == len(self._sira) - 1:
                asagi.state(["disabled"])

    def _tasi(self, anahtar: str, yon: int):
        i = self._sira.index(anahtar)
        j = i + yon
        if not 0 <= j < len(self._sira):
            return
        self._sira[i], self._sira[j] = self._sira[j], self._sira[i]
        self._satirlari_ciz()

    def _hepsini_goster(self):
        for anahtar, var in self._vars.items():
            var.set(True)

    def _hepsini_gizle(self):
        for anahtar, var in self._vars.items():
            var.set(anahtar in CARI_LISTE_ZORUNLU)

    def _varsayilan(self):
        self.ayarlar = cari_liste_varsayilan_ayarlari()
        self._sira = [k for k, _b, _w, _g in CARI_LISTE_KOLONLARI]
        for anahtar, _b, w, g in CARI_LISTE_KOLONLARI:
            self._vars[anahtar].set(True if anahtar in CARI_LISTE_ZORUNLU else g)
            self._genislik[anahtar].set(str(w))
        self._satirlari_ciz()

    def _uygula(self):
        kolonlar = self.ayarlar.setdefault("kolonlar", {})
        varsayilan_w = {k: w for k, _b, w, _g in CARI_LISTE_KOLONLARI}
        for anahtar, var in self._vars.items():
            cfg = kolonlar.setdefault(anahtar, {})
            cfg["gorunur"] = True if anahtar in CARI_LISTE_ZORUNLU else bool(var.get())
            try:
                w = int(str(self._genislik[anahtar].get()).strip())
            except (TypeError, ValueError):
                w = int(cfg.get("genislik") or varsayilan_w[anahtar])
            cfg["genislik"] = max(40, min(w, 600))
        self.ayarlar["sira"] = list(self._sira)
        cari_liste_ayarlari_kaydet(self.ayarlar)
        self.ayarlar = cari_liste_ayarlari_yukle()
        if self._on_uygula:
            self._on_uygula(self.ayarlar)
        self.destroy()


class CariTopluGrupDialog(tk.Toplevel):
    """Seçili carilere sektör grubu toplu atama (önizleme + onay)."""

    def __init__(
        self,
        parent,
        *,
        secili_idler: list[int],
        kayit_ozet: list[dict],
        on_basarili: Callable | None = None,
    ):
        super().__init__(parent)
        self.title("Toplu Sektör Grubu Ata")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        self._secili = list(secili_idler)
        self._kayitlar = list(kayit_ozet)  # {id, kod, unvan, grup}
        self._on_basarili = on_basarili
        self._calisiyor = False
        self.result = None

        from database.kart_turu_service import KartTuruService

        try:
            sektorler = [s["ad"] for s in KartTuruService.sektor_listele(sadece_aktif=True)]
        except Exception:
            from database.cari_service import CariService

            sektorler = CariService.gruplari_listele()

        ust = ttk.Frame(self, padding=12)
        ust.pack(fill="both", expand=True)
        ttk.Label(
            ust,
            text=f"Seçili kayıt: {len(self._secili)}  |  Firma kapsamındaki sektör grubuna atanır.",
            wraplength=420,
        ).pack(anchor="w")

        satir = ttk.Frame(ust)
        satir.pack(fill="x", pady=(10, 4))
        ttk.Label(satir, text="Hedef sektör grubu:").pack(side="left")
        self.grup_cb = ttk.Combobox(satir, values=sektorler, state="readonly", width=28)
        self.grup_cb.pack(side="left", padx=8)
        if sektorler:
            self.grup_cb.set(sektorler[0])
        ttk.Button(satir, text="Yeni Grup…", command=self._yeni_grup).pack(side="left")

        self.mod_var = tk.StringVar(value="yalniz_bos")
        ttk.Radiobutton(
            ust,
            text="Yalnız grubu olmayanlara ata (farklı grubu olanlar atlanır)",
            variable=self.mod_var,
            value="yalniz_bos",
            command=self._onizleme_guncelle,
        ).pack(anchor="w", pady=(8, 0))
        ttk.Radiobutton(
            ust,
            text="Mevcut grubu değiştir (eski sektör grubu üzerine yazar; ana/alt tür değişmez)",
            variable=self.mod_var,
            value="degistir",
            command=self._onizleme_guncelle,
        ).pack(anchor="w")

        self.onizleme = ttk.Label(ust, text="", foreground="#333333", justify="left")
        self.onizleme.pack(anchor="w", pady=(10, 4))
        self.grup_cb.bind("<<ComboboxSelected>>", lambda _e: self._onizleme_guncelle())

        alt = ttk.Frame(ust)
        alt.pack(fill="x", pady=(12, 0))
        self.ata_btn = ttk.Button(alt, text="Ata", command=self._ata)
        self.ata_btn.pack(side="left")
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right")
        self._onizleme_guncelle()
        self.bind("<Escape>", lambda _e: self.destroy())

    def _yeni_grup(self):
        from tkinter import simpledialog, messagebox
        from database.kart_turu_service import KartTuruService

        ad = simpledialog.askstring("Yeni sektör grubu", "Grup adı:", parent=self)
        if not ad:
            return
        try:
            kayit = KartTuruService.sektor_kaydet({"ad": ad.strip(), "sektor_listesinde": True})
            ad_kayit = kayit.get("ad") if isinstance(kayit, dict) else str(kayit)
        except Exception as hata:
            messagebox.showerror("Grup", str(hata), parent=self)
            return
        degerler = list(self.grup_cb["values"])
        if ad_kayit not in degerler:
            degerler.append(ad_kayit)
            self.grup_cb["values"] = degerler
        self.grup_cb.set(ad_kayit)
        self._onizleme_guncelle()

    def _onizleme_guncelle(self):
        hedef = (self.grup_cb.get() or "").strip()
        degistir = self.mod_var.get() == "degistir"
        degisecek = 0
        zaten = 0
        farkli = 0
        for k in self._kayitlar:
            mevcut = (k.get("grup") or "").strip()
            if mevcut == hedef:
                zaten += 1
            elif not mevcut:
                degisecek += 1
            elif degistir:
                degisecek += 1
                farkli += 1
            else:
                farkli += 1
        self.onizleme.configure(
            text=(
                f"Hedef: {hedef or '—'}\n"
                f"Grubu değişecek: {degisecek}\n"
                f"Zaten hedef grupta: {zaten}\n"
                f"Farklı grubu olan: {farkli}"
                + ("" if degistir else " (atlanacak)")
            )
        )
        self.ata_btn.configure(
            text=f"{degisecek} Cariye Grup Ata" if degisecek else "Ata"
        )
        try:
            self.ata_btn.state(["!disabled"] if hedef and degisecek else ["disabled"])
        except tk.TclError:
            pass

    def _ata(self):
        from tkinter import messagebox
        from database.cari_service import CariService

        if self._calisiyor:
            return
        hedef = (self.grup_cb.get() or "").strip()
        if not hedef or not self._secili:
            messagebox.showwarning("Eksik", "Grup ve cari seçimi zorunlu.", parent=self)
            return
        self._calisiyor = True
        try:
            self.ata_btn.state(["disabled"])
        except tk.TclError:
            pass
        try:
            sonuc = CariService.toplu_sektor_grubu_ata(
                self._secili,
                hedef,
                mevcut_grubu_degistir=(self.mod_var.get() == "degistir"),
            )
        except Exception as hata:
            self._calisiyor = False
            try:
                self.ata_btn.state(["!disabled"])
            except tk.TclError:
                pass
            messagebox.showerror("Toplu atama", str(hata), parent=self)
            return
        self.result = sonuc
        messagebox.showinfo(
            "Toplu atama",
            (
                f"Atanan: {sonuc['atanan']}\n"
                f"Zaten grupta: {sonuc['zaten_grupta']}\n"
                f"Farklı grup nedeniyle atlanan: {sonuc['atlanan_farkli_grup']}\n"
                f"Bulunamayan: {sonuc['bulunamayan']}"
            ),
            parent=self,
        )
        if self._on_basarili:
            self._on_basarili(sonuc)
        self.destroy()
