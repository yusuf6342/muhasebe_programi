"""Kredi / nakit avans gider fişi — açma ve muhasebe hesabı atama."""

from __future__ import annotations

from datetime import date
from tkinter import messagebox, ttk
import tkinter as tk

from database.kredi_gider_fisi_service import KrediGiderFisiService


def _para(tutar) -> str:
    if tutar is None:
        return "—"
    return f"{float(tutar):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def _tarih(d) -> str:
    if not d:
        return "—"
    if isinstance(d, date):
        return d.strftime("%d.%m.%Y")
    return str(d)


def kredi_gider_fisini_ac(
    parent,
    *,
    odeme_belge_no: str | None = None,
    gider_belge_no: str | None = None,
    fis_id: int | None = None,
) -> bool:
    """Ödeme / taksit / gider belgesinden konsolide gider fişini açar."""
    try:
        ozet = KrediGiderFisiService.ozet(
            odeme_belge_no=odeme_belge_no,
            gider_belge_no=gider_belge_no,
            fis_id=fis_id,
        )
    except Exception as exc:
        messagebox.showerror("Gider Fişi", str(exc), parent=parent)
        return False
    if not ozet or not ozet.get("satirlar"):
        messagebox.showinfo(
            "Gider Fişi",
            "Bu kayıt için faiz/masraf gider fişi yok (yalnız anapara veya henüz ödenmemiş).",
            parent=parent,
        )
        return False
    dlg = KrediGiderFisiDialog(parent, ozet)
    parent.wait_window(dlg)
    return True


class KrediGiderFisiDialog(tk.Toplevel):
    def __init__(self, parent, ozet: dict):
        super().__init__(parent)
        self.ozet = ozet
        self.title("Gider Fişi — Kredi / Finansman")
        self.geometry("720x520")
        self.minsize(640, 440)
        self.transient(parent)
        self.grab_set()
        try:
            from ui_pencere import pencere_os_krom_ac

            pencere_os_krom_ac(self)
        except Exception:
            pass

        ust = ttk.Frame(self, padding=10)
        ust.pack(fill="x")
        taksit = "—"
        if ozet.get("taksit_no"):
            taksit = f"{ozet['taksit_no']}/{ozet.get('taksit_sayisi') or '?'}"
        baslik = (
            f"{ozet.get('kredi_adi') or 'Kredi'}  ·  Taksit {taksit}  ·  "
            f"{_tarih(ozet.get('odeme_tarihi'))}"
        )
        ttk.Label(ust, text=baslik, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(
            ust,
            text=(
                f"Firma: {ozet.get('firma') or '—'}  |  Banka: {ozet.get('banka') or '—'}  |  "
                f"Ödeme: {ozet.get('odeme_belge_no') or '—'}  |  "
                f"{ozet.get('muhasebe_durum_etiket') or ''}"
            ),
            wraplength=680,
        ).pack(anchor="w", pady=(4, 0))

        ozet_f = ttk.LabelFrame(self, text="Tutarlar (anapara gider toplamına dahil değil)", padding=8)
        ozet_f.pack(fill="x", padx=10, pady=4)
        for etiket, deger in (
            ("Banka çıkışı (toplam ödeme)", _para(ozet.get("toplam_odeme"))),
            ("Anapara borcu azalması", _para(ozet.get("anapara"))),
            ("Faiz gideri", _para(ozet.get("faiz"))),
            ("Masraf gideri", _para(ozet.get("masraf"))),
            ("Gider toplamı (rapora giren)", _para(ozet.get("toplam_gider"))),
        ):
            sat = ttk.Frame(ozet_f)
            sat.pack(fill="x", pady=1)
            ttk.Label(sat, text=etiket, width=32).pack(side="left")
            ttk.Label(sat, text=deger, font=("Segoe UI", 9, "bold")).pack(side="left")

        tab_f = ttk.LabelFrame(self, text="Gider satırları / muhasebe hesapları", padding=8)
        tab_f.pack(fill="both", expand=True, padx=10, pady=4)
        cols = ("belge", "tur", "tutar", "hesap", "durum")
        self.tablo = ttk.Treeview(tab_f, columns=cols, show="headings", height=8, selectmode="browse")
        for k, b, w in (
            ("belge", "Fiş no", 120),
            ("tur", "Gider türü", 140),
            ("tutar", "Tutar", 100),
            ("hesap", "Muhasebe hesabı", 160),
            ("durum", "Durum", 160),
        ):
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=w, anchor="w")
        self.tablo.pack(fill="both", expand=True)
        self._fis_map: dict[str, int] = {}
        self._yenile_tablo()

        alt = ttk.Frame(self, padding=10)
        alt.pack(fill="x")
        ttk.Button(alt, text="Hesap Ata / Değiştir", command=self._hesap_ata).pack(side="left")
        ttk.Button(alt, text="Belge Önizleme", command=self._onizle).pack(side="left", padx=8)
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")

    def _yenile_tablo(self):
        for i in self.tablo.get_children():
            self.tablo.delete(i)
        self._fis_map.clear()
        for s in self.ozet.get("satirlar") or []:
            hesap = s.get("muhasebe_hesap_kodu") or "—"
            if s.get("muhasebe_hesap_adi"):
                hesap = f"{hesap} — {s['muhasebe_hesap_adi']}"
            iid = str(s["id"])
            self._fis_map[iid] = int(s["id"])
            self.tablo.insert(
                "",
                "end",
                iid=iid,
                values=(
                    s.get("belge_no"),
                    s.get("gider_turu"),
                    _para(s.get("tutar")),
                    hesap,
                    s.get("muhasebe_durum_etiket") or "—",
                ),
            )

    def _secili_fis_id(self) -> int | None:
        sec = self.tablo.selection()
        if not sec:
            return None
        return self._fis_map.get(sec[0])

    def _hesap_ata(self):
        fid = self._secili_fis_id()
        if not fid:
            messagebox.showinfo("Hesap", "Satır seçin.", parent=self)
            return
        dlg = HesapAtaDialog(self, fid)
        self.wait_window(dlg)
        if dlg.result:
            # Özeti yenile
            try:
                self.ozet = KrediGiderFisiService.ozet(
                    odeme_belge_no=self.ozet.get("odeme_belge_no"),
                    fis_id=fid,
                ) or self.ozet
            except Exception:
                pass
            self._yenile_tablo()

    def _onizle(self):
        belge = self.ozet.get("gider_belge_no") or self.ozet.get("odeme_belge_no")
        if not belge:
            return
        from belge_onizleme_ui import gider_fisi_onizle

        gider_fisi_onizle(self, belge)


