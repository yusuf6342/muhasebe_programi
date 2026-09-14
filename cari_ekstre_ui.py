"""Stok detaylı cari hesap ekstresi — fatura satırları açıklama altında."""

from __future__ import annotations

import html
import os
import tempfile
import webbrowser
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

from database.rapor_service import RaporService
from ui_takvim import takvim_butonu

STOKLU_TURLER = (
    "Satış Faturası",
    "Alış Faturası",
    "Satış İadesi",
    "Alış İadesi",
)

# Fatura içi (yalnız Açıklama hücresi): Kod | Ad | Miktar | Birim | Net Fiyat | Tutar
STOK_ACIKLAMA_BASLIK = ("Kod", "Ürün Adı", "Miktar", "Birim", "Net Fiyat", "Tutar")

# Monospace pad — fatura içi 6 alan Açıklama içinde
_STOK_PAD = {
    "kod": 10,
    "urun": 28,
    "miktar": 8,
    "birim": 6,
    "fiyat": 12,
    "tutar": 12,
}
_STOK_SEP = "  "
_STOK_SATIR_LEN = sum(_STOK_PAD.values()) + len(_STOK_SEP) * (len(_STOK_PAD) - 1)
_STOK_MONO = ("Consolas", "Cascadia Mono", "Courier New")


def _para(tutar) -> str:
    if tutar is None:
        return ""
    d = Decimal(str(tutar))
    if d == 0:
        return ""
    return f"{float(d):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _para_zorunlu(tutar) -> str:
    """Sıfır dahil göster (başlık satırı değil, satır tutarları için)."""
    d = Decimal(str(tutar or 0))
    return f"{float(d):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _miktar(deger) -> str:
    d = Decimal(str(deger or 0))
    if d == d.to_integral_value():
        return str(int(d))
    return f"{float(d):,.3f}".replace(",", "X").replace(".", ",").replace("X", ".").rstrip("0").rstrip(",")


def _tarih(t) -> str:
    if not t:
        return ""
    return t.strftime("%d.%m.%Y")


def _belge_baslik(belge: dict) -> str:
    """Örn: 'SF-00229 nolu Satış Faturası toplamı' veya tahsilat açıklaması."""
    tur = (belge.get("tur") or "").strip()
    no = (belge.get("belge_no") or "").strip()
    aciklama = (belge.get("aciklama") or "").strip()
    stoklu = tur in STOKLU_TURLER
    if stoklu and no:
        return f"{no} nolu {tur} toplamı"
    if aciklama:
        return f"{tur}: {aciklama}" if tur and tur not in aciklama else aciklama
    if tur and no:
        return f"{tur} — {no}"
    return tur or no or "Hareket"


def _iskontolu_kdvli_birim_fiyat(satir: dict) -> Decimal | None:
    """İskontolu + KDV'li net birim fiyat (genel / miktar)."""
    miktar = Decimal(str(satir.get("miktar") or 0))
    genel = Decimal(str(satir.get("genel") or 0))
    if miktar != 0:
        return genel / miktar
    # Fallback: birim fiyatına iskonto ve KDV uygula
    birim_fiyat = Decimal(str(satir.get("birim_fiyat") or 0))
    if birim_fiyat == 0:
        return None
    iskonto = Decimal(str(satir.get("iskonto_orani") or 0))
    kdv = Decimal(str(satir.get("kdv_orani") or 0))
    net_birim = birim_fiyat * (Decimal("1") - iskonto / Decimal("100"))
    return net_birim * (Decimal("1") + kdv / Decimal("100"))


def _stok_degerleri(satir: dict) -> tuple[str, str, str, str, str, str]:
    """Ürün Kodu, Ürün Adı, Miktar, Birim, Net Fiyat, Tutar(genel)."""
    fiyat = _iskontolu_kdvli_birim_fiyat(satir)
    return (
        (satir.get("urun_kodu") or "").strip(),
        (satir.get("urun_adi") or "").strip(),
        _miktar(satir.get("miktar")),
        (satir.get("birim") or "").strip(),
        _para_zorunlu(fiyat) if fiyat is not None else "",
        _para_zorunlu(satir.get("genel")),
    )


def _kes(metin: str, genislik: int) -> str:
    """Sabit genişlikte kes; gerekirse son karakteri … yap."""
    if genislik <= 0:
        return ""
    if len(metin) <= genislik:
        return metin
    if genislik == 1:
        return "…"
    return metin[: genislik - 1] + "…"


