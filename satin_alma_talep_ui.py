"""Satın Alma Talebi evrak formu, talep listesi ve talepten siparişe aktarım penceresi."""

from __future__ import annotations

import os
import tkinter as tk
from datetime import date, datetime
from decimal import Decimal
from tkinter import filedialog, messagebox, simpledialog, ttk

import fatura_tema as ftema
from satin_alma_ui import _SatinAlmaSatirGirisi, _liste_ust, _para, _tarih, pencere_ac
from satis_tema import (
    ACIK_BG,
    ACIK_SARI,
    BEYAZ,
    IKINCIL,
    KOYU_LACIVERT,
    LACIVERT,
    SARI,
    UYARI,
    font,
    tk_buton,
    treeview_stil,
)

TALEP_BASLIGI = "SATIN ALMA TALEBİ"
TALEP_NOTU = ("İç ihtiyaç belgesidir: stok, cari, KDV veya muhasebe kaydı oluşturmaz. "
              "Tahmini bedeller bilgi amaçlıdır, finansal kayıt değildir.")
PARA_BIRIMLERI = ("TRY", "USD", "EUR", "GBP")


def _tarih_oku(metin: str) -> date | None:
    metin = (metin or "").strip()
    if not metin:
        return None
    for bicim in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(metin, bicim).date()
        except ValueError:
            continue
    raise ValueError(f"Tarih anlaşılamadı: {metin} (gg.aa.yyyy)")


def _sayi(v) -> str:
    from satir_ici_urun_giris import sayi_metni

    return "" if v is None else sayi_metni(v)


def _d(v) -> Decimal:
    return Decimal(str(v if v not in (None, "") else 0))


def _depolar() -> list[str]:
    try:
        from sqlalchemy import select

        from database.database import get_session
        from database.models.stok import Depo

        with get_session() as s:
            return [d for d in s.scalars(select(Depo.ad).where(Depo.aktif.is_(True)).order_by(Depo.ad)).all()]
    except Exception:  # noqa: BLE001
        return ["ANA DEPO"]


def talep_formu_ac(app, talep_id: int | None = None) -> "SatinAlmaTalepDialog | None":
    return pencere_ac(app, SatinAlmaTalepDialog, talep_id=talep_id, baslik="Satın alma talebi")


def _talep_kolonlari() -> tuple[tuple[str, str, int], ...]:
    from fatura_satir_kolon_prefs import EKRAN_TALEP, FATURA_SATIR_KOLON_TANIM

    return tuple((k, b, g) for k, b, g, *_ in FATURA_SATIR_KOLON_TANIM[EKRAN_TALEP])


