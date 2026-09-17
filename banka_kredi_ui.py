"""FİNANS → BANKA KREDİLERİ — kurumsal kredi kartı / taksit / rapor ekranları."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from database.access import yetki_var
from database.banka_kredi_service import BankaKrediService
from database.session_manager import oturum

_NAVY = "#0b1f3a"
_YELLOW = "#e8b923"
_BG = "#eef1f5"
_PANEL = "#ffffff"
_DURUM_RENK = {
    "BEKLIYOR": "#5b7c99",
    "YAKLASIYOR": "#c9a227",
    "VADESI_GECTI": "#c0392b",
    "KISMEN_ODENDI": "#e67e22",
    "ODENDI": "#1e8449",
    "IPTAL": "#566573",
    "YAPILANDIRILDI": "#7d3c98",
    "ERKEN_KAPATILDI": "#1a5276",
}


def _para(tutar) -> str:
    return f"{Decimal(str(tutar or 0)):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _finans_menu_isaretle(app):
    try:
        from finans_ui import _finans_menu_isaretle as _isaretle

        _isaretle(app)
    except Exception:
        pass


def _oturum_banner(parent):
    frm = ttk.Frame(parent)
    frm.pack(fill="x", pady=(4, 8))
    firma = getattr(oturum, "company_name", None) or getattr(oturum, "firma_adi", None) or "—"
    donem = getattr(oturum, "donem_adi", None) or "—"
    kullanici = getattr(oturum, "kullanici_adi", None) or getattr(oturum, "ad_soyad", None) or "—"
    ttk.Label(
        frm,
        text=f"Firma: {firma}   |   Dönem: {donem}   |   Kullanıcı: {kullanici}",
        font=("Segoe UI", 9),
    ).pack(anchor="w")
    return frm


def _yetki(*kodlar) -> bool:
    if yetki_var("finans_duzenleme") and any(
        k.endswith("_odeme") or k.endswith("_olusturma") or k.endswith("_duzenleme") or k.endswith("_plan")
        for k in kodlar
    ):
        if yetki_var(*kodlar) or yetki_var("finans_duzenleme"):
            return True
    return yetki_var(*kodlar) or yetki_var("finans_goruntuleme")


def _ozet_kartlar(parent, ozet: dict):
    wrap = tk.Frame(parent, bg=_BG)
    wrap.pack(fill="x", pady=(8, 12))
    kartlar = (
        ("Toplam kredi borcu", ozet.get("toplam_borc")),
        ("Bu ay ödenecek", ozet.get("bu_ay_odenecek")),
        ("Gecikmiş taksit", ozet.get("gecikmis")),
        ("Bu ay ödenen anapara", ozet.get("bu_ay_odenen_anapara")),
        ("Bu ay finansman gideri", ozet.get("bu_ay_finansman_gideri")),
        ("Gelecek taksit", ozet.get("gelecek_taksit_tarihi")),
    )
    for i, (baslik, deger) in enumerate(kartlar):
        kutu = tk.Frame(wrap, bg=_PANEL, highlightbackground="#cfd6e0", highlightthickness=1)
        kutu.grid(row=0, column=i, padx=4, sticky="nsew")
        wrap.columnconfigure(i, weight=1)
        tk.Label(kutu, text=baslik, bg=_PANEL, fg="#445", font=("Segoe UI", 8)).pack(
            anchor="w", padx=10, pady=(8, 0)
        )
        if isinstance(deger, date):
            metin = deger.strftime("%d.%m.%Y")
        else:
            metin = _para(deger)
        tk.Label(
            kutu, text=metin, bg=_PANEL, fg=_NAVY, font=("Segoe UI", 12, "bold")
        ).pack(anchor="w", padx=10, pady=(2, 10))


def banka_kredileri_menusu_goster(app):
    BankaKrediService.schema_hazirla()
    if not (yetki_var("banka_kredi_goruntuleme") or yetki_var("finans_goruntuleme")):
        messagebox.showwarning("Yetki", "Banka kredilerini görüntüleme yetkiniz yok.")
        return
    app._icerigi_temizle()
    _finans_menu_isaretle(app)
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="BANKA KREDİLERİ", style="Baslik.TLabel").pack(side="left")
    try:
        from finans_ui import finans_menusu_goster

        ttk.Button(ust, text="← Finans Menüsü", command=lambda: finans_menusu_goster(app)).pack(
            side="right"
        )
    except Exception:
        pass
    _oturum_banner(app.icerik)
    ttk.Label(
        app.icerik,
        text="Kredi kartları, ödeme planları, taksit ödeme ve muhasebe eşleştirmeleri.",
    ).pack(anchor="w", pady=(4, 8))
    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", pady=(8, 0))
    alt.columnconfigure(0, weight=1, minsize=520)
    nav = getattr(app, "nav_ac", lambda c: c())
    for i, (baslik, komut) in enumerate(
        (
            ("Kredi Kartları", lambda: kredi_kartlari_sayfasi_goster(app)),
            ("Ödeme Planları", lambda: odeme_planlari_sayfasi_goster(app)),
            ("Bekleyen Taksitler", lambda: bekleyen_taksitler_sayfasi_goster(app)),
            ("Ödenen Taksitler", lambda: odenen_taksitler_sayfasi_goster(app)),
            ("Kredi Taksit Ödeme", lambda: kredi_taksit_odeme_sayfasi_goster(app)),
            ("Kredi Raporları", lambda: kredi_raporlari_sayfasi_goster(app)),
            ("Muhasebe Hesap Eşleştirmeleri", lambda: kredi_hesap_eslemeleri_sayfasi_goster(app)),
        )
    ):
        ttk.Button(
            alt, text=baslik, style="AltMenu.TButton", command=lambda c=komut: nav(c)
        ).grid(row=i, column=0, sticky="ew", pady=4)
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: banka_kredileri_menusu_goster(app))


def kredi_kartlari_sayfasi_goster(app):
    BankaKrediService.schema_hazirla()
    app._icerigi_temizle()
    _finans_menu_isaretle(app)
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="Kredi Kartları", style="Baslik.TLabel").pack(side="left")
    ttk.Button(
        ust, text="← Banka Kredileri", command=lambda: banka_kredileri_menusu_goster(app)
    ).pack(side="right")
    _oturum_banner(app.icerik)
    try:
        ozet = BankaKrediService.ozet_kartlar()
    except Exception:
        ozet = {}
    _ozet_kartlar(app.icerik, ozet)

    arac = ttk.Frame(app.icerik)
    arac.pack(fill="x", pady=(0, 8))

    kolonlar = (
        ("belge", "Belge No", 100),
        ("ad", "Kredi Adı", 160),
        ("banka", "Banka", 120),
        ("tur", "Tür", 80),
        ("pb", "PB", 45),
        ("ana", "Anapara", 95),
        ("kalan", "Kalan Anapara", 105),
        ("aylik", "Aylık Taksit", 100),
        ("odeme", "Ödeme Günü", 140),
        ("durum", "Durum", 95),
    )
    tablo = ttk.Treeview(
        app.icerik, columns=[k for k, _, _ in kolonlar], show="headings", height=16
    )
    for k, b, w in kolonlar:
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="e" if k in ("ana", "kalan", "aylik") else "w")
    tablo.pack(fill="both", expand=True)

    def yenile():
        tablo.delete(*tablo.get_children())
        for k in BankaKrediService.kredi_listesi(aktif_only=False):
            tablo.insert(
                "",
                "end",
                iid=str(k["id"]),
                values=(
                    k.get("belge_no") or k.get("kredi_kodu") or "",
                    k.get("kredi_adi") or "",
                    k.get("banka_adi") or "",
                    k.get("kredi_turu") or "",
                    k.get("para_birimi") or "TRY",
                    _para(k.get("ana_para")),
                    _para(k.get("kalan_anapara")),
                    _para(k.get("aylik_taksit_tutari")),
                    _odeme_gunu_yazi(k.get("gelecek_taksit_tarihi")),
                    k.get("durum") or "",
                ),
            )

    def secili_id():
        s = tablo.selection()
        return int(s[0]) if s else None

    def yeni_kredi():
        if not (yetki_var("banka_kredi_olusturma") or yetki_var("finans_duzenleme")):
            messagebox.showwarning("Yetki", "Yeni kredi oluşturma yetkiniz yok.")
            return
        from finans_ui import BankaKrediKullandirDialog
        from database.finans_service import FinansService

        bankalar = FinansService.banka_kartlari()
        if not bankalar:
            messagebox.showinfo("Banka", "Önce banka kartı tanımlayın.")
            return
        if len(bankalar) == 1:
            kart_id = bankalar[0].id
        else:
            sec = _BankaSecDialog(app.root if hasattr(app, "root") else app.icerik.winfo_toplevel(), bankalar)
            app.icerik.wait_window(sec)
            if not sec.kart_id:
                return
            kart_id = sec.kart_id
        dlg = BankaKrediKullandirDialog(
            app.icerik.winfo_toplevel(), kart_id
        )
        app.icerik.wait_window(dlg)
        yenile()

    def detay_ac():
        kid = secili_id()
        if not kid:
            return
        KrediDetayPenceresi(app.icerik.winfo_toplevel(), kid, yenile_cb=yenile)

    def pasife_al():
        kid = secili_id()
        if not kid:
            return
        if not messagebox.askyesno("Pasife al", "Seçili kredi pasife alınsın mı?"):
            return
        try:
            BankaKrediService.kredi_pasife_al(kid)
            yenile()
        except Exception as hata:
            messagebox.showerror("Hata", str(hata))

    def kapat():
        kid = secili_id()
        if not kid:
            return
        if not messagebox.askyesno("Kapat", "Kredi kapatılsın mı?"):
            return
        try:
            BankaKrediService.kredi_kapat(kid)
            yenile()
        except Exception as hata:
            messagebox.showerror("Hata", str(hata))

    ttk.Button(arac, text="Yeni kredi", command=yeni_kredi).pack(side="left", padx=2)
    ttk.Button(arac, text="Detay / İşlemler", command=detay_ac).pack(side="left", padx=2)
    ttk.Button(arac, text="Pasife al", command=pasife_al).pack(side="left", padx=2)
    ttk.Button(arac, text="Kapat", command=kapat).pack(side="left", padx=2)
    ttk.Button(arac, text="Yenile", command=yenile).pack(side="left", padx=2)
    tablo.bind("<Double-1>", lambda _e: detay_ac())
    yenile()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: kredi_kartlari_sayfasi_goster(app))


class _BankaSecDialog(tk.Toplevel):
    def __init__(self, parent, bankalar):
        super().__init__(parent)
        self.title("Banka seç")
        self.kart_id = None
        self.transient(parent)
        self.grab_set()
        ttk.Label(self, text="Kredi hangi banka kartına bağlansın?").pack(padx=12, pady=8)
        self.var = tk.StringVar()
        self._map = {}
        for b in bankalar:
            etiket = f"{b.banka_adi} — {b.sube or ''}"
            self._map[etiket] = b.id
        cb = ttk.Combobox(self, textvariable=self.var, values=list(self._map), state="readonly", width=40)
        cb.pack(padx=12, pady=4)
        if self._map:
            cb.current(0)
        ttk.Button(self, text="Seç", command=self._ok).pack(pady=10)

    def _ok(self):
        self.kart_id = self._map.get(self.var.get())
        self.destroy()


class KrediDetayPenceresi(tk.Toplevel):
    def __init__(self, parent, kredi_id, yenile_cb=None):
        super().__init__(parent)
        self.kredi_id = int(kredi_id)
        self.yenile_cb = yenile_cb
        self.title("Kredi detay ve işlemler")
        self.geometry("980x620")
        self.configure(bg=_BG)
        self._yukle()

    def _yukle(self):
        for w in self.winfo_children():
            w.destroy()
        detay = BankaKrediService.kredi_detay(self.kredi_id)
        if not detay:
            ttk.Label(self, text="Kredi bulunamadı.").pack(padx=20, pady=20)
            return
        ust = tk.Frame(self, bg=_NAVY)
        ust.pack(fill="x")
        tk.Label(
            ust,
            text=detay.get("kredi_adi") or "Kredi",
            bg=_NAVY,
            fg="white",
            font=("Segoe UI", 14, "bold"),
        ).pack(side="left", padx=12, pady=10)
        tk.Label(
            ust,
            text=f"  {detay.get('belge_no', '')}  |  Kalan: {_para(detay.get('kalan_anapara'))}",
            bg=_NAVY,
            fg=_YELLOW,
            font=("Segoe UI", 10),
        ).pack(side="left")

        arac = ttk.Frame(self)
        arac.pack(fill="x", padx=8, pady=8)
        islemler = (
            ("Ödeme planı", self._plan),
            ("Excel’den aktar", self._excel),
            ("Taksiti öde", self._ode),
            ("Kısmi ödeme", self._kismi),
            ("Ara ödeme", self._ara),
            ("Erken kapama", self._erken),
            ("Bağlı belgeler", self._bagli),
            ("İptal et", self._iptal),
        )
        for metin, komut in islemler:
            ttk.Button(arac, text=metin, command=komut).pack(side="left", padx=2)

        kolonlar = (
            ("no", "No", 40),
            ("vade", "Vade", 90),
            ("ana", "Anapara", 90),
            ("faiz", "Faiz", 80),
            ("bsmv", "BSMV", 70),
            ("kkdf", "KKDF", 70),
            ("masraf", "Masraf", 80),
            ("toplam", "Toplam", 90),
            ("odenen", "Ödenen", 90),
            ("durum", "Durum", 110),
        )
        self.tablo = ttk.Treeview(self, columns=[k for k, _, _ in kolonlar], show="headings", height=18)
        for k, b, w in kolonlar:
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=w, anchor="center" if k in ("no", "vade", "durum") else "e")
        for kod, renk in _DURUM_RENK.items():
            self.tablo.tag_configure(kod, foreground=renk)
        self.tablo.pack(fill="both", expand=True, padx=8, pady=4)
        for t in detay.get("taksitler") or []:
            bilesen = t if "toplam" in t else t
            toplam = bilesen.get("toplam")
            if toplam is None:
                toplam = (
                    Decimal(str(t.get("anapara") or 0))
                    + Decimal(str(t.get("faiz") or 0))
                    + Decimal(str(t.get("masraf") or 0))
                    + Decimal(str(t.get("bsmv") or 0))
                    + Decimal(str(t.get("kkdf") or 0))
                )
            durum = t.get("durum") or "BEKLIYOR"
            self.tablo.insert(
                "",
                "end",
                iid=str(t["id"]),
                values=(
                    t.get("taksit_no"),
                    t.get("vade_tarihi").strftime("%d.%m.%Y") if t.get("vade_tarihi") else "",
                    _para(t.get("anapara")),
                    _para(t.get("faiz")),
                    _para(t.get("bsmv")),
                    _para(t.get("kkdf")),
                    _para(
                        Decimal(str(t.get("masraf") or 0))
                        + Decimal(str(t.get("komisyon") or 0))
                        + Decimal(str(t.get("sigorta") or 0))
                        + Decimal(str(t.get("dosya_masrafi") or 0))
                        + Decimal(str(t.get("diger_masraflar") or 0))
                    ),
                    _para(toplam),
                    _para(t.get("odenen_tutar")),
                    durum,
                ),
                tags=(durum,),
            )
        self.tablo.bind("<Double-1>", lambda _e: self._ode())

    def _secili_taksit(self):
        s = self.tablo.selection()
        return int(s[0]) if s else None

    def _plan(self):
        messagebox.showinfo(
            "Ödeme planı",
            "Plan sürümleri BankaKrediService.plan_versiyonlari ile saklanır.\n"
            "Yeni plan için Excel aktarımını veya kullandırım ekranını kullanın.",
        )

    def _excel(self):
        if not (yetki_var("banka_kredi_excel") or yetki_var("finans_duzenleme") or yetki_var("excel_pdf")):
            messagebox.showwarning("Yetki", "Excel aktarma yetkiniz yok.")
            return
        yol = filedialog.askopenfilename(
            title="Ödeme planı Excel/CSV",
            filetypes=[("Excel/CSV", "*.xlsx *.xls *.csv"), ("Tümü", "*.*")],
        )
        if not yol:
            return
        try:
            plan = BankaKrediService.odeme_plani_excel_aktar(yol)
            BankaKrediService.odeme_plani_kaydet(self.kredi_id, plan, aciklama=f"Excel: {yol}")
            messagebox.showinfo("Aktarım", f"{len(plan)} taksit aktarıldı.")
            self._yukle()
        except Exception as hata:
            messagebox.showerror("Hata", str(hata))

    def _ode(self):
        tid = self._secili_taksit()
        if not tid:
            messagebox.showinfo("Seçim", "Ödenecek taksiti seçin.")
            return
        KrediTaksitOdemePenceresi(self, tid, yenile_cb=self._yukle)

    def _kismi(self):
        tid = self._secili_taksit()
        if not tid:
            messagebox.showinfo("Seçim", "Taksit seçin.")
            return
        tutar = simpledialog.askstring("Kısmi ödeme", "Ödenecek tutar:")
        if not tutar:
            return
        try:
            BankaKrediService.kisimi_ode(tid, tutar, dagitim="ONCE_MASRAF")
            messagebox.showinfo("Tamam", "Kısmi ödeme kaydedildi.")
            self._yukle()
            if self.yenile_cb:
                self.yenile_cb()
        except Exception as hata:
            messagebox.showerror("Hata", str(hata))

    def _ara(self):
        tutar = simpledialog.askstring("Ara ödeme", "Anapara / toplam ara ödeme tutarı:")
        if not tutar:
            return
        try:
            BankaKrediService.ara_ode(self.kredi_id, tutar)
            messagebox.showinfo("Tamam", "Ara ödeme kaydedildi.")
            self._yukle()
            if self.yenile_cb:
                self.yenile_cb()
        except Exception as hata:
            messagebox.showerror("Hata", str(hata))

    def _erken(self):
        if not (yetki_var("banka_kredi_erken_kapama") or yetki_var("finans_duzenleme")):
            messagebox.showwarning("Yetki", "Erken kapama yetkiniz yok.")
            return
        try:
            ozet = BankaKrediService.erken_kapama_ozeti(self.kredi_id)
            if not messagebox.askyesno(
                "Erken kapama",
                f"Kalan anapara: {_para(ozet.get('kalan_anapara'))}\n"
                f"Toplam kapama: {_para(ozet.get('toplam'))}\n\nDevam edilsin mi?",
            ):
                return
            BankaKrediService.erken_kapat(self.kredi_id)
            messagebox.showinfo("Tamam", "Erken kapama tamamlandı.")
            self._yukle()
            if self.yenile_cb:
                self.yenile_cb()
        except Exception as hata:
            messagebox.showerror("Hata", str(hata))

    def _bagli(self):
        belgeler = BankaKrediService.bagli_belgeler(kredi_id=self.kredi_id)
        win = tk.Toplevel(self)
        win.title("Bağlı belgeler")
        win.geometry("720x400")
        tv = ttk.Treeview(win, columns=("tur", "no", "tarih", "tutar"), show="headings")
        for k, b in (("tur", "Tür"), ("no", "Belge"), ("tarih", "Tarih"), ("tutar", "Tutar")):
            tv.heading(k, text=b)
            tv.column(k, width=140)
        tv.pack(fill="both", expand=True, padx=8, pady=8)
        for b in belgeler:
            tv.insert(
                "",
                "end",
                values=(
                    b.get("tur") or "",
                    b.get("belge_no") or "",
                    b.get("tarih") or "",
                    _para(b.get("tutar")),
                ),
            )

    def _iptal(self):
        if not (yetki_var("banka_kredi_odeme_iptal") or yetki_var("finans_duzenleme")):
            messagebox.showwarning("Yetki", "Ödeme iptal yetkiniz yok.")
            return
        neden = simpledialog.askstring("İptal", "İptal gerekçesi (zorunlu):")
        if not neden or not neden.strip():
            messagebox.showwarning("Gerekçe", "İptal gerekçesi zorunludur.")
            return
        odemeler = BankaKrediService.odeme_listesi(kredi_id=self.kredi_id)
        aktif = [o for o in odemeler if (o.get("durum") or "") == "AKTIF"]
        if not aktif:
            messagebox.showinfo("İptal", "İptal edilecek aktif ödeme yok.")
            return
        try:
            BankaKrediService.odeme_iptal(aktif[0]["id"], neden.strip())
            messagebox.showinfo("Tamam", "Son ödeme iptal edildi.")
            self._yukle()
        except Exception as hata:
            messagebox.showerror("Hata", str(hata))


class KrediTaksitOdemePenceresi(tk.Toplevel):
    """Kurumsal taksit ödeme — tek banka çıkışı önizlemesi."""

    def __init__(self, parent, taksit_id, yenile_cb=None):
        super().__init__(parent)
        self.taksit_id = int(taksit_id)
        self.yenile_cb = yenile_cb
        self._kilidi = False
        self.title("Kredi Taksit Ödeme")
        self.geometry("560x720")
        self.transient(parent)
        self.grab_set()
        try:
            self.bilgi = BankaKrediService.bekleyen_taksitler()
            self.detay = next(
                (t for t in BankaKrediService.bekleyen_taksitler(limit=2000) if t["taksit_id"] == self.taksit_id),
                None,
            )
            if not self.detay:
                from database.finans_service import FinansService

                self.detay = FinansService.banka_kredi_taksit_detay(self.taksit_id)
                self.detay["taksit_id"] = self.taksit_id
        except Exception as hata:
            messagebox.showerror("Hata", str(hata))
            self.destroy()
            return
        self._kur()

    def _kur(self):
        d = self.detay
        tk.Frame(self, bg=_NAVY, height=48).pack(fill="x")
        tk.Label(
            self,
            text=f"{d.get('kredi_adi', '')} — Taksit {d.get('taksit_no')}",
            font=("Segoe UI", 12, "bold"),
            fg=_NAVY,
        ).pack(anchor="w", padx=14, pady=(10, 2))
        ttk.Label(self, text=f"Vade: {d.get('vade_tarihi')}").pack(anchor="w", padx=14)

        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, padx=14, pady=8)
        self.vars = {}
        alanlar = (
            ("odeme_tarihi", "Ödeme tarihi (YYYY-MM-DD)", str(date.today())),
            ("banka_dekont_no", "Banka dekont no", ""),
            ("anapara", "Anapara", str(d.get("anapara") or 0)),
            ("faiz", "Faiz", str(d.get("faiz") or 0)),
            ("bsmv", "BSMV", str(d.get("bsmv") or 0)),
            ("kkdf", "KKDF", str(d.get("kkdf") or 0)),
            ("komisyon", "Komisyon", str(d.get("komisyon") or 0)),
            ("sigorta", "Sigorta", str(d.get("sigorta") or 0)),
            ("dosya_masrafi", "Dosya/işlem masrafı", str(d.get("dosya_masrafi") or 0)),
            ("diger_masraflar", "Diğer masraflar", str(d.get("diger_masraflar") or d.get("masraf") or 0)),
            ("gecikme_faizi", "Gecikme faizi", str(d.get("gecikme_faizi") or 0)),
            ("aciklama", "Açıklama", ""),
        )
        for i, (kod, etiket, deger) in enumerate(alanlar):
            ttk.Label(frm, text=etiket).grid(row=i, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=deger)
            self.vars[kod] = var
            ent = ttk.Entry(frm, textvariable=var, width=28)
            ent.grid(row=i, column=1, sticky="ew", pady=2)
            if kod in (
                "anapara",
                "faiz",
                "bsmv",
                "kkdf",
                "komisyon",
                "sigorta",
                "dosya_masrafi",
                "diger_masraflar",
                "gecikme_faizi",
            ):
                var.trace_add("write", lambda *_a: self._toplam_guncelle())

        ttk.Label(frm, text="Toplam taksit").grid(row=len(alanlar), column=0, sticky="w", pady=6)
        self.toplam_var = tk.StringVar(value="0,00")
        ttk.Entry(frm, textvariable=self.toplam_var, state="readonly", width=28).grid(
            row=len(alanlar), column=1, sticky="ew", pady=6
        )

        onizleme = tk.Text(self, height=6, wrap="word", font=("Segoe UI", 9))
        onizleme.pack(fill="x", padx=14, pady=4)
        onizleme.insert(
            "1.0",
            "Muhasebe önizleme:\n"
            "• Bankadan TOPLAM tutarda tek çıkış\n"
            "• Anapara → kredi borcu azaltılır (gider değil)\n"
            "• Faiz ve masraflar → bağlı gider fişleri (ikinci banka çıkışı yok)\n"
            "• Muhasebe fişi hesap eşleştirmeleri tanımlıysa oluşur",
        )
        onizleme.configure(state="disabled")

        alt = ttk.Frame(self)
        alt.pack(fill="x", padx=14, pady=10)
        ttk.Button(alt, text="Öde ve Kaydet", command=self._kaydet).pack(side="left", padx=4)
        ttk.Button(alt, text="Vazgeç", command=self.destroy).pack(side="left", padx=4)
        self._toplam_guncelle()

    def _d(self, kod) -> Decimal:
        try:
            return Decimal(str(self.vars[kod].get() or "0").replace(",", "."))
        except Exception:
            return Decimal("0")

    def _toplam_guncelle(self):
        toplam = sum(
            (
                self._d(k)
                for k in (
                    "anapara",
                    "faiz",
                    "bsmv",
                    "kkdf",
                    "komisyon",
                    "sigorta",
                    "dosya_masrafi",
                    "diger_masraflar",
                    "gecikme_faizi",
                )
            ),
            Decimal("0"),
        )
        self.toplam_var.set(_para(toplam))

    def _kaydet(self):
        if self._kilidi:
            return
        if not (yetki_var("banka_kredi_odeme") or yetki_var("finans_duzenleme")):
            messagebox.showwarning("Yetki", "Taksit ödeme yetkiniz yok.")
            return
        self._kilidi = True
        try:
            tarih_metin = self.vars["odeme_tarihi"].get().strip()
            odeme_tarihi = datetime.strptime(tarih_metin, "%Y-%m-%d").date()
            sonuc = BankaKrediService.taksit_ode(
                taksit_id=self.taksit_id,
                odeme_tarihi=odeme_tarihi,
                banka_dekont_no=self.vars["banka_dekont_no"].get().strip() or None,
                aciklama=self.vars["aciklama"].get().strip() or None,
                bilesenler={
                    "anapara": self._d("anapara"),
                    "faiz": self._d("faiz"),
                    "bsmv": self._d("bsmv"),
                    "kkdf": self._d("kkdf"),
                    "komisyon": self._d("komisyon"),
                    "sigorta": self._d("sigorta"),
                    "dosya_masrafi": self._d("dosya_masrafi"),
                    "diger_masraflar": self._d("diger_masraflar"),
                    "gecikme_faizi": self._d("gecikme_faizi"),
                },
                odeme_turu="TAKSIT",
            )
            messagebox.showinfo(
                "Ödeme",
                f"Ödeme kaydedildi.\nBelge: {sonuc.get('odeme_belge_no')}\n"
                f"Toplam: {_para(sonuc.get('toplam'))}",
            )
            if self.yenile_cb:
                self.yenile_cb()
            self.destroy()
        except Exception as hata:
            self._kilidi = False
            messagebox.showerror("Hata", str(hata))


def odeme_planlari_sayfasi_goster(app):
    kredi_kartlari_sayfasi_goster(app)
    messagebox.showinfo(
        "Ödeme planları",
        "Bir kredi kartına çift tıklayıp «Ödeme planı» / Excel aktarımını kullanın.",
    )


def bekleyen_taksitler_sayfasi_goster(app):
    BankaKrediService.schema_hazirla()
    app._icerigi_temizle()
    _finans_menu_isaretle(app)
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="Bekleyen Taksitler", style="Baslik.TLabel").pack(side="left")
    ttk.Button(
        ust, text="← Banka Kredileri", command=lambda: banka_kredileri_menusu_goster(app)
    ).pack(side="right")
    _oturum_banner(app.icerik)
    tv = ttk.Treeview(
        app.icerik,
        columns=("kredi", "no", "vade", "toplam", "durum"),
        show="headings",
        height=18,
    )
    for k, b, w in (
        ("kredi", "Kredi", 220),
        ("no", "Taksit", 60),
        ("vade", "Vade", 100),
        ("toplam", "Toplam", 100),
        ("durum", "Durum", 110),
    ):
        tv.heading(k, text=b)
        tv.column(k, width=w)
    tv.pack(fill="both", expand=True, pady=8)
    for t in BankaKrediService.bekleyen_taksitler(limit=500):
        tv.insert(
            "",
            "end",
            iid=str(t["taksit_id"]),
            values=(
                t.get("kredi_adi"),
                t.get("taksit_no"),
                t.get("vade_tarihi"),
                _para(t.get("toplam")),
                t.get("durum") or "BEKLIYOR",
            ),
        )

    def ode():
        s = tv.selection()
        if not s:
            return
        KrediTaksitOdemePenceresi(
            app.icerik.winfo_toplevel(),
            int(s[0]),
            yenile_cb=lambda: bekleyen_taksitler_sayfasi_goster(app),
        )

    ttk.Button(app.icerik, text="Taksiti Öde", command=ode).pack(anchor="w", pady=4)
    tv.bind("<Double-1>", lambda _e: ode())
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: bekleyen_taksitler_sayfasi_goster(app))


def odenen_taksitler_sayfasi_goster(app):
    BankaKrediService.schema_hazirla()
    app._icerigi_temizle()
    _finans_menu_isaretle(app)
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="Ödenen Taksitler", style="Baslik.TLabel").pack(side="left")
    ttk.Button(
        ust, text="← Banka Kredileri", command=lambda: banka_kredileri_menusu_goster(app)
    ).pack(side="right")
    _oturum_banner(app.icerik)
    tv = ttk.Treeview(
        app.icerik,
        columns=("kredi", "no", "odeme", "toplam", "belge"),
        show="headings",
        height=18,
    )
    for k, b, w in (
        ("kredi", "Kredi", 220),
        ("no", "Taksit", 60),
        ("odeme", "Ödeme", 100),
        ("toplam", "Toplam", 100),
        ("belge", "Belge", 120),
    ):
        tv.heading(k, text=b)
        tv.column(k, width=w)
    tv.pack(fill="both", expand=True, pady=8)
    for t in BankaKrediService.odenen_taksitler(limit=500):
        tv.insert(
            "",
            "end",
            values=(
                t.get("kredi_adi"),
                t.get("taksit_no"),
                t.get("odeme_tarihi"),
                _para(t.get("toplam") or t.get("odenen_tutar")),
                t.get("odeme_belge_no") or "",
            ),
        )
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: odenen_taksitler_sayfasi_goster(app))


def kredi_taksit_odeme_sayfasi_goster(app):
    bekleyen_taksitler_sayfasi_goster(app)


def _tarih_yazi(deger) -> str:
    if deger is None:
        return ""
    if isinstance(deger, date):
        return deger.strftime("%d.%m.%Y")
    return str(deger)


def _odeme_gunu_yazi(vade, odeme_gunu=None) -> str:
    """Örn: 15.09.2026 (ayın 15'i)"""
    if isinstance(vade, date):
        gun = vade.day
        return f"{vade.strftime('%d.%m.%Y')} (ayın {gun}'i)"
    if odeme_gunu:
        return f"Ayın {int(odeme_gunu)}'i"
    return ""


def _rapor_tablo(parent, kolonlar, satirlar, satir_degerleri, *, iid_al=None, cift_tik=None):
    """kolonlar: [(kod, baslik, genislik), ...] — Treeview doldurur."""
    cerceve = ttk.Frame(parent)
    cerceve.pack(fill="both", expand=True)
    tv = ttk.Treeview(
        cerceve,
        columns=[k for k, _, _ in kolonlar],
        show="headings",
        height=16,
    )
    kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=tv.yview)
    tv.configure(yscrollcommand=kaydir.set)
    tv.pack(side="left", fill="both", expand=True)
    kaydir.pack(side="right", fill="y")
    for k, b, w in kolonlar:
        tv.heading(k, text=b)
        ank = "e" if k in {
            "ana_para", "kalan_anapara", "kalan_borc", "toplam", "anapara", "faiz",
            "masraf", "tutar", "oran", "kredi_sayisi", "taksit_sayisi", "kalan_taksit",
            "aylik", "aylik_taksit",
        } else "w"
        tv.column(k, width=w, anchor=ank, stretch=True)
    if not satirlar:
        tv.insert("", "end", values=tuple("—" if i else "Kayıt yok" for i in range(len(kolonlar))))
        return tv
    for s in satirlar:
        kwargs = {}
        if iid_al is not None:
            iid = iid_al(s)
            if iid is not None:
                kwargs["iid"] = str(iid)
        tv.insert("", "end", values=satir_degerleri(s), **kwargs)
    if cift_tik is not None:
        def _acil(_event, tablo=tv, handler=cift_tik):
            secim = tablo.selection()
            if not secim:
                return
            handler(secim[0], tablo)

        tv.bind("<Double-1>", _acil)
    return tv


