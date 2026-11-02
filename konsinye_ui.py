"""Konsinye Takibi — verilen / alınan sekmeler, teslim, satış bildirimi, iade."""

from __future__ import annotations

import tkinter as tk
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from tkinter import messagebox, simpledialog, ttk
from typing import Any

from database.konsinye_service import (
    DURUM_ONAYLI,
    DURUM_TASLAK,
    YON_ALINAN,
    YON_VERILEN,
    KonsinyeService,
)
from database.stok_service import StokService
from satis_tema import ACIK_BG, BEYAZ, CIZGI, IKINCIL, LACIVERT, SARI, font, hub_ust_baslik, stil_uygula, tk_buton, treeview_stil
from ui_takvim import takvim_butonu
from urun_sec_ui import UrunSecDialog


def _miktar(v) -> str:
    """Gösterim: yalnız ondalık kesrin gereksiz sıfırlarını sil; 100→100 (tam sayının sıfırları silinmez)."""
    from database.konsinye_service import miktar_goster

    return miktar_goster(v)


def _tarih(d) -> str:
    if not d:
        return ""
    if isinstance(d, datetime):
        d = d.date()
    if isinstance(d, date):
        return d.strftime("%d.%m.%Y")
    return str(d)


def _tarih_oku(metin: str) -> date:
    metin = (metin or "").strip()
    for bicim in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(metin, bicim).date()
        except ValueError:
            continue
    raise ValueError(f"Tarih anlaşılamadı: {metin}")


def _sayi(metin: str, ad: str) -> Decimal:
    t = (metin or "").strip().replace(".", "").replace(",", ".") if "," in (metin or "") else (metin or "").strip()
    if not t:
        raise ValueError(f"{ad} zorunlu.")
    try:
        return Decimal(t)
    except InvalidOperation as exc:
        raise ValueError(f"{ad} sayı olmalı.") from exc


def konsinye_takibi_goster(app, *, yon: str | None = None) -> None:
    app._icerigi_temizle()
    stil_uygula(root=app)
    try:
        app.icerik.configure(bg=ACIK_BG)
    except tk.TclError:
        pass
    KonsinyeService.ensure_schema()

    kok = tk.Frame(app.icerik, bg=ACIK_BG)
    kok.pack(fill="both", expand=True)
    hub_ust_baslik(
        kok,
        baslik="KONSİNYE TAKİBİ",
        alt_baslik="Verdiğimiz: bize ait ürün karşı tarafta. Aldığımız: tedarikçiye ait ürün bizde.",
        app=app,
        geri_komut=lambda: __import__("stoklar_ui", fromlist=["stoklar_hub_goster"]).stoklar_hub_goster(app),
        geri_metin="Stoklara Dön",
    )

    def yardim():
        messagebox.showinfo(
            "Konsinye Yardım",
            "1) Yeni Teslim / Giriş ile malı konumlandırın (cari borç yazılmaz).\n"
            "2) Satış Bildir: müşteri satılan miktarı bildirir → fatura bekleyen artar.\n"
            "3) İade Al: satılmamış mal geri döner.\n"
            "4) Gerçek Satış/Alış Faturası oluşturun veya faturayla eşleştirin; "
            "hayali numara kabul edilmez. Stok tekrar hareket etmez.\n"
            "Kesin Al: fiziksel aynı kalır, sahiplik firmaya geçer. Raporlar menüsünü kullanın.",
            parent=app,
        )

    ust_ek = tk.Frame(kok, bg=ACIK_BG)
    ust_ek.pack(fill="x", padx=16, pady=(0, 4))
    tk_buton(ust_ek, "Yardım", yardim, rol="ikincil").pack(side="right")

    nb = ttk.Notebook(kok)
    nb.pack(fill="both", expand=True, padx=12, pady=8)

    verilen = _KonsinyeSekme(app, nb, YON_VERILEN)
    alinan = _KonsinyeSekme(app, nb, YON_ALINAN)
    nb.add(verilen.cerceve, text="Verdiğimiz Konsinyeler")
    nb.add(alinan.cerceve, text="Aldığımız Konsinyeler")
    if yon == YON_ALINAN:
        nb.select(1)
    else:
        nb.select(0)

    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: konsinye_takibi_goster(app, yon=yon))


