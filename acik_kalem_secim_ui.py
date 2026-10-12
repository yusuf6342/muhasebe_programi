"""Tahsilat / Ödeme Gir için açık borç seçim penceresi.

Sonuç sözleşmesi (``AcikKalemSecimDialog.sonuc``):
  * None → seçim yok (Devam veya Listeyi Kapat): servis otomatik FIFO uygular.
  * {"dagitim": [(hareket_id, Decimal)], "fazla": "FIFO" | "AVANS", "beklenen": {hareket_id: Decimal}}
    → yalnız seçilen belgeler, belge tarihi sırasıyla; artan tutar varsayılan olarak avans kalır.
  * ``VAZGEC`` → kullanıcı makbuza dönmek istedi; kayıt yapılmamalı.
"""

from __future__ import annotations

import tkinter as tk
from datetime import date
from decimal import Decimal
from tkinter import ttk

from tutar_bicim import tr_tutar

KURUS = Decimal("0.01")
VAZGEC = "VAZGEC"
SECILI_ZEMIN = "#D9F5E1"
SECILI_YAZI = "#0B3D1E"
ODAK_ZEMIN = "#FFE8A3"
LACIVERT = "#0B2A4A"
SECILI_ISARET = "☑ Seçili"
SECILMEDI_ISARET = "☐"


def _tarih(t) -> str:
    return t.strftime("%d.%m.%Y") if isinstance(t, date) else ""


def acik_kalemler(cari_id: int, para_birimi: str = "TRY") -> list[dict]:
    from database.acik_kalem_service import AcikKalemService

    return AcikKalemService.secim_listesi_getir(int(cari_id), para_birimi=para_birimi)


def diger_para_kalemleri(cari_id: int) -> dict[str, int]:
    from database.acik_kalem_service import AcikKalemService

    try:
        return AcikKalemService.diger_para_kalemleri(int(cari_id))
    except Exception:
        return {}