def _alan_sol(metin: str, genislik: int, *, kes: bool = True) -> str:
    metin = metin or ""
    if kes:
        metin = _kes(metin, genislik)
    elif len(metin) > genislik:
        metin = metin[:genislik]
    return metin.ljust(genislik)


def _alan_sag(metin: str, genislik: int, *, kes: bool = False) -> str:
    """Sayısal alan. kes=False: asla kırpma; gerekirse alan genişler."""
    metin = metin or ""
    if kes and len(metin) > genislik:
        metin = _kes(metin, genislik)
        return metin.rjust(genislik)
    return metin.rjust(max(genislik, len(metin)))


def _stok_aciklama_metni(
    kod: str, urun: str, miktar: str, birim: str, fiyat: str = "", tutar: str = ""
) -> str:
    """Açıklama hücresinde: Kod | Ürün Adı | Miktar | Birim | Net Fiyat | Tutar."""
    p = _STOK_PAD
    sep = _STOK_SEP

    kod_s = _alan_sol(kod, p["kod"])
    miktar_s = _alan_sag(miktar, p["miktar"], kes=True)
    birim_s = _alan_sol(birim, p["birim"])
    fiyat_s = _alan_sag(fiyat, p["fiyat"], kes=False)
    tutar_s = _alan_sag(tutar, p["tutar"], kes=False)

    sabit = (
        len(kod_s)
        + len(miktar_s)
        + len(birim_s)
        + len(fiyat_s)
        + len(tutar_s)
        + len(sep) * 5
    )
    urun_w = max(1, _STOK_SATIR_LEN - sabit)
    urun_s = _alan_sol(urun, urun_w)
    return sep.join((kod_s, urun_s, miktar_s, birim_s, fiyat_s, tutar_s))


def _stok_baslik_metni() -> str:
    return _stok_aciklama_metni(*STOK_ACIKLAMA_BASLIK)


def _stok_satir_metni(
    kod: str, urun: str, miktar: str, birim: str, fiyat: str = "", tutar: str = "", *_rest
) -> str:
    return _stok_aciklama_metni(kod, urun, miktar, birim, fiyat, tutar)


def _mono_font(size: int, bold: bool = False) -> tuple:
    weight = "bold" if bold else "normal"
    return (_STOK_MONO[0], size, weight)


