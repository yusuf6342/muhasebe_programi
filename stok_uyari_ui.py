"""Stoklar → Stok Uyarıları ve Sipariş İhtiyacı ekranı."""

from __future__ import annotations

import html
import logging
import threading
import tkinter as tk
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from satis_tema import ACIK_BG, IKINCIL, LACIVERT, SARI, font, tk_buton, treeview_stil

logger = logging.getLogger(__name__)

TUM = "Tümü"
DONEMLER = ("30 gün", "60 gün", "90 gün", "Özel")
_YOKLAMA_MS = 120
_BILDIRIM_MS = 5000


def _miktar(v) -> str:
    from database.stok_uyari_service import miktar_metni

    return miktar_metni(v)


def _para(v) -> str:
    if v is None:
        return ""
    s = f"{Decimal(str(v)):,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _tarih(d) -> str:
    if not d:
        return ""
    if isinstance(d, datetime):
        return d.strftime("%d.%m.%Y %H:%M")
    if isinstance(d, date):
        return d.strftime("%d.%m.%Y")
    return str(d)


def _tarih_oku(metin: str) -> date | None:
    metin = (metin or "").strip()
    if not metin:
        return None
    for bicim in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(metin, bicim).date()
        except ValueError:
            continue
    raise ValueError(f"Tarih anlaşılamadı: {metin} (gg.aa.yyyy)")


def _sayi_oku(metin: str, ad: str) -> Decimal | None:
    metin = (metin or "").strip().replace(".", "").replace(",", ".") if "," in (metin or "") else (metin or "").strip()
    if not metin:
        return None
    try:
        return Decimal(metin)
    except InvalidOperation as exc:
        raise ValueError(f"{ad} sayı olmalı.") from exc


def _arka_planda(widget: tk.Misc, is_fn: Callable[[], Any], bitti: Callable[[Any, Exception | None], None]) -> None:
    """Veritabanı işini ayrı iş parçacığında çalıştırır; sonuç Tk ana döngüsünde işlenir."""
    sonuc: dict[str, Any] = {}

    def calis():
        try:
            sonuc["deger"] = is_fn()
        except Exception as exc:  # noqa: BLE001 — sonuç ana iş parçacığında gösterilir
            logger.exception("Stok uyarı arka plan işi başarısız")
            sonuc["hata"] = exc
        sonuc["bitti"] = True

    threading.Thread(target=calis, daemon=True).start()

    def yokla():
        if not sonuc.get("bitti"):
            try:
                widget.after(_YOKLAMA_MS, yokla)
            except tk.TclError:
                pass
            return
        try:
            if widget.winfo_exists():
                bitti(sonuc.get("deger"), sonuc.get("hata"))
        except tk.TclError:
            pass

    widget.after(_YOKLAMA_MS, yokla)


def _cariler() -> list[tuple[int, str]]:
    from database.cari_service import CariService

    return [(c.id, f"{c.unvan} ({c.cari_kodu})") for c in sorted(CariService.aktif_cariler(),
                                                              key=lambda c: (c.unvan or "").lower())]


def _satir_degerleri(s: dict) -> dict[str, str]:
    son_alis, son_satis = s.get("son_alis") or {}, s.get("son_satis") or {}
    fiyat = s.get("tahmini_fiyat") or {}
    kaynak = s.get("ayar_kaynak") or {}
    kaynak_metni = ", ".join(f"{a}: {k}" for a, k in kaynak.items() if k and a in ("minimum", "hedef", "alim_birimi"))
    birim = s["temel_birim"]
    maliyet = s.get("maliyet_goster", True)

    def hareket(h, cari=True):
        if not h:
            return ""
        metin = f"{_tarih(h['tarih'])} {h['belge_no']} — {_miktar(h['miktar'])} {h['birim']}"
        return f"{metin} — {h.get('cari', '')}" if cari else metin

    def fiyat_metni(h):
        if not h or not maliyet:
            return ""
        kur = f" (kur {_miktar(h['kur'])})" if h.get("para_birimi", "TRY") != "TRY" and h.get("kur") else ""
        return f"{_para(h['net_fiyat'])} {h['para_birimi']} / {h['birim']}{kur}"

    return {
        "oncelik": s["oncelik_neden"] or "",
        "kod": s["stok_kodu"], "ad": s["stok_adi"], "marka": s["marka"], "grup": s["grup"], "depo": s["depo"],
        "birim": birim, "fiziksel": _miktar(s["fiziksel"]), "rezerve": _miktar(s["rezerve"]),
        "satilabilir": _miktar(s["satilabilir"]), "beklenen": _miktar(s["beklenen"]),
        "minimum": _miktar(s["minimum"]) if s["minimum"] is not None else "—",
        "hedef": _miktar(s["hedef"]) if s["hedef"] is not None else "—",
        "neden": s["neden_metni"], "oneri": s["oneri_metni"],
        "oneri_temel": f"{_miktar(s['oneri_temel'])} {birim}" if s["oneri_temel"] is not None else "",
        "durum": s["durum"], "takip": s["takip"], "tedarikci": s["tedarikci"], "ted_kaynak": s["tedarikci_kaynak"],
        "son_alis_tarih": _tarih(son_alis.get("tarih")),
        "son_alis_fiyat": fiyat_metni(son_alis),
        "son_alis_ted": son_alis.get("cari", ""),
        "son_satis_tarih": _tarih(son_satis.get("tarih")), "son_satis_musteri": son_satis.get("cari", ""),
        "son_satis_fiyat": (f"{_para(son_satis['net_fiyat'])} {son_satis['para_birimi']} / {son_satis['birim']}"
                            if son_satis else ""),
        "donem_son_alis": hareket(s.get("donem_son_alis")),
        "donem_son_satis": hareket(s.get("donem_son_satis")),
        "donem_alis": _miktar(s["donem_alis"]), "donem_alis_iade": _miktar(s["donem_alis_iade"]),
        "donem_satis": _miktar(s["donem_satis"]), "donem_satis_iade": _miktar(s["donem_satis_iade"]),
        "donem_net_satis": _miktar(s["donem_net_satis"]),
        "musteri_talebi": _miktar(s["musteri_talebi"]), "diger_depo": _miktar(s["diger_depo_stok"]),
        "tahmini_fiyat": f"{_para(fiyat['fiyat'])} / {fiyat['birim']} ({_tarih(fiyat['tarih'])})" if fiyat else "",
        "tahmini_bedel": _para(s["tahmini_bedel"]) if s.get("tahmini_bedel") is not None else "",
        "pb": fiyat.get("para_birimi", "") if fiyat else "",
        "ilk_olusma": _tarih(s["ilk_olusma"]), "son_degerlendirme": _tarih(s["son_degerlendirme"]),
        "ayar_kaynak": kaynak_metni,
    }


