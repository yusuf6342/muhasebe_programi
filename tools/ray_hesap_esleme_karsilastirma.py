"""Ray Mobilya: bağlı hesap eşleştirmeleri ile uygun alt hesap adaylarının karşılaştırması (salt okunur).

Gerçek DB'ye yazmaz: dosya ``mode=ro`` ile açılır, SQLite backup API ile TEMP kopyaya alınır,
tüm sorgular kopyada çalışır. Hiçbir eşleştirme seçilmez/değiştirilmez.

    python tools/ray_hesap_esleme_karsilastirma.py [--db yol] [--cikti inceleme/muhasebelestirme/Ray_Hesap_Esleme_Karsilastirma]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.tdhp_hesap_plani import fis_icin_alt_hesap_mi  # noqa: E402

VARSAYILAN_DB = Path(r"C:\Users\cigde\AppData\Local\MuhasebeProgrami\data\muhasebe.db")
KASA_ADAYLARI = ("100.01.0001", "100.01.0002")


def kopya_al(kaynak: Path) -> Path:
    hedef = Path(tempfile.mkdtemp(prefix="ray_esleme_rapor_")) / "muhasebe.db"
    src = sqlite3.connect(f"file:{kaynak.as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(hedef)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()
    return hedef


def uygunluk(c, h: dict, firma_id: int) -> str | None:
    """muhasebe_entegrasyon.hesap_uygunluk_sorunu ile aynı kurallar (saf SQL)."""
    if h["firma_id"] != firma_id:
        return "hesap bu firmada yok"
    if not h["aktif"]:
        return "pasif"
    if not fis_icin_alt_hesap_mi(h["hesap_kodu"]):
        return "ana/üst hesap (fiş yalnız 120.01.0001 biçimindeki alt hesaba yazılır)"
    alt = c.execute(
        "SELECT 1 FROM muhasebe_hesap_plani WHERE firma_id=? AND id<>? AND (ust_hesap_id=? OR hesap_kodu LIKE ?) LIMIT 1",
        (h["firma_id"], h["id"], h["id"], h["hesap_kodu"] + ".%"),
    ).fetchone()
    if alt:
        return "altında başka hesap var (kayıt kabul etmez)"
    if h["ust_hesap_id"]:
        ust = c.execute("SELECT hesap_kodu FROM muhasebe_hesap_plani WHERE id=?", (h["ust_hesap_id"],)).fetchone()
        if ust and not h["hesap_kodu"].startswith(ust[0] + "."):
            return f"üst hesabı ({ust[0]}) ile kod uyumsuz"
    return None


def kullanim(c, hesap_id: int) -> dict:
    r = c.execute(
        """SELECT COUNT(s.id),
                  SUM(CASE WHEN f.durum <> 'İptal' THEN 1 ELSE 0 END),
                  COALESCE(SUM(s.borc),0), COALESCE(SUM(s.alacak),0),
                  MAX(f.fis_tarihi), COUNT(DISTINCT s.fis_id)
           FROM muhasebe_fis_satirlari s JOIN muhasebe_fisleri f ON f.id = s.fis_id
           WHERE s.hesap_id = ?""",
        (hesap_id,),
    ).fetchone()
    borc, alacak = float(r[2] or 0), float(r[3] or 0)
    return {
        "fis_satiri_sayisi": int(r[0] or 0),
        "etkin_fis_satiri_sayisi": int(r[1] or 0),
        "fis_sayisi": int(r[5] or 0),
        "satir_borc_toplam": round(borc, 2),
        "satir_alacak_toplam": round(alacak, 2),
        "satir_bakiyesi": round(borc - alacak, 2),
        "son_kullanim_tarihi": r[4],
    }


def hesap_ozet(c, h: dict, firma_id: int) -> dict:
    return {
        "id": h["id"], "hesap_kodu": h["hesap_kodu"], "hesap_adi": h["hesap_adi"],
        "aktif": bool(h["aktif"]), "hesap_turu": h["hesap_turu"],
        "kayitli_borc_toplam": float(h["borc_toplam"] or 0), "kayitli_alacak_toplam": float(h["alacak_toplam"] or 0),
        "kayitli_bakiye": round(float(h["borc_toplam"] or 0) - float(h["alacak_toplam"] or 0), 2),
        "fise_uygunluk_sorunu": uygunluk(c, h, firma_id),
        **kullanim(c, h["id"]),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--db", type=Path, default=VARSAYILAN_DB)
    p.add_argument("--cikti", type=Path,
                   default=ROOT / "inceleme" / "muhasebelestirme" / "Ray_Hesap_Esleme_Karsilastirma")
    a = p.parse_args()
    kopya = kopya_al(a.db)
    c = sqlite3.connect(kopya)
    c.row_factory = sqlite3.Row
    firmalar = [dict(r) for r in c.execute("SELECT id, firma_kodu, unvan FROM firmalar")]
    firma_id = firmalar[0]["id"]

    def hesap(hid):
        r = c.execute("SELECT * FROM muhasebe_hesap_plani WHERE id=?", (hid,)).fetchone()
        return dict(r) if r else None

    eslemeler = []
    for e in c.execute("SELECT * FROM muhasebe_hesap_eslemeleri WHERE firma_id=? ORDER BY id", (firma_id,)).fetchall():
        if not e["hesap_id"]:
            continue
        h = hesap(e["hesap_id"])
        ana = h["hesap_kodu"].split(".")[0] if h else None
        adaylar = []
        if ana:
            for r in c.execute(
                "SELECT * FROM muhasebe_hesap_plani WHERE firma_id=? AND hesap_kodu LIKE ? ORDER BY hesap_kodu",
                (firma_id, ana + ".%"),
            ).fetchall():
                adaylar.append(hesap_ozet(c, dict(r), firma_id))
        eslemeler.append({
            "anahtar": e["anahtar"], "aciklama": e["aciklama"], "esleme_aktif": bool(e["aktif"]),
            "mevcut": hesap_ozet(c, h, firma_id) if h else None,
            "uygun_aday_sayisi": sum(1 for x in adaylar if x["fise_uygunluk_sorunu"] is None),
            "alt_hesaplar": adaylar,
        })

    kasa_kartlari = [dict(r) for r in c.execute(
        "SELECT id, hesap_adi, hesap_turu, alt_hesap_turu, aktif, acilis_bakiyesi FROM finans_hesaplari "
        "WHERE UPPER(hesap_turu)='KASA' ORDER BY id")]
    for k in kasa_kartlari:
        r = c.execute(
            "SELECT COUNT(*), MAX(tarih), COALESCE(SUM(CASE WHEN tutar IS NOT NULL THEN tutar END),0) "
            "FROM finans_hareketleri WHERE hesap_id=?", (k["id"],)).fetchone()
        k["finans_hareket_sayisi"], k["son_hareket_tarihi"] = int(r[0]), r[1]
    fh_kolonlari = [r[1] for r in c.execute("PRAGMA table_info('finans_hesaplari')")]
    muh_kolon = [k for k in fh_kolonlari if "muhasebe" in k or "hesap_kodu" in k or "hesap_plani" in k]

    kasa_detay = []
    for kod in KASA_ADAYLARI:
        r = c.execute("SELECT * FROM muhasebe_hesap_plani WHERE firma_id=? AND hesap_kodu=?", (firma_id, kod)).fetchone()
        if r is None:
            kasa_detay.append({"hesap_kodu": kod, "bulunamadi": True})
            continue
        oz = hesap_ozet(c, dict(r), firma_id)
        ad = (oz["hesap_adi"] or "").casefold()
        oz["ad_benzeri_kasa_karti"] = [k["hesap_adi"] for k in kasa_kartlari
                                       if k["hesap_adi"] and (k["hesap_adi"].casefold() in ad or ad in k["hesap_adi"].casefold())]
        oz["son_fisler"] = [dict(x) for x in c.execute(
            """SELECT f.fis_no, f.fis_tarihi, f.durum, f.kaynak_turu, s.borc, s.alacak, s.aciklama
               FROM muhasebe_fis_satirlari s JOIN muhasebe_fisleri f ON f.id=s.fis_id
               WHERE s.hesap_id=? ORDER BY f.fis_tarihi DESC, f.id DESC LIMIT 5""", (r["id"],))]
        kasa_detay.append(oz)

    rapor = {
        "uretim": datetime.now().isoformat(timespec="seconds"),
        "kaynak_db": str(a.db), "kopya_db": str(kopya), "yontem": "mode=ro + sqlite3 backup API, TEMP kopyada okuma",
        "firmalar": firmalar,
        "eslemeler": eslemeler,
        "kasa_adaylari": kasa_detay,
        "kasa_kartlari": kasa_kartlari,
        "kasa_karti_muhasebe_alani": muh_kolon or None,
        "not": "Otomatik seçim yapılmadı; hiçbir eşleştirme değiştirilmedi.",
    }
    a.cikti.parent.mkdir(parents=True, exist_ok=True)
    a.cikti.with_suffix(".json").write_text(json.dumps(rapor, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    a.cikti.with_suffix(".md").write_text(md(rapor), encoding="utf-8")
    print("Yazıldı:", a.cikti.with_suffix(".md"), a.cikti.with_suffix(".json"))


def tl(x) -> str:
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def md(r: dict) -> str:
    s = ["# Ray Mobilya — Hesap Eşleştirme Karşılaştırması", "",
         f"Üretim: {r['uretim']}  ", f"Kaynak: `{r['kaynak_db']}` ({r['yontem']})  ",
         f"Firma: {', '.join(f['firma_kodu'] + ' ' + f['unvan'] for f in r['firmalar'])}", "",
         "> Salt okunur rapor. **Otomatik seçim yapılmadı, hiçbir eşleştirme değiştirilmedi.** "
         "Bakiye: fiş satırlarından (iptal + ters fiş birbirini götürür) borç − alacak; "
         "'kayıtlı bakiye' hesap planındaki toplam alanlarıdır.", "",
         "## 1. Bağlı eşleştirmeler ve uygun alt hesap adayları", "",
         "| Eşleştirme | Mevcut hesap | Fişe uygun mu | Mevcut fiş satırı / bakiye | Uygun aday alt hesaplar (kod — ad, aktif, satır, bakiye) |",
         "|---|---|---|---|---|"]
    for e in r["eslemeler"]:
        m = e["mevcut"]
        uygun = [x for x in e["alt_hesaplar"] if x["fise_uygunluk_sorunu"] is None]
        ad_metni = "<br>".join(
            f"{x['hesap_kodu']} — {x['hesap_adi']} ({'aktif' if x['aktif'] else 'pasif'}, "
            f"{x['fis_satiri_sayisi']} satır, {tl(x['satir_bakiyesi'])})" for x in uygun) or "— yok (alt hesap açılmalı)"
        s.append(f"| {e['anahtar']} | {m['hesap_kodu']} — {m['hesap_adi']} | "
                 f"{'Evet' if m['fise_uygunluk_sorunu'] is None else 'Hayır: ' + m['fise_uygunluk_sorunu']} | "
                 f"{m['fis_satiri_sayisi']} / {tl(m['satir_bakiyesi'])} | {ad_metni} |")
    uygunsuz_alt = [(e["anahtar"], x) for e in r["eslemeler"] for x in e["alt_hesaplar"] if x["fise_uygunluk_sorunu"]]
    if uygunsuz_alt:
        s += ["", "Fişe uygun olmayan alt kayıtlar (aday değil):", ""]
        s += [f"- {a}: {x['hesap_kodu']} — {x['hesap_adi']}: {x['fise_uygunluk_sorunu']}" for a, x in uygunsuz_alt]
    s += ["", "## 2. Kasa adayları", "",
          "| Hesap | Ad | Aktif | Fişe uygun | Fiş satırı (etkin) | Fiş sayısı | Son kullanım | Satır bakiyesi | Kayıtlı bakiye |",
          "|---|---|---|---|---|---|---|---|---|"]
    for k in r["kasa_adaylari"]:
        if k.get("bulunamadi"):
            s.append(f"| {k['hesap_kodu']} | (hesap planında yok) | | | | | | | |")
            continue
        s.append(f"| {k['hesap_kodu']} | {k['hesap_adi']} | {'Evet' if k['aktif'] else 'Hayır'} | "
                 f"{'Evet' if k['fise_uygunluk_sorunu'] is None else k['fise_uygunluk_sorunu']} | "
                 f"{k['fis_satiri_sayisi']} ({k['etkin_fis_satiri_sayisi']}) | {k['fis_sayisi']} | "
                 f"{k['son_kullanim_tarihi'] or '—'} | {tl(k['satir_bakiyesi'])} | {tl(k['kayitli_bakiye'])} |")
    s += ["", "### Kasa kartı ilişkisi", ""]
    if r["kasa_karti_muhasebe_alani"]:
        s.append(f"Kasa kartında muhasebe alanı: {r['kasa_karti_muhasebe_alani']}")
    else:
        s.append("Kasa kartı tablosunda (`finans_hesaplari`) muhasebe hesap kodu / hesap planı ilişki alanı **yok**; "
                 "kasa kartı ile 100.01.xxxx hesapları arasında veritabanında bağ kurulmamış. Fiş, tüm kasa "
                 "kartları için tek `kasa` eşleştirmesini kullanır.")
    s += ["", "| Kasa kartı id | Ad | Aktif | Finans hareketi | Son hareket |", "|---|---|---|---|---|"]
    s += [f"| {k['id']} | {k['hesap_adi']} | {'Evet' if k['aktif'] else 'Hayır'} | {k['finans_hareket_sayisi']} | "
          f"{k['son_hareket_tarihi'] or '—'} |" for k in r["kasa_kartlari"]]
    for k in r["kasa_adaylari"]:
        if k.get("bulunamadi"):
            continue
        s += ["", f"**{k['hesap_kodu']} {k['hesap_adi']}** — ad benzerliği olan kasa kartı: "
              f"{', '.join(k['ad_benzeri_kasa_karti']) or 'yok'}"]
        if k["son_fisler"]:
            s.append("Son fiş satırları: " + "; ".join(
                f"{f['fis_no']} {f['fis_tarihi']} {f['durum']} B {tl(f['borc'] or 0)} A {tl(f['alacak'] or 0)}"
                for f in k["son_fisler"]))
        else:
            s.append("Hiç fiş satırında kullanılmamış.")
    s += ["", "## Sonuç", "", r["not"],
          "Seçim kullanıcıya aittir: Genel Muhasebe → Hesap Eşleştirmeleri ekranında ilgili satır seçilip "
          "'Hesap Bağla' ile fişe uygun alt hesap bağlanır."]
    return "\n".join(s) + "\n"


if __name__ == "__main__":
    main()
