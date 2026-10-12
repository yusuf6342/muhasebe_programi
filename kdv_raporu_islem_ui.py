"""KDV raporu işlemleri: belge KDV bilgisi, iade kaynak bağlama / 'kaynak yok', hatalı fiş düzeltme.

Hiçbiri fatura tutarını, stok, cari veya tahsilat hareketini değiştirmez. Fiş düzeltmesi yalnız
kullanıcının seçtiği belgeler için, önizleme ve onaydan sonra yapılır.
"""

from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import messagebox, simpledialog, ttk
from typing import Any

from satin_alma_rapor_ui import bicimle
from satis_tema import ACIK_BG, IKINCIL, font, tk_buton

from database import kdv_rapor_service as srv

BELIRTILMEMIS = "Belirtilmemiş"


def _yetki(*kodlar) -> bool:
    try:
        from database.access import yetki_var

        return bool(yetki_var(*kodlar))
    except Exception:  # noqa: BLE001
        return True


def _yenile(ekran) -> None:
    if ekran is not None:
        try:
            ekran.raporla()
        except Exception:  # noqa: BLE001
            pass


def _liste(parent, kolonlar, height=12, coklu=False) -> ttk.Treeview:
    agac = ttk.Treeview(parent, columns=[k for k, _b, _g in kolonlar], show="headings", height=height,
                        selectmode="extended" if coklu else "browse")
    for k, b, g in kolonlar:
        agac.heading(k, text=b)
        agac.column(k, width=g, anchor="e" if k in ("toplam", "tutar", "fis_kdv", "beklenen", "fark", "borc",
                                                     "alacak", "ortak") else "w", stretch=False)
    agac.tag_configure("uyari", background="#FFF4E0")
    agac.tag_configure("soluk", foreground="#888888")
    return agac


