"""Satın Alma → Masraf Dağıtımı: liste + gider belgesini alış katmanlarına dağıtma kartı."""

from __future__ import annotations

import tkinter as tk
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from tkinter import messagebox, simpledialog, ttk

from satis_tema import ACIK_BG, BEYAZ, CIZGI, IKINCIL, LACIVERT, SARI, font, tk_buton, treeview_stil


def _para(tutar) -> str:
    from satin_alma_ui import _para as para

    return para(tutar)


def _tarih(d) -> str:
    from satin_alma_ui import _tarih as tarih

    return tarih(d)


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


def _sayi(v) -> str:
    if v in (None, ""):
        return ""
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        return str(v)
    metin = f"{d.normalize():f}"
    return metin.replace(".", ",")


def _durum_etiketi(durum: str) -> str:
    return {"TASLAK": "Taslak", "ONAYLANDI": "Onaylandı", "İPTAL EDİLDİ": "İptal Edildi"}.get(durum, durum or "")


# ----------------------------------------------------------------- liste
def masraf_dagitimi_goster(app) -> None:
    from database.access import yetki_var
    from database.masraf_dagitim_service import DURUMLAR, MasrafDagitimService
    from satin_alma_ui import _liste_ust, satin_alma_hub_goster

    kok = _liste_ust(
        app,
        "MASRAF DAĞITIMI",
        "Nakliye, yükleme vb. gider belgelerini alış maliyetine (stok / SMM) dağıtın",
        lambda: satin_alma_hub_goster(app),
    )
    filtre = tk.Frame(kok, bg=ACIK_BG)
    filtre.pack(fill="x", padx=16, pady=(8, 0))

    def etiket(metin):
        tk.Label(filtre, text=metin, bg=ACIK_BG, fg=LACIVERT, font=font(10, "bold", app)).pack(side="left", padx=(8, 2))

    etiket("Başlangıç")
    bas = ttk.Entry(filtre, width=11)
    bas.insert(0, date(date.today().year, 1, 1).strftime("%d.%m.%Y"))
    bas.pack(side="left")
    etiket("Bitiş")
    bit = ttk.Entry(filtre, width=11)
    bit.insert(0, date.today().strftime("%d.%m.%Y"))
    bit.pack(side="left")
    etiket("Kaynak belge")
    kaynak = ttk.Entry(filtre, width=16)
    kaynak.pack(side="left")
    etiket("Cari")
    tedarikciler = []
    try:
        from database.alis_siparisi_service import AlisSiparisiService

        tedarikciler = [(int(c.id), c.unvan) for c in AlisSiparisiService.aktif_tedarikcileri()]
    except Exception:  # noqa: BLE001
        tedarikciler = []
    cari = ttk.Combobox(filtre, values=["Tümü"] + [u for _i, u in tedarikciler], state="readonly", width=24)
    cari.set("Tümü")
    cari.pack(side="left")
    etiket("Durum")
    durum = ttk.Combobox(filtre, values=["Tümü"] + [_durum_etiketi(d) for d in DURUMLAR], state="readonly", width=13)
    durum.set("Tümü")
    durum.pack(side="left")

    cerceve = ttk.Frame(kok)
    cerceve.pack(fill="both", expand=True, padx=16, pady=8)
    kolonlar = ("no", "tarih", "tur", "kaynak", "tutar", "alis", "yontem", "durum", "kullanici")
    tablo = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
    treeview_stil(tablo)
    for k, b, w, a in (
        ("no", "Dağıtım No", 100, "w"),
        ("tarih", "Tarih", 90, "center"),
        ("tur", "Kaynak Türü", 190, "w"),
        ("kaynak", "Kaynak Belge", 130, "w"),
        ("tutar", "Dağıtılan Tutar", 120, "e"),
        ("alis", "Alış Belgesi", 90, "center"),
        ("yontem", "Yöntem", 150, "w"),
        ("durum", "Durum", 100, "center"),
        ("kullanici", "Kullanıcı", 130, "w"),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor=a)
    tablo.pack(side="left", fill="both", expand=True)
    ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview).pack(side="right", fill="y")

    def yenile():
        try:
            b1, b2 = _tarih_oku(bas.get()), _tarih_oku(bit.get())
        except ValueError as e:
            messagebox.showerror("Filtre", str(e), parent=app)
            return
        cari_id = next((i for i, u in tedarikciler if u == cari.get()), None)
        durum_kod = next((d for d in DURUMLAR if _durum_etiketi(d) == durum.get()), None)
        try:
            kayitlar = MasrafDagitimService.listele(
                baslangic=b1, bitis=b2, kaynak=kaynak.get(), cari_id=cari_id, durum=durum_kod
            )
        except (ValueError, PermissionError) as e:
            messagebox.showerror("Masraf Dağıtımı", str(e), parent=app)
            return
        tablo.delete(*tablo.get_children())
        for i, r in enumerate(kayitlar):
            tablo.insert(
                "", "end", iid=str(r["id"]), tags=("tek" if i % 2 == 0 else "cift",),
                values=(r["dagitim_no"], _tarih(r["tarih"]), r["kaynak_turu"], r["kaynak_no"], _para(r["tutar"]),
                        r["alis_sayisi"], r["yontem"], _durum_etiketi(r["durum"]), r["kullanici"]),
            )

    def ac(dagitim_id=None):
        dlg = MasrafDagitimDialog(app, dagitim_id=dagitim_id)
        app.wait_window(dlg)
        yenile()

    def secili_ac(_e=None):
        sec = tablo.selection()
        if not sec:
            messagebox.showinfo("Seçim", "Dağıtım seçin.", parent=app)
            return
        ac(int(sec[0]))

    def eski():
        from satin_alma_ui import eski_fatura_masraflari_goster

        eski_fatura_masraflari_goster(app)

    alt = tk.Frame(kok, bg=ACIK_BG)
    alt.pack(fill="x", padx=16, pady=10)
    yeni_btn = tk_buton(alt, "Yeni", lambda: ac(None), rol="yeni")
    yeni_btn.pack(side="left")
    if not yetki_var("alis_masraf_duzenleme", "alis_masraf_onay"):
        yeni_btn.configure(state="disabled")
    tk_buton(alt, "Aç", secili_ac, rol="duzenle").pack(side="left", padx=6)
    tk_buton(alt, "Eski Fatura Masrafları", eski, rol="geri").pack(side="left", padx=6)
    tk_buton(alt, "Listele", yenile, rol="ara").pack(side="right")
    tablo.bind("<Double-1>", secili_ac)
    for w in (bas, bit, kaynak):
        w.bind("<Return>", lambda _e: yenile())
    cari.bind("<<ComboboxSelected>>", lambda _e: yenile())
    durum.bind("<<ComboboxSelected>>", lambda _e: yenile())
    yenile()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: masraf_dagitimi_goster(app))