class StokUyariEkrani:
    def __init__(self, app, geri: Callable[[], None]):
        from fatura_satir_kolon_prefs import EKRAN_STOK_UYARI, ayarlari_yukle

        self.app = app
        self.geri = geri
        self.ekran = EKRAN_STOK_UYARI
        self.kolon_ayar = ayarlari_yukle(self.ekran)
        self.satirlar: dict[str, dict] = {}
        self.sonuc: dict[str, Any] = {}
        self._yukleniyor = False
        self._tarama: dict[str, Any] | None = None
        self._kur()

    # ------------------------------------------------------------------ yerleşim
    def _kur(self) -> None:
        from fatura_satir_kolon_prefs import FATURA_SATIR_KOLON_TANIM, resize_bagla, tabloya_uygula
        from stoklar_ui import _liste_ust

        app = self.app
        self.kok = _liste_ust(app, "STOK UYARILARI VE SİPARİŞ İHTİYACI",
                              "Tükenen ve kritik seviyedeki ürünler, öneri miktarı ve taslak satın alma siparişi",
                              self.geri)
        self.ozet_lbl = tk.Label(self.kok, text="", bg=ACIK_BG, fg=LACIVERT, font=font(10, "bold", app), anchor="w")
        self.ozet_lbl.pack(fill="x", padx=16, pady=(6, 0))
        self.bildirim = tk.Label(self.kok, text="", bg=SARI, fg=LACIVERT, font=font(10, "bold", app), anchor="w")
        self.not_lbl = tk.Label(self.kok, text="", bg=ACIK_BG, fg=IKINCIL, font=font(8, root=app), anchor="w",
                                justify="left", wraplength=1400)
        self.not_lbl.pack(fill="x", padx=16)

        f = tk.Frame(self.kok, bg=ACIK_BG)
        f.pack(fill="x", padx=16, pady=(6, 2))
        self.v_arama, self.v_marka, self.v_grup, self.v_ted = (tk.StringVar() for _ in range(4))
        self.v_depo, self.v_neden, self.v_durum = tk.StringVar(value=TUM), tk.StringVar(value=TUM), tk.StringVar(value=TUM)
        self.v_donem = tk.StringVar(value=DONEMLER[0])
        self.v_bas, self.v_bit = tk.StringVar(), tk.StringVar(value=date.today().strftime("%d.%m.%Y"))
        self.v_ertelenen, self.v_kapanan = tk.BooleanVar(value=False), tk.BooleanVar(value=False)

        def etiket(metin, satir, sutun):
            tk.Label(f, text=metin, bg=ACIK_BG, fg=IKINCIL, font=font(9, root=app)).grid(
                row=satir, column=sutun, sticky="w", padx=(0, 4), pady=2)

        etiket("Ara (kod/ad/barkod)", 0, 0)
        e = ttk.Entry(f, textvariable=self.v_arama, width=24)
        e.grid(row=0, column=1, sticky="w", padx=(0, 10))
        e.bind("<Return>", lambda _e: self.yenile())
        etiket("Depo", 0, 2)
        from database.stok_service import StokService

        self.depolar = {d.ad: d.id for d in StokService.depolar()}
        ttk.Combobox(f, textvariable=self.v_depo, values=[TUM, *self.depolar], state="readonly", width=16).grid(
            row=0, column=3, sticky="w", padx=(0, 10))
        etiket("Neden", 0, 4)
        from database.stok_uyari_service import (
            DURUM_ERTELENDI,
            DURUM_INCELENECEK,
            DURUM_KARSILANDI,
            DURUM_KISMEN,
            DURUM_SIPARIS_VERILDI,
            DURUM_TASLAK_VAR,
            DURUM_TESLIM_BEKLENIYOR,
            NEDEN_ETIKET,
        )

        self._neden_kod = {v: k for k, v in NEDEN_ETIKET.items()}
        ttk.Combobox(f, textvariable=self.v_neden, values=[TUM, *NEDEN_ETIKET.values()], state="readonly",
                     width=18).grid(row=0, column=5, sticky="w", padx=(0, 10))
        etiket("Durum", 0, 6)
        ttk.Combobox(f, textvariable=self.v_durum, state="readonly", width=30, values=[
            TUM, DURUM_INCELENECEK, DURUM_TASLAK_VAR, DURUM_SIPARIS_VERILDI, DURUM_KISMEN, DURUM_TESLIM_BEKLENIYOR,
            DURUM_ERTELENDI, DURUM_KARSILANDI]).grid(row=0, column=7, sticky="w", padx=(0, 10))
        etiket("Marka", 1, 0)
        ttk.Entry(f, textvariable=self.v_marka, width=24).grid(row=1, column=1, sticky="w", padx=(0, 10))
        etiket("Grup", 1, 2)
        ttk.Entry(f, textvariable=self.v_grup, width=18).grid(row=1, column=3, sticky="w", padx=(0, 10))
        etiket("Tedarikçi", 1, 4)
        ttk.Entry(f, textvariable=self.v_ted, width=20).grid(row=1, column=5, sticky="w", padx=(0, 10))
        etiket("Dönem", 1, 6)
        donem_f = tk.Frame(f, bg=ACIK_BG)
        donem_f.grid(row=1, column=7, sticky="w")
        cb = ttk.Combobox(donem_f, textvariable=self.v_donem, values=DONEMLER, state="readonly", width=8)
        cb.pack(side="left")
        self.e_bas = ttk.Entry(donem_f, textvariable=self.v_bas, width=11, state="disabled")
        self.e_bit = ttk.Entry(donem_f, textvariable=self.v_bit, width=11, state="disabled")
        self.e_bas.pack(side="left", padx=(6, 2))
        self.e_bit.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda _e: self._donem_degisti())
        kf = tk.Frame(f, bg=ACIK_BG)
        kf.grid(row=0, column=8, rowspan=2, sticky="w", padx=(6, 0))
        ttk.Checkbutton(kf, text="Ertelenenleri göster", variable=self.v_ertelenen).pack(anchor="w")
        ttk.Checkbutton(kf, text="Kapananları göster", variable=self.v_kapanan).pack(anchor="w")
        tk_buton(f, "Filtrele", self.yenile, rol="ara").grid(row=0, column=9, rowspan=2, padx=(10, 0))

        cerceve = ttk.Frame(self.kok)
        cerceve.pack(fill="both", expand=True, padx=16, pady=4)
        tum = tuple(k for k, *_ in FATURA_SATIR_KOLON_TANIM[self.ekran])
        self.tablo = ttk.Treeview(cerceve, columns=tum, show="headings", selectmode="extended")
        treeview_stil(self.tablo)
        dikey = ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview)
        yatay = ttk.Scrollbar(cerceve, orient="horizontal", command=self.tablo.xview)
        self.tablo.configure(yscrollcommand=dikey.set, xscrollcommand=yatay.set)
        self.tablo.grid(row=0, column=0, sticky="nsew")
        dikey.grid(row=0, column=1, sticky="ns")
        yatay.grid(row=1, column=0, sticky="ew")
        cerceve.rowconfigure(0, weight=1)
        cerceve.columnconfigure(0, weight=1)
        self.kolon_ayar = tabloya_uygula(self.tablo, self.ekran, self.kolon_ayar)
        resize_bagla(self.tablo, self.ekran, ayar_getter=lambda: self.kolon_ayar,
                     ayar_setter=lambda a: setattr(self, "kolon_ayar", a), parent=self.kok)
        for etiket_adi, renk in (("tukendi", "#F9D6D5"), ("kritik", "#FFF1C2"), ("girisyok", "#EEF1F6"),
                                 ("ertelendi", "#E4E4E4"),
                                 ("taslak", "#DCEBFA"), ("kapandi", "#E8F5E9")):
            self.tablo.tag_configure(etiket_adi, background=renk)
        self.tablo.tag_configure("yeni", font=font(9, "bold", app))
        self._siralama: tuple[str, bool] | None = None
        for k in tum:
            self.tablo.heading(k, command=lambda kol=k: self._sirala(kol))
        self.tablo.bind("<Double-1>", self._cift_tik)
        self.tablo.bind("<<TreeviewSelect>>", lambda _e: self._secim_bilgi())

        self.durum_lbl = tk.Label(self.kok, text="", bg=ACIK_BG, fg=IKINCIL, font=font(9, root=app), anchor="w")
        self.durum_lbl.pack(fill="x", padx=16)
        self.ilerleme = ttk.Progressbar(self.kok, mode="determinate")

        alt1 = tk.Frame(self.kok, bg=ACIK_BG)
        alt1.pack(fill="x", padx=16, pady=(4, 2))
        alt2 = tk.Frame(self.kok, bg=ACIK_BG)
        alt2.pack(fill="x", padx=16, pady=(2, 10))
        for metin, komut, rol in (
            ("Satın Alma Siparişi Hazırla", self.siparis_hazirla, "yeni"),
            ("Ürün / Depo Ayarı", self.ayar_ac, "duzenle"),
            ("Ertele", self.ertele, "duzenle"),
            ("Ertelemeyi Kaldır", self.ertelemeyi_kaldir, "duzenle"),
            ("Takibi Kapat", self.takibi_kapat, "iptal"),
            ("Görüldü", self.goruldu, "duzenle"),
        ):
            tk_buton(alt1, metin, komut, rol=rol).pack(side="left", padx=(0, 6))
        self.btn_tara = tk_buton(alt1, "Yeniden Değerlendir", self.toplu_degerlendir, rol="kaydet")
        self.btn_tara.pack(side="right")
        tk_buton(alt1, "Yenile", self.yenile, rol="ara").pack(side="right", padx=6)
        for metin, komut, rol in (
            ("Geçmiş", self.gecmis_goster, "geri"),
            ("Alış Geçmişi / Tedarikçiler", self.alis_gecmisi_goster, "geri"),
            ("Stok Kartı", self.stok_karti_ac, "geri"),
            ("Bağlı Siparişi Aç", self.siparis_ac, "geri"),
        ):
            tk_buton(alt2, metin, komut, rol=rol).pack(side="left", padx=(0, 6))
        for metin, komut in (("Genel Ayarlar", self.genel_ayarlar), ("Kolonlar", self.kolonlar),
                             ("PDF", self.pdf), ("Excel", self.excel)):
            tk_buton(alt2, metin, komut, rol="yazdir").pack(side="right", padx=(6, 0))

        self._bildirim_after: str | None = None
        self.kok.bind("<Destroy>", self._kapandi, add="+")
        self._bildirim_dongusu()
        self.kok.after(50, self._acilis)

    def _kapandi(self, event) -> None:
        if event.widget is self.kok and self._bildirim_after:
            try:
                self.kok.after_cancel(self._bildirim_after)
            except tk.TclError:
                pass
            self._bildirim_after = None

    def _cift_tik(self, event) -> None:
        if self.tablo.identify_region(event.x, event.y) == "cell":
            self.ayar_ac()

    _SAYISAL = frozenset({"fiziksel", "rezerve", "satilabilir", "beklenen", "minimum", "hedef", "donem_alis",
                          "donem_alis_iade", "donem_satis", "donem_satis_iade", "donem_net_satis",
                          "musteri_talebi", "diger_depo", "tahmini_bedel"})

    def _sirala(self, kolon: str) -> None:
        """Başlığa tıklama: artan/azalan; satır kimliği (iid) değişmez, işlemler doğru kaydı açar."""
        azalan = bool(self._siralama and self._siralama[0] == kolon and not self._siralama[1])
        self._siralama = (kolon, azalan)

        def anahtar(iid):
            deger = self.tablo.set(iid, kolon)
            if kolon in self._SAYISAL:
                try:
                    return (0, Decimal(deger.replace(".", "").replace(",", ".") or "0"))
                except InvalidOperation:
                    return (1, Decimal("0"))
            if kolon == "oncelik":
                return (0, self.satirlar[iid]["oncelik"])
            return (0, deger.lower())

        for i, iid in enumerate(sorted(self.tablo.get_children(), key=anahtar, reverse=azalan)):
            self.tablo.move(iid, "", i)

    def _donem_degisti(self) -> None:
        ozel = self.v_donem.get() == "Özel"
        for e in (self.e_bas, self.e_bit):
            e.configure(state="normal" if ozel else "disabled")
        if ozel and not self.v_bas.get():
            self.v_bas.set((date.today() - timedelta(days=29)).strftime("%d.%m.%Y"))

    # ------------------------------------------------------------------ açılış / bildirim
    def _acilis(self) -> None:
        from database.stok_uyari_service import StokUyariService

        def is_():
            islenen = StokUyariService.bekleyenleri_isle()
            return islenen, StokUyariService.ilk_tarama_gerekli()

        def bitti(deger, hata):
            if hata is None and deger and deger[1]:
                if messagebox.askyesno(
                    "İlk tarama",
                    "Stok uyarıları bu firmada henüz taranmadı ya da sınıflandırma kuralları güncellendi "
                    "(hiç stok girişi olmayan kartlar artık «Stok girişi yok» başlığında).\n\n"
                    "Mevcut tüm ürün ve depolar şimdi değerlendirilsin mi? İşlem arka planda çalışır; "
                    "stok, hareket ve siparişlere dokunmaz.",
                    parent=self.app,
                ):
                    self.toplu_degerlendir(ilk=True)
                    return
            self.yenile()

        _arka_planda(self.kok, is_, bitti)

    def _bildirim_dongusu(self) -> None:
        from database.stok_uyari_service import NEDEN_ETIKET, StokUyariService

        try:
            if not self.kok.winfo_exists():
                return
        except tk.TclError:
            return
        olaylar = [o for o in StokUyariService.olaylari_al() if o.get("tur") in ("YENI", "NEDEN")]
        if olaylar:
            ornek = ", ".join(f"{o.get('stok_kodu', '')} ({NEDEN_ETIKET.get((o.get('nedenler') or [''])[0], '')})"
                              for o in olaylar[:4])
            ek = f" ve {len(olaylar) - 4} ürün daha" if len(olaylar) > 4 else ""
            self.bildirim.configure(text=f"  Yeni stok uyarısı: {ornek}{ek}. Liste yenilendi.")
            self.bildirim.pack(fill="x", padx=16, pady=(4, 0), after=self.ozet_lbl)
            try:
                if StokUyariService.genel_ayarlar().get("sesli_bildirim") == "1":
                    self.app.bell()
            except Exception:  # noqa: BLE001
                pass
            if not self._yukleniyor and self._tarama is None:
                self.yenile()
        self._bildirim_after = self.kok.after(_BILDIRIM_MS, self._bildirim_dongusu)

    # ------------------------------------------------------------------ liste
    def _filtre(self) -> dict[str, Any]:
        filtre: dict[str, Any] = {
            "arama": self.v_arama.get().strip(), "marka": self.v_marka.get().strip() or None,
            "grup": self.v_grup.get().strip() or None, "tedarikci": self.v_ted.get().strip() or None,
            "ertelenenler": self.v_ertelenen.get(), "kapananlar": self.v_kapanan.get(),
        }
        if self.v_depo.get() != TUM:
            filtre["depo_id"] = self.depolar.get(self.v_depo.get())
        if self.v_neden.get() != TUM:
            filtre["neden"] = self._neden_kod.get(self.v_neden.get())
        if self.v_durum.get() != TUM:
            filtre["durum"] = self.v_durum.get()
        if self.v_donem.get() == "Özel":
            bas, bit = _tarih_oku(self.v_bas.get()), _tarih_oku(self.v_bit.get())
            if not bas or not bit or bas > bit:
                raise ValueError("Özel dönem için geçerli başlangıç ve bitiş tarihi girin.")
            filtre["bas"], filtre["bit"] = bas, bit
        else:
            filtre["donem_gun"] = int(self.v_donem.get().split()[0])
        return filtre

    def yenile(self) -> None:
        from database.stok_uyari_service import StokUyariService

        if self._yukleniyor:
            return
        try:
            filtre = self._filtre()
        except ValueError as exc:
            messagebox.showwarning("Filtre", str(exc), parent=self.app)
            return
        self._yukleniyor = True
        self.durum_lbl.configure(text="Liste hazırlanıyor…")
        secili = {self.satirlar[i]["id"] for i in self.tablo.selection() if i in self.satirlar}

        def bitti(sonuc, hata):
            self._yukleniyor = False
            if hata is not None:
                self.durum_lbl.configure(text="")
                messagebox.showerror("Stok uyarıları", f"Liste alınamadı:\n{hata}", parent=self.app)
                return
            self._doldur(sonuc, secili)

        _arka_planda(self.kok, lambda: (StokUyariService.listele(filtre), StokUyariService.aktif_sayisi()), bitti)

    def _doldur(self, sonuc_sayi, secili: set[int]) -> None:
        sonuc, sayi = sonuc_sayi
        self.sonuc = sonuc
        self.tablo.delete(*self.tablo.get_children())
        self.satirlar.clear()
        gorunen = list(self.tablo["displaycolumns"])
        tum = list(self.tablo["columns"])
        for s in sonuc["satirlar"]:
            s["maliyet_goster"] = sonuc.get("maliyet_goster", True)
            d = _satir_degerleri(s)
            iid = str(s["id"])
            etiketler = []
            if not s["aktif"]:
                etiketler.append("kapandi")
            elif s["takip"] == "Ertelendi":
                etiketler.append("ertelendi")
            elif s["bag"] and s["bag"].get("taslak"):
                etiketler.append("taslak")
            elif "TUKENDI" in s["nedenler"] or "SATILABILIR_YOK" in s["nedenler"]:
                etiketler.append("tukendi")
            elif "KRITIK" in s["nedenler"]:
                etiketler.append("kritik")
            elif "GIRIS_YOK" in s["nedenler"]:
                etiketler.append("girisyok")
            if s["aktif"] and not s["goruldu"]:
                etiketler.append("yeni")
            self.tablo.insert("", "end", iid=iid, values=[d.get(k, "") for k in tum], tags=etiketler)
            self.satirlar[iid] = s
        yeniden = [str(i) for i in secili if str(i) in self.satirlar]
        if yeniden:
            self.tablo.selection_set(yeniden)
        bedel = sonuc.get("toplam_bedel") or {}
        bedel_metni = "; ".join(f"{_para(v)} {pb}" for pb, v in sorted(bedel.items())) or "—"
        self.ozet_lbl.configure(text=(
            f"Etkin ihtiyaç: {sayi['toplam']}   Tükenen: {sayi['tukenen']}   Kritik: {sayi['kritik']}   "
            f"Stok girişi yok: {sayi.get('giris_yok', 0)}   "
            f"Yeni (görülmemiş): {sayi['yeni']}   |   Listelenen: {len(sonuc['satirlar'])}   |   "
            f"Tahmini bedel (para birimi ayrı): {bedel_metni}"))
        self.not_lbl.configure(text=(
            f"Dönem: {_tarih(sonuc['bas'])} – {_tarih(sonuc['bit'])} (iadeler ayrı sütunlarda).  "
            f"{sonuc.get('not', '')}  Tahmini bedel son alış fiyatından hesaplanır; teklif değildir."
            + ("" if sonuc.get("maliyet_goster", True) else "  Maliyet görme yetkiniz olmadığı için fiyatlar gizli.")))
        self.durum_lbl.configure(text=f"{len(gorunen)} sütun görünür. Çift tık: ürün/depo ayarı.")
        self._menu_sayisi_guncelle(sayi)

    def _menu_sayisi_guncelle(self, sayi: dict) -> None:
        try:
            from ana_panel_ui import stok_uyari_rozeti_guncelle

            stok_uyari_rozeti_guncelle(self.app, sayi)
        except Exception:  # noqa: BLE001 — rozet yalnız bilgi amaçlı
            pass

    def _secim_bilgi(self) -> None:
        s = self._secili(tek=False, sessiz=True)
        if len(s) == 1:
            r = s[0]
            ek = []
            if r["bag"]:
                ek.append("Siparişler: " + ", ".join(f"{b['siparis_no']} ({b['durum']})" for b in r["bag"]["siparisler"]))
            if r["erteleme_bitis"]:
                ek.append(f"Erteleme: {_tarih(r['erteleme_bitis'])} — {r['erteleme_nedeni'] or ''}")
            self.durum_lbl.configure(text=f"{r['stok_kodu']} / {r['depo']}: {r['durum']}. " + "  ".join(ek))
        elif s:
            self.durum_lbl.configure(text=f"{len(s)} satır seçili.")

    def _secili(self, tek: bool = False, sessiz: bool = False) -> list[dict]:
        secim = [self.satirlar[i] for i in self.tablo.selection() if i in self.satirlar]
        if not secim and not sessiz:
            messagebox.showinfo("Seçim", "Önce listeden satır seçin.", parent=self.app)
        if tek and len(secim) > 1 and not sessiz:
            messagebox.showinfo("Seçim", "Bu işlem için tek satır seçin.", parent=self.app)
            return []
        return secim

    # ------------------------------------------------------------------ toplu değerlendirme
    def toplu_degerlendir(self, ilk: bool = False) -> None:
        from database.stok_uyari_service import StokUyariService

        if self._tarama is not None:
            self._tarama["iptal"] = True
            self.btn_tara.configure(text="Durduruluyor…")
            return
        durum: dict[str, Any] = {"iptal": False, "i": 0, "n": 0}
        self._tarama = durum
        self.btn_tara.configure(text="Durdur")
        self.ilerleme.pack(fill="x", padx=16, pady=(2, 0), before=self.durum_lbl)
        self.ilerleme.configure(value=0, maximum=1)

        def ilerle(i, n):
            durum["i"], durum["n"] = i, n

        def is_():
            return StokUyariService.toplu_degerlendir(ilerle, lambda: durum["iptal"], ilk_tarama=ilk)

        def goster():
            if self._tarama is not durum:
                return
            try:
                self.ilerleme.configure(maximum=max(1, durum["n"]), value=durum["i"])
                self.durum_lbl.configure(text=f"Değerlendiriliyor: {durum['i']} / {durum['n']} ürün–depo")
                self.kok.after(250, goster)
            except tk.TclError:
                pass

        def bitti(sonuc, hata):
            self._tarama = None
            StokUyariService.olaylari_al()
            self.btn_tara.configure(text="Yeniden Değerlendir")
            self.ilerleme.pack_forget()
            if hata is not None:
                messagebox.showerror("Yeniden değerlendirme", str(hata), parent=self.app)
            else:
                iptal = " (kullanıcı durdurdu; işlenen kısım kaydedildi)" if durum["iptal"] else ""
                messagebox.showinfo(
                    "Yeniden değerlendirme",
                    f"{sonuc['cift']} ürün–depo değerlendirildi{iptal}.\nYeni ihtiyaç: {sonuc['yeni']}   "
                    f"Kapanan: {sonuc['kapanan']}\nSüre: {sonuc['sure_sn']} sn", parent=self.app)
            self.yenile()

        _arka_planda(self.kok, is_, bitti)
        self.kok.after(250, goster)

    # ------------------------------------------------------------------ kullanıcı işlemleri
    def _hata(self, baslik: str, exc: Exception) -> None:
        messagebox.showerror(baslik, str(exc), parent=self.app)

    def ayar_ac(self) -> None:
        secim = self._secili(tek=True)
        if not secim:
            return
        s = secim[0]
        dlg = AyarDialog(self.app, s["stok_id"], s["depo_id"], f"{s['stok_kodu']} — {s['stok_adi']}", s["depo"])
        self.app.wait_window(dlg)
        if dlg.kaydedildi:
            self.yenile()

    def ertele(self) -> None:
        from database.stok_uyari_service import StokUyariService

        secim = [s for s in self._secili() if s["aktif"]]
        if not secim:
            return
        dlg = ErteleDialog(self.app, len(secim))
        self.app.wait_window(dlg)
        if not dlg.sonuc:
            return
        bitis, neden = dlg.sonuc
        try:
            for s in secim:
                StokUyariService.ertele(s["id"], bitis, neden)
        except Exception as exc:  # noqa: BLE001
            self._hata("Ertele", exc)
        self.yenile()

    def ertelemeyi_kaldir(self) -> None:
        from database.stok_uyari_service import StokUyariService

        secim = [s for s in self._secili() if s["erteleme_bitis"]]
        if not secim:
            return
        try:
            for s in secim:
                StokUyariService.ertelemeyi_kaldir(s["id"])
        except Exception as exc:  # noqa: BLE001
            self._hata("Ertelemeyi kaldır", exc)
        self.yenile()

    def takibi_kapat(self) -> None:
        from database.stok_uyari_service import StokUyariService

        secim = self._secili()
        if not secim:
            return
        urunler = {s["stok_id"]: s["stok_kodu"] for s in secim}
        if not messagebox.askyesno(
            "Takibi kapat",
            f"{len(urunler)} ürün için stok uyarısı takibi kapatılsın mı?\n"
            "Ürünün tüm depolardaki etkin ihtiyaç kaydı kapanır; stok ve siparişler değişmez.\n"
            "Tekrar açmak için Ürün / Depo Ayarı → Takip.", parent=self.app):
            return
        try:
            for sid in urunler:
                StokUyariService.takibi_kapat(sid)
        except Exception as exc:  # noqa: BLE001
            self._hata("Takibi kapat", exc)
        self.yenile()

    def goruldu(self) -> None:
        from database.stok_uyari_service import StokUyariService

        secim = self._secili()
        if secim:
            StokUyariService.goruldu_isaretle([s["id"] for s in secim])
            self.yenile()

    def gecmis_goster(self) -> None:
        from database.stok_uyari_service import StokUyariService

        secim = self._secili(tek=True)
        if not secim:
            return
        s = secim[0]
        satirlar = [(_tarih(g["tarih"]), g["islem"], g["detay"] or "", g["kullanici"] or "", g["ihtiyac_id"])
                    for g in StokUyariService.gecmis(s["id"])]
        _liste_penceresi(self.app, f"Geçmiş — {s['stok_kodu']} / {s['depo']}",
                         (("tarih", "Tarih", 130), ("islem", "İşlem", 130), ("detay", "Ayrıntı", 520),
                          ("kul", "Kullanıcı", 110), ("olay", "Kayıt", 60)), satirlar)

    def alis_gecmisi_goster(self) -> None:
        from database.stok_uyari_service import StokUyariService

        secim = self._secili(tek=True)
        if not secim:
            return
        s = secim[0]
        veri = StokUyariService.tedarikci_karsilastirma(s["stok_id"], s["alim_birimi"])
        goster = self.sonuc.get("maliyet_goster", True)
        ted = [(t["cari"], _tarih(t["son_tarih"]), t["son_belge"],
                (f"{_para(t['son_fiyat'])} {t['para_birimi']} / {t['birim']}" if goster and t["son_fiyat"] is not None
                 else ("Gizli" if not goster else "Birim çevrilemedi")),
                t["alis_sayisi"], f"{_miktar(t['toplam_temel'])} {veri.get('temel_birim', '')}")
               for t in veri["tedarikciler"]]
        satirlar = [(_tarih(a["tarih"]), a["belge_no"], a["cari"], f"{_miktar(a['miktar'])} {a['birim']}",
                     f"{_para(a['net_fiyat'])} {a['para_birimi']}" if goster else "Gizli",
                     _miktar(a["kur"]) if a["para_birimi"] != "TRY" else "",
                     f"{_para(a['stok_maliyeti_temel'])} TL / {veri.get('temel_birim', '')}" if goster else "Gizli")
                    for a in veri["satirlar"]]
        pencere = _liste_penceresi(
            self.app, f"Tedarikçi karşılaştırması — {s['stok_kodu']} (alım birimi: {veri.get('birim', '')})",
            (("ted", "Tedarikçi", 220), ("tarih", "Son Alış", 90), ("belge", "Belge", 110),
             ("fiyat", "Son Net Fiyat", 170), ("adet", "Alış Sayısı", 80), ("top", "Toplam Miktar", 110)), ted,
            yukseklik=8)
        ttk.Label(pencere, text=(
            "Tüm alışlar (iptal hariç, yeni → eski). Net fiyat: iskonto sonrası, KDV hariç, belge para biriminde. "
            "Stok maliyeti: giriş anındaki FIFO lot maliyeti (TL, temel birim; sonradan yapılan masraf dağıtımı "
            "lot üzerinde izlenir). Fiyatlar geçmiş alıştır; teklif değildir; "
            "farklı birim/döviz fiyatları doğrudan kıyaslanmaz.")).pack(anchor="w", padx=10, pady=(6, 0))
        _tablo_ekle(pencere, (("tarih", "Tarih", 85), ("belge", "Belge", 100), ("cari", "Tedarikçi", 200),
                              ("miktar", "Miktar", 95), ("fiyat", "Net Fiyat", 120), ("kur", "Kur", 70),
                              ("maliyet", "Stok Maliyeti", 140)), satirlar)

    def stok_karti_ac(self) -> None:
        from database.stok_service import StokService
        from stok_ui import StokKartiDialog

        secim = self._secili(tek=True)
        if not secim:
            return
        stok = StokService.stok_getir(int(secim[0]["stok_id"]))
        if stok is None:
            messagebox.showwarning("Stok kartı", "Stok kartı bulunamadı (silinmiş olabilir).", parent=self.app)
            return
        dlg = StokKartiDialog(self.app, stok=stok)
        self.app.wait_window(dlg)
        self.yenile()

    def siparis_ac(self) -> None:
        from alis_ui import AlisSiparisiDialog
        from database.alis_siparisi_service import AlisSiparisiService

        secim = self._secili(tek=True)
        if not secim:
            return
        bag = secim[0]["bag"]
        if not bag or not bag["siparisler"]:
            messagebox.showinfo("Sipariş", "Bu ihtiyaca bağlı satın alma siparişi yok.", parent=self.app)
            return
        siparisler = {b["siparis_id"]: b for b in bag["siparisler"]}
        sid = next(iter(siparisler))
        if len(siparisler) > 1:
            secilen = _secim_penceresi(self.app, "Bağlı siparişler",
                                       [(i, f"{b['siparis_no']} — {b['durum']} — termin {_tarih(b['termin'])}")
                                        for i, b in siparisler.items()])
            if secilen is None:
                return
            sid = secilen
        siparis = AlisSiparisiService.getir(int(sid))
        if siparis is None:
            messagebox.showwarning("Sipariş", "Sipariş bulunamadı (silinmiş olabilir).", parent=self.app)
            return
        dlg = AlisSiparisiDialog(self.app, siparis=siparis)
        self.app.wait_window(dlg)
        self.yenile()

    def siparis_hazirla(self) -> None:
        from database.stok_uyari_service import StokUyariService

        secim = [s for s in self._secili() if s["aktif"]]
        if not secim:
            return
        try:
            guncel = StokUyariService.guncel_kontrol([s["id"] for s in secim])
        except Exception as exc:  # noqa: BLE001
            self._hata("Sipariş hazırla", exc)
            return
        guncel = [g for g in guncel if g["aktif"]]
        kapanan = len(secim) - len(guncel)
        if not guncel:
            messagebox.showinfo("Sipariş hazırla", "Seçili ihtiyaçların tamamı güncel hesapta kapanmış.", parent=self.app)
            self.yenile()
            return
        if kapanan:
            messagebox.showinfo("Sipariş hazırla",
                                f"{kapanan} satır güncel stok/sipariş durumuna göre kapandı ve çıkarıldı.",
                                parent=self.app)
        dlg = SiparisDialog(self.app, guncel, self.sonuc.get("maliyet_goster", True))
        self.app.wait_window(dlg)
        if dlg.olusan:
            metin = "\n".join(f"{o['siparis_no']} — {o['satir']} satır" for o in dlg.olusan)
            messagebox.showinfo(
                "Taslak siparişler hazır",
                f"Taslak satın alma siparişleri oluşturuldu:\n{metin}\n\n"
                "Taslaklar beklenen alıma sayılmaz. Tedarikçiye göndermeden önce Satın Alma Siparişleri "
                "listesinden açıp kontrol edin ve «Kesinleştir» ile onaylayın.", parent=self.app)
        self.yenile()

    def genel_ayarlar(self) -> None:
        dlg = GenelAyarDialog(self.app)
        self.app.wait_window(dlg)
        if dlg.kaydedildi:
            self.yenile()

    def kolonlar(self) -> None:
        from fatura_satir_kolon_prefs import FaturaSatirKolonAyarDialog, tabloya_uygula

        def uygula(ayar):
            self.kolon_ayar = tabloya_uygula(self.tablo, self.ekran, ayar)

        FaturaSatirKolonAyarDialog(self.app, self.ekran, self.kolon_ayar, on_uygula=uygula,
                                   baslik="Stok Uyarıları — Kolonlar")

    # ------------------------------------------------------------------ dışa aktarma
    def _gorunen_tablo(self) -> tuple[list[str], list[list[str]]]:
        """Seçim varsa yalnız seçili satırlar; tedarikçiye göre gruplu. Tedarikçi, depo, birim ve fiyat
        tarihi sütunları gizli olsa da çıktıya eklenir."""
        gorunen = ["tedarikci"] + [k for k in self.tablo["displaycolumns"] if k != "tedarikci"]
        for zorunlu in ("depo", "birim", "oneri"):
            if zorunlu not in gorunen:
                gorunen.append(zorunlu)
        if self.sonuc.get("maliyet_goster", True) and "tahmini_fiyat" not in gorunen:
            gorunen.append("tahmini_fiyat")
        basliklar = [self.tablo.heading(k, "text") for k in gorunen]
        iidler = [i for i in self.tablo.selection() if i in self.satirlar] or list(self.tablo.get_children())
        iidler.sort(key=lambda i: (self.satirlar[i]["tedarikci"].lower(), self.satirlar[i]["oncelik"]))
        satirlar = [[self.tablo.set(iid, k) for k in gorunen] for iid in iidler]
        return basliklar, satirlar

    def _cikti_bilgisi(self) -> str:
        depo = self.v_depo.get()
        return (f"Dönem: {_tarih(self.sonuc.get('bas'))} – {_tarih(self.sonuc.get('bit'))}; Depo: {depo}; "
                "miktarlar temel birimde, öneri alım biriminde; fiyatlar geçmiş alıştan (tarihi parantezde).")

    def excel(self) -> None:
        from cek_senet_ui import _excel_aktar

        basliklar, satirlar = self._gorunen_tablo()
        _excel_aktar(self.app, "Stok Uyarıları ve Sipariş İhtiyacı", basliklar,
                     [[self._cikti_bilgisi()] + [""] * (len(basliklar) - 1)] + satirlar if satirlar else [],
                     initialfile=f"stok_uyarilari_{date.today():%Y%m%d}.xlsx")

    def pdf(self) -> None:
        from invoice_print.pdf_service import html_metnini_pdfe_cevir

        basliklar, satirlar = self._gorunen_tablo()
        if not satirlar:
            messagebox.showinfo("PDF", "Aktarılacak kayıt yok.", parent=self.app)
            return
        yol = filedialog.asksaveasfilename(parent=self.app, title="PDF kaydet", defaultextension=".pdf",
                                           filetypes=[("PDF", "*.pdf")],
                                           initialfile=f"stok_uyarilari_{date.today():%Y%m%d}.pdf")
        if not yol:
            return
        bas = "".join(f"<th>{html.escape(b)}</th>" for b in basliklar)
        govde = "".join("<tr>" + "".join(f"<td>{html.escape(str(h))}</td>" for h in r) + "</tr>" for r in satirlar)
        sayfa = (
            "<!doctype html><html><head><meta charset='utf-8'><style>"
            "@page{size:A4 landscape;margin:10mm}body{font-family:'Segoe UI',Arial;font-size:8pt}"
            "table{border-collapse:collapse;width:100%}th,td{border:1px solid #999;padding:2px 3px}"
            "th{background:#1F3864;color:#fff}thead{display:table-header-group}</style></head><body>"
            f"<h3>Stok Uyarıları ve Sipariş İhtiyacı</h3><div>{html.escape(self.ozet_lbl.cget('text'))}</div>"
            f"<div>{html.escape(self._cikti_bilgisi())}</div>"
            f"<div>{html.escape(self.not_lbl.cget('text'))}</div>"
            f"<div>Oluşturma: {datetime.now():%d.%m.%Y %H:%M}</div><br>"
            f"<table><thead><tr>{bas}</tr></thead><tbody>{govde}</tbody></table></body></html>")
        try:
            html_metnini_pdfe_cevir(sayfa, Path(yol), belge_adi="Stok uyarıları")
        except Exception as exc:  # noqa: BLE001
            self._hata("PDF", exc)
            return
        messagebox.showinfo("PDF", f"Kaydedildi:\n{yol}", parent=self.app)


