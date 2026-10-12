"""Özet Tablolar → Dönen Sermaye Bilançosu.

Hesap ``database.donen_sermaye_service`` içindedir; bu modül yalnız gösterir. Ekran, ayrıntı ve dışa aktarma
aynı hesap sonucunu kullanır. Başarıyla commit edilen her ön muhasebe işleminden sonra açık rapor seçili tarih
ve maliyet yöntemiyle kendiliğinden yeniden hesaplanır.
"""

from __future__ import annotations

import csv
import tkinter as tk
from datetime import date, datetime
from tkinter import filedialog, messagebox, ttk

from database import donen_sermaye_service as ds

YOKLAMA_MS = 1000
BASLIK = "Dönen Sermaye Bilançosu"
NEGATIF_RENK = "#B42318"


def _tarih_tr(t) -> str:
    return t.strftime("%d.%m.%Y") if isinstance(t, date) else ""


def tarih_oku(metin: str) -> date:
    metin = (metin or "").strip()
    for bicim in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(metin, bicim).date()
        except ValueError:
            continue
    raise ValueError("Tarih GG.AA.YYYY biçiminde olmalı.")


def _firma():
    from database.session_manager import oturum

    return getattr(oturum, "company_id", None)


def bilanco_sayfasi_goster(app):
    from ozet_tablolar_ui import _ozet_tablolar_menu_isaretle

    app._icerigi_temizle()
    _ozet_tablolar_menu_isaretle(app)
    panel = DonenSermayePaneli(app.icerik, app)
    panel.pack(fill="both", expand=True)
    app._donen_sermaye_paneli = panel
    return panel


