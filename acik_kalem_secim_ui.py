"""Tahsilat / Ödeme Gir için açık kalem seçim penceresi.

Sonuç sözleşmesi (``AcikKalemSecimDialog.sonuc``):
  * None → kullanıcı seçim yapmadan kapattı: servis FIFO uygular.
  * {"dagitim": [(hareket_id, Decimal)], "fazla": "FIFO" | "AVANS"} → yalnız seçilen kalemler,
    dağıtım dışı kalan tutar açıkça seçilen yönteme gider.
"""

from __future__ import annotations

import tkinter as tk
from datetime import date
from decimal import Decimal
from tkinter import messagebox, ttk

from tutar_bicim import tr_tutar, tutar_coz

KURUS = Decimal("0.01")


def _tarih(t) -> str:
    return t.strftime("%d.%m.%Y") if isinstance(t, date) else ""


def acik_kalemler(cari_id: int, para_birimi: str = "TRY") -> list[dict]:
    from database.acik_kalem_service import AcikKalemService

    return AcikKalemService.secim_listesi_getir(int(cari_id), para_birimi=para_birimi)


def dagitim_ozeti(tutar: Decimal, dagitim: dict[int, Decimal]) -> tuple[Decimal, Decimal]:
    """(dağıtılan, dağıtılmayan) — canlı toplam satırı için."""
    dagitilan = sum(dagitim.values(), Decimal("0")).quantize(KURUS)
    return dagitilan, (Decimal(tutar) - dagitilan).quantize(KURUS)


