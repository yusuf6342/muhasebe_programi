"""Cari risk ve limitler / vade farkı ekranları.

* ``RiskLimitPaneli`` — cari kartındaki Risk ve Limitler tablosu + Vade Farkı alanları.
* ``RiskDetayDialog`` — risk tutarının kaynak belgeleri (belge, tutar, durum).
* ``satis_risk_onayi`` — satış kaydı öncesi limit aşımı uyarısı / yetkili geçiş.

Risk tutarları kaynaklardan hesaplanır (``database.cari_risk_service``); burada saklanmaz.
"""

from __future__ import annotations

import tkinter as tk
from datetime import date, datetime
from decimal import Decimal
from tkinter import messagebox, simpledialog, ttk

from cari_kart_tema import (
    ACIK_BG,
    BASARI,
    BEYAZ,
    CIZGI,
    DIKKAT,
    IKINCIL,
    LACIVERT,
    METIN,
    UYARI,
    font,
    tk_buton,
)
from database import cari_risk_service as crs
from tutar_bicim import tr_tutar

DURUM_RENK = {
    crs.DURUM_TANIMSIZ: IKINCIL,
    crs.DURUM_UYGUN: BASARI,
    crs.DURUM_DOLU: DIKKAT,
    crs.DURUM_ASILDI: UYARI,
}
DONEM_SECENEK = ("", "Aylık", "Yıllık")
TABLO_TURLERI = (crs.TUR_ACIK, crs.TUR_CEK, crs.TUR_SENET, crs.TUR_PORTFOY, crs.TUR_TOPLAM)


def _tl(deger) -> str:
    return "—" if deger is None else f"{tr_tutar(deger)} TL"


def _tarih(t) -> str:
    if isinstance(t, datetime):
        return t.strftime("%d.%m.%Y %H:%M")
    return t.strftime("%d.%m.%Y") if isinstance(t, date) else ""


def _donem_kod(metin: str) -> str | None:
    return {"Aylık": crs.DONEM_AYLIK, "Yıllık": crs.DONEM_YILLIK}.get((metin or "").strip())