# ----------------------------------------------------------------------------- KDV bilgisi
def kdv_bilgisi_penceresi(app, belgeler: list[dict], ekran=None) -> tk.Toplevel | None:
    """Seçili belge(ler) için indirilebilirlik / işlem türü. Tek belgede mevcut değer gelir."""
    from database import kdv_belge_bilgi_service as kb
    from database.models.kdv_belge_bilgisi import INDIRILEBILIRLIK_SECENEKLERI, ISLEM_TURLERI, ISTISNA, TEVKIFAT

    belgeler = [b for b in belgeler if b.get("id") and b.get("tur") in kb.RAPOR_TURU]
    if not belgeler:
        messagebox.showinfo("KDV Bilgisi", "Belgeler sekmesinde bir veya daha çok belge seçin.", parent=app)
        return None
    if not _yetki(kb.DUZENLEME_YETKISI):
        messagebox.showwarning("KDV Bilgisi", "Belge KDV bilgisini düzenleme yetkiniz yok.", parent=app)
        return None
    alis = all(b["tur"] in kb.ALIS_TARAFI for b in belgeler)
    karisik = not alis and any(b["tur"] in kb.ALIS_TARAFI for b in belgeler)
    mevcut = kb.belge_bilgisi(belgeler[0]["tur"], belgeler[0]["id"]) if len(belgeler) == 1 else {}

    pencere = tk.Toplevel(app)
    pencere.title("KDV Bilgisi")
    pencere.configure(bg=ACIK_BG)
    pencere.transient(app)
    baslik = (f"{belgeler[0].get('tur_adi', '')} {belgeler[0].get('no', '')}" if len(belgeler) == 1
              else f"{len(belgeler)} belge (seçilenlere aynı bilgi uygulanır)")
    tk.Label(pencere, text=baslik, bg=ACIK_BG, font=font(10, "bold", app)).pack(anchor="w", padx=12, pady=(10, 2))
    tk.Label(pencere, text=(
        "Fatura tutarı, stok, cari ve muhasebe fişi değişmez; yalnız KDV raporundaki sınıflandırma değişir. "
        "Boş bırakılan alan 'Belirtilmemiş' kalır. Uygulanan kurallar yalnız raporda doğrulanmış olanlardır; "
        "özel matrah / ihraç kayıtlı / iade hakkı doğuran işlemler raporda ayrı 'desteklenmeyen' satırında "
        "gösterilir."), bg=ACIK_BG, fg=IKINCIL, justify="left", wraplength=520,
        font=font(9, "normal", app)).pack(anchor="w", padx=12)
    form = tk.Frame(pencere, bg=ACIK_BG)
    form.pack(fill="x", padx=12, pady=8)

    def satir(etiket, w, r):
        tk.Label(form, text=etiket, bg=ACIK_BG, font=font(9, "normal", app)).grid(row=r, column=0, sticky="w",
                                                                                pady=3)
        w.grid(row=r, column=1, sticky="w", padx=8, pady=3)

    ind_ad = [BELIRTILMEMIS] + list(INDIRILEBILIRLIK_SECENEKLERI.values())
    ind = ttk.Combobox(form, values=ind_ad, state="readonly" if alis else "disabled", width=34)
    ind.set(INDIRILEBILIRLIK_SECENEKLERI.get(mevcut.get("indirilebilirlik"), BELIRTILMEMIS))
    satir("İndirilebilirlik (alış tarafı)", ind, 0)
    islem_ad = [BELIRTILMEMIS] + list(ISLEM_TURLERI.values())
    islem = ttk.Combobox(form, values=islem_ad, state="readonly", width=34)
    islem.set(ISLEM_TURLERI.get(mevcut.get("islem_turu"), BELIRTILMEMIS))
    satir("İşlem türü", islem, 1)
    tev = tk.Frame(form, bg=ACIK_BG)
    pay = ttk.Spinbox(tev, from_=1, to=10, width=4)
    payda = ttk.Spinbox(tev, from_=1, to=10, width=4)
    pay.set(str(mevcut.get("tevkifat_pay") or ""))
    payda.set(str(mevcut.get("tevkifat_payda") or 10))
    pay.pack(side="left")
    tk.Label(tev, text=" / ", bg=ACIK_BG).pack(side="left")
    payda.pack(side="left")
    satir("Tevkifat oranı (yalnız tevkifatlı)", tev, 2)
    istisna = ttk.Entry(form, width=14)
    istisna.insert(0, mevcut.get("istisna_kodu") or "")
    satir("İstisna kodu (yalnız istisna)", istisna, 3)
    aciklama = ttk.Entry(form, width=50)
    aciklama.insert(0, mevcut.get("aciklama") or "")
    satir("Açıklama", aciklama, 4)
    if karisik:
        tk.Label(pencere, text="Seçimde satış tarafı belge de var: indirilebilirlik alanı kapalı.", bg=ACIK_BG,
                 fg=IKINCIL, font=font(9, "normal", app)).pack(anchor="w", padx=12)

    def kodu(ad: str, secenekler: dict) -> str | None:
        for k, v in secenekler.items():
            if v == ad:
                return k
        return None

    def kaydet():
        alanlar: dict[str, Any] = {"islem_turu": kodu(islem.get(), ISLEM_TURLERI),
                                   "aciklama": aciklama.get()}
        if alanlar["islem_turu"] == TEVKIFAT:
            alanlar["tevkifat_pay"], alanlar["tevkifat_payda"] = pay.get(), payda.get()
        if alanlar["islem_turu"] == ISTISNA:
            alanlar["istisna_kodu"] = istisna.get()
        if alis:
            alanlar["indirilebilirlik"] = kodu(ind.get(), INDIRILEBILIRLIK_SECENEKLERI)
        try:
            if len(belgeler) == 1:
                kb.bilgi_kaydet(belgeler[0]["tur"], belgeler[0]["id"], **alanlar)
            else:
                if not messagebox.askyesno("KDV Bilgisi", f"{len(belgeler)} belgeye aynı bilgi uygulansın mı?",
                                           parent=pencere):
                    return
                kb.toplu_bilgi_kaydet([(b["tur"], b["id"]) for b in belgeler], **alanlar)
        except Exception as hata:  # noqa: BLE001
            messagebox.showwarning("KDV Bilgisi", str(hata), parent=pencere)
            return
        pencere.destroy()
        _yenile(ekran)

    butonlar = tk.Frame(pencere, bg=ACIK_BG)
    butonlar.pack(fill="x", padx=12, pady=(4, 12))
    tk_buton(butonlar, "Kaydet", kaydet, rol="kaydet").pack(side="left")
    tk_buton(butonlar, "Vazgeç", pencere.destroy, rol="iptal").pack(side="right")
    pencere.kaydet = kaydet
    pencere.alanlar = {"indirilebilirlik": ind, "islem_turu": islem, "pay": pay, "payda": payda,
                       "istisna": istisna, "aciklama": aciklama}
    return pencere


# ----------------------------------------------------------------------------- iade kaynağı
def _iade_mi(r: dict | None) -> bool:
    return bool(r and r.get("id") and r.get("tur") in (srv.SATIS_IADE, srv.ALIS_IADE))