# ---------------------------------------------------------------------- yardımcı pencereler
def _tablo_ekle(parent, kolonlar, satirlar, yukseklik: int = 14) -> ttk.Treeview:
    f = ttk.Frame(parent)
    f.pack(fill="both", expand=True, padx=10, pady=6)
    t = ttk.Treeview(f, columns=[k for k, *_ in kolonlar], show="headings", height=yukseklik)
    for k, b, w in kolonlar:
        t.heading(k, text=b)
        t.column(k, width=w, anchor="w")
    sb = ttk.Scrollbar(f, orient="vertical", command=t.yview)
    t.configure(yscrollcommand=sb.set)
    t.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    for r in satirlar:
        t.insert("", "end", values=r)
    return t


def _liste_penceresi(parent, baslik, kolonlar, satirlar, yukseklik: int = 16) -> tk.Toplevel:
    w = tk.Toplevel(parent)
    w.title(baslik)
    w.geometry("980x560")
    w.transient(parent)
    if not satirlar:
        ttk.Label(w, text="Kayıt yok.").pack(anchor="w", padx=10, pady=(8, 0))
    _tablo_ekle(w, kolonlar, satirlar, yukseklik)
    ttk.Button(w, text="Kapat", command=w.destroy).pack(side="bottom", anchor="e", padx=10, pady=8)
    return w


