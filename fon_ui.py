"""Fon Yönetimi ekranı (Finans menüsü): bakiyeler, hareketler, para ayırma / kullanım, raporlar."""

from __future__ import annotations

import tkinter as tk
import uuid
from datetime import date, datetime
from decimal import Decimal
from tkinter import filedialog, messagebox, ttk

from database.access import yetki_var
from database.fon_service import (
    DESTEKLENEN_TAHSILAT_ACIKLAMA,
    TUTAR_ACIKLAMALARI,
    FonService,
)
from fon_rapor_cikti import excel_yaz, hucre_metni, pdf_yaz

BAKIYE_KOLONLARI = (
    ("fon", "Fon", 150, "w"),
    ("net_satis_payi", "Net Satış Payı", 110, "e"),
    ("tahsil_edilen", "Tahsil Edilen", 105, "e"),
    ("tahsil_edilmemis", "Tahsil Edilmemiş", 115, "e"),
    ("ayrilmis", "Ayrılmış", 95, "e"),
    ("kullanim", "Kullanım", 95, "e"),
    ("transfer_net", "Transfer (net)", 100, "e"),
    ("kullanilabilir", "Kullanılabilir", 100, "e"),
    ("ayrilabilir", "Ayrılabilecek Ek", 115, "e"),
    ("fon_acigi", "Fon Açığı", 90, "e"),
    ("donem_net_satis_payi", "Dönem Satış Payı", 115, "e"),
    ("donem_ayrilmis", "Dönem Ayrılan", 100, "e"),
    ("donem_kullanim", "Dönem Kullanım", 105, "e"),
)
HAREKET_KOLONLARI = (
    ("tarih", "Tarih", 80, "w"), ("tur", "Tür", 110, "w"), ("belge_no", "Belge No", 110, "w"),
    ("urun", "Ürün", 170, "w"), ("cari", "Müşteri", 160, "w"), ("fon_kod", "Fon", 80, "w"),
    ("yontem_adi", "Yöntem", 105, "w"), ("para_birimi", "Belge PB", 65, "w"), ("kur", "Kur", 70, "e"),
    ("doviz_taban", "Döviz Taban", 95, "e"),
    ("oran", "%", 55, "e"), ("taban", "TL Taban", 95, "e"), ("tutar", "TL Tutar", 90, "e"),
    ("durum", "Durum", 75, "w"), ("aciklama", "Açıklama / Kaynak", 220, "w"),
)
PARA_KOLONLARI = (
    ("id", "No", 50, "e"), ("tarih", "Tarih", 80, "w"), ("tur_adi", "İşlem", 130, "w"),
    ("fon_kod", "Fon", 80, "w"), ("tutar", "Tutar", 90, "e"), ("hesap_adi", "Kasa/Banka", 110, "w"),
    ("belge", "Belge", 150, "w"), ("kaynak", "Kaynak Tahsilat", 170, "w"),
    ("yardim_alan", "Yardım Alan", 120, "w"), ("amac", "Amaç", 130, "w"),
    ("gerekce", "Gerekçe", 130, "w"), ("kullanici", "Kullanıcı", 100, "w"),
)
URUN_KOLONLARI = (
    ("urun_kodu", "Ürün Kodu", 100, "w"), ("urun_adi", "Ürün Adı", 200, "w"), ("fon_kod", "Fon", 80, "w"),
    ("taban", "Net Taban", 110, "e"), ("satis_payi", "Satış Payı", 100, "e"), ("iade", "İade", 90, "e"),
    ("net", "Net Pay", 100, "e"),
)
TARIH_KOLONLARI = (
    ("tarih", "Tarih", 90, "w"), ("fon_kod", "Fon", 90, "w"), ("satis_payi", "Satış Payı", 110, "e"),
    ("iade", "İade", 100, "e"), ("ayrilan", "Ayrılan (net)", 110, "e"), ("kullanim", "Kullanım (net)", 110, "e"),
    ("transfer", "Transfer (net)", 110, "e"),
)
TRANSFER_KOLONLARI = (
    ("transfer_no", "Transfer No", 110, "w"), ("tarih", "Tarih", 80, "w"), ("kaynak_fon", "Kaynak Fon", 90, "w"),
    ("hedef_fon", "Hedef Fon", 90, "w"), ("tutar", "Tutar (TL)", 100, "e"), ("durum", "Durum", 65, "w"),
    ("aciklama", "Açıklama", 200, "w"), ("kullanici", "Kullanıcı", 100, "w"),
    ("iptal_tarihi", "İptal Tarihi", 85, "w"), ("iptal_gerekcesi", "İptal Gerekçesi", 180, "w"),
)
MUTABAKAT_KOLONLARI = (
    ("fon_kod", "Fon", 90, "w"), ("kalem", "Kalem", 150, "w"), ("acilis", "Açılış", 110, "e"),
    ("donem", "Dönem Hareketi", 120, "e"), ("kapanis", "Dönem Sonu", 110, "e"), ("tutarli", "Tutarlı", 70, "w"),
)
TANIM_KOLONLARI = (
    ("kod", "Kod", 90, "w"), ("ad", "Ad", 150, "w"), ("amac", "Amaç", 200, "w"),
    ("para_birimi", "Takip PB", 70, "w"), ("aktif", "Aktif", 60, "w"),
    ("yontem_adi", "Yöntem", 110, "w"), ("ek_bedel_kdv_orani", "Ek Bedel KDV %", 95, "e"),
    ("ek_bedel_hesap_kodu", "Ek Bedel Hesabı", 110, "w"),
    ("kullanim_hesap_kodu", "Kullanım Hesabı", 110, "w"), ("ayirma_hesap_kodu", "Ayırma Hesabı", 110, "w"),
    ("aciklama", "Açıklama", 200, "w"),
)
YONTEM_SECENEKLERI = {"İç pay": "IC_PAY", "Faturaya ek bedel": "EK_BEDEL"}


def _tarih_oku(metin: str) -> date | None:
    metin = (metin or "").strip()
    if not metin:
        return None
    try:
        return datetime.strptime(metin, "%d.%m.%Y").date()
    except ValueError as hata:
        raise ValueError(f"Tarih gg.aa.yyyy biçiminde olmalı: {metin}") from hata


def _oran_metni(oran) -> str:
    if oran is None or oran == "":
        return ""
    metin = format(Decimal(str(oran)).normalize(), "f")
    return metin.replace(".", ",")


def _tablo(parent, kolonlar, yukseklik=14) -> ttk.Treeview:
    kap = ttk.Frame(parent)
    kap.pack(fill="both", expand=True)
    tree = ttk.Treeview(kap, columns=[k[0] for k in kolonlar], show="headings", height=yukseklik)
    for anahtar, baslik, en, hiza in kolonlar:
        tree.heading(anahtar, text=baslik)
        tree.column(anahtar, width=en, anchor=hiza, stretch=True)
    dikey = ttk.Scrollbar(kap, orient="vertical", command=tree.yview)
    yatay = ttk.Scrollbar(kap, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=dikey.set, xscrollcommand=yatay.set)
    tree.grid(row=0, column=0, sticky="nsew")
    dikey.grid(row=0, column=1, sticky="ns")
    yatay.grid(row=1, column=0, sticky="ew")
    kap.rowconfigure(0, weight=1)
    kap.columnconfigure(0, weight=1)
    tree.tag_configure("iptal", foreground="#888888")
    tree.tag_configure("uyari", foreground="#B00020")
    return tree