# ===================================================================== form
class SatinAlmaTalepDialog(_SatinAlmaSatirGirisi, tk.Toplevel):
    _KOLONLAR = _talep_kolonlari()
    _FIYAT_KOLONLARI = ("fiyat", "pb", "kur", "kaynak", "tutar")

    def __init__(self, parent, talep_id=None):
        super().__init__(parent)
        from database.access import yetki_var
        from database.satin_alma_talep_service import ONCELIKLER, SatinAlmaTalepService
        from database.session_manager import oturum
        from satir_ici_urun_giris import HucreAlani
        from ui_pencere import evrak_penceresi_boyutlandir
        from ui_takvim import takvim_butonu

        self.SatinAlmaTalepService = SatinAlmaTalepService
        self.talep_id = talep_id
        self.row_version: int | None = None
        self._durum = "TASLAK"
        self._gorunen_durum = "TASLAK"
        self._isteyen_id = None
        self._kirli = False
        self._yukleniyor = True
        self._uyari_imzasi: tuple = ()
        self._stok_zamani: datetime | None = None
        self._fiyat_gor = yetki_var("alis_talep_fiyat_gorme", "maliyet_gorma")
        self._yetki_duzenle = yetki_var("alis_talep_duzenleme", "alis_duzenleme")
        self._yetki_onay = yetki_var("alis_talep_onay")
        self._yetki_iptal = yetki_var("alis_talep_iptal", "alis_talep_duzenleme", "alis_duzenleme", "iptal")
        self._yetki_aktarim = yetki_var("alis_talep_aktarim", "alis_talep_onay", "alis_duzenleme")
        self.title(TALEP_BASLIGI)
        self.configure(bg=ACIK_BG)
        evrak_penceresi_boyutlandir(self, genislik=1340, yukseklik=820, min_genislik=900, min_yukseklik=560)
        self.transient(parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel") else parent)

        # --- sarı evrak araç çubuğu (satın alma evrak düzeni)
        refs = ftema.ust_toolbar(self, baslik=TALEP_BASLIGI, fatura_no="Yeni", musteri_kisa="", durum="TASLAK")
        self._toolbar = refs
        refs["sol"].winfo_children()[0].configure(font=ftema.font(20, "bold", self))
        refs["musteri"].configure(text="İç ihtiyaç belgesi")
        self.durum_lbl = refs["rozet"]
        sag = refs["sag"]
        self.kaydet_btn = ftema.tk_buton(sag, "Kaydet (F1)", self._kaydet, rol="vurgu")
        self.kaydet_btn.pack(side="left", padx=3)
        for metin, islem in (("Önizle", "onizleme"), ("PDF", "pdf"), ("Word", "word"), ("Yazdır", "yazdir")):
            ftema.tk_buton(sag, metin, lambda i=islem: self.cikti(i), rol="ikincil").pack(side="left", padx=3)
        ftema.tk_buton(sag, "Kapat", self.kapat, rol="ikincil").pack(side="left", padx=(10, 3))
        ftema.renkleri_tersle(refs["cubuk"], haric=[self.durum_lbl])

        # --- alt çubuklar ekranın altına sabitlenir (kısa ekranda düğmeler görünür kalır)
        alt = tk.Frame(self, bg=ACIK_BG)
        alt.pack(side="bottom", fill="x", padx=10, pady=(2, 8))
        alt2 = tk.Frame(self, bg=ACIK_BG)
        alt2.pack(side="bottom", fill="x", padx=10, pady=(2, 0))
        self.mesaj_lbl = tk.Label(self, text="", bg=ACIK_BG, fg=LACIVERT, anchor="w", justify="left",
                                  wraplength=1200)
        self.mesaj_lbl.pack(side="bottom", fill="x", padx=12)
        toplam_fr = tk.Frame(self, bg=ACIK_SARI, highlightthickness=1, highlightbackground=SARI)
        toplam_fr.pack(side="bottom", fill="x", padx=10, pady=(2, 2))
        self.toplam_lbl = tk.Label(toplam_fr, text="", bg=ACIK_SARI, fg=KOYU_LACIVERT, anchor="w",
                                   font=font(10, "bold", self))
        self.toplam_lbl.pack(fill="x", padx=8, pady=(3, 0))
        tk.Label(toplam_fr, text=TALEP_NOTU, bg=ACIK_SARI, fg=IKINCIL, anchor="w", font=font(9, root=self)).pack(
            fill="x", padx=8, pady=(0, 3))

        self.gonder_btn = tk_buton(alt, "Onaya Gönder", self.onaya_gonder, rol="ara")
        self.onay_btn = tk_buton(alt, "Onayla", self.onayla, rol="kaydet")
        self.red_btn = tk_buton(alt, "Reddet", self.reddet, rol="iptal")
        self.geri_btn = tk_buton(alt, "Geri Gönder", self.geri_gonder, rol="duzenle")
        self.siparis_btn = tk_buton(alt, "Sipariş Oluştur", self.siparis_olustur, rol="yeni")
        self.teklif_btn = tk_buton(alt, "Teklife Aktar", self.teklife_aktar, rol="duzenle")
        self.iptal_btn = tk_buton(alt, "Talebi İptal Et", self.talep_iptal, rol="iptal")
        self.sil_btn = tk_buton(alt, "Taslağı Sil", self.talep_sil, rol="iptal")
        for b in (self.gonder_btn, self.onay_btn, self.red_btn, self.geri_btn, self.siparis_btn, self.teklif_btn,
                  self.iptal_btn, self.sil_btn):
            b.pack(side="left", padx=(0, 6))
        tk_buton(alt2, "Bağlı Belgeler", self.bagli_belgeler, rol="geri").pack(side="right", padx=(6, 0))
        tk_buton(alt2, "Geçmiş", self.gecmis_goster, rol="geri").pack(side="right", padx=(6, 0))
        tk_buton(alt2, "Ekler", self.ekler_goster, rol="geri").pack(side="right", padx=(6, 0))

        # --- başlık
        ust = tk.Frame(self, bg=ACIK_SARI, highlightthickness=1, highlightbackground=SARI)
        ust.pack(fill="x", padx=10, pady=(8, 4))
        for c in range(8):
            ust.columnconfigure(c, weight=1 if c % 2 else 0)

        def etiket(r, c, metin):
            tk.Label(ust, text=metin, bg=ACIK_SARI, fg=LACIVERT, font=font(10, "bold", self)).grid(
                row=r, column=c, sticky="w", padx=(10, 4), pady=3
            )

        def tarih_kutusu(r, c):
            fr = tk.Frame(ust, bg=ACIK_SARI)
            fr.grid(row=r, column=c, sticky="w", pady=3)
            e = ttk.Entry(fr, width=12)
            e.pack(side="left")
            btn = takvim_butonu(fr, e, on_select=self._degisti, width=7)
            return e, btn

        etiket(0, 0, "Talep No")
        self.no = ttk.Entry(ust, width=16)
        self.no.grid(row=0, column=1, sticky="we", pady=3)
        self.no.insert(0, SatinAlmaTalepService.talep_no() if not talep_id else "")
        etiket(0, 2, "Talep Tarihi")
        self.tarih, self._tarih_btn = tarih_kutusu(0, 3)
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        etiket(0, 4, "Firma")
        tk.Label(ust, text=oturum.firma_unvan or "", bg=ACIK_SARI, fg=KOYU_LACIVERT, anchor="w").grid(
            row=0, column=5, sticky="we")
        etiket(0, 6, "Talep Eden")
        self.isteyen_lbl = tk.Label(ust, text=oturum.ad_soyad or oturum.kullanici_adi or "", bg=ACIK_SARI,
                                    fg=KOYU_LACIVERT, anchor="w")
        self.isteyen_lbl.grid(row=0, column=7, sticky="we")
        etiket(1, 0, "Departman")
        self.departman = ttk.Entry(ust, width=18)
        self.departman.grid(row=1, column=1, sticky="we", pady=3)
        etiket(1, 2, "Depo")
        self.depo = ttk.Combobox(ust, values=_depolar(), width=16)
        self.depo.set("ANA DEPO")
        self.depo.grid(row=1, column=3, sticky="w", pady=3)
        etiket(1, 4, "Öncelik")
        self.oncelik = ttk.Combobox(ust, values=ONCELIKLER, state="readonly", width=12)
        self.oncelik.set("NORMAL")
        self.oncelik.grid(row=1, column=5, sticky="w", pady=3)
        etiket(1, 6, "İhtiyaç Tarihi")
        self.ihtiyac, self._ihtiyac_btn = tarih_kutusu(1, 7)
        etiket(2, 0, "Talep Nedeni")
        self.neden = ttk.Entry(ust)
        self.neden.grid(row=2, column=1, columnspan=3, sticky="we", pady=3)
        etiket(2, 4, "Proje / Referans")
        self.proje = ttk.Entry(ust)
        self.proje.grid(row=2, column=5, columnspan=3, sticky="we", pady=3, padx=(0, 10))
        etiket(3, 0, "Açıklama")
        self.aciklama = ttk.Entry(ust)
        self.aciklama.grid(row=3, column=1, columnspan=7, sticky="we", pady=(3, 8), padx=(0, 10))

        # --- satırlar
        satir_fr = tk.LabelFrame(self, text=" Talep Satırları ", bg=ACIK_BG, fg=LACIVERT, font=font(10, "bold", self))
        satir_fr.pack(fill="both", expand=True, padx=10, pady=4)
        arac = tk.Frame(satir_fr, bg=ACIK_BG)
        arac.pack(fill="x", pady=(2, 2))
        arac2 = tk.Frame(satir_fr, bg=ACIK_BG)
        arac2.pack(fill="x", pady=(0, 4))
        self._satir_dugmeleri = [
            tk_buton(arac, "Manuel Satır Ekle", self.manuel_satir_ekle, rol="ara"),
            tk_buton(arac, "Satırı Kopyala", self.satir_kopyala, rol="duzenle"),
            tk_buton(arac, "Tedarikçi Öner", self.tedarikci_oner, rol="duzenle"),
        ]
        for b in self._satir_dugmeleri:
            b.pack(side="left", padx=(0, 6))
        tk_buton(arac, "Tedarikçi Kartı", self.tedarikci_karti, rol="geri").pack(side="left", padx=(0, 6))
        self.eslestir_btn = tk_buton(arac, "Stok Kartıyla Eşleştir", self.stok_eslestir, rol="duzenle")
        self.eslestir_btn.pack(side="left", padx=(0, 6))
        self.kalan_iptal_btn = tk_buton(arac, "Kalanı İptal Et", self.kalan_iptal, rol="iptal")
        self.kalan_iptal_btn.pack(side="left", padx=(0, 6))
        self.yeniden_ac_btn = tk_buton(arac, "İadeyi Yeniden Aç", self.iade_yeniden_ac, rol="duzenle")
        self.yeniden_ac_btn.pack(side="left", padx=(0, 6))
        tk_buton(arac2, "Stok Bilgisini Yenile", self.stok_yenile, rol="ara").pack(side="left", padx=(0, 6))
        tk_buton(arac2, "Depo Stokları", self.depo_stoklari, rol="geri").pack(side="left", padx=(0, 6))
        tk_buton(arac2, "Kolonlar", self.kolon_ayarlari, rol="geri").pack(side="left", padx=(0, 6))
        self.stok_zaman_lbl = tk.Label(arac2, text="", bg=ACIK_BG, fg=IKINCIL, anchor="w")
        self.stok_zaman_lbl.pack(side="left", padx=(8, 0))
        self.satirlar: list[dict] = []
        alanlar = [
            HucreAlani("miktar", deger=lambda i: _sayi(self.satirlar[i].get("miktar") or 0)),
            HucreAlani("birim", "secim", secenekler=self._satir_birimleri, serbest=False),
            HucreAlani("aciklama", "metin", deger=lambda i: self.satirlar[i].get("aciklama") or ""),
            HucreAlani("ihtiyac", "metin", deger=lambda i: _tarih(self.satirlar[i].get("ihtiyac_tarihi"))),
        ]
        if self._fiyat_gor:
            alanlar += [
                HucreAlani("fiyat", deger=lambda i: _sayi(self.satirlar[i].get("tahmini_birim_fiyat"))),
                HucreAlani("pb", "secim", secenekler=lambda _i: PARA_BIRIMLERI, serbest=False),
                HucreAlani("kur", deger=lambda i: _sayi(self.satirlar[i].get("kur")), izin=self._kur_izin),
            ]
        self._satir_alani_kur(satir_fr, alanlar, depo=lambda: self.depo.get().strip())
        yatay = ttk.Scrollbar(satir_fr, orient="horizontal", command=self.satir_tablosu.xview)
        self.satir_tablosu.configure(xscrollcommand=yatay.set)
        yatay.pack(fill="x")
        self._kolon_ayar: dict = {}
        self._kolonlari_uygula()
        try:
            from fatura_satir_kolon_prefs import EKRAN_TALEP, resize_bagla

            resize_bagla(self.satir_tablosu, EKRAN_TALEP, ayar_getter=lambda: self._kolon_ayar,
                         ayar_setter=lambda a: setattr(self, "_kolon_ayar", a), parent=self)
        except Exception:  # noqa: BLE001
            pass
        self.satir_tablosu.tag_configure("eslesmemis", foreground=UYARI)

        for w in (self.tarih, self.departman, self.ihtiyac, self.neden, self.proje, self.aciklama, self.depo):
            w.bind("<KeyRelease>", self._degisti, add="+")
        self.oncelik.bind("<<ComboboxSelected>>", self._degisti, add="+")
        self.depo.bind("<<ComboboxSelected>>", self._depo_degisti, add="+")
        self.bind("<F1>", lambda _e: (self._kaydet(), "break")[1])
        self.protocol("WM_DELETE_WINDOW", self.kapat)
        if talep_id:
            self._yukle(int(talep_id))
        else:
            self._stok_zamani = datetime.now()
        self._yukleniyor = False
        self._kirli = False
        self._durum_uygula()
        self._toplam_guncelle()
        self._stok_zamani_goster()
        self._satir_ici_giris.odakla()

    # ---------------------------------------------------------- kolonlar
    def _kolonlari_uygula(self, ayar: dict | None = None) -> None:
        from fatura_satir_kolon_prefs import EKRAN_TALEP, tabloya_uygula

        try:
            self._kolon_ayar = tabloya_uygula(self.satir_tablosu, EKRAN_TALEP, ayar)
        except Exception:  # noqa: BLE001
            self._kolon_ayar = {}
        if not self._fiyat_gor:
            gorunen = [k for k in self.satir_tablosu["displaycolumns"] if k not in self._FIYAT_KOLONLARI]
            if gorunen == ["#all"]:
                gorunen = [k for k, *_ in self._KOLONLAR if k not in self._FIYAT_KOLONLARI]
            self.satir_tablosu["displaycolumns"] = gorunen

    def kolon_ayarlari(self):
        from fatura_satir_kolon_prefs import EKRAN_TALEP, FaturaSatirKolonAyarDialog

        FaturaSatirKolonAyarDialog(self, EKRAN_TALEP, self._kolon_ayar or {}, on_uygula=self._kolonlari_uygula,
                                   baslik="Talep Satırı Kolonları")

    # ---------------------------------------------------------- durum
    def _kilitli(self) -> bool:
        return getattr(self, "_durum", "TASLAK") != "TASLAK" or not getattr(self, "_yetki_duzenle", True)

    def _degisti(self, _e=None):
        if not self._yukleniyor and not self._kilitli():
            self._kirli = True

    def _satirlari_yenile(self) -> None:
        super()._satirlari_yenile()
        for i, s in enumerate(self.satirlar):
            if s.get("manuel") and not s.get("stok_id"):
                try:
                    self.satir_tablosu.item(str(i), tags=("eslesmemis",))
                except tk.TclError:
                    pass
        if hasattr(self, "toplam_lbl"):
            self._toplam_guncelle()
        if not getattr(self, "_yukleniyor", True):
            self._degisti()

    def _onayli(self) -> bool:
        return self._durum in ("ONAYLANDI", "SİPARİŞE AKTARILDI")

    def _durum_uygula(self):
        kilit = self._kilitli()
        durum = "disabled" if kilit else "normal"
        for w in (self.tarih, self.departman, self.ihtiyac, self.neden, self.proje, self.aciklama):
            w.configure(state=durum)
        for b in (self._tarih_btn, self._ihtiyac_btn):
            b.configure(state=durum)
        self.no.configure(state="readonly")
        self.depo.configure(state="disabled" if kilit else "normal")
        self.oncelik.configure(state="disabled" if kilit else "readonly")
        for b in self._satir_dugmeleri + [self.kaydet_btn]:
            b.configure(state=durum)
        onayli = self._onayli()
        self.gonder_btn.configure(state="normal" if self._durum == "TASLAK" and self._yetki_duzenle else "disabled")
        bekliyor = self._durum == "ONAYA GÖNDERİLDİ" and self._yetki_onay
        self.onay_btn.configure(state="normal" if bekliyor else "disabled")
        self.red_btn.configure(state="normal" if bekliyor else "disabled")
        self.geri_btn.configure(state="normal" if (bekliyor or (onayli and self._yetki_onay)) else "disabled")
        self.siparis_btn.configure(state="normal" if onayli and self._yetki_aktarim else "disabled")
        self.teklif_btn.configure(state="normal" if onayli else "disabled")
        self.kalan_iptal_btn.configure(state="normal" if onayli and self._yetki_iptal else "disabled")
        self.yeniden_ac_btn.configure(state="normal" if onayli and any(
            _d(s.get("yeniden_acilabilir")) > 0 for s in self.satirlar) else "disabled")
        self.eslestir_btn.configure(state="normal" if self._durum != "İPTAL" and self.talep_id else "disabled")
        self.iptal_btn.configure(
            state="normal" if self.talep_id and self._durum not in ("İPTAL",) and self._yetki_iptal else "disabled"
        )
        self.sil_btn.configure(state="normal" if self.talep_id and self._durum == "TASLAK" and self._yetki_duzenle
                               else "disabled")
        ftema.rozet_guncelle(self.durum_lbl, self._gorunen_durum)
        if self._gorunen_durum in ("REDDEDİLDİ",):
            self.durum_lbl.configure(bg=UYARI, fg=BEYAZ)
        elif self._gorunen_durum not in ftema.DURUM_RENKLERI:
            self.durum_lbl.configure(bg=LACIVERT, fg=SARI)
        try:
            self._toolbar["fatura_no"].configure(text=self.no.get() or "Yeni")
        except tk.TclError:
            pass
        self.title(f"{TALEP_BASLIGI} — {self.no.get() or 'Yeni'}")

    def _mesaj(self, metin: str, hata: bool = False):
        self.mesaj_lbl.configure(text=metin, fg=UYARI if hata else LACIVERT)

    # ---------------------------------------------------------- toplam
    @staticmethod
    def _satir_tutari(s: dict) -> Decimal | None:
        if s.get("tahmini_birim_fiyat") is None:
            return None
        return (_d(s.get("miktar")) * _d(s.get("tahmini_birim_fiyat"))).quantize(Decimal("0.01"))

    def toplam_metni(self) -> str:
        if not self._fiyat_gor:
            return "Tahmini bedeller: fiyat görme yetkiniz yok."
        para: dict[str, Decimal] = {}
        tl_karsilik = Decimal("0")
        fiyatsiz = 0
        for s in self.satirlar:
            tutar = self._satir_tutari(s)
            if tutar is None:
                fiyatsiz += 1
                continue
            pb = (s.get("para_birimi") or "TRY").upper()
            para[pb] = para.get(pb, Decimal("0")) + tutar
            tl_karsilik += tutar * (_d(s.get("kur")) if pb != "TRY" and s.get("kur") else Decimal("1"))
        if not para:
            return "Tahmini toplam: —"
        parcalar = [f"{_para(v)} {k}" for k, v in sorted(para.items(), key=lambda x: (x[0] != "TRY", x[0]))]
        metin = "Tahmini toplam (bilgi amaçlı): " + "  +  ".join(parcalar)
        if set(para) - {"TRY"}:
            metin += f"   (satır kurlarıyla ≈ {_para(tl_karsilik)} TRY)"
        if fiyatsiz:
            metin += f"   | {fiyatsiz} satır fiyatsız"
        return metin

    def _toplam_guncelle(self):
        self.toplam_lbl.configure(text=self.toplam_metni())

    # ---------------------------------------------------------- stok bilgisi
    def _stok_zamani_goster(self):
        z = self._stok_zamani
        self.stok_zaman_lbl.configure(
            text=(f"Stok bilgisi: {z:%d.%m.%Y %H:%M} itibarıyla — bilgi amaçlı, rezervasyon yapılmaz." if z else "")
        )

    def _stok_bilgisi(self, kod: str) -> dict:
        try:
            return self.SatinAlmaTalepService.stok_bilgisi(kod, self.depo.get().strip() or None)
        except Exception:  # noqa: BLE001
            return {"stok": None, "bekleyen": None, "diger_depo": None, "en_yakin_termin": None}

    def _stok_alanlarini_yaz(self, s: dict, bilgi: dict) -> None:
        s["stok"] = bilgi.get("stok")
        s["bekleyen"] = bilgi.get("bekleyen")
        s["diger"] = bilgi.get("diger_depo")
        s["termin"] = bilgi.get("en_yakin_termin")

    def stok_yenile(self):
        eski = self._yukleniyor
        self._yukleniyor = True
        try:
            for s in self.satirlar:
                if s.get("urun_kodu") and not (s.get("manuel") and not s.get("stok_id")):
                    self._stok_alanlarini_yaz(s, self._stok_bilgisi(s["urun_kodu"]))
            self._stok_zamani = datetime.now()
            self._satirlari_yenile()
        finally:
            self._yukleniyor = eski
        self._stok_zamani_goster()

    def _depo_degisti(self, _e=None):
        self._degisti()
        self.stok_yenile()

    def depo_stoklari(self):
        s = self._secili_satir()
        if s is None:
            return
        if not s.get("urun_kodu") or (s.get("manuel") and not s.get("stok_id")):
            messagebox.showinfo("Depo stokları", "Manuel satırın stok kartı yok.", parent=self)
            return
        try:
            satirlar = self.SatinAlmaTalepService.depo_stoklari(s["urun_kodu"])
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Depo stokları", str(e), parent=self)
            return
        secili_depo = self.depo.get().strip()
        metin = "\n".join(
            f"{'► ' if r['depo'] == secili_depo else '   '}{r['depo']}: {_sayi(r['miktar'])} {s.get('birim') or ''}"
            for r in satirlar
        ) or "Hiçbir depoda stok yok."
        messagebox.showinfo(
            f"Depo stokları — {s['urun_kodu']}",
            f"{metin}\n\nBilgi amaçlıdır; otomatik transfer veya rezervasyon yapılmaz. "
            "Başka depodan karşılamak için Depo Transfer ekranını kullanın.",
            parent=self,
        )

    # ---------------------------------------------------------- satırlar
    def _yeni_satir(self, degerler) -> dict:
        from database.stok_service import StokService

        kod = str(degerler[0] if degerler else "").strip()
        if not kod:
            raise ValueError("Stok bulunamadı.")
        bilgi = self._stok_bilgisi(kod)
        try:
            fiyat = Decimal(str(StokService.son_alis_fiyati(kod, Decimal("0")) or 0))
        except Exception:  # noqa: BLE001
            fiyat = Decimal("0")
        s = {
            "urun_kodu": kod,
            "urun_adi": str(degerler[1] if len(degerler) > 1 else "").strip() or kod,
            "birim": str(degerler[2] if len(degerler) > 2 else "").strip() or "Adet",
            "miktar": Decimal("1"),
            "aciklama": "",
            "manuel": False,
            "tahmini_birim_fiyat": fiyat if fiyat > 0 else None,
            "para_birimi": "TRY",
            "kur": Decimal("1"),
            "fiyat_kaynagi": "Son alış fiyatı" if fiyat > 0 else None,
        }
        self._stok_alanlarini_yaz(s, bilgi)
        return s

    def _termin_metni(self, s: dict) -> str:
        termin = s.get("siparis_termin") or s.get("termin")
        if not termin:
            return ""
        ihtiyac = s.get("ihtiyac_tarihi")
        if ihtiyac is None:
            try:
                ihtiyac = _tarih_oku(self.ihtiyac.get())
            except (ValueError, tk.TclError, AttributeError):
                ihtiyac = None
        return f"{_tarih(termin)} ⚠" if ihtiyac and termin > ihtiyac else _tarih(termin)

    def _satir_degerleri(self, s: dict) -> tuple:
        kod = s.get("urun_kodu") or ""
        if s.get("manuel") and not s.get("stok_id"):
            kod = "MANUEL"
        fiyatli = s.get("tahmini_birim_fiyat") is not None
        pb = (s.get("para_birimi") or "TRY") if fiyatli else ""
        degerler = {
            "kod": kod, "ad": s.get("urun_adi") or "", "aciklama": s.get("aciklama") or "",
            "birim": s.get("birim") or "", "miktar": _sayi(s.get("miktar")),
            "siparis": _sayi(s.get("siparis")), "teslim": _sayi(s.get("teslim")), "iade": _sayi(s.get("iade")),
            "iptal": _sayi(s.get("iptal")), "kalan": _sayi(s.get("kalan")),
            "stok": _sayi(s.get("stok")), "diger": _sayi(s.get("diger")), "bekleyen": _sayi(s.get("bekleyen")),
            "termin": self._termin_metni(s), "tedarikci": s.get("tedarikci") or "",
            "ihtiyac": _tarih(s.get("ihtiyac_tarihi")), "fiyat": _sayi(s.get("tahmini_birim_fiyat")), "pb": pb,
            "kur": _sayi(s.get("kur")) if fiyatli and pb != "TRY" else "",
            "kaynak": (s.get("fiyat_kaynagi") or "") if fiyatli else "",
            "tutar": _para(self._satir_tutari(s)) if fiyatli else "",
        }
        return tuple(degerler[k] for k, *_ in self._KOLONLAR)

    def _kur_izin(self, idx: int):
        if (self.satirlar[idx].get("para_birimi") or "TRY") == "TRY":
            return "TL satırda kur girilmez; önce döviz seçin."
        return True

    def _hucre_ozel(self, yeni: dict, kolon: str, metin: str) -> None:
        from satir_ici_urun_giris import ondalik

        if kolon == "ihtiyac":
            yeni["ihtiyac_tarihi"] = _tarih_oku(metin)
        elif kolon == "fiyat":
            fiyat = ondalik(metin) if metin else None
            if fiyat is not None and fiyat < 0:
                raise ValueError("Tahmini fiyat negatif olamaz.")
            yeni["tahmini_birim_fiyat"] = fiyat
            yeni["fiyat_kaynagi"] = "Elle" if fiyat is not None else None
        elif kolon == "pb":
            pb = (metin or "TRY").upper()
            if pb not in PARA_BIRIMLERI:
                raise ValueError("Geçersiz döviz.")
            eski = (yeni.get("para_birimi") or "TRY").upper()
            yeni["para_birimi"] = pb
            if pb == "TRY":
                yeni["kur"] = Decimal("1")
            elif pb != eski or _d(yeni.get("kur")) in (0, 1):
                try:
                    from database.doviz_service import DovizService

                    yeni["kur"] = DovizService.kur_degeri(date.today(), pb)
                except Exception:  # noqa: BLE001
                    yeni["kur"] = None
                    self.after_idle(lambda: self._mesaj(f"{pb} için güncel kur bulunamadı; Kur hücresine elle girin.",
                                                        hata=True))
        elif kolon == "kur":
            kur = ondalik(metin)
            if kur <= 0:
                raise ValueError("Kur sıfırdan büyük olmalıdır.")
            yeni["kur"] = kur

    def manuel_satir_ekle(self):
        if self._kilitli():
            return
        ad = simpledialog.askstring("Manuel satır", "Ürün / hizmet adı:", parent=self)
        if not ad or not ad.strip():
            return
        birim = simpledialog.askstring("Manuel satır", "Birim:", initialvalue="Adet", parent=self)
        if not birim or not birim.strip():
            return
        miktar = simpledialog.askstring("Manuel satır", "Miktar:", initialvalue="1", parent=self)
        if miktar is None:
            return
        teknik = simpledialog.askstring("Manuel satır", "Teknik açıklama (isteğe bağlı):", parent=self) or ""
        try:
            self.manuel_satir_ekle_degerle(ad, birim, miktar, teknik)
        except ValueError as e:
            messagebox.showwarning("Manuel satır", str(e), parent=self)

    def manuel_satir_ekle_degerle(self, ad: str, birim: str, miktar, teknik: str = "") -> None:
        from satir_ici_urun_giris import ondalik

        if not (ad or "").strip():
            raise ValueError("Ürün / hizmet adı zorunludur.")
        if not (birim or "").strip():
            raise ValueError("Birim zorunludur.")
        mik = ondalik(miktar)
        if mik <= 0:
            raise ValueError("Miktar sıfırdan büyük olmalıdır.")
        self.satirlar.append({
            "urun_kodu": "", "urun_adi": ad.strip(), "birim": birim.strip(), "miktar": mik,
            "aciklama": teknik.strip(), "manuel": True, "stok": None, "bekleyen": None,
            "tahmini_birim_fiyat": None, "para_birimi": "TRY", "kur": Decimal("1"),
        })
        self._satirlari_yenile()

    _KOPYALANMAYAN = ("id", "siparis", "teslim", "iade", "iptal", "kalan", "net_teslim", "yeniden_acilabilir",
                      "siparisler", "siparis_termin", "iptal_nedeni")

    def satir_kopyala(self, idx: int | None = None):
        if self._kilitli():
            return
        idx = self._secili_index() if idx is None else idx
        if idx is None:
            messagebox.showinfo("Kopyala", "Önce bir satır seçin.", parent=self)
            return
        kopya = {k: v for k, v in self.satirlar[idx].items() if k not in self._KOPYALANMAYAN}
        self.satirlar.insert(idx + 1, kopya)
        self._satirlari_yenile()
        try:
            self.satir_tablosu.selection_set(str(idx + 1))
        except tk.TclError:
            pass

    def tedarikci_oner(self):
        from database.alis_siparisi_service import AlisSiparisiService
        from satin_alma_ui import TedarikciSecDialog

        idx = self._secili_index()
        if idx is None or self._kilitli():
            messagebox.showinfo("Tedarikçi", "Önce bir satır seçin.", parent=self)
            return
        tedarikciler = AlisSiparisiService.aktif_tedarikcileri()
        dlg = TedarikciSecDialog(self, tedarikciler)
        self.wait_window(dlg)
        if dlg.result:
            cari = next((t for t in tedarikciler if int(t.id) == int(dlg.result[0])), None)
            self.satirlar[idx]["onerilen_tedarikci_id"] = int(dlg.result[0])
            self.satirlar[idx]["tedarikci"] = cari.unvan if cari else ""
            self._satirlari_yenile()

    def tedarikci_karti(self):
        s = self._secili_satir()
        if s is None:
            return
        if not s.get("onerilen_tedarikci_id"):
            messagebox.showinfo("Tedarikçi kartı", "Bu satırda önerilen tedarikçi yok (tedarikçi isteğe bağlıdır).",
                                parent=self)
            return
        from cari_kart_ui import CariDialog
        from database.cari_service import CariService

        cari = CariService.getir(int(s["onerilen_tedarikci_id"]))
        if cari is None:
            messagebox.showerror("Tedarikçi kartı", "Tedarikçi kartı bulunamadı.", parent=self)
            return
        CariDialog(self, cari=cari, cari_turu="Tedarikçi")

    def _satir_menusu(self, idx: int) -> list:
        ogeler = super()._satir_menusu(idx)
        ogeler += [
            ("Satırı Kopyala", lambda: self.satir_kopyala(idx)),
            ("Önerilen Tedarikçi…", self.tedarikci_oner),
            ("Tedarikçi Kartını Aç", self.tedarikci_karti),
            ("Depo Stokları…", self.depo_stoklari),
            ("Bağlı Belgeler…", self.bagli_belgeler),
            ("Kolon Ayarları…", self.kolon_ayarlari),
        ]
        if self._onayli():
            ogeler += [("Kalanı İptal Et…", self.kalan_iptal), ("İadeyi Yeniden Aç…", self.iade_yeniden_ac)]
        return ogeler

    # ------------------------------------------------------------- yükle
    def _yukle(self, talep_id: int):
        d = self.SatinAlmaTalepService.detay(talep_id)
        self._yukleniyor = True
        try:
            self.talep_id = int(d["id"])
            self.row_version = int(d["row_version"] or 1)
            self._durum = d["durum"]
            self._gorunen_durum = d["gorunen_durum"]
            self._isteyen_id = d.get("isteyen_kullanici_id")
            for w in (self.no, self.tarih, self.departman, self.ihtiyac, self.neden, self.proje, self.aciklama):
                w.configure(state="normal")
                w.delete(0, "end")
            self.no.insert(0, d["talep_no"])
            self.tarih.insert(0, _tarih(d["talep_tarihi"]))
            self.departman.insert(0, d.get("departman") or "")
            self.ihtiyac.insert(0, _tarih(d.get("ihtiyac_tarihi")))
            self.neden.insert(0, d.get("talep_nedeni") or "")
            self.proje.insert(0, d.get("proje_ref") or "")
            self.aciklama.insert(0, d.get("aciklama") or "")
            self.depo.configure(state="normal")
            self.depo.set(d.get("depo") or "ANA DEPO")
            self.oncelik.configure(state="readonly")
            self.oncelik.set(d.get("oncelik") or "NORMAL")
            self.isteyen_lbl.configure(text=d.get("isteyen_kullanici") or "")
            onayli = d["durum"] in ("ONAYLANDI", "SİPARİŞE AKTARILDI")
            self.satirlar = []
            for s in d["satirlar"]:
                satir = {
                    "id": s["id"], "urun_kodu": s["urun_kodu"], "urun_adi": s["urun_adi"], "aciklama": s["aciklama"],
                    "birim": s["birim"], "miktar": s["miktar"], "manuel": s["manuel"], "stok_id": s["stok_id"],
                    "stok": s["mevcut_stok"], "bekleyen": s["bekleyen_siparis"], "diger": s.get("diger_depo_stok"),
                    "termin": s.get("bekleyen_termin"), "siparis_termin": s.get("siparis_termin"),
                    "onerilen_tedarikci_id": s["onerilen_tedarikci_id"], "tedarikci": s["onerilen_tedarikci"],
                    "ihtiyac_tarihi": s["ihtiyac_tarihi"], "tahmini_birim_fiyat": s["tahmini_birim_fiyat"],
                    "para_birimi": s["para_birimi"], "kur": s["kur"], "fiyat_kaynagi": s["fiyat_kaynagi"],
                    "eslesmemis": s["eslesmemis"],
                }
                if onayli:
                    for k in ("siparis", "teslim", "iade", "iptal", "kalan", "net_teslim", "yeniden_acilabilir",
                              "siparisler"):
                        satir[k] = s.get(k)
                self.satirlar.append(satir)
            self._stok_zamani = d["satirlar"][0].get("stok_zamani") if d["satirlar"] else datetime.now()
            self._satirlari_yenile()
            notlar = []
            if d.get("geri_gonderme_nedeni") and d["durum"] == "TASLAK":
                notlar.append(f"Geri gönderme nedeni: {d['geri_gonderme_nedeni']}")
            if d.get("red_nedeni") and d["durum"] == "REDDEDİLDİ":
                notlar.append(f"Red nedeni: {d['red_nedeni']}")
            if d.get("onaylayan") and onayli:
                notlar.append(f"Onaylayan: {d['onaylayan']} ({_tarih(d.get('onay_tarihi'))})")
            if any(s["eslesmemis"] for s in d["satirlar"]):
                notlar.append("Manuel satırlar siparişe aktarılmadan önce stok kartıyla eşleştirilmelidir.")
            if onayli and any(_d(s.get("yeniden_acilabilir")) > 0 for s in d["satirlar"]):
                notlar.append("İade edilen miktar var; yeniden ihtiyaç ise 'İadeyi Yeniden Aç' ile açın.")
            self._mesaj("   |   ".join(notlar))
        finally:
            self._yukleniyor = False
        self._kirli = False
        self._stok_zamani_goster()

    # ---------------------------------------------------------- işlemler
    def _veriler(self) -> dict:
        return {
            "talep_no": self.no.get().strip(),
            "talep_tarihi": _tarih_oku(self.tarih.get()),
            "ihtiyac_tarihi": _tarih_oku(self.ihtiyac.get()),
            "depo": self.depo.get().strip() or "ANA DEPO",
            "departman": self.departman.get().strip(),
            "oncelik": self.oncelik.get(),
            "talep_nedeni": self.neden.get().strip(),
            "proje_ref": self.proje.get().strip(),
            "aciklama": self.aciklama.get().strip(),
        }

    def _tekrar_gerekcesi_sor(self, uyarilar: list[str]) -> str | None:
        metin = simpledialog.askstring(
            "Aynı ürün için açık talep var",
            "Aşağıdaki ürünler için açık talepler bulunuyor:\n\n" + "\n".join(uyarilar[:8])
            + "\n\nYine de devam etmek için gerekçe yazın:",
            parent=self,
        )
        return metin.strip() if metin and metin.strip() else None

    def _stok_yeterli_onayi(self) -> bool:
        yeterli = [
            f"{s.get('urun_kodu')} {s.get('urun_adi')}: depoda {_sayi(s.get('stok'))}, talep {_sayi(s.get('miktar'))}"
            for s in self.satirlar
            if s.get("stok") is not None and _d(s.get("miktar")) > 0 and _d(s.get("stok")) >= _d(s.get("miktar"))
            and not s.get("id")
        ]
        if not yeterli:
            return True
        return messagebox.askyesno(
            "Depoda yeterli stok var",
            "Seçili depoda talep miktarını karşılayan stok bulunuyor:\n\n" + "\n".join(yeterli[:8])
            + "\n\nYine de satın alma talebi kaydedilsin mi?",
            parent=self,
        )

    def _kaydet(self) -> bool:
        if self._kilitli():
            return False
        if not self._bekleyenleri_uygula():
            return False
        try:
            veriler = self._veriler()
        except ValueError as e:
            messagebox.showerror("Kaydedilemedi", str(e), parent=self)
            return False
        gerekce = None
        try:
            uyarilar = self.SatinAlmaTalepService.acik_talep_uyarilari(self.satirlar, self.talep_id)
        except Exception:  # noqa: BLE001
            uyarilar = []
        if uyarilar and tuple(uyarilar) != self._uyari_imzasi:
            gerekce = self._tekrar_gerekcesi_sor(uyarilar)
            if not gerekce:
                self._mesaj("Kayıt yapılmadı: aynı ürün için açık talep uyarısına gerekçe girilmedi.", hata=True)
                return False
        if not self._stok_yeterli_onayi():
            return False
        try:
            yeni_id = self.SatinAlmaTalepService.kaydet(veriler, self.satirlar, self.talep_id, self.row_version,
                                                        tekrar_gerekcesi=gerekce)
        except (ValueError, PermissionError) as e:
            messagebox.showerror("Kaydedilemedi", str(e), parent=self)
            return False
        if uyarilar:
            self._uyari_imzasi = tuple(uyarilar)
        self._yukle(yeni_id)
        self._durum_uygula()
        metin = f"{self.no.get()} kaydedildi ({datetime.now():%H:%M})."
        if uyarilar:
            metin += "  Aynı ürün için açık talepler: " + "; ".join(uyarilar[:4])
        self._mesaj(metin, hata=bool(uyarilar))
        return True

    def _kayitli_olmali(self) -> bool:
        if not self.talep_id:
            if not self._kaydet():
                return False
        elif self._kirli:
            if not messagebox.askyesno("Kaydedilmemiş değişiklik", "Önce değişiklikler kaydedilsin mi?", parent=self):
                return False
            if not self._kaydet():
                return False
        return True

    def _gecis(self, fn, *args, basari: str):
        try:
            fn(self.talep_id, *args)
        except (ValueError, PermissionError) as e:
            messagebox.showerror("Talep", str(e), parent=self)
            return False
        self._yukle(self.talep_id)
        self._durum_uygula()
        self._mesaj(basari)
        return True

    def onaya_gonder(self):
        if not self._kayitli_olmali():
            return False
        return self._gecis(self.SatinAlmaTalepService.onaya_gonder, basari="Talep onaya gönderildi; düzenleme kilitlendi.")

    def onayla(self):
        return self._gecis(self.SatinAlmaTalepService.onayla, basari="Talep onaylandı.")

    def _neden_sor(self, baslik: str) -> str | None:
        neden = simpledialog.askstring(baslik, f"{baslik} nedeni:", parent=self)
        return neden.strip() if neden and neden.strip() else None

    def reddet(self, neden: str | None = None):
        neden = neden or self._neden_sor("Red")
        if neden:
            return self._gecis(self.SatinAlmaTalepService.reddet, neden, basari="Talep reddedildi.")
        return False

    def geri_gonder(self, neden: str | None = None):
        neden = neden or self._neden_sor("Geri gönderme")
        if neden:
            return self._gecis(self.SatinAlmaTalepService.geri_gonder, neden,
                               basari="Talep düzeltme için taslağa geri gönderildi.")
        return False

    def talep_iptal(self):
        if not self.talep_id:
            return
        neden = self._neden_sor("İptal")
        if neden:
            self._gecis(self.SatinAlmaTalepService.iptal_et, neden, basari="Talep iptal edildi.")

    def talep_sil(self) -> bool:
        if not self.talep_id or self._durum != "TASLAK":
            return False
        if not messagebox.askyesno("Taslağı sil", f"{self.no.get()} taslak talebi silinsin mi?", parent=self):
            return False
        try:
            self.SatinAlmaTalepService.sil(self.talep_id)
        except (ValueError, PermissionError) as e:
            messagebox.showerror("Sil", str(e), parent=self)
            return False
        self._kirli = False
        self.destroy()
        return True

    def _secili_satir(self) -> dict | None:
        idx = self._secili_index()
        if idx is None:
            messagebox.showinfo("Seçim", "Önce bir satır seçin.", parent=self)
            return None
        return self.satirlar[idx]

    def kalan_iptal(self):
        s = self._secili_satir()
        if s is None or not s.get("id"):
            return
        miktar = simpledialog.askstring("Kalanı iptal et", f"İptal edilecek miktar (kalan {_sayi(s.get('kalan'))}):",
                                        initialvalue=_sayi(s.get("kalan")), parent=self)
        if not miktar:
            return
        neden = self._neden_sor("Kalan iptal")
        if not neden:
            return
        try:
            self.SatinAlmaTalepService.kalan_iptal(s["id"], miktar, neden)
        except (ValueError, PermissionError) as e:
            messagebox.showerror("Kalan iptal", str(e), parent=self)
            return
        self._yukle(self.talep_id)
        self._durum_uygula()

    def iade_yeniden_ac(self, miktar=None, neden: str | None = None) -> bool:
        s = self._secili_satir()
        if s is None or not s.get("id"):
            return False
        acilabilir = _d(s.get("yeniden_acilabilir"))
        if acilabilir <= 0:
            messagebox.showinfo("İadeyi yeniden aç", "Bu satırda yeniden açılabilecek iade miktarı yok.", parent=self)
            return False
        if miktar is None:
            miktar = simpledialog.askstring(
                "İadeyi yeniden aç",
                f"Tedarikçiye iade edilen {_sayi(s.get('iade'))} {s.get('birim')} miktarın ne kadarı yeniden "
                f"ihtiyaç olarak açılsın? (en fazla {_sayi(acilabilir)})",
                initialvalue=_sayi(acilabilir), parent=self)
            if not miktar:
                return False
        neden = neden or self._neden_sor("Yeniden açma")
        if not neden:
            return False
        try:
            self.SatinAlmaTalepService.iadeyi_yeniden_ac(s["id"], miktar, neden)
        except (ValueError, PermissionError) as e:
            messagebox.showerror("İadeyi yeniden aç", str(e), parent=self)
            return False
        self._yukle(self.talep_id)
        self._durum_uygula()
        self._mesaj("İade edilen miktar yeniden aktarılabilir ihtiyaca açıldı.")
        return True

    def stok_eslestir(self):
        s = self._secili_satir()
        if s is None or not s.get("id"):
            return
        if not s.get("manuel"):
            messagebox.showinfo("Eşleştir", "Bu satır zaten bir stok kartına bağlı.", parent=self)
            return
        kod = simpledialog.askstring("Stok kartıyla eşleştir", f"'{s['urun_adi']}' için stok kodu:", parent=self)
        if not kod:
            return
        try:
            self.SatinAlmaTalepService.manuel_satiri_eslestir(s["id"], kod)
        except (ValueError, PermissionError) as e:
            messagebox.showerror("Eşleştir", str(e), parent=self)
            return
        self._yukle(self.talep_id)
        self._durum_uygula()

    def siparis_olustur(self):
        if not self.talep_id or not self._onayli():
            return
        dlg = TalepAktarDialog(self, talep_id=self.talep_id)
        self.wait_window(dlg)
        if not dlg.result:
            return
        siparis_ac(self, dlg.result)
        self._yukle(self.talep_id)
        self._durum_uygula()

    def teklife_aktar(self):
        from database.alis_siparisi_service import AlisSiparisiService
        from database.tedarikci_teklif_service import TedarikciTeklifService
        from satin_alma_ui import TedarikciSecDialog

        if not self.talep_id:
            return
        tedarikciler = AlisSiparisiService.aktif_tedarikcileri()
        if not tedarikciler:
            messagebox.showerror("Teklif", "Aktif tedarikçi yok.", parent=self)
            return
        dlg = TedarikciSecDialog(self, tedarikciler)
        self.wait_window(dlg)
        if not dlg.result:
            return
        try:
            tid = TedarikciTeklifService.talepden_olustur(self.talep_id, dlg.result)
        except (ValueError, PermissionError) as e:
            messagebox.showerror("Teklif", str(e), parent=self)
            return
        self._mesaj(f"Tedarikçi teklif taslağı oluşturuldu (id={tid}).")

    def cikti(self, islem: str):
        if not self._kayitli_olmali():
            return None
        from talep_cikti_ui import cikti_al

        return cikti_al(self, self.talep_id, islem)

    def gecmis_goster(self):
        if not self.talep_id:
            messagebox.showinfo("Geçmiş", "Talep henüz kaydedilmedi.", parent=self)
            return
        g = self.SatinAlmaTalepService.detay(self.talep_id)["gecmis"]
        satirlar = [
            f"{x['tarih']:%d.%m.%Y %H:%M}  {x['islem']}  ({x['kullanici'] or '-'})"
            + (f"  {x['eski'] or ''} → {x['yeni']}" if x["yeni"] and x["eski"] != x["yeni"] else "")
            + (f"\n    {x['detay']}" if x["detay"] else "")
            for x in g
        ]
        messagebox.showinfo("İşlem geçmişi", "\n".join(satirlar) or "Kayıt yok.", parent=self)

    def ekler_goster(self):
        if not self._kayitli_olmali():
            return
        EklerDialog(self, self.talep_id, duzenlenebilir=self._durum in ("TASLAK", "REDDEDİLDİ"))

    def bagli_belgeler(self):
        if not self.talep_id:
            messagebox.showinfo("Bağlı belgeler", "Talep henüz kaydedilmedi.", parent=self)
            return None
        return BagliBelgelerDialog(self, self.talep_id, self.no.get())

    def kapat(self):
        if self._kirli and not self._kilitli():
            cevap = messagebox.askyesnocancel("Kaydedilmemiş değişiklik",
                                              "Değişiklikler kaydedilmedi. Kaydedilsin mi?", parent=self)
            if cevap is None:
                return
            if cevap and not self._kaydet():
                return
        self.destroy()


class EklerDialog(tk.Toplevel):
    def __init__(self, parent, talep_id: int, duzenlenebilir: bool = True):
        super().__init__(parent)
        from database.satin_alma_talep_service import EK_AZAMI_BAYT, EK_UZANTILARI, SatinAlmaTalepService

        self.S = SatinAlmaTalepService
        self.talep_id = talep_id
        self.title("Talep ekleri")
        self.geometry("620x360")
        self.transient(parent)
        tk.Label(self, text=f"İzin verilen türler: {', '.join(sorted(EK_UZANTILARI))} — en fazla "
                            f"{EK_AZAMI_BAYT // 1024 // 1024} MB. Dosyanın kopyası firma klasöründe saklanır.",
                 fg=IKINCIL, anchor="w", justify="left", wraplength=590).pack(fill="x", padx=8, pady=(8, 0))
        self.liste = ttk.Treeview(self, columns=("ad", "ekleyen", "tarih"), show="headings")
        treeview_stil(self.liste)
        for k, b, w in (("ad", "Dosya", 300), ("ekleyen", "Ekleyen", 130), ("tarih", "Tarih", 120)):
            self.liste.heading(k, text=b)
            self.liste.column(k, width=w)
        self.liste.pack(fill="both", expand=True, padx=8, pady=8)
        alt = tk.Frame(self)
        alt.pack(fill="x", padx=8, pady=(0, 8))
        durum = "normal" if duzenlenebilir else "disabled"
        tk_buton(alt, "Dosya Ekle", self.ekle, rol="yeni", state=durum).pack(side="left")
        tk_buton(alt, "Aç", self.ac, rol="duzenle").pack(side="left", padx=6)
        tk_buton(alt, "Kaldır", self.kaldir, rol="iptal", state=durum).pack(side="left")
        tk_buton(alt, "Kapat", self.destroy, rol="geri").pack(side="right")
        self.liste.bind("<Double-1>", lambda _e: self.ac())
        self.yenile()

    def yenile(self):
        self.liste.delete(*self.liste.get_children())
        for e in self.S.detay(self.talep_id)["ekler"]:
            self.liste.insert("", "end", iid=str(e["id"]), values=(e["dosya_adi"], e["ekleyen"] or "",
                                                                    f"{e['tarih']:%d.%m.%Y %H:%M}"))

    def ekle(self):
        yol = filedialog.askopenfilename(parent=self, title="Talebe eklenecek dosya")
        if not yol:
            return
        try:
            self.S.ek_ekle(self.talep_id, yol)
        except (ValueError, PermissionError, OSError) as e:
            messagebox.showerror("Ek", str(e), parent=self)
            return
        self.yenile()

    def ac(self):
        sec = self.liste.selection()
        if not sec:
            return
        try:
            os.startfile(str(self.S.ek_yolu(int(sec[0]))))  # noqa: S606
        except (ValueError, OSError) as e:
            messagebox.showerror("Ek açılamadı", str(e), parent=self)

    def kaldir(self):
        sec = self.liste.selection()
        if not sec or not messagebox.askyesno("Ek", "Seçili ek talepten kaldırılsın mı?", parent=self):
            return
        try:
            self.S.ek_sil(int(sec[0]))
        except (ValueError, PermissionError) as e:
            messagebox.showerror("Ek", str(e), parent=self)
            return
        self.yenile()


class BagliBelgelerDialog(tk.Toplevel):
    """Talep → sipariş → irsaliye → fatura / iade zinciri; çift tık belgeyi açar."""

    def __init__(self, parent, talep_id: int, talep_no: str = ""):
        super().__init__(parent)
        from database.satin_alma_talep_service import SatinAlmaTalepService

        self.S = SatinAlmaTalepService
        self.talep_id = int(talep_id)
        self.title(f"Bağlı belgeler — {talep_no}")
        self.geometry("720x380")
        self.transient(parent)
        tk.Label(self, text="Talepten oluşan sipariş ve ona bağlı irsaliye, fatura ve iade belgeleri. "
                            "Teslim miktarı irsaliye ve fatura arasında bir kez sayılır.",
                 fg=IKINCIL, anchor="w", wraplength=690, justify="left").pack(fill="x", padx=8, pady=(8, 0))
        self.tablo = ttk.Treeview(self, columns=("tur", "no", "tarih", "durum"), show="headings",
                                  selectmode="browse")
        treeview_stil(self.tablo)
        for k, b, w in (("tur", "Belge", 110), ("no", "Belge No", 200), ("tarih", "Tarih", 100),
                        ("durum", "Durum", 180)):
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=w)
        self.tablo.pack(fill="both", expand=True, padx=8, pady=8)
        alt = tk.Frame(self)
        alt.pack(fill="x", padx=8, pady=(0, 8))
        tk_buton(alt, "Belgeyi Aç", self.ac, rol="duzenle").pack(side="left")
        tk_buton(alt, "Kapat", self.destroy, rol="geri").pack(side="right")
        self.tablo.bind("<Double-1>", lambda _e: self.ac())
        self.belgeler = self.S.bagli_belgeler(self.talep_id)
        for i, b in enumerate(self.belgeler):
            self.tablo.insert("", "end", iid=str(i), values=(b["tur"], b["no"], _tarih(b["tarih"]), b["durum"]))
        if not self.belgeler:
            self.tablo.insert("", "end", iid="bos", values=("—", "Bağlı belge yok", "", ""))

    def ac(self):
        sec = self.tablo.selection()
        if not sec or sec[0] == "bos":
            return
        belge_ac(self, self.belgeler[int(sec[0])])


