"""Ödeme sözleri arayüzü: cari kart listesi, söz formu, detay/geçmiş, merkezi takvim ve evrak bağlama.

Söz bir planlama kaydıdır; fatura kapatmaz, kasa/banka/cari bakiyesini değiştirmez.
"""
from __future__ import annotations

import tkinter as tk
from datetime import date, datetime, timedelta
from decimal import Decimal
from tkinter import filedialog, messagebox, simpledialog, ttk

from database.cari_virman_makbuz_service import musteri_mi, tedarikci_mi
from database.odeme_sozu_service import (
    ALINAN,
    DURUMLAR,
    VERILEN,
    YON_ADLARI,
    YONTEMLER,
    OdemeSozuService,
    para_toplam_metni,
)
from tutar_bicim import tr_tutar, tutar_alani, tutar_coz
from ui_takvim import takvim_butonu

LISTE_SUTUNLARI = (
    ("cari", "Cari", 180),
    ("yon", "Yön", 70),
    ("soz", "Söz Tarihi", 82),
    ("vade", "Ödeme Tarihi", 88),
    ("tutar", "Tutar", 100),
    ("gerceklesen", "Gerçekleşen", 100),
    ("kalan", "Kalan", 100),
    ("pb", "Döviz", 50),
    ("yontem", "Yöntem", 90),
    ("durum", "Durum", 150),
    ("sorumlu", "Sorumlu", 90),
    ("not", "Son Not", 200),
)
ISLEM_ADLARI = {
    "OLUSTURMA": "Oluşturma",
    "ERTELEME": "Erteleme",
    "TUTAR": "Tutar değişikliği",
    "YONTEM": "Yöntem değişikliği",
    "GORUSME": "Görüşme notu",
    "IPTAL": "İptal",
    "DUZELTME": "Yetkili düzeltme",
    "BAGLANTI": "Evrak bağlandı",
    "BAGLANTI_IPTAL": "Bağlantı geri alındı",
}
DURUM_RENKLERI = {
    "Gecikti": "#b42318",
    "Bugün": "#b54708",
    "Yaklaşıyor": "#1d4ed8",
    "Tamamlandı": "#067647",
    "İptal": "#667085",
}


def _tarih_yazi(t) -> str:
    if isinstance(t, datetime):
        return t.strftime("%d.%m.%Y %H:%M")
    return t.strftime("%d.%m.%Y") if hasattr(t, "strftime") else str(t or "")


def _tarih_oku(metin: str, alan: str = "Tarih") -> date:
    try:
        return datetime.strptime((metin or "").strip(), "%d.%m.%Y").date()
    except ValueError as hata:
        raise ValueError(f"{alan} GG.AA.YYYY biçiminde olmalıdır.") from hata


def _para(deger) -> str:
    return tr_tutar(deger or 0)


def _modal(pencere: tk.Toplevel, parent) -> None:
    try:
        pencere.transient(parent.winfo_toplevel())
    except tk.TclError:
        pass
    pencere.update_idletasks()
    try:
        pencere.grab_set()
    except tk.TclError:
        pass
    pencere.focus_force()


def _grab_geri_ver(parent) -> None:
    try:
        ust = parent.winfo_toplevel()
        if ust.winfo_exists() and isinstance(ust, tk.Toplevel):
            ust.grab_set()
    except tk.TclError:
        pass


def cari_yonleri(cari_turu: str | None) -> tuple[str, ...]:
    """Müşteri → Alınan; tedarikçi → Verilen; her ikisi / belirsiz → iki yön de."""
    yonler = []
    if musteri_mi(cari_turu):
        yonler.append(ALINAN)
    if tedarikci_mi(cari_turu):
        yonler.append(VERILEN)
    return tuple(yonler) or (ALINAN, VERILEN)


def sozler_tablosu(parent, *, cari_goster: bool = True, height: int = 12) -> ttk.Treeview:
    kolonlar = [k for k in LISTE_SUTUNLARI if cari_goster or k[0] != "cari"]
    cerceve = ttk.Frame(parent)
    cerceve.pack(fill="both", expand=True)
    agac = ttk.Treeview(cerceve, columns=[k[0] for k in kolonlar], show="headings", height=height)
    for anahtar, baslik, gen in kolonlar:
        agac.heading(anahtar, text=baslik)
        sag = anahtar in ("tutar", "gerceklesen", "kalan")
        agac.column(anahtar, width=gen, anchor="e" if sag else "w", stretch=anahtar in ("cari", "not"))
    for durum, renk in DURUM_RENKLERI.items():
        agac.tag_configure(durum, foreground=renk)
    dikey = ttk.Scrollbar(cerceve, orient="vertical", command=agac.yview)
    yatay = ttk.Scrollbar(cerceve, orient="horizontal", command=agac.xview)
    agac.configure(yscrollcommand=dikey.set, xscrollcommand=yatay.set)
    agac.grid(row=0, column=0, sticky="nsew")
    dikey.grid(row=0, column=1, sticky="ns")
    yatay.grid(row=1, column=0, sticky="ew")
    cerceve.rowconfigure(0, weight=1)
    cerceve.columnconfigure(0, weight=1)
    agac._cari_goster = cari_goster  # type: ignore[attr-defined]
    return agac


def sozleri_doldur(agac: ttk.Treeview, sozler: list[dict]) -> None:
    agac.delete(*agac.get_children())
    for s in sozler:
        degerler = [
            f"{s['cari_kodu']} - {s['cari_unvan']}",
            "Alınan" if s["yon"] == ALINAN else "Verilen",
            _tarih_yazi(s["soz_tarihi"]),
            _tarih_yazi(s["vade_tarihi"]),
            _para(s["tutar"]),
            _para(s["gerceklesen"]),
            _para(s["kalan"]),
            s["para_birimi"],
            s["yontem"],
            s["durum_metni"] + (f" ({s['gecikme_gunu']} gün)" if s["gecikme_gunu"] else ""),
            s["sorumlu"],
            s["son_not"],
        ]
        if not getattr(agac, "_cari_goster", True):
            degerler = degerler[1:]
        agac.insert("", "end", iid=str(s["id"]), values=degerler, tags=(s["durum"],))


