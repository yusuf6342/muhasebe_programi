"""Ödeme ve kapatma izleme bileşenleri (satış/alış faturası, iade, devir, dekont, makbuz).

Tüm ekranlar aynı servis çıktısını (``database.kapatma_izleme_service``) kullanır; kayıtlar salt
okunurdur. Yeniden dağıtım bu pencerelerden yapılmaz.
"""

from __future__ import annotations

import tkinter as tk
from decimal import Decimal
from tkinter import messagebox, ttk

from database.kapatma_izleme_service import (
    BILINMIYOR,
    MESAJ_AVANS,
    evrak_kapatma_detayi,
    fatura_odeme_ozeti,
    kaynak_dagitim_detayi,
)


def _para(deger) -> str:
    if deger is None or deger == "":
        return ""
    try:
        d = Decimal(str(deger))
    except Exception:
        return str(deger)
    metin = f"{d:,.2f}"
    return metin.replace(",", "X").replace(".", ",").replace("X", ".")


def _tarih(deger) -> str:
    if not deger:
        return ""
    try:
        return deger.strftime("%d.%m.%Y")
    except Exception:
        return str(deger)


def _zaman(deger) -> str:
    if not deger:
        return ""
    try:
        return deger.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(deger)


def evraki_ac(parent, ac_tur: str, belge_no: str) -> None:
    if not belge_no:
        messagebox.showinfo("Evrak", "Bu satırın açılabilir evrakı yok.", parent=parent)
        return
    from belge_onizleme_ui import hareket_belgeyi_ac

    try:
        if not hareket_belgeyi_ac(parent, ac_tur or "", belge_no):
            messagebox.showinfo("Evrak", f"{belge_no} için açılabilir evrak bulunamadı.", parent=parent)
    except ValueError as hata:
        messagebox.showerror("Evrak", str(hata), parent=parent)


def _tablo(parent, kolonlar, height=8):
    cerceve = ttk.Frame(parent)
    tablo = ttk.Treeview(
        cerceve, columns=[k for k, *_ in kolonlar], show="headings", height=height, selectmode="browse"
    )
    for kolon, baslik, genislik, hiza in kolonlar:
        tablo.heading(kolon, text=baslik, anchor=hiza)
        tablo.column(kolon, width=genislik, minwidth=50, anchor=hiza, stretch=(hiza == "w"))
    dikey = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    yatay = ttk.Scrollbar(cerceve, orient="horizontal", command=tablo.xview)
    tablo.configure(yscrollcommand=dikey.set, xscrollcommand=yatay.set)
    tablo.grid(row=0, column=0, sticky="nsew")
    dikey.grid(row=0, column=1, sticky="ns")
    yatay.grid(row=1, column=0, sticky="ew")
    cerceve.rowconfigure(0, weight=1)
    cerceve.columnconfigure(0, weight=1)
    tablo.tag_configure("bilinmiyor", foreground="#8D6E63")
    tablo.tag_configure("eski", foreground="#37474F")
    return cerceve, tablo


KAPATAN_KOLONLARI = (
    ("tarih", "Tarih", 85, "center"),
    ("tur", "Evrak Türü", 190, "w"),
    ("no", "Evrak No", 120, "w"),
    ("pay", "Bu Evraka Payı", 110, "e"),
    ("toplam", "Ödeme Evrakı Toplamı", 130, "e"),
    ("pb", "Döviz", 50, "center"),
    ("islem", "İşlem Türü", 110, "w"),
    ("hesap", "Kasa / Banka", 140, "w"),
    ("yontem", "Yöntem", 90, "w"),
)

KAPATILAN_KOLONLARI = (
    ("tur", "Evrak Türü", 150, "w"),
    ("no", "Evrak No", 120, "w"),
    ("tarih", "Evrak Tarihi", 85, "center"),
    ("ilk", "İlk Tutar", 105, "e"),
    ("kapatilan", "Bu İşlemle Kapatılan", 130, "e"),
    ("sonrasi", "İşlem Sonrası Kalan", 125, "e"),
    ("pb", "Döviz", 50, "center"),
    ("islem", "İşlem Türü", 110, "w"),
)

