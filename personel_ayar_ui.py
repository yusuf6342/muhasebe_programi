"""Personel Ayarları — mevzuat parametreleri, belge türleri, yetki özeti, değişiklik geçmişi.

Ham sözlük dökümü yerine tablolar ve türüne uygun düzenleme formu (DOC Personel Ayarları).
"""

from __future__ import annotations

import json
import tkinter as tk
from datetime import date, datetime
from tkinter import messagebox, ttk

from sqlalchemy import select

# Bilinen alan anahtarları → değer türü (gün / oran / tarih / bool / metin)
_ALAN_TUR = {
    "gun": "gun",
    "gun_oncesi": "gun",
    "gun_sonra": "gun",
    "takip_ay_gun": "gun",
    "min_hizmet_yil": "gun",
    "yas_18_alti_veya_50_ustu_min": "gun",
    "oran": "oran",
    "prim_orani": "oran",
    "yuzde": "oran",
    "tarih": "tarih",
    "yururluk": "tarih",
    "baslangic": "tarih",
    "bitis": "tarih",
    "takip_ay_sonu": "bool",
    "aktif": "bool",
}


def _para_turkce_ad(kod: str) -> str:
    sozluk = {
        "YILLIK_IZIN_GUN": "Yıllık izin günü",
        "YILLIK_IZIN_ASGARI": "Yıllık izin asgari süreleri",
        "IHBAR_SURESI": "İhbar süresi",
        "KIDEM_TAVANI": "Kıdem tavanı",
        "ASGARI_UCRET": "Asgari ücret",
        "SGK_ISVEREN": "SGK işveren oranı",
        "SGK_ISCI": "SGK işçi oranı",
        "ISSizlik_ISVEREN": "İşsizlik işveren oranı",
        "ISSizlik_ISCI": "İşsizlik işçi oranı",
        "SGK_4A_ISE_GIRIS": "SGK 4/a işe giriş süresi",
        "SGK_4A_AYRILIS": "SGK 4/a ayrılış süresi",
        "SGK_4A_MPHB": "SGK 4/a MPHB son tarih",
        "SGK_4A_PRIM_ODEME": "SGK 4/a prim ödeme son tarih",
    }
    return sozluk.get((kod or "").upper(), (kod or "").replace("_", " ").title())


def _belge_sinif_tr(kod: str) -> str:
    m = {
        "ZORUNLU": "Zorunlu",
        "KOSULLU": "Koşullu",
        "ISTEGE": "İsteğe bağlı",
        "ISTEGE_BAGLI": "İsteğe bağlı",
    }
    return m.get((kod or "").upper(), kod or "—")


def _gizlilik_tr(kod: str) -> str:
    m = {
        "NORMAL": "Normal",
        "HASSAS": "Hassas",
        "COK_HASSAS": "Çok hassas",
        "TIBBI": "Tıbbi",
        "ADLI": "Adli",
        "HASSAS_SAGLIK": "Hassas sağlık",
        "HASSAS_ADLI": "Hassas adli",
    }
    return m.get((kod or "").upper(), kod or "—")


def _deger_ozeti(deger_json: str | None) -> str:
    if not deger_json:
        return "—"
    try:
        veri = json.loads(deger_json)
    except (TypeError, json.JSONDecodeError):
        return (deger_json or "")[:80]
    if isinstance(veri, dict):
        if "hizmet_yil_esikleri" in veri:
            parcalar = []
            for sat in veri.get("hizmet_yil_esikleri") or []:
                mx = sat.get("max_yil")
                gun = sat.get("gun")
                parcalar.append(f"≤{mx or '∞'} yıl → {gun} gün")
            ekstra = []
            if "yas_18_alti_veya_50_ustu_min" in veri:
                ekstra.append(f"yaş min {veri['yas_18_alti_veya_50_ustu_min']} gün")
            return "; ".join(parcalar + ekstra) or "{}"
        parcalar = []
        for k, v in list(veri.items())[:6]:
            if k == "aciklama":
                continue
            tur = _alan_turu(k, v)
            if tur == "oran":
                try:
                    parcalar.append(f"{k}: %{float(v) * 100:g}" if float(v) <= 1 else f"{k}: %{v}")
                except (TypeError, ValueError):
                    parcalar.append(f"{k}: {v}")
            elif tur == "gun":
                parcalar.append(f"{k}: {v} gün")
            elif tur == "bool":
                parcalar.append(f"{k}: {'Evet' if v else 'Hayır'}")
            else:
                parcalar.append(f"{k}: {v}")
        return "; ".join(parcalar) if parcalar else "{}"
    return str(veri)[:120]