class AcikKalemSecimDialog(tk.Toplevel):
    KOLONLAR = ("sec", "evrak", "tur", "tarih", "vade", "kalan", "dagit", "sonra", "durum",
                "ilk", "kapanan", "pb", "kayitli")
    BASLIKLAR = (
        ("sec", "Seç", 82), ("evrak", "Belge No", 118), ("tur", "Belge Türü", 128),
        ("tarih", "Belge Tarihi", 84), ("vade", "Vade", 84), ("kalan", "Açık Kalan", 106),
        ("dagit", "Bu Tahsilatla Kapanacak", 150), ("sonra", "İşlem Sonrası Kalan", 128),
        ("durum", "Durum", 100), ("ilk", "İlk Borç", 104), ("kapanan", "Önceki Kapamalar", 116),
        ("pb", "Para Birimi", 70), ("kayitli", "Kayıtlı Dağıtım", 110),
    )
    SAYISAL = ("kalan", "dagit", "sonra", "ilk", "kapanan", "kayitli")

    def __init__(self, parent, cari_id: int, tutar, *, kalemler: list[dict] | None = None,
                 baslik: str = "Kapatılacak Borçlar", cari_adi: str = "", ust_bilgi: dict | None = None,
                 onceki_secim=(), diger_para: dict | None = None, vazgec_izinli: bool = True,
                 islem_adi: str = "Tahsilat", kayitli: dict | None = None, artani_fifo: bool = False):
        """``kayitli`` (kayıtlı makbuz düzenlemesi): {"secili", "dagitim", "tutar", "fazla"} — seçim ve tutar
        değişmedikçe kayıtlı dağıtım aynen gösterilir/korunur; açık tutarlar belge geri alınmış gibi gelir."""
        super().__init__(parent)
        self.cari_id = int(cari_id)
        self.tutar = Decimal(str(tutar or 0)).quantize(KURUS)
        self.kalemler = kalemler if kalemler is not None else acik_kalemler(self.cari_id)
        self._kalem_map = {int(k["hareket_id"]): k for k in self.kalemler}
        self.secili: set[int] = {int(h) for h in onceki_secim if int(h) in self._kalem_map}
        self.kayitli = dict(kayitli) if kayitli else None
        self.artani_fifo = tk.BooleanVar(master=self, value=bool(artani_fifo))
        self.ust_bilgi = dict(ust_bilgi or {})
        self.diger_para = dict(diger_para or {})
        self.islem_adi = islem_adi
        self.sonuc = None
        self.vazgecildi = False
        self.onizleme: dict = {}
        self.title(baslik)
        self.configure(bg="#FFFFFF")
        self._boyutlandir()
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.kapat)
        self.bind("<Escape>", lambda _e: self.kapat())
        self._arayuz(baslik, cari_adi, vazgec_izinli)
        self._tabloyu_doldur()
        self._hesapla()
        self.tablo.focus_set()
        ilk = self.tablo.get_children()
        if ilk:
            self.tablo.focus(ilk[0])

    def _boyutlandir(self):
        try:
            from ui_pencere import calisma_alani

            x, y, aw, ah = calisma_alani(self)
        except Exception:
            x, y, aw, ah = 0, 0, int(self.winfo_screenwidth()), int(self.winfo_screenheight())
        w = max(760, min(1240, aw - 40))
        h = max(440, min(660, ah - 40))
        self.minsize(min(820, w), min(460, h))
        self.geometry(f"{w}x{h}+{x + max(0, (aw - w) // 2)}+{y + max(0, (ah - h) // 2)}")

    # --- Arayüz ---

    def _arayuz(self, baslik: str, cari_adi: str, vazgec_izinli: bool):
        stil = ttk.Style(self)
        stil.configure("BorcSecim.Treeview", rowheight=26, font=("Segoe UI", 10))
        stil.configure("BorcSecim.Treeview.Heading", font=("Segoe UI", 9, "bold"))
        stil.map("BorcSecim.Treeview", background=[("selected", ODAK_ZEMIN)],
                 foreground=[("selected", LACIVERT)])

        ust = tk.Frame(self, bg=LACIVERT)
        ust.pack(fill="x")
        tk.Label(ust, text=baslik.upper(), bg=LACIVERT, fg="#F5B700",
                 font=("Segoe UI", 13, "bold"), anchor="w").pack(side="left", padx=12, pady=6)
        bilgi = [
            ("Cari", self.ust_bilgi.get("cari") or cari_adi or "—"),
            (f"{self.islem_adi} Tutarı", tr_tutar(self.tutar)),
            ("Para Birimi", self.ust_bilgi.get("para_birimi") or "TRY"),
        ]
        if self.ust_bilgi.get("odeme"):
            bilgi.append(("Ödeme Yöntemi", self.ust_bilgi["odeme"]))
        bilgi_satiri = tk.Frame(self, bg="#FFF7D6")
        bilgi_satiri.pack(fill="x")
        for etiket, deger in bilgi:
            tk.Label(bilgi_satiri, text=f"{etiket}:", bg="#FFF7D6", fg="#475569",
                     font=("Segoe UI", 9)).pack(side="left", padx=(12, 2), pady=4)
            tk.Label(bilgi_satiri, text=str(deger), bg="#FFF7D6", fg=LACIVERT,
                     font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 10), pady=4)

        aciklama = ("Kapatmak istediğiniz belgeleri seçin (Seç sütununa tıklayın, çift tıklayın veya Boşluk). "
                    "Seçim yapmazsanız tutar en eski belgeden başlayarak otomatik FIFO ile dağıtılır.")
        if self.diger_para:
            diger = ", ".join(f"{pb}: {adet} belge" for pb, adet in sorted(self.diger_para.items()))
            aciklama += f"\nFarklı para birimli açık belgeler listede yok ({diger}); bu tutar onlara dağıtılmaz."
        tk.Label(self, text=aciklama, bg="#FFFFFF", fg="#475569", font=("Segoe UI", 9),
                 justify="left", anchor="w", wraplength=1150).pack(fill="x", padx=12, pady=(6, 4))
        self.duzenleme_lbl = tk.Label(self, text="", bg="#FFFFFF", fg=LACIVERT, font=("Segoe UI", 9, "bold"),
                                      justify="left", anchor="w", wraplength=1150)
        if self.kayitli is not None:
            self.duzenleme_lbl.pack(fill="x", padx=12, pady=(0, 4))

        # Alt bölümler önce paketlenir; dar ekranda tablo küçülür, düğmeler görünür kalır.
        alt = tk.Frame(self, bg="#FFFFFF")
        alt.pack(side="bottom", fill="x", padx=12, pady=(4, 10))
        sol = tk.Frame(alt, bg="#FFFFFF")
        sol.pack(side="left")
        ttk.Button(sol, text="Tümünü Seç", command=self.tumunu_sec).pack(side="left")
        ttk.Button(sol, text="Seçimi Temizle", command=self.temizle).pack(side="left", padx=6)
        sag = tk.Frame(alt, bg="#FFFFFF")
        sag.pack(side="right")
        self.devam_btn = tk.Button(sag, text="Devam", command=self.uygula, bg="#F5B700", fg=LACIVERT,
                                   activebackground="#E0A800", font=("Segoe UI", 10, "bold"),
                                   relief="flat", padx=18, pady=4, cursor="hand2")
        self.devam_btn.pack(side="right")
        ttk.Button(sag, text="Listeyi Kapat", command=self.kapat).pack(side="right", padx=6)
        if vazgec_izinli:
            ttk.Button(sag, text="Vazgeç (Makbuza Dön)", command=self.vazgec).pack(side="right")

        self.ozet_cerceve = tk.Frame(self, bg="#F1F5F9", highlightthickness=1, highlightbackground="#CBD5E1")
        self.ozet_cerceve.pack(side="bottom", fill="x", padx=12, pady=(4, 0))
        self.ozet_lbl: dict[str, tk.Label] = {}
        for anahtar, etiket in (("mod", "Dağıtım"), ("secilen", "Seçilen Açık Toplam"),
                                ("tutar", f"{self.islem_adi} Tutarı"), ("dagitilan", "Dağıtılacak"),
                                ("artan", "Artan (Avans)")):
            kutu = tk.Frame(self.ozet_cerceve, bg="#F1F5F9")
            kutu.pack(side="left", padx=10, pady=4)
            tk.Label(kutu, text=etiket, bg="#F1F5F9", fg="#64748B", font=("Segoe UI", 8)).pack(anchor="w")
            lbl = tk.Label(kutu, text="", bg="#F1F5F9", fg=LACIVERT, font=("Segoe UI", 11, "bold"))
            lbl.pack(anchor="w")
            self.ozet_lbl[anahtar] = lbl
        self.artan_chk = tk.Checkbutton(
            self.ozet_cerceve, text="Artanı seçilmeyen borçlara FIFO ile dağıt",
            variable=self.artani_fifo, command=self._hesapla, bg="#F1F5F9",
            font=("Segoe UI", 9), activebackground="#F1F5F9",
        )
        self.artan_chk.pack(side="right", padx=10)

        cerceve = ttk.Frame(self)
        cerceve.pack(fill="both", expand=True, padx=12)
        self.tablo = ttk.Treeview(cerceve, columns=self.KOLONLAR, show="headings", selectmode="browse",
                                  style="BorcSecim.Treeview")
        for kolon, metin, genislik in self.BASLIKLAR:
            self.tablo.heading(kolon, text=metin)
            hiza = "e" if kolon in self.SAYISAL else ("center" if kolon in ("sec", "pb", "tarih", "vade") else "w")
            self.tablo.column(kolon, width=genislik, minwidth=60, anchor=hiza, stretch=kolon == "tur")
        gorunen = [k for k in self.KOLONLAR if k != "kayitli"]
        if self.kayitli is not None:
            gorunen.insert(gorunen.index("dagit"), "kayitli")
        self.tablo.configure(displaycolumns=gorunen)
        dikey = ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview)
        yatay = ttk.Scrollbar(cerceve, orient="horizontal", command=self.tablo.xview)
        self.tablo.configure(yscrollcommand=dikey.set, xscrollcommand=yatay.set)
        self.tablo.grid(row=0, column=0, sticky="nsew")
        dikey.grid(row=0, column=1, sticky="ns")
        yatay.grid(row=1, column=0, sticky="ew")
        cerceve.rowconfigure(0, weight=1)
        cerceve.columnconfigure(0, weight=1)
        self.tablo.tag_configure("secili", background=SECILI_ZEMIN, foreground=SECILI_YAZI)
        self.tablo.tag_configure("kapanacak", foreground="#166534")
        self.tablo.bind("<Button-1>", self._tikla)
        self.tablo.bind("<Double-1>", lambda _e: (self.secimi_degistir(), "break")[1])
        self.tablo.bind("<space>", lambda _e: (self.secimi_degistir(), "break")[1])
        self.tablo.bind("<Return>", lambda _e: (self.uygula(), "break")[1])
        self.tablo.bind("<Control-a>", lambda _e: (self.tumunu_sec(), "break")[1])
        self.tablo.bind("<Control-A>", lambda _e: (self.tumunu_sec(), "break")[1])

    def _tikla(self, olay):
        if self.tablo.identify_region(olay.x, olay.y) != "cell":
            return None
        if self.tablo.identify_column(olay.x) != "#1":
            return None
        satir = self.tablo.identify_row(olay.y)
        if satir:
            self.tablo.focus(satir)
            self.tablo.selection_set(satir)
            self.secimi_degistir(int(satir))
            return "break"
        return None

    # --- Hesap ---

    def _satir_degerleri(self, k: dict) -> tuple:
        hid = int(k["hareket_id"])
        satir = (self.onizleme.get("satirlar") or {}).get(hid) or {}
        pay = satir.get("kapanacak") or Decimal("0")
        sonra = satir.get("sonra", Decimal(str(k["kalan"])))
        return (
            SECILI_ISARET if hid in self.secili else SECILMEDI_ISARET,
            k["evrak_no"], k["tur"], _tarih(k["tarih"]), _tarih(k.get("vade")),
            tr_tutar(k["kalan"]), tr_tutar(pay) if pay > 0 else "", tr_tutar(sonra),
            satir.get("durum", ""), tr_tutar(k["ilk_tutar"]), tr_tutar(k["kapanan"]),
            k.get("para_birimi") or "TRY",
            tr_tutar(k["kayitli_dagitim"]) if (k.get("kayitli_dagitim") or 0) > 0 else "",
        )

    def _tabloyu_doldur(self):
        for k in self.kalemler:
            self.tablo.insert("", "end", iid=str(k["hareket_id"]), values=self._satir_degerleri(k))

    def _hesapla(self):
        from database.acik_kalem_service import DAGITIM_SECILI, dagitim_onizleme

        sabit = self._kayitli_dagitim()
        self.onizleme = dagitim_onizleme(self.kalemler, self.tutar, self.secili,
                                         artani_fifo=bool(self.artani_fifo.get()), sabit=sabit)
        self.onizleme["kayitli_korundu"] = sabit is not None
        if self.kayitli is not None:
            if sabit is not None:
                metin = "Düzenleme: kayıtlı belge seçimi ve dağıtım tutarları korunuyor."
            elif self.secili:
                metin = ("Düzenleme: tutar veya seçim değişti — dağıtım seçili belgeler içinde yeniden "
                         "hesaplandı. Kaydetmeden önce kontrol edin.")
            else:
                metin = "Düzenleme: seçim yok — kayıtta otomatik FIFO uygulanır."
            self.duzenleme_lbl.configure(text=metin)
        for k in self.kalemler:
            hid = int(k["hareket_id"])
            pay = self.onizleme["satirlar"][hid]["kapanacak"]
            etiketler = ("secili",) if hid in self.secili else (("kapanacak",) if pay > 0 else ())
            self.tablo.item(str(hid), values=self._satir_degerleri(k), tags=etiketler)
        o = self.onizleme
        self.ozet_lbl["mod"].configure(text=o["mod"])
        self.ozet_lbl["secilen"].configure(text=tr_tutar(o["secilen_toplam"]) if self.secili else "—")
        self.ozet_lbl["tutar"].configure(text=tr_tutar(o["tutar"]))
        self.ozet_lbl["dagitilan"].configure(text=tr_tutar(o["dagitilan"]))
        artan_renk = "#B45309" if o["artan"] > 0 else LACIVERT
        self.ozet_lbl["artan"].configure(text=tr_tutar(o["artan"]), fg=artan_renk)
        durum = "normal" if o["mod"] == DAGITIM_SECILI else "disabled"
        self.artan_chk.configure(state=durum)

    def _kayitli_dagitim(self) -> dict | None:
        k = self.kayitli
        if not k or not k.get("secili") or not k.get("dagitim"):
            return None
        if set(self.secili) != {int(h) for h in k["secili"]}:
            return None
        if Decimal(str(k.get("tutar") or 0)).quantize(KURUS) != self.tutar:
            return None
        if bool(self.artani_fifo.get()) != ((k.get("fazla") or "AVANS") == "FIFO"):
            return None
        return {int(h): Decimal(str(t)) for h, t in k["dagitim"].items()}

    # --- Seçim ---

    def secimi_degistir(self, hid: int | None = None):
        if hid is None:
            odak = self.tablo.focus() or (self.tablo.selection() or ("",))[0]
            if not odak:
                return
            hid = int(odak)
        if hid in self.secili:
            self.secili.discard(hid)
        else:
            self.secili.add(hid)
        self._hesapla()

    def tumunu_sec(self):
        self.secili = set(self._kalem_map)
        self._hesapla()

    def temizle(self):
        self.secili.clear()
        self._hesapla()

    # --- Sonuç ---

    def _sonuc_uret(self):
        if not self.secili:
            return None
        satirlar = self.onizleme["satirlar"]
        dagitim = [(hid, pay) for hid, pay in self.onizleme["dagitim"] if hid in self.secili]
        return {
            "dagitim": dagitim,
            "fazla": "FIFO" if self.artani_fifo.get() else "AVANS",
            "beklenen": {hid: Decimal(str(self._kalem_map[hid]["kalan"])) for hid in self.secili},
            "secili": sorted(self.secili),
            "ozet": {
                "mod": self.onizleme["mod"],
                "dagitilan": self.onizleme["dagitilan"],
                "artan": self.onizleme["artan"],
                "kapanacak": {hid: s["kapanacak"] for hid, s in satirlar.items() if s["kapanacak"] > 0},
                "kayitli_korundu": bool(self.onizleme.get("kayitli_korundu")),
            },
            "kayitli": self.kayitli,
        }

    def uygula(self):
        self.sonuc = self._sonuc_uret()
        self.destroy()

    def kapat(self):
        """Listeyi Kapat / pencere kapatma: mevcut seçim korunur; seçim yoksa otomatik FIFO."""
        self.uygula()

    def vazgec(self):
        self.vazgecildi = True
        self.sonuc = VAZGEC
        self.destroy()