class SiparisTalepleriDialog(tk.Toplevel):
    """Alış siparişine pay aktaran talepler; çift tık talep formunu açar."""

    def __init__(self, parent, siparis_id: int, siparis_no: str = ""):
        super().__init__(parent)
        from database.satin_alma_talep_service import SatinAlmaTalepService

        self.title(f"Bağlı talepler — {siparis_no}")
        self.geometry("760x340")
        self.transient(parent)
        self.kayitlar = SatinAlmaTalepService.siparis_talepleri(int(siparis_id))
        self.tablo = ttk.Treeview(self, columns=("no", "tarih", "isteyen", "kod", "miktar", "birim"),
                                  show="headings", selectmode="browse")
        treeview_stil(self.tablo)
        for k, b, w, a in (("no", "Talep No", 110, "w"), ("tarih", "Tarih", 90, "center"),
                           ("isteyen", "Talep Eden", 160, "w"), ("kod", "Stok Kodu", 110, "w"),
                           ("miktar", "Siparişe Aktarılan", 120, "e"), ("birim", "Birim", 70, "center")):
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=w, anchor=a)
        self.tablo.pack(fill="both", expand=True, padx=8, pady=8)
        for i, r in enumerate(self.kayitlar):
            self.tablo.insert("", "end", iid=str(i), values=(r["talep_no"], _tarih(r["tarih"]), r["isteyen"],
                                                             r["urun_kodu"], _sayi(r["miktar"]), r["birim"]))
        if not self.kayitlar:
            self.tablo.insert("", "end", iid="bos", values=("—", "", "Bu sipariş talepten oluşmadı", "", "", ""))
        alt = tk.Frame(self)
        alt.pack(fill="x", padx=8, pady=(0, 8))
        tk_buton(alt, "Talebi Aç", self.ac, rol="duzenle").pack(side="left")
        tk_buton(alt, "Kapat", self.destroy, rol="geri").pack(side="right")
        self.tablo.bind("<Double-1>", lambda _e: self.ac())

    def ac(self):
        sec = self.tablo.selection()
        if not sec or sec[0] == "bos":
            return None
        return SatinAlmaTalepDialog(self, talep_id=self.kayitlar[int(sec[0])]["id"])


