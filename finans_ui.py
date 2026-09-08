"""FİNANS menüsü — Kasalar, Bankalar, Çek-Senet."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from database.finans_service import FinansService
from database.models.finans import BANKA_ALT_HESAP_TURLERI, POS_KART_TIPLERI
from ui_takvim import takvim_butonu


def _para(tutar):
    return f"{float(tutar or 0):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def _tarih(t):
    return t.strftime("%d.%m.%Y") if t else ""


def _finans_menu_isaretle(app):
    for dugme_anahtari, dugme in app.menu_dugmeleri.items():
        dugme.configure(style="SeciliMenu.TButton" if dugme_anahtari == "finans" else "Menu.TButton")


def finans_menusu_goster(app):
    app._icerigi_temizle()
    _finans_menu_isaretle(app)
    ttk.Label(app.icerik, text="FİNANS", style="Baslik.TLabel").pack(anchor="w")
    ttk.Label(
        app.icerik,
        text="Kasa ve banka hesapları, hareketler ve çek-senet işlemleri.",
    ).pack(anchor="w", pady=(8, 0))
    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", pady=(24, 0))
    alt.columnconfigure(0, weight=1, minsize=520)
    for i, (baslik, komut) in enumerate((
        ("KASALAR", lambda: kasalar_sayfasi_goster(app)),
        ("BANKALAR", lambda: bankalar_sayfasi_goster(app)),
        ("ÇEK-SENET MODÜLÜ", lambda: cek_senet_menusu_goster(app)),
    )):
        ttk.Button(alt, text=baslik, style="AltMenu.TButton", command=komut).grid(
            row=i, column=0, sticky="ew", pady=4
        )


def cek_senet_menusu_goster(app):
    app._icerigi_temizle()
    _finans_menu_isaretle(app)
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="ÇEK-SENET MODÜLÜ", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Finans Menüsü", command=lambda: finans_menusu_goster(app)).pack(side="right")
    ttk.Label(
        app.icerik,
        text="Alınan / verilen çek ve senet portföyü bu bölümde yönetilecek.",
    ).pack(anchor="w", pady=(14, 8))
    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", pady=(8, 0))
    alt.columnconfigure(0, weight=1, minsize=520)
    for i, baslik in enumerate((
        "ALINAN ÇEKLER",
        "VERİLEN ÇEKLER",
        "ALINAN SENETLER",
        "VERİLEN SENETLER",
        "VADE TAKİBİ / RAPORLAR",
    )):
        ttk.Button(
            alt,
            text=baslik,
            style="AltMenu.TButton",
            command=lambda b=baslik: _cek_senet_bos(app, b),
        ).grid(row=i, column=0, sticky="ew", pady=4)


def _cek_senet_bos(app, baslik):
    app._icerigi_temizle()
    _finans_menu_isaretle(app)
    ttk.Label(app.icerik, text=baslik, style="Baslik.TLabel").pack(anchor="w")
    ttk.Label(
        app.icerik,
        text="Bu bölüm sonraki adımda hazırlanacaktır (kayıt, vade, tahsil/ödeme, portföy).",
    ).pack(anchor="w", pady=(18, 0))
    ttk.Button(app.icerik, text="← Çek-Senet Modülü", command=lambda: cek_senet_menusu_goster(app)).pack(
        anchor="w", pady=(16, 0)
    )


class HesapDialog(tk.Toplevel):
    """Kasa hesabı ekle / düzenle."""

    def __init__(self, parent, hesap_turu="KASA", hesap=None):
        super().__init__(parent)
        self.hesap_turu = hesap_turu
        self.hesap = hesap
        self.result = None
        self.title("Kasa" + (" Düzenle" if hesap else " Ekle"))
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)

        alanlar = [
            ("Hesap Adı", "hesap_adi"),
            ("Açılış Bakiyesi", "acilis_bakiyesi"),
            ("Açıklama", "aciklama"),
        ]
        self.girdiler = {}
        for i, (etiket, anahtar) in enumerate(alanlar):
            ttk.Label(self, text=etiket).grid(row=i, column=0, padx=12, pady=5, sticky="w")
            ent = ttk.Entry(self, width=40)
            ent.grid(row=i, column=1, padx=12, pady=5)
            self.girdiler[anahtar] = ent

        if hesap:
            self.girdiler["hesap_adi"].insert(0, hesap.hesap_adi or "")
            self.girdiler["acilis_bakiyesi"].insert(0, str(hesap.acilis_bakiyesi or 0))
            self.girdiler["aciklama"].insert(0, hesap.aciklama or "")
        else:
            self.girdiler["acilis_bakiyesi"].insert(0, "0")

        butonlar = ttk.Frame(self)
        butonlar.grid(row=len(alanlar), column=0, columnspan=2, padx=12, pady=12, sticky="e")
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(butonlar, text="Kaydet", command=self.kaydet).pack(side="right")

    def kaydet(self):
        veri = {k: w.get().strip() for k, w in self.girdiler.items()}
        veri["hesap_turu"] = self.hesap_turu
        if self.hesap:
            veri["hesap_id"] = self.hesap.id
        try:
            self.result = FinansService.hesap_kaydet(veri)
        except ValueError as hata:
            messagebox.showerror("Kayıt", str(hata), parent=self)
            return
        self.destroy()


class AltHesapIslemDialog(tk.Toplevel):
    """KMH / POS / Kredi kartı / Krediler — basit giriş-çıkış."""

    def __init__(self, parent, kart, alt_tur: str, alt_etiket: str):
        super().__init__(parent)
        self.parent_dlg = parent
        self.kart_id = kart.id
        self.alt_tur = alt_tur
        self.title(f"{kart.banka_adi} — {alt_etiket}")
        self.geometry("820x520")
        self.transient(parent)
        self.grab_set()

        ust = ttk.Frame(self, padding=10)
        ust.pack(fill="x")
        self.bakiye_lbl = ttk.Label(ust, text="", font=("Segoe UI", 11, "bold"))
        self.bakiye_lbl.pack(side="left")
        ttk.Button(ust, text="Kapat", command=self.destroy).pack(side="right")

        form = ttk.LabelFrame(self, text="Yeni işlem", padding=10)
        form.pack(fill="x", padx=10, pady=4)
        ttk.Label(form, text="Tarih:").grid(row=0, column=0, sticky="w")
        tarih_c = ttk.Frame(form)
        tarih_c.grid(row=0, column=1, sticky="w", padx=4)
        self.tarih = ttk.Entry(tarih_c, width=12)
        self.tarih.pack(side="left")
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        takvim_butonu(tarih_c, self.tarih)

        ttk.Label(form, text="Tutar:").grid(row=0, column=2, sticky="w", padx=(12, 0))
        self.tutar = ttk.Entry(form, width=14)
        self.tutar.grid(row=0, column=3, sticky="w", padx=4)

        ttk.Label(form, text="Açıklama:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.aciklama = ttk.Entry(form, width=50)
        self.aciklama.grid(row=1, column=1, columnspan=3, sticky="ew", padx=4, pady=(6, 0))

        butonlar = ttk.Frame(form)
        butonlar.grid(row=2, column=0, columnspan=4, sticky="w", pady=(8, 0))
        ttk.Button(butonlar, text="Giriş (+)", command=lambda: self._hareket("giris")).pack(side="left")
        ttk.Button(butonlar, text="Çıkış (−)", command=lambda: self._hareket("cikis")).pack(side="left", padx=8)
        ttk.Button(butonlar, text="Yenile", command=self.listeyi_yenile).pack(side="left")

        cerceve = ttk.Frame(self, padding=10)
        cerceve.pack(fill="both", expand=True)
        self.tablo = ttk.Treeview(
            cerceve,
            columns=("tarih", "tur", "belge", "giris", "cikis", "aciklama"),
            show="headings",
        )
        for k, b, w in (
            ("tarih", "Tarih", 90),
            ("tur", "Hareket", 120),
            ("belge", "Belge", 120),
            ("giris", "Giriş", 100),
            ("cikis", "Çıkış", 100),
            ("aciklama", "Açıklama", 260),
        ):
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=w, anchor="w")
        kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=kaydir.set)
        self.tablo.pack(side="left", fill="both", expand=True)
        kaydir.pack(side="right", fill="y")
        self.listeyi_yenile()

    def _hesap(self):
        kart = FinansService.banka_karti_getir(self.kart_id)
        if not kart:
            return None, None
        return kart, FinansService.banka_alt_hesap(kart, self.alt_tur)

    def listeyi_yenile(self):
        _kart, hesap = self._hesap()
        for item in self.tablo.get_children():
            self.tablo.delete(item)
        if not hesap:
            self.bakiye_lbl.configure(text="Hesap bulunamadı — önce banka kartını kaydedin.")
            return
        bak = FinansService.bakiye(hesap)
        self.bakiye_lbl.configure(text=f"{hesap.hesap_adi}  ·  Bakiye: {_para(bak)}")
        for har in FinansService.hareketler(hesap_id=hesap.id, limit=400):
            isaret = FinansService.hareket_isareti(har.hareket_turu)
            self.tablo.insert(
                "",
                "end",
                values=(
                    _tarih(har.tarih),
                    har.hareket_turu,
                    har.belge_no,
                    _para(har.tutar) if isaret > 0 else "",
                    _para(har.tutar) if isaret < 0 else "",
                    har.aciklama or "",
                ),
            )

    def _hareket(self, yon):
        _kart, hesap = self._hesap()
        if not hesap:
            messagebox.showwarning("Hesap", "Önce banka kartını kaydedin.", parent=self)
            return
        try:
            tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
            FinansService.banka_manuel_hareket(
                hesap.id,
                tarih,
                self.tutar.get(),
                yon,
                aciklama=self.aciklama.get().strip() or None,
            )
        except ValueError as hata:
            messagebox.showerror("İşlem", str(hata), parent=self)
            return
        self.tutar.delete(0, "end")
        self.aciklama.delete(0, "end")
        self.listeyi_yenile()
        if hasattr(self.parent_dlg, "bakiyeleri_yenile"):
            self.parent_dlg.bakiyeleri_yenile()


class MevduatEvrakDialog(tk.Toplevel):
    """Kasadan yatırma / havale / nakit çekme / banka virman evrak formu."""

    def __init__(self, parent, tur: str, mevduat_hesap_id: int):
        super().__init__(parent)
        self.tur = tur
        self.mevduat_hesap_id = mevduat_hesap_id
        self.result = None
        basliklar = {
            "kby": "Kasadan Bankaya Yatan",
            "ahv": "Alınan Havale",
            "ghv": "Gönderilen Havale",
            "bnc": "Bankadan Nakit Çekilen",
            "bvr": "Banka Hesapları Arası Virman",
        }
        self.title(basliklar.get(tur, "Mevduat Evrakı"))
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)

        from database.cari_service import CariService

        row = 0
        ttk.Label(self, text="Tarih").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        tarih_c = ttk.Frame(self)
        tarih_c.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.tarih = ttk.Entry(tarih_c, width=14)
        self.tarih.pack(side="left")
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        takvim_butonu(tarih_c, self.tarih)

        row = 1
        ttk.Label(self, text="Tutar").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.tutar = ttk.Entry(self, width=18)
        self.tutar.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        self.kasa = None
        self.cari = None
        self.hedef_hesap = None
        self.cari_map = {}
        self._kasa_map = {}
        self._hedef_map = {}

        if tur in ("kby", "bnc"):
            row = 2
            kasalar = FinansService.hesaplar(hesap_turu="KASA")
            ttk.Label(self, text="Kasa").grid(row=row, column=0, padx=12, pady=6, sticky="w")
            self.kasa = ttk.Combobox(
                self,
                values=[h.hesap_adi for h in kasalar],
                state="readonly",
                width=36,
            )
            self.kasa.grid(row=row, column=1, padx=12, pady=6, sticky="w")
            self._kasa_map = {h.hesap_adi: h.id for h in kasalar}
            if kasalar:
                self.kasa.set(kasalar[0].hesap_adi)
        elif tur == "bvr":
            row = 2
            hedefler = FinansService.banka_mevduat_hesaplari(haric_hesap_id=mevduat_hesap_id)
            ttk.Label(self, text="Hedef banka hesabı").grid(
                row=row, column=0, padx=12, pady=6, sticky="w"
            )
            self.hedef_hesap = ttk.Combobox(
                self,
                values=[h.hesap_adi for h in hedefler],
                state="readonly",
                width=36,
            )
            self.hedef_hesap.grid(row=row, column=1, padx=12, pady=6, sticky="w")
            self._hedef_map = {h.hesap_adi: h.id for h in hedefler}
            if hedefler:
                self.hedef_hesap.set(hedefler[0].hesap_adi)
            ttk.Label(
                self,
                text="Kaynak: bu mevduat hesabı → hedef hesaba virman",
                foreground="#555",
            ).grid(row=row + 1, column=0, columnspan=2, padx=12, sticky="w")
            row = 3
        elif tur == "ahv":
            row = 2
            cariler = CariService.listele()
            self.cari_map = {
                f"{o['cari'].cari_kodu} - {o['cari'].unvan}": o["cari"].id for o in cariler
            }
            ttk.Label(self, text="Cari *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
            self.cari = ttk.Combobox(self, values=list(self.cari_map), width=36)
            self.cari.grid(row=row, column=1, padx=12, pady=6, sticky="w")
            if self.cari_map:
                self.cari.set(next(iter(self.cari_map)))
        else:  # ghv — cari opsiyonel
            row = 2
            cariler = CariService.listele()
            self.cari_map = {
                f"{o['cari'].cari_kodu} - {o['cari'].unvan}": o["cari"].id for o in cariler
            }
            degerler = ["(Cari yok)"] + list(self.cari_map)
            ttk.Label(self, text="Cari (opsiyonel)").grid(
                row=row, column=0, padx=12, pady=6, sticky="w"
            )
            self.cari = ttk.Combobox(self, values=degerler, width=36)
            self.cari.set("(Cari yok)")
            self.cari.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        if tur != "bvr":
            row = 3
        ttk.Label(self, text="Açıklama").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.aciklama = ttk.Entry(self, width=40)
        self.aciklama.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        butonlar = ttk.Frame(self)
        butonlar.grid(row=row + 1, column=0, columnspan=2, padx=12, pady=12, sticky="e")
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(butonlar, text="Kaydet", command=self.kaydet).pack(side="right")

    def kaydet(self):
        try:
            tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
            acik = self.aciklama.get().strip() or None
            if self.tur == "kby":
                if not self.kasa or not self.kasa.get():
                    raise ValueError("Kasa seçin.")
                belge = FinansService.kasadan_bankaya_yatan(
                    self._kasa_map[self.kasa.get()],
                    self.mevduat_hesap_id,
                    tarih,
                    self.tutar.get(),
                    acik,
                )
            elif self.tur == "ahv":
                if not self.cari or not self.cari.get().strip():
                    raise ValueError("Alınan havale için cari seçimi zorunludur.")
                cari_id = self.cari_map.get(self.cari.get())
                if cari_id is None:
                    raise ValueError("Geçerli bir cari seçin.")
                belge = FinansService.alinan_havale(
                    self.mevduat_hesap_id, tarih, self.tutar.get(), cari_id=cari_id, aciklama=acik
                )
            elif self.tur == "ghv":
                cari_id = None
                if self.cari and self.cari.get() and self.cari.get() != "(Cari yok)":
                    cari_id = self.cari_map.get(self.cari.get())
                    if cari_id is None:
                        raise ValueError("Geçerli bir cari seçin.")
                belge = FinansService.gonderilen_havale(
                    self.mevduat_hesap_id, tarih, self.tutar.get(), cari_id=cari_id, aciklama=acik
                )
            elif self.tur == "bnc":
                if not self.kasa or not self.kasa.get():
                    raise ValueError("Kasa seçin.")
                belge = FinansService.bankadan_nakit_cekilen(
                    self.mevduat_hesap_id,
                    self._kasa_map[self.kasa.get()],
                    tarih,
                    self.tutar.get(),
                    acik,
                )
            elif self.tur == "bvr":
                if not self.hedef_hesap or not self.hedef_hesap.get():
                    raise ValueError("Hedef banka hesabını seçin.")
                hedef_id = self._hedef_map.get(self.hedef_hesap.get())
                if hedef_id is None:
                    raise ValueError("Geçerli bir hedef hesap seçin.")
                belge = FinansService.banka_hesaplari_arasi_virman(
                    self.mevduat_hesap_id,
                    hedef_id,
                    tarih,
                    self.tutar.get(),
                    acik,
                )
            else:
                raise ValueError("Bilinmeyen evrak türü.")
        except ValueError as hata:
            messagebox.showerror("Evrak", str(hata), parent=self)
            return
        self.result = belge
        messagebox.showinfo("Kaydedildi", f"Belge no: {belge}", parent=self)
        self.destroy()


class MevduatIslemleriDialog(tk.Toplevel):
    """Mevduat işlem menüsü + evraklar + hareket listesi."""

    def __init__(self, parent, kart):
        super().__init__(parent)
        self.parent_dlg = parent
        self.kart_id = kart.id
        self.title(f"{kart.banka_adi} — Mevduat İşlemleri")
        self.geometry("960x600")
        self.minsize(860, 520)
        self.transient(parent)
        self.grab_set()

        ust = ttk.Frame(self, padding=10)
        ust.pack(fill="x")
        self.bakiye_lbl = ttk.Label(ust, text="", font=("Segoe UI", 11, "bold"))
        self.bakiye_lbl.pack(side="left")
        ttk.Button(ust, text="Kapat", command=self.destroy).pack(side="right")

        menu = ttk.LabelFrame(self, text="Evraklar", padding=10)
        menu.pack(fill="x", padx=10, pady=4)
        for i, (kod, baslik) in enumerate((
            ("kby", "Kasadan Bankaya Yatan"),
            ("ahv", "Alınan Havale"),
            ("ghv", "Gönderilen Havale"),
            ("bnc", "Bankadan Nakit Çekilen"),
            ("bvr", "Banka Hesapları Arası Virman"),
        )):
            ttk.Button(
                menu,
                text=baslik,
                width=26,
                command=lambda t=kod: self._evrak_ac(t),
            ).grid(row=i // 3, column=i % 3, padx=4, pady=4, sticky="ew")
        for c in range(3):
            menu.columnconfigure(c, weight=1)

        orta = ttk.LabelFrame(self, text="Mevduat hesabı hareketleri", padding=8)
        orta.pack(fill="both", expand=True, padx=10, pady=6)
        ust2 = ttk.Frame(orta)
        ust2.pack(fill="x", pady=(0, 4))
        ttk.Button(ust2, text="Yenile", command=self.listeyi_yenile).pack(side="right")

        cerceve = ttk.Frame(orta)
        cerceve.pack(fill="both", expand=True)
        self.tablo = ttk.Treeview(
            cerceve,
            columns=("tarih", "tur", "belge", "cari", "giris", "cikis", "bakiye", "aciklama"),
            show="headings",
        )
        for k, b, w in (
            ("tarih", "Tarih", 85),
            ("tur", "Hareket / Evrak", 150),
            ("belge", "Belge No", 110),
            ("cari", "Cari", 170),
            ("giris", "Giriş", 85),
            ("cikis", "Çıkış", 85),
            ("bakiye", "Bakiye", 95),
            ("aciklama", "Açıklama", 180),
        ):
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=w, anchor="w")
        kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=kaydir.set)
        self.tablo.pack(side="left", fill="both", expand=True)
        kaydir.pack(side="right", fill="y")

        self.ozet = ttk.Label(self, text="")
        self.ozet.pack(anchor="w", padx=12, pady=(0, 8))
        self.listeyi_yenile()

    def _mevduat_hesap(self):
        kart = FinansService.banka_karti_getir(self.kart_id)
        if not kart:
            return None, None
        return kart, FinansService.banka_alt_hesap(kart, "MEVDUAT")

    def listeyi_yenile(self):
        kart, hesap = self._mevduat_hesap()
        for item in self.tablo.get_children():
            self.tablo.delete(item)
        if not hesap:
            self.bakiye_lbl.configure(text="Mevduat hesabı bulunamadı.")
            return
        bak = FinansService.bakiye(hesap)
        self.bakiye_lbl.configure(text=f"{hesap.hesap_adi}  ·  Bakiye: {_para(bak)}")
        hareketler = FinansService.mevduat_hareketleri(hesap.id)
        toplam_giris = Decimal("0")
        toplam_cikis = Decimal("0")
        for har in hareketler:
            toplam_giris += har["giris"]
            toplam_cikis += har["cikis"]
            self.tablo.insert(
                "",
                "end",
                values=(
                    _tarih(har["tarih"]),
                    har["hareket_turu"],
                    har["belge_no"],
                    har.get("cari") or "—",
                    _para(har["giris"]) if har["giris"] else "",
                    _para(har["cikis"]) if har["cikis"] else "",
                    _para(har.get("bakiye", 0)),
                    har["aciklama"],
                ),
            )
        self.ozet.configure(
            text=f"{len(hareketler)} hareket · Toplam giriş: {_para(toplam_giris)} · Toplam çıkış: {_para(toplam_cikis)}"
        )
        if hasattr(self.parent_dlg, "bakiyeleri_yenile"):
            self.parent_dlg.bakiyeleri_yenile()

    def _evrak_ac(self, tur):
        _kart, hesap = self._mevduat_hesap()
        if not hesap:
            messagebox.showwarning("Hesap", "Önce banka kartını kaydedin.", parent=self)
            return
        dialog = MevduatEvrakDialog(self, tur, hesap.id)
        self.wait_window(dialog)
        if dialog.result:
            self.listeyi_yenile()


class PosIslemleriDialog(tk.Toplevel):
    """POS tahsilat (komisyonlu) + valör bekleyenler + KMH aktarım + hareketler."""

    def __init__(self, parent, kart):
        super().__init__(parent)
        self.parent_dlg = parent
        self.kart_id = kart.id
        self.title(f"{kart.banka_adi} — POS İşlemleri")
        self.geometry("980x640")
        self.minsize(900, 560)
        self.transient(parent)
        self.grab_set()

        # Vadesi gelenleri hemen dene
        FinansService.pos_valor_vadesi_gelenleri_aktar(banka_karti_id=self.kart_id)

        ust = ttk.Frame(self, padding=10)
        ust.pack(fill="x")
        self.bakiye_lbl = ttk.Label(ust, text="", font=("Segoe UI", 11, "bold"))
        self.bakiye_lbl.pack(side="left")
        ttk.Button(ust, text="Kapat", command=self.destroy).pack(side="right")

        menu = ttk.LabelFrame(self, text="Evraklar", padding=10)
        menu.pack(fill="x", padx=10, pady=4)
        ttk.Button(menu, text="Kredi / Banka Kartı Tahsilat", command=self._tahsilat_ac).pack(
            side="left", padx=4
        )
        ttk.Button(menu, text="Valör Aktarımlarını Çalıştır", command=self._valor_calistir).pack(
            side="left", padx=4
        )
        ttk.Button(menu, text="Yenile", command=self.listeyi_yenile).pack(side="left", padx=4)

        bekleyen = ttk.LabelFrame(self, text="Valör bekleyen (net → KMH)", padding=8)
        bekleyen.pack(fill="x", padx=10, pady=4)
        self.valor_tablo = ttk.Treeview(
            bekleyen,
            columns=("belge", "tahsilat", "valor", "saat", "kart", "brut", "kom", "net", "durum"),
            show="headings",
            height=5,
        )
        for k, b, w in (
            ("belge", "Belge", 110),
            ("tahsilat", "Tahsilat", 85),
            ("valor", "Valör", 85),
            ("saat", "Saat", 55),
            ("kart", "Kart", 90),
            ("brut", "Brüt", 80),
            ("kom", "Komisyon", 80),
            ("net", "Net", 80),
            ("durum", "Durum", 80),
        ):
            self.valor_tablo.heading(k, text=b)
            self.valor_tablo.column(k, width=w, anchor="w")
        self.valor_tablo.pack(fill="x")

        orta = ttk.LabelFrame(self, text="POS hesabı hareketleri", padding=8)
        orta.pack(fill="both", expand=True, padx=10, pady=6)
        cerceve = ttk.Frame(orta)
        cerceve.pack(fill="both", expand=True)
        self.tablo = ttk.Treeview(
            cerceve,
            columns=("tarih", "tur", "belge", "cari", "giris", "cikis", "bakiye", "aciklama"),
            show="headings",
        )
        for k, b, w in (
            ("tarih", "Tarih", 85),
            ("tur", "Hareket", 150),
            ("belge", "Belge", 110),
            ("cari", "Cari", 160),
            ("giris", "Giriş", 85),
            ("cikis", "Çıkış", 85),
            ("bakiye", "Bakiye", 90),
            ("aciklama", "Açıklama", 180),
        ):
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=w, anchor="w")
        kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=kaydir.set)
        self.tablo.pack(side="left", fill="both", expand=True)
        kaydir.pack(side="right", fill="y")

        self.ozet = ttk.Label(self, text="")
        self.ozet.pack(anchor="w", padx=12, pady=(0, 8))
        self.listeyi_yenile()

    def _kart_hesaplar(self):
        kart = FinansService.banka_karti_getir(self.kart_id)
        if not kart:
            return None, None, None
        return (
            kart,
            FinansService.banka_alt_hesap(kart, "POS"),
            FinansService.banka_alt_hesap(kart, "KMH"),
        )

    def listeyi_yenile(self):
        FinansService.pos_valor_vadesi_gelenleri_aktar(banka_karti_id=self.kart_id)
        kart, pos, _kmh = self._kart_hesaplar()
        for item in self.tablo.get_children():
            self.tablo.delete(item)
        for item in self.valor_tablo.get_children():
            self.valor_tablo.delete(item)
        if not pos:
            self.bakiye_lbl.configure(text="POS hesabı bulunamadı.")
            return
        bak = FinansService.bakiye(pos)
        valor_gun = getattr(kart, "pos_valor_gun", 1) if kart else 1
        self.bakiye_lbl.configure(
            text=(
                f"{pos.hesap_adi}  ·  Bakiye: {_para(bak)}  ·  "
                f"KK %{kart.kk_komisyon_orani if kart else 0:g} / "
                f"Banka kartı %{kart.banka_karti_komisyon_orani if kart else 0:g}  ·  "
                f"Valör: {valor_gun} gün (08:00)"
            )
        )
        for kayit in FinansService.pos_valor_bekleyenler(banka_karti_id=self.kart_id):
            tip = dict(POS_KART_TIPLERI).get(kayit.kart_tipi, kayit.kart_tipi)
            self.valor_tablo.insert(
                "",
                "end",
                values=(
                    kayit.belge_no,
                    _tarih(kayit.tahsilat_tarihi),
                    _tarih(kayit.valor_tarihi),
                    kayit.valor_saati,
                    tip,
                    _para(kayit.brut_tutar),
                    _para(kayit.komisyon_tutari),
                    _para(kayit.net_tutar),
                    kayit.durum,
                ),
            )
        for har in FinansService.pos_hareketleri(pos.id):
            self.tablo.insert(
                "",
                "end",
                values=(
                    _tarih(har["tarih"]),
                    har["hareket_turu"],
                    har["belge_no"],
                    har.get("cari") or "—",
                    _para(har["giris"]) if har["giris"] else "",
                    _para(har["cikis"]) if har["cikis"] else "",
                    _para(har["bakiye"]),
                    har["aciklama"],
                ),
            )
        if hasattr(self.parent_dlg, "bakiyeleri_yenile"):
            self.parent_dlg.bakiyeleri_yenile()

    def _tahsilat_ac(self):
        dialog = PosTahsilatDialog(self, self.kart_id)
        self.wait_window(dialog)
        if dialog.result:
            self.listeyi_yenile()

    def _valor_calistir(self):
        sonuclar = FinansService.pos_valor_vadesi_gelenleri_aktar(banka_karti_id=self.kart_id)
        if not sonuclar:
            messagebox.showinfo(
                "Valör",
                "Aktarılacak vadesi gelmiş kayıt yok.\n"
                "(Valör günü + 08:00 şartı aranır.)",
                parent=self,
            )
        else:
            messagebox.showinfo(
                "Valör",
                f"{len(sonuclar)} kayıt KMH hesabına aktarıldı.",
                parent=self,
            )
        self.listeyi_yenile()


class PosTahsilatDialog(tk.Toplevel):
    def __init__(self, parent, banka_karti_id):
        super().__init__(parent)
        self.banka_karti_id = banka_karti_id
        self.result = None
        self.title("POS Tahsilat (Kredi / Banka Kartı)")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)

        from database.cari_service import CariService

        kart = FinansService.banka_karti_getir(banka_karti_id)
        ttk.Label(
            self,
            text=(
                f"KK komisyon %{kart.kk_komisyon_orani:g} · "
                f"Banka kartı %{kart.banka_karti_komisyon_orani:g} · "
                f"Valör {kart.pos_valor_gun} gün / 08:00 → KMH"
            ),
            foreground="#555",
        ).grid(row=0, column=0, columnspan=2, padx=12, pady=(10, 4), sticky="w")

        ttk.Label(self, text="Tarih").grid(row=1, column=0, padx=12, pady=6, sticky="w")
        tarih_c = ttk.Frame(self)
        tarih_c.grid(row=1, column=1, padx=12, pady=6, sticky="w")
        self.tarih = ttk.Entry(tarih_c, width=14)
        self.tarih.pack(side="left")
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        takvim_butonu(tarih_c, self.tarih)

        ttk.Label(self, text="Kart tipi").grid(row=2, column=0, padx=12, pady=6, sticky="w")
        self.kart_tipi = ttk.Combobox(
            self,
            values=[e for _k, e in POS_KART_TIPLERI],
            state="readonly",
            width=28,
        )
        self.kart_tipi.set("Kredi Kartı")
        self.kart_tipi.grid(row=2, column=1, padx=12, pady=6, sticky="w")
        self._tip_map = {e: k for k, e in POS_KART_TIPLERI}

        ttk.Label(self, text="Brüt tutar").grid(row=3, column=0, padx=12, pady=6, sticky="w")
        self.tutar = ttk.Entry(self, width=18)
        self.tutar.grid(row=3, column=1, padx=12, pady=6, sticky="w")

        cariler = CariService.listele()
        self.cari_map = {
            f"{o['cari'].cari_kodu} - {o['cari'].unvan}": o["cari"].id for o in cariler
        }
        ttk.Label(self, text="Cari (opsiyonel)").grid(row=4, column=0, padx=12, pady=6, sticky="w")
        self.cari = ttk.Combobox(self, values=["(Cari yok)"] + list(self.cari_map), width=36)
        self.cari.set("(Cari yok)")
        self.cari.grid(row=4, column=1, padx=12, pady=6, sticky="w")

        ttk.Label(self, text="Açıklama").grid(row=5, column=0, padx=12, pady=6, sticky="w")
        self.aciklama = ttk.Entry(self, width=40)
        self.aciklama.grid(row=5, column=1, padx=12, pady=6, sticky="w")

        butonlar = ttk.Frame(self)
        butonlar.grid(row=6, column=0, columnspan=2, padx=12, pady=12, sticky="e")
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(butonlar, text="Kaydet", command=self.kaydet).pack(side="right")

    def kaydet(self):
        try:
            tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
            tip = self._tip_map.get(self.kart_tipi.get(), "KREDI_KARTI")
            cari_id = None
            if self.cari.get() and self.cari.get() != "(Cari yok)":
                cari_id = self.cari_map.get(self.cari.get())
                if cari_id is None:
                    raise ValueError("Geçerli bir cari seçin.")
            self.result = FinansService.pos_tahsilat(
                self.banka_karti_id,
                tarih,
                self.tutar.get(),
                kart_tipi=tip,
                cari_id=cari_id,
                aciklama=self.aciklama.get().strip() or None,
            )
        except ValueError as hata:
            messagebox.showerror("POS Tahsilat", str(hata), parent=self)
            return
        r = self.result
        messagebox.showinfo(
            "Kaydedildi",
            f"Belge: {r['belge_no']}\n"
            f"Brüt: {_para(r['brut'])} · Komisyon: {_para(r['komisyon'])} · Net: {_para(r['net'])}\n"
            f"Valör: {r['valor_tarihi'].strftime('%d.%m.%Y')} {r['valor_saati']} → KMH",
            parent=self,
        )
        self.destroy()


class BankaAnaKartDialog(tk.Toplevel):
    """Banka ana kartı: sol bilgiler, sağ bakiyeler, alt işlem menüleri."""

    def __init__(self, parent, kart=None):
        super().__init__(parent)
        self.kart = kart
        self.result = None
        self.title("Banka Ana Kartı" + (f" — {kart.banka_adi}" if kart else " — Yeni"))
        self.geometry("1000x720")
        self.minsize(920, 640)
        self.transient(parent)
        self.grab_set()

        kayit = ttk.Frame(self, padding=(12, 8, 12, 12))
        kayit.pack(side="bottom", fill="x")
        ttk.Button(kayit, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(kayit, text="KAYDET", width=16, command=self.kaydet).pack(side="right")

        ust = ttk.Frame(self, padding=12)
        ust.pack(side="top", fill="both", expand=True)

        sol = ttk.Frame(ust)
        sol.pack(side="left", fill="both", expand=True)
        sag = ttk.LabelFrame(ust, text="HESAP BAKİYELERİ", padding=14)
        sag.pack(side="right", fill="y", padx=(16, 0))

        ttk.Label(sol, text="BANKA ANA KARTI", style="Baslik.TLabel").pack(anchor="w", pady=(0, 8))
        form = ttk.LabelFrame(sol, text="Hesap bilgileri", padding=12)
        form.pack(fill="x")
        self.alanlar = {}

        # Banka adı: seçmeli + Yeni banka kartı
        ttk.Label(form, text="Banka Adı").grid(row=0, column=0, sticky="w", padx=4, pady=5)
        banka_adi = ttk.Combobox(form, values=FinansService.banka_adi_listesi(), width=36)
        banka_adi.grid(row=0, column=1, sticky="ew", padx=4, pady=5)
        self.alanlar["banka_adi"] = banka_adi
        ttk.Button(form, text="Yeni", width=8, command=self.yeni_banka_karti).grid(
            row=0, column=2, padx=(0, 4), pady=5
        )

        for i, (etiket, anahtar) in enumerate((
            ("Banka Şubesi", "sube"),
            ("Hesap No", "hesap_no"),
            ("IBAN", "iban"),
            ("Açıklama", "aciklama"),
        ), start=1):
            ttk.Label(form, text=etiket).grid(row=i, column=0, sticky="w", padx=4, pady=5)
            ent = ttk.Entry(form, width=42)
            ent.grid(row=i, column=1, columnspan=2, sticky="ew", padx=4, pady=5)
            self.alanlar[anahtar] = ent
        form.columnconfigure(1, weight=1)

        pos_ayar = ttk.LabelFrame(sol, text="POS hesabı ayarları (komisyon / valör)", padding=10)
        pos_ayar.pack(fill="x", pady=(10, 0))
        ttk.Label(pos_ayar, text="Kredi kartı komisyon %").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self.alanlar["kk_komisyon_orani"] = ttk.Entry(pos_ayar, width=12)
        self.alanlar["kk_komisyon_orani"].grid(row=0, column=1, sticky="w", padx=4, pady=4)
        ttk.Label(pos_ayar, text="Banka kartı komisyon %").grid(row=0, column=2, sticky="w", padx=(16, 4), pady=4)
        self.alanlar["banka_karti_komisyon_orani"] = ttk.Entry(pos_ayar, width=12)
        self.alanlar["banka_karti_komisyon_orani"].grid(row=0, column=3, sticky="w", padx=4, pady=4)
        ttk.Label(pos_ayar, text="Kaç günde hesaba geçer").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        self.alanlar["pos_valor_gun"] = ttk.Entry(pos_ayar, width=12)
        self.alanlar["pos_valor_gun"].grid(row=1, column=1, sticky="w", padx=4, pady=4)
        ttk.Label(
            pos_ayar,
            text="(1 = ertesi gün 08:00'de net bakiye KMH'ye aktarılır)",
            foreground="#555",
        ).grid(row=1, column=2, columnspan=2, sticky="w", padx=4)

        if kart:
            banka_adi.set(kart.banka_adi or "")
            self.alanlar["sube"].insert(0, kart.sube or "")
            self.alanlar["hesap_no"].insert(0, kart.hesap_no or "")
            self.alanlar["iban"].insert(0, kart.iban or "")
            self.alanlar["aciklama"].insert(0, kart.aciklama or "")
            self.alanlar["kk_komisyon_orani"].insert(0, str(kart.kk_komisyon_orani or 0))
            self.alanlar["banka_karti_komisyon_orani"].insert(
                0, str(kart.banka_karti_komisyon_orani or 0)
            )
            self.alanlar["pos_valor_gun"].insert(0, str(kart.pos_valor_gun if kart.pos_valor_gun is not None else 1))
        else:
            self.alanlar["kk_komisyon_orani"].insert(0, "0")
            self.alanlar["banka_karti_komisyon_orani"].insert(0, "0")
            self.alanlar["pos_valor_gun"].insert(0, "1")

        self.bakiye_etiketleri = {}
        for kod, etiket in BANKA_ALT_HESAP_TURLERI:
            satir = ttk.Frame(sag)
            satir.pack(fill="x", pady=6)
            ttk.Label(satir, text=etiket, width=20).pack(side="left")
            lbl = ttk.Label(satir, text=_para(0), font=("Segoe UI", 10, "bold"), width=16, anchor="e")
            lbl.pack(side="right")
            self.bakiye_etiketleri[kod] = lbl

        ttk.Label(
            sol,
            text="Kartı kaydettikten sonra alt hesap bakiyeleri ve işlem menüleri aktif olur.",
            foreground="#555",
        ).pack(anchor="w", pady=(10, 4))

        islem = ttk.LabelFrame(sol, text="İşlem menüleri", padding=10)
        islem.pack(fill="x", pady=(8, 0))
        for i, (kod, etiket) in enumerate(BANKA_ALT_HESAP_TURLERI):
            ttk.Button(
                islem,
                text=etiket.replace(" Hesabı", "") + " İşlemleri",
                width=28,
                command=lambda k=kod, e=etiket: self._islem_ac(k, e),
            ).grid(row=i // 3, column=i % 3, padx=6, pady=6, sticky="ew")
        for c in range(3):
            islem.columnconfigure(c, weight=1)

        self.bakiyeleri_yenile()

    def _banka_adi_listesini_yenile(self):
        degerler = FinansService.banka_adi_listesi()
        mevcut = self.alanlar["banka_adi"].get().strip()
        self.alanlar["banka_adi"]["values"] = degerler
        if mevcut:
            self.alanlar["banka_adi"].set(mevcut)

    def yeni_banka_karti(self):
        """Banka adı yanındaki Yeni — yeni banka ana kartı açar."""
        ad = simpledialog.askstring(
            "Yeni Banka Kartı",
            "Yeni kart için banka adını yazın:",
            parent=self,
            initialvalue=self.alanlar["banka_adi"].get().strip(),
        )
        if ad is None:
            return
        ad = (ad or "").strip()
        if not ad:
            messagebox.showwarning("Banka adı", "Banka adı boş olamaz.", parent=self)
            return

        app = self.master
        dialog = BankaAnaKartDialog(app, kart=None)
        dialog.alanlar["banka_adi"].set(ad)
        dialog._banka_adi_listesini_yenile()
        self.wait_window(dialog)
        self._banka_adi_listesini_yenile()
        if dialog.result:
            # Yeni kart kaydedildiyse listedeki adı seçilebilir kalsın
            self.alanlar["banka_adi"].set(dialog.result.banka_adi)

    def bakiyeleri_yenile(self):
        if not self.kart:
            for lbl in self.bakiye_etiketleri.values():
                lbl.configure(text=_para(0))
            return
        kart = FinansService.banka_karti_getir(self.kart.id)
        if not kart:
            return
        self.kart = kart
        bakiyeler = FinansService.banka_bakiyeler(kart)
        for kod, lbl in self.bakiye_etiketleri.items():
            lbl.configure(text=_para(bakiyeler.get(kod, 0)))

    def _islem_ac(self, alt_tur, alt_etiket):
        if not self.kart:
            messagebox.showinfo(
                "Kayıt",
                "İşlem menüsü için önce banka kartını kaydedin.",
                parent=self,
            )
            return
        if alt_tur == "MEVDUAT":
            dialog = MevduatIslemleriDialog(self, self.kart)
        elif alt_tur == "POS":
            dialog = PosIslemleriDialog(self, self.kart)
        else:
            dialog = AltHesapIslemDialog(self, self.kart, alt_tur, alt_etiket)
        self.wait_window(dialog)
        self.bakiyeleri_yenile()

    def kaydet(self):
        veri = {k: w.get().strip() for k, w in self.alanlar.items()}
        if self.kart:
            veri["kart_id"] = self.kart.id
        try:
            self.result = FinansService.banka_karti_kaydet(veri)
        except ValueError as hata:
            messagebox.showerror("Kayıt", str(hata), parent=self)
            return
        self.kart = self.result
        self.title(f"Banka Ana Kartı — {self.kart.banka_adi}")
        self._banka_adi_listesini_yenile()
        self.bakiyeleri_yenile()
        messagebox.showinfo(
            "Kaydedildi",
            "Banka kartı ve 5 alt hesap (mevduat, KMH, POS, kredi kartı, krediler) hazır.",
            parent=self,
        )


def _hesap_sayfasi(app, hesap_turu: str, baslik: str):
    app._icerigi_temizle()
    _finans_menu_isaretle(app)

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text=baslik, style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Finans Menüsü", command=lambda: finans_menusu_goster(app)).pack(side="right")

    ttk.Label(
        app.icerik,
        text="Hesapları yönetin; fatura tahsilat/ödemeleri otomatik buraya işlenir. Çift tık = hareketler.",
    ).pack(anchor="w", pady=(10, 4))

    cerceve = ttk.Frame(app.icerik)
    cerceve.pack(fill="both", expand=True, pady=6)

    kolonlar = ("ad", "acilis", "bakiye", "aciklama", "durum")
    basliklar = ("Kasa Adı", "Açılış", "Bakiye", "Açıklama", "Durum")
    genislik = (200, 110, 120, 280, 70)

    tablo = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse", height=10)
    for k, b, w in zip(kolonlar, basliklar, genislik):
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="w")
    kaydirma = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=kaydirma.set)
    tablo.pack(side="left", fill="both", expand=True)
    kaydirma.pack(side="right", fill="y")

    hareket_cerceve = ttk.LabelFrame(app.icerik, text="Hesap hareketleri", padding=6)
    hareket_cerceve.pack(fill="both", expand=True, pady=(4, 0))
    hareket_tablo = ttk.Treeview(
        hareket_cerceve,
        columns=("tarih", "tur", "belge", "giris", "cikis", "aciklama"),
        show="headings",
        height=8,
    )
    for k, b, w in (
        ("tarih", "Tarih", 90),
        ("tur", "Hareket", 140),
        ("belge", "Belge No", 120),
        ("giris", "Giriş", 100),
        ("cikis", "Çıkış", 100),
        ("aciklama", "Açıklama", 260),
    ):
        hareket_tablo.heading(k, text=b)
        hareket_tablo.column(k, width=w, anchor="w")
    h_kaydir = ttk.Scrollbar(hareket_cerceve, orient="vertical", command=hareket_tablo.yview)
    hareket_tablo.configure(yscrollcommand=h_kaydir.set)
    hareket_tablo.pack(side="left", fill="both", expand=True)
    h_kaydir.pack(side="right", fill="y")

    ozet = ttk.Label(app.icerik, text="")
    ozet.pack(anchor="w", pady=4)

    def listeyi_yenile():
        for item in tablo.get_children():
            tablo.delete(item)
        hesaplar = FinansService.hesaplar(hesap_turu=hesap_turu, aktif_only=False)
        toplam = Decimal("0")
        for h in hesaplar:
            if not h.aktif:
                continue
            bak = FinansService.bakiye(h)
            toplam += bak
            tablo.insert(
                "",
                "end",
                iid=str(h.id),
                values=(
                    h.hesap_adi,
                    _para(h.acilis_bakiyesi),
                    _para(bak),
                    (h.aciklama or "")[:60],
                    "Aktif" if h.aktif else "Pasif",
                ),
            )
        ozet.configure(
            text=f"Aktif hesap: {len([h for h in hesaplar if h.aktif])} · Toplam bakiye: {_para(toplam)}"
        )

    def hareketleri_goster(hesap_id=None):
        for item in hareket_tablo.get_children():
            hareket_tablo.delete(item)
        if not hesap_id:
            hareket_cerceve.configure(text="Hesap hareketleri")
            return
        hesap = FinansService.hesap_getir(hesap_id)
        if not hesap:
            return
        hareket_cerceve.configure(
            text=f"Hareketler — {hesap.hesap_adi} (bakiye: {_para(FinansService.bakiye(hesap))})"
        )
        for har in FinansService.hareketler(hesap_id=hesap_id, limit=300):
            isaret = FinansService.hareket_isareti(har.hareket_turu)
            hareket_tablo.insert(
                "",
                "end",
                values=(
                    _tarih(har.tarih),
                    har.hareket_turu,
                    har.belge_no,
                    _para(har.tutar) if isaret > 0 else "",
                    _para(har.tutar) if isaret < 0 else "",
                    har.aciklama or "",
                ),
            )

    def secili_id():
        secim = tablo.selection()
        return int(secim[0]) if secim else None

    def secim_degisti(_e=None):
        hid = secili_id()
        if hid:
            hareketleri_goster(hid)

    def yeni():
        dialog = HesapDialog(app, hesap_turu=hesap_turu)
        app.wait_window(dialog)
        if dialog.result:
            listeyi_yenile()
            tablo.selection_set(str(dialog.result.id))
            hareketleri_goster(dialog.result.id)

    def duzenle():
        hid = secili_id()
        if not hid:
            messagebox.showinfo("Seçim", "Bir hesap seçin.", parent=app)
            return
        hesap = FinansService.hesap_getir(hid)
        dialog = HesapDialog(app, hesap_turu=hesap_turu, hesap=hesap)
        app.wait_window(dialog)
        if dialog.result:
            listeyi_yenile()
            tablo.selection_set(str(dialog.result.id))
            hareketleri_goster(dialog.result.id)

    def pasif():
        hid = secili_id()
        if not hid:
            messagebox.showinfo("Seçim", "Bir hesap seçin.", parent=app)
            return
        hesap = FinansService.hesap_getir(hid)
        if not messagebox.askyesno(
            "Pasif",
            f"'{hesap.hesap_adi}' hesabı pasif yapılsın mı?\nHareketler silinmez.",
            parent=app,
        ):
            return
        try:
            FinansService.hesap_pasif_yap(hid)
        except ValueError as hata:
            messagebox.showerror("Pasif", str(hata), parent=app)
            return
        hareketleri_goster(None)
        listeyi_yenile()

    tablo.bind("<<TreeviewSelect>>", secim_degisti)
    tablo.bind("<Double-1>", lambda _e: duzenle())

    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", pady=8)
    ttk.Button(alt, text="Yeni Hesap", command=yeni).pack(side="left")
    ttk.Button(alt, text="Düzenle", command=duzenle).pack(side="left", padx=8)
    ttk.Button(alt, text="Pasif Yap", command=pasif).pack(side="left")
    ttk.Button(alt, text="Yenile", command=listeyi_yenile).pack(side="right")

    listeyi_yenile()


def kasalar_sayfasi_goster(app):
    _hesap_sayfasi(app, "KASA", "KASALAR")


def bankalar_sayfasi_goster(app):
    app._icerigi_temizle()
    _finans_menu_isaretle(app)

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="BANKALAR", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Finans Menüsü", command=lambda: finans_menusu_goster(app)).pack(side="right")

    ttk.Label(
        app.icerik,
        text="Banka ana kartları. Çift tık veya Düzenle ile kartı açın — sağda bakiyeler, altta işlem menüleri.",
    ).pack(anchor="w", pady=(10, 4))

    cerceve = ttk.Frame(app.icerik)
    cerceve.pack(fill="both", expand=True, pady=6)
    kolonlar = ("banka", "sube", "hesap_no", "iban", "mevduat", "kmh", "pos", "kk", "kredi")
    tablo = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
    for k, b, w in (
        ("banka", "Banka Adı", 140),
        ("sube", "Şube", 110),
        ("hesap_no", "Hesap No", 110),
        ("iban", "IBAN", 200),
        ("mevduat", "Mevduat", 95),
        ("kmh", "KMH", 90),
        ("pos", "POS", 90),
        ("kk", "Kredi Kartı", 95),
        ("kredi", "Krediler", 95),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="w")
    kaydirma = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=kaydirma.set)
    tablo.pack(side="left", fill="both", expand=True)
    kaydirma.pack(side="right", fill="y")

    ozet = ttk.Label(app.icerik, text="")
    ozet.pack(anchor="w", pady=4)

    def listeyi_yenile():
        for item in tablo.get_children():
            tablo.delete(item)
        kartlar = FinansService.banka_kartlari(aktif_only=False)
        aktif = 0
        for kart in kartlar:
            if not kart.aktif:
                continue
            aktif += 1
            bak = FinansService.banka_bakiyeler(kart)
            tablo.insert(
                "",
                "end",
                iid=str(kart.id),
                values=(
                    kart.banka_adi,
                    kart.sube or "—",
                    kart.hesap_no or "—",
                    kart.iban or "—",
                    _para(bak["MEVDUAT"]),
                    _para(bak["KMH"]),
                    _para(bak["POS"]),
                    _para(bak["KREDI_KARTI"]),
                    _para(bak["KREDILER"]),
                ),
            )
        ozet.configure(text=f"{aktif} aktif banka kartı")

    def secili_kart():
        secim = tablo.selection()
        if not secim:
            messagebox.showinfo("Seçim", "Bir banka kartı seçin.", parent=app)
            return None
        return FinansService.banka_karti_getir(int(secim[0]))

    def yeni():
        dialog = BankaAnaKartDialog(app)
        app.wait_window(dialog)
        listeyi_yenile()

    def duzenle():
        kart = secili_kart()
        if not kart:
            return
        dialog = BankaAnaKartDialog(app, kart)
        app.wait_window(dialog)
        listeyi_yenile()

    def pasif():
        kart = secili_kart()
        if not kart:
            return
        if not messagebox.askyesno(
            "Pasif",
            f"'{kart.banka_adi}' banka kartı ve alt hesapları pasif yapılsın mı?",
            parent=app,
        ):
            return
        try:
            FinansService.banka_karti_pasif_yap(kart.id)
        except ValueError as hata:
            messagebox.showerror("Pasif", str(hata), parent=app)
            return
        listeyi_yenile()

    tablo.bind("<Double-1>", lambda _e: duzenle())

    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", pady=8)
    ttk.Button(alt, text="Yeni Banka Kartı", command=yeni).pack(side="left")
    ttk.Button(alt, text="Kartı Aç / Düzenle", command=duzenle).pack(side="left", padx=8)
    ttk.Button(alt, text="Pasif Yap", command=pasif).pack(side="left")
    ttk.Button(alt, text="Yenile", command=listeyi_yenile).pack(side="right")

    listeyi_yenile()
