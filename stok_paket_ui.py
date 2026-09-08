"""Stok paket tanımlama ve paket üretim (birleştirme) arayüzü."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import tkinter as tk
from tkinter import messagebox, ttk

from database.satis_siparisi_service import decimal
from database.stok_service import StokService
from stok_ui import StokKartiDialog
from ui_takvim import takvim_butonu
from urun_sec_ui import UrunSecDialog


def _para(tutar):
    return f"{float(tutar):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def _tarih(t):
    return t.strftime("%d.%m.%Y") if t else ""


class PaketTanimDialog(tk.Toplevel):
    """Paket stok kartı + içindeki ürün miktarları (1 paket için)."""

    def __init__(self, parent, paket_stok=None):
        super().__init__(parent)
        self.result = None
        self.paket_stok = paket_stok
        self.bilesenler = []
        self.title("Paket Tanımı" + (f" — {paket_stok.stok_kodu}" if paket_stok else ""))
        self.geometry("920x560")
        self.minsize(800, 480)
        self.transient(parent)
        self.grab_set()

        ust = ttk.LabelFrame(self, text="Paket Stok Kartı (tür: Paket)", padding=10)
        ust.pack(fill="x", padx=12, pady=10)
        self.paket_etiket = ttk.Label(ust, text="— paket stok seçilmedi —")
        self.paket_etiket.pack(side="left", padx=(0, 8))
        ttk.Button(ust, text="Mevcut Paket Seç", command=self.paket_sec).pack(side="left", padx=4)
        ttk.Button(ust, text="Yeni Paket Kartı", command=self.yeni_paket_karti).pack(side="left", padx=4)

        form = ttk.LabelFrame(self, text="1 Paket İçeriği", padding=10)
        form.pack(fill="x", padx=12)
        self.urun_kodu = ttk.Entry(form, width=14)
        self.urun_adi = ttk.Entry(form, width=28)
        self.birim = ttk.Entry(form, width=8)
        self.miktar = ttk.Entry(form, width=10)
        self.miktar.insert(0, "1")
        for i, (etiket, w) in enumerate(
            (("Kod", self.urun_kodu), ("Ad", self.urun_adi), ("Birim", self.birim), ("Miktar", self.miktar))
        ):
            ttk.Label(form, text=etiket).grid(row=0, column=i, sticky="w", padx=3)
            w.grid(row=1, column=i, sticky="w", padx=3, pady=2)
        bt = ttk.Frame(form)
        bt.grid(row=1, column=4, padx=8)
        ttk.Button(bt, text="Ürün Seç", command=self.urun_sec).pack(side="left", padx=2)
        ttk.Button(bt, text="Satır Ekle", command=self.satir_ekle).pack(side="left", padx=2)
        ttk.Button(bt, text="Satır Sil", command=self.satir_sil).pack(side="left", padx=2)
        ttk.Label(
            form,
            text="Örnek: 5 dübel, 10 vida, 20 çivi → bir paket. Üretimde paket adedi × bu miktarlar düşülür.",
            foreground="#666666",
        ).grid(row=2, column=0, columnspan=5, sticky="w", pady=(6, 0))

        kolonlar = ("kod", "ad", "birim", "miktar")
        self.tablo = ttk.Treeview(self, columns=kolonlar, show="headings", height=12)
        for k, b in zip(kolonlar, ("Ürün Kodu", "Ürün Adı", "Birim", "1 Paket Miktarı")):
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=140 if k != "ad" else 280, anchor="w")
        self.tablo.pack(fill="both", expand=True, padx=12, pady=8)

        alt = ttk.Frame(self)
        alt.pack(fill="x", padx=12, pady=10)
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Tanımı Kaydet", command=self.kaydet).pack(side="right", padx=8)

        if paket_stok:
            self._paket_goster(paket_stok)
            for b in StokService.paket_bilesenleri(paket_stok.id):
                self.bilesenler.append(b)
            self._listeyi_yenile()

    def _paket_goster(self, stok):
        self.paket_stok = stok
        self.paket_etiket.configure(text=f"{stok.stok_kodu} — {stok.stok_adi}  |  Birim: {stok.birim}")

    def paket_sec(self):
        UrunSecDialog(self, on_select=self._paket_secildi)

    def _paket_secildi(self, degerler):
        kod = (degerler[0] or "").strip()
        stok = next((s for s in StokService.stoklari_ara(kod) if s.stok_kodu == kod), None)
        if not stok:
            messagebox.showerror("Stok", "Paket stok bulunamadı.", parent=self)
            return
        self._paket_goster(stok)
        self.bilesenler = StokService.paket_bilesenleri(stok.id)
        self._listeyi_yenile()

    def yeni_paket_karti(self):
        dialog = StokKartiDialog(self, baslangic={"kart_turu": "Paket"})
        self.wait_window(dialog)
        if dialog.result:
            self._paket_goster(dialog.result)

    def urun_sec(self):
        UrunSecDialog(self, on_select=self._urun_secildi)

    def _urun_secildi(self, degerler):
        self.urun_kodu.delete(0, "end")
        self.urun_kodu.insert(0, (degerler[0] or "").strip())
        self.urun_adi.delete(0, "end")
        self.urun_adi.insert(0, degerler[1] or "")
        self.birim.delete(0, "end")
        self.birim.insert(0, degerler[2] or "Adet")
        if not self.miktar.get().strip():
            self.miktar.insert(0, "1")
        try:
            self.miktar.focus_set()
        except tk.TclError:
            pass

    def satir_ekle(self):
        kod = self.urun_kodu.get().strip()
        ad = self.urun_adi.get().strip()
        if not kod:
            messagebox.showwarning("Eksik", "Ürün seçin.", parent=self)
            return
        try:
            miktar = decimal(self.miktar.get() or 0, "Miktar", Decimal("0.0001"))
        except ValueError as hata:
            messagebox.showerror("Miktar", str(hata), parent=self)
            return
        # Aynı kod varsa güncelle
        for b in self.bilesenler:
            if b["urun_kodu"] == kod:
                b["miktar"] = miktar
                b["urun_adi"] = ad or b["urun_adi"]
                b["birim"] = self.birim.get().strip() or b.get("birim") or "Adet"
                self._form_temizle()
                self._listeyi_yenile()
                return
        self.bilesenler.append(
            {
                "urun_kodu": kod,
                "urun_adi": ad,
                "birim": self.birim.get().strip() or "Adet",
                "miktar": miktar,
            }
        )
        self._form_temizle()
        self._listeyi_yenile()

    def _form_temizle(self):
        for w in (self.urun_kodu, self.urun_adi, self.birim, self.miktar):
            w.delete(0, "end")
        self.miktar.insert(0, "1")

    def satir_sil(self):
        secim = self.tablo.selection()
        if not secim:
            return
        idx = int(secim[0])
        if 0 <= idx < len(self.bilesenler):
            self.bilesenler.pop(idx)
            self._listeyi_yenile()

    def _listeyi_yenile(self):
        for item in self.tablo.get_children():
            self.tablo.delete(item)
        for i, b in enumerate(self.bilesenler):
            self.tablo.insert(
                "",
                "end",
                iid=str(i),
                values=(b["urun_kodu"], b["urun_adi"], b.get("birim", ""), b["miktar"]),
            )

    def kaydet(self):
        if not self.paket_stok:
            messagebox.showwarning("Paket", "Önce paket stok kartını seçin veya oluşturun.", parent=self)
            return
        if not self.bilesenler:
            messagebox.showwarning("İçerik", "Pakete en az bir ürün ekleyin.", parent=self)
            return
        try:
            StokService.paket_tanim_kaydet(self.paket_stok.id, self.bilesenler)
        except ValueError as hata:
            messagebox.showerror("Kayıt başarısız", str(hata), parent=self)
            return
        self.result = self.paket_stok.id
        messagebox.showinfo(
            "Kaydedildi",
            f"Paket tanımı kaydedildi: {self.paket_stok.stok_kodu}\n"
            "Not: Tanım tek başına depo bakiyesini değiştirmez.",
            parent=self,
        )
        uret = messagebox.askyesno(
            "Depoya işle",
            "Şimdi bileşenleri stoktan düşüp paket stoğu depoya eklemek ister misiniz?\n\n"
            "(Örnek: 3 kalemde toplam 24 ürün → 1 paket depoya girer, 24 ürün düşer.)",
            parent=self,
        )
        self.destroy()
        if uret and self.paket_stok:
            dialog = PaketUretimDialog(self.master, self.paket_stok)
            try:
                self.master.wait_window(dialog)
            except tk.TclError:
                pass
            if dialog.result:
                self.result = dialog.result


class PaketUretimDialog(tk.Toplevel):
    """Tanımlı paketten N adet üretir; bileşenler düşer, paket stoğa girer."""

    def __init__(self, parent, paket_stok):
        super().__init__(parent)
        self.result = None
        self.paket_stok = paket_stok
        self.bilesenler = StokService.paket_bilesenleri(paket_stok.id)
        self.title(f"Paket Oluştur — {paket_stok.stok_kodu}")
        self.geometry("720x480")
        self.transient(parent)
        self.grab_set()

        ttk.Label(
            self,
            text=(
                f"Paket: {paket_stok.stok_kodu} — {paket_stok.stok_adi}\n"
                "• Paket adedi kadar paket STOĞA GİRER (depo bakiyesi +N)\n"
                "• İçindeki her ürün (miktar × adet) STOKTAN DÜŞER\n"
                "• Paket birim maliyeti = düşülen ürünlerin maliyet toplamı ÷ paket adedi\n"
                "• Bu maliyet kar/zarar analizinde (FIFO / alış) kullanılır"
            ),
            justify="left",
            wraplength=680,
        ).pack(anchor="w", padx=12, pady=10)

        form = ttk.Frame(self, padding=8)
        form.pack(fill="x", padx=8)
        ttk.Label(form, text="Tarih").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        tarih_c = ttk.Frame(form)
        tarih_c.grid(row=0, column=1, sticky="w")
        self.tarih = ttk.Entry(tarih_c, width=14)
        self.tarih.pack(side="left")
        self.tarih.insert(0, _tarih(date.today()))
        takvim_butonu(tarih_c, self.tarih)

        depolar = tuple(d.ad for d in StokService.depolar()) or ("ANA DEPO",)
        ttk.Label(form, text="Depo").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        self.depo = ttk.Combobox(form, values=depolar, state="readonly", width=28)
        self.depo.grid(row=1, column=1, sticky="w", padx=4, pady=4)
        if depolar:
            self.depo.current(0)

        ttk.Label(form, text="Paket Adedi").grid(row=2, column=0, sticky="w", padx=4, pady=4)
        self.adet = ttk.Entry(form, width=14)
        self.adet.grid(row=2, column=1, sticky="w", padx=4, pady=4)
        self.adet.insert(0, "1")
        self.adet.bind("<KeyRelease>", self._onizleme)

        ttk.Label(form, text="Açıklama").grid(row=3, column=0, sticky="w", padx=4, pady=4)
        self.aciklama = ttk.Entry(form, width=40)
        self.aciklama.grid(row=3, column=1, sticky="w", padx=4, pady=4)

        self.onizleme = ttk.Label(self, text="", justify="left")
        self.onizleme.pack(anchor="w", padx=14, pady=6)

        kolonlar = ("kod", "ad", "birim", "birim_miktar", "toplam")
        self.tablo = ttk.Treeview(self, columns=kolonlar, show="headings", height=8)
        for k, b in zip(
            kolonlar,
            ("Kod", "Ürün", "Birim", "1 Paket", "Toplam Düşülecek"),
        ):
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=110 if k != "ad" else 220, anchor="w")
        self.tablo.pack(fill="both", expand=True, padx=12, pady=6)

        alt = ttk.Frame(self)
        alt.pack(fill="x", padx=12, pady=10)
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Depoya İşle (düş + paket gir)", command=self.uretim_yap).pack(
            side="right", padx=8
        )
        self._onizleme()

    def _onizleme(self, _e=None):
        try:
            adet = decimal(self.adet.get() or 0, "Adet", Decimal("0"))
        except ValueError:
            adet = Decimal("0")
        for item in self.tablo.get_children():
            self.tablo.delete(item)
        for b in self.bilesenler:
            toplam = decimal(b["miktar"], "M", Decimal("0")) * adet
            self.tablo.insert(
                "",
                "end",
                values=(b["urun_kodu"], b["urun_adi"], b.get("birim", ""), b["miktar"], toplam),
            )
        # Tahmini maliyet (FIFO birim × miktar)
        tahmini = Decimal("0")
        depo = self.depo.get().strip()
        for b in self.bilesenler:
            maliyetler = StokService.maliyetler(b["urun_kodu"], depo) if depo else {}
            birim = maliyetler.get("fifo") or maliyetler.get("agirlikli") or Decimal("0")
            tahmini += birim * decimal(b["miktar"], "M", Decimal("0")) * adet
        birim_paket = (tahmini / adet) if adet else Decimal("0")
        self.onizleme.configure(
            text=(
                f"Tahmini toplam maliyet: {_para(tahmini)}  |  "
                f"Tahmini paket birim maliyeti: {_para(birim_paket)}"
            )
        )

    def uretim_yap(self):
        try:
            tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
            adet = decimal(self.adet.get() or 0, "Paket adedi", Decimal("0.0001"))
        except ValueError as hata:
            messagebox.showerror("Geçersiz", str(hata), parent=self)
            return
        if not messagebox.askyesno(
            "Onay — stok dengesi",
            (
                f"{adet} paket → {self.depo.get()} deposuna GİRECEK.\n"
                f"İçerikteki ürünler aynı depodan DÜŞÜLECEK.\n"
                f"Stok dengesi korunur (bileşen çıkış = paket giriş maliyeti)."
            ),
            parent=self,
        ):
            return
        try:
            sonuc = StokService.paket_olustur(
                self.paket_stok.id,
                self.depo.get(),
                adet,
                tarih=tarih,
                aciklama=self.aciklama.get().strip(),
            )
        except ValueError as hata:
            messagebox.showerror("Üretim başarısız", str(hata), parent=self)
            return
        self.result = sonuc
        dusen = "\n".join(
            f"  − {b['miktar']} {b['urun_adi']} ({b['urun_kodu']}) = {_para(b['maliyet'])}"
            for b in sonuc.get("bilesenler", [])
        )
        messagebox.showinfo(
            "Stok güncellendi",
            (
                f"Fiş: {sonuc['fis_no']}  |  Depo: {sonuc['depo']}\n"
                f"+ {sonuc['adet']} paket → {sonuc['paket_kodu']} "
                f"(birim maliyet {_para(sonuc['birim_maliyet'])})\n"
                f"Toplam maliyet: {_para(sonuc['toplam_maliyet'])}\n\n"
                f"Düşülen ürünler:\n{dusen or '—'}"
            ),
            parent=self,
        )
        self.destroy()


def stok_paket_sayfasi_goster(app):
    app._icerigi_temizle()
    for dugme_anahtari, dugme in app.menu_dugmeleri.items():
        dugme.configure(style="SeciliMenu.TButton" if dugme_anahtari == "stoklar" else "Menu.TButton")
    ttk.Label(app.icerik, text="STOK PAKET TANIMLAMA", style="Baslik.TLabel").pack(anchor="w")
    ttk.Label(
        app.icerik,
        text=(
            "1) Paket tanımını kaydedin (içerik: örn. 5+10+9=24 ürün → 1 paket). "
            "2) «Depoya Paket İşle» ile bileşenleri stoktan düşüp paketi depoya ekleyin. "
            "Paket maliyeti = bileşen maliyetleri toplamı; satışta kar/zarar bu maliyetle hesaplanır."
        ),
        wraplength=800,
        justify="left",
    ).pack(anchor="w", pady=(12, 8))

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x", pady=6)
    ttk.Button(ust, text="← Stoklar Menüsü", command=lambda: app.sayfa_goster("stoklar")).pack(side="right")
    ttk.Button(ust, text="Yeni / Düzenle Tanım", command=lambda: _tanim_ac(app)).pack(side="left")
    ttk.Button(ust, text="Depoya Paket İşle", command=lambda: _uretim_ac(app)).pack(side="left", padx=8)
    ttk.Button(ust, text="Yenile", command=lambda: stok_paket_sayfasi_goster(app)).pack(side="left")

    cerceve = ttk.LabelFrame(app.icerik, text="Tanımlı Paketler", padding=8)
    cerceve.pack(fill="both", expand=True, pady=(8, 4))
    kolonlar = ("kod", "ad", "icerik", "mevcut")
    tablo = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse", height=10)
    for k, b in zip(kolonlar, ("Paket Kodu", "Paket Adı", "İçerik (1 paket)", "Mevcut Paket")):
        tablo.heading(k, text=b)
        tablo.column(k, width=140 if k != "icerik" else 360, anchor="w")
    tablo.pack(side="left", fill="both", expand=True)
    kaydirma = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=kaydirma.set)
    kaydirma.pack(side="right", fill="y")
    app._paket_tablosu = tablo

    for kayit in StokService.paket_tanimlari():
        stok = kayit["stok"]
        icerik = ", ".join(
            f"{b['miktar']} {b['urun_adi']}" for b in kayit["bilesenler"]
        )
        tablo.insert(
            "",
            "end",
            iid=str(stok.id),
            values=(stok.stok_kodu, stok.stok_adi, icerik, kayit["mevcut"]),
        )
    tablo.bind("<Double-1>", lambda _e: _tanim_ac(app, secili=True))

    uretim_cerceve = ttk.LabelFrame(app.icerik, text="Son Paket Üretimleri", padding=8)
    uretim_cerceve.pack(fill="both", expand=True, pady=(4, 0))
    uk = ("fis", "tarih", "paket", "adet", "birim", "toplam", "depo")
    ut = ttk.Treeview(uretim_cerceve, columns=uk, show="headings", height=6)
    for k, b in zip(
        uk,
        ("Fiş No", "Tarih", "Paket", "Adet", "Birim Maliyet", "Toplam", "Depo"),
    ):
        ut.heading(k, text=b)
        ut.column(k, width=100, anchor="w")
    ut.column("paket", width=200)
    ut.pack(fill="both", expand=True)
    for u in StokService.paket_uretimleri(40):
        paket = u.paket_stok
        ut.insert(
            "",
            "end",
            values=(
                u.fis_no,
                _tarih(u.uretim_tarihi),
                f"{paket.stok_kodu} — {paket.stok_adi}" if paket else "",
                u.paket_adedi,
                _para(u.birim_maliyet),
                _para(u.toplam_maliyet),
                u.depo,
            ),
        )


def _secili_paket(app):
    tablo = getattr(app, "_paket_tablosu", None)
    if not tablo:
        return None
    secim = tablo.selection()
    if not secim:
        return None
    return StokService.stok_getir(int(secim[0]))


def _tanim_ac(app, secili=False):
    stok = _secili_paket(app) if secili else None
    if secili and not stok:
        messagebox.showinfo("Seçim", "Düzenlenecek paketi seçin.", parent=app)
        return
    dialog = PaketTanimDialog(app, stok)
    app.wait_window(dialog)
    if dialog.result:
        stok_paket_sayfasi_goster(app)


def _uretim_ac(app):
    stok = _secili_paket(app)
    if not stok:
        messagebox.showinfo("Seçim", "Önce listeden paket seçin.", parent=app)
        return
    if not StokService.paket_bilesenleri(stok.id):
        messagebox.showwarning("Tanım yok", "Bu paketin içeriği tanımlı değil.", parent=app)
        return
    dialog = PaketUretimDialog(app, stok)
    app.wait_window(dialog)
    if dialog.result:
        stok_paket_sayfasi_goster(app)
