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
        self._secili_idler: set[int] = set()  # sayfalar arası kalıcı seçim (stok_id)
        self._islem_suruyor = False
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
        self.alt_gruplar_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            ust,
            text="Alt gruplar dahil",
            variable=self.alt_gruplar_var,
        ).grid(row=0, column=7, sticky="w", padx=(8, 0))
        ust.columnconfigure(1, weight=1)

        orta = tk.Frame(self, padx=10, pady=4)
        orta.pack(fill="both", expand=True)
        orta.rowconfigure(0, weight=1)
        orta.columnconfigure(0, weight=1)

        kolonlar = (
            "sec",
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
            "sec": "✓",
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
            "sec": 36,
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
            self.tablo.column(
                k, width=genislik[k], anchor="center" if k == "sec" else "w", stretch=(k == "ad")
            )
        sb = ttk.Scrollbar(orta, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=sb.set)
        self.tablo.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        self.tablo.bind("<<TreeviewSelect>>", self._secim_degisti)
        self.tablo.bind("<Double-1>", self._cift_tik_isaretle)
        self.tablo.bind("<Return>", lambda _e: self._seciliyi_ekle_akisi())
        self.tablo.bind("<space>", self._space_isaretle)
        self.tablo.bind("<Control-a>", self._hepsini_sec)
        self.tablo.bind("<Button-1>", self._tik_secim_kutusu, add="+")

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

        tk.Label(satir, text="Kısa ad (tekli)").grid(row=0, column=3, sticky="w", padx=(12, 0))
        self.kisa_ad = ttk.Entry(satir, width=20)
        self.kisa_ad.grid(row=0, column=4, sticky="w", padx=6)
        self._kisa_ad_uyari = tk.Label(
            satir,
            text="Çoklu seçimde her ürün kendi adını korur",
            fg="#666",
            font=("Segoe UI", 8),
        )
        self._kisa_ad_uyari.grid(row=0, column=5, sticky="w", padx=4)

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
        self.sayfa_lbl = tk.Label(alt, text="", fg="#555")
        self.sayfa_lbl.pack(side="left", padx=12)
        self.secim_lbl = tk.Label(alt, text="0 seçili", fg=KOYU_GRI, font=("Segoe UI", 9, "bold"))
        self.secim_lbl.pack(side="left", padx=8)
        self.hedef_uyari_lbl = tk.Label(alt, text="", fg="#B45309", font=("Segoe UI", 8))
        self.hedef_uyari_lbl.pack(side="left", padx=6)

        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")
        ttk.Button(
            alt,
            text="Kaydet ve Ekle",
            command=self._seciliyi_ekle_akisi,
        ).pack(side="right", padx=4)

        toplu = tk.Frame(self)
        toplu.pack(fill="x", padx=10, pady=(0, 10))
        self.btn_secilenleri = ttk.Button(
            toplu, text="Seçilenleri Ekle (0)", command=self._toplu_pin
        )
        self.btn_secilenleri.pack(side="left", padx=2)
        ttk.Button(
            toplu, text="Filtreye Uyanların Tümünü Seç", command=self._filtreye_uyanlari_sec
        ).pack(side="left", padx=2)
        ttk.Button(toplu, text="Seçimi Temizle", command=self._secimi_temizle).pack(
            side="left", padx=2
        )
        self.btn_grubun_tamami = ttk.Button(
            toplu, text="Grubun Tamamını Ekle", command=self._grubun_tamamini_ekle
        )
        self.btn_grubun_tamami.pack(side="left", padx=8)
        self.hizli_grup.bind("<<ComboboxSelected>>", lambda _e: self._ekleme_dugmelerini_ayarla())
        self._ekleme_dugmelerini_ayarla()

    def _filtreleri_yukle(self) -> None:
        """Stok grubu / marka listelerini doldur (seçenek + kartlardan)."""
        try:
            grup_adlari = StokService.hizli_satis_filtre_degerleri("rapor_grubu")
        except Exception:
            try:
                grup_adlari = StokService.secenekleri_listele("rapor_grubu")
            except Exception:
                grup_adlari = []
        try:
            marka_adlari = StokService.hizli_satis_filtre_degerleri("marka")
        except Exception:
            try:
                marka_adlari = StokService.secenekleri_listele("marka")
            except Exception:
                marka_adlari = []

        gruplar = [FILTRE_TUMU, FILTRE_GRUPSUZ] + list(grup_adlari)
        markalar = ["(Tümü)"] + list(marka_adlari)
        self.stok_grup_filtre.configure(values=gruplar, state="readonly")
        self.marka_filtre.configure(values=markalar, state="readonly")
        # current(0): bazı ttk temalarında set() boş görünebiliyor
        try:
            self.stok_grup_filtre.current(0)
        except tk.TclError:
            self.stok_grup_filtre.set(FILTRE_TUMU)
        try:
            self.marka_filtre.current(0)
        except tk.TclError:
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
                from database.fatura_kdv_service import satir_kdv_metin_sayisal

                kdv_metin = satir_kdv_metin_sayisal(kdv if kdv is not None else 20)
            except Exception:
                kdv_metin = "20"
            sid = int(u.get("stok_id") or 0)
            isaret = "☑" if sid in self._secili_idler else "☐"
            self.tablo.insert(
                "",
                "end",
                iid=str(i),
                values=(
                    isaret,
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
        self._secim_sayacini_guncelle()
        # Liste yenilenirken arama odağını koru
        try:
            if self.focus_get() is self.arama_entry or self.focus_get() is None:
                self.arama_entry.focus_set()
        except tk.TclError:
            pass

    def _hepsini_sec(self, _event=None):
        for i, u in enumerate(self._urunler):
            sid = int(u.get("stok_id") or 0)
            if sid:
                self._secili_idler.add(sid)
            self._satir_isaret_goster(str(i), sid in self._secili_idler)
        self.tablo.selection_set(self.tablo.get_children())
        self._secim_sayacini_guncelle()
        return "break"

    def _satir_isaret_goster(self, iid: str, isaretli: bool) -> None:
        try:
            degerler = list(self.tablo.item(iid, "values"))
            if not degerler:
                return
            degerler[0] = "☑" if isaretli else "☐"
            self.tablo.item(iid, values=degerler)
        except tk.TclError:
            pass

    def _stok_id_toggle(self, sid: int, iid: str | None = None) -> None:
        if not sid:
            return
        if sid in self._secili_idler:
            self._secili_idler.discard(sid)
            isaretli = False
        else:
            self._secili_idler.add(sid)
            isaretli = True
        if iid is not None:
            self._satir_isaret_goster(iid, isaretli)
        self._secim_sayacini_guncelle()

    def _tik_secim_kutusu(self, event):
        bolge = self.tablo.identify_region(event.x, event.y)
        if bolge != "cell":
            return
        kolon = self.tablo.identify_column(event.x)
        if kolon != "#1":  # sec
            return
        iid = self.tablo.identify_row(event.y)
        if not iid:
            return
        try:
            u = self._urunler[int(iid)]
            self._stok_id_toggle(int(u.get("stok_id") or 0), iid)
        except (ValueError, IndexError, TypeError):
            pass
        return "break"

    def _space_isaretle(self, _event=None):
        for iid in self.tablo.selection():
            try:
                u = self._urunler[int(iid)]
                self._stok_id_toggle(int(u.get("stok_id") or 0), iid)
            except (ValueError, IndexError, TypeError):
                continue
        return "break"

    def _cift_tik_isaretle(self, _event=None):
        """Toplu seçim: çift tık işareti değiştirir; pencereyi kapatmaz."""
        secim = self.tablo.selection()
        if not secim:
            return "break"
        try:
            u = self._urunler[int(secim[0])]
            self._stok_id_toggle(int(u.get("stok_id") or 0), secim[0])
        except (ValueError, IndexError, TypeError):
            pass
        return "break"

    def _secim_sayacini_guncelle(self) -> None:
        n = len(self._secili_idler)
        filtredeki = sum(
            1 for u in self._urunler if int(u.get("stok_id") or 0) in self._secili_idler
        )
        disarida = max(0, n - filtredeki)
        if disarida:
            metin = f"{n} seçili, {disarida} tanesi filtre dışında"
        else:
            metin = f"{n} seçili"
        try:
            self.secim_lbl.configure(text=metin)
            self.btn_secilenleri.configure(text=f"Seçilenleri Ekle ({n})")
        except (tk.TclError, AttributeError):
            pass
        self._ekleme_dugmelerini_ayarla()

    def _ekleme_dugmelerini_ayarla(self) -> None:
        hedef = (self.hizli_grup.get() or "").strip()
        ok = bool(hedef) and not self._islem_suruyor
        durum = "normal" if ok else "disabled"
        for btn in (
            getattr(self, "btn_secilenleri", None),
            getattr(self, "btn_grubun_tamami", None),
        ):
            if btn is None:
                continue
            try:
                btn.configure(state=durum)
            except tk.TclError:
                pass
        try:
            self.hedef_uyari_lbl.configure(
                text="" if hedef else "Hedef hızlı satış grubu seçilmedi — ekleme pasif"
            )
        except (tk.TclError, AttributeError):
            pass

    def _secimi_temizle(self) -> None:
        self._secili_idler.clear()
        for iid in self.tablo.get_children():
            self._satir_isaret_goster(iid, False)
        self._secim_sayacini_guncelle()

    def _filtreye_uyanlari_sec(self) -> None:
        """Mevcut arama/stok grubu/marka/stokta filtresine uyan tüm sayfalar."""
        filtre = self.stok_grup_filtre.get().strip()
        sadece_grupsuz = filtre == FILTRE_GRUPSUZ
        rapor = None if filtre in (FILTRE_TUMU, FILTRE_GRUPSUZ, "") else filtre
        marka = self.marka_filtre.get().strip()
        if marka in ("(Tümü)", ""):
            marka = None
        offset = 0
        limit = 200
        eklenen = 0
        while True:
            sonuc = StokService.hizli_satis_urun_ara(
                self.arama_entry.get().strip(),
                rapor_grubu=rapor,
                marka=marka,
                sadece_stokta=bool(self.stokta_var.get()),
                sadece_grupsuz=sadece_grupsuz,
                limit=limit,
                offset=offset,
                fiyat_adi=self.fiyat_adi,
            )
            urunler = sonuc.get("urunler") or []
            for u in urunler:
                sid = int(u.get("stok_id") or 0)
                if sid and sid not in self._secili_idler:
                    self._secili_idler.add(sid)
                    eklenen += 1
            toplam = int(sonuc.get("toplam") or 0)
            offset += len(urunler)
            if not urunler or offset >= toplam:
                break
        self._yukle()
        messagebox.showinfo(
            "Seçim",
            f"Filtreye uyan ürünler seçildi.\nYeni işaretlenen: {eklenen}\nToplam seçili: {len(self._secili_idler)}",
            parent=self,
        )

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
        """İşaretli stok kimlikleri (filtre dışı sayfalar dahil)."""
        if self._secili_idler:
            return sorted(self._secili_idler)
        # Geriye uyum: yalnızca satır vurgusu varsa onu kullan
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
        gruplar = StokService.hizli_satis_filtre_degerleri("rapor_grubu")
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
        gruplar = StokService.hizli_satis_filtre_degerleri("rapor_grubu")
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

    def _pin_alanlari(self, *, coklu: bool = False) -> dict:
        miktar = self.miktar_entry.get().strip() or "1"
        sira = self.sira_entry.get().strip()
        alan = {
            "varsayilan_miktar": miktar,
            "kart_rengi": self.renk_var.get().strip() or None,
            "gorsel_yolu": self.gorsel_yolu.get().strip() or None,
            "aktif": bool(self.aktif_var.get()),
        }
        if not coklu:
            alan["kisa_ad"] = self.kisa_ad.get().strip() or None
            alan["varsayilan_birim"] = self.birim_entry.get().strip() or None
            alan["sira_no"] = int(sira) if sira.isdigit() else None
        else:
            # Çoklu: ortak birim adı uygulanmaz; her ürün kendi satış birimini korur
            alan["varsayilan_birim"] = None
            alan["sira_no"] = None
        return alan

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
            messagebox.showinfo(
                "Seçim",
                "Seçilenleri Ekle için kutucuklarla ürün işaretleyin.",
                parent=self,
            )
            return
        if self._islem_suruyor:
            return
        ad = self.hizli_grup.get().strip()
        if not ad:
            messagebox.showwarning(
                "Hedef grup",
                "Önce hedef hızlı satış grubunu seçin.",
                parent=self,
            )
            return
        grup = self._hedef_hizli_grup(None)
        if not grup:
            return
        miktar = self.miktar_entry.get().strip() or "1"
        if miktar not in ("1", "1,0", "1.0"):
            if not messagebox.askyesno(
                "Ortak miktar",
                f"Varsayılan miktar «{miktar}» seçilen tüm kartlara uygulanacak. Devam?",
                parent=self,
            ):
                return
        self._islem_suruyor = True
        self._ekleme_dugmelerini_ayarla()
        try:
            self._hizli_gruplari_yukle()
            self.hizli_grup.set(grup["ad"])
            sonuc = HizliSatisService.pin_toplu_ekle(
                idler,
                hizli_satis_grubu_id=int(grup["id"]),
                grup_olustur_onayli=False,
                ortak=self._pin_alanlari(coklu=True),
            )
            messagebox.showinfo(
                "Seçilenleri Ekle",
                (
                    f"Eklenen: {sonuc['eklenen']}\n"
                    f"Atlanan (mevcut): {sonuc['atlanan']}\n"
                    f"Başarısız: {sonuc['basarisiz']}"
                ),
                parent=self,
            )
            if sonuc["basarisiz"] == 0:
                # Başarıda işlenen seçimleri temizle; filtreler kalsın
                for sid in idler:
                    self._secili_idler.discard(sid)
                self._yukle()
            self._bildir_degisti()
        finally:
            self._islem_suruyor = False
            self._ekleme_dugmelerini_ayarla()
            self.arama_entry.focus_set()

    def _grubun_tamamini_ekle(self) -> None:
        """Seçili stok rapor grubunun tamamını hedef hızlı satış grubuna pinler.

        Arama ve marka filtresi uygulanmaz; önizlemede belirtilir.
        """
        if self._islem_suruyor:
            return
        filtre = self.stok_grup_filtre.get().strip()
        if filtre in (FILTRE_TUMU, FILTRE_GRUPSUZ, ""):
            messagebox.showwarning(
                "Stok grubu",
                "Grubun Tamamını Ekle için üstte bir stok grubu seçin.",
                parent=self,
            )
            return
        ad = self.hizli_grup.get().strip()
        if not ad:
            messagebox.showwarning(
                "Hedef grup",
                "Önce hedef hızlı satış grubunu seçin.",
                parent=self,
            )
            return
        grup = self._hedef_hizli_grup(filtre)
        if not grup:
            return
        try:
            oniz = HizliSatisService.pin_stok_rapor_grubu_onizle(
                filtre,
                hizli_satis_grubu_id=int(grup["id"]),
                sadece_stokta=bool(self.stokta_var.get()),
                alt_gruplar_dahil=bool(self.alt_gruplar_var.get()),
            )
        except ValueError as exc:
            messagebox.showwarning("Önizleme", str(exc), parent=self)
            return
        metin = (
            f"Kaynak stok grubu: {oniz['kaynak_grup']}\n"
            f"Hedef hızlı satış grubu: {oniz['hedef_grup']}\n"
            f"Alt gruplar: {'dahil' if oniz.get('alt_gruplar_dahil') else 'yalnız doğrudan'}\n"
            f"Uygun ürün: {oniz['uygun']}\n"
            f"Hedefte zaten mevcut: {oniz['mevcut']}\n"
            f"Yeni kart eklenecek: {oniz['eklenecek']}\n\n"
            "Not: Metin araması ve marka filtresi bu işlemde kullanılmaz.\n"
            f"{'Yalnız stokta olanlar açık.' if oniz['sadece_stokta'] else 'Sıfır/eksi stoklu aktif ürünler de dahil.'}"
        )
        if oniz["eklenecek"] <= 0:
            messagebox.showinfo("Grubun Tamamı", metin + "\n\nEklenecek yeni ürün yok.", parent=self)
            return
        if not messagebox.askyesno(
            f"{oniz['eklenecek']} Ürünü Ekle",
            metin + "\n\nDevam edilsin mi?",
            parent=self,
        ):
            return
        self._islem_suruyor = True
        self._ekleme_dugmelerini_ayarla()
        try:
            sonuc = HizliSatisService.pin_stok_rapor_grubu_ekle(
                filtre,
                hizli_satis_grubu_id=int(grup["id"]),
                sadece_stokta=bool(self.stokta_var.get()),
                alt_gruplar_dahil=bool(self.alt_gruplar_var.get()),
                ortak=self._pin_alanlari(coklu=True),
            )
            ekstra = ""
            if sonuc.get("geri_alindi"):
                hatalar = sonuc.get("detay_hata") or []
                neden = hatalar[0].get("neden") if hatalar else "bilinmeyen hata"
                ekstra = f"\nİşlem geri alındı: {neden}"
            messagebox.showinfo(
                "Grubun Tamamı",
                (
                    f"{sonuc.get('eklenen', 0)} ürün eklendi, "
                    f"mevcut {sonuc.get('atlanan', oniz['mevcut'])} ürün atlandı.\n"
                    f"Başarısız: {sonuc.get('basarisiz', 0)}{ekstra}"
                ),
                parent=self,
            )
            self._bildir_degisti()
            self.listeyi_yenile()
        except ValueError as exc:
            messagebox.showerror("Grubun Tamamı", str(exc), parent=self)
        finally:
            self._islem_suruyor = False
            self._ekleme_dugmelerini_ayarla()
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
