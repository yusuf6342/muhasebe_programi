"""Lot etiketlerini yazdır — önizleme + baskı (stok miktarını değiştirmez).

Etikette: ürün adı, satış fiyatı, Code 128 barkod ve yazılı kod.
Stok kodu / giriş tarihi / lot yazısı varsayılan olarak basılmaz.
"""

from __future__ import annotations

import tempfile
import tkinter as tk
import webbrowser
from decimal import Decimal
from html import escape
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk
from typing import Any

from database.lot_barkod_service import (
    DURUM_BEKLIYOR,
    LotBarkodService,
)
from stok_barkod_ui import code128_svg, _para


def _adet_modu(satir: dict, mod: str) -> int:
    if mod == "giren":
        try:
            m = int(Decimal(str(satir.get("giren_miktar") or 1)))
        except Exception:
            m = 1
        return max(1, m)
    return max(1, int(satir.get("etiket_adedi") or 1))


def lot_etiket_html(
    satirlar: list[dict],
    *,
    genislik_mm: float = 60,
    yukseklik_mm: float = 40,
    lot_goster: bool = False,
) -> str:
    """Varsayılan 60×40 mm: ad + fiyat + barkod + yazılı kod (stok kodu yok)."""
    barkod_h = max(32, min(80, int(yukseklik_mm * 1.5)))
    modul = 2 if genislik_mm >= 50 else 1
    kartlar = []
    for s in satirlar:
        kod = (s.get("barkod") or "").strip()
        if not kod:
            continue
        adet = max(1, int(s.get("etiket_adedi") or 1))
        svg = code128_svg(kod, yukseklik=barkod_h, modul=modul)
        ad = escape(s.get("stok_adi") or "")
        birim = escape(s.get("birim") or "Adet")
        fiyat = s.get("satis_fiyati")
        fiyat_txt = escape(_para(fiyat) if fiyat is not None else "—")
        kdv = "KDV dahil" if s.get("kdv_dahil", True) else "KDV hariç"
        pb = escape((s.get("para_birimi") or "TRY").upper())
        lot_satir = ""
        if lot_goster and s.get("lot_no"):
            lot_satir = f'<div class="lot">Lot: {escape(str(s["lot_no"]))}</div>'
        for _ in range(adet):
            kartlar.append(
                f"""
                <div class="etiket">
                  <div class="ad">{ad}</div>
                  <div class="fiyat">{fiyat_txt} {pb}</div>
                  <div class="birim">{birim} · {kdv}</div>
                  {lot_satir}
                  <div class="barkod">{svg}</div>
                </div>
                """
            )
    govde = "\n".join(kartlar) or "<p>Basılacak etiket yok.</p>"
    return f"""<!DOCTYPE html>
<html lang="tr"><head><meta charset="utf-8"/>
<title>Lot Etiketleri</title>
<style>
@page {{ size: {genislik_mm}mm {yukseklik_mm}mm; margin: 0; }}
* {{ box-sizing: border-box; }}
body {{ font-family: "Segoe UI", Arial, sans-serif; margin: 0; padding: 8px; background: #eee; }}
.toolbar {{ background:#fff; padding:10px; margin-bottom:10px; border:1px solid #ccc; }}
.etiket {{
  width:{genislik_mm}mm; height:{yukseklik_mm}mm; background:#fff;
  border:1px dashed #999; padding:2mm; text-align:center;
  page-break-after:always; overflow:hidden;
  display:flex; flex-direction:column; align-items:center; justify-content:flex-start;
}}
.ad {{ font-size:11pt; font-weight:700; line-height:1.15; max-height:2.4em; overflow:hidden; }}
.fiyat {{ font-size:14pt; font-weight:700; margin-top:1mm; }}
.birim, .lot {{ font-size:8pt; color:#444; }}
.barkod {{ margin-top:auto; }}
@media print {{
  body {{ background:#fff; padding:0; }}
  .toolbar {{ display:none; }}
  .etiket {{ border:none; }}
}}
</style></head><body>
<div class="toolbar">
  <button onclick="window.print()">Yazdır</button>
  <span style="margin-left:12px">Önizleme — stok hareketi oluşmaz</span>
</div>
{govde}
</body></html>"""


