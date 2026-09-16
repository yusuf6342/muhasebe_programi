"""Teklif — stokta olmayan manuel ürün ekleme / düzenleme penceresi."""

from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from tkinter import messagebox, ttk
from typing import Any, Callable

from database.access import maliyet_izinli, yetki_var
from database.models.stok import VARSAYILAN_KDV_ORANI
from database.stok_service import StokService

# Mevcut birim kartları + teklif için genişletilmiş liste (serbest yazım yok)
TEKLIF_MANUEL_BIRIMLER = (
    "Adet",
    "Takım",
    "Set",
    "Çift",
    "Paket",
    "Koli",
    "Kutu",
    "Torba",
    "Kilogram",
    "Gram",
    "Metre",
    "Santimetre",
    "Boy",
    "Top",
    "Litre",
    "Mililitre",
    "Metrekare",
    "Hizmet",
    "Kg",
)

KDV_SECENEKLERI = ("0", "1", "8", "10", "18", "20")

TERMIN_ORNEKLERI = (
    "",
    "7–10 iş günü",
    "Siparişe özel üretim",
    "Tedarikçi teyidi bekleniyor",
    "Termin daha sonra bildirilecek",
    "İthalat süresine bağlıdır",
)

LINE_TYPE_MANUAL = "MANUAL_PRODUCT"
COST_OK = "OK"
COST_EKSIK = "EKSIK"
COST_TAHMINI = "TAHMINI"


def manuel_birim_listesi() -> list[str]:
    try:
        ekstra = list(StokService.secenekleri_listele("birim") or [])
    except Exception:
        ekstra = []
    return list(dict.fromkeys([*TEKLIF_MANUEL_BIRIMLER, *ekstra]))


def _d(metin, alan="Değer") -> Decimal:
    m = str(metin or "").strip().replace(" ", "")
    if not m:
        return Decimal("0")
    if "," in m:
        m = m.replace(".", "").replace(",", ".")
    try:
        return Decimal(m)
    except InvalidOperation as exc:
        raise ValueError(f"{alan} geçerli değil.") from exc


