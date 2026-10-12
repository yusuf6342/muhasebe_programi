"""Finans → Ödeme Takvimi: dört aylık kart, kredi taksiti, sabit gider, vergi / SGK ve borç çek / senet ödemeleri.

Satırdan kaynağa uygun mevcut ödeme evrakı açılır (kart ekstre ödemesi, kredi taksit ödemesi, sabit gider
ödemesi, çek / senet ödemesi). Toplamlar kayıt edilmiş geçerli ödemelerle kendiliğinden yenilenir; ekranı açmak kayıt üretmez.
"""

from __future__ import annotations

import tkinter as tk
from datetime import date, datetime
from tkinter import messagebox, ttk

from ana_panel_tema import (
    ACIK_BG,
    BEYAZ,
    CIZGI,
    FONT_ALT,
    FONT_KUCUK,
    FONT_UI_BOLD,
    KOYU_LACIVERT,
    LACIVERT,
    METIN,
    PASIF,
    SARI,
    UYARI,
    para_tr,
)
from database import odeme_takvimi_service as ots
from database.access import yetki_var
from giris_paneli_ui import _buton, tablo_stili

OKUMA_YETKISI = ("finans_goruntuleme", "finans_duzenleme", "odeme_durumu_goruntuleme")
YOKLAMA_MS = 1500
KOLONLAR = (
    ("tarih", "Tarih", 120, "w"), ("gun", "Gün", 90, "w"), ("tur", "Borç türü", 120, "w"),
    ("aciklama", "Hesap ve açıklama", 520, "w"), ("kalan", "Kalan TL", 140, "e"),
)


def _tarih(t) -> str:
    return t.strftime("%d.%m.%Y") if isinstance(t, date) else "—"


def _buyuk(metin: str) -> str:
    return str(metin).replace("i", "İ").replace("ı", "I").upper()


def odeme_takvimi_goster(app) -> None:
    if not yetki_var(*OKUMA_YETKISI):
        messagebox.showerror("Ödeme Takvimi", "Ödeme takvimini görüntüleme yetkiniz yok.")
        return
    app._icerigi_temizle()
    try:
        from finans_ui import _finans_menu_isaretle

        _finans_menu_isaretle(app)
    except Exception:  # noqa: BLE001
        pass
    OdemeTakvimiSayfasi(app.icerik, app).pack(fill="both", expand=True)
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: odeme_takvimi_goster(app))


