"""Tahsilat / ödeme makbuzu — çok satırlı, farklı ödeme şekilleri."""

from __future__ import annotations

import tkinter as tk
from datetime import date, datetime
from decimal import Decimal
from tkinter import messagebox, ttk

from database.cari_service import CariService
from database.finans_service import FinansService
from database.satis_siparisi_service import ODEME_SEKILLERI, decimal
from ui_takvim import tarih_alani

TAHSILAT_MAKBUZ_SEKILLERI = ODEME_SEKILLERI  # NAKİT / KASA, GELEN HAVALE, KREDİ KARTIYLA TAHSİLAT
ODEME_MAKBUZ_SEKILLERI = ("NAKİT / KASA", "GÖNDERİLEN HAVALE")


def _para(tutar):
    return f"{float(tutar or 0):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def _cari_etiket(cari):
    return f"{cari.cari_kodu} - {cari.unvan}"


def _hesap_ozet(makbuz) -> str:
    satirlar = list(getattr(makbuz, "satirlar", None) or [])
    if len(satirlar) > 1:
        adlar = []
        for s in satirlar:
            h = getattr(s, "finans_hesap", None)
            if h and h.hesap_adi not in adlar:
                adlar.append(h.hesap_adi)
        if len(adlar) == 1:
            return f"{adlar[0]} (+{len(satirlar) - 1})"
        return f"Çoklu ({len(satirlar)})"
    if satirlar:
        h = getattr(satirlar[0], "finans_hesap", None)
        if h:
            return h.hesap_adi
    return makbuz.finans_hesap.hesap_adi if makbuz.finans_hesap else "—"