def _doldur(tree: ttk.Treeview, kolonlar, satirlar: list[dict], etiket=None) -> None:
    tree.delete(*tree.get_children())
    for i, s in enumerate(satirlar):
        tree.insert("", "end", iid=str(i), values=[hucre_metni(s.get(k[0])) for k in kolonlar],
                    tags=(etiket(s),) if etiket and etiket(s) else ())
    if not satirlar:
        tree.insert("", "end", iid="bos", values=["Kayıt yok"] + [""] * (len(kolonlar) - 1), tags=("iptal",))


def fon_yonetimi_goster(app) -> None:
    if not yetki_var("fon_goruntuleme", "finans_goruntuleme", "finans_duzenleme"):
        messagebox.showerror("Fon Yönetimi", "Fon yönetimini görüntüleme yetkiniz yok.")
        return
    try:
        FonService.varsayilan_fonlari_hazirla()
    except Exception as hata:  # noqa: BLE001
        messagebox.showerror("Fon Yönetimi", f"Fon tabloları hazırlanamadı:\n{hata}")
        return
    app._icerigi_temizle()
    FonYonetimiSayfasi(app.icerik, app).pack(fill="both", expand=True)
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: fon_yonetimi_goster(app))


class FonYonetimiSayfasi(ttk.Frame):
    def __init__(self, parent, app=None):
        super().__init__(parent)
        self.app = app
        self._veri: dict[str, list[dict]] = {}
        ust = ttk.Frame(self)
        ust.pack(fill="x")
        ttk.Label(ust, text="FON YÖNETİMİ", style="Baslik.TLabel").pack(side="left")
        if app is not None:
            from finans_ui import finans_menusu_goster

            ttk.Button(ust, text="← Finans", command=lambda: finans_menusu_goster(app)).pack(side="right")

        aciklama = " · ".join(TUTAR_ACIKLAMALARI.values())
        ttk.Label(self, text=aciklama, wraplength=1150, foreground="#333").pack(anchor="w", pady=(6, 0))
        ttk.Label(self, text=DESTEKLENEN_TAHSILAT_ACIKLAMA, wraplength=1150, foreground="#555").pack(
            anchor="w", pady=(2, 6))

        filtre = ttk.Frame(self)
        filtre.pack(fill="x", pady=(0, 6))
        bugun = date.today()
        self.bas_var = tk.StringVar(value=date(bugun.year, 1, 1).strftime("%d.%m.%Y"))
        self.bit_var = tk.StringVar(value=bugun.strftime("%d.%m.%Y"))
        ttk.Label(filtre, text="Başlangıç:").pack(side="left")
        ttk.Entry(filtre, textvariable=self.bas_var, width=11).pack(side="left", padx=(2, 8))
        ttk.Label(filtre, text="Bitiş:").pack(side="left")
        ttk.Entry(filtre, textvariable=self.bit_var, width=11).pack(side="left", padx=(2, 8))
        ttk.Label(filtre, text="Şube:").pack(side="left")
        self.subeler = self._subeler()
        self.sube_var = tk.StringVar(value="Tümü")
        ttk.Combobox(filtre, textvariable=self.sube_var, state="readonly", width=18,
                     values=["Tümü"] + list(self.subeler)).pack(side="left", padx=(2, 8))
        ttk.Button(filtre, text="Yenile", command=self.yenile).pack(side="left")
        self.ozet_lbl = ttk.Label(filtre, text="", foreground="#1F4E79")
        self.ozet_lbl.pack(side="left", padx=12)

        islem = ttk.Frame(self)
        islem.pack(fill="x", pady=(0, 6))
        for metin, komut in (
            ("Para Ayır", self.para_ayir), ("Ayırmayı Geri Al", self.ayirmayi_geri_al),
            ("Fon Kullanımı", self.fon_kullan), ("Kullanımı Düzelt", self.kullanimi_duzelt),
            ("Fon Transferi", self.fon_transferi), ("Transferi İptal Et", self.transfer_iptal),
            ("Excel", lambda: self.disari_aktar("excel")), ("PDF", lambda: self.disari_aktar("pdf")),
        ):
            ttk.Button(islem, text=metin, command=komut).pack(side="left", padx=(0, 6))

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)
        self.sekmeler: dict[str, tuple[ttk.Treeview, tuple, str]] = {}
        for anahtar, baslik, kolonlar in (
            ("bakiye", "Fon Bakiyeleri", BAKIYE_KOLONLARI),
            ("hareket", "Satış Payı Hareketleri", HAREKET_KOLONLARI),
            ("para", "Para Ayırma / Kullanım", PARA_KOLONLARI),
            ("transfer", "Fon Transferleri", TRANSFER_KOLONLARI),
            ("urun", "Ürün Bazlı Rapor", URUN_KOLONLARI),
            ("tarih", "Tarih Bazlı Rapor", TARIH_KOLONLARI),
            ("mutabakat", "Mutabakat", MUTABAKAT_KOLONLARI),
            ("tanim", "Fon Tanımları", TANIM_KOLONLARI),
        ):
            cerceve = ttk.Frame(self.nb, padding=4)
            self.nb.add(cerceve, text=f"  {baslik}  ")
            if anahtar == "tanim":
                self._tanim_araclari(cerceve)
            if anahtar == "hareket":
                ttk.Label(cerceve, text="Çift tıklama kaynak belgeyi açar. İptal edilen kayıtlar gri görünür; "
                                        "toplamlara girmez. Dövizli belgelerde fon tabanı kayıtlı belge kuru "
                                        "ile TL'ye çevrilir; hak sonradan yeniden değerlenmez.",
                          foreground="#555").pack(anchor="w")
            if anahtar == "transfer":
                self._transfer_araclari(cerceve)
            tree = _tablo(cerceve, kolonlar)
            self.sekmeler[anahtar] = (tree, kolonlar, baslik)
        self.sekmeler["hareket"][0].bind("<Double-1>", self._kaynak_ac)
        self.sekmeler["transfer"][0].bind("<Double-1>", self._transfer_hareketleri)
        self.yenile()

    # ---------------------------------------------------------------- veri
    @staticmethod
    def _subeler() -> dict[str, int]:
        try:
            from sqlalchemy import select

            from database.database import get_session
            from database.models.sube import Sube

            with get_session() as s:
                return {f"{x.sube_kodu} - {x.sube_adi}": x.id for x in s.scalars(select(Sube).order_by(Sube.sube_kodu))}
        except Exception:  # noqa: BLE001
            return {}

    def _filtre(self):
        bas = _tarih_oku(self.bas_var.get())
        bit = _tarih_oku(self.bit_var.get())
        if bas and bit and bas > bit:
            raise ValueError("Başlangıç tarihi bitişten sonra olamaz.")
        return bas, bit, self.subeler.get(self.sube_var.get())

    def yenile(self) -> None:
        try:
            bas, bit, sube = self._filtre()
            bakiye = FonService.bakiyeler(bas, bit, sube)
            for b in bakiye:
                b["fon"] = f"{b['fon_kod']} - {b['fon_ad']}" + ("" if b["aktif"] else " (pasif)")
            hareket = FonService.hareket_listesi(baslangic=bas, bitis=bit, sube_id=sube)
            for h in hareket:
                h["urun"] = f"{h['urun_kodu']} {h['urun_adi']}".strip()
            self._veri = {
                "bakiye": bakiye, "hareket": hareket,
                "para": FonService.para_hareketleri(baslangic=bas, bitis=bit),
                "transfer": FonService.transfer_listesi(
                    fon_id=self._transfer_fonlari.get(self.transfer_fon_var.get()), baslangic=bas, bitis=bit),
                "urun": FonService.urun_bazli_rapor(bas, bit),
                "tarih": FonService.tarih_bazli_rapor(bas, bit),
                "mutabakat": FonService.mutabakat(bas, bit, sube),
                "tanim": FonService.fon_listesi(),
            }
        except Exception as hata:  # noqa: BLE001
            messagebox.showerror("Fon Yönetimi", str(hata), parent=self)
            return
        etiketler = {
            "bakiye": lambda s: "uyari" if s.get("fon_acigi") else None,
            "hareket": lambda s: "iptal" if s.get("durum") == "IPTAL" else (
                "uyari" if s.get("durum") == "INCELEME" else None),
            "mutabakat": lambda s: None if s.get("tutarli") else "uyari",
            "transfer": lambda s: "iptal" if s.get("durum") == "İptal" else None,
            "tanim": lambda s: None if s.get("aktif") else "iptal",
        }
        for anahtar, (tree, kolonlar, _) in self.sekmeler.items():
            _doldur(tree, kolonlar, self._veri.get(anahtar, []), etiketler.get(anahtar))
        toplam_acik = sum((b["fon_acigi"] for b in self._veri["bakiye"]), Decimal("0"))
        self.ozet_lbl.configure(
            text=f"Dönem: {self.bas_var.get()} – {self.bit_var.get()}  ·  Bakiyeler dönem sonu itibarıyla"
                 + (f"  ·  Fon açığı: {hucre_metni(toplam_acik)} TL" if toplam_acik else ""))

    def _secili(self, anahtar: str) -> dict | None:
        tree = self.sekmeler[anahtar][0]
        sec = tree.selection()
        if not sec or sec[0] == "bos":
            return None
        return self._veri.get(anahtar, [])[int(sec[0])]

    # ---------------------------------------------------------------- kaynak belge
    def _kaynak_ac(self, _event=None) -> None:
        s = self._secili("hareket")
        if not s:
            return
        try:
            if s["kaynak_turu"] == "SATIS_FATURASI":
                from app import CariDialog, SatisFaturasiDialog
                from database.satis_faturasi_service import SatisFaturasiService

                fatura = SatisFaturasiService.getir(s["belge_id"])
                if not fatura:
                    raise ValueError("Satış faturası bulunamadı.")
                SatisFaturasiDialog(self, fatura=fatura, cari_ac=lambda c: CariDialog(self, c))
            else:
                from app import SatisIadeFaturasiDialog
                from database.satis_iade_faturasi_service import SatisIadeFaturasiService

                iade = SatisIadeFaturasiService.getir(s["belge_id"])
                if not iade:
                    raise ValueError("Satış iade faturası bulunamadı.")
                SatisIadeFaturasiDialog(self, iade=iade)
        except Exception as hata:  # noqa: BLE001
            messagebox.showerror("Kaynak belge", str(hata), parent=self)

    # ---------------------------------------------------------------- para işlemleri
    def _fon_secenekleri(self, sadece_aktif=True) -> dict[str, int]:
        return {f"{f['kod']} - {f['ad']}": f["id"] for f in FonService.fon_listesi(sadece_aktif)}

    @staticmethod
    def _hesaplar() -> list[str]:
        try:
            from sqlalchemy import select

            from database.database import get_session
            from database.models.finans import FinansHesabi

            with get_session() as s:
                return [h.hesap_adi for h in s.scalars(
                    select(FinansHesabi).where(FinansHesabi.aktif.is_(True),
                                               FinansHesabi.hesap_turu.in_(("KASA", "BANKA")))
                    .order_by(FinansHesabi.hesap_adi))]
        except Exception:  # noqa: BLE001
            return []

    def para_ayir(self) -> None:
        fonlar = self._fon_secenekleri()
        bilgi = "\n".join(f"{b['fon_kod']}: ayrılabilecek ek tutar {hucre_metni(b['ayrilabilir'])} TL"
                          for b in self._veri.get("bakiye", []) if b["aktif"])
        kaynaklar = {"(Kaynak seçilmedi)": None}
        for k in FonService.kaynak_tahsilatlar():
            if k["kalan"] > 0:
                kaynaklar[f"{hucre_metni(k['tarih'])} {k['aciklama']} — kalan {hucre_metni(k['kalan'])} TL"] = k["anahtar"]
        sonuc = FormDialog.ac(self, "Para Ayır", [
            ("fon", "Fon", "combo", list(fonlar)), ("tarih", "Tarih", "tarih", None),
            ("tutar", "Tutar (TL)", "entry", None), ("aciklama", "Açıklama", "entry", None),
            ("hesap", "Kasa / Banka", "combo_serbest", [""] + self._hesaplar()),
            ("belge", "Finans belge no (isteğe bağlı)", "entry", None),
            ("kaynak", "Kaynak tahsilat", "combo", list(kaynaklar)),
        ], bilgi=bilgi + "\n\nBu işlem yalnız iç takiptir; banka transferi veya muhasebe fişi oluşturmaz.")
        if not sonuc:
            return
        self._calistir(lambda: FonService.para_ayir(
            fonlar[sonuc["fon"]], sonuc["tarih"], sonuc["tutar"], aciklama=sonuc["aciklama"],
            hesap_adi=sonuc["hesap"], finans_belge_no=sonuc["belge"], kaynak_anahtar=kaynaklar.get(sonuc["kaynak"]),
            istek_kimligi=sonuc["_istek"]), "Para ayırma kaydedildi.")

    def fon_kullan(self) -> None:
        fonlar = self._fon_secenekleri()
        bilgi = "\n".join(f"{b['fon_kod']}: kullanılabilir {hucre_metni(b['kullanim_limiti'])} TL"
                          + (f" — FON AÇIĞI {hucre_metni(b['fon_acigi'])} TL" if b["fon_acigi"] else "")
                          for b in self._veri.get("bakiye", []) if b["aktif"])
        sonuc = FormDialog.ac(self, "Fon Kullanımı", [
            ("fon", "Fon", "combo", list(fonlar)), ("tarih", "Tarih", "tarih", None),
            ("tutar", "Tutar (TL)", "entry", None), ("yardim_alan", "Yardım alan / ödeme yapılan", "entry", None),
            ("amac", "Amaç", "entry", None), ("aciklama", "Açıklama", "entry", None),
            ("hesap", "Kasa / Banka", "combo_serbest", [""] + self._hesaplar()),
            ("belge", "Finans belge no (isteğe bağlı)", "entry", None),
        ], bilgi=bilgi)
        if not sonuc:
            return
        self._calistir(lambda: FonService.fon_kullan(
            fonlar[sonuc["fon"]], sonuc["tarih"], sonuc["tutar"], yardim_alan=sonuc["yardim_alan"],
            amac=sonuc["amac"], aciklama=sonuc["aciklama"], hesap_adi=sonuc["hesap"],
            finans_belge_no=sonuc["belge"], istek_kimligi=sonuc["_istek"]), "Fon kullanımı kaydedildi.")

    def _ters_kayit(self, tur: str, baslik: str, fonksiyon) -> None:
        s = self._secili("para")
        if not s or s["tur"] != tur:
            self.nb.select(2)
            messagebox.showinfo(baslik, f"«Para Ayırma / Kullanım» sekmesinden bir "
                                        f"{'ayırma' if tur == 'AYIRMA' else 'kullanım'} kaydı seçin.", parent=self)
            return
        sonuc = FormDialog.ac(self, baslik, [
            ("tutar", "Tutar (TL)", "entry", None), ("gerekce", "Gerekçe", "entry", None),
            ("tarih", "Tarih", "tarih", None),
        ], bilgi=f"Kayıt #{s['id']} · {s['fon_kod']} · {hucre_metni(s['tutar'])} TL\n"
                 "Düzeltme silme yapmaz; gerekçeli ters kayıt oluşturur.", varsayilan={"tutar": hucre_metni(s["tutar"])})
        if not sonuc:
            return
        self._calistir(lambda: fonksiyon(s["id"], sonuc["tutar"], sonuc["gerekce"], sonuc["tarih"],
                                         istek_kimligi=sonuc["_istek"]), "Ters kayıt oluşturuldu.")

    def ayirmayi_geri_al(self) -> None:
        self._ters_kayit("AYIRMA", "Ayırmayı Geri Al", FonService.ayirmayi_geri_al)

    def kullanimi_duzelt(self) -> None:
        self._ters_kayit("KULLANIM", "Kullanımı Düzelt", FonService.kullanimi_duzelt)

    # ---------------------------------------------------------------- fon transferi
    def _transfer_araclari(self, cerceve) -> None:
        bar = ttk.Frame(cerceve)
        bar.pack(fill="x", pady=(0, 4))
        self._transfer_fonlari = {"Tümü": None, **self._fon_secenekleri(sadece_aktif=False)}
        self.transfer_fon_var = tk.StringVar(value="Tümü")
        ttk.Label(bar, text="Fon:").pack(side="left")
        ttk.Combobox(bar, textvariable=self.transfer_fon_var, state="readonly", width=22,
                     values=list(self._transfer_fonlari)).pack(side="left", padx=(2, 8))
        ttk.Button(bar, text="Filtrele", command=self.yenile).pack(side="left")
        ttk.Label(bar, text="Tarih filtresi üstteki dönemdir. Çift tıklama iki fondaki hareketleri ve iptal "
                            "ters kayıtlarını gösterir. Transfer kasa/banka hareketi ve muhasebe fişi oluşturmaz.",
                  foreground="#555").pack(side="left", padx=10)

    def fon_transferi(self) -> None:
        if not yetki_var("fon_transfer", "finans_duzenleme"):
            messagebox.showerror("Fon Transferi", "Fon transferi yetkiniz yok.", parent=self)
            return
        fonlar = self._fon_secenekleri()
        if len(fonlar) < 2:
            messagebox.showinfo("Fon Transferi", "Transfer için en az iki aktif fon gerekir.", parent=self)
            return
        sonuc = TransferDialog.ac(self, fonlar)
        if not sonuc:
            return
        self._calistir(lambda: FonService.transfer_kaydet(
            fonlar[sonuc["kaynak"]], fonlar[sonuc["hedef"]], sonuc["tarih"], sonuc["tutar"],
            aciklama=sonuc["aciklama"], istek_kimligi=sonuc["_istek"]), "Fon transferi kaydedildi.")

    def transfer_iptal(self) -> None:
        s = self._secili("transfer")
        if not s:
            self.nb.select(3)
            messagebox.showinfo("Transfer İptali", "«Fon Transferleri» sekmesinden bir transfer seçin.", parent=self)
            return
        if s["durum"] == "İptal":
            messagebox.showinfo("Transfer İptali", "Bu transfer zaten iptal edilmiş.", parent=self)
            return
        sonuc = FormDialog.ac(self, "Transfer İptali", [
            ("gerekce", "Gerekçe", "entry", None), ("tarih", "İptal tarihi", "tarih", None),
        ], bilgi=f"{s['transfer_no']} · {s['kaynak_fon']} → {s['hedef_fon']} · {hucre_metni(s['tutar'])} TL\n"
                 "İptal silme yapmaz; iki fona bağlı ters hareket yazar. Hedef fonda transfer edilen tutar "
                 "kullanılmışsa iptal engellenir.")
        if not sonuc:
            return
        self._calistir(lambda: FonService.transfer_iptal(s["id"], sonuc["gerekce"], sonuc["tarih"]),
                       "Transfer iptal edildi.")

    def _transfer_hareketleri(self, _event=None) -> None:
        s = self._secili("transfer")
        if not s:
            return
        kolonlar = (("id", "No", 50, "e"), ("tarih", "Tarih", 80, "w"), ("fon_kod", "Fon", 80, "w"),
                    ("tur_adi", "İşlem", 130, "w"), ("tutar", "Tutar (TL)", 100, "e"),
                    ("ters", "Ters Kayıt", 70, "w"), ("aciklama", "Açıklama", 260, "w"),
                    ("gerekce", "Gerekçe", 160, "w"), ("kullanici", "Kullanıcı", 100, "w"))
        try:
            satirlar = FonService.transfer_hareketleri(s["id"])
        except Exception as hata:  # noqa: BLE001
            messagebox.showerror("Transfer hareketleri", str(hata), parent=self)
            return
        for h in satirlar:
            h["ters"] = "Evet" if h["ters_kayit"] else ""
        pencere = tk.Toplevel(self)
        pencere.title(f"Transfer Hareketleri — {s['transfer_no']}")
        pencere.geometry("1000x320")
        _doldur(_tablo(ttk.Frame(pencere, padding=8), kolonlar), kolonlar, satirlar,
                lambda h: "iptal" if h["ters_kayit"] else None)
        for c in pencere.winfo_children():
            c.pack(fill="both", expand=True)

    def _calistir(self, islem, mesaj: str) -> None:
        try:
            islem()
        except Exception as hata:  # noqa: BLE001
            messagebox.showerror("Fon Yönetimi", str(hata), parent=self)
            return
        messagebox.showinfo("Fon Yönetimi", mesaj, parent=self)
        self.yenile()

    # ---------------------------------------------------------------- tanımlar
    def _tanim_araclari(self, cerceve) -> None:
        bar = ttk.Frame(cerceve)
        bar.pack(fill="x", pady=(0, 4))
        for metin, komut in (("Yeni Fon", self.fon_yeni), ("Düzenle", self.fon_duzenle),
                             ("Aktif / Pasif", self.fon_aktiflik), ("Sil", self.fon_sil),
                             ("Hesap Eşlemeleri", self.hesap_esleme),
                             ("Stok Grubuna Toplu Oran", self.toplu_oran)):
            ttk.Button(bar, text=metin, command=komut).pack(side="left", padx=(0, 6))

    def _hesap_secenekleri(self) -> tuple[list[str], callable]:
        hesaplar = [""] + [f"{k} - {a}" for k, a in FonService.hesap_listesi()]
        bul = lambda kod: next((h for h in hesaplar if kod and h.startswith(f"{kod} - ")), "")  # noqa: E731
        return hesaplar, bul

    def _tanim_formu(self, baslik, mevcut=None) -> dict | None:
        hesaplar, bul = self._hesap_secenekleri()
        varsayilan = dict(mevcut or {})
        yontem_kodu = varsayilan.get("yontem") or "IC_PAY"
        varsayilan["yontem"] = next((e for e, k in YONTEM_SECENEKLERI.items() if k == yontem_kodu), "İç pay")
        varsayilan["ek_bedel_kdv_orani"] = _oran_metni(varsayilan.get("ek_bedel_kdv_orani"))
        varsayilan["ek_bedel_hesap_kodu"] = bul(varsayilan.get("ek_bedel_hesap_kodu"))
        sonuc = FormDialog.ac(self, baslik, [
            ("kod", "Kod", "entry", None), ("ad", "Ad", "entry", None), ("amac", "Amaç", "entry", None),
            ("aciklama", "Açıklama", "entry", None),
            ("yontem", "Yöntem", "combo", list(YONTEM_SECENEKLERI)),
            ("ek_bedel_kdv_orani", "Ek bedel KDV oranı %", "entry", None),
            ("ek_bedel_hesap_kodu", "Ek bedel muhasebe hesabı", "combo", hesaplar),
        ], bilgi="Takip para birimi: TL.\n"
                 "İç pay: fon, ürün satış tutarının içinden ayrılır; fatura toplamı değişmez (varsayılan).\n"
                 "Faturaya ek bedel: fon bedeli ürünlerin KDV hariç, iskonto ve uzlaşma sonrası net tutarı "
                 "üzerinden hesaplanıp faturaya ayrı satır olarak eklenir; KDV oranı ve muhasebe hesabı zorunludur. "
                 "Yöntem değişikliği yalnız sonraki belgelere uygulanır.",
            varsayilan=varsayilan)
        if sonuc:
            sonuc["yontem"] = YONTEM_SECENEKLERI.get(sonuc["yontem"], "IC_PAY")
            sonuc["ek_bedel_hesap_kodu"] = (sonuc["ek_bedel_hesap_kodu"] or "").split(" - ")[0].strip()
            if sonuc["yontem"] != "EK_BEDEL":
                sonuc["ek_bedel_kdv_orani"] = sonuc["ek_bedel_hesap_kodu"] = None
        return sonuc

    def fon_yeni(self) -> None:
        sonuc = self._tanim_formu("Yeni Fon")
        if sonuc:
            self._calistir(lambda: FonService.fon_kaydet(sonuc), "Fon kaydedildi.")

    def fon_duzenle(self) -> None:
        s = self._secili("tanim")
        if not s:
            messagebox.showinfo("Fon", "Bir fon seçin.", parent=self)
            return
        sonuc = self._tanim_formu("Fonu Düzenle", s)
        if sonuc:
            self._calistir(lambda: FonService.fon_kaydet(sonuc, s["id"]), "Fon güncellendi.")

    def fon_aktiflik(self) -> None:
        s = self._secili("tanim")
        if s:
            self._calistir(lambda: FonService.fon_aktiflik(s["id"], not s["aktif"]),
                           "Fon pasifleştirildi." if s["aktif"] else "Fon aktifleştirildi.")

    def fon_sil(self) -> None:
        s = self._secili("tanim")
        if s and messagebox.askyesno("Fon", f"{s['kod']} silinsin mi?", parent=self):
            self._calistir(lambda: FonService.fon_sil(s["id"]), "Fon silindi.")

    def hesap_esleme(self) -> None:
        s = self._secili("tanim")
        if not s:
            messagebox.showinfo("Hesap Eşlemeleri", "Bir fon seçin.", parent=self)
            return
        hesaplar, bul = self._hesap_secenekleri()
        ek_bedel = s.get("yontem") == "EK_BEDEL"
        alanlar = [
            ("kullanim", "Fon kullanımı hesabı", "combo", hesaplar),
            ("ayirma", "Ayrılmış fon hesabı", "combo", hesaplar),
        ]
        if ek_bedel:
            alanlar.append(("ek_bedel", "Ek fon bedeli gelir hesabı", "combo", hesaplar))
        sonuc = FormDialog.ac(self, f"Hesap Eşlemeleri — {s['kod']}", alanlar,
            bilgi="Hesaplar mevcut hesap planından seçilir; yeni hesap açılmaz. İç fon payı için fiş oluşmaz; "
                  "gerçek ödeme/transfer belgeleri mevcut finans servisleriyle muhasebeleşir."
                  + ("\nEk fon bedeli satış fişinde bu hesaba alacak yazılır." if ek_bedel else ""),
            varsayilan={"kullanim": bul(s["kullanim_hesap_kodu"]), "ayirma": bul(s["ayirma_hesap_kodu"]),
                        "ek_bedel": bul(s.get("ek_bedel_hesap_kodu"))})
        if sonuc:
            kod = lambda v: (v or "").split(" - ")[0].strip() or None  # noqa: E731
            self._calistir(lambda: FonService.hesap_eslemesi_kaydet(
                s["id"], kullanim_hesap_kodu=kod(sonuc["kullanim"]), ayirma_hesap_kodu=kod(sonuc["ayirma"]),
                ek_bedel_hesap_kodu=(kod(sonuc.get("ek_bedel")) or "") if ek_bedel else None),
                "Hesap eşlemesi kaydedildi.")

    def toplu_oran(self) -> None:
        TopluOranDialog(self)

    # ---------------------------------------------------------------- dışa aktarım
    def disari_aktar(self, tur: str) -> None:
        anahtar = list(self.sekmeler)[self.nb.index(self.nb.select())]
        tree, kolonlar, baslik = self.sekmeler[anahtar]
        satirlar = [[s.get(k[0]) for k in kolonlar] for s in self._veri.get(anahtar, [])]
        if not satirlar:
            messagebox.showinfo("Dışa aktar", "Aktarılacak kayıt yok.", parent=self)
            return
        uzanti = ".xlsx" if tur == "excel" else ".pdf"
        yol = filedialog.asksaveasfilename(
            parent=self, defaultextension=uzanti, initialfile=f"Fon_{anahtar}_{date.today():%Y%m%d}{uzanti}",
            filetypes=[("Excel", "*.xlsx")] if tur == "excel" else [("PDF", "*.pdf")])
        if not yol:
            return
        alt = (f"Dönem: {self.bas_var.get()} – {self.bit_var.get()} · Şube: {self.sube_var.get()} · "
               "Bakiyeler dönem sonu itibarıyla; dönem hareketleri ayrı sütunlarda.")
        try:
            notlar = [
                "Fon takip para birimi: TL. İç pay yöntemindeki fon bilgisi müşteri çıktılarına eklenmez; "
                "faturaya ek bedel yöntemindeki fon bedeli faturada ayrı satırdır.",
                "Dövizli belgelerde: Belge PB, kayıtlı belge kuru, döviz taban, TL taban, oran ve TL tutar "
                "ayrı sütunlardadır. Fon hakkı belge kuruyla sabitlenir; kur farkı ayrı izlenir.",
                *TUTAR_ACIKLAMALARI.values(),
                DESTEKLENEN_TAHSILAT_ACIKLAMA,
            ]
            (excel_yaz if tur == "excel" else pdf_yaz)(yol, f"Fon Yönetimi — {baslik}", alt,
                                                       [k[1] for k in kolonlar], satirlar, notlar)
        except Exception as hata:  # noqa: BLE001
            messagebox.showerror("Dışa aktar", f"Dosya kaydedilemedi:\n{hata}", parent=self)
            return
        messagebox.showinfo("Dışa aktar", f"Kaydedildi:\n{yol}", parent=self)


