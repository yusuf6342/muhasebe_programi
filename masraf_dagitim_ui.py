"""Satın Alma → Masraf Dağıtımı: liste + gider belgesini alış katmanlarına dağıtma kartı."""

from __future__ import annotations

import tkinter as tk
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from tkinter import messagebox, simpledialog, ttk

from satis_tema import ACIK_BG, BEYAZ, CIZGI, IKINCIL, LACIVERT, SARI, font, tk_buton, treeview_stil


def _para(tutar) -> str:
    from satin_alma_ui import _para as para

    return para(tutar)


def _tarih(d) -> str:
    from satin_alma_ui import _tarih as tarih

    return tarih(d)


def _tarih_oku(metin: str) -> date | None:
    metin = (metin or "").strip()
    if not metin:
        return None
    for bicim in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(metin, bicim).date()
        except ValueError:
            continue
    raise ValueError(f"Tarih anlaşılamadı: {metin} (gg.aa.yyyy)")


def _sayi(v) -> str:
    if v in (None, ""):
        return ""
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        return str(v)
    metin = f"{d.normalize():f}"
    return metin.replace(".", ",")


TABLO_STILI = "MasrafDagitim.Treeview"


def tablo_stili(tablo: ttk.Treeview) -> None:
    """Kolon başlıkları her temada okunur kalsın: Vista başlık zeminini boyamaz, bu yüzden beyaz yazı kullanılmaz."""
    from tkinter import font as tkfont

    treeview_stil(tablo)
    stil = ttk.Style(tablo)
    govde, baslik = font(9, root=tablo), font(10, "bold", tablo)
    satir_y = tkfont.Font(root=tablo, font=govde).metrics("linespace") + 10
    stil.configure(TABLO_STILI, font=govde, rowheight=max(24, satir_y), fieldbackground=BEYAZ, background=BEYAZ,
                   foreground=LACIVERT)
    stil.configure(f"{TABLO_STILI}.Heading", font=baslik, background=SARI, foreground=LACIVERT, relief="raised")
    stil.map(f"{TABLO_STILI}.Heading", background=[("active", SARI)], foreground=[("active", LACIVERT)])
    stil.map(TABLO_STILI, background=[("selected", LACIVERT)], foreground=[("selected", BEYAZ)])
    tablo.configure(style=TABLO_STILI, show="headings")


def _durum_etiketi(durum: str) -> str:
    return {"TASLAK": "Taslak", "ONAYLANDI": "Onaylandı", "İPTAL EDİLDİ": "İptal Edildi"}.get(durum, durum or "")


# ----------------------------------------------------------------- liste
def masraf_dagitimi_goster(app) -> None:
    from database.access import yetki_var
    from database.masraf_dagitim_service import DURUMLAR, MasrafDagitimService
    from satin_alma_ui import _liste_ust, pencere_ac, satin_alma_hub_goster

    kok = _liste_ust(
        app,
        "MASRAF DAĞITIMI",
        "Nakliye, yükleme vb. gider belgelerini alış maliyetine (stok / SMM) dağıtın",
        lambda: satin_alma_hub_goster(app),
    )
    filtre = tk.Frame(kok, bg=ACIK_BG)
    filtre.pack(fill="x", padx=16, pady=(8, 0))

    def etiket(metin):
        tk.Label(filtre, text=metin, bg=ACIK_BG, fg=LACIVERT, font=font(10, "bold", app)).pack(side="left", padx=(8, 2))

    etiket("Başlangıç")
    bas = ttk.Entry(filtre, width=11)
    bas.insert(0, date(date.today().year, 1, 1).strftime("%d.%m.%Y"))
    bas.pack(side="left")
    etiket("Bitiş")
    bit = ttk.Entry(filtre, width=11)
    bit.insert(0, date.today().strftime("%d.%m.%Y"))
    bit.pack(side="left")
    etiket("Kaynak belge")
    kaynak = ttk.Entry(filtre, width=16)
    kaynak.pack(side="left")
    etiket("Cari")
    tedarikciler = []
    try:
        from database.alis_siparisi_service import AlisSiparisiService

        tedarikciler = [(int(c.id), c.unvan) for c in AlisSiparisiService.aktif_tedarikcileri()]
    except Exception:  # noqa: BLE001
        tedarikciler = []
    cari = ttk.Combobox(filtre, values=["Tümü"] + [u for _i, u in tedarikciler], state="readonly", width=24)
    cari.set("Tümü")
    cari.pack(side="left")
    etiket("Durum")
    durum = ttk.Combobox(filtre, values=["Tümü"] + [_durum_etiketi(d) for d in DURUMLAR], state="readonly", width=13)
    durum.set("Tümü")
    durum.pack(side="left")

    cerceve = ttk.Frame(kok)
    cerceve.pack(fill="both", expand=True, padx=16, pady=8)
    kolonlar = ("no", "tarih", "tur", "kaynak", "tutar", "alis", "yontem", "durum", "kullanici")
    tablo = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
    treeview_stil(tablo)
    for k, b, w, a in (
        ("no", "Dağıtım No", 100, "w"),
        ("tarih", "Tarih", 90, "center"),
        ("tur", "Kaynak Türü", 190, "w"),
        ("kaynak", "Kaynak Belge", 130, "w"),
        ("tutar", "Dağıtılan Tutar", 120, "e"),
        ("alis", "Alış Belgesi", 90, "center"),
        ("yontem", "Yöntem", 150, "w"),
        ("durum", "Durum", 100, "center"),
        ("kullanici", "Kullanıcı", 130, "w"),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor=a)
    tablo.pack(side="left", fill="both", expand=True)
    ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview).pack(side="right", fill="y")

    kaynaklar: dict[str, tuple[str, int, str]] = {}

    def kaynak_ac():
        sec = tablo.selection()
        if not sec or sec[0] not in kaynaklar:
            messagebox.showinfo("Seçim", "Dağıtım seçin.", parent=app)
            return
        kaynak_belge_ac(app, *kaynaklar[sec[0]])

    def yenile():
        try:
            b1, b2 = _tarih_oku(bas.get()), _tarih_oku(bit.get())
        except ValueError as e:
            messagebox.showerror("Filtre", str(e), parent=app)
            return
        cari_id = next((i for i, u in tedarikciler if u == cari.get()), None)
        durum_kod = next((d for d in DURUMLAR if _durum_etiketi(d) == durum.get()), None)
        try:
            kayitlar = MasrafDagitimService.listele(
                baslangic=b1, bitis=b2, kaynak=kaynak.get(), cari_id=cari_id, durum=durum_kod
            )
        except (ValueError, PermissionError) as e:
            messagebox.showerror("Masraf Dağıtımı", str(e), parent=app)
            return
        tablo.delete(*tablo.get_children())
        kaynaklar.clear()
        for i, r in enumerate(kayitlar):
            kaynaklar[str(r["id"])] = (r["kaynak_turu_kod"], r["kaynak_id"], r["kaynak_no"])
            tablo.insert(
                "", "end", iid=str(r["id"]), tags=("tek" if i % 2 == 0 else "cift",),
                values=(r["dagitim_no"], _tarih(r["tarih"]), r["kaynak_turu"], r["kaynak_no"], _para(r["tutar"]),
                        r["alis_sayisi"], r["yontem"], _durum_etiketi(r["durum"]), r["kullanici"]),
            )

    def ac(dagitim_id=None):
        if dagitim_id is None and not yetki_var("alis_masraf_duzenleme", "alis_masraf_onay"):
            messagebox.showwarning(
                "Masraf Dağıtımı — yetki",
                "Yeni masraf dağıtımı oluşturma yetkiniz yok.\n"
                "Gerekli izin: Alış masraf düzenleme veya Alış masraf onay.",
                parent=app,
            )
            return
        dlg = pencere_ac(app, MasrafDagitimDialog, dagitim_id=dagitim_id, baslik="Masraf dağıtımı")
        if dlg is not None and dlg.winfo_exists():
            app.wait_window(dlg)
        yenile()

    def secili_ac(_e=None):
        sec = tablo.selection()
        if not sec:
            messagebox.showinfo("Seçim", "Dağıtım seçin.", parent=app)
            return
        ac(int(sec[0]))

    def eski():
        from satin_alma_ui import eski_fatura_masraflari_goster

        eski_fatura_masraflari_goster(app)

    alt = tk.Frame(kok, bg=ACIK_BG)
    alt.pack(fill="x", padx=16, pady=10)
    tk_buton(alt, "Yeni", lambda: ac(None), rol="yeni").pack(side="left")
    tk_buton(alt, "Aç", secili_ac, rol="duzenle").pack(side="left", padx=6)
    tk_buton(alt, "Kaynak Belgeyi Aç", kaynak_ac, rol="ara").pack(side="left", padx=6)
    tk_buton(alt, "Eski Fatura Masrafları", eski, rol="geri").pack(side="left", padx=6)
    tk_buton(alt, "Listele", yenile, rol="ara").pack(side="right")
    tablo.bind("<Double-1>", secili_ac)
    for w in (bas, bit, kaynak):
        w.bind("<Return>", lambda _e: yenile())
    cari.bind("<<ComboboxSelected>>", lambda _e: yenile())
    durum.bind("<<ComboboxSelected>>", lambda _e: yenile())
    yenile()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: masraf_dagitimi_goster(app))