# --------------------------------------------------------- seçim pencereleri
class _SecimDialog(tk.Toplevel):
    """Arama kutulu tablo; çoklu seçimde işaretli satır id'lerini döndürür."""

    def __init__(self, parent, baslik, kolonlar, yukle, *, coklu=False, genislik=980):
        super().__init__(parent)
        self.title(baslik)
        self.configure(bg=ACIK_BG)
        self.transient(parent.winfo_toplevel())
        self.geometry(f"{genislik}x520")
        self.result = None
        self._yukle = yukle
        ust = tk.Frame(self, bg=ACIK_BG)
        ust.pack(fill="x", padx=10, pady=8)
        tk.Label(ust, text="Ara:", bg=ACIK_BG, fg=LACIVERT).pack(side="left")
        self.arama = ttk.Entry(ust, width=40)
        self.arama.pack(side="left", padx=6)
        self.arama.bind("<KeyRelease>", lambda _e: self._doldur())
        cerceve = ttk.Frame(self)
        cerceve.pack(fill="both", expand=True, padx=10)
        self.tablo = ttk.Treeview(
            cerceve, columns=[k for k, *_ in kolonlar], show="headings",
            selectmode="extended" if coklu else "browse",
        )
        treeview_stil(self.tablo)
        for k, b, w, a in kolonlar:
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=w, anchor=a)
        self.tablo.pack(side="left", fill="both", expand=True)
        ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview).pack(side="right", fill="y")
        alt = tk.Frame(self, bg=ACIK_BG)
        alt.pack(fill="x", padx=10, pady=8)
        tk_buton(alt, "Seç", self._sec, rol="kaydet").pack(side="right")
        tk_buton(alt, "Vazgeç", self.destroy, rol="geri").pack(side="right", padx=6)
        self.tablo.bind("<Double-1>", lambda _e: self._sec())
        self._doldur()
        self.arama.focus_set()

    def _doldur(self):
        self.tablo.delete(*self.tablo.get_children())
        for i, (iid, degerler) in enumerate(self._yukle(self.arama.get())):
            self.tablo.insert("", "end", iid=str(iid), values=degerler, tags=("tek" if i % 2 == 0 else "cift",))

    def _sec(self):
        sec = self.tablo.selection()
        if not sec:
            return
        self.result = [int(x) for x in sec]
        self.destroy()