class RiskLimitPaneli(tk.Frame):
    """Risk ve Limitler tablosu + Vade Farkı grubu (cari kartı detay paneli)."""

    def __init__(self, parent, *, cari_id_getir=None, on_degisim=None):
        super().__init__(parent, bg=BEYAZ)
        self._cari_id_getir = cari_id_getir or (lambda: None)
        self._on_degisim = on_degisim
        self._ozet: dict | None = None
        self._yukleniyor = False
        self._duzenlenebilir = True
        self.uygula_var = {t: tk.BooleanVar(master=self, value=False) for t in crs.LIMITLI_TURLER}
        self.limit_var = {t: tk.StringVar(master=self) for t in crs.LIMITLI_TURLER}
        self.aylik_var = tk.StringVar(master=self)
        self.yillik_var = tk.StringVar(master=self)
        self.donem_var = tk.StringVar(master=self)
        self.aciklama_var = tk.StringVar(master=self)
        self._hucre: dict[tuple[str, str], tk.Widget] = {}
        self._girisler: list[tk.Widget] = []
        self._olustur()
        for v in (*self.uygula_var.values(), *self.limit_var.values(), self.aylik_var, self.yillik_var,
                  self.donem_var, self.aciklama_var):
            v.trace_add("write", lambda *_a: self._degisti())

    # --- Arayüz ---

    def _olustur(self):
        r = self.winfo_toplevel()
        ust = tk.Frame(self, bg=BEYAZ)
        ust.pack(fill="x")
        tk.Label(ust, text="RİSK VE LİMİTLER", bg=BEYAZ, fg=LACIVERT, font=font(11, "bold", r)).pack(side="left")
        self.zaman_lbl = tk.Label(ust, text="", bg=BEYAZ, fg=IKINCIL, font=font(9, root=r))
        self.zaman_lbl.pack(side="left", padx=10)
        tk_buton(ust, "Risk Politikası…", self.politika_ac, rol="ikincil").pack(side="right")
        tk_buton(ust, "Risk Olayları", self.olaylar_ac, rol="ikincil").pack(side="right", padx=4)
        tk_buton(ust, "Yenile", self.yenile, rol="ikincil").pack(side="right")

        tablo = tk.Frame(self, bg=CIZGI)
        tablo.pack(fill="x", pady=(6, 2))
        basliklar = ("Risk Türü", "Güncel Risk", "Limit Uygula", "Limit (TL)", "Kalan Limit", "Aşım", "Durum")
        for c, b in enumerate(basliklar):
            tk.Label(tablo, text=b, bg=LACIVERT, fg=BEYAZ, font=font(9, "bold", r), padx=8, pady=4,
                     anchor="w" if c == 0 else "e" if c in (1, 3, 4, 5) else "center").grid(
                row=0, column=c, sticky="nsew", padx=(0, 1), pady=(0, 1))
            tablo.columnconfigure(c, weight=1 if c in (0, 6) else 0)
        for i, tur in enumerate(TABLO_TURLERI, start=1):
            kalin = tur == crs.TUR_TOPLAM
            zemin = "#FFF7D6" if kalin else (BEYAZ if i % 2 else ACIK_BG)
            f = font(10, "bold" if kalin else "normal", r)
            tk.Label(tablo, text=crs.TUR_ETIKET[tur], bg=zemin, fg=LACIVERT if kalin else METIN, font=f,
                     anchor="w", padx=8, pady=3).grid(row=i, column=0, sticky="nsew", padx=(0, 1), pady=(0, 1))
            risk = tk.Label(tablo, text="", bg=zemin, fg="#1D4ED8", font=font(10, "bold" if kalin else "underline", r),
                            anchor="e", padx=8, cursor="hand2")
            risk.grid(row=i, column=1, sticky="nsew", padx=(0, 1), pady=(0, 1))
            risk.bind("<Button-1>", lambda _e, t=tur: self.detay_ac(t))
            self._hucre[(tur, "risk")] = risk
            if tur in crs.LIMITLI_TURLER:
                chk = tk.Checkbutton(tablo, variable=self.uygula_var[tur], bg=zemin, activebackground=zemin,
                                     command=lambda t=tur: self._uygula_degisti(t))
                chk.grid(row=i, column=2, sticky="nsew", padx=(0, 1), pady=(0, 1))
                hucre = tk.Frame(tablo, bg=zemin)
                hucre.grid(row=i, column=3, sticky="nsew", padx=(0, 1), pady=(0, 1))
                giris = ttk.Entry(hucre, textvariable=self.limit_var[tur], width=14, justify="right")
                giris.pack(padx=4, pady=2)
                self._girisler += [chk, giris]
                self._hucre[(tur, "limit")] = giris
            else:
                tk.Label(tablo, text="Bilgi: toplam riske dahil", bg=zemin, fg=IKINCIL, font=font(9, root=r)).grid(
                    row=i, column=2, columnspan=2, sticky="nsew", padx=(0, 1), pady=(0, 1))
            for c, ad in ((4, "kalan"), (5, "asim"), (6, "durum")):
                lbl = tk.Label(tablo, text="", bg=zemin, fg=METIN, font=f, anchor="e" if c < 6 else "center",
                               padx=8)
                lbl.grid(row=i, column=c, sticky="nsew", padx=(0, 1), pady=(0, 1))
                self._hucre[(tur, ad)] = lbl
        self.avans_lbl = tk.Label(self, text="", bg=BEYAZ, fg=IKINCIL, font=font(9, root=r), anchor="w",
                                  justify="left")
        self.avans_lbl.pack(fill="x", pady=(2, 0))
        tk.Label(
            self, bg=BEYAZ, fg=IKINCIL, font=font(9, root=r), anchor="w", justify="left", wraplength=880,
            text=("Limit Uygula kapalıysa denetim yapılmaz. İşaretliyken 0 TL geçerli limittir; pozitif risk aşım "
                  "sayılır. Riskin kaynağını görmek için Güncel Risk tutarına tıklayın."),
        ).pack(fill="x", pady=(0, 6))

        vf = tk.LabelFrame(self, text=" Vade Farkı ", bg=BEYAZ, fg=LACIVERT, font=font(10, "bold", r), padx=8, pady=6)
        vf.pack(fill="x", pady=(4, 0))
        tk.Label(vf, text="Aylık Oran %", bg=BEYAZ, font=font(10, root=r)).grid(row=0, column=0, sticky="w")
        self.aylik_giris = ttk.Entry(vf, textvariable=self.aylik_var, width=10, justify="right")
        self.aylik_giris.grid(row=0, column=1, sticky="w", padx=(4, 16))
        tk.Label(vf, text="Yıllık Oran %", bg=BEYAZ, font=font(10, root=r)).grid(row=0, column=2, sticky="w")
        self.yillik_giris = ttk.Entry(vf, textvariable=self.yillik_var, width=10, justify="right")
        self.yillik_giris.grid(row=0, column=3, sticky="w", padx=(4, 16))
        tk.Label(vf, text="Esas Dönem", bg=BEYAZ, font=font(10, root=r)).grid(row=0, column=4, sticky="w")
        self.donem_cb = ttk.Combobox(vf, textvariable=self.donem_var, values=DONEM_SECENEK, state="readonly", width=9)
        self.donem_cb.grid(row=0, column=5, sticky="w", padx=(4, 16))
        tk_buton(vf, "Değişiklik Geçmişi", self.gecmis_ac, rol="ikincil").grid(row=0, column=6, sticky="e")
        tk.Label(vf, text="Açıklama", bg=BEYAZ, font=font(10, root=r)).grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.aciklama_giris = ttk.Entry(vf, textvariable=self.aciklama_var, width=60)
        self.aciklama_giris.grid(row=1, column=1, columnspan=5, sticky="ew", padx=(4, 16), pady=(6, 0))
        self.vf_not = tk.Label(vf, text="", bg=BEYAZ, fg=IKINCIL, font=font(9, root=r), anchor="w", justify="left")
        self.vf_not.grid(row=2, column=0, columnspan=7, sticky="w", pady=(4, 0))
        vf.columnconfigure(5, weight=1)
        self._girisler += [self.aylik_giris, self.yillik_giris, self.donem_cb, self.aciklama_giris]

    # --- Veri ---

    def doldur(self, cari) -> None:
        self._yukleniyor = True
        try:
            for tur, (limit_alan, uygula_alan) in crs.LIMIT_ALANLARI.items():
                self.uygula_var[tur].set(bool(getattr(cari, uygula_alan, False)) if cari else False)
                limit = getattr(cari, limit_alan, None) if cari else None
                self.limit_var[tur].set("" if limit is None else tr_tutar(limit))
            self.aylik_var.set(crs.oran_metni(getattr(cari, "vade_farki_aylik_oran", None)) if cari else "")
            self.yillik_var.set(crs.oran_metni(getattr(cari, "vade_farki_yillik_oran", None)) if cari else "")
            donem = getattr(cari, "vade_farki_donem", None) if cari else None
            self.donem_var.set(crs.DONEM_ETIKET.get(donem, ""))
            self.aciklama_var.set((getattr(cari, "vade_farki_aciklama", None) or "") if cari else "")
        finally:
            self._yukleniyor = False
        self._tabloyu_ciz()

    def degerler(self) -> dict:
        """Servise gidecek ham değerler (doğrulama ``cari_risk_service.kart_alanlarini_dogrula``)."""
        veri: dict = {}
        for tur, (limit_alan, uygula_alan) in crs.LIMIT_ALANLARI.items():
            veri[limit_alan] = self.limit_var[tur].get().strip()
            veri[uygula_alan] = bool(self.uygula_var[tur].get())
        veri["vade_farki_aylik_oran"] = self.aylik_var.get().strip()
        veri["vade_farki_yillik_oran"] = self.yillik_var.get().strip()
        veri["vade_farki_donem"] = _donem_kod(self.donem_var.get())
        veri["vade_farki_aciklama"] = self.aciklama_var.get().strip()
        return veri

    def snapshot(self) -> tuple:
        return tuple(sorted((k, str(v)) for k, v in self.degerler().items()))

    def risk_goster(self, ozet: dict | None) -> None:
        self._ozet = ozet
        self._tabloyu_ciz()

    def duzenlenebilir(self, acik: bool) -> None:
        from database.access import yetki_var

        self._duzenlenebilir = bool(acik) and yetki_var(crs.IZIN_LIMIT)
        for w in self._girisler:
            try:
                if isinstance(w, ttk.Combobox):
                    w.configure(state="readonly" if self._duzenlenebilir else "disabled")
                else:
                    w.configure(state="normal" if self._duzenlenebilir else "disabled")
            except tk.TclError:
                pass
        self._limit_girislerini_ayarla()

    def _uygula_degisti(self, tur: str):
        self._limit_girislerini_ayarla()
        if self.uygula_var[tur].get() and not self.limit_var[tur].get().strip():
            giris = self._hucre.get((tur, "limit"))
            if giris is not None:
                giris.focus_set()

    def _limit_girislerini_ayarla(self):
        for tur in crs.LIMITLI_TURLER:
            giris = self._hucre.get((tur, "limit"))
            if giris is None:
                continue
            acik = self._duzenlenebilir and bool(self.uygula_var[tur].get())
            giris.configure(state="normal" if acik else "disabled")

    def _degisti(self):
        if self._yukleniyor:
            return
        self._tabloyu_ciz()
        if callable(self._on_degisim):
            self._on_degisim()

    def _girilen_limit(self, tur: str):
        from tutar_bicim import tutar_coz

        ham = self.limit_var[tur].get().strip()
        if not ham:
            return None
        try:
            return tutar_coz(ham)
        except (ValueError, ArithmeticError):
            return None

    def _tabloyu_ciz(self):
        satirlar = (self._ozet or {}).get("satirlar") or {}
        for tur in TABLO_TURLERI:
            s = satirlar.get(tur) or {}
            risk = s.get("risk")
            self._hucre[(tur, "risk")].configure(text=_tl(risk) if risk is not None else "…")
            if tur in crs.LIMITLI_TURLER:
                uygula = bool(self.uygula_var[tur].get())
                limit = self._girilen_limit(tur)
                if uygula and limit is None:
                    d = {"kalan": None, "asim": None, "durum": crs.DURUM_TANIMSIZ, "etiket": "Limit girilmedi"}
                else:
                    d = crs.limit_durumu(risk or 0, limit, uygula)
                self._hucre[(tur, "kalan")].configure(text=_tl(d["kalan"]) if d["kalan"] is not None else "—")
                self._hucre[(tur, "asim")].configure(
                    text=_tl(d["asim"]) if d["asim"] else ("0,00 TL" if d["asim"] is not None else "—"),
                    fg=UYARI if d["asim"] else METIN,
                )
                self._hucre[(tur, "durum")].configure(text=d["etiket"], fg=DURUM_RENK.get(d["durum"], METIN))
            else:
                for ad in ("kalan", "asim", "durum"):
                    self._hucre[(tur, ad)].configure(text="—" if ad != "durum" else "Limitsiz (bilgi)", fg=IKINCIL)
        avans = (self._ozet or {}).get("avans") or Decimal("0")
        if self._ozet and self._ozet.get("tedarikci"):
            self.avans_lbl.configure(text="Tedarikçi kartı: müşteri açık hesap riski hesaplanmaz.")
        elif avans > 0:
            self.avans_lbl.configure(
                text=(f"Açık borç {_tl(self._ozet.get('acik_borc'))} − dağıtılmamış avans {_tl(avans)} "
                      "(avans açık hesap riskinden bir kez düşüldü).")
            )
        else:
            self.avans_lbl.configure(text="")
        zaman = (self._ozet or {}).get("zaman")
        self.zaman_lbl.configure(text=f"Hesaplandı: {_tarih(zaman)}" if zaman else "")
        donem = _donem_kod(self.donem_var.get())
        if donem == crs.DONEM_AYLIK:
            metin = "Esas oran: Aylık. Yıllık oran bilgi amaçlıdır; oranlar birbirine çevrilmez."
        elif donem == crs.DONEM_YILLIK:
            metin = "Esas oran: Yıllık. Aylık oran bilgi amaçlıdır; oranlar birbirine çevrilmez."
        else:
            metin = "Esas dönem seçilmedi: oranlar yalnız bilgi amaçlıdır. Vade farkı kendiliğinden borç oluşturmaz."
        self.vf_not.configure(text=metin)

    # --- Eylemler ---

    def yenile(self):
        cari_id = self._cari_id_getir()
        if not cari_id:
            return
        try:
            self.risk_goster(crs.risk_ozeti(int(cari_id)))
        except Exception as hata:
            messagebox.showerror("Risk", f"Risk hesaplanamadı: {hata}", parent=self)

    def detay_ac(self, tur: str):
        cari_id = self._cari_id_getir()
        if not cari_id:
            messagebox.showinfo("Risk", "Önce cari kartını kaydedin.", parent=self)
            return
        RiskDetayDialog(self, int(cari_id), tur=tur, on_degisim=self.yenile)

    def olaylar_ac(self):
        cari_id = self._cari_id_getir()
        if cari_id:
            RiskOlaylariDialog(self, int(cari_id))

    def gecmis_ac(self):
        cari_id = self._cari_id_getir()
        if cari_id:
            DegisiklikGecmisiDialog(self, int(cari_id))

    def politika_ac(self):
        risk_politikasi_sor(self)


