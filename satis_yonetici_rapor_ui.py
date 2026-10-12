"""Satışlar → Raporlar: müşteri/stok kârlılığı (çoklu dönem), yönetici analizleri ve özet.

Hesaplar ``database.satis_yonetici_rapor_service`` içindedir; ekranlar ortak ``RaporEkrani`` kullanır.
"""

from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import messagebox
from typing import Any, Callable

from satin_alma_rapor_ui import Filtre, Kolon, RaporEkrani, Tablo, bicimle
from satis_tema import ACIK_BG, hub_ust_baslik

from database.satis_maliyet_motoru import DONEMSEL, HAREKETLI, SON_ALIS, STANDART

AYLIK_MALIYET_SECENEK = [("FIFO", "FIFO"), (HAREKETLI, "Hareketli ağırlıklı ortalama"),
                         (DONEMSEL, "Dönemsel ağırlıklı ortalama (aylık)"),
                         (SON_ALIS, "Son alış maliyeti — karşılaştırma amaçlı"),
                         (STANDART, "Standart maliyet — karşılaştırma amaçlı")]
MALIYET_SECENEK = AYLIK_MALIYET_SECENEK + [
    ("SON ALIŞ FİYATI", "Son alış fiyatı (satıra kaydedilen)"),
    ("ORTALAMA ALIŞ FİYATI", "Ortalama alış fiyatı (satıra kaydedilen)"),
    ("AĞIRLIKLI ORTALAMA ALIŞ FİYATI", "Ağırlıklı ortalama alış fiyatı (satıra kaydedilen)")]


# ---------------------------------------------------------------------------
# Ortak
# ---------------------------------------------------------------------------

def _ust(app, baslik: str, alt: str) -> tk.Frame:
    temizle = getattr(app, "_icerigi_temizle", None)
    if callable(temizle):
        temizle()
    from satis_tema import stil_uygula
    from satis_ui import _menu_isaretle, satis_raporlar_hub_goster

    stil_uygula(root=app)
    _menu_isaretle(app)
    try:
        app.icerik.configure(bg=ACIK_BG)
    except tk.TclError:
        pass
    kok = tk.Frame(app.icerik, bg=ACIK_BG)
    kok.pack(fill="both", expand=True)
    hub_ust_baslik(kok, baslik=baslik, alt_baslik=alt, app=app,
                   geri_komut=lambda: satis_raporlar_hub_goster(app), geri_metin="← Raporlar")
    return kok


def _pencere_ust(pencere: tk.Toplevel) -> Callable[[Any, str, str], tk.Frame]:
    def ust(app, baslik, alt):
        kok = tk.Frame(pencere, bg=ACIK_BG)
        kok.pack(fill="both", expand=True)
        hub_ust_baslik(kok, baslik=baslik, alt_baslik=alt, app=app, geri_komut=pencere.destroy,
                       geri_metin="Kapat")
        return kok

    return ust


def _yetki(*kodlar) -> bool:
    try:
        from database.access import yetki_var

        return bool(yetki_var(*kodlar))
    except Exception:  # noqa: BLE001
        return True


def _ekran(app, baslik: str, kur: Callable[[], RaporEkrani], *, maliyet: bool = False) -> RaporEkrani | None:
    if not _yetki("satis_goruntuleme"):
        messagebox.showwarning(baslik, "Satış raporlarını görüntüleme yetkiniz yok.", parent=app)
        return None
    if maliyet and not (_yetki("maliyet_gorma") and _yetki("kar_gorma")):
        messagebox.showwarning(baslik, "Bu rapor için maliyet ve kâr görme yetkisi gerekir.", parent=app)
        return None
    ekran = kur()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: _ekran(app, baslik, kur, maliyet=maliyet))
    return ekran


def _yil_basi() -> date:
    return date(date.today().year, 1, 1)


def _ay_basi() -> date:
    return date.today().replace(day=1)


def _grup_secenekleri() -> list[tuple[str, str]]:
    out = [("", "(Tümü)")]
    try:
        from sqlalchemy import select

        from database.database import get_session
        from database.models.stok import StokGrubu

        with get_session() as s:
            gruplar = list(s.scalars(select(StokGrubu).where(StokGrubu.aktif.is_(True))
                                     .order_by(StokGrubu.seviye, StokGrubu.sira_no, StokGrubu.ad)).all())
        seviye = {1: "Ana", 2: "Tali", 3: "Alt"}
        out += [(str(g.id), f"{seviye.get(g.seviye, '')}: {g.ad}") for g in gruplar]
    except Exception:  # noqa: BLE001
        pass
    return out


def _depo_secenekleri() -> list[tuple[str, str]]:
    out = [("", "(Tümü)")]
    try:
        from sqlalchemy import select

        from database.database import get_session
        from database.models.stok import Depo

        with get_session() as s:
            out += [(d.ad, d.ad) for d in s.scalars(select(Depo).order_by(Depo.ad)).all()]
    except Exception:  # noqa: BLE001
        pass
    return out


def _sube_secenekleri() -> list[tuple[str, str]]:
    out = [("", "(Tümü)")]
    try:
        from sqlalchemy import select

        from database.database import get_session
        from database.models.sube import Sube

        with get_session() as s:
            out += [(str(x.id), x.sube_adi) for x in s.scalars(select(Sube).where(Sube.aktif.is_(True))).all()]
    except Exception:  # noqa: BLE001
        pass
    return out


def _ortak_filtreler(*, urun=True, grup=True, depo=True, kanal=True, maliyet=True) -> list[Filtre]:
    f = [Filtre("musteri", "cari_id", "Müşteri")]
    if urun:
        f.append(Filtre("metin", "urun", "Ürün kodu / adı"))
    if grup:
        f.append(Filtre("combo", "stok_grup_id", "Stok grubu", "", _grup_secenekleri()))
    if depo:
        f.append(Filtre("combo", "depo", "Depo", "", _depo_secenekleri()))
    subeler = _sube_secenekleri()
    if len(subeler) > 1:
        f.append(Filtre("combo", "sube_id", "Şube", "", subeler))
    if kanal:
        f.append(Filtre("combo", "kanal", "Kanal", "", [("", "(Tümü)"), ("fatura", "Fatura"),
                                                       ("hizli", "Hızlı Satış")]))
    if maliyet:
        f.append(Filtre("combo", "maliyet_yontemi", "Maliyet yöntemi", "FIFO", MALIYET_SECENEK))
    return f


def _servis_filtresi(f: dict) -> dict:
    out = dict(f)
    for anahtar in ("stok_grup_id", "sube_id"):
        out[anahtar] = int(out[anahtar]) if out.get(anahtar) else None
    return out


def _bilgi(f: dict, *ek: str) -> list[str]:
    return ["Para birimi: TL (KDV hariç)", f"Maliyet yöntemi: {f.get('maliyet_yontemi') or 'FIFO'}", *ek]


def _belge_ac(app, tur: str, belge_id) -> None:
    """Satış faturası / iade / sipariş belgesini açar (ana pencerede tanımlı diyaloglarla)."""
    import importlib
    import sys

    if not belge_id:
        return
    modul = sys.modules.get(type(app).__module__)
    try:
        if not hasattr(modul, "SatisFaturasiDialog"):
            modul = importlib.import_module("app")
        if tur in ("SATIS", "Satış"):
            from database.satis_faturasi_service import SatisFaturasiService

            belge = SatisFaturasiService.getir(int(belge_id))
            if belge:
                modul.SatisFaturasiDialog(app, fatura=belge)
        elif tur in ("IADE", "İade"):
            from database.satis_iade_faturasi_service import SatisIadeFaturasiService

            belge = SatisIadeFaturasiService.getir(int(belge_id))
            if belge:
                modul.SatisIadeFaturasiDialog(app, iade=belge)
        elif tur == "SIPARIS":
            from database.satis_siparisi_service import SatisSiparisiService

            belge = SatisSiparisiService.getir(int(belge_id))
            if belge:
                modul.SatisSiparisiDialog(app, siparis=belge)
    except Exception as hata:  # noqa: BLE001
        messagebox.showerror("Belge", f"Belge açılamadı:\n{hata}", parent=app)


def _etiket_kar(r: dict) -> str | None:
    if r.get("maliyet_durumu") not in (None, "", "Kesin"):
        return "soluk"
    kar = r.get("kar")
    if kar is None:
        return None
    return "uyari" if kar < 0 else None


# ---------------------------------------------------------------------------
# 1–3) Müşteri / stok kârlılığı + çoklu dönem
# ---------------------------------------------------------------------------