def belge_ac(parent, belge: dict):
    from alis_ui import AlisFaturasiDialog, AlisIadeFaturasiDialog, AlisIrsaliyesiDialog, AlisSiparisiDialog

    tur, bid = belge["tur"], int(belge["id"])
    if tur == "Sipariş":
        from database.alis_siparisi_service import AlisSiparisiService

        kayit = AlisSiparisiService.getir(bid)
        return AlisSiparisiDialog(parent, siparis=kayit) if kayit else None
    if tur == "İrsaliye":
        from database.alis_irsaliyesi_service import AlisIrsaliyesiService

        kayit = AlisIrsaliyesiService.getir(bid)
        return AlisIrsaliyesiDialog(parent, irsaliye=kayit) if kayit else None
    if tur == "Fatura":
        from database.alis_faturasi_service import AlisFaturasiService

        kayit = AlisFaturasiService.getir(bid)
        return AlisFaturasiDialog(parent, fatura=kayit) if kayit else None
    from database.alis_iade_faturasi_service import AlisIadeFaturasiService

    kayit = AlisIadeFaturasiService.getir(bid)
    return AlisIadeFaturasiDialog(parent, iade=kayit) if kayit else None


# ======================================================== aktarım penceresi
class TalepAktarDialog(tk.Toplevel):
    """Onaylı talep satırlarından aktarılacak miktarları seçer. result: {talep_satiri_id: Decimal}."""

    def __init__(self, parent, talep_id: int | None = None):
        super().__init__(parent)
        from database.satin_alma_talep_service import SatinAlmaTalepService

        self.result: dict[int, Decimal] | None = None
        self.title("Talepten Siparişe Aktar")
        self.configure(bg=ACIK_BG)
        self.geometry("1180x520")
        self.transient(parent)
        self.talep_id = talep_id
        self.satirlar = [s for s in SatinAlmaTalepService.aktarilabilir_satirlar()
                         if talep_id is None or s["talep_id"] == int(talep_id)]
        self.miktarlar = {s["talep_satiri_id"]: s["kalan"] for s in self.satirlar}
        self.secili = {s["talep_satiri_id"] for s in self.satirlar if not s["eslesmemis"]}
        tk.Label(self, text="İşaretli satırlar seçilen miktarla siparişe eklenir. 'Aktarılacak' hücresine çift "
                            "tıklayarak miktarı değiştirin. Miktar sipariş kaydedilene kadar tüketilmez. "
                            "Bir satırı farklı tedarikçilere bölmek için daha az miktar aktarın; kalan açık kalır.",
                 bg=ACIK_BG, fg=IKINCIL, anchor="w", justify="left", wraplength=1150).pack(fill="x", padx=10,
                                                                                           pady=(8, 4))
        cer = ttk.Frame(self)
        cer.pack(fill="both", expand=True, padx=10)
        kolonlar = (("sec", "Seç", 45), ("talep", "Talep No", 100), ("kod", "Stok Kodu", 90), ("ad", "Ürün", 200),
                    ("aciklama", "Teknik Açıklama", 170), ("birim", "Birim", 60), ("onayli", "Onaylı", 70),
                    ("siparis", "Siparişte", 70), ("kalan", "Kalan", 70), ("aktar", "Aktarılacak", 85),
                    ("ihtiyac", "İhtiyaç", 80), ("oncelik", "Öncelik", 70))
        self.tablo = ttk.Treeview(cer, columns=[k for k, *_ in kolonlar], show="headings")
        treeview_stil(self.tablo)
        for k, b, w in kolonlar:
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=w, anchor="center" if k in ("sec", "birim") else ("w" if k in (
                "talep", "kod", "ad", "aciklama", "oncelik") else "e"))
        self.tablo.pack(side="left", fill="both", expand=True)
        ttk.Scrollbar(cer, orient="vertical", command=self.tablo.yview).pack(side="right", fill="y")
        self.tablo.bind("<Button-1>", self._tikla)
        self.tablo.bind("<Double-1>", self._miktar_duzenle)
        alt = tk.Frame(self, bg=ACIK_BG)
        alt.pack(fill="x", padx=10, pady=8)
        tk_buton(alt, "Aktar", self.tamam, rol="kaydet").pack(side="right")
        tk_buton(alt, "Vazgeç", self.destroy, rol="geri").pack(side="right", padx=6)
        self._ciz()
        if not self.satirlar:
            tk.Label(alt, text="Aktarılabilir (onaylı ve kalanı olan) talep satırı yok.", bg=ACIK_BG, fg=UYARI).pack(
                side="left")

    def _ciz(self):
        self.tablo.delete(*self.tablo.get_children())
        for i, s in enumerate(self.satirlar):
            sid = s["talep_satiri_id"]
            self.tablo.insert("", "end", iid=str(sid), tags=("tek" if i % 2 == 0 else "cift",), values=(
                "⚠" if s["eslesmemis"] else ("☑" if sid in self.secili else "☐"), s["talep_no"],
                "MANUEL" if s["eslesmemis"] else s["urun_kodu"], s["urun_adi"], s["aciklama"], s["birim"],
                _sayi(s["onayli"]), _sayi(s["siparis"]), _sayi(s["kalan"]), _sayi(self.miktarlar[sid]),
                _tarih(s["ihtiyac_tarihi"]), s["oncelik"],
            ))

    def _tikla(self, event):
        if self.tablo.identify_column(event.x) != "#1":
            return
        iid = self.tablo.identify_row(event.y)
        if iid:
            self.sec_degistir(int(iid))
            return "break"

    def sec_degistir(self, sid: int):
        s = next(x for x in self.satirlar if x["talep_satiri_id"] == sid)
        if s["eslesmemis"]:
            messagebox.showwarning("Manuel satır", "Bu manuel satır önce talep formunda stok kartıyla eşleştirilmeli.",
                                   parent=self)
            return
        self.secili.symmetric_difference_update({sid})
        self._ciz()

    def _miktar_duzenle(self, event):
        iid = self.tablo.identify_row(event.y)
        if not iid or self.tablo.identify_column(event.x) == "#1":
            return
        sid = int(iid)
        metin = simpledialog.askstring("Aktarılacak miktar", "Miktar:", initialvalue=_sayi(self.miktarlar[sid]),
                                       parent=self)
        if metin is None:
            return
        try:
            self.miktar_ayarla(sid, metin)
        except ValueError as e:
            messagebox.showerror("Miktar", str(e), parent=self)

    def miktar_ayarla(self, sid: int, metin) -> None:
        from satir_ici_urun_giris import ondalik

        s = next(x for x in self.satirlar if x["talep_satiri_id"] == sid)
        mik = ondalik(metin)
        if mik <= 0:
            raise ValueError("Miktar sıfırdan büyük olmalıdır.")
        if mik > s["kalan"]:
            raise ValueError(f"Aktarılacak miktar kalanı ({_sayi(s['kalan'])}) aşamaz.")
        self.miktarlar[sid] = mik
        self.secili.add(sid)
        self._ciz()

    def tamam(self):
        if not self.secili:
            messagebox.showwarning("Seçim", "Aktarılacak satır seçin.", parent=self)
            return
        self.result = {sid: self.miktarlar[sid] for sid in sorted(self.secili)}
        self.destroy()