class LotEtiketYazdirDialog(tk.Toplevel):
    """Mal girişi sonrası veya bekleyen işlerden etiket önizleme / baskı."""

    def __init__(self, parent, is_ozeti: dict[str, Any] | None = None, *, is_id: int | None = None):
        super().__init__(parent)
        self.title("Lot Etiketlerini Yazdır")
        self.transient(parent)
        self.grab_set()
        self.resizable(True, True)
        self.geometry("820x480")
        self._is: dict[str, Any] | None = None
        self._adet_vars: dict[int, tk.StringVar] = {}
        self._adet_modu = tk.StringVar(value="satir")  # satir | giren | elle
        self._lot_goster = tk.BooleanVar(value=False)

        if is_ozeti:
            self._is = is_ozeti
        elif is_id:
            self._is = LotBarkodService.is_getir(int(is_id))
        if not self._is:
            messagebox.showwarning("Etiket", "Etiket işi bulunamadı.", parent=parent)
            self.after(10, self.destroy)
            return

        ust = ttk.Frame(self, padding=8)
        ust.pack(fill="x")
        ttk.Label(
            ust,
            text=(
                f"Kaynak: {self._is.get('kaynak_tur')}  ·  "
                f"Belge: {self._is.get('kaynak_belge_no')}  ·  "
                f"Durum: {self._is.get('durum')}"
            ),
        ).pack(anchor="w")
        ttk.Label(
            ust,
            text="Yeniden baskı stok / cari / muhasebe hareketi üretmez.",
            foreground="#555",
        ).pack(anchor="w", pady=(2, 0))

        sec = ttk.Frame(self, padding=(8, 0))
        sec.pack(fill="x")
        ttk.Label(sec, text="Adet:").pack(side="left")
        for metin, deger in (
            ("Satır başına 1", "satir"),
            ("Giren miktar kadar", "giren"),
            ("Elle", "elle"),
        ):
            ttk.Radiobutton(
                sec, text=metin, value=deger, variable=self._adet_modu, command=self._adet_modu_uygula
            ).pack(side="left", padx=6)
        ttk.Checkbutton(sec, text="Lot numarasını yazıyla göster", variable=self._lot_goster).pack(
            side="right"
        )

        tablo_cer = ttk.Frame(self, padding=8)
        tablo_cer.pack(fill="both", expand=True)
        kolonlar = ("sec", "ad", "barkod", "lot", "birim", "giren", "adet", "fiyat")
        self.tablo = ttk.Treeview(tablo_cer, columns=kolonlar, show="headings", height=12)
        baslik = {
            "sec": "✓",
            "ad": "Ürün",
            "barkod": "Barkod",
            "lot": "Lot",
            "birim": "Birim",
            "giren": "Giren",
            "adet": "Etiket",
            "fiyat": "Satış fiyatı",
        }
        gen = {"sec": 36, "ad": 200, "barkod": 100, "lot": 110, "birim": 60, "giren": 70, "adet": 60, "fiyat": 90}
        for c in kolonlar:
            self.tablo.heading(c, text=baslik[c])
            self.tablo.column(c, width=gen[c], anchor="center" if c != "ad" else "w")
        sb = ttk.Scrollbar(tablo_cer, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=sb.set)
        self.tablo.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self._secili: set[int] = set()
        self._doldur()
        self.tablo.bind("<Button-1>", self._tik, add="+")

        alt = ttk.Frame(self, padding=8)
        alt.pack(fill="x")
        ttk.Button(alt, text="Önizleme", command=self._onizle).pack(side="left")
        ttk.Button(alt, text="Yazıcıya gönder", command=self._yazdir).pack(side="left", padx=8)
        ttk.Button(alt, text="Etiketleme tamamlandı", command=self._tamamla).pack(side="left", padx=8)
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")

    def _doldur(self) -> None:
        self.tablo.delete(*self.tablo.get_children())
        self._adet_vars.clear()
        self._secili.clear()
        for s in self._is.get("satirlar") or []:
            sid = int(s["id"])
            self._secili.add(sid)
            adet = _adet_modu(s, self._adet_modu.get())
            self._adet_vars[sid] = tk.StringVar(value=str(adet))
            fiyat = s.get("satis_fiyati")
            self.tablo.insert(
                "",
                "end",
                iid=str(sid),
                values=(
                    "☑",
                    s.get("stok_adi") or "",
                    s.get("barkod") or "",
                    s.get("lot_no") or "",
                    s.get("birim") or "",
                    str(s.get("giren_miktar") or ""),
                    str(adet),
                    _para(fiyat) if fiyat is not None else "—",
                ),
            )

    def _adet_modu_uygula(self) -> None:
        mod = self._adet_modu.get()
        for s in self._is.get("satirlar") or []:
            sid = int(s["id"])
            if mod == "elle":
                continue
            adet = _adet_modu(s, mod)
            s["etiket_adedi"] = adet
            if str(sid) in self.tablo.get_children():
                vals = list(self.tablo.item(str(sid), "values"))
                vals[6] = str(adet)
                self.tablo.item(str(sid), values=vals)

    def _tik(self, event):
        if self.tablo.identify_region(event.x, event.y) != "cell":
            return
        col = self.tablo.identify_column(event.x)
        row = self.tablo.identify_row(event.y)
        if not row:
            return
        sid = int(row)
        if col == "#1":
            if sid in self._secili:
                self._secili.discard(sid)
                isaret = "☐"
            else:
                self._secili.add(sid)
                isaret = "☑"
            vals = list(self.tablo.item(row, "values"))
            vals[0] = isaret
            self.tablo.item(row, values=vals)
            return "break"
        if col == "#7" and self._adet_modu.get() == "elle":
            # basit adet girişi
            mevcut = self.tablo.set(row, "adet")
            yeni = simpledialog.askinteger(
                "Etiket adedi", "Kaç etiket?", initialvalue=int(mevcut or 1), minvalue=1, parent=self
            )
            if yeni:
                vals = list(self.tablo.item(row, "values"))
                vals[6] = str(yeni)
                self.tablo.item(row, values=vals)
            return "break"
        return None

    def _secili_satirlar(self) -> list[dict]:
        sonuc = []
        by_id = {int(s["id"]): s for s in (self._is.get("satirlar") or [])}
        for sid in self._secili:
            s = dict(by_id.get(sid) or {})
            if not s:
                continue
            try:
                adet = int(self.tablo.set(str(sid), "adet") or 1)
            except (tk.TclError, ValueError):
                adet = int(s.get("etiket_adedi") or 1)
            s["etiket_adedi"] = max(1, adet)
            if s.get("satis_fiyati") is None or Decimal(str(s.get("satis_fiyati") or 0)) <= 0:
                fiyat = LotBarkodService.satis_fiyati(s["stok_id"], s.get("birim"))
                if fiyat is None:
                    messagebox.showwarning(
                        "Satış fiyatı",
                        f"«{s.get('stok_adi')}» için satış fiyatı yok; etiket basılamaz.",
                        parent=self,
                    )
                    return []
                s["satis_fiyati"] = fiyat
            sonuc.append(s)
        return sonuc

    def _html_yaz(self) -> Path | None:
        satirlar = self._secili_satirlar()
        if not satirlar:
            if self._secili:
                return None
            messagebox.showinfo("Etiket", "En az bir satır seçin.", parent=self)
            return None
        html = lot_etiket_html(satirlar, lot_goster=bool(self._lot_goster.get()))
        yol = Path(tempfile.gettempdir()) / f"lot_etiket_{self._is['id']}.html"
        yol.write_text(html, encoding="utf-8")
        return yol

    def _onizle(self) -> None:
        yol = self._html_yaz()
        if yol:
            webbrowser.open(yol.as_uri())

    def _yazdir(self) -> None:
        yol = self._html_yaz()
        if not yol:
            return
        adetler = {}
        for s in self._secili_satirlar():
            adetler[int(s["id"])] = int(s["etiket_adedi"])
        try:
            self._is = LotBarkodService.basim_kaydet(int(self._is["id"]), adetler)
        except ValueError as exc:
            messagebox.showerror("Baskı", str(exc), parent=self)
            return
        webbrowser.open(yol.as_uri())
        messagebox.showinfo(
            "Baskı",
            "Önizleme açıldı. Yazdır diyaloğundan gönderin.\n"
            "İş durumu: Yazıcıya gönderildi (fiziksel yapıştırma onayı ayrıdır).",
            parent=self,
        )

    def _tamamla(self) -> None:
        try:
            self._is = LotBarkodService.etiketleme_tamamla(int(self._is["id"]))
        except ValueError as exc:
            messagebox.showerror("Etiketleme", str(exc), parent=self)
            return
        messagebox.showinfo("Etiketleme", "Etiketleme tamamlandı olarak işaretlendi.", parent=self)
        self.destroy()