def _karlilik_kolonlari(boyut: str, donemler: list, temel: int, maliyet_ok: bool) -> list[Kolon]:
    if boyut == "musteri":
        k = [Kolon("cari_kodu", "Kod", 80), Kolon("unvan", "Müşteri", 200)]
    else:
        k = [Kolon("urun_kodu", "Kod", 90), Kolon("urun_adi", "Ürün", 190), Kolon("ana_grup", "Ana Grup", 100),
             Kolon("tali_grup", "Tali Grup", 100), Kolon("alt_grup", "Alt Grup", 100)]
    ana = donemler[0].ad
    k += [Kolon("satis", f"{ana} Satış", 100, "para"), Kolon("iade", "İade", 85, "para"),
          Kolon("net", "Net Satış", 100, "para")]
    if boyut == "urun":
        k += [Kolon("satis_miktar", "Satış Mik.", 75, "miktar"), Kolon("iade_miktar", "İade Mik.", 70, "miktar"),
              Kolon("net_miktar", "Net Mik.", 75, "miktar"), Kolon("birim", "Birim", 50),
              Kolon("ort_fiyat", "Ort. Net Fiyat", 95, "fiyat")]
    if maliyet_ok:
        k += [Kolon("maliyet", "Maliyet", 95, "para")]
        if boyut == "urun":
            k.append(Kolon("ort_maliyet", "Ort. Maliyet", 90, "fiyat"))
        k += [Kolon("kar", "Brüt Kâr", 95, "para"), Kolon("marj", "Marj %", 70, "yuzde"),
              Kolon("maliyet_uzeri", "Maliyet Üz. Kâr %", 95, "yuzde")]
    if boyut == "musteri":
        k += [Kolon("fatura_sayisi", "Fatura", 55, "gun"), Kolon("ort_fatura", "Ort. Net Fatura", 100, "para")]
    k.append(Kolon("pay_satis", "Satış Payı %", 80, "yuzde"))
    if maliyet_ok:
        k += [Kolon("pay_kar", "Kâr Payı %", 75, "yuzde"), Kolon("maliyet_durumu", "Maliyet", 120)]
    k.append(Kolon("durum", "Dönem Durumu", 120))
    for i, d in enumerate(donemler[1:], 1):
        ek = " (temel)" if i == temel else ""
        k += [Kolon(f"satis_{i}", f"{d.ad}{ek} Net Satış", 120, "para"),
              Kolon(f"miktar_{i}", "Net Miktar", 75, "miktar")]
        if maliyet_ok:
            k += [Kolon(f"kar_{i}", "Kâr", 90, "para"), Kolon(f"marj_{i}", "Marj %", 65, "yuzde")]
    for i, d in enumerate(donemler):
        if i == temel:
            continue
        k += [Kolon(f"fark_satis_{i}", f"{d.ad} − Temel Net Satış", 140, "para"),
              Kolon(f"yuzde_satis_{i}", "Satış %", 70, "yuzde"),
              Kolon(f"fark_miktar_{i}", "Miktar Farkı", 85, "miktar"),
              Kolon(f"yuzde_miktar_{i}", "Miktar %", 70, "yuzde")]
        if maliyet_ok:
            k += [Kolon(f"fark_kar_{i}", "Kâr Farkı", 90, "para"), Kolon(f"yuzde_kar_{i}", "Kâr %", 65, "yuzde"),
                  Kolon(f"puan_marj_{i}", "Marj Farkı (puan)", 105, "fiyat")]
        k.append(Kolon(f"aciklama_{i}", "Açıklama", 240))
    return k


def _donem_kolonlari(maliyet_ok: bool) -> list[Kolon]:
    k = [Kolon("donem", "Dönem", 140), Kolon("temel", "", 50), Kolon("bas", "Başlangıç", 85, "tarih"),
         Kolon("bit", "Bitiş", 85, "tarih"), Kolon("gun_sayisi", "Gün", 45, "gun"),
         Kolon("durum", "Durum", 150), Kolon("satis", "Satış", 100, "para"), Kolon("iade", "İade", 90, "para"),
         Kolon("net", "Net Satış", 100, "para"), Kolon("miktar_metni", "Miktar", 120),
         Kolon("gunluk_net", "Günlük Ort. Net", 105, "para")]
    if maliyet_ok:
        k += [Kolon("maliyet", "Maliyet", 95, "para"), Kolon("kar", "Brüt Kâr", 95, "para"),
              Kolon("marj", "Marj %", 65, "yuzde"), Kolon("maliyet_uzeri", "Maliyet Üz. %", 85, "yuzde"),
              Kolon("gunluk_kar", "Günlük Ort. Kâr", 100, "para")]
    k += [Kolon("fatura_sayisi", "Fatura", 55, "gun"), Kolon("eksik_satir", "Eksik Maliyet", 85, "gun"),
          Kolon("fark_satis", "Satış Farkı", 95, "para"), Kolon("yuzde_satis", "Satış %", 65, "yuzde")]
    if maliyet_ok:
        k += [Kolon("fark_kar", "Kâr Farkı", 90, "para"), Kolon("yuzde_kar", "Kâr %", 60, "yuzde"),
              Kolon("puan_marj", "Marj Farkı (puan)", 105, "fiyat")]
    k.append(Kolon("aciklama", "Açıklama", 260))
    return k


def _karlilik_goster(app, boyut: str, **kw) -> RaporEkrani | None:
    from database import satis_yonetici_rapor_service as srv

    baslik = "MÜŞTERİ KÂRLILIĞI" if boyut == "musteri" else "STOK KÂRLILIĞI"
    durum_ekran: dict[str, RaporEkrani] = {}

    def hesapla(f):
        fs = _servis_filtresi(f)
        d = f["donemler"]
        sonuc = srv.karlilik_raporu(boyut, d["donemler"], d["temel"], fs, sadece=f.get("sadece") or None)
        ok = sonuc["maliyet_gorunur"]
        sonuc["_kolonlar"] = {"satirlar": _karlilik_kolonlari(boyut, sonuc["donem_listesi"], sonuc["temel"], ok),
                              "donemler": _donem_kolonlari(ok),
                              "tek_donem": _karlilik_kolonlari(boyut, sonuc["donem_listesi"][:1], 0, ok)}
        sonuc["_bilgi"] = _bilgi(fs)
        sonuc["_filtre"] = fs
        return sonuc

    def detay(r):
        ekran = durum_ekran.get("e")
        if ekran is None:
            return
        fs = ekran.sonuc.get("_filtre") or {}
        d = ekran.sonuc.get("donem_listesi") or []
        if not d:
            return
        anahtar = r.get("cari_id") if boyut == "musteri" else r.get("urun_kodu")
        ad = r.get("unvan") if boyut == "musteri" else f"{r.get('urun_kodu')} {r.get('urun_adi')}"
        if anahtar:
            karlilik_detay_goster(app, boyut, anahtar, ad, d[0].bas, d[0].bit, fs)

    def toplam(s):
        t = s.get("toplam") or {}
        if not t:
            return ""
        metin = (f"Ana dönem — Satış: {bicimle(t.get('satis'), 'para')}   İade: {bicimle(t.get('iade'), 'para')}   "
                 f"Net: {bicimle(t.get('net'), 'para')}")
        if s.get("maliyet_gorunur"):
            metin += (f"   Maliyet: {bicimle(t.get('maliyet'), 'para')}   Brüt kâr: {bicimle(t.get('kar'), 'para')}"
                      f"   Marj: {bicimle(t.get('marj'), 'yuzde')}   Maliyet üz. kâr: "
                      f"{bicimle(t.get('maliyet_uzeri'), 'yuzde')}")
        return metin

    def kur():
        bos = [Kolon("bos", "", 100)]
        ekran = RaporEkrani(
            app, baslik=baslik,
            alt=("Müşteri bazında net satış, iade, maliyet, brüt kâr ve marj; dönemler arası karşılaştırma "
                 "(çift tık: ürün ve belge ayrıntısı)") if boyut == "musteri" else
                ("Ürün bazında miktar, net satış, maliyet, brüt kâr ve marj; dönemler arası karşılaştırma "
                 "(çift tık: müşteri ve belge ayrıntısı)"),
            filtreler=[Filtre("donemler", "donemler", "Dönemler", ("bu_ay", "gecen_ay")),
                       *_ortak_filtreler(),
                       Filtre("combo", "sadece", "Göster", "", [("", "Tümü"), ("yeni", "Yalnız yeni satış"),
                                                              ("duran", "Yalnız satışı duran")])],
            tablolar=[Tablo("satirlar", "Karşılaştırma", list(bos), cift_tik=detay, etiket=_etiket_kar),
                      Tablo("donemler", "Dönem Toplamları", list(bos)),
                      Tablo("tek_donem", "Yalnız Bir Dönemde Olanlar", list(bos), cift_tik=detay)],
            hesapla=hesapla, toplam_metni=toplam, ust=_ust, hafiza=f"satis_{boyut}_karlilik", **kw)
        durum_ekran["e"] = ekran
        return ekran

    return _ekran(app, baslik.title(), kur)


def musteri_karlilik_goster(app, **kw) -> RaporEkrani | None:
    return _karlilik_goster(app, "musteri", **kw)


def stok_karlilik_goster(app, **kw) -> RaporEkrani | None:
    return _karlilik_goster(app, "urun", **kw)


def _satir_kolonlari(maliyet_ok: bool) -> list[Kolon]:
    k = [Kolon("belge_turu", "Tür", 55), Kolon("belge_no", "Belge No", 110), Kolon("tarih", "Tarih", 85, "tarih"),
         Kolon("unvan", "Müşteri", 160), Kolon("urun_kodu", "Ürün Kodu", 90), Kolon("urun_adi", "Ürün", 160),
         Kolon("miktar", "Miktar", 70, "miktar"), Kolon("birim", "Birim", 50),
         Kolon("temel_miktar", "Temel Mik.", 75, "miktar"), Kolon("brut", "Brüt", 90, "para"),
         Kolon("iskonto", "Satır İsk.", 85, "para"), Kolon("belge_duzeltme", "Belge Geneli", 85, "para"),
         Kolon("net", "Net", 95, "para"), Kolon("net_fiyat", "Net Fiyat", 90, "fiyat")]
    if maliyet_ok:
        k += [Kolon("birim_maliyet", "Birim Maliyet", 90, "fiyat"), Kolon("toplam_maliyet", "Maliyet", 90, "para"),
              Kolon("kar", "Kâr", 85, "para"), Kolon("marj", "Marj %", 65, "yuzde"),
              Kolon("maliyet_durumu", "Maliyet Durumu", 105), Kolon("maliyet_kaynagi", "Maliyet Kaynağı", 200)]
    k += [Kolon("kanal", "Kanal", 85), Kolon("para_birimi", "PB", 40), Kolon("kur", "Kur", 70, "fiyat"),
          Kolon("kur_tarihi", "Kur Tarihi", 80, "tarih"), Kolon("kur_kaynagi", "Kur Kaynağı", 70),
          Kolon("kaynak_belge_no", "Kaynak Fatura", 105)]
    return k


