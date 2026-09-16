"""Hızlı Satış — ÜRÜN EKLE (stok pin seçici + stok grubu bağlama).

Stok kartı oluşturmaz; mevcut kartı Hızlı Satış grubuna pinler.
Stok grubu = StokKarti.rapor_grubu (StokSecenek tur=rapor_grubu).
Hızlı satış grubu = HizliSatisGrubu (POS görsel bölümü).
"""

from __future__ import annotations

import tkinter as tk
from decimal import Decimal
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk
from typing import Callable

from database.hizli_satis_service import HizliSatisService
from database.stok_service import StokService
from stok_ui import StokKartiDialog

try:
    from hizli_satis_log import islem_yaz as _hs_log
except Exception:  # noqa: BLE001
    def _hs_log(*_a, **_k):  # type: ignore
        return None


SARİ = "#F5C518"
KOYU_GRI = "#2B2F33"
ACIK_GRI = "#F3F4F6"
FILTRE_TUMU = "(Tüm stok grupları)"
FILTRE_GRUPSUZ = "(Gruba bağlanmamış ürünler)"
SONUC_LIMIT = 80


def _para(tutar) -> str:
    try:
        return f"{float(tutar):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "—"


def _miktar(miktar) -> str:
    try:
        d = Decimal(str(miktar or 0))
        if d == d.to_integral_value():
            return str(int(d))
        return format(d, "f").rstrip("0").rstrip(".").replace(".", ",")
    except Exception:
        return str(miktar or 0)