class _ListeDialog(tk.Toplevel):
    def __init__(self, parent, baslik: str, kolonlar: tuple, *, genislik=980, yukseklik=460):
        super().__init__(parent)
        self.title(baslik)
        self.configure(bg=BEYAZ)
        self.transient(parent.winfo_toplevel())
        try:
            from ui_pencere import calisma_alani

            x, y, aw, ah = calisma_alani(self)
        except Exception:
            x, y, aw, ah = 0, 0, 1280, 720
        w, h = min(genislik, aw - 40), min(yukseklik, ah - 60)
        self.geometry(f"{w}x{h}+{x + (aw - w) // 2}+{y + (ah - h) // 2}")
        self.minsize(min(640, w), min(320, h))
        self.bind("<Escape>", lambda _e: self.destroy())
        self.ust = tk.Frame(self, bg=BEYAZ)
        self.ust.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(self.ust, text=baslik.upper(), bg=BEYAZ, fg=LACIVERT, font=font(12, "bold", self)).pack(side="left")
        self.alt = tk.Frame(self, bg=BEYAZ)
        self.alt.pack(side="bottom", fill="x", padx=12, pady=(4, 10))
        tk_buton(self.alt, "Kapat", self.destroy, rol="ikincil").pack(side="right")
        self.bilgi_lbl = tk.Label(self, text="", bg=BEYAZ, fg=IKINCIL, font=font(9, root=self), anchor="w",
                                  justify="left")
        self.bilgi_lbl.pack(side="bottom", fill="x", padx=12)
        cerceve = ttk.Frame(self)
        cerceve.pack(fill="both", expand=True, padx=12)
        self.tablo = ttk.Treeview(cerceve, columns=[k for k, _b, _g in kolonlar], show="headings",
                                  selectmode="browse")
        for k, b, g in kolonlar:
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=g, anchor="e" if k in ("ilk", "tutar", "yeni", "limit") else "w")
        dikey = ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=dikey.set)
        self.tablo.pack(side="left", fill="both", expand=True)
        dikey.pack(side="right", fill="y")


