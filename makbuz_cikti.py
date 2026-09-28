"""Tahsilat / ödeme / cari virman makbuzu çıktısı — A5 dikey makbuz; PDF (PyMuPDF) ve Word (python-docx).

Yalnız okur: makbuz, cari ve firma bilgisi okunur; hiçbir kayıt oluşturulmaz veya değiştirilmez.
Makbuz kimliği: kasa makbuzu için sayı (id), cari virman makbuzu için "V{id}".
PDF ve Word aynı milimetre düzenini (YERLESIM) kullanır:
- "A5": her makbuz ayrı A5 (148 × 210 mm) dikey sayfa
- "A4_IKILI": A4 yatay sayfada yan yana iki A5 makbuz (kesim çizgili)
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from invoice_print.amount_to_words import amount_to_words

A5 = "A5"
A4_IKILI = "A4_IKILI"
YERLESIMLER = {
    A5: "A5 dikey — sayfa başına tek makbuz (148 × 210 mm)",
    A4_IKILI: "A4 yatay — sayfaya iki makbuz (yan yana A5)",
}

MM = 72 / 25.4
A5_GEN, A5_YUK = 148.0, 210.0
A4_GEN, A4_YUK = 297.0, 210.0
MARJ = 10.0
ICERIK_GEN = A5_GEN - 2 * MARJ  # 128 mm

# Blok yükseklikleri (mm) — PDF ve Word birebir aynı
H_UST = 17.0
H_CIZGI = 2.5
H_BASLIK = 11.0
H_BILGI = 10.0  # iki satır
H_TUTAR = 17.0
H_TABLO_BAS = 6.0
H_TOPLAM = 6.0
H_ACIKLAMA = 13.0
H_IMZA_BAS, H_IMZA_AD, H_IMZA_TARIH, H_IMZA_ALAN = 5.0, 8.0, 7.0, 24.0
H_ALT = 5.0
BOSLUK = 2.0
IMZA_SUTUN = (48.0, 48.0, 32.0)
TABLO_SUTUN = (46.0, 52.0, 30.0)
BILGI_SUTUN = (40.0, 88.0)
# Cari virman: üç imza + kaşe; bağlı iki evrak satırı; mahsup metinli açıklama
IMZA_SUTUN_VIRMAN = (33.0, 33.0, 33.0, 29.0)
H_EVRAK = 7.0
H_VIRMAN_ACIKLAMA = 18.0

LACIVERT = "102A43"
SARI = "F4C542"
ACIK_SARI = "FFF6D6"
ACIK_MAVI = "E8EEF5"
CIZGI = "C9D3DE"
GRI = "5B6B7C"
KIRMIZI = "C0392B"


def _fitz():
    try:
        import pymupdf
    except ImportError:  # eski PyMuPDF sürümleri
        import fitz as pymupdf
    return pymupdf


def _rgb(hex_renk: str) -> tuple[float, float, float]:
    return tuple(int(hex_renk[i : i + 2], 16) / 255 for i in (0, 2, 4))


def para(tutar) -> str:
    metin = f"{Decimal(str(tutar or 0)):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{metin} ₺"


def tutar_yaziyla(tutar) -> str:
    return amount_to_words(tutar, "TRY")


def _satir_duzeni(adet: int) -> tuple[int, float, bool]:
    """(gösterilecek satır sayısı, satır yüksekliği mm, sıkışık mı) — sayfa taşmasın."""
    if adet <= 5:
        return max(3, adet), 7.0, False
    return min(adet, 7), 5.0, True


# ─── Veri ─────────────────────────────────────────────────────────
def firma_bilgisi() -> dict:
    """Aktif firmanın baskı bilgileri (firma kartı + fatura markası ayarları); boş alanlar boş kalır."""
    try:
        from invoice_print.branding import load_company_branding

        b = load_company_branding()
    except Exception:
        b = {}
    return firma_satirlari(b)


def firma_satirlari(b: dict) -> dict:
    adres = " ".join(x for x in (b.get("adres"), " / ".join(y for y in (b.get("ilce"), b.get("il")) if y)) if x)
    iletisim = "  ·  ".join(
        x
        for x in (
            f"Tel: {b['telefon']}" if b.get("telefon") else "",
            b.get("email") or "",
            b.get("web") or "",
        )
        if x
    )
    vergi = "  ·  ".join(
        x
        for x in (
            f"V.D.: {b['vergi_dairesi']}" if b.get("vergi_dairesi") else "",
            f"VKN: {b['vergi_no']}" if b.get("vergi_no") else "",
            f"MERSİS: {b['mersis']}" if b.get("mersis") else "",
        )
        if x
    )
    logo = b.get("logo_yolu")
    return {
        "unvan": (b.get("unvan") or "").strip(),
        "satirlar": [x for x in (adres, iletisim, vergi) if x],
        "logo_yolu": logo if logo and Path(logo).is_file() else None,
        "alt_bilgi": (b.get("alt_bilgi") or "").strip(),
    }


def virman_kimligi(virman_id) -> str:
    return f"V{int(virman_id)}"


def virman_id_coz(kimlik) -> int | None:
    """"V12" → 12 (cari virman makbuzu); kasa makbuzu kimliğinde None."""
    if isinstance(kimlik, str) and kimlik[:1].upper() == "V" and kimlik[1:].isdigit():
        return int(kimlik[1:])
    return None


def makbuz_cikti_verileri(makbuz_ids, firma: dict | None = None) -> list[dict]:
    """Seçilen makbuzların çıktı verisi (sırası korunur). Salt okunur."""
    from database.finans_service import FinansService

    firma = firma if firma is not None else firma_bilgisi()
    kk_adlari: dict[int, str] | None = None
    sonuc = []
    for makbuz_id in makbuz_ids:
        virman_id = virman_id_coz(makbuz_id)
        if virman_id is not None:
            from database.cari_virman_makbuz_service import CariVirmanMakbuzService

            k = CariVirmanMakbuzService.getir(virman_id)
            if k is None:
                raise ValueError(f"Cari virman makbuzu bulunamadı (id={virman_id}).")
            sonuc.append(_virman_verisi(k, firma))
            continue
        m = FinansService.kasa_makbuz_getir(int(makbuz_id))
        if m is None:
            raise ValueError(f"Makbuz bulunamadı (id={makbuz_id}).")
        satirlar = list(m.satirlar or [])
        if kk_adlari is None and any(s.kredi_karti_id for s in satirlar):
            kk_adlari = {k["id"]: k["etiket"] for k in FinansService.sirket_kredi_kartlari()}
        sonuc.append(_makbuz_verisi(m, satirlar, firma, kk_adlari or {}))
    return sonuc


def _makbuz_verisi(m, satirlar, firma: dict, kk_adlari: dict) -> dict:
    tahsilat = (m.makbuz_turu or "").upper() == "TAHSILAT"
    tarih = m.tarih.strftime("%d.%m.%Y") if m.tarih else ""
    odemeler = []
    for s in satirlar:
        h = s.finans_hesap
        hesap = kk_adlari.get(s.kredi_karti_id, h.hesap_adi if h else "") if s.kredi_karti_id else (h.hesap_adi if h else "")
        detay = []
        if s.kredi_karti_id:
            detay.append(f"Şirket kredi kartı · {int(s.taksit_sayisi or 1)} taksit")
        elif s.kart_tipi == "BANKA_KARTI":
            detay.append("Banka kartı")
        elif s.kart_tipi:
            detay.append(f"Kredi kartı · {int(s.taksit_sayisi or 1)} taksit")
        if s.tarih and m.tarih and s.tarih != m.tarih:
            detay.append(f"Tarih {s.tarih.strftime('%d.%m.%Y')}")
        if s.aciklama:
            detay.append(s.aciklama.strip())
        odemeler.append(
            {
                "yontem": (s.odeme_sekli or "").strip(),
                "hesap": hesap,
                "detay": " · ".join(detay),
                "tutar": para(s.tutar),
                "tutar_d": Decimal(str(s.tutar or 0)),
            }
        )
    if not odemeler and m.finans_hesap is not None:
        odemeler.append(
            {
                "yontem": "",
                "hesap": m.finans_hesap.hesap_adi,
                "detay": "",
                "tutar": para(m.tutar),
                "tutar_d": Decimal(str(m.tutar or 0)),
            }
        )
    cari = getattr(m, "cari", None)
    fatura_no = getattr(m, "bagli_fatura_no", None)
    return {
        "id": int(m.id),
        "tahsilat": tahsilat,
        "baslik": "TAHSİLAT MAKBUZU" if tahsilat else "ÖDEME MAKBUZU",
        "makbuz_no": (m.makbuz_no or "").strip(),
        "belge_no": m.belge_no or "",
        "belge_bilgi": (
            ("BELGE NO · BAĞLI SATIŞ FATURASI", f"{m.belge_no or ''} · {fatura_no}")
            if fatura_no
            else ("BELGE NO", m.belge_no or "")
        ),
        "tarih": tarih,
        "iptal": (m.durum or "") == "IPTAL",
        "cari_kodu": getattr(cari, "cari_kodu", "") or "",
        "cari_unvan": getattr(cari, "unvan", "") or "",
        "tutar_etiket": "TAHSİL EDİLEN TUTAR" if tahsilat else "ÖDENEN TUTAR",
        "tutar": para(m.tutar),
        "tutar_yaziyla": tutar_yaziyla(m.tutar),
        "odemeler": odemeler,
        "aciklama": (m.aciklama or "").strip(),
        "imzalar": (
            ("TESLİM EDEN / TAHSİL EDEN", "ÖDEMEYİ YAPAN")
            if tahsilat
            else ("ÖDEMEYİ YAPAN (FİRMA)", "TESLİM ALAN / TAHSİL EDEN")
        ),
        "firma": firma,
        "olusturma": datetime.now().strftime("%d.%m.%Y %H:%M"),
    }


def _virman_verisi(k, firma: dict) -> dict:
    from database.cari_virman_makbuz_service import VIRMAN_METNI

    musteri, tedarikci = getattr(k, "musteri", None), getattr(k, "tedarikci", None)
    m_kod, m_ad = getattr(musteri, "cari_kodu", "") or "", getattr(musteri, "unvan", "") or ""
    t_kod, t_ad = getattr(tedarikci, "cari_kodu", "") or "", getattr(tedarikci, "unvan", "") or ""
    return {
        "id": virman_kimligi(k.id),
        "virman": True,
        "tahsilat": True,
        "baslik": "CARİ VİRMAN MAKBUZU",
        "makbuz_no": (k.makbuz_no or "").strip(),
        "belge_no": k.belge_no or "",
        "tarih": k.tarih.strftime("%d.%m.%Y") if k.tarih else "",
        "iptal": (k.durum or "") == "IPTAL",
        "cari_kodu": m_kod,
        "cari_unvan": m_ad,
        "musteri_kodu": m_kod,
        "musteri_unvan": m_ad,
        "tedarikci_kodu": t_kod,
        "tedarikci_unvan": t_ad,
        "tutar_etiket": "VİRMAN TUTARI",
        "tutar": para(k.tutar),
        "tutar_yaziyla": tutar_yaziyla(k.tutar),
        "evraklar": [
            {
                "evrak": "Tahsilat evrakı",
                "detay": f"{m_kod} · müşteriden alacak azalır".strip(" ·"),
                "no": k.tahsilat_belge_no or "",
                "tutar": para(k.tutar),
            },
            {
                "evrak": "Ödeme evrakı",
                "detay": f"{t_kod} · tedarikçiye borç azalır".strip(" ·"),
                "no": k.odeme_belge_no or "",
                "tutar": para(k.tutar),
            },
        ],
        "odemeler": [],
        "virman_metni": VIRMAN_METNI,
        "aciklama": (k.aciklama or "").strip(),
        "imzalar": ("VİRMANI DÜZENLEYEN", "MÜŞTERİ YETKİLİSİ", "TEDARİKÇİ YETKİLİSİ"),
        "firma": firma,
        "olusturma": datetime.now().strftime("%d.%m.%Y %H:%M"),
    }


def _gosterilecek_odemeler(v: dict) -> tuple[list[dict], float, bool]:
    odemeler = list(v["odemeler"])
    adet, rh, sikisik = _satir_duzeni(len(odemeler))
    if len(odemeler) > adet:
        kalan = odemeler[adet - 1 :]
        toplam = sum((o["tutar_d"] for o in kalan), Decimal("0"))
        odemeler = odemeler[: adet - 1] + [
            {"yontem": f"Diğer {len(kalan)} ödeme satırı", "hesap": "", "detay": "", "tutar": para(toplam)}
        ]
    while len(odemeler) < adet:
        odemeler.append(None)
    return odemeler, rh, sikisik


# ─── Dosya adı / yazma ────────────────────────────────────────────
def _guvenli(metin: str) -> str:
    return re.sub(r"[^\w\-]+", "_", metin, flags=re.ASCII).strip("_") or "makbuz"


def dosya_adi(veriler: list[dict], yerlesim: str, uzanti: str) -> str:
    """Makbuz numarasıyla dosya adı: Tahsilat_Makbuzu_MKB-00001.pdf / Tahsilat_Makbuzlari_MKB-00001_MKB-00004_3_adet_A4.pdf"""
    if all(v.get("virman") for v in veriler):
        tur = "Cari_Virman"
    else:
        tur = "Tahsilat" if all(v["tahsilat"] for v in veriler) else ("Odeme" if not any(v["tahsilat"] for v in veriler) else "Kasa")
    nolar = [_guvenli(v["makbuz_no"] or v["belge_no"]) for v in veriler]
    ek = "_A4_ikili" if yerlesim == A4_IKILI else ""
    if len(nolar) == 1:
        return f"{tur}_Makbuzu_{nolar[0]}{ek}.{uzanti}"
    return f"{tur}_Makbuzlari_{nolar[0]}_{nolar[-1]}_{len(nolar)}_adet{ek}.{uzanti}"


def bos_dosya_yolu(yol: Path) -> Path:
    """Aynı adlı dosya varsa '(2)', '(3)' … ekli yeni ad."""
    yol = Path(yol)
    if not yol.exists():
        return yol
    i = 2
    while True:
        aday = yol.with_name(f"{yol.stem} ({i}){yol.suffix}")
        if not aday.exists():
            return aday
        i += 1


def _yaz(hedef: Path, veri: bytes, uzerine_yaz: bool) -> Path:
    hedef = Path(hedef)
    if hedef.exists() and not uzerine_yaz:
        raise FileExistsError(f"{hedef.name} zaten var. Üzerine yazmak için onay gerekir.")
    hedef.parent.mkdir(parents=True, exist_ok=True)
    gecici = hedef.with_name(f".{hedef.name}.tmp")
    gecici.write_bytes(veri)
    try:
        os.replace(gecici, hedef)
    except PermissionError as hata:
        gecici.unlink(missing_ok=True)
        raise PermissionError(f"{hedef.name} başka bir programda açık olabilir; kapatıp tekrar deneyin.") from hata
    return hedef


# ─── PDF ─────────────────────────────────────────────────────────
def _font_dosyalari() -> tuple[str | None, str | None]:
    klasor = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for normal, kalin in (("segoeui.ttf", "segoeuib.ttf"), ("arial.ttf", "arialbd.ttf"), ("calibri.ttf", "calibrib.ttf")):
        if (klasor / normal).is_file() and (klasor / kalin).is_file():
            return str(klasor / normal), str(klasor / kalin)
    return None, None


class _PdfCizici:
    def __init__(self, page, ox: float, oy: float):
        fitz = _fitz()
        self.fitz = fitz
        self.page = page
        self.ox, self.oy = ox, oy
        normal, kalin = _font_dosyalari()
        if normal:
            page.insert_font(fontname="mkr", fontfile=normal)
            page.insert_font(fontname="mkb", fontfile=kalin)
            self.fontlar = {False: "mkr", True: "mkb"}
            self._olcu = {False: fitz.Font(fontfile=normal), True: fitz.Font(fontfile=kalin)}
        else:
            self.fontlar = {False: "helv", True: "hebo"}
            self._olcu = {False: fitz.Font("helv"), True: fitz.Font("hebo")}

    def r(self, x, y, w, h):
        return self.fitz.Rect(
            (self.ox + x) * MM, (self.oy + y) * MM, (self.ox + x + w) * MM, (self.oy + y + h) * MM
        )

    def kutu(self, x, y, w, h, *, cizgi=CIZGI, dolgu=None, kalinlik=0.6, kesik=None):
        self.page.draw_rect(
            self.r(x, y, w, h),
            color=_rgb(cizgi) if cizgi else None,
            fill=_rgb(dolgu) if dolgu else None,
            width=kalinlik if cizgi else 0,
            dashes=kesik,
        )

    def cizgi(self, x1, y1, x2, y2, *, renk=CIZGI, kalinlik=0.6, kesik=None):
        self.page.draw_line(
            self.fitz.Point((self.ox + x1) * MM, (self.oy + y1) * MM),
            self.fitz.Point((self.ox + x2) * MM, (self.oy + y2) * MM),
            color=_rgb(renk),
            width=kalinlik,
            dashes=kesik,
        )

    def yazi(self, x, y, w, h, metin, boyut=8.0, *, kalin=False, renk="1F2933", hiza="sol", en_kucuk=5.5):
        if not metin:
            return
        hizalar = {"sol": 0, "orta": 1, "sag": 2}
        # Kutu yüksekliği görsel satır yüksekliğidir; yazı tipinin iniş payı için alta 1,5 mm tolerans
        rect = self.r(x, y, w, h + 1.5)
        boy = boyut
        while boy >= en_kucuk:
            kalan = self.page.insert_textbox(
                rect, metin, fontsize=boy, fontname=self.fontlar[kalin], color=_rgb(renk), align=hizalar[hiza]
            )
            if kalan >= 0:
                return
            boy -= 0.5
        # Hiç sığmıyorsa tek satıra kısalt (taşma/kesilme yerine üç nokta)
        olcu = self._olcu[kalin]
        kisa = " ".join(metin.split())
        if olcu.text_length(kisa, fontsize=en_kucuk) > rect.width - 2:
            while kisa and olcu.text_length(kisa + "…", fontsize=en_kucuk) > rect.width - 2:
                kisa = kisa[:-1]
            kisa += "…"
        genislik = olcu.text_length(kisa, fontsize=en_kucuk)
        bosluk = rect.width - genislik
        dx = {"sol": 0, "orta": bosluk / 2, "sag": bosluk}[hiza]
        self.page.insert_text(
            self.fitz.Point(rect.x0 + max(0, dx), rect.y0 + olcu.ascender * en_kucuk),
            kisa,
            fontsize=en_kucuk,
            fontname=self.fontlar[kalin],
            color=_rgb(renk),
        )

    def resim(self, x, y, w, h, yol):
        try:
            self.page.insert_image(self.r(x, y, w, h), filename=yol, keep_proportion=True)
        except Exception:
            pass

    def filigran(self, metin, x, y, boyut):
        p = self.fitz.Point((self.ox + x) * MM, (self.oy + y) * MM)
        self.page.insert_text(
            p,
            metin,
            fontsize=boyut,
            fontname=self.fontlar[True],
            color=_rgb(KIRMIZI),
            fill_opacity=0.18,
            morph=(p, self.fitz.Matrix(35)),
        )


def _makbuz_ciz(c: _PdfCizici, v: dict) -> None:
    if v.get("virman"):
        _virman_ciz(c, v)
        return
    x0, w = MARJ, ICERIK_GEN
    y = _ust_ciz(c, v)
    y = _bilgi_ciz(
        c,
        y,
        (
            (("TARİH", v["tarih"]), v["belge_bilgi"]),
            (("CARİ KODU", v["cari_kodu"]), ("CARİ ADI / ÜNVANI", v["cari_unvan"])),
        ),
    )
    y = _tutar_ciz(c, y, v)

    # Ödeme tablosu
    odemeler, rh, sikisik = _gosterilecek_odemeler(v)
    basliklar = ("ÖDEME YÖNTEMİ", "KASA / BANKA / POS HESABI", "TUTAR")
    xx = x0
    for b, sw in zip(basliklar, TABLO_SUTUN):
        c.kutu(xx, y, sw, H_TABLO_BAS, dolgu=ACIK_MAVI)
        c.yazi(xx + 1.6, y + 1.3, sw - 3, 3.8, b, 6.5, kalin=True, renk=LACIVERT, hiza="sag" if b == "TUTAR" else "sol")
        xx += sw
    y += H_TABLO_BAS
    for o in odemeler:
        xx = x0
        for i, sw in enumerate(TABLO_SUTUN):
            c.kutu(xx, y, sw, rh)
            if o:
                if i == 0:
                    if sikisik:
                        c.yazi(xx + 1.6, y + 0.7, sw - 3, rh - 1, o["yontem"], 7, renk="1F2933")
                    else:
                        c.yazi(xx + 1.6, y + 0.6, sw - 3, 3.6, o["yontem"], 7.3, kalin=True, renk="1F2933")
                        c.yazi(xx + 1.6, y + 3.7, sw - 3, 3.2, o["detay"], 6, renk=GRI, en_kucuk=4.8)
                elif i == 1:
                    c.yazi(xx + 1.6, y + (0.7 if sikisik else 1.4), sw - 3, rh - 1.2, o["hesap"], 7.3, renk="1F2933")
                else:
                    c.yazi(xx + 1.6, y + (0.7 if sikisik else 1.4), sw - 3, 4, o["tutar"], 7.8, kalin=True, renk="1F2933", hiza="sag")
            xx += sw
        y += rh
    c.kutu(x0, y, w, H_TOPLAM, dolgu=ACIK_MAVI)
    c.yazi(x0 + 1.6, y + 1.2, TABLO_SUTUN[0] + TABLO_SUTUN[1] - 3, 4, "TOPLAM", 7.5, kalin=True, renk=LACIVERT)
    c.yazi(x0 + w - TABLO_SUTUN[2] + 1.6, y + 1.0, TABLO_SUTUN[2] - 3, 4.4, v["tutar"], 8.5, kalin=True, renk=LACIVERT, hiza="sag")
    y += H_TOPLAM + BOSLUK

    # Açıklama
    c.kutu(x0, y, w, H_ACIKLAMA)
    c.yazi(x0 + 1.6, y + 0.8, 40, 3.2, "AÇIKLAMA", 6.3, kalin=True, renk=GRI)
    c.yazi(x0 + 1.6, y + 3.9, w - 3, H_ACIKLAMA - 4.5, v["aciklama"], 8, renk="1F2933", en_kucuk=5.5)
    y += H_ACIKLAMA + 3

    y = _imza_ciz(c, y, v["imzalar"], IMZA_SUTUN)
    _alt_ciz(c, y, v)


def _virman_ciz(c: _PdfCizici, v: dict) -> None:
    """Cari virman makbuzu: ödeme yöntemi / kasa-banka-POS alanı yoktur; bağlı iki cari evrakı gösterilir."""
    x0, w = MARJ, ICERIK_GEN
    y = _ust_ciz(c, v)
    y = _bilgi_ciz(
        c,
        y,
        (
            (("TARİH", v["tarih"]), ("BELGE NO", v["belge_no"])),
            (("MÜŞTERİ KODU", v["musteri_kodu"]), ("TAHSİLAT YAPILAN MÜŞTERİ", v["musteri_unvan"])),
            (("TEDARİKÇİ KODU", v["tedarikci_kodu"]), ("ÖDEME YAPILAN TEDARİKÇİ", v["tedarikci_unvan"])),
        ),
    )
    y = _tutar_ciz(c, y, v)

    basliklar = ("BAĞLI EVRAK", "EVRAK NO", "TUTAR")
    xx = x0
    for b, sw in zip(basliklar, TABLO_SUTUN):
        c.kutu(xx, y, sw, H_TABLO_BAS, dolgu=ACIK_MAVI)
        c.yazi(xx + 1.6, y + 1.3, sw - 3, 3.8, b, 6.5, kalin=True, renk=LACIVERT, hiza="sag" if b == "TUTAR" else "sol")
        xx += sw
    y += H_TABLO_BAS
    for e in v["evraklar"]:
        xx = x0
        for i, sw in enumerate(TABLO_SUTUN):
            c.kutu(xx, y, sw, H_EVRAK)
            if i == 0:
                c.yazi(xx + 1.6, y + 0.6, sw - 3, 3.6, e["evrak"], 7.3, kalin=True, renk="1F2933")
                c.yazi(xx + 1.6, y + 3.7, sw - 3, 3.2, e["detay"], 6, renk=GRI, en_kucuk=4.8)
            elif i == 1:
                c.yazi(xx + 1.6, y + 1.4, sw - 3, 4, e["no"], 7.8, kalin=True, renk="1F2933")
            else:
                c.yazi(xx + 1.6, y + 1.4, sw - 3, 4, e["tutar"], 7.8, kalin=True, renk="1F2933", hiza="sag")
            xx += sw
        y += H_EVRAK
    y += BOSLUK

    c.kutu(x0, y, w, H_VIRMAN_ACIKLAMA)
    c.yazi(x0 + 1.6, y + 0.8, 40, 3.2, "AÇIKLAMA", 6.3, kalin=True, renk=GRI)
    c.yazi(x0 + 1.6, y + 3.9, w - 3, 7.2, v["virman_metni"], 7.8, kalin=True, renk="1F2933", en_kucuk=6)
    c.yazi(x0 + 1.6, y + 11.4, w - 3, 5.6, v["aciklama"], 7.3, renk="1F2933", en_kucuk=5)
    y += H_VIRMAN_ACIKLAMA + 3

    y = _imza_ciz(c, y, v["imzalar"], IMZA_SUTUN_VIRMAN)
    _alt_ciz(c, y, v)


def _ust_ciz(c: _PdfCizici, v: dict) -> float:
    """Firma başlığı + başlık bandı (makbuz no); sonraki bloğun y'si."""
    x0, w = MARJ, ICERIK_GEN
    y = MARJ
    f = v["firma"]

    # Firma başlığı
    logo_w = 34.0 if f.get("logo_yolu") else 0.0
    if logo_w:
        c.resim(x0 + w - logo_w, y, logo_w, H_UST - 1, f["logo_yolu"])
    metin_w = w - logo_w - (3 if logo_w else 0)
    c.yazi(x0, y, metin_w, 6.2, f.get("unvan") or "", 11, kalin=True, renk=LACIVERT)
    yy = y + 6.4
    for satir in f.get("satirlar", [])[:3]:
        c.yazi(x0, yy, metin_w, 3.6, satir, 7.2, renk=GRI, en_kucuk=5)
        yy += 3.5
    y += H_UST
    c.kutu(x0, y + 0.3, w, 0.9, cizgi=None, dolgu=SARI)
    y += H_CIZGI

    # Başlık bandı + makbuz no
    no_w = 44.0
    c.kutu(x0, y, w - no_w, H_BASLIK, cizgi=None, dolgu=LACIVERT)
    c.yazi(x0 + 3, y + 2.6, w - no_w - 4, 7, v["baslik"], 14, kalin=True, renk="FFFFFF")
    c.kutu(x0 + w - no_w, y, no_w, H_BASLIK, cizgi=None, dolgu=SARI)
    etiket, no = ("MAKBUZ NO", v["makbuz_no"]) if v["makbuz_no"] else ("BELGE NO", v["belge_no"])
    c.yazi(x0 + w - no_w + 2, y + 0.9, no_w - 4, 3.4, etiket, 6.5, kalin=True, renk=LACIVERT)
    c.yazi(x0 + w - no_w + 2, y + 4.0, no_w - 4, 6.2, no, 12, kalin=True, renk=LACIVERT)
    return y + H_BASLIK + BOSLUK