def kaynak_bagla_penceresi(app, r: dict, ekran=None) -> tk.Toplevel | None:
    """Kullanıcı seçer: aynı carinin iade tarihine kadarki faturaları; program kendiliğinden bağlamaz."""
    from database import kdv_belge_bilgi_service as kb

    if not _iade_mi(r):
        messagebox.showinfo("Kaynak Bağla", "Bir satış veya alış iadesi seçin.", parent=app)
        return None
    if not _yetki(kb.DUZENLEME_YETKISI):
        messagebox.showwarning("Kaynak Bağla", "İade kaynak bağlantısını düzenleme yetkiniz yok.", parent=app)
        return None
    try:
        adaylar = kb.kaynak_adaylari(r["tur"], r["id"])
    except Exception as hata:  # noqa: BLE001
        messagebox.showwarning("Kaynak Bağla", str(hata), parent=app)
        return None
    pencere = tk.Toplevel(app)
    pencere.title(f"Kaynak Fatura Bağla — {r.get('no', '')}")
    pencere.geometry("760x460")
    pencere.configure(bg=ACIK_BG)
    tk.Label(pencere, text=(
        f"{r.get('tur_adi', '')} {r.get('no', '')} · {r.get('cari', '')}\nListe: aynı carinin iade tarihine kadarki "
        "iptal olmayan faturaları (iadedeki ürünleri içerenler üstte). Seçim sizindir; tutar, stok, cari ve fiş "
        "değişmez. Satır bağlantısı yalnız ürün faturada tek satırda ve miktar yeterliyse kurulur."),
        bg=ACIK_BG, fg=IKINCIL, justify="left", wraplength=720, font=font(9, "normal", app)).pack(
        anchor="w", padx=12, pady=(10, 6))
    kolonlar = (("no", "Fatura no", 130), ("tarih", "Tarih", 90), ("toplam", "Toplam", 120),
                ("ortak", "Ortak ürün", 110), ("secili", "Mevcut bağlantı", 120))
    agac = _liste(pencere, kolonlar)
    for i, a in enumerate(adaylar):
        agac.insert("", "end", iid=str(i), values=(
            a["no"], a["tarih"].strftime("%d.%m.%Y"), bicimle(a["toplam"], "para"),
            f"{a['ortak_urun']} / {a['urun_sayisi']}", "Evet" if a["secili"] else ""))
    agac.pack(fill="both", expand=True, padx=12)
    if not adaylar:
        tk.Label(pencere, text="Uygun fatura yok. Kaynak programda değilse 'Kaynak Yok Kaydet' kullanın.",
                 bg=ACIK_BG, fg=IKINCIL, font=font(9, "normal", app)).pack(anchor="w", padx=12)

    def bagla():
        sec = agac.selection()
        if not sec:
            messagebox.showinfo("Kaynak Bağla", "Bir fatura seçin.", parent=pencere)
            return
        a = adaylar[int(sec[0])]
        if not messagebox.askyesno("Kaynak Bağla", f"{r.get('no', '')} iadesi {a['no']} faturasına bağlansın mı?",
                                   parent=pencere):
            return
        try:
            s = kb.kaynak_bagla(r["tur"], r["id"], a["id"])
        except Exception as hata:  # noqa: BLE001
            messagebox.showwarning("Kaynak Bağla", str(hata), parent=pencere)
            return
        mesaj = f"Bağlandı: {s['iade_no']} → {s['fatura_no']}. Satır bağlantısı: {s['satir_baglandi']}."
        if s["bagsiz"]:
            mesaj += "\nBağlanamayan satırlar (raporda gösterilir):\n" + "\n".join(s["bagsiz"][:15])
        messagebox.showinfo("Kaynak Bağla", mesaj, parent=pencere)
        pencere.destroy()
        _yenile(ekran)

    butonlar = tk.Frame(pencere, bg=ACIK_BG)
    butonlar.pack(fill="x", padx=12, pady=8)
    tk_buton(butonlar, "Seçili Faturaya Bağla", bagla, rol="kaydet").pack(side="left")
    tk_buton(butonlar, "Kapat", pencere.destroy, rol="iptal").pack(side="right")
    pencere.agac, pencere.adaylar, pencere.bagla = agac, adaylar, bagla
    return pencere


def kaynak_yok_kaydet(app, r: dict, ekran=None) -> bool:
    from database import kdv_belge_bilgi_service as kb

    if not _iade_mi(r):
        messagebox.showinfo("Kaynak Yok", "Bir satış veya alış iadesi seçin.", parent=app)
        return False
    neden = simpledialog.askstring(
        "Kaynak Yok", f"{r.get('no', '')}: kaynak fatura programda neden yok?\n(ör. 'Devir öncesi satış', "
                      "'Geçmiş dönem — EVO öncesi')", parent=app)
    if not neden:
        return False
    try:
        kb.kaynak_yok_kaydet(r["tur"], r["id"], neden)
    except Exception as hata:  # noqa: BLE001
        messagebox.showwarning("Kaynak Yok", str(hata), parent=app)
        return False
    _yenile(ekran)
    return True