class RiskDetayDialog(_ListeDialog):
    KOLONLAR = (
        ("tur", "Risk Türü", 110), ("belge_turu", "Belge Türü", 130), ("belge_no", "Belge / Portföy No", 120),
        ("evrak_no", "Evrak No", 100), ("tarih", "Tarih", 82), ("vade", "Vade", 82),
        ("ilk", "İlk Tutar", 105), ("tutar", "Risk Tutarı", 110), ("durum", "Durum", 120),
        ("hedef", "Ciro Edilen", 160),
    )
    FILTRE = {"Tümü": None, **{crs.TUR_ETIKET[t]: t for t in TABLO_TURLERI if t != crs.TUR_TOPLAM}}

    def __init__(self, parent, cari_id: int, *, tur: str | None = None, on_degisim=None):
        super().__init__(parent, "Risk Ayrıntısı", self.KOLONLAR, genislik=1120)
        self.cari_id = int(cari_id)
        self._on_degisim = on_degisim
        self._satirlar: dict[str, dict] = {}
        tk.Label(self.ust, text="Göster:", bg=BEYAZ, font=font(10, root=self)).pack(side="left", padx=(16, 4))
        ilk = "Tümü" if tur in (None, crs.TUR_TOPLAM) else crs.TUR_ETIKET[tur]
        self.filtre = ttk.Combobox(self.ust, values=tuple(self.FILTRE), state="readonly", width=16)
        self.filtre.set(ilk)
        self.filtre.pack(side="left")
        self.filtre.bind("<<ComboboxSelected>>", lambda _e: self.yukle())
        self.kapanis_btn = tk_buton(self.alt, "Ciro Kapanışını Kesinleştir…", self.ciro_kapanisi, rol="vurgu")
        self.kapanis_btn.pack(side="left")
        self.tablo.bind("<<TreeviewSelect>>", lambda _e: self._dugme_durumu())
        self.yukle()

    def yukle(self):
        ozet = crs.risk_ozeti(self.cari_id)
        secilen = self.FILTRE.get(self.filtre.get())
        self.tablo.delete(*self.tablo.get_children())
        self._satirlar.clear()
        for tur, kayitlar in ozet["detay"].items():
            if secilen and tur != secilen:
                continue
            for k in kayitlar:
                iid = f"{tur}:{k['kimlik']}"
                self._satirlar[iid] = {**k, "risk_turu": tur}
                self.tablo.insert("", "end", iid=iid, values=(
                    crs.TUR_ETIKET[tur], k["belge_turu"], k["belge_no"], k.get("evrak_no", ""),
                    _tarih(k.get("tarih")), _tarih(k.get("vade")), tr_tutar(k["ilk_tutar"]),
                    tr_tutar(k["tutar"]), k["durum"], k.get("ciro_hedefi", ""),
                ))
        satirlar = ozet["satirlar"]
        self.bilgi_lbl.configure(text=(
            "  ·  ".join(f"{crs.TUR_ETIKET[t]}: {_tl(satirlar[t]['risk'])}" for t in TABLO_TURLERI)
            + "\nVadesi geçen ciro evrakı, kapanışı kesinleşene kadar riskte kalır. Karşılıksız/iade evrak "
              "müşteri açık hesabına döner; ayrıca ciro riski olarak sayılmaz."
        ))
        self._dugme_durumu()

    def _secili(self) -> dict | None:
        sec = self.tablo.selection()
        return self._satirlar.get(sec[0]) if sec else None

    def _dugme_durumu(self):
        s = self._secili()
        uygun = bool(s and s["risk_turu"] in (crs.TUR_CEK, crs.TUR_SENET) and s.get("evrak_id"))
        self.kapanis_btn.configure(state="normal" if uygun else "disabled")

    def ciro_kapanisi(self):
        from database.access import yetki_var
        from database.cek_senet_service import CekSenetService

        s = self._secili()
        if not s or not s.get("evrak_id"):
            return
        if not yetki_var("finans_duzenleme"):
            messagebox.showerror("Yetki", "Çek/senet durumunu değiştirme yetkiniz yok.", parent=self)
            return
        aciklama = simpledialog.askstring(
            "Ciro kapanışı",
            f"{s['belge_turu']} {s['belge_no']} ({tr_tutar(s['tutar'])} TL)\n"
            "Ciro edilen evrakın ödendiğini doğrulayan açıklamayı girin:",
            parent=self,
        )
        if aciklama is None:
            return
        try:
            CekSenetService.ciro_kapanisi_kesinlestir(int(s["evrak_id"]), aciklama=aciklama)
        except (ValueError, PermissionError) as hata:
            messagebox.showerror("Ciro kapanışı", str(hata), parent=self)
            return
        self.yukle()
        if callable(self._on_degisim):
            self._on_degisim()