def _bilgi_ciz(c: _PdfCizici, y: float, satirlar) -> float:
    x0 = MARJ
    for satir in satirlar:
        xx = x0
        for (etiket, deger), sw in zip(satir, BILGI_SUTUN):
            c.kutu(xx, y, sw, H_BILGI)
            c.yazi(xx + 1.6, y + 0.8, sw - 3, 3.2, etiket, 6.3, kalin=True, renk=GRI)
            c.yazi(xx + 1.6, y + 3.9, sw - 3, 5.8, deger, 9.5, kalin=True, renk="1F2933", en_kucuk=6)
            xx += sw
        y += H_BILGI
    return y + BOSLUK


def _tutar_ciz(c: _PdfCizici, y: float, v: dict) -> float:
    x0, w = MARJ, ICERIK_GEN
    c.kutu(x0, y, w, H_TUTAR, cizgi=SARI, dolgu=ACIK_SARI, kalinlik=1)
    c.yazi(x0 + 2, y + 1.2, 60, 3.6, v["tutar_etiket"], 7, kalin=True, renk=LACIVERT)
    if v["iptal"]:
        c.yazi(x0 + 2, y + 5, 50, 5, "İPTAL EDİLMİŞTİR", 10, kalin=True, renk=KIRMIZI)
    c.yazi(x0 + 50, y + 1.0, w - 52, 8.5, v["tutar"], 17, kalin=True, renk=LACIVERT, hiza="sag")
    c.yazi(x0 + 2, y + 10.2, w - 4, 6.4, v["tutar_yaziyla"], 7.8, renk="1F2933", en_kucuk=5.5)
    return y + H_TUTAR + BOSLUK