def stok_hareketleri_ac(parent, urun_kodu: str | None) -> None:
    try:
        from database.stok_service import StokService
        from stok_ui import StokHareketleriDialog

        from sqlalchemy import select

        from database.database import get_session
        from database.models.stok import StokKarti

        with get_session() as s:
            sid = s.scalar(select(StokKarti.id).where(StokKarti.stok_kodu == (urun_kodu or "").strip()))
        stok = StokService.stok_getir(int(sid)) if sid else None
        if stok is None:
            messagebox.showinfo("Stok hareketleri", "Bu satırın stok kartı bulunamadı.", parent=parent)
            return
        StokHareketleriDialog(parent, stok)
    except Exception as hata:  # noqa: BLE001
        messagebox.showerror("Stok hareketleri", f"Stok hareketleri açılamadı:\n{hata}", parent=parent)


def maliyet_katmanlari_goster(parent, r: dict, belge_satirlari: list[dict] | None = None) -> tk.Toplevel | None:
    """FIFO giriş katmanları fatura satırı bazında: her satırın tükettiği katmanlar, satır maliyeti ve brüt kârı.

    ``belge_satirlari``: aynı belgenin rapor satırları (satır net satışı ve kârı için).
    """
    from database import satis_yonetici_rapor_service as srv

    try:
        a = srv.satir_maliyet_ayrintisi(r.get("_belge_turu") or "SATIS", int(r.get("belge_id")),
                                        int(r.get("satir_id")))
        fatura_satirlari = (srv.fatura_fifo_ayrintisi(int(r.get("belge_id")))
                            if (r.get("_belge_turu") or "SATIS") == "SATIS" else [])
    except Exception as hata:  # noqa: BLE001
        messagebox.showerror("Maliyet katmanları", str(hata), parent=parent)
        return None
    pencere = tk.Toplevel(parent)
    pencere.title(f"Maliyet katmanları — {r.get('belge_no')} / {r.get('urun_kodu')}")
    pencere.geometry("980x420")
    pencere.configure(bg=ACIK_BG)
    from tkinter import ttk

    ust = (f"{r.get('belge_turu')} {r.get('belge_no')} ({bicimle(r.get('tarih'), 'tarih')}) — {r.get('urun_kodu')} "
           f"{r.get('urun_adi')}   Miktar: {bicimle(r.get('miktar'), 'miktar')} {r.get('birim') or ''}   "
           f"Birim maliyet: {bicimle(r.get('birim_maliyet'), 'fiyat')}   Toplam: "
           f"{bicimle(r.get('toplam_maliyet'), 'para')}\nYöntem: {r.get('maliyet_yontemi') or ''} — Kaynak: "
           f"{r.get('maliyet_kaynagi') or ''}")
    tk.Label(pencere, text=ust, bg=ACIK_BG, anchor="w", justify="left").pack(fill="x", padx=10, pady=(8, 4))
    kolonlar = (("satir_id", "Satır", 55, "metin"), ("urun", "Ürün", 150, "metin"),
                ("satir_miktar", "Satır Miktarı", 95, "metin"), ("giris_tarihi", "Giriş Tarihi", 85, "tarih"),
                ("giris_belge_no", "Giriş Belgesi", 110, "metin"), ("lot_no", "Lot / Katman", 140, "metin"),
                ("miktar", "Tüketilen (temel)", 100, "miktar"), ("birim_maliyet", "Birim Maliyet", 95, "fiyat"),
                ("tutar", "Satıra Düşen", 95, "para"), ("kar", "Brüt Kâr", 95, "para"))
    netler = {x.get("satir_id"): x for x in (belge_satirlari or []) if x.get("belge_id") == r.get("belge_id")}
    gruplar = fatura_satirlari or [{"satir_id": r.get("satir_id"), "urun_kodu": r.get("urun_kodu"),
                                    "urun_adi": r.get("urun_adi"), "miktar": r.get("miktar"), "birim": r.get("birim"),
                                    "katmanlar": a.get("katmanlar") or [],
                                    "fifo_maliyet": sum((k["tutar"] for k in a.get("katmanlar") or []), 0)}]
    satirlar: list[tuple[dict, str | None]] = []
    for g in gruplar:
        etiket = "secili" if g["satir_id"] == r.get("satir_id") else None
        for k in g["katmanlar"]:
            satirlar.append(({**k, "satir_id": g["satir_id"], "urun": g["urun_kodu"],
                              "satir_miktar": f"{bicimle(g['miktar'], 'miktar')} {g.get('birim') or ''}"}, etiket))
        rap = netler.get(g["satir_id"]) or (r if g["satir_id"] == r.get("satir_id") else {})
        kar = (rap["net"] - g["fifo_maliyet"]) if rap.get("net") is not None and g["katmanlar"] else None
        satirlar.append(({"satir_id": g["satir_id"], "urun": f"{g['urun_kodu']} — SATIR TOPLAMI",
                          "satir_miktar": f"{bicimle(g['miktar'], 'miktar')} {g.get('birim') or ''}",
                          "lot_no": "" if g["katmanlar"] else "katman yok (maliyet eksik)",
                          "tutar": g["fifo_maliyet"], "kar": kar}, "toplam"))
    if not gruplar[0]["katmanlar"] and a.get("hareketler"):
        satirlar = [({"giris_tarihi": h.get("tarih"), "giris_belge_no": h.get("belge_no"),
                      "lot_no": h.get("hareket_turu"), "miktar": h.get("miktar"),
                      "birim_maliyet": h.get("birim_maliyet")}, None) for h in a["hareketler"]]
    tablo = ttk.Treeview(pencere, columns=[k[0] for k in kolonlar], show="headings", height=12)
    for k, baslik, gen, tip in kolonlar:
        tablo.heading(k, text=baslik)
        tablo.column(k, width=gen, anchor="e" if tip in ("miktar", "fiyat", "para") else "w")
    tablo.tag_configure("toplam", background="#E8ECF4")
    tablo.tag_configure("secili", foreground="#1F3B73")
    for s, etiket in satirlar:
        tablo.insert("", "end", values=[bicimle(s.get(k), tip) for k, _b, _g, tip in kolonlar],
                     tags=(etiket,) if etiket else ())
    tablo.pack(fill="both", expand=True, padx=10, pady=4)
    pencere.fatura_satirlari = gruplar
    toplam_m = sum((s.get("miktar") or 0 for s in a.get("katmanlar") or []), 0)
    toplam_t = sum((s.get("tutar") or 0 for s in a.get("katmanlar") or []), 0)
    alt = (f"Seçili satır ({r.get('satir_id')}) — tüketilen: {bicimle(toplam_m, 'miktar')}   FIFO maliyeti: "
           f"{bicimle(toplam_t, 'para')}")
    if len(gruplar) > 1:
        alt += f"   |   Belge toplam FIFO maliyeti: {bicimle(sum((g['fifo_maliyet'] for g in gruplar), 0), 'para')}"
    if a.get("not"):
        alt += f"\n{a['not']}"
    tk.Label(pencere, text=alt, bg=ACIK_BG, anchor="w", justify="left", wraplength=940).pack(
        fill="x", padx=10, pady=(0, 6))
    btn = tk.Frame(pencere, bg=ACIK_BG)
    btn.pack(fill="x", padx=10, pady=(0, 8))
    from satis_tema import tk_buton

    tk_buton(btn, "Stok Hareketleri", lambda: stok_hareketleri_ac(pencere, r.get("urun_kodu")),
             rol="duzenle").pack(side="left")
    tk_buton(btn, "Kapat", pencere.destroy, rol="duzenle").pack(side="right")
    pencere.ayrinti = a
    return pencere