def plan_ozet_metni(sonuc, tutar=None) -> str:
    """Makbuz ekranında gösterilecek kısa dağıtım özeti."""
    if sonuc is None or sonuc == VAZGEC:
        return "Kapatma: Otomatik FIFO (en eski belgeden)."
    ozet = sonuc.get("ozet") or {}
    metin = f"Kapatma: Seçilen {len(sonuc.get('secili') or sonuc.get('dagitim') or [])} belge"
    if ozet.get("kayitli_korundu"):
        metin += " (kayıtlı dağıtım korunuyor)"
    if ozet:
        metin += f" · Dağıtılacak {tr_tutar(ozet.get('dagitilan') or 0)}"
        artan = ozet.get("artan") or Decimal("0")
        if artan > 0:
            metin += (f" · Artan {tr_tutar(artan)} "
                      f"{'diğer borçlara FIFO' if sonuc.get('fazla') == 'FIFO' else 'avans'}")
    return metin + "."


def kayitli_plan(cari_id: int, belge_no: str, tutar) -> dict | None:
    """Kayıtlı makbuzun kapatma seçimini düzenleme planı olarak yükler.

    Kullanıcı seçimi yoksa (otomatik FIFO ile kaydedilmiş) None döner. Plan ``kayitli`` bilgisini de taşır;
    seçim penceresi aynı bilgiyle açılınca kayıtlı tutarlar aynen gösterilir.
    """
    from database.acik_kalem_service import AcikKalemService

    durum = AcikKalemService.belge_secim_durumu(int(cari_id), belge_no)
    if not durum["secili"]:
        return None
    kalemler = {int(k["hareket_id"]): k for k in durum["kalemler"]}
    tutar = Decimal(str(tutar or 0)).quantize(KURUS)
    dagitim = [(int(k["hareket_id"]), durum["dagitim"][int(k["hareket_id"])]) for k in durum["kalemler"]
               if int(k["hareket_id"]) in durum["dagitim"]]
    dagitilan = sum((t for _h, t in dagitim), Decimal("0")).quantize(KURUS)
    return {
        "dagitim": dagitim,
        "fazla": durum["fazla"],
        "beklenen": {hid: Decimal(str(kalemler[hid]["kalan"])) for hid in durum["secili"]},
        "secili": sorted(durum["secili"]),
        "ozet": {"mod": "Seçilen Belgeler", "dagitilan": dagitilan, "artan": (tutar - dagitilan).quantize(KURUS),
                 "kapanacak": dict(dagitim), "kayitli_korundu": True},
        "kayitli": {"secili": list(durum["secili"]), "dagitim": dict(durum["dagitim"]), "tutar": tutar,
                    "fazla": durum["fazla"]},
    }