def _imza_ciz(c: _PdfCizici, y: float, imzalar, sutunlar) -> float:
    """Boş ad-soyad / tarih / imza alanları + firma kaşesi yeri (son sütun); imza varmış gibi bir şey çizilmez."""
    xx = MARJ
    basliklar = (*imzalar, "FİRMA KAŞESİ")
    imza_h = H_IMZA_BAS + H_IMZA_AD + H_IMZA_TARIH + H_IMZA_ALAN
    for i, (b, sw) in enumerate(zip(basliklar, sutunlar)):
        c.kutu(xx, y, sw, imza_h, cizgi=LACIVERT, kalinlik=0.7)
        c.kutu(xx, y, sw, H_IMZA_BAS, cizgi=LACIVERT, dolgu=ACIK_MAVI, kalinlik=0.7)
        c.yazi(xx + 1, y + 1.0, sw - 2, 3.6, b, 6.3, kalin=True, renk=LACIVERT, hiza="orta")
        if i < len(imzalar):
            yy = y + H_IMZA_BAS
            for etiket, h in (("Adı Soyadı", H_IMZA_AD), ("Tarih", H_IMZA_TARIH)):
                c.yazi(xx + 1.6, yy + h - 4.2, 18, 3.4, f"{etiket}:", 6.5, renk=GRI)
                c.cizgi(xx + 17, yy + h - 1.2, xx + sw - 2, yy + h - 1.2, kesik="[1 1] 0", renk=GRI, kalinlik=0.4)
                yy += h
            c.yazi(xx + 1.6, yy + 0.8, 12, 3.4, "İmza:", 6.5, renk=GRI)
        else:
            c.kutu(xx + 3, y + H_IMZA_BAS + 3, sw - 6, imza_h - H_IMZA_BAS - 6, cizgi=CIZGI, kesik="[2 2] 0")
        xx += sw
    return y + imza_h + 1.5