class FormDialog(tk.Toplevel):
    """Basit form; ``ac`` sonuç sözlüğü (``_istek``: tekrar kayıt kimliği) veya None döner."""

    def __init__(self, parent, baslik, alanlar, bilgi="", varsayilan=None):
        super().__init__(parent)
        self.title(baslik)
        self.transient(parent.winfo_toplevel())
        self.resizable(False, False)
        self.sonuc = None
        self._istek = uuid.uuid4().hex
        self.alanlar = alanlar
        self.degiskenler: dict[str, tk.StringVar] = {}
        govde = ttk.Frame(self, padding=12)
        govde.pack(fill="both", expand=True)
        if bilgi:
            ttk.Label(govde, text=bilgi, wraplength=460, foreground="#333", justify="left").grid(
                row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        varsayilan = varsayilan or {}
        for i, (anahtar, etiket, tur, secenekler) in enumerate(alanlar, start=1):
            ttk.Label(govde, text=etiket).grid(row=i, column=0, sticky="w", pady=3, padx=(0, 8))
            deger = varsayilan.get(anahtar, "")
            if tur == "tarih" and not deger:
                deger = date.today().strftime("%d.%m.%Y")
            if tur == "combo" and not deger and secenekler:
                deger = secenekler[0]
            var = tk.StringVar(value=str(deger or ""))
            self.degiskenler[anahtar] = var
            if tur in ("combo", "combo_serbest"):
                w = ttk.Combobox(govde, textvariable=var, values=secenekler or [], width=48,
                                 state="readonly" if tur == "combo" else "normal")
            else:
                w = ttk.Entry(govde, textvariable=var, width=50)
            w.grid(row=i, column=1, sticky="ew", pady=3)
        alt = ttk.Frame(govde)
        alt.grid(row=len(alanlar) + 1, column=0, columnspan=2, sticky="e", pady=(10, 0))
        self.kaydet_btn = ttk.Button(alt, text="Kaydet", command=self._tamam)
        self.kaydet_btn.pack(side="left", padx=4)
        ttk.Button(alt, text="Vazgeç", command=self.destroy).pack(side="left")
        self.bind("<Escape>", lambda _e: self.destroy())
        self.grab_set()

    def _tamam(self) -> None:
        sonuc = {"_istek": self._istek}
        try:
            for anahtar, etiket, tur, _ in self.alanlar:
                deger = self.degiskenler[anahtar].get().strip()
                if tur == "tarih":
                    deger = _tarih_oku(deger) or date.today()
                sonuc[anahtar] = deger
        except ValueError as hata:
            messagebox.showerror(self.title(), str(hata), parent=self)
            return
        self.sonuc = sonuc
        self.destroy()

    @classmethod
    def ac(cls, parent, baslik, alanlar, bilgi="", varsayilan=None) -> dict | None:
        dlg = cls(parent, baslik, alanlar, bilgi, varsayilan)
        parent.wait_window(dlg)
        return dlg.sonuc


class TransferDialog(tk.Toplevel):
    """Fonlar arası transfer formu; kaynağın kullanılabilir bakiyesini ve sonrası bakiyeleri canlı gösterir."""

    def __init__(self, parent, fonlar: dict[str, int]):
        super().__init__(parent)
        self.title("Fon Transferi")
        self.transient(parent.winfo_toplevel())
        self.resizable(False, False)
        self.fonlar = fonlar
        self.sonuc = None
        self._istek = uuid.uuid4().hex
        govde = ttk.Frame(self, padding=12)
        govde.pack(fill="both", expand=True)
        ttk.Label(govde, text="Yalnız ayrılmış ve kullanılabilir TL bakiye aktarılır. Kullanılmış veya tahsil "
                              "edilmemiş tutar transfer edilemez. Kasa/banka hareketi ve muhasebe fişi oluşmaz; "
                              "firma toplam fon bakiyesi değişmez.",
                  wraplength=470, foreground="#333", justify="left").grid(row=0, column=0, columnspan=2,
                                                                         sticky="w", pady=(0, 8))
        secenek = list(fonlar)
        self.v = {
            "tarih": tk.StringVar(value=date.today().strftime("%d.%m.%Y")),
            "kaynak": tk.StringVar(value=secenek[0]),
            "hedef": tk.StringVar(value=secenek[1]),
            "tutar": tk.StringVar(), "aciklama": tk.StringVar(),
        }
        satirlar = (("tarih", "Tarih", None), ("kaynak", "Kaynak fon", secenek), ("hedef", "Hedef fon", secenek),
                    ("tutar", "Tutar (TL)", None), ("aciklama", "Açıklama", None))
        for i, (anahtar, etiket, liste) in enumerate(satirlar, start=1):
            ttk.Label(govde, text=etiket).grid(row=i, column=0, sticky="w", pady=3, padx=(0, 8))
            if liste:
                w = ttk.Combobox(govde, textvariable=self.v[anahtar], values=liste, state="readonly", width=40)
            else:
                w = ttk.Entry(govde, textvariable=self.v[anahtar], width=42)
            w.grid(row=i, column=1, sticky="ew", pady=3)
        ttk.Label(govde, text="İşlem no").grid(row=6, column=0, sticky="w", pady=3)
        ttk.Label(govde, text="Kayıtta otomatik verilir (FTRyyyy-nnnnn)", foreground="#555").grid(
            row=6, column=1, sticky="w")
        self.bilgi = ttk.Label(govde, text="", foreground="#1F4E79", justify="left")
        self.bilgi.grid(row=7, column=0, columnspan=2, sticky="w", pady=(8, 0))
        alt = ttk.Frame(govde)
        alt.grid(row=8, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(alt, text="Kaydet", command=self._tamam).pack(side="left", padx=4)
        ttk.Button(alt, text="Vazgeç", command=self.destroy).pack(side="left")
        for anahtar in ("kaynak", "hedef", "tutar"):
            self.v[anahtar].trace_add("write", lambda *_a: self._onizle())
        self.bind("<Escape>", lambda _e: self.destroy())
        self._onizle()
        self.grab_set()

    def _onizle(self) -> None:
        try:
            o = FonService.transfer_onizleme(self.fonlar.get(self.v["kaynak"].get()),
                                             self.fonlar.get(self.v["hedef"].get()), self.v["tutar"].get())
        except Exception as hata:  # noqa: BLE001
            self.bilgi.configure(text=str(hata))
            return
        metin = f"Kaynak kullanılabilir bakiye: {hucre_metni(o['kaynak_kullanilabilir'])} TL"
        if o["kaynak_sonra"] is not None:
            metin += f"\nTransfer sonrası kaynak: {hucre_metni(o['kaynak_sonra'])} TL"
        if o["hedef_sonra"] is not None:
            metin += (f"\nHedef kullanılabilir: {hucre_metni(o['hedef_kullanilabilir'])} TL → "
                      f"transfer sonrası {hucre_metni(o['hedef_sonra'])} TL")
        self.bilgi.configure(text=metin)

    def _tamam(self) -> None:
        try:
            tarih = _tarih_oku(self.v["tarih"].get()) or date.today()
        except ValueError as hata:
            messagebox.showerror(self.title(), str(hata), parent=self)
            return
        if self.v["kaynak"].get() == self.v["hedef"].get():
            messagebox.showerror(self.title(), "Kaynak ve hedef fon aynı olamaz.", parent=self)
            return
        self.sonuc = {"_istek": self._istek, "tarih": tarih, "kaynak": self.v["kaynak"].get(),
                      "hedef": self.v["hedef"].get(), "tutar": self.v["tutar"].get().strip(),
                      "aciklama": self.v["aciklama"].get().strip()}
        self.destroy()

    @classmethod
    def ac(cls, parent, fonlar) -> dict | None:
        dlg = cls(parent, fonlar)
        parent.wait_window(dlg)
        return dlg.sonuc


class StokFonlariCercevesi(ttk.Frame):
    """Stok kartı «Fonlar» bölümü: ürün fon oranları, toplam aktif oran ve fon geçmişi."""

    KOLONLAR = (("fon", "Fon", 170, "w"), ("oran", "Oran %", 80, "e"), ("aktif", "Aktif", 60, "w"),
                ("aciklama", "Açıklama", 260, "w"), ("guncelleme", "Son Değişiklik", 110, "w"))

    def __init__(self, parent, stok_id: int | None):
        super().__init__(parent, padding=10)
        self.stok_id = stok_id
        self.satirlar: list[dict] = []
        from database.fon_service import tablolar_var

        if not stok_id:
            ttk.Label(self, text="Fon oranları kart kaydedildikten sonra girilebilir.").pack(anchor="w")
            return
        if not tablolar_var():
            ttk.Label(self, text="Fon tanımı yok. Finans → Fon Yönetimi ekranından fon tanımlayın.").pack(anchor="w")
            return
        ttk.Label(self, text="Oranlar yüzde olarak girilir (1,5 = %1,5). Yeni oran yalnız bundan sonraki onaylara "
                             "uygulanır; onaylanmış satışların oranı değişmez. Toplam aktif oran %100'ü aşamaz.",
                  wraplength=760, foreground="#555").pack(anchor="w", pady=(0, 6))
        self.tree = _tablo(self, self.KOLONLAR, yukseklik=6)
        self.tree.bind("<<TreeviewSelect>>", self._secildi)
        form = ttk.Frame(self)
        form.pack(fill="x", pady=6)
        self.oran_var, self.aciklama_var, self.aktif_var = tk.StringVar(), tk.StringVar(), tk.BooleanVar(value=True)
        ttk.Label(form, text="Oran %:").pack(side="left")
        ttk.Entry(form, textvariable=self.oran_var, width=8).pack(side="left", padx=(2, 8))
        ttk.Checkbutton(form, text="Aktif", variable=self.aktif_var).pack(side="left")
        ttk.Label(form, text="Açıklama:").pack(side="left", padx=(8, 2))
        ttk.Entry(form, textvariable=self.aciklama_var, width=30).pack(side="left")
        ttk.Button(form, text="Satıra Uygula", command=self._satira_uygula).pack(side="left", padx=6)
        alt = ttk.Frame(self)
        alt.pack(fill="x")
        self.toplam_lbl = ttk.Label(alt, text="", foreground="#1F4E79")
        self.toplam_lbl.pack(side="left")
        ttk.Button(alt, text="Fon Geçmişi", command=self._gecmis).pack(side="right")
        ttk.Button(alt, text="Fon Oranlarını Kaydet", command=self._kaydet).pack(side="right", padx=6)
        self._yukle()

    def _yukle(self) -> None:
        self.satirlar = FonService.stok_fon_oranlari(self.stok_id)
        self._goster()

    def _goster(self) -> None:
        gorunum = [{"fon": f"{s['fon_kod']} - {s['fon_ad']}" + ("" if s["fon_aktif"] else " (pasif fon)"),
                    "oran": _oran_metni(s["oran"]), "aktif": s["aktif"] if s["oran"] is not None else "",
                    "aciklama": s["aciklama"], "guncelleme": s["guncelleme"]} for s in self.satirlar]
        _doldur(self.tree, self.KOLONLAR, gorunum)
        toplam = sum((Decimal(str(s["oran"])) for s in self.satirlar
                      if s["oran"] is not None and s["aktif"] and s["fon_aktif"]), Decimal("0"))
        self.toplam_lbl.configure(text=f"Toplam aktif fon oranı: %{hucre_metni(toplam)}")

    def _secili(self) -> dict | None:
        sec = self.tree.selection()
        return self.satirlar[int(sec[0])] if sec and sec[0] != "bos" else None

    def _secildi(self, _e=None) -> None:
        s = self._secili()
        if s:
            self.oran_var.set(_oran_metni(s["oran"]))
            self.aktif_var.set(bool(s["aktif"]) or s["oran"] is None)
            self.aciklama_var.set(s["aciklama"])

    def _satira_uygula(self) -> None:
        from database.fon_service import oran_oku

        s = self._secili()
        if not s:
            messagebox.showinfo("Fonlar", "Bir fon satırı seçin.", parent=self)
            return
        try:
            s["oran"] = oran_oku(self.oran_var.get() or "0")
        except ValueError as hata:
            messagebox.showerror("Fonlar", str(hata), parent=self)
            return
        s["aktif"] = bool(self.aktif_var.get())
        s["aciklama"] = self.aciklama_var.get().strip()
        s["_degisti"] = True
        self._goster()

    def _kaydet(self) -> None:
        degisen = [s for s in self.satirlar if s.get("_degisti")]
        if not degisen:
            messagebox.showinfo("Fonlar", "Değişiklik yok.", parent=self)
            return
        try:
            FonService.stok_fon_oranlarini_kaydet(self.stok_id, [
                {"fon_id": s["fon_id"], "oran": s["oran"], "aktif": s["aktif"], "aciklama": s["aciklama"]}
                for s in degisen])
        except Exception as hata:  # noqa: BLE001
            messagebox.showerror("Fonlar", str(hata), parent=self)
            return
        messagebox.showinfo("Fonlar", "Fon oranları kaydedildi.", parent=self)
        self._yukle()

    def _gecmis(self) -> None:
        pencere = tk.Toplevel(self)
        pencere.title("Ürün Fon Geçmişi")
        pencere.geometry("980x520")
        nb = ttk.Notebook(pencere)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        oran_k = (("zaman", "Zaman", 130, "w"), ("fon", "Fon", 90, "w"), ("eski_oran", "Eski %", 70, "e"),
                  ("yeni_oran", "Yeni %", 70, "e"), ("eski_aktif", "Eski Aktif", 70, "w"),
                  ("yeni_aktif", "Yeni Aktif", 70, "w"), ("kaynak", "Kaynak", 70, "w"),
                  ("kullanici", "Kullanıcı", 120, "w"), ("aciklama", "Açıklama", 200, "w"))
        c1 = ttk.Frame(nb, padding=4)
        nb.add(c1, text="  Oran Değişiklikleri  ")
        _doldur(_tablo(c1, oran_k), oran_k, FonService.oran_gecmisi(self.stok_id))
        c2 = ttk.Frame(nb, padding=4)
        nb.add(c2, text="  Fon Hareketleri  ")
        try:
            hareket = FonService.stok_fon_gecmisi(self.stok_id)
        except Exception as hata:  # noqa: BLE001
            hareket = []
            ttk.Label(c2, text=str(hata), foreground="#B00020").pack(anchor="w")
        for h in hareket:
            h["urun"] = f"{h['urun_kodu']} {h['urun_adi']}".strip()
        _doldur(_tablo(c2, HAREKET_KOLONLARI), HAREKET_KOLONLARI, hareket,
                lambda s: "iptal" if s.get("durum") == "IPTAL" else None)


class TopluOranDialog(tk.Toplevel):
    """Stok grubuna toplu fon oranı: önce önizleme, sonra açık seçenekle uygulama."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Stok Grubuna Toplu Fon Oranı")
        self.transient(parent.winfo_toplevel())
        self.geometry("820x520")
        self.parent_sayfa = parent
        self.onizleme: list[dict] = []
        from sqlalchemy import select

        from database.database import get_session
        from database.models.stok import StokGrubu

        with get_session() as s:
            self.gruplar = {f"{'  ' * (g.seviye - 1)}{g.kod} - {g.ad}": g.id
                            for g in s.scalars(select(StokGrubu).order_by(StokGrubu.seviye, StokGrubu.kod))}
        self.fonlar = {f"{f['kod']} - {f['ad']}": f["id"] for f in FonService.fon_listesi(True)}
        ust = ttk.Frame(self, padding=8)
        ust.pack(fill="x")
        self.grup_var = tk.StringVar(value=next(iter(self.gruplar), ""))
        self.fon_var = tk.StringVar(value=next(iter(self.fonlar), ""))
        self.oran_var = tk.StringVar()
        self.politika_var = tk.StringVar(value="BOS")
        ttk.Label(ust, text="Grup:").grid(row=0, column=0, sticky="w")
        ttk.Combobox(ust, textvariable=self.grup_var, values=list(self.gruplar), state="readonly", width=34).grid(
            row=0, column=1, sticky="w", padx=4)
        ttk.Label(ust, text="Fon:").grid(row=0, column=2, sticky="w")
        ttk.Combobox(ust, textvariable=self.fon_var, values=list(self.fonlar), state="readonly", width=20).grid(
            row=0, column=3, sticky="w", padx=4)
        ttk.Label(ust, text="Oran %:").grid(row=0, column=4, sticky="w")
        ttk.Entry(ust, textvariable=self.oran_var, width=8).grid(row=0, column=5, sticky="w", padx=4)
        ttk.Radiobutton(ust, text="Yalnız oranı boş olan ürünlere uygula", value="BOS",
                        variable=self.politika_var).grid(row=1, column=0, columnspan=3, sticky="w", pady=4)
        ttk.Radiobutton(ust, text="Listeden seçilen ürünlerin oranını değiştir", value="SECILI",
                        variable=self.politika_var).grid(row=1, column=3, columnspan=3, sticky="w", pady=4)
        ttk.Button(ust, text="Önizle", command=self.onizle).grid(row=0, column=6, padx=6)
        ttk.Label(self, text="Grup ve ürün oranları üst üste eklenmez; sonuç ürün bazında saklanır. "
                             "«Seçilenleri değiştir» için listede ürünleri seçin (Ctrl/Shift).",
                  foreground="#555", padding=(8, 0)).pack(anchor="w")
        kolonlar = (("stok_kodu", "Kod", 100, "w"), ("stok_adi", "Ad", 240, "w"), ("mevcut", "Mevcut %", 80, "e"),
                    ("yeni", "Yeni %", 80, "e"), ("islem", "İşlem", 80, "w"), ("neden", "Not", 200, "w"))
        self.kolonlar = kolonlar
        cerceve = ttk.Frame(self, padding=8)
        cerceve.pack(fill="both", expand=True)
        self.tree = _tablo(cerceve, kolonlar)
        self.tree.configure(selectmode="extended")
        alt = ttk.Frame(self, padding=8)
        alt.pack(fill="x")
        ttk.Button(alt, text="Uygula", command=self.uygula).pack(side="right")
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right", padx=6)

    def _secili_stoklar(self) -> list[int]:
        return [self.onizleme[int(i)]["stok_id"] for i in self.tree.selection() if i != "bos"]

    def onizle(self) -> None:
        try:
            grup, fon, oran = self.gruplar[self.grup_var.get()], self.fonlar[self.fon_var.get()], self.oran_var.get()
            if self.politika_var.get() == "BOS":
                self.onizleme = FonService.toplu_oran_onizleme(grup, fon, oran, "BOS")
            else:
                # Seçim yoksa gruptaki tüm ürünler için olası değişiklik gösterilir; uygulama yalnız seçilene
                secili = self._secili_stoklar() if self.onizleme else []
                if not secili:
                    secili = [r["stok_id"] for r in FonService.toplu_oran_onizleme(grup, fon, oran, "BOS")]
                self.onizleme = FonService.toplu_oran_onizleme(grup, fon, oran, "SECILI", secili) if secili else []
        except Exception as hata:  # noqa: BLE001
            messagebox.showerror("Toplu oran", str(hata), parent=self)
            return
        _doldur(self.tree, self.kolonlar, self.onizleme, lambda s: "iptal" if s["islem"] == "ATLA" else None)

    def uygula(self) -> None:
        if not self.onizleme:
            messagebox.showinfo("Toplu oran", "Önce önizleme yapın.", parent=self)
            return
        politika = self.politika_var.get()
        secili = self._secili_stoklar() if politika == "SECILI" else None
        if politika == "SECILI" and not secili:
            messagebox.showinfo("Toplu oran", "Değiştirilecek ürünleri listeden seçin.", parent=self)
            return
        try:
            on = FonService.toplu_oran_onizleme(self.gruplar[self.grup_var.get()], self.fonlar[self.fon_var.get()],
                                                self.oran_var.get(), politika, secili)
            degisecek = sum(1 for r in on if r["islem"] != "ATLA")
            if not messagebox.askyesno("Toplu oran", f"{degisecek} ürüne uygulanacak. Onaylıyor musunuz?",
                                       parent=self):
                return
            sayac = FonService.toplu_oran_uygula(self.gruplar[self.grup_var.get()], self.fonlar[self.fon_var.get()],
                                                 self.oran_var.get(), politika, secili)
        except Exception as hata:  # noqa: BLE001
            messagebox.showerror("Toplu oran", str(hata), parent=self)
            return
        messagebox.showinfo("Toplu oran", f"Eklenen: {sayac['EKLE']} · Değiştirilen: {sayac['DEGISTIR']} · "
                                          f"Atlanan: {sayac['ATLA']}", parent=self)
        self.onizleme = on
        self.onizle()