# --------------------------------------------------------- pencere yardımcıları
def _grab_al(pencere) -> None:
    try:
        pencere.grab_set()
    except tk.TclError:
        pass


def _modal_bekle(parent, pencere) -> None:
    """Alt pencereyi bekler; üst pencerelerden birinde grab varsa kapanınca geri verir.

    Grab'lı bir kartın (ör. alış faturası) üstünde açılan grab'sız pencere tıklanamaz;
    bu yüzden alt pencere grab alır ve kapanınca önceki sahibine iade edilir.
    """
    if pencere is None:
        return
    try:
        onceki = parent.grab_current()
    except (tk.TclError, KeyError):
        onceki = None
    try:
        if pencere.winfo_exists():
            if onceki is not None:
                _grab_al(pencere)
            parent.wait_window(pencere)
    finally:
        try:
            if onceki is not None and onceki.winfo_exists():
                onceki.grab_set()
        except tk.TclError:
            pass


def alis_faturasi_ac(parent, fatura_id: int):
    from alis_ui import AlisFaturasiDialog
    from database.alis_faturasi_service import AlisFaturasiService

    fatura = AlisFaturasiService.getir(int(fatura_id))
    if not fatura:
        messagebox.showerror("Alış faturası", "Alış faturası bulunamadı.", parent=parent)
        return None
    pencere = AlisFaturasiDialog(parent, fatura=fatura)
    _modal_bekle(parent, pencere)
    return pencere


def kaynak_belge_ac(parent, kaynak_turu: str, kaynak_id: int, belge_no: str | None = None):
    from database.masraf_dagitim_service import KAYNAK_GIDER_FISI

    if kaynak_turu == KAYNAK_GIDER_FISI:
        from belge_onizleme_ui import gider_fisi_onizle

        if not belge_no:
            from database.finans_service import FinansService

            fis = FinansService.gider_fisi_getir(int(kaynak_id))
            belge_no = fis.belge_no if fis else ""
        try:
            onceki = parent.grab_current()
        except (tk.TclError, KeyError):
            onceki = None
        try:
            if not belge_no or not gider_fisi_onizle(parent, belge_no):
                messagebox.showerror("Gider fişi", "Gider fişi bulunamadı.", parent=parent)
        finally:
            if onceki is not None and onceki.winfo_exists():
                _grab_al(onceki)
        return None
    from hizmet_fatura_ui import HizmetFaturaDialog

    pencere = HizmetFaturaDialog(parent, fatura_id=int(kaynak_id))
    _modal_bekle(parent, pencere)
    return pencere


def dagitim_ac(parent, dagitim_id: int | None = None, kaynak: tuple[str, int] | None = None):
    pencere = MasrafDagitimDialog(parent, dagitim_id=dagitim_id, kaynak=kaynak)
    _modal_bekle(parent, pencere)
    return pencere


# --------------------------------------------------------- seçim pencereleri
class _SecimDialog(tk.Toplevel):
    """Arama kutulu tablo; çoklu seçimde işaretli satır id'lerini döndürür."""

    def __init__(self, parent, baslik, kolonlar, yukle, *, coklu=False, genislik=980, ek_butonlar=(),
                 hepsini_sec=False, aciklama: str | None = None):
        super().__init__(parent)
        self.title(baslik)
        self.configure(bg=ACIK_BG)
        self.transient(parent.winfo_toplevel())
        self.geometry(f"{genislik}x520")
        self.result = None
        self._yukle = yukle
        self._hepsini_sec = hepsini_sec
        self._arama_is = None
        ust = tk.Frame(self, bg=ACIK_BG)
        ust.pack(fill="x", padx=10, pady=8)
        tk.Label(ust, text="Ara:", bg=ACIK_BG, fg=LACIVERT).pack(side="left")
        self.arama = ttk.Entry(ust, width=40)
        self.arama.pack(side="left", padx=6)
        self.arama.bind("<KeyRelease>", lambda _e: self._arama_planla())
        self.adet_lbl = tk.Label(ust, text="", bg=ACIK_BG, fg=IKINCIL)
        self.adet_lbl.pack(side="left", padx=8)
        for metin, komut in ek_butonlar:
            tk_buton(ust, metin, lambda k=komut: k(self), rol="geri").pack(side="right", padx=4)
        if aciklama:
            tk.Label(self, text=aciklama, bg=ACIK_BG, fg=IKINCIL, justify="left", anchor="w",
                     wraplength=genislik - 40).pack(fill="x", padx=10)
        cerceve = ttk.Frame(self)
        cerceve.pack(fill="both", expand=True, padx=10)
        self.tablo = ttk.Treeview(
            cerceve, columns=[k for k, *_ in kolonlar], show="headings",
            selectmode="extended" if coklu else "browse",
        )
        treeview_stil(self.tablo)
        for k, b, w, a in kolonlar:
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=w, anchor=a)
        self.tablo.pack(side="left", fill="both", expand=True)
        ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview).pack(side="right", fill="y")
        alt = tk.Frame(self, bg=ACIK_BG)
        alt.pack(fill="x", padx=10, pady=8)
        tk_buton(alt, "Seç", self._sec, rol="kaydet").pack(side="right")
        tk_buton(alt, "Vazgeç", self.destroy, rol="geri").pack(side="right", padx=6)
        self.tablo.bind("<Double-1>", lambda _e: self._sec())
        self.tablo.bind("<Return>", lambda _e: self._sec())
        self._doldur()
        self.arama.focus_set()

    def _arama_planla(self):
        if self._arama_is is not None:
            self.after_cancel(self._arama_is)
        self._arama_is = self.after(300, self._doldur)

    def _doldur(self):
        self._arama_is = None
        self.tablo.delete(*self.tablo.get_children())
        try:
            kayitlar = list(self._yukle(self.arama.get()))
        except (ValueError, PermissionError) as e:
            messagebox.showerror(self.title(), str(e), parent=self)
            kayitlar = []
        for i, (iid, degerler) in enumerate(kayitlar):
            self.tablo.insert("", "end", iid=str(iid), values=degerler, tags=("tek" if i % 2 == 0 else "cift",))
        self.adet_lbl.configure(text=f"{len(kayitlar)} kayıt")
        if self._hepsini_sec and kayitlar:
            self.tablo.selection_set(self.tablo.get_children())

    def _sec(self):
        sec = self.tablo.selection()
        if not sec:
            return
        self.result = [int(x) if x.isdigit() else x for x in sec]
        self.destroy()