# --- Söz formu -------------------------------------------------------------------------------

class SozFormDialog(tk.Toplevel):
    """Yeni ödeme sözü. Bağlı faturalar isteğe bağlıdır; faturasız (avans) söz serbesttir."""

    def __init__(self, parent, *, cari_id: int, cari_adi: str, yonler: tuple[str, ...], yon: str | None = None):
        super().__init__(parent)
        self.parent = parent
        self.cari_id = int(cari_id)
        self.sonuc: int | None = None
        self.title("Yeni Ödeme Sözü")
        self.resizable(True, True)
        self.minsize(640, 560)
        self.protocol("WM_DELETE_WINDOW", self._kapat)

        govde = ttk.Frame(self, padding=12)
        govde.pack(fill="both", expand=True)
        govde.columnconfigure(1, weight=1)
        ttk.Label(govde, text=cari_adi, font=("Segoe UI", 11, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8)
        )

        self.yon_var = tk.StringVar(value=YON_ADLARI[yon or yonler[0]])
        self.soz_tarih_var = tk.StringVar(value=_tarih_yazi(date.today()))
        self.vade_var = tk.StringVar(value=_tarih_yazi(date.today() + timedelta(days=7)))
        self.tutar_var = tk.StringVar()
        self.pb_var = tk.StringVar(value="TRY")
        self.yontem_var = tk.StringVar(value=YONTEMLER[0])
        self.kisi_var = tk.StringVar()
        self.sorumlu_var = tk.StringVar(value=_aktif_kullanici())

        satir = 1

        def _etiket(metin):
            nonlocal satir
            ttk.Label(govde, text=metin).grid(row=satir, column=0, sticky="w", pady=3, padx=(0, 8))

        _etiket("Söz yönü")
        ttk.Combobox(govde, textvariable=self.yon_var, state="readonly",
                     values=[YON_ADLARI[y] for y in yonler], width=28).grid(row=satir, column=1, sticky="w")
        satir += 1
        for baslik, var in (("Söz verildiği tarih", self.soz_tarih_var), ("Vaat edilen ödeme tarihi", self.vade_var)):
            _etiket(baslik)
            kutu = ttk.Frame(govde)
            kutu.grid(row=satir, column=1, sticky="w")
            giris = ttk.Entry(kutu, textvariable=var, width=14)
            giris.pack(side="left")
            takvim_butonu(kutu, giris)
            satir += 1
        _etiket("Söz tutarı")
        kutu = ttk.Frame(govde)
        kutu.grid(row=satir, column=1, sticky="w")
        tutar_giris = ttk.Entry(kutu, textvariable=self.tutar_var, width=18)
        tutar_giris.pack(side="left")
        tutar_alani(tutar_giris, self.tutar_var)
        ttk.Combobox(kutu, textvariable=self.pb_var, values=("TRY", "USD", "EUR", "GBP"), width=6,
                     state="readonly").pack(side="left", padx=(6, 0))
        satir += 1
        _etiket("Ödeme yöntemi")
        ttk.Combobox(govde, textvariable=self.yontem_var, values=YONTEMLER, state="readonly",
                     width=18).grid(row=satir, column=1, sticky="w")
        satir += 1
        _etiket("Görüşülen kişi")
        ttk.Entry(govde, textvariable=self.kisi_var, width=40).grid(row=satir, column=1, sticky="ew")
        satir += 1
        _etiket("Sorumlu kullanıcı")
        ttk.Entry(govde, textvariable=self.sorumlu_var, width=30).grid(row=satir, column=1, sticky="w")
        satir += 1
        _etiket("Açıklama / görüşme notu")
        self.aciklama_txt = tk.Text(govde, height=3, width=50, wrap="word")
        self.aciklama_txt.grid(row=satir, column=1, sticky="ew")
        satir += 1

        fat = ttk.LabelFrame(govde, text="Bağlı faturalar (isteğe bağlı — boş bırakılırsa faturasız/avans söz)",
                             padding=6)
        fat.grid(row=satir, column=0, columnspan=3, sticky="nsew", pady=(10, 0))
        govde.rowconfigure(satir, weight=1)
        self.fatura_agac = ttk.Treeview(fat, columns=("sec", "no", "tur", "tarih", "acik", "pb", "tutar"),
                                        show="headings", height=6)
        for k, b, w in (("sec", "Seç", 40), ("no", "Fatura No", 120), ("tur", "Tür", 110), ("tarih", "Tarih", 80),
                        ("acik", "Açık Tutar", 100), ("pb", "Döviz", 50), ("tutar", "Söz Payı", 100)):
            self.fatura_agac.heading(k, text=b)
            self.fatura_agac.column(k, width=w, anchor="e" if k in ("acik", "tutar") else "w")
        self.fatura_agac.pack(fill="both", expand=True)
        self.fatura_agac.bind("<Double-1>", self._fatura_payi_gir)
        ttk.Label(fat, text="Çift tıklayarak faturayı seçin ve söz payını girin.",
                  foreground="#667085").pack(anchor="w")
        self._fatura_paylari: dict[str, Decimal] = {}
        self._acik_faturalar: dict[str, dict] = {}
        self._faturalari_yukle()

        alt = ttk.Frame(govde)
        alt.grid(row=satir + 1, column=0, columnspan=3, sticky="e", pady=(10, 0))
        ttk.Button(alt, text="Kaydet", command=self._kaydet).pack(side="right")
        ttk.Button(alt, text="Vazgeç", command=self._kapat).pack(side="right", padx=6)
        _modal(self, parent)

    def _yon(self) -> str:
        secim = self.yon_var.get()
        return next((k for k, v in YON_ADLARI.items() if v == secim), ALINAN)

    def _faturalari_yukle(self) -> None:
        from database.kapatma_izleme_service import acik_kalemler_listesi

        try:
            satirlar = acik_kalemler_listesi(self.cari_id)
        except Exception:
            satirlar = []
        for s in satirlar:
            if s["orijinal"] <= 0 or s["acik"] == 0:
                continue
            no = s["evrak_no"]
            self._acik_faturalar[no] = s
            self.fatura_agac.insert("", "end", iid=no, values=(
                "", no, s["evrak_turu"], _tarih_yazi(s["evrak_tarihi"]), _para(abs(s["acik"])),
                s["para_birimi"], "",
            ))

    def _fatura_payi_gir(self, _e=None) -> None:
        sec = self.fatura_agac.focus()
        if not sec:
            return
        satir = self._acik_faturalar[sec]
        varsayilan = self._fatura_paylari.get(sec) or abs(satir["acik"])
        metin = simpledialog.askstring(
            "Söz payı", f"{sec} için söz payı (0 = bağlantıyı kaldır):",
            initialvalue=_para(varsayilan), parent=self,
        )
        if metin is None:
            return
        try:
            tutar = tutar_coz(metin).quantize(Decimal("0.01"))
        except ValueError as hata:
            messagebox.showwarning("Söz payı", str(hata), parent=self)
            return
        if tutar < 0:
            messagebox.showwarning("Söz payı", "Pay negatif olamaz.", parent=self)
            return
        if tutar > abs(satir["acik"]):
            messagebox.showwarning("Söz payı", "Pay faturanın açık tutarını aşamaz.", parent=self)
            return
        if tutar == 0:
            self._fatura_paylari.pop(sec, None)
            self.fatura_agac.set(sec, "sec", "")
            self.fatura_agac.set(sec, "tutar", "")
        else:
            self._fatura_paylari[sec] = tutar
            self.fatura_agac.set(sec, "sec", "✓")
            self.fatura_agac.set(sec, "tutar", _para(tutar))

    def _kaydet(self) -> None:
        try:
            veriler = {
                "cari_id": self.cari_id,
                "yon": self._yon(),
                "soz_tarihi": _tarih_oku(self.soz_tarih_var.get(), "Söz tarihi"),
                "vade_tarihi": _tarih_oku(self.vade_var.get(), "Ödeme tarihi"),
                "tutar": tutar_coz(self.tutar_var.get()),
                "para_birimi": self.pb_var.get(),
                "yontem": self.yontem_var.get(),
                "gorusulen_kisi": self.kisi_var.get(),
                "sorumlu": self.sorumlu_var.get(),
                "aciklama": self.aciklama_txt.get("1.0", "end").strip(),
            }
            for no in self._fatura_paylari:
                if self._acik_faturalar[no]["para_birimi"] != veriler["para_birimi"]:
                    raise ValueError(f"{no} faturasının para birimi sözden farklı; dövizler ayrı tutulur.")
            self.sonuc = OdemeSozuService.olustur(veriler, list(self._fatura_paylari.items()))
        except (ValueError, PermissionError) as hata:
            messagebox.showwarning("Ödeme sözü", str(hata), parent=self)
            return
        self._kapat()

    def _kapat(self) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        _grab_geri_ver(self.parent)


