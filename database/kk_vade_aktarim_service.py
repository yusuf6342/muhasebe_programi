"""Firma kredi kartı Evo hareketlerinden vade/ekstre planı — mali borç üretmeden.

Mevcut ``finans_hareketleri`` / ``acilis_bakiyesi`` korunur. Yalnızca
``kredi_karti_odemeleri`` + taksit + (gerekirse) ekstre ödeme köprüsü yazılır ki
ödeme takvimi ve dönem ekstresi gerçek ``G.a_vtarih`` ile çalışsın.

Kimlik: EVB-BN-{evo_a_id} (dönem harcaması/ödemesi), EVB-KKD-{evo_a_id} (açılış planı).
Idempotent: aynı belge_no / istek_anahtarı ikinci kez borç yaratmaz.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.access import yazma_zorunlu
from database.database import get_session
from database.finans_service import FinansService
from database.kredi_karti_ekstre_service import KrediKartiEkstreService
from database.models.finans import (
    BankAccountMatchRule,
    FinansHareketi,
    FinansHesabi,
    KrediKartiEkstre,
    KrediKartiEkstreOdeme,
    KrediKartiOdeme,
    KrediKartiOdemeTaksit,
    KrediKartiTanimi,
)

SIFIR = Decimal("0.00")
KURUS = Decimal("0.01")
KAYNAK_EVO = "EVO"
KAYNAK_EVO_DEVIR = "EVO_DEVIR"
ISLEM_KODU = "KK_VADE_EKSTRE_V2"
BELGE_BN = "EVB-BN-"
BELGE_KKD = "EVB-KKD-"
ODEME_ISTEK = "EVO-KK-ODEME-"


def _d(v) -> Decimal:
    try:
        return Decimal(str(v if v is not None else 0).replace(",", ".")).quantize(
            KURUS, rounding=ROUND_HALF_UP
        )
    except Exception:
        return SIFIR


def _tarih(s) -> date | None:
    if s is None:
        return None
    if isinstance(s, date) and not isinstance(s, datetime):
        return s
    if isinstance(s, datetime):
        return s.date()
    metin = str(s).strip()
    if not metin:
        return None
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(metin[:19] if len(metin) > 10 else metin, fmt).date()
        except ValueError:
            continue
    return None


def kaynak_sha256(yol: Path) -> str:
    h = hashlib.sha256()
    with open(yol, "rb") as f:
        for parca in iter(lambda: f.read(1024 * 1024), b""):
            h.update(parca)
    return h.hexdigest()


def evo_anlik_yukle(yol: Path | str) -> dict:
    p = Path(yol)
    data = json.loads(p.read_text(encoding="utf-8"))
    data["_dosya"] = str(p.resolve())
    data["_sha256"] = kaynak_sha256(p)
    return data


def _kk_bankalar(data: dict) -> list[dict]:
    out = []
    for b in data.get("bankalar") or []:
        ad = (b.get("text") or "").strip()
        if ad.startswith("02"):
            out.append(b)
    return out


def _gun_modu(tarihler: list[date], *, esik: float = 0.7) -> int | None:
    if not tarihler:
        return None
    sayac = Counter(t.day for t in tarihler)
    gun, n = sayac.most_common(1)[0]
    if n / len(tarihler) >= esik:
        return int(gun)
    return None


class KkVadeAktarimService:
    """Evo anlık görüntü → Cin KK vade/ekstre planı."""

    @staticmethod
    def schema_hazirla() -> None:
        KrediKartiEkstreService.schema_hazirla()

    @staticmethod
    def kart_eslemeleri(session) -> list[dict]:
        """Evo 02 kartı ↔ Cin KrediKartiTanimi / finans hesabı."""
        kurallar = list(
            session.scalars(
                select(BankAccountMatchRule).where(
                    BankAccountMatchRule.alt_hesap_turu == "KREDI_KARTI",
                    BankAccountMatchRule.aktif.is_(True),
                )
            ).all()
        )
        tanimlar = list(
            session.scalars(
                select(KrediKartiTanimi).options(selectinload(KrediKartiTanimi.banka_karti))
            ).all()
        )
        by_bagli = {int(t.bagli_hesap_id): t for t in tanimlar if t.bagli_hesap_id}
        by_banka: dict[int, list] = defaultdict(list)
        for t in tanimlar:
            by_banka[int(t.banka_karti_id)].append(t)

        sonuc = []
        for k in kurallar:
            evo_id = str(k.evo_banka_id).strip()
            hesap = None
            if k.finans_hesap_id:
                hesap = session.get(FinansHesabi, int(k.finans_hesap_id))
            if hesap is None:
                adaylar = list(
                    session.scalars(
                        select(FinansHesabi).where(
                            FinansHesabi.banka_karti_id == int(k.banka_karti_id),
                            FinansHesabi.alt_hesap_turu == "KREDI_KARTI",
                        )
                    ).all()
                )
                gercek = [
                    h
                    for h in adaylar
                    if "— kredi kartı hesabı" not in (h.hesap_adi or "").casefold()
                ]
                hesap = (gercek or adaylar)[0] if (gercek or adaylar) else None
            kk = by_bagli.get(int(hesap.id)) if hesap else None
            if kk is None:
                aday_t = by_banka.get(int(k.banka_karti_id), [])
                if len(aday_t) == 1:
                    kk = aday_t[0]
            sonuc.append(
                {
                    "evo_id": evo_id,
                    "evo_adi": k.evo_banka_adi or "",
                    "banka_karti_id": int(k.banka_karti_id),
                    "hesap_id": int(hesap.id) if hesap else None,
                    "hesap_adi": hesap.hesap_adi if hesap else None,
                    "acilis": _d(hesap.acilis_bakiyesi) if hesap else SIFIR,
                    "bakiye": FinansService.bakiye(hesap) if hesap else SIFIR,
                    "kredi_karti_id": int(kk.id) if kk else None,
                    "kart_adi": kk.kart_adi if kk else None,
                    "kesim_gunu": kk.hesap_kesim_gunu if kk else None,
                    "son_odeme_gunu": kk.son_odeme_gunu if kk else None,
                }
            )
        return sonuc

    @staticmethod
    def kaynak_hareketleri(data: dict, evo_id: str) -> list[dict]:
        eid = str(evo_id).strip()
        satirlar = []
        for h in data.get("banka_hareketleri") or []:
            if str(h.get("G.a_banka_id") or "").strip() != eid:
                continue
            aid = str(h.get("G.a_id") or "").strip()
            if not aid:
                continue
            tarih = _tarih(h.get("G.a_tarih"))
            vtarih = _tarih(h.get("G.a_vtarih"))
            cikan = _d(h.get("G.a_cikan"))
            giren = _d(h.get("G.a_giren"))
            try:
                taksit = int(str(h.get("G.a_taksit") or "0").strip() or "0")
            except ValueError:
                taksit = 0
            try:
                taksit_no = int(str(h.get("G.a_taksit_no") or "0").strip() or "0")
            except ValueError:
                taksit_no = 0
            satirlar.append(
                {
                    "evo_a_id": aid,
                    "tarih": tarih,
                    "vtarih": vtarih,
                    "cikan": cikan,
                    "giren": giren,
                    "taksit": taksit,
                    "taksit_no": taksit_no or 1,
                    "aciklama": (h.get("G.a_ack") or "")[:500],
                    "kalan": _d(h.get("Kalan")),
                    "kapatilan": _d(h.get("Kapatilan")),
                    "tur": (h.get("FIN_TUR.a_adi") or ""),
                }
            )
        return satirlar

    @staticmethod
    def _cin_belge_seti(session, hesap_id: int) -> dict[str, FinansHareketi]:
        harfler = list(
            session.scalars(
                select(FinansHareketi).where(FinansHareketi.hesap_id == int(hesap_id))
            ).all()
        )
        return {str(h.belge_no or ""): h for h in harfler if h.belge_no}

    @staticmethod
    def _mevcut_odeme_belgeleri(session, kredi_karti_id: int) -> set[str]:
        return {
            str(b)
            for b in session.scalars(
                select(KrediKartiOdeme.belge_no).where(
                    KrediKartiOdeme.kredi_karti_id == int(kredi_karti_id)
                )
            ).all()
        }

    @staticmethod
    def _kesim_ve_vade(
        kart: KrediKartiTanimi,
        islem_tarihi: date,
        vtarih: date | None,
        taksit_no: int,
    ) -> tuple[date | None, date | None, str]:
        """(ekstre_kesim, vade, vade_kaynagi)."""
        if vtarih is None:
            return None, None, "vade_dogrulanamadi"
        if KrediKartiEkstreService.kesim_gunu(kart) is not None:
            try:
                donem = KrediKartiEkstreService.taksit_donem_bilgisi(
                    islem_tarihi, max(1, taksit_no), kart
                )
                kesim = donem.get("kesim_tarihi")
                # Kaynak vtarih esas; kural yalnızca dönem/kesim için
                return kesim, vtarih, "evo_a_vtarih+kart_kesim_kurali"
            except Exception:
                pass
        # Kesim günü yok: vade hem dönem hem son ödeme köprüsü
        return vtarih, vtarih, "evo_a_vtarih"

    @staticmethod
    def _ekstre_garanti(
        session,
        kart: KrediKartiTanimi,
        kesim: date,
        son_odeme: date | None,
    ) -> KrediKartiEkstre:
        ekstre = session.scalar(
            select(KrediKartiEkstre).where(
                KrediKartiEkstre.kredi_karti_id == int(kart.id),
                KrediKartiEkstre.kesim_tarihi == kesim,
            )
        )
        if ekstre is None:
            gun = KrediKartiEkstreService.kesim_gunu(kart) or kesim.day
            donem = KrediKartiEkstreService._donem(kesim, gun, kart)
            ekstre = KrediKartiEkstre(
                kredi_karti_id=int(kart.id),
                kesim_tarihi=kesim,
                donem_baslangic=donem["donem_baslangic"],
                donem_bitis=donem["donem_bitis"],
                son_odeme_tarihi=son_odeme or donem.get("son_odeme_tarihi"),
                son_odeme_manuel=bool(son_odeme),
                durum="KESILMIS" if kesim <= date.today() else "KESILMEMIS",
                toplam_borc=SIFIR,
                odenen=SIFIR,
                kalan=SIFIR,
                para_birimi=(kart.para_birimi or "TRY"),
                kesin=kesim <= date.today(),
            )
            session.add(ekstre)
            session.flush()
        elif son_odeme and (
            ekstre.son_odeme_tarihi is None
            or (not ekstre.son_odeme_manuel and ekstre.son_odeme_tarihi != son_odeme)
        ):
            ekstre.son_odeme_tarihi = son_odeme
            ekstre.son_odeme_manuel = True
            session.flush()
        return ekstre

    @staticmethod
    def _plan_odeme_yaz(
        session,
        *,
        kart: KrediKartiTanimi,
        belge_no: str,
        tarih: date,
        tutar: Decimal,
        vtarih: date | None,
        taksit_sayisi: int,
        taksit_no: int,
        aciklama: str,
        kaynak_turu: str,
        referans_no: str | None,
    ) -> str:
        """Mali hareket yazmadan KrediKartiOdeme + tek taksit satırı."""
        mevcut = session.scalar(
            select(KrediKartiOdeme).where(KrediKartiOdeme.belge_no == belge_no)
        )
        if mevcut is not None:
            return "zaten_var"

        kesim, vade, kaynak = KkVadeAktarimService._kesim_ve_vade(
            kart, tarih, vtarih, taksit_no
        )
        if vade is None:
            return "vade_dogrulanamadi"

        n = max(1, int(taksit_sayisi or 1))
        tur = "TEK_CEKIM" if n <= 1 else "TAKSITLI"
        odeme = KrediKartiOdeme(
            belge_no=belge_no,
            tarih=tarih,
            vade_tarihi=vade,
            banka_karti_id=int(kart.banka_karti_id),
            kredi_karti_id=int(kart.id),
            cari_id=0,
            cekim_turu=tur,
            taksit_sayisi=n,
            tutar=tutar,
            referans_no=referans_no,
            aciklama=(aciklama or "")[:500] or None,
            durum="AÇIK",
            kaynak_turu=kaynak_turu,
        )
        session.add(odeme)
        session.flush()
        session.add(
            KrediKartiOdemeTaksit(
                odeme_id=odeme.id,
                taksit_no=max(1, int(taksit_no or 1)),
                vade_tarihi=vade,
                tutar=tutar,
                durum="BEKLIYOR",
                ekstre_kesim_tarihi=kesim,
            )
        )
        session.flush()
        # Tüm taksitler kalıcı kart hareketi (EVO/devirde nötr KK TAKSİT — borç çiftlenmez)
        try:
            from database.kk_taksit_islem_service import odeme_tum_taksitleri_isle

            odeme_tum_taksitleri_isle(session, odeme)
        except Exception:
            pass
        if kesim is not None:
            KkVadeAktarimService._ekstre_garanti(session, kart, kesim, vade)
        return f"yazildi:{kaynak}"

    @staticmethod
    def _odeme_fifo_dagit(
        session,
        kart: KrediKartiTanimi,
        tarih: date,
        tutar: Decimal,
    ) -> list[tuple[KrediKartiEkstre, Decimal, Decimal]]:
        """Ödemeyi kesimi ≤ ödeme tarihi olan açık dönemlere eski→yeni dağıtır.

        Dönüş: [(ekstre, uygulanan, fazla)]. Yeni finans hareketi yazılmaz.
        Açık dönem yoksa ödeme günü ekstrene fazla olarak bağlanır.
        """
        tutar = _d(tutar)
        if tutar <= 0:
            return []
        veri = KrediKartiEkstreService.donem_borclari(
            session, kart_ids=[int(kart.id)], tarih=tarih
        ).get(int(kart.id))
        kalan_odeme = tutar
        dagilim: list[tuple[KrediKartiEkstre, Decimal, Decimal]] = []
        if veri:
            for kesim, g in sorted(veri["donemler"].items()):
                if kesim > tarih or kalan_odeme <= 0:
                    continue
                kalan = _d(g.get("kalan"))
                if kalan <= 0:
                    continue
                pay = min(kalan_odeme, kalan)
                son = g.get("son_odeme_tarihi") or kesim
                ekstre_id = g.get("ekstre_id")
                ekstre = (
                    session.get(KrediKartiEkstre, int(ekstre_id))
                    if ekstre_id
                    else None
                )
                if ekstre is None:
                    ekstre = KkVadeAktarimService._ekstre_garanti(
                        session, kart, kesim, son
                    )
                dagilim.append((ekstre, pay, SIFIR))
                kalan_odeme -= pay
        if not dagilim:
            # Açık dönem yok — peşin fazla; sentetik dönem üretme
            if KrediKartiEkstreService.kesim_gunu(kart) is not None:
                try:
                    donem = KrediKartiEkstreService.donem_bilgisi(tarih, kart)
                    kesim = donem["kesim_tarihi"]
                    son = donem.get("son_odeme_tarihi") or tarih
                except Exception:
                    kesim, son = tarih, tarih
            else:
                # Kart kesim günü yoksa en yakın mevcut ekstre; yoksa tarih köprüsü
                mevcut = session.scalars(
                    select(KrediKartiEkstre)
                    .where(KrediKartiEkstre.kredi_karti_id == int(kart.id))
                    .order_by(KrediKartiEkstre.kesim_tarihi.desc())
                ).first()
                if mevcut is not None and mevcut.kesim_tarihi <= tarih:
                    kesim, son = mevcut.kesim_tarihi, mevcut.son_odeme_tarihi or tarih
                else:
                    kesim, son = tarih, tarih
            ekstre = KkVadeAktarimService._ekstre_garanti(session, kart, kesim, son)
            dagilim.append((ekstre, tutar, tutar))
            return dagilim
        if kalan_odeme > 0:
            e, p, _f = dagilim[-1]
            dagilim[-1] = (e, p + kalan_odeme, kalan_odeme)
        return dagilim

    @staticmethod
    def _plan_odeme_bagla(
        session,
        *,
        kart: KrediKartiTanimi,
        belge_no: str,
        tarih: date,
        tutar: Decimal,
        aciklama: str,
        finans_belge_no: str,
    ) -> str:
        """Mevcut banka giriş hareketine ekstre ödeme köprüsü (yeni finans hareketi yok).

        Ödeme, ödeme tarihindeki açık ekstre dönemlerine FIFO ile bağlanır; ödeme
        gününe boş dönem açılmaz. Tekrarlayan istek yeni kayıt üretmez.
        """
        anahtar = f"{ODEME_ISTEK}{finans_belge_no}"
        onceki = session.scalar(
            select(KrediKartiEkstreOdeme).where(KrediKartiEkstreOdeme.istek_anahtari == anahtar)
        )
        if onceki is not None:
            return "zaten_var"
        ayni_belge = session.scalar(
            select(KrediKartiEkstreOdeme).where(KrediKartiEkstreOdeme.belge_no == belge_no)
        )
        if ayni_belge is not None:
            return "zaten_var"

        kart_hesap = None
        if getattr(kart, "bagli_hesap_id", None):
            kart_hesap = session.get(FinansHesabi, int(kart.bagli_hesap_id))
        if kart_hesap is None:
            kart_hesap = KrediKartiEkstreService.kart_hesabi(session, kart)

        dagilim = KkVadeAktarimService._odeme_fifo_dagit(session, kart, tarih, tutar)
        if not dagilim:
            return "bos"
        metin = (aciklama or "Evo kart ödemesi (plan köprüsü)")[:500]
        etkilenen: list[KrediKartiEkstre] = []
        for i, (ekstre, pay, fazla) in enumerate(dagilim):
            if i == 0:
                bno, ist = belge_no, anahtar
            else:
                bno = f"{belge_no}-S{i + 1}"[:50]
                ist = f"{anahtar}-S{i + 1}"[:64]
                if session.scalar(
                    select(KrediKartiEkstreOdeme).where(
                        KrediKartiEkstreOdeme.istek_anahtari == ist
                    )
                ):
                    continue
            session.add(
                KrediKartiEkstreOdeme(
                    ekstre_id=ekstre.id,
                    belge_no=bno,
                    tarih=tarih,
                    tutar=pay,
                    hesap_turu="MEVDUAT",
                    finans_hesap_id=None,
                    kart_hesap_id=int(kart_hesap.id) if kart_hesap else None,
                    aciklama=metin if i == 0 else f"{metin} · dilim {i + 1}"[:500],
                    finans_belge_no=finans_belge_no,
                    istek_anahtari=ist,
                    kaynak="EKSTRE",
                    fazla_odeme=fazla,
                )
            )
            etkilenen.append(ekstre)
        session.flush()
        for ekstre in etkilenen:
            KrediKartiEkstreService._taksit_durumlarini_esitle(session, ekstre, kart)
        return "yazildi"

    @staticmethod
    def _acilis_plan_adaylari(
        kaynak: list[dict],
        *,
        cin_bn_idler: set[str],
        acilis_borc: Decimal,
        donem_baslangic: date,
    ) -> list[dict]:
        """Açılış bakiyesini karşılayan, Cin'de EVB-BN olmayan taksit/harcama satırları.

        Evo ``Kalan`` alanı gelecek taksitlerde sıkça 0 gelir; bu yüzden
        vadesi dönem başı ve sonrası olan çıkışlar (Cin'de yoksa) adaya alınır.
        Gerçekten kapanmış geçmiş satır (vade < dönem ve Kalan=0 + Kapatilan>=tutar) elenir.
        """
        if acilis_borc <= 0:
            return []
        adaylar = []
        for s in kaynak:
            if s["cikan"] <= 0:
                continue
            aid = s["evo_a_id"]
            if aid in cin_bn_idler:
                continue
            vt = s["vtarih"] or s["tarih"]
            if vt is None:
                continue
            gelecek_veya_donem = vt >= donem_baslangic
            acik_kalan = s["kalan"] > 0
            # Geçmiş + tamamen kapatılmış → açılış planına alma
            if (
                not gelecek_veya_donem
                and not acik_kalan
                and s["kapatilan"] >= s["cikan"]
            ):
                continue
            if not gelecek_veya_donem and not acik_kalan:
                continue
            # Kalan doluysa onu kullan; gelecek taksitte Kalan=0 ise cikan
            tutar = s["kalan"] if acik_kalan else s["cikan"]
            if tutar <= 0:
                continue
            adaylar.append({**s, "plan_tutar": tutar})

        # Önce vade, sonra işlem tarihi
        adaylar.sort(key=lambda x: (x["vtarih"] or date.max, x["tarih"] or date.max, x["evo_a_id"]))
        kalan = acilis_borc
        secilen = []
        for a in adaylar:
            if kalan <= 0:
                break
            pay = min(a["plan_tutar"], kalan)
            if pay <= 0:
                continue
            secilen.append({**a, "plan_tutar": pay})
            kalan -= pay
        # Kalan açılış için kaynak satır yoksa — vade uydurulmaz; üst katman bekleyecek yazar
        if kalan > KURUS:
            secilen.append(
                {
                    "evo_a_id": f"ACILIS-KALAN",
                    "tarih": donem_baslangic,
                    "vtarih": None,
                    "cikan": kalan,
                    "giren": SIFIR,
                    "taksit": 0,
                    "taksit_no": 1,
                    "aciklama": "Açılış bakiyesi — kaynak taksit/vade eşleşmedi",
                    "kalan": kalan,
                    "kapatilan": SIFIR,
                    "tur": "",
                    "plan_tutar": kalan,
                    "vade_eksik": True,
                }
            )
        return secilen

    @staticmethod
    def hazirlik(
        data: dict,
        *,
        donem_baslangic: date | None = None,
        session=None,
    ) -> dict:
        """Salt okunur plan: kart başına eylemler + mutabakat özeti."""
        KkVadeAktarimService.schema_hazirla()
        donem_baslangic = donem_baslangic or date(2026, 9, 1)

        def calis(s) -> dict:
            eslemeler = KkVadeAktarimService.kart_eslemeleri(s)
            kartlar = []
            for es in eslemeler:
                evo_id = es["evo_id"]
                kaynak = KkVadeAktarimService.kaynak_hareketleri(data, evo_id)
                if es["kredi_karti_id"] is None or es["hesap_id"] is None:
                    kartlar.append(
                        {
                            **es,
                            "tespit": "eslesme_eksik",
                            "eylemler": [],
                            "kaynak_adet": len(kaynak),
                        }
                    )
                    continue

                belgeler = KkVadeAktarimService._cin_belge_seti(s, es["hesap_id"])
                bn_idler = set()
                for bno in belgeler:
                    if bno.startswith(BELGE_BN):
                        bn_idler.add(bno[len(BELGE_BN) :])
                mevcut_odeme = KkVadeAktarimService._mevcut_odeme_belgeleri(
                    s, es["kredi_karti_id"]
                )
                kart = s.get(KrediKartiTanimi, int(es["kredi_karti_id"]))

                eylemler = []
                # 1) Dönem EVB-BN çıkış → plan
                for bno, har in belgeler.items():
                    if not bno.startswith(BELGE_BN):
                        continue
                    aid = bno[len(BELGE_BN) :]
                    kay = next((x for x in kaynak if x["evo_a_id"] == aid), None)
                    tur = (har.hareket_turu or "").upper()
                    if "ÇIKIŞ" in tur or "CIKIS" in tur:
                        if bno in mevcut_odeme:
                            eylemler.append(
                                {
                                    "eylem": "degismeyecek",
                                    "neden": "plan_zaten_var",
                                    "belge_no": bno,
                                    "tutar": str(_d(har.tutar)),
                                }
                            )
                            continue
                        vt = kay["vtarih"] if kay else None
                        if vt is None:
                            eylemler.append(
                                {
                                    "eylem": "bekleyecek",
                                    "neden": "vade_dogrulanamadi",
                                    "belge_no": bno,
                                    "tutar": str(_d(har.tutar)),
                                    "islem_tarihi": har.tarih.isoformat() if har.tarih else None,
                                }
                            )
                            continue
                        eylemler.append(
                            {
                                "eylem": "tarihi_duzeltilecek",
                                "tur": "harcama_plan",
                                "belge_no": bno,
                                "evo_a_id": aid,
                                "tutar": str(_d(har.tutar)),
                                "islem_tarihi": (kay["tarih"] or har.tarih).isoformat(),
                                "vtarih": vt.isoformat(),
                                "taksit": kay["taksit"] if kay else 0,
                                "taksit_no": kay["taksit_no"] if kay else 1,
                                "aciklama": (kay["aciklama"] if kay else har.aciklama) or "",
                                "kaynak_turu": KAYNAK_EVO,
                            }
                        )
                    elif "GİRİŞ" in tur or "GIRIS" in tur:
                        odeme_bno = f"KKE-EVO-{aid}"[:50]
                        eylemler.append(
                            {
                                "eylem": "tarihi_duzeltilecek",
                                "tur": "odeme_kopru",
                                "belge_no": odeme_bno,
                                "finans_belge_no": bno,
                                "evo_a_id": aid,
                                "tutar": str(_d(har.tutar)),
                                "islem_tarihi": (kay["tarih"] if kay else har.tarih).isoformat()
                                if (kay and kay["tarih"]) or har.tarih
                                else None,
                                "aciklama": (kay["aciklama"] if kay else har.aciklama) or "",
                            }
                        )

                # 2) Açılış planı
                acilis_borc = -es["acilis"] if es["acilis"] < 0 else SIFIR
                adaylar = KkVadeAktarimService._acilis_plan_adaylari(
                    kaynak,
                    cin_bn_idler=bn_idler,
                    acilis_borc=acilis_borc,
                    donem_baslangic=donem_baslangic,
                )
                plan_toplam = SIFIR
                acilis_vadesiz = SIFIR
                for a in adaylar:
                    bno = f"{BELGE_KKD}{a['evo_a_id']}"[:50]
                    if bno in mevcut_odeme:
                        eylemler.append(
                            {
                                "eylem": "degismeyecek",
                                "neden": "devir_plan_var",
                                "belge_no": bno,
                                "tutar": str(a["plan_tutar"]),
                            }
                        )
                        plan_toplam += a["plan_tutar"]
                        continue
                    # Vade yoksa uydurma — ödeme raporunda ayrı görünür grup
                    if a.get("vade_eksik") or a.get("vtarih") is None:
                        acilis_vadesiz += a["plan_tutar"]
                        eylemler.append(
                            {
                                "eylem": "bekleyecek",
                                "neden": "vade_dogrulanamadi",
                                "belge_no": bno,
                                "tutar": str(a["plan_tutar"]),
                                "aciklama": a.get("aciklama") or "",
                            }
                        )
                        continue
                    eylemler.append(
                        {
                            "eylem": "kaynakla_degistirilecek",
                            "tur": "devir_plan",
                            "belge_no": bno,
                            "evo_a_id": a["evo_a_id"],
                            "tutar": str(a["plan_tutar"]),
                            "islem_tarihi": (a["tarih"] or donem_baslangic).isoformat(),
                            "vtarih": a["vtarih"].isoformat(),
                            "taksit": a["taksit"],
                            "taksit_no": a["taksit_no"],
                            "aciklama": a["aciklama"] or "Evo açılış/devir taksit planı",
                            "kaynak_turu": KAYNAK_EVO_DEVIR,
                        }
                    )
                    plan_toplam += a["plan_tutar"]

                # Kesim/son ödeme çıkarımı (yalnız boşsa öner)
                vtarihler = [
                    x["vtarih"]
                    for x in kaynak
                    if x["cikan"] > 0 and x["vtarih"] is not None
                ]
                oner_son = _gun_modu(vtarihler)
                oner_kesim = None
                if oner_son and kart and kart.hesap_kesim_gunu is None:
                    # Kesim ≈ son ödemeden 5 gün önce (yaygın TR örüntüsü) — yalnızca öneri
                    oner_kesim = ((oner_son - 5 - 1) % 31) + 1

                evo_borc = sum((x["cikan"] - x["giren"] for x in kaynak), SIFIR)
                tespit = "sorunsuz"
                if acilis_vadesiz > KURUS:
                    tespit = "tarih_eksik"
                elif abs(plan_toplam - acilis_borc) > Decimal("1.00") and acilis_borc > 0:
                    tespit = "acilis_plan_farki"
                if es["kesim_gunu"] is None and tespit == "sorunsuz":
                    tespit = "yanlis_donem"

                kartlar.append(
                    {
                        **es,
                        "tespit": tespit,
                        "kaynak_adet": len(kaynak),
                        "evo_net_borc": str(evo_borc),
                        "acilis_borc": str(acilis_borc),
                        "acilis_plan_toplam": str(plan_toplam),
                        "acilis_vadesiz": str(acilis_vadesiz),
                        "onerilen_son_odeme_gunu": oner_son,
                        "onerilen_kesim_gunu": oner_kesim,
                        "eylemler": eylemler,
                        "yazilacak": sum(
                            1
                            for e in eylemler
                            if e["eylem"] in ("tarihi_duzeltilecek", "kaynakla_degistirilecek")
                        ),
                        "bekleyen": sum(1 for e in eylemler if e["eylem"] == "bekleyecek"),
                    }
                )

            return {
                "islem_kodu": ISLEM_KODU,
                "kaynak_dosya": data.get("_dosya"),
                "kaynak_sha256": data.get("_sha256"),
                "cekilme_zamani": data.get("cekilme_zamani"),
                "devir_tarihi": data.get("devir_tarihi"),
                "donem_baslangic": donem_baslangic.isoformat(),
                "kartlar": kartlar,
            }

        if session is not None:
            return calis(session)
        with get_session() as s:
            return calis(s)

    @staticmethod
    def uygula(
        data: dict,
        *,
        donem_baslangic: date | None = None,
        kart_gun_yaz: bool = True,
        dry_run: bool = False,
    ) -> dict:
        """Hazırlık planını atomik uygular. dry_run=True ise yazmaz."""
        yazma_zorunlu("finans_duzenleme")
        KkVadeAktarimService.schema_hazirla()
        donem_baslangic = donem_baslangic or date(2026, 9, 1)

        with get_session() as session:
            plan = KkVadeAktarimService.hazirlik(
                data, donem_baslangic=donem_baslangic, session=session
            )
            ozet = {
                "dry_run": dry_run,
                "yazilan_harcama": 0,
                "yazilan_devir": 0,
                "yazilan_odeme": 0,
                "atlanan": 0,
                "bekleyen": 0,
                "kart_gun_guncelleme": [],
                "hatalar": [],
                "kart_sonuclar": [],
            }
            if dry_run:
                ozet["plan"] = plan
                return ozet

            for k in plan["kartlar"]:
                kid = k.get("kredi_karti_id")
                if not kid:
                    ozet["hatalar"].append({"evo_id": k["evo_id"], "hata": "kk_yok"})
                    continue
                kart = session.get(KrediKartiTanimi, int(kid))
                if kart is None:
                    ozet["hatalar"].append({"evo_id": k["evo_id"], "hata": "kk_yok"})
                    continue

                # Kart gün kuralı — yalnız boşsa ve güvenilir öneri varsa
                if kart_gun_yaz:
                    degisti = False
                    if kart.son_odeme_gunu is None and k.get("onerilen_son_odeme_gunu"):
                        kart.son_odeme_gunu = int(k["onerilen_son_odeme_gunu"])
                        degisti = True
                    if kart.hesap_kesim_gunu is None and k.get("onerilen_kesim_gunu"):
                        # Son ödeme çıkarıldıysa kesim önerisini yalnız birlikte yaz
                        if kart.son_odeme_gunu is not None:
                            kart.hesap_kesim_gunu = int(k["onerilen_kesim_gunu"])
                            degisti = True
                    if degisti:
                        ozet["kart_gun_guncelleme"].append(
                            {
                                "kredi_karti_id": int(kart.id),
                                "kesim": kart.hesap_kesim_gunu,
                                "son_odeme": kart.son_odeme_gunu,
                                "yontem": "evo_vtarih_gun_modu>=0.7",
                            }
                        )

                for e in k["eylemler"]:
                    try:
                        if e["eylem"] == "bekleyecek":
                            ozet["bekleyen"] += 1
                            continue
                        if e["eylem"] == "degismeyecek":
                            ozet["atlanan"] += 1
                            continue
                        if e.get("tur") == "harcama_plan":
                            r = KkVadeAktarimService._plan_odeme_yaz(
                                session,
                                kart=kart,
                                belge_no=e["belge_no"],
                                tarih=_tarih(e["islem_tarihi"]),
                                tutar=_d(e["tutar"]),
                                vtarih=_tarih(e.get("vtarih")),
                                taksit_sayisi=int(e.get("taksit") or 1) or 1,
                                taksit_no=int(e.get("taksit_no") or 1) or 1,
                                aciklama=e.get("aciklama") or "",
                                kaynak_turu=KAYNAK_EVO,
                                referans_no=e.get("evo_a_id"),
                            )
                            if r.startswith("yazildi"):
                                ozet["yazilan_harcama"] += 1
                            elif r == "vade_dogrulanamadi":
                                ozet["bekleyen"] += 1
                            else:
                                ozet["atlanan"] += 1
                        elif e.get("tur") == "devir_plan":
                            r = KkVadeAktarimService._plan_odeme_yaz(
                                session,
                                kart=kart,
                                belge_no=e["belge_no"],
                                tarih=_tarih(e["islem_tarihi"]),
                                tutar=_d(e["tutar"]),
                                vtarih=_tarih(e.get("vtarih")),
                                taksit_sayisi=int(e.get("taksit") or 1) or 1,
                                taksit_no=int(e.get("taksit_no") or 1) or 1,
                                aciklama=e.get("aciklama") or "",
                                kaynak_turu=KAYNAK_EVO_DEVIR,
                                referans_no=e.get("evo_a_id"),
                            )
                            if r.startswith("yazildi"):
                                ozet["yazilan_devir"] += 1
                            elif r == "vade_dogrulanamadi":
                                ozet["bekleyen"] += 1
                            else:
                                ozet["atlanan"] += 1
                        elif e.get("tur") == "odeme_kopru":
                            r = KkVadeAktarimService._plan_odeme_bagla(
                                session,
                                kart=kart,
                                belge_no=e["belge_no"],
                                tarih=_tarih(e["islem_tarihi"]),
                                tutar=_d(e["tutar"]),
                                aciklama=e.get("aciklama") or "",
                                finans_belge_no=e["finans_belge_no"],
                            )
                            if r == "yazildi":
                                ozet["yazilan_odeme"] += 1
                            else:
                                ozet["atlanan"] += 1
                    except Exception as exc:
                        ozet["hatalar"].append(
                            {
                                "evo_id": k["evo_id"],
                                "belge_no": e.get("belge_no"),
                                "hata": str(exc),
                            }
                        )

                # Taksit durumlarını ekstre ödemelerine göre eşitle
                for ekstre in session.scalars(
                    select(KrediKartiEkstre).where(
                        KrediKartiEkstre.kredi_karti_id == int(kart.id)
                    )
                ).all():
                    KrediKartiEkstreService._taksit_durumlarini_esitle(session, ekstre, kart)

                # Mutabakat: plan borcu vs defter
                veri = KrediKartiEkstreService.donem_borclari(
                    session, kart_ids=[int(kart.id)]
                )[int(kart.id)]
                plan_borc = _d(veri["toplam_borc"])
                defter = -_d(k["bakiye"]) if _d(k["bakiye"]) < 0 else SIFIR
                # Pozitif bakiye (alacak) → plan 0 beklenir
                if _d(k["bakiye"]) > 0:
                    defter = SIFIR
                ozet["kart_sonuclar"].append(
                    {
                        "evo_id": k["evo_id"],
                        "kredi_karti_id": int(kart.id),
                        "kart_adi": kart.kart_adi,
                        "defter_borc": str(defter if _d(k["bakiye"]) <= 0 else SIFIR),
                        "defter_bakiye": str(_d(k["bakiye"])),
                        "plan_borc": str(plan_borc),
                        "fark": str(plan_borc - (-_d(k["bakiye"]) if _d(k["bakiye"]) < 0 else SIFIR)),
                        "belirsiz": str(_d(veri["belirsiz"])),
                    }
                )

            session.commit()
            ozet["plan_ozet"] = {
                "kaynak_sha256": plan["kaynak_sha256"],
                "kart_sayisi": len(plan["kartlar"]),
            }
            return ozet

    @staticmethod
    def mutabakat(session=None) -> dict:
        """Uygulama sonrası kart bazında defter ↔ plan karşılaştırması."""

        def calis(s) -> dict:
            satirlar = []
            for es in KkVadeAktarimService.kart_eslemeleri(s):
                if not es["kredi_karti_id"]:
                    continue
                veri = KrediKartiEkstreService.donem_borclari(
                    s, kart_ids=[int(es["kredi_karti_id"])]
                )[int(es["kredi_karti_id"])]
                plan_borc = _d(veri["toplam_borc"])
                bak = _d(es["bakiye"])
                defter_borc = -bak if bak < 0 else SIFIR
                satirlar.append(
                    {
                        "evo_id": es["evo_id"],
                        "kart_adi": es["kart_adi"],
                        "defter_bakiye": str(bak),
                        "defter_borc": str(defter_borc),
                        "plan_borc": str(plan_borc),
                        "fark": str(plan_borc - defter_borc),
                        "belirsiz": str(_d(veri["belirsiz"])),
                        "donem_sayisi": len(veri["donemler"]),
                    }
                )
            return {"kartlar": satirlar}

        if session is not None:
            return calis(session)
        with get_session() as s:
            return calis(s)