# ----------------------------------------------------------------------------- hatalı fişler
def hatali_fis_penceresi(app, bas: date, bit: date, ekran=None) -> tk.Toplevel | None:
    from database import kdv_fis_duzeltme_service as dz

    try:
        sonuc = dz.hatali_fisler(bas, bit)
    except Exception as hata:  # noqa: BLE001
        messagebox.showwarning("Hatalı KDV Fişleri", str(hata), parent=app)
        return None
    pencere = tk.Toplevel(app)
    pencere.title(f"KDV'si Hatalı Muhasebe Fişleri — {bas:%d.%m.%Y} – {bit:%d.%m.%Y}")
    pencere.geometry("1250x620")
    pencere.configure(bg=ACIK_BG)
    tk.Label(pencere, text=(
        "Belgeye bağlı fişteki KDV, belgenin doğrulanmış KDV'sinden farklı olanlar. Geçmiş fişler değiştirilmez; "
        "düzeltme yalnız seçtiğiniz belgeler için, önizlemeden sonra, belge tarihinde yalnız fark kadar ayrı bir "
        "'KDV düzeltme fişi' ile yapılır (KDV hesabı ↔ matrah hesabı). Cari, stok ve tahsilat kayıtlarına "
        "dokunulmaz; öncesinde doğrulanmış yedek alınır; kapalı dönemde yapılmaz; tekrar çalıştırmak ikinci fiş "
        "yazmaz."), bg=ACIK_BG, fg=IKINCIL, justify="left", wraplength=1200, font=font(9, "normal", app)).pack(
        anchor="w", padx=12, pady=(10, 6))
    kolonlar = (("tarih", "Tarih", 80), ("tur", "Tür", 130), ("no", "Belge no", 110), ("cari", "Cari", 170),
                ("fis_no", "Fiş no", 95), ("duz", "Düzeltme fişi", 95), ("fis_kdv", "Fişteki KDV", 100),
                ("beklenen", "Beklenen KDV", 100), ("fark", "Fark", 90), ("durum", "Durum", 190),
                ("aciklama", "Açıklama", 400))
    agac = _liste(pencere, kolonlar, height=16, coklu=True)
    rows = sonuc["satirlar"]

    def doldur():
        agac.delete(*agac.get_children())
        for i, r in enumerate(rows):
            agac.insert("", "end", iid=str(i), tags=(r.get("_etiket"),) if r.get("_etiket") else (), values=(
                r["tarih"].strftime("%d.%m.%Y"), r["tur_adi"], r["no"], r["cari"], r["fis_no"],
                r["duzeltme_fis_no"], bicimle(r["fis_kdv"], "para"), bicimle(r["beklenen_kdv"], "para"),
                bicimle(r["fark"], "para"), r["durum"], r["aciklama"]))

    doldur()
    agac.pack(fill="both", expand=True, padx=12)
    bilgi = tk.Label(pencere, text=sonuc.get("mesaj") or f"{len(rows)} belge listelendi.", bg=ACIK_BG, fg=IKINCIL,
                     font=font(9, "normal", app))
    bilgi.pack(anchor="w", padx=12)

    def secili() -> list[dict]:
        return [rows[int(i)] for i in agac.selection()]

    def onizleme():
        sec = secili()
        if len(sec) != 1:
            messagebox.showinfo("Önizleme", "Önizleme için tek belge seçin.", parent=pencere)
            return
        try:
            o = dz.duzeltme_onizleme(sec[0]["tur"], sec[0]["id"])
        except Exception as hata:  # noqa: BLE001
            messagebox.showwarning("Önizleme", str(hata), parent=pencere)
            return
        onizleme_penceresi(pencere, o)

    def evrak():
        sec = secili()
        if sec:
            from kdv_raporu_ui import evrak_ac

            evrak_ac(app, sec[0]["tur"], sec[0]["id"])

    def duzelt():
        sec = [r for r in secili() if r.get("duzeltilebilir")]
        if not sec:
            messagebox.showinfo("Düzelt", "Düzeltilebilir durumda bir veya daha çok belge seçin (önce önizleme alın).",
                                parent=pencere)
            return
        if not _yetki(dz.DUZELTME_YETKISI):
            messagebox.showwarning("Düzelt", "KDV fişi düzeltme yetkiniz yok (yönetici gerekir).", parent=pencere)
            return
        gerekce = simpledialog.askstring("Düzeltme gerekçesi",
                                         f"{len(sec)} belge için düzeltme fişi yazılacak. Gerekçe:", parent=pencere)
        if not gerekce:
            return
        if not messagebox.askyesno("Düzelt", (
                f"{len(sec)} belge için belge tarihinde KDV düzeltme fişi yazılacak.\nÖnce veritabanı yedeği alınır. "
                "Devam edilsin mi?"), parent=pencere):
            return
        try:
            s = dz.duzelt([(r["tur"], r["id"]) for r in sec], gerekce)
        except Exception as hata:  # noqa: BLE001
            messagebox.showwarning("Düzelt", str(hata), parent=pencere)
            return
        satirlar = [f"Yazılan düzeltme fişi: {len(s['yazilan'])}", f"Zaten doğru: {len(s['zaten_dogru'])}",
                    f"Atlanan: {len(s['atlanan'])}"]
        satirlar += [f"  {no}: {neden}" for no, neden in s["atlanan"][:10]]
        if s["yedek"]:
            satirlar.append(f"Yedek: {s['yedek']}")
        messagebox.showinfo("Düzelt", "\n".join(satirlar), parent=pencere)
        try:
            rows[:] = dz.hatali_fisler(bas, bit)["satirlar"]
        except Exception:  # noqa: BLE001
            pass
        doldur()
        _yenile(ekran)

    butonlar = tk.Frame(pencere, bg=ACIK_BG)
    butonlar.pack(fill="x", padx=12, pady=8)
    tk_buton(butonlar, "Düzeltme Önizlemesi", onizleme, rol="duzenle").pack(side="left")
    tk_buton(butonlar, "Evrakı Aç", evrak, rol="duzenle").pack(side="left", padx=6)
    db = tk_buton(butonlar, "Seçilenleri Düzelt…", duzelt, rol="kaydet")
    db.pack(side="left", padx=6)
    if not _yetki(dz.DUZELTME_YETKISI):
        db.configure(state="disabled")
        tk.Label(butonlar, text="Düzeltme yetkiniz yok (yalnız görüntüleme).", bg=ACIK_BG, fg=IKINCIL,
                 font=font(9, "normal", app)).pack(side="left", padx=8)
    tk_buton(butonlar, "Kapat", pencere.destroy, rol="iptal").pack(side="right")
    pencere.agac, pencere.satirlar = agac, rows
    return pencere