class HizliSatisUrunEkleDialog(tk.Toplevel):
    """Ürün arama / stok grubu atama / Hızlı Satış'a pin."""

    def __init__(
        self,
        parent,
        *,
        varsayilan_hizli_grup_kod: str | None = None,
        fiyat_adi: str | None = None,
        on_degisti: Callable[[], None] | None = None,
    ):
        super().__init__(parent)
        self.title("Ürün Ekle — Hızlı Satış")
        self.geometry("1100x640")
        self.minsize(960, 560)
        self.transient(parent)
        self.grab_set()
        self.fiyat_adi = fiyat_adi
        self.on_degisti = on_degisti
        self._arama_after = None
        self._urunler: list[dict] = []
        self._secili: dict | None = None
        self._offset = 0
        self._toplam = 0
        self.varsayilan_hizli_grup_kod = varsayilan_hizli_grup_kod

        self._ui_kur()
        self._hizli_gruplari_yukle()
        self._filtreleri_yukle()
        self.bind("<Escape>", lambda _e: self.destroy())
        self.after(50, lambda: self.arama_entry.focus_set())
        self.listeyi_yenile()

    def _ui_kur(self) -> None:
        ust = tk.Frame(self, bg=ACIK_GRI, padx=10, pady=8)
        ust.pack(fill="x")

        tk.Label(ust, text="Ara", bg=ACIK_GRI, font=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        self.arama_entry = ttk.Entry(ust, width=36)
        self.arama_entry.grid(row=0, column=1, sticky="ew", padx=(6, 12))
        self.arama_entry.bind("<KeyRelease>", self._arama_gecikmeli)
        self.arama_entry.bind("<Return>", lambda _e: self._seciliyi_ekle_akisi())

        tk.Label(ust, text="Stok grubu", bg=ACIK_GRI).grid(row=0, column=2, sticky="w")
        self.stok_grup_filtre = ttk.Combobox(ust, state="readonly", width=28)
        self.stok_grup_filtre.grid(row=0, column=3, sticky="w", padx=(6, 12))
        self.stok_grup_filtre.bind("<<ComboboxSelected>>", lambda _e: self.listeyi_yenile())

        tk.Label(ust, text="Marka", bg=ACIK_GRI).grid(row=0, column=4, sticky="w")
        self.marka_filtre = ttk.Combobox(ust, state="readonly", width=16)
        self.marka_filtre.grid(row=0, column=5, sticky="w", padx=(6, 8))
        self.marka_filtre.bind("<<ComboboxSelected>>", lambda _e: self.listeyi_yenile())

        self.stokta_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            ust,
            text="Sadece stokta olanlar",
            variable=self.stokta_var,
            command=self.listeyi_yenile,
        ).grid(row=0, column=6, sticky="w")
        ust.columnconfigure(1, weight=1)

        orta = tk.Frame(self, padx=10, pady=4)
        orta.pack(fill="both", expand=True)
        orta.rowconfigure(0, weight=1)
        orta.columnconfigure(0, weight=1)

        kolonlar = (
            "kod",
            "ad",
            "barkod",
            "marka",
            "grup",
            "birim",
            "kdv",
            "fiyat",
            "stok",
            "raf",
        )
        self.tablo = ttk.Treeview(
            orta, columns=kolonlar, show="headings", selectmode="extended"
        )
        baslik = {
            "kod": "Stok Kodu",
            "ad": "Ad",
            "barkod": "Barkod",
            "marka": "Marka",
            "grup": "Stok Grubu",
            "birim": "Birim",
            "kdv": "KDV %",
            "fiyat": "Satış Fiyatı",
            "stok": "Mevcut Stok",
            "raf": "Raf",
        }
        genislik = {
            "kod": 100,
            "ad": 180,
            "barkod": 100,
            "marka": 80,
            "grup": 110,
            "birim": 60,
            "kdv": 55,
            "fiyat": 90,
            "stok": 80,
            "raf": 70,
        }
        for k in kolonlar:
            self.tablo.heading(k, text=baslik[k])
            self.tablo.column(k, width=genislik[k], anchor="w")
        sb = ttk.Scrollbar(orta, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=sb.set)
        self.tablo.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        self.tablo.bind("<<TreeviewSelect>>", self._secim_degisti)
        self.tablo.bind("<Double-1>", lambda _e: self._seciliyi_ekle_akisi())
        self.tablo.bind("<Return>", lambda _e: self._seciliyi_ekle_akisi())
        self.tablo.bind("<Control-a>", self._hepsini_sec)

        bilgi = tk.LabelFrame(self, text=" Seçili ürün ", padx=10, pady=8)
        bilgi.pack(fill="x", padx=10, pady=4)
        self.bilgi_lbl = tk.Label(
            bilgi,
            text="Listeden ürün seçin.",
            anchor="w",
            justify="left",
            font=("Segoe UI", 9),
        )
        self.bilgi_lbl.pack(fill="x")

        stok_grp = tk.Frame(bilgi)
        stok_grp.pack(fill="x", pady=(6, 0))
        tk.Label(stok_grp, text="Bağlı stok grubu:").pack(side="left")
        self.stok_grup_lbl = tk.Label(stok_grp, text="—", font=("Segoe UI", 9, "bold"))
        self.stok_grup_lbl.pack(side="left", padx=6)
        ttk.Button(
            stok_grp, text="STOK GRUBU SEÇ", command=self._stok_grubu_sec
        ).pack(side="left", padx=4)
        ttk.Button(
            stok_grp,
            text="YENİ STOK GRUBU OLUŞTUR",
            command=self._yeni_stok_grubu,
        ).pack(side="left", padx=4)
        ttk.Button(
            stok_grp,
            text="STOK GRUBU ATA (toplu)",
            command=self._toplu_stok_grubu_ata,
        ).pack(side="left", padx=8)

        pin = tk.LabelFrame(self, text=" Hızlı Satış pin ayarları ", padx=10, pady=8)
        pin.pack(fill="x", padx=10, pady=4)
        satir = tk.Frame(pin)
        satir.pack(fill="x")
        tk.Label(satir, text="Hızlı satış grubu").grid(row=0, column=0, sticky="w")
        self.hizli_grup = ttk.Combobox(satir, state="readonly", width=28)
        self.hizli_grup.grid(row=0, column=1, sticky="w", padx=6)
        ttk.Button(satir, text="Yeni grup…", command=self._yeni_hizli_grup).grid(
            row=0, column=2, padx=4
        )

        tk.Label(satir, text="Kısa ad").grid(row=0, column=3, sticky="w", padx=(12, 0))
        self.kisa_ad = ttk.Entry(satir, width=20)
        self.kisa_ad.grid(row=0, column=4, sticky="w", padx=6)

        tk.Label(satir, text="Miktar").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.miktar_entry = ttk.Entry(satir, width=8)
        self.miktar_entry.insert(0, "1")
        self.miktar_entry.grid(row=1, column=1, sticky="w", padx=6, pady=(6, 0))

        tk.Label(satir, text="Birim").grid(row=1, column=3, sticky="w", pady=(6, 0))
        self.birim_entry = ttk.Entry(satir, width=12)
        self.birim_entry.grid(row=1, column=4, sticky="w", padx=6, pady=(6, 0))

        tk.Label(satir, text="Sıra").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.sira_entry = ttk.Entry(satir, width=8)
        self.sira_entry.grid(row=2, column=1, sticky="w", padx=6, pady=(6, 0))

        self.aktif_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(satir, text="Aktif", variable=self.aktif_var).grid(
            row=2, column=3, sticky="w", pady=(6, 0)
        )

        self.renk_var = tk.StringVar(value="")
        ttk.Button(satir, text="Kart rengi…", command=self._renk_sec).grid(
            row=2, column=4, sticky="w", padx=6, pady=(6, 0)
        )
        ttk.Button(satir, text="Görsel…", command=self._gorsel_sec).grid(
            row=2, column=5, sticky="w", pady=(6, 0)
        )
        self.gorsel_yolu = tk.StringVar(value="")

        alt = tk.Frame(self, padx=10, pady=10)
        alt.pack(fill="x")
        ttk.Button(
            alt, text="Yeni ürün kartı oluştur", command=self._yeni_stok_karti
        ).pack(side="left")
        ttk.Button(alt, text="Toplu ekle", command=self._toplu_pin).pack(side="left", padx=8)
        self.sayfa_lbl = tk.Label(alt, text="", fg="#555")
        self.sayfa_lbl.pack(side="left", padx=16)
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")
        ttk.Button(
            alt,
            text="KAYDET VE EKLE",
            command=self._seciliyi_ekle_akisi,
        ).pack(side="right", padx=8)

    def _filtreleri_yukle(self) -> None:
        gruplar = [FILTRE_TUMU, FILTRE_GRUPSUZ] + StokService.secenekleri_listele(
            "rapor_grubu"
        )
        self.stok_grup_filtre["values"] = gruplar
        self.stok_grup_filtre.set(FILTRE_TUMU)
        markalar = ["(Tümü)"] + StokService.secenekleri_listele("marka")
        self.marka_filtre["values"] = markalar
        self.marka_filtre.set("(Tümü)")

    def _hizli_gruplari_yukle(self) -> None:
        HizliSatisService.schema_hazirla()
        gruplar = HizliSatisService.hizli_gruplari_listele()
        self._hizli_grup_map = {g["ad"]: g for g in gruplar}
        adlar = [g["ad"] for g in gruplar]
        self.hizli_grup["values"] = adlar
        hedef = None
        if self.varsayilan_hizli_grup_kod and str(self.varsayilan_hizli_grup_kod).startswith(
            "HSG:"
        ):
            for g in gruplar:
                if g["kod"] == self.varsayilan_hizli_grup_kod:
                    hedef = g["ad"]
                    break
        if hedef:
            self.hizli_grup.set(hedef)
        elif adlar:
            self.hizli_grup.set(adlar[0])
        else:
            self.hizli_grup.set("")

    def _arama_gecikmeli(self, _event=None) -> None:
        if self._arama_after is not None:
            try:
                self.after_cancel(self._arama_after)
            except tk.TclError:
                pass
        self._arama_after = self.after(300, self.listeyi_yenile)

    def listeyi_yenile(self) -> None:
        self._arama_after = None
        self._offset = 0
        self._yukle()

    def _yukle(self) -> None:
        for item in self.tablo.get_children():
            self.tablo.delete(item)
        filtre = self.stok_grup_filtre.get().strip()
        sadece_grupsuz = filtre == FILTRE_GRUPSUZ
        rapor = None if filtre in (FILTRE_TUMU, FILTRE_GRUPSUZ, "") else filtre
        marka = self.marka_filtre.get().strip()
        if marka in ("(Tümü)", ""):
            marka = None
        try:
            sonuc = StokService.hizli_satis_urun_ara(
                self.arama_entry.get().strip(),
                rapor_grubu=rapor,
                marka=marka,
                sadece_stokta=bool(self.stokta_var.get()),
                sadece_grupsuz=sadece_grupsuz,
                limit=SONUC_LIMIT,
                offset=self._offset,
                fiyat_adi=self.fiyat_adi,
            )
        except Exception as exc:  # noqa: BLE001
            _hs_log("HATA", "Ürün arama başarısız", detay={"hata": str(exc)})
            messagebox.showerror("Arama", str(exc), parent=self)
            return

        self._urunler = sonuc.get("urunler") or []
        self._toplam = int(sonuc.get("toplam") or 0)
        for i, u in enumerate(self._urunler):
            kdv = u.get("kdv_orani")
            try:
                kdv_metin = f"{Decimal(str(kdv if kdv is not None else 20)):f}".rstrip("0").rstrip(".") or "0"
            except Exception:
                kdv_metin = "20"
            self.tablo.insert(
                "",
                "end",
                iid=str(i),
                values=(
                    u.get("stok_kodu") or "",
                    u.get("stok_adi") or "",
                    u.get("barkod") or "",
                    u.get("marka") or "",
                    u.get("rapor_grubu") or "",
                    u.get("birim") or "",
                    kdv_metin,
                    _para(u.get("birim_fiyat")),
                    _miktar(u.get("mevcut_stok")),
                    u.get("raf_yeri") or "",
                ),
            )
        bit = self._offset + len(self._urunler)
        self.sayfa_lbl.configure(
            text=f"{self._offset + 1 if self._urunler else 0}–{bit} / {self._toplam}"
            if self._toplam
            else "0 ürün"
        )

    def _hepsini_sec(self, _event=None):
        self.tablo.selection_set(self.tablo.get_children())
        return "break"

    def _secim_degisti(self, _event=None) -> None:
        secim = self.tablo.selection()
        if not secim:
            self._secili = None
            self.bilgi_lbl.configure(text="Listeden ürün seçin.")
            self.stok_grup_lbl.configure(text="—")
            return
        idx = int(secim[0])
        if idx < 0 or idx >= len(self._urunler):
            return
        u = self._urunler[idx]
        self._secili = u
        self.bilgi_lbl.configure(
            text=(
                f"{u.get('stok_kodu')} — {u.get('stok_adi')}  |  "
                f"Fiyat: {_para(u.get('birim_fiyat'))} TL  |  "
                f"Stok: {_miktar(u.get('mevcut_stok'))} {u.get('birim') or ''}"
            )
        )
        self.stok_grup_lbl.configure(text=(u.get("rapor_grubu") or "— bağlı değil —"))
        self.kisa_ad.delete(0, "end")
        self.kisa_ad.insert(0, (u.get("stok_adi") or "")[:40])
        self.birim_entry.delete(0, "end")
        self.birim_entry.insert(0, u.get("birim") or "Adet")
        if not self.hizli_grup.get().strip() and u.get("rapor_grubu"):
            # Varsayılan: stok grubu adı
            self.hizli_grup.set(u["rapor_grubu"])

    def _secili_stok_idler(self) -> list[int]:
        idler = []
        for iid in self.tablo.selection():
            try:
                u = self._urunler[int(iid)]
                idler.append(int(u["stok_id"]))
            except Exception:
                continue
        return idler

    def _stok_grubu_sec(self) -> None:
        if not self._secili:
            messagebox.showinfo("Seçim", "Önce bir ürün seçin.", parent=self)
            return
        gruplar = StokService.secenekleri_listele("rapor_grubu")
        if not gruplar:
            messagebox.showwarning(
                "Stok grubu",
                "Tanımlı stok grubu yok. Önce «YENİ STOK GRUBU OLUŞTUR» kullanın.",
                parent=self,
            )
            return
        sec = _ListeSecDialog(self, "Stok grubu seç", gruplar)
        self.wait_window(sec)
        if not sec.sonuc:
            return
        try:
            StokService.stok_rapor_grubu_ata(int(self._secili["stok_id"]), sec.sonuc)
            self._filtreleri_yukle()
            self.listeyi_yenile()
            # seçimi koru
            for i, u in enumerate(self._urunler):
                if int(u["stok_id"]) == int(self._secili["stok_id"]):
                    self.tablo.selection_set(str(i))
                    self._secim_degisti()
                    break
            self._bildir_degisti()
        except ValueError as exc:
            messagebox.showerror("Stok grubu", str(exc), parent=self)

    def _yeni_stok_grubu(self) -> None:
        ad = simpledialog.askstring(
            "Yeni stok grubu",
            "Stok grubu adı (rapor_grubu / StokSecenek):",
            parent=self,
        )
        if not ad or not ad.strip():
            return
        try:
            kayit = StokService.secenek_ekle("rapor_grubu", ad.strip())
            self._filtreleri_yukle()
            messagebox.showinfo("Stok grubu", f"«{kayit}» eklendi.", parent=self)
            if self._secili:
                if messagebox.askyesno(
                    "Bağla",
                    f"Seçili ürüne «{kayit}» stok grubu atansın mı?",
                    parent=self,
                ):
                    StokService.stok_rapor_grubu_ata(int(self._secili["stok_id"]), kayit)
                    self.listeyi_yenile()
                    self._bildir_degisti()
        except ValueError as exc:
            messagebox.showerror("Stok grubu", str(exc), parent=self)

    def _toplu_stok_grubu_ata(self) -> None:
        idler = self._secili_stok_idler()
        if not idler:
            messagebox.showinfo("Seçim", "Toplu atama için ürün seçin.", parent=self)
            return
        if not messagebox.askyesno(
            "Stok grubu ata",
            "Seçilen ürünlerin ana stok grubu değiştirilecektir. Devam edilsin mi?",
            parent=self,
        ):
            return
        gruplar = StokService.secenekleri_listele("rapor_grubu")
        if not gruplar:
            messagebox.showwarning("Stok grubu", "Tanımlı stok grubu yok.", parent=self)
            return
        sec = _ListeSecDialog(self, "Stok grubu seç", gruplar)
        self.wait_window(sec)
        if not sec.sonuc:
            return
        try:
            sonuc = StokService.stok_rapor_grubu_toplu_ata(idler, sec.sonuc)
            messagebox.showinfo(
                "Tamam",
                f"{sonuc['guncellenen']} ürünün stok grubu «{sonuc['rapor_grubu']}» oldu.",
                parent=self,
            )
            self.listeyi_yenile()
            self._bildir_degisti()
        except ValueError as exc:
            messagebox.showerror("Stok grubu", str(exc), parent=self)

    def _yeni_hizli_grup(self) -> None:
        ad = simpledialog.askstring(
            "Yeni hızlı satış grubu",
            "POS görsel grubu adı:",
            parent=self,
        )
        if not ad or not ad.strip():
            return
        try:
            g = HizliSatisService.hizli_grup_olustur(ad.strip())
            self._hizli_gruplari_yukle()
            self.hizli_grup.set(g["ad"])
            self._bildir_degisti()
        except ValueError as exc:
            messagebox.showerror("Grup", str(exc), parent=self)

    def _renk_sec(self) -> None:
        renk = colorchooser.askcolor(parent=self, title="Kart rengi")
        if renk and renk[1]:
            self.renk_var.set(renk[1])

    def _gorsel_sec(self) -> None:
        yol = filedialog.askopenfilename(
            parent=self,
            title="Kart görseli",
            filetypes=[("Resimler", "*.png;*.jpg;*.jpeg;*.gif;*.webp"), ("Tümü", "*.*")],
        )
        if yol:
            self.gorsel_yolu.set(yol)

    def _yeni_stok_karti(self) -> None:
        dialog = StokKartiDialog(
            self,
            baslangic={
                "stok_kodu": self.arama_entry.get().strip()[:50],
                "stok_adi": "",
            },
            rapor_grubu_zorunlu=True,
        )
        self.wait_window(dialog)
        if not dialog.result:
            return
        stok = dialog.result
        self.listeyi_yenile()
        for i, u in enumerate(self._urunler):
            if int(u.get("stok_id") or 0) == int(getattr(stok, "id", 0) or 0):
                self.tablo.selection_set(str(i))
                self.tablo.see(str(i))
                self._secim_degisti()
                break
        self.arama_entry.focus_set()

    def _hedef_hizli_grup(self, stok_rapor: str | None) -> dict | None:
        ad = self.hizli_grup.get().strip() or (stok_rapor or "").strip()
        if not ad:
            return None
        mevcut = HizliSatisService.hizli_grup_bul_veya_hazirla(ad, olustur=False)
        if mevcut:
            return mevcut
        if not messagebox.askyesno(
            "Hızlı satış grubu",
            f"«{ad}» adlı hızlı satış grubu yok.\nOluşturulsun mu?",
            parent=self,
        ):
            return None
        return HizliSatisService.hizli_grup_olustur(ad)

    def _pin_alanlari(self) -> dict:
        miktar = self.miktar_entry.get().strip() or "1"
        sira = self.sira_entry.get().strip()
        return {
            "kisa_ad": self.kisa_ad.get().strip() or None,
            "varsayilan_birim": self.birim_entry.get().strip() or None,
            "varsayilan_miktar": miktar,
            "sira_no": int(sira) if sira.isdigit() else None,
            "kart_rengi": self.renk_var.get().strip() or None,
            "gorsel_yolu": self.gorsel_yolu.get().strip() or None,
            "aktif": bool(self.aktif_var.get()),
        }

    def _seciliyi_ekle_akisi(self, _event=None) -> None:
        if not self._secili:
            messagebox.showinfo("Seçim", "Eklenecek ürünü seçin.", parent=self)
            return
        u = self._secili
        rapor = (u.get("rapor_grubu") or "").strip()
        if not rapor:
            messagebox.showwarning("Stok grubu", HizliSatisService.STOK_GRUBU_UYARI, parent=self)
            return
        fiyat = u.get("birim_fiyat")
        if fiyat is None or Decimal(str(fiyat)) <= 0:
            if not messagebox.askyesno(
                "Fiyat yok",
                "Bu ürünün satış fiyatı tanımlı değil veya 0.\nYine de eklensin mi?",
                parent=self,
            ):
                return
        try:
            grup = self._hedef_hizli_grup(rapor)
            if not grup:
                return
            self._hizli_gruplari_yukle()
            self.hizli_grup.set(grup["ad"])
            HizliSatisService.pin_ekle(
                int(u["stok_id"]),
                hizli_satis_grubu_id=int(grup["id"]),
                grup_olustur_onayli=False,
                **self._pin_alanlari(),
            )
            _hs_log(
                "PIN",
                "Ürün Hızlı Satış'a eklendi",
                detay={"stok_id": u["stok_id"], "grup": grup["ad"]},
            )
            messagebox.showinfo(
                "Eklendi",
                f"«{u.get('stok_kodu')}» → {grup['ad']} grubuna eklendi.",
                parent=self,
            )
            self._bildir_degisti()
            self.arama_entry.focus_set()
        except ValueError as exc:
            messagebox.showwarning("Eklenemedi", str(exc), parent=self)
        except Exception as exc:  # noqa: BLE001
            _hs_log("HATA", "Pin ekleme hatası", detay={"hata": str(exc)})
            messagebox.showerror("Hata", str(exc), parent=self)

    def _toplu_pin(self) -> None:
        idler = self._secili_stok_idler()
        if not idler:
            messagebox.showinfo("Seçim", "Toplu ekleme için ürün seçin (Ctrl/Shift).", parent=self)
            return
        # İlk seçilinin rapor grubundan varsayılan
        ornek = self._urunler[int(self.tablo.selection()[0])]
        rapor = (ornek.get("rapor_grubu") or "").strip()
        grup = self._hedef_hizli_grup(rapor)
        if not grup:
            return
        self._hizli_gruplari_yukle()
        self.hizli_grup.set(grup["ad"])
        sonuc = HizliSatisService.pin_toplu_ekle(
            idler,
            hizli_satis_grubu_id=int(grup["id"]),
            grup_olustur_onayli=False,
        )
        messagebox.showinfo(
            "Toplu ekleme",
            (
                f"Eklenen: {sonuc['eklenen']}\n"
                f"Atlanan: {sonuc['atlanan']}\n"
                f"Başarısız: {sonuc['basarisiz']}"
            ),
            parent=self,
        )
        self._bildir_degisti()
        self.arama_entry.focus_set()

    def _bildir_degisti(self) -> None:
        if self.on_degisti:
            try:
                self.on_degisti()
            except Exception:
                pass


class _ListeSecDialog(tk.Toplevel):
    def __init__(self, parent, baslik: str, degerler: list[str]):
        super().__init__(parent)
        self.title(baslik)
        self.geometry("360x320")
        self.transient(parent)
        self.grab_set()
        self.sonuc: str | None = None
        lst = tk.Listbox(self, font=("Segoe UI", 10))
        lst.pack(fill="both", expand=True, padx=10, pady=10)
        for d in degerler:
            lst.insert("end", d)
        if degerler:
            lst.selection_set(0)

        def onay(_e=None):
            sec = lst.curselection()
            if not sec:
                return
            self.sonuc = lst.get(sec[0])
            self.destroy()

        lst.bind("<Double-1>", onay)
        ttk.Button(self, text="Seç", command=onay).pack(pady=6)
        self.bind("<Escape>", lambda _e: self.destroy())