class AcikKalemSecimDialog(tk.Toplevel):
    KOLONLAR = ("sec", "tarih", "tur", "evrak", "ilk", "kapanan", "kalan", "vade", "dagit")
    BASLIKLAR = (
        ("sec", "Seç", 44), ("tarih", "Tarih", 90), ("tur", "Tür", 150), ("evrak", "Evrak No", 150),
        ("ilk", "İlk Tutar", 110), ("kapanan", "Kapanan", 110), ("kalan", "Kalan", 110),
        ("vade", "Vade", 90), ("dagit", "Kapatılacak", 120),
    )

    def __init__(self, parent, cari_id: int, tutar, *, kalemler: list[dict] | None = None,
                 baslik: str = "Açık Kalem Seçimi", cari_adi: str = ""):
        super().__init__(parent)
        self.cari_id = int(cari_id)
        self.tutar = Decimal(str(tutar)).quantize(KURUS)
        self.kalemler = kalemler if kalemler is not None else acik_kalemler(self.cari_id)
        self._kalem_map = {int(k["hareket_id"]): k for k in self.kalemler}
        self.dagitim: dict[int, Decimal] = {}
        self.sonuc = None
        self.title(baslik)
        self.geometry("1080x560")
        self.minsize(760, 400)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.kapat)
        self.bind("<Escape>", lambda _e: self.kapat())
        self._arayuz(cari_adi)
        self._tabloyu_doldur()
        self._toplamlari_guncelle()

    def _arayuz(self, cari_adi):
        tk.Label(
            self, text=f"AÇIK KALEM SEÇİMİ{(' — ' + cari_adi) if cari_adi else ''}",
            font=("Segoe UI", 13, "bold"), fg="#0d2b52", anchor="w",
        ).pack(fill="x", padx=12, pady=(10, 0))
        ttk.Label(
            self,
            text=("Kapatılacak kalemleri seçin (çift tık / boşluk). Seçim yapmadan kapatırsanız tutar en eski "
                  "kalemden başlayarak (FIFO) dağıtılır."),
            foreground="#555555",
        ).pack(fill="x", padx=12, pady=(2, 6))
        cerceve = ttk.Frame(self)
        cerceve.pack(fill="both", expand=True, padx=12)
        self.tablo = ttk.Treeview(cerceve, columns=self.KOLONLAR, show="headings", selectmode="extended")
        for kolon, metin, genislik in self.BASLIKLAR:
            self.tablo.heading(kolon, text=metin)
            sayisal = kolon in ("ilk", "kapanan", "kalan", "dagit")
            self.tablo.column(kolon, width=genislik, anchor="e" if sayisal else ("center" if kolon == "sec" else "w"))
        kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=kaydir.set)
        self.tablo.pack(side="left", fill="both", expand=True)
        kaydir.pack(side="right", fill="y")
        self.tablo.tag_configure("secili", background="#e3f2fd")
        self.tablo.bind("<Double-1>", lambda _e: self.secimi_degistir())
        self.tablo.bind("<space>", lambda _e: (self.secimi_degistir(), "break")[1])
        self.tablo.bind("<<TreeviewSelect>>", lambda _e: self._tutar_alanini_doldur())

        satir = ttk.Frame(self)
        satir.pack(fill="x", padx=12, pady=6)
        ttk.Label(satir, text="Seçili kalem için kapatılacak tutar:").pack(side="left")
        self.kalem_tutar = ttk.Entry(satir, width=16, justify="right")
        self.kalem_tutar.pack(side="left", padx=6)
        self.kalem_tutar.bind("<Return>", lambda _e: self.kalem_tutari_uygula())
        ttk.Button(satir, text="Tutarı Uygula", command=self.kalem_tutari_uygula).pack(side="left")
        ttk.Button(satir, text="Seçimi Kaldır", command=self.secimi_kaldir).pack(side="left", padx=6)
        ttk.Button(satir, text="Tümünü Temizle", command=self.temizle).pack(side="left")

        self.toplam_lbl = tk.Label(self, font=("Segoe UI", 12, "bold"), anchor="w", justify="left")
        self.toplam_lbl.pack(fill="x", padx=12, pady=(4, 2))

        alt = ttk.Frame(self)
        alt.pack(fill="x", padx=12, pady=(4, 12))
        ttk.Button(alt, text="Seçimsiz Kapat (FIFO)", command=self.kapat).pack(side="right")
        ttk.Button(alt, text="Seçimi Uygula", command=self.uygula).pack(side="right", padx=8)

    def _satir_degerleri(self, k: dict) -> tuple:
        hid = int(k["hareket_id"])
        pay = self.dagitim.get(hid)
        return (
            "✓" if pay else "",
            _tarih(k["tarih"]), k["tur"], k["evrak_no"],
            tr_tutar(k["ilk_tutar"]), tr_tutar(k["kapanan"]), tr_tutar(k["kalan"]),
            _tarih(k.get("vade")),
            tr_tutar(pay) if pay else "",
        )

    def _tabloyu_doldur(self):
        for k in self.kalemler:
            self.tablo.insert("", "end", iid=str(k["hareket_id"]), values=self._satir_degerleri(k))

    def _satiri_yenile(self, hid: int):
        self.tablo.item(str(hid), values=self._satir_degerleri(self._kalem_map[hid]),
                        tags=("secili",) if hid in self.dagitim else ())

    def _toplamlari_guncelle(self):
        dagitilan, kalan = dagitim_ozeti(self.tutar, self.dagitim)
        renk = "#c62828" if kalan < 0 else ("#0d47a1" if kalan > 0 else "#2e7d32")
        self.toplam_lbl.configure(
            text=(f"İşlem tutarı: {tr_tutar(self.tutar)}   ·   Dağıtılan: {tr_tutar(dagitilan)}   ·   "
                  f"Dağıtılmayan: {tr_tutar(kalan)}   ·   Seçili kalem: {len(self.dagitim)}"),
            fg=renk,
        )

    def _secili_idler(self) -> list[int]:
        return [int(i) for i in self.tablo.selection()]

    def _tutar_alanini_doldur(self):
        secim = self._secili_idler()
        self.kalem_tutar.delete(0, "end")
        if len(secim) == 1 and secim[0] in self.dagitim:
            self.kalem_tutar.insert(0, tr_tutar(self.dagitim[secim[0]]))

    def secimi_degistir(self):
        for hid in self._secili_idler():
            if hid in self.dagitim:
                self.dagitim.pop(hid)
            else:
                _, kalan = dagitim_ozeti(self.tutar, self.dagitim)
                pay = min(Decimal(str(self._kalem_map[hid]["kalan"])), max(Decimal("0"), kalan))
                if pay <= 0:
                    messagebox.showinfo(
                        "Tutar dağıtıldı",
                        "İşlem tutarının tamamı dağıtıldı. Başka kalem seçmek için önce bir tutarı azaltın.",
                        parent=self,
                    )
                    break
                self.dagitim[hid] = pay.quantize(KURUS)
            self._satiri_yenile(hid)
        self._toplamlari_guncelle()
        self._tutar_alanini_doldur()

    def kalem_tutari_uygula(self):
        secim = self._secili_idler()
        if len(secim) != 1:
            messagebox.showinfo("Kalem tutarı", "Tutar girmek için tek bir kalem seçin.", parent=self)
            return
        hid = secim[0]
        try:
            pay = tutar_coz(self.kalem_tutar.get()).quantize(KURUS)
        except (ValueError, ArithmeticError):
            messagebox.showerror("Kalem tutarı", "Geçerli bir tutar girin.", parent=self)
            return
        kalan_kalem = Decimal(str(self._kalem_map[hid]["kalan"]))
        if pay < 0 or pay > kalan_kalem:
            messagebox.showerror(
                "Kalem tutarı", f"Tutar 0 ile kalemin kalanı ({tr_tutar(kalan_kalem)}) arasında olmalı.", parent=self
            )
            return
        diger = sum((v for k, v in self.dagitim.items() if k != hid), Decimal("0"))
        if diger + pay > self.tutar:
            messagebox.showerror(
                "Kalem tutarı",
                f"Toplam dağıtım işlem tutarını ({tr_tutar(self.tutar)}) aşamaz. "
                f"Bu kalem için en fazla {tr_tutar(self.tutar - diger)} girilebilir.",
                parent=self,
            )
            return
        if pay == 0:
            self.dagitim.pop(hid, None)
        else:
            self.dagitim[hid] = pay
        self._satiri_yenile(hid)
        self._toplamlari_guncelle()

    def secimi_kaldir(self):
        for hid in self._secili_idler():
            self.dagitim.pop(hid, None)
            self._satiri_yenile(hid)
        self._toplamlari_guncelle()

    def temizle(self):
        idler = list(self.dagitim)
        self.dagitim.clear()
        for hid in idler:
            self._satiri_yenile(hid)
        self._toplamlari_guncelle()

    def _fazla_yontemi_sor(self, kalan: Decimal) -> str | None:
        pencere = tk.Toplevel(self)
        pencere.title("Dağıtılmayan tutar")
        pencere.transient(self)
        pencere.grab_set()
        pencere.resizable(False, False)
        tk.Label(
            pencere,
            text=(f"Seçilen kalemlere dağıtılmayan {tr_tutar(kalan)} kaldı.\n"
                  "Bu tutar nasıl işlensin?"),
            font=("Segoe UI", 11, "bold"), justify="left",
        ).pack(padx=16, pady=(14, 8), anchor="w")
        secim = {"deger": None}

        def _sec(deger):
            secim["deger"] = deger
            pencere.destroy()

        butonlar = ttk.Frame(pencere)
        butonlar.pack(fill="x", padx=16, pady=(0, 14))
        ttk.Button(butonlar, text="Diğer açık kalemlere FIFO", command=lambda: _sec("FIFO")).pack(side="left")
        ttk.Button(butonlar, text="Avans (açık kredi) olarak bırak", command=lambda: _sec("AVANS")).pack(
            side="left", padx=8
        )
        ttk.Button(butonlar, text="Geri dön", command=pencere.destroy).pack(side="left")
        pencere.bind("<Escape>", lambda _e: pencere.destroy())
        self.wait_window(pencere)
        return secim["deger"]

    def uygula(self):
        if not self.dagitim:
            self.kapat()
            return
        dagitilan, kalan = dagitim_ozeti(self.tutar, self.dagitim)
        if kalan < 0:
            messagebox.showerror("Dağıtım", "Dağıtılan toplam işlem tutarını aşıyor.", parent=self)
            return
        fazla = "FIFO"
        if kalan > 0:
            fazla = self._fazla_yontemi_sor(kalan)
            if fazla is None:
                return
        sira = {int(k["hareket_id"]): i for i, k in enumerate(self.kalemler)}
        self.sonuc = {
            "dagitim": [(hid, self.dagitim[hid]) for hid in sorted(self.dagitim, key=lambda h: sira.get(h, 0))],
            "fazla": fazla,
        }
        self.destroy()

    def kapat(self):
        self.sonuc = None
        self.destroy()


def kapatma_plani_sor(parent, cari_id: int, tutar, *, cari_adi: str = "", baslik: str = "Açık Kalem Seçimi"):
    """Açık kalem varsa pencereyi açar. (acildi, sonuc) döner; sonuc None → FIFO."""
    tutar = Decimal(str(tutar or 0))
    if tutar <= 0 or not cari_id:
        return False, None
    kalemler = acik_kalemler(int(cari_id))
    if not kalemler:
        return False, None
    onceki_grab = parent.grab_current()
    pencere = AcikKalemSecimDialog(parent, int(cari_id), tutar, kalemler=kalemler, baslik=baslik, cari_adi=cari_adi)
    parent.wait_window(pencere)
    if onceki_grab is not None:
        try:
            if onceki_grab.winfo_exists():
                onceki_grab.grab_set()
        except tk.TclError:
            pass
    return True, pencere.sonuc
