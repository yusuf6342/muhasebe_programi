"""Tedarikçi cari kartı — Haftalık Ödeme (N Cuma taksiti + ödeme mahsubu)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

import tkinter as tk
from tkinter import messagebox, ttk

from database.haftalik_odeme_service import (
    ODEME_YONTEM_HAVALE,
    ODEME_YONTEM_KART,
    ODEME_YONTEM_NAKIT,
    TAKSIT_ADET,
    HaftalikOdemeService,
    hafta_araligi,
    taksit_adet_dogrula,
)
from tutar_bicim import tr_tutar, tutar_alani, tutar_coz


def _tl(deger) -> str:
    try:
        d = Decimal(str(deger or 0))
    except Exception:
        d = Decimal("0")
    return f"{d:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _tr_tarih(d: date | None) -> str:
    if not d:
        return ""
    return d.strftime("%d.%m.%Y")


class HaftalikOdemeDialog(tk.Toplevel):
    """Önceki kalan + bu hafta açık + toplam; taksit sayısı ayarlanabilir."""

    def __init__(self, parent, cari, referans: date | None = None):
        super().__init__(parent)
        self.parent = parent
        self.cari = cari
        self.cari_id = int(cari.id)
        self.cari_adi = f"{getattr(cari, 'cari_kodu', '')} — {getattr(cari, 'unvan', '')}"
        self._ref = referans or date.today()
        self._taksit_adet = TAKSIT_ADET
        self._yenile_askida = False
        self.title(f"Haftalık Ödeme — {self.cari_adi}")
        self.geometry("1180x720")
        self.minsize(960, 560)
        self.protocol("WM_DELETE_WINDOW", self._kapat)

        govde = ttk.Frame(self, padding=10)
        govde.pack(fill="both", expand=True)

        ttk.Label(govde, text=self.cari_adi, font=("Segoe UI", 11, "bold")).pack(
            anchor="w"
        )
        ttk.Label(
            govde,
            text=(
                "Açılış + alış faturaları seçilen sayıda Cuma taksitine bölünür. "
                "Ödemeler en eski açık vadeden mahsup edilir. "
                "Toplam ödenecek = önceki kalan + bu haftanın açık taksitleri."
            ),
            foreground="#667085",
        ).pack(anchor="w", pady=(2, 8))

        ust = ttk.Frame(govde)
        ust.pack(fill="x", pady=(0, 6))
        ttk.Label(ust, text="Hafta").pack(side="left")
        self.hafta_var = tk.StringVar()
        self.hafta_cb = ttk.Combobox(
            ust, textvariable=self.hafta_var, state="readonly", width=32
        )
        self.hafta_cb.pack(side="left", padx=(6, 8))
        self.hafta_cb.bind("<<ComboboxSelected>>", lambda _e: self.yenile(otomatik=True))
        ttk.Button(ust, text="◀", width=3, command=self._onceki_hafta).pack(side="left")
        ttk.Button(ust, text="▶", width=3, command=self._sonraki_hafta).pack(
            side="left", padx=(2, 8)
        )
        ttk.Button(ust, text="Bu hafta", command=self._bu_hafta).pack(side="left")

        # Haftalık taksit sayısı
        ttk.Label(ust, text="Haftalık taksit sayısı").pack(side="left", padx=(16, 4))
        self.taksit_var = tk.StringVar(value=str(TAKSIT_ADET))
        self.taksit_entry = ttk.Entry(ust, textvariable=self.taksit_var, width=5)
        self.taksit_entry.pack(side="left")
        self.taksit_uyari = ttk.Label(ust, text="", foreground="#b91c1c")
        self.taksit_uyari.pack(side="left", padx=(6, 0))
        self.taksit_var.trace_add("write", self._taksit_adet_degisti)

        ttk.Button(ust, text="Yenile / Planla", command=lambda: self.yenile(True)).pack(
            side="right"
        )

        ozet = ttk.Frame(govde)
        ozet.pack(fill="x", pady=(0, 8))
        self._lbl_onceki = self._ozet_kutu(ozet, "Önceki haftalardan kalan")
        self._lbl_bu = self._ozet_kutu(ozet, "Bu haftanın açık taksitleri")
        self._lbl_toplam, self._fr_toplam = self._ozet_kutu(
            ozet, "Toplam ödenecek", vurgu=True, frame_don=True
        )
        ttk.Button(
            self._fr_toplam, text="Ödeme Yap", command=self._odeme_yap_ac
        ).pack(anchor="w", pady=(6, 0))
        self._son_rapor: dict | None = None
        self._toplam_odenecek = Decimal("0")

        self.detay_lbl = ttk.Label(govde, foreground="#334155")
        self.detay_lbl.pack(anchor="w", pady=(0, 6))

        paned = ttk.Panedwindow(govde, orient="vertical")
        paned.pack(fill="both", expand=True)

        ust_p = ttk.Frame(paned)
        paned.add(ust_p, weight=3)
        lf1 = ttk.LabelFrame(ust_p, text="Bu haftanın açık taksitleri", padding=6)
        lf1.pack(fill="both", expand=True)
        self.agac_hafta = self._tablo(lf1)

        lf2 = ttk.LabelFrame(ust_p, text="Önceki haftalardan kalan (gecikmiş)", padding=6)
        lf2.pack(fill="both", expand=True, pady=(8, 0))
        self.agac_onceki = self._tablo(lf2)

        alt_p = ttk.Frame(paned)
        paned.add(alt_p, weight=2)
        self._lf_plan = ttk.LabelFrame(
            alt_p, text=f"Ödeme planı (belge / {TAKSIT_ADET} taksit)", padding=6
        )
        self._lf_plan.pack(side="left", fill="both", expand=True, padx=(0, 4))
        cols_p = ("belge", "tarih", "adet", "valor", "plan", "odenen", "kalan")
        self.agac_plan = ttk.Treeview(
            self._lf_plan, columns=cols_p, show="headings", height=6
        )
        for c, t, w in (
            ("belge", "Fatura", 130),
            ("tarih", "Belge tarihi", 90),
            ("adet", "Taksit", 50),
            ("valor", "Ort. valör", 70),
            ("plan", "Planlanan", 90),
            ("odenen", "Mahsup", 90),
            ("kalan", "Kalan", 90),
        ):
            self.agac_plan.heading(c, text=t)
            self.agac_plan.column(c, width=w, anchor="center")
        self.agac_plan.pack(fill="both", expand=True)

        lf4 = ttk.LabelFrame(alt_p, text="Gelecek haftalara kalan (özet)", padding=6)
        lf4.pack(side="left", fill="both", expand=True, padx=(4, 0))
        self.lbl_gelecek = ttk.Label(lf4, font=("Segoe UI", 10))
        self.lbl_gelecek.pack(anchor="w", pady=4)
        self.agac_gelecek = self._tablo(lf4, height=5)

        self._hafta_seceneklerini_doldur()
        self.yenile(otomatik=True)
        try:
            self.transient(parent)
            self.grab_set()
        except tk.TclError:
            pass

    def _ozet_kutu(
        self, parent, baslik: str, vurgu: bool = False, *, frame_don: bool = False
    ):
        fr = ttk.LabelFrame(parent, text=baslik, padding=8)
        fr.pack(side="left", fill="x", expand=True, padx=(0, 6))
        lbl = ttk.Label(
            fr,
            text="0,00 TL",
            font=("Segoe UI", 14, "bold"),
            foreground="#1d4ed8" if vurgu else "#0f172a",
        )
        lbl.pack(anchor="w")
        if frame_don:
            return lbl, fr
        return lbl

    def _tablo(self, parent, height: int = 7) -> ttk.Treeview:
        cols = ("belge", "sira", "vade", "plan", "odenen", "kalan")
        agac = ttk.Treeview(parent, columns=cols, show="headings", height=height)
        for c, t, w in (
            ("belge", "Belge no", 140),
            ("sira", "Taksit", 60),
            ("vade", "Vade", 95),
            ("plan", "Planlanan", 95),
            ("odenen", "Mahsup", 95),
            ("kalan", "Kalan", 95),
        ):
            agac.heading(c, text=t)
            agac.column(c, width=w, anchor="center")
        sb = ttk.Scrollbar(parent, orient="vertical", command=agac.yview)
        agac.configure(yscrollcommand=sb.set)
        agac.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return agac

    def _hafta_etiket(self, bas: date, bit: date) -> str:
        return f"{_tr_tarih(bas)} – {_tr_tarih(bit)}"

    def _hafta_seceneklerini_doldur(self) -> None:
        bugun_bas, _ = hafta_araligi(date.today())
        secenekler = []
        self._hafta_map: dict[str, date] = {}
        for i in range(-16, 9):
            bas = bugun_bas + timedelta(days=7 * i)
            bit = bas + timedelta(days=6)
            etiket = self._hafta_etiket(bas, bit)
            if i == 0:
                etiket = f"{etiket} (bu hafta)"
            secenekler.append(etiket)
            self._hafta_map[etiket] = bas
        self.hafta_cb["values"] = secenekler
        hedef_bas, _ = hafta_araligi(self._ref)
        for etiket, bas in self._hafta_map.items():
            if bas == hedef_bas:
                self.hafta_var.set(etiket)
                break
        else:
            self.hafta_var.set(secenekler[16])

    def _secili_referans(self) -> date:
        etiket = self.hafta_var.get()
        bas = self._hafta_map.get(etiket)
        if bas:
            bit = bas + timedelta(days=6)
            bugun = date.today()
            if bas <= bugun <= bit:
                return min(self._ref, bugun) if bas <= self._ref <= bit else bugun
            if bit < bugun:
                return bit
            return bas
        return self._ref

    def _taksit_adet_oku(self) -> int | None:
        ham = (self.taksit_var.get() or "").strip()
        try:
            return taksit_adet_dogrula(ham)
        except ValueError:
            return None

    def _taksit_adet_degisti(self, *_args) -> None:
        if self._yenile_askida:
            return
        adet = self._taksit_adet_oku()
        if adet is None:
            self.taksit_uyari.configure(text="Pozitif tam sayı girin")
            return
        self.taksit_uyari.configure(text="")
        if adet == self._taksit_adet:
            return
        self._taksit_adet = adet
        self.after(50, lambda: self.yenile(otomatik=True))

    def _onceki_hafta(self) -> None:
        bas, _ = hafta_araligi(self._secili_referans())
        self._ref = bas - timedelta(days=7)
        self._hafta_seceneklerini_doldur()
        self.yenile(otomatik=True)

    def _sonraki_hafta(self) -> None:
        bas, _ = hafta_araligi(self._secili_referans())
        self._ref = bas + timedelta(days=7)
        self._hafta_seceneklerini_doldur()
        self.yenile(otomatik=True)

    def _bu_hafta(self) -> None:
        self._ref = date.today()
        self._hafta_seceneklerini_doldur()
        self.yenile(otomatik=True)

    def _satirlari_doldur(self, agac: ttk.Treeview, satirlar: list) -> None:
        agac.delete(*agac.get_children())
        for s in satirlar:
            agac.insert(
                "",
                "end",
                values=(
                    s.get("belge_no") or "",
                    f"{s.get('taksit_no')}/{s.get('taksit_adet')}",
                    _tr_tarih(s.get("vade_tarihi")),
                    _tl(s.get("planlanan_tutar")),
                    _tl(s.get("odenen_tutar")),
                    _tl(s.get("kalan")),
                ),
            )

    def yenile(self, otomatik: bool = True) -> None:
        adet = self._taksit_adet_oku()
        if adet is None:
            self.taksit_uyari.configure(text="Pozitif tam sayı girin")
            return
        self.taksit_uyari.configure(text="")
        self._taksit_adet = adet
        ref = self._secili_referans()
        self._ref = ref
        self._yenile_askida = True
        try:
            rapor = HaftalikOdemeService.haftalik_rapor(
                self.cari_id,
                referans=ref,
                otomatik_plan=otomatik,
                taksit_adet=adet,
            )
        except Exception as hata:
            messagebox.showerror("Haftalık Ödeme", str(hata), parent=self)
            return
        finally:
            self._yenile_askida = False

        try:
            self._lf_plan.configure(text=f"Ödeme planı (belge / {adet} taksit)")
        except tk.TclError:
            pass

        self._lbl_onceki.configure(
            text=f"{_tl(rapor.get('onceki_haftalardan_kalan'))} TL"
        )
        adet_acik = rapor.get("bu_hafta_acik_adet") or 0
        self._lbl_bu.configure(
            text=f"{_tl(rapor.get('bu_hafta_acik_taksitler'))} TL  ({adet_acik} taksit)"
        )
        self._toplam_odenecek = Decimal(str(rapor.get("toplam_odenecek") or 0))
        self._son_rapor = rapor
        self._lbl_toplam.configure(text=f"{_tl(self._toplam_odenecek)} TL")

        fark = rapor.get("plan_cari_fark")
        try:
            fark_d = Decimal(str(fark or 0))
        except Exception:
            fark_d = Decimal("0")
        mut_metin = (
            f"   |   Cari kart: {_tl(rapor.get('cari_kalan_abs'))} TL"
            f"   |   Plan açık: {_tl(rapor.get('cari_acik_bakiye'))} TL"
        )
        if abs(fark_d) > Decimal("0.005"):
            mut_metin += f"   |   Fark: {_tl(fark_d)} TL"
            disi = rapor.get("plan_disi_hareketler") or []
            if disi:
                mut_metin += f" ({len(disi)} plan dışı hareket)"
        self.detay_lbl.configure(
            text=(
                f"Taksit: {adet}"
                f"   |   Hafta: {_tr_tarih(rapor['hafta_bas'])} – {_tr_tarih(rapor['hafta_bit'])}"
                f"   |   Hafta başı devri: {_tl(rapor.get('hafta_basi_devri'))} TL"
                f"   |   Vadesi gelen: {_tl(rapor.get('vadesi_gelen'))} TL"
                f"   |   Bu hafta ödeme: {_tl(rapor.get('hafta_odeme_toplam'))} TL"
                f"   |   Hafta sonu kalan: {_tl(rapor.get('hafta_sonu_kalan'))} TL"
                f"{mut_metin}"
            )
        )

        self._satirlari_doldur(self.agac_hafta, rapor.get("bu_hafta_odenecek") or [])
        self._satirlari_doldur(self.agac_onceki, rapor.get("onceki_satirlar") or [])
        self._satirlari_doldur(self.agac_gelecek, rapor.get("gelecek_satirlar") or [])
        self.lbl_gelecek.configure(
            text=f"Gelecek haftalara kalan: {_tl(rapor.get('gelecek_haftalara_kalan'))} TL"
        )

        self.agac_plan.delete(*self.agac_plan.get_children())
        for p in rapor.get("plan_ozetleri") or []:
            valor = p.get("ortalama_valor_gun")
            valor_metin = (
                f"{float(valor):.2f}".replace(".", ",") if valor is not None else ""
            )
            self.agac_plan.insert(
                "",
                "end",
                values=(
                    p.get("belge_no") or "",
                    _tr_tarih(p.get("fatura_tarihi")),
                    p.get("taksit_adet"),
                    valor_metin,
                    _tl(p.get("planlanan_toplam")),
                    _tl(p.get("odenen_toplam")),
                    _tl(p.get("kalan_toplam")),
                ),
            )

    def _odeme_yap_ac(self) -> None:
        if self._son_rapor is None:
            self.yenile(otomatik=True)
        if self._son_rapor is None:
            return
        dlg = HaftalikOdemeYapDialog(
            self,
            cari_id=self.cari_id,
            cari_adi=self.cari_adi,
            rapor=self._son_rapor,
            taksit_adet=self._taksit_adet,
            onerilen=self._toplam_odenecek,
        )
        self.wait_window(dlg)
        if getattr(dlg, "result", None):
            self.yenile(otomatik=True)

    def _kapat(self) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()


class HaftalikOdemeYapDialog(tk.Toplevel):
    """Haftalık ödeme — tutar/yöntem/hesap + taksit mahsup önizlemesi."""

    YONTEMLER = (
        ("Nakit", ODEME_YONTEM_NAKIT),
        ("Havale/EFT", ODEME_YONTEM_HAVALE),
        ("Kredi Kartı", ODEME_YONTEM_KART),
    )

    def __init__(
        self,
        parent,
        *,
        cari_id: int,
        cari_adi: str,
        rapor: dict,
        taksit_adet: int,
        onerilen: Decimal,
    ):
        super().__init__(parent)
        self.parent = parent
        self.cari_id = int(cari_id)
        self.cari_adi = cari_adi
        self.rapor = rapor
        self.taksit_adet = int(taksit_adet)
        self.onerilen = Decimal(str(onerilen or 0))
        self.result = None
        self._istek = f"ho-{cari_id}-{uuid.uuid4().hex[:16]}"
        self._hesap_map: dict[str, int] = {}
        self._kart_map: dict[str, int] = {}

        bas = rapor.get("hafta_bas")
        bit = rapor.get("hafta_bit")
        self.title(f"Ödeme Yap — {cari_adi}")
        self.geometry("780x620")
        self.minsize(680, 520)
        self.protocol("WM_DELETE_WINDOW", self._kapat)

        govde = ttk.Frame(self, padding=12)
        govde.pack(fill="both", expand=True)

        ttk.Label(govde, text=cari_adi, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(
            govde,
            text=(
                f"Hafta: {_tr_tarih(bas)} – {_tr_tarih(bit)}   |   "
                f"Önerilen (Toplam ödenecek): {_tl(self.onerilen)} TL"
            ),
            foreground="#475569",
        ).pack(anchor="w", pady=(2, 10))

        form = ttk.LabelFrame(govde, text="Ödeme", padding=10)
        form.pack(fill="x")

        ttk.Label(form, text="Ödeme tarihi").grid(row=0, column=0, sticky="w", pady=4)
        self.tarih_var = tk.StringVar(value=date.today().strftime("%d.%m.%Y"))
        ttk.Entry(form, textvariable=self.tarih_var, width=14).grid(
            row=0, column=1, sticky="w", pady=4
        )

        ttk.Label(form, text="Ödeme tutarı (TL)").grid(row=1, column=0, sticky="w", pady=4)
        self.tutar_var = tk.StringVar(value=tr_tutar(self.onerilen))
        self.tutar_entry = ttk.Entry(form, textvariable=self.tutar_var, width=16, justify="right")
        self.tutar_entry.grid(row=1, column=1, sticky="w", pady=4)
        tutar_alani(self.tutar_entry, self.tutar_var)
        ttk.Label(
            form, text="Önerilen tutarı silebilir / değiştirebilirsiniz", foreground="#64748b"
        ).grid(row=1, column=2, sticky="w", padx=8)

        ttk.Label(form, text="Ödeme yöntemi").grid(row=2, column=0, sticky="w", pady=4)
        self.yontem_var = tk.StringVar(value=self.YONTEMLER[0][0])
        self.yontem_cb = ttk.Combobox(
            form,
            textvariable=self.yontem_var,
            values=[a for a, _ in self.YONTEMLER],
            state="readonly",
            width=22,
        )
        self.yontem_cb.grid(row=2, column=1, sticky="w", pady=4)
        self.yontem_cb.bind("<<ComboboxSelected>>", lambda _e: self._yontem_degisti())

        self.hesap_lbl = ttk.Label(form, text="Kasa hesabı")
        self.hesap_lbl.grid(row=3, column=0, sticky="w", pady=4)
        self.hesap_var = tk.StringVar()
        self.hesap_cb = ttk.Combobox(
            form, textvariable=self.hesap_var, state="readonly", width=48
        )
        self.hesap_cb.grid(row=3, column=1, columnspan=2, sticky="w", pady=4)

        self.taksit_lbl = ttk.Label(form, text="Kart taksit")
        self.taksit_var = tk.StringVar(value="1")
        self.taksit_sb = ttk.Spinbox(
            form, from_=1, to=24, textvariable=self.taksit_var, width=6
        )
        self.taksit_lbl.grid(row=4, column=0, sticky="w", pady=4)
        self.taksit_sb.grid(row=4, column=1, sticky="w", pady=4)

        ttk.Label(form, text="Açıklama").grid(row=5, column=0, sticky="w", pady=4)
        self.aciklama_var = tk.StringVar(
            value=f"Haftalık ödeme {_tr_tarih(bas)}–{_tr_tarih(bit)}"
        )
        ttk.Entry(form, textvariable=self.aciklama_var, width=52).grid(
            row=5, column=1, columnspan=2, sticky="w", pady=4
        )

        btn_fr = ttk.Frame(form)
        btn_fr.grid(row=6, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Button(btn_fr, text="Önizle", command=self._onizle).pack(side="left", padx=(0, 6))
        ttk.Button(btn_fr, text="Kaydet", command=self._kaydet).pack(side="left", padx=(0, 6))
        ttk.Button(btn_fr, text="İptal", command=self._kapat).pack(side="left")

        self.oniz_ozet = ttk.Label(govde, text="", foreground="#334155")
        self.oniz_ozet.pack(anchor="w", pady=(10, 4))

        lf = ttk.LabelFrame(govde, text="Mahsup önizleme", padding=6)
        lf.pack(fill="both", expand=True)
        cols = ("belge", "sira", "vade", "onceki", "mahsup", "kalan")
        self.agac = ttk.Treeview(lf, columns=cols, show="headings", height=10)
        for c, t, w in (
            ("belge", "Belge no", 130),
            ("sira", "Taksit", 60),
            ("vade", "Vade", 90),
            ("onceki", "Önceki kalan", 100),
            ("mahsup", "Mahsup", 100),
            ("kalan", "Kalan", 100),
        ):
            self.agac.heading(c, text=t)
            self.agac.column(c, width=w, anchor="center")
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.agac.yview)
        self.agac.configure(yscrollcommand=sb.set)
        self.agac.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self._yontem_degisti()
        self.after(50, self._onizle)
        try:
            self.transient(parent)
            self.grab_set()
        except tk.TclError:
            pass

    def _yontem_kodu(self) -> str:
        etiket = self.yontem_var.get()
        for ad, kod in self.YONTEMLER:
            if ad == etiket:
                return kod
        return ODEME_YONTEM_NAKIT

    def _yontem_degisti(self) -> None:
        from database.finans_service import FinansService

        yon = self._yontem_kodu()
        self._hesap_map.clear()
        self._kart_map.clear()
        if yon == ODEME_YONTEM_NAKIT:
            self.hesap_lbl.configure(text="Kasa hesabı")
            hesaplar = FinansService.kasa_hesaplari()
            adlar = []
            for h in hesaplar:
                ad = h.hesap_adi
                adlar.append(ad)
                self._hesap_map[ad] = int(h.id)
            self.hesap_cb["values"] = adlar
            if adlar:
                self.hesap_var.set(adlar[0])
            self.taksit_lbl.grid_remove()
            self.taksit_sb.grid_remove()
        elif yon == ODEME_YONTEM_HAVALE:
            self.hesap_lbl.configure(text="Banka hesabı")
            hesaplar = FinansService.gider_fisi_odeme_hesaplari()
            adlar = []
            for h in hesaplar:
                if (h.hesap_turu or "").upper() != "BANKA":
                    continue
                alt = (h.alt_hesap_turu or "").upper()
                if alt not in ("MEVDUAT", "KMH"):
                    continue
                ad = h.hesap_adi
                adlar.append(ad)
                self._hesap_map[ad] = int(h.id)
            self.hesap_cb["values"] = adlar
            if adlar:
                self.hesap_var.set(adlar[0])
            self.taksit_lbl.grid_remove()
            self.taksit_sb.grid_remove()
        else:
            self.hesap_lbl.configure(text="Firma kredi kartı")
            kartlar = FinansService.sirket_kredi_kartlari()
            adlar = []
            for k in kartlar:
                ad = k["etiket"]
                adlar.append(ad)
                self._kart_map[ad] = int(k["id"])
            self.hesap_cb["values"] = adlar
            if adlar:
                self.hesap_var.set(adlar[0])
            self.taksit_lbl.grid()
            self.taksit_sb.grid()
        self.after(30, self._onizle)

    def _tarih_oku(self) -> date:
        ham = (self.tarih_var.get() or "").strip()
        try:
            return datetime.strptime(ham, "%d.%m.%Y").date()
        except ValueError as hata:
            raise ValueError("Ödeme tarihi gg.aa.yyyy olmalıdır.") from hata

    def _tutar_oku(self) -> Decimal:
        try:
            t = tutar_coz(self.tutar_var.get())
        except (InvalidOperation, ValueError, TypeError) as hata:
            raise ValueError("Ödeme tutarı geçerli bir sayı olmalıdır.") from hata
        if t <= 0:
            raise ValueError("Ödeme tutarı pozitif olmalıdır.")
        return t.quantize(Decimal("0.01"))

    def _onizle(self) -> None:
        try:
            tutar = self._tutar_oku()
            tarih = self._tarih_oku()
            on = HaftalikOdemeService.odeme_dagitim_onizle(
                self.cari_id,
                tutar,
                tarih,
                taksit_adet=self.taksit_adet,
                referans=self.rapor.get("hafta_bas"),
            )
        except Exception as exc:
            self.oniz_ozet.configure(text=str(exc), foreground="#b91c1c")
            self.agac.delete(*self.agac.get_children())
            return
        self.oniz_ozet.configure(
            text=(
                f"Makbuz önerisi: {on.get('makbuz_no_oneri') or '—'}   |   "
                f"Mahsup: {_tl(on.get('mahsup_toplam'))} TL   |   "
                f"Avans / erken: {_tl(on.get('avans'))} TL"
            ),
            foreground="#334155",
        )
        self.agac.delete(*self.agac.get_children())
        for s in on.get("dagitim") or []:
            self.agac.insert(
                "",
                "end",
                values=(
                    s.get("belge_no") or "",
                    f"{s.get('taksit_no')}/{s.get('taksit_adet')}",
                    _tr_tarih(s.get("vade_tarihi")),
                    _tl(s.get("onceki_kalan")),
                    _tl(s.get("mahsup")),
                    _tl(s.get("kalan")),
                ),
            )

    def _kaydet(self) -> None:
        try:
            tutar = self._tutar_oku()
            tarih = self._tarih_oku()
            yon = self._yontem_kodu()
            kw: dict = {
                "cari_id": self.cari_id,
                "tutar": tutar,
                "odeme_tarihi": tarih,
                "yontem": yon,
                "aciklama": self.aciklama_var.get(),
                "istek_anahtari": self._istek,
                "taksit_adet": self.taksit_adet,
                "referans": self.rapor.get("hafta_bas"),
            }
            if yon == ODEME_YONTEM_KART:
                ad = self.hesap_var.get()
                if ad not in self._kart_map:
                    raise ValueError("Firma kredi kartı seçin.")
                kw["kredi_karti_id"] = self._kart_map[ad]
                kw["taksit_sayisi"] = int(str(self.taksit_var.get() or "1").strip() or "1")
            else:
                ad = self.hesap_var.get()
                if ad not in self._hesap_map:
                    raise ValueError("Hesap seçin.")
                kw["finans_hesap_id"] = self._hesap_map[ad]
            # Önizlemeyi güncelle
            self._onizle()
            sonuc = HaftalikOdemeService.odeme_yap(**kw)
            self.result = sonuc
            messagebox.showinfo(
                "Ödeme Yap",
                (
                    f"Ödeme kaydedildi.\n"
                    f"Belge: {sonuc.get('belge_no')}\n"
                    f"Makbuz: {sonuc.get('makbuz_no')}\n"
                    f"Tutar: {_tl(sonuc.get('tutar'))} TL"
                ),
                parent=self,
            )
            self._kapat()
        except Exception as exc:
            messagebox.showerror("Ödeme Yap", str(exc), parent=self)

    def _kapat(self) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