def siparis_ac(parent, miktarlar: dict[int, Decimal]):
    """Seçilen talep miktarlarıyla yeni alış siparişi kartını açar (kayıtla birlikte pay tüketilir)."""
    from alis_ui import AlisSiparisiDialog
    from database.alis_siparisi_service import AlisSiparisiService
    from database.satin_alma_talep_service import SatinAlmaTalepService

    try:
        hazir = SatinAlmaTalepService.siparis_satirlari_hazirla(miktarlar)
    except (ValueError, PermissionError) as e:
        messagebox.showerror("Sipariş Oluştur", str(e), parent=parent)
        return None
    cari = None
    if hazir["onerilen_tedarikci_id"]:
        cari = next((c for c in AlisSiparisiService.aktif_tedarikcileri()
                     if int(c.id) == int(hazir["onerilen_tedarikci_id"])), None)
    dlg = AlisSiparisiDialog(parent, cari=cari, hazir_satirlar=hazir["satirlar"])
    parent.wait_window(dlg)
    return dlg.result


# ===================================================================== liste
_LISTE_GORUNUMLERI = (
    ("Tümü", ""), ("Onay Bekleyenler", "onay_bekleyen"), ("Siparişe Aktarılmamış", "aktarilmamis"),
    ("Kısmen Aktarılmış", "kismen"), ("Geciken İhtiyaçlar", "geciken"),
)
_LISTE_KOLONLARI = (
    ("no", "Talep No", 105, "w"), ("tarih", "Tarih", 85, "center"), ("isteyen", "Talep Eden", 140, "w"),
    ("departman", "Departman", 110, "w"), ("depo", "Depo", 100, "w"), ("ihtiyac", "İhtiyaç Tarihi", 95, "center"),
    ("oncelik", "Öncelik", 75, "center"), ("durum", "Durum", 190, "w"), ("satir", "Satır", 50, "e"),
    ("toplam", "Tahmini Toplam", 115, "e"),
)
_ONCELIK_SIRASI = {"ACİL": 0, "YÜKSEK": 1, "NORMAL": 2, "DÜŞÜK": 3}