class LotEtiketBekleyenPencere(tk.Toplevel):
    """Bekleyen etiket işleri listesi."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Etiket Bekleyenler")
        self.geometry("720x400")
        self.transient(parent)
        cer = ttk.Frame(self, padding=8)
        cer.pack(fill="both", expand=True)
        self.tablo = ttk.Treeview(
            cer, columns=("id", "belge", "tur", "durum", "tarih", "satir"), show="headings", height=14
        )
        for c, b, w in (
            ("id", "İş #", 60),
            ("belge", "Belge", 120),
            ("tur", "Kaynak", 100),
            ("durum", "Durum", 140),
            ("tarih", "Tarih", 140),
            ("satir", "Satır", 60),
        ):
            self.tablo.heading(c, text=b)
            self.tablo.column(c, width=w)
        self.tablo.pack(fill="both", expand=True)
        self.tablo.bind("<Double-1>", self._ac)
        alt = ttk.Frame(self, padding=8)
        alt.pack(fill="x")
        ttk.Button(alt, text="Yenile", command=self.yenile).pack(side="left")
        ttk.Button(alt, text="Aç", command=self._ac).pack(side="left", padx=6)
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")
        self.yenile()

    def yenile(self) -> None:
        self.tablo.delete(*self.tablo.get_children())
        for is_ in LotBarkodService.bekleyenler():
            t = is_.get("olusturma_tarihi")
            self.tablo.insert(
                "",
                "end",
                iid=str(is_["id"]),
                values=(
                    is_["id"],
                    is_.get("kaynak_belge_no") or "",
                    is_.get("kaynak_tur") or "",
                    is_.get("durum") or "",
                    t.strftime("%d.%m.%Y %H:%M") if t else "",
                    len(is_.get("satirlar") or []),
                ),
            )

    def _ac(self, _e=None) -> None:
        sec = self.tablo.selection()
        if not sec:
            return
        LotEtiketYazdirDialog(self, is_id=int(sec[0]))


def lot_etiket_sonrasi_ac(parent, is_ozeti: dict | None) -> None:
    """Kayıt sonrası güvenli açılış (hata giriş kaydını bozmaz)."""
    if not is_ozeti:
        return
    try:
        LotEtiketYazdirDialog(parent, is_ozeti)
    except Exception as exc:  # noqa: BLE001
        try:
            messagebox.showwarning(
                "Lot etiket",
                f"Etiket penceresi açılamadı (mal girişi kaydı tamam):\n{exc}",
                parent=parent,
            )
        except Exception:
            pass


def etiket_bekleyenler_goster(app) -> None:
    LotEtiketBekleyenPencere(app)
