"""Ürün aramasından kısa yeni ürün kaydı (satırın altında açılan kompakt panel).

Kart mevcut ``StokService.stok_kaydi`` ile oluşturulur: açılış stoku, stok hareketi,
cari veya muhasebe etkisi yoktur; evrak kaydedilmez. Kayıt ``yalniz_yeni`` ile yapılır,
böylece aynı kodlu bir kart (eşzamanlı kayıt dahil) asla üzerine yazılmaz.
"""
from __future__ import annotations

import re
import tkinter as tk
from decimal import Decimal, InvalidOperation
from tkinter import messagebox, ttk
from typing import Any, Callable

BIRIM_VARSAYILAN = ("Adet", "Kg", "Metre", "Koli", "Paket", "Torba", "Boy", "Top", "Litre")


def metin_turu(metin: str) -> str:
    """Yazılan arama metninin türü: barkod | kod | ad."""
    m = (metin or "").strip()
    if not m:
        return "ad"
    if m.isdigit() and len(m) >= 8:
        return "barkod"
    if " " not in m and re.search(r"\d", m) and re.search(r"[A-Za-zÇĞİÖŞÜçğıöşü]", m):
        return "kod"
    if " " not in m and re.fullmatch(r"[A-Z0-9][A-Z0-9._\-/]*", m) and any(c in m for c in "-_./"):
        return "kod"
    return "ad"


def on_doldurma(metin: str) -> dict[str, str]:
    tur = metin_turu(metin)
    m = (metin or "").strip()
    return {
        "stok_adi": m if tur == "ad" else "",
        "stok_kodu": m if tur == "kod" else "",
        "barkod": m if tur == "barkod" else "",
    }


def _secenekler(tur: str, varsayilan: tuple[str, ...] = ()) -> list[str]:
    try:
        from database.stok_service import StokService

        liste = [s for s in StokService.secenekleri_listele(tur) if s]
    except Exception:
        liste = []
    for v in varsayilan:
        if v not in liste:
            liste.append(v)
    return liste


def _otomatik_kod() -> str:
    from database.stok_service import StokService

    return StokService.ean13_olustur()


def kisa_stok_olustur(veri: dict[str, Any], *, kaynak: str = "Satın Alma – Kısa Yeni Ürün"):
    """Doğrulanmış veriden kart oluşturur; mevcut kartın üzerine asla yazmaz."""
    from database.stok_service import StokService
    from database.user_audit import audit_document

    barkodlar = None
    if veri.get("barkod"):
        barkodlar = [{"barkod": veri["barkod"], "birim": veri["birim"], "fiyat_adi": "SATIŞ FİYATI 1", "fiyat": "0"}]
    kart = {
        "stok_kodu": veri["stok_kodu"],
        "stok_adi": veri["stok_adi"],
        "birim": veri["birim"],
        "kdv_orani": veri["kdv_orani"],
        "rapor_grubu": veri.get("rapor_grubu") or None,
        "kart_turu": "Ticari Mal",
        "minimum_stok": "0",
        "yalniz_yeni": True,
    }
    stok = StokService.stok_kaydi(kart, [], birimler=None, barkodlar=barkodlar)
    try:
        StokService._teklif_arama_onbellek.clear()
    except Exception:
        pass
    try:
        audit_document(
            "KISA_STOK_OLUSTUR", modul="stok", kayit_id=str(getattr(stok, "id", "")), belge_no=stok.stok_kodu,
            yeni={"kaynak": kaynak, "stok_kodu": stok.stok_kodu, "stok_adi": stok.stok_adi},
        )
    except Exception:
        pass
    return StokService.stok_getir(stok.id) or stok