class KasaMakbuzDialog(tk.Toplevel):
    """Çok satırlı tahsilat/ödeme makbuzu (nakit, havale, POS)."""

    def __init__(self, parent, makbuz_turu: str, finans_hesap_id=None, cari_id=None):
        super().__init__(parent)
        self.result = None
        self.makbuz_turu = (makbuz_turu or "").strip().upper()
        if self.makbuz_turu not in ("TAHSILAT", "ODEME"):
            raise ValueError("makbuz_turu TAHSILAT veya ODEME olmalıdır.")

        self.tahsilat = self.makbuz_turu == "TAHSILAT"
        self._odeme_sekilleri = (
            TAHSILAT_MAKBUZ_SEKILLERI if self.tahsilat else ODEME_MAKBUZ_SEKILLERI
        )
        self._varsayilan_hesap_id = finans_hesap_id
        self._varsayilan_cari_id = int(cari_id) if cari_id else None
        self.satirlar: list[dict] = []

        self.title("Tahsilat Makbuzu" if self.tahsilat else "Ödeme Makbuzu")
        self.geometry("720x560")
        self.minsize(640, 480)
        self.transient(parent)
        self.grab_set()

        cariler = CariService.listele(hizli=True)
        self.cari_map = {}
        self._tum_cari_etiketleri = []
        for o in cariler:
            cari = o["cari"]
            etiket = _cari_etiket(cari)
            self.cari_map[etiket] = cari.id
            self._tum_cari_etiketleri.append(etiket)
        # Karttan açıldıysa cari listede yoksa yine de ekle
        if self._varsayilan_cari_id:
            if self._varsayilan_cari_id not in self.cari_map.values():
                cari = CariService.getir(self._varsayilan_cari_id)
                if cari is not None:
                    etiket = _cari_etiket(cari)
                    self.cari_map[etiket] = cari.id
                    self._tum_cari_etiketleri.insert(0, etiket)

        form = ttk.Frame(self, padding=14)
        form.pack(fill="both", expand=True)
        form.columnconfigure(1, weight=1)
        form.rowconfigure(4, weight=1)

        self.girdiler = {}
        tarih_alani(
            form,
            0,
            "Tarih *",
            "tarih",
            date.today().strftime("%d.%m.%Y"),
            self.girdiler,
        )

        cari_etiket = "Cari hesap * (gönderen)" if self.tahsilat else "Cari hesap * (alıcı)"
        ttk.Label(form, text=cari_etiket).grid(row=1, column=0, sticky="nw", padx=4, pady=6)
        cari_c = ttk.Frame(form)
        cari_c.grid(row=1, column=1, sticky="ew", padx=4, pady=6)
        cari_c.columnconfigure(0, weight=1)
        self.cari_var = tk.StringVar()
        self.cari_combo = ttk.Combobox(
            cari_c,
            textvariable=self.cari_var,
            values=self._tum_cari_etiketleri,
            width=48,
        )
        self.cari_combo.grid(row=0, column=0, sticky="ew")
        self.cari_combo.bind("<KeyRelease>", self._cari_filtrele)
        self.cari_combo.bind("<<ComboboxSelected>>", self._cari_secildi_uyari)
        # Cari kartından açıldıysa cariyi kilitle
        if self._varsayilan_cari_id:
            for etiket, cid in self.cari_map.items():
                if cid == self._varsayilan_cari_id:
                    self.cari_var.set(etiket)
                    break
            self.cari_combo.configure(state="disabled")
            ttk.Label(
                cari_c,
                text="Cari kartından seçildi.",
                foreground="#555",
                font=("Segoe UI", 8),
            ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        else:
            ttk.Label(
                cari_c,
                text="Aramak için cari adından en az 3 harf yazın.",
                foreground="#555",
                font=("Segoe UI", 8),
            ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        ttk.Label(form, text="Makbuz no").grid(row=2, column=0, sticky="w", padx=4, pady=6)
        self.makbuz_no = ttk.Entry(form, width=28)
        self.makbuz_no.grid(row=2, column=1, sticky="w", padx=4, pady=6)

        ttk.Label(form, text="Açıklama").grid(row=3, column=0, sticky="nw", padx=4, pady=6)
        self.aciklama = ttk.Entry(form, width=48)
        self.aciklama.grid(row=3, column=1, sticky="ew", padx=4, pady=6)

        satir_kutu = ttk.LabelFrame(
            form,
            text="Tahsilat satırları" if self.tahsilat else "Ödeme satırları",
            padding=8,
        )
        satir_kutu.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        satir_kutu.columnconfigure(0, weight=1)
        satir_kutu.rowconfigure(0, weight=1)

        self.tablo = ttk.Treeview(
            satir_kutu,
            columns=("tarih", "sekil", "hesap", "tutar", "aciklama"),
            show="headings",
            selectmode="browse",
            height=8,
        )
        for k, b, w in (
            ("tarih", "Tarih", 90),
            ("sekil", "Ödeme şekli", 160),
            ("hesap", "Hesap", 160),
            ("tutar", "Tutar", 100),
            ("aciklama", "Açıklama", 160),
        ):
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=w, anchor="w")
        kaydir = ttk.Scrollbar(satir_kutu, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=kaydir.set)
        self.tablo.grid(row=0, column=0, sticky="nsew")
        kaydir.grid(row=0, column=1, sticky="ns")

        satir_btn = ttk.Frame(satir_kutu)
        satir_btn.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(satir_btn, text="Satır Ekle", command=self._satir_ekle).pack(side="left")
        ttk.Button(satir_btn, text="Düzenle", command=self._satir_duzenle).pack(side="left", padx=6)
        ttk.Button(satir_btn, text="Sil", command=self._satir_sil).pack(side="left")
        self.toplam_lbl = ttk.Label(satir_btn, text="Toplam: 0,00 TL", font=("Segoe UI", 10, "bold"))
        self.toplam_lbl.pack(side="right")

        ipucu = (
            "Birden fazla satır ekleyebilirsiniz: nakit, gelen havale ve kredi kartı (POS) aynı makbuzda."
            if self.tahsilat
            else "Birden fazla satır: nakit kasa veya gönderilen havale."
        )
        ttk.Label(form, text=ipucu, foreground="#555", wraplength=620).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(10, 0)
        )

        alt = ttk.Frame(self, padding=(14, 8))
        alt.pack(fill="x", side="bottom")
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(alt, text="Kaydet", width=12, command=self.kaydet).pack(side="right")

        if self._varsayilan_hesap_id:
            self.after(50, self._varsayilan_kasa_satiri)
        if self.tahsilat:
            self._son_uyari_cari_id = None
            self.after(200, self._cari_uyari_goster)

    def _secili_cari_id(self):
        if self._varsayilan_cari_id:
            return self._varsayilan_cari_id
        metin = (self.cari_var.get() or "").strip()
        return self.cari_map.get(metin) if metin else None

    def _cari_secildi_uyari(self, _event=None):
        self._son_uyari_cari_id = None
        self._cari_uyari_goster()

    def _cari_uyari_goster(self):
        if not self.tahsilat:
            return
        cari_id = self._secili_cari_id()
        if not cari_id:
            return
        if getattr(self, "_son_uyari_cari_id", None) == cari_id:
            return
        self._son_uyari_cari_id = cari_id
        from app import cari_uyari_goster

        cari_uyari_goster(self, cari_id)

    def _varsayilan_kasa_satiri(self):
        """Kasa kartından açıldığında satır dialogunu o kasa ile aç."""
        try:
            hesap = FinansService.hesap_getir(int(self._varsayilan_hesap_id))
        except (TypeError, ValueError):
            return
        if not hesap:
            return
        dialog = self._satir_dialog(
            {
                "tahsilat_tarihi": date.today(),
                "odeme_sekli": "NAKİT / KASA",
                "hesap": hesap.hesap_adi,
                "tutar": "",
                "aciklama": "",
            }
        )
        self.wait_window(dialog)
        if dialog.result:
            self.satirlar.append(dialog.result)
            self._satir_listesini_yenile()

    def _cari_filtrele(self, _event=None):
        metin = self.cari_var.get().strip()
        if not metin:
            self.cari_combo["values"] = self._tum_cari_etiketleri
            return
        if len(metin) < 3:
            self.cari_combo["values"] = ()
            return
        ara = metin.casefold()
        self.cari_combo["values"] = [
            e for e in self._tum_cari_etiketleri if ara in e.casefold()
        ]

    def _satir_listesini_yenile(self):
        for item in self.tablo.get_children():
            self.tablo.delete(item)
        toplam = Decimal("0")
        for i, s in enumerate(self.satirlar):
            tarih = s.get("tahsilat_tarihi") or s.get("tarih")
            if hasattr(tarih, "strftime"):
                tarih_metin = tarih.strftime("%d.%m.%Y")
            else:
                tarih_metin = str(tarih or "")
            tutar = decimal(s.get("tutar") or 0, "Tutar", Decimal("0"))
            toplam += tutar
            self.tablo.insert(
                "",
                "end",
                iid=str(i),
                values=(
                    tarih_metin,
                    s.get("odeme_sekli") or "",
                    s.get("hesap") or "",
                    _para(tutar),
                    s.get("aciklama") or "",
                ),
            )
        self.toplam_lbl.configure(text=f"Toplam: {_para(toplam)}")

    def _satir_dialog(self, veri=None):
        from app import SiparisTahsilatiDialog

        return SiparisTahsilatiDialog(
            self,
            veri=veri,
            odeme_sekilleri=self._odeme_sekilleri,
        )

    def _satir_ekle(self):
        dialog = self._satir_dialog()
        self.wait_window(dialog)
        if dialog.result:
            self.satirlar.append(dialog.result)
            self._satir_listesini_yenile()

    def _satir_duzenle(self):
        secim = self.tablo.selection()
        if not secim:
            messagebox.showinfo("Seçim", "Düzenlenecek satırı seçin.", parent=self)
            return
        idx = int(secim[0])
        dialog = self._satir_dialog(self.satirlar[idx])
        self.wait_window(dialog)
        if dialog.result:
            self.satirlar[idx] = dialog.result
            self._satir_listesini_yenile()

    def _satir_sil(self):
        secim = self.tablo.selection()
        if not secim:
            messagebox.showinfo("Seçim", "Silinecek satırı seçin.", parent=self)
            return
        idx = int(secim[0])
        del self.satirlar[idx]
        self._satir_listesini_yenile()

    def kaydet(self):
        try:
            cari_id = self._varsayilan_cari_id
            if not cari_id:
                cari_metin = (self.cari_var.get() or "").strip()
                cari_id = self.cari_map.get(cari_metin) if cari_metin else None
            if not cari_id:
                raise ValueError("Cari hesap seçin.")
            if not self.satirlar:
                raise ValueError(
                    "En az bir tahsilat satırı ekleyin."
                    if self.tahsilat
                    else "En az bir ödeme satırı ekleyin."
                )
            tarih = datetime.strptime(self.girdiler["tarih"].get(), "%d.%m.%Y").date()
            satirlar = []
            for s in self.satirlar:
                satirlar.append(
                    {
                        "tarih": s.get("tahsilat_tarihi") or s.get("tarih") or tarih,
                        "odeme_sekli": s.get("odeme_sekli"),
                        "hesap": s.get("hesap"),
                        "tutar": s.get("tutar"),
                        "aciklama": s.get("aciklama") or None,
                    }
                )
            veriler = {
                "tarih": tarih,
                "cari_id": cari_id,
                "makbuz_no": self.makbuz_no.get().strip() or None,
                "aciklama": self.aciklama.get().strip() or None,
                "satirlar": satirlar,
            }
            if self.makbuz_turu == "TAHSILAT":
                self.result = FinansService.kasa_tahsilat_makbuzu_kaydet(veriler)
            else:
                self.result = FinansService.kasa_odeme_makbuzu_kaydet(veriler)
        except ValueError as hata:
            messagebox.showerror(self.title(), str(hata), parent=self)
            return
        messagebox.showinfo(
            "Kaydedildi",
            f"{self.result.belge_no} — {_para(self.result.tutar)}",
            parent=self,
        )
        self.destroy()