def karlilik_detay_goster(app, boyut: str, anahtar, ad: str, bas: date, bit: date, filtre: dict,
                          ikinci: Any = None, ikinci_ad: str = "") -> tk.Toplevel:
    """Müşteri → ürün → belge/satır veya ürün → müşteri → belge/satır ayrıntısı (ayrı pencere)."""
    from database import satis_yonetici_rapor_service as srv

    pencere = tk.Toplevel(app)
    pencere.title(f"Kârlılık ayrıntısı — {ad}")
    pencere.geometry("1250x680")
    pencere.configure(bg=ACIK_BG)
    maliyet_ok = srv.maliyet_gorunur()
    alt_boyut = "urun" if boyut == "musteri" else "musteri"

    def hesapla(_f):
        s = srv.karlilik_detay(boyut, anahtar, bas, bit, filtre, ikinci)
        s["_bilgi"] = _bilgi(filtre, f"Dönem: {bas:%d.%m.%Y}–{bit:%d.%m.%Y}", f"Kayıt: {ad} {ikinci_ad}".strip())
        return s

    def alt_detay(r):
        if ikinci:
            return
        a2 = r.get("urun_kodu") if alt_boyut == "urun" else r.get("cari_id")
        ad2 = f"{r.get('urun_kodu')} {r.get('urun_adi')}" if alt_boyut == "urun" else r.get("unvan", "")
        if a2:
            karlilik_detay_goster(app, boyut, anahtar, ad, bas, bit, filtre, a2, f"→ {ad2}")

    kirilim = ([Kolon("urun_kodu", "Ürün Kodu", 90), Kolon("urun_adi", "Ürün", 200),
                Kolon("net_miktar", "Net Miktar", 80, "miktar"), Kolon("birim", "Birim", 50),
                Kolon("miktar_metni", "Miktar (birimli)", 150)]
               if alt_boyut == "urun" else [Kolon("cari_kodu", "Kod", 80), Kolon("unvan", "Müşteri", 220)])
    kirilim += [Kolon("satis", "Satış", 95, "para"), Kolon("iade", "İade", 85, "para"),
                Kolon("net", "Net", 95, "para")]
    if maliyet_ok:
        kirilim += [Kolon("maliyet", "Maliyet", 90, "para"), Kolon("kar", "Kâr", 90, "para"),
                    Kolon("marj", "Marj %", 65, "yuzde"), Kolon("maliyet_durumu", "Maliyet", 120)]
    kirilim += [Kolon("fatura_sayisi", "Fatura", 55, "gun"), Kolon("pay_satis", "Pay %", 60, "yuzde")]
    belge = [Kolon("belge_turu", "Tür", 55), Kolon("belge_no", "Belge No", 110), Kolon("tarih", "Tarih", 85, "tarih"),
             Kolon("unvan", "Müşteri", 180), Kolon("kanal", "Kanal", 85), Kolon("net", "Net", 95, "para")]
    if maliyet_ok:
        belge += [Kolon("maliyet", "Maliyet", 90, "para"), Kolon("kar", "Kâr", 90, "para"),
                  Kolon("marj", "Marj %", 65, "yuzde"), Kolon("maliyet_durumu", "Maliyet", 120)]
    tablolar = [Tablo("belgeler", "Belgeler", belge, cift_tik=lambda r: _belge_ac(
                    app, "SATIS" if r.get("belge_turu") == "Satış" else "IADE", r.get("belge_id"))),
                Tablo("satirlar", "Satırlar", _satir_kolonlari(maliyet_ok), etiket=_etiket_kar,
                      cift_tik=lambda r: _belge_ac(app, r.get("_belge_turu"), r.get("belge_id")))]
    if not ikinci:
        tablolar.insert(0, Tablo("kirilim", "Ürünler" if alt_boyut == "urun" else "Müşteriler", kirilim,
                                 cift_tik=alt_detay, etiket=_etiket_kar))

    def toplam(s):
        t = s.get("toplam") or {}
        metin = f"Net: {bicimle(t.get('net'), 'para')}   İade: {bicimle(t.get('iade'), 'para')}"
        if maliyet_ok:
            metin += f"   Kâr: {bicimle(t.get('kar'), 'para')}   Marj: {bicimle(t.get('marj'), 'yuzde')}"
        return metin

    def secili_satir(e: RaporEkrani) -> dict | None:
        r = e.secili("satirlar")
        if not r:
            messagebox.showinfo("Ayrıntı", "Önce 'Satırlar' sekmesinde bir satır seçin.", parent=pencere)
            return None
        return r[0]

    def fatura_ac(e: RaporEkrani) -> None:
        r = secili_satir(e)
        if r:
            _belge_ac(app, r.get("_belge_turu"), r.get("belge_id"))

    def katmanlar(e: RaporEkrani) -> None:
        r = secili_satir(e)
        if r:
            maliyet_katmanlari_goster(pencere, r, e._satirlar.get("satirlar"))

    def hareketler(e: RaporEkrani) -> None:
        r = secili_satir(e)
        if r:
            stok_hareketleri_ac(pencere, r.get("urun_kodu"))

    butonlar = [("Faturayı Aç", fatura_ac, "duzenle"), ("Stok Hareketleri", hareketler, "duzenle")]
    if maliyet_ok:
        butonlar.insert(1, ("Maliyet Katmanları (FIFO)", katmanlar, "duzenle"))
    ekran = RaporEkrani(app, baslik=f"KÂRLILIK AYRINTISI — {ad} {ikinci_ad}".strip(),
                        alt=f"{bas:%d.%m.%Y} – {bit:%d.%m.%Y} (çift tık: alt kırılım / belgeyi aç)",
                        filtreler=[], tablolar=tablolar, hesapla=hesapla, toplam_metni=toplam,
                        ust=_pencere_ust(pencere), otomatik=False, ek_butonlar=butonlar)
    ekran.raporla(senkron=True)
    pencere.ekran = ekran
    return pencere


# ---------------------------------------------------------------------------
# 5) Düşük marjlı / zararına satışlar
# ---------------------------------------------------------------------------

def dusuk_marj_goster(app, **kw) -> RaporEkrani | None:
    from database import satis_yonetici_rapor_service as srv

    def hesapla(f):
        fs = _servis_filtresi(f)
        s = srv.dusuk_marjli_satislar(f["bas"], f["bit"], fs, f["hedef_marj"], f["tur"])
        s["_bilgi"] = _bilgi(fs, f"Hedef marj %{f['hedef_marj']}")
        return s

    def kur():
        return RaporEkrani(
            app, baslik="DÜŞÜK MARJLI / ZARARINA SATIŞLAR",
            alt="Hedef marjın altında kalan, zararına veya maliyeti eksik satış satırları (çift tık: faturayı aç)",
            filtreler=[Filtre("tarih", "bas", "Başlangıç", _ay_basi()), Filtre("tarih", "bit", "Bitiş", date.today()),
                       Filtre("sayi", "hedef_marj", "Hedef marj %", 10),
                       Filtre("combo", "tur", "Göster", "tumu", [("tumu", "Tümü"), ("zararina", "Zararına"),
                                                               ("hedef_alti", "Hedef altı"),
                                                               ("eksik", "Maliyeti eksik")]),
                       *_ortak_filtreler(kanal=False)],
            tablolar=[Tablo("satirlar", "Satırlar", [
                Kolon("durum", "Durum", 105), Kolon("unvan", "Müşteri", 170), Kolon("urun_kodu", "Ürün Kodu", 90),
                Kolon("urun_adi", "Ürün", 170), Kolon("belge_no", "Fatura", 110), Kolon("tarih", "Tarih", 85, "tarih"),
                Kolon("miktar", "Miktar", 65, "miktar"), Kolon("birim", "Birim", 50),
                Kolon("net_fiyat", "Net Fiyat", 90, "fiyat"), Kolon("birim_maliyet", "Birim Maliyet", 90, "fiyat"),
                Kolon("net", "Net", 90, "para"), Kolon("toplam_maliyet", "Maliyet", 90, "para"),
                Kolon("kar", "Kâr", 85, "para"), Kolon("marj", "Marj %", 65, "yuzde"),
                Kolon("hedef_fark", "Hedefe Fark (puan)", 110, "fiyat"),
                Kolon("maliyet_kaynagi", "Maliyet Kaynağı", 190)],
                etiket=lambda r: "uyari" if r.get("durum") == "Zararına" else (
                    "soluk" if r.get("durum") == "Maliyeti eksik" else None),
                cift_tik=lambda r: _belge_ac(app, "SATIS", r.get("belge_id")))],
            hesapla=hesapla, ust=_ust, hafiza="satis_dusuk_marj",
            toplam_metni=lambda s: (
                f"Zararına: {s.get('ozet', {}).get('zararina', 0)} satır "
                f"(toplam zarar {bicimle(s.get('ozet', {}).get('zarar_toplam'), 'para')})   "
                f"Hedef altı: {s.get('ozet', {}).get('hedef_alti', 0)}   "
                f"Maliyeti eksik: {s.get('ozet', {}).get('eksik', 0)}" if s.get("ozet") else ""),
            **kw)

    return _ekran(app, "Düşük Marjlı Satışlar", kur, maliyet=True)


# ---------------------------------------------------------------------------
# 6) Satış ve tahsilat performansı
# ---------------------------------------------------------------------------

def tahsilat_performansi_goster(app, **kw) -> RaporEkrani | None:
    from database import satis_yonetici_rapor_service as srv

    def hesapla(f):
        fs = _servis_filtresi(f)
        s = srv.tahsilat_performansi(f["bas"], f["bit"], fs, acik_bakiyeliler=f["acik_bakiyeliler"])
        s["_bilgi"] = ["Para birimi: TL"]
        return s

    def kur():
        maliyet_ok = srv.maliyet_gorunur()
        kolonlar = [Kolon("cari_kodu", "Kod", 80), Kolon("unvan", "Müşteri", 200),
                    Kolon("net", "Net Satış (dönem)", 110, "para")]
        if maliyet_ok:
            kolonlar += [Kolon("kar", "Kâr", 90, "para"), Kolon("marj", "Marj %", 60, "yuzde")]
        kolonlar += [Kolon("tahsilat", "Tahsilat (dönem)", 110, "para"),
                     Kolon("tahsilat_orani", "Tahsilat / Satış %", 105, "yuzde"),
                     Kolon("acik_alacak", "Açık Alacak (bugün)", 120, "para"),
                     Kolon("vadesi_gecmis", "Vadesi Geçmiş", 105, "para"),
                     Kolon("gecikme_gun", "Ort. Gecikme Gün", 105, "gun1"),
                     Kolon("gerceklesen_vade_gun", "Gerç. Vade Sapması Gün", 135, "gun1"),
                     Kolon("gerceklesen_tahsil_gun", "Gerç. Tahsil Süresi Gün", 135, "gun1"),
                     Kolon("eslesmemis_alacak", "Faturaya Bağlanmayan Tahsilat", 165, "para"),
                     Kolon("soz", "Açık Ödeme Sözü", 110, "para"),
                     Kolon("soz_geciken", "Gecikmiş Söz", 100, "para")]
        return RaporEkrani(
            app, baslik="SATIŞ VE TAHSİLAT PERFORMANSI",
            alt="Müşteri bazında dönem satışı, tahsilatı, açık/vadesi geçmiş alacak ve gerçekleşen ödeme süresi",
            filtreler=[Filtre("tarih", "bas", "Başlangıç", _yil_basi()), Filtre("tarih", "bit", "Bitiş", date.today()),
                       Filtre("musteri", "cari_id", "Müşteri"),
                       Filtre("check", "acik_bakiyeliler", "Bakiyesi açık tüm müşteriler", False)],
            tablolar=[Tablo("satirlar", "Müşteriler", kolonlar,
                            etiket=lambda r: "uyari" if (r.get("vadesi_gecmis") or 0) > 0 else None)],
            hesapla=hesapla, ust=_ust, hafiza="satis_tahsilat_performans",
            toplam_metni=lambda s: "   ".join(
                f"{ad}: {bicimle((s.get('toplam') or {}).get(k), 'para')}" for ad, k in (
                    ("Net satış", "net"), ("Tahsilat", "tahsilat"), ("Açık alacak", "acik_alacak"),
                    ("Vadesi geçmiş", "vadesi_gecmis"), ("Bağlanmayan tahsilat", "eslesmemis_alacak"),
                    ("Açık söz", "soz"))) if s.get("toplam") else "",
            **kw)

    return _ekran(app, "Satış ve Tahsilat Performansı", kur)