class KisaUrunPaneli(tk.Toplevel):
    def __init__(self, dialog, metin: str, *, cipa=None, ayrintili: Callable[[str], Any] | None = None):
        super().__init__(dialog.winfo_toplevel())
        self.dialog = dialog
        self.result = None
        self._ayrintili = ayrintili
        self._kaydediliyor = False
        self._olusan = None  # kart oluştuysa tekrar denemede ikinci kart açılmaz
        self.title("Yeni Ürün Ekle")
        self.transient(dialog.winfo_toplevel())
        self.resizable(False, False)
        self.configure(bg="#0B2A4A")

        from database.fatura_kdv_service import firma_varsayilan_kdv_orani

        try:
            kdv_vars = f"{Decimal(str(firma_varsayilan_kdv_orani())).normalize():f}"
        except Exception:
            kdv_vars = "20"
        dolu = on_doldurma(metin)

        govde = tk.Frame(self, bg="#FFFFFF", padx=10, pady=8)
        govde.pack(fill="both", expand=True, padx=1, pady=1)
        tk.Label(govde, text="Yeni Ürün Ekle", bg="#FFFFFF", fg="#0B2A4A",
                 font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 6))

        def _etiket(metin_, satir, sutun):
            tk.Label(govde, text=metin_, bg="#FFFFFF", fg="#334155", font=("Segoe UI", 9)).grid(
                row=satir, column=sutun, sticky="w", padx=(0 if sutun == 0 else 12, 4), pady=2)

        _etiket("Ürün adı *", 1, 0)
        self.ad = ttk.Entry(govde, width=36)
        self.ad.grid(row=1, column=1, columnspan=3, sticky="we", pady=2)
        _etiket("Stok kodu", 2, 0)
        self.kod = ttk.Entry(govde, width=18)
        self.kod.grid(row=2, column=1, sticky="we", pady=2)
        _etiket("Barkod", 2, 2)
        self.barkod = ttk.Entry(govde, width=18)
        self.barkod.grid(row=2, column=3, sticky="we", pady=2)
        _etiket("Birim", 3, 0)
        self.birim = ttk.Combobox(govde, width=16, values=_secenekler("birim", BIRIM_VARSAYILAN))
        self.birim.grid(row=3, column=1, sticky="we", pady=2)
        _etiket("KDV %", 3, 2)
        self.kdv = ttk.Combobox(govde, width=16, values=("0", "1", "10", "20"))
        self.kdv.grid(row=3, column=3, sticky="we", pady=2)
        _etiket("Ürün grubu", 4, 0)
        self.grup = ttk.Combobox(govde, width=16, values=_secenekler("rapor_grubu"))
        self.grup.grid(row=4, column=1, sticky="we", pady=2)
        self.kod_bilgi = tk.Label(govde, text="", bg="#FFFFFF", fg="#64748B", font=("Segoe UI", 8))
        self.kod_bilgi.grid(row=4, column=2, columnspan=2, sticky="w", padx=(12, 0))
        self.hata_lbl = tk.Label(govde, text="", bg="#FFFFFF", fg="#B91C1C", font=("Segoe UI", 8),
                                 wraplength=420, justify="left")
        self.hata_lbl.grid(row=5, column=0, columnspan=4, sticky="w")

        self.ad.insert(0, dolu["stok_adi"])
        if dolu["stok_kodu"]:
            self.kod.insert(0, dolu["stok_kodu"])
            self._oto_kod = False
        else:
            try:
                self.kod.insert(0, _otomatik_kod())
                self._oto_kod = True
                self.kod_bilgi.configure(text="Stok kodu otomatik üretildi; değiştirebilirsiniz.")
            except Exception:
                self._oto_kod = False
        self.barkod.insert(0, dolu["barkod"])
        self.birim.set("Adet")
        self.kdv.set(kdv_vars)

        alt = tk.Frame(govde, bg="#FFFFFF")
        alt.grid(row=6, column=0, columnspan=4, sticky="we", pady=(8, 0))
        self.kaydet_btn = tk.Button(
            alt, text="Kaydet ve Satıra Ekle", command=self.kaydet, bg="#0B2A4A", fg="#FFD84D",
            activebackground="#163E68", activeforeground="#FFD84D", relief="flat", padx=12, pady=4,
            font=("Segoe UI", 9, "bold"),
        )
        self.kaydet_btn.pack(side="right")
        ttk.Button(alt, text="Vazgeç", command=self.vazgec).pack(side="right", padx=6)
        if ayrintili is not None:
            ttk.Button(alt, text="Ayrıntılı Stok Kartı", command=self._ayrintili_ac).pack(side="left")

        self.bind("<Return>", lambda _e: self.kaydet())
        self.bind("<Escape>", lambda _e: self.vazgec())
        self.protocol("WM_DELETE_WINDOW", self.vazgec)
        self._konumla(cipa)
        (self.kod if dolu["stok_kodu"] and not dolu["stok_adi"] else self.ad).focus_set()
        if not dolu["stok_adi"]:
            self.ad.focus_set()

    def _konumla(self, cipa) -> None:
        try:
            self.update_idletasks()
            if cipa is not None:
                x = cipa.winfo_rootx()
                y = cipa.winfo_rooty() + cipa.winfo_height() + 2
            else:
                ust = self.dialog.winfo_toplevel()
                x, y = ust.winfo_rootx() + 60, ust.winfo_rooty() + 120
            w, h = self.winfo_reqwidth(), self.winfo_reqheight()
            ew, eh = self.winfo_screenwidth(), self.winfo_screenheight()
            if x + w > ew - 8:
                x = max(8, ew - w - 8)
            if y + h > eh - 48:
                y = max(8, y - h - 40)
            self.geometry(f"+{x}+{y}")
            self.grab_set()
        except tk.TclError:
            pass

    # ─── doğrulama
    def _veri(self) -> dict[str, Any]:
        from database.stok_kodu_barkod_service import normalize_stock_code_as_text

        ad = self.ad.get().strip()
        kod = normalize_stock_code_as_text(self.kod.get()).strip()
        barkod = normalize_stock_code_as_text(self.barkod.get()).strip()
        if not ad:
            raise ValueError("Ürün adı zorunludur.")
        if (barkod and ad == barkod) or metin_turu(ad) == "barkod":
            raise ValueError("Barkod ürün adı olarak kaydedilemez; ürün adını yazın.")
        if not kod:
            kod = _otomatik_kod()
        try:
            kdv = Decimal((self.kdv.get() or "20").replace("%", "").replace(",", ".").strip())
        except InvalidOperation:
            raise ValueError("KDV oranı sayı olmalıdır.") from None
        if kdv < 0 or kdv > 100:
            raise ValueError("KDV oranı 0–100 arasında olmalıdır.")
        return {
            "stok_adi": ad,
            "stok_kodu": kod,
            "barkod": barkod,
            "birim": (self.birim.get() or "Adet").strip() or "Adet",
            "kdv_orani": kdv,
            "rapor_grubu": (self.grup.get() or "").strip() or None,
        }

    def _mevcut_sec(self, stok, neden: str) -> bool:
        return messagebox.askyesno(
            "Kayıtlı ürün",
            f"{neden}\n{getattr(stok, 'stok_kodu', '')} — {getattr(stok, 'stok_adi', '')}\n\n"
            "Mevcut kart satıra eklensin mi?",
            parent=self,
        )

    @staticmethod
    def _tam_kart(stok):
        from database.stok_service import StokService

        sid = getattr(stok, "id", None)
        return (StokService.stok_getir(sid) if sid else None) or stok

    # ─── eylemler
    def kaydet(self) -> None:
        if self._kaydediliyor:
            return
        if self._olusan is not None:
            self.result = self._olusan
            self.destroy()
            return
        try:
            veri = self._veri()
        except ValueError as hata:
            self.hata_lbl.configure(text=str(hata))
            return
        from hizli_stok_karti_ui import mukerrer_kontrol

        self._kaydediliyor = True
        self.kaydet_btn.configure(state="disabled")
        try:
            kontrol = mukerrer_kontrol(stok_kodu=veri["stok_kodu"], barkod=veri["barkod"], stok_adi=veri["stok_adi"])
            if kontrol["barkod_cakisma"] is not None:
                if self._mevcut_sec(kontrol["barkod_cakisma"], "Bu barkod başka bir kartta kayıtlı:"):
                    self.result = self._tam_kart(kontrol["barkod_cakisma"])
                    self.destroy()
                return
            if kontrol["kod_cakisma"] is not None:
                if self._oto_kod and veri["stok_kodu"] == self.kod.get().strip():
                    veri["stok_kodu"] = _otomatik_kod()
                elif self._mevcut_sec(kontrol["kod_cakisma"], "Bu stok kodu başka bir kartta kayıtlı:"):
                    self.result = self._tam_kart(kontrol["kod_cakisma"])
                    self.destroy()
                    return
                else:
                    self.hata_lbl.configure(text="Stok kodu kullanılıyor; farklı bir kod girin.")
                    return
            ayni = [s for s in kontrol["benzer_adlar"]
                    if (s.stok_adi or "").strip().casefold() == veri["stok_adi"].casefold()]
            if ayni:
                cevap = messagebox.askyesnocancel(
                    "Aynı adlı ürün",
                    f"Aynı adlı kart var: {ayni[0].stok_kodu} — {ayni[0].stok_adi}\n\n"
                    "Evet: Mevcut kartı satıra ekle\nHayır: Yine de yeni kart oluştur\nİptal: Geri dön",
                    parent=self,
                )
                if cevap is None:
                    return
                if cevap:
                    self.result = self._tam_kart(ayni[0])
                    self.destroy()
                    return
            try:
                self._olusan = kisa_stok_olustur(veri)
            except ValueError as hata:
                self.hata_lbl.configure(text=str(hata))
                return
            except Exception as hata:  # noqa: BLE001
                self.hata_lbl.configure(text=f"Kayıt yapılamadı: {hata}")
                return
            self.result = self._olusan
            self.destroy()
        finally:
            self._kaydediliyor = False
            try:
                if self.winfo_exists():
                    self.kaydet_btn.configure(state="normal")
            except tk.TclError:
                pass

    def vazgec(self) -> None:
        self.result = self._olusan
        self.destroy()

    def _ayrintili_ac(self) -> None:
        metin = self.ad.get().strip() or self.barkod.get().strip()
        self.destroy()
        if self._ayrintili is not None:
            self.result = self._ayrintili(metin)


def kisa_urun_paneli_ac(dialog, metin: str = "", *, cipa=None, ayrintili: Callable[[str], Any] | None = None):
    """Paneli açar ve kapanana kadar bekler; kaydedilen/seçilen kartı (yoksa None) döner."""
    try:
        from database.access import yetki_var

        if not yetki_var("stok_duzenleme", "yeni_kayit"):
            messagebox.showwarning("Yetki", "Stok kartı oluşturma yetkiniz yok.", parent=dialog)
            return None
    except Exception:
        pass
    panel = KisaUrunPaneli(dialog, metin, cipa=cipa, ayrintili=ayrintili)
    dialog.wait_window(panel)
    return panel.result