def _alt_ciz(c: _PdfCizici, y: float, v: dict) -> None:
    x0, w = MARJ, ICERIK_GEN
    f = v["firma"]
    alt = f"Belge No: {v['belge_no']}  ·  Oluşturma: {v['olusturma']}"
    if f.get("alt_bilgi"):
        alt = f"{f['alt_bilgi']}  ·  {alt}"
    c.yazi(x0, y, w, H_ALT, alt, 6, renk=GRI, hiza="orta", en_kucuk=4.5)

    if v["iptal"]:
        c.filigran("İPTAL", 34, 138, 64)


def pdf_uret(veriler: list[dict], yerlesim: str = A5) -> bytes:
    fitz = _fitz()

    if not veriler:
        raise ValueError("Çıktı için en az bir makbuz seçin.")
    a5 = fitz.open()
    for v in veriler:
        page = a5.new_page(width=A5_GEN * MM, height=A5_YUK * MM)
        _makbuz_ciz(_PdfCizici(page, 0, 0), v)
    if yerlesim == A4_IKILI:
        doc = fitz.open()
        for i in range(0, len(veriler), 2):
            page = doc.new_page(width=A4_GEN * MM, height=A4_YUK * MM)
            yarim = A4_GEN / 2
            page.show_pdf_page(fitz.Rect(0, 0, yarim * MM, A4_YUK * MM), a5, i)
            if i + 1 < len(veriler):
                page.show_pdf_page(fitz.Rect(yarim * MM, 0, A4_GEN * MM, A4_YUK * MM), a5, i + 1)
            page.draw_line(
                fitz.Point(yarim * MM, 4 * MM),
                fitz.Point(yarim * MM, (A4_YUK - 4) * MM),
                color=_rgb("9AA5B1"),
                width=0.5,
                dashes="[3 3] 0",
            )
    else:
        doc = a5
    doc.set_metadata(
        {
            "title": ", ".join(v["makbuz_no"] or v["belge_no"] for v in veriler),
            "subject": (
                "Cari Virman Makbuzu"
                if all(v.get("virman") for v in veriler)
                else ("Tahsilat Makbuzu" if veriler[0]["tahsilat"] else "Ödeme Makbuzu")
            ),
            "creator": "Cin Muhasebe",
        }
    )
    try:
        doc.subset_fonts()
    except Exception:
        pass
    _tire_eslemesini_duzelt(doc)
    return doc.tobytes(garbage=3, deflate=True)


