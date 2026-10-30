"""Görev, katkı, değerlendirme, kariyer ve prim dönem servisleri."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, or_, select

from database.access import yetki_var, yetki_zorunlu, yazma_zorunlu
from database.database import get_session
from database.models.personel import (
    DURUM_AKTIF,
    HAKEDIS_IPTAL,
    HAKEDIS_ONAYLI,
    HAKEDIS_TASLAK,
    HAREKET_MAAS_ODEME,
    Personel,
    PersonelCalismaDonemi,
    PersonelHakedis,
    PersonelHesapHareketi,
)
from database.models.personel_performans import (
    BORDRO_KAYNAK_ON_EK,
    GOREV_ALANLARI,
    GOREV_DURUMLARI_MVP,
    IS_DURUMLARI,
    IS_PLANLANDI,
    KADEME_OGRENEN,
    PRIM_ACIK_DURUMLAR,
    PRIM_BORDRO,
    PRIM_DURUMLARI,
    PRIM_EKSIK,
    PRIM_GECISLER,
    PRIM_HESAPLANDI,
    PRIM_INCELEME,
    PRIM_KAPALI_DURUMLAR,
    PRIM_MVP_HESAPLANDI,
    PRIM_MVP_ONAYLANDI,
    PRIM_MVP_TASLAK,
    PRIM_ODENDI,
    PRIM_ONAYLI,
    PRIM_TASLAK,
    VARSAYILAN_OLCUT_SURUM,
    VARSAYILAN_POLITIKA_JSON,
    PersonelDegerlendirme,
    PersonelFaturaHDonuk,
    PersonelGelisimPlani,
    PersonelGorev,
    PersonelGorevAtama,
    PersonelIsGecmis,
    PersonelIsKaydi,
    PersonelKariyerKarari,
    PersonelKatki,
    PersonelKatkiOlay,
    PersonelOlcutSurumu,
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
    def olcut_agirliklari(surum: str | None = None) -> dict[str, Decimal]:
        """Sürümlü ölçüt ağırlıkları (görev/kalite/ekip/gelişim). Eksikte 40/30/20/10."""
        schema_hazirla()
        surum = (surum or VARSAYILAN_OLCUT_SURUM).strip()
        varsayilan = {
            "gorev_sonucu": Decimal("0.40"),
            "kalite": Decimal("0.30"),
            "ekip_katkisi": Decimal("0.20"),
            "gelisim": Decimal("0.10"),
        }
        kod_map = {
            "GOREV_SONUCU": "gorev_sonucu",
            "KALITE": "kalite",
            "EKIP": "ekip_katkisi",
            "GELISIM": "gelisim",
        }
        with get_session() as session:
            satirlar = session.scalars(
                select(PersonelOlcutSurumu).where(
                    PersonelOlcutSurumu.surum == surum,
                    PersonelOlcutSurumu.aktif.is_(True),
                )
            ).all()
            if not satirlar:
                return varsayilan
            sonuc = dict(varsayilan)
            for o in satirlar:
                key = kod_map.get(o.kod)
                if key:
                    sonuc[key] = Decimal(o.agirlik)
            return sonuc

    @staticmethod
    def olcut_surum_listele() -> list[dict]:
        yetki_zorunlu(*OKU)
        schema_hazirla()
        with get_session() as session:
            satirlar = session.scalars(
                select(PersonelOlcutSurumu)
                .where(PersonelOlcutSurumu.aktif.is_(True))
                .order_by(PersonelOlcutSurumu.surum.desc(), PersonelOlcutSurumu.kod)
            ).all()
            return [
                {
                    "id": o.id,
                    "kod": o.kod,
                    "surum": o.surum,
                    "gorev_alani": o.gorev_alani,
                    "ad": o.ad,
                    "agirlik": float(o.agirlik),
                    "hedef": float(o.hedef) if o.hedef is not None else None,
                    "ornek_alt_sinir": o.ornek_alt_sinir,
                    "yuksek_iyi": o.yuksek_iyi,
                }
                for o in satirlar
            ]

    @staticmethod
    def olcut_surum_kaydet(veri: dict) -> dict:
        """Yeni ölçüt sürümü ekler; mevcut sürümleri silmez (kapalı dönemler korunur)."""
        yazma_zorunlu(*YAZ)
        schema_hazirla()
        surum = (veri.get("surum") or "").strip()
        if not surum:
            raise ValueError("Ölçüt sürümü zorunludur.")
        kod = (veri.get("kod") or "").strip().upper()
        if not kod:
            raise ValueError("Ölçüt kodu zorunludur.")
        with get_session() as session:
            mevcut = session.scalar(
                select(PersonelOlcutSurumu).where(
                    PersonelOlcutSurumu.kod == kod,
                    PersonelOlcutSurumu.surum == surum,
                )
            )
            if mevcut is not None:
                raise ValueError(
                    f"Ölçüt {kod}/{surum} zaten var. Kapalı dönemleri korumak için yeni sürüm kullanın."
                )
            o = PersonelOlcutSurumu(
                kod=kod,
                surum=surum,
                gorev_alani=(veri.get("gorev_alani") or "SATIS").upper(),
                ad=(veri.get("ad") or kod).strip(),
                agirlik=_para(veri.get("agirlik") or 0),
                hedef=_para(veri["hedef"]) if veri.get("hedef") is not None else None,
                ornek_alt_sinir=int(veri.get("ornek_alt_sinir") or 5),
                yuksek_iyi=bool(veri.get("yuksek_iyi", True)),
                veri_kaynagi=veri.get("veri_kaynagi"),
                aktif=True,
            )
            session.add(o)
            session.flush()
            return {"id": o.id, "kod": o.kod, "surum": o.surum, "agirlik": float(o.agirlik)}

    @staticmethod
    def degerlendirme_kaydet(veri: dict) -> dict:
        yazma_zorunlu(*YAZ)
        schema_hazirla()
        g = _para(veri.get("gorev_sonucu") or 0)
        k = _para(veri.get("kalite") or 0)
        e = _para(veri.get("ekip_katkisi") or 0)
        gel = _para(veri.get("gelisim") or 0)
        ornek = int(veri.get("ornek_sayisi") or 0)
        eksik = bool(veri.get("eksik_veri"))
        surum = (veri.get("olcut_surum") or VARSAYILAN_OLCUT_SURUM).strip()
        agirlik = PersonelPerformansService.olcut_agirliklari(surum)
        ornek_alt = int(veri.get("ornek_alt_sinir") or 5)
        kesin = bool(veri.get("kesin")) and not eksik and ornek >= ornek_alt
        toplam = (
            g * agirlik["gorev_sonucu"]
            + k * agirlik["kalite"]
            + e * agirlik["ekip_katkisi"]
            + gel * agirlik["gelisim"]
        )
        with get_session() as session:
            d = session.scalar(
                select(PersonelDegerlendirme).where(
                    PersonelDegerlendirme.personel_id == int(veri["personel_id"]),
                    PersonelDegerlendirme.yil == int(veri["yil"]),
                    PersonelDegerlendirme.ay == int(veri["ay"]),
                )
            )
            # Kesin kayıt + kapalı prim dönemi: ağırlık sürümü sessizce değişmez
            if d is not None and d.kesin and d.olcut_surum and d.olcut_surum != surum:
                kapali = session.scalar(
                    select(PersonelPrimDonem).where(
                        PersonelPrimDonem.yil == int(veri["yil"]),
                        PersonelPrimDonem.ay == int(veri["ay"]),
                        PersonelPrimDonem.durum.in_(tuple(PRIM_KAPALI_DURUMLAR)),
                    )
                )
                if kapali is not None and not veri.get("zorla"):
                    raise ValueError(
                        "Kapalı dönemin kesin değerlendirmesi yeni ölçüt sürümüyle sessizce "
                        "yeniden yazılmaz. Yeni sürüm için açık dönem veya zorla=True gerekir."
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
            d.olcut_surum = surum
            session.flush()
            return {
                "id": d.id,
                "toplam_puan": float(d.toplam_puan),
                "kesin": d.kesin,
                "eksik_veri": d.eksik_veri,
                "olcut_surum": d.olcut_surum,
                "agirliklar": {kk: float(vv) for kk, vv in agirlik.items()},
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
        """Unvan / görev / ücret bandı / geçerlilik ile kariyer karar kaydı."""
        yazma_zorunlu(*YAZ)
        schema_hazirla()
        with get_session() as session:
            if session.get(Personel, int(veri["personel_id"])) is None:
                raise ValueError("Personel bulunamadı.")
            if veri.get("id"):
                k = session.get(PersonelKariyerKarari, int(veri["id"]))
                if k is None:
                    raise ValueError("Kariyer kararı bulunamadı.")
                if k.onayli and not veri.get("zorla"):
                    raise ValueError("Onaylı kariyer kararı sessizce değiştirilemez.")
            else:
                k = PersonelKariyerKarari(personel_id=int(veri["personel_id"]))
                session.add(k)
            k.personel_id = int(veri["personel_id"])
            k.yol = (veri.get("yol") or k.yol or "UZMANLIK").upper()
            k.kademe = (veri.get("kademe") or k.kademe or KADEME_OGRENEN).upper()
            k.unvan = veri.get("unvan") if "unvan" in veri else k.unvan
            k.gorev = veri.get("gorev") if "gorev" in veri else k.gorev
            k.ucret_bandi = veri.get("ucret_bandi") if "ucret_bandi" in veri else k.ucret_bandi
            if veri.get("gecerlilik") or not getattr(k, "gecerlilik", None):
                k.gecerlilik = _tarih(veri.get("gecerlilik")) or date.today()
            k.karar_veren = _kullanici()
            k.eksik_kosullar = (
                veri.get("eksik_kosullar") if "eksik_kosullar" in veri else k.eksik_kosullar
            )
            if "onayli" in veri:
                k.onayli = bool(veri.get("onayli"))
            k.ortaklik_degil = True
            k.aciklama = veri.get("aciklama") if "aciklama" in veri else k.aciklama
            session.flush()
            return {
                "id": k.id,
                "personel_id": k.personel_id,
                "kademe": k.kademe,
                "yol": k.yol,
                "unvan": k.unvan,
                "gorev": k.gorev,
                "ucret_bandi": k.ucret_bandi,
                "gecerlilik": k.gecerlilik.isoformat() if k.gecerlilik else None,
                "onayli": k.onayli,
                "ortaklik_degil": True,
            }

    @staticmethod
    def kariyer_listele(personel_id: int | None = None) -> list[dict]:
        yetki_zorunlu(*OKU)
        schema_hazirla()
        with get_session() as session:
            q = select(PersonelKariyerKarari).order_by(
                PersonelKariyerKarari.gecerlilik.desc(), PersonelKariyerKarari.id.desc()
            )
            if personel_id is not None:
                q = q.where(PersonelKariyerKarari.personel_id == int(personel_id))
            return [
                {
                    "id": k.id,
                    "personel_id": k.personel_id,
                    "yol": k.yol,
                    "kademe": k.kademe,
                    "unvan": k.unvan,
                    "gorev": k.gorev,
                    "ucret_bandi": k.ucret_bandi,
                    "gecerlilik": k.gecerlilik.isoformat() if k.gecerlilik else None,
                    "karar_veren": k.karar_veren,
                    "eksik_kosullar": k.eksik_kosullar,
                    "onayli": k.onayli,
                    "ortaklik_degil": k.ortaklik_degil,
                    "aciklama": k.aciklama,
                }
                for k in session.scalars(q.limit(200)).all()
            ]

    @staticmethod
    def kariyer_onayla(karar_id: int) -> dict:
        yazma_zorunlu(*YAZ)
        schema_hazirla()
        with get_session() as session:
            k = session.get(PersonelKariyerKarari, int(karar_id))
            if k is None:
                raise ValueError("Kariyer kararı bulunamadı.")
            k.onayli = True
            k.karar_veren = _kullanici()
            k.ortaklik_degil = True
            session.flush()
            return {"id": k.id, "onayli": True, "kademe": k.kademe, "ortaklik_degil": True}

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
    def _hakedis_prim_yaz(
        session,
        *,
        personel_id: int,
        yil: int,
        ay: int,
        tutar: Decimal,
        kaynak: str,
        aciklama: str,
        mevcut_hakedis_id: int | None = None,
    ) -> dict:
        """Tek dönem+personel için ek ödeme hakedişi; aynı kaynak ikinci borç açmaz."""
        tutar = _para(tutar)
        if mevcut_hakedis_id:
            h = session.get(PersonelHakedis, int(mevcut_hakedis_id))
            if h is not None and h.durum != HAKEDIS_IPTAL:
                h.ek_odeme = tutar
                h.net_hakedis = (
                    _para(h.temel_ucret) + tutar + _para(h.fazla_mesai) - _para(h.kesinti)
                )
                h.bordro_kaynagi = kaynak
                session.flush()
                return {
                    "hakedis_id": h.id,
                    "bordro_baglanti_id": kaynak,
                    "tutar": float(tutar),
                    "mevcut": True,
                }
        eski = session.scalar(
            select(PersonelHakedis).where(
                PersonelHakedis.bordro_kaynagi == kaynak,
                PersonelHakedis.durum != HAKEDIS_IPTAL,
            )
        )
        if eski is not None:
            eski.ek_odeme = tutar
            eski.net_hakedis = (
                _para(eski.temel_ucret) + tutar + _para(eski.fazla_mesai) - _para(eski.kesinti)
            )
            session.flush()
            return {
                "hakedis_id": eski.id,
                "bordro_baglanti_id": kaynak,
                "tutar": float(tutar),
                "mevcut": True,
            }
        calisma = session.scalar(
            select(PersonelCalismaDonemi).where(
                PersonelCalismaDonemi.personel_id == int(personel_id),
                PersonelCalismaDonemi.aktif.is_(True),
            )
        )
        if calisma is None:
            raise ValueError(f"Personel {personel_id} için aktif çalışma dönemi yok.")
        h = PersonelHakedis(
            personel_id=int(personel_id),
            donem_id=int(calisma.id),
            yil=int(yil),
            ay=int(ay),
            kayit_turu="PRIM",
            temel_ucret=Decimal("0"),
            ek_odeme=tutar,
            fazla_mesai=Decimal("0"),
            kesinti=Decimal("0"),
            net_hakedis=tutar,
            bordro_kaynagi=kaynak,
            aciklama=aciklama,
            durum=HAKEDIS_TASLAK,
            olusturan=_kullanici(),
        )
        session.add(h)
        session.flush()
        return {
            "hakedis_id": h.id,
            "bordro_baglanti_id": kaynak,
            "tutar": float(tutar),
            "mevcut": False,
        }

    @staticmethod
    def bordroya_aktar(donem_id: int, *, yil: int | None = None, ay: int | None = None) -> dict:
        """Onaylı tarih aralıklı dönem paylarını PersonelHakedis.ek_odeme'ye bağlar (idempotent)."""
        yazma_zorunlu("personel_prim_onay", "personel_finans_duzenleme")
        schema_hazirla()
        with get_session() as session:
            d = session.get(PersonelPrimDonemi, int(donem_id))
            if d is None:
                raise ValueError("Dönem bulunamadı.")
            if d.durum not in (PRIM_ONAYLI, PRIM_BORDRO):
                raise ValueError("Bordro aktarımı için onaylı dönem gerekir.")
            yil = int(yil or d.bitis.year)
            ay = int(ay or d.bitis.month)
            baglilar = []
            for p in session.scalars(
                select(PersonelPrimPayDetay).where(PersonelPrimPayDetay.donem_id == d.id)
            ).all():
                kaynak = p.bordro_baglanti_id or f"{BORDRO_KAYNAK_ON_EK}:{d.id}:{p.personel_id}"
                r = PersonelPerformansService._hakedis_prim_yaz(
                    session,
                    personel_id=p.personel_id,
                    yil=yil,
                    ay=ay,
                    tutar=Decimal(p.toplam),
                    kaynak=kaynak,
                    aciklama=f"Prim dönemi {d.baslangic}–{d.bitis}",
                    mevcut_hakedis_id=p.hakedis_id,
                )
                p.hakedis_id = r["hakedis_id"]
                p.bordro_baglanti_id = r["bordro_baglanti_id"]
                baglilar.append(r)
            d.durum = PRIM_BORDRO
            session.flush()
            return {
                "baglandi": True,
                "donem_id": d.id,
                "durum": d.durum,
                "kayitlar": baglilar,
                "yeniden": all(x.get("mevcut") for x in baglilar) if baglilar else True,
            }

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
        olcut_surum: str | None = None,
        aciklama: str | None = None,
    ) -> dict:
        yazma_zorunlu(*PRIM_YAZ)
        schema_hazirla()
        yil, ay = int(yil), int(ay)
        if ay < 1 or ay > 12:
            raise ValueError("Ay 1–12 olmalı.")
        pol = politika_json or VARSAYILAN_POLITIKA_JSON
        PersonelPerformansService.politika_agirliklari(pol)  # doğrula
        surum = (olcut_surum or VARSAYILAN_OLCUT_SURUM).strip()
        with get_session() as session:
            mevcut = session.scalar(
                select(PersonelPrimDonem).where(
                    PersonelPrimDonem.yil == yil, PersonelPrimDonem.ay == ay
                )
            )
            if mevcut is not None:
                # Kapalı dönemde politika/ölçüt sessizce değişmez — mevcut kaydı döndür
                return {
                    "id": mevcut.id,
                    "yil": mevcut.yil,
                    "ay": mevcut.ay,
                    "durum": mevcut.durum,
                    "havuz": float(mevcut.havuz),
                    "politika_json": mevcut.politika_json,
                    "olcut_surum": mevcut.olcut_surum,
                    "mevcut": True,
                }
            d = PersonelPrimDonem(
                yil=yil,
                ay=ay,
                durum=PRIM_TASLAK,
                havuz=_para(havuz),
                politika_json=pol,
                olcut_surum=surum,
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
                "olcut_surum": d.olcut_surum,
                "mevcut": False,
            }

    @staticmethod
    def _ay_araligi(yil: int, ay: int) -> tuple[date, date]:
        bas = date(int(yil), int(ay), 1)
        if ay == 12:
            bit = date(int(yil) + 1, 1, 1) - timedelta(days=1)
        else:
            bit = date(int(yil), int(ay) + 1, 1) - timedelta(days=1)
        return bas, bit

    @staticmethod
    def _hizmet_yili(giris: date | None, referans: date) -> int:
        if giris is None:
            return 0
        yil = referans.year - giris.year
        if (referans.month, referans.day) < (giris.month, giris.day):
            yil -= 1
        return max(0, yil)

    @staticmethod
    def satis_fatura_h_satirlari(
        bas: date,
        bit: date,
        *,
        h_once_map: dict[int, Decimal] | None = None,
        session=None,
    ) -> list[dict]:
        """Onaylı satış faturalarından S/C/F/T → H satırları (iptal/silinen hariç).

        S = tl_matrah (KDV hariç net), C = Σ fifo_birim_maliyeti×miktar,
        F = KDV dahil borç (genel + fon), T = kesinleşmiş tahsilat toplamı.
        """
        from database.models.satis_faturasi import (
            SatisFaturasi,
            SatisFaturasiSatiri,
            SatisFaturasiTahsilati,
        )

        h_once_map = h_once_map or {}

        def _calis(sess) -> list[dict]:
            faturalar = list(
                sess.scalars(
                    select(SatisFaturasi).where(
                        SatisFaturasi.fatura_tarihi >= bas,
                        SatisFaturasi.fatura_tarihi <= bit,
                        SatisFaturasi.onaylandi.is_(True),
                        or_(
                            SatisFaturasi.is_deleted.is_(False),
                            SatisFaturasi.is_deleted.is_(None),
                        ),
                        SatisFaturasi.durum != "İPTAL",
                    )
                ).all()
            )
            satirlar: list[dict] = []
            for f in faturalar:
                satir_list = list(
                    sess.scalars(
                        select(SatisFaturasiSatiri).where(
                            SatisFaturasiSatiri.fatura_id == f.id
                        )
                    ).all()
                )
                C = sum(
                    (
                        Decimal(str(s.fifo_birim_maliyeti or 0))
                        * Decimal(str(s.miktar or 0))
                        for s in satir_list
                    ),
                    Decimal("0"),
                )
                eksik_maliyet = bool(satir_list) and all(
                    Decimal(str(s.fifo_birim_maliyeti or 0)) == 0 for s in satir_list
                )
                S = Decimal(str(f.tl_matrah or 0))
                F = (
                    Decimal(str(f.tl_genel_toplam or 0))
                    + Decimal(str(f.fon_ek_bedel_tutari or 0))
                    + Decimal(str(f.fon_ek_bedel_kdv or 0))
                )
                tahsil_sat = list(
                    sess.scalars(
                        select(SatisFaturasiTahsilati).where(
                            SatisFaturasiTahsilati.fatura_id == f.id,
                            SatisFaturasiTahsilati.tahsilat_tarihi <= bit,
                        )
                    ).all()
                )
                if tahsil_sat:
                    T = sum(
                        (Decimal(str(t.tutar or 0)) for t in tahsil_sat), Decimal("0")
                    )
                else:
                    T = Decimal(str(f.tahsilat_tutari or 0))
                # Çek/senet/avans sözü sayılmaz: yalnız nakit/banka/POS benzeri şekiller
                # (şekil boşsa mevcut tutar kabul; bilinmeyen şekiller T'ye dahil)
                h = tahsil_kar_katkisi(S=S, C=C, F=F, T=T)
                h_once = _para(h_once_map.get(int(f.id), 0))
                satirlar.append(
                    {
                        "fatura_id": int(f.id),
                        "fatura_no": f.fatura_no,
                        "S": h["S"],
                        "C": h["C"],
                        "M": h["M"],
                        "F": h["F"],
                        "T": h["T"],
                        "q": h["q"],
                        "H": h["H"],
                        "H_once": h_once,
                        "H_fark": h["H"] - h_once,
                        "eksik_maliyet": eksik_maliyet,
                        "eksik_tahsilat": False,
                    }
                )
            return satirlar

        if session is not None:
            return _calis(session)
        with get_session() as sess:
            return _calis(sess)

    @staticmethod
    def _onceki_h_donuk(session, fatura_idler: list[int], yil: int, ay: int) -> dict[int, Decimal]:
        """Önceki aylık dönemlerde dondurulmuş son H (fatura bazında)."""
        if not fatura_idler:
            return {}
        onceki_donemler = list(
            session.scalars(
                select(PersonelPrimDonem)
                .where(
                    or_(
                        PersonelPrimDonem.yil < int(yil),
                        and_(
                            PersonelPrimDonem.yil == int(yil),
                            PersonelPrimDonem.ay < int(ay),
                        ),
                    )
                )
                .order_by(PersonelPrimDonem.yil.desc(), PersonelPrimDonem.ay.desc())
            ).all()
        )
        sonuc: dict[int, Decimal] = {}
        kalan = set(int(x) for x in fatura_idler)
        for od in onceki_donemler:
            if not kalan:
                break
            for row in session.scalars(
                select(PersonelFaturaHDonuk).where(
                    PersonelFaturaHDonuk.aylik_donem_id == od.id,
                    PersonelFaturaHDonuk.fatura_id.in_(list(kalan)),
                )
            ).all():
                if row.fatura_id in kalan:
                    sonuc[int(row.fatura_id)] = _para(row.H)
                    kalan.discard(int(row.fatura_id))
        return sonuc

    @staticmethod
    def _aylik_h_donuk_yaz(session, donem: PersonelPrimDonem, satirlar: list[dict]) -> None:
        """Dönem fatura H görüntüsünü dondur (yeniden hesapta üzerine yaz — idempotent).

        Eski şemada donem_id NOT NULL olabileceğinden, aynı ay için gölge
        PersonelPrimDonemi (simülasyon) bağlanır; asıl anahtar aylik_donem_id'dir.
        """
        donem_id = int(donem.id)
        for eski in session.scalars(
            select(PersonelFaturaHDonuk).where(
                PersonelFaturaHDonuk.aylik_donem_id == donem_id
            )
        ).all():
            session.delete(eski)
        session.flush()
        if not satirlar:
            return
        bas, bit = PersonelPerformansService._ay_araligi(donem.yil, donem.ay)
        golge = session.scalar(
            select(PersonelPrimDonemi).where(
                PersonelPrimDonemi.baslangic == bas,
                PersonelPrimDonemi.bitis == bit,
                PersonelPrimDonemi.simulasyon.is_(True),
            )
        )
        if golge is None:
            golge = PersonelPrimDonemi(
                baslangic=bas,
                bitis=bit,
                durum=PRIM_TASLAK,
                simulasyon=True,
                hesaplayan=_kullanici(),
                aciklama=f"Aylık H dondurma gölgesi {donem.yil}-{donem.ay:02d}",
            )
            session.add(golge)
            session.flush()
        for fs in satirlar:
            session.add(
                PersonelFaturaHDonuk(
                    donem_id=int(golge.id),
                    aylik_donem_id=donem_id,
                    fatura_id=int(fs["fatura_id"]),
                    fatura_no=fs.get("fatura_no"),
                    S=_para(fs["S"]),
                    C=_para(fs["C"]),
                    M=_para(fs["M"]),
                    F=_para(fs["F"]),
                    T=_para(fs["T"]),
                    q=_para(fs["q"]),
                    H=_para(fs["H"]),
                    H_once=_para(fs.get("H_once") or 0),
                    H_fark=_para(fs.get("H_fark") or 0),
                    eksik_maliyet=bool(fs.get("eksik_maliyet")),
                    eksik_tahsilat=bool(fs.get("eksik_tahsilat")),
                )
            )

    @staticmethod
    def prim_kisiler_olcumden(
        session,
        *,
        yil: int,
        ay: int,
        bitis: date,
    ) -> list[dict]:
        """Katkı puanı + hizmet yılı (ölçüm verisi). Stub performans=100 yok."""
        bas, bit = PersonelPerformansService._ay_araligi(yil, ay)
        katkilar = session.scalars(
            select(PersonelKatki).where(
                PersonelKatki.tarih >= bas, PersonelKatki.tarih <= bit
            )
        ).all()
        puan_map: dict[int, Decimal] = {}
        for k in katkilar:
            puan_map[k.personel_id] = puan_map.get(k.personel_id, Decimal("0")) + Decimal(
                str(k.puan)
            )
        # Dönem değerlendirmesi varsa katkı puanına tercih et (0–100)
        for pid in list(puan_map.keys()):
            deg = session.scalar(
                select(PersonelDegerlendirme).where(
                    PersonelDegerlendirme.personel_id == pid,
                    PersonelDegerlendirme.yil == int(yil),
                    PersonelDegerlendirme.ay == int(ay),
                )
            )
            if deg is not None and deg.toplam_puan is not None:
                puan_map[pid] = min(
                    Decimal("100"), max(Decimal("0"), _para(deg.toplam_puan))
                )
            else:
                puan_map[pid] = min(
                    Decimal("100"), max(Decimal("0"), puan_map[pid])
                )

        kisiler = []
        for pid, puan in sorted(puan_map.items()):
            calisma = session.scalar(
                select(PersonelCalismaDonemi).where(
                    PersonelCalismaDonemi.personel_id == int(pid),
                    PersonelCalismaDonemi.aktif.is_(True),
                )
            )
            hy = PersonelPerformansService._hizmet_yili(
                calisma.giris_tarihi if calisma else None, bitis
            )
            kisiler.append(
                {
                    "personel_id": pid,
                    "hizmet_yili": hy,
                    "performans": float(puan),
                    "katilim": 1,
                }
            )
        return kisiler

    @staticmethod
    def prim_hesapla(
        donem_id: int,
        *,
        kisiler: list[dict] | None = None,
        havuz=None,
        uygun_gider=None,
        onceki_zarar=None,
        guvence=None,
        prim_orani=None,
        satis_verisinden: bool = True,
    ) -> dict:
        """Satış/ölçüm verisinden havuz + 50/30/20 dağıtım. Yeniden çalıştırma pay çoğaltmaz.

        havuz verilmezse (veya satis_verisinden=True ve havuz None): onaylı faturalardan
        tahsil edilmiş kâr katkısı (H farkı) → havuz_hesapla → prim bütçesi kullanılır.
        Sabit stub tutar yazılmaz.
        """
        yazma_zorunlu(*PRIM_YAZ)
        schema_hazirla()
        with get_session() as session:
            d = session.get(PersonelPrimDonem, int(donem_id))
            if d is None:
                raise ValueError("Prim dönemi bulunamadı.")
            if d.durum in PRIM_KAPALI_DURUMLAR:
                raise ValueError("Kapalı dönem sessizce yeniden hesaplanamaz.")
            agirlik = PersonelPerformansService.politika_agirliklari(d.politika_json)
            bas, bit = PersonelPerformansService._ay_araligi(d.yil, d.ay)
            kaynak_ozet: dict[str, Any] = {"kaynak": "manuel_havuz"}
            eksik_veri = False

            if havuz is not None and not satis_verisinden:
                d.havuz = _para(havuz)
                kaynak_ozet = {"kaynak": "manuel_havuz", "havuz": float(d.havuz)}
            else:
                # Gerçek satış faturalarından H farkı
                once_probe = PersonelPerformansService.satis_fatura_h_satirlari(
                    bas, bit, session=session
                )
                h_once = PersonelPerformansService._onceki_h_donuk(
                    session, [s["fatura_id"] for s in once_probe], d.yil, d.ay
                )
                fatura_satirlari = PersonelPerformansService.satis_fatura_h_satirlari(
                    bas, bit, h_once_map=h_once, session=session
                )
                tahsil_kar = sum(
                    (_para(s["H_fark"]) for s in fatura_satirlari), Decimal("0")
                )
                if any(s.get("eksik_maliyet") or s.get("eksik_tahsilat") for s in fatura_satirlari):
                    eksik_veri = True
                # Politika: aktif prim politikası veya parametre
                pol = session.scalar(
                    select(PersonelPrimPolitika)
                    .where(PersonelPrimPolitika.aktif.is_(True))
                    .order_by(PersonelPrimPolitika.gecerli_baslangic.desc())
                )
                ug = _para(
                    uygun_gider
                    if uygun_gider is not None
                    else (0 if pol is None else 0)
                )
                oz = _para(onceki_zarar if onceki_zarar is not None else 0)
                guv = _para(
                    guvence
                    if guvence is not None
                    else (pol.guvence_tutari if pol else 0)
                )
                oran = _para(
                    prim_orani
                    if prim_orani is not None
                    else (pol.prim_orani if pol else Decimal("0.10"))
                )
                # Manuel havuz override: yalnız açıkça verilirse (satış tabanı üzerine değil)
                if havuz is not None:
                    d.havuz = _para(havuz)
                    kaynak_ozet = {
                        "kaynak": "manuel_override",
                        "tahsil_kar_fark": float(tahsil_kar),
                        "fatura_sayisi": len(fatura_satirlari),
                        "havuz": float(d.havuz),
                    }
                else:
                    hv = havuz_hesapla(
                        tahsil_kar_katkisi_toplam=tahsil_kar,
                        uygun_giderler=ug,
                        onceki_zarar_devri=oz,
                        guvence_tutari=guv,
                        prim_orani=oran,
                    )
                    d.havuz = hv["prim_butcesi"]
                    kaynak_ozet = {
                        "kaynak": "satis_fatura",
                        "tahsil_kar_fark": float(tahsil_kar),
                        "uygun_gider": float(ug),
                        "guvence": float(guv),
                        "prim_orani": float(oran),
                        "G": float(hv["G"]),
                        "B": float(hv["B"]),
                        "prim_butcesi": float(hv["prim_butcesi"]),
                        "fatura_sayisi": len(fatura_satirlari),
                        "eksik_veri": eksik_veri,
                    }
                PersonelPerformansService._aylik_h_donuk_yaz(session, d, fatura_satirlari)

            # Katkı / ölçümden kişi listesi (verilmediyse); stub performans yok
            if kisiler is None:
                kisiler = PersonelPerformansService.prim_kisiler_olcumden(
                    session, yil=d.yil, ay=d.ay, bitis=bit
                )

            dagitim_kisiler = [
                DagitimKisi(
                    personel_id=int(k["personel_id"]),
                    hizmet_yili=int(k.get("hizmet_yili") or 0),
                    performans=_para(
                        k.get("performans") if k.get("performans") is not None else 0
                    ),
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

            # Idempotent: mevcut payları sil, yeniden yaz (bordro bağlıysa engelle)
            for eski in session.scalars(
                select(PersonelPrimPay).where(PersonelPrimPay.donem_id == d.id)
            ).all():
                if eski.hakedis_id or eski.bordro_baglanti_id:
                    raise ValueError(
                        "Bordroya bağlı pay varken yeniden hesap yapılamaz; önce iptal edin."
                    )
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
            if eksik_veri or not dagitim_kisiler:
                d.durum = PRIM_EKSIK
            else:
                d.durum = PRIM_HESAPLANDI
            d.hesaplayan = _kullanici()
            d.hesap_zamani = datetime.now()
            if not d.olcut_surum:
                d.olcut_surum = VARSAYILAN_OLCUT_SURUM
            # Kaynak özeti aciklama alanında (kısa)
            ozet = (
                f"kaynak={kaynak_ozet.get('kaynak')} "
                f"fat={kaynak_ozet.get('fatura_sayisi', '—')} "
                f"H_fark={kaynak_ozet.get('tahsil_kar_fark', '—')}"
            )
            d.aciklama = ((d.aciklama or "").split("|kaynak=")[0].strip() + f" |{ozet}").strip(" |")
            session.flush()
            return {
                "donem_id": d.id,
                "yil": d.yil,
                "ay": d.ay,
                "durum": d.durum,
                "havuz": float(d.havuz),
                "politika_json": d.politika_json,
                "olcut_surum": d.olcut_surum,
                "dagitilan": float(dag["dagitilan"]),
                "dagitilmamis": float(dag["dagitilmamis"]),
                "paylar": pay_satirlari,
                "kaynak": kaynak_ozet,
                "eksik_veri": eksik_veri,
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
                    "hakedis_id": p.hakedis_id,
                    "bordro_baglanti_id": p.bordro_baglanti_id,
                    "odenen": float(p.odenen or 0),
                }
                for p in session.scalars(
                    select(PersonelPrimPay)
                    .where(PersonelPrimPay.donem_id == int(donem_id))
                    .order_by(PersonelPrimPay.personel_id)
                ).all()
            ]

    @staticmethod
    def prim_durum_gecis(donem_id: int, yeni_durum: str, *, gerekce: str | None = None) -> dict:
        """Taslak → Veriler eksik → Hesaplandı → İncelemede → Onaylandı → Bordroya aktarıldı → Ödendi."""
        yeni = (yeni_durum or "").strip().upper()
        if yeni in (PRIM_ONAYLI, PRIM_BORDRO, PRIM_ODENDI):
            yazma_zorunlu("personel_prim_onay", "personel_finans_duzenleme")
        else:
            yazma_zorunlu(*PRIM_YAZ)
        schema_hazirla()
        if yeni not in dict(PRIM_DURUMLARI):
            raise ValueError(f"Geçersiz dönem durumu: {yeni}")
        with get_session() as session:
            d = session.get(PersonelPrimDonem, int(donem_id))
            if d is None:
                raise ValueError("Prim dönemi bulunamadı.")
            izinli = PRIM_GECISLER.get(d.durum, frozenset())
            if yeni not in izinli:
                raise ValueError(f"Geçiş yok: {d.durum} → {yeni}")
            d.durum = yeni
            if gerekce:
                d.aciklama = ((d.aciklama or "") + f" | {gerekce}").strip(" |")
            session.flush()
            return {"id": d.id, "durum": d.durum}

    @staticmethod
    def prim_incelemeye_al(donem_id: int) -> dict:
        return PersonelPerformansService.prim_durum_gecis(donem_id, PRIM_INCELEME)

    @staticmethod
    def prim_onayla(donem_id: int, *, bordroya_aktar: bool = True) -> dict:
        """Hesaplandı/İncelemede → Onaylandı; varsayılan olarak ek ödemeye aktarır."""
        yazma_zorunlu("personel_prim_onay", "personel_finans_duzenleme")
        schema_hazirla()
        with get_session() as session:
            d = session.get(PersonelPrimDonem, int(donem_id))
            if d is None:
                raise ValueError("Prim dönemi bulunamadı.")
            if d.durum not in (PRIM_HESAPLANDI, PRIM_INCELEME):
                raise ValueError("Yalnız hesaplanmış / incelemedeki dönem onaylanır.")
            d.durum = PRIM_ONAYLI
            d.onaylayan = _kullanici()
            d.onay_zamani = datetime.now()
            session.flush()
            sonuc = {"id": d.id, "durum": d.durum, "onaylayan": d.onaylayan}
        if bordroya_aktar:
            bag = PersonelPerformansService.prim_bordroya_bagla(donem_id)
            sonuc["bordro"] = bag
            sonuc["durum"] = bag.get("durum", sonuc["durum"])
        return sonuc

    @staticmethod
    def _prim_bordro_kaynak(donem_id: int, personel_id: int) -> str:
        return f"{BORDRO_KAYNAK_ON_EK}:{int(donem_id)}:{int(personel_id)}"

    @staticmethod
    def prim_bordroya_bagla(donem_id: int) -> dict:
        """Onaylı prim paylarını PersonelHakedis.ek_odeme'ye bağlar (idempotent).

        Aynı dönem+personel için ikinci çağrı yeni borç/ödeme üretmez.
        Resmî vergi/SGK motoru kurulmaz; net hakediş takibine ek ödeme yazar.
        """
        yazma_zorunlu("personel_prim_onay", "personel_finans_duzenleme")
        schema_hazirla()

        with get_session() as session:
            d = session.get(PersonelPrimDonem, int(donem_id))
            if d is None:
                raise ValueError("Prim dönemi bulunamadı.")
            if d.durum == PRIM_BORDRO:
                baglar = [
                    {
                        "personel_id": p.personel_id,
                        "hakedis_id": p.hakedis_id,
                        "bordro_baglanti_id": p.bordro_baglanti_id,
                        "tutar": float(p.tutar),
                    }
                    for p in session.scalars(
                        select(PersonelPrimPay).where(PersonelPrimPay.donem_id == d.id)
                    ).all()
                ]
                return {
                    "baglandi": True,
                    "donem_id": d.id,
                    "durum": d.durum,
                    "tekrar": True,
                    "baglantilar": baglar,
                    "hakedis_sayisi": len(
                        {b["hakedis_id"] for b in baglar if b.get("hakedis_id")}
                    ),
                }
            if d.durum not in (PRIM_ONAYLI, PRIM_MVP_ONAYLANDI):
                raise ValueError("Bordro bağlantısı için onaylı dönem gerekir.")
            paylar = list(
                session.scalars(
                    select(PersonelPrimPay).where(PersonelPrimPay.donem_id == d.id)
                ).all()
            )
            if not paylar:
                raise ValueError("Aktarılacak prim payı yok.")

            yil, ay = int(d.yil), int(d.ay)
            baglantilar = []
            for p in paylar:
                kaynak = PersonelPerformansService._prim_bordro_kaynak(d.id, p.personel_id)
                if p.hakedis_id and p.bordro_baglanti_id == kaynak:
                    baglantilar.append(
                        {
                            "personel_id": p.personel_id,
                            "hakedis_id": p.hakedis_id,
                            "bordro_baglanti_id": p.bordro_baglanti_id,
                            "tutar": float(p.tutar),
                            "mevcut": True,
                        }
                    )
                    continue
                # Aktif veya iptal edilmiş aynı kaynak/unique anahtar → yeniden kullan (çift borç yok)
                eski = session.scalar(
                    select(PersonelHakedis).where(PersonelHakedis.bordro_kaynagi == kaynak)
                )
                calisma = session.scalar(
                    select(PersonelCalismaDonemi).where(
                        PersonelCalismaDonemi.personel_id == int(p.personel_id),
                        PersonelCalismaDonemi.aktif.is_(True),
                    )
                )
                if calisma is None:
                    raise ValueError(
                        f"Personel {p.personel_id} için aktif çalışma dönemi yok."
                    )
                if eski is None:
                    eski = session.scalar(
                        select(PersonelHakedis).where(
                            PersonelHakedis.personel_id == int(p.personel_id),
                            PersonelHakedis.donem_id == int(calisma.id),
                            PersonelHakedis.yil == yil,
                            PersonelHakedis.ay == ay,
                            PersonelHakedis.kayit_turu == "PRIM",
                        )
                    )
                if eski is not None:
                    eski.ek_odeme = _para(p.tutar)
                    eski.net_hakedis = _para(p.tutar)
                    eski.bordro_kaynagi = kaynak
                    eski.durum = HAKEDIS_TASLAK
                    eski.aciklama = f"Prim dönemi {yil}-{ay:02d} ek ödeme"
                    session.flush()
                    p.hakedis_id = eski.id
                    p.bordro_baglanti_id = kaynak
                    baglantilar.append(
                        {
                            "personel_id": p.personel_id,
                            "hakedis_id": eski.id,
                            "bordro_baglanti_id": kaynak,
                            "tutar": float(p.tutar),
                            "mevcut": True,
                        }
                    )
                    continue

                h = PersonelHakedis(
                    personel_id=int(p.personel_id),
                    donem_id=int(calisma.id),
                    yil=yil,
                    ay=ay,
                    kayit_turu="PRIM",
                    temel_ucret=Decimal("0"),
                    ek_odeme=_para(p.tutar),
                    fazla_mesai=Decimal("0"),
                    kesinti=Decimal("0"),
                    net_hakedis=_para(p.tutar),
                    bordro_kaynagi=kaynak,
                    aciklama=f"Prim dönemi {yil}-{ay:02d} ek ödeme",
                    durum=HAKEDIS_TASLAK,
                    olusturan=_kullanici(),
                )
                session.add(h)
                session.flush()
                p.hakedis_id = int(h.id)
                p.bordro_baglanti_id = kaynak
                baglantilar.append(
                    {
                        "personel_id": p.personel_id,
                        "hakedis_id": h.id,
                        "bordro_baglanti_id": kaynak,
                        "tutar": float(p.tutar),
                        "mevcut": False,
                    }
                )

            d.durum = PRIM_BORDRO
            session.flush()
            return {
                "baglandi": True,
                "donem_id": d.id,
                "durum": d.durum,
                "tekrar": False,
                "baglantilar": baglantilar,
                "hakedis_sayisi": len({b["hakedis_id"] for b in baglantilar}),
            }

    @staticmethod
    def prim_bordro_iptal(donem_id: int) -> dict:
        """Bordroya aktarılmış ama ödenmemiş prim bağlantısını geri alır (çift borç yok)."""
        yazma_zorunlu("personel_prim_onay", "personel_finans_duzenleme")
        schema_hazirla()
        with get_session() as session:
            d = session.get(PersonelPrimDonem, int(donem_id))
            if d is None:
                raise ValueError("Prim dönemi bulunamadı.")
            if d.durum == PRIM_ODENDI:
                raise ValueError("Ödenmiş prim sessizce iptal edilemez.")
            if d.durum not in (PRIM_BORDRO, PRIM_ONAYLI):
                raise ValueError("İptal yalnız onaylı / bordroya aktarılmış dönemde.")
            iptal_say = 0
            for p in session.scalars(
                select(PersonelPrimPay).where(PersonelPrimPay.donem_id == d.id)
            ).all():
                if not p.hakedis_id:
                    continue
                h = session.get(PersonelHakedis, int(p.hakedis_id))
                if h is None:
                    p.hakedis_id = None
                    p.bordro_baglanti_id = None
                    continue
                # Ödeme hareketi varsa iptali engelle
                odeme = session.scalar(
                    select(PersonelHesapHareketi).where(
                        PersonelHesapHareketi.hakedis_id == h.id,
                        PersonelHesapHareketi.hareket_turu == HAREKET_MAAS_ODEME,
                        PersonelHesapHareketi.iptal.is_(False),
                    )
                )
                if odeme is not None:
                    raise ValueError(
                        f"Personel {p.personel_id}: ödeme kaydı varken prim iptal edilemez."
                    )
                if h.durum != HAKEDIS_IPTAL:
                    h.durum = HAKEDIS_IPTAL
                    iptal_say += 1
                p.hakedis_id = None
                p.bordro_baglanti_id = None
                p.odenen = Decimal("0")
            d.durum = PRIM_HESAPLANDI
            d.iptal_eden = _kullanici()
            d.iptal_zamani = datetime.now()
            d.onaylayan = None
            d.onay_zamani = None
            session.flush()
            return {
                "donem_id": d.id,
                "durum": d.durum,
                "iptal_edilen_hakedis": iptal_say,
            }

    @staticmethod
    def prim_iptal(donem_id: int) -> dict:
        """Ödenmemiş bordro aktarımını geri alır; dönem Hesaplandı'ya döner."""
        return PersonelPerformansService.prim_bordro_iptal(donem_id)

    @staticmethod
    def prim_donem_cikti(donem_id: int) -> dict:
        """Dönem pay çıktısı için meta + satırlar (Excel/PDF ortak kaynak)."""
        yetki_zorunlu(*PRIM_OKU)
        schema_hazirla()
        with get_session() as session:
            d = session.get(PersonelPrimDonem, int(donem_id))
            if d is None:
                raise ValueError("Prim dönemi bulunamadı.")
            paylar = list(
                session.scalars(
                    select(PersonelPrimPay)
                    .where(PersonelPrimPay.donem_id == d.id)
                    .order_by(PersonelPrimPay.personel_id)
                ).all()
            )
            personel_ad: dict[int, str] = {}
            for p in paylar:
                if p.personel_id in personel_ad:
                    continue
                kart = session.get(Personel, int(p.personel_id))
                if kart is None:
                    personel_ad[p.personel_id] = f"#{p.personel_id}"
                else:
                    personel_ad[p.personel_id] = (
                        f"{kart.kod} — {(kart.ad or '').strip()} {(kart.soyad or '').strip()}".strip()
                    )
            satirlar = [
                {
                    "personel_id": p.personel_id,
                    "personel": personel_ad.get(p.personel_id, f"#{p.personel_id}"),
                    "ekip_pay": float(p.ekip_pay),
                    "katki_pay": float(p.katki_pay),
                    "kidem_pay": float(p.kidem_pay),
                    "tutar": float(p.tutar),
                    "hakedis_id": p.hakedis_id,
                    "bordro_baglanti_id": p.bordro_baglanti_id,
                }
                for p in paylar
            ]
            dagitilan = sum((Decimal(str(s["tutar"])) for s in satirlar), Decimal("0"))
            firma = getattr(oturum, "firma_unvan", None) or getattr(oturum, "firma_kodu", None) or "—"
            return {
                "donem_id": d.id,
                "yil": d.yil,
                "ay": d.ay,
                "durum": d.durum,
                "havuz": float(d.havuz),
                "politika_json": d.politika_json,
                "olcut_surum": d.olcut_surum or VARSAYILAN_OLCUT_SURUM,
                "hesaplayan": d.hesaplayan,
                "onaylayan": d.onaylayan,
                "firma": firma,
                "filtreler": "tüm dönem payları",
                "hesap_surumu": d.olcut_surum or VARSAYILAN_OLCUT_SURUM,
                "satirlar": satirlar,
                "dagitilan": float(dagitilan),
                "dagitilmamis": float(_para(d.havuz) - dagitilan),
            }

    @staticmethod
    def prim_excel_aktar(donem_id: int, yol: str) -> str:
        """Dönem kişi paylarını Excel'e yazar (dönem, firma, politika, ölçüt sürümü)."""
        veri = PersonelPerformansService.prim_donem_cikti(donem_id)
        from openpyxl import Workbook
        from openpyxl.styles import Font

        wb = Workbook()
        ws = wb.active
        ws.title = "Prim Payları"
        ws.append(["Cin Muhasebe — Prim dönem pay çıktısı"])
        ws.append(["Firma", veri["firma"]])
        ws.append(["Dönem", f"{veri['yil']}-{veri['ay']:02d}"])
        ws.append(["Durum", veri["durum"]])
        ws.append(["Havuz", float(veri["havuz"])])
        ws.append(["Politika", veri["politika_json"]])
        ws.append(["Ölçüt / hesap sürümü", veri["olcut_surum"]])
        ws.append(["Filtreler", veri["filtreler"]])
        ws.append([])
        baslik = [
            "Personel",
            "Personel ID",
            "Ekip pay",
            "Katkı pay",
            "Kıdem pay",
            "Tutar",
            "Hakediş ID",
            "Bordro kaynak",
        ]
        ws.append(baslik)
        for cell in ws[ws.max_row]:
            cell.font = Font(bold=True)
        for s in veri["satirlar"]:
            ws.append(
                [
                    s["personel"],
                    s["personel_id"],
                    s["ekip_pay"],
                    s["katki_pay"],
                    s["kidem_pay"],
                    s["tutar"],
                    s.get("hakedis_id") or "",
                    s.get("bordro_baglanti_id") or "",
                ]
            )
        ws.append([])
        ws.append(["Dağıtılan", veri["dagitilan"]])
        ws.append(["Dağılmamış", veri["dagitilmamis"]])
        wb.save(yol)
        return yol

    @staticmethod
    def prim_pdf_aktar(donem_id: int, yol: str) -> str:
        """Dönem kişi paylarını PDF'e yazar; reportlab yoksa düz metin yazar."""
        veri = PersonelPerformansService.prim_donem_cikti(donem_id)
        baslik_satir = (
            f"Firma: {veri['firma']} | Dönem: {veri['yil']}-{veri['ay']:02d} | "
            f"Durum: {veri['durum']} | Ölçüt: {veri['olcut_surum']} | "
            f"Politika: {veri['politika_json']}"
        )
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        except ImportError as exc:
            # .pdf uzantısına düz metin yazma — gerçek PDF veya açık hata
            raise RuntimeError(
                "PDF çıktısı için reportlab gerekli. "
                "Excel aktarımını kullanın veya reportlab kurun."
            ) from exc

        doc = SimpleDocTemplate(
            yol,
            pagesize=landscape(A4),
            leftMargin=18,
            rightMargin=18,
            topMargin=24,
            bottomMargin=24,
        )
        styles = getSampleStyleSheet()
        story = [
            Paragraph("Cin Muhasebe — Prim dönem pay çıktısı", styles["Title"]),
            Paragraph(baslik_satir, styles["Normal"]),
            Paragraph(
                f"Havuz: {veri['havuz']:,.2f} | Filtreler: {veri['filtreler']}",
                styles["Normal"],
            ),
            Spacer(1, 8),
        ]
        data = [["Personel", "Ekip", "Katkı", "Kıdem", "Tutar"]]
        for s in veri["satirlar"]:
            data.append(
                [
                    s["personel"],
                    f"{s['ekip_pay']:,.2f}",
                    f"{s['katki_pay']:,.2f}",
                    f"{s['kidem_pay']:,.2f}",
                    f"{s['tutar']:,.2f}",
                ]
            )
        data.append(["Toplam / dağılmamış", "", "", "", f"{veri['dagitilan']:,.2f}"])
        tbl = Table(data, repeatRows=1)
        tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B3A5F")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FFF8E7")]),
                ]
            )
        )
        story.append(tbl)
        doc.build(story)
        return yol