def onizleme_penceresi(parent, o: dict) -> tk.Toplevel:
    p = tk.Toplevel(parent)
    p.title(f"Düzeltme Önizlemesi — {o['no']}")
    p.geometry("820x380")
    p.configure(bg=ACIK_BG)
    ust = (f"{o['tur_adi']} {o['no']} · {o['cari']} · belge tarihi {o['tarih']:%d.%m.%Y}\n"
           f"Mevcut fiş: {o['fis_no'] or '—'}   Fişteki KDV: {bicimle(o['fis_kdv'], 'para')}   "
           f"Beklenen: {bicimle(o['beklenen_kdv'], 'para')}   Fark: {bicimle(o['fark'], 'para')}")
    tk.Label(p, text=ust, bg=ACIK_BG, justify="left", font=font(10, "bold", p)).pack(anchor="w", padx=12, pady=(10, 4))
    if o["satirlar"]:
        tk.Label(p, text=f"Yazılacak düzeltme fişi ({o['fis_tarihi']:%d.%m.%Y}, kaynak {o['kaynak_turu']}):",
                 bg=ACIK_BG, fg=IKINCIL, font=font(9, "normal", p)).pack(anchor="w", padx=12)
        agac = _liste(p, (("hesap", "Hesap", 140), ("ad", "Hesap adı", 300), ("borc", "Borç", 110),
                          ("alacak", "Alacak", 110)), height=4)
        for i, s in enumerate(o["satirlar"]):
            agac.insert("", "end", iid=str(i), values=(s["hesap_kodu"], s["hesap_adi"], bicimle(s["borc"], "para"),
                                                       bicimle(s["alacak"], "para")))
        agac.pack(fill="x", padx=12, pady=4)
    durum = "Düzeltilebilir." if o["duzeltilebilir"] else f"Düzeltilemez: {o['neden']}"
    tk.Label(p, text=durum, bg=ACIK_BG, fg="#1B5E20" if o["duzeltilebilir"] else "#B71C1C", justify="left",
             wraplength=780, font=font(9, "bold", p)).pack(anchor="w", padx=12, pady=6)
    tk_buton(p, "Kapat", p.destroy, rol="iptal").pack(anchor="e", padx=12, pady=8)
    return p