class DonenSermayePaneli(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._istek = 0
        self._calisan = False
        self._bekleyen = False
        self._sonuc: dict | None = None
        self._sayac = ds.degisim_sayaci()
        self._yontemler = self._yontem_listesi()
        self._stil()
        self._ust()
        self._govde()
        self.after(50, self.yenile)
        self.after(YOKLAMA_MS, self._yokla)

    # --- kurulum ---
    @staticmethod
    def _yontem_listesi() -> dict[str, str]:
        from database.stok_rapor_service import degerleme_yontemleri

        return {ad: kod for kod, ad in degerleme_yontemleri()}

    def _stil(self):
        stil = ttk.Style(self)
        stil.configure("DonenSermaye.Treeview", font=("Segoe UI", 9), rowheight=23)
        stil.configure("DonenSermaye.Treeview.Heading", font=("Segoe UI", 9, "bold"))

    def _ust(self):
        from ozet_tablolar_ui import ozet_tablolar_menusu_goster

        ust = ttk.Frame(self)
        ust.pack(fill="x")
        ttk.Label(ust, text=BASLIK, style="Baslik.TLabel").pack(side="left")
        ttk.Button(ust, text="← Özet Tablolar Menüsü",
                   command=lambda: ozet_tablolar_menusu_goster(self.app)).pack(side="right")
        ttk.Label(self, wraplength=1100, justify="left", text=(
            "Seçilen tarih sonu, yalnız ön muhasebe kayıtlarından (muhasebeleşme şartı yok). Kapsam: 1 ve 3 "
            "gruplarına karşılık gelen varlık ve borçlar. Şirketin alacağı artı, borcu eksi; kasa / banka / KMH / "
            "POS hep aktifte, kredi ve kredi kartı hep pasifte. Dönen sermaye = aktif genel toplamı + pasif genel "
            "toplamı; özkaynakla denkleştirme yapılmaz.")).pack(anchor="w", pady=(6, 4))

        filtre = ttk.Frame(self)
        filtre.pack(fill="x", pady=(2, 4))
        ttk.Label(filtre, text="Rapor tarihi:").pack(side="left")
        self.tarih_e = ttk.Entry(filtre, width=11)
        self.tarih_e.insert(0, _tarih_tr(date.today()))
        self.tarih_e.pack(side="left", padx=(4, 0))
        self.tarih_e.bind("<Return>", lambda _e: self._tarih_degisti())
        try:
            from ui_takvim import takvim_butonu

            takvim_butonu(filtre, self.tarih_e, on_select=lambda *_a: self._tarih_degisti(), width=7)
        except Exception:  # noqa: BLE001 — takvim yoksa elle giriş yeterli
            pass
        ttk.Label(filtre, text="Stok maliyet yöntemi:").pack(side="left", padx=(14, 4))
        self.yontem_cb = ttk.Combobox(filtre, values=list(self._yontemler), state="readonly", width=44)
        self.yontem_cb.set(next(iter(self._yontemler)))
        self.yontem_cb.pack(side="left")
        self.yontem_cb.bind("<<ComboboxSelected>>", lambda _e: self.yenile())
        self.yenile_btn = ttk.Button(filtre, text="Yenile", command=self.yenile)
        self.yenile_btn.pack(side="right")
        ttk.Button(filtre, text="Dışa aktar (CSV)", command=self._disa_aktar).pack(side="right", padx=(0, 6))
        ttk.Button(filtre, text="Demirbaş grupları", command=self._demirbas).pack(side="right", padx=(0, 6))

        durum = ttk.Frame(self)
        durum.pack(fill="x")
        self.durum_lbl = ttk.Label(durum, text="Hazırlanıyor…", foreground="#5B6573")
        self.durum_lbl.pack(side="left")
        self.bayat_lbl = ttk.Label(durum, text="", foreground="#B54708", font=("Segoe UI", 9, "bold"))
        self.bayat_lbl.pack(side="left", padx=10)

    def _govde(self):
        sonuc = tk.Frame(self, bg="#0F2A4A")
        sonuc.pack(side="bottom", fill="x", pady=(6, 0))
        self.toplam_lbl = tk.Label(sonuc, text="", bg="#0F2A4A", fg="white", font=("Segoe UI", 10), anchor="w")
        self.toplam_lbl.pack(side="left", padx=12, pady=8)
        self.sonuc_lbl = tk.Label(sonuc, text="", bg="#0F2A4A", fg="#FFD25A", font=("Segoe UI", 13, "bold"))
        self.sonuc_lbl.pack(side="right", padx=12, pady=8)

        not_f = ttk.Frame(self)
        not_f.pack(side="bottom", fill="x", pady=(6, 0))
        self.notlar = tk.Text(not_f, height=8, wrap="word", font=("Segoe UI", 9), relief="flat", bg="#F7F9FB")
        not_sb = ttk.Scrollbar(not_f, orient="vertical", command=self.notlar.yview)
        self.notlar.configure(yscrollcommand=not_sb.set, state="disabled")
        self.notlar.tag_configure("eksik", foreground=NEGATIF_RENK, font=("Segoe UI", 9, "bold"))
        self.notlar.tag_configure("not", foreground="#344054")
        not_sb.pack(side="right", fill="y")
        self.notlar.pack(side="left", fill="x", expand=True)

        govde = ttk.Frame(self)
        govde.pack(fill="both", expand=True, pady=(4, 0))
        govde.columnconfigure(0, weight=1, uniform="ds")
        govde.columnconfigure(1, weight=1, uniform="ds")
        govde.rowconfigure(0, weight=1)
        self.tablolar = {}
        for i, (taraf, baslik) in enumerate(((ds.AKTIF, "AKTİF"), (ds.PASIF, "PASİF"))):
            cerceve, tablo = self._tablo(govde, baslik)
            cerceve.grid(row=0, column=i, sticky="nsew", padx=(0, 6) if i == 0 else (6, 0))
            self.tablolar[taraf] = tablo

    def _tablo(self, parent, baslik):
        cerceve = ttk.Frame(parent)
        tablo = ttk.Treeview(cerceve, columns=("kalem", "tutar"), show="headings", selectmode="browse",
                             style="DonenSermaye.Treeview")
        tablo.heading("kalem", text=baslik, anchor="w")
        tablo.heading("tutar", text="Tutar TL", anchor="e")
        tablo.column("kalem", width=360, minwidth=180, anchor="w", stretch=True)
        tablo.column("tutar", width=140, minwidth=110, anchor="e", stretch=False)
        sb = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
        tablo.configure(yscrollcommand=sb.set)
        tablo.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        tablo.tag_configure(ds.BASLIK, font=("Segoe UI", 9, "bold"), background="#D9E2EC")
        tablo.tag_configure(ds.ALT_BASLIK, font=("Segoe UI", 9, "bold italic"), background="#EEF2F6")
        tablo.tag_configure(ds.ARA_TOPLAM, font=("Segoe UI", 9, "bold"), background="#FFF6D6")
        tablo.tag_configure(ds.ALT_TOPLAM, font=("Segoe UI", 9, "italic"), background="#F7F9FB")
        tablo.tag_configure("genel", font=("Segoe UI", 10, "bold"), background="#C5D4E8")
        tablo.tag_configure("negatif", foreground=NEGATIF_RENK)
        tablo.bind("<Double-1>", lambda e, t=tablo: self._ayrinti(t))
        return cerceve, tablo

    # --- yenileme ---
    def _parametreler(self) -> tuple[date, str]:
        d = tarih_oku(self.tarih_e.get())
        return d, self._yontemler.get(self.yontem_cb.get()) or next(iter(self._yontemler.values()))

    def _tarih_degisti(self):
        try:
            d = tarih_oku(self.tarih_e.get())
        except ValueError as hata:
            messagebox.showwarning("Rapor tarihi", str(hata), parent=self)
            return
        if d > date.today():
            messagebox.showwarning("Rapor tarihi", "Rapor tarihi bugünden sonra olamaz.", parent=self)
            self.tarih_e.delete(0, "end")
            self.tarih_e.insert(0, _tarih_tr(date.today()))
        self.yenile()

    def yenile(self):
        try:
            d, yontem = self._parametreler()
        except ValueError as hata:
            messagebox.showwarning("Rapor tarihi", str(hata), parent=self)
            return
        d = min(d, date.today())
        if self._calisan:
            self._bekleyen = True
            return
        self._istek += 1
        jeton = (self._istek, _firma(), d, yontem)
        self._calisan = True
        self._bekleyen = False
        self.yenile_btn.configure(state="disabled", text="Hesaplanıyor…")
        self.durum_lbl.configure(text="Hesaplanıyor…")
        from ui_bg import arka_planda

        arka_planda(self, lambda: ds.hesapla(d, yontem),
                    on_ok=lambda s, j=jeton: self._geldi(j, s),
                    on_err=lambda e, j=jeton: self._hata(j, e))

    def _bitti(self, jeton) -> bool:
        if not self.winfo_exists():
            return False
        self._calisan = False
        self.yenile_btn.configure(state="normal", text="Yenile")
        guncel = jeton[0] == self._istek and jeton[1] == _firma()
        if self._bekleyen or not guncel:
            self.after(10, self.yenile)
            return False
        try:
            d, yontem = self._parametreler()
        except ValueError:
            return True
        if (min(d, date.today()), yontem) != jeton[2:]:
            self.after(10, self.yenile)
            return False
        return True

    def _hata(self, jeton, hata):
        if not self._bitti(jeton):
            return
        self.bayat_lbl.configure(text="Güncel değil")
        self.durum_lbl.configure(text=f"Yenileme başarısız: {hata}")

    def _geldi(self, jeton, sonuc):
        if not self._bitti(jeton):
            return
        self._sonuc = sonuc
        self._sayac = sonuc["sayac"]
        self.bayat_lbl.configure(text="")
        self.durum_lbl.configure(text=f"{_tarih_tr(sonuc['tarih'])} sonu · son yenileme "
                                      f"{sonuc['zaman']:%H:%M:%S} · {sonuc['sure_ms'] / 1000:.1f} sn")
        self._ciz(sonuc)
        if ds.degisim_sayaci() != self._sayac:
            self.after(10, self.yenile)

    def _yokla(self):
        if not self.winfo_exists():
            return
        try:
            if not self._calisan and self._sonuc is not None and ds.degisim_sayaci() != self._sayac:
                self.bayat_lbl.configure(text="Güncelleniyor…")
                self.yenile()
        finally:
            self.after(YOKLAMA_MS, self._yokla)

    # --- çizim ---
    def _ciz(self, sonuc):
        for taraf, toplam_ad, toplam in ((ds.AKTIF, "AKTİF GENEL TOPLAMI", sonuc["aktif_toplam"]),
                                         (ds.PASIF, "PASİF GENEL TOPLAMI", sonuc["pasif_toplam"])):
            tablo = self.tablolar[taraf]
            tablo.delete(*tablo.get_children())
            tablo._satirlar = {}
            for r in sonuc[taraf]:
                girinti = {ds.BASLIK: "", ds.ALT_BASLIK: "   ", ds.KALEM: "      ", ds.ALT_TOPLAM: "   ",
                           ds.ARA_TOPLAM: ""}[r["seviye"]]
                tutar = "" if r["tutar"] is None else ds.tutar_metni(r["tutar"])
                etiketler = [r["seviye"]]
                if r["tutar"] is not None and r["tutar"] < 0:
                    etiketler.append("negatif")
                iid = tablo.insert("", "end", values=(girinti + r["etiket"], tutar), tags=tuple(etiketler))
                tablo._satirlar[iid] = r
            etiketler = ["genel"] + (["negatif"] if toplam < 0 else [])
            tablo.insert("", "end", values=(toplam_ad, ds.tutar_metni(toplam)), tags=tuple(etiketler))
        a, p, s = sonuc["aktif_toplam"], sonuc["pasif_toplam"], sonuc["donen_sermaye"]
        self.toplam_lbl.configure(text=f"Aktif Genel Toplamı: {ds.tutar_metni(a)} TL     "
                                       f"Pasif Genel Toplamı: {ds.tutar_metni(p)} TL")
        self.sonuc_lbl.configure(text=f"Dönen Sermaye: {ds.tutar_metni(a)} + ({ds.tutar_metni(p)}) = "
                                      f"{ds.tutar_metni(s)} TL")
        self.notlar.configure(state="normal")
        self.notlar.delete("1.0", "end")
        if sonuc["eksikler"]:
            self.notlar.insert("end", "Eksik / incelenecek kayıtlar — sonuç bu kalemler çözülmeden tamamlanmış "
                                      "sayılmaz:\n", "eksik")
            for m in sonuc["eksikler"]:
                self.notlar.insert("end", f"• {m}\n", "eksik")
        for m in sonuc["notlar"]:
            self.notlar.insert("end", f"• {m}\n", "not")
        self.notlar.configure(state="disabled")

    def _ayrinti(self, tablo):
        sec = tablo.selection()
        r = getattr(tablo, "_satirlar", {}).get(sec[0]) if sec else None
        if not r or r["seviye"] != ds.KALEM or not r.get("ayrinti"):
            return
        pen = tk.Toplevel(self)
        pen.title(f"{r['etiket']} — ayrıntı")
        pen.geometry("620x420")
        pen.transient(self.winfo_toplevel())
        ttk.Label(pen, text=f"{r['etiket']}: {ds.tutar_metni(r['tutar'])} TL "
                            f"({_tarih_tr(self._sonuc['tarih'])} sonu)",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=10, pady=(10, 4))
        f = ttk.Frame(pen)
        f.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        t = ttk.Treeview(f, columns=("ad", "tutar"), show="headings")
        t.heading("ad", text="Kalem", anchor="w")
        t.heading("tutar", text="Tutar TL", anchor="e")
        t.column("ad", width=420, anchor="w")
        t.column("tutar", width=140, anchor="e")
        sb = ttk.Scrollbar(f, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        t.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for ad, tutar in r["ayrinti"]:
            t.insert("", "end", values=(ad, ds.tutar_metni(tutar)))

    # --- dışa aktarma / demirbaş ---
    def _disa_aktar(self):
        if not self._sonuc:
            return
        yol = filedialog.asksaveasfilename(
            parent=self, defaultextension=".csv", filetypes=[("CSV", "*.csv")],
            initialfile=f"donen_sermaye_{self._sonuc['tarih']:%Y%m%d}.csv")
        if not yol:
            return
        with open(yol, "w", newline="", encoding="utf-8-sig") as f:
            yazici = csv.writer(f, delimiter=";")
            yazici.writerows(ds.disa_aktarim_satirlari(self._sonuc))
            yazici.writerow([])
            for m in self._sonuc["eksikler"]:
                yazici.writerow(["Eksik", "", m, ""])
            for m in self._sonuc["notlar"]:
                yazici.writerow(["Not", "", m, ""])
        messagebox.showinfo(BASLIK, f"Kaydedildi:\n{yol}", parent=self)

    def _demirbas(self):
        try:
            DemirbasGruplariDialog(self, on_kaydet=self.yenile)
        except PermissionError as hata:
            messagebox.showwarning("Yetki", str(hata), parent=self)


class DemirbasGruplariDialog(tk.Toplevel):
    """Stok gruplarından demirbaş olanları işaretleme (alt grupları da hariç tutulur)."""

    def __init__(self, parent, on_kaydet=None):
        super().__init__(parent)
        self.title("Demirbaş stok grupları")
        self.geometry("720x560")
        self.transient(parent.winfo_toplevel())
        self._on_kaydet = on_kaydet
        ttk.Label(self, wraplength=680, justify="left", text=(
            "İşaretlenen grup ve tüm alt grupları ile bunlara bağlı kartlar Dönen Sermaye Bilançosu stok "
            "toplamından hariç tutulur. Kart türü 'Demirbaş' olan kartlar her durumda hariçtir. Stok kayıtları "
            "değişmez. İşaretlemek / kaldırmak için satıra çift tıklayın veya boşluk tuşuna basın.")).pack(
            anchor="w", padx=10, pady=(10, 6))
        f = ttk.Frame(self)
        f.pack(fill="both", expand=True, padx=10)
        self.agac = ttk.Treeview(f, columns=("isaret", "kod", "kart"), show="tree headings", selectmode="browse")
        self.agac.heading("#0", text="Grup", anchor="w")
        self.agac.heading("isaret", text="Demirbaş")
        self.agac.heading("kod", text="Kod", anchor="w")
        self.agac.heading("kart", text="Kart", anchor="e")
        self.agac.column("#0", width=330)
        self.agac.column("isaret", width=80, anchor="center")
        self.agac.column("kod", width=170, anchor="w")
        self.agac.column("kart", width=60, anchor="e")
        sb = ttk.Scrollbar(f, orient="vertical", command=self.agac.yview)
        self.agac.configure(yscrollcommand=sb.set)
        self.agac.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.agac.bind("<Double-1>", lambda _e: self._degistir())
        self.agac.bind("<space>", lambda _e: self._degistir())
        alt = ttk.Frame(self)
        alt.pack(fill="x", padx=10, pady=10)
        ttk.Button(alt, text="Kaydet", command=self._kaydet).pack(side="right")
        ttk.Button(alt, text="Vazgeç", command=self.destroy).pack(side="right", padx=(0, 6))
        self._isaretli: set[int] = set()
        gruplar = ds.stok_gruplari()
        idler = {g["id"] for g in gruplar}
        for g in sorted(gruplar, key=lambda x: x["seviye"]):
            ust = str(g["parent_id"]) if g["parent_id"] in idler else ""
            self.agac.insert(ust, "end", iid=str(g["id"]), text=f"{g['ad']}  (#{g['id']})",
                             values=("✓" if g["demirbas"] else "", g["kod"], g["kart"]), open=True)
            if g["demirbas"]:
                self._isaretli.add(g["id"])

    def _degistir(self):
        sec = self.agac.selection()
        if not sec:
            return
        gid = int(sec[0])
        if gid in self._isaretli:
            self._isaretli.discard(gid)
        else:
            self._isaretli.add(gid)
        self.agac.set(sec[0], "isaret", "✓" if gid in self._isaretli else "")

    def _kaydet(self):
        try:
            ds.demirbas_gruplarini_kaydet(self._isaretli)
        except (PermissionError, ValueError) as hata:
            messagebox.showwarning("Demirbaş grupları", str(hata), parent=self)
            return
        self.destroy()
        if self._on_kaydet:
            self._on_kaydet()
