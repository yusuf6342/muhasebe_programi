"""Firma kredi kartı çalışma ekranı — özet, harcama/taksit, ödeme, ekstre, ayarlar."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from database.finans_service import FinansService
from database.models.finans import KK_STANDART_MAX_TAKSIT


def _para(tutar, pb: str = "TRY") -> str:
    return (
        f"{Decimal(str(tutar or 0)):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        + (f" {pb}" if pb else "")
    )


def _tarih(d) -> str:
    if isinstance(d, date):
        return d.strftime("%d.%m.%Y")
    return str(d or "—")


def _durum_metin(kod: str, *, bugun: date | None = None, vade=None, odenen=None, tutar=None) -> str:
    k = (kod or "").upper()
    odenen_d = Decimal(str(odenen or 0))
    tutar_d = Decimal(str(tutar or 0))
    if k == "ODENDI" or (tutar_d > 0 and odenen_d >= tutar_d):
        return "Ödendi"
    if odenen_d > 0:
        return "Kısmen ödendi"
    if vade and bugun and isinstance(vade, date) and vade < bugun:
        return "Gecikmiş"
    if k in ("BEKLIYOR", ""):
        return "Bekliyor"
    return kod or "—"


class FirmaKrediKartiCalismaDialog(tk.Toplevel):
    """Tek kart çalışma alanı: sekmeler + zorunlu butonlar."""

    def __init__(self, parent, kredi_karti_id: int):
        super().__init__(parent)
        self.parent_app = parent
        self.kredi_karti_id = int(kredi_karti_id)
        self._secili_odeme_id: int | None = None
        self._secili_ekstre_id: int | None = None
        self.geometry("1180x760")
        self.minsize(1020, 640)
        self.transient(parent)
        try:
            self.grab_set()
            from ui_pencere import pencere_os_krom_ac

            pencere_os_krom_ac(self)
        except Exception:
            pass

        self.kart = FinansService.kredi_karti_getir(self.kredi_karti_id)
        if not self.kart:
            messagebox.showerror("Kart", "Kredi kartı bulunamadı.", parent=parent)
            self.destroy()
            return
        banka = getattr(self.kart, "kart_bankasi", None) or getattr(
            getattr(self.kart, "banka_karti", None), "banka_adi", None
        ) or "—"
        son4 = self.kart.son_dort_hane or "????"
        self.title(f"FİRMA KREDİ KARTI — {banka} / {self.kart.kart_adi} / ****{son4}")

        ust = ttk.Frame(self, padding=10)
        ust.pack(fill="x")
        self.baslik = tk.Label(
            ust,
            text=f"FİRMA KREDİ KARTI — {banka} / {self.kart.kart_adi} / ****{son4}",
            font=("Segoe UI", 16, "bold"),
            fg="#0b1f4d",
            bg="#f5d76e",
            padx=10,
            pady=6,
            anchor="w",
        )
        self.baslik.pack(side="left", fill="x", expand=True)
        ttk.Button(ust, text="Kapat", command=self.destroy).pack(side="right", padx=4)

        btn = ttk.Frame(self, padding=(10, 0))
        btn.pack(fill="x")
        for metin, cmd in (
            ("Yeni Harcama", lambda: self._harcama_ac(taksitli=False)),
            ("Taksitli Harcama", lambda: self._harcama_ac(taksitli=True)),
            ("Taksit Planını Düzenle", self._plan_duzenle),
            ("Ödeme Kaydet", self._odeme_kaydet),
            ("Hesap Ekstresi", self._ekstre_odak),
            ("Yenile", self.yenile),
        ):
            ttk.Button(btn, text=metin, command=cmd).pack(side="left", padx=3, pady=4)

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=10, pady=8)
        self.tab_ozet = ttk.Frame(self.nb, padding=8)
        self.tab_harcama = ttk.Frame(self.nb, padding=8)
        self.tab_odeme = ttk.Frame(self.nb, padding=8)
        self.tab_ekstre = ttk.Frame(self.nb, padding=8)
        self.tab_ayar = ttk.Frame(self.nb, padding=8)
        self.nb.add(self.tab_ozet, text="Özet")
        self.nb.add(self.tab_harcama, text="Harcama ve Taksitler")
        self.nb.add(self.tab_odeme, text="Ödemeler")
        self.nb.add(self.tab_ekstre, text="Ekstre")
        self.nb.add(self.tab_ayar, text="Kart Ayarları")

        self._ozet_kur()
        self._harcama_kur()
        self._odeme_kur()
        self._ekstre_kur()
        self._ayar_kur()
        self.yenile()

    # --- sekmeler ---
    def _ozet_kur(self):
        self.ozet_lbl = tk.Label(
            self.tab_ozet, text="", font=("Segoe UI", 12), justify="left", anchor="nw"
        )
        self.ozet_lbl.pack(fill="both", expand=True, anchor="nw")

    def _harcama_kur(self):
        ttk.Label(
            self.tab_harcama,
            text="Harcama / plan satırları. Plan vadesi iç plandır; banka vadesi ayrıdır.",
            font=("Segoe UI", 10),
        ).pack(anchor="w")
        cols = (
            "belge", "tarih", "aciklama", "taksit", "plan_vade", "banka_vade",
            "tutar", "odenen", "kalan", "durum",
        )
        box = ttk.Frame(self.tab_harcama)
        box.pack(fill="both", expand=True, pady=6)
        self.harcama_tv = ttk.Treeview(box, columns=cols, show="headings", selectmode="browse")
        for k, b, w in (
            ("belge", "Belge", 110),
            ("tarih", "İşlem", 85),
            ("aciklama", "Açıklama", 160),
            ("taksit", "Tk", 40),
            ("plan_vade", "Plan vadesi", 95),
            ("banka_vade", "Banka vadesi", 95),
            ("tutar", "Tutar", 90),
            ("odenen", "Ödenen", 80),
            ("kalan", "Kalan", 80),
            ("durum", "Durum", 110),
        ):
            self.harcama_tv.heading(k, text=b)
            self.harcama_tv.column(k, width=w, anchor="e" if k in ("tutar", "odenen", "kalan") else "w")
        sy = ttk.Scrollbar(box, orient="vertical", command=self.harcama_tv.yview)
        self.harcama_tv.configure(yscrollcommand=sy.set)
        self.harcama_tv.pack(side="left", fill="both", expand=True)
        sy.pack(side="right", fill="y")
        self.harcama_tv.bind("<<TreeviewSelect>>", self._harcama_secildi)
        self._odeme_map: dict[str, int] = {}

    def _odeme_kur(self):
        ttk.Label(
            self.tab_odeme,
            text="Karta yapılan banka/kasa ödemeleri (ekstre ödemeleri).",
            font=("Segoe UI", 10),
        ).pack(anchor="w")
        cols = ("tarih", "belge", "tutar", "kesim", "kaynak", "durum")
        box = ttk.Frame(self.tab_odeme)
        box.pack(fill="both", expand=True, pady=6)
        self.odeme_tv = ttk.Treeview(box, columns=cols, show="headings")
        for k, b, w in (
            ("tarih", "Tarih", 90),
            ("belge", "Belge", 120),
            ("tutar", "Tutar", 100),
            ("kesim", "Kesim", 90),
            ("kaynak", "Kaynak", 110),
            ("durum", "Durum", 160),
        ):
            self.odeme_tv.heading(k, text=b)
            self.odeme_tv.column(k, width=w, anchor="e" if k == "tutar" else "w")
        sy = ttk.Scrollbar(box, orient="vertical", command=self.odeme_tv.yview)
        self.odeme_tv.configure(yscrollcommand=sy.set)
        self.odeme_tv.pack(side="left", fill="both", expand=True)
        sy.pack(side="right", fill="y")

    def _ekstre_kur(self):
        ust = ttk.Frame(self.tab_ekstre)
        ust.pack(fill="x")
        ttk.Label(ust, text="Dönem ekstresi", font=("Segoe UI", 11, "bold")).pack(side="left")
        for metin, cmd in (
            ("Aç / Yenile", self._ekstre_liste_yenile),
            ("Detay", self._ekstre_detay),
            ("PDF Kaydet", self._pdf_kaydet),
            ("Excel Kaydet", self._excel_kaydet),
            ("Yazdır", self._yazdir),
            ("E-posta İçin Hazırla", self._email_hazirla),
        ):
            ttk.Button(ust, text=metin, command=cmd).pack(side="right", padx=3)

        self.ekstre_ozet = tk.Label(
            self.tab_ekstre, text="", font=("Segoe UI", 11), justify="left", anchor="w"
        )
        self.ekstre_ozet.pack(fill="x", pady=4)

        cols = ("kesim", "donem", "son_odeme", "borc", "odenen", "kalan", "asgari", "durum")
        box = ttk.Frame(self.tab_ekstre)
        box.pack(fill="both", expand=True)
        self.ekstre_tv = ttk.Treeview(box, columns=cols, show="headings", selectmode="browse")
        for k, b, w in (
            ("kesim", "Kesim", 90),
            ("donem", "Dönem", 150),
            ("son_odeme", "Banka son ödeme", 110),
            ("borc", "Borç", 90),
            ("odenen", "Ödenen", 90),
            ("kalan", "Kalan", 90),
            ("asgari", "Asgari", 90),
            ("durum", "Durum", 120),
        ):
            self.ekstre_tv.heading(k, text=b)
            self.ekstre_tv.column(k, width=w, anchor="e" if k in ("borc", "odenen", "kalan", "asgari") else "w")
        sy = ttk.Scrollbar(box, orient="vertical", command=self.ekstre_tv.yview)
        self.ekstre_tv.configure(yscrollcommand=sy.set)
        self.ekstre_tv.pack(side="left", fill="both", expand=True)
        sy.pack(side="right", fill="y")
        self.ekstre_tv.bind("<<TreeviewSelect>>", self._ekstre_secildi)
        self._ekstre_map: dict[str, int | None] = {}

    def _ayar_kur(self):
        f = self.tab_ayar
        ttk.Label(f, text="Kart tanımı ve asgari / faiz profili", font=("Segoe UI", 12, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8)
        )
        ttk.Button(f, text="Kart Tanımını Düzenle…", command=self._kart_tanim).grid(
            row=1, column=0, sticky="w", padx=4, pady=4
        )
        ttk.Button(f, text="Faiz oran / kural tanımı…", command=self._faiz_tanim).grid(
            row=1, column=1, sticky="w", padx=4, pady=4
        )
        ttk.Label(
            f,
            text=(
                "Asgari: doğrulanmış ekstre tutarı önceliklidir; kart oranı yoksa «Tanımlanmadı».\n"
                "Akdi ve gecikme faizleri ayrı tanımlıdır; eksik profilde tahmini tutar borç yazılmaz.\n"
                "CVV bu uygulamada saklanmaz."
            ),
            justify="left",
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=10)

        ttk.Label(f, text="Banka ürün türü").grid(row=3, column=0, sticky="w", padx=4, pady=4)
        self.urun_turu = ttk.Combobox(
            f, values=("(Seçiniz)", "BIREYSEL", "TICARI", "KURUMSAL"), state="readonly", width=16
        )
        self.urun_turu.grid(row=3, column=1, sticky="w")
        ttk.Label(f, text="Ödeme vadesi yöntemi").grid(row=4, column=0, sticky="w", padx=4, pady=4)
        self.vade_yontem = ttk.Combobox(
            f,
            values=("KESIM_ARTI_N", "AYIN_GUNU"),
            state="readonly",
            width=16,
        )
        self.vade_yontem.grid(row=4, column=1, sticky="w")
        ttk.Label(f, text="Asgari oran % (kaynak yoksa)").grid(row=5, column=0, sticky="w", padx=4, pady=4)
        self.asgari_oran = ttk.Entry(f, width=12)
        self.asgari_oran.grid(row=5, column=1, sticky="w")
        ttk.Label(f, text="Asgari kaynak").grid(row=6, column=0, sticky="w", padx=4, pady=4)
        self.asgari_kaynak = ttk.Entry(f, width=36)
        self.asgari_kaynak.grid(row=6, column=1, sticky="w")
        self.oto_faiz = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            f, text="Otomatik faiz tahakkuku (doğrulanmış profil gerekir)", variable=self.oto_faiz
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=6)
        ttk.Button(f, text="Ayarları Kaydet", command=self._ayar_kaydet).grid(
            row=8, column=0, sticky="w", pady=10
        )
        self.ayar_ornek = ttk.Label(f, text="", foreground="#555")
        self.ayar_ornek.grid(row=9, column=0, columnspan=3, sticky="w")

    # --- veri ---
    def yenile(self):
        from database.kredi_karti_ekstre_service import KrediKartiEkstreService

        self.kart = FinansService.kredi_karti_getir(self.kredi_karti_id)
        if not self.kart:
            return
        oz = KrediKartiEkstreService.kart_borc_ozeti(self.kredi_karti_id)
        pb = oz.get("para_birimi") or "TRY"
        limit_metin = (
            f"Hesaplanan kullanılabilir limit: {_para(oz['kullanilabilir'], pb)}"
            if oz.get("limit_tanimli")
            else "Kullanılabilir limit: Tanımlanmamış"
        )
        tarihler = KrediKartiEkstreService.kart_tarih_ozeti(self.kart)
        asgari_metin = "Tanımlanmadı"
        try:
            for e in KrediKartiEkstreService.acik_ekstreler(self.kredi_karti_id):
                if e.get("asgari_tutar") is not None:
                    kalan_a = max(
                        Decimal("0"),
                        Decimal(str(e["asgari_tutar"])) - Decimal(str(e.get("asgari_odenen") or 0)),
                    )
                    asgari_metin = (
                        f"Ekstre asgari {_para(e['asgari_tutar'], pb)} · "
                        f"kalan asgari {_para(kalan_a, pb)}"
                    )
                    break
        except Exception:
            pass
        asim = oz.get("limit_asimi") or 0
        asim_metin = f"\nLimit aşımı:               {_para(asim, pb)}" if asim and asim > 0 else ""
        fazla = oz.get("fazla_odeme") or 0
        fazla_metin = f"\nFazla ödeme:               {_para(fazla, pb)}" if fazla else ""
        uyari = oz.get("limit_uyari") or ""
        self.ozet_lbl.configure(
            text=(
                f"Kart Limiti:               "
                f"{_para(oz['limit'], pb) if oz.get('limit_tanimli') else 'Tanımlanmamış'}\n"
                f"Kullanılan Limit:          {_para(oz.get('kullanilan'), pb)}\n"
                f"{limit_metin}\n"
                f"Güncel toplam kart borcu:  {_para(oz.get('toplam_borc'), pb)}\n"
                f"Bu dönem kalan borç:       {_para(oz.get('kesilmis_kalan'), pb)}\n"
                f"Kalan asgari ödeme:        {asgari_metin}\n"
                f"Banka son ödeme tarihi:    {tarihler.get('son_odeme_metin') or '—'}\n"
                f"Gelecek taksitler toplamı: {_para(oz.get('kesilmemis'), pb)}"
                f"{asim_metin}{fazla_metin}\n"
                f"(Banka KK toplamı ile kart limiti ayrıdır; gelecek taksit çift sayılmaz.)"
                + (f"\n{uyari}" if uyari else "")
            )
        )

        # Harcama tablosu
        for i in self.harcama_tv.get_children():
            self.harcama_tv.delete(i)
        self._odeme_map.clear()
        bugun = date.today()
        for t in FinansService.kredi_karti_bekleyen_taksitler(
            self.kart.banka_karti_id, limit=500, kredi_karti_id=self.kredi_karti_id
        ):
            iid = f"t{t['taksit_id']}"
            if t.get("odeme_id"):
                self._odeme_map[iid] = int(t["odeme_id"])
            kalan = Decimal(str(t["tutar"])) - Decimal(str(t.get("odenen_tutar") or 0))
            self.harcama_tv.insert(
                "",
                "end",
                iid=iid,
                values=(
                    t.get("belge_no") or "",
                    "",
                    t.get("kart") or "",
                    t.get("taksit_no"),
                    _tarih(t.get("vade_tarihi")),
                    _tarih(t.get("banka_vade_tarihi")),
                    _para(t.get("tutar"), ""),
                    _para(t.get("odenen_tutar") or 0, ""),
                    _para(kalan, ""),
                    _durum_metin(
                        t.get("durum"),
                        bugun=bugun,
                        vade=t.get("vade_tarihi"),
                        odenen=t.get("odenen_tutar"),
                        tutar=t.get("tutar"),
                    ),
                ),
            )
        # Açık ödemelerin tüm taksitleri (ödendi dahil) — plan düzenleme için
        try:
            odemeler = [
                o
                for o in FinansService.kredi_karti_odemeleri(banka_karti_id=self.kart.banka_karti_id, limit=400)
                if int(o.get("kredi_karti_id") or 0) == self.kredi_karti_id
            ]
        except Exception:
            odemeler = []
        for o in odemeler:
            for t in o.get("taksitler") or []:
                if (t.get("durum") or "").upper() == "PLAN_IPTAL":
                    continue
                if (t.get("durum") or "").upper() != "ODENDI":
                    continue
                iid = f"o{o.get('id') or o.get('belge_no')}_{t.get('taksit_no')}"
                if o.get("id"):
                    self._odeme_map[iid] = int(o["id"])
                self.harcama_tv.insert(
                    "",
                    "end",
                    iid=iid,
                    values=(
                        o.get("belge_no") or "",
                        _tarih(o.get("tarih")),
                        (o.get("aciklama") or "")[:40],
                        t.get("taksit_no"),
                        _tarih(t.get("vade_tarihi")),
                        "—",
                        _para(t.get("tutar"), ""),
                        _para(t.get("tutar"), ""),
                        _para(0, ""),
                        "Ödendi",
                    ),
                )

        self._odeme_liste_yenile()
        self._ekstre_liste_yenile()
        self._ayar_doldur()

    def _odeme_liste_yenile(self):
        from database.kredi_karti_ekstre_service import KrediKartiEkstreService

        for i in self.odeme_tv.get_children():
            self.odeme_tv.delete(i)
        try:
            for e in KrediKartiEkstreService.ekstreleri_hesapla(
                kredi_karti_id=self.kredi_karti_id, odenenleri_dahil=True
            ):
                eid = e.get("ekstre_id")
                if not eid:
                    continue
                try:
                    det = KrediKartiEkstreService.ekstre_detay(int(eid))
                except Exception:
                    continue
                for o in det.get("odemeler") or []:
                    self.odeme_tv.insert(
                        "",
                        "end",
                        values=(
                            _tarih(o.get("tarih")),
                            o.get("belge_no") or "",
                            _para(o.get("tutar"), ""),
                            _tarih(det.get("kesim_tarihi")),
                            o.get("kaynak") or "",
                            "İptal" if o.get("iptal") else "Geçerli",
                        ),
                    )
        except Exception as exc:
            self.odeme_tv.insert("", "end", values=("—", str(exc)[:40], "", "", "", ""))

    def _ekstre_liste_yenile(self):
        from database.kredi_karti_ekstre_service import KrediKartiEkstreService
        from kk_ekstre_ui import DURUM_ETIKET

        for i in self.ekstre_tv.get_children():
            self.ekstre_tv.delete(i)
        self._ekstre_map.clear()
        try:
            satirlar = KrediKartiEkstreService.ekstreleri_hesapla(
                kredi_karti_id=self.kredi_karti_id, odenenleri_dahil=True
            )
        except Exception as exc:
            self.ekstre_ozet.configure(text=f"Ekstre yüklenemedi: {exc}")
            return
        pb = (getattr(self.kart, "para_birimi", None) or "TRY").upper()
        for s in satirlar:
            iid = str(s.get("ekstre_id") or f"k{s.get('kesim_tarihi')}")
            self._ekstre_map[iid] = int(s["ekstre_id"]) if s.get("ekstre_id") else None
            asgari = s.get("asgari_tutar")
            self.ekstre_tv.insert(
                "",
                "end",
                iid=iid,
                values=(
                    _tarih(s.get("kesim_tarihi")),
                    f"{_tarih(s.get('donem_baslangic'))}–{_tarih(s.get('donem_bitis'))}",
                    _tarih(s.get("son_odeme_tarihi")) if s.get("son_odeme_tarihi") else "Tanımlanmadı",
                    _para(s.get("tl_tutar") or s.get("toplam_borc") or 0, ""),
                    _para(s.get("odenen") or 0, ""),
                    _para(s.get("kalan") or 0, ""),
                    _para(asgari, "") if asgari is not None else "Tanımlanmadı",
                    DURUM_ETIKET.get(s.get("durum"), s.get("durum") or ""),
                ),
            )
        self.ekstre_ozet.configure(
            text=f"{len(satirlar)} dönem · PB {pb} · PDF/Excel aynı rapor anını kullanır"
        )

    def _ayar_doldur(self):
        k = self.kart
        tur = getattr(k, "banka_urun_turu", None) or "(Seçiniz)"
        self.urun_turu.set(tur)
        yontem = getattr(k, "odeme_vade_yontemi", None) or "KESIM_ARTI_N"
        self.vade_yontem.set(yontem)
        self.asgari_oran.delete(0, "end")
        if getattr(k, "asgari_oran_yuzde", None) is not None:
            self.asgari_oran.insert(0, str(k.asgari_oran_yuzde))
        self.asgari_kaynak.delete(0, "end")
        self.asgari_kaynak.insert(0, getattr(k, "asgari_kaynak", None) or "")
        self.oto_faiz.set(bool(getattr(k, "otomatik_faiz_tahakkuku", False)))
        from database.kredi_karti_ekstre_service import KrediKartiEkstreService

        ornek = KrediKartiEkstreService.kart_tarih_ozeti(k)
        self.ayar_ornek.configure(
            text=(
                f"Örnek sonraki kesim: {ornek.get('sonraki_kesim_metin')} · "
                f"son ödeme: {ornek.get('son_odeme_metin')}"
            )
        )

    # --- eylemler ---
    def _harcama_secildi(self, _e=None):
        sec = self.harcama_tv.selection()
        if not sec:
            self._secili_odeme_id = None
            return
        self._secili_odeme_id = self._odeme_map.get(sec[0])

    def _ekstre_secildi(self, _e=None):
        sec = self.ekstre_tv.selection()
        if not sec:
            self._secili_ekstre_id = None
            return
        self._secili_ekstre_id = self._ekstre_map.get(sec[0])

    def _harcama_ac(self, *, taksitli: bool):
        from finans_ui import KrediKartiOdemeDialog

        dlg = KrediKartiOdemeDialog(self, self.kart.banka_karti_id)
        # Kartı seç
        for etiket, kid in getattr(dlg, "_kart_map", {}).items():
            if int(kid) == self.kredi_karti_id:
                dlg.kart.set(etiket)
                break
        if taksitli:
            dlg.cekim.set("Taksitli Çekim")
            dlg._cekim_degisti()
            dlg.taksit.set("6")
        else:
            dlg.cekim.set("Tek Çekim")
            dlg._cekim_degisti()
        dlg._kart_degisti()
        self.wait_window(dlg)
        self.yenile()

    def _plan_duzenle(self):
        if not self._secili_odeme_id:
            messagebox.showinfo(
                "Taksit Planını Düzenle",
                "Listeden bir harcama/taksit satırı seçin.",
                parent=self,
            )
            return
        dlg = TaksitPlaniniDuzenleDialog(self, int(self._secili_odeme_id))
        self.wait_window(dlg)
        if dlg.result:
            self.yenile()

    def _odeme_kaydet(self):
        from kk_ekstre_ui import KkEkstreOdemeDialog
        from database.kredi_karti_ekstre_service import KrediKartiEkstreService

        acik = KrediKartiEkstreService.acik_ekstreler(self.kredi_karti_id)
        if not acik:
            messagebox.showinfo(
                "Ödeme",
                "Ödenecek açık ekstre yok. Önce dönem borcu oluşmalı.",
                parent=self,
            )
            return
        hedef = acik[0]
        if self._secili_ekstre_id:
            for e in acik:
                if int(e.get("ekstre_id") or 0) == int(self._secili_ekstre_id):
                    hedef = e
                    break
        try:
            detay = KrediKartiEkstreService.ekstre_detay(int(hedef["ekstre_id"]))
            dlg = KkEkstreOdemeDialog(self, detay, yenile_cb=self.yenile)
            self.wait_window(dlg)
        except Exception as exc:
            messagebox.showerror("Ödeme", str(exc), parent=self)
        self.yenile()

    def _ekstre_odak(self):
        self.nb.select(self.tab_ekstre)
        self._ekstre_liste_yenile()

    def _ekstre_detay(self):
        from kk_ekstre_ui import KkEkstreDetayDialog

        if not self._secili_ekstre_id:
            messagebox.showinfo("Ekstre", "Listeden bir dönem seçin.", parent=self)
            return
        KkEkstreDetayDialog(
            self, {"ekstre_id": self._secili_ekstre_id}, yenile_cb=self.yenile
        )

    def _rapor(self):
        from database.kk_ekstre_rapor_service import rapor_verisi

        return rapor_verisi(
            self.kredi_karti_id,
            ekstre_id=self._secili_ekstre_id,
        )

    def _pdf_kaydet(self):
        from database.kk_ekstre_rapor_service import pdf_kaydet

        try:
            rapor = self._rapor()
        except Exception as exc:
            messagebox.showerror("PDF", str(exc), parent=self)
            return
        yol = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".pdf",
            initialfile=f"{rapor['dosya_kok']}.pdf",
            filetypes=[("PDF", "*.pdf")],
        )
        if not yol:
            return
        try:
            pdf_kaydet(rapor, yol)
            messagebox.showinfo("PDF", f"Kaydedildi:\n{yol}", parent=self)
        except Exception as exc:
            messagebox.showerror("PDF", str(exc), parent=self)

    def _excel_kaydet(self):
        from database.kk_ekstre_rapor_service import excel_kaydet

        try:
            rapor = self._rapor()
        except Exception as exc:
            messagebox.showerror("Excel", str(exc), parent=self)
            return
        yol = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".xlsx",
            initialfile=f"{rapor['dosya_kok']}.xlsx",
            filetypes=[("Excel", "*.xlsx")],
        )
        if not yol:
            return
        try:
            excel_kaydet(rapor, yol)
            messagebox.showinfo("Excel", f"Kaydedildi:\n{yol}", parent=self)
        except Exception as exc:
            messagebox.showerror("Excel", str(exc), parent=self)

    def _yazdir(self):
        from database.kk_ekstre_rapor_service import pdf_kaydet
        import os

        try:
            rapor = self._rapor()
            tmp = Path(tempfile.gettempdir()) / f"{rapor['dosya_kok']}.pdf"
            pdf_kaydet(rapor, tmp)
            os.startfile(str(tmp), "print")  # noqa: S606 — kullanıcı yazdırma
        except Exception as exc:
            messagebox.showerror("Yazdır", str(exc), parent=self)

    def _email_hazirla(self):
        from database.kk_ekstre_rapor_service import email_icin_hazirla

        try:
            rapor = self._rapor()
            klasor = filedialog.askdirectory(parent=self, title="E-posta ekleri klasörü")
            if not klasor:
                return
            yollar = email_icin_hazirla(rapor, klasor)
            messagebox.showinfo(
                "E-posta",
                "Dosyalar hazırlandı (otomatik gönderim yok):\n"
                f"PDF: {yollar['pdf']}\nExcel: {yollar['excel']}",
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror("E-posta", str(exc), parent=self)

    def _kart_tanim(self):
        from finans_ui import KrediKartiTanimDialog

        dlg = KrediKartiTanimDialog(
            self, self.kart.banka_karti_id, kart_id=self.kredi_karti_id
        )
        self.wait_window(dlg)
        self.yenile()

    def _faiz_tanim(self):
        try:
            from faiz_urun_tanim_ui import faiz_urun_tanim_goster

            faiz_urun_tanim_goster(
                self.parent_app, urun_turu="KK", urun_id=self.kredi_karti_id
            )
        except Exception as exc:
            messagebox.showerror("Faiz", str(exc), parent=self)

    def _ayar_kaydet(self):
        k = self.kart
        veri = {
            "kart_id": k.id,
            "banka_karti_id": k.banka_karti_id,
            "kart_adi": k.kart_adi,
            "kart_bankasi": k.kart_bankasi,
            "kart_sahibi": k.kart_sahibi,
            "kart_markasi": k.kart_markasi,
            "kart_numarasi": k.kart_numarasi,
            "son_dort_hane": k.son_dort_hane,
            "son_kullanim": k.son_kullanim,
            "kart_limiti": k.kart_limiti,
            "hesap_kesim_gunu": k.hesap_kesim_gunu,
            "son_odeme_gunu": k.son_odeme_gunu,
            "kesimden_sonra_odeme_gun": k.kesimden_sonra_odeme_gun,
            "para_birimi": k.para_birimi,
            "aciklama": k.aciklama,
            "aktif": k.aktif,
            "odeme_vade_yontemi": self.vade_yontem.get(),
            "banka_urun_turu": None
            if self.urun_turu.get() in ("", "(Seçiniz)")
            else self.urun_turu.get(),
            "asgari_oran_yuzde": self.asgari_oran.get(),
            "asgari_kaynak": self.asgari_kaynak.get(),
            "otomatik_faiz_tahakkuku": self.oto_faiz.get(),
        }
        try:
            FinansService.kredi_karti_kaydet(veri)
            messagebox.showinfo("Ayarlar", "Kaydedildi.", parent=self)
            self.yenile()
        except ValueError as exc:
            messagebox.showerror("Ayarlar", str(exc), parent=self)


class TaksitPlaniniDuzenleDialog(tk.Toplevel):
    """Zorunlu: kalan anapara için yeni iç plan sürümü."""

    def __init__(self, parent, odeme_id: int):
        super().__init__(parent)
        self.odeme_id = int(odeme_id)
        self.result = None
        self.title("Taksit Planını Düzenle — İç ödeme planı")
        self.geometry("920x640")
        self.minsize(820, 560)
        self.transient(parent)
        try:
            self.grab_set()
            from ui_pencere import pencere_os_krom_ac

            pencere_os_krom_ac(self)
        except Exception:
            pass

        from database.kk_plan_service import plan_durum_ozeti

        try:
            self.ozet = plan_durum_ozeti(self.odeme_id)
        except Exception as exc:
            messagebox.showerror("Plan", str(exc), parent=parent)
            self.destroy()
            return

        ttk.Label(
            self,
            text=(
                f"{self.ozet['belge_no']} · {_para(self.ozet['tutar'])} · "
                f"Ödenen {_para(self.ozet['odenen_toplam'])} · "
                f"Kalan anapara {_para(self.ozet['kalan_anapara'])} · "
                f"sürüm {self.ozet['plan_versiyon']}"
            ),
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=12, pady=8)

        if self.ozet["tamamen_odendi"]:
            ttk.Label(
                self,
                text="Kalan borç yok — plan salt okunur; yeniden borç açılamaz.",
                foreground="#8a0000",
            ).pack(anchor="w", padx=12)
            ttk.Button(self, text="Kapat", command=self.destroy).pack(pady=12)
            return

        orta = ttk.Frame(self, padding=8)
        orta.pack(fill="both", expand=True)
        sol = ttk.LabelFrame(orta, text="Eski plan", padding=6)
        sol.pack(side="left", fill="both", expand=True, padx=(0, 4))
        sag = ttk.LabelFrame(orta, text="Yeni kalan plan önizleme", padding=6)
        sag.pack(side="left", fill="both", expand=True, padx=(4, 0))

        self.eski_tv = ttk.Treeview(
            sol, columns=("no", "vade", "tutar", "odenen", "kalan", "durum"), show="headings", height=12
        )
        for k, b, w in (
            ("no", "No", 40), ("vade", "Vade", 90), ("tutar", "Tutar", 80),
            ("odenen", "Ödenen", 80), ("kalan", "Kalan", 80), ("durum", "Durum", 90),
        ):
            self.eski_tv.heading(k, text=b)
            self.eski_tv.column(k, width=w)
        self.eski_tv.pack(fill="both", expand=True)
        for s in self.ozet["satirlar"]:
            self.eski_tv.insert(
                "",
                "end",
                values=(
                    s["taksit_no"],
                    _tarih(s["vade_tarihi"]),
                    _para(s["tutar"], ""),
                    _para(s["odenen"], ""),
                    _para(s["kalan"], ""),
                    "Kilitli" if s["kilitli"] else s["durum"],
                ),
            )

        form = ttk.Frame(sag)
        form.pack(fill="x")
        ttk.Label(form, text="Yeni KALAN taksit sayısı").grid(row=0, column=0, sticky="w", pady=3)
        self.kalan_n = ttk.Combobox(
            form,
            values=[str(i) for i in range(1, KK_STANDART_MAX_TAKSIT + 1)],
            width=6,
            state="readonly",
        )
        self.kalan_n.set("2")
        self.kalan_n.grid(row=0, column=1, sticky="w")
        self.kalan_n.bind("<<ComboboxSelected>>", lambda _e: self._onizle())
        ttk.Label(form, text="Yeni başlangıç vadesi").grid(row=1, column=0, sticky="w", pady=3)
        self.bas_vade = ttk.Entry(form, width=12)
        self.bas_vade.insert(0, date.today().strftime("%d.%m.%Y"))
        self.bas_vade.grid(row=1, column=1, sticky="w")
        self.bas_vade.bind("<KeyRelease>", lambda _e: self._onizle())
        ttk.Label(form, text="Değişiklik açıklaması *").grid(row=2, column=0, sticky="w", pady=3)
        self.aciklama = ttk.Entry(form, width=40)
        self.aciklama.grid(row=2, column=1, sticky="w")

        self.yeni_tv = ttk.Treeview(
            sag,
            columns=("no", "eski_v", "yeni_v", "eski_k", "yeni_t"),
            show="headings",
            height=8,
        )
        for k, b, w in (
            ("no", "No", 40),
            ("eski_v", "Eski Vade", 90),
            ("yeni_v", "Yeni Vade", 90),
            ("eski_k", "Eski Kalan", 90),
            ("yeni_t", "Yeni Tutar", 90),
        ):
            self.yeni_tv.heading(k, text=b)
            self.yeni_tv.column(k, width=w)
        self.yeni_tv.pack(fill="both", expand=True, pady=6)
        ttk.Label(
            sag,
            text="İç ödeme planı — banka ekstresindeki vade kendiliğinden değişmez.",
            foreground="#555",
        ).pack(anchor="w")

        alt = ttk.Frame(self, padding=10)
        alt.pack(fill="x")
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(alt, text="Kaydet", command=self._kaydet).pack(side="right")
        self._onizle()

    def _onizle(self):
        from database.kk_plan_service import plan_onizleme
        from database.finans_service import FinansService

        for i in self.yeni_tv.get_children():
            self.yeni_tv.delete(i)
        try:
            n = int(self.kalan_n.get())
            bas = datetime.strptime(self.bas_vade.get().strip(), "%d.%m.%Y").date()
        except Exception:
            return
        kart = FinansService.kredi_karti_getir(self.ozet["kredi_karti_id"])
        try:
            plan = plan_onizleme(
                self.ozet["kalan_anapara"], n, bas, kart=kart, cekim_tarihi=self.ozet["tarih"]
            )
        except ValueError:
            return
        eski_kalanlar = [s for s in self.ozet["satirlar"] if not s["kilitli"] and s["kalan"] > 0]
        for i, s in enumerate(plan):
            eski = eski_kalanlar[i] if i < len(eski_kalanlar) else None
            self.yeni_tv.insert(
                "",
                "end",
                values=(
                    s["taksit_no"],
                    _tarih(eski["vade_tarihi"]) if eski else "—",
                    _tarih(s["vade_tarihi"]),
                    _para(eski["kalan"], "") if eski else "—",
                    _para(s["tutar"], ""),
                ),
            )

    def _kaydet(self):
        from database.kk_plan_service import plani_duzenle

        try:
            n = int(self.kalan_n.get())
            bas = datetime.strptime(self.bas_vade.get().strip(), "%d.%m.%Y").date()
            self.result = plani_duzenle(
                self.odeme_id,
                yeni_kalan_taksit_sayisi=n,
                yeni_baslangic_vade=bas,
                aciklama=self.aciklama.get(),
                beklenen_versiyon=self.ozet["plan_versiyon"],
            )
        except ValueError as exc:
            messagebox.showerror("Plan", str(exc), parent=self)
            return
        messagebox.showinfo(
            "Plan",
            f"İç plan sürüm {self.result['plan_versiyon']} kaydedildi.\n"
            f"Kalan {_para(self.result['kalan_anapara'])} · "
            f"{len(self.result['yeni_plan'])} taksit.",
            parent=self,
        )
        self.destroy()