# ---------------------------------------------------------------------------
# 7) Satışı azalan ve alışverişi duran müşteriler
# ---------------------------------------------------------------------------

def _kars_araligi(f: dict) -> tuple[date, date]:
    from database.satis_kar_analiz_service import SatisKarAnalizService
    from database.satis_yonetici_rapor_service import donem_araligi

    if f.get("kars") == "gecen_yil_ayni":
        return donem_araligi("gecen_yil_ayni", referans=(f["bas"], f["bit"]))
    return SatisKarAnalizService.onceki_es_donem(f["bas"], f["bit"])


def azalan_musteriler_goster(app, **kw) -> RaporEkrani | None:
    from database import satis_yonetici_rapor_service as srv

    def hesapla(f):
        if not f.get("bas") or not f.get("bit"):
            raise ValueError("Dönem tarihlerini girin.")
        kars = _kars_araligi(f)
        fs = _servis_filtresi(f)
        s = srv.azalan_musteriler((f["bas"], f["bit"]), kars, fs, f["inaktif_gun"], f["dusus"], tur=f["tur"])
        s["_bilgi"] = ["Para birimi: TL (KDV hariç)"]
        return s

    def kur():
        return RaporEkrani(
            app, baslik="SATIŞI AZALAN VE ALIŞVERİŞİ DURAN MÜŞTERİLER",
            alt="Dönem karşılaştırması, son satış tarihi ve son alışverişten bu yana geçen gün",
            filtreler=[Filtre("tarih", "bas", "Dönem başı", _ay_basi()), Filtre("tarih", "bit", "Dönem sonu", date.today()),
                       Filtre("combo", "kars", "Karşılaştırma", "onceki", [("onceki", "Önceki eş dönem"),
                                                                        ("gecen_yil_ayni", "Geçen yılın aynı dönemi")]),
                       Filtre("sayi", "inaktif_gun", "Hareketsizlik günü", 90),
                       Filtre("sayi", "dusus", "Düşüş eşiği %", 20),
                       Filtre("combo", "tur", "Göster", "tumu", [("tumu", "Tümü"), ("azalan", "Satışı azalan"),
                                                               ("duran", "Alışverişi duran"),
                                                               ("donemde_yok", "Dönemde satış yok")]),
                       *_ortak_filtreler(maliyet=False, kanal=False, depo=False)],
            tablolar=[Tablo("satirlar", "Müşteriler", [
                Kolon("cari_kodu", "Kod", 80), Kolon("unvan", "Müşteri", 220),
                Kolon("net_donem", "Net Satış (dönem)", 115, "para"), Kolon("net_kars", "Net Satış (karş.)", 115, "para"),
                Kolon("fark", "Fark", 95, "para"), Kolon("yuzde", "Değişim %", 80, "yuzde"),
                Kolon("son_satis", "Son Satış", 85, "tarih"), Kolon("gun", "Geçen Gün", 70, "gun"),
                Kolon("durum", "Durum", 300), Kolon("aciklama", "Açıklama", 220)],
                etiket=lambda r: "uyari")],
            hesapla=hesapla, ust=_ust, hafiza="satis_azalan_musteri", **kw)

    return _ekran(app, "Satışı Azalan Müşteriler", kur)


# ---------------------------------------------------------------------------
# 8) Ürün satış hızı ve stokta bekleyen sermaye
# ---------------------------------------------------------------------------

def urun_satis_hizi_goster(app, **kw) -> RaporEkrani | None:
    from database import satis_yonetici_rapor_service as srv

    def hesapla(f):
        fs = _servis_filtresi(f)
        s = srv.urun_satis_hizi(f["bas"], f["bit"], fs, yavas_gun=f["yavas_gun"], tur=f["tur"])
        s["_bilgi"] = ["Miktar: stok temel birimi", "Stok değeri: FIFO"]
        return s

    def kur():
        maliyet_ok = srv.maliyet_gorunur()
        kolonlar = [Kolon("urun_kodu", "Kod", 90), Kolon("urun_adi", "Ürün", 200), Kolon("ana_grup", "Ana Grup", 100),
                    Kolon("birim", "Birim", 50), Kolon("mevcut", "Mevcut Stok", 85, "miktar")]
        if maliyet_ok:
            kolonlar.append(Kolon("stok_deger", "Stok Maliyet Değeri", 125, "para"))
        kolonlar += [Kolon("satis_miktar", "Dönem Net Satış Mik.", 125, "miktar"),
                     Kolon("gunluk_hiz", "Günlük Hız", 80, "fiyat"), Kolon("yeterlilik_gun", "Yeterlilik Gün", 95, "gun"),
                     Kolon("son_satis", "Son Satış", 85, "tarih"), Kolon("son_satis_gun", "Son Satıştan Gün", 105, "gun"),
                     Kolon("net", "Dönem Net Satış", 105, "para")]
        if maliyet_ok:
            kolonlar += [Kolon("kar", "Dönem Kârı", 95, "para"), Kolon("marj", "Marj %", 60, "yuzde")]
        kolonlar.append(Kolon("aciklama", "Açıklama", 250))
        return RaporEkrani(
            app, baslik="ÜRÜN SATIŞ HIZI VE STOKTA BEKLEYEN SERMAYE",
            alt="Mevcut stok, satış hızı, yeterlilik günü ve stok maliyet değeri",
            filtreler=[Filtre("tarih", "bas", "Satış dönemi başı", date.today().replace(day=1, month=1)),
                       Filtre("tarih", "bit", "Dönem sonu", date.today()),
                       Filtre("combo", "tur", "Göster", "tumu", [("tumu", "Tümü"), ("satis_yok", "Satışı olmayan stok"),
                                                               ("yavas", "Yavaş dönen"),
                                                               ("stoksuz_satan", "Stokta yok ama satılan")]),
                       Filtre("sayi", "yavas_gun", "Yavaş: yeterlilik > gün", 180),
                       Filtre("metin", "urun", "Ürün kodu / adı"),
                       Filtre("combo", "stok_grup_id", "Stok grubu", "", _grup_secenekleri()),
                       Filtre("combo", "depo", "Depo", "", _depo_secenekleri())],
            tablolar=[Tablo("satirlar", "Ürünler", kolonlar, etiket=lambda r: (
                "uyari" if r.get("aciklama") == "Stokta yok ama satılıyor" else (
                    "soluk" if r.get("aciklama", "").startswith("Dönemde satış yok") else None)))],
            hesapla=hesapla, ust=_ust, hafiza="satis_urun_hizi",
            toplam_metni=lambda s: (f"Stok maliyet değeri: {bicimle((s.get('toplam') or {}).get('stok_deger'), 'para')}"
                                    if (s.get("toplam") or {}).get("stok_deger") is not None else ""),
            **kw)

    return _ekran(app, "Ürün Satış Hızı", kur)


# ---------------------------------------------------------------------------
# 9) İskonto ve iade analizi
# ---------------------------------------------------------------------------

def iskonto_iade_goster(app, **kw) -> RaporEkrani | None:
    from database import satis_yonetici_rapor_service as srv

    def hesapla(f):
        fs = _servis_filtresi(f)
        s = srv.iskonto_iade_analizi(f["bas"], f["bit"], fs, f["boyut"])
        bas_kolon = {"musteri": [Kolon("cari_kodu", "Kod", 80), Kolon("unvan", "Müşteri", 200)],
                     "urun": [Kolon("urun_kodu", "Kod", 90), Kolon("urun_adi", "Ürün", 200)],
                     "grup": [Kolon("grup", "Ana Grup", 200)]}[f["boyut"]]
        s["_kolonlar"] = {"ozet": bas_kolon + [
            Kolon("brut", "Brüt", 100, "para"), Kolon("iskonto", "Satır İskontosu", 105, "para"),
            Kolon("belge_duzeltme", "Belge Geneli (−indirim)", 140, "para"),
            Kolon("toplam_iskonto", "Toplam İndirim", 105, "para"), Kolon("iskonto_orani", "Etkin İsk. %", 85, "yuzde"),
            Kolon("satis", "Satış (net)", 100, "para"), Kolon("iade", "İade Tutarı", 95, "para"),
            Kolon("iade_miktar", "İade Miktarı", 85, "miktar"), Kolon("iade_orani", "İade / Satış %", 95, "yuzde"),
            Kolon("kaynakli_iade", "Kaynaklı İade Satırı", 120, "gun"),
            Kolon("kaynaksiz_iade", "Kaynaksız İade Satırı", 125, "gun"), Kolon("net", "Net Satış", 100, "para")]}
        s["_bilgi"] = ["Para birimi: TL (KDV hariç)"]
        return s

    def kur():
        return RaporEkrani(
            app, baslik="İSKONTO VE İADE ANALİZİ",
            alt="Müşteri, ürün veya grup bazında iskonto ve iadeler (çift tık iade satırı: iade faturasını aç)",
            filtreler=[Filtre("tarih", "bas", "Başlangıç", _ay_basi()), Filtre("tarih", "bit", "Bitiş", date.today()),
                       Filtre("combo", "boyut", "Kırılım", "musteri", [("musteri", "Müşteri"), ("urun", "Ürün"),
                                                                     ("grup", "Stok grubu")]),
                       *_ortak_filtreler(maliyet=False)],
            tablolar=[Tablo("ozet", "Özet", [Kolon("bos", "", 100)]),
                      Tablo("iadeler", "İade Satırları", [
                          Kolon("belge_no", "İade No", 110), Kolon("tarih", "Tarih", 85, "tarih"),
                          Kolon("unvan", "Müşteri", 180), Kolon("urun_kodu", "Ürün Kodu", 90),
                          Kolon("urun_adi", "Ürün", 170), Kolon("miktar", "Miktar", 65, "miktar"),
                          Kolon("birim", "Birim", 50), Kolon("net", "Tutar (KDV hariç)", 110, "para"),
                          Kolon("kaynak_belge_no", "Kaynak Fatura", 110), Kolon("baglanti", "Bağlantı", 150)],
                          cift_tik=lambda r: _belge_ac(app, "IADE", r.get("belge_id")))],
            hesapla=hesapla, ust=_ust, hafiza="satis_iskonto_iade", **kw)

    return _ekran(app, "İskonto ve İade Analizi", kur)