def kapatma_plani_sor(parent, cari_id: int, tutar, *, cari_adi: str = "", baslik: str = "Kapatılacak Borçlar",
                      ust_bilgi: dict | None = None, onceki_secim=(), vazgec_izinli: bool = True,
                      islem_adi: str = "Tahsilat", haric_belge_no: str | None = None,
                      kayitli: dict | None = None, artani_fifo: bool = False):
    """Açık kalem varsa pencereyi açar. (acildi, sonuc) döner; sonuc None → FIFO, VAZGEC → kaydetme.

    ``haric_belge_no``: düzenlenen kayıtlı belgenin tahsisleri geri alınmış gibi listelenir.
    """
    from database.acik_kalem_service import AcikKalemService

    tutar = Decimal(str(tutar or 0))
    if tutar <= 0 or not cari_id:
        return False, None
    kalemler = AcikKalemService.secim_listesi_getir(int(cari_id), haric_belge_no=haric_belge_no)
    if not kalemler:
        return False, None
    onceki_grab = parent.grab_current()
    pencere = AcikKalemSecimDialog(
        parent, int(cari_id), tutar, kalemler=kalemler, baslik=baslik, cari_adi=cari_adi,
        ust_bilgi=ust_bilgi, onceki_secim=onceki_secim, diger_para=diger_para_kalemleri(int(cari_id)),
        vazgec_izinli=vazgec_izinli, islem_adi=islem_adi,
        kayitli=kayitli if haric_belge_no else None, artani_fifo=artani_fifo,
    )
    parent.wait_window(pencere)
    if onceki_grab is not None:
        try:
            if onceki_grab.winfo_exists():
                onceki_grab.grab_set()
        except tk.TclError:
            pass
    return True, pencere.sonuc