def _secim_penceresi(parent, baslik: str, secenekler: list[tuple[Any, str]]):
    w = tk.Toplevel(parent)
    w.title(baslik)
    w.transient(parent)
    w.grab_set()
    lb = tk.Listbox(w, width=70, height=min(12, len(secenekler)))
    for _k, metin in secenekler:
        lb.insert("end", metin)
    lb.pack(padx=10, pady=10)
    sonuc: dict[str, Any] = {}

    def tamam(_e=None):
        if lb.curselection():
            sonuc["k"] = secenekler[lb.curselection()[0]][0]
        w.destroy()

    lb.bind("<Double-1>", tamam)
    ttk.Button(w, text="Aç", command=tamam).pack(pady=(0, 10))
    parent.wait_window(w)
    return sonuc.get("k")


class AyarDialog(tk.Toplevel):
    """Ürün (tüm depolar) veya ürün–depo ayarı; boş alan = üst seviyeden (depo → ürün → stok kartı → firma)."""

    TAKIP = ("Üst seviyeden", "Takip et", "Takip etme")

    def __init__(self, parent, stok_id: int, depo_id: int | None, baslik: str, depo_adi: str | None):
        super().__init__(parent)
        self.stok_id, self.depo_id, self.kaydedildi = stok_id, depo_id, False
        self.title(f"Stok uyarı ayarı — {baslik}")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        self.v_kapsam = tk.StringVar(value="depo" if depo_id else "urun")
        ust = ttk.Frame(self, padding=12)
        ust.pack(fill="x")
        ttk.Label(ust, text=baslik, font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Radiobutton(ust, text="Ürün ayarı (tüm depolar)", value="urun", variable=self.v_kapsam,
                        command=self._yukle).pack(anchor="w", pady=(6, 0))
        if depo_id:
            ttk.Radiobutton(ust, text=f"Yalnız bu depo: {depo_adi}", value="depo", variable=self.v_kapsam,
                            command=self._yukle).pack(anchor="w")
        self.cariler = _cariler()
        self._cari_metin = {i: m for i, m in self.cariler}
        g = ttk.Frame(self, padding=(12, 0))
        g.pack(fill="x")
        ttk.Label(g, text="Alan", font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(g, text="Değer (boş = üst seviye)", font=("Segoe UI", 9, "bold")).grid(row=0, column=1, sticky="w")
        ttk.Label(g, text="Geçerli değer / kaynak", font=("Segoe UI", 9, "bold")).grid(row=0, column=2, sticky="w",
                                                                                      padx=(12, 0))
        self.v = {k: tk.StringVar() for k in ("takip", "minimum", "hedef", "alim_birimi", "paket_kati", "ted")}
        self.etkin_lbl: dict[str, ttk.Label] = {}
        self.cb_birim = ttk.Combobox(g, textvariable=self.v["alim_birimi"], width=28, state="readonly")
        alanlar = (
            ("takip", "Takip", ttk.Combobox(g, textvariable=self.v["takip"], values=self.TAKIP, state="readonly",
                                            width=28)),
            ("minimum", "Minimum stok (temel birim)", ttk.Entry(g, textvariable=self.v["minimum"], width=30)),
            ("hedef", "Hedef stok (temel birim)", ttk.Entry(g, textvariable=self.v["hedef"], width=30)),
            ("alim_birimi", "Alım birimi", self.cb_birim),
            ("paket_kati", "Paket / koli katı (alım birimi)", ttk.Entry(g, textvariable=self.v["paket_kati"], width=30)),
            ("ted", "Tercih edilen tedarikçi", ttk.Combobox(g, textvariable=self.v["ted"], width=40, state="readonly",
                                                             values=["", *[m for _i, m in self.cariler]])),
        )
        for i, (k, etiket, w) in enumerate(alanlar, start=1):
            ttk.Label(g, text=etiket).grid(row=i, column=0, sticky="w", pady=3)
            w.grid(row=i, column=1, sticky="w", pady=3)
            self.etkin_lbl[k] = ttk.Label(g, text="", foreground="#555")
            self.etkin_lbl[k].grid(row=i, column=2, sticky="w", padx=(12, 0))
        ttk.Label(self, padding=(12, 6), foreground="#555", justify="left", text=(
            "Öneri = hedef − satılabilir − beklenen alım (eksi stok kırpılmaz); alım birimine çevrilip "
            "paket katına yukarı yuvarlanır.\nHedef yoksa öneri «Kullanıcı belirleyecek» olur. "
            "Minimum boşsa stok kartındaki minimum stok (0'dan büyükse) veya firma varsayılanı kullanılır.")).pack(
            anchor="w")
        alt = ttk.Frame(self, padding=12)
        alt.pack(fill="x")
        ttk.Button(alt, text="Vazgeç", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Kaydet", command=self._kaydet).pack(side="right", padx=8)
        self._yukle()

    def _kapsam_depo(self) -> int | None:
        return self.depo_id if self.v_kapsam.get() == "depo" else None

    def _yukle(self) -> None:
        from database.stok_uyari_service import StokUyariService, miktar_metni

        veri = StokUyariService.ayar_getir(self.stok_id, self.depo_id)
        kayit = StokUyariService.ayar_getir(self.stok_id, self._kapsam_depo())["kayit"]
        self.cb_birim.configure(values=["", *veri["birimler"]])
        takip = kayit.get("takip")
        self.v["takip"].set(self.TAKIP[0] if takip is None else (self.TAKIP[1] if takip else self.TAKIP[2]))
        for k in ("minimum", "hedef", "paket_kati"):
            self.v[k].set(miktar_metni(kayit.get(k)) if kayit.get(k) is not None else "")
        self.v["alim_birimi"].set(kayit.get("alim_birimi") or "")
        self.v["ted"].set(self._cari_metin.get(kayit.get("tercih_tedarikci_id"), ""))
        etkin = veri["etkin"]
        kaynak = etkin.get("kaynak", {})

        def goster(alan, deger):
            k = kaynak.get(alan) or "—"
            return f"{deger if deger not in (None, '') else '—'}   ({k})"

        self.etkin_lbl["takip"].configure(text=goster("takip", "Açık" if etkin.get("takip") else "Kapalı"))
        for k in ("minimum", "hedef", "paket_kati"):
            self.etkin_lbl[k].configure(text=goster(k, miktar_metni(etkin.get(k)) if etkin.get(k) is not None else None))
        self.etkin_lbl["alim_birimi"].configure(text=goster("alim_birimi", etkin.get("alim_birimi")))
        self.etkin_lbl["ted"].configure(text=goster("tercih_tedarikci_id",
                                                    self._cari_metin.get(etkin.get("tercih_tedarikci_id"))))

    def _kaydet(self) -> None:
        from database.stok_uyari_service import StokUyariService

        takip = self.v["takip"].get()
        ted_metin = self.v["ted"].get()
        ted_id = next((i for i, m in self.cariler if m == ted_metin), None) if ted_metin else None
        veriler = {
            "takip": None if takip == self.TAKIP[0] else takip == self.TAKIP[1],
            "minimum": self.v["minimum"].get().strip(), "hedef": self.v["hedef"].get().strip(),
            "alim_birimi": self.v["alim_birimi"].get().strip(), "paket_kati": self.v["paket_kati"].get().strip(),
            "tercih_tedarikci_id": ted_id,
        }
        try:
            StokUyariService.ayar_kaydet(self.stok_id, self._kapsam_depo(), veriler)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Ayar", str(exc), parent=self)
            return
        self.kaydedildi = True
        self.destroy()


class ErteleDialog(tk.Toplevel):
    def __init__(self, parent, adet: int):
        super().__init__(parent)
        self.sonuc: tuple[date, str] | None = None
        self.title("Ertele")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both")
        ttk.Label(f, text=f"{adet} ihtiyaç kaydı ertelenecek. Süre bitince liste ve bildirimde yeniden görünür.\n"
                          "Bekleyen müşteri siparişi olan ürünler ertelense de listede kalır.").grid(
            row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(f, text="Bitiş tarihi (gg.aa.yyyy)").grid(row=1, column=0, sticky="w", pady=(10, 2))
        self.v_bitis = tk.StringVar(value=(date.today() + timedelta(days=7)).strftime("%d.%m.%Y"))
        ttk.Entry(f, textvariable=self.v_bitis, width=14).grid(row=1, column=1, sticky="w", pady=(10, 2))
        ttk.Label(f, text="Gerekçe (zorunlu)").grid(row=2, column=0, sticky="nw", pady=2)
        self.t_neden = tk.Text(f, width=46, height=3)
        self.t_neden.grid(row=2, column=1, sticky="w", pady=2)
        alt = ttk.Frame(f)
        alt.grid(row=3, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(alt, text="Vazgeç", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Ertele", command=self._tamam).pack(side="right", padx=8)

    def _tamam(self) -> None:
        try:
            bitis = _tarih_oku(self.v_bitis.get())
        except ValueError as exc:
            messagebox.showwarning("Ertele", str(exc), parent=self)
            return
        neden = self.t_neden.get("1.0", "end").strip()
        if not bitis or bitis <= date.today():
            messagebox.showwarning("Ertele", "Bitiş tarihi bugünden sonra olmalı.", parent=self)
            return
        if not neden:
            messagebox.showwarning("Ertele", "Erteleme gerekçesi zorunludur.", parent=self)
            return
        self.sonuc = (bitis, neden)
        self.destroy()


class GenelAyarDialog(tk.Toplevel):
    def __init__(self, parent):
        from database.stok_uyari_service import StokUyariService

        super().__init__(parent)
        self.kaydedildi = False
        self.title("Stok uyarıları — firma varsayılanları")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        g = StokUyariService.genel_ayarlar()
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both")
        self.v_takip = tk.BooleanVar(value=g.get("takip", "1") == "1")
        self.v_min, self.v_hedef = tk.StringVar(value=g.get("minimum", "")), tk.StringVar(value=g.get("hedef", ""))
        self.v_ses = tk.BooleanVar(value=g.get("sesli_bildirim") == "1")
        ttk.Checkbutton(f, text="Ürünler varsayılan olarak takip edilsin", variable=self.v_takip).grid(
            row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(f, text="Varsayılan minimum (boş = kapalı)").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(f, textvariable=self.v_min, width=12).grid(row=1, column=1, sticky="w")
        ttk.Label(f, text="Varsayılan hedef (boş = kullanıcı belirler)").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Entry(f, textvariable=self.v_hedef, width=12).grid(row=2, column=1, sticky="w")
        ttk.Checkbutton(f, text="Yeni uyarıda sesli bildirim", variable=self.v_ses).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(f, foreground="#555", text=(
            "Öncelik: depo ayarı → ürün ayarı → stok kartı (minimum stok, varsayılan alış birimi) → firma.\n"
            f"Son tam tarama: {g.get('ilk_tarama') or 'yapılmadı'}")).grid(row=4, column=0, columnspan=2, sticky="w",
                                                                           pady=(8, 0))
        alt = ttk.Frame(f)
        alt.grid(row=5, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(alt, text="Vazgeç", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Kaydet", command=self._kaydet).pack(side="right", padx=8)

    def _kaydet(self) -> None:
        from database.stok_uyari_service import StokUyariService

        try:
            StokUyariService.genel_ayar_kaydet({
                "takip": "1" if self.v_takip.get() else "0", "minimum": self.v_min.get().strip(),
                "hedef": self.v_hedef.get().strip(), "sesli_bildirim": "1" if self.v_ses.get() else "0"})
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Genel ayarlar", str(exc), parent=self)
            return
        self.kaydedildi = True
        messagebox.showinfo("Genel ayarlar",
                            "Kaydedildi. Mevcut kayıtların yeni varsayılanla hesaplanması için "
                            "«Yeniden Değerlendir» kullanın.", parent=self)
        self.destroy()


class SiparisDialog(tk.Toplevel):
    """Seçili ihtiyaçlar → düzenlenebilir taslak sipariş satırları (tedarikçi, miktar, birim, fiyat)."""

    def __init__(self, parent, satirlar: list[dict], maliyet_goster: bool):
        from database.stok_uyari_service import StokUyariService

        super().__init__(parent)
        self.olusan: list[dict] = []
        self.title("Satın alma siparişi hazırla (taslak)")
        self.transient(parent)
        self.grab_set()
        self.geometry("1180x560")
        self.cariler = _cariler()
        self._cari_metin = {i: m for i, m in self.cariler}
        ust = ttk.Frame(self, padding=10)
        ust.pack(fill="x")
        ttk.Label(ust, justify="left", text=(
            "Miktarlar güncel stok ve beklenen alımla yeniden hesaplandı. Aynı tedarikçi + depo tek taslak "
            "siparişte toplanır.\nTaslak, kesinleştirilene kadar beklenen alıma sayılmaz; tedarikçiye "
            "gönderilmez. Fiyat son alıştan gelir (teklif değildir), TL ve KDV hariçtir.")).pack(anchor="w")
        tf = ttk.Frame(ust)
        tf.pack(anchor="w", pady=(6, 0))
        ttk.Label(tf, text="Termin (gg.aa.yyyy)").pack(side="left")
        self.v_termin = tk.StringVar(value=(date.today() + timedelta(days=7)).strftime("%d.%m.%Y"))
        ttk.Entry(tf, textvariable=self.v_termin, width=12).pack(side="left", padx=6)

        kap = ttk.Frame(self)
        kap.pack(fill="both", expand=True, padx=10)
        canvas = tk.Canvas(kap, highlightthickness=0)
        sb = ttk.Scrollbar(kap, orient="vertical", command=canvas.yview)
        ic = ttk.Frame(canvas)
        ic.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=ic, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for c, b in enumerate(("Ürün", "Depo", "Satılabilir / Beklenen", "Durum", "Tedarikçi", "Miktar", "Birim",
                               "B.Fiyat (TL)", "KDV %", "Ek sipariş", "İsk. %")):
            ttk.Label(ic, text=b, font=("Segoe UI", 9, "bold")).grid(row=0, column=c, sticky="w", padx=3, pady=3)
        self.girdiler: list[dict] = []
        for r, s in enumerate(satirlar, start=1):
            birimler = StokUyariService.ayar_getir(s["stok_id"], s["depo_id"])["birimler"]
            birim = s["alim_birimi"] or s["temel_birim"]
            fiyat = s.get("tahmini_fiyat") or {}
            fiyat_tl = ""
            if fiyat and maliyet_goster:
                fiyat_tl = str((fiyat["fiyat"] * (fiyat.get("kur") or 1) if fiyat["para_birimi"] != "TRY"
                                else fiyat["fiyat"]).quantize(Decimal("0.01"))).replace(".", ",")
            miktar = s["oneri_alim"] if s["oneri_alim"] is not None and s["oneri_alim"] > 0 else None
            v = {
                "ted": tk.StringVar(value=self._cari_metin.get(s["tedarikci_id"], "")),
                "miktar": tk.StringVar(value=_miktar(miktar) if miktar is not None else ""),
                "birim": tk.StringVar(value=birim), "fiyat": tk.StringVar(value=fiyat_tl),
                "kdv": tk.StringVar(value=""), "ek": tk.BooleanVar(value=False), "iskonto": tk.StringVar(value=""),
            }
            taslak_var = bool(s["bag"] and s["bag"].get("taslak"))
            ttk.Label(ic, text=f"{s['stok_kodu']} — {s['stok_adi'][:40]}").grid(row=r, column=0, sticky="w", padx=3)
            ttk.Label(ic, text=s["depo"]).grid(row=r, column=1, sticky="w", padx=3)
            ttk.Label(ic, text=f"{_miktar(s['satilabilir'])} / {_miktar(s['beklenen'])} {s['temel_birim']}").grid(
                row=r, column=2, sticky="w", padx=3)
            uyari = s["durum"] + (" — hedef yok, miktarı siz girin" if s["hedef"] is None else "")
            ttk.Label(ic, text=uyari, foreground="#B83B3B" if taslak_var or s["hedef"] is None else "#333").grid(
                row=r, column=3, sticky="w", padx=3)
            ttk.Combobox(ic, textvariable=v["ted"], values=[m for _i, m in self.cariler], width=30,
                         state="readonly").grid(row=r, column=4, padx=3)
            ttk.Entry(ic, textvariable=v["miktar"], width=9).grid(row=r, column=5, padx=3)
            ttk.Combobox(ic, textvariable=v["birim"], values=birimler, width=8, state="readonly").grid(
                row=r, column=6, padx=3)
            ttk.Entry(ic, textvariable=v["fiyat"], width=10).grid(row=r, column=7, padx=3)
            ttk.Entry(ic, textvariable=v["kdv"], width=5).grid(row=r, column=8, padx=3)
            cb = ttk.Checkbutton(ic, variable=v["ek"])
            cb.grid(row=r, column=9, padx=3)
            if not taslak_var:
                cb.state(["disabled"])
            ttk.Entry(ic, textvariable=v["iskonto"], width=5).grid(row=r, column=10, padx=3)
            self.girdiler.append({"satir": s, "v": v, "taslak_var": taslak_var})
        alt = ttk.Frame(self, padding=10)
        alt.pack(fill="x")
        ttk.Button(alt, text="Vazgeç", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Taslak Siparişleri Oluştur", command=self._olustur).pack(side="right", padx=8)

    def _olustur(self) -> None:
        from database.stok_uyari_service import StokUyariService

        try:
            termin = _tarih_oku(self.v_termin.get())
            secimler = []
            for g in self.girdiler:
                s, v = g["satir"], g["v"]
                miktar = _sayi_oku(v["miktar"].get(), f"{s['stok_kodu']} miktarı")
                if miktar is None or miktar <= 0:
                    continue
                if g["taslak_var"] and not v["ek"].get():
                    raise ValueError(f"{s['stok_kodu']}: bu ihtiyaç için taslak sipariş zaten var. "
                                     "Yine de eklemek için «Ek sipariş» kutusunu işaretleyin.")
                ted_id = next((i for i, m in self.cariler if m == v["ted"].get()), None)
                if not ted_id:
                    raise ValueError(f"{s['stok_kodu']}: tedarikçi seçin.")
                kdv = _sayi_oku(v["kdv"].get(), "KDV")
                secimler.append({
                    "ihtiyac_id": s["id"], "row_version": s["row_version"], "tedarikci_id": ted_id,
                    "miktar": miktar, "birim": v["birim"].get(), "fiyat": _sayi_oku(v["fiyat"].get(), "Fiyat") or 0,
                    "kdv": kdv, "teslim_depo": s["depo"], "ek_siparis": bool(v["ek"].get()),
                    "iskonto": _sayi_oku(v["iskonto"].get(), "İskonto") or 0,
                })
            if not secimler:
                raise ValueError("Miktarı sıfırdan büyük en az bir satır girin.")
            self.olusan = StokUyariService.siparis_hazirla(secimler, termin)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Sipariş hazırla", str(exc), parent=self)
            return
        self.destroy()


def stok_uyari_goster(app) -> None:
    from stoklar_ui import stoklar_hub_goster

    StokUyariEkrani(app, lambda: stoklar_hub_goster(app))
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: stok_uyari_goster(app))