def _alan_turu(anahtar: str, deger) -> str:
    k = (anahtar or "").casefold()
    if k in _ALAN_TUR:
        return _ALAN_TUR[k]
    if "oran" in k or "yuzde" in k or k.endswith("_orani"):
        return "oran"
    if "tarih" in k or k.endswith("_date"):
        return "tarih"
    if isinstance(deger, bool):
        return "bool"
    if isinstance(deger, (int, float)) and not isinstance(deger, bool):
        if "gun" in k or k.endswith("_gun"):
            return "gun"
        if 0 <= float(deger) <= 1 and ("oran" in k or "prim" in k):
            return "oran"
        return "gun"
    return "metin"


def _parse_deger_json(raw: str | None):
    if not raw:
        return {}
    try:
        veri = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {"_ham": raw}
    if isinstance(veri, dict):
        return veri
    return {"_deger": veri}


def _mevzuat_formu(parent, parametre, *, on_kaydet) -> None:
    """Gün/oran/tarih/bool alanlarına uygun form; simpledialog kullanılmaz."""
    dlg = tk.Toplevel(parent)
    dlg.title(f"Mevzuat — {_para_turkce_ad(parametre.kod)}")
    dlg.transient(parent)
    dlg.grab_set()
    from ui_pencere import pencere_os_krom_ac

    pencere_os_krom_ac(dlg)
    dlg.minsize(520, 360)

    govde = ttk.Frame(dlg, padding=12)
    govde.pack(fill="both", expand=True)

    ttk.Label(
        govde,
        text=f"{_para_turkce_ad(parametre.kod)} (v{parametre.surum}) — kod: {parametre.kod}",
        wraplength=480,
    ).pack(anchor="w")
    ttk.Label(
        govde,
        text=(
            f"Kaynak: {parametre.resmi_kaynak or '—'} | Kontrol: {parametre.kontrol_tarihi} | "
            f"Yürürlük: {parametre.yururluk_baslangic}"
        ),
        wraplength=480,
    ).pack(anchor="w", pady=(2, 8))

    veri = _parse_deger_json(parametre.deger_json)
    alanlar: dict[str, tuple[str, tk.Variable]] = {}
    hata_lbl = ttk.Label(govde, text="", foreground="#b3261e", wraplength=480)
    form = ttk.Frame(govde)
    form.pack(fill="x", pady=4)

    esik_tree = None
    esik_satirlar: list[dict] = []

    if "hizmet_yil_esikleri" in veri and isinstance(veri.get("hizmet_yil_esikleri"), list):
        ttk.Label(form, text="Hizmet yılı eşikleri (gün)", font=("", 9, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 4)
        )
        esik_tree = ttk.Treeview(
            form, columns=("max_yil", "gun"), show="headings", height=4
        )
        esik_tree.heading("max_yil", text="Max hizmet yılı")
        esik_tree.heading("gun", text="Gün")
        esik_tree.column("max_yil", width=140)
        esik_tree.column("gun", width=80)
        esik_tree.grid(row=1, column=0, columnspan=2, sticky="we", pady=2)
        esik_satirlar = [dict(s) for s in veri["hizmet_yil_esikleri"]]
        for i, sat in enumerate(esik_satirlar):
            esik_tree.insert(
                "",
                "end",
                iid=str(i),
                values=(sat.get("max_yil") if sat.get("max_yil") is not None else "∞", sat.get("gun")),
            )

        def _esik_duzenle():
            sec = esik_tree.selection()
            if not sec:
                return
            idx = int(sec[0])
            sat = esik_satirlar[idx]
            ed = tk.Toplevel(dlg)
            ed.title("Eşik satırı")
            ed.transient(dlg)
            ed.grab_set()
            fr = ttk.Frame(ed, padding=10)
            fr.pack()
            mx_v = tk.StringVar(value="" if sat.get("max_yil") is None else str(sat.get("max_yil")))
            gun_v = tk.StringVar(value=str(sat.get("gun", "")))
            ttk.Label(fr, text="Max yıl (boş = ∞)").grid(row=0, column=0, sticky="w")
            ttk.Entry(fr, textvariable=mx_v, width=10).grid(row=0, column=1)
            ttk.Label(fr, text="Gün").grid(row=1, column=0, sticky="w")
            ttk.Spinbox(fr, from_=0, to=365, textvariable=gun_v, width=8).grid(row=1, column=1)

            def ok():
                try:
                    g = int(gun_v.get())
                    if g < 0:
                        raise ValueError("Gün negatif olamaz.")
                    mx_raw = (mx_v.get() or "").strip()
                    mx = None if mx_raw in ("", "∞", "None") else int(mx_raw)
                    if mx is not None and mx < 0:
                        raise ValueError("Max yıl negatif olamaz.")
                except ValueError as exc:
                    messagebox.showerror("Eşik", str(exc), parent=ed)
                    return
                esik_satirlar[idx] = {"max_yil": mx, "gun": g}
                esik_tree.item(sec[0], values=(mx if mx is not None else "∞", g))
                ed.destroy()

            ttk.Button(fr, text="Tamam", command=ok).grid(row=2, column=0, columnspan=2, pady=8)

        ttk.Button(form, text="Seçili eşiği düzenle", command=_esik_duzenle).grid(
            row=2, column=0, sticky="w", pady=4
        )
        row = 3
        for anahtar in ("yas_18_alti_veya_50_ustu_min", "min_hizmet_yil", "kaynak_not"):
            if anahtar not in veri:
                continue
            deger = veri[anahtar]
            tur = _alan_turu(anahtar, deger)
            ttk.Label(form, text=anahtar.replace("_", " ")).grid(row=row, column=0, sticky="w", pady=2)
            if tur == "gun":
                var = tk.StringVar(value=str(deger))
                ttk.Spinbox(form, from_=0, to=365, textvariable=var, width=10).grid(
                    row=row, column=1, sticky="w"
                )
            else:
                var = tk.StringVar(value=str(deger) if deger is not None else "")
                ttk.Entry(form, textvariable=var, width=36).grid(row=row, column=1, sticky="w")
            alanlar[anahtar] = (tur, var)
            row += 1
    elif "_ham" in veri:
        ttk.Label(
            form,
            text="Bu parametre yapılandırılmış alanlara dönüştürülemedi; değer okunur biçimde gösterilir. "
            "Yanlış genel düzenleyici açılmaz.",
            wraplength=460,
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        txt = tk.Text(form, height=6, wrap="word", width=60)
        txt.grid(row=1, column=0, columnspan=2, sticky="we", pady=4)
        txt.insert("1.0", veri["_ham"])
        txt.configure(state="disabled")
        hata_lbl.configure(text="Ham değer düzenlenemez; kaynak doğrulanmış yapı gerekir.")
    else:
        row = 0
        for anahtar, deger in veri.items():
            if isinstance(deger, (dict, list)):
                ttk.Label(form, text=f"{anahtar} (karmaşık)").grid(row=row, column=0, sticky="nw", pady=2)
                det = ttk.Label(form, text=json.dumps(deger, ensure_ascii=False)[:200], wraplength=320)
                det.grid(row=row, column=1, sticky="w")
                row += 1
                continue
            tur = _alan_turu(anahtar, deger)
            etiket = anahtar.replace("_", " ")
            if tur == "gun":
                etiket += " (gün)"
            elif tur == "oran":
                etiket += " (%)"
            elif tur == "tarih":
                etiket += " (YYYY-AA-GG)"
            ttk.Label(form, text=etiket).grid(row=row, column=0, sticky="w", pady=2)
            if tur == "gun":
                var = tk.StringVar(value=str(deger))
                ttk.Spinbox(form, from_=0, to=366, textvariable=var, width=10).grid(
                    row=row, column=1, sticky="w"
                )
            elif tur == "oran":
                try:
                    yuzde = float(deger) * 100 if float(deger) <= 1 else float(deger)
                except (TypeError, ValueError):
                    yuzde = deger
                var = tk.StringVar(value=str(yuzde))
                ttk.Entry(form, textvariable=var, width=12).grid(row=row, column=1, sticky="w")
            elif tur == "tarih":
                var = tk.StringVar(value=str(deger or ""))
                ttk.Entry(form, textvariable=var, width=14).grid(row=row, column=1, sticky="w")
            elif tur == "bool":
                var = tk.StringVar(value="Evet" if deger else "Hayır")
                ttk.Combobox(
                    form, textvariable=var, values=("Evet", "Hayır"), width=10, state="readonly"
                ).grid(row=row, column=1, sticky="w")
            else:
                var = tk.StringVar(value="" if deger is None else str(deger))
                ttk.Entry(form, textvariable=var, width=40).grid(row=row, column=1, sticky="w")
            alanlar[anahtar] = (tur, var)
            row += 1

    hata_lbl.pack(anchor="w", pady=(6, 0))
    gerekce_var = tk.StringVar()
    gf = ttk.Frame(govde)
    gf.pack(fill="x", pady=(8, 0))
    ttk.Label(gf, text="Gerekçe (zorunlu)").pack(side="left")
    ttk.Entry(gf, textvariable=gerekce_var, width=48).pack(side="left", padx=6)

    dirty = {"v": False}

    def _mark(*_a):
        dirty["v"] = True

    for _tur, var in alanlar.values():
        try:
            var.trace_add("write", _mark)
        except Exception:
            pass
    gerekce_var.trace_add("write", _mark)

    def _topla() -> str | None:
        hata_lbl.configure(text="")
        if "_ham" in veri:
            hata_lbl.configure(text="Ham değer bu formdan kaydedilemez.")
            return None
        yeni = dict(veri)
        if esik_tree is not None:
            yeni["hizmet_yil_esikleri"] = list(esik_satirlar)
        for anahtar, (tur, var) in alanlar.items():
            raw = (var.get() if hasattr(var, "get") else "") or ""
            raw = str(raw).strip()
            try:
                if tur == "gun":
                    if raw == "":
                        hata_lbl.configure(text=f"{anahtar}: gün sayısı zorunlu.")
                        return None
                    v = int(raw)
                    if v < 0:
                        hata_lbl.configure(text=f"{anahtar}: negatif gün kabul edilmez.")
                        return None
                    yeni[anahtar] = v
                elif tur == "oran":
                    if raw == "":
                        hata_lbl.configure(text=f"{anahtar}: oran zorunlu.")
                        return None
                    yuzde = float(raw.replace(",", "."))
                    if yuzde < 0:
                        hata_lbl.configure(text=f"{anahtar}: oran negatif olamaz.")
                        return None
                    # Formda yüzde gösterilir; kayıtta 0–1 oran saklanır (≤1 ise zaten oran)
                    yeni[anahtar] = yuzde if yuzde <= 1 else yuzde / 100.0
                elif tur == "tarih":
                    if not raw:
                        yeni[anahtar] = None
                        continue
                    date.fromisoformat(raw)
                    yeni[anahtar] = raw
                elif tur == "bool":
                    yeni[anahtar] = raw.casefold() in ("evet", "true", "1", "e")
                else:
                    yeni[anahtar] = raw
            except ValueError:
                hata_lbl.configure(text=f"{anahtar}: geçersiz değer veya tarih (YYYY-AA-GG).")
                return None
        return json.dumps(yeni, ensure_ascii=False)

    def kaydet():
        gerekce = (gerekce_var.get() or "").strip()
        if not gerekce:
            hata_lbl.configure(text="Gerekçe zorunludur.")
            return
        yeni_json = _topla()
        if yeni_json is None:
            return
        if yeni_json == parametre.deger_json:
            dlg.destroy()
            return
        try:
            on_kaydet(yeni_json, gerekce)
            dirty["v"] = False
            dlg.destroy()
        except Exception as exc:
            hata_lbl.configure(text=str(exc))

    def vazgec():
        if dirty["v"]:
            sec = messagebox.askyesnocancel(
                "Kaydedilmemiş değişiklik",
                "Kaydet / Değişiklikleri bırak / Geri dön",
                parent=dlg,
            )
            if sec is None:
                return
            if sec:
                kaydet()
                return
        dlg.destroy()

    dug = ttk.Frame(govde)
    dug.pack(fill="x", pady=(12, 0))
    ttk.Button(dug, text="Kaydet", command=kaydet).pack(side="left", padx=(0, 6))
    ttk.Button(dug, text="Vazgeç", command=vazgec).pack(side="left")
    dlg.protocol("WM_DELETE_WINDOW", vazgec)


def _belge_turu_formu(parent, tur, *, on_kaydet) -> None:
    dlg = tk.Toplevel(parent)
    dlg.title(f"Belge türü — {tur.ad}")
    dlg.transient(parent)
    dlg.grab_set()
    from ui_pencere import pencere_os_krom_ac

    pencere_os_krom_ac(dlg)
    fr = ttk.Frame(dlg, padding=12)
    fr.pack(fill="both", expand=True)

    ad_v = tk.StringVar(value=tur.ad or "")
    acik_v = tk.StringVar(value=getattr(tur, "aciklama", None) or "")
    sinif_v = tk.StringVar(value=tur.sinif or "ISTEGE_BAGLI")
    kosul_v = tk.StringVar(value=tur.uygulanma_kosulu or "")
    giz_v = tk.StringVar(value=tur.gizlilik or "NORMAL")
    dayanak_v = tk.StringVar(value=tur.hukuki_dayanak or "")
    aktif_v = tk.StringVar(value="Evet" if tur.aktif else "Hayır")
    hata = ttk.Label(fr, text="", foreground="#b3261e")

    satirlar = [
        ("Belge adı", ad_v, None),
        ("Açıklama", acik_v, None),
        ("Gereklilik", sinif_v, ("ZORUNLU", "KOSULLU", "ISTEGE_BAGLI")),
        ("Uygulanma koşulu", kosul_v, None),
        ("Gizlilik", giz_v, ("NORMAL", "HASSAS", "HASSAS_SAGLIK", "HASSAS_ADLI", "ADLI", "TIBBI")),
        ("Dayanak", dayanak_v, None),
        ("Aktif", aktif_v, ("Evet", "Hayır")),
    ]
    for i, (etiket, var, secenek) in enumerate(satirlar):
        ttk.Label(fr, text=etiket).grid(row=i, column=0, sticky="w", pady=2)
        if secenek:
            ttk.Combobox(fr, textvariable=var, values=secenek, width=36, state="readonly").grid(
                row=i, column=1, sticky="w"
            )
        else:
            ttk.Entry(fr, textvariable=var, width=40).grid(row=i, column=1, sticky="w")
    hata.grid(row=len(satirlar), column=0, columnspan=2, sticky="w")

    def kaydet():
        hata.configure(text="")
        if not (ad_v.get() or "").strip():
            hata.configure(text="Belge adı zorunlu.")
            return
        if sinif_v.get() == "KOSULLU" and not (kosul_v.get() or "").strip():
            hata.configure(text="Koşullu belgede uygulanma koşulu doldurulmalı.")
            return
        try:
            on_kaydet(
                {
                    "ad": ad_v.get().strip(),
                    "aciklama": (acik_v.get() or "").strip() or None,
                    "sinif": sinif_v.get(),
                    "uygulanma_kosulu": (kosul_v.get() or "").strip() or None,
                    "gizlilik": giz_v.get(),
                    "hukuki_dayanak": (dayanak_v.get() or "").strip() or None,
                    "aktif": aktif_v.get() == "Evet",
                }
            )
            dlg.destroy()
        except Exception as exc:
            hata.configure(text=str(exc))

    dug = ttk.Frame(fr)
    dug.grid(row=len(satirlar) + 1, column=0, columnspan=2, pady=10, sticky="w")
    ttk.Button(dug, text="Kaydet", command=kaydet).pack(side="left", padx=(0, 6))
    ttk.Button(dug, text="Vazgeç", command=dlg.destroy).pack(side="left")


def ayarlar_ekrani_goster(app) -> None:
    """Personel menüsünden çağrılır; sekmeli düzenli ayar ekranı."""
    app._icerigi_temizle()
    from personel_ui import _ust

    _ust(app, "PERSONEL AYARLARI")
    from database.database import get_session
    from database.models.personel import (
        PersonelBelgeTuru,
        PersonelErisimLog,
        PersonelMevzuatParametre,
    )
    from database.personel_sema import schema_hazirla
    from database.session_manager import oturum

    schema_hazirla()

    ttk.Label(
        app.icerik,
        text=(
            "Mevzuat parametreleri, belge kuralları ve erişim özeti. "
            "Süre/oranlar kaynak göstermeden sabitlenmez; geçmiş bordro kuralları korunur."
        ),
        wraplength=820,
    ).pack(anchor="w", pady=(8, 4))

    nb = ttk.Notebook(app.icerik)
    nb.pack(fill="both", expand=True, pady=6)

    # —— Mevzuat ——
    fr_m = ttk.Frame(nb, padding=6)
    nb.add(fr_m, text="Mevzuat Parametreleri")
    ust_m = ttk.Frame(fr_m)
    ust_m.pack(fill="x")
    ara_m = tk.StringVar()
    ttk.Label(ust_m, text="Ara:").pack(side="left")
    ttk.Entry(ust_m, textvariable=ara_m, width=24).pack(side="left", padx=4)
    kolon_m = ("ad", "kapsam", "deger", "yururluk", "durum", "kaynak")
    tab_m = ttk.Treeview(fr_m, columns=kolon_m, show="headings", height=14)
    for k, b, w in (
        ("ad", "Parametre adı", 180),
        ("kapsam", "Kapsam", 120),
        ("deger", "Değer / özet", 220),
        ("yururluk", "Yürürlük", 120),
        ("durum", "Durum", 80),
        ("kaynak", "Kaynak", 160),
    ):
        tab_m.heading(k, text=b)
        tab_m.column(k, width=w, anchor="w")
    tab_m.pack(fill="both", expand=True, pady=6)
    detay_m = ttk.Label(fr_m, text="", wraplength=780, foreground="#333")
    detay_m.pack(anchor="w")

    id_map_m: dict[str, int] = {}
    secili_m = {"id": None}

    def _mevzuat_doldur():
        onceki = secili_m["id"]
        tab_m.delete(*tab_m.get_children())
        id_map_m.clear()
        q = (ara_m.get() or "").strip().casefold()
        with get_session() as session:
            rows = list(
                session.scalars(
                    select(PersonelMevzuatParametre).order_by(
                        PersonelMevzuatParametre.kod, PersonelMevzuatParametre.surum
                    )
                )
            )
        for p in rows:
            ad = _para_turkce_ad(p.kod)
            if q and q not in ad.casefold() and q not in (p.kod or "").casefold():
                continue
            durum = "Aktif" if p.aktif else "Pasif"
            if p.yururluk_baslangic and p.yururluk_baslangic > date.today():
                durum = "Gelecek"
            iid = str(p.id)
            id_map_m[iid] = p.id
            tab_m.insert(
                "",
                "end",
                iid=iid,
                values=(
                    f"{ad} (v{p.surum})",
                    p.kapsam or "—",
                    _deger_ozeti(p.deger_json),
                    f"{p.yururluk_baslangic:%d.%m.%Y}" if p.yururluk_baslangic else "—",
                    durum,
                    (p.resmi_kaynak or "")[:40],
                ),
            )
        if onceki is not None and str(onceki) in id_map_m:
            tab_m.selection_set(str(onceki))
            tab_m.see(str(onceki))

    def _mevzuat_sec(_e=None):
        sec = tab_m.selection()
        if not sec:
            detay_m.configure(text="")
            secili_m["id"] = None
            return
        pid = id_map_m.get(sec[0])
        secili_m["id"] = pid
        with get_session() as session:
            p = session.get(PersonelMevzuatParametre, pid)
            if not p:
                return
            detay_m.configure(
                text=(
                    f"Kod: {p.kod} | Sürüm: {p.surum} | Kontrol: {p.kontrol_tarihi} | "
                    f"Onaylayan: {p.onaylayan or '—'} | Kaynak: {p.resmi_kaynak}\n"
                    f"Değer özeti: {_deger_ozeti(p.deger_json)}"
                )
            )

    def _mevzuat_duzenle():
        sec = tab_m.selection()
        if not sec:
            messagebox.showinfo("Mevzuat", "Düzenlemek için satır seçin.", parent=app)
            return
        from database.access import yetki_var

        if not yetki_var("personel_ayar", "sistem_ayarlari"):
            messagebox.showwarning("Yetki", "Mevzuat kuralı değiştirme yetkiniz yok.", parent=app)
            return
        pid = id_map_m.get(sec[0])
        with get_session() as session:
            p = session.get(PersonelMevzuatParametre, pid)
            if not p:
                return
            # Form oturum dışında kullanılsın diye alanları kopyala
            class _P:
                pass

            kopya = _P()
            for a in (
                "id",
                "kod",
                "surum",
                "deger_json",
                "resmi_kaynak",
                "kontrol_tarihi",
                "yururluk_baslangic",
            ):
                setattr(kopya, a, getattr(p, a))

        def _kaydet(yeni_json: str, gerekce: str):
            kullanici = getattr(oturum, "kullanici_adi", None) or getattr(oturum, "ad_soyad", None)
            if not kullanici:
                raise ValueError("Oturum yok; sahte kullanıcı ile kayıt yapılmaz.")
            with get_session() as session:
                kayit = session.get(PersonelMevzuatParametre, pid)
                if kayit is None:
                    raise ValueError("Kayıt bulunamadı; listeyi yenileyin.")
                if kayit.deger_json != kopya.deger_json:
                    raise ValueError(
                        "Kayıt başka oturumda değişmiş. Yenileyip kendi değişikliğinizi gözden geçirin."
                    )
                # Eski sürümü pasife al; yeni sürüm ekle (geçmiş bordro kural kimliği korunur)
                eski_surum = str(kayit.surum)
                try:
                    yeni_surum = str(int(eski_surum) + 1)
                except ValueError:
                    yeni_surum = f"{eski_surum}+1"
                eski_json = kayit.deger_json
                kayit.aktif = False
                yeni = PersonelMevzuatParametre(
                    kod=kayit.kod,
                    surum=yeni_surum,
                    deger_json=yeni_json,
                    resmi_kaynak=kayit.resmi_kaynak,
                    kontrol_tarihi=date.today(),
                    yururluk_baslangic=date.today(),
                    yururluk_bitis=None,
                    kapsam=kayit.kapsam,
                    aktif=True,
                    onaylayan=str(kullanici),
                )
                session.add(yeni)
                session.flush()
                session.add(
                    PersonelErisimLog(
                        kullanici=str(kullanici),
                        islem="MEVZUAT_DEGISTIR",
                        belge_id=None,
                        surum_id=yeni.id,
                        personel_id=None,
                        zaman=datetime.now(),
                        ayrinti=(
                            f"{kayit.kod} v{eski_surum}→v{yeni_surum} | "
                            f"{gerekce.strip()[:60]} | eski={eski_json[:40] if eski_json else ''}"
                        ),
                    )
                )
                session.commit()
                secili_m["id"] = yeni.id
            messagebox.showinfo(
                "Kayıt",
                "Yeni mevzuat sürümü kaydedildi; eski sürüm pasife alındı.",
                parent=app,
            )
            _mevzuat_doldur()
            _gecmis_doldur()

        parent = app.root if hasattr(app, "root") else app
        _mevzuat_formu(parent, kopya, on_kaydet=_kaydet)

    ttk.Button(ust_m, text="Yenile", command=_mevzuat_doldur).pack(side="right", padx=2)
    ttk.Button(ust_m, text="Düzenle", command=_mevzuat_duzenle).pack(side="right", padx=2)
    ara_m.trace_add("write", lambda *_a: _mevzuat_doldur())
    tab_m.bind("<<TreeviewSelect>>", _mevzuat_sec)
    _mevzuat_doldur()

    # —— Belge türleri ——
    fr_b = ttk.Frame(nb, padding=6)
    nb.add(fr_b, text="Belge Türleri")
    ust_b = ttk.Frame(fr_b)
    ust_b.pack(fill="x")
    kolon_b = ("ad", "gereklilik", "kosul", "erisim", "durum")
    tab_b = ttk.Treeview(fr_b, columns=kolon_b, show="headings", height=14)
    for k, b, w in (
        ("ad", "Belge adı", 200),
        ("gereklilik", "Gereklilik", 100),
        ("kosul", "Uygulanma koşulu", 220),
        ("erisim", "Erişim", 100),
        ("durum", "Durum", 80),
    ):
        tab_b.heading(k, text=b)
        tab_b.column(k, width=w, anchor="w")
    tab_b.pack(fill="both", expand=True, pady=6)
    id_map_b: dict[str, int] = {}

    def _belge_doldur():
        tab_b.delete(*tab_b.get_children())
        id_map_b.clear()
        with get_session() as session:
            rows = list(session.scalars(select(PersonelBelgeTuru).order_by(PersonelBelgeTuru.ad)))
        for t in rows:
            iid = str(t.id)
            id_map_b[iid] = t.id
            tab_b.insert(
                "",
                "end",
                iid=iid,
                values=(
                    t.ad,
                    _belge_sinif_tr(t.sinif),
                    (t.uygulanma_kosulu or "—")[:60],
                    _gizlilik_tr(t.gizlilik),
                    "Aktif" if t.aktif else "Pasif",
                ),
            )

    def _belge_duzenle():
        sec = tab_b.selection()
        if not sec:
            messagebox.showinfo("Belge", "Düzenlemek için satır seçin.", parent=app)
            return
        from database.access import yetki_var

        if not yetki_var("personel_ayar", "sistem_ayarlari"):
            messagebox.showwarning("Yetki", "Belge kuralı değiştirme yetkiniz yok.", parent=app)
            return
        tid = id_map_b.get(sec[0])
        with get_session() as session:
            t = session.get(PersonelBelgeTuru, tid)
            if not t:
                return

            class _T:
                pass

            kopya = _T()
            for a in (
                "id",
                "ad",
                "sinif",
                "uygulanma_kosulu",
                "gizlilik",
                "hukuki_dayanak",
                "aktif",
            ):
                setattr(kopya, a, getattr(t, a))
            kopya.aciklama = getattr(t, "aciklama", None)

        def _kaydet(veri: dict):
            kullanici = getattr(oturum, "kullanici_adi", None) or getattr(oturum, "ad_soyad", None)
            if not kullanici:
                raise ValueError("Oturum yok; sahte kullanıcı ile kayıt yapılmaz.")
            with get_session() as session:
                kayit = session.get(PersonelBelgeTuru, tid)
                if kayit is None:
                    raise ValueError("Belge türü bulunamadı.")
                eski = f"{kayit.ad}|{kayit.sinif}|{kayit.aktif}"
                kayit.ad = veri["ad"]
                kayit.sinif = veri["sinif"]
                kayit.uygulanma_kosulu = veri["uygulanma_kosulu"]
                kayit.gizlilik = veri["gizlilik"]
                kayit.hukuki_dayanak = veri["hukuki_dayanak"]
                kayit.aktif = bool(veri["aktif"])
                session.add(
                    PersonelErisimLog(
                        kullanici=str(kullanici),
                        islem="BELGE_TURU_DEGISTIR",
                        belge_id=None,
                        surum_id=kayit.id,
                        personel_id=None,
                        zaman=datetime.now(),
                        ayrinti=f"{eski} → {kayit.ad}|{kayit.sinif}|{kayit.aktif}",
                    )
                )
                session.commit()
            messagebox.showinfo("Kayıt", "Belge türü güncellendi. Geçmiş dosyalar silinmedi.", parent=app)
            _belge_doldur()
            _gecmis_doldur()

        parent = app.root if hasattr(app, "root") else app
        _belge_turu_formu(parent, kopya, on_kaydet=_kaydet)

    def _belge_aktif_toggle():
        sec = tab_b.selection()
        if not sec:
            return
        from database.access import yetki_var

        if not yetki_var("personel_ayar", "sistem_ayarlari"):
            messagebox.showwarning("Yetki", "Belge kuralı değiştirme yetkiniz yok.", parent=app)
            return
        tid = id_map_b.get(sec[0])
        with get_session() as session:
            t = session.get(PersonelBelgeTuru, tid)
            if not t:
                return
            t.aktif = not t.aktif
            session.commit()
        _belge_doldur()

    ttk.Button(ust_b, text="Yenile", command=_belge_doldur).pack(side="right", padx=2)
    ttk.Button(ust_b, text="Düzenle", command=_belge_duzenle).pack(side="right", padx=2)
    ttk.Button(ust_b, text="Aktif / Pasif", command=_belge_aktif_toggle).pack(side="right", padx=2)
    _belge_doldur()

    # —— Yetki özeti ——
    fr_y = ttk.Frame(nb, padding=6)
    nb.add(fr_y, text="Yetki ve Gizlilik")
    ttk.Label(
        fr_y,
        text=(
            "Bu ekran mevcut rol/izin modelini kullanır. "
            "personel_ayar, sistem_ayarlari ve hassas belge erişimi ayrı değerlendirilir. "
            "Çalışan sağlık/adli belge içerikleri burada listelenmez."
        ),
        wraplength=780,
    ).pack(anchor="w")
    kullanici = getattr(oturum, "kullanici_adi", None) or "—"
    rol = getattr(oturum, "role_kod", None) or getattr(oturum, "role_ad", None) or "—"
    ttk.Label(fr_y, text=f"Oturum: {kullanici}  |  Rol: {rol}", font=("", 10, "bold")).pack(
        anchor="w", pady=8
    )
    try:
        from database.access import yetki_var

        for kod, ad in (
            ("personel_ayar", "Personel ayarlarını görüntüle / değiştir"),
            ("sistem_ayarlari", "Sistem ayarları"),
            ("personel_duzenleme", "Personel kartı düzenleme"),
            ("personel_hassas_saglik", "Hassas sağlık belgesi"),
            ("personel_hassas_adli", "Hassas adli belge"),
        ):
            var = "Var" if yetki_var(kod) else "Yok"
            ttk.Label(fr_y, text=f"• {ad}: {var}").pack(anchor="w")
    except Exception as exc:
        ttk.Label(fr_y, text=f"Yetki tablosu okunamadı: {exc}", foreground="#b3261e").pack(anchor="w")

    # —— Geçmiş ——
    fr_g = ttk.Frame(nb, padding=6)
    nb.add(fr_g, text="Değişiklik Geçmişi")
    kolon_g = ("zaman", "kullanici", "alan", "ozet")
    tab_g = ttk.Treeview(fr_g, columns=kolon_g, show="headings", height=14)
    for k, b, w in (
        ("zaman", "Zaman", 140),
        ("kullanici", "Kullanıcı", 120),
        ("alan", "Kayıt", 180),
        ("ozet", "Özet", 280),
    ):
        tab_g.heading(k, text=b)
        tab_g.column(k, width=w, anchor="w")
    tab_g.pack(fill="both", expand=True)

    def _gecmis_doldur():
        tab_g.delete(*tab_g.get_children())
        with get_session() as session:
            rows = list(
                session.scalars(
                    select(PersonelErisimLog)
                    .where(
                        PersonelErisimLog.islem.in_(
                            ("MEVZUAT_DEGISTIR", "BELGE_TURU_DEGISTIR")
                        )
                    )
                    .order_by(PersonelErisimLog.zaman.desc())
                    .limit(200)
                )
            )
        for g in rows:
            tab_g.insert(
                "",
                "end",
                values=(
                    g.zaman.strftime("%d.%m.%Y %H:%M") if g.zaman else "—",
                    g.kullanici or "—",
                    g.islem,
                    (g.ayrinti or "")[:80],
                ),
            )

    ttk.Button(fr_g, text="Yenile", command=_gecmis_doldur).pack(anchor="e", pady=4)
    _gecmis_doldur()

    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: ayarlar_ekrani_goster(app))