def _tire_eslemesini_duzelt(doc) -> None:
    # Segoe UI'da '-' ve U+2010 aynı glif; ToUnicode U+2010 yazınca PDF'te "MKB-00001" aranamaz / kopyalanamaz.
    for xref in range(1, doc.xref_length()):
        try:
            if not doc.xref_is_stream(xref):
                continue
            akis = doc.xref_stream(xref)
        except Exception:
            continue
        if akis and b"begincmap" in akis and b"<2010>" in akis:
            doc.update_stream(xref, akis.replace(b"<2010>", b"<002d>"))


def pdf_kaydet(veriler: list[dict], hedef, yerlesim: str = A5, *, uzerine_yaz: bool = False) -> Path:
    return _yaz(Path(hedef), pdf_uret(veriler, yerlesim), uzerine_yaz)


def onizleme_goruntuleri(pdf: bytes, genislik_px: int) -> list[bytes]:
    """PDF sayfalarını PNG olarak (önizleme = yazdırılacak dosyanın kendisi)."""
    fitz = _fitz()

    doc = fitz.open(stream=pdf, filetype="pdf")
    sonuc = []
    for page in doc:
        olcek = max(0.2, genislik_px / page.rect.width)
        sonuc.append(page.get_pixmap(matrix=fitz.Matrix(olcek, olcek), alpha=False).tobytes("png"))
    return sonuc