class RiskOlaylariDialog(_ListeDialog):
    KOLONLAR = (
        ("zaman", "Zaman", 120), ("belge_turu", "Belge Türü", 110), ("belge_no", "Belge No", 110),
        ("tur", "Risk Türü", 100), ("yeni", "Yeni Risk", 105), ("limit", "Limit", 100),
        ("karar", "Karar", 110), ("kullanici", "Kullanıcı", 100), ("gerekce", "Gerekçe", 220),
    )

    def __init__(self, parent, cari_id: int):
        super().__init__(parent, "Risk Limiti Aşım Kayıtları", self.KOLONLAR, genislik=1100)
        karar = {crs.KARAR_UYARI_GECILDI: "Uyarı geçildi", crs.KARAR_YETKILI_GECIS: "Yetkili geçiş"}
        for i, o in enumerate(crs.olaylar(int(cari_id))):
            self.tablo.insert("", "end", iid=str(i), values=(
                _tarih(o["zaman"]), o["belge_turu"], o["belge_no"], o["risk_turu"], tr_tutar(o["yeni_risk"]),
                tr_tutar(o["limit"]), karar.get(o["karar"], o["karar"]), o["kullanici"], o["gerekce"],
            ))
        politika = "Uyarı ver" if crs.politika_getir() == crs.POLITIKA_UYARI else "Engelle (yetkili geçiş)"
        self.bilgi_lbl.configure(text=f"Firma risk aşım davranışı: {politika}")