class HesapAtaDialog(tk.Toplevel):
    def __init__(self, parent, fis_id: int):
        super().__init__(parent)
        self.fis_id = fis_id
        self.result = None
        self.title("Muhasebe hesabı ata")
        self.geometry("420x220")
        self.transient(parent)
        self.grab_set()
        try:
            from ui_pencere import pencere_os_krom_ac

            pencere_os_krom_ac(self)
        except Exception:
            pass

        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="both", expand=True)
        ttk.Label(
            frm,
            text="Hesap kodu (ör. 660.01.0001). Yeni gider fişi oluşmaz.",
            wraplength=380,
        ).pack(anchor="w")
        self.kod = ttk.Entry(frm, width=28)
        self.kod.pack(anchor="w", pady=8)
        self.krediye = tk.BooleanVar(value=True)
        self.firmaya = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frm, text="Bu kredi için varsayılan kaydet", variable=self.krediye
        ).pack(anchor="w")
        ttk.Checkbutton(
            frm, text="Firma eşlemesine de kaydet", variable=self.firmaya
        ).pack(anchor="w")
        alt = ttk.Frame(frm)
        alt.pack(fill="x", pady=(12, 0))
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(alt, text="Kaydet", command=self.kaydet).pack(side="right")

    def kaydet(self):
        kod = (self.kod.get() or "").strip()
        if not kod:
            messagebox.showwarning("Hesap", "Hesap kodu girin.", parent=self)
            return
        try:
            self.result = KrediGiderFisiService.hesap_ata(
                self.fis_id,
                hesap_kodu=kod,
                krediye_kaydet=bool(self.krediye.get()),
                firma_eslemeye_kaydet=bool(self.firmaya.get()),
            )
        except Exception as exc:
            messagebox.showerror("Hesap", str(exc), parent=self)
            return
        messagebox.showinfo(
            "Hesap",
            f"Atandı: {self.result['yeni']['kod']} — {self.result['yeni'].get('ad') or ''}\n"
            "Yeni gider kaydı oluşturulmadı.",
            parent=self,
        )
        self.destroy()