# ─── Word ────────────────────────────────────────────────────────
def _docx_yardimcilari():
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    def eleman(ad, **nitelikler):
        e = OxmlElement(ad)
        for k, deger in nitelikler.items():
            e.set(qn(k), str(deger))
        return e

    return eleman, qn


def _sirali_ekle(ebeveyn, yeni, sonrakiler: tuple[str, ...]) -> None:
    """OOXML şema sırası: yeni öğeyi, kendisinden sonra gelmesi gereken ilk öğenin önüne ekler."""
    _eleman, qn = _docx_yardimcilari()
    for eski in ebeveyn.findall(yeni.tag):
        ebeveyn.remove(eski)
    etiketler = {qn(f"w:{ad}") for ad in sonrakiler}
    for cocuk in ebeveyn:
        if cocuk.tag in etiketler:
            cocuk.addprevious(yeni)
            return
    ebeveyn.append(yeni)


_TCPR_BORDERS_SONRASI = ("shd", "noWrap", "tcMar", "textDirection", "tcFitText", "vAlign", "hideMark")
_TCPR_SHD_SONRASI = _TCPR_BORDERS_SONRASI[1:]


def docx_uret(veriler: list[dict], yerlesim: str = A5) -> bytes:
    import io

    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.enum.text import WD_BREAK
    from docx.shared import Mm, Pt

    if not veriler:
        raise ValueError("Çıktı için en az bir makbuz seçin.")
    eleman, qn = _docx_yardimcilari()
    doc = Document()
    for p in list(doc.paragraphs):
        p._element.getparent().remove(p._element)
    normal = doc.styles["Normal"]
    normal.font.name = "Segoe UI"
    normal.font.size = Pt(8)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Segoe UI")
    pf = normal.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    pf.line_spacing = 1.0

    bolum = doc.sections[0]
    if yerlesim == A4_IKILI:
        bolum.orientation = WD_ORIENT.LANDSCAPE
        bolum.page_width, bolum.page_height = Mm(A4_GEN), Mm(A4_YUK)
        cols = bolum._sectPr.find(qn("w:cols"))
        if cols is None:
            cols = eleman("w:cols")
            bolum._sectPr.append(cols)
        cols.set(qn("w:num"), "2")
        cols.set(qn("w:space"), str(round(2 * MARJ * 56.692)))
        cols.set(qn("w:sep"), "1")
    else:
        bolum.orientation = WD_ORIENT.PORTRAIT
        bolum.page_width, bolum.page_height = Mm(A5_GEN), Mm(A5_YUK)
    for kenar in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(bolum, kenar, Mm(MARJ))
    bolum.header_distance = bolum.footer_distance = Mm(0)

    for i, v in enumerate(veriler):
        _docx_makbuz(doc, v)
        if i < len(veriler) - 1:
            p = _docx_bosluk(doc, 1)
            p.add_run().add_break(WD_BREAK.COLUMN if yerlesim == A4_IKILI else WD_BREAK.PAGE)
    _docx_bosluk(doc, 1)  # Word gövdenin tabloyla bitmesine izin vermez; boş sayfa açmasın diye 1 mm
    tampon = io.BytesIO()
    doc.core_properties.title = ", ".join(v["makbuz_no"] or v["belge_no"] for v in veriler)
    doc.core_properties.author = veriler[0]["firma"].get("unvan") or "Cin Muhasebe"
    doc.save(tampon)
    return tampon.getvalue()


def docx_kaydet(veriler: list[dict], hedef, yerlesim: str = A5, *, uzerine_yaz: bool = False) -> Path:
    return _yaz(Path(hedef), docx_uret(veriler, yerlesim), uzerine_yaz)


def _docx_bosluk(doc, mm: float):
    from docx.enum.text import WD_LINE_SPACING
    from docx.shared import Mm, Pt

    p = doc.add_paragraph()
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    p.paragraph_format.line_spacing = Mm(mm)
    p.paragraph_format.space_after = Pt(0)
    r = p.add_run("")
    r.font.size = Pt(1)
    return p


def _docx_tablo(doc, satir: int, sutunlar_mm, yukseklikler_mm):
    from docx.enum.table import WD_ROW_HEIGHT_RULE, WD_TABLE_ALIGNMENT
    from docx.shared import Mm

    eleman, qn = _docx_yardimcilari()
    t = doc.add_table(rows=satir, cols=len(sutunlar_mm))
    t.alignment = WD_TABLE_ALIGNMENT.LEFT
    t.autofit = False
    tblPr = t._tbl.tblPr
    _sirali_ekle(
        tblPr,
        eleman("w:tblInd", **{"w:w": "0", "w:type": "dxa"}),
        ("tblBorders", "shd", "tblLayout", "tblCellMar", "tblLook", "tblCaption", "tblDescription"),
    )
    _sirali_ekle(
        tblPr, eleman("w:tblLayout", **{"w:type": "fixed"}), ("tblCellMar", "tblLook", "tblCaption", "tblDescription")
    )
    mar = eleman("w:tblCellMar")
    for kenar, deger in (("top", 0), ("left", 85), ("bottom", 0), ("right", 85)):
        mar.append(eleman(f"w:{kenar}", **{"w:w": str(deger), "w:type": "dxa"}))
    _sirali_ekle(tblPr, mar, ("tblLook", "tblCaption", "tblDescription"))
    grid = t._tbl.tblGrid
    for gc, w in zip(grid.findall(qn("w:gridCol")), sutunlar_mm):
        gc.set(qn("w:w"), str(round(w * 56.692)))
    for r, h in zip(t.rows, yukseklikler_mm):
        r.height = Mm(h)
        r.height_rule = WD_ROW_HEIGHT_RULE.EXACTLY
        for cell, w in zip(r.cells, sutunlar_mm):
            cell.width = Mm(w)
    return t


