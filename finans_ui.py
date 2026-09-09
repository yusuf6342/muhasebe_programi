"""FİNANS menüsü — Kasalar, Bankalar, Çek-Senet."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from database.finans_service import FinansService
from database.kk_cekimi_service import KkCekimiService
from database.models.finans import (
    BANKA_ALT_HESAP_TURLERI,
    KK_CEKIM_TURLERI,
    KK_MAX_TAKSIT,
    POS_KART_TIPLERI,
    POS_MAX_TAKSIT,
)
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
        text="Kasa ve banka hesapları, banka işlem evrakları ve çek-senet.",
    ).pack(anchor="w", pady=(8, 0))
    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", pady=(24, 0))
    alt.columnconfigure(0, weight=1, minsize=520)
    for i, (baslik, komut) in enumerate((
        ("KASALAR", lambda: kasalar_sayfasi_goster(app)),
        ("BANKALAR", lambda: bankalar_sayfasi_goster(app)),
        ("BANKA İŞLEMLERİ", lambda: banka_islemleri_menusu_goster(app)),
        ("ÇEK-SENET MODÜLÜ", lambda: cek_senet_menusu_goster(app)),
    )):
        ttk.Button(alt, text=baslik, style="AltMenu.TButton", command=komut).grid(
            row=i, column=0, sticky="ew", pady=4
        )


BANKA_ISLEM_EVRAKLARI = (
    ("KASADAN BANKAYA YATIRILAN", "kby"),
    ("BANKADAN ÇEKİLEN", "bnc"),
    ("ALINAN HAVALE", "ahv"),
    ("GÖNDERİLEN HAVALE", "ghv"),
    ("BANKALAR ARASI VİRMAN", "bvr"),
    ("KREDİ KARTI İLE ÖDEME", "kko"),
    ("KREDİ KARTI POS CİHAZIYLA TAHSİLAT", "kpt"),
    ("MÜŞTERİDEN TEDARİKÇİYE KREDİ KARTI ÇEKİMİ", "kkc"),
)


def banka_islemleri_menusu_goster(app):
    app._icerigi_temizle()
    _finans_menu_isaretle(app)
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="BANKA İŞLEMLERİ", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Finans Menüsü", command=lambda: finans_menusu_goster(app)).pack(side="right")
    ttk.Label(
        app.icerik,
        text="Kasa–banka, havale, kredi kartı ve müşteri–tedarikçi KK çekim evrakları.",
    ).pack(anchor="w", pady=(14, 8))
    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", pady=(8, 0))
    alt.columnconfigure(0, weight=1, minsize=520)
    for i, (baslik, kod) in enumerate(BANKA_ISLEM_EVRAKLARI):
        if kod == "kby":
            komut = lambda: kasadan_bankaya_yatirilan_sayfasi_goster(app)
        elif kod == "bnc":
            komut = lambda: bankadan_cekilen_sayfasi_goster(app)
        elif kod == "ahv":
            komut = lambda: alinan_havale_sayfasi_goster(app)
        elif kod == "ghv":
            komut = lambda: gonderilen_havale_sayfasi_goster(app)
        elif kod == "bvr":
            komut = lambda: bankalar_arasi_virman_sayfasi_goster(app)
        elif kod == "kko":
            komut = lambda: kredi_karti_odeme_sayfasi_goster(app)
        elif kod == "kpt":
            komut = lambda: kredi_karti_pos_tahsilat_sayfasi_goster(app)
        elif kod == "kkc":
            komut = lambda: kk_cekimi_sayfasi_goster(app)
        else:
            komut = lambda b=baslik: _banka_islem_bos(app, b)
        ttk.Button(
            alt,
            text=baslik,
            style="AltMenu.TButton",
            command=komut,
        ).grid(row=i, column=0, sticky="ew", pady=4)


def _banka_islem_bos(app, baslik):
    app._icerigi_temizle()
    _finans_menu_isaretle(app)
    ttk.Label(app.icerik, text=baslik, style="Baslik.TLabel").pack(anchor="w")
    ttk.Label(
        app.icerik,
        text="Bu evrak formu henüz hazır değil. Alanları ve işleyişi tarif ettiğinde buraya ekleyeceğiz.",
    ).pack(anchor="w", pady=(18, 0))
    ttk.Button(
        app.icerik,
        text="← Banka İşlemleri",
        command=lambda: banka_islemleri_menusu_goster(app),
    ).pack(anchor="w", pady=(16, 0))


def kasadan_bankaya_yatirilan_sayfasi_goster(app):
    """Kasadan bankaya yatırılan fiş listesi + yeni fiş."""
    app._icerigi_temizle()
    _finans_menu_isaretle(app)

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="KASADAN BANKAYA YATIRILAN", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Banka İşlemleri", command=lambda: banka_islemleri_menusu_goster(app)).pack(
        side="right"
    )
    ttk.Label(
        app.icerik,
        text="Kasadan nakit çıkışı; mevduat, KMH, kredi kartı veya vadeli hesaba yatırma.",
    ).pack(anchor="w", pady=(10, 6))

    butonlar = ttk.Frame(app.icerik)
    butonlar.pack(fill="x", pady=(4, 8))
    ttk.Button(butonlar, text="Yeni Fiş", command=lambda: _kby_yeni_fis(app)).pack(side="left")
    ttk.Button(butonlar, text="Güncelle", command=lambda: _kby_guncelle_fis(app, tablo)).pack(
        side="left", padx=8
    )
    ttk.Button(
        butonlar,
        text="Yenile",
        command=lambda: kasadan_bankaya_yatirilan_sayfasi_goster(app),
    ).pack(side="left", padx=8)

    cerceve = ttk.Frame(app.icerik)
    cerceve.pack(fill="both", expand=True)
    tablo = ttk.Treeview(
        cerceve,
        columns=("tarih", "belge", "kasa", "banka", "tutar", "aciklama"),
        show="headings",
        selectmode="browse",
    )
    for k, b, w in (
        ("tarih", "Tarih", 90),
        ("belge", "Belge No", 120),
        ("kasa", "Kasa", 150),
        ("banka", "Banka hesabı", 220),
        ("tutar", "Tutar", 110),
        ("aciklama", "Açıklama", 260),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="w")
    kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=kaydir.set)
    tablo.pack(side="left", fill="both", expand=True)
    kaydir.pack(side="right", fill="y")
    tablo.bind("<Double-1>", lambda _e: _kby_guncelle_fis(app, tablo))

    for kayit in FinansService.kasadan_bankaya_yatan_listele():
        tablo.insert(
            "",
            "end",
            iid=kayit["belge_no"],
            values=(
                _tarih(kayit["tarih"]),
                kayit["belge_no"],
                kayit["kasa"],
                kayit["banka_hesap"],
                _para(kayit["tutar"]),
                kayit["aciklama"],
            ),
        )


def _kby_yeni_fis(app):
    dialog = KasadanBankayaYatirDialog(app)
    app.wait_window(dialog)
    if dialog.result:
        kasadan_bankaya_yatirilan_sayfasi_goster(app)


def _kby_guncelle_fis(app, tablo):
    secim = tablo.selection()
    if not secim:
        messagebox.showinfo("Güncelle", "Lütfen güncellenecek fişi seçin.", parent=app)
        return
    dialog = KasadanBankayaYatirDialog(app, belge_no=secim[0])
    app.wait_window(dialog)
    if dialog.result:
        kasadan_bankaya_yatirilan_sayfasi_goster(app)


def _combobox_id_sec(cb, id_map: dict, hedef_id):
    if hedef_id is None:
        return False
    for etiket, deger in id_map.items():
        if deger == hedef_id:
            cb.set(etiket)
            return True
    return False


class KasadanBankayaYatirDialog(tk.Toplevel):
    """Kasadan bankaya yatırılan fiş formu."""

    ALT_ETIKET = {
        "MEVDUAT": "Mevduat",
        "KMH": "KMH",
        "KREDI_KARTI": "Kredi Kartı",
        "VADELI": "Vadeli",
        "POS": "POS",
        "KREDILER": "Krediler",
    }

    def __init__(self, parent, belge_no=None):
        super().__init__(parent)
        self.result = None
        self.belge_no = belge_no
        self._mevcut = None
        if belge_no:
            try:
                self._mevcut = FinansService.banka_islem_fis_getir(belge_no)
            except ValueError as hata:
                messagebox.showerror("Fiş", str(hata), parent=parent)
                self.destroy()
                return
        self.title(
            "Kasadan Bankaya Yatırılan — Güncelle" if belge_no else "Kasadan Bankaya Yatırılan"
        )
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)

        self._kasa_map = {}
        self._banka_map = {}
        self._hesap_map = {}

        row = 0
        ttk.Label(self, text="Tarih *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        tarih_c = ttk.Frame(self)
        tarih_c.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.tarih = ttk.Entry(tarih_c, width=14)
        self.tarih.pack(side="left")
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        takvim_butonu(tarih_c, self.tarih)

        row = 1
        kasalar = FinansService.hesaplar(hesap_turu="KASA")
        ttk.Label(self, text="Kasa *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.kasa = ttk.Combobox(self, state="readonly", width=42)
        self.kasa.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        self._kasa_map = {}
        kasa_etiketleri = []
        for h in kasalar:
            bak = FinansService.bakiye(h)
            etiket = f"{h.hesap_adi}  ({_para(bak)})"
            self._kasa_map[etiket] = h.id
            kasa_etiketleri.append(etiket)
        self.kasa.configure(values=kasa_etiketleri)
        if kasa_etiketleri:
            self.kasa.set(kasa_etiketleri[0])
        self.kasa.bind("<<ComboboxSelected>>", lambda _e: self._kasa_bilgi())

        row = 2
        self.kasa_bilgi = ttk.Label(self, text="", foreground="#555")
        self.kasa_bilgi.grid(row=row, column=1, columnspan=2, padx=12, sticky="w")

        row = 3
        kartlar = FinansService.banka_kartlari(aktif_only=True)
        ttk.Label(self, text="Banka *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.banka = ttk.Combobox(self, state="readonly", width=42)
        self.banka.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        self._banka_map = {}
        banka_etiketleri = []
        for k in kartlar:
            etiket = k.banka_adi
            if k.sube:
                etiket = f"{etiket} / {k.sube}"
            if k.hesap_no:
                etiket = f"{etiket} ({k.hesap_no})"
            self._banka_map[etiket] = k.id
            banka_etiketleri.append(etiket)
        self.banka.configure(values=banka_etiketleri)
        if banka_etiketleri:
            self.banka.set(banka_etiketleri[0])
        self.banka.bind("<<ComboboxSelected>>", lambda _e: self._hesaplari_doldur())

        row = 4
        ttk.Label(self, text="Banka hesabı *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.hesap = ttk.Combobox(self, state="readonly", width=42)
        self.hesap.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        self.hesap.bind("<<ComboboxSelected>>", lambda _e: self._hesap_bilgi())
        ttk.Label(
            self,
            text="(Mevduat, KMH, kredi kartı, vadeli)",
            foreground="#555",
        ).grid(row=row, column=3, sticky="w")

        row = 5
        self.hesap_bilgi = ttk.Label(self, text="", foreground="#555")
        self.hesap_bilgi.grid(row=row, column=1, columnspan=2, padx=12, sticky="w")

        row = 6
        ttk.Label(self, text="Tutar *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.tutar = ttk.Entry(self, width=18)
        self.tutar.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        row = 7
        ttk.Label(self, text="Dekont / makbuz no").grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        self.dekont = ttk.Entry(self, width=24)
        self.dekont.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        row = 8
        ttk.Label(self, text="Açıklama").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.aciklama = ttk.Entry(self, width=44)
        self.aciklama.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")

        if self.belge_no:
            ttk.Label(
                self,
                text=f"Belge: {self.belge_no}",
                foreground="#555",
            ).grid(row=9, column=0, columnspan=2, padx=12, sticky="w")

        butonlar = ttk.Frame(self)
        butonlar.grid(row=10, column=0, columnspan=3, padx=12, pady=14, sticky="e")
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(
            butonlar,
            text="Güncelle" if self.belge_no else "Kaydet",
            command=self.kaydet,
        ).pack(side="right")

        self._hesaplari_doldur()
        self._kasa_bilgi()
        self._mevcutu_yukle()

    def _mevcutu_yukle(self):
        m = self._mevcut
        if not m:
            return
        self.tarih.delete(0, "end")
        self.tarih.insert(0, m["tarih"].strftime("%d.%m.%Y"))
        self.tutar.delete(0, "end")
        self.tutar.insert(0, str(m["tutar"]))
        if m.get("dekont_no"):
            self.dekont.insert(0, m["dekont_no"])
        # Varsayılan açıklama metnini formda göstermeyelim
        acik = m.get("aciklama") or ""
        if " → " not in acik:
            self.aciklama.insert(0, acik)
        elif not acik.startswith(tuple(self._kasa_map.keys())):
            # kullanıcı açıklaması olabilir
            self.aciklama.insert(0, acik)
        _combobox_id_sec(self.kasa, self._kasa_map, m.get("kasa_id"))
        self._kasa_bilgi()
        _combobox_id_sec(self.banka, self._banka_map, m.get("banka_karti_id"))
        self._hesaplari_doldur()
        _combobox_id_sec(self.hesap, self._hesap_map, m.get("banka_hesap_id"))
        self._hesap_bilgi()
        # Açıklamayı hesaplar seçildikten sonra düzgün bas
        self.aciklama.delete(0, "end")
        ham = m.get("aciklama") or ""
        # otomatik üretilmiş "A → B" satırını boş bırak
        if " → " in ham and not (m.get("dekont_no") and ham.endswith("")):
            # basit: sadece kullanıcı metni gibi görünenleri koy
            parts = ham.split(" → ", 1)
            if len(parts) == 2 and " | " not in parts[0]:
                pass  # default path description
            else:
                self.aciklama.insert(0, ham)
        else:
            if ham and " → " not in ham:
                self.aciklama.insert(0, ham)

    def _kasa_bilgi(self):
        kid = self._kasa_map.get(self.kasa.get())
        if not kid:
            self.kasa_bilgi.configure(text="")
            return
        h = FinansService.hesap_getir(kid)
        if h:
            self.kasa_bilgi.configure(text=f"Kasa bakiyesi: {_para(FinansService.bakiye(h))}")

    def _hesaplari_doldur(self):
        self._hesap_map = {}
        self.hesap.set("")
        self.hesap_bilgi.configure(text="")
        banka_id = self._banka_map.get(self.banka.get())
        if not banka_id:
            self.hesap.configure(values=[])
            return
        hesaplar = FinansService.banka_yatirim_hesaplari(banka_karti_id=banka_id)
        etiketler = []
        for h in hesaplar:
            alt = (h.alt_hesap_turu or "").upper() or "BANKA"
            tip = self.ALT_ETIKET.get(alt, alt.title())
            bak = FinansService.bakiye(h)
            etiket = f"{tip} — {_para(bak)}"
            if etiket in self._hesap_map:
                etiket = f"{h.hesap_adi} ({_para(bak)})"
            self._hesap_map[etiket] = h.id
            etiketler.append(etiket)
        self.hesap.configure(values=etiketler)
        if etiketler:
            secim = etiketler[0]
            for e, hid in self._hesap_map.items():
                hh = next((x for x in hesaplar if x.id == hid), None)
                if hh and (hh.alt_hesap_turu or "").upper() == "MEVDUAT":
                    secim = e
                    break
            self.hesap.set(secim)
            self._hesap_bilgi()
        else:
            self.hesap_bilgi.configure(
                text="Bu bankada yatırılabilecek hesap yok (mevduat/KMH/KK/vadeli)."
            )

    def _hesap_bilgi(self):
        hid = self._hesap_map.get(self.hesap.get())
        if not hid:
            self.hesap_bilgi.configure(text="")
            return
        h = FinansService.hesap_getir(hid)
        if not h:
            return
        alt = (h.alt_hesap_turu or "").upper() or "—"
        tip = self.ALT_ETIKET.get(alt, alt)
        self.hesap_bilgi.configure(
            text=f"{h.hesap_adi} · Tür: {tip} · Bakiye: {_para(FinansService.bakiye(h))}"
        )

    def kaydet(self):
        try:
            tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
            kasa_id = self._kasa_map.get(self.kasa.get())
            if not kasa_id:
                raise ValueError("Kasa seçin.")
            if not self._banka_map.get(self.banka.get()):
                raise ValueError("Banka seçin.")
            hesap_id = self._hesap_map.get(self.hesap.get())
            if not hesap_id:
                raise ValueError("Banka hesabı seçin.")
            belge = FinansService.kasadan_bankaya_yatan(
                kasa_id,
                hesap_id,
                tarih,
                self.tutar.get(),
                aciklama=self.aciklama.get().strip() or None,
                dekont_no=self.dekont.get().strip() or None,
                belge_no=self.belge_no,
            )
        except ValueError as hata:
            messagebox.showerror("Fiş", str(hata), parent=self)
            return
        self.result = belge
        messagebox.showinfo(
            "Kaydedildi" if not self.belge_no else "Güncellendi",
            f"Belge no: {belge}",
            parent=self,
        )
        self.destroy()


def bankadan_cekilen_sayfasi_goster(app):
    """Bankadan çekilen (nakit) fiş listesi + yeni fiş."""
    app._icerigi_temizle()
    _finans_menu_isaretle(app)

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="BANKADAN ÇEKİLEN", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Banka İşlemleri", command=lambda: banka_islemleri_menusu_goster(app)).pack(
        side="right"
    )
    ttk.Label(
        app.icerik,
        text="Mevduat, KMH, kredi kartı veya vadeli hesaptan nakit çekip kasaya yatırma.",
    ).pack(anchor="w", pady=(10, 6))

    butonlar = ttk.Frame(app.icerik)
    butonlar.pack(fill="x", pady=(4, 8))
    ttk.Button(butonlar, text="Yeni Fiş", command=lambda: _bnc_yeni_fis(app)).pack(side="left")
    ttk.Button(butonlar, text="Güncelle", command=lambda: _bnc_guncelle_fis(app, tablo)).pack(
        side="left", padx=8
    )
    ttk.Button(
        butonlar,
        text="Yenile",
        command=lambda: bankadan_cekilen_sayfasi_goster(app),
    ).pack(side="left", padx=8)

    cerceve = ttk.Frame(app.icerik)
    cerceve.pack(fill="both", expand=True)
    tablo = ttk.Treeview(
        cerceve,
        columns=("tarih", "belge", "banka", "kasa", "tutar", "aciklama"),
        show="headings",
        selectmode="browse",
    )
    for k, b, w in (
        ("tarih", "Tarih", 90),
        ("belge", "Belge No", 120),
        ("banka", "Banka hesabı", 220),
        ("kasa", "Kasa", 150),
        ("tutar", "Tutar", 110),
        ("aciklama", "Açıklama", 260),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="w")
    kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=kaydir.set)
    tablo.pack(side="left", fill="both", expand=True)
    kaydir.pack(side="right", fill="y")
    tablo.bind("<Double-1>", lambda _e: _bnc_guncelle_fis(app, tablo))

    for kayit in FinansService.bankadan_nakit_cekilen_listele():
        tablo.insert(
            "",
            "end",
            iid=kayit["belge_no"],
            values=(
                _tarih(kayit["tarih"]),
                kayit["belge_no"],
                kayit["banka_hesap"],
                kayit["kasa"],
                _para(kayit["tutar"]),
                kayit["aciklama"],
            ),
        )


def _bnc_yeni_fis(app):
    dialog = BankadanCekilenDialog(app)
    app.wait_window(dialog)
    if dialog.result:
        bankadan_cekilen_sayfasi_goster(app)


def _bnc_guncelle_fis(app, tablo):
    secim = tablo.selection()
    if not secim:
        messagebox.showinfo("Güncelle", "Lütfen güncellenecek fişi seçin.", parent=app)
        return
    dialog = BankadanCekilenDialog(app, belge_no=secim[0])
    app.wait_window(dialog)
    if dialog.result:
        bankadan_cekilen_sayfasi_goster(app)


class BankadanCekilenDialog(tk.Toplevel):
    """Bankadan çekilen fiş formu (KBY'nin tersi)."""

    ALT_ETIKET = KasadanBankayaYatirDialog.ALT_ETIKET

    def __init__(self, parent, belge_no=None):
        super().__init__(parent)
        self.result = None
        self.belge_no = belge_no
        self._mevcut = None
        if belge_no:
            try:
                self._mevcut = FinansService.banka_islem_fis_getir(belge_no)
            except ValueError as hata:
                messagebox.showerror("Fiş", str(hata), parent=parent)
                self.destroy()
                return
        self.title("Bankadan Çekilen — Güncelle" if belge_no else "Bankadan Çekilen")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)

        self._kasa_map = {}
        self._banka_map = {}
        self._hesap_map = {}

        row = 0
        ttk.Label(self, text="Tarih *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        tarih_c = ttk.Frame(self)
        tarih_c.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.tarih = ttk.Entry(tarih_c, width=14)
        self.tarih.pack(side="left")
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        takvim_butonu(tarih_c, self.tarih)

        row = 1
        kartlar = FinansService.banka_kartlari(aktif_only=True)
        ttk.Label(self, text="Banka *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.banka = ttk.Combobox(self, state="readonly", width=42)
        self.banka.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        banka_etiketleri = []
        for k in kartlar:
            etiket = k.banka_adi
            if k.sube:
                etiket = f"{etiket} / {k.sube}"
            if k.hesap_no:
                etiket = f"{etiket} ({k.hesap_no})"
            self._banka_map[etiket] = k.id
            banka_etiketleri.append(etiket)
        self.banka.configure(values=banka_etiketleri)
        if banka_etiketleri:
            self.banka.set(banka_etiketleri[0])
        self.banka.bind("<<ComboboxSelected>>", lambda _e: self._hesaplari_doldur())

        row = 2
        ttk.Label(self, text="Banka hesabı *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.hesap = ttk.Combobox(self, state="readonly", width=42)
        self.hesap.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        self.hesap.bind("<<ComboboxSelected>>", lambda _e: self._hesap_bilgi())
        ttk.Label(
            self,
            text="(Mevduat, KMH, kredi kartı, vadeli)",
            foreground="#555",
        ).grid(row=row, column=3, sticky="w")

        row = 3
        self.hesap_bilgi = ttk.Label(self, text="", foreground="#555")
        self.hesap_bilgi.grid(row=row, column=1, columnspan=2, padx=12, sticky="w")

        row = 4
        kasalar = FinansService.hesaplar(hesap_turu="KASA")
        ttk.Label(self, text="Kasa *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.kasa = ttk.Combobox(self, state="readonly", width=42)
        self.kasa.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        kasa_etiketleri = []
        for h in kasalar:
            bak = FinansService.bakiye(h)
            etiket = f"{h.hesap_adi}  ({_para(bak)})"
            self._kasa_map[etiket] = h.id
            kasa_etiketleri.append(etiket)
        self.kasa.configure(values=kasa_etiketleri)
        if kasa_etiketleri:
            self.kasa.set(kasa_etiketleri[0])
        self.kasa.bind("<<ComboboxSelected>>", lambda _e: self._kasa_bilgi())

        row = 5
        self.kasa_bilgi = ttk.Label(self, text="", foreground="#555")
        self.kasa_bilgi.grid(row=row, column=1, columnspan=2, padx=12, sticky="w")

        row = 6
        ttk.Label(self, text="Tutar *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.tutar = ttk.Entry(self, width=18)
        self.tutar.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        row = 7
        ttk.Label(self, text="Dekont / makbuz no").grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        self.dekont = ttk.Entry(self, width=24)
        self.dekont.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        row = 8
        ttk.Label(self, text="Açıklama").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.aciklama = ttk.Entry(self, width=44)
        self.aciklama.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")

        if self.belge_no:
            ttk.Label(
                self,
                text=f"Belge: {self.belge_no}",
                foreground="#555",
            ).grid(row=9, column=0, columnspan=2, padx=12, sticky="w")

        butonlar = ttk.Frame(self)
        butonlar.grid(row=10, column=0, columnspan=3, padx=12, pady=14, sticky="e")
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(
            butonlar,
            text="Güncelle" if self.belge_no else "Kaydet",
            command=self.kaydet,
        ).pack(side="right")

        self._hesaplari_doldur()
        self._kasa_bilgi()
        self._mevcutu_yukle()

    def _mevcutu_yukle(self):
        m = self._mevcut
        if not m:
            return
        self.tarih.delete(0, "end")
        self.tarih.insert(0, m["tarih"].strftime("%d.%m.%Y"))
        self.tutar.delete(0, "end")
        self.tutar.insert(0, str(m["tutar"]))
        if m.get("dekont_no"):
            self.dekont.insert(0, m["dekont_no"])
        _combobox_id_sec(self.banka, self._banka_map, m.get("banka_karti_id"))
        self._hesaplari_doldur()
        _combobox_id_sec(self.hesap, self._hesap_map, m.get("banka_hesap_id"))
        self._hesap_bilgi()
        _combobox_id_sec(self.kasa, self._kasa_map, m.get("kasa_id"))
        self._kasa_bilgi()
        self.aciklama.delete(0, "end")
        ham = m.get("aciklama") or ""
        if ham and " → " not in ham:
            self.aciklama.insert(0, ham)

    def _kasa_bilgi(self):
        kid = self._kasa_map.get(self.kasa.get())
        if not kid:
            self.kasa_bilgi.configure(text="")
            return
        h = FinansService.hesap_getir(kid)
        if h:
            self.kasa_bilgi.configure(text=f"Kasa bakiyesi: {_para(FinansService.bakiye(h))}")

    def _hesaplari_doldur(self):
        self._hesap_map = {}
        self.hesap.set("")
        self.hesap_bilgi.configure(text="")
        banka_id = self._banka_map.get(self.banka.get())
        if not banka_id:
            self.hesap.configure(values=[])
            return
        hesaplar = FinansService.banka_yatirim_hesaplari(banka_karti_id=banka_id)
        etiketler = []
        for h in hesaplar:
            alt = (h.alt_hesap_turu or "").upper() or "BANKA"
            tip = self.ALT_ETIKET.get(alt, alt.title())
            bak = FinansService.bakiye(h)
            etiket = f"{tip} — {_para(bak)}"
            if etiket in self._hesap_map:
                etiket = f"{h.hesap_adi} ({_para(bak)})"
            self._hesap_map[etiket] = h.id
            etiketler.append(etiket)
        self.hesap.configure(values=etiketler)
        if etiketler:
            secim = etiketler[0]
            for e, hid in self._hesap_map.items():
                hh = next((x for x in hesaplar if x.id == hid), None)
                if hh and (hh.alt_hesap_turu or "").upper() == "MEVDUAT":
                    secim = e
                    break
            self.hesap.set(secim)
            self._hesap_bilgi()
        else:
            self.hesap_bilgi.configure(
                text="Bu bankada çekilebilecek hesap yok (mevduat/KMH/KK/vadeli)."
            )

    def _hesap_bilgi(self):
        hid = self._hesap_map.get(self.hesap.get())
        if not hid:
            self.hesap_bilgi.configure(text="")
            return
        h = FinansService.hesap_getir(hid)
        if not h:
            return
        alt = (h.alt_hesap_turu or "").upper() or "—"
        tip = self.ALT_ETIKET.get(alt, alt)
        self.hesap_bilgi.configure(
            text=f"{h.hesap_adi} · Tür: {tip} · Bakiye: {_para(FinansService.bakiye(h))}"
        )

    def kaydet(self):
        try:
            tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
            if not self._banka_map.get(self.banka.get()):
                raise ValueError("Banka seçin.")
            hesap_id = self._hesap_map.get(self.hesap.get())
            if not hesap_id:
                raise ValueError("Banka hesabı seçin.")
            kasa_id = self._kasa_map.get(self.kasa.get())
            if not kasa_id:
                raise ValueError("Kasa seçin.")
            belge = FinansService.bankadan_nakit_cekilen(
                hesap_id,
                kasa_id,
                tarih,
                self.tutar.get(),
                aciklama=self.aciklama.get().strip() or None,
                dekont_no=self.dekont.get().strip() or None,
                belge_no=self.belge_no,
            )
        except ValueError as hata:
            messagebox.showerror("Fiş", str(hata), parent=self)
            return
        self.result = belge
        messagebox.showinfo(
            "Kaydedildi" if not self.belge_no else "Güncellendi",
            f"Belge no: {belge}",
            parent=self,
        )
        self.destroy()


def alinan_havale_sayfasi_goster(app):
    _havale_sayfasi_goster(
        app,
        baslik="ALINAN HAVALE",
        aciklama="Gönderen cariden banka hesabına gelen havale (cari tahsilat).",
        tur="ahv",
        liste_fn=FinansService.alinan_havale_listele,
        cari_kolon="Gönderen cari",
    )


def gonderilen_havale_sayfasi_goster(app):
    _havale_sayfasi_goster(
        app,
        baslik="GÖNDERİLEN HAVALE",
        aciklama="Banka hesabından alıcı cariye giden havale (cari ödeme).",
        tur="ghv",
        liste_fn=FinansService.gonderilen_havale_listele,
        cari_kolon="Alıcı cari",
    )


def _havale_sayfasi_goster(app, baslik, aciklama, tur, liste_fn, cari_kolon):
    app._icerigi_temizle()
    _finans_menu_isaretle(app)

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text=baslik, style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Banka İşlemleri", command=lambda: banka_islemleri_menusu_goster(app)).pack(
        side="right"
    )
    ttk.Label(app.icerik, text=aciklama).pack(anchor="w", pady=(10, 6))

    butonlar = ttk.Frame(app.icerik)
    butonlar.pack(fill="x", pady=(4, 8))

    def _yenile():
        if tur == "ahv":
            alinan_havale_sayfasi_goster(app)
        else:
            gonderilen_havale_sayfasi_goster(app)

    def _yeni():
        dialog = HavaleFisDialog(app, tur=tur)
        app.wait_window(dialog)
        if dialog.result:
            _yenile()

    def _guncelle():
        secim = tablo.selection()
        if not secim:
            messagebox.showinfo("Güncelle", "Lütfen güncellenecek fişi seçin.", parent=app)
            return
        dialog = HavaleFisDialog(app, tur=tur, belge_no=secim[0])
        app.wait_window(dialog)
        if dialog.result:
            _yenile()

    ttk.Button(butonlar, text="Yeni Fiş", command=_yeni).pack(side="left")
    ttk.Button(butonlar, text="Güncelle", command=_guncelle).pack(side="left", padx=8)
    ttk.Button(butonlar, text="Yenile", command=_yenile).pack(side="left", padx=8)

    cerceve = ttk.Frame(app.icerik)
    cerceve.pack(fill="both", expand=True)
    tablo = ttk.Treeview(
        cerceve,
        columns=("tarih", "belge", "cari", "banka", "tutar", "aciklama"),
        show="headings",
        selectmode="browse",
    )
    for k, b, w in (
        ("tarih", "Tarih", 90),
        ("belge", "Belge No", 120),
        ("cari", cari_kolon, 220),
        ("banka", "Banka hesabı", 200),
        ("tutar", "Tutar", 110),
        ("aciklama", "Açıklama", 240),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="w")
    kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=kaydir.set)
    tablo.pack(side="left", fill="both", expand=True)
    kaydir.pack(side="right", fill="y")
    tablo.bind("<Double-1>", lambda _e: _guncelle())

    for kayit in liste_fn():
        tablo.insert(
            "",
            "end",
            iid=kayit["belge_no"],
            values=(
                _tarih(kayit["tarih"]),
                kayit["belge_no"],
                kayit["cari"],
                kayit["banka_hesap"],
                _para(kayit["tutar"]),
                kayit["aciklama"],
            ),
        )


class HavaleFisDialog(tk.Toplevel):
    """Alınan / gönderilen havale fiş formu."""

    ALT_ETIKET = KasadanBankayaYatirDialog.ALT_ETIKET

    def __init__(self, parent, tur: str, belge_no=None):
        super().__init__(parent)
        self.tur = tur  # ahv | ghv
        self.result = None
        self.belge_no = belge_no
        self._mevcut = None
        if belge_no:
            try:
                self._mevcut = FinansService.banka_islem_fis_getir(belge_no)
            except ValueError as hata:
                messagebox.showerror("Fiş", str(hata), parent=parent)
                self.destroy()
                return
        alinan = tur == "ahv"
        baslik = "Alınan Havale" if alinan else "Gönderilen Havale"
        self.title(f"{baslik} — Güncelle" if belge_no else baslik)
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)

        from database.cari_service import CariService

        self._cari_map = {}
        self._banka_map = {}
        self._hesap_map = {}

        row = 0
        ttk.Label(self, text="Tarih *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        tarih_c = ttk.Frame(self)
        tarih_c.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.tarih = ttk.Entry(tarih_c, width=14)
        self.tarih.pack(side="left")
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        takvim_butonu(tarih_c, self.tarih)

        row = 1
        cari_etiket = "Gönderen cari *" if alinan else "Alıcı cari *"
        cariler = CariService.listele()
        self._cari_map = {
            f"{o['cari'].cari_kodu} - {o['cari'].unvan}": o["cari"].id for o in cariler
        }
        ttk.Label(self, text=cari_etiket).grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.cari = ttk.Combobox(self, values=list(self._cari_map), width=42)
        self.cari.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        if self._cari_map:
            self.cari.set(next(iter(self._cari_map)))

        row = 2
        kartlar = FinansService.banka_kartlari(aktif_only=True)
        ttk.Label(self, text="Banka *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.banka = ttk.Combobox(self, state="readonly", width=42)
        self.banka.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        banka_etiketleri = []
        for k in kartlar:
            etiket = k.banka_adi
            if k.sube:
                etiket = f"{etiket} / {k.sube}"
            if k.hesap_no:
                etiket = f"{etiket} ({k.hesap_no})"
            self._banka_map[etiket] = k.id
            banka_etiketleri.append(etiket)
        self.banka.configure(values=banka_etiketleri)
        if banka_etiketleri:
            self.banka.set(banka_etiketleri[0])
        self.banka.bind("<<ComboboxSelected>>", lambda _e: self._hesaplari_doldur())

        row = 3
        ttk.Label(self, text="Banka hesabı *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.hesap = ttk.Combobox(self, state="readonly", width=42)
        self.hesap.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        self.hesap.bind("<<ComboboxSelected>>", lambda _e: self._hesap_bilgi())
        ttk.Label(
            self,
            text="(Mevduat, KMH, kredi kartı, vadeli)",
            foreground="#555",
        ).grid(row=row, column=3, sticky="w")

        row = 4
        self.hesap_bilgi = ttk.Label(self, text="", foreground="#555")
        self.hesap_bilgi.grid(row=row, column=1, columnspan=2, padx=12, sticky="w")

        row = 5
        ttk.Label(self, text="Meblağ *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.tutar = ttk.Entry(self, width=18)
        self.tutar.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        row = 6
        ttk.Label(self, text="Dekont / referans no").grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        self.dekont = ttk.Entry(self, width=24)
        self.dekont.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        row = 7
        ttk.Label(self, text="Açıklama").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.aciklama = ttk.Entry(self, width=44)
        self.aciklama.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")

        if self.belge_no:
            ttk.Label(
                self,
                text=f"Belge: {self.belge_no}",
                foreground="#555",
            ).grid(row=8, column=0, columnspan=2, padx=12, sticky="w")

        butonlar = ttk.Frame(self)
        butonlar.grid(row=9, column=0, columnspan=3, padx=12, pady=14, sticky="e")
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(
            butonlar,
            text="Güncelle" if self.belge_no else "Kaydet",
            command=self.kaydet,
        ).pack(side="right")

        self._hesaplari_doldur()
        self._mevcutu_yukle()

    def _mevcutu_yukle(self):
        m = self._mevcut
        if not m:
            return
        self.tarih.delete(0, "end")
        self.tarih.insert(0, m["tarih"].strftime("%d.%m.%Y"))
        self.tutar.delete(0, "end")
        self.tutar.insert(0, str(m["tutar"]))
        if m.get("dekont_no"):
            self.dekont.insert(0, m["dekont_no"])
        cari_etiket = (m.get("cari_etiket") or "").strip()
        if cari_etiket and cari_etiket in self._cari_map:
            self.cari.set(cari_etiket)
        else:
            _combobox_id_sec(self.cari, self._cari_map, m.get("cari_id"))
        _combobox_id_sec(self.banka, self._banka_map, m.get("banka_karti_id"))
        self._hesaplari_doldur()
        _combobox_id_sec(self.hesap, self._hesap_map, m.get("banka_hesap_id"))
        self._hesap_bilgi()
        self.aciklama.delete(0, "end")
        ham = m.get("aciklama") or ""
        varsayilan = "Alınan havale" if self.tur == "ahv" else "Gönderilen havale"
        if ham and ham != varsayilan:
            self.aciklama.insert(0, ham)

    def _hesaplari_doldur(self):
        self._hesap_map = {}
        self.hesap.set("")
        self.hesap_bilgi.configure(text="")
        banka_id = self._banka_map.get(self.banka.get())
        if not banka_id:
            self.hesap.configure(values=[])
            return
        hesaplar = FinansService.banka_yatirim_hesaplari(banka_karti_id=banka_id)
        etiketler = []
        for h in hesaplar:
            alt = (h.alt_hesap_turu or "").upper() or "BANKA"
            tip = self.ALT_ETIKET.get(alt, alt.title())
            bak = FinansService.bakiye(h)
            etiket = f"{tip} — {_para(bak)}"
            if etiket in self._hesap_map:
                etiket = f"{h.hesap_adi} ({_para(bak)})"
            self._hesap_map[etiket] = h.id
            etiketler.append(etiket)
        self.hesap.configure(values=etiketler)
        if etiketler:
            secim = etiketler[0]
            for e, hid in self._hesap_map.items():
                hh = next((x for x in hesaplar if x.id == hid), None)
                if hh and (hh.alt_hesap_turu or "").upper() == "MEVDUAT":
                    secim = e
                    break
            self.hesap.set(secim)
            self._hesap_bilgi()
        else:
            self.hesap_bilgi.configure(text="Bu bankada uygun hesap yok.")

    def _hesap_bilgi(self):
        hid = self._hesap_map.get(self.hesap.get())
        if not hid:
            self.hesap_bilgi.configure(text="")
            return
        h = FinansService.hesap_getir(hid)
        if not h:
            return
        alt = (h.alt_hesap_turu or "").upper() or "—"
        tip = self.ALT_ETIKET.get(alt, alt)
        self.hesap_bilgi.configure(
            text=f"{h.hesap_adi} · Tür: {tip} · Bakiye: {_para(FinansService.bakiye(h))}"
        )

    def kaydet(self):
        try:
            tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
            cari_id = self._cari_map.get(self.cari.get().strip()) if self.cari.get() else None
            if cari_id is None:
                raise ValueError(
                    "Gönderen cari seçin." if self.tur == "ahv" else "Alıcı cari seçin."
                )
            if not self._banka_map.get(self.banka.get()):
                raise ValueError("Banka seçin.")
            hesap_id = self._hesap_map.get(self.hesap.get())
            if not hesap_id:
                raise ValueError("Banka hesabı seçin.")
            kwargs = dict(
                banka_hesap_id=hesap_id,
                tarih=tarih,
                tutar=self.tutar.get(),
                cari_id=cari_id,
                aciklama=self.aciklama.get().strip() or None,
                dekont_no=self.dekont.get().strip() or None,
                belge_no=self.belge_no,
            )
            if self.tur == "ahv":
                belge = FinansService.alinan_havale(**kwargs)
            else:
                belge = FinansService.gonderilen_havale(**kwargs)
        except ValueError as hata:
            messagebox.showerror("Fiş", str(hata), parent=self)
            return
        self.result = belge
        messagebox.showinfo(
            "Kaydedildi" if not self.belge_no else "Güncellendi",
            f"Belge no: {belge}",
            parent=self,
        )
        self.destroy()


def bankalar_arasi_virman_sayfasi_goster(app):
    app._icerigi_temizle()
    _finans_menu_isaretle(app)

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="BANKALAR ARASI VİRMAN", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Banka İşlemleri", command=lambda: banka_islemleri_menusu_goster(app)).pack(
        side="right"
    )
    ttk.Label(
        app.icerik,
        text="Bir banka hesabından diğerine EFT veya havale ile virman.",
    ).pack(anchor="w", pady=(10, 6))

    butonlar = ttk.Frame(app.icerik)
    butonlar.pack(fill="x", pady=(4, 8))

    def _yeni():
        dialog = BankalarArasiVirmanDialog(app)
        app.wait_window(dialog)
        if dialog.result:
            bankalar_arasi_virman_sayfasi_goster(app)

    def _guncelle():
        secim = tablo.selection()
        if not secim:
            messagebox.showinfo("Güncelle", "Lütfen güncellenecek fişi seçin.", parent=app)
            return
        dialog = BankalarArasiVirmanDialog(app, belge_no=secim[0])
        app.wait_window(dialog)
        if dialog.result:
            bankalar_arasi_virman_sayfasi_goster(app)

    ttk.Button(butonlar, text="Yeni Fiş", command=_yeni).pack(side="left")
    ttk.Button(butonlar, text="Güncelle", command=_guncelle).pack(side="left", padx=8)
    ttk.Button(
        butonlar,
        text="Yenile",
        command=lambda: bankalar_arasi_virman_sayfasi_goster(app),
    ).pack(side="left", padx=8)

    cerceve = ttk.Frame(app.icerik)
    cerceve.pack(fill="both", expand=True)
    tablo = ttk.Treeview(
        cerceve,
        columns=("tarih", "belge", "tur", "cikis", "giris", "tutar", "aciklama"),
        show="headings",
        selectmode="browse",
    )
    for k, b, w in (
        ("tarih", "Tarih", 90),
        ("belge", "Belge No", 110),
        ("tur", "Tür", 70),
        ("cikis", "Çıkış hesabı", 200),
        ("giris", "Giriş hesabı", 200),
        ("tutar", "Tutar", 100),
        ("aciklama", "Açıklama", 220),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="w")
    kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=kaydir.set)
    tablo.pack(side="left", fill="both", expand=True)
    kaydir.pack(side="right", fill="y")
    tablo.bind("<Double-1>", lambda _e: _guncelle())

    for kayit in FinansService.bankalar_arasi_virman_listele():
        tablo.insert(
            "",
            "end",
            iid=kayit["belge_no"],
            values=(
                _tarih(kayit["tarih"]),
                kayit["belge_no"],
                kayit["belge_turu"],
                kayit["cikis_hesap"],
                kayit["giris_hesap"],
                _para(kayit["tutar"]),
                kayit["aciklama"],
            ),
        )


class BankalarArasiVirmanDialog(tk.Toplevel):
    """Çıkış bankası → giriş bankası virman (EFT / Havale)."""

    ALT_ETIKET = KasadanBankayaYatirDialog.ALT_ETIKET

    def __init__(self, parent, belge_no=None):
        super().__init__(parent)
        self.result = None
        self.belge_no = belge_no
        self._mevcut = None
        if belge_no:
            try:
                self._mevcut = FinansService.banka_islem_fis_getir(belge_no)
            except ValueError as hata:
                messagebox.showerror("Fiş", str(hata), parent=parent)
                self.destroy()
                return
        self.title(
            "Bankalar Arası Virman — Güncelle" if belge_no else "Bankalar Arası Virman"
        )
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)

        self._cikis_banka_map = {}
        self._giris_banka_map = {}
        self._cikis_hesap_map = {}
        self._giris_hesap_map = {}

        row = 0
        ttk.Label(self, text="Tarih *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        tarih_c = ttk.Frame(self)
        tarih_c.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.tarih = ttk.Entry(tarih_c, width=14)
        self.tarih.pack(side="left")
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        takvim_butonu(tarih_c, self.tarih)

        row = 1
        ttk.Label(self, text="Belge türü *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.belge_turu = ttk.Combobox(
            self, values=("EFT", "HAVALE"), state="readonly", width=16
        )
        self.belge_turu.set("HAVALE")
        self.belge_turu.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        # --- Çıkış ---
        row = 2
        ttk.Label(self, text="Çıkış bankası *").grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        self.cikis_banka = ttk.Combobox(self, state="readonly", width=42)
        self.cikis_banka.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        self.cikis_banka.bind(
            "<<ComboboxSelected>>", lambda _e: self._hesaplari_doldur("cikis")
        )

        row = 3
        ttk.Label(self, text="Çıkış hesabı *").grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        self.cikis_hesap = ttk.Combobox(self, state="readonly", width=42)
        self.cikis_hesap.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        self.cikis_hesap.bind("<<ComboboxSelected>>", lambda _e: self._hesap_bilgi("cikis"))

        row = 4
        self.cikis_bilgi = ttk.Label(self, text="", foreground="#555")
        self.cikis_bilgi.grid(row=row, column=1, columnspan=2, padx=12, sticky="w")

        # --- Giriş ---
        row = 5
        ttk.Label(self, text="Giriş bankası *").grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        self.giris_banka = ttk.Combobox(self, state="readonly", width=42)
        self.giris_banka.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        self.giris_banka.bind(
            "<<ComboboxSelected>>", lambda _e: self._hesaplari_doldur("giris")
        )

        row = 6
        ttk.Label(self, text="Giriş hesabı *").grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        self.giris_hesap = ttk.Combobox(self, state="readonly", width=42)
        self.giris_hesap.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        self.giris_hesap.bind("<<ComboboxSelected>>", lambda _e: self._hesap_bilgi("giris"))

        row = 7
        self.giris_bilgi = ttk.Label(self, text="", foreground="#555")
        self.giris_bilgi.grid(row=row, column=1, columnspan=2, padx=12, sticky="w")

        row = 8
        ttk.Label(self, text="Meblağ *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.tutar = ttk.Entry(self, width=18)
        self.tutar.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        row = 9
        ttk.Label(self, text="Dekont / referans no").grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        self.dekont = ttk.Entry(self, width=24)
        self.dekont.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        row = 10
        ttk.Label(self, text="Açıklama").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.aciklama = ttk.Entry(self, width=44)
        self.aciklama.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")

        if self.belge_no:
            ttk.Label(
                self,
                text=f"Belge: {self.belge_no}",
                foreground="#555",
            ).grid(row=11, column=0, columnspan=2, padx=12, sticky="w")

        butonlar = ttk.Frame(self)
        butonlar.grid(row=12, column=0, columnspan=3, padx=12, pady=14, sticky="e")
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(
            butonlar,
            text="Güncelle" if self.belge_no else "Kaydet",
            command=self.kaydet,
        ).pack(side="right")

        self._bankalari_doldur()
        self._mevcutu_yukle()

    def _mevcutu_yukle(self):
        m = self._mevcut
        if not m:
            return
        self.tarih.delete(0, "end")
        self.tarih.insert(0, m["tarih"].strftime("%d.%m.%Y"))
        self.tutar.delete(0, "end")
        self.tutar.insert(0, str(m["tutar"]))
        if m.get("dekont_no"):
            self.dekont.insert(0, m["dekont_no"])
        belge_turu = (m.get("belge_turu") or "HAVALE").strip().upper()
        if belge_turu in ("EFT", "HAVALE"):
            self.belge_turu.set(belge_turu)
        _combobox_id_sec(self.cikis_banka, self._cikis_banka_map, m.get("cikis_banka_karti_id"))
        self._hesaplari_doldur("cikis")
        _combobox_id_sec(self.cikis_hesap, self._cikis_hesap_map, m.get("cikis_hesap_id"))
        self._hesap_bilgi("cikis")
        _combobox_id_sec(self.giris_banka, self._giris_banka_map, m.get("giris_banka_karti_id"))
        self._hesaplari_doldur("giris")
        _combobox_id_sec(self.giris_hesap, self._giris_hesap_map, m.get("giris_hesap_id"))
        self._hesap_bilgi("giris")
        self.aciklama.delete(0, "end")
        ham = m.get("aciklama") or ""
        if ham and " → " not in ham:
            self.aciklama.insert(0, ham)

    def _banka_etiket(self, k):
        etiket = k.banka_adi
        if k.sube:
            etiket = f"{etiket} / {k.sube}"
        if k.hesap_no:
            etiket = f"{etiket} ({k.hesap_no})"
        return etiket

    def _bankalari_doldur(self):
        kartlar = FinansService.banka_kartlari(aktif_only=True)
        etiketler = []
        self._cikis_banka_map = {}
        self._giris_banka_map = {}
        for k in kartlar:
            etiket = self._banka_etiket(k)
            self._cikis_banka_map[etiket] = k.id
            self._giris_banka_map[etiket] = k.id
            etiketler.append(etiket)
        self.cikis_banka.configure(values=etiketler)
        self.giris_banka.configure(values=etiketler)
        if etiketler:
            self.cikis_banka.set(etiketler[0])
            # Giriş için mümkünse ikinci banka
            self.giris_banka.set(etiketler[1] if len(etiketler) > 1 else etiketler[0])
        self._hesaplari_doldur("cikis")
        self._hesaplari_doldur("giris")

    def _hesaplari_doldur(self, yon: str):
        if yon == "cikis":
            banka_cb, hesap_cb, bilgi, bmap, hmap = (
                self.cikis_banka,
                self.cikis_hesap,
                self.cikis_bilgi,
                self._cikis_banka_map,
                "_cikis_hesap_map",
            )
        else:
            banka_cb, hesap_cb, bilgi, bmap, hmap = (
                self.giris_banka,
                self.giris_hesap,
                self.giris_bilgi,
                self._giris_banka_map,
                "_giris_hesap_map",
            )
        setattr(self, hmap, {})
        hesap_cb.set("")
        bilgi.configure(text="")
        banka_id = bmap.get(banka_cb.get())
        if not banka_id:
            hesap_cb.configure(values=[])
            return
        hesaplar = FinansService.banka_yatirim_hesaplari(banka_karti_id=banka_id)
        etiketler = []
        hesap_map = {}
        for h in hesaplar:
            alt = (h.alt_hesap_turu or "").upper() or "BANKA"
            tip = self.ALT_ETIKET.get(alt, alt.title())
            bak = FinansService.bakiye(h)
            etiket = f"{tip} — {_para(bak)}"
            if etiket in hesap_map:
                etiket = f"{h.hesap_adi} ({_para(bak)})"
            hesap_map[etiket] = h.id
            etiketler.append(etiket)
        setattr(self, hmap, hesap_map)
        hesap_cb.configure(values=etiketler)
        if etiketler:
            secim = etiketler[0]
            for e, hid in hesap_map.items():
                hh = next((x for x in hesaplar if x.id == hid), None)
                if hh and (hh.alt_hesap_turu or "").upper() == "MEVDUAT":
                    secim = e
                    break
            hesap_cb.set(secim)
            self._hesap_bilgi(yon)
        else:
            bilgi.configure(text="Bu bankada uygun hesap yok.")

    def _hesap_bilgi(self, yon: str):
        if yon == "cikis":
            hesap_cb, bilgi, hmap = self.cikis_hesap, self.cikis_bilgi, self._cikis_hesap_map
        else:
            hesap_cb, bilgi, hmap = self.giris_hesap, self.giris_bilgi, self._giris_hesap_map
        hid = hmap.get(hesap_cb.get())
        if not hid:
            bilgi.configure(text="")
            return
        h = FinansService.hesap_getir(hid)
        if not h:
            return
        alt = (h.alt_hesap_turu or "").upper() or "—"
        tip = self.ALT_ETIKET.get(alt, alt)
        bilgi.configure(
            text=f"{h.hesap_adi} · Tür: {tip} · Bakiye: {_para(FinansService.bakiye(h))}"
        )

    def kaydet(self):
        try:
            tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
            belge_turu = (self.belge_turu.get() or "").strip().upper()
            if belge_turu not in ("EFT", "HAVALE"):
                raise ValueError("Belge türü EFT veya Havale seçin.")
            cikis_id = self._cikis_hesap_map.get(self.cikis_hesap.get())
            giris_id = self._giris_hesap_map.get(self.giris_hesap.get())
            if not cikis_id:
                raise ValueError("Çıkış bankası hesabını seçin.")
            if not giris_id:
                raise ValueError("Giriş bankası hesabını seçin.")
            belge = FinansService.banka_hesaplari_arasi_virman(
                cikis_id,
                giris_id,
                tarih,
                self.tutar.get(),
                aciklama=self.aciklama.get().strip() or None,
                belge_turu=belge_turu,
                dekont_no=self.dekont.get().strip() or None,
                belge_no=self.belge_no,
            )
        except ValueError as hata:
            messagebox.showerror("Fiş", str(hata), parent=self)
            return
        self.result = belge
        messagebox.showinfo(
            "Kaydedildi" if not self.belge_no else "Güncellendi",
            f"Belge no: {belge}",
            parent=self,
        )
        self.destroy()


def kredi_karti_odeme_sayfasi_goster(app):
    app._icerigi_temizle()
    _finans_menu_isaretle(app)

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="KREDİ KARTI İLE ÖDEME", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Banka İşlemleri", command=lambda: banka_islemleri_menusu_goster(app)).pack(
        side="right"
    )
    ttk.Label(
        app.icerik,
        text="Cariye kredi kartı ile ödeme (tek çekim veya taksitli, max 24).",
    ).pack(anchor="w", pady=(10, 6))

    butonlar = ttk.Frame(app.icerik)
    butonlar.pack(fill="x", pady=(4, 8))

    def _yeni():
        dialog = BankaIslemKkOdemeDialog(app)
        app.wait_window(dialog)
        if dialog.result:
            kredi_karti_odeme_sayfasi_goster(app)

    def _guncelle():
        secim = tablo.selection()
        if not secim:
            messagebox.showinfo("Güncelle", "Lütfen güncellenecek fişi seçin.", parent=app)
            return
        dialog = BankaIslemKkOdemeDialog(app, belge_no=secim[0])
        app.wait_window(dialog)
        if dialog.result:
            kredi_karti_odeme_sayfasi_goster(app)

    ttk.Button(butonlar, text="Yeni Fiş", command=_yeni).pack(side="left")
    ttk.Button(butonlar, text="Güncelle", command=_guncelle).pack(side="left", padx=8)
    ttk.Button(
        butonlar,
        text="Yenile",
        command=lambda: kredi_karti_odeme_sayfasi_goster(app),
    ).pack(side="left", padx=8)

    cerceve = ttk.Frame(app.icerik)
    cerceve.pack(fill="both", expand=True)
    tablo = ttk.Treeview(
        cerceve,
        columns=("tarih", "belge", "cari", "banka", "kart", "cekim", "tutar", "aciklama"),
        show="headings",
        selectmode="browse",
    )
    for k, b, w in (
        ("tarih", "Tarih", 85),
        ("belge", "Belge No", 110),
        ("cari", "Cari", 180),
        ("banka", "Banka", 120),
        ("kart", "Kart", 130),
        ("cekim", "Çekim", 100),
        ("tutar", "Tutar", 100),
        ("aciklama", "Açıklama", 180),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="w")
    kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=kaydir.set)
    tablo.pack(side="left", fill="both", expand=True)
    kaydir.pack(side="right", fill="y")
    tablo.bind("<Double-1>", lambda _e: _guncelle())

    for kayit in FinansService.kredi_karti_odemeleri():
        cekim = kayit["cekim_turu"]
        if kayit["taksit_sayisi"] > 1:
            cekim = f"{cekim} ({kayit['taksit_sayisi']})"
        tablo.insert(
            "",
            "end",
            iid=kayit["belge_no"],
            values=(
                _tarih(kayit["tarih"]),
                kayit["belge_no"],
                kayit["cari"],
                kayit["banka"],
                kayit["kart"],
                cekim,
                _para(kayit["tutar"]),
                kayit["aciklama"],
            ),
        )


class BankaIslemKkOdemeDialog(tk.Toplevel):
    """Banka işlemleri — kredi kartı ile ödeme fişi."""

    def __init__(self, parent, belge_no=None):
        super().__init__(parent)
        self.result = None
        self.belge_no = belge_no
        self._mevcut = None
        if belge_no:
            try:
                self._mevcut = FinansService.kredi_karti_odeme_getir(belge_no)
            except ValueError as hata:
                messagebox.showerror("Fiş", str(hata), parent=parent)
                self.destroy()
                return

        self.title(
            "Kredi Kartı ile Ödeme — Güncelle" if belge_no else "Kredi Kartı ile Ödeme"
        )
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)

        from database.cari_service import CariService

        self._cari_map = {}
        self._banka_map = {}
        self._kart_map = {}
        self._cekim_map = {e: k for k, e in KK_CEKIM_TURLERI}

        row = 0
        ttk.Label(self, text="Tarih *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        tarih_c = ttk.Frame(self)
        tarih_c.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.tarih = ttk.Entry(tarih_c, width=14)
        self.tarih.pack(side="left")
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        takvim_butonu(tarih_c, self.tarih)
        self.tarih.bind("<FocusOut>", lambda _e: self._vade_ve_plan_guncelle())
        self.tarih.bind("<KeyRelease>", lambda _e: self._vade_ve_plan_guncelle())

        row = 1
        cariler = CariService.listele()
        self._cari_map = {
            f"{o['cari'].cari_kodu} - {o['cari'].unvan}": o["cari"].id for o in cariler
        }
        ttk.Label(self, text="Cari hesap *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.cari = ttk.Combobox(self, values=list(self._cari_map), width=42)
        self.cari.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        if self._cari_map:
            self.cari.set(next(iter(self._cari_map)))

        row = 2
        kartlar_banka = FinansService.banka_kartlari(aktif_only=True)
        ttk.Label(self, text="Kredi kartı bankası *").grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        self.banka = ttk.Combobox(self, state="readonly", width=42)
        self.banka.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        banka_etiketleri = []
        for k in kartlar_banka:
            etiket = k.banka_adi
            if k.sube:
                etiket = f"{etiket} / {k.sube}"
            self._banka_map[etiket] = k.id
            banka_etiketleri.append(etiket)
        self.banka.configure(values=banka_etiketleri)
        if banka_etiketleri:
            self.banka.set(banka_etiketleri[0])
        self.banka.bind("<<ComboboxSelected>>", lambda _e: self._kartlari_doldur())

        row = 3
        ttk.Label(self, text="Kredi kartı *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.kart = ttk.Combobox(self, state="readonly", width=42)
        self.kart.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        self.kart.bind("<<ComboboxSelected>>", lambda _e: self._limit_bilgi())

        row = 4
        self.limit_lbl = ttk.Label(self, text="", foreground="#555")
        self.limit_lbl.grid(row=row, column=1, columnspan=2, padx=12, sticky="w")

        row = 5
        ttk.Label(self, text="Çekim türü *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.cekim = ttk.Combobox(
            self,
            values=[e for _k, e in KK_CEKIM_TURLERI],
            state="readonly",
            width=28,
        )
        self.cekim.set("Tek Çekim")
        self.cekim.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.cekim.bind("<<ComboboxSelected>>", lambda _e: self._cekim_degisti())

        row = 6
        ttk.Label(self, text="Taksit sayısı").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.taksit = ttk.Combobox(
            self,
            values=[str(i) for i in range(1, KK_MAX_TAKSIT + 1)],
            width=8,
            state="disabled",
        )
        self.taksit.set("1")
        self.taksit.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.taksit.bind("<<ComboboxSelected>>", lambda _e: self._vade_ve_plan_guncelle())

        row = 7
        ttk.Label(self, text="Vade (1. taksit)").grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        self.vade = ttk.Entry(self, width=14, state="readonly")
        self.vade.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        row = 8
        ttk.Label(self, text="Meblağ *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.tutar = ttk.Entry(self, width=18)
        self.tutar.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.tutar.bind("<KeyRelease>", lambda _e: self._vade_ve_plan_guncelle())

        row = 9
        ttk.Label(self, text="Referans / onay no").grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        self.referans = ttk.Entry(self, width=24)
        self.referans.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        row = 10
        ttk.Label(self, text="Açıklama").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.aciklama = ttk.Entry(self, width=44)
        self.aciklama.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")

        row = 11
        plan_f = ttk.LabelFrame(self, text="Taksit planı önizleme", padding=8)
        plan_f.grid(row=row, column=0, columnspan=3, padx=12, pady=8, sticky="ew")
        self.plan_tablo = ttk.Treeview(
            plan_f,
            columns=("no", "vade", "tutar"),
            show="headings",
            height=6,
        )
        for k, b, w in (("no", "No", 50), ("vade", "Vade", 100), ("tutar", "Tutar", 100)):
            self.plan_tablo.heading(k, text=b)
            self.plan_tablo.column(k, width=w, anchor="w")
        self.plan_tablo.pack(fill="x")

        if self.belge_no:
            ttk.Label(self, text=f"Belge: {self.belge_no}", foreground="#555").grid(
                row=12, column=0, columnspan=2, padx=12, sticky="w"
            )

        butonlar = ttk.Frame(self)
        butonlar.grid(row=13, column=0, columnspan=3, padx=12, pady=12, sticky="e")
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(
            butonlar,
            text="Güncelle" if self.belge_no else "Kaydet",
            command=self.kaydet,
        ).pack(side="right")

        self._kartlari_doldur()
        self._mevcutu_yukle()
        self._vade_ve_plan_guncelle()

    def _kartlari_doldur(self):
        self._kart_map = {}
        self.kart.set("")
        self.limit_lbl.configure(text="")
        banka_id = self._banka_map.get(self.banka.get())
        if not banka_id:
            self.kart.configure(values=[])
            return
        kartlar = FinansService.kredi_kartlari(banka_karti_id=banka_id)
        etiketler = []
        for kk in kartlar:
            etiket = kk.kart_adi
            if kk.son_dort_hane:
                etiket = f"{etiket} (****{kk.son_dort_hane})"
            self._kart_map[etiket] = kk.id
            etiketler.append(etiket)
        self.kart.configure(values=etiketler)
        if etiketler:
            self.kart.set(etiketler[0])
            self._limit_bilgi()
        else:
            self.limit_lbl.configure(
                text="Bu bankada tanımlı kredi kartı yok. Bankalar menüsünden kart ekleyin."
            )

    def _cekim_degisti(self):
        tur = self._cekim_map.get(self.cekim.get(), "TEK_CEKIM")
        if tur == "TEK_CEKIM":
            self.taksit.set("1")
            self.taksit.configure(state="disabled")
        else:
            self.taksit.configure(state="readonly")
            if self.taksit.get() == "1":
                self.taksit.set("2")
        self._vade_ve_plan_guncelle()

    def _limit_bilgi(self):
        kid = self._kart_map.get(self.kart.get())
        if not kid:
            self.limit_lbl.configure(text="")
            return
        kk = FinansService.kredi_karti_getir(kid)
        if not kk:
            return
        kullanilan = FinansService.kredi_karti_kullanilan(kid)
        limit = Decimal(str(kk.kart_limiti or 0))
        if limit > 0:
            self.limit_lbl.configure(
                text=f"Limit: {_para(limit)} · Kullanılan: {_para(kullanilan)} · "
                f"Kalan: {_para(limit - kullanilan)}"
            )
        else:
            self.limit_lbl.configure(text="Limit tanımlı değil (kontrol yapılmaz).")

    def _vade_yaz(self, metin):
        self.vade.configure(state="normal")
        self.vade.delete(0, "end")
        self.vade.insert(0, metin)
        self.vade.configure(state="readonly")

    def _vade_ve_plan_guncelle(self):
        for item in self.plan_tablo.get_children():
            self.plan_tablo.delete(item)
        try:
            tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
        except ValueError:
            self._vade_yaz("")
            return
        self._vade_yaz(tarih.strftime("%d.%m.%Y"))
        tur = self._cekim_map.get(self.cekim.get(), "TEK_CEKIM")
        try:
            n = 1 if tur == "TEK_CEKIM" else int(self.taksit.get() or "1")
        except ValueError:
            return
        try:
            tutar = Decimal(str(self.tutar.get() or "0").replace(",", "."))
        except Exception:
            tutar = Decimal("0")
        if tutar <= 0:
            return
        try:
            plan = FinansService.kk_taksit_plani(tarih, n, tutar)
        except ValueError:
            return
        for satir in plan:
            self.plan_tablo.insert(
                "",
                "end",
                values=(
                    satir["taksit_no"],
                    _tarih(satir["vade_tarihi"]),
                    _para(satir["tutar"]),
                ),
            )

    def _mevcutu_yukle(self):
        m = self._mevcut
        if not m:
            return
        self.tarih.delete(0, "end")
        self.tarih.insert(0, m["tarih"].strftime("%d.%m.%Y"))
        self.tutar.delete(0, "end")
        self.tutar.insert(0, str(m["tutar"]))
        if m.get("referans_no"):
            self.referans.insert(0, m["referans_no"])
        if m.get("aciklama"):
            self.aciklama.insert(0, m["aciklama"])
        if m.get("cari_etiket") and m["cari_etiket"] in self._cari_map:
            self.cari.set(m["cari_etiket"])
        else:
            _combobox_id_sec(self.cari, self._cari_map, m.get("cari_id"))
        _combobox_id_sec(self.banka, self._banka_map, m.get("banka_karti_id"))
        self._kartlari_doldur()
        _combobox_id_sec(self.kart, self._kart_map, m.get("kredi_karti_id"))
        self._limit_bilgi()
        tur = m.get("cekim_turu") or "TEK_CEKIM"
        etiket = dict(KK_CEKIM_TURLERI).get(tur, "Tek Çekim")
        self.cekim.set(etiket)
        self._cekim_degisti()
        if tur == "TAKSITLI":
            self.taksit.set(str(m.get("taksit_sayisi") or 2))

    def kaydet(self):
        try:
            tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
            cari_id = self._cari_map.get(self.cari.get().strip()) if self.cari.get() else None
            if cari_id is None:
                raise ValueError("Cari hesap seçin.")
            banka_id = self._banka_map.get(self.banka.get())
            if not banka_id:
                raise ValueError("Kredi kartı bankasını seçin.")
            kart_id = self._kart_map.get(self.kart.get())
            if not kart_id:
                raise ValueError("Kredi kartı seçin.")
            tur = self._cekim_map.get(self.cekim.get(), "TEK_CEKIM")
            sonuc = FinansService.kredi_karti_odeme(
                banka_id,
                kart_id,
                cari_id,
                tarih,
                self.tutar.get(),
                cekim_turu=tur,
                taksit_sayisi=self.taksit.get(),
                referans_no=self.referans.get().strip() or None,
                aciklama=self.aciklama.get().strip() or None,
                belge_no=self.belge_no,
            )
        except ValueError as hata:
            messagebox.showerror("Fiş", str(hata), parent=self)
            return
        self.result = sonuc.get("belge_no")
        messagebox.showinfo(
            "Kaydedildi" if not self.belge_no else "Güncellendi",
            f"Belge no: {self.result}",
            parent=self,
        )
        self.destroy()


def kredi_karti_pos_tahsilat_sayfasi_goster(app):
    app._icerigi_temizle()
    _finans_menu_isaretle(app)

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="KREDİ KARTI POS CİHAZIYLA TAHSİLAT", style="Baslik.TLabel").pack(
        side="left"
    )
    ttk.Button(ust, text="← Banka İşlemleri", command=lambda: banka_islemleri_menusu_goster(app)).pack(
        side="right"
    )
    ttk.Label(
        app.icerik,
        text="Cari tahsilat; POS hesabına brüt giriş + taksit komisyonu. Valörde net KMH'ye geçer (max 12 taksit).",
    ).pack(anchor="w", pady=(10, 6))

    butonlar = ttk.Frame(app.icerik)
    butonlar.pack(fill="x", pady=(4, 8))

    def _yeni():
        dialog = BankaIslemPosTahsilatDialog(app)
        if dialog.winfo_exists():
            app.wait_window(dialog)
        if dialog.result:
            kredi_karti_pos_tahsilat_sayfasi_goster(app)

    def _guncelle():
        secim = tablo.selection()
        if not secim:
            messagebox.showinfo("Güncelle", "Lütfen güncellenecek fişi seçin.", parent=app)
            return
        dialog = BankaIslemPosTahsilatDialog(app, belge_no=secim[0])
        if dialog.winfo_exists():
            app.wait_window(dialog)
        if dialog.result:
            kredi_karti_pos_tahsilat_sayfasi_goster(app)

    ttk.Button(butonlar, text="Yeni Fiş", command=_yeni).pack(side="left")
    ttk.Button(butonlar, text="Güncelle", command=_guncelle).pack(side="left", padx=8)
    ttk.Button(
        butonlar,
        text="Yenile",
        command=lambda: kredi_karti_pos_tahsilat_sayfasi_goster(app),
    ).pack(side="left", padx=8)

    cerceve = ttk.Frame(app.icerik)
    cerceve.pack(fill="both", expand=True)
    tablo = ttk.Treeview(
        cerceve,
        columns=("tarih", "belge", "cari", "banka", "cekim", "brut", "komisyon", "net", "durum", "aciklama"),
        show="headings",
        selectmode="browse",
    )
    for k, b, w in (
        ("tarih", "Tarih", 85),
        ("belge", "Belge No", 100),
        ("cari", "Cari", 160),
        ("banka", "Banka", 110),
        ("cekim", "Çekim", 90),
        ("brut", "Brüt", 95),
        ("komisyon", "Komisyon", 90),
        ("net", "Net", 95),
        ("durum", "Durum", 80),
        ("aciklama", "Açıklama", 160),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="w")
    kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=kaydir.set)
    tablo.pack(side="left", fill="both", expand=True)
    kaydir.pack(side="right", fill="y")
    tablo.bind("<Double-1>", lambda _e: _guncelle())

    for kayit in FinansService.pos_tahsilat_listele():
        tablo.insert(
            "",
            "end",
            iid=kayit["belge_no"],
            values=(
                _tarih(kayit["tarih"]),
                kayit["belge_no"],
                kayit["cari"],
                kayit["banka"],
                kayit["cekim"],
                _para(kayit["brut"]),
                _para(kayit["komisyon"]),
                _para(kayit["net"]),
                kayit["durum"],
                kayit["aciklama"],
            ),
        )


class BankaIslemPosTahsilatDialog(tk.Toplevel):
    """Banka işlemleri — kredi kartı POS tahsilat fişi (tek / taksit max 12)."""

    def __init__(self, parent, belge_no=None):
        super().__init__(parent)
        self.result = None
        self.belge_no = belge_no
        self._mevcut = None
        self._oranlar = {n: Decimal("0") for n in range(1, POS_MAX_TAKSIT + 1)}
        if belge_no:
            try:
                self._mevcut = FinansService.pos_tahsilat_getir(belge_no)
                if (self._mevcut.get("durum") or "") != "BEKLIYOR":
                    messagebox.showerror(
                        "Fiş",
                        "Valöre aktarılmış POS tahsilatı güncellenemez.",
                        parent=parent,
                    )
                    self.destroy()
                    return
            except ValueError as hata:
                messagebox.showerror("Fiş", str(hata), parent=parent)
                self.destroy()
                return

        self.title(
            "Kredi Kartı POS Tahsilat — Güncelle" if belge_no else "Kredi Kartı POS Cihazıyla Tahsilat"
        )
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)

        from database.cari_service import CariService

        self._cari_map = {}
        self._banka_map = {}
        self._cekim_map = {e: k for k, e in KK_CEKIM_TURLERI}

        row = 0
        ttk.Label(self, text="Tarih *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        tarih_c = ttk.Frame(self)
        tarih_c.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.tarih = ttk.Entry(tarih_c, width=14)
        self.tarih.pack(side="left")
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        takvim_butonu(tarih_c, self.tarih)

        row = 1
        cariler = CariService.listele()
        self._cari_map = {
            f"{o['cari'].cari_kodu} - {o['cari'].unvan}": o["cari"].id for o in cariler
        }
        ttk.Label(self, text="Cari hesap *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.cari = ttk.Combobox(self, values=list(self._cari_map), width=42)
        self.cari.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        if self._cari_map:
            self.cari.set(next(iter(self._cari_map)))

        row = 2
        kartlar_banka = FinansService.banka_kartlari(aktif_only=True)
        ttk.Label(self, text="POS bankası *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.banka = ttk.Combobox(self, state="readonly", width=42)
        self.banka.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        banka_etiketleri = []
        for k in kartlar_banka:
            etiket = k.banka_adi
            if k.sube:
                etiket = f"{etiket} / {k.sube}"
            self._banka_map[etiket] = k.id
            banka_etiketleri.append(etiket)
        self.banka.configure(values=banka_etiketleri)
        if banka_etiketleri:
            self.banka.set(banka_etiketleri[0])
        self.banka.bind("<<ComboboxSelected>>", lambda _e: self._banka_degisti())

        row = 3
        self.pos_bilgi = ttk.Label(self, text="", foreground="#555")
        self.pos_bilgi.grid(row=row, column=1, columnspan=2, padx=12, sticky="w")

        row = 4
        ttk.Label(self, text="Çekim türü *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.cekim = ttk.Combobox(
            self,
            values=[e for _k, e in KK_CEKIM_TURLERI],
            state="readonly",
            width=28,
        )
        self.cekim.set("Tek Çekim")
        self.cekim.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.cekim.bind("<<ComboboxSelected>>", lambda _e: self._cekim_degisti())

        row = 5
        ttk.Label(self, text="Taksit sayısı").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.taksit = ttk.Combobox(
            self,
            values=[str(i) for i in range(1, POS_MAX_TAKSIT + 1)],
            width=8,
            state="disabled",
        )
        self.taksit.set("1")
        self.taksit.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.taksit.bind("<<ComboboxSelected>>", lambda _e: self._ozet_guncelle())

        row = 6
        ttk.Label(self, text="Meblağ (brüt) *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.tutar = ttk.Entry(self, width=18)
        self.tutar.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.tutar.bind("<KeyRelease>", lambda _e: self._ozet_guncelle())

        row = 7
        ttk.Label(self, text="Referans / onay no").grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        self.referans = ttk.Entry(self, width=24)
        self.referans.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        row = 8
        ttk.Label(self, text="Açıklama").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.aciklama = ttk.Entry(self, width=44)
        self.aciklama.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")

        row = 9
        ozet_f = ttk.LabelFrame(self, text="Komisyon özeti (POS hesabı)", padding=8)
        ozet_f.grid(row=row, column=0, columnspan=3, padx=12, pady=8, sticky="ew")
        self.oran_lbl = ttk.Label(ozet_f, text="Komisyon oranı: —")
        self.oran_lbl.pack(anchor="w")
        self.komisyon_lbl = ttk.Label(ozet_f, text="Banka masrafı: —")
        self.komisyon_lbl.pack(anchor="w")
        self.net_lbl = ttk.Label(ozet_f, text="Net (valöre): —")
        self.net_lbl.pack(anchor="w")
        ttk.Label(
            ozet_f,
            text="Oranlar banka ana kartı → POS taksit komisyon tablosundan alınır.",
            foreground="#555",
        ).pack(anchor="w", pady=(4, 0))

        if self.belge_no:
            ttk.Label(self, text=f"Belge: {self.belge_no}", foreground="#555").grid(
                row=10, column=0, columnspan=2, padx=12, sticky="w"
            )

        butonlar = ttk.Frame(self)
        butonlar.grid(row=11, column=0, columnspan=3, padx=12, pady=12, sticky="e")
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(
            butonlar,
            text="Güncelle" if self.belge_no else "Kaydet",
            command=self.kaydet,
        ).pack(side="right")

        self._banka_degisti()
        self._mevcutu_yukle()
        self._ozet_guncelle()

    def _taksit_sayisi(self) -> int:
        tur = self._cekim_map.get(self.cekim.get(), "TEK_CEKIM")
        if tur == "TEK_CEKIM":
            return 1
        try:
            return int(self.taksit.get() or "1")
        except ValueError:
            return 1

    def _banka_degisti(self):
        banka_id = self._banka_map.get(self.banka.get())
        self._oranlar = {n: Decimal("0") for n in range(1, POS_MAX_TAKSIT + 1)}
        if not banka_id:
            self.pos_bilgi.configure(text="")
            self._ozet_guncelle()
            return
        kart = FinansService.banka_karti_getir(banka_id)
        if not kart:
            self.pos_bilgi.configure(text="")
            self._ozet_guncelle()
            return
        self._oranlar = FinansService.pos_taksit_komisyonlari(banka_id)
        valor = int(kart.pos_valor_gun if kart.pos_valor_gun is not None else 1)
        self.pos_bilgi.configure(
            text=f"POS hesabı · Valör {valor} gün / 08:00 → KMH · "
            f"1. taksit komisyon %{self._oranlar.get(1, 0):g}"
        )
        self._ozet_guncelle()

    def _cekim_degisti(self):
        tur = self._cekim_map.get(self.cekim.get(), "TEK_CEKIM")
        if tur == "TEK_CEKIM":
            self.taksit.set("1")
            self.taksit.configure(state="disabled")
        else:
            self.taksit.configure(state="readonly")
            if self.taksit.get() == "1":
                self.taksit.set("2")
        self._ozet_guncelle()

    def _ozet_guncelle(self):
        n = self._taksit_sayisi()
        oran = Decimal(str(self._oranlar.get(n, 0) or 0))
        try:
            brut = Decimal(str(self.tutar.get() or "0").replace(",", "."))
        except Exception:
            brut = Decimal("0")
        if brut < 0:
            brut = Decimal("0")
        komisyon = (brut * oran / Decimal("100")).quantize(Decimal("0.01"))
        net = brut - komisyon
        self.oran_lbl.configure(text=f"Komisyon oranı ({n} taksit): %{oran:g}")
        self.komisyon_lbl.configure(text=f"Banka masrafı: {_para(komisyon)}")
        self.net_lbl.configure(text=f"Net (valöre): {_para(net)}")

    def _mevcutu_yukle(self):
        m = self._mevcut
        if not m:
            return
        self.tarih.delete(0, "end")
        self.tarih.insert(0, m["tarih"].strftime("%d.%m.%Y"))
        self.tutar.delete(0, "end")
        self.tutar.insert(0, str(m["tutar"]))
        if m.get("aciklama"):
            self.aciklama.delete(0, "end")
            self.aciklama.insert(0, m["aciklama"])
        if m.get("cari_etiket") and m["cari_etiket"] in self._cari_map:
            self.cari.set(m["cari_etiket"])
        else:
            _combobox_id_sec(self.cari, self._cari_map, m.get("cari_id"))
        _combobox_id_sec(self.banka, self._banka_map, m.get("banka_karti_id"))
        self._banka_degisti()
        n = int(m.get("taksit_sayisi") or 1)
        if n <= 1:
            self.cekim.set(dict(KK_CEKIM_TURLERI).get("TEK_CEKIM", "Tek Çekim"))
            self._cekim_degisti()
        else:
            self.cekim.set(dict(KK_CEKIM_TURLERI).get("TAKSITLI", "Taksitli Çekim"))
            self._cekim_degisti()
            self.taksit.set(str(n))

    def kaydet(self):
        try:
            tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
            cari_id = self._cari_map.get(self.cari.get().strip()) if self.cari.get() else None
            if cari_id is None:
                raise ValueError("Cari hesap seçin.")
            banka_id = self._banka_map.get(self.banka.get())
            if not banka_id:
                raise ValueError("POS bankasını seçin.")
            n = self._taksit_sayisi()
            sonuc = FinansService.pos_tahsilat(
                banka_id,
                tarih,
                self.tutar.get(),
                kart_tipi="KREDI_KARTI",
                cari_id=cari_id,
                aciklama=self.aciklama.get().strip() or None,
                taksit_sayisi=n,
                referans_no=self.referans.get().strip() or None,
                belge_no=self.belge_no,
            )
        except ValueError as hata:
            messagebox.showerror("Fiş", str(hata), parent=self)
            return
        self.result = sonuc.get("belge_no")
        messagebox.showinfo(
            "Kaydedildi" if not self.belge_no else "Güncellendi",
            f"Belge: {self.result}\n"
            f"Brüt: {_para(sonuc['brut'])} · Komisyon %{sonuc['komisyon_orani']:g}: "
            f"{_para(sonuc['komisyon'])} · Net: {_para(sonuc['net'])}\n"
            f"Valör: {sonuc['valor_tarihi'].strftime('%d.%m.%Y')} {sonuc['valor_saati']} → KMH",
            parent=self,
        )
        self.destroy()


def kk_cekimi_sayfasi_goster(app):
    """Müşteriden tedarikçiye kredi kartı çekimi — Banka İşlemleri menüsü."""
    app._icerigi_temizle()
    _finans_menu_isaretle(app)

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="MÜŞTERİDEN TEDARİKÇİYE KREDİ KARTI ÇEKİMİ", style="Baslik.TLabel").pack(
        side="left"
    )
    ttk.Button(ust, text="← Banka İşlemleri", command=lambda: banka_islemleri_menusu_goster(app)).pack(
        side="right"
    )
    ttk.Label(
        app.icerik,
        text="Müşteriye alacak, tedarikçiye borç yazılır. Banka adı ve taksit serbest girilir; kasa/banka hesabına işlem düşmez.",
    ).pack(anchor="w", pady=(10, 6))

    arama_c = ttk.Frame(app.icerik)
    arama_c.pack(fill="x", pady=(0, 8))
    ttk.Label(arama_c, text="Ara:").pack(side="left")
    arama = ttk.Entry(arama_c, width=36)
    arama.pack(side="left", padx=6)

    butonlar = ttk.Frame(app.icerik)
    butonlar.pack(fill="x", pady=(0, 8))

    def _listeyi_yenile():
        for item in tablo.get_children():
            tablo.delete(item)
        for kayit in KkCekimiService.listele(arama.get().strip()):
            tablo.insert(
                "",
                "end",
                iid=kayit["belge_no"],
                values=(
                    kayit["belge_no"],
                    _tarih(kayit["tarih"]),
                    f"{kayit['musteri_kodu']} - {kayit['musteri_unvan']}",
                    f"{kayit['tedarikci_kodu']} - {kayit['tedarikci_unvan']}",
                    _para(kayit["tutar"]),
                    kayit["banka"],
                    kayit["cekim_turu"],
                    kayit["taksit_sayisi"],
                    kayit["aciklama"],
                ),
            )

    def _yeni():
        from app import KkCekimiDialog

        dialog = KkCekimiDialog(app)
        if dialog.winfo_exists():
            app.wait_window(dialog)
        if dialog.result:
            _listeyi_yenile()

    def _guncelle():
        from app import KkCekimiDialog

        secim = tablo.selection()
        if not secim:
            messagebox.showinfo("Seçim", "Lütfen güncellenecek KK çekim fişini seçin.", parent=app)
            return
        dialog = KkCekimiDialog(app, belge_no=secim[0])
        if dialog.winfo_exists():
            app.wait_window(dialog)
        if dialog.result:
            _listeyi_yenile()

    def _iptal():
        secim = tablo.selection()
        if not secim:
            messagebox.showinfo("Seçim", "Lütfen iptal edilecek KK çekim fişini seçin.", parent=app)
            return
        belge_no = secim[0]
        if not messagebox.askyesno(
            "KK çekim iptal",
            f"{belge_no} numaralı fiş iptal edilsin mi?\nMüşteri alacağı ve tedarikçi borcu geri alınır.",
            parent=app,
        ):
            return
        try:
            KkCekimiService.iptal_et(belge_no)
        except ValueError as hata:
            messagebox.showerror("İptal edilemedi", str(hata), parent=app)
            return
        _listeyi_yenile()

    ttk.Button(arama_c, text="Listele", command=_listeyi_yenile).pack(side="left")
    ttk.Button(butonlar, text="Yeni KK Çekim Fişi", command=_yeni).pack(side="left")
    ttk.Button(butonlar, text="Güncelle", command=_guncelle).pack(side="left", padx=8)
    ttk.Button(butonlar, text="İptal Et", command=_iptal).pack(side="left", padx=8)
    ttk.Button(butonlar, text="Yenile", command=_listeyi_yenile).pack(side="left", padx=8)

    cerceve = ttk.Frame(app.icerik)
    cerceve.pack(fill="both", expand=True)
    tablo = ttk.Treeview(
        cerceve,
        columns=("belge", "tarih", "musteri", "tedarikci", "tutar", "banka", "cekim", "taksit", "aciklama"),
        show="headings",
        selectmode="browse",
    )
    for k, b, w in (
        ("belge", "Belge No", 100),
        ("tarih", "Tarih", 85),
        ("musteri", "Müşteri (Alacak)", 170),
        ("tedarikci", "Tedarikçi (Borç)", 170),
        ("tutar", "Tutar", 100),
        ("banka", "Banka", 110),
        ("cekim", "Çekim Türü", 100),
        ("taksit", "Taksit", 60),
        ("aciklama", "Açıklama", 160),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="w")
    kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=kaydir.set)
    tablo.pack(side="left", fill="both", expand=True)
    kaydir.pack(side="right", fill="y")
    tablo.bind("<Double-1>", lambda _e: _guncelle())

    _listeyi_yenile()


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
            ttk.Label(self, text="Gönderen cari *").grid(
                row=row, column=0, padx=12, pady=6, sticky="w"
            )
            self.cari = ttk.Combobox(self, values=list(self.cari_map), width=36)
            self.cari.grid(row=row, column=1, padx=12, pady=6, sticky="w")
            if self.cari_map:
                self.cari.set(next(iter(self.cari_map)))
        else:  # ghv
            row = 2
            cariler = CariService.listele()
            self.cari_map = {
                f"{o['cari'].cari_kodu} - {o['cari'].unvan}": o["cari"].id for o in cariler
            }
            ttk.Label(self, text="Alıcı cari *").grid(
                row=row, column=0, padx=12, pady=6, sticky="w"
            )
            self.cari = ttk.Combobox(self, values=list(self.cari_map), width=36)
            self.cari.grid(row=row, column=1, padx=12, pady=6, sticky="w")
            if self.cari_map:
                self.cari.set(next(iter(self.cari_map)))

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
                if not self.cari or not self.cari.get().strip():
                    raise ValueError("Gönderilen havale için alıcı cari seçimi zorunludur.")
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


class KrediKartiIslemleriDialog(tk.Toplevel):
    """Kredi kartı tanımları + ödeme evrakı + taksitler + KK hesap hareketleri."""

    def __init__(self, parent, kart):
        super().__init__(parent)
        self.parent_dlg = parent
        self.kart_id = kart.id
        self.title(f"{kart.banka_adi} — Kredi Kartı İşlemleri")
        self.geometry("1020x680")
        self.minsize(940, 600)
        self.transient(parent)
        self.grab_set()

        ust = ttk.Frame(self, padding=10)
        ust.pack(fill="x")
        self.bakiye_lbl = ttk.Label(ust, text="", font=("Segoe UI", 11, "bold"))
        self.bakiye_lbl.pack(side="left")
        ttk.Button(ust, text="Kapat", command=self.destroy).pack(side="right")

        menu = ttk.LabelFrame(self, text="Evraklar / Kartlar", padding=10)
        menu.pack(fill="x", padx=10, pady=4)
        ttk.Button(menu, text="Kredi Kartı Tanımla", command=self._kart_tanim_ac).pack(
            side="left", padx=4
        )
        ttk.Button(menu, text="Kartları Düzenle", command=self._kart_liste_ac).pack(
            side="left", padx=4
        )
        ttk.Button(menu, text="Yeni Ödeme Evrakı", command=self._odeme_ac).pack(
            side="left", padx=4
        )
        ttk.Button(menu, text="Yenile", command=self.listeyi_yenile).pack(side="left", padx=4)

        kartlar_f = ttk.LabelFrame(self, text="Tanımlı kredi kartları", padding=8)
        kartlar_f.pack(fill="x", padx=10, pady=4)
        self.kart_tablo = ttk.Treeview(
            kartlar_f,
            columns=("banka", "ad", "marka", "no", "skt", "limit", "kullanilan", "kalan", "kesim", "odeme"),
            show="headings",
            height=4,
        )
        for k, b, w in (
            ("banka", "Banka", 100),
            ("ad", "Kart adı", 130),
            ("marka", "Marka", 80),
            ("no", "Kart no", 90),
            ("skt", "SKT", 55),
            ("limit", "Limit", 90),
            ("kullanilan", "Kullanılan", 90),
            ("kalan", "Kalan", 90),
            ("kesim", "Kesim", 55),
            ("odeme", "Ödeme", 55),
        ):
            self.kart_tablo.heading(k, text=b)
            self.kart_tablo.column(k, width=w, anchor="w")
        self.kart_tablo.pack(fill="x")
        self.kart_tablo.bind("<Double-1>", lambda _e: self._kart_duzenle_secili())

        taksit_f = ttk.LabelFrame(self, text="Bekleyen taksitler", padding=8)
        taksit_f.pack(fill="x", padx=10, pady=4)
        self.taksit_tablo = ttk.Treeview(
            taksit_f,
            columns=("belge", "kart", "no", "vade", "tutar"),
            show="headings",
            height=5,
        )
        for k, b, w in (
            ("belge", "Belge", 120),
            ("kart", "Kart", 140),
            ("no", "Taksit", 70),
            ("vade", "Vade", 90),
            ("tutar", "Tutar", 100),
        ):
            self.taksit_tablo.heading(k, text=b)
            self.taksit_tablo.column(k, width=w, anchor="w")
        self.taksit_tablo.pack(fill="x")

        orta = ttk.LabelFrame(self, text="KK ödeme evrakları / hesap hareketleri", padding=8)
        orta.pack(fill="both", expand=True, padx=10, pady=6)
        cerceve = ttk.Frame(orta)
        cerceve.pack(fill="both", expand=True)
        self.tablo = ttk.Treeview(
            cerceve,
            columns=("tarih", "vade", "belge", "cari", "kart", "tur", "tutar", "aciklama"),
            show="headings",
        )
        for k, b, w in (
            ("tarih", "Tarih", 85),
            ("vade", "Vade", 85),
            ("belge", "Belge", 120),
            ("cari", "Firma", 170),
            ("kart", "Kart", 120),
            ("tur", "Çekim", 100),
            ("tutar", "Tutar", 95),
            ("aciklama", "Açıklama", 160),
        ):
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=w, anchor="w")
        kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=kaydir.set)
        self.tablo.pack(side="left", fill="both", expand=True)
        kaydir.pack(side="right", fill="y")

        self.listeyi_yenile()

    def _kk_hesap(self):
        kart = FinansService.banka_karti_getir(self.kart_id)
        if not kart:
            return None, None
        return kart, FinansService.banka_alt_hesap(kart, "KREDI_KARTI")

    def listeyi_yenile(self):
        kart, hesap = self._kk_hesap()
        for t in (self.kart_tablo, self.taksit_tablo, self.tablo):
            for item in t.get_children():
                t.delete(item)
        if not hesap:
            self.bakiye_lbl.configure(text="Kredi kartı hesabı bulunamadı.")
            return
        bak = FinansService.bakiye(hesap)
        self.bakiye_lbl.configure(text=f"{hesap.hesap_adi}  ·  Bakiye (borç): {_para(bak)}")

        for kk in FinansService.kredi_kartlari(banka_karti_id=self.kart_id):
            kullanilan = FinansService.kredi_karti_kullanilan(kk.id)
            limit = Decimal(str(kk.kart_limiti or 0))
            kalan = limit - kullanilan if limit > 0 else Decimal("0")
            maske = f"****{kk.son_dort_hane}" if kk.son_dort_hane else "—"
            self.kart_tablo.insert(
                "",
                "end",
                iid=str(kk.id),
                values=(
                    kk.kart_bankasi or "—",
                    kk.kart_adi,
                    kk.kart_markasi or "—",
                    maske,
                    kk.son_kullanim or "—",
                    _para(limit) if limit else "—",
                    _para(kullanilan),
                    _para(kalan) if limit else "—",
                    kk.hesap_kesim_gunu or "—",
                    kk.son_odeme_gunu or "—",
                ),
            )

        for t in FinansService.kredi_karti_bekleyen_taksitler(self.kart_id):
            self.taksit_tablo.insert(
                "",
                "end",
                values=(
                    t["belge_no"],
                    t["kart"],
                    f"{t['taksit_no']}/{t['taksit_sayisi']}",
                    _tarih(t["vade_tarihi"]),
                    _para(t["tutar"]),
                ),
            )

        for o in FinansService.kredi_karti_odemeleri(self.kart_id):
            self.tablo.insert(
                "",
                "end",
                values=(
                    _tarih(o["tarih"]),
                    _tarih(o["vade_tarihi"]),
                    o["belge_no"],
                    o["cari"] or "—",
                    o["kart"],
                    o["cekim_turu"] if o["taksit_sayisi"] == 1 else f"{o['cekim_turu']} ({o['taksit_sayisi']})",
                    _para(o["tutar"]),
                    o["aciklama"],
                ),
            )
        if hasattr(self.parent_dlg, "bakiyeleri_yenile"):
            self.parent_dlg.bakiyeleri_yenile()

    def _kart_tanim_ac(self):
        dialog = KrediKartiTanimDialog(self, self.kart_id)
        self.wait_window(dialog)
        if dialog.result:
            self.listeyi_yenile()

    def _kart_liste_ac(self):
        self._kart_duzenle_secili(zorunlu=False)

    def _kart_duzenle_secili(self, zorunlu=True):
        secim = self.kart_tablo.selection()
        if not secim:
            if zorunlu:
                messagebox.showinfo("Kart", "Düzenlemek için bir kart seçin.", parent=self)
            else:
                kartlar = FinansService.kredi_kartlari(banka_karti_id=self.kart_id)
                if not kartlar:
                    messagebox.showinfo(
                        "Kart",
                        "Henüz tanımlı kart yok. Önce «Kredi Kartı Tanımla» ile ekleyin.",
                        parent=self,
                    )
                    return
                dialog = KrediKartiTanimDialog(self, self.kart_id, kart_id=kartlar[0].id)
                self.wait_window(dialog)
                if dialog.result:
                    self.listeyi_yenile()
            return
        dialog = KrediKartiTanimDialog(self, self.kart_id, kart_id=int(secim[0]))
        self.wait_window(dialog)
        if dialog.result:
            self.listeyi_yenile()

    def _odeme_ac(self):
        kartlar = FinansService.kredi_kartlari(banka_karti_id=self.kart_id)
        if not kartlar:
            messagebox.showwarning(
                "Kart gerekli",
                "Ödeme için önce bu bankaya en az bir kredi kartı tanımlayın.",
                parent=self,
            )
            return
        dialog = KrediKartiOdemeDialog(self, self.kart_id)
        self.wait_window(dialog)
        if dialog.result:
            self.listeyi_yenile()


class KrediKartiTanimDialog(tk.Toplevel):
    MARKALAR = ("(Seçiniz)", "Visa", "Mastercard", "Troy", "Amex", "Diğer")

    def __init__(self, parent, banka_karti_id, kart_id=None):
        super().__init__(parent)
        self.banka_karti_id = banka_karti_id
        self.kart_id = kart_id
        self.result = None
        self.title("Kredi Kartı Tanımı" + (" — Düzenle" if kart_id else " — Yeni"))
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)

        kart = FinansService.kredi_karti_getir(kart_id) if kart_id else None
        banka = FinansService.banka_karti_getir(banka_karti_id)
        varsayilan_banka = (banka.banka_adi if banka else "") or ""

        row = 0
        ttk.Label(self, text="Kartın bankası *").grid(row=row, column=0, padx=12, pady=5, sticky="w")
        self.kart_bankasi = ttk.Entry(self, width=36)
        self.kart_bankasi.grid(row=row, column=1, padx=12, pady=5, sticky="w")

        row = 1
        ttk.Label(self, text="Kart adı *").grid(row=row, column=0, padx=12, pady=5, sticky="w")
        self.kart_adi = ttk.Entry(self, width=36)
        self.kart_adi.grid(row=row, column=1, padx=12, pady=5, sticky="w")
        ttk.Label(self, text="(ör. İşletme Kartı, Alışveriş)", foreground="#555").grid(
            row=row, column=2, sticky="w"
        )

        row = 2
        ttk.Label(self, text="Kart sahibi").grid(row=row, column=0, padx=12, pady=5, sticky="w")
        self.kart_sahibi = ttk.Entry(self, width=36)
        self.kart_sahibi.grid(row=row, column=1, padx=12, pady=5, sticky="w")

        row = 3
        ttk.Label(self, text="Kart markası").grid(row=row, column=0, padx=12, pady=5, sticky="w")
        self.kart_markasi = ttk.Combobox(
            self, values=self.MARKALAR, state="readonly", width=20
        )
        self.kart_markasi.set("(Seçiniz)")
        self.kart_markasi.grid(row=row, column=1, padx=12, pady=5, sticky="w")

        row = 4
        ttk.Label(self, text="Kart numarası").grid(row=row, column=0, padx=12, pady=5, sticky="w")
        self.kart_no = ttk.Entry(self, width=28)
        self.kart_no.grid(row=row, column=1, padx=12, pady=5, sticky="w")
        ttk.Label(self, text="(liste ekranında ****1234)", foreground="#555").grid(
            row=row, column=2, sticky="w"
        )

        row = 5
        ttk.Label(self, text="Son kullanım (AA/YY)").grid(
            row=row, column=0, padx=12, pady=5, sticky="w"
        )
        self.son_kullanim = ttk.Entry(self, width=10)
        self.son_kullanim.grid(row=row, column=1, padx=12, pady=5, sticky="w")

        row = 6
        ttk.Label(self, text="Güvenlik kodu (CVV)").grid(
            row=row, column=0, padx=12, pady=5, sticky="w"
        )
        self.cvv = ttk.Entry(self, width=8, show="*")
        self.cvv.grid(row=row, column=1, padx=12, pady=5, sticky="w")

        row = 7
        ttk.Label(self, text="Kart limiti").grid(row=row, column=0, padx=12, pady=5, sticky="w")
        self.limit = ttk.Entry(self, width=16)
        self.limit.grid(row=row, column=1, padx=12, pady=5, sticky="w")

        row = 8
        ttk.Label(self, text="Hesap kesim günü (1-28)").grid(
            row=row, column=0, padx=12, pady=5, sticky="w"
        )
        self.kesim = ttk.Entry(self, width=8)
        self.kesim.grid(row=row, column=1, padx=12, pady=5, sticky="w")
        ttk.Label(self, text="Her ayın bu günü ekstre kesilir", foreground="#555").grid(
            row=row, column=2, sticky="w"
        )

        row = 9
        ttk.Label(self, text="Son ödeme günü (1-28)").grid(
            row=row, column=0, padx=12, pady=5, sticky="w"
        )
        self.son_odeme = ttk.Entry(self, width=8)
        self.son_odeme.grid(row=row, column=1, padx=12, pady=5, sticky="w")

        row = 10
        ttk.Label(self, text="Açıklama").grid(row=row, column=0, padx=12, pady=5, sticky="w")
        self.aciklama = ttk.Entry(self, width=40)
        self.aciklama.grid(row=row, column=1, columnspan=2, padx=12, pady=5, sticky="w")

        if kart:
            self.kart_bankasi.insert(0, kart.kart_bankasi or varsayilan_banka)
            self.kart_adi.insert(0, kart.kart_adi or "")
            self.kart_sahibi.insert(0, kart.kart_sahibi or "")
            if kart.kart_markasi:
                self.kart_markasi.set(kart.kart_markasi)
            if kart.kart_numarasi:
                # Görüntüde 4'lü grupla
                no = kart.kart_numarasi
                self.kart_no.insert(0, " ".join(no[i : i + 4] for i in range(0, len(no), 4)))
            self.son_kullanim.insert(0, kart.son_kullanim or "")
            self.cvv.insert(0, kart.guvenlik_kodu or "")
            self.limit.insert(0, str(kart.kart_limiti or 0))
            if kart.hesap_kesim_gunu:
                self.kesim.insert(0, str(kart.hesap_kesim_gunu))
            if kart.son_odeme_gunu:
                self.son_odeme.insert(0, str(kart.son_odeme_gunu))
            self.aciklama.insert(0, kart.aciklama or "")
        else:
            self.kart_bankasi.insert(0, varsayilan_banka)
            self.limit.insert(0, "0")

        butonlar = ttk.Frame(self)
        butonlar.grid(row=11, column=0, columnspan=3, padx=12, pady=12, sticky="e")
        if kart:
            ttk.Button(butonlar, text="Pasif Yap", command=self._pasif).pack(side="left", padx=(0, 12))
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(butonlar, text="Kaydet", command=self.kaydet).pack(side="right")

    def kaydet(self):
        if not self.kart_bankasi.get().strip():
            messagebox.showerror("Kart", "Kartın bankası zorunludur.", parent=self)
            return
        veri = {
            "banka_karti_id": self.banka_karti_id,
            "kart_bankasi": self.kart_bankasi.get(),
            "kart_adi": self.kart_adi.get(),
            "kart_sahibi": self.kart_sahibi.get(),
            "kart_markasi": self.kart_markasi.get(),
            "kart_numarasi": self.kart_no.get(),
            "son_kullanim": self.son_kullanim.get(),
            "guvenlik_kodu": self.cvv.get(),
            "kart_limiti": self.limit.get(),
            "hesap_kesim_gunu": self.kesim.get(),
            "son_odeme_gunu": self.son_odeme.get(),
            "aciklama": self.aciklama.get(),
            "aktif": True,
        }
        if self.kart_id:
            veri["kart_id"] = self.kart_id
        try:
            self.result = FinansService.kredi_karti_kaydet(veri)
        except ValueError as hata:
            messagebox.showerror("Kart", str(hata), parent=self)
            return
        messagebox.showinfo("Kaydedildi", f"Kart: {self.result.kart_adi}", parent=self)
        self.destroy()

    def _pasif(self):
        if not self.kart_id:
            return
        if not messagebox.askyesno("Pasif", "Bu kartı pasif yapmak istiyor musunuz?", parent=self):
            return
        try:
            FinansService.kredi_karti_pasif_yap(self.kart_id)
        except ValueError as hata:
            messagebox.showerror("Kart", str(hata), parent=self)
            return
        self.result = True
        self.destroy()


class KrediKartiOdemeDialog(tk.Toplevel):
    """Kredi kartı ödeme evrakı: tarih, vade, tek/taksit, firma, kart."""

    def __init__(self, parent, banka_karti_id):
        super().__init__(parent)
        self.banka_karti_id = banka_karti_id
        self.result = None
        self.title("Kredi Kartı Ödeme Evrakı")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)

        from database.cari_service import CariService

        row = 0
        ttk.Label(self, text="Tarih (çekim) *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        tarih_c = ttk.Frame(self)
        tarih_c.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.tarih = ttk.Entry(tarih_c, width=14)
        self.tarih.pack(side="left")
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        takvim_butonu(tarih_c, self.tarih)
        self.tarih.bind("<FocusOut>", lambda _e: self._vade_ve_plan_guncelle())
        self.tarih.bind("<KeyRelease>", lambda _e: self._vade_ve_plan_guncelle())

        row = 1
        ttk.Label(self, text="Vade tarihi").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.vade = ttk.Entry(self, width=14, state="readonly")
        self.vade.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        ttk.Label(
            self,
            text="Tek çekim = çekim günü · Taksitli = 1. taksit (çekim günü)",
            foreground="#555",
        ).grid(row=row, column=2, padx=4, sticky="w")

        row = 2
        ttk.Label(self, text="Çekim türü *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.cekim = ttk.Combobox(
            self,
            values=[e for _k, e in KK_CEKIM_TURLERI],
            state="readonly",
            width=28,
        )
        self.cekim.set("Tek Çekim")
        self.cekim.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.cekim.bind("<<ComboboxSelected>>", lambda _e: self._cekim_degisti())
        self._cekim_map = {e: k for k, e in KK_CEKIM_TURLERI}

        row = 3
        ttk.Label(self, text="Taksit sayısı").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.taksit = ttk.Combobox(
            self,
            values=[str(i) for i in range(1, KK_MAX_TAKSIT + 1)],
            width=8,
            state="disabled",
        )
        self.taksit.set("1")
        self.taksit.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.taksit.bind("<<ComboboxSelected>>", lambda _e: self._vade_ve_plan_guncelle())

        row = 4
        ttk.Label(self, text="Ödeme tutarı *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.tutar = ttk.Entry(self, width=18)
        self.tutar.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.tutar.bind("<KeyRelease>", lambda _e: self._vade_ve_plan_guncelle())

        row = 5
        cariler = CariService.listele()
        self.cari_map = {
            f"{o['cari'].cari_kodu} - {o['cari'].unvan}": o["cari"].id for o in cariler
        }
        ttk.Label(self, text="Ödeme yapılan firma *").grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        self.cari = ttk.Combobox(self, values=list(self.cari_map), width=40)
        self.cari.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")

        row = 6
        kartlar = FinansService.kredi_kartlari(banka_karti_id=banka_karti_id)
        self._kart_map = {}
        kart_etiketleri = []
        for kk in kartlar:
            etiket = kk.kart_adi
            if kk.son_dort_hane:
                etiket = f"{etiket} (****{kk.son_dort_hane})"
            self._kart_map[etiket] = kk.id
            kart_etiketleri.append(etiket)
        ttk.Label(self, text="Ödeme kartı *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.kart = ttk.Combobox(
            self, values=kart_etiketleri, state="readonly", width=40
        )
        self.kart.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        if kart_etiketleri:
            self.kart.set(kart_etiketleri[0])
        self.kart.bind("<<ComboboxSelected>>", lambda _e: self._limit_bilgi())

        row = 7
        self.limit_lbl = ttk.Label(self, text="", foreground="#555")
        self.limit_lbl.grid(row=row, column=0, columnspan=3, padx=12, sticky="w")

        row = 8
        ttk.Label(self, text="Referans / onay no").grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        self.referans = ttk.Entry(self, width=24)
        self.referans.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        row = 9
        ttk.Label(self, text="Açıklama").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.aciklama = ttk.Entry(self, width=40)
        self.aciklama.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")

        row = 10
        plan_f = ttk.LabelFrame(self, text="Taksit planı önizleme", padding=8)
        plan_f.grid(row=row, column=0, columnspan=3, padx=12, pady=8, sticky="ew")
        self.plan_tablo = ttk.Treeview(
            plan_f,
            columns=("no", "vade", "tutar"),
            show="headings",
            height=6,
        )
        for k, b, w in (("no", "No", 50), ("vade", "Vade", 100), ("tutar", "Tutar", 100)):
            self.plan_tablo.heading(k, text=b)
            self.plan_tablo.column(k, width=w, anchor="w")
        self.plan_tablo.pack(fill="x")

        butonlar = ttk.Frame(self)
        butonlar.grid(row=11, column=0, columnspan=3, padx=12, pady=12, sticky="e")
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(butonlar, text="Kaydet", command=self.kaydet).pack(side="right")

        self._limit_bilgi()
        self._vade_ve_plan_guncelle()

    def _cekim_degisti(self):
        tur = self._cekim_map.get(self.cekim.get(), "TEK_CEKIM")
        if tur == "TEK_CEKIM":
            self.taksit.set("1")
            self.taksit.configure(state="disabled")
        else:
            self.taksit.configure(state="readonly")
            if self.taksit.get() == "1":
                self.taksit.set("2")
        self._vade_ve_plan_guncelle()

    def _limit_bilgi(self):
        kid = self._kart_map.get(self.kart.get())
        if not kid:
            self.limit_lbl.configure(text="")
            return
        kk = FinansService.kredi_karti_getir(kid)
        if not kk:
            return
        kullanilan = FinansService.kredi_karti_kullanilan(kid)
        limit = Decimal(str(kk.kart_limiti or 0))
        if limit > 0:
            self.limit_lbl.configure(
                text=f"Limit: {_para(limit)} · Kullanılan: {_para(kullanilan)} · "
                f"Kalan: {_para(limit - kullanilan)}"
            )
        else:
            self.limit_lbl.configure(text="Limit tanımlı değil (kontrol yapılmaz).")

    def _vade_ve_plan_guncelle(self):
        for item in self.plan_tablo.get_children():
            self.plan_tablo.delete(item)
        try:
            tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
        except ValueError:
            self._vade_yaz("")
            return
        self._vade_yaz(tarih.strftime("%d.%m.%Y"))
        tur = self._cekim_map.get(self.cekim.get(), "TEK_CEKIM")
        try:
            n = 1 if tur == "TEK_CEKIM" else int(self.taksit.get() or "1")
        except ValueError:
            return
        try:
            tutar = Decimal(str(self.tutar.get() or "0").replace(",", "."))
        except Exception:
            tutar = Decimal("0")
        if tutar <= 0:
            return
        try:
            plan = FinansService.kk_taksit_plani(tarih, n, tutar)
        except ValueError:
            return
        for satir in plan:
            self.plan_tablo.insert(
                "",
                "end",
                values=(
                    satir["taksit_no"],
                    _tarih(satir["vade_tarihi"]),
                    _para(satir["tutar"]),
                ),
            )

    def _vade_yaz(self, metin):
        self.vade.configure(state="normal")
        self.vade.delete(0, "end")
        self.vade.insert(0, metin)
        self.vade.configure(state="readonly")

    def kaydet(self):
        try:
            tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
            tur = self._cekim_map.get(self.cekim.get(), "TEK_CEKIM")
            n = 1 if tur == "TEK_CEKIM" else int(self.taksit.get() or "1")
            cari_id = self.cari_map.get(self.cari.get())
            if cari_id is None:
                raise ValueError("Ödeme yapılan firmayı seçin.")
            kart_id = self._kart_map.get(self.kart.get())
            if kart_id is None:
                raise ValueError("Ödeme kartını seçin.")
            self.result = FinansService.kredi_karti_odeme(
                self.banka_karti_id,
                kart_id,
                cari_id,
                tarih,
                self.tutar.get(),
                cekim_turu=tur,
                taksit_sayisi=n,
                referans_no=self.referans.get().strip() or None,
                aciklama=self.aciklama.get().strip() or None,
            )
        except ValueError as hata:
            messagebox.showerror("Ödeme", str(hata), parent=self)
            return
        r = self.result
        plan_ozet = "\n".join(
            f"  {s['taksit_no']}. {_tarih(s['vade_tarihi'])}  {_para(s['tutar'])}"
            for s in r["plan"][:6]
        )
        if len(r["plan"]) > 6:
            plan_ozet += f"\n  … +{len(r['plan']) - 6} taksit"
        messagebox.showinfo(
            "Kaydedildi",
            f"Belge: {r['belge_no']}\n"
            f"{r['cekim_turu']} · {_para(r['tutar'])}\n"
            f"Vade (1.): {_tarih(r['vade_tarihi'])}\n"
            f"Taksit planı:\n{plan_ozet}",
            parent=self,
        )
        self.destroy()


class BankaAnaKartDialog(tk.Toplevel):
    """Banka ana kartı: sol bilgiler, sağ bakiyeler, alt işlem menüleri."""

    def __init__(self, parent, kart=None):
        super().__init__(parent)
        if kart and getattr(kart, "id", None):
            kart = FinansService.banka_karti_getir(kart.id) or kart
        self.kart = kart
        self.result = None
        self.title("Banka Ana Kartı" + (f" — {kart.banka_adi}" if kart else " — Yeni"))
        self.geometry("1000x820")
        self.minsize(920, 720)
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
        ttk.Label(pos_ayar, text="Kredi kartı (tek çekim yedek) %").grid(
            row=0, column=0, sticky="w", padx=4, pady=4
        )
        self.alanlar["kk_komisyon_orani"] = ttk.Entry(pos_ayar, width=12)
        self.alanlar["kk_komisyon_orani"].grid(row=0, column=1, sticky="w", padx=4, pady=4)
        ttk.Label(pos_ayar, text="Banka kartı komisyon %").grid(
            row=0, column=2, sticky="w", padx=(16, 4), pady=4
        )
        self.alanlar["banka_karti_komisyon_orani"] = ttk.Entry(pos_ayar, width=12)
        self.alanlar["banka_karti_komisyon_orani"].grid(row=0, column=3, sticky="w", padx=4, pady=4)
        ttk.Label(pos_ayar, text="Kaç günde hesaba geçer").grid(
            row=1, column=0, sticky="w", padx=4, pady=4
        )
        self.alanlar["pos_valor_gun"] = ttk.Entry(pos_ayar, width=12)
        self.alanlar["pos_valor_gun"].grid(row=1, column=1, sticky="w", padx=4, pady=4)
        ttk.Label(
            pos_ayar,
            text="(1 = ertesi gün 08:00'de net bakiye KMH'ye aktarılır)",
            foreground="#555",
        ).grid(row=1, column=2, columnspan=2, sticky="w", padx=4)

        taksit_oran = ttk.LabelFrame(
            sol, text="POS hesabı taksit komisyon oranları (kredi kartı, max 12 ay)", padding=10
        )
        taksit_oran.pack(fill="x", pady=(10, 0))
        ttk.Label(
            taksit_oran,
            text="Her taksit sayısı için komisyon % — tahsilatta banka masrafı bu orana göre kesilir.",
            foreground="#555",
        ).pack(anchor="w", pady=(0, 6))
        oran_grid = ttk.Frame(taksit_oran)
        oran_grid.pack(fill="x")
        self.pos_taksit_oranlari = {}
        mevcut_oranlar = {}
        if kart:
            mevcut_oranlar = {
                int(r.taksit_sayisi): Decimal(str(r.komisyon_orani or 0))
                for r in (kart.pos_taksit_komisyonlari or [])
            }
            if 1 not in mevcut_oranlar or mevcut_oranlar.get(1, 0) == 0:
                mevcut_oranlar[1] = Decimal(str(kart.kk_komisyon_orani or 0))
        for i in range(1, POS_MAX_TAKSIT + 1):
            r, c = (i - 1) // 6, ((i - 1) % 6) * 2
            ttk.Label(oran_grid, text=f"{i}. ay %").grid(row=r, column=c, sticky="w", padx=(4, 2), pady=3)
            ent = ttk.Entry(oran_grid, width=7)
            ent.grid(row=r, column=c + 1, sticky="w", padx=(0, 10), pady=3)
            baslangic = mevcut_oranlar.get(i, Decimal("0"))
            ent.insert(0, f"{baslangic:g}" if baslangic else "0")
            self.pos_taksit_oranlari[i] = ent

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
        elif alt_tur == "KREDI_KARTI":
            dialog = KrediKartiIslemleriDialog(self, self.kart)
        else:
            dialog = AltHesapIslemDialog(self, self.kart, alt_tur, alt_etiket)
        self.wait_window(dialog)
        self.bakiyeleri_yenile()

    def kaydet(self):
        veri = {k: w.get().strip() for k, w in self.alanlar.items()}
        if self.kart:
            veri["kart_id"] = self.kart.id
        veri["pos_taksit_komisyonlari"] = {
            n: (w.get() or "0").strip() for n, w in self.pos_taksit_oranlari.items()
        }
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