IPTAL_KOLONLARI = (
    ("zaman", "Geri Alma Zamanı", 120, "center"),
    ("kullanici", "Kullanıcı", 110, "w"),
    ("neden", "Gerekçe", 240, "w"),
    ("no", "Evrak No", 120, "w"),
    ("tutar", "Tutar", 100, "e"),
    ("tarih", "İlk İşlem Tarihi", 95, "center"),
    ("islem", "İşlem Türü", 100, "w"),
)


class KapatilanBorclarPaneli(ttk.LabelFrame):
    """Kaydedilmiş ödeme evrakının "Kapatılan Borçlar / Alacaklar" tablosu (salt okunur)."""

    def __init__(self, parent, belge_no: str, cari_id: int, *, baslik="Kapatılan Borçlar / Alacaklar", height=5):
        super().__init__(parent, text=baslik, padding=6)
        self.belge_no = belge_no
        self.cari_id = int(cari_id)
        self._satirlar: dict[str, dict] = {}
        cerceve, self.tablo = _tablo(self, KAPATILAN_KOLONLARI, height=height)
        cerceve.pack(fill="both", expand=True)
        alt = ttk.Frame(self)
        alt.pack(fill="x", pady=(4, 0))
        self.ozet_lbl = ttk.Label(alt, text="", foreground="#1B2A4A", wraplength=720, justify="left")
        self.ozet_lbl.pack(side="left", fill="x", expand=True)
        ttk.Button(alt, text="Evrakı Aç", command=self.secili_evraki_ac).pack(side="right")
        self.tablo.bind("<Double-1>", lambda _e: self.secili_evraki_ac())
        self.yenile()

    def yenile(self):
        self.tablo.delete(*self.tablo.get_children())
        self._satirlar.clear()
        try:
            veri = kaynak_dagitim_detayi(self.belge_no, self.cari_id)
        except Exception as hata:
            self.ozet_lbl.configure(text=f"Kapatma bilgisi okunamadı: {hata}")
            return
        for i, s in enumerate(veri["satirlar"]):
            iid = str(i)
            self._satirlar[iid] = s
            etiket = "bilinmiyor" if s["kaynak"] == "BILINMIYOR" else ("eski" if s["kaynak"] != "KAYIT" else "")
            self.tablo.insert(
                "",
                "end",
                iid=iid,
                tags=(etiket,) if etiket else (),
                values=(
                    s["evrak_turu"],
                    s["evrak_no"],
                    _tarih(s.get("evrak_tarihi")),
                    _para(s.get("ilk_tutar")),
                    _para(s["kapatilan"]),
                    _para(s.get("sonrasi_kalan")),
                    s.get("para_birimi") or "TRY",
                    s.get("tur") or "",
                ),
            )
        parcalar = [
            f"Evrak toplamı {_para(veri['toplam'])} = dağıtılan {_para(veri['dagitilan'])}"
            f" + kullanılmamış avans {_para(veri['avans_kalan'])}"
        ]
        if veri["bilinmeyen"] > 0:
            parcalar[0] += f" + {BILINMIYOR.lower()} {_para(veri['bilinmeyen'])}"
        if veri["mesaj"]:
            parcalar.append(veri["mesaj"])
        elif not veri["satirlar"]:
            parcalar.append(MESAJ_AVANS if veri["avans_kalan"] > 0 else "Kapatma kaydı yok.")
        if veri["iptaller"]:
            parcalar.append(f"Geri alınmış {len(veri['iptaller'])} kapatma kaydı var (Kapatma Detayı).")
        if veri["uyari"]:
            parcalar.append("⚠ " + veri["uyari"])
        self.ozet_lbl.configure(text="  |  ".join(parcalar))

    def secili_evraki_ac(self):
        secim = self.tablo.selection()
        if not secim:
            return
        s = self._satirlar.get(secim[0]) or {}
        if s.get("kaynak") == "BILINMIYOR":
            messagebox.showinfo("Evrak", f"{BILINMIYOR}: bu pay kayıtlı bir evraka bağlanamıyor.", parent=self)
            return
        evraki_ac(self.winfo_toplevel(), s.get("ac_tur") or "", s.get("evrak_no") or "")