# ---------------------------------------------------------------------------
# 10) Bekleyen satış siparişleri ve teslimat
# ---------------------------------------------------------------------------

def bekleyen_siparisler_goster(app, **kw) -> RaporEkrani | None:
    from database import satis_yonetici_rapor_service as srv

    def hesapla(f):
        fs = _servis_filtresi(f)
        s = srv.bekleyen_satis_siparisleri(fs, sadece_geciken=f["sadece_geciken"])
        s["_bilgi"] = ["Kalan tutar: TL, KDV hariç, sipariş kuru"]
        return s

    def kur():
        maliyet_ok = srv.maliyet_gorunur()
        kolonlar = [Kolon("siparis_no", "Sipariş", 105), Kolon("siparis_tarihi", "Tarih", 85, "tarih"),
                    Kolon("unvan", "Müşteri", 170), Kolon("urun_kodu", "Ürün Kodu", 90), Kolon("urun_adi", "Ürün", 160),
                    Kolon("birim", "Birim", 50), Kolon("siparis_miktar", "Sipariş", 70, "miktar"),
                    Kolon("karsilanan", "İrs./Fat. Karşılanan", 120, "miktar"),
                    Kolon("sevk_edilen", "Sevk Edilen", 85, "miktar"),
                    Kolon("sevk_bekleyen", "Sevk Bekleyen", 90, "miktar"), Kolon("kalan", "Kalan", 70, "miktar"),
                    Kolon("teslim_tarihi", "Teslim Tarihi", 90, "tarih"), Kolon("gecikme", "Gecikme Gün", 85, "gun"),
                    Kolon("kalan_tutar", "Kalan Tutar", 100, "para"), Kolon("para_birimi", "Belge PB", 60),
                    Kolon("stok_durumu", "Stok Yeterliliği", 130),
                    Kolon("karsilanabilir", "Stoktan Karşılanabilir", 130, "miktar")]
        if maliyet_ok:
            kolonlar.append(Kolon("tahmini_kar", "Tahmini Kâr", 100, "para"))
        kolonlar.append(Kolon("durum", "Sipariş Durumu", 115))
        return RaporEkrani(
            app, baslik="BEKLEYEN SATIŞ SİPARİŞLERİ VE TESLİMAT",
            alt="Kalan miktar, kısmi teslim, gecikme, stok yeterliliği ve tahmini kâr",
            filtreler=[Filtre("musteri", "cari_id", "Müşteri"), Filtre("metin", "urun", "Ürün kodu / adı"),
                       Filtre("check", "sadece_geciken", "Yalnız gecikenler", False)],
            tablolar=[Tablo("satirlar", "Sipariş Satırları", kolonlar, etiket=lambda r: (
                "uyari" if r.get("gecikme") or r.get("stok_durumu") == "Yetersiz" else None),
                cift_tik=lambda r: _belge_ac(app, "SIPARIS", r.get("siparis_id")))],
            hesapla=hesapla, ust=_ust, hafiza="satis_bekleyen_siparis",
            toplam_metni=lambda s: (
                f"Kalan tutar: {bicimle((s.get('toplam') or {}).get('kalan_tutar'), 'para')}   "
                f"Geciken satır: {(s.get('toplam') or {}).get('geciken', 0)}"
                + (f"   Tahmini kâr (gerçekleşmemiş): {bicimle(s['toplam']['tahmini_kar'], 'para')}"
                   if (s.get("toplam") or {}).get("tahmini_kar") is not None else "")) if s.get("toplam") else "",
            **kw)

    return _ekran(app, "Bekleyen Satış Siparişleri", kur)


# ---------------------------------------------------------------------------
# Müşteri bazında yıllık / aylık satışlar
# ---------------------------------------------------------------------------

def _musteri_grubu_secenekleri() -> list[tuple[str, str]]:
    out = [("", "(Tümü)")]
    try:
        from sqlalchemy import select

        from database.database import get_session
        from database.models.cari import MusteriGrubu

        with get_session() as s:
            out += [(g.ad, g.ad) for g in s.scalars(select(MusteriGrubu).order_by(MusteriGrubu.ad)).all()]
    except Exception:  # noqa: BLE001
        pass
    return out


TEMEL_BASLIK = "MÜŞTERİ BAZINDA YILLIK/AYLIK SATIŞLAR"


def standart_maliyet_goster(app) -> tk.Toplevel:
    """Karşılaştırma amaçlı standart maliyet tanımları (ürün, geçerlilik tarihi, temel birim maliyeti)."""
    from datetime import datetime
    from tkinter import ttk

    from database import satis_maliyet_motoru as motor

    pencere = tk.Toplevel(app)
    pencere.title("Standart Maliyetler (karşılaştırma amaçlı)")
    pencere.geometry("860x480")
    pencere.configure(bg=ACIK_BG)
    tk.Label(pencere, bg=ACIK_BG, anchor="w", justify="left", wraplength=820,
             text="Standart maliyet yalnız raporda karşılaştırma için kullanılır; stok, fatura ve muhasebe kayıtlarını "
                  "değiştirmez. Maliyet ürünün temel birimi başınadır ve geçerlilik tarihinden itibaren kullanılır. "
                  "Tanımı olmayan satışlar 'Eksik maliyet' görünür.").pack(fill="x", padx=10, pady=(8, 4))
    giris = tk.Frame(pencere, bg=ACIK_BG)
    giris.pack(fill="x", padx=10, pady=4)
    alanlar: dict[str, ttk.Entry] = {}
    for i, (anahtar, etiket, gen) in enumerate((("stok_kodu", "Stok kodu", 16), ("tarih", "Geçerlilik (GG.AA.YYYY)", 12),
                                                 ("maliyet", "Birim maliyet", 12), ("aciklama", "Açıklama", 28))):
        tk.Label(giris, text=etiket, bg=ACIK_BG).grid(row=0, column=i, sticky="w", padx=(0, 8))
        e = ttk.Entry(giris, width=gen)
        e.grid(row=1, column=i, sticky="w", padx=(0, 8))
        alanlar[anahtar] = e
    alanlar["tarih"].insert(0, date.today().strftime("%d.%m.%Y"))
    kolonlar = (("stok_kodu", "Stok Kodu", 100), ("stok_adi", "Ürün", 220), ("birim", "Temel Birim", 80),
                ("gecerlilik_tarihi", "Geçerlilik", 90), ("birim_maliyet", "Birim Maliyet", 100),
                ("aciklama", "Açıklama", 160), ("olusturan", "Kaydeden", 90))
    tablo = ttk.Treeview(pencere, columns=[k for k, _b, _g in kolonlar], show="headings", height=12)
    for k, b, g in kolonlar:
        tablo.heading(k, text=b)
        tablo.column(k, width=g, anchor="e" if k == "birim_maliyet" else "w")
    tablo.pack(fill="both", expand=True, padx=10, pady=4)
    kayitlar: list[dict] = []

    def yukle():
        kayitlar.clear()
        kayitlar.extend(motor.standart_maliyetler())
        tablo.delete(*tablo.get_children())
        for i, r in enumerate(kayitlar):
            tablo.insert("", "end", iid=str(i), values=[
                bicimle(r[k], "tarih" if k == "gecerlilik_tarihi" else ("fiyat" if k == "birim_maliyet" else "metin"))
                for k, _b, _g in kolonlar])

    def kaydet():
        try:
            tarih = datetime.strptime(alanlar["tarih"].get().strip(), "%d.%m.%Y").date()
            tutar = alanlar["maliyet"].get().strip()
            if "," in tutar:
                tutar = tutar.replace(".", "").replace(",", ".")
            motor.standart_maliyet_kaydet(alanlar["stok_kodu"].get(), tarih, tutar, alanlar["aciklama"].get())
        except Exception as hata:  # noqa: BLE001
            messagebox.showwarning("Standart maliyet", str(hata), parent=pencere)
            return
        yukle()

    def sil():
        secim = tablo.selection()
        if not secim:
            return
        r = kayitlar[int(secim[0])]
        if not messagebox.askyesno("Standart maliyet", f"{r['stok_kodu']} — {bicimle(r['gecerlilik_tarihi'], 'tarih')} "
                                   "tanımı silinsin mi?", parent=pencere):
            return
        try:
            motor.standart_maliyet_sil(r["id"])
        except Exception as hata:  # noqa: BLE001
            messagebox.showwarning("Standart maliyet", str(hata), parent=pencere)
            return
        yukle()

    from satis_tema import tk_buton

    btn = tk.Frame(pencere, bg=ACIK_BG)
    btn.pack(fill="x", padx=10, pady=(0, 8))
    tk_buton(btn, "Kaydet / Güncelle", kaydet, rol="ara").pack(side="left")
    tk_buton(btn, "Seçiliyi Sil", sil, rol="duzenle").pack(side="left", padx=6)
    tk_buton(btn, "Kapat", pencere.destroy, rol="duzenle").pack(side="right")
    try:
        yukle()
    except Exception as hata:  # noqa: BLE001
        messagebox.showwarning("Standart maliyet", str(hata), parent=pencere)
    pencere.yukle = yukle
    return pencere