def _hucre_bicim(cell, *, dolgu=None, cerceve=CIZGI, kalinlik=4, dikey="top", kesik=False, cizgisiz=()):
    from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT

    eleman, _qn = _docx_yardimcilari()
    tcPr = cell._tc.get_or_add_tcPr()
    if cerceve:
        kenarlar = eleman("w:tcBorders")
        for kenar in ("top", "left", "bottom", "right"):
            if kenar in cizgisiz:
                kenarlar.append(eleman(f"w:{kenar}", **{"w:val": "nil"}))
                continue
            kenarlar.append(
                eleman(
                    f"w:{kenar}",
                    **{"w:val": "dashed" if kesik else "single", "w:sz": str(kalinlik), "w:space": "0", "w:color": cerceve},
                )
            )
        _sirali_ekle(tcPr, kenarlar, _TCPR_BORDERS_SONRASI)
    if dolgu:
        _sirali_ekle(tcPr, eleman("w:shd", **{"w:val": "clear", "w:color": "auto", "w:fill": dolgu}), _TCPR_SHD_SONRASI)
    cell.vertical_alignment = {
        "top": WD_CELL_VERTICAL_ALIGNMENT.TOP,
        "center": WD_CELL_VERTICAL_ALIGNMENT.CENTER,
        "bottom": WD_CELL_VERTICAL_ALIGNMENT.BOTTOM,
    }[dikey]


def _yazi(cell_veya_p, metin, boyut=8.0, *, kalin=False, renk="1F2933", hiza="sol", yeni=False, italik=False):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    if hasattr(cell_veya_p, "paragraphs"):
        p = cell_veya_p.add_paragraph() if yeni else cell_veya_p.paragraphs[0]
    else:
        p = cell_veya_p
    p.alignment = {"sol": WD_ALIGN_PARAGRAPH.LEFT, "orta": WD_ALIGN_PARAGRAPH.CENTER, "sag": WD_ALIGN_PARAGRAPH.RIGHT}[hiza]
    p.paragraph_format.space_after = Pt(0)
    r = p.add_run(metin or "")
    r.font.size = Pt(boyut)
    r.font.bold = kalin
    r.font.italic = italik
    r.font.color.rgb = RGBColor.from_string(renk)
    return p


def _kenarsiz(t):
    for r in t.rows:
        for c in r.cells:
            _hucre_bicim(c, cerceve=None)


def _docx_makbuz(doc, v: dict) -> None:
    if v.get("virman"):
        _docx_virman(doc, v)
        return
    _docx_ust(doc, v)
    _docx_bilgi(
        doc,
        (
            (("TARİH", v["tarih"]), v["belge_bilgi"]),
            (("CARİ KODU", v["cari_kodu"]), ("CARİ ADI / ÜNVANI", v["cari_unvan"])),
        ),
    )
    _docx_tutar(doc, v)

    # Ödeme tablosu
    odemeler, rh, sikisik = _gosterilecek_odemeler(v)
    yuk = (H_TABLO_BAS, *([rh] * len(odemeler)), H_TOPLAM)
    t = _docx_tablo(doc, len(yuk), TABLO_SUTUN, yuk)
    for c, baslik in enumerate(("ÖDEME YÖNTEMİ", "KASA / BANKA / POS HESABI", "TUTAR")):
        cell = t.cell(0, c)
        _hucre_bicim(cell, dolgu=ACIK_MAVI, dikey="center")
        _yazi(cell, baslik, 6.5, kalin=True, renk=LACIVERT, hiza="sag" if c == 2 else "sol")
    for r, o in enumerate(odemeler, start=1):
        for c in range(3):
            _hucre_bicim(t.cell(r, c), dikey="center" if sikisik else "top")
        if not o:
            continue
        if sikisik:
            _yazi(t.cell(r, 0), o["yontem"], 7)
        else:
            _yazi(t.cell(r, 0), o["yontem"], 7.3, kalin=True)
            if o["detay"]:
                _yazi(t.cell(r, 0), o["detay"], 6, renk=GRI, yeni=True)
        _yazi(t.cell(r, 1), o["hesap"], 7.3)
        _yazi(t.cell(r, 2), o["tutar"], 7.8, kalin=True, hiza="sag")
    son = len(yuk) - 1
    toplam_sol = t.cell(son, 0).merge(t.cell(son, 1))
    _hucre_bicim(toplam_sol, dolgu=ACIK_MAVI, dikey="center")
    _yazi(toplam_sol, "TOPLAM", 7.5, kalin=True, renk=LACIVERT)
    _hucre_bicim(t.cell(son, 2), dolgu=ACIK_MAVI, dikey="center")
    _yazi(t.cell(son, 2), v["tutar"], 8.5, kalin=True, renk=LACIVERT, hiza="sag")
    _docx_bosluk(doc, BOSLUK)

    # Açıklama
    t = _docx_tablo(doc, 1, (ICERIK_GEN,), (H_ACIKLAMA,))
    _hucre_bicim(t.cell(0, 0))
    _yazi(t.cell(0, 0), "AÇIKLAMA", 6.3, kalin=True, renk=GRI)
    if v["aciklama"]:
        _yazi(t.cell(0, 0), v["aciklama"], 8 if len(v["aciklama"]) < 180 else 6.5, yeni=True)
    _docx_bosluk(doc, 3)

    _docx_imza(doc, v["imzalar"], IMZA_SUTUN)
    _docx_alt(doc, v)


def _docx_virman(doc, v: dict) -> None:
    _docx_ust(doc, v)
    _docx_bilgi(
        doc,
        (
            (("TARİH", v["tarih"]), ("BELGE NO", v["belge_no"])),
            (("MÜŞTERİ KODU", v["musteri_kodu"]), ("TAHSİLAT YAPILAN MÜŞTERİ", v["musteri_unvan"])),
            (("TEDARİKÇİ KODU", v["tedarikci_kodu"]), ("ÖDEME YAPILAN TEDARİKÇİ", v["tedarikci_unvan"])),
        ),
    )
    _docx_tutar(doc, v)

    yuk = (H_TABLO_BAS, *([H_EVRAK] * len(v["evraklar"])))
    t = _docx_tablo(doc, len(yuk), TABLO_SUTUN, yuk)
    for c, baslik in enumerate(("BAĞLI EVRAK", "EVRAK NO", "TUTAR")):
        cell = t.cell(0, c)
        _hucre_bicim(cell, dolgu=ACIK_MAVI, dikey="center")
        _yazi(cell, baslik, 6.5, kalin=True, renk=LACIVERT, hiza="sag" if c == 2 else "sol")
    for r, e in enumerate(v["evraklar"], start=1):
        _hucre_bicim(t.cell(r, 0))
        _yazi(t.cell(r, 0), e["evrak"], 7.3, kalin=True)
        _yazi(t.cell(r, 0), e["detay"], 6, renk=GRI, yeni=True)
        for c, metin, hiza in ((1, e["no"], "sol"), (2, e["tutar"], "sag")):
            _hucre_bicim(t.cell(r, c), dikey="center")
            _yazi(t.cell(r, c), metin, 7.8, kalin=True, hiza=hiza)
    _docx_bosluk(doc, BOSLUK)

    t = _docx_tablo(doc, 1, (ICERIK_GEN,), (H_VIRMAN_ACIKLAMA,))
    _hucre_bicim(t.cell(0, 0))
    _yazi(t.cell(0, 0), "AÇIKLAMA", 6.3, kalin=True, renk=GRI)
    _yazi(t.cell(0, 0), v["virman_metni"], 7.8, kalin=True, yeni=True)
    if v["aciklama"]:
        _yazi(t.cell(0, 0), v["aciklama"], 7.3 if len(v["aciklama"]) < 110 else 6, yeni=True)
    _docx_bosluk(doc, 3)

    _docx_imza(doc, v["imzalar"], IMZA_SUTUN_VIRMAN)
    _docx_alt(doc, v)