# ------------------------------------------------------------------ kart
class MasrafDagitimDialog(tk.Toplevel):
    """Kaynak gider belgesi seç → alış satırlarını seç → önizle → taslak / onay."""

    HEDEF_KOLONLARI = (
        ("fatura", "Alış Faturası", 110, "w"),
        ("kod", "Stok Kodu", 90, "w"),
        ("ad", "Stok Adı", 170, "w"),
        ("depo", "Depo", 90, "w"),
        ("birim", "Ana Birim", 70, "center"),
        ("miktar", "Ana Birim Mik.", 90, "e"),
        ("alis", "Alış Tutarı", 95, "e"),
        ("maliyet", "Mevcut Maliyet", 95, "e"),
        ("olcu", "Ölçü / Elle", 80, "e"),
        ("pay", "Dağıtılan Pay", 95, "e"),
        ("stok", "Stok Payı", 85, "e"),
        ("smm", "SMM Payı", 85, "e"),
        ("yeni", "Yeni Birim Maliyet", 110, "e"),
    )

    def __init__(self, parent, dagitim_id: int | None = None):
        super().__init__(parent)
        from database.access import yetki_var
        from database.masraf_dagitim_service import YONTEM_ETIKETLERI, YONTEMLER

        self.title("Masraf Dağıtımı")
        self.configure(bg=ACIK_BG)
        self.transient(parent.winfo_toplevel())
        self.geometry("1320x800")
        self.dagitim_id = dagitim_id
        self.row_version: int | None = None
        self.durum = "TASLAK"
        self.kaynak: dict | None = None
        self.secili_kaynak: set[int] = set()
        self.hedefler: list[dict] = []
        self.onizleme: dict | None = None
        self._degisti = False
        self._yukleniyor = False
        self._yontem_kodlari = {YONTEM_ETIKETLERI[k]: k for k in YONTEMLER}
        self._yetki_taslak = yetki_var("alis_masraf_duzenleme", "alis_masraf_onay")
        self._yetki_onay = yetki_var("alis_masraf_onay")
        self._yetki_geri = yetki_var("alis_masraf_geri_al")

        # --- başlık
        bant = tk.Frame(self, bg=LACIVERT)
        bant.pack(fill="x")
        tk.Label(bant, text="MASRAF DAĞITIMI", bg=LACIVERT, fg=SARI, font=font(18, "bold", self)).pack(
            side="left", padx=16, pady=10
        )
        self.durum_lbl = tk.Label(bant, text="", bg=LACIVERT, fg=BEYAZ, font=font(12, "bold", self))
        self.durum_lbl.pack(side="right", padx=16)

        ust = tk.Frame(self, bg=ACIK_BG)
        ust.pack(fill="x", padx=12, pady=(8, 0))
        tk.Label(ust, text="Dağıtım No", bg=ACIK_BG, fg=LACIVERT).grid(row=0, column=0, sticky="w")
        self.no_lbl = tk.Label(ust, text="(yeni)", bg=ACIK_BG, fg=LACIVERT, font=font(11, "bold", self))
        self.no_lbl.grid(row=0, column=1, sticky="w", padx=(4, 16))
        tk.Label(ust, text="Tarih", bg=ACIK_BG, fg=LACIVERT).grid(row=0, column=2, sticky="w")
        self.tarih = ttk.Entry(ust, width=12)
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        self.tarih.grid(row=0, column=3, padx=(4, 16))
        tk.Label(ust, text="Yöntem", bg=ACIK_BG, fg=LACIVERT).grid(row=0, column=4, sticky="w")
        self.yontem = ttk.Combobox(ust, values=list(self._yontem_kodlari), state="readonly", width=22)
        self.yontem.set(YONTEM_ETIKETLERI["TUTAR"])
        self.yontem.grid(row=0, column=5, padx=(4, 16))
        tk.Label(ust, text="Dağıtılacak Tutar (TL)", bg=ACIK_BG, fg=LACIVERT).grid(row=0, column=6, sticky="w")
        self.tutar = ttk.Entry(ust, width=14, justify="right")
        self.tutar.grid(row=0, column=7, padx=(4, 16))
        tk.Label(ust, text="Açıklama", bg=ACIK_BG, fg=LACIVERT).grid(row=1, column=0, sticky="w", pady=4)
        self.aciklama = ttk.Entry(ust, width=90)
        self.aciklama.grid(row=1, column=1, columnspan=7, sticky="we", padx=4, pady=4)

        # --- kaynak
        kutu1 = tk.LabelFrame(self, text=" 1) Kaynak gider belgesi ", bg=ACIK_BG, fg=LACIVERT,
                              font=font(10, "bold", self))
        kutu1.pack(fill="x", padx=12, pady=6)
        ks = tk.Frame(kutu1, bg=ACIK_BG)
        ks.pack(fill="x", padx=6, pady=4)
        self.kaynak_btn = tk_buton(ks, "Kaynak Belge Seç…", self._kaynak_sec_dialog, rol="ara")
        self.kaynak_btn.pack(side="left")
        self.kaynak_lbl = tk.Label(ks, text="Kaynak seçilmedi.", bg=ACIK_BG, fg=IKINCIL, font=font(10, root=self))
        self.kaynak_lbl.pack(side="left", padx=10)
        self.kaynak_tablo = ttk.Treeview(
            kutu1, columns=("sec", "kod", "ad", "tutar", "dagitilan", "kalan", "uygun"), show="headings", height=4
        )
        treeview_stil(self.kaynak_tablo)
        for k, b, w, a in (
            ("sec", "Seç", 50, "center"), ("kod", "Kod", 110, "w"), ("ad", "Gider Satırı", 300, "w"),
            ("tutar", "KDV Hariç Tutar", 120, "e"), ("dagitilan", "Önceki Dağıtım", 120, "e"),
            ("kalan", "Kalan", 110, "e"), ("uygun", "Maliyete Uygun", 110, "center"),
        ):
            self.kaynak_tablo.heading(k, text=b)
            self.kaynak_tablo.column(k, width=w, anchor=a)
        self.kaynak_tablo.pack(fill="x", padx=6, pady=(0, 6))
        self.kaynak_tablo.bind("<Button-1>", self._kaynak_tikla)

        # --- hedefler
        kutu2 = tk.LabelFrame(self, text=" 2) Masrafın yükleneceği alış satırları ", bg=ACIK_BG, fg=LACIVERT,
                              font=font(10, "bold", self))
        kutu2.pack(fill="both", expand=True, padx=12, pady=6)
        hs = tk.Frame(kutu2, bg=ACIK_BG)
        hs.pack(fill="x", padx=6, pady=4)
        self.hedef_btn = tk_buton(hs, "Alış Satırı Ekle…", self._hedef_sec_dialog, rol="ara")
        self.hedef_btn.pack(side="left")
        self.hedef_sil_btn = tk_buton(hs, "Satırı Çıkar", self._hedef_cikar, rol="iptal")
        self.hedef_sil_btn.pack(side="left", padx=6)
        tk.Label(hs, text="Ağırlık/hacim/elle yönteminde değeri girmek için 'Ölçü / Elle' hücresine çift tıklayın.",
                 bg=ACIK_BG, fg=IKINCIL).pack(side="left", padx=10)
        cerceve = ttk.Frame(kutu2)
        cerceve.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.hedef_tablo = ttk.Treeview(
            cerceve, columns=[k for k, *_ in self.HEDEF_KOLONLARI], show="headings", selectmode="browse"
        )
        treeview_stil(self.hedef_tablo)
        for k, b, w, a in self.HEDEF_KOLONLARI:
            self.hedef_tablo.heading(k, text=b)
            self.hedef_tablo.column(k, width=w, anchor=a)
        self.hedef_tablo.pack(side="left", fill="both", expand=True)
        ttk.Scrollbar(cerceve, orient="vertical", command=self.hedef_tablo.yview).pack(side="right", fill="y")
        self.hedef_tablo.bind("<Double-1>", self._olcu_duzenle)

        # --- özet + düğmeler
        self.ozet_lbl = tk.Label(self, text="", bg=BEYAZ, fg=LACIVERT, justify="left", anchor="w",
                                 font=font(10, root=self), highlightthickness=1, highlightbackground=CIZGI)
        self.ozet_lbl.pack(fill="x", padx=12, pady=(0, 6), ipady=6)
        alt = tk.Frame(self, bg=ACIK_BG)
        alt.pack(fill="x", padx=12, pady=(0, 10))
        self.onizle_btn = tk_buton(alt, "Önizle", self.onizle, rol="ara")
        self.onizle_btn.pack(side="left")
        self.taslak_btn = tk_buton(alt, "Taslak Kaydet", self.taslak_kaydet, rol="duzenle")
        self.taslak_btn.pack(side="left", padx=6)
        self.onay_btn = tk_buton(alt, "Onayla ve Uygula", self.onayla, rol="kaydet")
        self.onay_btn.pack(side="left", padx=6)
        self.geri_btn = tk_buton(alt, "Geri Al", self.geri_al, rol="iptal")
        self.geri_btn.pack(side="left", padx=6)
        self.iptal_btn = tk_buton(alt, "Taslağı İptal Et", self.taslak_iptal, rol="iptal")
        self.iptal_btn.pack(side="left", padx=6)
        tk_buton(alt, "Geçmiş", self._gecmis_goster, rol="geri").pack(side="left", padx=6)
        tk_buton(alt, "Kapat", self.kapat, rol="geri").pack(side="right")

        for w in (self.tarih, self.tutar, self.aciklama):
            w.bind("<KeyRelease>", lambda _e: self._degisiklik())
        self.yontem.bind("<<ComboboxSelected>>", lambda _e: self._degisiklik())
        self.protocol("WM_DELETE_WINDOW", self.kapat)

        if dagitim_id:
            self._yukle(dagitim_id)
        self._durum_uygula()

    # -------------------------------------------------------------- durum
    def _salt_okunur(self) -> bool:
        return self.durum != "TASLAK" or not self._yetki_taslak

    def _durum_uygula(self):
        salt = self._salt_okunur()
        durum_str = "disabled" if salt else "normal"
        for w in (self.tarih, self.tutar, self.aciklama):
            w.configure(state=durum_str)
        self.yontem.configure(state="disabled" if salt else "readonly")
        for b in (self.kaynak_btn, self.hedef_btn, self.hedef_sil_btn, self.onizle_btn, self.taslak_btn):
            b.configure(state=durum_str)
        self.onay_btn.configure(state="normal" if self.durum == "TASLAK" and self._yetki_onay else "disabled")
        self.geri_btn.configure(state="normal" if self.durum == "ONAYLANDI" and self._yetki_geri else "disabled")
        self.iptal_btn.configure(
            state="normal" if self.durum == "TASLAK" and self.dagitim_id and self._yetki_taslak else "disabled"
        )
        self.durum_lbl.configure(text=_durum_etiketi(self.durum).upper())

    def _degisiklik(self):
        if self._yukleniyor:
            return
        self._degisti = True
        if self.onizleme is not None:
            self.onizleme = None
            self.ozet_lbl.configure(text="Değişiklik yapıldı; önizleme geçersiz. Yeniden 'Önizle'ye basın.",
                                    fg=LACIVERT)
        self._hedefleri_ciz()

    # --------------------------------------------------------------- yükle
    def _yukle(self, dagitim_id: int):
        from database.masraf_dagitim_service import YONTEM_ETIKETLERI, MasrafDagitimService

        d = MasrafDagitimService.getir(dagitim_id)
        self._yukleniyor = True
        try:
            self.dagitim_id = int(d["id"])
            self.row_version = int(d["row_version"] or 1)
            self.durum = d["durum"]
            self.no_lbl.configure(text=d["dagitim_no"])
            self.tarih.delete(0, "end")
            self.tarih.insert(0, _tarih(d["dagitim_tarihi"]))
            self.yontem.set(YONTEM_ETIKETLERI.get(d["yontem"], d["yontem"]))
            self.tutar.delete(0, "end")
            self.tutar.insert(0, _sayi(d["tutar"]))
            self.aciklama.delete(0, "end")
            self.aciklama.insert(0, d.get("aciklama") or "")
            self._kaynak_yukle(int(d["kaynak_id"]), secili=set(d["kaynak_satir_idler"]), tutar_ayarla=False)
            self.hedefler = [
                {
                    "satir_id": s["alis_fatura_satiri_id"], "fatura_no": s["alis_fatura_no"], "urun_kodu": s["urun_kodu"],
                    "urun_adi": s["urun_adi"], "depo": s["depo"], "birim": s["birim"], "ana_miktar": s["ana_miktar"],
                    "alis_tutari": s["alis_tutari"], "birim_maliyet": s["eski_birim_maliyet"],
                    "olcu": s["olcu"], "elle_tutar": s["elle_tutar"],
                    "_sonuc": s if d["durum"] != "TASLAK" else None,
                }
                for s in d["satirlar"]
            ]
            self._hedefleri_ciz()
            if d["durum"] != "TASLAK":
                self.ozet_lbl.configure(text=self._ozet_metni(d, d.get("geri_alma_nedeni")))
        finally:
            self._yukleniyor = False
        self._degisti = False

    def _ozet_metni(self, d: dict, not_=None) -> str:
        metin = (
            f"Dağıtılan: {_para(d.get('tutar'))} TL   |   Stoka: {_para(d.get('stok_payi'))} TL   |   "
            f"SMM'ye: {_para(d.get('smm_payi'))} TL   |   İade edilen kısım (giderde kalır): {_para(d.get('iade_payi'))} TL"
        )
        if d.get("onaylayan"):
            metin += f"\nOnaylayan: {d['onaylayan']} ({_tarih(d.get('onay_tarihi'))})"
        if d.get("fis_id"):
            metin += f"   |   Muhasebe fişi id: {d['fis_id']}"
        if d.get("ters_fis_id"):
            metin += f"   |   Ters fiş id: {d['ters_fis_id']}"
        if not_:
            metin += f"\nNeden: {not_}"
        return metin

    # -------------------------------------------------------------- kaynak
    def _kaynak_sec_dialog(self):
        from database.masraf_dagitim_service import MasrafDagitimService

        belgeler: dict[int, dict] = {}

        def yukle(arama):
            belgeler.clear()
            for b in MasrafDagitimService.kaynak_belgeler(arama):
                belgeler[b["id"]] = b
                yield b["id"], (b["tur_etiket"], b["no"], _tarih(b["tarih"]), b["cari"], b["para_birimi"],
                                _para(b["uygun_tutar"]), _para(b["onceki_dagitim"]), _para(b["kalan"]))

        dlg = _SecimDialog(
            self, "Kaynak gider belgesi seç",
            (("tur", "Belge Türü", 180, "w"), ("no", "Belge No", 120, "w"), ("tarih", "Tarih", 85, "center"),
             ("cari", "Cari", 200, "w"), ("pb", "Döviz", 50, "center"), ("uygun", "Uygun Tutar", 100, "e"),
             ("onceki", "Önceki Dağıtım", 100, "e"), ("kalan", "Kalan", 100, "e")),
            lambda a: list(yukle(a)),
        )
        self.wait_window(dlg)
        if dlg.result:
            self.kaynak_ayarla(dlg.result[0])

    def kaynak_ayarla(self, kaynak_id: int):
        self._kaynak_yukle(int(kaynak_id), secili=None, tutar_ayarla=True)
        self._degisiklik()

    def _kaynak_yukle(self, kaynak_id: int, *, secili: set[int] | None, tutar_ayarla: bool):
        from database.masraf_dagitim_service import MasrafDagitimService

        self.kaynak = MasrafDagitimService.kaynak_detay(kaynak_id, self.dagitim_id)
        if secili is None:
            secili = {s["id"] for s in self.kaynak["satirlar"] if s["uygun"] and s["kalan"] > 0}
        self.secili_kaynak = set(secili)
        k = self.kaynak
        self.kaynak_lbl.configure(
            text=f"{k['no']}  |  {_tarih(k['tarih'])}  |  {k['cari']}  |  {k['para_birimi']}"
            + (f" (kur {_sayi(k['kur'])})" if k["para_birimi"] != "TRY" else "")
            + "  |  Tutarlar KDV hariç TL",
            fg=LACIVERT,
        )
        self._kaynak_ciz()
        if tutar_ayarla:
            self._tutari_secimden_ayarla()

    def _kaynak_ciz(self):
        self.kaynak_tablo.delete(*self.kaynak_tablo.get_children())
        for s in (self.kaynak or {}).get("satirlar", []):
            self.kaynak_tablo.insert(
                "", "end", iid=str(s["id"]),
                values=("☑" if s["id"] in self.secili_kaynak else "☐", s["kod"], s["ad"], _para(s["tutar"]),
                        _para(s["dagitilan"]), _para(s["kalan"]), "Evet" if s["uygun"] else "Hayır"),
            )

    def _tutari_secimden_ayarla(self):
        toplam = sum((s["kalan"] for s in self.kaynak["satirlar"] if s["id"] in self.secili_kaynak), Decimal("0"))
        self.tutar.configure(state="normal")
        self.tutar.delete(0, "end")
        self.tutar.insert(0, _sayi(toplam))

    def _kaynak_tikla(self, event):
        if self._salt_okunur() or self.kaynak_tablo.identify_column(event.x) != "#1":
            return
        iid = self.kaynak_tablo.identify_row(event.y)
        if iid:
            self.kaynak_satir_degistir(int(iid))
            return "break"

    def kaynak_satir_degistir(self, satir_id: int):
        s = next((x for x in self.kaynak["satirlar"] if x["id"] == satir_id), None)
        if s is None:
            return
        if satir_id in self.secili_kaynak:
            self.secili_kaynak.discard(satir_id)
        else:
            if not s["uygun"] and not messagebox.askyesno(
                "Uygunluk",
                f"'{s['ad']}' satırı otomatik olarak maliyete uygun görülmüyor (ör. satış teslimatı, kira).\n"
                "Yine de maliyete dağıtmak istiyor musunuz?",
                parent=self,
            ):
                return
            self.secili_kaynak.add(satir_id)
        self._kaynak_ciz()
        self._tutari_secimden_ayarla()
        self._degisiklik()

    # ------------------------------------------------------------ hedefler
    def _hedef_sec_dialog(self):
        from database.masraf_dagitim_service import MasrafDagitimService

        adaylar: dict[int, dict] = {}

        def yukle(arama):
            adaylar.clear()
            mevcut = {h["satir_id"] for h in self.hedefler}
            for h in MasrafDagitimService.hedef_satirlar(arama):
                if h["satir_id"] in mevcut:
                    continue
                adaylar[h["satir_id"]] = h
                yield h["satir_id"], (h["fatura_no"], _tarih(h["tarih"]), h["tedarikci"], h["urun_kodu"],
                                      h["urun_adi"], h["depo"], h["birim"], _sayi(h["ana_miktar"]),
                                      _para(h["alis_tutari"]), _sayi(h["birim_maliyet"]), _sayi(h["kalan"]))

        dlg = _SecimDialog(
            self, "Masraf yüklenecek alış satırlarını seç (Ctrl/Shift ile çoklu)",
            (("fatura", "Alış Faturası", 110, "w"), ("tarih", "Tarih", 85, "center"),
             ("ted", "Tedarikçi", 150, "w"), ("kod", "Stok Kodu", 90, "w"), ("ad", "Stok Adı", 180, "w"),
             ("depo", "Depo", 90, "w"), ("birim", "Birim", 60, "center"), ("miktar", "Ana Mik.", 70, "e"),
             ("alis", "Alış Tutarı", 95, "e"), ("maliyet", "Birim Maliyet", 90, "e"), ("kalan", "Stokta", 70, "e")),
            lambda a: list(yukle(a)), coklu=True, genislik=1200,
        )
        self.wait_window(dlg)
        if dlg.result:
            self.hedef_ekle([adaylar[i] for i in dlg.result if i in adaylar])

    def hedef_ekle(self, satirlar: list[dict]):
        mevcut = {h["satir_id"] for h in self.hedefler}
        for h in satirlar:
            if h["satir_id"] in mevcut:
                continue
            self.hedefler.append({**h, "olcu": h.get("agirlik"), "elle_tutar": None, "_sonuc": None})
        self._hedefleri_ciz()
        self._degisiklik()

    def _hedef_cikar(self):
        sec = self.hedef_tablo.selection()
        if not sec:
            return
        self.hedefler = [h for h in self.hedefler if str(h["satir_id"]) != sec[0]]
        self._hedefleri_ciz()
        self._degisiklik()

    def _yontem_kodu(self) -> str:
        return self._yontem_kodlari.get(self.yontem.get(), "TUTAR")

    def _olcu_duzenle(self, event):
        if self._salt_okunur():
            return
        iid = self.hedef_tablo.identify_row(event.y)
        if not iid:
            return
        yontem = self._yontem_kodu()
        if yontem not in ("AGIRLIK", "HACIM", "ELLE"):
            messagebox.showinfo("Ölçü", "Ölçü / elle tutar yalnızca ağırlık, hacim veya elle yönteminde girilir.",
                                parent=self)
            return
        h = next(x for x in self.hedefler if str(x["satir_id"]) == iid)
        alan = "elle_tutar" if yontem == "ELLE" else "olcu"
        baslik = {"ELLE": "Bu satıra dağıtılacak tutar (TL)", "AGIRLIK": "Birim ağırlık (kg / ana birim)",
                  "HACIM": "Birim hacim (m³ / ana birim)"}[yontem]
        metin = simpledialog.askstring("Değer", baslik, initialvalue=_sayi(h.get(alan)), parent=self)
        if metin is None:
            return
        self.hedef_deger_ayarla(int(iid), metin)

    def hedef_deger_ayarla(self, satir_id: int, metin: str):
        alan = "elle_tutar" if self._yontem_kodu() == "ELLE" else "olcu"
        h = next(x for x in self.hedefler if x["satir_id"] == satir_id)
        metin = (metin or "").strip().replace(",", ".")
        h[alan] = Decimal(metin) if metin else None
        self._degisiklik()
        self._hedefleri_ciz()

    def _hedefleri_ciz(self):
        yontem = self._yontem_kodu()
        sonuclar = {}
        if self.onizleme is not None:
            sonuclar = {s["alis_fatura_satiri_id"]: s for s in self.onizleme["satirlar"]}
        self.hedef_tablo.delete(*self.hedef_tablo.get_children())
        for i, h in enumerate(self.hedefler):
            s = sonuclar.get(h["satir_id"]) or h.get("_sonuc")
            olcu = h.get("elle_tutar") if yontem == "ELLE" else h.get("olcu")
            self.hedef_tablo.insert(
                "", "end", iid=str(h["satir_id"]), tags=("tek" if i % 2 == 0 else "cift",),
                values=(h["fatura_no"], h["urun_kodu"], h["urun_adi"], h["depo"], h["birim"], _sayi(h["ana_miktar"]),
                        _para(h["alis_tutari"]), _sayi(h["birim_maliyet"]), _sayi(olcu),
                        _para(s["pay"]) if s else "", _para(s["stok_payi"]) if s else "",
                        _para(s["smm_payi"]) if s else "", _sayi(s["yeni_birim_maliyet"]) if s else ""),
            )

    # ------------------------------------------------------------- işlemler
    def _veri(self) -> dict:
        if not self.kaynak:
            raise ValueError("Önce kaynak gider belgesini seçin.")
        return {
            "dagitim_tarihi": _tarih_oku(self.tarih.get()) or date.today(),
            "kaynak_id": self.kaynak["id"],
            "kaynak_satir_idler": sorted(self.secili_kaynak),
            "tutar": self.tutar.get(),
            "yontem": self._yontem_kodu(),
            "aciklama": self.aciklama.get(),
            "hedefler": [
                {"satir_id": h["satir_id"], "olcu": h.get("olcu"), "elle_tutar": h.get("elle_tutar")}
                for h in self.hedefler
            ],
        }

    def onizle(self) -> bool:
        from database.masraf_dagitim_service import MasrafDagitimService

        try:
            self.onizleme = MasrafDagitimService.onizle(self._veri(), self.dagitim_id)
        except (ValueError, PermissionError) as e:
            self.onizleme = None
            self._hedefleri_ciz()
            messagebox.showerror("Önizleme", str(e), parent=self)
            return False
        self._hedefleri_ciz()
        o = self.onizleme
        metin = self._ozet_metni(o)
        if o["engeller"]:
            metin += "\nONAY ENGELİ:\n- " + "\n- ".join(o["engeller"])
        if o["uyarilar"]:
            metin += "\nUyarı:\n- " + "\n- ".join(o["uyarilar"])
        self.ozet_lbl.configure(text=metin, fg="#B83B3B" if o["engeller"] else LACIVERT)
        return True

    def taslak_kaydet(self, *, sessiz: bool = False) -> bool:
        from database.masraf_dagitim_service import MasrafDagitimService

        if self.onizleme is None and not self.onizle():
            return False
        try:
            self.dagitim_id = MasrafDagitimService.taslak_kaydet(self._veri(), self.dagitim_id, self.row_version)
        except (ValueError, PermissionError) as e:
            messagebox.showerror("Taslak", str(e), parent=self)
            return False
        d = MasrafDagitimService.getir(self.dagitim_id)
        self.row_version = int(d["row_version"] or 1)
        self.no_lbl.configure(text=d["dagitim_no"])
        self._degisti = False
        self._durum_uygula()
        if not sessiz:
            messagebox.showinfo("Taslak", f"{d['dagitim_no']} taslak olarak kaydedildi. Stok ve muhasebe değişmedi.",
                                parent=self)
        return True

    def onayla(self) -> bool:
        from database.masraf_dagitim_service import MasrafDagitimService, ZatenIslendi

        if self.onizleme is None and not self.onizle():
            return False
        if self.onizleme["engeller"]:
            messagebox.showerror("Onay", "Onay engellendi:\n- " + "\n- ".join(self.onizleme["engeller"]), parent=self)
            return False
        o = self.onizleme
        if not messagebox.askyesno(
            "Onay",
            f"{_para(o['tutar'])} TL maliyete aktarılacak.\nStoka: {_para(o['stok_payi'])} TL, "
            f"SMM'ye: {_para(o['smm_payi'])} TL.\n\nOnaylıyor musunuz?",
            parent=self,
        ):
            return False
        if (self._degisti or not self.dagitim_id) and not self.taslak_kaydet(sessiz=True):
            return False
        try:
            sonuc = MasrafDagitimService.onayla(self.dagitim_id, self.row_version)
        except ZatenIslendi as e:
            messagebox.showinfo("Onay", str(e), parent=self)
            self._yukle(self.dagitim_id)
            self._durum_uygula()
            return False
        except (ValueError, PermissionError) as e:
            messagebox.showerror("Onay", str(e), parent=self)
            return False
        self._yukle(self.dagitim_id)
        self._durum_uygula()
        mesaj = f"{sonuc['dagitim_no']} onaylandı."
        if sonuc["uyarilar"]:
            mesaj += "\n\n" + "\n".join(sonuc["uyarilar"])
        messagebox.showinfo("Onay", mesaj, parent=self)
        return True

    def geri_al(self, neden: str | None = None) -> bool:
        from database.masraf_dagitim_service import MasrafDagitimService

        if not self.dagitim_id:
            return False
        if neden is None:
            neden = simpledialog.askstring("Geri Al", "Geri alma nedeni:", parent=self)
            if not neden:
                return False
        try:
            yapildi = MasrafDagitimService.geri_al(self.dagitim_id, neden)
        except (ValueError, PermissionError) as e:
            messagebox.showerror("Geri Al", str(e), parent=self)
            return False
        self._yukle(self.dagitim_id)
        self._durum_uygula()
        messagebox.showinfo(
            "Geri Al", "Dağıtım geri alındı; maliyet ve muhasebe etkisi ters kayıtla kaldırıldı." if yapildi
            else "Dağıtım zaten geri alınmış; ek işlem yapılmadı.", parent=self,
        )
        return yapildi

    def taslak_iptal(self):
        from database.masraf_dagitim_service import MasrafDagitimService

        if not self.dagitim_id or not messagebox.askyesno("İptal", "Taslak iptal edilsin mi?", parent=self):
            return
        try:
            MasrafDagitimService.iptal_et(self.dagitim_id, "Taslak iptal")
        except (ValueError, PermissionError) as e:
            messagebox.showerror("İptal", str(e), parent=self)
            return
        self._yukle(self.dagitim_id)
        self._durum_uygula()

    def _gecmis_goster(self):
        from database.masraf_dagitim_service import MasrafDagitimService

        if not self.dagitim_id:
            messagebox.showinfo("Geçmiş", "Kayıt henüz oluşturulmadı.", parent=self)
            return
        g = MasrafDagitimService.getir(self.dagitim_id)["gecmis"]
        satirlar = [f"{_tarih(x['tarih'])} {x['tarih']:%H:%M}  {x['islem']}  ({x['kullanici'] or '-'})"
                    + (f"\n    {x['detay']}" if x["detay"] else "") for x in g]
        messagebox.showinfo("İşlem geçmişi", "\n".join(satirlar) or "Kayıt yok.", parent=self)

    def kapat(self):
        if self._degisti and not self._salt_okunur():
            cevap = messagebox.askyesnocancel(
                "Kaydedilmemiş değişiklik", "Değişiklikler kaydedilmedi. Taslak olarak kaydedilsin mi?", parent=self
            )
            if cevap is None:
                return
            if cevap and not self.taslak_kaydet(sessiz=True):
                return
        self.destroy()