def _liste_sirala_anahtari(kolon: str):
    alanlar = {
        "no": lambda r: r["talep_no"], "tarih": lambda r: (r["talep_tarihi"] or date.min, r["id"]),
        "isteyen": lambda r: r["isteyen"].casefold(), "departman": lambda r: r["departman"].casefold(),
        "depo": lambda r: r["depo"].casefold(), "ihtiyac": lambda r: r["ihtiyac_tarihi"] or date.max,
        "oncelik": lambda r: _ONCELIK_SIRASI.get(r["oncelik"], 9), "durum": lambda r: r["durum"],
        "satir": lambda r: r["satir_adet"], "toplam": lambda r: r["tahmini_toplam"] or Decimal("0"),
    }
    return alanlar[kolon]


def satin_alma_talep_listesi_goster(app) -> dict:
    from database.satin_alma_talep_service import DURUMLAR, ONCELIKLER, SatinAlmaTalepService
    from satin_alma_ui import satin_alma_hub_goster

    kok = _liste_ust(app, "SATIN ALMA TALEP LİSTESİ",
                     "Talepleri filtreleyin, açın, onaylayın ve siparişe aktarın",
                     lambda: satin_alma_hub_goster(app))
    f1 = tk.Frame(kok, bg=ACIK_BG)
    f1.pack(fill="x", padx=16, pady=(8, 0))
    f2 = tk.Frame(kok, bg=ACIK_BG)
    f2.pack(fill="x", padx=16, pady=(4, 0))
    f3 = tk.Frame(kok, bg=ACIK_BG)
    f3.pack(fill="x", padx=16, pady=(4, 0))
    alanlar: dict[str, tk.Widget] = {}

    def alan(parent, metin, anahtar, genislik=12, degerler=None, varsayilan=""):
        tk.Label(parent, text=metin, bg=ACIK_BG, fg=LACIVERT, font=font(10, "bold", app)).pack(side="left",
                                                                                               padx=(8, 2))
        if degerler is not None:
            w = ttk.Combobox(parent, values=degerler, state="readonly", width=genislik)
            w.set(varsayilan or degerler[0])
        else:
            w = ttk.Entry(parent, width=genislik)
            w.insert(0, varsayilan)
        w.pack(side="left")
        alanlar[anahtar] = w

    alan(f1, "Başlangıç", "bas", 11, varsayilan=date(date.today().year, 1, 1).strftime("%d.%m.%Y"))
    alan(f1, "Bitiş", "bit", 11, varsayilan=date.today().strftime("%d.%m.%Y"))
    alan(f1, "Talep No", "no", 12)
    alan(f1, "Talep Eden", "isteyen", 16)
    alan(f1, "Departman / Depo", "dd", 16)
    alan(f2, "Durum", "durum", 26, ("Tümü",) + DURUMLAR)
    alan(f2, "Öncelik", "oncelik", 10, ("Tümü",) + ONCELIKLER)
    alan(f2, "Stok", "stok", 16)
    gorunum = tk.StringVar(value="")
    for metin, deger in _LISTE_GORUNUMLERI:
        tk.Radiobutton(f3, text=metin, variable=gorunum, value=deger, tristatevalue="\x00", bg=ACIK_BG, fg=LACIVERT,
                       command=lambda: yenile()).pack(side="left", padx=(8, 0))

    cer = ttk.Frame(kok)
    cer.pack(fill="both", expand=True, padx=16, pady=8)
    tablo = ttk.Treeview(cer, columns=[k for k, *_ in _LISTE_KOLONLARI], show="headings", selectmode="browse")
    treeview_stil(tablo)
    siralama = {"kolon": None, "ters": False}
    for k, b, w, a in _LISTE_KOLONLARI:
        tablo.heading(k, text=b, command=lambda kol=k: sirala(kol))
        tablo.column(k, width=w, anchor=a)
    tablo.pack(side="left", fill="both", expand=True)
    ttk.Scrollbar(cer, orient="vertical", command=tablo.yview).pack(side="right", fill="y")
    tablo.tag_configure("gecikmis", foreground=UYARI)
    durum = {"kayitlar": []}

    def ciz():
        kayitlar = list(durum["kayitlar"])
        if siralama["kolon"]:
            kayitlar.sort(key=_liste_sirala_anahtari(siralama["kolon"]), reverse=siralama["ters"])
        for k, b, *_ in _LISTE_KOLONLARI:
            ok = (" ▼" if siralama["ters"] else " ▲") if k == siralama["kolon"] else ""
            tablo.heading(k, text=b + ok)
        tablo.delete(*tablo.get_children())
        for i, r in enumerate(kayitlar):
            etiketler = ["tek" if i % 2 == 0 else "cift"]
            if r["ihtiyac_tarihi"] and r["ihtiyac_tarihi"] < date.today() and r["durum"] not in (
                    "TAMAMLANDI", "İPTAL", "REDDEDİLDİ"):
                etiketler.append("gecikmis")
            tablo.insert("", "end", iid=str(r["id"]), tags=tuple(etiketler), values=(
                r["talep_no"], _tarih(r["talep_tarihi"]), r["isteyen"], r["departman"], r["depo"],
                _tarih(r["ihtiyac_tarihi"]), r["oncelik"], r["durum"], r["satir_adet"],
                _para(r["tahmini_toplam"]) if r["tahmini_toplam"] is not None else "—",
            ))
        ozet_lbl.configure(text=f"{len(kayitlar)} talep. Tahmini toplam bilgi amaçlıdır; finansal kayıt değildir. "
                                "Dövizli satırlar talepteki kurla TL'ye çevrilir.")

    def sirala(kolon: str):
        siralama["ters"] = not siralama["ters"] if siralama["kolon"] == kolon else False
        siralama["kolon"] = kolon
        ciz()

    def yenile():
        try:
            durum["kayitlar"] = SatinAlmaTalepService.listele(
                alanlar["durum"].get(), baslangic=_tarih_oku(alanlar["bas"].get()),
                bitis=_tarih_oku(alanlar["bit"].get()), no=alanlar["no"].get(), isteyen=alanlar["isteyen"].get(),
                departman_depo=alanlar["dd"].get(), oncelik=alanlar["oncelik"].get(), stok=alanlar["stok"].get(),
                gorunum=gorunum.get() or None,
            )
        except (ValueError, PermissionError) as e:
            messagebox.showerror("Talep listesi", str(e), parent=app)
            return
        ciz()

    def ac(talep_id=None):
        dlg = talep_formu_ac(app, talep_id)
        if dlg is not None and dlg.winfo_exists():
            app.wait_window(dlg)
        yenile()

    def secili_id() -> int | None:
        sec = tablo.selection()
        if not sec:
            messagebox.showinfo("Seçim", "Talep seçin.", parent=app)
            return None
        return int(sec[0])

    def secili_ac(_e=None):
        tid = secili_id()
        if tid is not None:
            ac(tid)

    def sil():
        tid = secili_id()
        if tid is None:
            return
        no = tablo.set(str(tid), "no")
        if not messagebox.askyesno("Talep sil", f"{no} silinsin mi?\nYalnızca siparişe bağlanmamış taslak silinir; "
                                                "diğer durumlar iptal edilmelidir.", parent=app):
            return
        try:
            SatinAlmaTalepService.sil(tid)
        except (ValueError, PermissionError) as e:
            messagebox.showerror("Talep sil", str(e), parent=app)
            return
        yenile()

    alt = tk.Frame(kok, bg=ACIK_BG)
    alt.pack(side="bottom", fill="x", padx=16, pady=10)
    ozet_lbl = tk.Label(kok, text="", bg=ACIK_BG, fg=IKINCIL, anchor="w")
    ozet_lbl.pack(side="bottom", fill="x", padx=18)
    tk_buton(alt, "Yeni Talep", lambda: ac(None), rol="yeni").pack(side="left")
    tk_buton(alt, "Aç", secili_ac, rol="duzenle").pack(side="left", padx=6)
    tk_buton(alt, "Sil", sil, rol="iptal").pack(side="left")
    tk_buton(alt, "Ürün Bazlı Rapor", lambda: pencere_ac(app, UrunBazliRaporDialog, baslik="Ürün bazlı talep raporu"),
             rol="geri").pack(side="left", padx=6)
    tk_buton(alt, "Listele", yenile, rol="ara").pack(side="right")
    tablo.bind("<Double-1>", secili_ac)
    tablo.bind("<Return>", secili_ac)
    for anahtar, w in alanlar.items():
        if isinstance(w, ttk.Combobox):
            w.bind("<<ComboboxSelected>>", lambda _e: yenile())
        else:
            w.bind("<Return>", lambda _e: yenile())
    yenile()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: satin_alma_talep_listesi_goster(app))
    return {"tablo": tablo, "yenile": yenile, "sirala": sirala, "gorunum": gorunum, "alanlar": alanlar,
            "secili_ac": secili_ac}


