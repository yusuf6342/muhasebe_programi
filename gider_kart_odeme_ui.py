"""Giderin kredi kartıyla ödenmesi: kart, tek çekim / taksit, ilk ekstre dönemi, faiz ve banka planı.

``KartOdemePaneli`` gider fişi ve ödeme takvimi sabit gider ödemesi pencerelerinde aynı işleyişle kullanılır.
``GiderKartOdemeleriDialog`` kayıtları listeler; hatalı kaydı düzeltir (``DuzeltmeDialog``) veya iptal eder,
bankanın gerçekleşmiş iadesini gider / faiz / ücret kırılımıyla kaydeder (``IadeDialog``).
"""

from __future__ import annotations

import tkinter as tk
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from tkinter import messagebox, simpledialog, ttk

from database import gider_kart_odeme_service as gk
from database.models.finans import KK_MAX_TAKSIT


def _para(t) -> str:
    return f"{Decimal(str(t or 0)):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def _tarih(t) -> str:
    return t.strftime("%d.%m.%Y") if isinstance(t, date) else ""


def tutar_oku(metin: str, alan: str = "Tutar") -> Decimal:
    m = (metin or "").strip().replace(" ", "").replace("TL", "")
    if not m:
        raise ValueError(f"{alan} girin.")
    if "," in m:
        m = m.replace(".", "").replace(",", ".")
    try:
        return Decimal(m)
    except InvalidOperation as hata:
        raise ValueError(f"{alan} geçersiz: {metin}") from hata


def _tarih_oku(metin: str, alan: str) -> date:
    try:
        return datetime.strptime((metin or "").strip(), "%d.%m.%Y").date()
    except ValueError as hata:
        raise ValueError(f"{alan} GG.AA.YYYY biçiminde olmalı.") from hata


