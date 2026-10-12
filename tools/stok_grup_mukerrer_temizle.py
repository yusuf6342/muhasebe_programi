"""Açılış geçişinin ürettiği mükerrer stok gruplarını güvenli biçimde temizler.

Kullanım:
    python tools/stok_grup_mukerrer_temizle.py <firma.db> [--uygula] [--json cikti.json]

Kural:
- Yalnızca aynı firma DB'si, aynı seviye, aynı üst grup (parent_id) ve birebir aynı ad
  (Türkçe büyük/küçük harf duyarsız) taşıyan VE kodu geçişin ürettiği biçimde olan
  (ad'dan türetilen kod + isteğe bağlı sayı soneki) gruplar birleştirilir.
- Hayatta kalan kayıt en küçük id'dir; stok kartı (ana/tali/alt) ve alt grup (parent_id)
  bağlantıları önce ona taşınır, sonra kopya silinir.
- Gruba bağlı olmayan stoklar, rapor_grubu adı bir ana grupla birebir eşleşiyorsa
  (geçişin tasarlanan davranışı) o ana gruba bağlanır.
- Tümü tek işlemde; doğrulama başarısızsa geri alınır. Yeniden çalıştırınca değişiklik üretmez.
--uygula verilmezse yalnızca rapor üretir (kuru çalışma).
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sqlite3
import sys
from datetime import datetime


def ad_anahtari(metin: str | None) -> str:
    return " ".join((metin or "").strip().replace("İ", "i").replace("I", "ı").casefold().split())


def kod_uret(ad: str) -> str:
    temiz = re.sub(r"[^A-Za-z0-9ÇĞİÖŞÜçğıöşü]+", "", (ad or "").upper())
    return temiz[:20] or "GRUP"


def gecis_kodu_mu(kod: str | None, ad: str | None) -> bool:
    baz = ad_anahtari(kod_uret(ad or ""))
    k = ad_anahtari(kod)
    return k == baz or (k.startswith(baz) and k[len(baz):].isdigit())


def ref_kolonlari(c: sqlite3.Connection) -> list[tuple[str, str]]:
    sonuc = []
    for (t,) in c.execute("select name from sqlite_master where type='table'"):
        for col in c.execute(f'pragma table_info("{t}")'):
            ad = col[1]
            if (t == "stok_gruplari" and ad == "parent_id") or (
                t != "stok_gruplari" and ad in ("ana_grup_id", "tali_grup_id", "alt_grup_id")
            ):
                sonuc.append((t, ad))
    return sonuc


def anlik_durum(c: sqlite3.Connection, refs) -> dict:
    gruplar = {r[0]: r for r in c.execute("select id,kod,ad,seviye,parent_id from stok_gruplari")}
    bag = {}
    for t, k in refs:
        for rid, gid in c.execute(f'select rowid, "{k}" from "{t}" where "{k}" is not null'):
            g = gruplar.get(gid)
            bag[(t, k, rid)] = (g[3], ad_anahtari(g[2])) if g else ("YOK", gid)
    return {"grup": len(gruplar), "bag": bag}


def temizle(c: sqlite3.Connection) -> dict:
    refs = ref_kolonlari(c)
    once = anlik_durum(c, refs)
    birlesen = []
    for seviye in (1, 2, 3):
        while True:
            kume = collections.defaultdict(list)
            for gid, kod, ad, sev, parent in c.execute(
                "select id,kod,ad,seviye,parent_id from stok_gruplari where seviye=? order by id",
                (seviye,),
            ):
                if gecis_kodu_mu(kod, ad):
                    kume[(parent, ad_anahtari(ad))].append(gid)
            mukerrer = {k: v for k, v in kume.items() if len(v) > 1}
            if not mukerrer:
                break
            for (parent, key), ids in mukerrer.items():
                kalan, silinen = ids[0], ids[1:]
                tasinan = 0
                for t, k in refs:
                    for i in range(0, len(silinen), 500):
                        parca = silinen[i:i + 500]
                        ph = ",".join("?" * len(parca))
                        cur = c.execute(f'update "{t}" set "{k}"=? where "{k}" in ({ph})', [kalan, *parca])
                        tasinan += cur.rowcount
                for i in range(0, len(silinen), 500):
                    parca = silinen[i:i + 500]
                    c.execute(f"delete from stok_gruplari where id in ({','.join('?' * len(parca))})", parca)
                birlesen.append({"seviye": seviye, "parent_id": parent, "ad_anahtari": key,
                                 "kalan_id": kalan, "silinen_adet": len(silinen), "tasinan_bag": tasinan})

    ana = {}
    for gid, ad in c.execute(
        "select id, ad from stok_gruplari where seviye=1 and parent_id is null order by id"
    ):
        ana.setdefault(ad_anahtari(ad), gid)
    baglanan = collections.Counter()
    stoklar = c.execute(
        "select id, rapor_grubu from stok_kartlari where ana_grup_id is null "
        "and rapor_grubu is not null and rapor_grubu <> ''"
    ).fetchall()
    for sid, rg in stoklar:
        k = ad_anahtari(rg)
        hedef = ana.get(k)
        if hedef is None and " /" in k:
            hedef = ana.get(k.split(" /")[0].strip())
        if hedef is not None:
            c.execute("update stok_kartlari set ana_grup_id=? where id=? and ana_grup_id is null", (hedef, sid))
            baglanan[hedef] += 1

    sonra = anlik_durum(c, refs)
    hatalar = []
    for anahtar, deger in once["bag"].items():
        if sonra["bag"].get(anahtar) != deger:
            hatalar.append(f"bag degisti: {anahtar} {deger} -> {sonra['bag'].get(anahtar)}")
    yeni_bag = set(sonra["bag"]) - set(once["bag"])
    if len(yeni_bag) != sum(baglanan.values()):
        hatalar.append(f"yeni bag sayisi uyusmuyor: {len(yeni_bag)} != {sum(baglanan.values())}")
    if any(v[0] == "YOK" for v in sonra["bag"].values()):
        hatalar.append("olmayan gruba bag var")
    fk = c.execute("pragma foreign_key_check(stok_gruplari)").fetchall() + c.execute(
        "pragma foreign_key_check(stok_kartlari)").fetchall()
    if fk:
        hatalar.append(f"foreign_key_check: {fk[:5]}")
    return {
        "once_grup": once["grup"],
        "sonra_grup": sonra["grup"],
        "birlesen_kume": len(birlesen),
        "silinen_grup": sum(b["silinen_adet"] for b in birlesen),
        "tasinan_bag": sum(b["tasinan_bag"] for b in birlesen),
        "baglanan_stok": sum(baglanan.values()),
        "baglanan_stok_grup": {str(k): v for k, v in baglanan.items()},
        "kumeler": birlesen,
        "hatalar": hatalar,
    }


def yedekle(db: str) -> str:
    kok = os.path.join(os.path.dirname(os.path.abspath(db)), "yedekler")
    if os.path.basename(os.path.dirname(os.path.abspath(db))) == "companies":
        kok = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(db))), "yedekler")
    hedef_dir = os.path.join(kok, "stok_grup_temizlik_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    os.makedirs(hedef_dir)
    hedef = os.path.join(hedef_dir, os.path.basename(db))
    a = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    b = sqlite3.connect(hedef)
    a.backup(b)
    if b.execute("pragma integrity_check").fetchone()[0] != "ok":
        raise RuntimeError("yedek integrity_check basarisiz")
    for (t,) in a.execute("select name from sqlite_master where type='table'"):
        if a.execute(f'select count(*) from "{t}"').fetchone() != b.execute(f'select count(*) from "{t}"').fetchone():
            raise RuntimeError(f"yedek satir sayisi uyusmuyor: {t}")
    a.close()
    b.close()
    return hedef


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("db")
    p.add_argument("--uygula", action="store_true")
    p.add_argument("--json")
    a = p.parse_args()
    c = sqlite3.connect(a.db, isolation_level=None)
    if not c.execute("select 1 from sqlite_master where name='stok_gruplari'").fetchone():
        print(json.dumps({"db": a.db, "durum": "stok_gruplari tablosu yok"}, ensure_ascii=False))
        return 0
    yedek = None
    if a.uygula:
        c.close()
        yedek = yedekle(a.db)
        c = sqlite3.connect(a.db, isolation_level=None)
    c.execute("pragma foreign_keys=ON")
    c.execute("begin immediate")
    try:
        sonuc = temizle(c)
        if sonuc["hatalar"] or not a.uygula:
            c.execute("rollback")
        else:
            c.execute("commit")
    except Exception:
        c.execute("rollback")
        raise
    sonuc.update({"db": a.db, "uygulandi": bool(a.uygula and not sonuc["hatalar"]), "yedek": yedek})
    if sonuc["uygulandi"]:
        sonuc["integrity_check"] = c.execute("pragma integrity_check").fetchone()[0]
    c.close()
    ozet = {k: v for k, v in sonuc.items() if k not in ("kumeler", "baglanan_stok_grup")}
    print(json.dumps(ozet, ensure_ascii=False, indent=1))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(sonuc, f, ensure_ascii=False, indent=1)
    return 1 if sonuc["hatalar"] else 0


if __name__ == "__main__":
    sys.exit(main())