def kasa_makbuzlari_sayfasi(app, makbuz_turu=None, geri_fn=None):
    """Makbuz listesi (isteğe bağlı filtre: TAHSILAT / ODEME)."""
    from finans_ui import finans_menusu_goster, _finans_menu_isaretle

    app._icerigi_temizle()
    _finans_menu_isaretle(app)
    geri = geri_fn or finans_menusu_goster

    if makbuz_turu == "TAHSILAT":
        baslik = "TAHSİLAT MAKBUZLARI"
    elif makbuz_turu == "ODEME":
        baslik = "ÖDEME MAKBUZLARI"
    else:
        baslik = "KASA MAKBUZLARI"

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text=baslik, style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Geri", command=lambda: geri(app)).pack(side="right")

    ttk.Label(
        app.icerik,
        text="Çok satırlı cari tahsilat (TMK) ve ödeme (OMK) makbuzları — nakit, havale, POS.",
    ).pack(anchor="w", pady=(10, 4))

    cerceve = ttk.Frame(app.icerik)
    cerceve.pack(fill="both", expand=True, pady=6)
    tablo = ttk.Treeview(
        cerceve,
        columns=("belge", "tarih", "tur", "hesap", "cari", "tutar", "durum", "aciklama"),
        show="headings",
        selectmode="browse",
    )
    for k, b, w in (
        ("belge", "Belge", 110),
        ("tarih", "Tarih", 90),
        ("tur", "Tür", 90),
        ("hesap", "Hesap", 160),
        ("cari", "Cari", 200),
        ("tutar", "Tutar", 110),
        ("durum", "Durum", 70),
        ("aciklama", "Açıklama", 200),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="w")
    kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=kaydir.set)
    tablo.pack(side="left", fill="both", expand=True)
    kaydir.pack(side="right", fill="y")

    def yenile():
        for item in tablo.get_children():
            tablo.delete(item)
        for m in FinansService.kasa_makbuz_listele(makbuz_turu=makbuz_turu):
            cari = getattr(m, "cari", None)
            tablo.insert(
                "",
                "end",
                iid=str(m.id),
                values=(
                    m.belge_no,
                    m.tarih.strftime("%d.%m.%Y") if m.tarih else "",
                    "Tahsilat" if m.makbuz_turu == "TAHSILAT" else "Ödeme",
                    _hesap_ozet(m),
                    f"{cari.cari_kodu} - {cari.unvan}" if cari else "—",
                    _para(m.tutar),
                    m.durum,
                    (m.aciklama or "")[:80],
                ),
            )

    def yeni(tur):
        dlg = KasaMakbuzDialog(app, makbuz_turu=tur)
        app.wait_window(dlg)
        if dlg.result:
            yenile()

    def iptal():
        secim = tablo.selection()
        if not secim:
            messagebox.showinfo("Seçim", "Bir makbuz seçin.", parent=app)
            return
        if not messagebox.askyesno("İptal", "Makbuz iptal edilsin mi?", parent=app):
            return
        try:
            FinansService.kasa_makbuz_iptal(int(secim[0]))
        except ValueError as hata:
            messagebox.showerror("İptal", str(hata), parent=app)
            return
        yenile()

    def ac(_event=None):
        secim = tablo.selection()
        if not secim:
            messagebox.showinfo("Seçim", "Bir makbuz seçin.", parent=app)
            return
        degerler = tablo.item(secim[0], "values")
        belge_no = (degerler[0] if degerler else "") or ""
        if not belge_no:
            return
        from belge_onizleme_ui import kasa_makbuz_onizle

        kasa_makbuz_onizle(app, belge_no)

    butonlar = ttk.Frame(app.icerik)
    butonlar.pack(fill="x", pady=6)
    if makbuz_turu in (None, "TAHSILAT"):
        ttk.Button(
            butonlar, text="Yeni Tahsilat Makbuzu", command=lambda: yeni("TAHSILAT")
        ).pack(side="left")
    if makbuz_turu in (None, "ODEME"):
        ttk.Button(
            butonlar, text="Yeni Ödeme Makbuzu", command=lambda: yeni("ODEME")
        ).pack(side="left", padx=8)
    ttk.Button(butonlar, text="Belgeyi Aç", command=ac).pack(side="left", padx=8)
    ttk.Button(butonlar, text="İptal Et", command=iptal).pack(side="left", padx=8)
    ttk.Button(butonlar, text="Yenile", command=yenile).pack(side="left")
    tablo.bind("<Double-1>", ac)

    yenile()