AYLIK_TIP = {"net": "para", "maliyet": "para", "kar": "para", "marj": "yuzde", "fatura": "gun", "birlikte": "para"}


def _aylik_kolonlar(sonuc: dict) -> tuple[list[Kolon], list[Kolon]]:
    from database.satis_yonetici_rapor_service import AYLAR, BIRLIKTE_ALT

    g = sonuc["gosterge"]
    birlikte = g == "birlikte"
    gk = "net" if birlikte else g
    tip = AYLIK_TIP[gk]
    fark_tip = "fiyat" if gk == "marj" else tip
    yil = sonuc["yil"]

    def ay_adi(i: int) -> str:
        return AYLAR[i - 1] + (" (devam)" if sonuc["devam"] and i == sonuc["son_ay"] else "")

    aylar = [Kolon(f"ay_{i}", ay_adi(i), 105 if sonuc["devam"] and i == sonuc["son_ay"] else 92, tip)
             for i in range(1, 13)]
    ana = [Kolon("cari_kodu", "Müşteri Kodu", 85), Kolon("unvan", "Müşteri Unvanı", 210)]
    if birlikte:
        for i in range(1, 13):
            ana += [Kolon(f"ay_{i}_{a}", f"{AYLAR[i - 1][:3]} {ad}", 70 if a == "marj" else 88, AYLIK_TIP[a])
                    for a, ad in BIRLIKTE_ALT]
        ana += [Kolon(f"toplam_{a}", f"{yil} {ad}", 75 if a == "marj" else 100, AYLIK_TIP[a])
                for a, ad in BIRLIKTE_ALT]
    else:
        ana += [*aylar, Kolon("toplam", f"{yil} Toplam", 105, tip)]
    for y in sonuc["yillar"][1:]:
        ana += [Kolon(f"toplam_{y}", f"{y} " + ("Net" if birlikte else "Toplam"), 100, tip)]
        if birlikte:
            ana += [Kolon(f"kar_{y}", f"{y} Kâr", 95, "para"), Kolon(f"marj_{y}", f"{y} Marj %", 75, "yuzde")]
        ana.append(Kolon(f"fark_{y}", f"Fark ({yil}−{y})" + (" puan" if gk == "marj" else ""), 105, fark_tip))
        if gk != "marj":
            ana.append(Kolon(f"yuzde_{y}", "Değişim %", 80, "yuzde"))
    if sonuc["maliyet_gorunur"]:
        ana.append(Kolon("maliyet_durumu", "Maliyet Durumu", 190))
    kars = [Kolon("cari_kodu", "Müşteri Kodu", 85), Kolon("unvan", "Müşteri Unvanı", 190)]
    if birlikte:
        kars.append(Kolon("olcu", "Ölçü", 130))
    kars += [Kolon("satir", "Yıl / Fark", 140), Kolon("kapsam", "Kapsanan Tarihler", 170),
             *[Kolon(k.anahtar, k.baslik, k.genislik, tip) for k in aylar], Kolon("toplam", "Toplam", 120, tip)]
    return ana, kars


EKSIK_KOLONLARI = [Kolon("tarih", "Tarih", 85, "tarih"), Kolon("belge_turu", "Tür", 55),
                   Kolon("belge_no", "Belge No", 110), Kolon("unvan", "Müşteri", 180),
                   Kolon("urun_kodu", "Ürün Kodu", 90), Kolon("urun_adi", "Ürün", 180),
                   Kolon("miktar", "Miktar", 70, "miktar"), Kolon("birim", "Birim", 50),
                   Kolon("net", "Net", 95, "para"), Kolon("eksik_nedeni", "Eksik Nedeni / Kaynak", 330)]


def musteri_aylik_satis_goster(app, **kw) -> RaporEkrani | None:
    from database import satis_yonetici_rapor_service as srv
    from database.satis_yonetici_rapor_service import AYLAR, AYLIK_GOSTERGELER

    bu_yil = date.today().year
    durum_ekran: dict[str, RaporEkrani] = {}

    def hesapla(f):
        fs = _servis_filtresi(f)
        yil = int(f.get("yil") or bu_yil)
        kars = {yil - i for i in (1, 2, 3) if f.get(f"k{i}")}
        for parca in str(f.get("diger_yillar") or "").replace(";", ",").split(","):
            parca = parca.strip()
            if parca:
                if not parca.isdigit() or not 1900 < int(parca) <= bu_yil:
                    raise ValueError(f"Karşılaştırma yılı geçersiz: {parca}")
                kars.add(int(parca))
        sonuc = srv.musteri_aylik_satis(
            yil, gosterge=f.get("gosterge") or "net", karsilastirma=sorted(kars),
            ayni_tarihe_kadar=bool(f.get("ayni_tarihe_kadar")), filtre=fs, para_birimi=f.get("para_birimi") or "",
            siralama=f.get("siralama") or "toplam", siralama_ay=int(f["siralama_ay"]) if f.get("siralama_ay") else None,
            satissizlar=bool(f.get("satissizlar")))
        ana, karsilastirma = _aylik_kolonlar(sonuc)
        sonuc["_kolonlar"] = {"satirlar": ana, "karsilastirma": karsilastirma}
        sonuc["_bilgi"] = [f"Gösterge: {sonuc['gosterge_adi']}", f"Para birimi: {sonuc['birim']}",
                           f"Maliyet yöntemi: {sonuc['maliyet_yontemi']}"]
        sonuc["_filtre"] = fs
        return sonuc

    def aralik(yil: int, kolon: str | None) -> tuple[date, date, str]:
        ekran = durum_ekran["e"]
        parcalar = (kolon or "").split("_")
        if parcalar[0] == "ay" and len(parcalar) > 1 and parcalar[1].isdigit():
            ay = int(parcalar[1])
            from database.satis_yonetici_rapor_service import _ay_sonu

            return date(yil, ay, 1), _ay_sonu(yil, ay), f"{AYLAR[ay - 1]} {yil}"
        if parcalar[-1].isdigit() and len(parcalar[-1]) == 4:
            y = int(parcalar[-1])
            return date(y, 1, 1), date(y, 12, 31), str(y)
        y = ekran.sonuc.get("yil", yil)
        return date(y, 1, 1), date(y, 12, 31), str(y)

    def detay(r, yil=None):
        from database.satis_yonetici_rapor_service import HENUZ_GELMEDI, KAPSAM_DISI

        ekran = durum_ekran.get("e")
        if ekran is None or not ekran.sonuc:
            return
        kolon = ekran.son_kolon
        y = yil or ekran.sonuc.get("yil", bu_yil)
        if kolon and kolon.startswith("ay_") and r.get(kolon) in (HENUZ_GELMEDI, KAPSAM_DISI):
            return
        bas, bit, ad = aralik(y, kolon)
        if bit > date.today():
            bit = date.today()
        karlilik_detay_goster(app, "musteri", r.get("cari_id"), f"{r.get('unvan')} — {ad}", bas, bit,
                              ekran.sonuc.get("_filtre") or {})

    def etiket(r):
        if r.get("_sabit"):
            return "toplam"
        if r.get("_eksik") and durum_ekran["e"].sonuc.get("gosterge") in ("maliyet", "kar", "marj", "birlikte"):
            return "soluk"
        return None

    def kars_etiket(r):
        if str(r.get("satir", "")).startswith(("Fark", "Değişim")):
            return "soluk"
        return "toplam" if r.get("unvan") == "GENEL TOPLAM" else None

    def toplam(s):
        g = s.get("genel") or {}
        if not g:
            return ""
        ekran = durum_ekran.get("e")
        yontem = s.get("maliyet_yontemi") or "FIFO"
        if ekran is not None:
            ekran.baslik = TEMEL_BASLIK + (f" — {yontem}" if s.get("maliyet_gorunur") else "")
        if s["gosterge"] == "birlikte":
            metin = (f"{s['yil']} — Net: {bicimle(g.get('toplam_net'), 'para')}   "
                     f"Maliyet: {bicimle(g.get('toplam_maliyet'), 'para')}   "
                     f"Brüt satış kârı: {bicimle(g.get('toplam_kar'), 'para')}   "
                     f"Marj: {bicimle(g.get('toplam_marj'), 'yuzde')} {s['birim']}")
        else:
            tip = AYLIK_TIP[s["gosterge"]]
            metin = (f"{s['gosterge_adi']} — {s['yil']} toplam: {bicimle(g.get('toplam'), tip)} "
                     f"{s['birim'] if tip == 'para' else ''}")
        if s.get("maliyet_gorunur"):
            metin += f"   |   Maliyet yöntemi: {yontem}"
            if s.get("eksik"):
                metin += f"   |   Eksik maliyetli satır: {len(s['eksik'])}"
        return metin

    def standart_maliyetler(_e) -> None:
        standart_maliyet_goster(app)

    gostergeler = [(k, v[0]) for k, v in AYLIK_GOSTERGELER.items()]
    maliyet_ok = _yetki("maliyet_gorma") and _yetki("kar_gorma")
    if not maliyet_ok:
        gostergeler = [g for g in gostergeler if g[0] not in ("maliyet", "kar", "marj", "birlikte")]

    def kur():
        bos = [Kolon("bos", "", 100)]
        ekran = RaporEkrani(
            app, baslik=TEMEL_BASLIK,
            alt="Her müşteri bir satırda, Ocak–Aralık ve yıllık toplam; net satış, maliyet, brüt satış kârı ve marj; "
                "geçmiş yıllarla karşılaştırma (hücreye çift tık: o müşteri ve ayın ürün, fatura ve satır ayrıntısı)",
            filtreler=[
                Filtre("combo", "yil", "Yıl", str(bu_yil), [(str(y), str(y)) for y in range(bu_yil, bu_yil - 11, -1)]),
                Filtre("combo", "gosterge", "Gösterilecek bilgi", "net", gostergeler),
                Filtre("check", "k1", "Önceki yıl ile karşılaştır", False),
                Filtre("check", "k2", "2 yıl önce", False),
                Filtre("check", "k3", "3 yıl önce", False),
                Filtre("metin", "diger_yillar", "Diğer yıllar (ör. 2020, 2019)"),
                Filtre("check", "ayni_tarihe_kadar", "Önceki yılların aynı tarihine kadar", False),
                Filtre("combo", "siralama", "Sıralama", "toplam", [
                    ("toplam", "Yıllık toplam (göstergeye göre)"), ("ay", "Seçilen ayın değeri"),
                    ("kar", "Yıllık kâr"), ("degisim", "Değişim (ilk karşılaştırma yılına göre)"),
                    ("unvan", "Unvan (A–Z)")]),
                Filtre("combo", "siralama_ay", "Sıralama ayı", str(date.today().month),
                       [(str(i), AYLAR[i - 1]) for i in range(1, 13)]),
                Filtre("check", "satissizlar", "Satış yapmayan müşterileri göster", False),
                Filtre("combo", "para_birimi", "Para birimi", "", [
                    ("", "Tümü — TL karşılığı (belge kuru)"), ("TRY", "Yalnız TL belgeler"),
                    ("USD", "Yalnız USD belgeler (USD)"), ("EUR", "Yalnız EUR belgeler (EUR)"),
                    ("GBP", "Yalnız GBP belgeler (GBP)")]),
                Filtre("combo", "musteri_grubu", "Müşteri grubu", "", _musteri_grubu_secenekleri()),
                *_ortak_filtreler(urun=False, grup=False, maliyet=False),
                *([Filtre("combo", "maliyet_yontemi", "Maliyet yöntemi", "FIFO", AYLIK_MALIYET_SECENEK)]
                  if maliyet_ok else [])],
            tablolar=[Tablo("satirlar", "Aylık Satışlar", list(bos), cift_tik=detay, etiket=etiket),
                      Tablo("karsilastirma", "Yıl Karşılaştırması (aynı aylar)", list(bos),
                            cift_tik=lambda r: detay(r, r.get("_yil")) if r.get("_yil") else None,
                            etiket=kars_etiket),
                      Tablo("eksik", "Eksik maliyet", list(EKSIK_KOLONLARI),
                            cift_tik=lambda r: _belge_ac(app, r.get("_belge_turu"), r.get("belge_id")))],
            ek_butonlar=[("Standart Maliyetler", standart_maliyetler, "duzenle")] if maliyet_ok else None,
            hesapla=hesapla, toplam_metni=toplam, ust=_ust, hafiza="satis_musteri_aylik", **kw)
        durum_ekran["e"] = ekran
        return ekran

    return _ekran(app, "Müşteri Bazında Yıllık/Aylık Satışlar", kur)