class OdemeTakvimiSayfasi(tk.Frame):
    def __init__(self, parent, app=None, *, bugun_fn=None):
        super().__init__(parent, bg=ACIK_BG)
        self.app = app
        self._bugun_fn = bugun_fn or date.today
        self._veri: dict | None = None
        self._kalemler: dict[str, dict] = {}
        self._imza = None
        self._yoklama = None

        ust = tk.Frame(self, bg=LACIVERT)
        ust.pack(fill="x")
        tk.Label(ust, text="ÖDEME TAKVİMİ", bg=LACIVERT, fg=BEYAZ, font=("Segoe UI", 13, "bold")).pack(
            side="left", padx=14, pady=8)
        self.lbl_donem = tk.Label(ust, text="", bg=LACIVERT, fg=SARI, font=FONT_UI_BOLD)
        self.lbl_donem.pack(side="left", padx=8)
        if app is not None:
            from finans_ui import finans_menusu_goster

            _buton(ust, "← Finans", lambda: finans_menusu_goster(app)).pack(side="right", padx=10, pady=6)
        _buton(ust, "Yenile", self.yenile).pack(side="right", pady=6)
        tk.Frame(self, bg=SARI, height=3).pack(fill="x")

        self.ozet = tk.Frame(self, bg=ACIK_BG)
        self.ozet.pack(fill="x", padx=12, pady=(10, 4))
        self.lbl_uyari = tk.Label(self, text="", bg=ACIK_BG, fg=UYARI, font=FONT_UI_BOLD, justify="left",
                                  anchor="w", wraplength=1150)
        self.lbl_uyari.pack(fill="x", padx=14)
        self.lbl_not = tk.Label(self, text="", bg=ACIK_BG, fg=PASIF, font=FONT_KUCUK, justify="left", anchor="w",
                                wraplength=1150)
        self.lbl_not.pack(fill="x", padx=14, pady=(0, 4))

        bar = tk.Frame(self, bg=ACIK_BG)
        bar.pack(fill="x", padx=12, pady=(2, 4))
        self.btn_odeme = _buton(bar, "Ödeme evrakını aç", self.odeme_ac, vurgu=True)
        self.btn_odeme.pack(side="left")
        tk.Label(bar, text="Satıra çift tıklayarak da açılır. Evrakı açmak veya vazgeçmek borcu değiştirmez.",
                 bg=ACIK_BG, fg=PASIF, font=FONT_KUCUK).pack(side="left", padx=10)

        govde = tk.PanedWindow(self, orient="vertical", bg=ACIK_BG, sashwidth=6, bd=0)
        govde.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        f = tk.Frame(govde, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
        self.tablo = ttk.Treeview(f, columns=[k[0] for k in KOLONLAR], show="headings", style=tablo_stili(f),
                                  selectmode="browse")
        for kod, ad, gen, hiza in KOLONLAR:
            self.tablo.heading(kod, text=ad, anchor=hiza)
            self.tablo.column(kod, width=gen, anchor=hiza, stretch=kod == "aciklama")
        sb = ttk.Scrollbar(f, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=sb.set)
        self.tablo.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tablo.tag_configure("baslik", background=LACIVERT, foreground=BEYAZ, font=FONT_UI_BOLD)
        self.tablo.tag_configure("gecmis_baslik", background=UYARI, foreground=BEYAZ, font=FONT_UI_BOLD)
        self.tablo.tag_configure("toplam", background=SARI, foreground=KOYU_LACIVERT, font=FONT_UI_BOLD)
        self.tablo.tag_configure("gecikmis", foreground=UYARI)
        self.tablo.tag_configure("tahmini", foreground=PASIF)
        self.tablo.bind("<<TreeviewSelect>>", lambda _e: self._detay_goster())
        self.tablo.bind("<Double-1>", lambda _e: self.odeme_ac())
        govde.add(f, minsize=200, stretch="always")

        alt = tk.Frame(govde, bg=ACIK_BG)
        sol = tk.Frame(alt, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
        sol.pack(side="left", fill="both", expand=True, padx=(0, 6))
        tk.Label(sol, text="Seçili borcun ayrıntısı", bg=BEYAZ, fg=LACIVERT, font=FONT_UI_BOLD).pack(
            anchor="w", padx=8, pady=(6, 0))
        self.detay = tk.Text(sol, height=8, wrap="word", font=FONT_ALT, bd=0, bg=BEYAZ, fg=METIN)
        self.detay.pack(fill="both", expand=True, padx=8, pady=6)
        sag = tk.Frame(alt, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
        sag.pack(side="left", fill="both", expand=True)
        tk.Label(sag, text="Eksik bilgiler", bg=BEYAZ, fg=UYARI, font=FONT_UI_BOLD).pack(anchor="w", padx=8,
                                                                                         pady=(6, 0))
        self.eksik = tk.Text(sag, height=8, wrap="word", font=FONT_ALT, bd=0, bg=BEYAZ, fg=METIN)
        self.eksik.pack(fill="both", expand=True, padx=8, pady=6)
        govde.add(alt, minsize=120)

        self.yenile()
        self._yokla()

    # ------------------------------------------------------------------ veri
    def _firma(self):
        from database.session_manager import oturum

        return getattr(oturum, "company_id", None)

    def yenile(self) -> None:
        secili = self._secili_anahtar()
        try:
            self._veri = ots.hesapla(self._bugun_fn())
        except Exception as hata:  # noqa: BLE001
            self.lbl_uyari.configure(text=f"Ödeme takvimi hesaplanamadı: {hata}")
            return
        self._imza = (self._veri["sayac"], self._veri["baslangic"], self._firma())
        self._ozet_ciz()
        self._tablo_doldur(secili)
        self._eksik_yaz()

    def _yokla(self) -> None:
        """Commit edilmiş değişiklik, ay değişimi veya firma değişiminde yeniden hesapla."""
        if not self.winfo_exists():
            return
        try:
            from database.donen_sermaye_service import degisim_sayaci

            imza = (degisim_sayaci(), ots.donem(self._bugun_fn())[0], self._firma())
            if imza != self._imza:
                self.yenile()
        except Exception:  # noqa: BLE001
            pass
        self._yoklama = self.after(YOKLAMA_MS, self._yokla)

    def destroy(self):
        if self._yoklama is not None:
            try:
                self.after_cancel(self._yoklama)
            except tk.TclError:
                pass
        super().destroy()

    # ------------------------------------------------------------------ çizim
    def _kutu(self, parent, baslik: str, tutar, alt: str = "", *, vurgu: bool = False, uyari: bool = False):
        bg = SARI if vurgu else BEYAZ
        k = tk.Frame(parent, bg=bg, highlightthickness=1, highlightbackground=UYARI if uyari else CIZGI)
        k.pack(side="left", fill="both", expand=True, padx=(0, 8))
        tk.Label(k, text=baslik, bg=bg, fg=UYARI if uyari else LACIVERT, font=FONT_UI_BOLD).pack(
            anchor="w", padx=10, pady=(8, 0))
        tk.Label(k, text=para_tr(tutar), bg=bg, fg=KOYU_LACIVERT, font=("Segoe UI", 14, "bold")).pack(
            anchor="e", padx=10)
        tk.Label(k, text=alt, bg=bg, fg=PASIF, font=FONT_KUCUK).pack(anchor="w", padx=10, pady=(0, 8))

    def _ozet_ciz(self) -> None:
        v = self._veri
        for w in self.ozet.winfo_children():
            w.destroy()
        self.lbl_donem.configure(text=f"{_tarih(v['baslangic'])} – {_tarih(v['bitis'])}")
        eksik = " · toplam eksik (bkz. Eksik bilgiler)" if v["toplam_eksik"] else ""
        for a in v["aylar"]:
            self._kutu(self.ozet, a["ad"], a["toplam"],
                       ("Tahmini ekstre dahil" if a["tahmini_var"] else f"{len(a['kalemler'])} ödeme") + eksik)
        self._kutu(self.ozet, "4 aylık genel toplam", v["genel_toplam"],
                   ("Tahmini ekstreler dahil" if any(a["tahmini_var"] for a in v["aylar"]) else "") + eksik,
                   vurgu=True)
        if v["gecmis"]:
            self._kutu(self.ozet, "Geçmişten kalan", v["gecmis_toplam"], "Genel toplama dahil değil", uyari=True)
        self.lbl_uyari.configure(text="  ".join(v["uyarilar"]))
        self.lbl_not.configure(text="  ".join(v["notlar"]))

    def _satir(self, k: dict) -> None:
        etiket = k["aciklama"]
        if k["gecikmis"]:
            etiket += "  — Gecikmiş"
        tag = "gecikmis" if k["gecikmis"] else ("tahmini" if k["tahmini"] else "")
        self._kalemler[k["anahtar"]] = k
        self.tablo.insert("", "end", iid=k["anahtar"], tags=(tag,) if tag else (), values=(
            _tarih(k["tarih"]), k["gun"], k["tur"], etiket, para_tr(k["kalan"])))

    def _tablo_doldur(self, secili: str | None) -> None:
        v = self._veri
        self.tablo.delete(*self.tablo.get_children())
        self._kalemler.clear()
        if v["gecmis"]:
            self.tablo.insert("", "end", iid="_gecmis", tags=("gecmis_baslik",),
                              values=("", "", "", "GEÇMİŞTEN KALAN ÖDEMELER", ""))
            for k in v["gecmis"]:
                self._satir(k)
            self.tablo.insert("", "end", iid="_gecmis_toplam", tags=("toplam",),
                              values=("Geçmiş toplamı", "", "", "4 aylık toplama dahil değil",
                                      para_tr(v["gecmis_toplam"])))
        for a in v["aylar"]:
            if not a["kalemler"]:
                continue
            kod = f"_ay_{a['yil']}_{a['ay']}"
            self.tablo.insert("", "end", iid=kod, tags=("baslik",), values=("", "", "", _buyuk(a["ad"]), ""))
            for k in a["kalemler"]:
                self._satir(k)
            self.tablo.insert("", "end", iid=kod + "_toplam", tags=("toplam",), values=(
                f"{ots.AY_ADLARI[a['ay'] - 1]} toplamı", "", "",
                "Tahmini ekstre dahil" if a["tahmini_var"] else "", para_tr(a["toplam"])))
        self.tablo.insert("", "end", iid="_genel", tags=("toplam",),
                          values=("Genel toplam", "", "", "4 ay", para_tr(v["genel_toplam"])))
        if secili and secili in self._kalemler:
            self.tablo.selection_set(secili)
            self.tablo.see(secili)
        self._detay_goster()

    def _eksik_yaz(self) -> None:
        self.eksik.configure(state="normal")
        self.eksik.delete("1.0", "end")
        eksikler = self._veri["eksikler"]
        if not eksikler:
            self.eksik.insert("end", "Eksik bilgi yok.")
        for e in eksikler:
            tutar = para_tr(e["tutar"]) if e.get("tutar") is not None else "tutar belirlenemedi"
            self.eksik.insert("end", f"• {e['tur']} — {e['ad']} ({tutar}): {e['neden']}\n")
        self.eksik.configure(state="disabled")

    def _secili_anahtar(self) -> str | None:
        sec = self.tablo.selection() if hasattr(self, "tablo") else ()
        return sec[0] if sec and sec[0] in self._kalemler else None

    def secili_kalem(self) -> dict | None:
        a = self._secili_anahtar()
        return self._kalemler.get(a) if a else None

    def _detay_goster(self) -> None:
        k = self.secili_kalem()
        self.detay.configure(state="normal")
        self.detay.delete("1.0", "end")
        if k is None:
            self.detay.insert("end", "Bir borç satırı seçin.")
        else:
            self.detay.insert("end", detay_metni(k))
        self.detay.configure(state="disabled")

    # ------------------------------------------------------------------ ödeme
    def odeme_ac(self) -> None:
        k = self.secili_kalem()
        if k is None:
            messagebox.showinfo("Ödeme Takvimi", "Önce tek bir borç satırı seçin.", parent=self)
            return
        try:
            odeme_evraki_ac(self.winfo_toplevel(), k, self.yenile)
        except (ValueError, PermissionError) as hata:
            messagebox.showwarning("Ödeme Takvimi", str(hata), parent=self)


def detay_metni(k: dict) -> str:
    satirlar = [f"{k['tur']} · {k['aciklama']}", f"Takvim tarihi: {_tarih(k['tarih'])} {k['gun']}",
                f"Kalan ödeme: {para_tr(k['kalan'])}"]
    if k["kaynak"] == ots.KAYNAK_KART:
        satirlar += [f"Ekstre dönemi: {_tarih(k['donem_baslangic'])} – {_tarih(k['kesim'])}",
                     f"Hesap kesimi: {_tarih(k['kesim'])}",
                     f"Son ödeme tarihi: {_tarih(k['son_odeme']) if k['son_odeme'] else 'tanımsız (eksik bilgi)'}",
                     f"Ekstre toplamı {para_tr(k['toplam'])} · ödenen {para_tr(k['odenen'])}",
                     "Durum: " + ("Tahmini — ekstre henüz kesilmedi" if k["tahmini"] else "Kesilmiş ekstre")
                     + (" · Gecikmiş" if k["gecikmis"] else "")]
        satirlar += [f"   {_tarih(d['islem_tarihi'])} {d['belge_no']} {d['aciklama']}: {para_tr(d['tutar'])}"
                     for d in k["detay"]]
    elif k["kaynak"] == ots.KAYNAK_KREDI:
        satirlar.append(f"Taksit vadesi: {_tarih(k['vade'])}" + (" · Gecikmiş" if k["gecikmis"] else ""))
        satirlar.append("Kalan bileşenler: " + ", ".join(
            f"{ad} {para_tr(k['bilesen'][alan])}" for alan, ad in (
                ("anapara", "anapara"), ("faiz", "faiz"), ("bsmv", "BSMV"), ("kkdf", "KKDF"),
                ("komisyon", "komisyon"), ("sigorta", "sigorta"), ("dosya_masrafi", "dosya"),
                ("diger_masraflar", "diğer masraf"), ("gecikme_faizi", "gecikme faizi"))
            if k["bilesen"].get(alan)))
        satirlar.append(f"Bu taksite ödenen: {para_tr(k['odenen'])}")
    elif k["kaynak"] == ots.KAYNAK_CEK_SENET:
        satirlar += [f"Portföy no: {k['portfoy_no']} · evrak no: {k['evrak_no']} · durum: {k['durum_etiket']}",
                     f"Alacaklı: {k['hesap']}",
                     f"Vade: {_tarih(k['vade'])}" + (" · Gecikmiş" if k["gecikmis"] else "")
                     + f" · düzenleme {_tarih(k['duzenleme'])} (bilgi; takvim vadeye göre)",
                     f"Evrak tutarı {para_tr(k['toplam'])} · ödenen {para_tr(k['odenen'])}"
                     + (f" · {k['doviz']}" if k["doviz"] else "")]
        if k["banka"] or k["iban"]:
            satirlar.append("Çek bankası / hesabı: " + " · ".join(p for p in (k["banka"], k["iban"]) if p))
        satirlar += [f"   {_tarih(o['tarih'])} ödeme {para_tr(o['tutar'])}" + (" — İPTAL" if o["iptal"] else "")
                     for o in k["odemeler"]]
    else:
        satirlar += [f"Plan: {k['hesap']} ({k['kategori_adi']}) · dönem {k['ay']:02d}.{k['yil']}",
                     f"Ödeme vadesi: {_tarih(k['vade'])}" + (" · Gecikmiş" if k["gecikmis"] else ""),
                     f"Dönem tutarı {para_tr(k['toplam'])} · ödenen {para_tr(k['odenen'])}"
                     + (f" · faturaya bağlı {para_tr(k['faturaya_bagli'])}" if k["faturaya_bagli"] else "")]
        if k["donem_id"] is None:
            satirlar.append("Dönem kaydı henüz yok; plan kuralından gösteriliyor (ödeme kaydedilince oluşur).")
    return "\n".join(satirlar)


def odeme_evraki_ac(parent, k: dict, yenile_cb) -> None:
    """Kaynağa uygun mevcut ödeme evrakı; kaynak, hesap ve kalan tutar hazır gelir."""
    if k["kaynak"] == ots.KAYNAK_KART:
        from database.kredi_karti_ekstre_service import KrediKartiEkstreService
        from kk_ekstre_ui import KkEkstreOdemeDialog

        detay = next((h for h in KrediKartiEkstreService.ekstreleri_hesapla(kredi_karti_id=k["kart_id"])
                      if h["kesim_tarihi"] == k["kesim"]), None)
        if detay is None:
            raise ValueError("Ekstre bulunamadı (kart pasif olabilir). Kredi kartı ekranından kontrol edin.")
        return KkEkstreOdemeDialog(parent, detay, tamami=False, yenile_cb=yenile_cb)
    if k["kaynak"] == ots.KAYNAK_KREDI:
        from banka_kredi_ui import KrediTaksitOdemePenceresi

        return KrediTaksitOdemePenceresi(parent, k["taksit_id"], yenile_cb=yenile_cb)
    if k["kaynak"] == ots.KAYNAK_CEK_SENET:
        from cek_senet_ui import OdeDialog
        from database.cek_senet_service import CekSenetService, odeme_engeli

        evrak = CekSenetService.getir(k["evrak_id"])
        if evrak is None:
            raise ValueError("Çek / senet evrakı bulunamadı; Çek / Senet ekranından kontrol edin.")
        engel = odeme_engeli(evrak)
        if engel:
            raise ValueError(f"{evrak.get('portfoy_no')}: {engel} Çek / Senet ekranından kontrol edin.")
        return OdeDialog(parent, evrak, on_kaydet=yenile_cb)
    return SabitGiderOdemeDialog(parent, k, yenile_cb)


class SabitGiderOdemeDialog(tk.Toplevel):
    """Sabit gider / vergi dönemi ödemesi: gider fişiyle öde veya yapılmış ödeme evrakını bağla."""

    def __init__(self, parent, kalem: dict, yenile_cb=None):
        from database import sabit_gider_service as sg
        from database.finans_service import FinansService
        from database.hizmet_service import HizmetService

        super().__init__(parent)
        self.kalem = kalem
        self.yenile_cb = yenile_cb
        self._kilit = False
        self.title("Sabit Gider Ödeme")
        self.configure(bg=ACIK_BG)
        self.geometry("560x430")
        self.transient(parent)
        ust = tk.Frame(self, bg=LACIVERT)
        ust.pack(fill="x")
        tk.Label(ust, text=f"{_buyuk(kalem['tur'])} — {kalem['hesap']}", bg=LACIVERT, fg=BEYAZ,
                 font=("Segoe UI", 11, "bold")).pack(side="left", padx=12, pady=8)
        tk.Frame(self, bg=SARI, height=3).pack(fill="x")
        tk.Label(self, text=f"Dönem {kalem['ay']:02d}.{kalem['yil']} · vade {_tarih(kalem['vade'])} · "
                            f"kalan {para_tr(kalem['kalan'])}", bg=ACIK_BG, fg=KOYU_LACIVERT,
                 font=FONT_UI_BOLD).pack(anchor="w", padx=12, pady=(8, 4))

        self.mod = tk.StringVar(value="fis")
        for deger, metin in (("fis", "Gider fişi ile öde (kasa / banka)"),
                             ("kart", "Kredi kartıyla öde (tek çekim / taksit)"),
                             ("bagla", "Yapılmış ödeme evrakını bağla (makbuz, havale, kartla ödeme)")):
            tk.Radiobutton(self, text=metin, variable=self.mod, value=deger, bg=ACIK_BG, font=FONT_ALT,
                           command=self._mod_degisti).pack(anchor="w", padx=12)
        frm = tk.Frame(self, bg=ACIK_BG)
        frm.pack(fill="x", padx=12, pady=8)
        self._frm = frm
        self.kart_paneli = None
        self._hesaplar = [(int(h.id), h.hesap_adi) for h in FinansService.gider_fisi_odeme_hesaplari()
                          if (h.alt_hesap_turu or "").upper() != "KREDI_KARTI"]
        self._hizmetler = [(int(h.id), f"{h.hizmet_kodu} — {h.hizmet_adi}")
                           for h in HizmetService.listele(hizmet_turu="GIDER")]
        self.alanlar: dict[str, tk.Widget] = {}

        def satir(i, etiket, w):
            tk.Label(frm, text=etiket, bg=ACIK_BG, font=FONT_ALT).grid(row=i, column=0, sticky="w", pady=3)
            w.grid(row=i, column=1, sticky="ew", pady=3)
            return w

        frm.columnconfigure(1, weight=1)
        self.hesap = satir(0, "Ödeme hesabı", ttk.Combobox(frm, values=[h[1] for h in self._hesaplar],
                                                            state="readonly"))
        self.hizmet = satir(1, "Gider hizmet kartı", ttk.Combobox(frm, values=[h[1] for h in self._hizmetler],
                                                                  state="readonly"))
        self.belge = satir(2, "Evrak no", ttk.Entry(frm))
        self.tutar = satir(3, "Ödeme tutarı", ttk.Entry(frm))
        self.tutar.insert(0, f"{kalem['kalan']:.2f}".replace(".", ","))
        self.tarih = satir(4, "İşlem tarihi", ttk.Entry(frm))
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        self.aciklama = satir(5, "Açıklama", ttk.Entry(frm))
        self.aciklama.insert(0, f"{kalem['hesap']} {kalem['ay']:02d}.{kalem['yil']}")
        tk.Label(self, text="Borç yalnız ödeme kaydedilip bu döneme bağlandığında azalır. Faturası kesilen gider "
                            "için faturayı 'Sabit Gider Planları → Dönemler' ekranından bağlayın.",
                 bg=ACIK_BG, fg=PASIF, font=FONT_KUCUK, wraplength=520, justify="left").pack(anchor="w", padx=12)
        alt = tk.Frame(self, bg=ACIK_BG)
        alt.pack(fill="x", padx=12, pady=10)
        _buton(alt, "Vazgeç", self.destroy).pack(side="right")
        self.btn = _buton(alt, "Kaydet", self.kaydet, vurgu=True)
        self.btn.pack(side="right", padx=6)
        if not yetki_var(*sg.YAZMA_YETKISI):
            self.btn.configure(state="disabled")
            tk.Label(alt, text="Ödeme kaydetme yetkiniz yok.", bg=ACIK_BG, fg=UYARI, font=FONT_ALT).pack(side="left")
        self._mod_degisti()
        self.bind("<Escape>", lambda _e: self.destroy())

    def _mod_degisti(self) -> None:
        fis, kart = self.mod.get() == "fis", self.mod.get() == "kart"
        self.hesap.configure(state="readonly" if fis else "disabled")
        self.hizmet.configure(state="readonly" if fis or kart else "disabled")
        self.tarih.configure(state="normal" if fis or kart else "disabled")
        self.belge.configure(state="disabled" if fis or kart else "normal")
        if kart and self.kart_paneli is None:
            from gider_kart_odeme_ui import KartOdemePaneli
            from kk_ekstre_ui import tutar_coz

            self.kart_paneli = KartOdemePaneli(
                self, tutar_fn=lambda: tutar_coz(self.tutar.get()),
                tarih_fn=lambda: datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date())
        if self.kart_paneli is not None:
            if kart:
                self.kart_paneli.pack(fill="both", expand=True, padx=12, pady=(0, 4), after=self._frm)
                self.geometry("780x900")
            else:
                self.kart_paneli.pack_forget()
                self.geometry("560x430")

    def kaydet(self) -> None:
        from database import sabit_gider_service as sg
        from kk_ekstre_ui import tutar_coz

        if self._kilit:
            return
        k = self.kalem
        try:
            tutar = tutar_coz(self.tutar.get())
            if tutar > k["kalan"]:
                raise ValueError(f"Ödeme tutarı kalan borçtan ({para_tr(k['kalan'])}) fazla. Sabit gider dönemi "
                                 "fazla ödemeyi gelecek dönemlere dağıtmaz; en çok kalan kadar girin.")
            self._kilit = True
            if self.mod.get() == "fis":
                if self.hesap.current() < 0 or self.hizmet.current() < 0:
                    raise ValueError("Ödeme hesabını ve gider hizmet kartını seçin.")
                tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
                sonuc = sg.gider_fisi_ile_ode(
                    k["plan_id"], k["yil"], k["ay"], finans_hesap_id=self._hesaplar[self.hesap.current()][0],
                    hizmet_id=self._hizmetler[self.hizmet.current()][0], tutar=tutar, tarih=tarih,
                    aciklama=self.aciklama.get().strip())
                mesaj = f"Gider fişi {sonuc['belge_no']} kaydedildi ve döneme bağlandı."
            elif self.mod.get() == "kart":
                from database import gider_kart_odeme_service as gk
                from gider_kart_odeme_ui import sonuc_metni

                if self.hizmet.current() < 0:
                    raise ValueError("Gider hizmet kartını seçin.")
                sonuc = gk.kart_ile_ode(
                    **self.kart_paneli.veri(),
                    islem_tarihi=datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date(),
                    gider_tutari=tutar, hizmet_id=self._hizmetler[self.hizmet.current()][0],
                    kaynak={"tur": gk.KAYNAK_SABIT, "plan_id": k["plan_id"], "yil": k["yil"], "ay": k["ay"]},
                    aciklama=self.aciklama.get().strip())
                mesaj = sonuc_metni(sonuc)
            else:
                belge = self.belge.get().strip()
                if not belge:
                    raise ValueError("Bağlanacak ödeme evrakının numarasını yazın.")
                donem_id = sg.donem_hazirla(k["plan_id"], k["yil"], k["ay"])
                sg.baglanti_ekle(donem_id, belge, tutar, aciklama="Ödeme takviminden")
                mesaj = f"{belge} döneme bağlandı."
        except (ValueError, PermissionError) as hata:
            self._kilit = False
            messagebox.showwarning("Sabit gider ödeme", str(hata), parent=self)
            return
        messagebox.showinfo("Sabit gider ödeme", mesaj, parent=self)
        if self.yenile_cb:
            self.yenile_cb()
        self.destroy()