def kredi_raporlari_sayfasi_goster(app):
    if not (yetki_var("banka_kredi_rapor") or yetki_var("finans_goruntuleme")):
        messagebox.showwarning("Yetki", "Rapor görüntüleme yetkiniz yok.")
        return
    BankaKrediService.schema_hazirla()
    app._icerigi_temizle()
    _finans_menu_isaretle(app)
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="Kredi Raporları", style="Baslik.TLabel").pack(side="left")
    ttk.Button(
        ust, text="← Banka Kredileri", command=lambda: banka_kredileri_menusu_goster(app)
    ).pack(side="right")
    _oturum_banner(app.icerik)
    ttk.Label(
        app.icerik,
        text="Bir kredi satırına çift tıklayarak detay ve işlemler penceresini açabilirsiniz.",
        font=("Segoe UI", 9),
    ).pack(anchor="w", pady=(0, 4))

    parent = app.icerik.winfo_toplevel()

    def _kredi_ac(iid, _tablo=None):
        try:
            kid = int(str(iid).split(":")[-1])
        except ValueError:
            return
        KrediDetayPenceresi(parent, kid, yenile_cb=lambda: _yenile(gun_var.get()))

    def _taksit_kredi_ac(iid, _tablo=None):
        # iid formatı: kredi_id:taksit_id veya sadece kredi_id
        try:
            parcalar = str(iid).split(":")
            kid = int(parcalar[0])
        except ValueError:
            return
        KrediDetayPenceresi(parent, kid, yenile_cb=lambda: _yenile(gun_var.get()))

    def _yenile(gun=30):
        for cocuk in notebook.winfo_children():
            cocuk.destroy()
        # Bakiye özeti
        f1 = ttk.Frame(notebook)
        notebook.add(f1, text="Bakiye özeti")
        _rapor_tablo(
            f1,
            (
                ("belge", "Belge No", 100),
                ("banka", "Banka", 130),
                ("kredi", "Kredi", 160),
                ("ana", "Anapara", 95),
                ("kalan_a", "Kalan Anapara", 105),
                ("aylik", "Aylık Taksit", 105),
                ("vade", "Ödeme Günü / Vade", 150),
                ("kalan_b", "Kalan Borç", 95),
                ("taksit", "Kalan Tk.", 70),
                ("durum", "Durum", 90),
            ),
            BankaKrediService.rapor_bakiye_ozeti(),
            lambda s: (
                s.get("belge_no") or "",
                s.get("banka_adi") or "",
                s.get("kredi_adi") or "",
                _para(s.get("ana_para")),
                _para(s.get("kalan_anapara")),
                _para(s.get("aylik_taksit_tutari")),
                _odeme_gunu_yazi(s.get("gelecek_taksit_tarihi"), s.get("odeme_gunu")),
                _para(s.get("kalan_borc")),
                s.get("kalan_taksit_sayisi") or 0,
                s.get("durum") or "",
            ),
            iid_al=lambda s: s.get("kredi_id"),
            cift_tik=_kredi_ac,
        )
        # Bankalara göre
        f2 = ttk.Frame(notebook)
        notebook.add(f2, text="Bankalara göre")
        _rapor_tablo(
            f2,
            (
                ("banka", "Banka", 200),
                ("adet", "Kredi Sayısı", 100),
                ("ana", "Anapara", 120),
                ("kalan_a", "Kalan Anapara", 120),
                ("kalan_b", "Kalan Borç", 120),
            ),
            BankaKrediService.rapor_bankalara_gore(),
            lambda s: (
                s.get("banka_adi") or "",
                s.get("kredi_sayisi") or 0,
                _para(s.get("ana_para")),
                _para(s.get("kalan_anapara")),
                _para(s.get("kalan_borc")),
            ),
        )
        # Vadesi geçen
        f3 = ttk.Frame(notebook)
        notebook.add(f3, text="Vadesi geçen")
        _rapor_tablo(
            f3,
            (
                ("kredi", "Kredi", 180),
                ("no", "Taksit", 60),
                ("vade", "Vade", 100),
                ("ana", "Anapara", 90),
                ("faiz", "Faiz", 80),
                ("masraf", "Masraf", 80),
                ("toplam", "Taksit Tutarı", 100),
                ("durum", "Durum", 100),
            ),
            BankaKrediService.rapor_vadesi_gecen(),
            lambda s: (
                s.get("kredi_adi") or "",
                s.get("taksit_no") or "",
                _tarih_yazi(s.get("vade_tarihi")),
                _para(s.get("anapara")),
                _para(s.get("faiz")),
                _para(
                    Decimal(str(s.get("bsmv") or 0))
                    + Decimal(str(s.get("kkdf") or 0))
                    + Decimal(str(s.get("komisyon") or 0))
                    + Decimal(str(s.get("sigorta") or 0))
                    + Decimal(str(s.get("dosya_masrafi") or 0))
                    + Decimal(str(s.get("diger_masraflar") or 0))
                    + Decimal(str(s.get("masraf") or 0))
                    + Decimal(str(s.get("gecikme_faizi") or 0))
                ),
                _para(s.get("toplam")),
                s.get("durum") or "",
            ),
            iid_al=lambda s: f"{s.get('kredi_id')}:{s.get('taksit_id')}",
            cift_tik=_taksit_kredi_ac,
        )
        # Takvim
        f4 = ttk.Frame(notebook)
        notebook.add(f4, text=f"{gun} gün takvim")
        _rapor_tablo(
            f4,
            (
                ("vade", "Vade", 100),
                ("adet", "Taksit Adedi", 90),
                ("ana", "Anapara", 100),
                ("faiz", "Faiz", 90),
                ("masraf", "Masraf", 90),
                ("toplam", "Taksit Tutarı", 110),
            ),
            BankaKrediService.rapor_takvim(gun),
            lambda s: (
                _tarih_yazi(s.get("vade_tarihi")),
                s.get("taksit_sayisi") or 0,
                _para(s.get("anapara")),
                _para(s.get("faiz")),
                _para(s.get("masraf")),
                _para(s.get("toplam")),
            ),
        )
        # Maliyet
        f5 = ttk.Frame(notebook)
        notebook.add(f5, text="Maliyet dağılımı")
        _rapor_tablo(
            f5,
            (
                ("etiket", "Bileşen", 220),
                ("tutar", "Tutar", 120),
                ("oran", "Oran %", 90),
            ),
            BankaKrediService.rapor_maliyet_dagilimi(),
            lambda s: (
                s.get("etiket") or s.get("bilesen") or "",
                _para(s.get("tutar")),
                _para(s.get("oran")),
            ),
        )

    arac = ttk.Frame(app.icerik)
    arac.pack(fill="x", pady=(4, 6))
    ttk.Label(arac, text="Takvim:").pack(side="left")
    gun_var = tk.IntVar(value=30)
    for g in (7, 30, 90):
        ttk.Radiobutton(
            arac, text=f"{g} gün", variable=gun_var, value=g,
            command=lambda: _yenile(gun_var.get()),
        ).pack(side="left", padx=4)
    ttk.Button(arac, text="Yenile", command=lambda: _yenile(gun_var.get())).pack(
        side="left", padx=8
    )

    notebook = ttk.Notebook(app.icerik)
    notebook.pack(fill="both", expand=True, pady=(4, 0))
    _yenile(30)

    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: kredi_raporlari_sayfasi_goster(app))