def _aktif_kullanici() -> str:
    from database.odeme_sozu_service import _kullanici

    return _kullanici() or ""


# --- Söz detayı -------------------------------------------------------------------------------

class SozDetayDialog(tk.Toplevel):
    """Söz bilgisi + değişiklik geçmişi + bağlı ödeme evrakları + işlemler."""

    def __init__(self, parent, soz_id: int, on_degisti=None):
        super().__init__(parent)
        self.parent = parent
        self.soz_id = int(soz_id)
        self.on_degisti = on_degisti
        self.title("Ödeme Sözü Detayı")
        self.geometry("900x620")
        self.minsize(760, 520)
        self.protocol("WM_DELETE_WINDOW", self._kapat)

        govde = ttk.Frame(self, padding=10)
        govde.pack(fill="both", expand=True)
        self.baslik_lbl = ttk.Label(govde, font=("Segoe UI", 11, "bold"))
        self.baslik_lbl.pack(anchor="w")
        self.bilgi_lbl = ttk.Label(govde, justify="left")
        self.bilgi_lbl.pack(anchor="w", pady=(4, 8))

        dugmeler = ttk.Frame(govde)
        dugmeler.pack(fill="x", pady=(0, 8))
        for metin, komut in (
            ("Görüşme Notu", self._not_ekle),
            ("Ertele", self._ertele),
            ("Tutar Değiştir", self._tutar),
            ("Yöntem Değiştir", self._yontem),
            ("Evrak Bağla (sonradan)", self._sonradan_bagla),
            ("Bağlantıyı Kaldır", self._baglanti_kaldir),
            ("Elle Tamamla", self._elle_tamamla),
            ("İptal Et", self._iptal),
        ):
            ttk.Button(dugmeler, text=metin, command=komut).pack(side="left", padx=(0, 4))

        sekmeler = ttk.Notebook(govde)
        sekmeler.pack(fill="both", expand=True)
        f1 = ttk.Frame(sekmeler, padding=4)
        f2 = ttk.Frame(sekmeler, padding=4)
        f3 = ttk.Frame(sekmeler, padding=4)
        sekmeler.add(f1, text="Değişiklik Geçmişi")
        sekmeler.add(f2, text="Bağlı Ödeme Evrakları")
        sekmeler.add(f3, text="Bağlı Faturalar")
        self.gecmis_agac = self._agac(f1, (("zaman", "Tarih", 120), ("kullanici", "Kullanıcı", 100),
                                           ("islem", "İşlem", 130), ("eski", "Eski", 110), ("yeni", "Yeni", 140),
                                           ("aciklama", "Açıklama", 260)))
        self.baglanti_agac = self._agac(f2, (("tarih", "Tarih", 80), ("tur", "Evrak Türü", 120),
                                             ("no", "Evrak No", 120), ("tutar", "Söze Bağlanan", 100),
                                             ("evrak", "Evrak Tutarı", 100), ("pb", "Döviz", 50),
                                             ("kullanici", "Kullanıcı", 90), ("durum", "Durum", 160)))
        self.baglanti_agac.bind("<Double-1>", self._evrak_ac)
        self.fatura_agac = self._agac(f3, (("no", "Fatura No", 140), ("tutar", "Söz Payı", 110)))
        ttk.Label(f3, text="Söz faturayı kapatmaz; kapatma yalnızca gerçek ödeme evrakıyla yapılır.",
                  foreground="#667085").pack(anchor="w")
        ttk.Button(govde, text="Kapat", command=self._kapat).pack(anchor="e", pady=(8, 0))
        self.yenile()
        _modal(self, parent)

    @staticmethod
    def _agac(parent, kolonlar) -> ttk.Treeview:
        agac = ttk.Treeview(parent, columns=[k[0] for k in kolonlar], show="headings", height=10)
        for k, b, w in kolonlar:
            agac.heading(k, text=b)
            agac.column(k, width=w, anchor="e" if k in ("tutar", "evrak") else "w")
        dikey = ttk.Scrollbar(parent, orient="vertical", command=agac.yview)
        agac.configure(yscrollcommand=dikey.set)
        dikey.pack(side="right", fill="y")
        agac.pack(fill="both", expand=True)
        return agac

    def yenile(self) -> None:
        try:
            s = OdemeSozuService.getir(self.soz_id)
        except ValueError as hata:
            messagebox.showerror("Ödeme sözü", str(hata), parent=self)
            return
        self._soz = s
        self.baslik_lbl.configure(text=f"{s['cari_kodu']} - {s['cari_unvan']}  ·  {s['yon_adi']}")
        satirlar = [
            f"Söz tarihi: {_tarih_yazi(s['soz_tarihi'])}    Ödeme tarihi: {_tarih_yazi(s['vade_tarihi'])}"
            f"    Yöntem: {s['yontem']}",
            f"Tutar: {_para(s['tutar'])} {s['para_birimi']}    Gerçekleşen: {_para(s['gerceklesen'])}"
            f"    Kalan: {_para(s['kalan'])}    Durum: {s['durum_metni']}",
            f"Görüşülen: {s['gorusulen_kisi'] or '-'}    Sorumlu: {s['sorumlu'] or '-'}"
            f"    Oluşturan: {s['olusturan'] or '-'}",
        ]
        if s["aciklama"]:
            satirlar.append(f"Açıklama: {s['aciklama']}")
        if s["kapanis_nedeni"]:
            satirlar.append(f"Kapanış gerekçesi: {s['kapanis_nedeni']}")
        self.bilgi_lbl.configure(text="\n".join(satirlar))
        self.gecmis_agac.delete(*self.gecmis_agac.get_children())
        for g in s["gecmis"]:
            self.gecmis_agac.insert("", "end", values=(
                _tarih_yazi(g["zaman"]), g["kullanici"], ISLEM_ADLARI.get(g["islem"], g["islem"]),
                g["eski"], g["yeni"], g["aciklama"],
            ))
        self.baglanti_agac.delete(*self.baglanti_agac.get_children())
        for b in s["baglantilar"]:
            durum = "Geri alındı" + (f" — {b['iptal_nedeni']}" if b["iptal_nedeni"] else "") if b["iptal"] else "Geçerli"
            self.baglanti_agac.insert("", "end", iid=str(b["id"]), values=(
                _tarih_yazi(b["tarih"]), b["evrak_turu"], b["evrak_no"], _para(b["tutar"]),
                _para(b["evrak_tutari"]), b["para_birimi"], b["kullanici"], durum,
            ))
        self.fatura_agac.delete(*self.fatura_agac.get_children())
        for no, tutar in s["faturalar"]:
            self.fatura_agac.insert("", "end", values=(no, _para(tutar)))

    def _islem(self, fonk, *args, **kwargs) -> bool:
        try:
            fonk(*args, **kwargs)
        except (ValueError, PermissionError) as hata:
            messagebox.showwarning("Ödeme sözü", str(hata), parent=self)
            return False
        self.yenile()
        if self.on_degisti:
            self.on_degisti()
        return True

    def _sor(self, baslik, soru, varsayilan="") -> str | None:
        return simpledialog.askstring(baslik, soru, initialvalue=varsayilan, parent=self)

    def _not_ekle(self) -> None:
        pen = tk.Toplevel(self)
        pen.title("Görüşme Notu")
        pen.resizable(False, False)
        fr = ttk.Frame(pen, padding=10)
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text="Not").grid(row=0, column=0, sticky="w")
        not_var = tk.StringVar()
        giris = ttk.Entry(fr, textvariable=not_var, width=50)
        giris.grid(row=0, column=1, sticky="ew")
        hizli = ttk.Frame(fr)
        hizli.grid(row=1, column=1, sticky="w", pady=4)
        hat_var = tk.StringVar()
        for metin, gun in (("Görüştüm", None), ("Yarın ara", 1), ("Haftaya ara", 7)):
            def _sec(m=metin, g=gun):
                not_var.set(m)
                hat_var.set(_tarih_yazi(date.today() + timedelta(days=g)) if g else "")
            ttk.Button(hizli, text=metin, command=_sec).pack(side="left", padx=(0, 4))
        ttk.Label(fr, text="Hatırlatma tarihi").grid(row=2, column=0, sticky="w")
        hk = ttk.Frame(fr)
        hk.grid(row=2, column=1, sticky="w")
        hg = ttk.Entry(hk, textvariable=hat_var, width=14)
        hg.pack(side="left")
        takvim_butonu(hk, hg)

        def _tamam():
            try:
                hatirlat = _tarih_oku(hat_var.get(), "Hatırlatma tarihi") if hat_var.get().strip() else None
            except ValueError as hata:
                messagebox.showwarning("Görüşme notu", str(hata), parent=pen)
                return
            if self._islem(OdemeSozuService.gorusme_notu, self.soz_id, not_var.get(), hatirlat_tarihi=hatirlat):
                pen.destroy()
                self.grab_set()

        def _vazgec():
            pen.destroy()
            self.grab_set()

        ttk.Button(fr, text="Kaydet", command=_tamam).grid(row=3, column=1, sticky="e", pady=(8, 0))
        pen.protocol("WM_DELETE_WINDOW", _vazgec)
        pen.transient(self)
        pen.grab_set()
        giris.focus_set()

    def _ertele(self) -> None:
        yeni = self._sor("Ertele", "Yeni ödeme tarihi (GG.AA.YYYY):", _tarih_yazi(self._soz["vade_tarihi"]))
        if not yeni:
            return
        try:
            tarih = _tarih_oku(yeni, "Yeni ödeme tarihi")
        except ValueError as hata:
            messagebox.showwarning("Ertele", str(hata), parent=self)
            return
        aciklama = self._sor("Ertele", "Erteleme açıklaması:")
        if aciklama is not None:
            self._islem(OdemeSozuService.ertele, self.soz_id, tarih, aciklama)

    def _tutar(self) -> None:
        yeni = self._sor("Tutar Değiştir", "Yeni söz tutarı:", _para(self._soz["tutar"]))
        if not yeni:
            return
        aciklama = self._sor("Tutar Değiştir", "Değişiklik açıklaması:")
        if aciklama is None:
            return
        try:
            tutar = tutar_coz(yeni)
        except ValueError as hata:
            messagebox.showwarning("Tutar", str(hata), parent=self)
            return
        self._islem(OdemeSozuService.tutar_degistir, self.soz_id, tutar, aciklama)

    def _yontem(self) -> None:
        yeni = self._sor("Yöntem Değiştir", "Yeni yöntem (" + ", ".join(YONTEMLER) + "):", self._soz["yontem"])
        if not yeni:
            return
        aciklama = self._sor("Yöntem Değiştir", "Açıklama:") or ""
        self._islem(OdemeSozuService.yontem_degistir, self.soz_id, yeni.strip(), aciklama)

    def _iptal(self) -> None:
        neden = self._sor("İptal Et", "İptal nedeni (zorunlu):")
        if neden is not None:
            self._islem(OdemeSozuService.iptal_et, self.soz_id, neden)

    def _elle_tamamla(self) -> None:
        if not messagebox.askyesno(
            "Elle Tamamla",
            "Bu işlem yetkili düzeltmedir: söz tamamlandı sayılır, hiçbir para hareketi oluşmaz "
            "ve fatura kapanmaz. Devam edilsin mi?",
            parent=self,
        ):
            return
        neden = self._sor("Elle Tamamla", "Düzeltme gerekçesi (zorunlu):")
        if neden is not None:
            self._islem(OdemeSozuService.elle_tamamla, self.soz_id, neden)

    def _sonradan_bagla(self) -> None:
        belge = self._sor("Evrak Bağla", "Kayıtlı ödeme evrakının numarası (makbuz / havale / KK / çek-senet):")
        if not belge:
            return
        bilgi = OdemeSozuService.evrak_bilgisi(belge.strip(), self._soz["cari_id"])
        if bilgi is None or not bilgi["gecerli"]:
            messagebox.showwarning("Evrak Bağla", "Bu cariye ait geçerli bir ödeme evrakı bulunamadı.", parent=self)
            return
        onerilen = min(bilgi["tutar"], self._soz["kalan"])
        tutar_m = self._sor("Evrak Bağla", f"{bilgi['evrak_turu']} · evrak tutarı {_para(bilgi['tutar'])} "
                                           f"{bilgi['para_birimi']}\nSöze bağlanacak tutar:", _para(onerilen))
        if not tutar_m:
            return
        try:
            tutar = tutar_coz(tutar_m)
        except ValueError as hata:
            messagebox.showwarning("Evrak Bağla", str(hata), parent=self)
            return
        self._islem(
            OdemeSozuService.baglanti_ekle, self.soz_id, evrak_turu=bilgi["evrak_turu"],
            evrak_belge_no=belge.strip(), tutar=tutar, evrak_tutari=bilgi["tutar"],
            para_birimi=bilgi["para_birimi"], tarih=bilgi["tarih"], evrak_id=bilgi["evrak_id"], sonradan=True,
        )

    def _baglanti_kaldir(self) -> None:
        sec = self.baglanti_agac.focus()
        if not sec:
            messagebox.showinfo("Bağlantı", "Kaldırılacak bağlantıyı seçin.", parent=self)
            return
        neden = self._sor("Bağlantıyı Kaldır", "Gerekçe (zorunlu):")
        if neden is not None:
            self._islem(OdemeSozuService.baglanti_kaldir, int(sec), neden)

    def _evrak_ac(self, _e=None) -> None:
        sec = self.baglanti_agac.focus()
        if not sec:
            return
        degerler = self.baglanti_agac.item(sec, "values")
        try:
            from belge_onizleme_ui import hareket_belgeyi_ac

            hareket_belgeyi_ac(self, degerler[1], degerler[2])
        except Exception as hata:
            messagebox.showinfo("Evrak", f"Evrak açılamadı: {hata}", parent=self)

    def _kapat(self) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        _grab_geri_ver(self.parent)