class DegisiklikGecmisiDialog(_ListeDialog):
    KOLONLAR = (("zaman", "Zaman", 130), ("alan", "Alan", 220), ("eski", "Eski Değer", 150),
                ("yeni", "Yeni Değer", 150), ("kullanici", "Kullanıcı", 120))
    ALAN_ADI = {
        "acik_hesap_risk_limiti": "Açık hesap limiti", "acik_hesap_limit_uygula": "Açık hesap limit uygula",
        "cek_risk_limiti": "Ciro çek limiti", "cek_limit_uygula": "Ciro çek limit uygula",
        "senet_risk_limiti": "Ciro senet limiti", "senet_limit_uygula": "Ciro senet limit uygula",
        "toplam_risk_limiti": "Toplam risk limiti", "toplam_limit_uygula": "Toplam limit uygula",
        "vade_farki_aylik_oran": "Vade farkı aylık oran %", "vade_farki_yillik_oran": "Vade farkı yıllık oran %",
        "vade_farki_donem": "Vade farkı esas dönem", "vade_farki_aciklama": "Vade farkı açıklama",
    }

    def __init__(self, parent, cari_id: int):
        super().__init__(parent, "Risk / Vade Farkı Değişiklik Geçmişi", self.KOLONLAR, genislik=820)
        for i, k in enumerate(crs.degisiklik_gecmisi(int(cari_id))):
            self.tablo.insert("", "end", iid=str(i), values=(
                _tarih(k["zaman"]), self.ALAN_ADI.get(k["alan"], k["alan"]), k["eski"], k["yeni"], k["kullanici"],
            ))
        self.bilgi_lbl.configure(text="Oran değişikliği geçmiş belgeleri değiştirmez ve borç oluşturmaz.")