class ManuelUrunDialog(tk.Toplevel):
    """STOKTA OLMAYAN ÜRÜN EKLE — zorunlu: ad, birim, miktar, KDV."""

    def __init__(
        self,
        parent,
        *,
        baslangic: dict[str, Any] | None = None,
        on_save: Callable[[dict], None] | None = None,
        duzenle: bool = False,
    ):
        super().__init__(parent)
        self.title("STOKTA OLMAYAN ÜRÜN EKLE" if not duzenle else "MANUEL ÜRÜN DÜZENLE")
        self.geometry("560x640")
        self.transient(parent)
        self.grab_set()
        self.on_save = on_save
        self.result: dict | None = None
        self._baslangic = dict(baslangic or {})
        self._alanlar: dict[str, Any] = {}
        self._hata_stil = {"highlightthickness": 2, "highlightbackground": "#C62828", "highlightcolor": "#C62828"}

        ust = ttk.Frame(self, padding=10)
        ust.pack(fill="x")
        ttk.Label(
            ust,
            text="Stok kartı oluşturulmaz. Ürün yalnız bu teklif satırına eklenir.",
            wraplength=520,
        ).pack(anchor="w")

        govde = ttk.Frame(self, padding=(10, 0, 10, 10))
        govde.pack(fill="both", expand=True)
        canvas = tk.Canvas(govde, highlightthickness=0)
        scroll = ttk.Scrollbar(govde, orient="vertical", command=canvas.yview)
        form = ttk.Frame(canvas)
        form.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=form, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        r = 0
        r = self._entry(form, r, "urun_adi", "Ürün Adı *", width=48, zorunlu=True)
        r = self._text(form, r, "aciklama", "Açıklama", height=2)
        r = self._entry(form, r, "marka", "Marka", width=28)
        r = self._entry(form, r, "model", "Model", width=28)
        r = self._entry(form, r, "uretici_kodu", "Üretici Kodu", width=28)
        r = self._entry(form, r, "barkod", "Barkod", width=28)
        r = self._entry(form, r, "miktar", "Miktar *", width=14, zorunlu=True, default="1")
        r = self._combo(form, r, "birim", "Birim *", manuel_birim_listesi(), zorunlu=True, default="Adet")

        maliyet_cerceve = ttk.LabelFrame(form, text="Alış / Maliyet (iç hesaplama)", padding=6)
        maliyet_cerceve.grid(row=r, column=0, columnspan=2, sticky="ew", pady=6)
        r += 1
        if maliyet_izinli():
            self._entry(maliyet_cerceve, 0, "alis_birim", "Alış Birim Fiyatı", width=14)
            self._combo(
                maliyet_cerceve, 1, "alis_pb", "Alış Para Birimi", ["TRY", "USD", "EUR"], default="TRY"
            )
            self._entry(maliyet_cerceve, 2, "alis_kur", "Alış Kuru", width=12, default="1")
            ttk.Label(maliyet_cerceve, text="Tahmini Alış Maliyeti").grid(row=3, column=0, sticky="w", pady=2)
            self.lbl_tahmini = ttk.Label(maliyet_cerceve, text="—")
            self.lbl_tahmini.grid(row=3, column=1, sticky="w", padx=4)
            for w in (self._alanlar.get("alis_birim"), self._alanlar.get("alis_kur"), self._alanlar.get("miktar")):
                if w:
                    w.bind("<KeyRelease>", lambda _e: self._tahmini_guncelle())
        else:
            ttk.Label(
                maliyet_cerceve,
                text="Alış maliyeti görme yetkiniz yok.",
                foreground="#64748B",
            ).grid(row=0, column=0, sticky="w")
            self.lbl_tahmini = None

        r = self._entry(form, r, "teklif_fiyat", "Teklif Birim Fiyatı", width=14)
        r = self._combo(
            form,
            r,
            "kdv",
            "KDV Oranı *",
            list(KDV_SECENEKLERI),
            zorunlu=True,
            default=str(int(VARSAYILAN_KDV_ORANI)),
        )
        r = self._entry(form, r, "iskonto", "Satır İskontosu %", width=10, default="0")
        r = self._entry(form, r, "termin_gun", "Termin Süresi (Gün)", width=10)
        r = self._entry(form, r, "termin_tarih", "Tahmini Teslim Tarihi", width=14)
        r = self._combo(form, r, "termin_not", "Termin Açıklaması", list(TERMIN_ORNEKLERI), default="")
        r = self._text(form, r, "tedarikci_not", "Tedarikçi Açıklaması", height=2)
        r = self._text(form, r, "ic_not", "İç Not", height=2)
        r = self._text(form, r, "musteri_aciklama", "Müşteri Açıklaması", height=2)

        self.donustur_var = tk.BooleanVar(value=bool(self._baslangic.get("convert_later")))
        ttk.Checkbutton(
            form,
            text="Stok Kartına Daha Sonra Dönüştürülsün",
            variable=self.donustur_var,
        ).grid(row=r, column=0, columnspan=2, sticky="w", pady=6)

        alt = ttk.Frame(self, padding=10)
        alt.pack(fill="x")
        ttk.Button(alt, text="Vazgeç", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(alt, text="Teklife Ekle" if not duzenle else "Kaydet", command=self._kaydet).pack(
            side="right", padx=4
        )

        self._doldur(self._baslangic)
        self._tahmini_guncelle()
        self.after(50, lambda: self._alanlar["urun_adi"].focus_set())

    def _entry(self, parent, row, key, label, width=20, zorunlu=False, default=""):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=2)
        e = ttk.Entry(parent, width=width)
        e.grid(row=row, column=1, sticky="ew", padx=4, pady=2)
        if default and key not in self._baslangic:
            e.insert(0, default)
        self._alanlar[key] = e
        self._alanlar[f"_{key}_zorunlu"] = zorunlu
        return row + 1

    def _combo(self, parent, row, key, label, values, zorunlu=False, default=""):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=2)
        c = ttk.Combobox(parent, values=values, width=28, state="readonly")
        c.grid(row=row, column=1, sticky="ew", padx=4, pady=2)
        if default:
            c.set(default)
        self._alanlar[key] = c
        self._alanlar[f"_{key}_zorunlu"] = zorunlu
        return row + 1

    def _text(self, parent, row, key, label, height=2):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="nw", pady=2)
        t = tk.Text(parent, height=height, width=40)
        t.grid(row=row, column=1, sticky="ew", padx=4, pady=2)
        self._alanlar[key] = t
        return row + 1

    def _get(self, key: str) -> str:
        w = self._alanlar.get(key)
        if w is None:
            return ""
        if isinstance(w, tk.Text):
            return w.get("1.0", "end").strip()
        return str(w.get()).strip()

    def _set(self, key: str, deger):
        w = self._alanlar.get(key)
        if w is None or deger is None:
            return
        if isinstance(w, tk.Text):
            w.delete("1.0", "end")
            w.insert("1.0", str(deger))
        elif isinstance(w, ttk.Combobox):
            w.set(str(deger))
        else:
            w.delete(0, "end")
            w.insert(0, str(deger))

    def _doldur(self, d: dict):
        esle = {
            "urun_adi": d.get("urun_adi") or d.get("manual_product_name") or "",
            "aciklama": d.get("aciklama") or d.get("manual_description") or d.get("customer_note") or "",
            "marka": d.get("marka") or d.get("manual_brand") or "",
            "model": d.get("model") or d.get("manual_model") or "",
            "uretici_kodu": d.get("manual_manufacturer_code") or "",
            "barkod": d.get("manual_barcode") or "",
            "miktar": d.get("miktar", "1"),
            "birim": d.get("birim") or d.get("unit_name_snapshot") or "Adet",
            "alis_birim": d.get("estimated_purchase_unit_price")
            or d.get("purchase_unit_price_base")
            or d.get("birim_maliyet")
            or "",
            "alis_pb": d.get("purchase_currency") or "TRY",
            "alis_kur": d.get("purchase_exchange_rate") or "1",
            "teklif_fiyat": d.get("teklif_fiyati") or d.get("manual_offer_unit_price") or "",
            "kdv": str(d.get("kdv_orani") or int(VARSAYILAN_KDV_ORANI)).rstrip("0").rstrip(".")
            if d.get("kdv_orani") is not None
            else str(int(VARSAYILAN_KDV_ORANI)),
            "iskonto": d.get("iskonto_orani", "0"),
            "termin_gun": d.get("delivery_term_days") or "",
            "termin_tarih": d.get("estimated_delivery_date") or "",
            "termin_not": d.get("delivery_term_note") or "",
            "tedarikci_not": d.get("supplier_note") or "",
            "ic_not": d.get("internal_note") or "",
            "musteri_aciklama": d.get("customer_note") or d.get("aciklama") or "",
        }
        for k, v in esle.items():
            if v == "" or v is None:
                continue
            if hasattr(v, "isoformat"):
                v = v.isoformat()
            self._set(k, v)
        # KDV sayısal format
        kdv = self._get("kdv")
        if kdv.endswith(".0"):
            self._set("kdv", kdv[:-2])

    def _temizle_hata(self, key: str):
        w = self._alanlar.get(key)
        if w is None:
            return
        try:
            w.configure(highlightthickness=0)
        except tk.TclError:
            pass

    def _isaretle_hata(self, key: str):
        w = self._alanlar.get(key)
        if w is None:
            return
        try:
            w.configure(**self._hata_stil)
            w.focus_set()
        except tk.TclError:
            try:
                w.focus_set()
            except tk.TclError:
                pass

    def _tahmini_guncelle(self):
        if not self.lbl_tahmini:
            return
        try:
            miktar = _d(self._get("miktar") or "0")
            alis = _d(self._get("alis_birim") or "0")
            kur = _d(self._get("alis_kur") or "1")
            if kur <= 0:
                kur = Decimal("1")
            tahmini = (alis * kur * miktar).quantize(Decimal("0.01"))
            self.lbl_tahmini.configure(text=f"{tahmini} {self._get('alis_pb') or 'TRY'}")
        except Exception:
            self.lbl_tahmini.configure(text="—")

    def _kaydet(self):
        for k in ("urun_adi", "birim", "miktar", "kdv"):
            self._temizle_hata(k)

        ad = self._get("urun_adi")
        if not ad:
            self._isaretle_hata("urun_adi")
            messagebox.showwarning("Zorunlu Alan", "Ürün adı zorunludur.", parent=self)
            return
        birim = self._get("birim")
        if not birim:
            self._isaretle_hata("birim")
            messagebox.showwarning("Zorunlu Alan", "Ürün birimi zorunludur.", parent=self)
            return
        if birim not in manuel_birim_listesi():
            self._isaretle_hata("birim")
            messagebox.showwarning(
                "Birim",
                "Lütfen listedeki birimlerden birini seçin.",
                parent=self,
            )
            return
        try:
            miktar = _d(self._get("miktar"), "Miktar")
        except ValueError as exc:
            self._isaretle_hata("miktar")
            messagebox.showwarning("Miktar", str(exc), parent=self)
            return
        if miktar <= 0:
            self._isaretle_hata("miktar")
            messagebox.showwarning("Miktar", "Miktar sıfırdan büyük olmalıdır.", parent=self)
            return
        kdv_metin = self._get("kdv") or str(int(VARSAYILAN_KDV_ORANI))
        try:
            kdv = _d(kdv_metin, "KDV")
        except ValueError as exc:
            self._isaretle_hata("kdv")
            messagebox.showwarning("KDV", str(exc), parent=self)
            return

        alis = Decimal("0")
        kur = Decimal("1")
        pb = "TRY"
        if maliyet_izinli() and "alis_birim" in self._alanlar:
            try:
                alis = _d(self._get("alis_birim") or "0", "Alış")
                kur = _d(self._get("alis_kur") or "1", "Kur")
                if kur <= 0:
                    kur = Decimal("1")
                pb = self._get("alis_pb") or "TRY"
            except ValueError as exc:
                messagebox.showwarning("Alış", str(exc), parent=self)
                return
        elif not maliyet_izinli():
            # Yetkisiz: maliyet taşıma
            alis = Decimal("0")

        base = (alis * kur).quantize(Decimal("0.0001"))
        cost_status = COST_TAHMINI if base > 0 else COST_EKSIK

        teklif_fiyat = Decimal("0")
        tf = self._get("teklif_fiyat")
        is_manual_price = False
        if tf:
            try:
                teklif_fiyat = _d(tf, "Teklif fiyatı")
                is_manual_price = True
            except ValueError as exc:
                messagebox.showwarning("Fiyat", str(exc), parent=self)
                return

        try:
            isk = _d(self._get("iskonto") or "0", "İskonto")
        except ValueError as exc:
            messagebox.showwarning("İskonto", str(exc), parent=self)
            return

        termin_gun = None
        tg = self._get("termin_gun")
        if tg:
            try:
                termin_gun = int(tg)
            except ValueError:
                messagebox.showwarning("Termin", "Termin günü sayı olmalıdır.", parent=self)
                return

        termin_tarih = None
        tt = self._get("termin_tarih")
        if tt:
            try:
                termin_tarih = date.fromisoformat(tt.replace(".", "-")[:10])
            except ValueError:
                messagebox.showwarning(
                    "Termin",
                    "Teslim tarihi YYYY-MM-DD formatında olmalıdır.",
                    parent=self,
                )
                return
        elif termin_gun is not None:
            termin_tarih = date.today() + timedelta(days=termin_gun)

        musteri_ack = self._get("musteri_aciklama") or self._get("aciklama")
        veri = {
            "is_manual_item": True,
            "manuel": True,
            "line_type": LINE_TYPE_MANUAL,
            "product_id": None,
            "stok_id": None,
            "urun_kodu": "MANUEL",
            "urun_adi": ad,
            "manual_product_name": ad,
            "aciklama": musteri_ack or None,
            "manual_description": self._get("aciklama") or None,
            "marka": self._get("marka") or None,
            "manual_brand": self._get("marka") or None,
            "varyant": self._get("model") or None,
            "manual_model": self._get("model") or None,
            "manual_manufacturer_code": self._get("uretici_kodu") or None,
            "manual_barcode": self._get("barkod") or None,
            "miktar": miktar,
            "birim": birim,
            "unit_name_snapshot": birim,
            "estimated_purchase_unit_price": base if base > 0 else None,
            "birim_maliyet": base,
            "purchase_unit_price": alis,
            "purchase_currency": pb,
            "purchase_exchange_rate": kur,
            "purchase_unit_price_base": base,
            "purchase_total_cost": (base * miktar).quantize(Decimal("0.01")),
            "maliyet_kaynagi": "MANUEL" if base > 0 else "EKSIK",
            "cost_status": cost_status,
            "teklif_fiyati": teklif_fiyat,
            "manual_offer_unit_price": teklif_fiyat if is_manual_price else None,
            "is_manual_price": is_manual_price,
            "kdv_orani": kdv,
            "iskonto_orani": isk,
            "delivery_term_days": termin_gun,
            "estimated_delivery_date": termin_tarih,
            "delivery_term_note": self._get("termin_not") or None,
            "supplier_note": self._get("tedarikci_not") or None,
            "internal_note": self._get("ic_not") or None,
            "customer_note": musteri_ack or None,
            "stock_conversion_status": "BEKLIYOR" if self.donustur_var.get() else None,
            "hizmet_satiri": birim.casefold() == "hizmet",
        }
        if cost_status == COST_EKSIK and yetki_var("maliyet_gorma", "satis_duzenleme"):
            messagebox.showwarning(
                "Maliyet",
                "Manuel ürünün alış maliyeti girilmemiştir. "
                "Teklif kaydedilebilir ancak kâr ve marj analizi eksik olacaktır.",
                parent=self,
            )

        self.result = veri
        if self.on_save:
            self.on_save(veri)
        self.destroy()