# --- Cari kart listesi ------------------------------------------------------------------------

class CariOdemeSozleriDialog(tk.Toplevel):
    """Cari kartından açılan ödeme sözleri listesi (Alınan / Verilen) ve özet."""

    def __init__(self, parent, cari):
        super().__init__(parent)
        self.parent = parent
        self.cari_id = int(cari.id)
        self.cari_adi = f"{cari.cari_kodu} - {cari.unvan}"
        self.yonler = cari_yonleri(getattr(cari, "cari_turu", ""))
        baslik = "Ödeme Sözleri (Alınan)" if self.yonler == (ALINAN,) else (
            "Ödeme Sözleri (Verilen)" if self.yonler == (VERILEN,) else "Ödeme Sözleri")
        self.title(f"{baslik} — {self.cari_adi}")
        self.geometry("1150x560")
        self.minsize(900, 420)
        self.protocol("WM_DELETE_WINDOW", self._kapat)

        govde = ttk.Frame(self, padding=10)
        govde.pack(fill="both", expand=True)
        ttk.Label(govde, text=self.cari_adi, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.ozet_lbl = ttk.Label(govde, foreground="#1d4ed8")
        self.ozet_lbl.pack(anchor="w", pady=(2, 6))

        ust = ttk.Frame(govde)
        ust.pack(fill="x", pady=(0, 6))
        self.yon_var = tk.StringVar(value="Tümü")
        if len(self.yonler) > 1:
            ttk.Label(ust, text="Yön").pack(side="left")
            cb = ttk.Combobox(ust, textvariable=self.yon_var, state="readonly", width=24,
                              values=["Tümü"] + [YON_ADLARI[y] for y in self.yonler])
            cb.pack(side="left", padx=(4, 12))
            cb.bind("<<ComboboxSelected>>", lambda _e: self.yenile())
        self.acik_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(ust, text="Yalnız açık sözler", variable=self.acik_var,
                        command=self.yenile).pack(side="left")
        ttk.Button(ust, text="Yeni Söz", command=self._yeni).pack(side="right")
        ttk.Button(ust, text="Detay / Geçmiş", command=self._detay).pack(side="right", padx=6)

        self.agac = sozler_tablosu(govde, cari_goster=False)
        self.agac.bind("<Double-1>", lambda _e: self._detay())
        ttk.Label(govde, text="Söz planlama kaydıdır; kasa, banka, cari bakiye ve fatura durumunu değiştirmez.",
                  foreground="#667085").pack(anchor="w", pady=(6, 0))
        self.yenile()
        _modal(self, parent)

    def _yon(self) -> str | None:
        secim = self.yon_var.get()
        return next((k for k, v in YON_ADLARI.items() if v == secim), None)

    def yenile(self) -> None:
        try:
            sozler = OdemeSozuService.liste(cari_id=self.cari_id, yon=self._yon(),
                                            sadece_acik=self.acik_var.get())
            if len(self.yonler) == 1:
                sozler = [s for s in sozler if s["yon"] == self.yonler[0]]
            oz = OdemeSozuService.cari_ozeti(self.cari_id)
        except Exception as hata:
            messagebox.showerror("Ödeme sözleri", str(hata), parent=self)
            return
        sozleri_doldur(self.agac, sozler)
        self.ozet_lbl.configure(text=(
            f"Açık: {oz['acik_adet']}  |  Yaklaşan: {oz['yaklasan_adet']} / {para_toplam_metni(oz['yaklasan_tutar'])}"
            f"  |  Bugün: {oz['bugun_adet']} / {para_toplam_metni(oz['bugun_tutar'])}"
            f"  |  Geciken: {oz['geciken_adet']} / {para_toplam_metni(oz['geciken_tutar'])}"
        ))

    def _yeni(self) -> None:
        dlg = SozFormDialog(self, cari_id=self.cari_id, cari_adi=self.cari_adi, yonler=self.yonler,
                            yon=self._yon())
        self.wait_window(dlg)
        if dlg.sonuc:
            self.yenile()

    def _detay(self) -> None:
        sec = self.agac.focus()
        if not sec:
            messagebox.showinfo("Ödeme sözleri", "Bir söz seçin.", parent=self)
            return
        dlg = SozDetayDialog(self, int(sec), on_degisti=self.yenile)
        self.wait_window(dlg)
        self.yenile()

    def _kapat(self) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        _grab_geri_ver(self.parent)


# --- Merkezi takvim / liste -------------------------------------------------------------------

class OdemeSozleriMerkezDialog(tk.Toplevel):
    """Tüm cariler için ödeme sözleri takvimi: filtreler, 7/14/30 gün tahmini akış, CSV."""

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Ödeme Sözleri Takvimi")
        self.geometry("1280x720")
        self.minsize(1000, 560)

        govde = ttk.Frame(self, padding=10)
        govde.pack(fill="both", expand=True)
        ttk.Label(govde, text="ÖDEME SÖZLERİ TAKVİMİ", font=("Segoe UI", 12, "bold")).pack(anchor="w")

        oz = ttk.Frame(govde)
        oz.pack(fill="x", pady=(6, 4))
        self.gunluk_lbl = ttk.Label(oz, justify="left", font=("Segoe UI", 10, "bold"))
        self.gunluk_lbl.pack(anchor="w")
        self.akis_lbl = ttk.Label(oz, justify="left")
        self.akis_lbl.pack(anchor="w", pady=(2, 0))
        ttk.Label(oz, text="Tahmini nakit akışıdır; gerçek kasa/banka bakiyesine eklenmez.",
                  foreground="#b54708").pack(anchor="w")

        flt = ttk.LabelFrame(govde, text="Filtreler", padding=6)
        flt.pack(fill="x", pady=(4, 6))
        self.cari_var = tk.StringVar()
        self.yon_var = tk.StringVar(value="Tümü")
        self.sorumlu_var = tk.StringVar()
        self.bas_var = tk.StringVar()
        self.bit_var = tk.StringVar()
        self.durum_var = tk.StringVar(value="Tümü")
        self.yontem_var = tk.StringVar(value="Tümü")
        self.pb_var = tk.StringVar(value="Tümü")
        self.acik_var = tk.BooleanVar(value=True)

        def _alan(metin, widget, sutun, satir=0):
            ttk.Label(flt, text=metin).grid(row=satir, column=sutun, sticky="w", padx=(0, 4))
            widget.grid(row=satir, column=sutun + 1, sticky="w", padx=(0, 10), pady=2)

        _alan("Cari", ttk.Entry(flt, textvariable=self.cari_var, width=22), 0)
        _alan("Yön", ttk.Combobox(flt, textvariable=self.yon_var, state="readonly", width=22,
                                  values=["Tümü"] + list(YON_ADLARI.values())), 2)
        _alan("Sorumlu", ttk.Entry(flt, textvariable=self.sorumlu_var, width=14), 4)
        _alan("Durum", ttk.Combobox(flt, textvariable=self.durum_var, state="readonly", width=16,
                                    values=["Tümü", *DURUMLAR]), 6)
        for i, (metin, var) in enumerate((("Vade başlangıç", self.bas_var), ("Vade bitiş", self.bit_var))):
            kutu = ttk.Frame(flt)
            giris = ttk.Entry(kutu, textvariable=var, width=11)
            giris.pack(side="left")
            takvim_butonu(kutu, giris, width=6)
            _alan(metin, kutu, i * 2, 1)
        _alan("Yöntem", ttk.Combobox(flt, textvariable=self.yontem_var, state="readonly", width=12,
                                     values=["Tümü", *YONTEMLER]), 4, 1)
        _alan("Döviz", ttk.Combobox(flt, textvariable=self.pb_var, state="readonly", width=8,
                                    values=("Tümü", "TRY", "USD", "EUR", "GBP")), 6, 1)
        dg = ttk.Frame(flt)
        dg.grid(row=0, column=8, rowspan=2, sticky="e")
        ttk.Checkbutton(dg, text="Yalnız açık", variable=self.acik_var).pack(anchor="w")
        ttk.Button(dg, text="Listele", command=self.yenile).pack(fill="x", pady=2)
        ttk.Button(dg, text="Temizle", command=self._temizle).pack(fill="x")

        hizli = ttk.Frame(govde)
        hizli.pack(fill="x", pady=(0, 4))
        for metin, gun in (("Bugün", 0), ("7 gün", 7), ("14 gün", 14), ("30 gün", 30), ("Gecikenler", -1)):
            ttk.Button(hizli, text=metin, command=lambda g=gun: self._hizli(g)).pack(side="left", padx=(0, 4))
        ttk.Button(hizli, text="CSV Dışa Aktar", command=self._csv).pack(side="right")
        ttk.Button(hizli, text="Detay / Geçmiş", command=self._detay).pack(side="right", padx=6)

        self.agac = sozler_tablosu(govde, cari_goster=True, height=16)
        self.agac.bind("<Double-1>", lambda _e: self._detay())
        self.alt_lbl = ttk.Label(govde, foreground="#667085")
        self.alt_lbl.pack(anchor="w", pady=(4, 0))
        self._sozler: list[dict] = []
        self.yenile()

    def _temizle(self) -> None:
        for v in (self.cari_var, self.sorumlu_var, self.bas_var, self.bit_var):
            v.set("")
        for v in (self.yon_var, self.durum_var, self.yontem_var, self.pb_var):
            v.set("Tümü")
        self.acik_var.set(True)
        self.yenile()

    def _hizli(self, gun: int) -> None:
        bugun = date.today()
        self.durum_var.set("Tümü")
        if gun < 0:
            self.bas_var.set("")
            self.bit_var.set("")
            self.durum_var.set("Gecikti")
        else:
            self.bas_var.set(_tarih_yazi(bugun) if gun == 0 else "")
            self.bit_var.set(_tarih_yazi(bugun + timedelta(days=gun)))
        self.acik_var.set(True)
        self.yenile()

    def _secim(self, var, sozluk=None):
        deger = var.get()
        if deger in ("", "Tümü"):
            return None
        if sozluk:
            return next((k for k, v in sozluk.items() if v == deger), None)
        return deger

    def yenile(self) -> None:
        try:
            bas = _tarih_oku(self.bas_var.get(), "Vade başlangıç") if self.bas_var.get().strip() else None
            bit = _tarih_oku(self.bit_var.get(), "Vade bitiş") if self.bit_var.get().strip() else None
            sozler = OdemeSozuService.liste(
                yon=self._secim(self.yon_var, YON_ADLARI), sorumlu=self.sorumlu_var.get().strip() or None,
                vade_bas=bas, vade_bit=bit, durum=self._secim(self.durum_var),
                yontem=self._secim(self.yontem_var), para_birimi=self._secim(self.pb_var),
                sadece_acik=self.acik_var.get(),
            )
            takvim = OdemeSozuService.takvim_ozeti()
        except ValueError as hata:
            messagebox.showwarning("Ödeme sözleri", str(hata), parent=self)
            return
        cari = self.cari_var.get().strip().casefold()
        if cari:
            sozler = [s for s in sozler if cari in s["cari_kodu"].casefold() or cari in s["cari_unvan"].casefold()]
        self._sozler = sozler
        sozleri_doldur(self.agac, sozler)
        self.gunluk_lbl.configure(text=(
            f"Bugün beklenen giriş: {para_toplam_metni(takvim['bugun_giris'])}     "
            f"Bugün söz verilen çıkış: {para_toplam_metni(takvim['bugun_cikis'])}\n"
            f"Geciken müşteri sözleri: {para_toplam_metni(takvim['geciken_musteri'])}     "
            f"Geciken tedarikçi sözleri: {para_toplam_metni(takvim['geciken_tedarikci'])}"
        ))
        self.akis_lbl.configure(text="\n".join(
            f"{gun} gün içinde — Beklenen giriş: {para_toplam_metni(a['giris'])}   "
            f"Söz verilen çıkış: {para_toplam_metni(a['cikis'])}"
            for gun, a in takvim["araliklar"].items()
        ))
        kalan: dict[str, Decimal] = {}
        for s in sozler:
            kalan[s["para_birimi"]] = kalan.get(s["para_birimi"], Decimal("0")) + s["kalan"]
        self.alt_lbl.configure(text=f"{len(sozler)} söz  ·  Listelenen kalan: {para_toplam_metni(kalan)}")

    def _detay(self) -> None:
        sec = self.agac.focus()
        if not sec:
            messagebox.showinfo("Ödeme sözleri", "Bir söz seçin.", parent=self)
            return
        dlg = SozDetayDialog(self, int(sec), on_degisti=self.yenile)
        self.wait_window(dlg)
        self.yenile()

    def _csv(self) -> None:
        if not self._sozler:
            messagebox.showinfo("CSV", "Aktarılacak söz yok.", parent=self)
            return
        yol = filedialog.asksaveasfilename(
            parent=self, defaultextension=".csv", filetypes=[("CSV", "*.csv")],
            initialfile=f"odeme_sozleri_{date.today():%Y%m%d}.csv",
        )
        if not yol:
            return
        try:
            OdemeSozuService.csv_yaz(self._sozler, yol)
        except OSError as hata:
            messagebox.showerror("CSV", str(hata), parent=self)
            return
        messagebox.showinfo("CSV", f"{len(self._sozler)} söz aktarıldı:\n{yol}", parent=self)


# --- Evrak kaydında söze bağlama --------------------------------------------------------------

class SozBaglamaDialog(tk.Toplevel):
    """Ödeme evrakı kaydedildikten sonra açık sözlere tutar dağıtımı (isteğe bağlı, çoklu)."""

    def __init__(self, parent, *, sozler, evrak_turu, belge_no, tutar, para_birimi, evrak_id, tarih):
        super().__init__(parent)
        self.parent = parent
        self.evrak = dict(evrak_turu=evrak_turu, evrak_belge_no=belge_no, evrak_tutari=tutar,
                          para_birimi=para_birimi, evrak_id=evrak_id, tarih=tarih)
        self.tutar = Decimal(str(tutar))
        self.sonuc = 0
        self.title("Ödeme Sözüne Bağla")
        self.resizable(True, False)
        self.protocol("WM_DELETE_WINDOW", self._kapat)
        govde = ttk.Frame(self, padding=10)
        govde.pack(fill="both", expand=True)
        ttk.Label(govde, text=f"{evrak_turu} {belge_no} · {_para(tutar)} {para_birimi}",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Label(govde, text="Bu cari için açık ödeme sözü var. Evrakı bir veya birden fazla söze "
                              "bağlayabilirsiniz (isteğe bağlı). Söz faturayı kapatmaz.",
                  wraplength=620, justify="left").pack(anchor="w", pady=(4, 8))
        tablo = ttk.Frame(govde)
        tablo.pack(fill="x")
        for i, b in enumerate(("Ödeme Tarihi", "Tutar", "Kalan", "Yöntem", "Durum", "Bağlanacak")):
            ttk.Label(tablo, text=b, font=("Segoe UI", 9, "bold")).grid(row=0, column=i, sticky="w", padx=4)
        self.satirlar: list[tuple[dict, tk.StringVar]] = []
        for r, s in enumerate(sozler, start=1):
            for i, v in enumerate((_tarih_yazi(s["vade_tarihi"]), _para(s["tutar"]), _para(s["kalan"]),
                                   s["yontem"], s["durum_metni"])):
                ttk.Label(tablo, text=v).grid(row=r, column=i, sticky="w", padx=4, pady=1)
            var = tk.StringVar()
            giris = ttk.Entry(tablo, textvariable=var, width=14, justify="right")
            giris.grid(row=r, column=5, padx=4)
            self.satirlar.append((s, var))
        if len(self.satirlar) == 1:
            s, var = self.satirlar[0]
            var.set(_para(min(s["kalan"], self.tutar)))
        alt = ttk.Frame(govde)
        alt.pack(fill="x", pady=(10, 0))
        ttk.Button(alt, text="Bağla", command=self._bagla).pack(side="right")
        ttk.Button(alt, text="Bağlamadan Geç", command=self._kapat).pack(side="right", padx=6)
        _modal(self, parent)

    def _bagla(self) -> None:
        dagitim = []
        toplam = Decimal("0")
        try:
            for s, var in self.satirlar:
                metin = var.get().strip()
                if not metin:
                    continue
                t = tutar_coz(metin).quantize(Decimal("0.01"))
                if t <= 0:
                    continue
                if t > s["kalan"]:
                    raise ValueError(f"{_tarih_yazi(s['vade_tarihi'])} tarihli sözün kalanı "
                                     f"({_para(s['kalan'])}) aşılamaz.")
                dagitim.append((s["id"], t))
                toplam += t
            if toplam > self.tutar:
                raise ValueError(f"Bağlanan toplam ({_para(toplam)}) evrak tutarını aşamaz.")
        except ValueError as hata:
            messagebox.showwarning("Söze bağla", str(hata), parent=self)
            return
        if not dagitim:
            self._kapat()
            return
        hatalar = []
        for soz_id, t in dagitim:
            try:
                OdemeSozuService.baglanti_ekle(soz_id, tutar=t, **self.evrak)
                self.sonuc += 1
            except (ValueError, PermissionError) as hata:
                hatalar.append(str(hata))
        if hatalar:
            messagebox.showwarning("Söze bağla", "\n".join(hatalar), parent=self)
        self._kapat()

    def _kapat(self) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        _grab_geri_ver(self.parent)


def evrak_kaydi_sonrasi_bagla(parent, *, cari_id, yon: str, evrak_turu: str, belge_no: str | None) -> int:
    """Havale / KK / çek-senet gibi cari hareketli evraklar: tutar ve döviz kayıtlı evraktan okunur."""
    if not cari_id or not belge_no:
        return 0
    try:
        bilgi = OdemeSozuService.evrak_bilgisi(belge_no, int(cari_id))
    except Exception:
        return 0
    if not bilgi or not bilgi["gecerli"]:
        return 0
    return soz_baglama_sor(parent, cari_id=cari_id, yon=yon, evrak_turu=evrak_turu, belge_no=belge_no,
                           tutar=bilgi["tutar"], para_birimi=bilgi["para_birimi"], evrak_id=bilgi["evrak_id"],
                           tarih=bilgi["tarih"])


def soz_baglama_sor(parent, *, cari_id, yon: str, evrak_turu: str, belge_no: str, tutar,
                    para_birimi: str = "TRY", evrak_id: int | None = None, tarih: date | None = None) -> int:
    """Kayıt sonrası: carinin bu yönde açık sözü varsa bağlama penceresi açar. Bağlanan söz sayısını döner.

    Hiçbir hata evrak kaydını geri almaz; söz bağlantısı her zaman isteğe bağlıdır.
    """
    if not cari_id or not belge_no:
        return 0
    try:
        tutar = Decimal(str(tutar or 0))
        if tutar <= 0:
            return 0
        sozler = OdemeSozuService.acik_sozler(int(cari_id), yon, (para_birimi or "TRY").upper())
    except Exception:
        return 0
    if not sozler:
        return 0
    dlg = SozBaglamaDialog(parent, sozler=sozler, evrak_turu=evrak_turu, belge_no=belge_no, tutar=tutar,
                           para_birimi=(para_birimi or "TRY").upper(), evrak_id=evrak_id, tarih=tarih)
    parent.wait_window(dlg)
    return dlg.sonuc