class _KonsinyeSekme:
    def __init__(self, app, parent, yon: str):
        self.app = app
        self.yon = yon
        self.cerceve = tk.Frame(parent, bg=ACIK_BG)
        self._secili_id: int | None = None
        self._ozet_lbl: dict[str, tk.Label] = {}
        self._liste_kur()
        self.yenile()

    def _liste_kur(self):
        ozet = tk.Frame(self.cerceve, bg=ACIK_BG)
        ozet.pack(fill="x", padx=8, pady=(8, 0))
        for i, (anahtar, baslik) in enumerate(
            (
                ("acik_teslim", "Açık teslim"),
                ("kalan_satir", "Kalan satır"),
                ("fatura_bekleyen_belge", "Fatura bekleyen"),
                ("toplam_belge", "Toplam belge"),
            )
        ):
            kutu = tk.Frame(ozet, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
            kutu.grid(row=0, column=i, sticky="nsew", padx=4, pady=4)
            ozet.columnconfigure(i, weight=1)
            tk.Label(kutu, text=baslik, bg=BEYAZ, fg=IKINCIL, font=font(8, root=self.app)).pack(
                anchor="w", padx=8, pady=(6, 0)
            )
            lbl = tk.Label(kutu, text="0", bg=BEYAZ, fg=LACIVERT, font=font(13, "bold", self.app))
            lbl.pack(anchor="w", padx=8, pady=(0, 8))
            self._ozet_lbl[anahtar] = lbl

        arac = tk.Frame(self.cerceve, bg=ACIK_BG)
        arac.pack(fill="x", padx=8, pady=6)
        yeni_metin = "Yeni Teslim" if self.yon == YON_VERILEN else "Yeni Konsinye Girişi"
        tk_buton(arac, yeni_metin, self._yeni, rol="ana").pack(side="left", padx=2)
        tk_buton(arac, "Yenile", self.yenile, rol="ikincil").pack(side="left", padx=2)
        if self.yon == YON_VERILEN:
            tk_buton(arac, "Satış Bildir", self._satis_bildir, rol="ikincil").pack(side="left", padx=2)
        else:
            tk_buton(arac, "Kesin Al", self._kesin_al, rol="ikincil").pack(side="left", padx=2)
        tk_buton(arac, "İade Al", self._iade, rol="ikincil").pack(side="left", padx=2)
        if self.yon == YON_VERILEN:
            tk_buton(arac, "Satış Faturası Oluştur", self._satis_fatura_olustur, rol="ana").pack(
                side="left", padx=2
            )
        else:
            tk_buton(arac, "Alış Faturası Oluştur", self._alis_fatura_olustur, rol="ana").pack(
                side="left", padx=2
            )
        tk_buton(arac, "Faturayla Eşleştir", self._fatura_bagla, rol="ikincil").pack(side="left", padx=2)
        tk_buton(arac, "Onayla", self._onayla, rol="ikincil").pack(side="left", padx=2)
        tk_buton(arac, "Raporlar", self._raporlar, rol="ikincil").pack(side="left", padx=2)

        filtre = tk.Frame(self.cerceve, bg=ACIK_BG)
        filtre.pack(fill="x", padx=8, pady=(0, 4))
        tk.Label(filtre, text="Ara (cari/ürün/belge)", bg=ACIK_BG, fg=IKINCIL).pack(side="left")
        self.ara = ttk.Entry(filtre, width=28)
        self.ara.pack(side="left", padx=6)
        self.ara.bind("<Return>", lambda _e: self.yenile())
        tk.Label(filtre, text="Durum", bg=ACIK_BG, fg=IKINCIL).pack(side="left", padx=(12, 0))
        self.durum = ttk.Combobox(
            filtre, values=("Tümü", "TASLAK", "ONAYLI", "KAPALI"), state="readonly", width=12
        )
        self.durum.set("Tümü")
        self.durum.pack(side="left", padx=4)
        self.durum.bind("<<ComboboxSelected>>", lambda _e: self.yenile())

        tablo_fr = tk.Frame(self.cerceve, bg=ACIK_BG)
        tablo_fr.pack(fill="both", expand=True, padx=8, pady=4)
        kolonlar = ("belge_no", "tarih", "cari", "durum", "satir", "kalan", "fatura_bek")
        self.tablo = ttk.Treeview(tablo_fr, columns=kolonlar, show="headings", height=12)
        basliklar = {
            "belge_no": "Belge",
            "tarih": "Tarih",
            "cari": "Cari",
            "durum": "Durum",
            "satir": "Satır",
            "kalan": "Kalan (temel)",
            "fatura_bek": "Fatura bekleyen",
        }
        for k, b in basliklar.items():
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=110 if k != "cari" else 220, anchor="w")
        sy = ttk.Scrollbar(tablo_fr, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=sy.set)
        self.tablo.pack(side="left", fill="both", expand=True)
        sy.pack(side="right", fill="y")
        treeview_stil(self.tablo)
        self.tablo.bind("<<TreeviewSelect>>", self._secim)
        self.tablo.bind("<Double-1>", lambda _e: self._ayrinti())

        detay = tk.LabelFrame(self.cerceve, text="Satırlar", bg=ACIK_BG, fg=LACIVERT)
        detay.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        sk = ("kod", "ad", "miktar", "kalan", "bildirilen", "fatura", "iade", "adim")
        self.satir_tablo = ttk.Treeview(detay, columns=sk, show="headings", height=7)
        for k, b in zip(
            sk,
            ("Kod", "Ürün", "Teslim", "Kalan", "Bildirilen", "Faturalanan", "İade", "Adım"),
        ):
            self.satir_tablo.heading(k, text=b)
            self.satir_tablo.column(k, width=90 if k != "ad" else 180, anchor="w")
        self.satir_tablo.pack(fill="both", expand=True, padx=4, pady=4)
        treeview_stil(self.satir_tablo)

    def yenile(self):
        durum = self.durum.get()
        durum_f = None if durum == "Tümü" else durum
        try:
            # Ekranda sayfalama yok; tüm kayıtlar (filtre + arama)
            liste = KonsinyeService.listele(yon=self.yon, durum=durum_f, limit=None)
            ozet = KonsinyeService.ozet_kutulari(self.yon)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Konsinye", str(exc), parent=self.app)
            return
        for k, lbl in self._ozet_lbl.items():
            lbl.configure(text=str(ozet.get(k, 0)))
        q = (self.ara.get() or "").strip().casefold()
        for i in self.tablo.get_children():
            self.tablo.delete(i)
        for t in liste:
            metin = " ".join(
                [
                    str(t.get("belge_no") or ""),
                    str(t.get("cari_unvan") or ""),
                    str(t.get("cari_kodu") or ""),
                    " ".join(s.get("stok_kodu") or "" for s in t.get("satirlar") or []),
                ]
            ).casefold()
            if q and q not in metin:
                continue
            self.tablo.insert(
                "",
                "end",
                iid=str(t["id"]),
                values=(
                    t["belge_no"],
                    _tarih(t["belge_tarihi"]),
                    t.get("cari_unvan") or "",
                    t["durum"],
                    t["satir_sayisi"],
                    _miktar(t["kalan_toplam"]),
                    _miktar(t["fatura_bekleyen_toplam"]),
                ),
            )
        self._satirlari_temizle()
        self._secili_id = None

    def _secim(self, _e=None):
        sec = self.tablo.selection()
        if not sec:
            return
        self._secili_id = int(sec[0])
        self._ayrinti()

    def _satirlari_temizle(self):
        for i in self.satir_tablo.get_children():
            self.satir_tablo.delete(i)

    def _ayrinti(self):
        if not self._secili_id:
            return
        t = KonsinyeService.getir(self._secili_id)
        if not t:
            return
        self._satirlari_temizle()
        for s in t.get("satirlar") or []:
            self.satir_tablo.insert(
                "",
                "end",
                iid=str(s["id"]),
                values=(
                    s["stok_kodu"],
                    s["stok_adi"],
                    _miktar(s["temel_miktar"]),
                    _miktar(s["kalan_miktar"]),
                    _miktar(s["bildirilen_miktar"]),
                    _miktar(s["faturalanan_miktar"]),
                    _miktar(s["iade_miktar"]),
                    s["adim"],
                ),
            )

    def _secili_teslim(self) -> dict[str, Any] | None:
        if not self._secili_id:
            messagebox.showinfo("Konsinye", "Listeden bir teslim seçin.", parent=self.app)
            return None
        return KonsinyeService.getir(self._secili_id)

    def _secili_satir_id(self) -> int | None:
        sec = self.satir_tablo.selection()
        if not sec:
            messagebox.showinfo("Konsinye", "Alttaki satır tablosundan ürün satırı seçin.", parent=self.app)
            return None
        return int(sec[0])

    def _yeni(self):
        dlg = _TeslimDialog(self.app, yon=self.yon)
        self.app.wait_window(dlg)
        if dlg.result:
            self.yenile()
            try:
                self.tablo.selection_set(str(dlg.result["id"]))
                self._secili_id = int(dlg.result["id"])
                self._ayrinti()
            except tk.TclError:
                pass

    def _onayla(self):
        t = self._secili_teslim()
        if not t:
            return
        if t["durum"] != DURUM_TASLAK:
            messagebox.showinfo("Konsinye", "Yalnız taslak onaylanır.", parent=self.app)
            return
        ozet = (
            f"Belge: {t['belge_no']}\nCari: {t['cari_unvan']}\nDepo: {t['depo']}\n"
            f"Satır: {t['satir_sayisi']}\n\nOnayda stok konumu güncellenir; cari borç yazılmaz."
        )
        if not messagebox.askyesno("Onay", ozet, parent=self.app):
            return
        try:
            KonsinyeService.teslim_onayla(t["id"])
            messagebox.showinfo("Konsinye", "Teslim onaylandı.", parent=self.app)
            self.yenile()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Konsinye", str(exc), parent=self.app)

    def _miktar_iste(self, baslik: str, max_m: Decimal) -> Decimal | None:
        metin = simpledialog.askstring(
            baslik,
            f"Miktar (en fazla {_miktar(max_m)} temel birim):",
            parent=self.app,
            initialvalue=_miktar(max_m),
        )
        if metin is None:
            return None
        try:
            m = _sayi(metin, "Miktar")
        except ValueError as exc:
            messagebox.showerror("Konsinye", str(exc), parent=self.app)
            return None
        if m <= 0 or m > max_m:
            messagebox.showerror("Konsinye", "Miktar geçersiz.", parent=self.app)
            return None
        return m

    def _satis_bildir(self):
        t = self._secili_teslim()
        if not t or t["durum"] != DURUM_ONAYLI:
            messagebox.showinfo("Konsinye", "Onaylı teslim ve satır seçin.", parent=self.app)
            return
        sid = self._secili_satir_id()
        if not sid:
            return
        satir = next((s for s in t["satirlar"] if s["id"] == sid), None)
        if not satir or satir["kalan_miktar"] <= 0:
            messagebox.showinfo("Konsinye", "Kalan miktarı olan satır seçin.", parent=self.app)
            return
        m = self._miktar_iste("Satış Bildirimi", Decimal(str(satir["kalan_miktar"])))
        if m is None:
            return
        tarih_m = simpledialog.askstring(
            "Gerçek satış tarihi", "gg.aa.yyyy:", parent=self.app, initialvalue=_tarih(date.today())
        )
        try:
            gt = _tarih_oku(tarih_m) if tarih_m else date.today()
            KonsinyeService.satis_bildir(teslim_satiri_id=sid, miktar=m, gercek_tarih=gt)
            messagebox.showinfo("Konsinye", "Satış bildirimi kaydedildi.", parent=self.app)
            self.yenile()
            self.tablo.selection_set(str(t["id"]))
            self._secili_id = t["id"]
            self._ayrinti()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Konsinye", str(exc), parent=self.app)

    def _iade(self):
        t = self._secili_teslim()
        if not t or t["durum"] != DURUM_ONAYLI:
            messagebox.showinfo("Konsinye", "Onaylı teslim ve satır seçin.", parent=self.app)
            return
        sid = self._secili_satir_id()
        if not sid:
            return
        satir = next((s for s in t["satirlar"] if s["id"] == sid), None)
        if not satir or satir["kalan_miktar"] <= 0:
            messagebox.showinfo("Konsinye", "Kalan miktarı olan satır seçin.", parent=self.app)
            return
        m = self._miktar_iste("İade", Decimal(str(satir["kalan_miktar"])))
        if m is None:
            return
        try:
            KonsinyeService.iade_al(teslim_satiri_id=sid, miktar=m)
            messagebox.showinfo("Konsinye", "İade kaydedildi.", parent=self.app)
            self.yenile()
            self.tablo.selection_set(str(t["id"]))
            self._secili_id = t["id"]
            self._ayrinti()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Konsinye", str(exc), parent=self.app)

    def _kesin_al(self):
        t = self._secili_teslim()
        if not t or t["durum"] != DURUM_ONAYLI:
            messagebox.showinfo("Konsinye", "Onaylı alınan konsinye satırı seçin.", parent=self.app)
            return
        sid = self._secili_satir_id()
        if not sid:
            return
        satir = next((s for s in t["satirlar"] if s["id"] == sid), None)
        if not satir or satir["kalan_miktar"] <= 0:
            return
        m = self._miktar_iste("Kesin Al", Decimal(str(satir["kalan_miktar"])))
        if m is None:
            return
        if not messagebox.askyesno(
            "Kesin Al",
            "Bu miktar tedarikçiden kesin alıma dönüşecek; alış faturası bekleyen artacak. Devam?",
            parent=self.app,
        ):
            return
        try:
            KonsinyeService.kesin_al(teslim_satiri_id=sid, miktar=m)
            messagebox.showinfo("Konsinye", "Kesin alım kaydedildi.", parent=self.app)
            self.yenile()
            self.tablo.selection_set(str(t["id"]))
            self._secili_id = t["id"]
            self._ayrinti()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Konsinye", str(exc), parent=self.app)

    def _fatura_bagla(self):
        """Mevcut gerçek fatura kimliğiyle eşleştir (hayali numara kabul edilmez)."""
        t = self._secili_teslim()
        if not t:
            return
        sid = self._secili_satir_id()
        if not sid:
            return
        satir = next((s for s in t["satirlar"] if s["id"] == sid), None)
        bek = Decimal(str((satir or {}).get("fatura_bekleyen") or 0))
        if bek <= 0:
            messagebox.showinfo("Konsinye", "Fatura bekleyen miktar yok.", parent=self.app)
            return
        m = self._miktar_iste("Faturayla Eşleştir", bek)
        if m is None:
            return
        belge_id_s = simpledialog.askstring(
            "Fatura kimliği",
            "Gerçek fatura ID (zorunlu). Yalnız numara yeterli değildir:",
            parent=self.app,
        )
        if not belge_id_s or not str(belge_id_s).strip().isdigit():
            messagebox.showerror("Konsinye", "Geçerli fatura ID girin.", parent=self.app)
            return
        belge_no = simpledialog.askstring(
            "Fatura no", "Kontrol için fatura no (isteğe bağlı):", parent=self.app
        )
        try:
            KonsinyeService.fatura_bagla(
                teslim_satiri_id=sid,
                miktar=m,
                belge_id=int(belge_id_s),
                belge_no=belge_no,
                onayli=True,
            )
            messagebox.showinfo(
                "Konsinye",
                "Gerçek faturaya bağlandı (stok tekrar hareket etmez).",
                parent=self.app,
            )
            self.yenile()
            self.tablo.selection_set(str(t["id"]))
            self._secili_id = t["id"]
            self._ayrinti()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Konsinye", str(exc), parent=self.app)

    def _satis_fatura_olustur(self):
        t = self._secili_teslim()
        if not t or t["durum"] != DURUM_ONAYLI:
            messagebox.showinfo("Konsinye", "Onaylı verilen teslim ve satır seçin.", parent=self.app)
            return
        sid = self._secili_satir_id()
        if not sid:
            return
        satir = next((s for s in t["satirlar"] if s["id"] == sid), None)
        bek = Decimal(str((satir or {}).get("fatura_bekleyen") or 0))
        if bek <= 0:
            messagebox.showinfo("Konsinye", "Fatura bekleyen miktar yok.", parent=self.app)
            return
        m = self._miktar_iste("Satış faturası miktarı", bek)
        if m is None:
            return
        try:
            hazir = KonsinyeService.satis_faturasi_satirlari_hazirla([(sid, m)])
            messagebox.showinfo(
                "Konsinye",
                f"Satış faturası için {len(hazir['satirlar'])} satır hazır "
                f"(cari_id={hazir['cari_id']}).\n"
                "Satış Faturası ekranından kaydedip onaylayın; ardından "
                "«Faturayla Eşleştir» ile belge ID bağlayın.\n"
                "(Stok bildiriminde zaten çıktı — fatura onayı tekrar düşürmez.)",
                parent=self.app,
            )
            # Hazır satırları pano/öznitelik — ana fatura UI açılırsa kullanılsın
            self.app._konsinye_fatura_hazir = hazir
            if hasattr(self.app, "yeni_satis_faturasi"):
                self.app.yeni_satis_faturasi()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Konsinye", str(exc), parent=self.app)

    def _alis_fatura_olustur(self):
        t = self._secili_teslim()
        if not t or t["durum"] != DURUM_ONAYLI:
            messagebox.showinfo("Konsinye", "Onaylı alınan teslim ve satır seçin.", parent=self.app)
            return
        sid = self._secili_satir_id()
        if not sid:
            return
        satir = next((s for s in t["satirlar"] if s["id"] == sid), None)
        bek = Decimal(str((satir or {}).get("fatura_bekleyen") or 0))
        if bek <= 0:
            messagebox.showinfo("Konsinye", "Fatura bekleyen (kesin alınan) yok.", parent=self.app)
            return
        m = self._miktar_iste("Alış faturası miktarı", bek)
        if m is None:
            return
        try:
            hazir = KonsinyeService.alis_faturasi_satirlari_hazirla([(sid, m)])
            self.app._konsinye_fatura_hazir = hazir
            messagebox.showinfo(
                "Konsinye",
                f"Alış faturası için {len(hazir['satirlar'])} satır hazır "
                f"(cari_id={hazir['cari_id']}).\n"
                "Alış Faturası ekranından kaydedin; stok kesin alımda oluştuğu için "
                "tekrar giriş yazılmaz. Sonra «Faturayla Eşleştir».",
                parent=self.app,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Konsinye", str(exc), parent=self.app)

    def _raporlar(self):
        from database.konsinye_rapor_service import KonsinyeRaporService

        menu = tk.Menu(self.app, tearoff=0)

        def _goster(baslik, veri):
            win = tk.Toplevel(self.app)
            win.title(baslik)
            win.geometry("960x480")
            txt = tk.Text(win, wrap="none", font=("Consolas", 9))
            txt.pack(fill="both", expand=True)
            satirlar = veri.get("satirlar") or veri.get("hatalar") or []
            txt.insert("end", f"{baslik} — {veri.get('adet', len(satirlar))} kayıt\n\n")
            for s in satirlar[:2000]:
                txt.insert("end", f"{s}\n")
            if veri.get("dilimler"):
                for k, v in veri["dilimler"].items():
                    txt.insert("end", f"\n[{k}] {len(v)} satır\n")
                    for s in v[:200]:
                        txt.insert("end", f"  {s}\n")

        menu.add_command(
            label="Müşterideki Konsinye Mallar",
            command=lambda: _goster(
                "Müşterideki", KonsinyeRaporService.musterideki_mallar()
            ),
        )
        menu.add_command(
            label="Tedarikçiye Ait Envanter",
            command=lambda: _goster(
                "Tedarikçi Envanter", KonsinyeRaporService.tedarikci_envanteri()
            ),
        )
        menu.add_command(
            label="Faturalanmayı Bekleyen",
            command=lambda: _goster(
                "Fatura Bekleyen", KonsinyeRaporService.fatura_bekleyen(yon=self.yon)
            ),
        )
        menu.add_command(
            label="Yaşlandırma",
            command=lambda: _goster("Yaşlandırma", KonsinyeRaporService.yaslandirma()),
        )
        menu.add_command(
            label="Hareket Geçmişi",
            command=lambda: _goster(
                "Hareket", KonsinyeRaporService.hareket_gecmisi()
            ),
        )
        menu.add_command(
            label="Tutarlılık / Hata",
            command=lambda: _goster(
                "Tutarlılık", KonsinyeRaporService.tutarlilik()
            ),
        )
        try:
            menu.tk_popup(self.app.winfo_pointerx(), self.app.winfo_pointery())
        finally:
            menu.grab_release()


class _TeslimDialog(tk.Toplevel):
    def __init__(self, parent, *, yon: str):
        super().__init__(parent)
        self.result = None
        self.yon = yon
        self.cari_id: int | None = None
        self.satirlar: list[dict[str, Any]] = []
        self.title("Yeni Konsinye Teslim" if yon == YON_VERILEN else "Yeni Konsinye Girişi")
        self.geometry("920x560")
        self.minsize(800, 480)
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)

        ust = ttk.LabelFrame(self, text="Belge", padding=10)
        ust.pack(fill="x", padx=12, pady=10)
        ttk.Label(ust, text="Cari").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self.cari_ad = ttk.Entry(ust, width=36)
        self.cari_ad.grid(row=0, column=1, sticky="w", padx=4, pady=4)
        self.cari_kod = ttk.Label(ust, text="")
        self.cari_kod.grid(row=0, column=2, sticky="w", padx=4)
        from cari_arama_alani import CariAramaAlani

        tur = "Müşteri" if yon == YON_VERILEN else "Tedarikçi"
        self._cari_arama = CariAramaAlani(
            self,
            self.cari_ad,
            cari_turu=tur,
            on_secim=self._cari_sec,
            on_temizle=self._cari_temizle,
            secili_ad=lambda: self.cari_ad.get(),
            kayit_adi=tur,
        )
        ttk.Label(ust, text="Tarih").grid(row=0, column=3, sticky="w", padx=4)
        tf = ttk.Frame(ust)
        tf.grid(row=0, column=4, sticky="w")
        self.tarih = ttk.Entry(tf, width=12)
        self.tarih.pack(side="left")
        self.tarih.insert(0, _tarih(date.today()))
        takvim_butonu(tf, self.tarih)

        depolar = tuple(d.ad for d in StokService.depolar()) or ("ANA DEPO",)
        ttk.Label(ust, text="Depo").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        self.depo = ttk.Combobox(ust, values=depolar, state="readonly", width=28)
        self.depo.grid(row=1, column=1, sticky="w", padx=4, pady=4)
        if depolar:
            self.depo.current(0)
        ttk.Label(ust, text="Açıklama").grid(row=1, column=2, sticky="w", padx=4)
        self.aciklama = ttk.Entry(ust, width=40)
        self.aciklama.grid(row=1, column=3, columnspan=2, sticky="ew", padx=4, pady=4)

        form = ttk.LabelFrame(self, text="Ürün satırı", padding=8)
        form.pack(fill="x", padx=12)
        self.kod = ttk.Entry(form, width=14)
        self.ad = ttk.Entry(form, width=28)
        self.birim = ttk.Combobox(form, values=("Adet", "Kg", "Metre", "Koli", "Paket"), width=8)
        self.birim.set("Adet")
        self.miktar = ttk.Entry(form, width=10)
        self.miktar.insert(0, "1")
        self.fiyat = ttk.Entry(form, width=12)
        self.fiyat.insert(0, "0")
        for i, (e, w) in enumerate(
            (("Kod", self.kod), ("Ad", self.ad), ("Birim", self.birim), ("Miktar", self.miktar), ("Fiyat", self.fiyat))
        ):
            ttk.Label(form, text=e).grid(row=0, column=i, sticky="w", padx=3)
            w.grid(row=1, column=i, sticky="w", padx=3, pady=2)
        bf = ttk.Frame(form)
        bf.grid(row=1, column=5, padx=8)
        ttk.Button(bf, text="Ürün Seç", command=self._urun_sec).pack(side="left", padx=2)
        ttk.Button(bf, text="Ekle", command=self._satir_ekle).pack(side="left", padx=2)
        self.kod.bind("<Return>", lambda _e: self._urun_sec())

        liste_fr = ttk.LabelFrame(self, text="Satırlar", padding=8)
        liste_fr.pack(fill="both", expand=True, padx=12, pady=8)
        self.liste = ttk.Treeview(
            liste_fr, columns=("kod", "ad", "birim", "miktar", "fiyat"), show="headings", height=10
        )
        for k, b in (("kod", "Kod"), ("ad", "Ad"), ("birim", "Birim"), ("miktar", "Miktar"), ("fiyat", "Fiyat")):
            self.liste.heading(k, text=b)
            self.liste.column(k, width=100 if k != "ad" else 220)
        self.liste.pack(fill="both", expand=True)

        alt = ttk.Frame(self)
        alt.pack(fill="x", padx=12, pady=10)
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(alt, text="Kaydet ve Onayla", command=lambda: self._kaydet(True)).pack(side="right", padx=4)
        ttk.Button(alt, text="Taslak Kaydet", command=lambda: self._kaydet(False)).pack(side="right", padx=4)

    def _cari_sec(self, cari):
        self.cari_id = int(cari.id)
        self.cari_ad.delete(0, "end")
        self.cari_ad.insert(0, cari.unvan or "")
        self.cari_kod.configure(text=cari.cari_kodu or "")

    def _cari_temizle(self):
        self.cari_id = None
        self.cari_kod.configure(text="")

    def _urun_secildi(self, degerler):
        kod = degerler[0] if degerler else ""
        ad = degerler[1] if len(degerler) > 1 else ""
        birim = degerler[2] if len(degerler) > 2 else "Adet"
        self.kod.delete(0, "end")
        self.kod.insert(0, kod or "")
        self.ad.delete(0, "end")
        self.ad.insert(0, ad or "")
        self.birim.set(birim or "Adet")
        self.miktar.focus_set()

    def _urun_sec(self):
        UrunSecDialog(self, on_select=self._urun_secildi)

    def _satir_ekle(self):
        kod = (self.kod.get() or "").strip()
        if not kod:
            messagebox.showerror("Konsinye", "Ürün kodu girin.", parent=self)
            return
        try:
            mik = _sayi(self.miktar.get(), "Miktar")
            fiyat = _sayi(self.fiyat.get() or "0", "Fiyat")
        except ValueError as exc:
            messagebox.showerror("Konsinye", str(exc), parent=self)
            return
        self.satirlar.append(
            {
                "stok_kodu": kod,
                "stok_adi": (self.ad.get() or "").strip() or kod,
                "birim": self.birim.get() or "Adet",
                "miktar": mik,
                "birim_fiyat": fiyat,
            }
        )
        self.liste.insert(
            "",
            "end",
            values=(kod, self.ad.get(), self.birim.get(), _miktar(mik), _miktar(fiyat)),
        )
        self.kod.delete(0, "end")
        self.ad.delete(0, "end")
        self.miktar.delete(0, "end")
        self.miktar.insert(0, "1")
        self.kod.focus_set()

    def _kaydet(self, onayla: bool):
        if not self.cari_id:
            messagebox.showerror("Konsinye", "Cari seçin.", parent=self)
            return
        if not self.satirlar:
            messagebox.showerror("Konsinye", "En az bir satır ekleyin.", parent=self)
            return
        depo_ad = self.depo.get()
        depolar = {d.ad: d.id for d in StokService.depolar()}
        depo_id = depolar.get(depo_ad)
        if not depo_id:
            messagebox.showerror("Konsinye", "Depo bulunamadı.", parent=self)
            return
        try:
            bt = _tarih_oku(self.tarih.get())
            if onayla:
                ozet = (
                    f"Cari: {self.cari_ad.get()}\nDepo: {depo_ad}\n"
                    f"Satır: {len(self.satirlar)}\n\n"
                    "Onayda stok konumu güncellenir; cari borç yazılmaz. Devam?"
                )
                if not messagebox.askyesno("Onay özeti", ozet, parent=self):
                    return
            self.result = KonsinyeService.teslim_kaydet(
                yon=self.yon,
                cari_id=self.cari_id,
                depo_id=int(depo_id),
                belge_tarihi=bt,
                satirlar=self.satirlar,
                aciklama=self.aciklama.get(),
                onayla=onayla,
            )
            messagebox.showinfo(
                "Konsinye",
                f"Belge {self.result['belge_no']} {'onaylandı' if onayla else 'taslak kaydedildi'}.",
                parent=self,
            )
            self.destroy()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Konsinye", str(exc), parent=self)
