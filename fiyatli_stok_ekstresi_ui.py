"""Fiyatlı Stok Ekstresi — Tkinter arayüzü (stok kartı + Stok Raporları)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

from database.fiyatli_stok_ekstresi_service import FiyatliStokEkstreService
from database.stok_service import CIKIS_HAREKETLERI, GIRIS_HAREKETLERI, StokService
from ui_takvim import takvim_butonu

_KOLONLAR = (
    "tarih",
    "saat",
    "tur",
    "belge_turu",
    "belge_no",
    "cari_kodu",
    "cari_adi",
    "depo",
    "etiket",
    "giren",
    "net_giris",
    "cikan",
    "net_cikis",
    "kalan",
    "fifo_kalan",
    "cikis_mf",
    "giris_t",
    "cikis_t",
    "cikis_mal",
    "pb",
    "kur",
    "uyari",
)

_BASLIKLAR = (
    "Tarih",
    "Saat",
    "Hareket",
    "Belge Türü",
    "Belge No",
    "Cari Kodu",
    "Cari Kart Adı",
    "Depo",
    "Etiket",
    "Giriş Miktarı",
    "Net Giriş Birim Fiyatı",
    "Çıkış Miktarı",
    "Net Çıkış Birim Fiyatı",
    "Kalan Miktar",
    "FIFO Kalan Değeri",
    "Çıkış Maliyet F.",
    "Giriş Tutarı",
    "Çıkış Tutarı",
    "Çıkış Maliyeti",
    "PB",
    "Kur",
    "Uyarı",
)

_GENISLIKLER = (
    85,
    70,
    110,
    100,
    100,
    80,
    150,
    90,
    80,
    85,
    120,
    85,
    120,
    85,
    110,
    95,
    90,
    90,
    95,
    45,
    55,
    140,
)

_SAYISAL = {
    "giren",
    "net_giris",
    "cikan",
    "net_cikis",
    "kalan",
    "fifo_kalan",
    "cikis_mf",
    "giris_t",
    "cikis_t",
    "cikis_mal",
    "kur",
}

_BELGE_KOLONLARI = {"belge_turu", "belge_no"}
_CARI_KOLONLARI = {"cari_kodu", "cari_adi"}


def _para(tutar) -> str:
    if tutar is None:
        return ""
    try:
        return f"{float(tutar):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return ""


def _mik(deger) -> str:
    if deger is None:
        return ""
    try:
        d = Decimal(str(deger))
    except Exception:
        return ""
    if d == 0:
        return ""
    if d == d.to_integral_value():
        return str(int(d))
    return (
        f"{float(d):,.4f}".replace(",", "X").replace(".", ",").replace("X", ".")
        .rstrip("0")
        .rstrip(",")
    )


def _tarih_goster(t) -> str:
    if not t:
        return ""
    if isinstance(t, str):
        return t
    return t.strftime("%d.%m.%Y")


def _tarih_oku(entry, zorunlu=False):
    metin = (entry.get() or "").strip()
    if not metin:
        if zorunlu:
            raise ValueError("Tarih zorunludur.")
        return None
    return datetime.strptime(metin, "%d.%m.%Y").date()


def _belge_ac(parent, belge_no: str, hareket_turu: str) -> bool:
    """StokService.belge_bul + stok_ui._hareket_evrak_ac benzeri açılış. True = belge açıldı."""
    bulunan = StokService.belge_bul(belge_no, hareket_turu)
    if not bulunan:
        messagebox.showinfo(
            "Evrak",
            f"{hareket_turu} / {belge_no} için açılabilir evrak bulunamadı.",
            parent=parent,
        )
        return False
    tur, kimlik = bulunan
    try:
        if tur == "satis_fatura":
            from app import CariDialog, SatisFaturasiDialog
            from database.satis_faturasi_service import SatisFaturasiService

            fatura = SatisFaturasiService.getir(kimlik)
            if not fatura:
                raise ValueError("Satış faturası bulunamadı.")
            dialog = SatisFaturasiDialog(
                parent, fatura=fatura, cari_ac=lambda cari: CariDialog(parent, cari)
            )
            parent.wait_window(dialog)
        elif tur == "alis_fatura":
            from alis_ui import AlisFaturasiDialog
            from app import CariDialog
            from database.alis_faturasi_service import AlisFaturasiService

            fatura = AlisFaturasiService.getir(kimlik)
            if not fatura:
                raise ValueError("Alış faturası bulunamadı.")
            dialog = AlisFaturasiDialog(
                parent,
                fatura=fatura,
                cari_ac=lambda c: CariDialog(parent, c, cari_turu="Tedarikçi"),
            )
            parent.wait_window(dialog)
        elif tur == "satis_iade":
            from app import SatisIadeFaturasiDialog
            from database.satis_iade_faturasi_service import SatisIadeFaturasiService

            iade = SatisIadeFaturasiService.getir(kimlik)
            if not iade:
                raise ValueError("Satış iade faturası bulunamadı.")
            dialog = SatisIadeFaturasiDialog(parent, iade=iade)
            parent.wait_window(dialog)
        elif tur == "alis_iade":
            from alis_ui import AlisIadeFaturasiDialog
            from database.alis_iade_faturasi_service import AlisIadeFaturasiService

            iade = AlisIadeFaturasiService.getir(kimlik)
            if not iade:
                raise ValueError("Alış iade faturası bulunamadı.")
            dialog = AlisIadeFaturasiDialog(parent, iade=iade)
            parent.wait_window(dialog)
        elif tur == "stok_giris":
            messagebox.showinfo(
                "Stok girişi",
                f"Bu hareket manuel stok girişidir.\nBelge / Lot: {kimlik}",
                parent=parent,
            )
            return False
        else:
            messagebox.showinfo(
                "Evrak",
                f"Bu belge türü ({tur}) için açılış tanımlı değil.",
                parent=parent,
            )
            return False
    except ValueError as hata:
        messagebox.showerror("Evrak açılamadı", str(hata), parent=parent)
        return False
    return True


def _cari_ac(parent, cari_id) -> None:
    if not cari_id:
        messagebox.showinfo("Cari", "Bu satırda cari bağlantısı yok.", parent=parent)
        return
    try:
        from cari_kart_ui import CariDialog
        from database.cari_service import CariService

        cari = CariService.getir(int(cari_id))
        if not cari:
            messagebox.showwarning("Cari", "Cari kartı bulunamadı.", parent=parent)
            return
        dialog = CariDialog(parent, cari=cari)
        parent.wait_window(dialog)
    except Exception as exc:
        messagebox.showerror("Cari", f"Cari kartı açılamadı: {exc}", parent=parent)


class _FiyatliEkstrePanel(ttk.Frame):
    """Filtre + özet + tablo — hem diyalog hem rapor gövdesinde kullanılır."""

    def __init__(self, master, *, host, stok_id=None, pad=(8, 4)):
        super().__init__(master)
        self.host = host  # wait_window / messagebox parent
        self._stok_id = int(stok_id) if stok_id else None
        self._sonuc = None
        self._satir_meta: dict[str, dict] = {}
        self._evrak_aciliyor = False
        self._ozet_etiketleri: dict[str, ttk.Label] = {}
        self._maliyet_cerceveleri: list[ttk.Frame] = []
        self.pack(fill="both", expand=True, padx=pad[0], pady=pad[1])
        self._kur()
        if self._stok_id:
            self.yenile()

    def _kur(self):
        vb, ve = FiyatliStokEkstreService.varsayilan_tarih_araligi()

        stok_satir = ttk.Frame(self)
        stok_satir.pack(fill="x", pady=(0, 4))
        ttk.Label(stok_satir, text="Stok:").pack(side="left")
        self.stok_kodu = ttk.Entry(stok_satir, width=14)
        self.stok_kodu.pack(side="left", padx=4)
        self.stok_adi = ttk.Entry(stok_satir, width=36)
        self.stok_adi.pack(side="left", padx=4)
        self._stok_sec_btn = ttk.Button(stok_satir, text="Stok Seç", command=self._stok_sec)
        self._stok_sec_btn.pack(side="left", padx=4)
        if self._stok_id:
            stok = StokService.stok_getir(self._stok_id)
            if stok:
                self.stok_kodu.insert(0, stok.stok_kodu or "")
                self.stok_adi.insert(0, stok.stok_adi or "")
            self.stok_kodu.configure(state="readonly")
            self.stok_adi.configure(state="readonly")
            self._stok_sec_btn.configure(state="disabled")
        else:
            self.stok_adi.configure(state="readonly")
            self.stok_kodu.bind("<Return>", lambda _e: self._stok_kodundan_yukle())

        filtre = ttk.Frame(self)
        filtre.pack(fill="x", pady=2)
        ttk.Label(filtre, text="Başlangıç:").pack(side="left")
        b_c = ttk.Frame(filtre)
        b_c.pack(side="left")
        self.baslangic = ttk.Entry(b_c, width=11)
        self.baslangic.pack(side="left")
        self.baslangic.insert(0, _tarih_goster(vb))
        takvim_butonu(b_c, self.baslangic)

        ttk.Label(filtre, text="Bitiş:").pack(side="left", padx=(8, 0))
        e_c = ttk.Frame(filtre)
        e_c.pack(side="left")
        self.bitis = ttk.Entry(e_c, width=11)
        self.bitis.pack(side="left")
        self.bitis.insert(0, _tarih_goster(ve))
        takvim_butonu(e_c, self.bitis)

        depolar = ["Tüm Depolar"] + [d.ad for d in StokService.depolar()]
        ttk.Label(filtre, text="Depo:").pack(side="left", padx=(8, 2))
        self.depo = ttk.Combobox(filtre, values=depolar, state="readonly", width=14)
        self.depo.set("Tüm Depolar")
        self.depo.pack(side="left")

        filtre2 = ttk.Frame(self)
        filtre2.pack(fill="x", pady=2)
        turler = ["(Tümü)"] + sorted(set(GIRIS_HAREKETLERI + CIKIS_HAREKETLERI))
        ttk.Label(filtre2, text="Hareket:").pack(side="left")
        self.hareket_turu = ttk.Combobox(filtre2, values=turler, state="readonly", width=16)
        self.hareket_turu.set("(Tümü)")
        self.hareket_turu.pack(side="left", padx=4)

        ttk.Label(filtre2, text="Belge No:").pack(side="left", padx=(8, 2))
        self.belge_no = ttk.Entry(filtre2, width=12)
        self.belge_no.pack(side="left")

        ttk.Label(filtre2, text="Para:").pack(side="left", padx=(8, 2))
        self.para_birimi = ttk.Combobox(
            filtre2, values=["Tümü", "TRY"], state="readonly", width=8
        )
        self.para_birimi.set("Tümü")
        self.para_birimi.pack(side="left")

        self.kdv_dahil = tk.BooleanVar(value=False)
        ttk.Checkbutton(filtre2, text="KDV dahil", variable=self.kdv_dahil).pack(
            side="left", padx=(10, 0)
        )

        dugmeler = ttk.Frame(self)
        dugmeler.pack(fill="x", pady=(4, 4))
        ttk.Button(dugmeler, text="Yenile", command=self.yenile).pack(side="left")
        ttk.Button(dugmeler, text="Filtreyi Temizle", command=self.filtre_temizle).pack(
            side="left", padx=4
        )
        ttk.Button(dugmeler, text="Belgeyi Aç", command=self.belgeyi_ac).pack(side="left", padx=4)
        ttk.Button(dugmeler, text="Cari Kartı Aç", command=self.cari_ac).pack(side="left", padx=4)
        ttk.Button(dugmeler, text="Excel", command=self.excel_aktar).pack(side="left", padx=(12, 4))
        ttk.Button(dugmeler, text="PDF", command=self.pdf_aktar).pack(side="left")

        ozet = ttk.Frame(self)
        ozet.pack(fill="x", pady=(2, 6))
        miktar_kartlari = (
            ("devir_miktar", "Devir Miktarı"),
            ("giren_miktar", "Giren"),
            ("cikan_miktar", "Çıkan"),
            ("kalan_miktar", "Kalan"),
        )
        maliyet_kartlari = (
            ("devir_degeri", "Devir Değeri"),
            ("giris_tutari", "Giriş Tutarı"),
            ("cikis_maliyeti", "Çıkış Maliyeti"),
            ("kalan_stok_degeri", "Kalan Stok Değeri"),
        )
        for anahtar, baslik in miktar_kartlari:
            self._ozet_karti_ekle(ozet, anahtar, baslik, maliyet=False)
        for anahtar, baslik in maliyet_kartlari:
            self._ozet_karti_ekle(ozet, anahtar, baslik, maliyet=True)

        tablo_cer = ttk.Frame(self)
        tablo_cer.pack(fill="both", expand=True)
        self.tablo = ttk.Treeview(tablo_cer, columns=_KOLONLAR, show="headings", selectmode="browse")
        for kolon, baslik, w in zip(_KOLONLAR, _BASLIKLAR, _GENISLIKLER):
            ank = "e" if kolon in _SAYISAL else "w"
            self.tablo.heading(kolon, text=baslik, anchor=ank)
            self.tablo.column(kolon, width=w, anchor=ank, minwidth=40)
        dy = ttk.Scrollbar(tablo_cer, orient="vertical", command=self.tablo.yview)
        dx = ttk.Scrollbar(tablo_cer, orient="horizontal", command=self.tablo.xview)
        self.tablo.configure(yscrollcommand=dy.set, xscrollcommand=dx.set)
        self.tablo.grid(row=0, column=0, sticky="nsew")
        dy.grid(row=0, column=1, sticky="ns")
        dx.grid(row=1, column=0, sticky="ew")
        tablo_cer.rowconfigure(0, weight=1)
        tablo_cer.columnconfigure(0, weight=1)

        self.tablo.tag_configure("giris", foreground="#B71C1C")
        self.tablo.tag_configure("cikis", foreground="#1B5E20")
        self.tablo.tag_configure("notr", foreground="#627D98")
        self.tablo.tag_configure("devri", background="#1E3A5F", foreground="white")
        self.tablo.bind("<Double-1>", self._cift_tikla)

        self.durum = ttk.Label(self, text="Stok seçip Yenile ile ekstreyi getirin.")
        self.durum.pack(anchor="w", pady=(4, 0))

    def _ozet_karti_ekle(self, parent, anahtar: str, baslik: str, *, maliyet: bool):
        cer = ttk.Frame(parent, padding=(8, 4))
        cer.pack(side="left", padx=4)
        ttk.Label(cer, text=baslik, foreground="#546E7A").pack(anchor="w")
        lbl = ttk.Label(cer, text="—", font=("Segoe UI", 10, "bold"))
        lbl.pack(anchor="w")
        self._ozet_etiketleri[anahtar] = lbl
        if maliyet:
            self._maliyet_cerceveleri.append(cer)

    def _stok_sec(self):
        win = tk.Toplevel(self.host)
        win.title("Stok Seç")
        win.geometry("560x400")
        win.transient(self.host)
        win.grab_set()
        ara = ttk.Entry(win)
        ara.pack(fill="x", padx=8, pady=8)
        lb = tk.Listbox(win)
        lb.pack(fill="both", expand=True, padx=8)
        map_s: dict[str, object] = {}

        def doldur(*_a):
            lb.delete(0, "end")
            map_s.clear()
            for stok in StokService.stoklari_ara(ara.get().strip()):
                et = f"{stok.stok_kodu} — {stok.stok_adi}"
                lb.insert("end", et)
                map_s[et] = stok

        def tamam(_e=None):
            sel = lb.curselection()
            if not sel:
                return
            stok = map_s[lb.get(sel[0])]
            self._stok_id = int(stok.id)
            self.stok_kodu.configure(state="normal")
            self.stok_kodu.delete(0, "end")
            self.stok_kodu.insert(0, stok.stok_kodu or "")
            self.stok_adi.configure(state="normal")
            self.stok_adi.delete(0, "end")
            self.stok_adi.insert(0, stok.stok_adi or "")
            self.stok_adi.configure(state="readonly")
            win.destroy()
            self.yenile()

        ara.bind("<KeyRelease>", doldur)
        lb.bind("<Double-1>", tamam)
        doldur()
        ttk.Button(win, text="Seç", command=tamam).pack(pady=8)

    def _stok_kodundan_yukle(self):
        kod = (self.stok_kodu.get() or "").strip()
        if not kod:
            return
        bulunan = StokService.stok_kodu_onerileri(kod, limit=5)
        eslesen = next((s for s in bulunan if (s.stok_kodu or "").casefold() == kod.casefold()), None)
        if eslesen is None and len(bulunan) == 1:
            eslesen = bulunan[0]
        if not eslesen:
            messagebox.showwarning("Stok", f"«{kod}» kodlu stok bulunamadı.", parent=self.host)
            return
        self._stok_id = int(eslesen.id)
        self.stok_kodu.delete(0, "end")
        self.stok_kodu.insert(0, eslesen.stok_kodu or "")
        self.stok_adi.configure(state="normal")
        self.stok_adi.delete(0, "end")
        self.stok_adi.insert(0, eslesen.stok_adi or "")
        self.stok_adi.configure(state="readonly")
        self.yenile()

    def filtre_temizle(self):
        vb, ve = FiyatliStokEkstreService.varsayilan_tarih_araligi()
        self.baslangic.delete(0, "end")
        self.baslangic.insert(0, _tarih_goster(vb))
        self.bitis.delete(0, "end")
        self.bitis.insert(0, _tarih_goster(ve))
        self.depo.set("Tüm Depolar")
        self.hareket_turu.set("(Tümü)")
        self.belge_no.delete(0, "end")
        self.para_birimi.set("Tümü")
        self.kdv_dahil.set(False)
        if self._stok_id:
            self.yenile()

    def yenile(self):
        if not self._stok_id:
            kod = (self.stok_kodu.get() or "").strip()
            if kod:
                self._stok_kodundan_yukle()
                return
            messagebox.showwarning("Stok", "Önce stok seçin.", parent=self.host)
            return
        try:
            bas = _tarih_oku(self.baslangic, zorunlu=True)
            bit = _tarih_oku(self.bitis, zorunlu=True)
        except ValueError:
            messagebox.showerror("Tarih", "Tarihleri gg.aa.yyyy formatında girin.", parent=self.host)
            return
        depo_adi = self.depo.get()
        if depo_adi in ("", "Tüm Depolar", "(Tümü)"):
            depo_adi = None
        hareket = self.hareket_turu.get()
        if hareket in ("", "(Tümü)"):
            hareket = None
        pb = self.para_birimi.get()
        if pb in ("", "Tümü"):
            pb = None
        try:
            sonuc = FiyatliStokEkstreService.ekstre(
                self._stok_id,
                baslangic=bas,
                bitis=bit,
                depo_adi=depo_adi,
                hareket_turu=hareket,
                belge_no=(self.belge_no.get() or "").strip() or None,
                para_birimi=pb,
                kdv_dahil=bool(self.kdv_dahil.get()),
            )
        except ValueError as hata:
            messagebox.showerror("Ekstre", str(hata), parent=self.host)
            return
        except Exception as exc:
            messagebox.showerror("Ekstre", f"Ekstre hesaplanamadı: {exc}", parent=self.host)
            return

        self._sonuc = sonuc
        self._tabloyu_doldur(sonuc)
        self._ozeti_guncelle(sonuc)
        uyarilar = sonuc.get("uyarilar") or []
        ekstra = f"  ·  {len(uyarilar)} uyarı" if uyarilar else ""
        self.durum.configure(
            text=(
                f"{sonuc.get('stok_kodu')} — {sonuc.get('stok_adi')}  ·  "
                f"{len(sonuc.get('satirlar') or [])} satır  ·  "
                f"Maliyet: {sonuc.get('maliyet_yontemi')}{ekstra}"
            )
        )

    def _ozeti_guncelle(self, sonuc: dict):
        ozet = sonuc.get("ozet") or {}
        maliyet_ok = bool(sonuc.get("maliyet_gorunur"))
        for cer in self._maliyet_cerceveleri:
            if maliyet_ok:
                cer.pack(side="left", padx=4)
            else:
                cer.pack_forget()
        miktar_anahtar = ("devir_miktar", "giren_miktar", "cikan_miktar", "kalan_miktar")
        for anahtar, lbl in self._ozet_etiketleri.items():
            deger = ozet.get(anahtar)
            if anahtar in miktar_anahtar:
                lbl.configure(text=_mik(deger) or "0")
            else:
                lbl.configure(text=_para(deger) if deger is not None else "—")

    def _tabloyu_doldur(self, sonuc: dict):
        for item in self.tablo.get_children():
            self.tablo.delete(item)
        self._satir_meta.clear()
        maliyet_ok = bool(sonuc.get("maliyet_gorunur"))
        for sira, s in enumerate(sonuc.get("satirlar") or []):
            yon = s.get("yon") or "notr"
            tag = "devri" if yon == "devri" or s.get("satir_turu") == "devri" else yon
            iid = f"r{sira}"
            self._satir_meta[iid] = s
            cikis_mf = _para(s.get("cikis_maliyet_fiyat")) if maliyet_ok else ""
            giris_t = _para(s.get("giris_tutari")) if maliyet_ok else ""
            cikis_mal = _para(s.get("cikis_maliyeti")) if maliyet_ok else ""
            fifo_kalan = _para(s.get("kalan_deger")) if maliyet_ok else ""
            net_g = s.get("net_giris_birim_fiyat", s.get("giris_birim_fiyat"))
            net_c = s.get("net_cikis_birim_fiyat", s.get("cikis_satis_fiyat"))
            fiyat_yok = bool(s.get("fiyat_yok"))
            net_g_txt = _para(net_g) if net_g is not None else (
                "Fiyat yok" if fiyat_yok and yon == "giris" else ""
            )
            net_c_txt = _para(net_c) if net_c is not None else (
                "Fiyat yok" if fiyat_yok and yon == "cikis" else ""
            )
            self.tablo.insert(
                "",
                "end",
                iid=iid,
                values=(
                    _tarih_goster(s.get("tarih")),
                    s.get("saat") or "",
                    s.get("hareket_turu") or "",
                    s.get("belge_turu") or "",
                    s.get("belge_no") or "",
                    s.get("cari_kodu") or "",
                    s.get("cari_adi") or "",
                    s.get("depo") or "",
                    s.get("etiket") or "",
                    _mik(s.get("giren")),
                    net_g_txt,
                    _mik(s.get("cikan")),
                    net_c_txt,
                    _mik(s.get("kalan")),
                    fifo_kalan,
                    cikis_mf,
                    giris_t,
                    _para(s.get("cikis_tutari")),
                    cikis_mal,
                    s.get("para_birimi") or "",
                    _para(s.get("kur")) if s.get("kur") is not None else "",
                    s.get("uyari") or s.get("fiyat_kaynak") or "",
                ),
                tags=(tag,),
            )

    def _secili_satir(self) -> dict | None:
        secim = self.tablo.selection()
        if not secim:
            return None
        return self._satir_meta.get(secim[0])

    def _cift_tikla(self, event):
        if self._evrak_aciliyor:
            return
        bolge = self.tablo.identify_region(event.x, event.y)
        if bolge != "cell":
            return
        satir = self.tablo.identify_row(event.y)
        kolon_id = self.tablo.identify_column(event.x)
        if not satir or not kolon_id:
            return
        try:
            kolon_idx = int(kolon_id.replace("#", "")) - 1
        except ValueError:
            return
        if kolon_idx < 0 or kolon_idx >= len(_KOLONLAR):
            return
        kolon = _KOLONLAR[kolon_idx]
        meta = self._satir_meta.get(satir)
        if not meta:
            return
        self.tablo.selection_set(satir)
        if kolon in _BELGE_KOLONLARI:
            self._belge_ac_meta(meta)
        elif kolon in _CARI_KOLONLARI:
            if meta.get("cari_id"):
                _cari_ac(self.host, meta.get("cari_id"))
            else:
                messagebox.showinfo("Cari", "Bu satırda cari bağlantısı yok.", parent=self.host)

    def _belge_ac_meta(self, meta: dict):
        if self._evrak_aciliyor:
            return
        belge_no = (meta.get("belge_no") or "").strip()
        tur = (meta.get("hareket_turu") or "").strip()
        if not belge_no or tur in ("DEVRİ", ""):
            messagebox.showinfo("Evrak", "Bu satırda açılabilir belge yok.", parent=self.host)
            return
        self._evrak_aciliyor = True
        try:
            acildi = _belge_ac(self.host, belge_no, tur)
            if acildi:
                messagebox.showinfo(
                    "Yenile",
                    "Belge açıldı. Değişiklikleri görmek için Yenile düğmesine basın.",
                    parent=self.host,
                )
        finally:
            self._evrak_aciliyor = False

    def belgeyi_ac(self):
        meta = self._secili_satir()
        if not meta:
            messagebox.showinfo("Belge", "Önce bir satır seçin.", parent=self.host)
            return
        self._belge_ac_meta(meta)

    def cari_ac(self):
        meta = self._secili_satir()
        if not meta:
            messagebox.showinfo("Cari", "Önce bir satır seçin.", parent=self.host)
            return
        _cari_ac(self.host, meta.get("cari_id"))

    def excel_aktar(self):
        if not self._sonuc:
            messagebox.showwarning("Excel", "Önce ekstreyi getirin.", parent=self.host)
            return
        yol = filedialog.asksaveasfilename(
            parent=self.host,
            title="Excel olarak kaydet",
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx"), ("Tüm dosyalar", "*.*")],
            initialfile=f"fiyatli_stok_ekstresi_{self._sonuc.get('stok_kodu') or 'stok'}.xlsx",
        )
        if not yol:
            return
        try:
            FiyatliStokEkstreService.excel_aktar(self._sonuc, yol)
            messagebox.showinfo("Excel", f"Dosya kaydedildi:\n{yol}", parent=self.host)
        except Exception as exc:
            messagebox.showerror("Excel", f"Aktarım başarısız: {exc}", parent=self.host)

    def pdf_aktar(self):
        if not self._sonuc:
            messagebox.showwarning("PDF", "Önce ekstreyi getirin.", parent=self.host)
            return
        yol = filedialog.asksaveasfilename(
            parent=self.host,
            title="PDF olarak kaydet",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf"), ("Tüm dosyalar", "*.*")],
            initialfile=f"fiyatli_stok_ekstresi_{self._sonuc.get('stok_kodu') or 'stok'}.pdf",
        )
        if not yol:
            return
        try:
            FiyatliStokEkstreService.pdf_aktar(self._sonuc, yol)
            messagebox.showinfo("PDF", f"Dosya kaydedildi:\n{yol}", parent=self.host)
        except Exception as exc:
            messagebox.showerror("PDF", f"Aktarım başarısız: {exc}", parent=self.host)


class FiyatliStokEkstreDialog(tk.Toplevel):
    """Stok kartından açılan fiyatlı ekstre penceresi."""

    def __init__(self, parent, stok_id=None):
        super().__init__(parent)
        self._stok_id = int(stok_id) if stok_id else None
        baslik = "Fiyatlı Stok Ekstresi"
        if self._stok_id:
            stok = StokService.stok_getir(self._stok_id)
            if stok:
                baslik = f"Fiyatlı Stok Ekstresi — {stok.stok_kodu} / {stok.stok_adi}"
        self.title(baslik)
        self.geometry("1280x720")
        self.minsize(980, 520)
        self.transient(parent)
        try:
            self.grab_set()
        except tk.TclError:
            pass
        ust = ttk.Frame(self, padding=(10, 8, 10, 0))
        ust.pack(fill="x")
        ttk.Label(ust, text="FİYATLI STOK EKSTRESİ", font=("Segoe UI", 12, "bold")).pack(
            side="left"
        )
        ttk.Button(ust, text="Kapat", command=self.destroy).pack(side="right")
        self.panel = _FiyatliEkstrePanel(self, host=self, stok_id=self._stok_id, pad=(10, 6))

    @property
    def _sonuc(self):
        return getattr(self.panel, "_sonuc", None)


def fiyatli_stok_ekstresi_goster(app, stok_id=None):
    """Stok Raporları hub'ından gömülü rapor ekranı."""
    from stok_rapor_ui import _rapor_ust

    _rapor_ust(app, "FİYATLI STOK EKSTRESİ")
    panel = _FiyatliEkstrePanel(app.icerik, host=app, stok_id=stok_id, pad=(0, 4))
    # Rapor gövdesinde sonuca dışarıdan erişim için
    app._fiyatli_ekstre_panel = panel
