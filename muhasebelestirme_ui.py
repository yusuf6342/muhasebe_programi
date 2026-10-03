"""Ayarlar → Muhasebeleştirme Ayarları ve Genel Muhasebe → Muhasebeleştirilecek Evraklar."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from datetime import date, datetime
from tkinter import messagebox, simpledialog, ttk

from database.models.genel_muhasebe import (
    BELGE_BEKLIYOR,
    BELGE_DURUMLARI,
    BELGE_HATALI,
    BELGE_INCELEME,
    BELGE_MUHASEBE_DISI,
)
from database.muhasebe_entegrasyon import EVRAKLAR
from database.muhasebe_service import para_goster
from database.muhasebelestirme_service import (
    YONTEM_ADLARI,
    MuhasebelestirmeService,
    ZatenCalisiyor,
)
from database.session_manager import oturum

_YONTEM_KOD = {v: k for k, v in YONTEM_ADLARI.items()}

_ACIKLAMA = (
    "Otomatik: Evrak kesinleştiği anda muhasebe fişi aynı işlemde oluşur. Fiş oluşturulamazsa "
    "(ör. hesap eşleştirmesi eksik) evrak da kesinleşmez; hata mesajı gösterilir.\n"
    "Sonradan: Evrak kesinleşir; stok, cari, kasa/banka ve KDV gibi ön muhasebe hareketleri hemen "
    "oluşur, fakat muhasebe fişi oluşmaz. Evrak 'Muhasebeleştirilecek Evraklar' listesine düşer; fiş "
    "oradan tek tek veya toplu oluşturulur.\n"
    "Teklif, sipariş ve taslak evraklar hiçbir yöntemde fiş oluşturmaz. Ayar değişikliği yalnız bundan "
    "sonraki evrakları etkiler; geçmiş evrak ve mevcut fişler değişmez."
)


def _menu_ayarlar(app):
    kabuk = getattr(app, "_ana_panel_kabuk", None)
    if kabuk:
        kabuk.menu_secili_guncelle("ayarlar")


def _firma_adi() -> str:
    return getattr(oturum, "firma_unvan", None) or getattr(oturum, "firma_kodu", None) or "—"


# ================================================================ Ayarlar sayfası
def muhasebelestirme_ayarlari_goster(app) -> None:
    app._icerigi_temizle()
    _menu_ayarlar(app)
    try:
        ayar = MuhasebelestirmeService.ayarlar()
    except Exception as hata:
        messagebox.showerror("Muhasebeleştirme Ayarları", str(hata), parent=app)
        return

    ttk.Label(app.icerik, text="MUHASEBELEŞTİRME AYARLARI", style="Baslik.TLabel").pack(
        anchor="w", padx=20, pady=(16, 0))
    ttk.Label(
        app.icerik,
        text=f"Yalnız seçili firma için geçerlidir. Aktif firma: {_firma_adi()}",
        style="AnaPanelMuted.TLabel",
    ).pack(anchor="w", padx=20, pady=(8, 0))

    ust = ttk.LabelFrame(app.icerik, text="Firma geneli", padding=12)
    ust.pack(fill="x", padx=20, pady=(14, 0))
    gm_var = tk.BooleanVar(value=ayar["gm_kullan"])
    ttk.Checkbutton(ust, text="Bu firmada genel muhasebe (muhasebe fişi) kullanılsın", variable=gm_var).grid(
        row=0, column=0, columnspan=3, sticky="w")
    ttk.Label(ust, text="Varsayılan yöntem:").grid(row=1, column=0, sticky="w", pady=(8, 0))
    varsayilan_var = tk.StringVar(value=YONTEM_ADLARI[ayar["varsayilan"]])
    ttk.Combobox(ust, textvariable=varsayilan_var, state="readonly", width=14,
                 values=[YONTEM_ADLARI["otomatik"], YONTEM_ADLARI["sonradan"]]).grid(
        row=1, column=1, sticky="w", padx=8, pady=(8, 0))
    son = ""
    if ayar.get("guncelleme_tarihi"):
        son = f"Son değişiklik: {ayar['guncelleme_tarihi']:%d.%m.%Y %H:%M} — {ayar.get('guncelleyen') or 'sistem'}"
    if ayar.get("aciklama"):
        son = (son + "\n" if son else "") + ayar["aciklama"]
    if son:
        ttk.Label(ust, text=son, style="AnaPanelMuted.TLabel", wraplength=820, justify="left").grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))
    ttk.Label(ust, text=_ACIKLAMA, wraplength=820, justify="left").grid(
        row=3, column=0, columnspan=3, sticky="w", pady=(10, 0))
    ttk.Button(ust, text="Finans İşlem Ayarları…", command=lambda: FinansIslemAyarlariDialog(app)).grid(
        row=1, column=2, sticky="w", padx=(24, 0), pady=(8, 0))

    orta = ttk.LabelFrame(app.icerik, text="Evrak türüne göre (boş bırakılırsa firma varsayılanı)", padding=12)
    orta.pack(fill="x", padx=20, pady=(12, 0))
    for i, baslik in enumerate(("Evrak türü", "Yöntem", "Etkin", "Kesinleşme anı (Kaydet / Onayla)", "Durum")):
        ttk.Label(orta, text=baslik, font=("Segoe UI", 9, "bold")).grid(row=0, column=i, sticky="w", padx=4)
    secimler: dict[str, tk.StringVar] = {}
    secenekler = [YONTEM_ADLARI["varsayilan"], YONTEM_ADLARI["otomatik"], YONTEM_ADLARI["sonradan"]]
    for r, t in enumerate(ayar["turler"], start=1):
        ttk.Label(orta, text=t["ad"]).grid(row=r, column=0, sticky="w", padx=4, pady=2)
        v = tk.StringVar(value=YONTEM_ADLARI[t["secim"]])
        secimler[t["evrak_turu"]] = v
        ttk.Combobox(orta, textvariable=v, values=secenekler, state="readonly", width=16).grid(
            row=r, column=1, sticky="w", padx=4)
        etkin = {"kapali": "GM kapalı"}.get(t["etkin"], YONTEM_ADLARI.get(t["etkin"], t["etkin"]))
        ttk.Label(orta, text=etkin).grid(row=r, column=2, sticky="w", padx=4)
        ttk.Label(orta, text=t["kesinlesme"], wraplength=330, justify="left").grid(
            row=r, column=3, sticky="w", padx=4)
        sorun = "Eşleştirme uygun" if not t["eslesme_sorunlari"] else "Eşleştirme sorunu var"
        lbl = ttk.Label(orta, text=sorun, foreground="#2e7d32" if not t["eslesme_sorunlari"] else "#c62828")
        lbl.grid(row=r, column=4, sticky="w", padx=4)
        if t["eslesme_sorunlari"]:
            metin = "\n".join(t["eslesme_sorunlari"])
            lbl.bind("<Button-1>", lambda _e, m=metin, a=t["ad"]: messagebox.showinfo(a, m, parent=app))
            lbl.configure(cursor="hand2")

    alt_bilgi = ttk.LabelFrame(app.icerik, text="Bu yöntemlerle yönetilmeyen evraklar", padding=12)
    alt_bilgi.pack(fill="x", padx=20, pady=(12, 0))
    ttk.Label(alt_bilgi, text="\n".join(f"• {d}" for d in ayar["desteklenmeyen"]), wraplength=820,
              justify="left").pack(anchor="w")

    def kaydet():
        try:
            sonuc = MuhasebelestirmeService.ayar_kaydet(
                gm_kullan=bool(gm_var.get()),
                varsayilan=_YONTEM_KOD[varsayilan_var.get()],
                turler={e: _YONTEM_KOD[v.get()] for e, v in secimler.items()},
            )
        except Exception as hata:
            messagebox.showerror("Muhasebeleştirme Ayarları", str(hata), parent=app)
            return
        mesaj = "Ayarlar kaydedildi. Geçmiş evraklar ve mevcut fişler değiştirilmedi."
        t = sonuc.get("gecmis_tarama")
        if t:
            mesaj += (f"\n\nGenel muhasebe açıldı: {t['inceleme']} geçmiş evrak 'İnceleme gerekiyor' olarak "
                      "Muhasebeleştirilecek Evraklar listesine eklendi (fiş oluşturulmadı).")
        messagebox.showinfo("Muhasebeleştirme Ayarları", mesaj, parent=app)
        muhasebelestirme_ayarlari_goster(app)

    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", padx=20, pady=16)
    ttk.Button(alt, text="Kaydet", command=kaydet).pack(side="left")
    ttk.Button(alt, text="Muhasebeleştirilecek Evraklar",
               command=lambda: muhasebelestirilecek_evraklar_goster(app)).pack(side="left", padx=8)
    ttk.Button(alt, text="Geri", command=lambda: app.sayfa_goster("ayarlar")).pack(side="left")


# ================================================================ Finans İşlem Ayarları
_SECIM_TANIMSIZ = "— Tanımsız (evrak incelemeye düşer) —"
_CEK_SECIM = {"evet": "Fiş üretsin", "hayir": "Fiş üretmesin (muhasebe dışı)"}
_HESAP_BOS = "— Bağlı değil —"


class FinansIslemAyarlariDialog(tk.Toplevel):
    """KMH / POS / şirket kartı, çek/senet aşamaları ve banka kredisi muhasebe seçenekleri.

    Hesap listesinde yalnız fişe uygun (aktif, alt, yaprak) hesaplar bulunur; seçenek veya hesap
    tanımsız bırakılırsa ilgili evrak fiş üretmez, 'İnceleme gerekiyor' olarak bekler.
    """

    def __init__(self, parent):
        super().__init__(parent)
        from database import muhasebe_finans_ayarlari as fa

        self.fa = fa
        self.title("Finans İşlem Ayarları")
        self.geometry("1000x720")
        self.transient(parent)
        try:
            self.veri = fa.ekran_verisi()
        except Exception as hata:
            messagebox.showerror("Finans İşlem Ayarları", str(hata), parent=parent)
            self.destroy()
            return
        self._aday_etiket = {f"{a['kod']} — {a['ad']}": a["id"] for a in self.veri["adaylar"]}
        self._kod_etiket = {a["kod"]: f"{a['kod']} — {a['ad']}" for a in self.veri["adaylar"]}
        self.hesap_var: dict[str, tk.StringVar] = {}
        self._hesap_ilk: dict[str, str] = {}
        self.secim_var: dict[str, tk.StringVar] = {}
        self._secim_etiket: dict[str, dict[str, str]] = {}

        ttk.Label(self, padding=(10, 8, 10, 0), wraplength=940, justify="left", text=(
            f"Yalnız seçili firma için geçerlidir ({_firma_adi()}). Hesap listesinde yalnız fişe uygun alt hesaplar "
            "vardır; varsayılan hesap atanmaz. Bir seçenek veya hesap tanımsız bırakılırsa ilgili evrak kaydedilir "
            "ama fiş üretmez, 'İnceleme gerekiyor' olarak bekler; açıklamasında eksik ayar ve yeri yazar.")
        ).pack(fill="x")
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=8)
        gruplar = {g["baslik"]: g["satirlar"] for g in self.veri["gruplar"]}
        basliklar = [b for b, _ in fa.HESAP_GRUPLARI]

        s1 = self._sekme(nb, "KMH / POS / Şirket kartı")
        ttk.Label(s1, wraplength=900, justify="left", foreground="#555", text=(
            "KMH: KMH alt hesabına yapılan tahsilat, havale ve virmanlar bu hesaba yazılır. POS: kart tahsilatında "
            "net tutar valör alacağına, komisyon gider hesabına; valör aktarımında POS alacağı KMH'ye aktarılır. "
            "Şirket kartı: kartla cari ödemesinde kart borcu bu hesapta izlenir.")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        self._hesap_satirlari(s1, gruplar[basliklar[0]], 1)

        s2 = self._sekme(nb, "Çek / Senet")
        ttk.Label(s2, text="Aşama", font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(s2, text="Fiş", font=("Segoe UI", 9, "bold")).grid(row=0, column=1, sticky="w")
        ttk.Label(s2, text="Fiş satırları", font=("Segoe UI", 9, "bold")).grid(row=0, column=2, sticky="w")
        r = 1
        for kod, ad, aciklama in fa.CEK_SENET_ASAMALARI:
            ttk.Label(s2, text=ad).grid(row=r, column=0, sticky="w", pady=2)
            self._secim(s2, fa.cek_senet_anahtari(kod), _CEK_SECIM, r, 1, 26)
            ttk.Label(s2, text=aciklama, wraplength=420, justify="left", foreground="#555").grid(
                row=r, column=2, sticky="w", padx=6)
            r += 1
        ttk.Separator(s2).grid(row=r, column=0, columnspan=3, sticky="ew", pady=8)
        self._hesap_satirlari(s2, gruplar[basliklar[1]], r + 1)

        s3 = self._sekme(nb, "Banka Kredisi")
        ttk.Label(s3, text="Fiş zamanı").grid(row=0, column=0, sticky="w", pady=2)
        self._secim(s3, fa.KREDI_FIS_ZAMANI, dict(fa.KREDI_FIS_ZAMANLARI), 0, 1, 60, span=2)
        ttk.Label(s3, text="Kısa / uzun vade ayrımı").grid(row=1, column=0, sticky="w", pady=2)
        self._secim(s3, fa.KREDI_VADE_AYRIMI, dict(fa.KREDI_VADE_AYRIMLARI), 1, 1, 60, span=2)
        ttk.Label(s3, wraplength=900, justify="left", foreground="#555", text=(
            "Kullandırım: Borç mevduat/KMH — Alacak kısa (ve 12 ay ayrımında uzun) vadeli kredi. Taksit: Borç kredi "
            "anaparası (taksit vadesine göre kısa/uzun) + faiz, BSMV, KKDF, komisyon, sigorta, dosya, gecikme "
            "giderleri — Alacak ödeme hesabı. 'Yalnız taksit' seçilirse kredi bakiyesinin açılış/elle fişle "
            "girilmiş olması gerekir. Uzun vadeden kısa vadeye aktarım (400 → 300) otomatik yapılmaz.")).grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(4, 8))
        self._hesap_satirlari(s3, gruplar[basliklar[2]], 3)

        s4 = self._sekme(nb, "Kasa / Banka Kartları")
        ttk.Label(s4, wraplength=900, justify="left", foreground="#555", text=(
            "Kasa: kasa kartında muhasebe hesabı seçilmemişse fiş bu hesaba yazılır. Banka: her banka alt hesabı "
            "(mevduat, KMH, POS, kredi kartı, krediler) kartın kendi muhasebe hesabına yazılır; kartta seçim yoksa "
            "eski firma varsayılanı (banka / KMH / POS valör / şirket kartı) kullanılır, o da yoksa evrak 'İnceleme "
            "gerekiyor' olur. Kart hesapları aşağıdaki düğmeden veya Finans → Banka kartı → Muhasebe Hesapları'ndan "
            "seçilir.")).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        self._hesap_satirlari(s4, gruplar[basliklar[3]], 1)
        ttk.Button(s4, text="Kart muhasebe hesapları…", command=self._kart_hesaplari).grid(
            row=3, column=0, sticky="w", pady=(10, 0))

        s5 = self._sekme(nb, "Kur farkı")
        ttk.Label(s5, wraplength=900, justify="left", foreground="#555", text=(
            "Döviz sabit satış faturasının fatura içi TL tahsilatında kapatılan döviz tutarı için fatura kuru ile "
            "tahsilat günü kuru arasındaki fark: lehte ise Borç alıcılar — Alacak kur farkı geliri; aleyhte ise Borç "
            "kur farkı gideri — Alacak alıcılar. Tahsilat günü kuru yoksa fark tahmin edilmez, kayıt 'İnceleme "
            "gerekiyor' olur. Dönem sonu değerleme ve kur farkı faturası (KDV) bu ekrandan üretilmez.")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        self._hesap_satirlari(s5, gruplar[basliklar[4]], 1)

        s6 = self._sekme(nb, "Alış iadesi")
        ttk.Label(s6, wraplength=900, justify="left", foreground="#555", text=(
            "Alış iadesi fişi: Borç tedarikçi (iade bedeli + KDV) — Alacak ticari mallar (gerçek FIFO stok maliyeti) "
            "ve indirilecek KDV; bedel ile stok maliyeti arasındaki fark, yönüne göre aşağıdaki iki hesaptan birine "
            "yazılır. Hesaplar kendiliğinden seçilmez; fark oluştuğunda ilgili hesap tanımsızsa iade 'İnceleme "
            "gerekiyor' olur (fark sıfırsa hesap aranmaz). Dövizli iadede tedarikçinin döviz borcu kaynak alış "
            "kuruyla kayıtlıdır; iade kuruyla arasındaki fark kur farkı kaydı olarak saklanır, fişi aşağıdaki seçime "
            "göre yazılır (seçim yoksa 'İnceleme gerekiyor').")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        ttk.Label(s6, text="Dövizli iade kur farkı").grid(row=1, column=0, sticky="w", pady=2)
        self._secim(s6, fa.ALIS_IADE_KUR_FARKI, dict(fa.ALIS_IADE_KUR_FARKI_SECENEKLERI), 1, 1, 80, span=2)
        ttk.Label(s6, text="Dövizli iade KDV kuru").grid(row=2, column=0, sticky="w", pady=2)
        self._secim(s6, fa.ALIS_IADE_KDV_KURU, dict(fa.ALIS_IADE_KDV_KURU_SECENEKLERI), 2, 1, 40, span=2)
        ttk.Label(s6, wraplength=900, justify="left", foreground="#555", text="\n".join(
            f"• {ad}: {fa.ALIS_IADE_KDV_KURU_ACIKLAMALARI[kod]}" for kod, ad in fa.ALIS_IADE_KDV_KURU_SECENEKLERI)
            + "\nSeçim yapılmadıkça dövizli iade taslak kaydedilir ve onaylanabilir, ama kesin muhasebeleştirilmez "
              "('İnceleme gerekiyor'). Seçilen yöntem iade onaylanırken belgeye yazılır; sonradan değiştirmek "
              "onaylı iadeleri etkilemez. TL iadeler etkilenmez.").grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(0, 8))
        self._hesap_satirlari(s6, gruplar[basliklar[5]], 4)
        for i, s in enumerate(gruplar[basliklar[5]]):
            ttk.Label(s6, text=fa.MALIYET_FARKI_ACIKLAMALARI.get(s["anahtar"], ""), wraplength=880,
                      justify="left", foreground="#555").grid(row=6 + i, column=0, columnspan=3, sticky="w")

        alt = ttk.Frame(self, padding=10)
        alt.pack(fill="x")
        ttk.Button(alt, text="Kaydet", command=self._kaydet).pack(side="left")
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")

    def _kart_hesaplari(self):
        from finans_muhasebe_hesap_ui import KartMuhasebeHesaplariDialog

        KartMuhasebeHesaplariDialog(self)

    def _sekme(self, nb, baslik):
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text=baslik)
        return f

    def _secim(self, ust, anahtar, etiketler: dict[str, str], satir, kolon, genislik, span=1):
        mevcut = self.veri["secenekler"].get(anahtar)
        v = tk.StringVar(value=etiketler.get(mevcut, _SECIM_TANIMSIZ))
        ttk.Combobox(ust, textvariable=v, state="readonly", width=genislik,
                     values=[_SECIM_TANIMSIZ, *etiketler.values()]).grid(
            row=satir, column=kolon, columnspan=span, sticky="w", padx=6, pady=2)
        self.secim_var[anahtar] = v
        self._secim_etiket[anahtar] = etiketler

    def _hesap_satirlari(self, ust, satirlar, baslangic):
        degerler = [_HESAP_BOS, *self._aday_etiket]
        for i, s in enumerate(satirlar, start=baslangic):
            ttk.Label(ust, text=s["ad"]).grid(row=i, column=0, sticky="w", pady=2)
            ilk = self._kod_etiket.get(s["hesap_kodu"], _HESAP_BOS) if not s["sorun"] else _HESAP_BOS
            v = tk.StringVar(value=ilk)
            ttk.Combobox(ust, textvariable=v, values=degerler, state="readonly", width=48).grid(
                row=i, column=1, sticky="w", padx=6, pady=2)
            durum = ("Fişe uygun" if not s["sorun"] else
                     "Bağlı değil" if not s["hesap_kodu"] else f"{s['hesap_kodu']}: {s['sorun']}")
            ttk.Label(ust, text=durum, foreground="#2e7d32" if not s["sorun"] else "#c62828",
                      wraplength=360).grid(row=i, column=2, sticky="w", padx=6)
            self.hesap_var[s["anahtar"]] = v
            self._hesap_ilk[s["anahtar"]] = ilk

    def secimler(self) -> dict[str, str | None]:
        sonuc = {}
        for anahtar, v in self.secim_var.items():
            ters = {etiket: kod for kod, etiket in self._secim_etiket[anahtar].items()}
            sonuc[anahtar] = ters.get(v.get())
        return sonuc

    def _kaydet(self):
        from database.muhasebe_entegrasyon import HesapEslemeService

        try:
            for anahtar, v in self.hesap_var.items():
                if v.get() != self._hesap_ilk[anahtar]:
                    HesapEslemeService.kaydet(anahtar, self._aday_etiket.get(v.get()))
                    self._hesap_ilk[anahtar] = v.get()
            self.fa.kaydet(self.secimler())
        except Exception as hata:
            messagebox.showerror("Finans İşlem Ayarları", str(hata), parent=self)
            return
        messagebox.showinfo("Finans İşlem Ayarları", (
            "Ayarlar kaydedildi. Bundan sonraki evraklar bu ayarlarla muhasebeleşir.\n\n"
            "Ayar eksikliği yüzünden 'İnceleme gerekiyor' kalan evrakları Genel Muhasebe → Muhasebeleştirilecek "
            "Evraklar ekranından seçip muhasebeleştirebilirsiniz (mevcut fişler değişmez)."), parent=self)
        self.destroy()


# ================================================================ Bekleyen evraklar
_DURUM_FILTRELERI = {
    "Bekleyen + Hatalı": (BELGE_BEKLIYOR, BELGE_HATALI),
    "İnceleme gerekiyor": (BELGE_INCELEME,),
    **{d: (d,) for d in BELGE_DURUMLARI if d not in (BELGE_INCELEME,)},
    "Tümü": None,
}


def _tarih(metin: str) -> date | None:
    metin = (metin or "").strip()
    if not metin:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(metin, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Geçersiz tarih: {metin}")


def muhasebelestirilecek_evraklar_goster(app, geri=None) -> None:
    app._icerigi_temizle()
    if geri is None:
        from genel_muhasebe_ui import genel_muhasebe_menusu_goster

        geri = lambda: genel_muhasebe_menusu_goster(app)  # noqa: E731
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="MUHASEBELEŞTİRİLECEK EVRAKLAR", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Geri", command=geri).pack(side="right")
    ttk.Label(
        app.icerik,
        text=f"Firma: {_firma_adi()}  |  Fiş yalnız muhasebe tarafında oluşur; stok, cari, kasa/banka "
             "hareketleri yeniden üretilmez. Fiş tarihi evrak tarihidir.",
        style="AnaPanelMuted.TLabel",
    ).pack(anchor="w", pady=(4, 6))

    filtre = ttk.Frame(app.icerik)
    filtre.pack(fill="x", pady=(0, 6))
    ttk.Label(filtre, text="Başlangıç:").pack(side="left")
    bas = ttk.Entry(filtre, width=11)
    bas.pack(side="left", padx=(2, 8))
    ttk.Label(filtre, text="Bitiş:").pack(side="left")
    bit = ttk.Entry(filtre, width=11)
    bit.pack(side="left", padx=(2, 8))
    ttk.Label(filtre, text="Tür:").pack(side="left")
    turler = {"Tümü": None, **{t["ad"]: e for e, t in EVRAKLAR.items()}}
    tur_var = tk.StringVar(value="Tümü")
    ttk.Combobox(filtre, textvariable=tur_var, values=list(turler), state="readonly", width=22).pack(
        side="left", padx=(2, 8))
    ttk.Label(filtre, text="Cari / evrak no:").pack(side="left")
    cari = ttk.Entry(filtre, width=18)
    cari.pack(side="left", padx=(2, 8))
    ttk.Label(filtre, text="Durum:").pack(side="left")
    durum_var = tk.StringVar(value="Bekleyen + Hatalı")
    ttk.Combobox(filtre, textvariable=durum_var, values=list(_DURUM_FILTRELERI), state="readonly",
                 width=20).pack(side="left", padx=(2, 8))

    kolonlar = ("tur", "tarih", "no", "cari", "tutar", "pb", "durum", "fis", "sorun")
    cerceve = ttk.Frame(app.icerik)
    cerceve.pack(fill="both", expand=True)
    tablo = ttk.Treeview(cerceve, columns=kolonlar, show="headings", height=16, selectmode="extended")
    for k, t, w in (
        ("tur", "Evrak Türü", 150), ("tarih", "Tarih", 85), ("no", "Evrak No", 120), ("cari", "Cari", 190),
        ("tutar", "Tutar (TL)", 100), ("pb", "PB", 45), ("durum", "Durum", 130), ("fis", "Fiş No", 110),
        ("sorun", "Eksik eşleştirme / hata", 380),
    ):
        tablo.heading(k, text=t)
        tablo.column(k, width=w, anchor="e" if k == "tutar" else "w")
    sb = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=sb.set)
    tablo.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    tablo.tag_configure("hata", foreground="#c62828")
    tablo.tag_configure("inceleme", foreground="#8d6e00")

    durum_lbl = ttk.Label(app.icerik, text="")
    durum_lbl.pack(anchor="w", pady=(4, 0))
    ilerleme = ttk.Progressbar(app.icerik, mode="determinate")
    ilerleme.pack(fill="x", pady=(2, 0))
    ilerleme_lbl = ttk.Label(app.icerik, text="")
    ilerleme_lbl.pack(anchor="w")

    kayitlar: dict[str, dict] = {}
    durum = {"calisiyor": False, "durdur": False, "son_basarisiz": []}

    def yenile():
        try:
            liste = MuhasebelestirmeService.listele(
                baslangic=_tarih(bas.get()), bitis=_tarih(bit.get()), evrak_turu=turler[tur_var.get()],
                cari_metni=cari.get(), durumlar=_DURUM_FILTRELERI[durum_var.get()],
            )
            sayilar = MuhasebelestirmeService.durum_sayilari()
        except Exception as hata:
            messagebox.showerror("Muhasebeleştirilecek Evraklar", str(hata), parent=app)
            return
        tablo.delete(*tablo.get_children())
        kayitlar.clear()
        for k in liste:
            iid = str(k["id"])
            kayitlar[iid] = k
            etiket = ("hata",) if k["durum"] == BELGE_HATALI else ("inceleme",) if k["durum"] == BELGE_INCELEME else ()
            tablo.insert("", "end", iid=iid, tags=etiket, values=(
                k["evrak_adi"], k["belge_tarihi"].strftime("%d.%m.%Y") if k["belge_tarihi"] else "",
                k["belge_no"] or "", k["cari_adi"] or "", para_goster(k["tutar"]), k["para_birimi"] or "",
                k["durum"], k["fis_no"] or "", (k["sorun"] or "").replace("\n", " "),
            ))
        durum_lbl.configure(text=f"Listelenen: {len(liste)}   |   " + "   ".join(
            f"{d}: {n}" for d, n in sayilar.items() if n))

    def secili_idler() -> list[tuple[int, int]]:
        return [(kayitlar[i]["id"], kayitlar[i]["row_version"]) for i in tablo.selection() if i in kayitlar]

    def baslat(ogeler: list[tuple[int, int]]):
        if durum["calisiyor"] or MuhasebelestirmeService.calisiyor_mu():
            messagebox.showinfo("Muhasebeleştir", "Muhasebeleştirme zaten çalışıyor.", parent=app)
            return
        if not ogeler:
            messagebox.showinfo("Muhasebeleştir", "Listeden evrak seçin.", parent=app)
            return
        try:
            kontrol = MuhasebelestirmeService.on_kontrol([o[0] for o in ogeler])
        except Exception as hata:
            messagebox.showerror("Muhasebeleştir", str(hata), parent=app)
            return
        metin = f"Seçili evrak: {kontrol['secili']}\nİşlenecek: {kontrol['islenebilir']}"
        if kontrol["sorunlar"]:
            metin += "\n\nTespit edilen sorunlar:\n• " + "\n• ".join(kontrol["sorunlar"][:12])
        if not kontrol["islenebilir"]:
            messagebox.showinfo("Muhasebeleştir", metin, parent=app)
            return
        if not messagebox.askyesno("Muhasebeleştir", metin + "\n\nDevam edilsin mi?", parent=app):
            return
        durum.update(calisiyor=True, durdur=False)
        btn_mh.configure(state="disabled")
        btn_tekrar.configure(state="disabled")
        btn_durdur.configure(state="normal")
        ilerleme.configure(maximum=len(ogeler), value=0)
        kuyruk: queue.Queue = queue.Queue()

        def is_parcacigi():
            try:
                sonuc = MuhasebelestirmeService.muhasebelestir(
                    ogeler,
                    ilerleme=lambda i, n, s: kuyruk.put(("ilerleme", i, n, dict(s))),
                    durdur=lambda: durum["durdur"],
                )
                kuyruk.put(("bitti", sonuc))
            except ZatenCalisiyor as hata:
                kuyruk.put(("hata", str(hata)))
            except Exception as hata:
                kuyruk.put(("hata", str(hata)))

        threading.Thread(target=is_parcacigi, daemon=True).start()

        def izle():
            son = None
            try:
                while True:
                    son = kuyruk.get_nowait()
                    if son[0] == "ilerleme":
                        _t, i, n, s = son
                        ilerleme.configure(value=i)
                        ilerleme_lbl.configure(
                            text=f"{i}/{n}  —  başarılı {s['basarili']}, başarısız {s['basarisiz']}, "
                                 f"atlanan {s['atlanan']}")
                    else:
                        break
            except queue.Empty:
                pass
            if son is None or son[0] == "ilerleme":
                app.after(150, izle)
                return
            durum["calisiyor"] = False
            btn_mh.configure(state="normal")
            btn_tekrar.configure(state="normal")
            btn_durdur.configure(state="disabled")
            if son[0] == "hata":
                messagebox.showerror("Muhasebeleştir", son[1], parent=app)
                yenile()
                return
            sonuc = son[1]
            durum["son_basarisiz"] = [r["id"] for r in sonuc["sonuclar"] if r["durum"] == "hata"]
            rapor = (f"Başarılı: {sonuc['basarili']}\nBaşarısız: {sonuc['basarisiz']}\n"
                     f"Atlanan: {sonuc['atlanan']}")
            if sonuc.get("durduruldu"):
                rapor += "\n\nİşlem kullanıcı tarafından durduruldu; kalan evraklar işlenmedi."
            hatalar = [r for r in sonuc["sonuclar"] if r["durum"] != "basarili"]
            if hatalar:
                rapor += "\n\nAyrıntı:\n" + "\n".join(
                    f"• {kayitlar.get(str(r['id']), {}).get('belge_no') or r['id']}: {r['mesaj']}"
                    for r in hatalar[:15])
                if len(hatalar) > 15:
                    rapor += f"\n… ve {len(hatalar) - 15} kayıt daha (listede 'Hatalı' filtresiyle görülebilir)."
            messagebox.showinfo("Muhasebeleştirme Sonucu", rapor, parent=app)
            yenile()

        app.after(150, izle)

    def muhasebelestir():
        baslat(secili_idler())

    def basarisizlari_tekrar():
        try:
            liste = MuhasebelestirmeService.listele(durumlar=(BELGE_HATALI,))
        except Exception as hata:
            messagebox.showerror("Muhasebeleştir", str(hata), parent=app)
            return
        baslat([(k["id"], k["row_version"]) for k in liste])

    def fisi_ac():
        sec = [kayitlar[i] for i in tablo.selection() if i in kayitlar]
        if not sec or not sec[0]["fis_id"]:
            messagebox.showinfo("Fiş", "Bağlı fişi olan bir evrak seçin.", parent=app)
            return
        from genel_muhasebe_ui import FisDialog

        FisDialog(app, fis_id=int(sec[0]["fis_id"]), on_save=yenile)

    def muhasebe_disi():
        ids = [o[0] for o in secili_idler()]
        if not ids:
            messagebox.showinfo("Muhasebe dışı", "Evrak seçin.", parent=app)
            return
        neden = simpledialog.askstring(
            "Muhasebe dışı bırak",
            "Seçili evraklar fiş oluşturulmadan listeden çıkarılacak (ör. başka yolla muhasebeleşmiş).\nNeden:",
            parent=app)
        if not neden:
            return
        try:
            n = MuhasebelestirmeService.muhasebe_disi_birak(ids, neden)
        except Exception as hata:
            messagebox.showerror("Muhasebe dışı", str(hata), parent=app)
            return
        messagebox.showinfo("Muhasebe dışı", f"{n} evrak muhasebe dışı bırakıldı.", parent=app)
        yenile()

    def geri_al():
        ids = [kayitlar[i]["id"] for i in tablo.selection()
               if i in kayitlar and kayitlar[i]["durum"] == BELGE_MUHASEBE_DISI]
        if not ids:
            messagebox.showinfo("Geri al", "Muhasebe dışı durumdaki evrakları seçin.", parent=app)
            return
        try:
            n = MuhasebelestirmeService.muhasebe_disindan_geri_al(ids)
        except Exception as hata:
            messagebox.showerror("Geri al", str(hata), parent=app)
            return
        messagebox.showinfo("Geri al", f"{n} evrak yeniden bekleyenlere alındı.", parent=app)
        yenile()

    def gecmisi_tara():
        if not messagebox.askyesno(
            "Geçmişi tara",
            "Durum kaydı olmayan kesinleşmiş evraklar listeye eklenecek. Bağlı fişi olanlar "
            "'Muhasebeleştirildi', olmayanlar 'İnceleme gerekiyor' olur. Fiş oluşturulmaz. Devam?",
            parent=app,
        ):
            return
        try:
            t = MuhasebelestirmeService.gecmis_tara()
        except Exception as hata:
            messagebox.showerror("Geçmişi tara", str(hata), parent=app)
            return
        messagebox.showinfo("Geçmişi tara", f"Eklenen: muhasebeleştirilmiş {t['muhasebelestirildi']}, "
                                            f"inceleme gerekiyor {t['inceleme']}.", parent=app)
        yenile()

    def gecmis_finans():
        GecmisFinansDialog(app, on_ekle=yenile)

    arac = ttk.Frame(app.icerik)
    arac.pack(fill="x", pady=(6, 0))
    ttk.Button(filtre, text="Yenile", command=yenile).pack(side="left", padx=4)
    btn_mh = ttk.Button(arac, text="Seçilileri Muhasebeleştir", command=muhasebelestir)
    btn_mh.pack(side="left")
    ttk.Button(arac, text="Tümünü Seç", command=lambda: tablo.selection_set(tablo.get_children())).pack(
        side="left", padx=4)
    btn_tekrar = ttk.Button(arac, text="Başarısızları Yeniden Dene", command=basarisizlari_tekrar)
    btn_tekrar.pack(side="left", padx=4)
    btn_durdur = ttk.Button(arac, text="Durdur", state="disabled", command=lambda: durum.update(durdur=True))
    btn_durdur.pack(side="left", padx=4)
    ttk.Button(arac, text="Fişi Aç", command=fisi_ac).pack(side="left", padx=4)
    ttk.Button(arac, text="Muhasebe Dışı Bırak", command=muhasebe_disi).pack(side="left", padx=4)
    ttk.Button(arac, text="Muhasebe Dışından Geri Al", command=geri_al).pack(side="left", padx=4)
    ttk.Button(arac, text="Geçmişi Tara", command=gecmisi_tara).pack(side="left", padx=4)
    ttk.Button(arac, text="Geçmiş Finans Evrakları", command=gecmis_finans).pack(side="left", padx=4)
    tablo.bind("<Double-1>", lambda _e: fisi_ac())
    yenile()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: muhasebelestirilecek_evraklar_goster(app, geri))


_GECMIS_KATEGORILER = {
    "kesin": "Kesin (listeye alınabilir)",
    "belirsiz": "Belirsiz (kaynak kanıtlanamıyor)",
    "karar_bekliyor": "Karar bekliyor",
    "muhasebelestirilmis": "Zaten muhasebeleştirilmiş",
    "listede": "Zaten listede",
}


class GecmisFinansDialog(tk.Toplevel):
    """Geçmiş tahsilat/ödeme/makbuz/havale/virman evrakları: önizleme ve seçimle bekleyenlere alma.

    Yalnız 'kesin' kayıtlar seçilebilir; fiş oluşturulmaz, seçilenler bekleyen listesine düşer.
    """

    def __init__(self, parent, on_ekle=None):
        super().__init__(parent)
        self.title("Geçmiş Finans Evrakları")
        self.geometry("1100x560")
        self.transient(parent)
        self.on_ekle = on_ekle
        self.veri: dict = {}
        ust = ttk.Frame(self, padding=8)
        ust.pack(fill="x")
        ttk.Label(ust, text="Görünüm:").pack(side="left")
        self.kat_var = tk.StringVar(value=_GECMIS_KATEGORILER["kesin"])
        cb = ttk.Combobox(ust, textvariable=self.kat_var, values=list(_GECMIS_KATEGORILER.values()),
                          state="readonly", width=34)
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", lambda _e: self._doldur())
        self.ozet = ttk.Label(ust, text="", foreground="#555")
        self.ozet.pack(side="left", padx=12)
        ttk.Label(self, padding=(8, 0), foreground="#555", wraplength=1060, text=(
            "Kayıtlar yalnız kalıcı bağlantıyla sınıflanır (açıklama/tutar/tarih benzerliği kullanılmaz). "
            "Kesin kayıtları seçip bekleyenlere alabilirsiniz; fiş, Muhasebeleştirilecek Evraklar ekranından "
            "oluşturulur. Belirsiz kayıtlar mevcut fişlerle eşleştirilmez.")).pack(fill="x")
        kolonlar = ("tur", "belge", "tarih", "cari", "tutar", "neden")
        self.tablo = ttk.Treeview(self, columns=kolonlar, show="headings", selectmode="extended")
        for k, baslik, gen in (("tur", "Evrak", 150), ("belge", "Belge No", 130), ("tarih", "Tarih", 85),
                               ("cari", "Cari", 220), ("tutar", "Tutar", 100), ("neden", "Açıklama", 380)):
            self.tablo.heading(k, text=baslik)
            self.tablo.column(k, width=gen, anchor="e" if k == "tutar" else "w")
        self.tablo.pack(fill="both", expand=True, padx=8, pady=6)
        alt = ttk.Frame(self, padding=8)
        alt.pack(fill="x")
        self.btn_ekle = ttk.Button(alt, text="Seçilileri Bekleyenlere Al", command=self._ekle)
        self.btn_ekle.pack(side="left")
        ttk.Button(alt, text="Tümünü Seç", command=lambda: self.tablo.selection_set(self.tablo.get_children())
                   ).pack(side="left", padx=4)
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")
        self._yukle()

    def _kategori(self) -> str:
        return next(k for k, v in _GECMIS_KATEGORILER.items() if v == self.kat_var.get())

    def _yukle(self):
        try:
            self.veri = MuhasebelestirmeService.gecmis_finans_onizle()
        except Exception as hata:
            messagebox.showerror("Geçmiş finans evrakları", str(hata), parent=self)
            self.veri = {}
        sayilar = {k: sum(len(kat.get(k, [])) for kat in self.veri.values()) for k in _GECMIS_KATEGORILER}
        self.ozet.configure(text="  ".join(f"{_GECMIS_KATEGORILER[k].split(' (')[0]}: {n}" for k, n in sayilar.items()))
        self._doldur()

    def _doldur(self):
        self.tablo.delete(*self.tablo.get_children())
        kat = self._kategori()
        self.btn_ekle.configure(state="normal" if kat == "kesin" else "disabled")
        self._satirlar: dict[str, tuple[str, object]] = {}
        for evrak, kategoriler in self.veri.items():
            ad = EVRAKLAR.get(evrak, {}).get("ad", evrak)
            for r in kategoriler.get(kat, []):
                iid = self.tablo.insert("", "end", values=(
                    ad, r["belge_no"] or "", r["tarih"].strftime("%d.%m.%Y") if r.get("tarih") else "",
                    r.get("cari_adi") or "", para_goster(r["tutar"]), r.get("neden") or ""))
                self._satirlar[iid] = (evrak, r["anahtar"])

    def _ekle(self):
        secim = [self._satirlar[i] for i in self.tablo.selection() if i in self._satirlar]
        if not secim:
            messagebox.showinfo("Geçmiş finans evrakları", "Listeye alınacak kesin kayıtları seçin.", parent=self)
            return
        if not messagebox.askyesno(
                "Geçmiş finans evrakları",
                f"{len(secim)} evrak bekleyen listesine alınacak (fiş oluşturulmaz). Devam?", parent=self):
            return
        try:
            sonuc = MuhasebelestirmeService.gecmis_finans_ekle(secim)
        except Exception as hata:
            messagebox.showerror("Geçmiş finans evrakları", str(hata), parent=self)
            return
        metin = f"Bekleyenlere alınan: {len(sonuc['eklenen'])}"
        if sonuc["reddedilen"]:
            metin += f"\nAlınmayan: {len(sonuc['reddedilen'])}\n" + "\n".join(
                f"• {r['anahtar']}: {r['neden']}" for r in sonuc["reddedilen"][:10])
        messagebox.showinfo("Geçmiş finans evrakları", metin, parent=self)
        if self.on_ekle:
            self.on_ekle()
        self._yukle()