def bagli_dagitimlar_goster(parent, *, alis_fatura_id: int | None = None, kaynak_id: int | None = None) -> None:
    """Alış faturası / gider belgesi kartından bağlı masraf dağıtımlarını gösterir."""
    from database.masraf_dagitim_service import MasrafDagitimService

    if alis_fatura_id:
        kayitlar = MasrafDagitimService.fatura_baglantilari(alis_fatura_id)
        satirlar = [f"{k['dagitim_no']}  {_tarih(k['tarih'])}  {k['kaynak_no']}  pay {_para(k['pay'])} TL  "
                    f"({_durum_etiketi(k['durum'])})" for k in kayitlar]
        baslik = "Bu alış faturasına dağıtılan masraflar"
    else:
        bilgi = MasrafDagitimService.kaynak_baglantilari(int(kaynak_id or 0))
        satirlar = [f"{k['dagitim_no']}  {_tarih(k['tarih'])}  {_para(k['tutar'])} TL  ({_durum_etiketi(k['durum'])})"
                    for k in bilgi["dagitimlar"]]
        if bilgi.get("kalan") is not None:
            satirlar.append(f"\nDağıtılan: {_para(bilgi['dagitilan'])} TL   Kalan: {_para(bilgi['kalan'])} TL")
        baslik = "Bu gider belgesinden yapılan masraf dağıtımları"
    messagebox.showinfo(baslik, "\n".join(satirlar) or "Bağlı masraf dağıtımı yok.", parent=parent)