def risk_politikasi_sor(parent) -> str | None:
    """Firma risk aşım davranışını gösterir; yetkili kullanıcı değiştirebilir."""
    mevcut = crs.politika_getir()
    metin = "Uyarı ver (kullanıcı devam edebilir)" if mevcut == crs.POLITIKA_UYARI else \
        "Engelle (yalnız yetkili kullanıcı gerekçeyle geçebilir)"
    cevap = messagebox.askyesnocancel(
        "Risk aşım davranışı",
        f"Mevcut firma ayarı: {metin}\n\nEvet: Uyarı ver\nHayır: Engelle (yetkili geçiş)\nİptal: değiştirme",
        parent=parent,
    )
    if cevap is None:
        return None
    yeni = crs.POLITIKA_UYARI if cevap else crs.POLITIKA_ENGEL
    try:
        return crs.politika_ayarla(yeni)
    except (PermissionError, ValueError) as hata:
        messagebox.showerror("Risk aşım davranışı", str(hata), parent=parent)
        return None


# ─── Satış öncesi kontrol ────────────────────────────────────────────────
class RiskAsimDialog(tk.Toplevel):
    def __init__(self, parent, kontrol: dict, belge_turu: str):
        super().__init__(parent)
        from database.access import yetki_var

        self.kontrol = kontrol
        self.sonuc: dict | None = None
        self.engel = kontrol.get("politika") == crs.POLITIKA_ENGEL
        self.yetkili = yetki_var(crs.IZIN_ASIM)
        self.title("Risk limiti aşılıyor")
        self.configure(bg=BEYAZ)
        self.transient(parent.winfo_toplevel())
        self.resizable(False, False)
        self.grab_set()
        tk.Label(self, text="RİSK LİMİTİ AŞILIYOR", bg=UYARI, fg=BEYAZ, font=font(12, "bold", self),
                 anchor="w", padx=12, pady=6).pack(fill="x")
        tk.Label(self, text=f"{belge_turu} kaydı müşterinin risk limitini aşacak.", bg=BEYAZ, fg=METIN,
                 font=font(10, root=self), anchor="w").pack(fill="x", padx=12, pady=(8, 4))
        tablo = tk.Frame(self, bg=CIZGI)
        tablo.pack(fill="x", padx=12)
        for c, b in enumerate(("Limit", "Mevcut Risk", "İşlem Etkisi", "Yeni Risk", "Limit (TL)", "Aşım")):
            tk.Label(tablo, text=b, bg=LACIVERT, fg=BEYAZ, font=font(9, "bold", self), padx=8, pady=3).grid(
                row=0, column=c, sticky="nsew", padx=(0, 1), pady=(0, 1))
        for i, a in enumerate(kontrol.get("asimlar") or [], start=1):
            for c, deger in enumerate((a["etiket"], _tl(a["mevcut"]), _tl(a["etki"]), _tl(a["yeni"]),
                                       _tl(a["limit"]), _tl(a["asim"]))):
                tk.Label(tablo, text=deger, bg=BEYAZ, fg=UYARI if c == 5 else METIN,
                         font=font(10, "bold" if c in (0, 5) else "normal", self), padx=8, pady=3,
                         anchor="w" if c == 0 else "e").grid(row=i, column=c, sticky="nsew", padx=(0, 1), pady=(0, 1))
        if self.engel and not self.yetkili:
            bilgi = ("Firma ayarı: limit aşımında kayıt engellenir. Bu işlem için yetkili kullanıcı onayı gerekir "
                     "(cari_risk_asim_onay).")
        elif self.engel:
            bilgi = "Firma ayarı: limit aşımı engellenir. Yetkili geçiş için gerekçe zorunludur."
        else:
            bilgi = "Firma ayarı: uyarı. Devam ederseniz karar kullanıcı ve zamanla kaydedilir."
        tk.Label(self, text=bilgi, bg=BEYAZ, fg=IKINCIL, font=font(9, root=self), anchor="w", justify="left",
                 wraplength=640).pack(fill="x", padx=12, pady=(8, 2))
        satir = tk.Frame(self, bg=BEYAZ)
        satir.pack(fill="x", padx=12, pady=(2, 4))
        tk.Label(satir, text="Gerekçe" + (" (zorunlu)" if self.engel else " (isteğe bağlı)"), bg=BEYAZ,
                 font=font(10, root=self)).pack(side="left")
        self.gerekce = ttk.Entry(satir, width=60)
        self.gerekce.pack(side="left", fill="x", expand=True, padx=(6, 0))
        alt = tk.Frame(self, bg=BEYAZ)
        alt.pack(fill="x", padx=12, pady=(6, 12))
        tk_buton(alt, "Vazgeç", self.destroy, rol="ikincil").pack(side="right")
        if not self.engel:
            tk_buton(alt, "Yine de Devam Et", self.devam, rol="vurgu").pack(side="right", padx=6)
        elif self.yetkili:
            tk_buton(alt, "Yetkili Geçiş ile Kaydet", self.devam, rol="tehlike").pack(side="right", padx=6)
        else:
            self.gerekce.configure(state="disabled")
        self.bind("<Escape>", lambda _e: self.destroy())
        self.gerekce.focus_set()

    def devam(self):
        gerekce = self.gerekce.get().strip()
        if self.engel and not gerekce:
            messagebox.showwarning("Gerekçe", "Yetkili geçiş için gerekçe yazın.", parent=self)
            self.gerekce.focus_set()
            return
        self.sonuc = {
            "kontrol": self.kontrol,
            "karar": crs.KARAR_YETKILI_GECIS if self.engel else crs.KARAR_UYARI_GECILDI,
            "gerekce": gerekce,
        }
        self.destroy()