def kredi_hesap_eslemeleri_sayfasi_goster(app):
    if not (
        yetki_var("banka_kredi_hesap_esleme")
        or yetki_var("finans_duzenleme")
        or yetki_var("muhasebe_fis_olusturma")
    ):
        messagebox.showwarning("Yetki", "Hesap eşleştirme yetkiniz yok.")
        return
    app._icerigi_temizle()
    _finans_menu_isaretle(app)
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="Kredi Muhasebe Hesap Eşleştirmeleri", style="Baslik.TLabel").pack(
        side="left"
    )
    ttk.Button(
        ust, text="← Banka Kredileri", command=lambda: banka_kredileri_menusu_goster(app)
    ).pack(side="right")
    _oturum_banner(app.icerik)
    ttk.Label(
        app.icerik,
        text="Hesap kodları kaynak koda sabitlenmez. Firma bazında eşleştirin. "
        "Öneri: 300/400 krediler, 102 banka, 660/780 finansman giderleri.",
    ).pack(anchor="w", pady=(8, 8))
    try:
        from database.muhasebe_entegrasyon import HesapEslemeService
        from database.models.genel_muhasebe import ESLEME_ANAHTARLARI

        liste = HesapEslemeService.listele()
        kredi_anahtarlar = {a for a, _ in ESLEME_ANAHTARLARI if a.startswith("kredi_") or a.startswith("kur_")}
        kredi_anahtarlar |= {"banka", "giderler"}
        tv = ttk.Treeview(app.icerik, columns=("anahtar", "aciklama", "hesap"), show="headings", height=18)
        for k, b, w in (
            ("anahtar", "Anahtar", 180),
            ("aciklama", "Açıklama", 260),
            ("hesap", "Hesap", 200),
        ):
            tv.heading(k, text=b)
            tv.column(k, width=w)
        tv.pack(fill="both", expand=True)
        for e in liste:
            if e.get("anahtar") not in kredi_anahtarlar:
                continue
            hesap = e.get("hesap_kodu") or ""
            if e.get("hesap_adi"):
                hesap = f"{hesap} {e.get('hesap_adi')}".strip()
            tv.insert("", "end", values=(e.get("anahtar"), e.get("aciklama"), hesap or "— seçilmedi —"))

        def kaydet():
            s = tv.selection()
            if not s:
                return
            anahtar = tv.item(s[0], "values")[0]
            hesap_id = simpledialog.askinteger(
                "Hesap",
                f"{anahtar} için muhasebe hesap_id girin (boş=kaldır için 0):",
            )
            if hesap_id is None:
                return
            try:
                HesapEslemeService.kaydet(anahtar, None if hesap_id == 0 else hesap_id)
                kredi_hesap_eslemeleri_sayfasi_goster(app)
            except Exception as hata:
                messagebox.showerror("Hata", str(hata))

        ttk.Button(app.icerik, text="Seçili satırı eşleştir", command=kaydet).pack(anchor="w", pady=6)
    except Exception as hata:
        ttk.Label(app.icerik, text=f"Eşleştirme ekranı açılamadı: {hata}").pack(anchor="w")
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: kredi_hesap_eslemeleri_sayfasi_goster(app))
