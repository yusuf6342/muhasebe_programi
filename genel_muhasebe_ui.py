"""GENEL MUHASEBE menüsü — hesap planı, fişler, mizan, bilanço, gelir tablosu."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from database.models.genel_muhasebe import FIS_TURLERI, HESAP_TURLERI
from database.muhasebe_service import (
    HesapPlanService,
    MuhasebeFisService,
    MuhasebeRaporService,
    MuhasebeService,
    decimal,
    para_goster,
)
from database.muhasebe_entegrasyon import HesapEslemeService
from database.tdhp_hesap_plani import fis_alt_hesap_zorunlu, fis_icin_alt_hesap_mi
from database.session_manager import oturum


def _menu_isaretle(app):
    kabuk = getattr(app, "_ana_panel_kabuk", None)
    if kabuk is not None:
        kabuk.menu_secili_guncelle("genel_muhasebe")
        return
    for anahtar, dugme in app.menu_dugmeleri.items():
        if anahtar == "genel_muhasebe":
            dugme.configure(style="SeciliMenu.TButton")
        elif anahtar == "hizli_satis":
            dugme.configure(style="HizliSatisMenu.TButton")
        else:
            dugme.configure(style="Menu.TButton")


def _ust_bilgi(parent) -> ttk.Frame:
    """Firma, mali yıl, tarih aralığı bilgisi."""
    cerceve = ttk.Frame(parent)
    cerceve.pack(fill="x", pady=(4, 10))
    firma = oturum.firma_unvan or "—"
    donem = oturum.donem_adi or "—"
    bugun = date.today().strftime("%d.%m.%Y")
    ttk.Label(
        cerceve,
        text=f"Firma: {firma}   |   Dönem: {donem}   |   Bugün: {bugun}   |   Rapor para birimi: TL",
    ).pack(anchor="w")
    return cerceve


def _tarih_parse(metin: str) -> date | None:
    metin = (metin or "").strip()
    if not metin:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(metin, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Geçersiz tarih: {metin}")


def genel_muhasebe_menusu_goster(app):
    try:
        MuhasebeService.schema_hazirla()
    except Exception as hata:
        messagebox.showerror("Genel Muhasebe", str(hata), parent=app)
        return
    app._icerigi_temizle()
    _menu_isaretle(app)
    ttk.Label(app.icerik, text="GENEL MUHASEBE", style="Baslik.TLabel").pack(anchor="w")
    _ust_bilgi(app.icerik)
    ttk.Label(
        app.icerik,
        text="Hesap planı, muhasebe fişleri ve temel raporlar.",
    ).pack(anchor="w")
    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", pady=(24, 0))
    alt.columnconfigure(0, weight=1, minsize=520)
    nav = getattr(app, "nav_ac", lambda c: c())
    for i, (baslik, komut) in enumerate(
        (
            ("HESAP PLANI", lambda: hesap_plani_goster(app)),
            ("MUHASEBE FİŞLERİ", lambda: fisler_goster(app)),
            ("HESAP EŞLEŞTİRMELERİ", lambda: eslemeler_goster(app)),
            ("MİZAN", lambda: mizan_goster(app)),
            ("BİLANÇO", lambda: bilanco_goster(app)),
            ("GELİR TABLOSU", lambda: gelir_tablosu_goster(app)),
        )
    ):
        ttk.Button(alt, text=baslik, style="AltMenu.TButton", command=lambda c=komut: nav(c)).grid(
            row=i, column=0, sticky="ew", pady=4
        )
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: genel_muhasebe_menusu_goster(app))


def _geri(app):
    genel_muhasebe_menusu_goster(app)


# ---------- Hesap Eşleştirmeleri ----------


def eslemeler_goster(app):
    app._icerigi_temizle()
    _menu_isaretle(app)
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="HESAP EŞLEŞTİRMELERİ", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Genel Muhasebe", command=lambda: _geri(app)).pack(side="right")
    _ust_bilgi(app.icerik)
    ttk.Label(
        app.icerik,
        text="Satış/alış/kasa entegrasyonu bu eşleştirmeleri kullanır. Hesap kodları programa sabit yazılmaz.",
    ).pack(anchor="w", pady=(0, 8))

    arac = ttk.Frame(app.icerik)
    arac.pack(fill="x", pady=(0, 8))

    kolonlar = ("anahtar", "aciklama", "kod", "ad")
    tablo = ttk.Treeview(app.icerik, columns=kolonlar, show="headings", height=14)
    for k, t, w in (
        ("anahtar", "Anahtar", 140),
        ("aciklama", "Açıklama", 260),
        ("kod", "Hesap Kodu", 100),
        ("ad", "Hesap Adı", 220),
    ):
        tablo.heading(k, text=t)
        tablo.column(k, width=w)
    tablo.pack(fill="both", expand=True)

    kayitlar: dict[str, dict] = {}

    def yenile():
        tablo.delete(*tablo.get_children())
        kayitlar.clear()
        try:
            for e in HesapEslemeService.listele():
                iid = e["anahtar"]
                kayitlar[iid] = e
                tablo.insert(
                    "",
                    "end",
                    iid=iid,
                    values=(
                        e["anahtar"],
                        e["aciklama"],
                        e["hesap_kodu"] or "—",
                        e["hesap_adi"] or "—",
                    ),
                )
        except Exception as hata:
            messagebox.showerror("Eşleştirme", str(hata), parent=app)

    def oneri():
        if not messagebox.askyesno(
            "Tek Düzen / Eşleştirme",
            "Tek Düzen ana hesaplar yüklensin ve standart eşleştirmeler "
            "(100, 102, 120, 153, 191, 320, 391, 600, 621, 770) bağlansın mı?",
            parent=app,
        ):
            return
        try:
            n = HesapEslemeService.oneri_hesaplari_olustur()
            messagebox.showinfo("Tamam", f"İşlem tamam. Yeni eklenen ana hesap: {n}", parent=app)
            yenile()
        except Exception as hata:
            messagebox.showerror("Eşleştirme", str(hata), parent=app)

    def bagla():
        sec = tablo.selection()
        if not sec:
            messagebox.showinfo("Seçim", "Eşleştirme satırı seçin.", parent=app)
            return
        e = kayitlar[sec[0]]
        dlg = tk.Toplevel(app)
        dlg.title(f"Eşleştir: {e['anahtar']}")
        dlg.transient(app)
        dlg.grab_set()
        frm = ttk.Frame(dlg, padding=14)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=e["aciklama"]).pack(anchor="w")
        ttk.Label(frm, text="Hesap kodu:").pack(anchor="w", pady=(8, 0))
        kod_e = ttk.Entry(frm, width=20)
        kod_e.pack(anchor="w")
        if e.get("hesap_kodu"):
            kod_e.insert(0, e["hesap_kodu"])

        def kaydet():
            kod = kod_e.get().strip()
            try:
                if not kod:
                    HesapEslemeService.kaydet(e["anahtar"], None)
                else:
                    hesaplar = HesapPlanService.listele(arama=kod, sadece_aktif=True)
                    h = next((x for x in hesaplar if x["hesap_kodu"] == kod), None)
                    if not h:
                        raise ValueError("Hesap bulunamadı.")
                    HesapEslemeService.kaydet(e["anahtar"], h["id"])
            except Exception as hata:
                messagebox.showerror("Eşleştirme", str(hata), parent=dlg)
                return
            dlg.destroy()
            yenile()

        ttk.Button(frm, text="Kaydet", command=kaydet).pack(anchor="e", pady=(12, 0))

    ttk.Button(arac, text="Yenile", command=yenile).pack(side="right", padx=2)
    ttk.Button(arac, text="Hesap Bağla", command=bagla).pack(side="right", padx=2)
    ttk.Button(arac, text="Önerilen Hesapları Oluştur", command=oneri).pack(side="right", padx=2)
    yenile()


# ---------- Hesap Planı ----------


def hesap_plani_goster(app):
    app._icerigi_temizle()
    _menu_isaretle(app)
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="HESAP PLANI", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Genel Muhasebe", command=lambda: _geri(app)).pack(side="right")
    _ust_bilgi(app.icerik)

    arac = ttk.Frame(app.icerik)
    arac.pack(fill="x", pady=(0, 8))
    ttk.Label(arac, text="Ara:").pack(side="left")
    arama = ttk.Entry(arac, width=28)
    arama.pack(side="left", padx=6)
    sadece_aktif = tk.BooleanVar(value=True)
    ttk.Checkbutton(arac, text="Yalnız aktif", variable=sadece_aktif).pack(side="left", padx=8)

    kolonlar = (
        "kod",
        "ad",
        "seviye",
        "tur",
        "borc",
        "alacak",
        "bakiye",
        "durum",
    )
    tablo = ttk.Treeview(app.icerik, columns=kolonlar, show="headings", height=18)
    basliklar = {
        "kod": "Hesap Kodu",
        "ad": "Hesap Adı",
        "seviye": "Seviye",
        "tur": "Tür",
        "borc": "Borç Toplamı",
        "alacak": "Alacak Toplamı",
        "bakiye": "Bakiye",
        "durum": "Durum",
    }
    genislik = {
        "kod": 100,
        "ad": 260,
        "seviye": 60,
        "tur": 80,
        "borc": 110,
        "alacak": 110,
        "bakiye": 110,
        "durum": 70,
    }
    for k in kolonlar:
        tablo.heading(k, text=basliklar[k])
        tablo.column(k, width=genislik[k], anchor="w" if k in ("kod", "ad", "tur") else "e")
    tablo.pack(fill="both", expand=True)

    kayitlar: dict[str, dict] = {}

    def yenile():
        tablo.delete(*tablo.get_children())
        kayitlar.clear()
        try:
            liste = HesapPlanService.listele(
                arama=arama.get(), sadece_aktif=sadece_aktif.get()
            )
        except Exception as hata:
            messagebox.showerror("Hesap Planı", str(hata), parent=app)
            return
        for h in liste:
            iid = str(h["id"])
            kayitlar[iid] = h
            tablo.insert(
                "",
                "end",
                iid=iid,
                values=(
                    h["hesap_kodu"],
                    h["hesap_adi"],
                    h["hesap_seviyesi"],
                    h["hesap_turu"],
                    para_goster(h["borc_toplam"]),
                    para_goster(h["alacak_toplam"]),
                    para_goster(h["bakiye"]),
                    "Aktif" if h["aktif"] else "Pasif",
                ),
            )

    def secili_id():
        sec = tablo.selection()
        return int(sec[0]) if sec else None

    def ekle():
        HesapDialog(app, on_save=yenile)

    def alt_hesap_ekle():
        hid = secili_id()
        if not hid:
            messagebox.showinfo("Seçim", "Üst hesap için bir satır seçin.", parent=app)
            return
        ust = kayitlar.get(str(hid))
        if not ust:
            messagebox.showinfo("Seçim", "Hesap bulunamadı.", parent=app)
            return
        if not ust.get("aktif", True):
            messagebox.showwarning("Hesap", "Pasif hesabın altına hesap eklenemez.", parent=app)
            return
        HesapDialog(app, on_save=yenile, ust_hesap=ust)

    def duzenle():
        hid = secili_id()
        if not hid:
            messagebox.showinfo("Seçim", "Hesap seçin.", parent=app)
            return
        HesapDialog(app, hesap_id=hid, on_save=yenile)

    def pasif():
        hid = secili_id()
        if not hid:
            messagebox.showinfo("Seçim", "Hesap seçin.", parent=app)
            return
        if not messagebox.askyesno("Pasife al", "Hesap pasife alınsın mı?", parent=app):
            return
        try:
            HesapPlanService.pasife_al(hid)
            yenile()
        except Exception as hata:
            messagebox.showerror("Hesap", str(hata), parent=app)

    def sag_tik(event):
        row = tablo.identify_row(event.y)
        if not row:
            return
        tablo.selection_set(row)
        tablo.focus(row)
        menu = tk.Menu(tablo, tearoff=0)
        menu.add_command(label="Alt Hesap Ekle", command=alt_hesap_ekle)
        menu.add_command(label="Düzenle", command=duzenle)
        menu.add_separator()
        menu.add_command(label="Pasife Al", command=pasif)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def tdhp_yukle():
        if not messagebox.askyesno(
            "Tek Düzen Hesap Planı",
            "Türkiye Tek Düzen Hesap Planı ana hesapları (sınıf, grup ve 3 haneli)\n"
            "yüklensin mi?\n\nMevcut hesaplar silinmez; yalnızca eksikler eklenir.",
            parent=app,
        ):
            return
        try:
            n = MuhasebeService.ana_hesaplari_doldur()
            MuhasebeService.esleme_sablonlarini_doldur()
            messagebox.showinfo(
                "Hesap Planı",
                f"Tek Düzen ana hesaplar yüklendi.\nYeni eklenen: {n}",
                parent=app,
            )
            yenile()
        except Exception as hata:
            messagebox.showerror("Hesap Planı", str(hata), parent=app)

    tablo.bind("<Button-3>", sag_tik)
    # Windows'ta bazı temalarda Button-2 / Control-Button-1 de sağ tık sayılır
    tablo.bind("<Button-2>", sag_tik)
    tablo.bind("<Control-Button-1>", sag_tik)

    ttk.Button(arac, text="Yenile", command=yenile).pack(side="right", padx=2)
    ttk.Button(arac, text="Pasife Al", command=pasif).pack(side="right", padx=2)
    ttk.Button(arac, text="Düzenle", command=duzenle).pack(side="right", padx=2)
    ttk.Button(arac, text="Alt Hesap Ekle", command=alt_hesap_ekle).pack(side="right", padx=2)
    ttk.Button(arac, text="Yeni Hesap", command=ekle).pack(side="right", padx=2)
    ttk.Button(arac, text="Tek Düzen Planı Yükle", command=tdhp_yukle).pack(side="right", padx=2)
    arama.bind("<Return>", lambda _e: yenile())
    yenile()


def _oneri_alt_hesap_kodu(ust_kod: str, yeni_seviye: int | None = None) -> str:
    """Üst hesap koduna göre noktalı sıralı alt kod önerir.

    Noktasız üst (örn. 120) → 2 haneli: 120.01, 120.02, ...
    Noktalı üst (örn. 120.01) → 4 haneli: 120.01.0001, 120.01.0002, ...
    """
    del yeni_seviye  # biçim üst kodun nokta yapısına göre belirlenir
    ust_kod = (ust_kod or "").strip()
    if not ust_kod:
        return ""

    hane = 2 if ust_kod.count(".") == 0 else 4
    prefix = f"{ust_kod}."
    try:
        mevcutlar = [
            str(h["hesap_kodu"]).strip()
            for h in HesapPlanService.listele(arama=ust_kod, sadece_aktif=False)
        ]
    except Exception:
        mevcutlar = []

    max_n = 0
    for kod in mevcutlar:
        if not kod.startswith(prefix):
            continue
        son = kod[len(prefix) :]
        if "." in son:
            continue
        if len(son) == hane and son.isdigit():
            max_n = max(max_n, int(son))

    sonraki = max_n + 1
    limit = 10**hane
    if sonraki >= limit:
        return f"{prefix}{sonraki}"
    return f"{prefix}{sonraki:0{hane}d}"


class HesapDialog(tk.Toplevel):
    def __init__(
        self,
        parent,
        *,
        hesap_id: int | None = None,
        on_save=None,
        ust_hesap: dict | None = None,
    ):
        super().__init__(parent)
        self.title("Alt Hesap" if ust_hesap and not hesap_id else "Hesap Kartı")
        self.resizable(False, False)
        self.hesap_id = hesap_id
        self.on_save = on_save
        self.ust_hesap = ust_hesap
        self.transient(parent)
        self.grab_set()

        frm = ttk.Frame(self, padding=16)
        frm.pack(fill="both", expand=True)

        mevcut = HesapPlanService.getir(hesap_id) if hesap_id else None
        satir = 0

        if ust_hesap and not hesap_id:
            ttk.Label(
                frm,
                text=f"Üst hesap: {ust_hesap['hesap_kodu']} — {ust_hesap['hesap_adi']}",
                font=("Segoe UI", 10, "bold"),
            ).grid(row=satir, column=0, columnspan=2, sticky="w", pady=(0, 8))
            satir += 1

        ttk.Label(frm, text="Hesap Kodu:").grid(row=satir, column=0, sticky="w", pady=4)
        self.kod = ttk.Entry(frm, width=24)
        self.kod.grid(row=satir, column=1, pady=4)
        satir += 1
        ttk.Label(frm, text="Hesap Adı:").grid(row=satir, column=0, sticky="w", pady=4)
        self.ad = ttk.Entry(frm, width=40)
        self.ad.grid(row=satir, column=1, pady=4)
        satir += 1
        ttk.Label(frm, text="Hesap Türü:").grid(row=satir, column=0, sticky="w", pady=4)
        self.tur = ttk.Combobox(frm, values=list(HESAP_TURLERI), state="readonly", width=22)
        self.tur.grid(row=satir, column=1, sticky="w", pady=4)
        self.tur.set("Aktif")
        satir += 1
        ttk.Label(frm, text="Üst Hesap:").grid(row=satir, column=0, sticky="w", pady=4)
        self.ust = ttk.Entry(frm, width=24)
        self.ust.grid(row=satir, column=1, pady=4)
        satir += 1
        ttk.Label(frm, text="Seviye:").grid(row=satir, column=0, sticky="w", pady=4)
        self.seviye = ttk.Entry(frm, width=24)
        self.seviye.grid(row=satir, column=1, pady=4)
        self.seviye.insert(0, "1")
        satir += 1

        if mevcut:
            self.kod.insert(0, mevcut["hesap_kodu"])
            self.kod.configure(state="disabled")
            self.ad.insert(0, mevcut["hesap_adi"])
            self.tur.set(mevcut["hesap_turu"])
            if mevcut["ust_hesap_id"]:
                self.ust.insert(0, str(mevcut["ust_hesap_id"]))
            self.seviye.delete(0, "end")
            self.seviye.insert(0, str(mevcut["hesap_seviyesi"]))
        elif ust_hesap:
            self.ust.insert(0, str(ust_hesap["id"]))
            self.ust.configure(state="disabled")
            self.tur.set(ust_hesap.get("hesap_turu") or "Aktif")
            yeni_seviye = int(ust_hesap.get("hesap_seviyesi") or 1) + 1
            self.seviye.delete(0, "end")
            self.seviye.insert(0, str(yeni_seviye))
            self.seviye.configure(state="disabled")
            oneri = _oneri_alt_hesap_kodu(ust_hesap.get("hesap_kodu") or "", yeni_seviye)
            if oneri:
                self.kod.insert(0, oneri)
            self.ad.focus_set()

        ttk.Button(frm, text="Kaydet", command=self._kaydet).grid(
            row=satir, column=1, sticky="e", pady=(12, 0)
        )

    def _kaydet(self):
        try:
            ust = self.ust.get().strip()
            if self.ust_hesap and not self.hesap_id:
                ust = str(self.ust_hesap["id"])
            seviye_txt = self.seviye.get().strip()
            if self.ust_hesap and not self.hesap_id:
                seviye = int(self.ust_hesap.get("hesap_seviyesi") or 1) + 1
            else:
                seviye = int(seviye_txt or 1)
            veriler = {
                "hesap_kodu": self.kod.get().strip(),
                "hesap_adi": self.ad.get().strip(),
                "hesap_turu": self.tur.get(),
                "ust_hesap_id": int(ust) if ust else None,
                "hesap_seviyesi": seviye,
                "aktif": True,
            }
            if self.hesap_id:
                HesapPlanService.guncelle(self.hesap_id, veriler)
            else:
                HesapPlanService.ekle(veriler)
        except Exception as hata:
            messagebox.showerror("Hesap", str(hata), parent=self)
            return
        if self.on_save:
            self.on_save()
        self.destroy()


# ---------- Fişler ----------


def fisler_goster(app):
    app._icerigi_temizle()
    _menu_isaretle(app)
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="MUHASEBE FİŞLERİ", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Genel Muhasebe", command=lambda: _geri(app)).pack(side="right")
    _ust_bilgi(app.icerik)

    filtre = ttk.Frame(app.icerik)
    filtre.pack(fill="x", pady=(0, 8))
    ttk.Label(filtre, text="Başlangıç:").pack(side="left")
    bas = ttk.Entry(filtre, width=12)
    bas.pack(side="left", padx=4)
    bas.insert(0, date.today().replace(month=1, day=1).strftime("%d.%m.%Y"))
    ttk.Label(filtre, text="Bitiş:").pack(side="left")
    bit = ttk.Entry(filtre, width=12)
    bit.pack(side="left", padx=4)
    bit.insert(0, date.today().strftime("%d.%m.%Y"))

    kolonlar = ("no", "tarih", "tur", "aciklama", "borc", "alacak", "durum")
    tablo = ttk.Treeview(app.icerik, columns=kolonlar, show="headings", height=16)
    for k, t, w in (
        ("no", "Fiş No", 120),
        ("tarih", "Tarih", 90),
        ("tur", "Tür", 110),
        ("aciklama", "Açıklama", 260),
        ("borc", "Borç", 100),
        ("alacak", "Alacak", 100),
        ("durum", "Durum", 90),
    ):
        tablo.heading(k, text=t)
        tablo.column(k, width=w)
    tablo.pack(fill="both", expand=True)

    def yenile():
        tablo.delete(*tablo.get_children())
        try:
            liste = MuhasebeFisService.listele(
                baslangic=_tarih_parse(bas.get()),
                bitis=_tarih_parse(bit.get()),
            )
        except Exception as hata:
            messagebox.showerror("Fişler", str(hata), parent=app)
            return
        for f in liste:
            tablo.insert(
                "",
                "end",
                iid=str(f["id"]),
                values=(
                    f["fis_no"],
                    f["fis_tarihi"].strftime("%d.%m.%Y"),
                    f["fis_turu"],
                    f["aciklama"][:60],
                    para_goster(f["toplam_borc"]),
                    para_goster(f["toplam_alacak"]),
                    f["durum"],
                ),
            )

    def yeni():
        FisDialog(app, on_save=yenile)

    def ac():
        sec = tablo.selection()
        if not sec:
            messagebox.showinfo("Seçim", "Fiş seçin.", parent=app)
            return
        FisDialog(app, fis_id=int(sec[0]), on_save=yenile)

    def iptal():
        sec = tablo.selection()
        if not sec:
            messagebox.showinfo("Seçim", "Fiş seçin.", parent=app)
            return
        if not messagebox.askyesno("İptal", "Fiş iptal edilsin mi? (ters kayıt)", parent=app):
            return
        try:
            MuhasebeFisService.iptal(int(sec[0]))
            yenile()
        except Exception as hata:
            messagebox.showerror("İptal", str(hata), parent=app)

    ttk.Button(filtre, text="Yenile", command=yenile).pack(side="right", padx=2)
    ttk.Button(filtre, text="İptal / Ters Kayıt", command=iptal).pack(side="right", padx=2)
    ttk.Button(filtre, text="Aç / Düzenle", command=ac).pack(side="right", padx=2)
    ttk.Button(filtre, text="Yeni Fiş", command=yeni).pack(side="right", padx=2)
    yenile()


class FisDialog(tk.Toplevel):
    def __init__(self, parent, *, fis_id: int | None = None, on_save=None):
        super().__init__(parent)
        self.title("Muhasebe Fişi")
        self.geometry("980x560")
        self.fis_id = fis_id
        self.on_save = on_save
        self.transient(parent)
        self.grab_set()

        ust = ttk.Frame(self, padding=10)
        ust.pack(fill="x")
        ttk.Label(ust, text="Fiş No:").grid(row=0, column=0, sticky="w")
        self.fis_no = ttk.Label(ust, text="(yeni)")
        self.fis_no.grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(ust, text="Tarih:").grid(row=0, column=2, sticky="w", padx=(16, 0))
        self.tarih = ttk.Entry(ust, width=12)
        self.tarih.grid(row=0, column=3, padx=4)
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        ttk.Label(ust, text="Tür:").grid(row=0, column=4, sticky="w", padx=(12, 0))
        self.tur = ttk.Combobox(ust, values=list(FIS_TURLERI), state="readonly", width=16)
        self.tur.grid(row=0, column=5, padx=4)
        self.tur.set(FIS_TURLERI[0])
        ttk.Label(ust, text="Belge No:").grid(row=1, column=0, sticky="w", pady=6)
        self.belge = ttk.Entry(ust, width=18)
        self.belge.grid(row=1, column=1, sticky="w", padx=6)
        ttk.Label(ust, text="Açıklama:").grid(row=1, column=2, sticky="w")
        self.aciklama = ttk.Entry(ust, width=50)
        self.aciklama.grid(row=1, column=3, columnspan=3, sticky="ew", padx=4)

        orta = ttk.Frame(self, padding=(10, 0))
        orta.pack(fill="both", expand=True)
        kolonlar = ("kod", "ad", "aciklama", "borc", "alacak", "btarih", "bno")
        self.tablo = ttk.Treeview(orta, columns=kolonlar, show="headings", height=12)
        for k, t, w in (
            ("kod", "Hesap Kodu", 90),
            ("ad", "Hesap Adı", 180),
            ("aciklama", "Açıklama", 180),
            ("borc", "Borç", 90),
            ("alacak", "Alacak", 90),
            ("btarih", "Belge Tarihi", 90),
            ("bno", "Belge No", 90),
        ):
            self.tablo.heading(k, text=t)
            self.tablo.column(k, width=w)
        self.tablo.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(orta, orient="vertical", command=self.tablo.yview)
        sb.pack(side="right", fill="y")
        self.tablo.configure(yscrollcommand=sb.set)

        satir_frm = ttk.LabelFrame(
            self,
            text="Satır ekle (yalnızca alt hesap: 120.01.0001)",
            padding=8,
        )
        satir_frm.pack(fill="x", padx=10, pady=6)
        ttk.Label(satir_frm, text="Hesap kodu:").pack(side="left")
        self.s_kod = ttk.Entry(satir_frm, width=12)
        self.s_kod.pack(side="left", padx=4)
        ttk.Label(satir_frm, text="Borç:").pack(side="left")
        self.s_borc = ttk.Entry(satir_frm, width=10)
        self.s_borc.pack(side="left", padx=4)
        ttk.Label(satir_frm, text="Alacak:").pack(side="left")
        self.s_alacak = ttk.Entry(satir_frm, width=10)
        self.s_alacak.pack(side="left", padx=4)
        ttk.Label(satir_frm, text="Açıklama:").pack(side="left")
        self.s_acik = ttk.Entry(satir_frm, width=24)
        self.s_acik.pack(side="left", padx=4)
        ttk.Button(satir_frm, text="Satır Ekle", command=self._satir_ekle).pack(side="left", padx=6)
        ttk.Button(satir_frm, text="Satır Sil", command=self._satir_sil).pack(side="left")

        alt = ttk.Frame(self, padding=10)
        alt.pack(fill="x")
        self.lbl_borc = ttk.Label(alt, text="Toplam Borç: 0,00")
        self.lbl_borc.pack(side="left")
        self.lbl_alacak = ttk.Label(alt, text="Toplam Alacak: 0,00")
        self.lbl_alacak.pack(side="left", padx=16)
        self.lbl_fark = ttk.Label(alt, text="Fark: 0,00")
        self.lbl_fark.pack(side="left", padx=16)
        ttk.Button(alt, text="Taslak Kaydet", command=lambda: self._kaydet("Taslak")).pack(
            side="right", padx=4
        )
        ttk.Button(
            alt, text="Kesinleştir", command=lambda: self._kaydet("Kesinleşmiş")
        ).pack(side="right", padx=4)

        self._satir_verileri: list[dict] = []
        if fis_id:
            self._yukle()
        self._toplamlari_guncelle()

    def _yukle(self):
        data = MuhasebeFisService.getir(self.fis_id)
        if not data:
            return
        self.fis_no.configure(text=data["fis_no"])
        self.tarih.delete(0, "end")
        self.tarih.insert(0, data["fis_tarihi"].strftime("%d.%m.%Y"))
        self.tur.set(data["fis_turu"])
        self.belge.insert(0, data["belge_no"])
        self.aciklama.insert(0, data["aciklama"])
        for s in data["satirlar"]:
            self._satir_verileri.append(
                {
                    "hesap_id": s["hesap_id"],
                    "hesap_kodu": s["hesap_kodu"],
                    "hesap_adi": s["hesap_adi"],
                    "aciklama": s["aciklama"],
                    "borc": s["borc"],
                    "alacak": s["alacak"],
                    "belge_tarihi": s["belge_tarihi"],
                    "belge_no": s["belge_no"],
                }
            )
        self._tabloyu_doldur()
        if data["durum"] == "Kesinleşmiş":
            messagebox.showinfo(
                "Fiş",
                "Kesinleşmiş fiş salt okunur. Değişiklik için iptal/ters kayıt kullanın.",
                parent=self,
            )

    def _tabloyu_doldur(self):
        self.tablo.delete(*self.tablo.get_children())
        for i, s in enumerate(self._satir_verileri):
            bt = s["belge_tarihi"].strftime("%d.%m.%Y") if s.get("belge_tarihi") else ""
            self.tablo.insert(
                "",
                "end",
                iid=str(i),
                values=(
                    s["hesap_kodu"],
                    s["hesap_adi"],
                    s.get("aciklama") or "",
                    para_goster(s["borc"]),
                    para_goster(s["alacak"]),
                    bt,
                    s.get("belge_no") or "",
                ),
            )
        self._toplamlari_guncelle()

    def _satir_ekle(self):
        kod = self.s_kod.get().strip()
        if not kod:
            messagebox.showwarning("Satır", "Hesap kodu girin.", parent=self)
            return
        try:
            fis_alt_hesap_zorunlu(kod)
        except ValueError as hata:
            messagebox.showerror("Hesap", str(hata), parent=self)
            return
        try:
            hesaplar = HesapPlanService.listele(arama=kod, sadece_aktif=True)
        except Exception as hata:
            messagebox.showerror("Hesap", str(hata), parent=self)
            return
        hesap = next((h for h in hesaplar if h["hesap_kodu"] == kod), None)
        if hesap is None:
            messagebox.showwarning(
                "Hesap",
                "Aktif alt hesap bulunamadı.\nÖrnek: 120.01.0001",
                parent=self,
            )
            return
        if not fis_icin_alt_hesap_mi(hesap["hesap_kodu"]):
            messagebox.showerror(
                "Hesap",
                f"Bu hesaba fiş yazılamaz: {hesap['hesap_kodu']}\n\n"
                "Yalnızca 120.01.0001 biçimindeki alt hesaplar kullanılabilir.",
                parent=self,
            )
            return
        try:
            borc = decimal(self.s_borc.get() or 0)
            alacak = decimal(self.s_alacak.get() or 0)
        except Exception:
            messagebox.showwarning("Tutar", "Borç/alacak geçersiz.", parent=self)
            return
        self._satir_verileri.append(
            {
                "hesap_id": hesap["id"],
                "hesap_kodu": hesap["hesap_kodu"],
                "hesap_adi": hesap["hesap_adi"],
                "aciklama": self.s_acik.get().strip(),
                "borc": borc,
                "alacak": alacak,
                "belge_tarihi": None,
                "belge_no": "",
            }
        )
        self.s_kod.delete(0, "end")
        self.s_borc.delete(0, "end")
        self.s_alacak.delete(0, "end")
        self.s_acik.delete(0, "end")
        self._tabloyu_doldur()

    def _satir_sil(self):
        sec = self.tablo.selection()
        if not sec:
            return
        idx = int(sec[0])
        if 0 <= idx < len(self._satir_verileri):
            del self._satir_verileri[idx]
            self._tabloyu_doldur()

    def _toplamlari_guncelle(self):
        tb = sum((decimal(s["borc"]) for s in self._satir_verileri), Decimal("0"))
        ta = sum((decimal(s["alacak"]) for s in self._satir_verileri), Decimal("0"))
        fark = tb - ta
        self.lbl_borc.configure(text=f"Toplam Borç: {para_goster(tb)}")
        self.lbl_alacak.configure(text=f"Toplam Alacak: {para_goster(ta)}")
        renk = "#c62828" if fark != 0 else "#2e7d32"
        self.lbl_fark.configure(text=f"Fark: {para_goster(fark)}", foreground=renk)

    def _kaydet(self, durum: str):
        try:
            veriler = {
                "fis_tarihi": _tarih_parse(self.tarih.get()),
                "fis_turu": self.tur.get(),
                "aciklama": self.aciklama.get(),
                "belge_no": self.belge.get(),
                "durum": durum,
                "satirlar": self._satir_verileri,
            }
            MuhasebeFisService.kaydet(veriler, fis_id=self.fis_id)
        except Exception as hata:
            messagebox.showerror("Fiş", str(hata), parent=self)
            return
        if self.on_save:
            self.on_save()
        self.destroy()


# ---------- Raporlar ----------


def _rapor_ust(app, baslik: str, bas_var, bit_var, yenile, excel, pdf):
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text=baslik, style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Genel Muhasebe", command=lambda: _geri(app)).pack(side="right")
    _ust_bilgi(app.icerik)
    filtre = ttk.Frame(app.icerik)
    filtre.pack(fill="x", pady=(0, 8))
    ttk.Label(filtre, text="Başlangıç:").pack(side="left")
    bas_var.pack(side="left", padx=4)
    ttk.Label(filtre, text="Bitiş:").pack(side="left")
    bit_var.pack(side="left", padx=4)
    ttk.Button(filtre, text="PDF Oluştur", command=pdf).pack(side="right", padx=2)
    ttk.Button(filtre, text="Excel'e Aktar", command=excel).pack(side="right", padx=2)
    ttk.Button(filtre, text="Yenile", command=yenile).pack(side="right", padx=2)
    return filtre


def mizan_goster(app):
    app._icerigi_temizle()
    _menu_isaretle(app)
    bas = ttk.Entry(width=12)
    bit = ttk.Entry(width=12)
    bas.insert(0, date.today().replace(month=1, day=1).strftime("%d.%m.%Y"))
    bit.insert(0, date.today().strftime("%d.%m.%Y"))

    kolonlar = ("kod", "ad", "ob", "oa", "db", "da", "bb", "ab")
    tablo = ttk.Treeview(app.icerik, columns=kolonlar, show="headings", height=16)
    for k, t, w in (
        ("kod", "Hesap Kodu", 90),
        ("ad", "Hesap Adı", 200),
        ("ob", "Önceki Borç", 95),
        ("oa", "Önceki Alacak", 95),
        ("db", "Dönem Borç", 95),
        ("da", "Dönem Alacak", 95),
        ("bb", "Borç Bakiyesi", 95),
        ("ab", "Alacak Bakiyesi", 95),
    ):
        tablo.heading(k, text=t)
        tablo.column(k, width=w)
    uyari = ttk.Label(app.icerik, text="")
    son_data = {"mizan": None}

    def yenile():
        tablo.delete(*tablo.get_children())
        try:
            data = MuhasebeRaporService.mizan(_tarih_parse(bas.get()), _tarih_parse(bit.get()))
        except Exception as hata:
            messagebox.showerror("Mizan", str(hata), parent=app)
            return
        son_data["mizan"] = data
        for s in data["satirlar"]:
            tablo.insert(
                "",
                "end",
                values=(
                    s["hesap_kodu"],
                    s["hesap_adi"],
                    para_goster(s["onceki_borc"]),
                    para_goster(s["onceki_alacak"]),
                    para_goster(s["donem_borc"]),
                    para_goster(s["donem_alacak"]),
                    para_goster(s["borc_bakiyesi"]),
                    para_goster(s["alacak_bakiyesi"]),
                ),
            )
        t = data["toplamlar"]
        tablo.insert(
            "",
            "end",
            values=(
                "",
                "GENEL TOPLAM",
                para_goster(t["onceki_borc"]),
                para_goster(t["onceki_alacak"]),
                para_goster(t["donem_borc"]),
                para_goster(t["donem_alacak"]),
                para_goster(t["borc_bakiyesi"]),
                para_goster(t["alacak_bakiyesi"]),
            ),
        )
        if data["dengeli"]:
            uyari.configure(text="Mizan dengede.", foreground="#2e7d32")
        else:
            uyari.configure(
                text="Uyarı: Toplam borç bakiyesi ile alacak bakiyesi eşit değil.",
                foreground="#c62828",
            )

    def excel():
        data = son_data["mizan"]
        if not data:
            yenile()
            data = son_data["mizan"]
        if not data:
            return
        yol = filedialog.asksaveasfilename(
            parent=app,
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialfile="mizan.xlsx",
        )
        if not yol:
            return
        satirlar = [
            [
                s["hesap_kodu"],
                s["hesap_adi"],
                float(s["onceki_borc"]),
                float(s["onceki_alacak"]),
                float(s["donem_borc"]),
                float(s["donem_alacak"]),
                float(s["borc_bakiyesi"]),
                float(s["alacak_bakiyesi"]),
            ]
            for s in data["satirlar"]
        ]
        try:
            MuhasebeRaporService.excel_aktar(
                "Mizan",
                [
                    "Hesap Kodu",
                    "Hesap Adı",
                    "Önceki Borç",
                    "Önceki Alacak",
                    "Dönem Borç",
                    "Dönem Alacak",
                    "Borç Bakiyesi",
                    "Alacak Bakiyesi",
                ],
                satirlar,
                Path(yol),
            )
            messagebox.showinfo("Excel", f"Kaydedildi:\n{yol}", parent=app)
        except Exception as hata:
            messagebox.showerror("Excel", str(hata), parent=app)

    def pdf():
        data = son_data["mizan"]
        if not data:
            yenile()
            data = son_data["mizan"]
        if not data:
            return
        yol = filedialog.asksaveasfilename(
            parent=app,
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
            initialfile="mizan.pdf",
        )
        if not yol:
            return
        lines = [
            f"{s['hesap_kodu']} {s['hesap_adi'][:40]} B:{para_goster(s['borc_bakiyesi'])} A:{para_goster(s['alacak_bakiyesi'])}"
            for s in data["satirlar"]
        ]
        try:
            MuhasebeRaporService.pdf_olustur("MIZAN", lines, Path(yol))
            messagebox.showinfo("PDF", f"Kaydedildi:\n{yol}", parent=app)
        except Exception as hata:
            messagebox.showerror("PDF", str(hata), parent=app)

    _rapor_ust(app, "MİZAN", bas, bit, yenile, excel, pdf)
    tablo.pack(fill="both", expand=True)
    uyari.pack(anchor="w", pady=6)
    yenile()


def bilanco_goster(app):
    app._icerigi_temizle()
    _menu_isaretle(app)
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="BİLANÇO", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Genel Muhasebe", command=lambda: _geri(app)).pack(side="right")
    _ust_bilgi(app.icerik)

    filtre = ttk.Frame(app.icerik)
    filtre.pack(fill="x", pady=(0, 8))
    ttk.Label(filtre, text="Bitiş Tarihi:").pack(side="left")
    bit = ttk.Entry(filtre, width=12)
    bit.pack(side="left", padx=4)
    bit.insert(0, date.today().strftime("%d.%m.%Y"))

    govde = ttk.Frame(app.icerik)
    govde.pack(fill="both", expand=True)
    govde.columnconfigure(0, weight=1)
    govde.columnconfigure(1, weight=1)

    sol = ttk.LabelFrame(govde, text="AKTİF (VARLIKLAR)", padding=8)
    sol.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
    sag = ttk.LabelFrame(govde, text="PASİF (KAYNAKLAR)", padding=8)
    sag.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

    aktif_agac = ttk.Treeview(sol, columns=("tutar",), show="tree headings", height=16)
    aktif_agac.heading("#0", text="Hesap / Grup")
    aktif_agac.heading("tutar", text="Tutar")
    aktif_agac.column("tutar", width=110, anchor="e")
    aktif_agac.pack(fill="both", expand=True)

    pasif_agac = ttk.Treeview(sag, columns=("tutar",), show="tree headings", height=16)
    pasif_agac.heading("#0", text="Hesap / Grup")
    pasif_agac.heading("tutar", text="Tutar")
    pasif_agac.column("tutar", width=110, anchor="e")
    pasif_agac.pack(fill="both", expand=True)

    ozet = ttk.Label(app.icerik, text="")
    ozet.pack(anchor="w", pady=8)
    son = {"data": None}

    def doldur(agac, gruplar):
        agac.delete(*agac.get_children())
        for g in gruplar:
            gid = agac.insert(
                "", "end", text=f"{g['kod']} {g['ad']}", values=(para_goster(g["toplam"]),)
            )
            for h in g["hesaplar"]:
                agac.insert(
                    gid,
                    "end",
                    text=f"{h['hesap_kodu']} {h['hesap_adi']}",
                    values=(para_goster(h["bakiye"]),),
                )

    def yenile():
        try:
            data = MuhasebeRaporService.bilanco(_tarih_parse(bit.get()))
        except Exception as hata:
            messagebox.showerror("Bilanço", str(hata), parent=app)
            return
        son["data"] = data
        doldur(aktif_agac, data["aktif"])
        doldur(pasif_agac, data["pasif"])
        if data["dengeli"]:
            ozet.configure(
                text=(
                    f"Aktif Toplamı: {para_goster(data['aktif_toplam'])}   |   "
                    f"Pasif Toplamı: {para_goster(data['pasif_toplam'])}   |   "
                    f"Fark: {para_goster(data['fark'])} — Bilanço dengede"
                ),
                foreground="#2e7d32",
            )
        else:
            ozet.configure(
                text=(
                    f"Aktif Toplamı: {para_goster(data['aktif_toplam'])}   |   "
                    f"Pasif Toplamı: {para_goster(data['pasif_toplam'])}   |   "
                    f"Fark: {para_goster(data['fark'])} — Bilanço dengede değil"
                ),
                foreground="#c62828",
            )

    def excel():
        if not son["data"]:
            yenile()
        data = son["data"]
        if not data:
            return
        yol = filedialog.asksaveasfilename(
            parent=app, defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")],
            initialfile="bilanco.xlsx",
        )
        if not yol:
            return
        satirlar = []
        for g in data["aktif"]:
            satirlar.append([f"AKTIF {g['kod']}", g["ad"], float(g["toplam"])])
            for h in g["hesaplar"]:
                satirlar.append([h["hesap_kodu"], h["hesap_adi"], float(h["bakiye"])])
        for g in data["pasif"]:
            satirlar.append([f"PASIF {g['kod']}", g["ad"], float(g["toplam"])])
            for h in g["hesaplar"]:
                satirlar.append([h["hesap_kodu"], h["hesap_adi"], float(h["bakiye"])])
        try:
            MuhasebeRaporService.excel_aktar(
                "Bilanco", ["Kod", "Ad", "Tutar"], satirlar, Path(yol)
            )
            messagebox.showinfo("Excel", f"Kaydedildi:\n{yol}", parent=app)
        except Exception as hata:
            messagebox.showerror("Excel", str(hata), parent=app)

    def pdf():
        if not son["data"]:
            yenile()
        data = son["data"]
        if not data:
            return
        yol = filedialog.asksaveasfilename(
            parent=app, defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
            initialfile="bilanco.pdf",
        )
        if not yol:
            return
        lines = [
            f"Aktif: {para_goster(data['aktif_toplam'])}",
            f"Pasif: {para_goster(data['pasif_toplam'])}",
            f"Fark: {para_goster(data['fark'])}",
        ]
        try:
            MuhasebeRaporService.pdf_olustur("BILANCO", lines, Path(yol))
            messagebox.showinfo("PDF", f"Kaydedildi:\n{yol}", parent=app)
        except Exception as hata:
            messagebox.showerror("PDF", str(hata), parent=app)

    ttk.Button(filtre, text="PDF Oluştur", command=pdf).pack(side="right", padx=2)
    ttk.Button(filtre, text="Excel'e Aktar", command=excel).pack(side="right", padx=2)
    ttk.Button(filtre, text="Yenile", command=yenile).pack(side="right", padx=2)
    yenile()


def gelir_tablosu_goster(app):
    app._icerigi_temizle()
    _menu_isaretle(app)
    bas = ttk.Entry(width=12)
    bit = ttk.Entry(width=12)
    bas.insert(0, date.today().replace(month=1, day=1).strftime("%d.%m.%Y"))
    bit.insert(0, date.today().strftime("%d.%m.%Y"))

    tablo = ttk.Treeview(app.icerik, columns=("tutar",), show="tree headings", height=18)
    tablo.heading("#0", text="Kalem")
    tablo.heading("tutar", text="Tutar (TL)")
    tablo.column("tutar", width=140, anchor="e")
    son = {"data": None}

    def yenile():
        tablo.delete(*tablo.get_children())
        try:
            data = MuhasebeRaporService.gelir_tablosu(
                _tarih_parse(bas.get()), _tarih_parse(bit.get())
            )
        except Exception as hata:
            messagebox.showerror("Gelir Tablosu", str(hata), parent=app)
            return
        son["data"] = data
        for ad, tutar, tip in data["kalemler"]:
            iid = tablo.insert("", "end", text=ad, values=(para_goster(tutar),))
            if tip == "net":
                renk = "#2e7d32" if tutar >= 0 else "#c62828"
                tablo.tag_configure("net", foreground=renk)
                tablo.item(iid, tags=("net",))

    def excel():
        if not son["data"]:
            yenile()
        data = son["data"]
        if not data:
            return
        yol = filedialog.asksaveasfilename(
            parent=app, defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")],
            initialfile="gelir_tablosu.xlsx",
        )
        if not yol:
            return
        satirlar = [[ad, float(t)] for ad, t, _ in data["kalemler"]]
        try:
            MuhasebeRaporService.excel_aktar(
                "Gelir", ["Kalem", "Tutar"], satirlar, Path(yol)
            )
            messagebox.showinfo("Excel", f"Kaydedildi:\n{yol}", parent=app)
        except Exception as hata:
            messagebox.showerror("Excel", str(hata), parent=app)

    def pdf():
        if not son["data"]:
            yenile()
        data = son["data"]
        if not data:
            return
        yol = filedialog.asksaveasfilename(
            parent=app, defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
            initialfile="gelir_tablosu.pdf",
        )
        if not yol:
            return
        lines = [f"{ad}: {para_goster(t)}" for ad, t, _ in data["kalemler"]]
        try:
            MuhasebeRaporService.pdf_olustur("GELIR TABLOSU", lines, Path(yol))
            messagebox.showinfo("PDF", f"Kaydedildi:\n{yol}", parent=app)
        except Exception as hata:
            messagebox.showerror("PDF", str(hata), parent=app)

    _rapor_ust(app, "GELİR TABLOSU", bas, bit, yenile, excel, pdf)
    tablo.pack(fill="both", expand=True)
    yenile()