def _docx_ust(doc, v: dict) -> None:
    from docx.shared import Mm

    f = v["firma"]
    # Firma başlığı
    logo_w = 34.0 if f.get("logo_yolu") else 0.0
    t = _docx_tablo(doc, 1, (ICERIK_GEN - logo_w, logo_w) if logo_w else (ICERIK_GEN,), (H_UST,))
    _kenarsiz(t)
    sol = t.cell(0, 0)
    _yazi(sol, f.get("unvan") or "", 11, kalin=True, renk=LACIVERT)
    for satir in f.get("satirlar", [])[:3]:
        _yazi(sol, satir, 7.2, renk=GRI, yeni=True)
    if logo_w:
        sag = t.cell(0, 1)
        _yazi(sag, "", hiza="sag")
        try:
            sag.paragraphs[0].add_run().add_picture(f["logo_yolu"], height=Mm(H_UST - 2))
        except Exception:
            pass
    p = _docx_bosluk(doc, H_CIZGI)
    eleman, qn = _docx_yardimcilari()
    pPr = p._p.get_or_add_pPr()
    bdr = eleman("w:pBdr")
    bdr.append(eleman("w:top", **{"w:val": "single", "w:sz": "18", "w:space": "0", "w:color": SARI}))
    _sirali_ekle(
        pPr,
        bdr,
        ("shd", "tabs", "suppressAutoHyphens", "kinsoku", "wordWrap", "overflowPunct", "topLinePunct",
         "autoSpaceDE", "autoSpaceDN", "bidi", "adjustRightInd", "snapToGrid", "spacing", "ind",
         "contextualSpacing", "mirrorIndents", "suppressOverlap", "jc", "textDirection", "textAlignment",
         "textboxTightWrap", "outlineLvl", "divId", "cnfStyle", "rPr", "sectPr", "pPrChange"),
    )

    # Başlık bandı
    no_w = 44.0
    t = _docx_tablo(doc, 1, (ICERIK_GEN - no_w, no_w), (H_BASLIK,))
    _hucre_bicim(t.cell(0, 0), dolgu=LACIVERT, cerceve=None, dikey="center")
    _yazi(t.cell(0, 0), v["baslik"], 14, kalin=True, renk="FFFFFF")
    _hucre_bicim(t.cell(0, 1), dolgu=SARI, cerceve=None, dikey="center")
    etiket, no = ("MAKBUZ NO", v["makbuz_no"]) if v["makbuz_no"] else ("BELGE NO", v["belge_no"])
    _yazi(t.cell(0, 1), etiket, 6.5, kalin=True, renk=LACIVERT)
    _yazi(t.cell(0, 1), no, 12, kalin=True, renk=LACIVERT, yeni=True)
    _docx_bosluk(doc, BOSLUK)


def _docx_bilgi(doc, satirlar) -> None:
    t = _docx_tablo(doc, len(satirlar), BILGI_SUTUN, (H_BILGI,) * len(satirlar))
    for r, satir in enumerate(satirlar):
        for c, (etiket, deger) in enumerate(satir):
            cell = t.cell(r, c)
            _hucre_bicim(cell)
            _yazi(cell, etiket, 6.3, kalin=True, renk=GRI)
            _yazi(cell, deger, 9.5 if len(deger) < 44 else 7.5, kalin=True, yeni=True)
    _docx_bosluk(doc, BOSLUK)


def _docx_tutar(doc, v: dict) -> None:
    t = _docx_tablo(doc, 1, (50.0, ICERIK_GEN - 50.0), (H_TUTAR,))
    for cell in t.rows[0].cells:
        _hucre_bicim(cell, dolgu=ACIK_SARI, cerceve=None)
    a, b = t.cell(0, 0), t.cell(0, 1)
    birlesik = a.merge(b)
    _hucre_bicim(birlesik, dolgu=ACIK_SARI, cerceve=SARI, kalinlik=8)
    ic = birlesik.paragraphs[0]
    _yazi(ic, v["tutar_etiket"], 7, kalin=True, renk=LACIVERT)
    if v["iptal"]:
        _yazi(ic, "   İPTAL EDİLMİŞTİR", 9, kalin=True, renk=KIRMIZI)
    _yazi(birlesik, v["tutar"], 17, kalin=True, renk=LACIVERT, hiza="sag", yeni=True)
    _yazi(birlesik, v["tutar_yaziyla"], 7.8, yeni=True)
    _docx_bosluk(doc, BOSLUK)


def _docx_imza(doc, imzalar, sutunlar) -> None:
    from docx.enum.text import WD_TAB_ALIGNMENT, WD_TAB_LEADER
    from docx.shared import Mm

    yuk = (H_IMZA_BAS, H_IMZA_AD, H_IMZA_TARIH, H_IMZA_ALAN)
    t = _docx_tablo(doc, 4, sutunlar, yuk)
    for c, baslik in enumerate((*imzalar, "FİRMA KAŞESİ")):
        _hucre_bicim(t.cell(0, c), dolgu=ACIK_MAVI, cerceve=LACIVERT, kalinlik=6, dikey="center")
        _yazi(t.cell(0, c), baslik, 6.3, kalin=True, renk=LACIVERT, hiza="orta")
    for c in range(len(imzalar)):
        for r, etiket in ((1, "Adı Soyadı:\t"), (2, "Tarih:\t")):
            cizgisiz = ("bottom",) if r == 1 else ("top", "bottom")
            _hucre_bicim(t.cell(r, c), cerceve=LACIVERT, kalinlik=6, dikey="bottom", cizgisiz=cizgisiz)
            p = _yazi(t.cell(r, c), etiket, 6.5, renk=GRI)
            p.paragraph_format.tab_stops.add_tab_stop(
                Mm(sutunlar[c] - 3.5), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS
            )
        _hucre_bicim(t.cell(3, c), cerceve=LACIVERT, kalinlik=6, cizgisiz=("top",))
        _yazi(t.cell(3, c), "İmza:", 6.5, renk=GRI)
    kase = len(imzalar)
    for r in range(1, 4):
        _hucre_bicim(t.cell(r, kase), cerceve=LACIVERT, kalinlik=6)
    t.cell(1, kase).merge(t.cell(3, kase))
    _docx_bosluk(doc, 1.5)


def _docx_alt(doc, v: dict) -> None:
    f = v["firma"]
    alt = f"Belge No: {v['belge_no']}  ·  Oluşturma: {v['olusturma']}"
    if f.get("alt_bilgi"):
        alt = f"{f['alt_bilgi']}  ·  {alt}"
    t = _docx_tablo(doc, 1, (ICERIK_GEN,), (H_ALT,))
    _kenarsiz(t)
    _yazi(t.cell(0, 0), alt, 6, renk=GRI, hiza="orta")