class KartOdemePaneli(ttk.LabelFrame):
    """Kart ödeme alanları ve düzenlenebilir taksit planı. ``veri()`` servis argümanlarını döndürür."""

    KOLONLAR = (("no", "Taksit", 60, "center"), ("donem", "Ekstre dönemi", 170, "w"),
                ("kesim", "Hesap kesimi", 95, "center"), ("gun", "Gün", 85, "w"),
                ("son", "Son ödeme", 95, "center"), ("tutar", "Karta yansıyacak", 120, "e"))

    def __init__(self, parent, *, tutar_fn, tarih_fn, **kw):
        super().__init__(parent, text="Kredi kartıyla ödeme", padding=8, **kw)
        self.tutar_fn, self.tarih_fn = tutar_fn, tarih_fn
        self.istek_anahtari = uuid.uuid4().hex
        self._plan: list[dict] = []
        self._secenekler: list[dict] = []
        try:
            self._kartlar = gk.kartlar()
        except Exception as hata:  # noqa: BLE001 — kart listesi alınamazsa panel boş açılır, nedeni yazılır
            self._kartlar = []
            self._kart_hatasi = str(hata)
        self.columnconfigure(1, weight=1)

        ttk.Label(self, text="Kredi kartı *").grid(row=0, column=0, sticky="w", padx=4, pady=3)
        self.kart = ttk.Combobox(self, state="readonly", values=[k["ad"] for k in self._kartlar], width=44)
        self.kart.grid(row=0, column=1, columnspan=3, sticky="ew", padx=4, pady=3)
        self.kart.bind("<<ComboboxSelected>>", lambda _e: self._kart_degisti())
        self.kart_bilgi = ttk.Label(self, text="", foreground="#555", wraplength=620, justify="left")
        self.kart_bilgi.grid(row=1, column=0, columnspan=4, sticky="w", padx=4)

        ttk.Label(self, text="Ödeme şekli *").grid(row=2, column=0, sticky="w", padx=4, pady=3)
        sekil = ttk.Frame(self)
        sekil.grid(row=2, column=1, columnspan=3, sticky="w", padx=4, pady=3)
        self.sekil = tk.StringVar(value="TEK")
        ttk.Radiobutton(sekil, text="Tek çekim", value="TEK", variable=self.sekil,
                        command=self._sekil_degisti).pack(side="left")
        ttk.Radiobutton(sekil, text="Taksitli", value="TAKSIT", variable=self.sekil,
                        command=self._sekil_degisti).pack(side="left", padx=(12, 0))
        ttk.Label(sekil, text="Taksit sayısı").pack(side="left", padx=(16, 4))
        self.taksit = ttk.Spinbox(sekil, from_=2, to=KK_MAX_TAKSIT, width=5)
        self.taksit.set("3")
        self.taksit.pack(side="left")

        ttk.Label(self, text="İlk ekstre dönemi *").grid(row=3, column=0, sticky="w", padx=4, pady=3)
        self.ilk = ttk.Combobox(self, state="readonly", width=44)
        self.ilk.grid(row=3, column=1, columnspan=3, sticky="ew", padx=4, pady=3)

        ttk.Label(self, text="Faiz ve ücret *").grid(row=4, column=0, sticky="nw", padx=4, pady=3)
        faiz = ttk.Frame(self)
        faiz.grid(row=4, column=1, columnspan=3, sticky="w", padx=4, pady=3)
        self.faiz = tk.StringVar(value="")
        ttk.Radiobutton(faiz, text="Faizsiz (banka planı toplamı = gider tutarı)", value=gk.FAIZSIZ,
                        variable=self.faiz, command=self._faiz_degisti).pack(anchor="w")
        ttk.Radiobutton(faiz, text="Faiz / ücret var (bankanın gerçek tutarını girin)", value=gk.FAIZ_GIRILDI,
                        variable=self.faiz, command=self._faiz_degisti).pack(anchor="w")

        ttk.Label(self, text="Taksitlerin toplamı").grid(row=5, column=0, sticky="w", padx=4, pady=3)
        toplam = ttk.Frame(self)
        toplam.grid(row=5, column=1, columnspan=3, sticky="w", padx=4, pady=3)
        self.toplam = ttk.Entry(toplam, width=16)
        self.toplam.pack(side="left")
        ttk.Label(toplam, text="Ayrı banka ücreti").pack(side="left", padx=(16, 4))
        self.ucret = ttk.Entry(toplam, width=12)
        self.ucret.pack(side="left")
        ttk.Label(toplam, text="dönemi").pack(side="left", padx=(8, 4))
        self.ucret_donem = ttk.Combobox(toplam, state="readonly", width=24)
        self.ucret_donem.pack(side="left")

        self._duzeltme = False
        self._acik_donem = False
        self._radyolar = [w for w in sekil.winfo_children() if isinstance(w, ttk.Radiobutton)]
        dugmeler = ttk.Frame(self)
        dugmeler.grid(row=6, column=0, columnspan=4, sticky="ew", padx=4, pady=(6, 2))
        self._dugmeler = dugmeler
        self.btn_taslak = ttk.Button(dugmeler, text="Eşit taslak oluştur", command=self.taslak_olustur)
        self.btn_taslak.pack(side="left")
        self.ozet = ttk.Label(dugmeler, text="Plan yok — eşit taslak oluşturun veya banka planını girin.",
                              foreground="#8a5a00")
        self.ozet.pack(side="left", padx=10)

        tablo_cerceve = ttk.Frame(self)
        tablo_cerceve.grid(row=7, column=0, columnspan=4, sticky="nsew", padx=4, pady=2)
        self.rowconfigure(7, weight=1)
        self.tablo = ttk.Treeview(tablo_cerceve, columns=[k[0] for k in self.KOLONLAR], show="headings", height=6)
        for ad, baslik, gen, hiz in self.KOLONLAR:
            self.tablo.heading(ad, text=baslik)
            self.tablo.column(ad, width=gen, anchor=hiz, stretch=ad == "donem")
        kay = ttk.Scrollbar(tablo_cerceve, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=kay.set)
        self.tablo.pack(side="left", fill="both", expand=True)
        kay.pack(side="right", fill="y")
        self.tablo.bind("<Double-1>", self._satir_duzenle)
        ttk.Label(self, text="Banka planını kontrol edin: tutar veya kesim tarihini düzeltmek için satıra çift "
                             "tıklayın. Taksit toplamı karta yansıyacak tutarla kuruşu kuruşuna eşleşmelidir. "
                             "Kart ödemesinde kasa / banka çıkışı olmaz; çıkış ekstre ödenince oluşur.",
                  foreground="#555", wraplength=640, justify="left").grid(row=8, column=0, columnspan=4,
                                                                          sticky="w", padx=4, pady=(4, 0))
        if not self._kartlar:
            self.kart_bilgi.configure(text=getattr(self, "_kart_hatasi", "") or
                                      "Firmada geçerli kredi kartı yok. Finans → Bankalar → Kredi Kartı İşlemleri.",
                                      foreground="#b00020")
        else:
            self.kart.current(0)
            self._kart_degisti()
        self._sekil_degisti()

    # ------------------------------------------------------------------ alan değişimleri
    def _secili_kart(self) -> dict | None:
        i = self.kart.current()
        return self._kartlar[i] if 0 <= i < len(self._kartlar) else None

    def _kart_degisti(self) -> None:
        k = self._secili_kart()
        if not k:
            return
        son = (f"kesimden {k['kesimden_sonra_odeme_gun']} gün sonra" if k["kesimden_sonra_odeme_gun"] not in
               (None, "") else (f"her ayın {k['son_odeme_gunu']}. günü" if k["son_odeme_gunu"] else "tanımsız"))
        metin = (f"Hesap kesim günü: {k['kesim_gunu'] or 'tanımsız'} · Son ödeme: {son}"
                 + (f" · Limit {_para(k['limit'])}" if k["limit"] > 0 else " · Limit tanımsız"))
        if k["uyarilar"]:
            metin += "\n" + "\n".join(k["uyarilar"])
        self.kart_bilgi.configure(text=metin, foreground="#8a5a00" if k["uyarilar"] else "#555")
        self._secenekleri_yenile()
        self._plan_temizle()

    def _secenekleri_yenile(self) -> None:
        k = self._secili_kart()
        self._secenekler = []
        if k and k["kesim_tanimli"]:
            try:
                self._secenekler = gk.ilk_kesim_secenekleri(k["id"], self.tarih_fn())
            except ValueError:
                self._secenekler = []
        metinler = [f"{_tarih(s['kesim'])} {s['gun']} — dönem {_tarih(s['donem_baslangic'])}–{_tarih(s['kesim'])}"
                    f" · son ödeme {_tarih(s['son_odeme'])}" for s in self._secenekler]
        eski = self.ilk.current()
        self.ilk.configure(values=metinler)
        self.ucret_donem.configure(values=metinler)
        if metinler:
            self.ilk.current(eski if 0 <= eski < len(metinler) else 0)
            if self.ucret_donem.current() < 0:
                self.ucret_donem.current(0)

    def _sekil_degisti(self) -> None:
        self.taksit.configure(state="normal" if self.sekil.get() == "TAKSIT" else "disabled")
        self._plan_temizle()

    def _faiz_degisti(self) -> None:
        if self.faiz.get() == gk.FAIZSIZ:
            self.ucret.configure(state="normal")
            self.ucret.delete(0, "end")
            self.ucret.configure(state="disabled")
            self.toplam.configure(state="normal")
            self.toplam.delete(0, "end")
            try:
                self.toplam.insert(0, f"{self.tutar_fn():.2f}".replace(".", ","))
            except (ValueError, TypeError):
                pass
            self.toplam.configure(state="disabled")
        else:
            self.ucret.configure(state="disabled" if self._acik_donem else "normal")
            self.toplam.configure(state="normal")
        self._ozet_yaz()

    def _plan_temizle(self) -> None:
        self._plan = []
        self._tablo_yaz()

    # ------------------------------------------------------------------ plan
    def taslak_olustur(self) -> None:
        try:
            k = self._secili_kart()
            if not k:
                raise ValueError("Kredi kartı seçin.")
            self._secenekleri_yenile()
            if k["kesim_tanimli"] and self.ilk.current() < 0:
                raise ValueError("İlk ekstre dönemini seçin.")
            n = 1 if self.sekil.get() == "TEK" else int(self.taksit.get())
            if self.sekil.get() == "TAKSIT" and n < 2:
                raise ValueError("Taksitli ödemede taksit sayısı en az 2 olmalıdır.")
            if self.faiz.get() == gk.FAIZSIZ or not self.toplam.get().strip():
                toplam = self.tutar_fn()
            else:
                toplam = tutar_oku(self.toplam.get(), "Taksitlerin toplamı")
            if self.faiz.get() != gk.FAIZSIZ and not self.toplam.get().strip():
                self.toplam.insert(0, f"{toplam:.2f}".replace(".", ","))
            ilk = self._secenekler[self.ilk.current()]["kesim"] if k["kesim_tanimli"] else None
            self._plan = gk.esit_taslak(k["id"], ilk, n, toplam)
        except (ValueError, TypeError) as hata:
            messagebox.showwarning("Taksit planı", str(hata), parent=self.winfo_toplevel())
            return
        self._tablo_yaz()

    def _tablo_yaz(self) -> None:
        self.tablo.delete(*self.tablo.get_children())
        n = len(self._plan)
        for i, s in enumerate(self._plan):
            donem = f"{_tarih(s['donem_baslangic'])} – {_tarih(s['kesim'])}" + (" (ödendi)" if s.get("kapali") else "")
            self.tablo.insert("", "end", iid=str(i), values=(
                f"{i + 1} / {n}", donem, _tarih(s["kesim"]), s["gun"], _tarih(s["son_odeme"]), _para(s["tutar"])))
        self._ozet_yaz()

    # ------------------------------------------------------------------ kayıt düzeltmesi
    def duzeltme_yukle(self, *, kart_id: int, faiz_durumu: str, plan: list[dict], ucret: dict | None,
                       acik_donem: bool) -> None:
        """Mevcut kaydın kartı, faiz onayı, planı ve ayrı ücreti. Açık dönem düzeltmesinde kart, ücret ve ödenmiş
        dönemlerin kesimi kilitlidir; plan satır ekle / son açık satırı sil ile değişir."""
        from database.database import get_session
        from database.models.finans import KrediKartiTanimi

        sira = next((i for i, k in enumerate(self._kartlar) if k["id"] == int(kart_id)), None)
        if sira is None:
            raise ValueError("Kaydın kartı pasif veya TL kartı değil; önce kart tanımını kontrol edin.")
        self._duzeltme, self._acik_donem = True, acik_donem
        self.kart.current(sira)
        self._kart_degisti()
        self.faiz.set(faiz_durumu)
        self._faiz_degisti()
        if ucret and faiz_durumu == gk.FAIZ_GIRILDI:
            self.ucret.delete(0, "end")
            self.ucret.insert(0, f"{ucret['tutar']:.2f}".replace(".", ","))
            kesimler = [s["kesim"] for s in self._secenekler]
            if ucret["kesim"] in kesimler:
                self.ucret_donem.current(kesimler.index(ucret["kesim"]))
        with get_session() as ses:
            kart = ses.get(KrediKartiTanimi, int(kart_id))
            self._plan = [{**gk.donem_satiri(kart, r["kesim"]), "taksit_no": i, "tutar": r["tutar"],
                           "kapali": bool(r.get("kapali"))} for i, r in enumerate(plan, 1)]
        self.sekil.set("TEK" if len(self._plan) == 1 else "TAKSIT")
        self.taksit.configure(state="normal")
        self.taksit.set(str(max(len(self._plan), 2)))
        if faiz_durumu == gk.FAIZ_GIRILDI:
            self.toplam.delete(0, "end")
            self.toplam.insert(0, f"{sum((r['tutar'] for r in self._plan), Decimal('0')):.2f}".replace(".", ","))
        if acik_donem:
            self.kart.configure(state="disabled")
            self.ucret.configure(state="disabled")
            self.ucret_donem.configure(state="disabled")
            self.btn_taslak.configure(state="disabled")
            for r in self._radyolar:
                r.configure(state="disabled")
            self.taksit.configure(state="disabled")
            ttk.Button(self._dugmeler, text="Son açık satırı sil", command=self.son_satiri_sil).pack(side="right")
            ttk.Button(self._dugmeler, text="Dönem ekle", command=self.satir_ekle).pack(side="right", padx=6)
        self._tablo_yaz()

    def satir_ekle(self) -> None:
        from database.database import get_session
        from database.kredi_karti_ekstre_service import KrediKartiEkstreService as E
        from database.models.finans import KrediKartiTanimi

        ust = self.winfo_toplevel()
        k = self._secili_kart()
        if not k or not self._plan or self._plan[-1]["kesim"] is None:
            return
        yeni = simpledialog.askstring("Dönem ekle", "Sonraki ekstre dönemine yazılacak taksit tutarı:", parent=ust)
        if not yeni:
            return
        try:
            tutar = tutar_oku(yeni, "Taksit tutarı")
            if tutar <= 0 or tutar != tutar.quantize(Decimal("0.01")):
                raise ValueError("Taksit tutarı sıfırdan büyük ve en çok iki ondalık olmalıdır.")
        except ValueError as hata:
            messagebox.showwarning("Taksit planı", str(hata), parent=ust)
            return
        with get_session() as ses:
            kart = ses.get(KrediKartiTanimi, k["id"])
            kesim = E.kesim_ay_sonra(self._plan[-1]["kesim"], 1, kart)
            self._plan.append({**gk.donem_satiri(kart, kesim), "taksit_no": len(self._plan) + 1, "tutar": tutar,
                               "kapali": False})
        self._tablo_yaz()

    def son_satiri_sil(self) -> None:
        if not self._plan or self._plan[-1].get("kapali"):
            messagebox.showwarning("Taksit planı", "Ödenmiş dönemin satırı silinemez; kapanmış dönem yeniden "
                                   "yazılmaz.", parent=self.winfo_toplevel())
            return
        if len(self._plan) == 1:
            messagebox.showwarning("Taksit planı", "Planda en az bir satır kalmalıdır.", parent=self.winfo_toplevel())
            return
        self._plan.pop()
        self._tablo_yaz()

    def _beklenen(self) -> Decimal | None:
        try:
            if self.faiz.get() == gk.FAIZSIZ:
                return Decimal(str(self.tutar_fn()))
            if self.toplam.get().strip():
                return tutar_oku(self.toplam.get())
        except (ValueError, TypeError):
            return None
        return None

    def _ozet_yaz(self) -> None:
        if not self._plan:
            self.ozet.configure(text="Plan yok — eşit taslak oluşturun veya banka planını girin.",
                                foreground="#8a5a00")
            return
        toplam = sum((s["tutar"] for s in self._plan), Decimal("0"))
        beklenen = self._beklenen()
        if beklenen is None:
            self.ozet.configure(text=f"Plan toplamı {_para(toplam)}", foreground="#555")
        elif toplam == beklenen:
            self.ozet.configure(text=f"Plan toplamı {_para(toplam)} — eşleşiyor", foreground="#1b6e20")
        else:
            self.ozet.configure(text=f"Plan toplamı {_para(toplam)} ≠ {_para(beklenen)} (fark {_para(toplam - beklenen)})",
                                foreground="#b00020")

    def _satir_duzenle(self, event) -> None:
        iid = self.tablo.identify_row(event.y)
        if not iid:
            return
        i = int(iid)
        kolon = self.tablo.identify_column(event.x)
        ad = self.KOLONLAR[int(kolon.replace("#", "")) - 1][0] if kolon else "tutar"
        ust = self.winfo_toplevel()
        s = self._plan[i]
        try:
            if ad in ("kesim", "donem", "gun", "son"):
                if s.get("kapali"):
                    raise ValueError("Bu dönemin ekstresi ödenmiş; kesim tarihi değiştirilemez. Tutar hatalıysa "
                                     "tutarı düzeltin: fark ilk açık döneme ayrı düzeltme satırı olarak yazılır.")
                if s["kesim"] is None:
                    raise ValueError("Kartın hesap kesim günü tanımsız; kesim tarihi girilemez. Kesim günü kart "
                                     "tanımına girilince dönemler kendiliğinden belirlenir.")
                yeni = simpledialog.askstring("Ekstre kesimi", f"{i + 1}. taksitin hesap kesim tarihi (GG.AA.YYYY):",
                                              initialvalue=_tarih(s["kesim"]), parent=ust)
                if not yeni:
                    return
                k = self._secili_kart()
                yeni_kesim = _tarih_oku(yeni, "Kesim tarihi")
                from database.database import get_session
                from database.kredi_karti_ekstre_service import KrediKartiEkstreService as E
                from database.models.finans import KrediKartiTanimi

                with get_session() as ses:
                    kart = ses.get(KrediKartiTanimi, k["id"])
                    if not E.kesim_gecerli_mi(yeni_kesim, kart):
                        raise ValueError(f"{_tarih(yeni_kesim)} kartın hesap kesim günü değil "
                                         f"(kesim günü {kart.hesap_kesim_gunu}).")
                    s.update(gk.donem_satiri(kart, yeni_kesim))
            else:
                yeni = simpledialog.askstring("Taksit tutarı", f"{i + 1}. taksitin bankadaki tutarı:",
                                              initialvalue=f"{s['tutar']:.2f}".replace(".", ","), parent=ust)
                if not yeni:
                    return
                tutar = tutar_oku(yeni, "Taksit tutarı")
                if tutar <= 0 or tutar != tutar.quantize(Decimal("0.01")):
                    raise ValueError("Taksit tutarı sıfırdan büyük ve en çok iki ondalık olmalıdır.")
                s["tutar"] = tutar
        except ValueError as hata:
            messagebox.showwarning("Taksit planı", str(hata), parent=ust)
            return
        self._tablo_yaz()

    # ------------------------------------------------------------------ kayıt verisi
    def veri(self) -> dict:
        k = self._secili_kart()
        if not k:
            raise ValueError("Kredi kartı seçin.")
        if self.faiz.get() not in (gk.FAIZSIZ, gk.FAIZ_GIRILDI):
            raise ValueError("Faiz ve ücret durumunu seçin: banka planı faizsiz mi, faiz / ücret var mı? "
                             "Bilinmeyen faiz sıfır sayılmaz.")
        if not self._plan:
            raise ValueError("Taksit planı yok. 'Eşit taslak oluştur' ile taslak oluşturup banka planına göre "
                             "doğrulayın.")
        if not self._duzeltme and self.sekil.get() == "TEK" and len(self._plan) != 1:
            raise ValueError("Tek çekimde plan tek satır olmalı; taslağı yeniden oluşturun.")
        if not self._duzeltme and self.sekil.get() == "TAKSIT" and len(self._plan) < 2:
            raise ValueError("Taksitli ödemede en az iki taksit olmalı; taslağı yeniden oluşturun.")
        ucret = None
        if self.faiz.get() == gk.FAIZ_GIRILDI and self.ucret.get().strip():
            if k["kesim_tanimli"] and self.ucret_donem.current() < 0:
                raise ValueError("Ayrı banka ücretinin ekstre dönemini seçin.")
            ucret = {"tutar": tutar_oku(self.ucret.get(), "Banka ücreti"),
                     "kesim": self._secenekler[self.ucret_donem.current()]["kesim"] if k["kesim_tanimli"] else None}
        return {"istek_anahtari": self.istek_anahtari, "kredi_karti_id": k["id"], "faiz_durumu": self.faiz.get(),
                "plan": [{"kesim": s["kesim"], "tutar": s["tutar"]} for s in self._plan], "ucret": ucret}