def satis_risk_onayi(parent, cari_id, etki, *, belge_turu: str = "Satış Faturası"):
    """(devam, kayit). Aşım yoksa (True, None). Kullanıcı vazgeçerse (False, None).

    Risk hesaplanamazsa satış engellenmez; hata yalnız bilgilendirilir.
    """
    if not cari_id:
        return True, None
    try:
        kontrol = crs.islem_kontrolu(int(cari_id), etki)
    except Exception:
        return True, None
    if not kontrol.get("asimlar"):
        return True, None
    pencere = RiskAsimDialog(parent, kontrol, belge_turu)
    parent.wait_window(pencere)
    if pencere.sonuc is None:
        return False, None
    return True, {**pencere.sonuc, "belge_turu": belge_turu}


def risk_olayi_yaz(kayit: dict | None, belge_no: str | None) -> None:
    if not kayit:
        return
    try:
        crs.olay_kaydet(kayit["kontrol"], belge_turu=kayit["belge_turu"], belge_no=belge_no,
                        karar=kayit["karar"], gerekce=kayit.get("gerekce"))
    except Exception:
        pass


def satis_etkisi(veriler: dict) -> Decimal:
    """Satış belgesinin açık hesaba eklenecek kısmı: TL genel toplam − peşin tahsilat (en az 0)."""
    toplam = Decimal(str(veriler.get("tl_genel_toplam") or 0))
    tahsilat = Decimal(str(veriler.get("tahsilat_tutari") or 0))
    return max(Decimal("0"), toplam - tahsilat)
