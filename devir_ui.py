"""Ayarlar → Firma ve Dönem İşlemleri + Yıllık Devir Sihirbazı (Aşama 2 UI iskeleti)."""

from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from tkinter import messagebox, ttk

from database.devir_service import DURUM_ETIKET, DevirService
from database.donem_service import DonemService
from database.session_manager import oturum
from ana_panel_tema import KOYU_LACIVERT, LACIVERT, SARI

_ADIMLAR = (
    "Dönemi Seç",
    "Devir Seçenekleri",
    "Kontrol ve Ön İzleme",
    "Onay ve Başlat",
    "Sonuç",
)


def firma_donem_islemleri_goster(app) -> None:
    """Ayarlar hub: dönem, sihirbaz, ayarlar, kontroller, karşılaştırma, geçmiş."""
    app._icerigi_temizle()
    kabuk = getattr(app, "_ana_panel_kabuk", None)
    if kabuk:
        kabuk.menu_secili_guncelle("ayarlar")

    ttk.Label(app.icerik, text="FİRMA VE DÖNEM İŞLEMLERİ", style="Baslik.TLabel").pack(
        anchor="w", padx=20, pady=(16, 0)
    )
    ttk.Label(
        app.icerik,
        text=(
            f"{oturum.firma_unvan or '—'} — aynı firma altında dönem açma, "
            "yıllık devir ve kapanış–açılış karşılaştırma."
        ),
        style="AnaPanelMuted.TLabel",
        wraplength=720,
    ).pack(anchor="w", padx=20, pady=(8, 0))

    ttk.Button(
        app.icerik, text="← Ayarlar", command=lambda: _ayarlara_don(app)
    ).pack(anchor="w", padx=20, pady=(12, 0))

    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", padx=20, pady=(20, 0))
    alt.columnconfigure(0, weight=1, minsize=420)

    def _donem():
        from sistem_ui import donemler_yonet_goster

        donemler_yonet_goster(app)

    def _sihirbaz():
        YillikDevirSihirbazi(app)

    def _ayarlar():
        devir_ayarlari_goster(app)

    def _kontroller():
        isler = DevirService.isleri_listele(limit=1)
        if not isler:
            messagebox.showinfo("Kontrol", "Önce sihirbazdan bir devir işi oluşturun.", parent=app)
            return
        try:
            s = DevirService.on_kontrol(isler[0]["id"])
            messagebox.showinfo(
                "Devir Öncesi Kontroller",
                f"İş: {isler[0]['is_no']}\nSonuç: {s.get('sonuc')}\n"
                f"Hata: {len(s.get('hatalar') or [])}  Uyarı: {len(s.get('uyarilar') or [])}",
                parent=app,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Kontrol", str(exc), parent=app)

    def _karsilastirma():
        karsilastirma_raporu_goster(app)

    def _gecmis():
        devir_gecmisi_goster(app)

    for i, (baslik, komut) in enumerate(
        (
            ("DÖNEM YÖNETİMİ", _donem),
            ("YILLIK DEVİR SİHİRBAZI", _sihirbaz),
            ("DEVİR AYARLARI", _ayarlar),
            ("DEVİR ÖNCESİ KONTROLLER", _kontroller),
            ("DEVİR KARŞILAŞTIRMA RAPORU", _karsilastirma),
            ("DEVİR GEÇMİŞİ VE DÜZELTMELERİ", _gecmis),
        )
    ):
        app._alt_menu_dugme(alt, baslik, komut, row=i, column=0, sticky="ew", pady=4)


def _ayarlara_don(app) -> None:
    from ana_panel_ui import ayarlar_goster

    ayarlar_goster(app)


def devir_ayarlari_goster(app) -> None:
    app._icerigi_temizle()
    ttk.Label(app.icerik, text="DEVİR AYARLARI", style="Baslik.TLabel").pack(
        anchor="w", padx=20, pady=(16, 0)
    )
    ttk.Button(
        app.icerik, text="← Firma ve Dönem", command=lambda: firma_donem_islemleri_goster(app)
    ).pack(anchor="w", padx=20, pady=(8, 12))

    paket = DevirService.ayarlari_getir()
    ayar = paket["ayarlar"]
    frm = ttk.LabelFrame(app.icerik, text=f"Firma varsayılanları (sürüm {paket['surum']})", padding=12)
    frm.pack(fill="x", padx=20, pady=8)

    cari_var = tk.StringVar(value=ayar.get("cari_modu", "ACIK_BELGE_VADE"))
    stok_var = tk.StringVar(value=ayar.get("stok_maliyet", "MEVCUT_YONTEM"))
    negatif_var = tk.StringVar(value=ayar.get("negatif_kayitlar", "AYNEN"))
    gm_var = tk.BooleanVar(value=bool(ayar.get("genel_muhasebe")))
    kilit_var = tk.BooleanVar(value=bool(ayar.get("donem_kilidi_kesin", True)))

    ttk.Label(frm, text="Cari devri:").grid(row=0, column=0, sticky="w", pady=4)
    ttk.Combobox(
        frm,
        textvariable=cari_var,
        values=("ACIK_BELGE_VADE", "OZET_BAKIYE"),
        state="readonly",
        width=28,
    ).grid(row=0, column=1, sticky="w", pady=4)

    ttk.Label(frm, text="Stok maliyet:").grid(row=1, column=0, sticky="w", pady=4)
    ttk.Combobox(
        frm,
        textvariable=stok_var,
        values=(
            "MEVCUT_YONTEM",
            "FIFO",
            "AO",
            "DONEMSEL_AO",
            "YALNIZ_MIKTAR",
            "SECILEN_FIYAT",
        ),
        state="readonly",
        width=28,
    ).grid(row=1, column=1, sticky="w", pady=4)

    ttk.Label(frm, text="Negatif kayıtlar:").grid(row=2, column=0, sticky="w", pady=4)
    ttk.Combobox(
        frm,
        textvariable=negatif_var,
        values=("AYNEN",),
        state="readonly",
        width=28,
    ).grid(row=2, column=1, sticky="w", pady=4)

    ttk.Checkbutton(frm, text="Genel muhasebe aşamasını etkinleştir", variable=gm_var).grid(
        row=3, column=0, columnspan=2, sticky="w", pady=4
    )
    ttk.Checkbutton(
        frm, text="Kesin devirde kaynak dönemi kilitle", variable=kilit_var
    ).grid(row=4, column=0, columnspan=2, sticky="w", pady=4)

    def kaydet():
        try:
            DevirService.ayarlari_kaydet(
                {
                    "cari_modu": cari_var.get(),
                    "stok_maliyet": stok_var.get(),
                    "negatif_kayitlar": negatif_var.get(),
                    "genel_muhasebe": gm_var.get(),
                    "donem_kilidi_kesin": kilit_var.get(),
                }
            )
            messagebox.showinfo("Devir Ayarları", "Kaydedildi.", parent=app)
            devir_ayarlari_goster(app)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Devir Ayarları", str(exc), parent=app)

    ttk.Button(app.icerik, text="Kaydet", command=kaydet).pack(anchor="w", padx=20, pady=12)


def karsilastirma_raporu_goster(app) -> None:
    app._icerigi_temizle()
    ttk.Label(app.icerik, text="DEVİR KARŞILAŞTIRMA RAPORU", style="Baslik.TLabel").pack(
        anchor="w", padx=20, pady=(16, 0)
    )
    ttk.Button(
        app.icerik, text="← Firma ve Dönem", command=lambda: firma_donem_islemleri_goster(app)
    ).pack(anchor="w", padx=20, pady=(8, 12))

    isler = DevirService.isleri_listele(limit=20)
    if not isler:
        ttk.Label(app.icerik, text="Henüz devir işi yok.").pack(anchor="w", padx=20)
        return

    sec = tk.StringVar(value=isler[0]["is_no"])
    ttk.Label(app.icerik, text="İş:").pack(anchor="w", padx=20)
    ttk.Combobox(
        app.icerik,
        textvariable=sec,
        values=[i["is_no"] for i in isler],
        state="readonly",
        width=28,
    ).pack(anchor="w", padx=20, pady=4)

    tablo = ttk.Treeview(
        app.icerik,
        columns=("modul", "kaynak", "hedef", "fark", "ok", "acik"),
        show="headings",
        height=12,
    )
    for k, b, w in (
        ("modul", "Modül", 100),
        ("kaynak", "Kaynak Kapanış", 120),
        ("hedef", "Hedef Açılış", 120),
        ("fark", "Fark", 100),
        ("ok", "OK", 50),
        ("acik", "Açıklama", 280),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="w" if k == "acik" else "center")
    tablo.pack(fill="both", expand=True, padx=20, pady=8)
    ozet_lbl = ttk.Label(app.icerik, text="")
    ozet_lbl.pack(anchor="w", padx=20)

    def calistir():
        is_ = next((i for i in isler if i["is_no"] == sec.get()), None)
        if not is_:
            return
        try:
            for x in tablo.get_children():
                tablo.delete(x)
            rapor = DevirService.karsilastirma_raporu(is_["id"])
            for s in rapor.get("satirlar") or []:
                tablo.insert(
                    "",
                    "end",
                    values=(
                        s["modul"],
                        s["kaynak_kapanis"],
                        s["hedef_acilis"],
                        s["fark"],
                        "Evet" if s["ok"] else "Hayır",
                        s.get("aciklama") or "",
                    ),
                )
            ozet_lbl.configure(text=f"{rapor.get('mesaj')} — {rapor.get('is_no')}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Karşılaştırma", str(exc), parent=app)

    def yedek_test():
        is_ = next((i for i in isler if i["is_no"] == sec.get()), None)
        if not is_:
            return
        try:
            if not is_.get("yedek_dogrulandi"):
                DevirService.yedek_al_ve_dogrula(is_["id"])
                is_ = DevirService.is_getir(is_["id"]) or is_
            r = DevirService.yedek_geri_yukle_dogrula(is_["id"])
            messagebox.showinfo(
                "Yedek Geri Yükleme Testi",
                f"Integrity: {r.get('integrity')}\n"
                f"Kopya: {r.get('kopya')}\n"
                f"Canlı DB değişmedi: {r.get('canli_db_degismedi')}\n"
                f"Sayımlar: {r.get('sayimlar')}",
                parent=app,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Yedek", str(exc), parent=app)

    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", padx=20, pady=8)
    ttk.Button(alt, text="Karşılaştırmayı Çalıştır", command=calistir).pack(side="left")
    ttk.Button(alt, text="Yedek Al + Geri Yükle Doğrula", command=yedek_test).pack(
        side="left", padx=8
    )


def devir_gecmisi_goster(app) -> None:
    app._icerigi_temizle()
    ttk.Label(app.icerik, text="DEVİR GEÇMİŞİ", style="Baslik.TLabel").pack(
        anchor="w", padx=20, pady=(16, 0)
    )
    ttk.Button(
        app.icerik, text="← Firma ve Dönem", command=lambda: firma_donem_islemleri_goster(app)
    ).pack(anchor="w", padx=20, pady=(8, 12))

    tablo = ttk.Treeview(
        app.icerik,
        columns=("no", "tur", "durum", "kesim", "acilis", "yedek"),
        show="headings",
        height=14,
    )
    for k, b, w in (
        ("no", "İş No", 120),
        ("tur", "Tür", 100),
        ("durum", "Durum", 140),
        ("kesim", "Kesim", 100),
        ("acilis", "Açılış", 100),
        ("yedek", "Yedek", 70),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="center")
    tablo.pack(fill="both", expand=True, padx=20, pady=8)

    for is_ in DevirService.isleri_listele():
        tablo.insert(
            "",
            "end",
            iid=str(is_["id"]),
            values=(
                is_["is_no"],
                is_["devir_turu"],
                is_.get("durum_etiket") or DURUM_ETIKET.get(is_["durum"], is_["durum"]),
                _tarih(is_["kesim_tarihi"]),
                _tarih(is_["acilis_tarihi"]),
                "Evet" if is_.get("yedek_dogrulandi") else "—",
            ),
        )

    def geri_al():
        s = tablo.selection()
        if not s:
            return
        if not messagebox.askyesno(
            "Geri Al",
            "Yalnız bu işin eşleştirmeleri silinir; cari/stok/finans hareketleri korunur. Devam?",
            parent=app,
        ):
            return
        try:
            r = DevirService.geri_al(int(s[0]))
            messagebox.showinfo("Geri Al", r.get("mesaj"), parent=app)
            for i in tablo.get_children():
                tablo.delete(i)
            for is_ in DevirService.isleri_listele():
                tablo.insert(
                    "",
                    "end",
                    iid=str(is_["id"]),
                    values=(
                        is_["is_no"],
                        is_["devir_turu"],
                        is_.get("durum_etiket") or DURUM_ETIKET.get(is_["durum"], is_["durum"]),
                        _tarih(is_["kesim_tarihi"]),
                        _tarih(is_["acilis_tarihi"]),
                        "Evet" if is_.get("yedek_dogrulandi") else "—",
                    ),
                )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Geri Al", str(exc), parent=app)

    def guncelleme_kontrol():
        s = tablo.selection()
        if not s:
            return
        try:
            r = DevirService.on_devir_guncelleme_gerekli_mi(int(s[0]))
            messagebox.showinfo("Ön Devir Güncelleme", r.get("mesaj"), parent=app)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Güncelleme", str(exc), parent=app)

    alt2 = ttk.Frame(app.icerik)
    alt2.pack(fill="x", padx=20, pady=6)
    ttk.Button(alt2, text="Geri Al (eşleştirme)", command=geri_al).pack(side="left")
    ttk.Button(alt2, text="Ön Devir Güncelleme Kontrolü", command=guncelleme_kontrol).pack(
        side="left", padx=8
    )


def _tarih(v) -> str:
    if isinstance(v, date):
        return v.strftime("%d.%m.%Y")
    return str(v or "—")


class YillikDevirSihirbazi(tk.Toplevel):
    """5 adımlı sihirbaz — Aşama 2: dönem seçimi + iş oluşturma; yazma Aşama 3+."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Yıllık Devir Sihirbazı")
        self.transient(parent)
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)
        self.geometry("960x640")
        self.minsize(800, 520)
        self.app = parent
        self.adim = 0
        self.is_kayit: dict | None = None
        self.donemler = DonemService.listele()

        ust = tk.Frame(self, bg=LACIVERT, height=56)
        ust.pack(fill="x")
        ust.pack_propagate(False)
        self.baslik_lbl = tk.Label(
            ust,
            text=f"{oturum.firma_unvan or 'Firma'} — Yıllık Devir",
            bg=LACIVERT,
            fg=SARI,
            font=("Segoe UI", 12, "bold"),
            anchor="w",
        )
        self.baslik_lbl.pack(fill="x", padx=16, pady=8)

        self.adim_cerceve = ttk.Frame(self, padding=(12, 8))
        self.adim_cerceve.pack(fill="x")
        self.adim_etiketleri: list[tk.Label] = []
        for i, ad in enumerate(_ADIMLAR):
            lbl = tk.Label(
                self.adim_cerceve,
                text=f"{i + 1}. {ad}",
                font=("Segoe UI", 9),
                padx=8,
                pady=4,
            )
            lbl.pack(side="left", padx=2)
            self.adim_etiketleri.append(lbl)

        govde = ttk.Frame(self, padding=12)
        govde.pack(fill="both", expand=True)
        govde.columnconfigure(0, weight=3)
        govde.columnconfigure(1, weight=1)
        govde.rowconfigure(0, weight=1)

        self.icerik = ttk.Frame(govde)
        self.icerik.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.ozet = ttk.LabelFrame(govde, text="Devir Özeti", padding=10)
        self.ozet.grid(row=0, column=1, sticky="nsew")
        self.ozet_metin = tk.Text(self.ozet, width=32, height=18, wrap="word", state="disabled")
        self.ozet_metin.pack(fill="both", expand=True)

        # Seçimler
        self.kaynak_var = tk.StringVar()
        self.hedef_var = tk.StringVar()
        self.kesim_var = tk.StringVar()
        self.acilis_var = tk.StringVar()
        self.tur_var = tk.StringVar(value="ON_DEVIR")
        self.modul_vars = {
            "CARI": tk.BooleanVar(value=True),
            "STOK": tk.BooleanVar(value=True),
            "FINANS": tk.BooleanVar(value=True),
            "ACIK_ISLEM": tk.BooleanVar(value=True),
            "GENEL_MUHASEBE": tk.BooleanVar(value=False),
        }
        self._donem_seceneklerini_doldur()

        alt = tk.Frame(self, bg="#F5F5F5")
        alt.pack(fill="x", side="bottom")
        ic_alt = ttk.Frame(alt, padding=10)
        ic_alt.pack(fill="x")
        self.btn_geri = ttk.Button(ic_alt, text="Geri", command=self._geri)
        self.btn_geri.pack(side="left")
        self.btn_ileri = ttk.Button(ic_alt, text="İleri", command=self._ileri)
        self.btn_ileri.pack(side="left", padx=6)
        self.btn_kontrol = ttk.Button(ic_alt, text="Kontrol Et", command=self._kontrol, state="disabled")
        self.btn_kontrol.pack(side="left", padx=6)
        self.btn_onizle = ttk.Button(ic_alt, text="Ön İzle", command=self._onizle, state="disabled")
        self.btn_onizle.pack(side="left")
        self.btn_baslat = tk.Button(
            ic_alt,
            text="Devri Başlat",
            bg=SARI,
            fg=KOYU_LACIVERT,
            activebackground=SARI,
            relief="flat",
            padx=12,
            state="disabled",
            command=self._baslat,
        )
        self.btn_baslat.pack(side="left", padx=10)
        ttk.Button(ic_alt, text="Kapat", command=self.destroy).pack(side="right")

        self._adim_goster()

    def _donem_seceneklerini_doldur(self) -> None:
        self._donem_map = {d["donem_adi"]: d for d in self.donemler}
        adlar = [d["donem_adi"] for d in self.donemler]
        if len(adlar) >= 2:
            # En yeni bitiş = muhtemel kaynak; bir sonraki yıl adı hedef olabilir
            sirali = sorted(self.donemler, key=lambda x: x["bitis_tarihi"] or date.min, reverse=True)
            self.kaynak_var.set(sirali[0]["donem_adi"])
            self.hedef_var.set(sirali[1]["donem_adi"] if len(sirali) > 1 else "")
            self._tarihleri_kaynaktan()
        elif len(adlar) == 1:
            self.kaynak_var.set(adlar[0])
            self._tarihleri_kaynaktan()

    def _tarihleri_kaynaktan(self) -> None:
        k = self._donem_map.get(self.kaynak_var.get())
        if not k:
            return
        bitis = k.get("bitis_tarihi")
        if isinstance(bitis, date):
            self.kesim_var.set(bitis.strftime("%d.%m.%Y"))
            acilis = bitis + timedelta(days=1)
            self.acilis_var.set(acilis.strftime("%d.%m.%Y"))

    def _parse_tarih(self, metin: str) -> date:
        return date(int(metin[6:10]), int(metin[3:5]), int(metin[0:2]))

    def _adim_goster(self) -> None:
        for w in self.icerik.winfo_children():
            w.destroy()
        for i, lbl in enumerate(self.adim_etiketleri):
            if i == self.adim:
                lbl.configure(bg=SARI, fg=KOYU_LACIVERT, font=("Segoe UI", 9, "bold"))
            elif i < self.adim:
                lbl.configure(bg="#E8E8E8", fg=LACIVERT, font=("Segoe UI", 9))
            else:
                lbl.configure(bg="#FAFAFA", fg="#888", font=("Segoe UI", 9))

        if self.adim == 0:
            self._adim_donem()
        elif self.adim == 1:
            self._adim_secenekler()
        elif self.adim == 2:
            self._adim_kontrol()
        elif self.adim == 3:
            self._adim_onay()
        else:
            self._adim_sonuc()

        self.btn_geri.configure(state="normal" if self.adim > 0 else "disabled")
        self.btn_ileri.configure(state="normal" if self.adim < 4 else "disabled")
        self.btn_kontrol.configure(state="normal" if self.adim == 2 else "disabled")
        self.btn_onizle.configure(state="normal" if self.adim == 2 else "disabled")
        self._ozet_guncelle()

    def _adim_donem(self) -> None:
        ttk.Label(
            self.icerik,
            text="Kaynak ve hedef dönemi seçin. Aynı dönem engellenir.",
            wraplength=560,
        ).pack(anchor="w", pady=(0, 12))
        adlar = list(self._donem_map.keys()) or ["(dönem yok — önce Dönem Yönetimi)"]
        sat = ttk.Frame(self.icerik)
        sat.pack(fill="x", pady=4)
        ttk.Label(sat, text="Eski dönem (kaynak):", width=22).pack(side="left")
        cb_k = ttk.Combobox(sat, textvariable=self.kaynak_var, values=adlar, state="readonly", width=28)
        cb_k.pack(side="left")
        cb_k.bind("<<ComboboxSelected>>", lambda _e: (self._tarihleri_kaynaktan(), self._ozet_guncelle()))

        sat2 = ttk.Frame(self.icerik)
        sat2.pack(fill="x", pady=4)
        ttk.Label(sat2, text="Yeni dönem (hedef):", width=22).pack(side="left")
        cb_h = ttk.Combobox(sat2, textvariable=self.hedef_var, values=adlar, state="readonly", width=28)
        cb_h.pack(side="left")
        cb_h.bind("<<ComboboxSelected>>", lambda _e: self._ozet_guncelle())

        sat3 = ttk.Frame(self.icerik)
        sat3.pack(fill="x", pady=4)
        ttk.Label(sat3, text="Kesim tarihi:", width=22).pack(side="left")
        ttk.Entry(sat3, textvariable=self.kesim_var, width=14).pack(side="left")

        sat4 = ttk.Frame(self.icerik)
        sat4.pack(fill="x", pady=4)
        ttk.Label(sat4, text="Açılış tarihi:", width=22).pack(side="left")
        ttk.Entry(sat4, textvariable=self.acilis_var, width=14).pack(side="left")

        ttk.Label(
            self.icerik,
            text="Hedef dönem yoksa Ayarlar → Firma ve Dönem → Dönem Yönetimi ile açın.",
            foreground="#666",
            wraplength=560,
        ).pack(anchor="w", pady=(16, 0))

    def _adim_secenekler(self) -> None:
        ttk.Label(self.icerik, text="Basit görünüm — modül kapsamı ve devir türü.").pack(
            anchor="w", pady=(0, 10)
        )
        for kod, baslik in (
            ("CARI", "Cariler ve Vadeler"),
            ("STOK", "Stoklar ve Maliyet"),
            ("FINANS", "Finans Hesapları"),
            ("ACIK_ISLEM", "Açık İşlemler"),
            ("GENEL_MUHASEBE", "Genel Muhasebe (yetkili)"),
        ):
            ttk.Checkbutton(self.icerik, text=baslik, variable=self.modul_vars[kod]).pack(
                anchor="w", pady=2
            )
        ttk.Separator(self.icerik, orient="horizontal").pack(fill="x", pady=10)
        ttk.Label(self.icerik, text="Devir türü:").pack(anchor="w")
        ttk.Radiobutton(
            self.icerik,
            text="Ön Devir — kaynak düzenlenebilir kalabilir",
            variable=self.tur_var,
            value="ON_DEVIR",
        ).pack(anchor="w")
        ttk.Radiobutton(
            self.icerik,
            text="Kesin Devir — kontrollerden sonra kaynak kilitlenir",
            variable=self.tur_var,
            value="KESIN_DEVIR",
        ).pack(anchor="w")

    def _adim_kontrol(self) -> None:
        ttk.Label(
            self.icerik,
            text=(
                "Kontrol ve ön izleme motoru Aşama 3 ile yazılacak.\n"
                "Bu adımda iş kaydı oluşturulur; veri değiştirilmez."
            ),
            wraplength=560,
            justify="left",
        ).pack(anchor="w", pady=8)
        if self.is_kayit:
            ttk.Label(
                self.icerik,
                text=f"İş: {self.is_kayit['is_no']} — {self.is_kayit.get('durum_etiket')}",
                font=("Segoe UI", 10, "bold"),
            ).pack(anchor="w", pady=8)

    def _adim_onay(self) -> None:
        ttk.Label(
            self.icerik,
            text="Devri Başlat, geçerli ön izleme + doğrulanmış yedek sonrası Aşama 3+ ile etkinleşir.",
            wraplength=560,
        ).pack(anchor="w", pady=8)
        if self.is_kayit:
            ttk.Label(
                self.icerik,
                text=(
                    f"{self.is_kayit['is_no']}\n"
                    f"Tür: {self.is_kayit['devir_turu']}\n"
                    f"Yedek: {'doğrulandı' if self.is_kayit.get('yedek_dogrulandi') else 'yok'}"
                ),
                justify="left",
            ).pack(anchor="w", pady=8)

    def _adim_sonuc(self) -> None:
        ttk.Label(
            self.icerik,
            text="Sonuç ekranı Aşama 5–6 ile doldurulacak. İş geçmişinden kayıtları izleyebilirsiniz.",
            wraplength=560,
        ).pack(anchor="w", pady=8)

    def _ozet_guncelle(self) -> None:
        kaps = [k for k, v in self.modul_vars.items() if v.get()]
        metin = (
            f"Firma: {oturum.firma_unvan or '—'}\n"
            f"Kaynak: {self.kaynak_var.get() or '—'}\n"
            f"Hedef: {self.hedef_var.get() or '—'}\n"
            f"Kesim: {self.kesim_var.get() or '—'}\n"
            f"Açılış: {self.acilis_var.get() or '—'}\n"
            f"Tür: {self.tur_var.get()}\n"
            f"Modüller: {', '.join(kaps) or '—'}\n"
        )
        if self.is_kayit:
            metin += f"\nİş: {self.is_kayit['is_no']}\nDurum: {self.is_kayit.get('durum_etiket')}"
        self.ozet_metin.configure(state="normal")
        self.ozet_metin.delete("1.0", "end")
        self.ozet_metin.insert("1.0", metin)
        self.ozet_metin.configure(state="disabled")
        self.baslik_lbl.configure(
            text=(
                f"{oturum.firma_unvan or 'Firma'} • "
                f"{self.kaynak_var.get() or '?'} → {self.hedef_var.get() or '?'} • "
                f"{self.kesim_var.get() or '—'} kapanış • {self.acilis_var.get() or '—'} açılış"
            )
        )

    def _secim_dogrula(self) -> tuple[int, int, date, date]:
        k = self._donem_map.get(self.kaynak_var.get())
        h = self._donem_map.get(self.hedef_var.get())
        if not k or not h:
            raise ValueError("Kaynak ve hedef dönem seçilmelidir.")
        if k["id"] == h["id"]:
            raise ValueError("Kaynak ve hedef dönem aynı olamaz.")
        kesim = self._parse_tarih(self.kesim_var.get().strip())
        acilis = self._parse_tarih(self.acilis_var.get().strip())
        if acilis <= kesim:
            raise ValueError("Açılış tarihi kesimden sonra olmalıdır.")
        return int(k["id"]), int(h["id"]), kesim, acilis

    def _geri(self) -> None:
        if self.adim > 0:
            self.adim -= 1
            self._adim_goster()

    def _ileri(self) -> None:
        try:
            if self.adim == 0:
                self._secim_dogrula()
            if self.adim == 1:
                kid, hid, kesim, acilis = self._secim_dogrula()
                kaps = [k for k, v in self.modul_vars.items() if v.get()]
                if not kaps:
                    raise ValueError("En az bir modül seçin.")
                mevcut = DevirService.aktif_devir_isi(kid, hid)
                if mevcut and mevcut["durum"] not in (
                    "TAMAMLANDI",
                    "UYARILAR_VAR",
                    "BASARISIZ",
                    "GERI_ALINDI",
                ):
                    if not messagebox.askyesno(
                        "Mevcut İş",
                        f"Açık iş: {mevcut['is_no']} ({mevcut.get('durum_etiket')}).\n"
                        "Bu işi kullanmak ister misiniz?",
                        parent=self,
                    ):
                        return
                    self.is_kayit = mevcut
                elif not self.is_kayit:
                    self.is_kayit = DevirService.is_olustur(
                        kaynak_donem_id=kid,
                        hedef_donem_id=hid,
                        kesim_tarihi=kesim,
                        acilis_tarihi=acilis,
                        devir_turu=self.tur_var.get(),
                        kapsam=kaps,
                    )
            if self.adim < 4:
                self.adim += 1
                self._adim_goster()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Devir", str(exc), parent=self)

    def _kontrol(self) -> None:
        if not self.is_kayit:
            messagebox.showwarning("Kontrol", "Önce dönem seçeneklerinden iş oluşturun (İleri).", parent=self)
            return
        try:
            sonuc = DevirService.on_kontrol(self.is_kayit["id"])
            self.is_kayit = DevirService.is_getir(self.is_kayit["id"]) or self.is_kayit
            h = len(sonuc.get("hatalar") or [])
            u = len(sonuc.get("uyarilar") or [])
            satirlar = []
            for x in (sonuc.get("hatalar") or [])[:8]:
                satirlar.append(f"Hata: {x.get('mesaj')}")
            for x in (sonuc.get("uyarilar") or [])[:8]:
                satirlar.append(f"Uyarı: {x.get('mesaj')}")
            messagebox.showinfo(
                "Kontrol",
                f"Sonuç: {sonuc.get('sonuc')}\nHata: {h}  Uyarı: {u}\n"
                + ("\n".join(satirlar) if satirlar else "Engelleyici sorun yok."),
                parent=self,
            )
            self._ozet_guncelle()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Kontrol", str(exc), parent=self)

    def _onizle(self) -> None:
        if not self.is_kayit:
            messagebox.showwarning("Ön İzleme", "Önce iş oluşturun (İleri).", parent=self)
            return
        try:
            paket = DevirService.onizleme_hesapla(self.is_kayit["id"])
            self.is_kayit = paket["is"]
            ozet = paket["ozet"]
            cari = (ozet.get("moduller") or {}).get("CARI") or {}
            stok = (ozet.get("moduller") or {}).get("STOK") or {}
            fin = (ozet.get("moduller") or {}).get("FINANS") or {}
            messagebox.showinfo(
                "Ön İzleme",
                "Veri değiştirilmedi.\n"
                f"Cari açık kalem: {cari.get('kalem_sayisi', '—')}\n"
                f"Stok satır: {stok.get('satir_sayisi', '—')}  "
                f"bilinen değer: {stok.get('deger_bilinen', '—')}\n"
                f"Finans hesap: {fin.get('hesap_sayisi', '—')}  "
                f"TL taşıma: {fin.get('tl_tasima_toplam', '—')}\n"
                f"İş durumu: {self.is_kayit.get('durum_etiket')}",
                parent=self,
            )
            self.btn_baslat.configure(
                state="normal" if self.is_kayit.get("onizleme_gecerli") else "disabled"
            )
            self._ozet_guncelle()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Ön İzleme", str(exc), parent=self)

    def _baslat(self) -> None:
        if not self.is_kayit or not self.is_kayit.get("onizleme_gecerli"):
            messagebox.showwarning(
                "Devri Başlat",
                "Önce geçerli bir ön izleme alın.",
                parent=self,
            )
            return
        ozet = (
            f"İş: {self.is_kayit.get('is_no')}\n"
            f"Tür: {self.is_kayit.get('devir_turu')}\n"
            f"Yedek: {'doğrulandı' if self.is_kayit.get('yedek_dogrulandi') else 'yok — alınacak'}\n\n"
            "Aynı firma DB’sinde ikinci fatura/stok hareketi üretilmez; "
            "açık kalemler eşleştirilir. Kesin devirde kaynak dönem kilitlenir."
        )
        if not messagebox.askyesno("Devri Başlat — Onay", ozet, parent=self):
            return
        try:
            if not self.is_kayit.get("yedek_dogrulandi"):
                DevirService.yedek_al_ve_dogrula(self.is_kayit["id"])
            sonuc = DevirService.uygula(self.is_kayit["id"])
            self.is_kayit = sonuc["is"]
            self.adim = 4
            self._adim_goster()
            messagebox.showinfo(
                "Devir",
                f"{sonuc.get('mesaj')}\nYeni eşleştirme: {sonuc.get('yeni_eslesme')}\n"
                f"Durum: {self.is_kayit.get('durum_etiket')}",
                parent=self,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Devri Başlat", str(exc), parent=self)