# ------------------------------------------------------------------ kart
class MasrafDagitimDialog(tk.Toplevel):
    """Kaynak gider belgesi seç → alış satırlarını seç → önizle → taslak / onay."""

    HEDEF_KOLONLARI = (
        ("fatura", "Alış Faturası", 110, "w"),
        ("kod", "Stok Kodu", 90, "w"),
        ("ad", "Stok Adı", 170, "w"),
        ("depo", "Depo", 90, "w"),
        ("birim", "Ana Birim", 70, "center"),
        ("miktar", "Ana Birim Mik.", 90, "e"),
        ("alis", "Alış Tutarı", 95, "e"),
        ("maliyet", "Mevcut Maliyet", 95, "e"),
        ("olcu", "Ölçü / Elle", 80, "e"),
        ("pay", "Dağıtılan Pay", 95, "e"),
        ("stok", "Stok Payı", 85, "e"),
        ("smm", "SMM Payı", 85, "e"),
        ("yeni", "Yeni Birim Maliyet", 110, "e"),
    )

    def __init__(self, parent, dagitim_id: int | None = None, kaynak: tuple[str, int] | None = None):
        super().__init__(parent)
        from database.access import yetki_var
        from database.masraf_dagitim_service import YONTEM_ETIKETLERI, YONTEMLER

        self.title("Masraf Dağıtımı")
        self.configure(bg=ACIK_BG)
        self.transient(parent.winfo_toplevel())
        ekran_g, ekran_y = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{min(1320, max(800, ekran_g - 40))}x{min(800, max(560, ekran_y - 100))}+10+10")
        self.minsize(800, 520)
        self.dagitim_id = dagitim_id
        self.row_version: int | None = None
        self.durum = "TASLAK"
        self.kaynak: dict | None = None
        self.kaynak_turu = "HIZMET_FATURASI"
        self.secili_kaynak: set[int] = set()
        self.hedefler: list[dict] = []
        self.onizleme: dict | None = None
        self._degisti = False
        self._yukleniyor = False
        self._yontem_kodlari = {YONTEM_ETIKETLERI[k]: k for k in YONTEMLER}
        self._yetki_taslak = yetki_var("alis_masraf_duzenleme", "alis_masraf_onay")
        self._yetki_onay = yetki_var("alis_masraf_onay")
        self._yetki_geri = yetki_var("alis_masraf_geri_al")

        # --- başlık
        bant = tk.Frame(self, bg=LACIVERT)
        bant.pack(fill="x")
        tk.Label(bant, text="MASRAF DAĞITIMI", bg=LACIVERT, fg=SARI, font=font(14, "bold", self)).pack(
            side="left", padx=16, pady=4
        )
        self.durum_lbl = tk.Label(bant, text="", bg=LACIVERT, fg=BEYAZ, font=font(12, "bold", self))
        self.durum_lbl.pack(side="right", padx=16)

        ust = tk.Frame(self, bg=ACIK_BG)
        ust.pack(fill="x", padx=12, pady=(8, 0))
        tk.Label(ust, text="Dağıtım No", bg=ACIK_BG, fg=LACIVERT).grid(row=0, column=0, sticky="w")
        self.no_lbl = tk.Label(ust, text="(yeni)", bg=ACIK_BG, fg=LACIVERT, font=font(11, "bold", self))
        self.no_lbl.grid(row=0, column=1, sticky="w", padx=(4, 16))
        tk.Label(ust, text="Tarih", bg=ACIK_BG, fg=LACIVERT).grid(row=0, column=2, sticky="w")
        self.tarih = ttk.Entry(ust, width=12)
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        self.tarih.grid(row=0, column=3, padx=(4, 16))
        tk.Label(ust, text="Yöntem", bg=ACIK_BG, fg=LACIVERT).grid(row=0, column=4, sticky="w")
        self.yontem = ttk.Combobox(ust, values=list(self._yontem_kodlari), state="readonly", width=22)
        self.yontem.set(YONTEM_ETIKETLERI["TUTAR"])
        self.yontem.grid(row=0, column=5, padx=(4, 16))
        tk.Label(ust, text="Dağıtılacak Tutar (TL)", bg=ACIK_BG, fg=LACIVERT).grid(row=0, column=6, sticky="w")
        self.tutar = ttk.Entry(ust, width=14, justify="right")
        self.tutar.grid(row=0, column=7, padx=(4, 16))
        tk.Label(ust, text="Açıklama", bg=ACIK_BG, fg=LACIVERT).grid(row=1, column=0, sticky="w", pady=4)
        self.aciklama = ttk.Entry(ust, width=90)
        self.aciklama.grid(row=1, column=1, columnspan=7, sticky="we", padx=4, pady=4)

        # --- özet + düğmeler: tablolardan önce alta yerleşir ki küçük pencerede / ölçekte kırpılmasın
        alt = tk.Frame(self, bg=ACIK_BG)
        alt.pack(side="bottom", fill="x", padx=12, pady=(0, 10))
        self.alt_cubuk = alt
        self._alt_satir1 = tk.Frame(alt, bg=ACIK_BG)
        self._alt_satir1.pack(fill="x")
        self._alt_satir2 = tk.Frame(alt, bg=ACIK_BG)
        self.onizle_btn = tk_buton(alt, "Dağıtımı Hesapla", self.onizle, rol="ara")
        self.taslak_btn = tk_buton(alt, "Taslağı Kaydet", self.taslak_kaydet, rol="duzenle")
        self.onay_btn = tk_buton(alt, "Onayla ve Uygula", self.onayla, rol="kaydet")
        self.kapat_btn = tk_buton(alt, "Kapat", self.kapat, rol="geri")
        self.geri_btn = tk_buton(alt, "Geri Al", self.geri_al, rol="iptal")
        self.iptal_btn = tk_buton(alt, "Taslağı İptal Et", self.taslak_iptal, rol="iptal")
        self.gecmis_btn = tk_buton(alt, "Geçmiş", self._gecmis_goster, rol="geri")
        for b in (self.onizle_btn, self.taslak_btn, self.onay_btn, self.kapat_btn, self.geri_btn, self.iptal_btn,
                  self.gecmis_btn):
            b.configure(pady=4)
        self.kapat_btn.pack(in_=self._alt_satir1, side="right")
        for b in (self.onizle_btn, self.taslak_btn, self.onay_btn):
            b.pack(in_=self._alt_satir1, side="left", padx=(0, 6))
        self._alt_tek_satir: bool | None = None
        alt.bind("<Configure>", self._alt_yerlesim)
        self._alt_yerlesim()
        self.ozet_lbl = tk.Label(self, text="", bg=BEYAZ, fg=LACIVERT, justify="left", anchor="w",
                                 font=font(9, root=self), highlightthickness=1, highlightbackground=CIZGI)
        self.ozet_lbl.pack(side="bottom", fill="x", padx=12, pady=(0, 6), ipady=2)
        self.ozet_lbl.bind("<Configure>", lambda e: self.ozet_lbl.configure(wraplength=max(200, e.width - 16)))

        # --- orta alan: yer daraldığında iki tablo da (grid ağırlığıyla) orantılı küçülür, biri kaybolmaz
        orta = tk.Frame(self, bg=ACIK_BG)
        orta.pack(fill="both", expand=True, padx=12)
        orta.columnconfigure(0, weight=1)
        orta.rowconfigure(0, weight=1)
        orta.rowconfigure(1, weight=3)

        # --- kaynak
        kutu1 = tk.LabelFrame(orta, text=" 1) Kaynak masraf belgesi (nakliye gider fişi / hizmet faturası) ",
                              bg=ACIK_BG, fg=LACIVERT, font=font(10, "bold", self))
        kutu1.grid(row=0, column=0, sticky="nsew", pady=(6, 3))
        ks = tk.Frame(kutu1, bg=ACIK_BG)
        ks.pack(fill="x", padx=6, pady=4)
        self.kaynak_btn = tk_buton(ks, "Kaynak Belge Seç…", self._kaynak_sec_dialog, rol="ara")
        self.kaynak_btn.pack(side="left")
        tk_buton(ks, "Kaynak Belgeyi Aç", self.kaynak_belgeyi_ac, rol="geri").pack(side="left", padx=6)
        self.kaynak_lbl = tk.Label(ks, text="Kaynak seçilmedi.", bg=ACIK_BG, fg=IKINCIL, font=font(10, root=self))
        self.kaynak_lbl.pack(side="left", padx=10)
        self.kural_lbl = tk.Label(kutu1, text="", bg=ACIK_BG, fg=IKINCIL, font=font(9, root=self), anchor="w",
                                  justify="left")
        self.kural_lbl.pack(fill="x", padx=8)
        self.kaynak_tablo = ttk.Treeview(
            kutu1, columns=("sec", "kod", "ad", "tutar", "dagitilan", "kalan", "uygun"), show="headings", height=3
        )
        tablo_stili(self.kaynak_tablo)
        for k, b, w, a in (
            ("sec", "Seç", 50, "center"), ("kod", "Kod", 110, "w"), ("ad", "Gider Satırı", 300, "w"),
            ("tutar", "KDV Hariç Tutar", 120, "e"), ("dagitilan", "Önceki Dağıtım", 120, "e"),
            ("kalan", "Kalan", 110, "e"), ("uygun", "Maliyete Uygun", 110, "center"),
        ):
            self.kaynak_tablo.heading(k, text=b)
            self.kaynak_tablo.column(k, width=w, anchor=a)
        self.kaynak_tablo.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.kaynak_tablo.bind("<Button-1>", self._kaynak_tikla)

        # --- hedefler
        kutu2 = tk.LabelFrame(orta, text=" 2) Masrafın yükleneceği alış satırları ", bg=ACIK_BG, fg=LACIVERT,
                              font=font(10, "bold", self))
        kutu2.grid(row=1, column=0, sticky="nsew", pady=(3, 6))
        hs = tk.Frame(kutu2, bg=ACIK_BG)
        hs.pack(fill="x", padx=6, pady=4)
        self.fatura_btn = tk_buton(hs, "Alış Faturası Seç…", self._alis_faturasi_sec_dialog, rol="ara")
        self.fatura_btn.pack(side="left")
        self.hedef_btn = tk_buton(hs, "Alış Satırı Ekle…", self._hedef_sec_dialog, rol="ara")
        self.hedef_btn.pack(side="left", padx=6)
        self.hedef_sil_btn = tk_buton(hs, "Satırı Çıkar", self._hedef_cikar, rol="iptal")
        self.hedef_sil_btn.pack(side="left")
        tk_buton(hs, "Alış Faturasını Aç", self.alis_faturasini_ac, rol="geri").pack(side="left", padx=6)
        tk.Label(hs, text="Ağırlık/hacim/elle yönteminde değeri girmek için 'Ölçü / Elle' hücresine çift tıklayın.",
                 bg=ACIK_BG, fg=IKINCIL).pack(side="left", padx=10)
        cerceve = ttk.Frame(kutu2)
        cerceve.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.hedef_tablo = ttk.Treeview(
            cerceve, columns=[k for k, *_ in self.HEDEF_KOLONLARI], show="headings", selectmode="browse", height=4
        )
        tablo_stili(self.hedef_tablo)
        for k, b, w, a in self.HEDEF_KOLONLARI:
            self.hedef_tablo.heading(k, text=b)
            self.hedef_tablo.column(k, width=w, anchor=a)
        dikey = ttk.Scrollbar(cerceve, orient="vertical", command=self.hedef_tablo.yview)
        yatay = ttk.Scrollbar(cerceve, orient="horizontal", command=self.hedef_tablo.xview)
        self.hedef_tablo.configure(yscrollcommand=dikey.set, xscrollcommand=yatay.set)
        yatay.pack(side="bottom", fill="x")
        dikey.pack(side="right", fill="y")
        self.hedef_tablo.pack(side="left", fill="both", expand=True)
        self.hedef_tablo.bind("<Double-1>", self._olcu_duzenle)
        for cubuk in (ks, hs):
            for w in cubuk.winfo_children():
                if isinstance(w, tk.Button):
                    w.configure(font=font(10, "bold", self), padx=10, pady=3)
        # Yer daraldığında alış tablosu en az başlık + 2 satır, kaynak tablosu başlık + 1 satır gösterir
        self.update_idletasks()
        satir_y = int(ttk.Style(self).lookup(TABLO_STILI, "rowheight") or 24)
        orta.rowconfigure(0, minsize=ks.winfo_reqheight() + self.kural_lbl.winfo_reqheight() + 2 * satir_y + 40)
        orta.rowconfigure(1, minsize=hs.winfo_reqheight() + yatay.winfo_reqheight() + 3 * satir_y + 34)

        for w in (self.tarih, self.tutar, self.aciklama):
            w.bind("<KeyRelease>", lambda _e: self._degisiklik())
        self.yontem.bind("<<ComboboxSelected>>", lambda _e: self._degisiklik())
        self.protocol("WM_DELETE_WINDOW", self.kapat)

        if dagitim_id:
            self._yukle(dagitim_id)
        elif kaynak:
            self.kaynak_ayarla(int(kaynak[1]), tur=kaynak[0])
        self._durum_uygula()

    def _alt_yerlesim(self, _e=None):
        """İkincil düğmeler genişlik yetiyorsa ana satıra, yetmiyorsa ikinci satıra akar (hiçbiri kırpılmaz)."""
        ikincil = (self.geri_btn, self.iptal_btn, self.gecmis_btn)
        gerekli = sum(b.winfo_reqwidth() + 6 for b in (self.onizle_btn, self.taslak_btn, self.onay_btn, *ikincil))
        gerekli += self.kapat_btn.winfo_reqwidth() + 12
        tek = self.alt_cubuk.winfo_width() >= gerekli
        if tek == self._alt_tek_satir:
            return
        self._alt_tek_satir = tek
        for b in ikincil:
            b.pack_forget()
        hedef = self._alt_satir1 if tek else self._alt_satir2
        for b in ikincil:
            b.pack(in_=hedef, side="left", padx=(0, 6))
        if tek:
            self._alt_satir2.pack_forget()
        else:
            self._alt_satir2.pack(fill="x", pady=(4, 0))

    # -------------------------------------------------------------- durum
    def _salt_okunur(self) -> bool:
        return self.durum != "TASLAK" or not self._yetki_taslak

    def _durum_uygula(self):
        salt = self._salt_okunur()
        durum_str = "disabled" if salt else "normal"
        for w in (self.tarih, self.tutar, self.aciklama):
            w.configure(state=durum_str)
        self.yontem.configure(state="disabled" if salt else "readonly")
        for b in (self.kaynak_btn, self.fatura_btn, self.hedef_btn, self.hedef_sil_btn, self.onizle_btn,
                  self.taslak_btn):
            b.configure(state=durum_str)
        self.onay_btn.configure(state="normal" if self.durum == "TASLAK" and self._yetki_onay else "disabled")
        self.geri_btn.configure(state="normal" if self.durum == "ONAYLANDI" and self._yetki_geri else "disabled")
        self.iptal_btn.configure(
            state="normal" if self.durum == "TASLAK" and self.dagitim_id and self._yetki_taslak else "disabled"
        )
        metin = _durum_etiketi(self.durum).upper()
        if self.durum == "ONAYLANDI":
            metin += "  —  SALT OKUNUR (değişiklik için Geri Al, ardından yeniden dağıtın)"
        elif self.durum != "TASLAK":
            metin += "  —  SALT OKUNUR"
        elif not self._yetki_taslak:
            metin += "  —  SALT OKUNUR (düzenleme yetkiniz yok)"
        self.durum_lbl.configure(text=metin)

    def _degisiklik(self):
        if self._yukleniyor:
            return
        self._degisti = True
        if self.durum == "TASLAK":
            for h in self.hedefler:
                h["_sonuc"] = None
        if self.onizleme is not None:
            self.onizleme = None
            self.ozet_lbl.configure(text="Değişiklik yapıldı; önizleme geçersiz. Yeniden 'Dağıtımı Hesapla'ya basın.",
                                    fg=LACIVERT)
        self._hedefleri_ciz()

    # --------------------------------------------------------------- yükle
    def _yukle(self, dagitim_id: int):
        from database.masraf_dagitim_service import YONTEM_ETIKETLERI, MasrafDagitimService

        d = MasrafDagitimService.getir(dagitim_id)
        self._yukleniyor = True
        try:
            self.dagitim_id = int(d["id"])
            self.row_version = int(d["row_version"] or 1)
            self.durum = d["durum"]
            self.no_lbl.configure(text=d["dagitim_no"])
            self.tarih.delete(0, "end")
            self.tarih.insert(0, _tarih(d["dagitim_tarihi"]))
            self.yontem.set(YONTEM_ETIKETLERI.get(d["yontem"], d["yontem"]))
            self.tutar.delete(0, "end")
            self.tutar.insert(0, _sayi(d["tutar"]))
            self.aciklama.delete(0, "end")
            self.aciklama.insert(0, d.get("aciklama") or "")
            try:
                self._kaynak_yukle(int(d["kaynak_id"]), tur=d["kaynak_turu"], secili=set(d["kaynak_satir_idler"]),
                                   tutar_ayarla=False)
            except ValueError:
                self.kaynak_turu = d["kaynak_turu"]
                self.kaynak = {"id": int(d["kaynak_id"]), "tur": d["kaynak_turu"], "no": d["kaynak_no"],
                               "satirlar": []}
                self.secili_kaynak = set(d["kaynak_satir_idler"])
                self.kaynak_lbl.configure(text=f"{d['kaynak_no']} — kaynak belge bulunamadı (silinmiş).", fg="#B83B3B")
                self._kaynak_ciz()
            self.hedefler = [
                {
                    "satir_id": s["alis_fatura_satiri_id"], "fatura_id": s["alis_fatura_id"],
                    "fatura_no": s["alis_fatura_no"], "urun_kodu": s["urun_kodu"],
                    "urun_adi": s["urun_adi"], "depo": s["depo"], "birim": s["birim"], "ana_miktar": s["ana_miktar"],
                    "alis_tutari": s["alis_tutari"], "birim_maliyet": s["eski_birim_maliyet"],
                    "olcu": s["olcu"], "elle_tutar": s["elle_tutar"],
                    "_sonuc": s,
                }
                for s in d["satirlar"]
            ]
            self._hedefleri_ciz()
            if d["durum"] != "TASLAK":
                self.ozet_lbl.configure(text=self._ozet_metni(d, d.get("geri_alma_nedeni")))
            else:
                self.ozet_lbl.configure(
                    text="Kayıtlı taslak (maliyet değişmedi) — " + self._ozet_metni(d),
                    fg=LACIVERT,
                )
        finally:
            self._yukleniyor = False
        self._degisti = False

    def _ozet_metni(self, d: dict, not_=None) -> str:
        metin = (
            f"Dağıtılan: {_para(d.get('tutar'))} TL   |   Stoka: {_para(d.get('stok_payi'))} TL   |   "
            f"SMM'ye: {_para(d.get('smm_payi'))} TL   |   İade edilen kısım (giderde kalır): {_para(d.get('iade_payi'))} TL"
        )
        if d.get("kaynak_toplam") is not None:
            metin += (
                f"\nKaynak belge toplamı: {_para(d['kaynak_toplam'])} TL   |   Daha önce dağıtılan: "
                f"{_para(d['kaynak_onceki'])} TL   |   Bu dağıtım: {_para(d.get('tutar'))} TL   |   "
                f"Dağıtım sonrası kalan: {_para(d['kaynak_kalan_sonra'])} TL"
            )
        if d.get("onaylayan"):
            metin += f"\nOnaylayan: {d['onaylayan']} ({_tarih(d.get('onay_tarihi'))})"
        if d.get("fis_id"):
            metin += f"   |   Muhasebe fişi id: {d['fis_id']}"
        if d.get("ters_fis_id"):
            metin += f"   |   Ters fiş id: {d['ters_fis_id']}"
        if not_:
            metin += f"\nNeden: {not_}"
        return metin

    # -------------------------------------------------------------- kaynak
    def _kaynak_sec_dialog(self):
        from database.masraf_dagitim_service import MasrafDagitimService

        belgeler: dict[str, dict] = {}

        def yukle(arama):
            belgeler.clear()
            for b in MasrafDagitimService.kaynak_belgeler(arama):
                anahtar = f"{b['tur']}:{b['id']}"
                belgeler[anahtar] = b
                yield anahtar, (b["tur_etiket"], b["no"], _tarih(b["tarih"]), b["cari"], b["aciklama"],
                                b["para_birimi"], _para(b["genel_toplam"]), _para(b["toplam"]),
                                _para(b["uygun_tutar"]), _para(b["onceki_dagitim"]), _para(b["kalan"]))

        dlg = _SecimDialog(
            self, "Kaynak masraf belgesi seç (nakliye gider fişi / hizmet alış faturası)",
            (("tur", "Belge Türü", 160, "w"), ("no", "Belge No", 115, "w"), ("tarih", "Tarih", 85, "center"),
             ("cari", "Cari / Kasa-Banka", 170, "w"), ("aciklama", "Açıklama", 170, "w"), ("pb", "Döviz", 45, "center"),
             ("genel", "Belge Tutarı", 95, "e"), ("toplam", "Dağıtılabilir", 95, "e"),
             ("uygun", "Maliyete Uygun", 95, "e"), ("onceki", "Önceki Dağıtım", 95, "e"), ("kalan", "Kalan", 90, "e")),
            lambda a: list(yukle(a)), genislik=1320,
            ek_butonlar=(("Listede Görünmeyenler…", self._gorunmeyenleri_goster),),
            aciklama="Belge no, tarih (gg.aa.yyyy), cari / kasa adı, hizmet adı veya tutarla arayın. "
                     "Belge Tutarı KDV dahil, Dağıtılabilir KDV hariç tutardır (gider fişinde KDV ayrı kaydedilmez). "
                     "Nakliyecinin ürün tedarikçisinden farklı olması bağlantıyı engellemez.",
        )
        _modal_bekle(self, dlg)
        if dlg.result:
            tur, kid = str(dlg.result[0]).split(":")
            self.kaynak_ayarla(int(kid), tur=tur)

    def _gorunmeyenleri_goster(self, secim_penceresi):
        from database.masraf_dagitim_service import MasrafDagitimService

        kayitlar = MasrafDagitimService.kaynak_gorunmeyenler(secim_penceresi.arama.get())
        satirlar = [f"{k['tur_etiket']}  {k['no']}  {_tarih(k['tarih'])}  {k['cari']}  {_para(k['tutar'])} TL\n"
                    f"    → {k['neden']}" for k in kayitlar[:40]]
        if len(kayitlar) > 40:
            satirlar.append(f"… ve {len(kayitlar) - 40} kayıt daha (aramayı daraltın).")
        satirlar.append(
            "\nNot: Yalnızca açık firmanın evrakları listelenir. Ürün alış faturasının içine satır olarak "
            "yazılan nakliye veya alış faturasına eklenmiş eski usul masraflar (Eski Fatura Masrafları) "
            "burada kaynak belge olarak çıkmaz."
        )
        messagebox.showinfo("Listede görünmeyen masraf evrakları", "\n".join(satirlar), parent=secim_penceresi)

    def kaynak_ayarla(self, kaynak_id: int, tur: str = "HIZMET_FATURASI"):
        self._kaynak_yukle(int(kaynak_id), tur=tur, secili=None, tutar_ayarla=True)
        self._degisiklik()

    def _kaynak_yukle(self, kaynak_id: int, *, tur: str = "HIZMET_FATURASI", secili: set[int] | None,
                      tutar_ayarla: bool):
        from database.masraf_dagitim_service import KAYNAK_GIDER_FISI, MasrafDagitimService

        self.kaynak = MasrafDagitimService.kaynak_detay(kaynak_id, self.dagitim_id, tur=tur)
        self.kaynak_turu = self.kaynak["tur"]
        if secili is None:
            gider_fisi = self.kaynak_turu == KAYNAK_GIDER_FISI
            secili = {s["id"] for s in self.kaynak["satirlar"] if (s["uygun"] or gider_fisi) and s["kalan"] > 0}
        self.secili_kaynak = set(secili)
        k = self.kaynak
        self.kaynak_lbl.configure(
            text=f"{k['tur_etiket']}  |  {k['no']}  |  {_tarih(k['tarih'])}  |  {k['cari']}  |  {k['para_birimi']}"
            + (f" (kur {_sayi(k['kur'])})" if k["para_birimi"] != "TRY" else "")
            + f"  |  Toplam {_para(k['toplam'])}  Dağıtılan {_para(k['dagitilan'])}  Kalan {_para(k['kalan'])} TL",
            fg=LACIVERT,
        )
        self.kural_lbl.configure(text=k.get("kural") or "")
        self._kaynak_ciz()
        if tutar_ayarla:
            self._tutari_secimden_ayarla()

    def kaynak_belgeyi_ac(self):
        if not self.kaynak:
            messagebox.showinfo("Kaynak belge", "Önce kaynak masraf belgesini seçin.", parent=self)
            return
        kaynak_belge_ac(self, self.kaynak_turu, self.kaynak["id"], self.kaynak.get("no"))
        if self.durum == "TASLAK" and self.kaynak.get("satirlar"):
            try:
                self._kaynak_yukle(self.kaynak["id"], tur=self.kaynak_turu, secili=self.secili_kaynak,
                                   tutar_ayarla=False)
            except ValueError:
                pass

    def _kaynak_ciz(self):
        self.kaynak_tablo.delete(*self.kaynak_tablo.get_children())
        for s in (self.kaynak or {}).get("satirlar", []):
            self.kaynak_tablo.insert(
                "", "end", iid=str(s["id"]),
                values=("☑" if s["id"] in self.secili_kaynak else "☐", s["kod"], s["ad"], _para(s["tutar"]),
                        _para(s["dagitilan"]), _para(s["kalan"]), "Evet" if s["uygun"] else "Hayır"),
            )

    def _tutari_secimden_ayarla(self):
        toplam = sum((s["kalan"] for s in self.kaynak["satirlar"] if s["id"] in self.secili_kaynak), Decimal("0"))
        self.tutar.configure(state="normal")
        self.tutar.delete(0, "end")
        self.tutar.insert(0, _sayi(toplam))

    def _kaynak_tikla(self, event):
        if self._salt_okunur() or self.kaynak_tablo.identify_column(event.x) != "#1":
            return
        iid = self.kaynak_tablo.identify_row(event.y)
        if iid:
            self.kaynak_satir_degistir(int(iid))
            return "break"

    def kaynak_satir_degistir(self, satir_id: int):
        s = next((x for x in self.kaynak["satirlar"] if x["id"] == satir_id), None)
        if s is None:
            return
        if satir_id in self.secili_kaynak:
            self.secili_kaynak.discard(satir_id)
        else:
            if not s["uygun"] and not messagebox.askyesno(
                "Uygunluk",
                f"'{s['ad']}' satırı otomatik olarak maliyete uygun görülmüyor (ör. satış teslimatı, kira).\n"
                "Yine de maliyete dağıtmak istiyor musunuz?",
                parent=self,
            ):
                return
            self.secili_kaynak.add(satir_id)
        self._kaynak_ciz()
        self._tutari_secimden_ayarla()
        self._degisiklik()

    # ------------------------------------------------------------ hedefler
    def _alis_faturasi_sec_dialog(self):
        from database.masraf_dagitim_service import MasrafDagitimService

        def yukle(arama):
            for f in MasrafDagitimService.hedef_faturalar(arama):
                yield f["fatura_id"], (f["fatura_no"], f["tedarikci_fatura_no"], _tarih(f["tarih"]), f["tedarikci"],
                                       f["depo"], f["satir_sayisi"], _para(f["matrah"]), _para(f["dagitilan"]))

        dlg = _SecimDialog(
            self, "Masrafın bağlanacağı ürün alış faturasını seç",
            (("no", "Alış Faturası", 120, "w"), ("tno", "Tedarikçi Fat. No", 120, "w"), ("tarih", "Tarih", 85, "center"),
             ("ted", "Tedarikçi", 220, "w"), ("depo", "Depo", 100, "w"), ("satir", "Satır", 50, "center"),
             ("matrah", "KDV Hariç Tutar", 110, "e"), ("dagitilan", "Önceki Masraf", 100, "e")),
            lambda a: list(yukle(a)), genislik=1000,
            aciklama="Fatura no, tedarikçi, tarih veya ürünle arayın. Tedarikçinin nakliyeciden farklı olması sorun değildir.",
        )
        _modal_bekle(self, dlg)
        if dlg.result:
            self._hedef_sec_dialog(fatura_id=int(dlg.result[0]))

    def _hedef_sec_dialog(self, fatura_id: int | None = None):
        from database.masraf_dagitim_service import MasrafDagitimService

        adaylar: dict[int, dict] = {}

        def yukle(arama):
            adaylar.clear()
            mevcut = {h["satir_id"] for h in self.hedefler}
            for h in MasrafDagitimService.hedef_satirlar(arama, fatura_id=fatura_id):
                if h["satir_id"] in mevcut:
                    continue
                adaylar[h["satir_id"]] = h
                yield h["satir_id"], (h["fatura_no"], _tarih(h["tarih"]), h["tedarikci"], h["urun_kodu"],
                                      h["urun_adi"], h["depo"], h["birim"], _sayi(h["ana_miktar"]),
                                      _para(h["alis_tutari"]), _sayi(h["birim_maliyet"]), _sayi(h["kalan"]),
                                      _para(h["dagitilan"]))

        dlg = _SecimDialog(
            self, "Masraf yüklenecek alış satırlarını seç (Ctrl/Shift ile çoklu)",
            (("fatura", "Alış Faturası", 110, "w"), ("tarih", "Tarih", 85, "center"),
             ("ted", "Tedarikçi", 150, "w"), ("kod", "Stok Kodu", 90, "w"), ("ad", "Stok Adı", 180, "w"),
             ("depo", "Depo", 90, "w"), ("birim", "Birim", 60, "center"), ("miktar", "Ana Mik.", 70, "e"),
             ("alis", "Alış Tutarı", 95, "e"), ("maliyet", "Birim Maliyet", 90, "e"), ("kalan", "Stokta", 70, "e"),
             ("onceki", "Önceki Masraf", 90, "e")),
            lambda a: list(yukle(a)), coklu=True, genislik=1290, hepsini_sec=fatura_id is not None,
        )
        _modal_bekle(self, dlg)
        if dlg.result:
            self.hedef_ekle([adaylar[i] for i in dlg.result if i in adaylar])

    def alis_faturasini_ac(self):
        sec = self.hedef_tablo.selection()
        h = next((x for x in self.hedefler if str(x["satir_id"]) == (sec[0] if sec else "")), None)
        if h is None and self.hedefler:
            h = self.hedefler[0]
        if h is None or not h.get("fatura_id"):
            messagebox.showinfo("Alış faturası", "Önce bir alış satırı seçin.", parent=self)
            return
        alis_faturasi_ac(self, int(h["fatura_id"]))

    def hedef_ekle(self, satirlar: list[dict]):
        mevcut = {h["satir_id"] for h in self.hedefler}
        for h in satirlar:
            if h["satir_id"] in mevcut:
                continue
            self.hedefler.append({**h, "olcu": h.get("agirlik"), "elle_tutar": None, "_sonuc": None})
        self._hedefleri_ciz()
        self._degisiklik()

    def _hedef_cikar(self):
        sec = self.hedef_tablo.selection()
        if not sec:
            return
        self.hedefler = [h for h in self.hedefler if str(h["satir_id"]) != sec[0]]
        self._hedefleri_ciz()
        self._degisiklik()

    def _yontem_kodu(self) -> str:
        return self._yontem_kodlari.get(self.yontem.get(), "TUTAR")

    def _olcu_duzenle(self, event):
        if self._salt_okunur():
            return
        iid = self.hedef_tablo.identify_row(event.y)
        if not iid:
            return
        yontem = self._yontem_kodu()
        if yontem not in ("AGIRLIK", "HACIM", "ELLE"):
            messagebox.showinfo("Ölçü", "Ölçü / elle tutar yalnızca ağırlık, hacim veya elle yönteminde girilir.",
                                parent=self)
            return
        h = next(x for x in self.hedefler if str(x["satir_id"]) == iid)
        alan = "elle_tutar" if yontem == "ELLE" else "olcu"
        baslik = {"ELLE": "Bu satıra dağıtılacak tutar (TL)", "AGIRLIK": "Birim ağırlık (kg / ana birim)",
                  "HACIM": "Birim hacim (m³ / ana birim)"}[yontem]
        metin = simpledialog.askstring("Değer", baslik, initialvalue=_sayi(h.get(alan)), parent=self)
        if metin is None:
            return
        self.hedef_deger_ayarla(int(iid), metin)

    def hedef_deger_ayarla(self, satir_id: int, metin: str):
        alan = "elle_tutar" if self._yontem_kodu() == "ELLE" else "olcu"
        h = next(x for x in self.hedefler if x["satir_id"] == satir_id)
        metin = (metin or "").strip().replace(",", ".")
        h[alan] = Decimal(metin) if metin else None
        self._degisiklik()
        self._hedefleri_ciz()

    def _hedefleri_ciz(self):
        yontem = self._yontem_kodu()
        sonuclar = {}
        if self.onizleme is not None:
            sonuclar = {s["alis_fatura_satiri_id"]: s for s in self.onizleme["satirlar"]}
        self.hedef_tablo.delete(*self.hedef_tablo.get_children())
        for i, h in enumerate(self.hedefler):
            s = sonuclar.get(h["satir_id"]) or h.get("_sonuc")
            olcu = h.get("elle_tutar") if yontem == "ELLE" else h.get("olcu")
            self.hedef_tablo.insert(
                "", "end", iid=str(h["satir_id"]), tags=("tek" if i % 2 == 0 else "cift",),
                values=(h["fatura_no"], h["urun_kodu"], h["urun_adi"], h["depo"], h["birim"], _sayi(h["ana_miktar"]),
                        _para(h["alis_tutari"]), _sayi(h["birim_maliyet"]), _sayi(olcu),
                        _para(s["pay"]) if s else "", _para(s["stok_payi"]) if s else "",
                        _para(s["smm_payi"]) if s else "", _sayi(s["yeni_birim_maliyet"]) if s else ""),
            )

    # ------------------------------------------------------------- işlemler
    def _veri(self) -> dict:
        if not self.kaynak:
            raise ValueError("Önce kaynak gider belgesini seçin.")
        return {
            "dagitim_tarihi": _tarih_oku(self.tarih.get()) or date.today(),
            "kaynak_turu": self.kaynak_turu,
            "kaynak_id": self.kaynak["id"],
            "kaynak_satir_idler": sorted(self.secili_kaynak),
            "tutar": self.tutar.get(),
            "yontem": self._yontem_kodu(),
            "aciklama": self.aciklama.get(),
            "hedefler": [
                {"satir_id": h["satir_id"], "olcu": h.get("olcu"), "elle_tutar": h.get("elle_tutar")}
                for h in self.hedefler
            ],
        }

    def onizle(self) -> bool:
        from database.masraf_dagitim_service import MasrafDagitimService

        try:
            self.onizleme = MasrafDagitimService.onizle(self._veri(), self.dagitim_id)
        except (ValueError, PermissionError) as e:
            self.onizleme = None
            self._hedefleri_ciz()
            messagebox.showerror("Önizleme", str(e), parent=self)
            return False
        self._hedefleri_ciz()
        o = self.onizleme
        metin = self._ozet_metni(o)
        if o["engeller"]:
            metin += "\nONAY ENGELİ:\n- " + "\n- ".join(o["engeller"])
        if o["uyarilar"]:
            metin += "\nUyarı:\n- " + "\n- ".join(o["uyarilar"])
        self.ozet_lbl.configure(text=metin, fg="#B83B3B" if o["engeller"] else LACIVERT)
        return True

    def taslak_kaydet(self, *, sessiz: bool = False) -> bool:
        from database.masraf_dagitim_service import MasrafDagitimService

        if self.onizleme is None and not self.onizle():
            return False
        veri = self._veri()
        inceleme = self.onizleme.get("mukerrer_inceleme") or []
        if inceleme:
            if not messagebox.askyesno(
                "İnceleme gerekli",
                "Aynı alış satırında kaynak belgesi olmayan eski masraf kaydı var:\n- " + "\n- ".join(inceleme)
                + "\n\nBu masrafın o kayıttan FARKLI olduğunu doğruladınız mı?",
                parent=self,
            ):
                return False
            veri["mukerrer_inceleme_onay"] = True
        try:
            self.dagitim_id = MasrafDagitimService.taslak_kaydet(veri, self.dagitim_id, self.row_version)
        except (ValueError, PermissionError) as e:
            messagebox.showerror("Taslak", str(e), parent=self)
            return False
        d = MasrafDagitimService.getir(self.dagitim_id)
        self.row_version = int(d["row_version"] or 1)
        self.no_lbl.configure(text=d["dagitim_no"])
        self._degisti = False
        self._durum_uygula()
        if not sessiz:
            messagebox.showinfo("Taslak", f"{d['dagitim_no']} taslak olarak kaydedildi. Stok ve muhasebe değişmedi.",
                                parent=self)
        return True

    def onayla(self) -> bool:
        from database.masraf_dagitim_service import MasrafDagitimService, ZatenIslendi

        if self.onizleme is None and not self.onizle():
            return False
        if self.onizleme["engeller"]:
            messagebox.showerror("Onay", "Onay engellendi:\n- " + "\n- ".join(self.onizleme["engeller"]), parent=self)
            return False
        o = self.onizleme
        if not messagebox.askyesno(
            "Onay",
            f"{_para(o['tutar'])} TL maliyete aktarılacak.\nStoka: {_para(o['stok_payi'])} TL, "
            f"SMM'ye: {_para(o['smm_payi'])} TL.\n\nOnaylıyor musunuz?",
            parent=self,
        ):
            return False
        if (self._degisti or not self.dagitim_id) and not self.taslak_kaydet(sessiz=True):
            return False
        try:
            sonuc = MasrafDagitimService.onayla(self.dagitim_id, self.row_version)
        except ZatenIslendi as e:
            messagebox.showinfo("Onay", str(e), parent=self)
            self._yukle(self.dagitim_id)
            self._durum_uygula()
            return False
        except (ValueError, PermissionError) as e:
            messagebox.showerror("Onay", str(e), parent=self)
            return False
        self._yukle(self.dagitim_id)
        self._durum_uygula()
        mesaj = f"{sonuc['dagitim_no']} onaylandı."
        if sonuc["uyarilar"]:
            mesaj += "\n\n" + "\n".join(sonuc["uyarilar"])
        messagebox.showinfo("Onay", mesaj, parent=self)
        return True

    def geri_al(self, neden: str | None = None) -> bool:
        from database.masraf_dagitim_service import MasrafDagitimService

        if not self.dagitim_id:
            return False
        if neden is None:
            neden = simpledialog.askstring("Geri Al", "Geri alma nedeni:", parent=self)
            if not neden:
                return False
        try:
            yapildi = MasrafDagitimService.geri_al(self.dagitim_id, neden)
        except (ValueError, PermissionError) as e:
            messagebox.showerror("Geri Al", str(e), parent=self)
            return False
        self._yukle(self.dagitim_id)
        self._durum_uygula()
        messagebox.showinfo(
            "Geri Al", "Dağıtım geri alındı; maliyet ve muhasebe etkisi ters kayıtla kaldırıldı." if yapildi
            else "Dağıtım zaten geri alınmış; ek işlem yapılmadı.", parent=self,
        )
        return yapildi

    def taslak_iptal(self):
        from database.masraf_dagitim_service import MasrafDagitimService

        if not self.dagitim_id or not messagebox.askyesno("İptal", "Taslak iptal edilsin mi?", parent=self):
            return
        try:
            MasrafDagitimService.iptal_et(self.dagitim_id, "Taslak iptal")
        except (ValueError, PermissionError) as e:
            messagebox.showerror("İptal", str(e), parent=self)
            return
        self._yukle(self.dagitim_id)
        self._durum_uygula()

    def _gecmis_goster(self):
        from database.masraf_dagitim_service import MasrafDagitimService

        if not self.dagitim_id:
            messagebox.showinfo("Geçmiş", "Kayıt henüz oluşturulmadı.", parent=self)
            return
        g = MasrafDagitimService.getir(self.dagitim_id)["gecmis"]
        satirlar = [f"{_tarih(x['tarih'])} {x['tarih']:%H:%M}  {x['islem']}  ({x['kullanici'] or '-'})"
                    + (f"\n    {x['detay']}" if x["detay"] else "") for x in g]
        messagebox.showinfo("İşlem geçmişi", "\n".join(satirlar) or "Kayıt yok.", parent=self)

    def kapat(self):
        if self._degisti and not self._salt_okunur():
            cevap = messagebox.askyesnocancel(
                "Kaydedilmemiş değişiklik", "Değişiklikler kaydedilmedi. Taslak olarak kaydedilsin mi?", parent=self
            )
            if cevap is None:
                return
            if cevap and not self.taslak_kaydet(sessiz=True):
                return
        self.destroy()