class UrunBazliRaporDialog(tk.Toplevel):
    _KOLONLAR = (
        ("kod", "Stok Kodu", 95), ("ad", "Ürün", 200), ("birim", "Birim", 55), ("adet", "Talep Sayısı", 80),
        ("talep", "Talep", 70), ("onayli", "Onaylı", 70), ("siparis", "Sipariş Payı", 85),
        ("teslim", "Teslim", 70), ("iade", "İade", 60), ("net_teslim", "Net Teslim", 80), ("iptal", "İptal", 60),
        ("kalan", "Aktarılmamış Açık İhtiyaç", 150), ("bekleyen_teslim", "Sipariş Verilmiş – Teslim Bekleyen", 190),
    )

    def __init__(self, parent):
        super().__init__(parent)
        from database.satin_alma_talep_service import SatinAlmaTalepService

        self.S = SatinAlmaTalepService
        self.title("Ürün bazlı talep raporu")
        self.geometry("1320x540")
        self.transient(parent)
        ust = tk.Frame(self)
        ust.pack(fill="x", padx=8, pady=(8, 0))
        self.bas = self._alan(ust, "Başlangıç", date(date.today().year, 1, 1).strftime("%d.%m.%Y"))
        self.bit = self._alan(ust, "Bitiş", date.today().strftime("%d.%m.%Y"))
        tk.Label(ust, text="Depo").pack(side="left", padx=(8, 2))
        self.depo = ttk.Combobox(ust, values=["Tümü"] + _depolar(), state="readonly", width=16)
        self.depo.set("Tümü")
        self.depo.pack(side="left")
        self.stok = self._alan(ust, "Stok", "", 16)
        tk_buton(ust, "Listele", self.yenile, rol="ara").pack(side="left", padx=8)
        self.kapsam_lbl = tk.Label(self, text="", fg=IKINCIL, anchor="w", justify="left")
        self.kapsam_lbl.pack(fill="x", padx=10, pady=(4, 0))
        self.tablo = ttk.Treeview(self, columns=[k for k, *_ in self._KOLONLAR], show="headings")
        treeview_stil(self.tablo)
        for k, b, w in self._KOLONLAR:
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=w, anchor="w" if k in ("kod", "ad") else "e")
        self.tablo.pack(fill="both", expand=True, padx=8, pady=8)
        self.depo.bind("<<ComboboxSelected>>", lambda _e: self.yenile())
        self.yenile()

    @staticmethod
    def _alan(parent, metin, deger, genislik=11):
        tk.Label(parent, text=metin).pack(side="left", padx=(8, 2))
        e = ttk.Entry(parent, width=genislik)
        e.insert(0, deger)
        e.pack(side="left")
        e.bind("<Return>", lambda _e: parent.winfo_toplevel().yenile())
        return e

    def yenile(self):
        try:
            bas, bit = _tarih_oku(self.bas.get()), _tarih_oku(self.bit.get())
            satirlar = self.S.urun_bazli_rapor(bas, bit, depo=self.depo.get(), stok=self.stok.get())
        except (ValueError, PermissionError) as e:
            messagebox.showerror("Rapor", str(e), parent=self)
            return
        self.kapsam_lbl.configure(text=(
            f"Kapsam: talep tarihi {_tarih(bas) or 'başlangıçsız'} – {_tarih(bit) or 'bugün'} | Depo: {self.depo.get()}"
            f"{' | Stok: ' + self.stok.get() if self.stok.get().strip() else ''} | İptal talepler hariç. "
            "Farklı birimler ayrı satırda gösterilir, toplanmaz."
        ))
        self.tablo.delete(*self.tablo.get_children())
        for i, r in enumerate(satirlar):
            self.tablo.insert("", "end", tags=("tek" if i % 2 == 0 else "cift",), values=(
                r["urun_kodu"] or "MANUEL", r["urun_adi"], r["birim"], r["talep_sayisi"],
                *(_sayi(r[k]) for k in ("talep", "onayli", "siparis", "teslim", "iade", "net_teslim", "iptal",
                                        "kalan", "bekleyen_teslim")),
            ))
        self.satirlar = satirlar