class KapatmaDetayDialog(tk.Toplevel):
    """Bir evrakın ödeme / kapatma ayrıntısı: kapatanlar, kapattıkları ve iptal geçmişi."""

    def __init__(self, parent, belge_no: str, cari_id: int | None = None, *, baslik: str | None = None):
        super().__init__(parent)
        self.belge_no = (belge_no or "").strip()
        self.cari_id = cari_id
        self.title(baslik or f"Kapatma Detayı — {self.belge_no}")
        self.transient(parent)
        self.geometry("980x520")
        self.minsize(640, 360)
        self._kapatan_satirlari: dict[str, dict] = {}

        ust = ttk.Frame(self, padding=(10, 8))
        ust.pack(fill="x")
        self.baslik_lbl = ttk.Label(ust, text="", font=("Segoe UI", 11, "bold"))
        self.baslik_lbl.pack(anchor="w")
        self.ozet_lbl = ttk.Label(ust, text="", font=("Segoe UI", 10))
        self.ozet_lbl.pack(anchor="w", pady=(2, 0))
        self.mesaj_lbl = ttk.Label(ust, text="", foreground="#1565C0", wraplength=900, justify="left")
        self.mesaj_lbl.pack(anchor="w")
        self.uyari_lbl = ttk.Label(ust, text="", foreground="#C62828", wraplength=900, justify="left")
        self.uyari_lbl.pack(anchor="w")

        self.defter = ttk.Notebook(self)
        self.defter.pack(fill="both", expand=True, padx=10)
        self.kapatan_sayfa = ttk.Frame(self.defter, padding=4)
        cerceve, self.kapatan_tablo = _tablo(self.kapatan_sayfa, KAPATAN_KOLONLARI, height=10)
        cerceve.pack(fill="both", expand=True)
        self.kapatan_tablo.bind("<Double-1>", lambda _e: self.secili_evraki_ac())
        self.defter.add(self.kapatan_sayfa, text="Bu Evrakı Kapatanlar")
        self.kaynak_sayfa = ttk.Frame(self.defter, padding=4)
        self.kaynak_panel = None
        self.iptal_sayfa = ttk.Frame(self.defter, padding=4)
        cerceve, self.iptal_tablo = _tablo(self.iptal_sayfa, IPTAL_KOLONLARI, height=10)
        cerceve.pack(fill="both", expand=True)
        self.defter.add(self.iptal_sayfa, text="İptal / Geri Alınan Geçmiş")

        alt = ttk.Frame(self, padding=(10, 8))
        alt.pack(fill="x")
        ttk.Label(
            alt,
            text="Kayıtlar salt okunurdur; yeniden dağıtım ayrı onaylı işlemle yapılır.",
            foreground="#666666",
        ).pack(side="left")
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Yenile", command=self.yenile).pack(side="right", padx=4)
        ttk.Button(alt, text="Evrakı Aç", command=self.secili_evraki_ac).pack(side="right", padx=4)
        self.bind("<Escape>", lambda _e: self.destroy())
        self.yenile()

    def yenile(self):
        try:
            veri = evrak_kapatma_detayi(self.belge_no, self.cari_id)
        except Exception as hata:
            messagebox.showerror("Kapatma Detayı", str(hata), parent=self)
            return
        self.cari_id = veri.get("cari_id") or self.cari_id
        self.baslik_lbl.configure(text=f"{veri['evrak_turu'] or 'Evrak'}  {self.belge_no}")
        if veri["taslak"]:
            ozet = f"Toplam: {_para(veri['esas_tutar'])}  |  Durum: Taslak"
        elif veri["esas_tutar"] > 0:
            ozet = (
                f"Toplam: {_para(veri['esas_tutar'])} {veri['para_birimi']}  |  "
                f"Kapanan: {_para(veri['kapanan'])}  |  Kalan: {_para(veri['kalan'])}  |  "
                f"Ödeme Durumu: {veri['odeme_durumu'] or '-'}"
            )
        else:
            ozet = ""
        self.ozet_lbl.configure(text=ozet)
        self.mesaj_lbl.configure(text=veri["mesaj"] or "")
        self.uyari_lbl.configure(text=("⚠ " + veri["uyari"]) if veri["uyari"] else "")

        self.kapatan_tablo.delete(*self.kapatan_tablo.get_children())
        self._kapatan_satirlari.clear()
        for i, s in enumerate(veri["kapatanlar"]):
            iid = str(i)
            self._kapatan_satirlari[iid] = s
            etiket = "bilinmiyor" if s["kaynak"] == "BILINMIYOR" else ("eski" if s["kaynak"] != "KAYIT" else "")
            self.kapatan_tablo.insert(
                "",
                "end",
                iid=iid,
                tags=(etiket,) if etiket else (),
                values=(
                    _tarih(s["tarih"]),
                    s["evrak_turu"],
                    s["evrak_no"],
                    _para(s["pay"]),
                    _para(s["evrak_toplami"]),
                    s["para_birimi"],
                    s["tur"],
                    s["hesap"],
                    s["yontem"],
                ),
            )

        kaynak = veri.get("kaynak")
        if kaynak and self.cari_id:
            if self.kaynak_panel is None:
                self.kaynak_panel = KapatilanBorclarPaneli(
                    self.kaynak_sayfa, self.belge_no, int(self.cari_id), height=10
                )
                self.kaynak_panel.pack(fill="both", expand=True)
                self.defter.insert(1, self.kaynak_sayfa, text="Bu Evrakın Kapattıkları")
            else:
                self.kaynak_panel.yenile()
            if not veri["kapatanlar"] and veri["esas_tutar"] <= 0:
                self.defter.select(self.kaynak_sayfa)

        self.iptal_tablo.delete(*self.iptal_tablo.get_children())
        iptaller = list(veri["iptaller"]) + list((kaynak or {}).get("iptaller") or [])
        for i, s in enumerate(iptaller):
            self.iptal_tablo.insert(
                "",
                "end",
                iid=str(i),
                values=(
                    _zaman(s["iptal_zamani"]),
                    s["kullanici"],
                    s["neden"],
                    s["evrak_no"],
                    _para(s["tutar"]),
                    _tarih(s["islem_tarihi"]),
                    s["tur"],
                ),
            )

    def secili_evraki_ac(self):
        try:
            aktif = self.defter.select()
        except tk.TclError:
            aktif = ""
        if self.kaynak_panel is not None and aktif == str(self.kaynak_sayfa):
            self.kaynak_panel.secili_evraki_ac()
            return
        secim = self.kapatan_tablo.selection()
        if not secim:
            messagebox.showinfo("Evrak", "Açılacak satırı seçin.", parent=self)
            return
        s = self._kapatan_satirlari.get(secim[0]) or {}
        if s.get("kaynak") == "BILINMIYOR":
            messagebox.showinfo(
                "Evrak", f"{BILINMIYOR}: eski kayıtta bu payın hangi evraktan geldiği tutulmamış.", parent=self
            )
            return
        evraki_ac(self, s.get("ac_tur") or "", s.get("belge_no") or s.get("evrak_no") or "")
        self.yenile()


