"""22 riskli cari — 31.08.2026 kapanış kanıtı (15 önce, kalan 7).

finans_jq max 1 yıl; boşluksuz 01.09.(N-1)–31.08.N dilimleri.
Devreden yalnız en eski dolu dilimde açılış sayılır (mükerrer yok).
Özet 31.08 kanıtı değildir. Salt okuma. Stok çekmez. K05 açmaz.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.cari22_kapanis_kanit
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from tools.dnm_d1._ortak import CALISMA, KAYNAK, dec, oturum_gecersiz_mi, parse_tarih, yaz_json, yaz_kaynak
from tools.dnm_d1.donem_sabitleri import DONEM_SONU, RAPOR_ONEKI_KAYNAK

DONEM = DONEM_SONU
KESIM = "2026-09-01T00:00:00+03:00"
ILK_YIL = 2015


def _yukle(ad: str) -> dict[str, Any]:
    return json.loads((KAYNAK / f"{RAPOR_ONEKI_KAYNAK}{ad}.json").read_text(encoding="utf-8"))


def _risk_sirasi() -> tuple[list[str], list[str], list[str]]:
    ak = _yukle("ACIK_KALEM")
    duz = _yukle("CARI_EKSTRE_KAPANIS_DUZELTILMIS")
    r15 = sorted(
        {str(c["kaynak_cari_id"]) for c in ak.get("cariler") or [] if c.get("detay_yok_uyari")},
        key=lambda x: int(x),
    )
    r22 = sorted(
        {
            str(c["kaynak_cari_id"])
            for c in duz.get("cariler") or []
            if c.get("kanit_durumu") == "DOGRULANMAMIS_OZET"
        },
        key=lambda x: int(x),
    )
    if not set(r15) <= set(r22):
        raise SystemExit(f"15 ⊄ 22: {set(r15) - set(r22)}")
    kalan = [x for x in r22 if x not in set(r15)]
    return r15 + kalan, r15, kalan


def _dilimler_kapanis_ekseni(son: date = DONEM) -> list[tuple[str, str]]:
    """Boşluksuz ≤1y: 01.09.Y-1–31.08.Y … geriye ILK_YIL."""
    out: list[tuple[date, date]] = []
    y = son.year
    while y >= ILK_YIL:
        bas = date(y - 1, 9, 1)
        bit = date(y, 8, 31)
        if bit > son:
            bit = son
        if bas < date(ILK_YIL, 1, 1):
            bas = date(ILK_YIL, 1, 1)
        if bas <= bit:
            out.append((bas, bit))
        y -= 1
        if bas <= date(ILK_YIL, 1, 1):
            break
    return [(a.strftime("%d.%m.%Y"), b.strftime("%d.%m.%Y")) for a, b in out]


def _blok(blok: Any) -> dict[str, str] | None:
    if isinstance(blok, list) and blok:
        b = blok[0] if isinstance(blok[0], dict) else {}
    elif isinstance(blok, dict):
        b = blok
    else:
        return None
    if not b:
        return None
    return {
        "borc": str(dec(b.get("Borc") or b.get("borc"))),
        "alacak": str(dec(b.get("Alacak") or b.get("alacak"))),
        "bakiye": str(dec(b.get("Bakiye") or b.get("bakiye"))),
    }


def _cek(client, mid: str, bas: str, son: str, *, yeniden: bool = True) -> dict[str, Any]:
    y = client._post(
        "Musteri/base/",
        {
            "cmd": "finans_jq_listesi",
            "UID": client.uid,
            "musteri_id": str(mid),
            "b_tarihi": bas,
            "s_tarihi": son,
            "tur": "-1",
        },
    )
    if oturum_gecersiz_mi(y) and yeniden:
        client.login()
        return _cek(client, mid, bas, son, yeniden=False)
    if y.get("status") != "OK":
        return {
            "bas": bas,
            "son": son,
            "status": y.get("status"),
            "hata": y.get("veri"),
            "detay": [],
            "devreden": None,
            "ozet": None,
            "detay_toplam_sayisi": None,
        }
    v = y.get("veri")
    if not isinstance(v, dict):
        return {
            "bas": bas,
            "son": son,
            "status": "ERR",
            "hata": v,
            "detay": [],
            "devreden": None,
            "ozet": None,
            "detay_toplam_sayisi": None,
        }
    det = v.get("Detay") or []
    if not isinstance(det, list):
        det = []
    return {
        "bas": bas,
        "son": son,
        "status": "OK",
        "detay": [x for x in det if isinstance(x, dict)],
        "devreden": _blok(v.get("Devreden")),
        "ozet": _blok(v.get("Özet") or v.get("Ozet")),
        "detay_toplam_sayisi": v.get("Detay_Toplam_Sayisi"),
    }


def _kapanis(
    detay: list[dict],
    *,
    en_eski_devreden: dict[str, str] | None,
) -> dict[str, Any]:
    acilis = None
    acilis_kaynak = None
    if en_eski_devreden is not None:
        acilis = dec(en_eski_devreden.get("bakiye"))
        acilis_kaynak = "DEVREDEN_EN_ESKI_DOLU_DILIM"

    satirlar: list[dict] = []
    for row in detay:
        t = parse_tarih(row.get("Tarih"))
        if t is None or t > DONEM:
            continue
        satirlar.append(row)
    satirlar.sort(
        key=lambda r: (
            parse_tarih(r.get("Tarih")) or date.min,
            int(str(r.get("Satir") or 0) or 0),
        )
    )

    borc = sum((dec(r.get("Borc")) for r in satirlar), Decimal("0"))
    alacak = sum((dec(r.get("Alacak")) for r in satirlar), Decimal("0"))

    # Devir/açılış satır ipuçları (kaynak metin)
    def _metin(r: dict) -> str:
        return " ".join(
            str(r.get(k) or "")
            for k in ("Ack", "ack", "Aciklama", "Tur", "TurAdi", "Belge")
        ).upper()

    devir_satir = [
        {
            "tarih": r.get("Tarih"),
            "tur": r.get("Tur") or r.get("TurAdi"),
            "ack": r.get("Ack") or r.get("ack") or r.get("Aciklama"),
            "borc": str(dec(r.get("Borc"))),
            "alacak": str(dec(r.get("Alacak"))),
            "bakiye": str(dec(r.get("Bakiye"))),
            "id": r.get("id"),
        }
        for r in satirlar
        if any(x in _metin(r) for x in ("DEVİR", "DEVIR", "AÇILIŞ", "ACILIS", "AÇILIS"))
    ]

    kapanis = None
    kanit = "KANIT_YOK"
    if satirlar:
        kapanis = dec(satirlar[-1].get("Bakiye"))
        kanit = "SON_DETAY_BAKIYE_<=31.08"
    elif acilis is not None and acilis != 0:
        # Hareket yok; sıfır-dışı Devreden kaynak kapanış sayılır
        kapanis = acilis
        kanit = "YALNIZ_DEVREDEN_HAREKET_YOK"
    elif acilis is not None and acilis == 0 and not satirlar:
        # Devreden=0 + Detay yok → Özet varsa hâlâ kanıtsız (Özet tarih bağımsız)
        kanit = "KANIT_YOK_DETAY_BOS_DEVREDEN_SIFIR"

    return {
        "acilis_devir_bakiye": str(acilis) if acilis is not None else None,
        "acilis_kaynak": acilis_kaynak,
        "devir_satir_adet": len(devir_satir),
        "devir_satir_ornek": devir_satir[:10],
        "borc": str(borc),
        "alacak": str(alacak),
        "kapanis_bakiye_3108_kanitli": str(kapanis) if kanit.startswith(("SON_", "YALNIZ_")) else None,
        "kanit_durumu": kanit,
        "detay_satir_adet": len(satirlar),
    }


def main() -> int:
    from entegrasyon.evobulut_client import EvobulutClient, load_credentials, _uid_bul

    sira, r15, kalan = _risk_sirasi()
    kart = {str(r.get("R.a_id")): r for r in (_yukle("CARI").get("kayitlar") or [])}
    dilimler = _dilimler_kapanis_ekseni()

    # Sınır kontrolü: her dilim ≤366 gün
    for bas_s, son_s in dilimler:
        a = datetime.strptime(bas_s, "%d.%m.%Y").date()
        b = datetime.strptime(son_s, "%d.%m.%Y").date()
        if (b - a).days > 366:
            raise SystemExit(f"dilim >1y: {bas_s}-{son_s}")

    creds = load_credentials()
    client = EvobulutClient(creds)
    yanit = client._post(
        "index/base/",
        {"cmd": "euas", "p1": creds.kullanici_kodu, "p2": creds.sifre, "app": creds.app},
    )
    client.uid = _uid_bul(yanit)
    firma_id = ((yanit.get("veri") or {}).get("Ana") or [{}])[0].get("a_firma_id")

    sonuclar: list[dict[str, Any]] = []
    for i, cid in enumerate(sira, 1):
        if i == 1 or i % 5 == 0:
            client.login()
        k = kart.get(cid) or {}
        unvan = (k.get("text") or "").split("----")[0].strip() or k.get("R.a_ad")
        grup = "15_kanitsiz" if cid in set(r15) else "22_kalan"

        cekilen: list[dict[str, Any]] = []
        ham_detay: list[dict] = []
        # 22 riskli: tüm dilimleri tara (Özet≠0 iken erken kesme yasak — eski hareket kaçmasın)
        for bas, son in dilimler:
            r = _cek(client, cid, bas, son)
            n = len(r.get("detay") or [])
            cekilen.append(
                {
                    "bas": r["bas"],
                    "son": r["son"],
                    "status": r["status"],
                    "detay_adet": n,
                    "devreden": r.get("devreden"),
                    "ozet": r.get("ozet"),
                    "detay_toplam_sayisi": r.get("detay_toplam_sayisi"),
                    "hata": r.get("hata"),
                }
            )
            ham_detay.extend(r.get("detay") or [])
            time.sleep(0.04)

        # id birleşimi
        birlesen: dict[str, dict] = {}
        for row in ham_detay:
            rid = str(row.get("id") or "") or (
                f"{row.get('Tarih')}|{row.get('Satir')}|{row.get('Borc')}|{row.get('Alacak')}|{row.get('Tur')}"
            )
            birlesen[rid] = row
        detay_u = list(birlesen.values())

        # En eski sıfır-dışı Devreden; yoksa None (sıfır Devreden kanıt sayılmaz)
        en_eski_dev = None
        en_eski_dev_sifir = None
        for d in reversed(cekilen):
            dv = d.get("devreden")
            if dv is None:
                continue
            if en_eski_dev_sifir is None:
                en_eski_dev_sifir = dv
            if dec(dv.get("bakiye")) != 0 or dec(dv.get("borc")) != 0 or dec(dv.get("alacak")) != 0:
                en_eski_dev = dv
                break
        if en_eski_dev is None and detay_u:
            # Detay varken açılış için en eski dilim Devreden (0 olabilir)
            en_eski_dev = en_eski_dev_sifir

        # Kapanış dilimi (ilk) Devreden — rapor için ayrı; toplama EKLENMEZ
        kapanis_dilim_dev = cekilen[0].get("devreden") if cekilen else None

        kap = _kapanis(detay_u, en_eski_devreden=en_eski_dev)

        dogrulanmamis_ozet = None
        for d in cekilen:
            if d.get("ozet") and (
                dec(d["ozet"].get("bakiye")) != 0
                or dec(d["ozet"].get("borc")) != 0
                or dec(d["ozet"].get("alacak")) != 0
            ):
                dogrulanmamis_ozet = d["ozet"]
                break
        if dogrulanmamis_ozet is None and cekilen:
            dogrulanmamis_ozet = cekilen[0].get("ozet")

        kayit = {
            "kaynak_cari_id": cid,
            "kod": k.get("R.a_kod") or None,
            "unvan": unvan,
            "grup": grup,
            "kullanilan_tarih_araliklari": [
                {
                    "bas": d["bas"],
                    "son": d["son"],
                    "detay_adet": d["detay_adet"],
                    "devreden_bakiye": (d.get("devreden") or {}).get("bakiye") if d.get("devreden") else None,
                    "status": d["status"],
                }
                for d in cekilen
            ],
            "acilis_devir": {
                "bakiye": kap["acilis_devir_bakiye"],
                "kaynak": kap["acilis_kaynak"],
                "kapanis_dilimi_devreden_ayri_toplanmadi": kapanis_dilim_dev,
                "devir_satir_adet": kap["devir_satir_adet"],
                "devir_satir_ornek": kap["devir_satir_ornek"],
            },
            "borc": kap["borc"],
            "alacak": kap["alacak"],
            "kapanis_bakiye_3108_kanitli": kap["kapanis_bakiye_3108_kanitli"],
            "kanit_durumu": kap["kanit_durumu"],
            "detay_satir_adet": kap["detay_satir_adet"],
            "doviz": "TL",
            "doviz_ayri": {
                "not": "UI: Genel/TL/USD/EUR ayrı; bu çekim tur=-1 Genel Ekstre (TL). Döviz kırılımı API'de yok.",
                "usd": None,
                "eur": None,
            },
            "dogrulanmamis_ozet": dogrulanmamis_ozet,
            "ozet_31_08_degil": True,
            "dilimler": cekilen,
            "donem_sonu_dahil": DONEM.isoformat(),
            "kesim_istanbul": KESIM,
        }
        sonuclar.append(kayit)
        print(
            f"cari22 {i}/{len(sira)} {grup} id={cid} dilim={len(cekilen)} "
            f"detay={kap['detay_satir_adet']} kanit={kap['kanit_durumu']} "
            f"kap={kap['kapanis_bakiye_3108_kanitli']} acilis={kap['acilis_devir_bakiye']}",
            flush=True,
        )

    kanitli = sum(1 for x in sonuclar if x.get("kapanis_bakiye_3108_kanitli") is not None)
    out = {
        "format": "d1-cari22-kapanis-kanit-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "firma_id_login": str(firma_id),
        "donem_sonu_dahil": DONEM.isoformat(),
        "kesim_istanbul": KESIM,
        "menu_yolu_ui": {
            "yol": "Raporlar → Finans Raporları → Müşteri Hesap Raporları",
            "url_hash": "#ajax/rapor_musteri_hesap.html",
            "rapor": "Müşteri Hesap Toplamı Tarih (Devirli)",
            "filtre": {
                "baslangic": "01.09.2025",
                "bitis": "31.08.2026",
                "ekstre_cinsi": "Genel Ekstre (TL) / TL / USD / EUR ayrı",
                "hareket_gorenler_checkbox": "Sadece Tarih Aralığında Hareket Görenleri Listele — kanıtsızlarda KAPALI tutulmalı",
            },
            "not": "Finans Raporları → Ekstreler (rap_fin_002) = Kasa/Banka; cari değil.",
            "api": "Musteri/base cmd=finans_jq_listesi (max 1 yıl)",
        },
        "adet_22": len(sonuclar),
        "adet_15_once": len(r15),
        "adet_kalan": len(kalan),
        "toplam_37_degil": True,
        "kanitli_adet": kanitli,
        "kanitsiz_adet": len(sonuclar) - kanitli,
        "dilim_sablonu": dilimler,
        "cariler": sonuclar,
        "olcut": (
            "finans_jq ≤1y boşluksuz 01.09–31.08 dilimleri; Detay id birleşimi; "
            "Devreden yalnız en eski dolu dilimde; Özet 31.08 sayılmaz"
        ),
        "k05": False,
        "stok_yeniden_cekilmedi": True,
    }
    yaz_kaynak("DOGRULAMA_CARI22_KAPANIS_KANIT", out)

    # Özet tablo
    tablo = [
        {
            "id": x["kaynak_cari_id"],
            "kod": x.get("kod"),
            "unvan": x.get("unvan"),
            "grup": x["grup"],
            "araliklar": [
                f"{a['bas']}–{a['son']}(n={a['detay_adet']})"
                for a in x["kullanilan_tarih_araliklari"]
            ],
            "acilis": (x.get("acilis_devir") or {}).get("bakiye"),
            "borc": x.get("borc"),
            "alacak": x.get("alacak"),
            "kapanis_3108": x.get("kapanis_bakiye_3108_kanitli"),
            "kanit": x.get("kanit_durumu"),
            "doviz": x.get("doviz"),
        }
        for x in sonuclar
    ]
    yaz_json(
        CALISMA / "CARI22_KAPANIS_KANIT_OZET.json",
        {
            "zaman": out["zaman"],
            "kanitli": kanitli,
            "kanitsiz": out["kanitsiz_adet"],
            "k05": False,
            "menu_yolu_ui": out["menu_yolu_ui"],
            "tablo": tablo,
            "kanit": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_CARI22_KAPANIS_KANIT.json",
        },
    )
    print(
        json.dumps(
            {"kanitli": kanitli, "kanitsiz": out["kanitsiz_adet"], "k05": False, "adet": len(sonuclar)},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