class StokDetayliCariEkstreDialog(tk.Toplevel):
    """Tarih | Açıklama | Borç | Alacak | Bakiye — fatura içi 6 alan Açıklama'da."""

    def __init__(self, parent, cari):
        super().__init__(parent)
        if cari is None:
            raise ValueError("Cari gerekli.")
        self.cari = cari
        self._ham = None
        self._zoom = 1.0
        self._tam_ekran = False
        self._onceki_geometry = None
        self.title(f"Stok Detaylı Cari Ekstre — {cari.cari_kodu} {cari.unvan}")
        self.geometry("1100x680")
        self.minsize(900, 520)
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()

        ust = ttk.Frame(self, padding=(12, 10, 12, 6))
        ust.pack(fill="x")
        ttk.Label(
            ust,
            text="STOK DETAYLI CARİ HESAP EKSTRESİ",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w")
        self.ozet = ttk.Label(
            ust,
            text=f"{cari.cari_kodu} — {cari.unvan}",
            font=("Segoe UI", 10),
            foreground="#1a237e",
        )
        self.ozet.pack(anchor="w", pady=(2, 0))

        filtre = ttk.Frame(self, padding=(12, 0, 12, 6))
        filtre.pack(fill="x")
        ttk.Label(filtre, text="Başlangıç:").pack(side="left")
        bas_c = ttk.Frame(filtre)
        bas_c.pack(side="left", padx=(4, 8))
        self.tarih_bas = ttk.Entry(bas_c, width=11)
        self.tarih_bas.pack(side="left")
        takvim_butonu(bas_c, self.tarih_bas, on_select=self.yenile)

        ttk.Label(filtre, text="Bitiş:").pack(side="left")
        bit_c = ttk.Frame(filtre)
        bit_c.pack(side="left", padx=(4, 8))
        self.tarih_bit = ttk.Entry(bit_c, width=11)
        self.tarih_bit.pack(side="left")
        takvim_butonu(bit_c, self.tarih_bit, on_select=self.yenile)

        ttk.Label(filtre, text="Stok ara:").pack(side="left", padx=(4, 0))
        self.stok_ara = ttk.Entry(filtre, width=16)
        self.stok_ara.pack(side="left", padx=4)
        self.stok_ara.bind("<Return>", lambda _e: self.yenile())

        ttk.Button(filtre, text="Uygula", command=self.yenile).pack(side="left", padx=(8, 4))
        ttk.Button(filtre, text="Tümünü Aç", command=self._hepsini_ac).pack(side="left", padx=2)
        ttk.Button(filtre, text="Tümünü Kapat", command=self._hepsini_kapat).pack(side="left", padx=2)
        ttk.Button(filtre, text="Excel", command=self._excel_aktar).pack(side="left", padx=(12, 0))

        zoom_bar = ttk.Frame(filtre)
        zoom_bar.pack(side="left", padx=(16, 0))
        ttk.Button(zoom_bar, text="−", width=3, command=self._zoom_azalt).pack(side="left")
        self.zoom_lbl = ttk.Label(zoom_bar, text="100%", width=5, anchor="center")
        self.zoom_lbl.pack(side="left", padx=2)
        ttk.Button(zoom_bar, text="+", width=3, command=self._zoom_arttir).pack(side="left")

        kapat_btn = ttk.Button(filtre, text="✕", width=3, command=self.destroy)
        kapat_btn.pack(side="right")
        self.tam_ekran_btn = ttk.Button(
            filtre, text="□", width=3, command=self._tam_ekran_degistir
        )
        self.tam_ekran_btn.pack(side="right", padx=(0, 2))
        try:
            _win_font = ("Segoe UI", 9)
            self.tam_ekran_btn.configure(font=_win_font)
            kapat_btn.configure(font=_win_font)
        except tk.TclError:
            pass
        ttk.Button(filtre, text="Yazdır", command=self._yazdir).pack(side="right", padx=(0, 8))

        tablo_cerceve = ttk.Frame(self, padding=(12, 0, 12, 8))
        tablo_cerceve.pack(fill="both", expand=True)

        self._stil = ttk.Style(self)
        try:
            self._stil.map(
                "StokEkstre.Treeview",
                background=[("selected", "#cfe2f3")],
                foreground=[("selected", "#000000")],
            )
        except tk.TclError:
            pass

        # Ana kolonlar: yalnız 5 — fatura içi 6 alan Açıklama'da
        self._kolonlar = ("tarih", "aciklama", "borc", "alacak", "bakiye")
        self._kolon_ayar = {
            "tarih": ("Tarih", 110, "center"),
            "aciklama": ("Açıklama", 720, "e"),  # Borç tarafına (sağa) yaslı
            "borc": ("Borç", 130, "e"),
            "alacak": ("Alacak", 130, "e"),
            "bakiye": ("Bakiye", 130, "e"),
        }
        # show=headings: #0 ağaç kolonu yok → dikey çizgi/ok yok
        self.tablo = ttk.Treeview(
            tablo_cerceve,
            columns=self._kolonlar,
            show="headings",
            style="StokEkstre.Treeview",
            selectmode="browse",
        )
        self._uygula_zoom()

        dikey = ttk.Scrollbar(tablo_cerceve, orient="vertical", command=self.tablo.yview)
        yatay = ttk.Scrollbar(tablo_cerceve, orient="horizontal", command=self.tablo.xview)
        self.tablo.configure(yscrollcommand=dikey.set, xscrollcommand=yatay.set)
        self.tablo.grid(row=0, column=0, sticky="nsew")
        dikey.grid(row=0, column=1, sticky="ns")
        yatay.grid(row=1, column=0, sticky="ew")
        tablo_cerceve.rowconfigure(0, weight=1)
        tablo_cerceve.columnconfigure(0, weight=1)

        alt = ttk.Frame(self, padding=(12, 0, 12, 12))
        alt.pack(fill="x")
        self.alt_ozet = ttk.Label(alt, text="", font=("Segoe UI", 9, "bold"), foreground="#1a237e")
        self.alt_ozet.pack(side="right")

        self.after(50, self.yenile)

    def _uygula_zoom(self):
        """Font, satır yüksekliği ve kolon genişliklerini zoom faktörüne göre uygula."""
        z = self._zoom
        stil = self._stil
        row_h = max(18, int(round(22 * z)))
        f_govde = max(7, int(round(9 * z)))
        f_baslik = max(7, int(round(9 * z)))
        f_belge = max(8, int(round(10 * z)))
        f_stok = max(7, int(round(9 * z)))
        stil.configure(
            "StokEkstre.Treeview",
            rowheight=row_h,
            font=("Segoe UI", f_govde),
            fieldbackground="#ffffff",
        )
        stil.configure(
            "StokEkstre.Treeview.Heading",
            font=("Segoe UI", f_baslik, "bold"),
            padding=(max(2, int(4 * z)), max(2, int(4 * z))),
        )
        self.tablo.column("#0", width=0, minwidth=0, stretch=False)
        for kolon in self._kolonlar:
            baslik, genislik, hiza = self._kolon_ayar[kolon]
            if kolon == "aciklama":
                hiza = "e"
            w = max(36, int(round(genislik * z)))
            stretch = kolon == "aciklama"
            if kolon in ("borc", "alacak", "bakiye"):
                mw = min(w, max(80, int(round(80 * z))))
            else:
                mw = max(28, w // 2)
            self.tablo.heading(kolon, text=baslik, anchor=hiza)
            self.tablo.column(
                kolon,
                width=w,
                minwidth=mw,
                anchor=hiza,
                stretch=stretch,
            )
        self.tablo.tag_configure(
            "belge", background="#e8eef5", font=("Segoe UI", f_belge, "bold")
        )
        self.tablo.tag_configure(
            "belge_cift", background="#f5f7fa", font=("Segoe UI", f_belge, "bold")
        )
        self.tablo.tag_configure(
            "stok_baslik",
            background="#cfd8dc",
            foreground="#263238",
            font=_mono_font(f_stok, bold=True),
        )
        self.tablo.tag_configure(
            "ayirici",
            background="#90a4ae",
            foreground="#90a4ae",
            font=("Segoe UI", max(1, int(round(2 * z)))),
        )
        self.tablo.tag_configure(
            "stok", background="#ffffff", foreground="#37474f", font=_mono_font(f_stok)
        )
        self.tablo.tag_configure(
            "stok_cift",
            background="#fafbfc",
            foreground="#37474f",
            font=_mono_font(f_stok),
        )
        if hasattr(self, "zoom_lbl"):
            self.zoom_lbl.configure(text=f"{int(round(z * 100))}%")

    def _zoom_arttir(self):
        if self._zoom >= 1.4:
            return
        self._zoom = round(min(1.4, self._zoom + 0.2), 1)
        self._uygula_zoom()

    def _zoom_azalt(self):
        if self._zoom <= 0.8:
            return
        self._zoom = round(max(0.8, self._zoom - 0.2), 1)
        self._uygula_zoom()

    def _ekran_boyutuna_yay(self):
        """zoomed desteklenmeyen Tk sürümlerinde ekranı doldur."""
        w = self.winfo_screenwidth()
        h = self.winfo_screenheight()
        self.geometry(f"{w}x{h}+0+0")

    def _tam_ekran_degistir(self):
        """Windows wm_state('zoomed') ile büyüt / eski geometriye dön."""
        # wm_state / state tek argüman alır (örn. 'zoomed'); True/False formu TypeError verir.
        if not self._tam_ekran:
            self._onceki_geometry = self.geometry()
            try:
                self.wm_state("zoomed")
            except tk.TclError:
                try:
                    self.state("zoomed")
                except tk.TclError:
                    self._ekran_boyutuna_yay()
            self._tam_ekran = True
            self.tam_ekran_btn.configure(text="❐")
        else:
            try:
                self.wm_state("normal")
            except tk.TclError:
                try:
                    self.state("normal")
                except tk.TclError:
                    pass
            if self._onceki_geometry:
                self.geometry(self._onceki_geometry)
            self._tam_ekran = False
            self.tam_ekran_btn.configure(text="□")

    def _belge_degerleri(self, tarih, baslik, borc, alacak, bakiye) -> tuple:
        return (
            _tarih(tarih) if not isinstance(tarih, str) else tarih,
            baslik,
            _para(borc),
            _para(alacak),
            _para(bakiye),
        )

    def _bos_degerler(self) -> tuple:
        return ("", "", "", "", "")

    def _stok_deger_satiri(self, aciklama: str) -> tuple:
        return ("", aciklama, "", "", "")

    def _tarih_araligi(self):
        baslangic = bitis = None
        try:
            bas = (self.tarih_bas.get() or "").strip()
            bit = (self.tarih_bit.get() or "").strip()
            if bas:
                baslangic = datetime.strptime(bas, "%d.%m.%Y").date()
            if bit:
                bitis = datetime.strptime(bit, "%d.%m.%Y").date()
        except ValueError:
            messagebox.showerror("Tarih", "Tarihleri gg.aa.yyyy formatında girin.", parent=self)
            return None, None, False
        if baslangic and bitis and baslangic > bitis:
            messagebox.showwarning("Tarih", "Başlangıç bitişten sonra olamaz.", parent=self)
            return None, None, False
        return baslangic, bitis, True

    def yenile(self):
        baslangic, bitis, ok = self._tarih_araligi()
        if not ok:
            return
        if self._ham is None:
            try:
                self._ham = RaporService.stok_detayli_ekstre(self.cari.id)
            except ValueError as hata:
                messagebox.showerror("Ekstre", str(hata), parent=self)
                return

        rapor = self._ham
        stok_filtre = (self.stok_ara.get() or "").strip().casefold()

        for item in self.tablo.get_children():
            self.tablo.delete(item)

        belgeler = list(reversed(rapor.get("belgeler") or []))
        gosterilen = 0
        borc_t = Decimal("0")
        alacak_t = Decimal("0")
        son_bakiye = Decimal("0")

        for belge in belgeler:
            tarih = belge.get("tarih")
            if baslangic and tarih and tarih < baslangic:
                continue
            if bitis and tarih and tarih > bitis:
                continue

            stok_satirlari = list(belge.get("stok_satirlari") or [])
            stoklu = belge.get("tur") in STOKLU_TURLER
            if stok_filtre:
                stok_satirlari = [
                    s
                    for s in stok_satirlari
                    if stok_filtre in (s.get("urun_kodu") or "").casefold()
                    or stok_filtre in (s.get("urun_adi") or "").casefold()
                ]
                if stoklu and not stok_satirlari:
                    continue
                if not stoklu:
                    continue

            borc = Decimal(str(belge.get("borc") or 0))
            alacak = Decimal(str(belge.get("alacak") or 0))
            bakiye = Decimal(str(belge.get("bakiye") or 0))
            tag = "belge" if gosterilen % 2 == 0 else "belge_cift"
            parent = self.tablo.insert(
                "",
                "end",
                values=self._belge_degerleri(
                    tarih, _belge_baslik(belge), borc, alacak, bakiye
                ),
                tags=(tag,),
                open=True,
            )
            gosterilen += 1
            borc_t += borc
            alacak_t += alacak
            son_bakiye = bakiye

            # Fatura içi: 6 alan yalnız Açıklama hücresinde (monospace)
            if stoklu and stok_satirlari:
                self.tablo.insert(
                    parent,
                    "end",
                    values=self._bos_degerler(),
                    tags=("ayirici",),
                )
                self.tablo.insert(
                    parent,
                    "end",
                    values=self._stok_deger_satiri(_stok_baslik_metni()),
                    tags=("stok_baslik",),
                )
                for i, s in enumerate(stok_satirlari):
                    stok_tag = "stok" if i % 2 == 0 else "stok_cift"
                    kod, urun, miktar, birim, fiyat, tutar = _stok_degerleri(s)
                    self.tablo.insert(
                        parent,
                        "end",
                        values=self._stok_deger_satiri(
                            _stok_aciklama_metni(kod, urun, miktar, birim, fiyat, tutar)
                        ),
                        tags=(stok_tag,),
                    )

        self.ozet.configure(
            text=(
                f"{rapor['cari'].cari_kodu} — {rapor['cari'].unvan}  |  "
                f"Genel bakiye: {_para(rapor.get('bakiye')) or '0,00'}"
            )
        )
        self.alt_ozet.configure(
            text=(
                f"Belge: {gosterilen}  |  "
                f"Borç: {_para(borc_t) or '0,00'}  |  "
                f"Alacak: {_para(alacak_t) or '0,00'}  |  "
                f"Son bakiye: {_para(son_bakiye) or '0,00'}"
            )
        )

    def _hepsini_ac(self):
        for item in self.tablo.get_children():
            self.tablo.item(item, open=True)

    def _hepsini_kapat(self):
        for item in self.tablo.get_children():
            self.tablo.item(item, open=False)

    def _filtrelenmis_belgeler(self):
        """Tarih / stok filtresine göre belge listesi (Excel ve yazdır ile aynı)."""
        if self._ham is None:
            self.yenile()
        if self._ham is None:
            return None
        baslangic, bitis, ok = self._tarih_araligi()
        if not ok:
            return None
        stok_filtre = (self.stok_ara.get() or "").strip().casefold()
        belgeler = list(reversed(self._ham.get("belgeler") or []))
        sonuc = []
        for belge in belgeler:
            tarih = belge.get("tarih")
            if baslangic and tarih and tarih < baslangic:
                continue
            if bitis and tarih and tarih > bitis:
                continue
            stok_satirlari = list(belge.get("stok_satirlari") or [])
            stoklu = belge.get("tur") in STOKLU_TURLER
            if stok_filtre:
                stok_satirlari = [
                    s
                    for s in stok_satirlari
                    if stok_filtre in (s.get("urun_kodu") or "").casefold()
                    or stok_filtre in (s.get("urun_adi") or "").casefold()
                ]
                if stoklu and not stok_satirlari:
                    continue
                if not stoklu:
                    continue
            sonuc.append((belge, stok_satirlari if stoklu else []))
        return sonuc

    def _ekstre_html(self, belgeler) -> str:
        """A4 yazdır — ekranla 1:1: Tarih | Açıklama | Borç | Alacak | Bakiye.

        Fatura içi: Kod | Ürün Adı | Miktar | Birim | Net Fiyat | Tutar → Açıklama.
        Belge satırında Borç/Alacak/Bakiye; stok satırlarında bu üç hücre boş.
        """
        rapor = self._ham
        cari = rapor["cari"]
        bas = (self.tarih_bas.get() or "").strip() or "—"
        bit = (self.tarih_bit.get() or "").strip() or "—"
        bakiye = _para(rapor.get("bakiye")) or "0,00"

        bloklar = []
        for belge, stok_satirlari in belgeler:
            tarih = html.escape(_tarih(belge.get("tarih")))
            aciklama = html.escape(_belge_baslik(belge))
            borc = html.escape(_para(belge.get("borc")) or "")
            alacak = html.escape(_para(belge.get("alacak")) or "")
            bakiye_s = html.escape(_para(belge.get("bakiye")) or "")
            blok = [
                "<tr class='belge'>",
                f"<td class='c'>{tarih}</td>",
                f"<td class='aciklama'>{aciklama}</td>",
                f"<td class='n'>{borc}</td>",
                f"<td class='n'>{alacak}</td>",
                f"<td class='n'>{bakiye_s}</td>",
                "</tr>",
            ]
            if stok_satirlari:
                blok.append(
                    "<tr class='ayirici'><td colspan='5'></td></tr>"
                )
                blok.append(
                    "<tr class='stok-baslik'>"
                    "<td></td>"
                    f"<td class='aciklama stok-line'>{html.escape(_stok_baslik_metni())}</td>"
                    "<td class='n'></td><td class='n'></td><td class='n'></td>"
                    "</tr>"
                )
                for i, s in enumerate(stok_satirlari):
                    kod, urun, miktar, birim, fiyat, tutar = _stok_degerleri(s)
                    satir = html.escape(
                        _stok_aciklama_metni(kod, urun, miktar, birim, fiyat, tutar)
                    )
                    cls = "stok" if i % 2 == 0 else "stok-cift"
                    blok.append(
                        f"<tr class='{cls}'>"
                        "<td></td>"
                        f"<td class='aciklama stok-line'>{satir}</td>"
                        "<td class='n'></td>"
                        "<td class='n'></td>"
                        "<td class='n'></td>"
                        "</tr>"
                    )
            bloklar.append("\n".join(blok))

        govde = "\n".join(bloklar) or (
            "<tr><td colspan='5'>Filtrelere uygun hareket yok.</td></tr>"
        )
        baslik = "Stok Detaylı Cari Hesap Ekstresi"
        return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8"/>
<title>{html.escape(baslik)}</title>
<style>
  @page {{ size: A4 portrait; margin: 12mm; }}
  * {{ box-sizing: border-box; }}
  html, body {{
    margin: 0; padding: 0;
    width: 100%; max-width: 100%;
    overflow-x: hidden;
    font-family: 'Segoe UI', Tahoma, sans-serif;
    color: #111;
    font-size: 9pt;
  }}
  body {{ width: 186mm; max-width: 100%; }}
  .toolbar {{ margin-bottom: 8px; }}
  .toolbar button {{ padding: 6px 14px; font-size: 13px; cursor: pointer; }}
  h1 {{ font-size: 13pt; margin: 0 0 4px; font-weight: 700; }}
  .meta {{ margin: 0 0 10px; color: #333; font-size: 8.5pt; line-height: 1.35; }}
  /* tarih 12 | aciklama 52 | borc 12 | alacak 12 | bakiye 12 */
  table.ekstre {{
    border-collapse: collapse;
    width: 100%; max-width: 100%;
    table-layout: fixed;
  }}
  table.ekstre col.c-tarih {{ width: 12%; }}
  table.ekstre col.c-aciklama {{ width: 52%; }}
  table.ekstre col.c-borc {{ width: 12%; }}
  table.ekstre col.c-alacak {{ width: 12%; }}
  table.ekstre col.c-bakiye {{ width: 12%; }}
  table.ekstre > thead > tr > th {{
    border: none;
    border-bottom: 2px solid #333;
    background: #f0f0f0;
    padding: 3px 4px;
    font-size: 8pt;
    font-weight: 700;
    vertical-align: middle;
    white-space: nowrap;
    overflow: hidden;
  }}
  table.ekstre > tbody > tr.belge > td {{
    border: none;
    border-bottom: 1px solid #c5cdd4;
    padding: 3px 4px;
    vertical-align: middle;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    font-weight: 600;
    background: #eef2f6;
    line-height: 1.25;
  }}
  table.ekstre > tbody > tr.ayirici > td {{
    border: none;
    padding: 0;
    height: 3px;
    background: #90a4ae;
    line-height: 0;
    font-size: 0;
  }}
  table.ekstre > tbody > tr.stok-baslik > td {{
    border: none;
    border-bottom: 1px solid #90a4ae;
    padding: 2px 4px;
    vertical-align: middle;
    font-weight: 700;
    font-size: 7.5pt;
    background: #cfd8dc;
    color: #263238;
    line-height: 1.2;
  }}
  table.ekstre > tbody > tr.stok > td,
  table.ekstre > tbody > tr.stok-cift > td {{
    border: none;
    border-bottom: 1px solid #e8ecf0;
    padding: 2px 4px;
    vertical-align: middle;
    font-weight: 400;
    font-size: 8pt;
    line-height: 1.2;
    background: #fff;
  }}
  table.ekstre > tbody > tr.stok-cift > td {{ background: #fafbfc; }}
  th.c, td.c {{ text-align: center; }}
  th.n, td.n {{ text-align: right; }}
  th.aciklama, td.aciklama {{
    text-align: right !important;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  td.stok-line {{
    font-family: Consolas, 'Cascadia Mono', 'Courier New', monospace;
    font-size: 8pt;
    color: #37474f;
    padding-right: 6px !important;
  }}
  tr.stok-baslik td.stok-line {{ color: #263238; }}
  @media print {{
    .toolbar {{ display: none !important; }}
    html, body {{
      margin: 0 !important;
      padding: 0 !important;
      width: 100% !important;
      max-width: 100% !important;
      overflow: hidden;
    }}
    table.ekstre {{
      width: 100% !important;
      max-width: 100% !important;
    }}
  }}
</style>
</head>
<body>
  <div class="toolbar">
    <button type="button" onclick="window.print()">Yazdır</button>
  </div>
  <h1>{html.escape(baslik)}</h1>
  <p class="meta">
    <strong>{html.escape(cari.cari_kodu)}</strong> — {html.escape(cari.unvan or "")}<br/>
    Dönem: {html.escape(bas)} – {html.escape(bit)} &nbsp;·&nbsp;
    Genel bakiye: {html.escape(bakiye)}
  </p>
  <table class="ekstre">
    <colgroup>
      <col class="c-tarih"/><col class="c-aciklama"/>
      <col class="c-borc"/><col class="c-alacak"/><col class="c-bakiye"/>
    </colgroup>
    <thead>
      <tr>
        <th class="c">Tarih</th>
        <th class="aciklama">Açıklama</th>
        <th class="n">Borç</th>
        <th class="n">Alacak</th>
        <th class="n">Bakiye</th>
      </tr>
    </thead>
    <tbody>
      {govde}
    </tbody>
  </table>
</body>
</html>
"""

    def _yazdir(self):
        belgeler = self._filtrelenmis_belgeler()
        if belgeler is None:
            return
        klasor = Path(tempfile.gettempdir()) / "muhasebe_belge"
        klasor.mkdir(exist_ok=True)
        kod = "".join(c if c.isalnum() or c in "-_" else "_" for c in (self.cari.cari_kodu or ""))[:20]
        dosya = klasor / f"stok_ekstre_{kod or 'cari'}.html"
        dosya.write_text(self._ekstre_html(belgeler), encoding="utf-8")
        webbrowser.open(dosya.as_uri())
        messagebox.showinfo(
            "Yazdırma",
            "Ekstre tarayıcıda açıldı.\n"
            "Yazdır iletişim kutusu için Yazdır düğmesine basın veya Ctrl+P kullanın.\n"
            "Sayfa yönü: A4 dikey (portrait).",
            parent=self,
        )

    def _excel_aktar(self):
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Alignment, Font, PatternFill
        except ImportError:
            messagebox.showerror(
                "Excel",
                "openpyxl yüklü değil. Kurulum: pip install openpyxl",
                parent=self,
            )
            return
        belgeler_filt = self._filtrelenmis_belgeler()
        if belgeler_filt is None:
            return

        yol = filedialog.asksaveasfilename(
            parent=self,
            title="Ekstreyi kaydet",
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialfile=f"stok_ekstre_{self.cari.cari_kodu}_{date.today():%Y%m%d}.xlsx",
        )
        if not yol:
            return

        wb = Workbook()
        ws = wb.active
        ws.title = "Stok Ekstre"
        basliklar = ["Tarih", "Açıklama", "Borç", "Alacak", "Bakiye"]
        ws.append(basliklar)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for col in (3, 4, 5):
            ws.cell(1, col).alignment = Alignment(horizontal="right")

        baslik_fill = PatternFill("solid", fgColor="CFD8DC")
        belge_font = Font(bold=True)

        for belge, stok_satirlari in belgeler_filt:
            tarih = belge.get("tarih")
            borc = float(belge.get("borc") or 0) or None
            alacak = float(belge.get("alacak") or 0) or None
            bakiye = float(belge.get("bakiye") or 0) or None
            ws.append([
                _tarih(tarih),
                _belge_baslik(belge),
                borc,
                alacak,
                bakiye,
            ])
            for cell in ws[ws.max_row]:
                cell.font = belge_font

            if stok_satirlari:
                ws.append(["", _stok_baslik_metni(), None, None, None])
                for cell in ws[ws.max_row]:
                    cell.font = Font(bold=True, size=9, name="Consolas")
                    cell.fill = baslik_fill
                for s in stok_satirlari:
                    kod, urun, miktar, birim, fiyat, tutar = _stok_degerleri(s)
                    ws.append([
                        "",
                        _stok_aciklama_metni(kod, urun, miktar, birim, fiyat, tutar),
                        None,
                        None,
                        None,
                    ])
                    ws.cell(ws.max_row, 2).font = Font(name="Consolas", size=9)

        genislikler = {"A": 12, "B": 72, "C": 14, "D": 14, "E": 14}
        for col, width in genislikler.items():
            ws.column_dimensions[col].width = width
        for row in ws.iter_rows(min_row=2, min_col=3, max_col=5):
            for cell in row:
                if cell.value is not None and isinstance(cell.value, (int, float)):
                    cell.alignment = Alignment(horizontal="right")
                    cell.number_format = "#,##0.00"

        try:
            wb.save(yol)
        except PermissionError:
            messagebox.showerror(
                "Excel",
                "Dosya kaydedilemedi. Dosya başka bir programda (ör. Excel) açık olabilir.\n"
                f"Yol: {yol}",
                parent=self,
            )
            return
        except OSError as hata:
            messagebox.showerror(
                "Excel",
                f"Dosya kaydedilemedi:\n{hata}",
                parent=self,
            )
            return

        messagebox.showinfo(
            "Excel",
            f"Stok detaylı ekstre kaydedildi.\n{Path(yol)}",
            parent=self,
        )