def kapatma_detayi_ac(parent, belge_no: str, cari_id: int | None = None) -> None:
    if not (belge_no or "").strip():
        messagebox.showinfo("Kapatma Detayı", "Önce evrakı kaydedin.", parent=parent)
        return
    onceki_grab = None
    try:
        onceki_grab = parent.grab_current()
    except tk.TclError:
        pass
    dialog = KapatmaDetayDialog(parent, belge_no, cari_id)
    try:
        dialog.grab_set()
    except tk.TclError:
        pass
    parent.wait_window(dialog)
    if onceki_grab is not None:
        try:
            if onceki_grab.winfo_exists():
                onceki_grab.grab_set()
        except tk.TclError:
            pass


class OdemeKapatmaBilgisi(ttk.Frame):
    """Fatura ekranı alt satırı: Ödeme ve Kapatma Bilgisi + Kapatma Detayı düğmesi.

    Dar ekranda yatay kaydırılabilir; satır düzenleme alanlarıyla etkileşmez.
    """

    def __init__(self, parent, *, fatura_turu: str = "SATIS", fatura_id_getir=None):
        super().__init__(parent)
        self.fatura_turu = fatura_turu
        self._fatura_id_getir = fatura_id_getir or (lambda: None)
        self._ozet = None
        self._tuval = tk.Canvas(self, height=30, highlightthickness=0, bd=0)
        self._tuval.pack(side="top", fill="x", expand=True)
        self._kaydirma = ttk.Scrollbar(self, orient="horizontal", command=self._tuval.xview)
        self._tuval.configure(xscrollcommand=self._kaydirma_ayarla)
        self.ic = ttk.Frame(self._tuval)
        self._pencere = self._tuval.create_window((0, 0), window=self.ic, anchor="nw")
        ttk.Label(self.ic, text="Ödeme ve Kapatma Bilgisi:", font=("Segoe UI", 9, "bold")).pack(
            side="left", padx=(0, 8)
        )
        self.lbl = ttk.Label(self.ic, text="", font=("Segoe UI", 9))
        self.lbl.pack(side="left")
        ttk.Button(self.ic, text="Kapatma Detayı", command=self.detay_ac).pack(side="left", padx=(10, 0))
        self.ic.bind("<Configure>", self._boyut)
        self._tuval.bind("<Configure>", self._boyut)

    def _kaydirma_ayarla(self, bas, son):
        self._kaydirma.set(bas, son)
        try:
            if float(bas) <= 0.0 and float(son) >= 1.0:
                self._kaydirma.pack_forget()
            elif not self._kaydirma.winfo_ismapped():
                self._kaydirma.pack(side="top", fill="x")
        except (tk.TclError, ValueError):
            pass

    def _boyut(self, _e=None):
        try:
            self._tuval.configure(scrollregion=self._tuval.bbox("all"), height=self.ic.winfo_reqheight())
        except tk.TclError:
            pass

    def yenile(self):
        fid = self._fatura_id_getir()
        if not fid:
            self._ozet = None
            self.lbl.configure(text="Fatura kaydedilmedi — Henüz cari borç oluşmadı")
            return
        try:
            oz = fatura_odeme_ozeti(int(fid), self.fatura_turu)
        except Exception as hata:
            self._ozet = None
            self.lbl.configure(text=f"Okunamadı: {hata}")
            return
        self._ozet = oz
        if oz["taslak"]:
            metin = f"Toplam {_para(oz['toplam'])}  |  Henüz cari borç oluşmadı (taslak)"
        elif oz["iptal"]:
            metin = "Evrak iptal edildi"
        else:
            metin = (
                f"Toplam {_para(oz['toplam'])}  |  Kapanan {_para(oz['kapanan'])}  |  "
                f"Kalan {_para(oz['kalan'])}  |  Durum: {oz['durum'] or '-'}"
            )
            if not oz["tutarli"]:
                metin += "  |  ⚠ Tutarsızlık (Kapatma Detayı)"
        self.lbl.configure(text=metin)

    def detay_ac(self):
        oz = self._ozet
        if not oz:
            self.yenile()
            oz = self._ozet
        if not oz:
            messagebox.showinfo("Kapatma Detayı", "Önce faturayı kaydedin.", parent=self.winfo_toplevel())
            return
        kapatma_detayi_ac(self.winfo_toplevel(), oz["belge_no"], oz["cari_id"])
        self.yenile()