def sonuc_metni(sonuc: dict) -> str:
    metin = (f"Gider fişi {sonuc['gider_fisi']} ve kart ödemesi {sonuc['kart_odeme']} kaydedildi.\n"
             f"Kapanan gider: {_para(sonuc['gider_tutari'])} · karta yansıyan: {_para(sonuc['kart_toplami'])}"
             f" ({'tek çekim' if sonuc['taksit_sayisi'] == 1 else str(sonuc['taksit_sayisi']) + ' taksit'})")
    if sonuc["finansman_farki"] > 0:
        metin += f"\nFinansman farkı {_para(sonuc['finansman_farki'])} bir kez kaydedildi."
    if sonuc.get("mevcut"):
        metin = "Bu ödeme daha önce kaydedilmişti; yeni kayıt oluşturulmadı.\n" + metin
    return metin


class DuzeltmeDialog(tk.Toplevel):
    """Hatalı tutar / kart / taksit bilgisinin kontrollü düzeltmesi. İade kaydı üretmez; eski kayıtlar silinmez,
    eski / yeni değer, neden, kullanıcı ve zaman düzeltme geçmişinde kalır."""

    def __init__(self, parent, gider_kart_odeme_id: int, *, sonra=None):
        super().__init__(parent)
        self.title("Kartla gider ödemesi — kayıt düzeltmesi")
        self.geometry("900x760")
        self.transient(parent)
        self.sonra = sonra
        self.anahtar = uuid.uuid4().hex
        self.bilgi = gk.duzeltme_bilgisi(gider_kart_odeme_id)
        b = self.bilgi
        cer = ttk.Frame(self, padding=10)
        cer.pack(fill="both", expand=True)
        cer.columnconfigure(1, weight=1)
        acik = b["tur"] == gk.DUZELTME_ACIK_DONEM
        aciklama = ("Hiçbir taksit ve ekstre ödemesi yok: eski kart kayıtları 'Düzeltildi' olur, düzeltme gününe ters "
                    "hareket ve düzeltilmiş kayıt yazılır. Kart, tutar ve plan değiştirilebilir."
                    if not acik else
                    "Ödenmiş ekstre dönemi var: ödenmiş dönemler yeniden yazılmaz, kart ve ayrı ücret değiştirilemez. "
                    "Açık dönemler ters satır + yeni planla değişir; ödenmiş dönem tutarı farkı ilk açık döneme ayrı "
                    "düzeltme satırı olarak yazılır.")
        ttk.Label(cer, text=(f"Gider fişi {b['gider_fisi']} · işlem {_tarih(b['islem_tarihi'])} · kapanan gider "
                             f"{_para(b['gider_tutari'])} · karta yansıyan {_para(b['kart_toplami'])}"),
                  font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(cer, text=aciklama + " Banka gerçekten iade ettiyse bu ekranı değil 'Banka iadesi'ni kullanın.",
                  foreground="#8a5a00", wraplength=860, justify="left").grid(row=1, column=0, columnspan=2,
                                                                             sticky="w", pady=(2, 6))
        ttk.Label(cer, text="Doğru gider tutarı *").grid(row=2, column=0, sticky="w", padx=4, pady=3)
        self.gider = ttk.Entry(cer, width=16)
        self.gider.insert(0, f"{b['gider_tutari']:.2f}".replace(".", ","))
        self.gider.grid(row=2, column=1, sticky="w", padx=4, pady=3)
        self.gider.bind("<FocusOut>", lambda _e: self.panel._faiz_degisti() if self.panel.faiz.get() == gk.FAIZSIZ
                        else None)
        ttk.Label(cer, text="Düzeltme nedeni *").grid(row=3, column=0, sticky="w", padx=4, pady=3)
        self.neden = ttk.Entry(cer, width=70)
        self.neden.grid(row=3, column=1, sticky="ew", padx=4, pady=3)
        self.panel = KartOdemePaneli(cer, tutar_fn=lambda: tutar_oku(self.gider.get(), "Gider tutarı"),
                                     tarih_fn=lambda: b["islem_tarihi"])
        self.panel.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=6)
        cer.rowconfigure(4, weight=1)
        try:
            self.panel.duzeltme_yukle(kart_id=b["kredi_karti_id"], faiz_durumu=b["faiz_durumu"], plan=b["plan"],
                                      ucret=b["ucret"], acik_donem=acik)
        except ValueError:
            self.destroy()
            raise
        gecmis = ttk.LabelFrame(cer, text="Düzeltme geçmişi", padding=6)
        gecmis.grid(row=5, column=0, columnspan=2, sticky="ew")
        self.gecmis = ttk.Treeview(gecmis, columns=("tarih", "tur", "neden", "kullanici", "eski", "yeni"),
                                   show="headings", height=3)
        for ad, baslik, gen in (("tarih", "Tarih", 85), ("tur", "Tür", 85), ("neden", "Neden", 230),
                                ("kullanici", "Kullanıcı", 110), ("eski", "Eski (gider / kart)", 150),
                                ("yeni", "Yeni (gider / kart)", 150)):
            self.gecmis.heading(ad, text=baslik)
            self.gecmis.column(ad, width=gen, stretch=ad == "neden")
        self.gecmis.pack(fill="x")
        for h in b["gecmis"]:
            self.gecmis.insert("", "end", values=(
                _tarih(h["tarih"]), "Açık dönem" if h["tur"] == gk.DUZELTME_ACIK_DONEM else "Tam", h["neden"],
                h["kullanici"] or "", f"{h['eski'].get('gider_tutari', '')} / {h['eski'].get('kart_toplami', '')}",
                f"{h['yeni'].get('gider_tutari', '')} / {h['yeni'].get('kart_toplami', '')}"))
        alt = ttk.Frame(self, padding=(10, 6))
        alt.pack(fill="x")
        ttk.Button(alt, text="Vazgeç", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Düzeltmeyi kaydet", command=self.kaydet).pack(side="right", padx=8)
        self.bind("<Escape>", lambda _e: self.destroy())

    def kaydet(self) -> None:
        try:
            veri = self.panel.veri()
            gider = tutar_oku(self.gider.get(), "Gider tutarı")
            neden = self.neden.get().strip()
            if not neden:
                raise ValueError("Düzeltme nedeni yazın.")
        except ValueError as hata:
            messagebox.showwarning("Kayıt düzeltmesi", str(hata), parent=self)
            return
        acik = self.bilgi["tur"] == gk.DUZELTME_ACIK_DONEM
        if not messagebox.askyesno("Kayıt düzeltmesi", "Düzeltme tek işlemde kaydedilir; eski kayıtlar silinmez, iade "
                                   "kaydı oluşmaz. Devam edilsin mi?", parent=self):
            return
        try:
            sonuc = gk.duzelt(self.bilgi["id"], istek_anahtari=self.anahtar, neden=neden, gider_tutari=gider,
                              plan=veri["plan"], faiz_durumu=veri["faiz_durumu"],
                              kredi_karti_id=veri["kredi_karti_id"],
                              ucret=gk.UCRET_AYNI if acik else veri["ucret"])
        except (ValueError, PermissionError) as hata:
            messagebox.showwarning("Kayıt düzeltmesi", str(hata), parent=self)
            return
        metin = (f"Düzeltme #{sonuc['duzeltme_id']} kaydedildi.\nGider {sonuc['eski']['gider_tutari']} → "
                 f"{sonuc['yeni']['gider_tutari']} TL · karta yansıyan {sonuc['eski']['kart_toplami']} → "
                 f"{sonuc['yeni']['kart_toplami']} TL")
        if sonuc["duzeltilen_kayitlar"]:
            metin += f"\nDüzeltildi olarak işaretlenen: {sonuc['duzeltilen_kayitlar']}"
        if sonuc["yeni_kayitlar"]:
            metin += f"\nYeni kart kayıtları: {sonuc['yeni_kayitlar']}"
        if sonuc.get("mevcut"):
            metin = "Bu düzeltme daha önce kaydedilmişti; yeni kayıt oluşmadı.\n" + metin
        messagebox.showinfo("Kayıt düzeltmesi", metin, parent=self)
        if self.sonra:
            self.sonra()
        self.destroy()


class IadeDialog(tk.Toplevel):
    """Bankanın gerçekleşmiş iadesi: gider (ana para), faiz ve ayrı ücret payı ayrı girilir."""

    def __init__(self, parent, kayit: dict, *, sonra=None):
        super().__init__(parent)
        self.title("Banka iadesi kaydet")
        self.transient(parent)
        self.kayit, self.sonra = kayit, sonra
        self.anahtar = uuid.uuid4().hex
        cer = ttk.Frame(self, padding=12)
        cer.pack(fill="both", expand=True)
        ttk.Label(cer, text="Yalnız bankanın gerçekleştirdiği iade kaydedilir. Hatalı tutar / kart / taksit girişi "
                            "için 'Düzelt' kullanın; banka iade etmediyse iade kaydı oluşturmayın.\nİade, iade "
                            "tarihinin ekstresine kart alacağı olarak yazılır; kapanmış ekstreler değişmez. Gider "
                            "kalanı yalnız gider (ana para) iadesi kadar açılır; iade edilmeyen faiz / ücret olduğu "
                            "gibi kalır.", wraplength=520, justify="left", foreground="#8a5a00").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        self.alanlar = {}
        satirlar = (("tarih", "İade tarihi (GG.AA.YYYY) *", date.today().strftime("%d.%m.%Y"), ""),
                    ("gider", "Gider (ana para) iadesi", "", f"en çok {_para(kayit['iade_edilebilir'])}"),
                    ("faiz", "Faiz iadesi", "", f"en çok {_para(kayit['faiz_iade_edilebilir'])}"),
                    ("ucret", "Ayrı ücret iadesi", "", f"en çok {_para(kayit['ucret_iade_edilebilir'])}"),
                    ("aciklama", "Açıklama / banka belge no", "", ""))
        for i, (ad, etiket, deger, ipucu) in enumerate(satirlar, 1):
            ttk.Label(cer, text=etiket).grid(row=i, column=0, sticky="w", padx=4, pady=3)
            e = ttk.Entry(cer, width=18 if ad != "aciklama" else 40)
            e.insert(0, deger)
            e.grid(row=i, column=1, sticky="w", padx=4, pady=3)
            ttk.Label(cer, text=ipucu, foreground="#555").grid(row=i, column=2, sticky="w")
            self.alanlar[ad] = e
        if kayit["ucret_iade_edilebilir"] <= 0:
            self.alanlar["ucret"].configure(state="disabled")
        if kayit["faiz_iade_edilebilir"] <= 0:
            self.alanlar["faiz"].configure(state="disabled")
        alt = ttk.Frame(self, padding=(12, 6))
        alt.pack(fill="x")
        ttk.Button(alt, text="Vazgeç", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="İadeyi kaydet", command=self.kaydet).pack(side="right", padx=8)
        self.bind("<Escape>", lambda _e: self.destroy())

    def _tutar(self, ad: str, alan: str) -> Decimal:
        m = self.alanlar[ad].get().strip()
        return tutar_oku(m, alan) if m else Decimal("0")

    def kaydet(self) -> None:
        try:
            tarih = _tarih_oku(self.alanlar["tarih"].get(), "İade tarihi")
            sonuc = gk.iade_kaydet(self.kayit["id"], tarih=tarih, tutar=self._tutar("gider", "Gider iadesi"),
                                   faiz_tutari=self._tutar("faiz", "Faiz iadesi"),
                                   ucret_tutari=self._tutar("ucret", "Ücret iadesi"),
                                   aciklama=self.alanlar["aciklama"].get().strip(), istek_anahtari=self.anahtar)
        except (ValueError, PermissionError) as hata:
            messagebox.showwarning("Banka iadesi", str(hata), parent=self)
            return
        messagebox.showinfo("Banka iadesi", (
            f"{sonuc['belge_no']} kaydedildi ({_para(sonuc['tutar'])}): gider {_para(sonuc['gider'])}, faiz "
            f"{_para(sonuc['faiz'])}, ücret {_para(sonuc['ucret'])}. Ekstre: {_tarih(sonuc['kesim']) or 'belirsiz'}."),
            parent=self)
        if self.sonra:
            self.sonra()
        self.destroy()


class GiderKartOdemeleriDialog(tk.Toplevel):
    """Kartla gider ödemeleri: kayıt düzeltmesi, hatalı kayıt iptali ve bankanın gerçek iadesi."""

    KOLONLAR = (("tarih", "İşlem", 85, "center"), ("kart", "Kart", 150, "w"), ("kaynak", "Kaynak gider", 230, "w"),
                ("gider", "Kapanan gider", 105, "e"), ("kart_toplam", "Karta yansıyan", 105, "e"),
                ("fark", "Finansman", 85, "e"), ("taksit", "Taksit", 55, "center"), ("ilk", "İlk kesim", 85, "center"),
                ("iade", "İade", 90, "e"), ("duzeltme", "Düzeltme", 65, "center"), ("durum", "Durum", 70, "w"))

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Kartla Gider Ödemeleri")
        self.geometry("1160x480")
        self.transient(parent)
        self._kayitlar: dict[str, dict] = {}
        cer = ttk.Frame(self, padding=10)
        cer.pack(fill="both", expand=True)
        self.tablo = ttk.Treeview(cer, columns=[k[0] for k in self.KOLONLAR], show="headings", selectmode="browse")
        for ad, baslik, gen, hiz in self.KOLONLAR:
            self.tablo.heading(ad, text=baslik)
            self.tablo.column(ad, width=gen, anchor=hiz, stretch=ad == "kaynak")
        kay = ttk.Scrollbar(cer, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=kay.set)
        self.tablo.pack(side="left", fill="both", expand=True)
        kay.pack(side="right", fill="y")
        self.tablo.bind("<<TreeviewSelect>>", lambda _e: self._secim())
        self.bilgi = ttk.Label(self, text="", foreground="#555", wraplength=1060, justify="left")
        self.bilgi.pack(fill="x", padx=10)
        alt = ttk.Frame(self, padding=(10, 6))
        alt.pack(fill="x")
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")
        self.btn_duzelt = ttk.Button(alt, text="Düzelt", command=self.duzelt)
        self.btn_duzelt.pack(side="left")
        self.btn_iade = ttk.Button(alt, text="Banka iadesi kaydet", command=self.iade)
        self.btn_iade.pack(side="left", padx=8)
        self.btn_iptal = ttk.Button(alt, text="Hatalı kaydı iptal et", command=self.iptal)
        self.btn_iptal.pack(side="left")
        ttk.Button(alt, text="Yenile", command=self.yenile).pack(side="left", padx=8)
        from database.access import yetki_var

        if not yetki_var(*gk.YAZMA_YETKISI):
            for b in (self.btn_duzelt, self.btn_iade, self.btn_iptal):
                b.configure(state="disabled")
        self.bind("<Escape>", lambda _e: self.destroy())
        self.yenile()

    def yenile(self) -> None:
        secili = self.tablo.selection()
        self.tablo.delete(*self.tablo.get_children())
        self._kayitlar = {}
        try:
            kayitlar = gk.liste()
        except Exception as hata:  # noqa: BLE001
            self.bilgi.configure(text=f"Liste alınamadı: {hata}", foreground="#b00020")
            return
        for k in kayitlar:
            iid = str(k["id"])
            self._kayitlar[iid] = k
            self.tablo.insert("", "end", iid=iid, values=(
                _tarih(k["islem_tarihi"]), k["kart"], k["kaynak"], _para(k["gider_tutari"]),
                _para(k["kart_toplami"]), _para(k["finansman_farki"]) if k["finansman_farki"] else "—",
                k["taksit_sayisi"], _tarih(k["ilk_kesim"]), _para(k["iade_toplami"]) if k["iade_toplami"] else "—",
                k["duzeltme_sayisi"] or "—", "İptal" if k["durum"] == "IPTAL" else "Açık"))
        if secili and secili[0] in self._kayitlar:
            self.tablo.selection_set(secili[0])
        self._secim()

    def _secili(self) -> dict | None:
        s = self.tablo.selection()
        return self._kayitlar.get(s[0]) if s else None

    def _secim(self) -> None:
        k = self._secili()
        if not k:
            self.bilgi.configure(text="Bir kayıt seçin.", foreground="#555")
            return
        parca = [f"Gider fişi {k['gider_fisi']} · kart ödemesi {k['kart_odeme']}"]
        if k["ucret_kart_odeme"]:
            parca.append(f"ücret {k['ucret_kart_odeme']}")
        if k["iadeler"]:
            ik = k["iade_kirilimi"]
            parca.append("iadeler " + ", ".join(k["iadeler"]) + f" (gider {_para(ik['gider'])}, faiz "
                         f"{_para(ik['faiz'])}, ücret {_para(ik['ucret'])})")
        if k["durum"] == "IPTAL":
            parca.append(f"iptal nedeni: {k['iptal_nedeni']}")
        else:
            if k["kilit"]:
                parca.append(f"Program iptali yapılamaz: {k['kilit']}")
            if k["duzeltme_engeli"]:
                parca.append(f"Düzeltme yapılamaz: {k['duzeltme_engeli']}")
            elif k["duzeltme_turu"] == gk.DUZELTME_ACIK_DONEM:
                parca.append("Düzeltme yalnız açık dönemlerde (ödenmiş ekstreler korunur)")
        self.bilgi.configure(text=" · ".join(parca), foreground="#555")

    def duzelt(self) -> None:
        k = self._secili()
        if not k:
            return
        if k["duzeltme_engeli"]:
            messagebox.showwarning("Kayıt düzeltmesi", k["duzeltme_engeli"], parent=self)
            return
        try:
            DuzeltmeDialog(self, k["id"], sonra=self.yenile)
        except ValueError as hata:
            messagebox.showwarning("Kayıt düzeltmesi", str(hata), parent=self)

    def iptal(self) -> None:
        k = self._secili()
        if not k:
            return
        if k["kilit"]:
            messagebox.showwarning("İptal", k["kilit"], parent=self)
            return
        neden = simpledialog.askstring("Hatalı kaydı iptal et",
                                       "Gider kapanışı ve kart borcu birlikte geri alınır; kayıtlar silinmez.\n"
                                       "İptal nedeni:", parent=self)
        if not neden:
            return
        try:
            gk.iptal(k["id"], neden)
        except (ValueError, PermissionError) as hata:
            messagebox.showwarning("İptal", str(hata), parent=self)
            return
        self.yenile()

    def iade(self) -> None:
        k = self._secili()
        if not k or k["durum"] != "AÇIK":
            messagebox.showinfo("Banka iadesi", "Açık bir kayıt seçin.", parent=self)
            return
        IadeDialog(self, k, sonra=self.yenile)
