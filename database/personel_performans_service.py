"""Görev, katkı, değerlendirme, kariyer ve prim dönem servisleri."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, or_, select

from database.access import yetki_var, yetki_zorunlu, yazma_zorunlu
from database.database import get_session
from database.models.personel import DURUM_AKTIF, Personel, PersonelCalismaDonemi
from database.models.personel_performans import (
    GOREV_ALANLARI,
    GOREV_DURUMLARI_MVP,
    IS_DURUMLARI,
    IS_PLANLANDI,
    KADEME_OGRENEN,
    PRIM_BORDRO,
    PRIM_EKSIK,
    PRIM_HESAPLANDI,
    PRIM_MVP_HESAPLANDI,
    PRIM_MVP_ONAYLANDI,
    PRIM_MVP_TASLAK,
    PRIM_ONAYLI,
    PRIM_TASLAK,
    VARSAYILAN_POLITIKA_JSON,
    PersonelDegerlendirme,
    PersonelGelisimPlani,
    PersonelGorev,
    PersonelGorevAtama,
    PersonelIsGecmis,
    PersonelIsKaydi,
    PersonelKariyerKarari,
    PersonelKatki,
    PersonelKatkiOlay,
    PersonelPrimDonem,
    PersonelPrimDonemi,
    PersonelPrimPay,
    PersonelPrimPayDetay,
    PersonelPrimPolitika,
)
from database.personel_performans_sema import schema_hazirla
from database.personel_prim_motoru import (
    DagitimKisi,
    havuz_hesapla,
    kisi_dagitimi,
    kidem_katsayisi,
    tahsil_kar_katkisi,
)
from database.personel_service import _kullanici, _para, _tarih
from database.session_manager import oturum

OKU = ("personel_goruntuleme", "personel_duzenleme", "personel_performans", "goruntuleme")
YAZ = ("personel_duzenleme", "personel_performans")
PRIM_OKU = ("personel_finans_goruntuleme", "personel_prim_goruntuleme", "personel_finans_duzenleme")
PRIM_YAZ = ("personel_finans_duzenleme", "personel_prim_onay")


class PersonelPerformansService:
    @staticmethod
    def hazirla() -> None:
        schema_hazirla()

    # --- Görev atama / iş ----------------------------------------------------

    @staticmethod
    def gorev_ata(veri: dict) -> dict:
        yazma_zorunlu(*YAZ)
        schema_hazirla()
        with get_session() as session:
            if session.get(Personel, int(veri["personel_id"])) is None:
                raise ValueError("Personel bulunamadı.")
            g = PersonelGorevAtama(
                personel_id=int(veri["personel_id"]),
                donem_id=veri.get("donem_id"),
                gorev_alani=(veri.get("gorev_alani") or "SATIS").upper(),
                rol=(veri.get("rol") or "ASIL").upper(),
                yonetici_personel_id=veri.get("yonetici_personel_id"),
                gecerli_baslangic=_tarih(veri.get("gecerli_baslangic")) or date.today(),
                gecerli_bitis=_tarih(veri.get("gecerli_bitis")),
                aciklama=veri.get("aciklama"),
            )
            session.add(g)
            session.flush()
            return {"id": g.id}

    @staticmethod
    def _hedef_saat_normalize(v) -> str | None:
        s = (str(v).strip() if v is not None else "")
        if not s:
            return None
        import re

        m = re.fullmatch(r"(\d{1,2}):(\d{2})", s)
        if not m:
            raise ValueError("Hedef saat SS:DD biçiminde olmalı (ör. 14:30).")
        h, dk = int(m.group(1)), int(m.group(2))
        if h > 23 or dk > 59:
            raise ValueError("Hedef saat geçersiz.")
        return f"{h:02d}:{dk:02d}"

    @staticmethod
    def _aktif_donem_id(session, personel_id: int | None) -> int | None:
        if not personel_id:
            return None
        d = session.scalar(
            select(PersonelCalismaDonemi).where(
                PersonelCalismaDonemi.personel_id == int(personel_id),
                PersonelCalismaDonemi.aktif.is_(True),
            )
        )
        return int(d.id) if d is not None else None

    @staticmethod
    def _is_gecmis_yaz(session, is_id: int, alan: str, eski, yeni, aktor: str) -> None:
        e = None if eski is None else str(eski)
        y = None if yeni is None else str(yeni)
        if e == y:
            return
        session.add(
            PersonelIsGecmis(
                is_kaydi_id=int(is_id),
                alan=alan,
                eski_deger=e,
                yeni_deger=y,
                kullanici=aktor,
                zaman=datetime.now(),
            )
        )

    @staticmethod
    def _is_dict(k: PersonelIsKaydi, personel_map: dict[int, Personel] | None = None) -> dict:
        p = None
        if k.sorumlu_personel_id and personel_map is not None:
            p = personel_map.get(int(k.sorumlu_personel_id))
        elif k.sorumlu_personel_id:
            p = None
        atanmamis = k.sorumlu_personel_id is None
        if p is not None:
            etiket = f"{p.kod} — {p.ad} {p.soyad}".strip()
            kod, ad = p.kod, f"{p.ad} {p.soyad}".strip()
        elif atanmamis:
            etiket, kod, ad = "Atanmamış", None, "Atanmamış"
        else:
            etiket = f"Personel #{k.sorumlu_personel_id}"
            kod, ad = None, etiket
        hedef = k.hedef_tarih.isoformat() if k.hedef_tarih else None
        if hedef and k.hedef_saat:
            hedef = f"{hedef} {k.hedef_saat}"
        return {
            "id": k.id,
            "baslik": k.baslik,
            "gorev_alani": k.gorev_alani,
            "durum": k.durum,
            "sorumlu_personel_id": k.sorumlu_personel_id,
            "donem_id": k.donem_id,
            "sorumlu_kod": kod,
            "sorumlu_ad": ad,
            "sorumlu_etiket": etiket,
            "atanmamis": atanmamis,
            "hedef_tarih": k.hedef_tarih.isoformat() if k.hedef_tarih else None,
            "hedef_saat": k.hedef_saat,
            "hedef_gosterim": hedef or "",
            "oncelik": k.oncelik,
            "dis_engel": k.dis_engel,
            "aciklama": k.aciklama,
            "kaynak_belge_turu": k.kaynak_belge_turu,
            "kaynak_belge_id": k.kaynak_belge_id,
            "olusturan": k.olusturan,
            "guncelleyen": k.guncelleyen,
            "performansa_dahil": (not atanmamis) and k.durum != IS_PLANLANDI,
            "eksik_sorumlu": atanmamis,
        }

    @staticmethod
    def is_kaydet(veri: dict) -> dict:
        yazma_zorunlu(*YAZ)
        schema_hazirla()
        aktor = _kullanici()
        baslik = (veri.get("baslik") or "").strip()
        if not baslik:
            raise ValueError("İş başlığı zorunludur.")
        alan = (veri.get("gorev_alani") or "SATIS").strip().upper()
        if alan not in dict(GOREV_ALANLARI):
            raise ValueError("Geçersiz iş alanı.")
        durum = (veri.get("durum") or IS_PLANLANDI).strip().upper()
        if durum not in dict(IS_DURUMLARI):
            raise ValueError("Geçersiz iş durumu.")
        yeni_mi = not veri.get("id")
        if yeni_mi and veri.get("sorumlu_personel_id") in (None, ""):
            raise ValueError("Sorumlu personel seçilmelidir.")
        hedef_saat = (
            PersonelPerformansService._hedef_saat_normalize(veri["hedef_saat"])
            if "hedef_saat" in veri
            else None
        )

        with get_session() as session:
            if veri.get("id"):
                k = session.get(PersonelIsKaydi, int(veri["id"]))
                if k is None:
                    raise ValueError("İş kaydı bulunamadı.")
                eski_sorumlu = k.sorumlu_personel_id
                eski_durum = k.durum
                eski_baslik = k.baslik
            else:
                k = PersonelIsKaydi(
                    baslik=baslik,
                    gorev_alani=alan,
                    durum=durum,
                    olusturan=aktor,
                )
                session.add(k)
                session.flush()
                eski_sorumlu = None
                eski_durum = None
                eski_baslik = None
                PersonelPerformansService._is_gecmis_yaz(
                    session, k.id, "olusturma", None, baslik, aktor
                )

            k.baslik = baslik
            k.gorev_alani = alan
            k.durum = durum
            k.dis_engel = (veri.get("dis_engel") or "").strip() or None
            k.aciklama = (veri.get("aciklama") or "").strip() or None
            if "hedef_tarih" in veri:
                k.hedef_tarih = _tarih(veri["hedef_tarih"])
            if "hedef_saat" in veri:
                k.hedef_saat = hedef_saat
            if "oncelik" in veri:
                k.oncelik = int(veri["oncelik"])
            if "takip_personel_id" in veri:
                k.takip_personel_id = veri["takip_personel_id"] or None
            if "destek_personel_ids" in veri:
                ids = veri["destek_personel_ids"]
                k.destek_personel_ids = (
                    ",".join(str(i) for i in ids) if isinstance(ids, (list, tuple)) else ids
                )
            if "kaynak_belge_turu" in veri:
                k.kaynak_belge_turu = veri["kaynak_belge_turu"]
            if "kaynak_belge_id" in veri:
                k.kaynak_belge_id = veri["kaynak_belge_id"]
            if "gerceklesen_tarih" in veri:
                k.gerceklesen_tarih = _tarih(veri["gerceklesen_tarih"])
            if "is_buyuklugu" in veri:
                k.is_buyuklugu = _para(veri["is_buyuklugu"])

            if "sorumlu_personel_id" in veri or yeni_mi:
                sid = veri.get("sorumlu_personel_id")
                if sid in (None, ""):
                    if yeni_mi:
                        raise ValueError("Sorumlu personel seçilmelidir.")
                    k.sorumlu_personel_id = None
                    k.donem_id = None
                else:
                    p = session.get(Personel, int(sid))
                    if p is None:
                        raise ValueError("Sorumlu personel bulunamadı.")
                    k.sorumlu_personel_id = int(sid)
                    k.donem_id = PersonelPerformansService._aktif_donem_id(session, int(sid))

            # Tamamlandı → otomatik değerlendirme/prim yok (yalnız durum alanı)
            k.guncelleyen = aktor
            k.guncelleme = datetime.now()
            session.flush()

            if not yeni_mi:
                PersonelPerformansService._is_gecmis_yaz(
                    session, k.id, "baslik", eski_baslik, k.baslik, aktor
                )
                PersonelPerformansService._is_gecmis_yaz(
                    session, k.id, "sorumlu_personel_id", eski_sorumlu, k.sorumlu_personel_id, aktor
                )
                PersonelPerformansService._is_gecmis_yaz(
                    session, k.id, "durum", eski_durum, k.durum, aktor
                )
            session.flush()
            pmap: dict[int, Personel] = {}
            if k.sorumlu_personel_id:
                p = session.get(Personel, int(k.sorumlu_personel_id))
                if p is not None:
                    pmap[p.id] = p
            return PersonelPerformansService._is_dict(k, pmap)

    @staticmethod
    def is_getir(is_id: int) -> dict:
        yetki_zorunlu(*OKU)
        schema_hazirla()
        with get_session() as session:
            k = session.get(PersonelIsKaydi, int(is_id))
            if k is None:
                raise ValueError("İş kaydı bulunamadı.")
            pmap = {}
            if k.sorumlu_personel_id:
                p = session.get(Personel, int(k.sorumlu_personel_id))
                if p is not None:
                    pmap[p.id] = p
            return PersonelPerformansService._is_dict(k, pmap)

    @staticmethod
    def is_gecmis(is_id: int) -> list[dict]:
        yetki_zorunlu(*OKU)
        schema_hazirla()
        with get_session() as session:
            satirlar = session.scalars(
                select(PersonelIsGecmis)
                .where(PersonelIsGecmis.is_kaydi_id == int(is_id))
                .order_by(PersonelIsGecmis.id.desc())
            ).all()
            return [
                {
                    "id": g.id,
                    "alan": g.alan,
                    "eski_deger": g.eski_deger,
                    "yeni_deger": g.yeni_deger,
                    "kullanici": g.kullanici,
                    "zaman": g.zaman.isoformat(sep=" ", timespec="minutes") if g.zaman else None,
                }
                for g in satirlar
            ]

    @staticmethod
    def is_panosu(
        *,
        personel_id: int | None = None,
        atanmamis: bool = False,
        durum: str | None = None,
        baslik_arama: str = "",
        limit: int = 300,
    ) -> list[dict]:
        yetki_zorunlu(*OKU)
        schema_hazirla()
        with get_session() as session:
            q = select(PersonelIsKaydi).order_by(PersonelIsKaydi.oncelik, PersonelIsKaydi.id.desc())
            if atanmamis:
                q = q.where(PersonelIsKaydi.sorumlu_personel_id.is_(None))
            elif personel_id is not None:
                q = q.where(
                    or_(
                        PersonelIsKaydi.sorumlu_personel_id == int(personel_id),
                        PersonelIsKaydi.takip_personel_id == int(personel_id),
                    )
                )
            if durum:
                q = q.where(PersonelIsKaydi.durum == durum.strip().upper())
            a = (baslik_arama or "").strip()
            if a:
                q = q.where(PersonelIsKaydi.baslik.ilike(f"%{a}%"))
            kayitlar = session.scalars(q.limit(limit)).all()
            ids = {k.sorumlu_personel_id for k in kayitlar if k.sorumlu_personel_id}
            pmap: dict[int, Personel] = {}
            if ids:
                for p in session.scalars(select(Personel).where(Personel.id.in_(ids))).all():
                    pmap[p.id] = p
            return [PersonelPerformansService._is_dict(k, pmap) for k in kayitlar]

    @staticmethod
    def personel_secenekleri(*, yalniz_aktif: bool = True, arama: str = "") -> list[dict]:
        """İş atama için personel listesi — sahte kayıt üretmez."""
        yetki_zorunlu(*OKU)
        schema_hazirla()
        a = (arama or "").strip()
        with get_session() as session:
            q = select(Personel).order_by(Personel.kod)
            if yalniz_aktif:
                q = q.where(Personel.calisma_durumu == DURUM_AKTIF)
            if a:
                like = f"%{a}%"
                from sqlalchemy import func

                q = q.where(
                    or_(
                        Personel.kod.ilike(like),
                        Personel.ad.ilike(like),
                        Personel.soyad.ilike(like),
                        func.concat(Personel.ad, " ", Personel.soyad).ilike(like),
                    )
                )
            sonuc = []
            for p in session.scalars(q.limit(500)).all():
                donem = next((d for d in p.donemler if d.aktif), None)
                sonuc.append(
                    {
                        "id": p.id,
                        "kod": p.kod,
                        "ad_soyad": f"{p.ad} {p.soyad}".strip(),
                        "etiket": f"{p.kod} — {p.ad} {p.soyad}".strip(),
                        "calisma_durumu": p.calisma_durumu,
                        "donem_id": donem.id if donem else None,
                    }
                )
            return sonuc

    # --- Katkı ---------------------------------------------------------------

    @staticmethod
    def katki_kaydet(veri: dict) -> dict:
        yazma_zorunlu(*YAZ)
        schema_hazirla()
        pay = _para(veri.get("pay_yuzde") or 100)
        with get_session() as session:
            # Aynı aşamada toplam pay kontrolü (yeni kayıt)
            asama = (veri.get("asama") or "").upper()
            belge_id = int(veri["belge_id"])
            kaynak = (veri.get("kaynak_turu") or "SATIS_FATURA").upper()
            satir_id = int(veri.get("satir_id") or 0)
            mevcutlar = session.scalars(
                select(PersonelKatkiOlay).where(
                    PersonelKatkiOlay.kaynak_turu == kaynak,
                    PersonelKatkiOlay.belge_id == belge_id,
                    PersonelKatkiOlay.satir_id == satir_id,
                    PersonelKatkiOlay.asama == asama,
                    PersonelKatkiOlay.iptal.is_(False),
                )
            ).all()
            toplam_pay = sum((Decimal(m.pay_yuzde) for m in mevcutlar), Decimal("0")) + pay
            if toplam_pay > Decimal("100.0001"):
                raise ValueError("Aynı aşamanın toplam katkısı %100'ü aşamaz.")
            olay = PersonelKatkiOlay(
                personel_id=int(veri["personel_id"]),
                yapan_personel_id=int(veri.get("yapan_personel_id") or veri["personel_id"]),
                kaydeden_kullanici=_kullanici(),
                kaynak_turu=kaynak,
                belge_id=belge_id,
                satir_id=satir_id,
                asama=asama,
                olay_surum=int(veri.get("olay_surum") or 1),
                pay_yuzde=pay,
                adet=_para(veri.get("adet") or 1),
                satir_sayisi=_para(veri.get("satir_sayisi") or 0),
                zorluk=_para(veri.get("zorluk") or 1),
                hatasiz=veri.get("hatasiz"),
                tarih=_tarih(veri.get("tarih")) or date.today(),
                aciklama=veri.get("aciklama"),
            )
            session.add(olay)
            session.flush()
            return {"id": olay.id}

    @staticmethod
    def katki_raporu(personel_id: int | None = None, bas=None, bit=None) -> list[dict]:
        yetki_zorunlu(*OKU)
        schema_hazirla()
        b1 = _tarih(bas) or date.today().replace(day=1)
        b2 = _tarih(bit) or date.today()
        with get_session() as session:
            q = select(PersonelKatkiOlay).where(
                PersonelKatkiOlay.iptal.is_(False),
                PersonelKatkiOlay.tarih >= b1,
                PersonelKatkiOlay.tarih <= b2,
            )
            if personel_id:
                q = q.where(PersonelKatkiOlay.personel_id == int(personel_id))
            return [
                {
                    "id": o.id,
                    "personel_id": o.personel_id,
                    "yapan_personel_id": o.yapan_personel_id,
                    "kaydeden": o.kaydeden_kullanici,
                    "asama": o.asama,
                    "kaynak_turu": o.kaynak_turu,
                    "belge_id": o.belge_id,
                    "pay_yuzde": float(o.pay_yuzde),
                    "adet": float(o.adet),
                    "satir_sayisi": float(o.satir_sayisi),
                    "hatasiz": o.hatasiz,
                    "tarih": o.tarih.isoformat(),
                }
                for o in session.scalars(q.limit(500)).all()
            ]

    # --- Değerlendirme / kariyer ---------------------------------------------

    @staticmethod
    def degerlendirme_kaydet(veri: dict) -> dict:
        yazma_zorunlu(*YAZ)
        schema_hazirla()
        # Örnek ağırlıklar 40/30/20/10 — ayardan okunabilir
        g = _para(veri.get("gorev_sonucu") or 0)
        k = _para(veri.get("kalite") or 0)
        e = _para(veri.get("ekip_katkisi") or 0)
        gel = _para(veri.get("gelisim") or 0)
        ornek = int(veri.get("ornek_sayisi") or 0)
        eksik = bool(veri.get("eksik_veri"))
        kesin = bool(veri.get("kesin")) and not eksik and ornek >= int(veri.get("ornek_alt_sinir") or 5)
        toplam = g * Decimal("0.40") + k * Decimal("0.30") + e * Decimal("0.20") + gel * Decimal("0.10")
        with get_session() as session:
            d = session.scalar(
                select(PersonelDegerlendirme).where(
                    PersonelDegerlendirme.personel_id == int(veri["personel_id"]),
                    PersonelDegerlendirme.yil == int(veri["yil"]),
                    PersonelDegerlendirme.ay == int(veri["ay"]),
                )
            )
            if d is None:
                d = PersonelDegerlendirme(
                    personel_id=int(veri["personel_id"]),
                    yil=int(veri["yil"]),
                    ay=int(veri["ay"]),
                )
                session.add(d)
            d.gorev_sonucu, d.kalite, d.ekip_katkisi, d.gelisim = g, k, e, gel
            d.toplam_puan = toplam.quantize(Decimal("0.01"))
            d.ornek_sayisi = ornek
            d.eksik_veri = eksik
            d.kesin = kesin
            d.calisan_aciklama = veri.get("calisan_aciklama")
            d.itiraz = veri.get("itiraz")
            d.degerlendiren = _kullanici()
            d.olcut_surum = veri.get("olcut_surum") or "2026-10-16"
            session.flush()
            return {
                "id": d.id,
                "toplam_puan": float(d.toplam_puan),
                "kesin": d.kesin,
                "eksik_veri": d.eksik_veri,
            }

    @staticmethod
    def gelisim_plani(veri: dict) -> dict:
        yazma_zorunlu(*YAZ)
        schema_hazirla()
        bas = _tarih(veri.get("baslangic")) or date.today()
        bit = _tarih(veri.get("bitis")) or (bas + timedelta(days=90))
        with get_session() as session:
            p = PersonelGelisimPlani(
                personel_id=int(veri["personel_id"]),
                baslangic=bas,
                bitis=bit,
                hedef_beceri=(veri.get("hedef_beceri") or "").strip() or "Beceri",
                egitim_destegi=veri.get("egitim_destegi"),
                uygulama_gorevi=veri.get("uygulama_gorevi"),
                kontrol_tarihi=_tarih(veri.get("kontrol_tarihi")),
            )
            session.add(p)
            session.flush()
            return {"id": p.id, "baslangic": bas.isoformat(), "bitis": bit.isoformat()}

    @staticmethod
    def kariyer_karari(veri: dict) -> dict:
        yazma_zorunlu(*YAZ)
        schema_hazirla()
        with get_session() as session:
            k = PersonelKariyerKarari(
                personel_id=int(veri["personel_id"]),
                yol=(veri.get("yol") or "UZMANLIK").upper(),
                kademe=(veri.get("kademe") or KADEME_OGRENEN).upper(),
                unvan=veri.get("unvan"),
                gorev=veri.get("gorev"),
                ucret_bandi=veri.get("ucret_bandi"),
                gecerlilik=_tarih(veri.get("gecerlilik")) or date.today(),
                karar_veren=_kullanici(),
                eksik_kosullar=veri.get("eksik_kosullar"),
                onayli=bool(veri.get("onayli")),
                ortaklik_degil=True,
                aciklama=veri.get("aciklama"),
            )
            session.add(k)
            session.flush()
            return {"id": k.id, "kademe": k.kademe, "ortaklik_degil": True}

    # --- Prim dönemi ---------------------------------------------------------

    @staticmethod
    def politika_getir(referans: date | None = None) -> dict | None:
        yetki_zorunlu(*PRIM_OKU)
        schema_hazirla()
        referans = referans or date.today()
        with get_session() as session:
            p = session.scalar(
                select(PersonelPrimPolitika)
                .where(
                    PersonelPrimPolitika.aktif.is_(True),
                    PersonelPrimPolitika.gecerli_baslangic <= referans,
                    or_(
                        PersonelPrimPolitika.gecerli_bitis.is_(None),
                        PersonelPrimPolitika.gecerli_bitis >= referans,
                    ),
                )
                .order_by(PersonelPrimPolitika.gecerli_baslangic.desc())
            )
            if p is None:
                return None
            return {
                "id": p.id,
                "kod": p.kod,
                "surum": p.surum,
                "prim_orani": float(p.prim_orani),
                "guvence_tutari": float(p.guvence_tutari),
                "agirlik_ekip": float(p.agirlik_ekip),
                "agirlik_katki": float(p.agirlik_katki),
                "agirlik_kidem": float(p.agirlik_kidem),
                "canli_politika": p.canli_politika,
                "aciklama": p.aciklama,
            }

    @staticmethod
    def donem_olustur(baslangic, bitis, *, simulasyon: bool = True) -> dict:
        yazma_zorunlu(*PRIM_YAZ)
        schema_hazirla()
        b1, b2 = _tarih(baslangic), _tarih(bitis)
        if not b1 or not b2 or b2 < b1:
            raise ValueError("Geçersiz dönem aralığı.")
        with get_session() as session:
            cakisanlar = session.scalars(
                select(PersonelPrimDonemi).where(
                    PersonelPrimDonemi.baslangic <= b2,
                    PersonelPrimDonemi.bitis >= b1,
                    PersonelPrimDonemi.durum != "IPTAL",
                )
            ).all()
            for c in cakisanlar:
                if c.simulasyon and simulasyon:
                    c.durum = "IPTAL"
                else:
                    raise ValueError("Dönemler çakışmamalı.")
            pol = session.scalar(
                select(PersonelPrimPolitika)
                .where(PersonelPrimPolitika.aktif.is_(True))
                .order_by(PersonelPrimPolitika.gecerli_baslangic.desc())
            )
            d = PersonelPrimDonemi(
                baslangic=b1,
                bitis=b2,
                durum=PRIM_TASLAK,
                politika_id=pol.id if pol else None,
                politika_surum=pol.surum if pol else None,
                guvence=pol.guvence_tutari if pol else 0,
                simulasyon=bool(simulasyon),
                hesaplayan=_kullanici(),
            )
            session.add(d)
            session.flush()
            return {"id": d.id, "durum": d.durum, "simulasyon": d.simulasyon}

    @staticmethod
    def donem_hesapla(
        donem_id: int,
        *,
        tahsil_kar=None,
        uygun_gider=None,
        onceki_zarar=None,
        kisiler: list[dict] | None = None,
        fatura_satirlari: list[dict] | None = None,
    ) -> dict:
        """Simülasyon veya manuel girdilerle havuz + dağıtım. Canlı ödeme üretmez."""
        yazma_zorunlu(*PRIM_YAZ)
        schema_hazirla()
        with get_session() as session:
            d = session.get(PersonelPrimDonemi, int(donem_id))
            if d is None:
                raise ValueError("Dönem bulunamadı.")
            if d.durum in (PRIM_ONAYLI, PRIM_BORDRO, PRIM_ODENDI):
                raise ValueError("Onaylı/ödendi dönem sessizce yeniden hesaplanamaz.")
            pol = session.get(PersonelPrimPolitika, d.politika_id) if d.politika_id else None

            eksik = False
            if fatura_satirlari is not None:
                toplam_h_fark = Decimal("0")
                for fs in fatura_satirlari:
                    if fs.get("eksik_maliyet") or fs.get("eksik_tahsilat"):
                        eksik = True
                    h = tahsil_kar_katkisi(
                        S=fs["S"], C=fs["C"], F=fs["F"], T=fs["T"]
                    )
                    h_once = _para(fs.get("H_once") or 0)
                    toplam_h_fark += h["H"] - h_once
                tahsil_kar = toplam_h_fark
            else:
                tahsil_kar = _para(tahsil_kar if tahsil_kar is not None else d.tahsil_kar)

            uygun_gider = _para(uygun_gider if uygun_gider is not None else d.uygun_gider)
            onceki_zarar = _para(onceki_zarar if onceki_zarar is not None else d.onceki_zarar)
            guvence = pol.guvence_tutari if pol else d.guvence
            oran = pol.prim_orani if pol else Decimal("0.10")

            havuz = havuz_hesapla(
                tahsil_kar_katkisi_toplam=tahsil_kar,
                uygun_giderler=uygun_gider,
                onceki_zarar_devri=onceki_zarar,
                guvence_tutari=guvence,
                prim_orani=oran,
            )
            d.tahsil_kar = havuz and tahsil_kar  # type: ignore
            d.tahsil_kar = _para(tahsil_kar)
            d.uygun_gider = uygun_gider
            d.onceki_zarar = onceki_zarar
            d.yeni_zarar = havuz["yeni_zarar_devri"]
            d.guvence = havuz["guvence_tutari"]
            d.taban_b = havuz["B"]
            d.prim_butcesi = havuz["prim_butcesi"]
            d.eksik_veri = eksik
            d.hesaplayan = _kullanici()
            d.durum = PRIM_EKSIK if eksik else PRIM_HESAPLANDI

            # Eski payları temizle (idempotent yeniden hesap)
            for eski in session.scalars(
                select(PersonelPrimPayDetay).where(PersonelPrimPayDetay.donem_id == d.id)
            ).all():
                session.delete(eski)
            session.flush()

            dagitim_kisiler = []
            for k in kisiler or []:
                dagitim_kisiler.append(
                    DagitimKisi(
                        personel_id=int(k["personel_id"]),
                        hizmet_yili=int(k.get("hizmet_yili") or 0),
                        performans=_para(k.get("performans") or 0),
                        katilim=_para(k.get("katilim") or 1),
                    )
                )
            dag = kisi_dagitimi(
                havuz["prim_butcesi"],
                dagitim_kisiler,
                agirlik_ekip=pol.agirlik_ekip if pol else Decimal("0.50"),
                agirlik_katki=pol.agirlik_katki if pol else Decimal("0.30"),
                agirlik_kidem=pol.agirlik_kidem if pol else Decimal("0.20"),
            )
            for s in dag["kisiler"]:
                session.add(
                    PersonelPrimPayDetay(
                        donem_id=d.id,
                        personel_id=s["personel_id"],
                        katilim=s["katilim"],
                        performans=s["performans"],
                        kidem_katsayi=s["kidem_katsayi"],
                        ekip_payi=s["ekip_payi"],
                        katki_payi=s["katki_payi"],
                        kidem_payi=s["kidem_payi"],
                        toplam=s["toplam"],
                        hak_edilen=s["toplam"],
                        odenen=0,
                        kalan=s["toplam"],
                    )
                )
            d.dagitilan = dag["dagitilan"]
            d.dagitilmamis = dag["dagitilmamis"]
            session.flush()
            return {
                "donem_id": d.id,
                "durum": d.durum,
                "havuz": {k: float(v) if isinstance(v, Decimal) else v for k, v in havuz.items()},
                "dagitim": {
                    "butce": float(dag["butce"]),
                    "dagitilan": float(dag["dagitilan"]),
                    "dagitilmamis": float(dag["dagitilmamis"]),
                    "katki_dilimi_dagitilmadi": dag["katki_dilimi_dagitilmadi"],
                    "kisiler": [
                        {**{kk: float(vv) if isinstance(vv, Decimal) else vv for kk, vv in s.items()}}
                        for s in dag["kisiler"]
                    ],
                },
                "simulasyon": d.simulasyon,
                "eksik_veri": d.eksik_veri,
                "uyari": "Simülasyon gerçek ödeme/fiş üretmez." if d.simulasyon else None,
            }

    @staticmethod
    def donem_onayla(donem_id: int) -> dict:
        yazma_zorunlu("personel_prim_onay", "personel_finans_duzenleme")
        schema_hazirla()
        with get_session() as session:
            d = session.get(PersonelPrimDonemi, int(donem_id))
            if d is None:
                raise ValueError("Dönem bulunamadı.")
            if d.eksik_veri or d.durum == PRIM_EKSIK:
                raise ValueError("Eksik veri varken dönem onaylanamaz.")
            if d.durum not in (PRIM_HESAPLANDI, "INCELEMEDE"):
                raise ValueError("Yalnız hesaplanmış dönem onaylanır.")
            d.durum = PRIM_ONAYLI
            d.onaylayan = _kullanici()
            d.onay_zamani = datetime.now()
            session.flush()
            return {"id": d.id, "durum": d.durum}

    @staticmethod
    def bordroya_aktar(donem_id: int, *, yil: int | None = None, ay: int | None = None) -> dict:
        """MVP stub — vergi/SGK/bordro motoru yok; bağlantı üretilmez."""
        yazma_zorunlu("personel_prim_onay", "personel_finans_duzenleme")
        schema_hazirla()
        _ = (donem_id, yil, ay)
        return {"baglandi": False, "neden": "BORDRO_BAGLANTI_MVP"}

    @staticmethod
    def _pay_ozet(donem_id: int) -> list[dict]:
        with get_session() as session:
            return [
                {
                    "id": p.id,
                    "personel_id": p.personel_id,
                    "toplam": float(p.toplam),
                    "hakedis_id": p.hakedis_id,
                }
                for p in session.scalars(
                    select(PersonelPrimPayDetay).where(
                        PersonelPrimPayDetay.donem_id == int(donem_id)
                    )
                ).all()
            ]

    @staticmethod
    def _aktif_donem(personel_id: int) -> int:
        from database.models.personel import PersonelCalismaDonemi

        with get_session() as session:
            d = session.scalar(
                select(PersonelCalismaDonemi).where(
                    PersonelCalismaDonemi.personel_id == int(personel_id),
                    PersonelCalismaDonemi.aktif.is_(True),
                )
            )
            if d is None:
                raise ValueError("Aktif çalışma dönemi yok.")
            return int(d.id)

    @staticmethod
    def donem_getir(donem_id: int) -> dict:
        yetki_zorunlu(*PRIM_OKU)
        schema_hazirla()
        # Başkasının ücretini gizle
        finans = yetki_var(*PRIM_OKU)
        with get_session() as session:
            d = session.get(PersonelPrimDonemi, int(donem_id))
            if d is None:
                raise ValueError("Dönem bulunamadı.")
            paylar = []
            for p in session.scalars(
                select(PersonelPrimPayDetay).where(PersonelPrimPayDetay.donem_id == d.id)
            ).all():
                if finans:
                    paylar.append(
                        {
                            "personel_id": p.personel_id,
                            "performans": float(p.performans),
                            "kidem_katsayi": float(p.kidem_katsayi),
                            "ekip_payi": float(p.ekip_payi),
                            "katki_payi": float(p.katki_payi),
                            "kidem_payi": float(p.kidem_payi),
                            "toplam": float(p.toplam),
                            "hakedis_id": p.hakedis_id,
                        }
                    )
                else:
                    paylar.append({"personel_id": p.personel_id, "toplam": None})
            return {
                "id": d.id,
                "baslangic": d.baslangic.isoformat(),
                "bitis": d.bitis.isoformat(),
                "durum": d.durum,
                "tahsil_kar": float(d.tahsil_kar) if finans else None,
                "uygun_gider": float(d.uygun_gider) if finans else None,
                "prim_butcesi": float(d.prim_butcesi) if finans else None,
                "dagitilan": float(d.dagitilan) if finans else None,
                "dagitilmamis": float(d.dagitilmamis) if finans else None,
                "eksik_veri": d.eksik_veri,
                "simulasyon": d.simulasyon,
                "politika_surum": d.politika_surum,
                "paylar": paylar,
            }

    # --- MVP Ölçme / Prim ----------------------------------------------------

    @staticmethod
    def politika_agirliklari(politika_json: str | None = None) -> dict[str, Decimal]:
        """politika_json → ekip/katki/kidem (oran 0–1). Toplam %100 zorunlu."""
        import json

        ham = (politika_json or VARSAYILAN_POLITIKA_JSON).strip() or VARSAYILAN_POLITIKA_JSON
        try:
            veri = json.loads(ham)
        except Exception as exc:
            raise ValueError("politika_json geçersiz JSON.") from exc
        ekip = Decimal(str(veri.get("ekip", 50)))
        katki = Decimal(str(veri.get("katki", 30)))
        kidem = Decimal(str(veri.get("kidem", 20)))
        # Yüzde veya oran kabul et
        if ekip + katki + kidem > Decimal("1.0001"):
            ekip, katki, kidem = ekip / 100, katki / 100, kidem / 100
        toplam = ekip + katki + kidem
        if abs(toplam - Decimal("1")) > Decimal("0.0001"):
            raise ValueError("Dağıtım ağırlıkları toplamı %100 olmalı.")
        return {"ekip": ekip, "katki": katki, "kidem": kidem}

    @staticmethod
    def tahsil_kar_h(*, S, C, F=None, T=None, tahsilat_orani=None) -> dict:
        """H = M × q. Örnek: S=100000 C=70000 tahsilat %50 → H=15000."""
        if tahsilat_orani is not None and F is None and T is None:
            m = _para(S) - _para(C)
            f = abs(m) if m != 0 else Decimal("1")
            # Marj üzerinden oran: F=S varsayımı yerine doğrudan q
            from database.personel_prim_motoru import D, q2

            q = min(Decimal("1"), max(Decimal("0"), D(tahsilat_orani)))
            return {
                "S": q2(D(S)),
                "C": q2(D(C)),
                "M": q2(m),
                "q": q,
                "H": q2(m * q),
            }
        f_val = F if F is not None else S
        t_val = T if T is not None else (
            Decimal(str(F if F is not None else S)) * Decimal(str(tahsilat_orani or 0))
        )
        return tahsil_kar_katkisi(S=S, C=C, F=f_val, T=t_val)

    @staticmethod
    def gorev_mvp_kaydet(veri: dict) -> dict:
        yazma_zorunlu(*YAZ)
        schema_hazirla()
        baslik = (veri.get("baslik") or "").strip()
        if not baslik:
            raise ValueError("Görev başlığı zorunludur.")
        durum = (veri.get("durum") or IS_PLANLANDI).strip().upper()
        if durum not in dict(GOREV_DURUMLARI_MVP):
            raise ValueError("Geçersiz görev durumu (PLANLANDI|BASLADI|ENGELLENDI|KONTROL|TAMAMLANDI).")
        with get_session() as session:
            if session.get(Personel, int(veri["personel_id"])) is None:
                raise ValueError("Personel bulunamadı.")
            if veri.get("id"):
                g = session.get(PersonelGorev, int(veri["id"]))
                if g is None:
                    raise ValueError("Görev bulunamadı.")
            else:
                g = PersonelGorev(personel_id=int(veri["personel_id"]), baslik=baslik)
                session.add(g)
            g.personel_id = int(veri["personel_id"])
            g.baslik = baslik
            g.durum = durum
            g.hedef_tarih = _tarih(veri.get("hedef_tarih"))
            g.gerceklesen_tarih = _tarih(veri.get("gerceklesen_tarih"))
            g.aciklama = (veri.get("aciklama") or "").strip() or None
            session.flush()
            return {
                "id": g.id,
                "personel_id": g.personel_id,
                "baslik": g.baslik,
                "durum": g.durum,
                "hedef_tarih": g.hedef_tarih.isoformat() if g.hedef_tarih else None,
                "gerceklesen_tarih": g.gerceklesen_tarih.isoformat() if g.gerceklesen_tarih else None,
            }

    @staticmethod
    def katki_mvp_kaydet(veri: dict) -> dict:
        yazma_zorunlu(*YAZ)
        schema_hazirla()
        with get_session() as session:
            if session.get(Personel, int(veri["personel_id"])) is None:
                raise ValueError("Personel bulunamadı.")
            k = session.scalar(
                select(PersonelKatki).where(
                    PersonelKatki.personel_id == int(veri["personel_id"]),
                    PersonelKatki.belge_turu == (veri.get("belge_turu") or "SATIS_FATURA").upper(),
                    PersonelKatki.belge_id == int(veri["belge_id"]),
                    PersonelKatki.asama == (veri.get("asama") or "").upper(),
                )
            )
            if k is None:
                k = PersonelKatki(
                    personel_id=int(veri["personel_id"]),
                    belge_turu=(veri.get("belge_turu") or "SATIS_FATURA").upper(),
                    belge_id=int(veri["belge_id"]),
                    asama=(veri.get("asama") or "HAZIRLAMA").upper(),
                )
                session.add(k)
            k.puan = _para(veri.get("puan") or 0)
            k.tarih = _tarih(veri.get("tarih")) or date.today()
            k.aciklama = veri.get("aciklama")
            session.flush()
            return {
                "id": k.id,
                "personel_id": k.personel_id,
                "belge_turu": k.belge_turu,
                "belge_id": k.belge_id,
                "asama": k.asama,
                "puan": float(k.puan),
            }

    @staticmethod
    def prim_donem_listele() -> list[dict]:
        yetki_zorunlu(*PRIM_OKU)
        schema_hazirla()
        with get_session() as session:
            satirlar = session.scalars(
                select(PersonelPrimDonem).order_by(
                    PersonelPrimDonem.yil.desc(), PersonelPrimDonem.ay.desc()
                )
            ).all()
            return [
                {
                    "id": d.id,
                    "yil": d.yil,
                    "ay": d.ay,
                    "durum": d.durum,
                    "havuz": float(d.havuz),
                    "politika_json": d.politika_json,
                    "etiket": f"{d.yil}-{d.ay:02d} · {d.durum} · havuz {float(d.havuz):,.2f}",
                }
                for d in satirlar
            ]

    @staticmethod
    def prim_donem_olustur(
        yil: int,
        ay: int,
        *,
        havuz=0,
        politika_json: str | None = None,
        aciklama: str | None = None,
    ) -> dict:
        yazma_zorunlu(*PRIM_YAZ)
        schema_hazirla()
        yil, ay = int(yil), int(ay)
        if ay < 1 or ay > 12:
            raise ValueError("Ay 1–12 olmalı.")
        pol = politika_json or VARSAYILAN_POLITIKA_JSON
        PersonelPerformansService.politika_agirliklari(pol)  # doğrula
        with get_session() as session:
            mevcut = session.scalar(
                select(PersonelPrimDonem).where(
                    PersonelPrimDonem.yil == yil, PersonelPrimDonem.ay == ay
                )
            )
            if mevcut is not None:
                return {
                    "id": mevcut.id,
                    "yil": mevcut.yil,
                    "ay": mevcut.ay,
                    "durum": mevcut.durum,
                    "havuz": float(mevcut.havuz),
                    "politika_json": mevcut.politika_json,
                    "mevcut": True,
                }
            d = PersonelPrimDonem(
                yil=yil,
                ay=ay,
                durum=PRIM_MVP_TASLAK,
                havuz=_para(havuz),
                politika_json=pol,
                aciklama=aciklama,
            )
            session.add(d)
            session.flush()
            return {
                "id": d.id,
                "yil": d.yil,
                "ay": d.ay,
                "durum": d.durum,
                "havuz": float(d.havuz),
                "politika_json": d.politika_json,
                "mevcut": False,
            }

    @staticmethod
    def prim_hesapla(
        donem_id: int,
        *,
        kisiler: list[dict] | None = None,
        havuz=None,
    ) -> dict:
        """Havuzu 50/30/20 (politika_json) ile dağıtır. Yeniden çalıştırma pay çoğaltmaz."""
        yazma_zorunlu(*PRIM_YAZ)
        schema_hazirla()
        with get_session() as session:
            d = session.get(PersonelPrimDonem, int(donem_id))
            if d is None:
                raise ValueError("Prim dönemi bulunamadı.")
            if d.durum == PRIM_MVP_ONAYLANDI:
                raise ValueError("Onaylı dönem sessizce yeniden hesaplanamaz.")
            if havuz is not None:
                d.havuz = _para(havuz)
            agirlik = PersonelPerformansService.politika_agirliklari(d.politika_json)

            # Katkı puanlarından otomatik kişi listesi (verilmediyse)
            if kisiler is None:
                bas = date(d.yil, d.ay, 1)
                if d.ay == 12:
                    bit = date(d.yil + 1, 1, 1) - timedelta(days=1)
                else:
                    bit = date(d.yil, d.ay + 1, 1) - timedelta(days=1)
                katkilar = session.scalars(
                    select(PersonelKatki).where(
                        PersonelKatki.tarih >= bas, PersonelKatki.tarih <= bit
                    )
                ).all()
                puan_map: dict[int, Decimal] = {}
                for k in katkilar:
                    puan_map[k.personel_id] = puan_map.get(k.personel_id, Decimal("0")) + Decimal(
                        k.puan
                    )
                kisiler = [
                    {
                        "personel_id": pid,
                        "hizmet_yili": 0,
                        "performans": float(puan) if puan <= 100 else 100,
                        "katilim": 1,
                    }
                    for pid, puan in sorted(puan_map.items())
                ]

            dagitim_kisiler = [
                DagitimKisi(
                    personel_id=int(k["personel_id"]),
                    hizmet_yili=int(k.get("hizmet_yili") or 0),
                    performans=_para(k.get("performans") if k.get("performans") is not None else 100),
                    katilim=_para(k.get("katilim") or 1),
                )
                for k in (kisiler or [])
            ]
            dag = kisi_dagitimi(
                d.havuz,
                dagitim_kisiler,
                agirlik_ekip=agirlik["ekip"],
                agirlik_katki=agirlik["katki"],
                agirlik_kidem=agirlik["kidem"],
            )

            # Idempotent: mevcut payları sil, yeniden yaz
            for eski in session.scalars(
                select(PersonelPrimPay).where(PersonelPrimPay.donem_id == d.id)
            ).all():
                session.delete(eski)
            session.flush()

            pay_satirlari = []
            for s in dag["kisiler"]:
                pay = PersonelPrimPay(
                    donem_id=d.id,
                    personel_id=s["personel_id"],
                    tutar=s["toplam"],
                    ekip_pay=s["ekip_payi"],
                    katki_pay=s["katki_payi"],
                    kidem_pay=s["kidem_payi"],
                )
                session.add(pay)
                pay_satirlari.append(
                    {
                        "personel_id": s["personel_id"],
                        "tutar": float(s["toplam"]),
                        "ekip_pay": float(s["ekip_payi"]),
                        "katki_pay": float(s["katki_payi"]),
                        "kidem_pay": float(s["kidem_payi"]),
                    }
                )
            d.durum = PRIM_MVP_HESAPLANDI
            d.hesaplayan = _kullanici()
            d.hesap_zamani = datetime.now()
            session.flush()
            return {
                "donem_id": d.id,
                "yil": d.yil,
                "ay": d.ay,
                "durum": d.durum,
                "havuz": float(d.havuz),
                "politika_json": d.politika_json,
                "dagitilan": float(dag["dagitilan"]),
                "dagitilmamis": float(dag["dagitilmamis"]),
                "paylar": pay_satirlari,
            }

    @staticmethod
    def prim_paylari(donem_id: int) -> list[dict]:
        yetki_zorunlu(*PRIM_OKU)
        schema_hazirla()
        with get_session() as session:
            return [
                {
                    "id": p.id,
                    "donem_id": p.donem_id,
                    "personel_id": p.personel_id,
                    "tutar": float(p.tutar),
                    "ekip_pay": float(p.ekip_pay),
                    "katki_pay": float(p.katki_pay),
                    "kidem_pay": float(p.kidem_pay),
                }
                for p in session.scalars(
                    select(PersonelPrimPay)
                    .where(PersonelPrimPay.donem_id == int(donem_id))
                    .order_by(PersonelPrimPay.personel_id)
                ).all()
            ]

    @staticmethod
    def prim_onayla(donem_id: int) -> dict:
        yazma_zorunlu("personel_prim_onay", "personel_finans_duzenleme")
        schema_hazirla()
        with get_session() as session:
            d = session.get(PersonelPrimDonem, int(donem_id))
            if d is None:
                raise ValueError("Prim dönemi bulunamadı.")
            if d.durum != PRIM_MVP_HESAPLANDI:
                raise ValueError("Yalnız hesaplanmış dönem onaylanır.")
            d.durum = PRIM_MVP_ONAYLANDI
            session.flush()
            return {"id": d.id, "durum": d.durum}

    @staticmethod
    def prim_bordroya_bagla(donem_id: int) -> dict:
        """Onaylı prim → bordro bağlantısı (MVP stub, vergi motoru yok)."""
        yazma_zorunlu("personel_prim_onay", "personel_finans_duzenleme")
        schema_hazirla()
        with get_session() as session:
            d = session.get(PersonelPrimDonem, int(donem_id))
            if d is None:
                raise ValueError("Prim dönemi bulunamadı.")
            if d.durum != PRIM_MVP_ONAYLANDI:
                raise ValueError("Bordro bağlantısı için onaylı dönem gerekir.")
        return {"baglandi": False, "neden": "BORDRO_BAGLANTI_MVP", "donem_id": int(donem_id)}