class BagliMasraflarDialog(tk.Toplevel):
    """İki yönlü erişim: alış faturasından bağlı masraflar / masraf belgesinden bağlı alış faturaları."""

    def __init__(self, parent, *, alis_fatura_id: int | None = None, kaynak_id: int | None = None,
                 kaynak_turu: str = "HIZMET_FATURASI"):
        super().__init__(parent)
        self.configure(bg=ACIK_BG)
        self.transient(parent.winfo_toplevel())
        self.geometry("1080x460")
        self.alis_fatura_id = int(alis_fatura_id) if alis_fatura_id else None
        self.kaynak_id = int(kaynak_id) if kaynak_id else None
        self.kaynak_turu = kaynak_turu
        self._satirlar: dict[str, dict] = {}
        if self.alis_fatura_id:
            self.title("Bağlı Masraflar")
            baslik = "BU ALIŞ FATURASINA BAĞLI MASRAFLAR"
            kolonlar = (("no", "Dağıtım No", 100, "w"), ("tarih", "Tarih", 85, "center"),
                        ("tur", "Masraf Belgesi Türü", 170, "w"), ("kaynak", "Masraf Belgesi", 130, "w"),
                        ("cari", "Nakliyeci / Kasa", 180, "w"), ("urun", "Ürün Satırları", 200, "w"),
                        ("pay", "Bu Faturaya Pay", 110, "e"), ("durum", "Durum", 90, "center"))
        else:
            self.title("Bağlı Alış Faturaları")
            baslik = "BU MASRAF BELGESİNE BAĞLI ALIŞ FATURALARI"
            kolonlar = (("no", "Dağıtım No", 100, "w"), ("tarih", "Tarih", 85, "center"),
                        ("fatura", "Alış Faturası", 130, "w"), ("ftarih", "Fatura Tarihi", 90, "center"),
                        ("ted", "Tedarikçi", 220, "w"), ("pay", "Pay", 110, "e"),
                        ("yontem", "Yöntem", 140, "w"), ("durum", "Durum", 90, "center"))
        bant = tk.Frame(self, bg=LACIVERT)
        bant.pack(fill="x")
        tk.Label(bant, text=baslik, bg=LACIVERT, fg=SARI, font=font(13, "bold", self)).pack(side="left", padx=12, pady=8)
        cerceve = ttk.Frame(self)
        cerceve.pack(fill="both", expand=True, padx=10, pady=8)
        self.tablo = ttk.Treeview(cerceve, columns=[k for k, *_ in kolonlar], show="headings", selectmode="browse")
        treeview_stil(self.tablo)
        for k, b, w, a in kolonlar:
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=w, anchor=a)
        self.tablo.pack(side="left", fill="both", expand=True)
        ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview).pack(side="right", fill="y")
        self.ozet_lbl = tk.Label(self, text="", bg=ACIK_BG, fg=LACIVERT, anchor="w", justify="left",
                                 font=font(10, root=self))
        self.ozet_lbl.pack(fill="x", padx=12)
        alt = tk.Frame(self, bg=ACIK_BG)
        alt.pack(fill="x", padx=10, pady=8)
        tk_buton(alt, "Masraf Dağıtımını Aç", self.dagitimi_ac, rol="duzenle").pack(side="left")
        if self.alis_fatura_id:
            tk_buton(alt, "Masraf Belgesini Aç", self.kaynak_ac, rol="ara").pack(side="left", padx=6)
            self.tablo.bind("<Double-1>", lambda _e: self.kaynak_ac())
        else:
            tk_buton(alt, "Alış Faturasını Aç", self.fatura_ac, rol="ara").pack(side="left", padx=6)
            tk_buton(alt, "Yeni Dağıtım (Alış Faturasına Bağla)", self.yeni_dagitim, rol="yeni").pack(side="left")
            self.tablo.bind("<Double-1>", lambda _e: self.fatura_ac())
        tk_buton(alt, "Kapat", self.destroy, rol="geri").pack(side="right")
        self.yenile()

    def yenile(self):
        from database.masraf_dagitim_service import MasrafDagitimService

        self.tablo.delete(*self.tablo.get_children())
        self._satirlar.clear()
        if self.alis_fatura_id:
            kayitlar = MasrafDagitimService.fatura_baglantilari(self.alis_fatura_id, iptaller=True)
            for i, k in enumerate(kayitlar):
                iid = str(k["id"])
                self._satirlar[iid] = {"dagitim_id": k["id"], "kaynak_turu": k["kaynak_turu"],
                                       "kaynak_id": k["kaynak_id"], "kaynak_no": k["kaynak_no"]}
                urunler = ", ".join(
                    f"{s['urun_kodu']}: {_sayi(s['eski_birim_maliyet'])} + pay {_para(s['pay'])} → "
                    f"{_sayi(s['yeni_birim_maliyet'])}" for s in k["satirlar"])
                self.tablo.insert("", "end", iid=iid, tags=("tek" if i % 2 == 0 else "cift",), values=(
                    k["dagitim_no"], _tarih(k["tarih"]), k["kaynak_turu_etiket"], k["kaynak_no"], k["kaynak_cari"],
                    urunler, _para(k["pay"]), _durum_etiketi(k["durum"])))
            onayli = sum((k["pay"] for k in kayitlar if k["durum"] == "ONAYLANDI"), Decimal("0"))
            metin = (f"Onaylı dağıtımlarla bu faturanın maliyetine eklenen masraf: {_para(onayli)} TL. "
                     "Faturadaki tedarikçi alış fiyatı değişmez; ek masraf yalnız stok maliyet katmanına işlenir."
                     if kayitlar else "Bu alış faturasına bağlı masraf dağıtımı yok.")
            if any(k["durum"] == "ONAYLANDI" for k in kayitlar):
                metin += ("\nBu fatura onaylı dağıtıma bağlı olduğu için düzenlenemez / iptal edilemez; "
                          "önce ilgili dağıtımı Geri Al ile çözün.")
            self.ozet_lbl.configure(text=metin)
            return
        bilgi = MasrafDagitimService.kaynak_baglantilari(int(self.kaynak_id or 0), self.kaynak_turu)
        sira = 0
        for d in bilgi["dagitimlar"]:
            for f in d["alis_faturalari"] or [{"fatura_id": None, "fatura_no": "", "tarih": None, "tedarikci": "",
                                               "pay": d["tutar"]}]:
                iid = f"{d['id']}:{f['fatura_id'] or 0}"
                self._satirlar[iid] = {"dagitim_id": d["id"], "fatura_id": f["fatura_id"]}
                self.tablo.insert("", "end", iid=iid, tags=("tek" if sira % 2 == 0 else "cift",), values=(
                    d["dagitim_no"], _tarih(d["tarih"]), f["fatura_no"], _tarih(f["tarih"]), f["tedarikci"],
                    _para(f["pay"]), d["yontem"], _durum_etiketi(d["durum"])))
                sira += 1
        k = bilgi.get("kaynak") or {}
        metin = (f"{k.get('tur_etiket', '')} {k.get('no', '')}   |   Dağıtılabilir toplam: {_para(bilgi.get('toplam'))} TL"
                 f"   |   Dağıtılan (onaylı): {_para(bilgi['dagitilan'])} TL   |   Kalan: {_para(bilgi['kalan'])} TL")
        if any(d["durum"] == "ONAYLANDI" for d in bilgi["dagitimlar"]):
            metin += ("\nBu belge onaylı dağıtıma bağlı olduğu için düzenlenemez / iptal edilemez; "
                      "önce ilgili dağıtımı Geri Al ile çözün.")
        self.ozet_lbl.configure(text=metin)

    def _secili(self) -> dict | None:
        sec = self.tablo.selection()
        if not sec:
            kalemler = self.tablo.get_children()
            if len(kalemler) == 1:
                sec = kalemler
        if not sec:
            messagebox.showinfo("Seçim", "Listeden bir satır seçin.", parent=self)
            return None
        return self._satirlar.get(sec[0])

    def dagitimi_ac(self):
        s = self._secili()
        if s:
            dagitim_ac(self, s["dagitim_id"])
            self.yenile()

    def kaynak_ac(self):
        s = self._secili()
        if s:
            kaynak_belge_ac(self, s["kaynak_turu"], s["kaynak_id"], s.get("kaynak_no"))

    def fatura_ac(self):
        s = self._secili()
        if s and s.get("fatura_id"):
            alis_faturasi_ac(self, s["fatura_id"])

    def yeni_dagitim(self):
        from database.access import yetki_var

        if not yetki_var("alis_masraf_duzenleme", "alis_masraf_onay"):
            messagebox.showwarning("Masraf Dağıtımı — yetki", "Yeni masraf dağıtımı oluşturma yetkiniz yok.",
                                   parent=self)
            return
        dagitim_ac(self, None, kaynak=(self.kaynak_turu, int(self.kaynak_id)))
        self.yenile()


def bagli_dagitimlar_goster(parent, *, alis_fatura_id: int | None = None, kaynak_id: int | None = None,
                            kaynak_turu: str = "HIZMET_FATURASI"):
    """Alış faturası / masraf belgesi kartından bağlı belgeleri gösterir; ilgili evrak tek tıkla açılır."""
    try:
        pencere = BagliMasraflarDialog(parent, alis_fatura_id=alis_fatura_id, kaynak_id=kaynak_id,
                                       kaynak_turu=kaynak_turu)
    except (ValueError, PermissionError) as e:
        messagebox.showerror("Bağlı masraflar", str(e), parent=parent)
        return None
    _modal_bekle(parent, pencere)
    return pencere