# ---------------------------------------------------------------------------
# 11) Yönetici satış özeti
# ---------------------------------------------------------------------------

RAPOR_ACICILAR: dict[str, Callable] = {
    "musteri_aylik": musteri_aylik_satis_goster,
    "musteri_kar": musteri_karlilik_goster,
    "stok_kar": stok_karlilik_goster,
    "dusuk_marj": dusuk_marj_goster,
    "tahsilat": tahsilat_performansi_goster,
    "azalan": azalan_musteriler_goster,
    "urun_hizi": urun_satis_hizi_goster,
    "iskonto_iade": iskonto_iade_goster,
    "bekleyen_siparis": bekleyen_siparisler_goster,
}


def _rapor_ac(app, anahtar: str | None) -> None:
    fn = RAPOR_ACICILAR.get(anahtar or "")
    if fn is not None:
        fn(app)


def yonetici_ozeti_goster(app, **kw) -> RaporEkrani | None:
    from database import satis_yonetici_rapor_service as srv

    def hesapla(f):
        if not f.get("bas") or not f.get("bit"):
            raise ValueError("Dönem tarihlerini girin.")
        kars = _kars_araligi(f)
        fs = _servis_filtresi(f)
        s = srv.yonetici_ozeti((f["bas"], f["bit"]), kars, fs, hedef_marj=f["hedef_marj"])
        for g in s["gostergeler"]:
            g["donem_metin"] = (bicimle(g.get("donem"), "yuzde") if "marjı" in g["gosterge"]
                                else bicimle(g.get("donem"), "gun" if isinstance(g.get("donem"), int) else "para"))
            g["kars_metin"] = (bicimle(g.get("karsilastirma"), "yuzde") if "marjı" in g["gosterge"]
                               else bicimle(g.get("karsilastirma"), "para"))
            g["fark_metin"] = (f"{bicimle(g.get('fark'), 'fiyat')} puan" if g.get("degisim") == "puan"
                               else bicimle(g.get("fark"), "para"))
        s["_bilgi"] = _bilgi(fs, f"Karşılaştırma: {kars[0]:%d.%m.%Y}–{kars[1]:%d.%m.%Y}")
        return s

    def kur():
        maliyet_ok = srv.maliyet_gorunur()
        kisa = [Kolon("net", "Net Satış", 100, "para")]
        if maliyet_ok:
            kisa += [Kolon("kar", "Kâr", 90, "para"), Kolon("marj", "Marj %", 60, "yuzde")]
        kisa.append(Kolon("pay_satis", "Pay %", 55, "yuzde"))
        tablolar = [
            Tablo("gostergeler", "Göstergeler", [
                Kolon("gosterge", "Gösterge", 300), Kolon("tur", "Tür", 220),
                Kolon("donem_metin", "Seçili Dönem", 120), Kolon("kars_metin", "Karşılaştırma", 120),
                Kolon("fark_metin", "Fark", 110), Kolon("yuzde", "Değişim %", 80, "yuzde"),
                Kolon("aciklama", "Açıklama", 260)],
                cift_tik=lambda r: _rapor_ac(app, r.get("rapor"))),
            Tablo("musteriler", "En Çok Satılan Müşteriler",
                  [Kolon("cari_kodu", "Kod", 80), Kolon("unvan", "Müşteri", 220)] + kisa,
                  cift_tik=lambda r: _rapor_ac(app, "musteri_kar")),
            Tablo("urunler", "En Çok Satılan Ürünler",
                  [Kolon("urun_kodu", "Kod", 90), Kolon("urun_adi", "Ürün", 220)] + kisa,
                  cift_tik=lambda r: _rapor_ac(app, "stok_kar")),
            Tablo("azalan", "Satışı Azalan / Duran", [
                Kolon("unvan", "Müşteri", 220), Kolon("net_donem", "Dönem", 100, "para"),
                Kolon("net_kars", "Karşılaştırma", 100, "para"), Kolon("son_satis", "Son Satış", 85, "tarih"),
                Kolon("durum", "Durum", 300)], cift_tik=lambda r: _rapor_ac(app, "azalan")),
            Tablo("bekleyen", "Bekleyen Siparişler", [
                Kolon("siparis_no", "Sipariş", 105), Kolon("unvan", "Müşteri", 180), Kolon("urun_adi", "Ürün", 160),
                Kolon("kalan", "Kalan", 70, "miktar"), Kolon("teslim_tarihi", "Teslim", 85, "tarih"),
                Kolon("gecikme", "Gecikme", 65, "gun"), Kolon("kalan_tutar", "Kalan Tutar", 100, "para")],
                cift_tik=lambda r: _rapor_ac(app, "bekleyen_siparis")),
        ]
        if maliyet_ok:
            tablolar.insert(3, Tablo("dusuk_marj", "Düşük Marjlı Satışlar", [
                Kolon("durum", "Durum", 105), Kolon("unvan", "Müşteri", 170), Kolon("urun_adi", "Ürün", 170),
                Kolon("belge_no", "Fatura", 110), Kolon("net", "Net", 90, "para"), Kolon("kar", "Kâr", 85, "para"),
                Kolon("marj", "Marj %", 60, "yuzde")], cift_tik=lambda r: _rapor_ac(app, "dusuk_marj")))
        return RaporEkrani(
            app, baslik="YÖNETİCİ SATIŞ ÖZETİ",
            alt="Seçili dönem ve karşılaştırma dönemi tek ekranda (çift tık: ayrıntılı raporu aç)",
            filtreler=[Filtre("tarih", "bas", "Dönem başı", _ay_basi()), Filtre("tarih", "bit", "Dönem sonu", date.today()),
                       Filtre("combo", "kars", "Karşılaştırma", "onceki", [("onceki", "Önceki eş dönem"),
                                                                        ("gecen_yil_ayni", "Geçen yılın aynı dönemi")]),
                       Filtre("sayi", "hedef_marj", "Hedef marj %", 10),
                       Filtre("musteri", "cari_id", "Müşteri"),
                       Filtre("combo", "maliyet_yontemi", "Maliyet yöntemi", "FIFO", MALIYET_SECENEK)],
            tablolar=tablolar, hesapla=hesapla, ust=_ust, hafiza="satis_yonetici_ozet", **kw)

    return _ekran(app, "Yönetici Satış Özeti", kur)
