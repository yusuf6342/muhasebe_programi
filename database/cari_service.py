from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import unicodedata
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from database.database import get_session
from database.access import yazma_zorunlu
from database.finans_service import FinansService
from database.models.cari import Cari, CariIslem, SatisHareketi
# SatisFaturasi ilişkileri — önce hedef sınıflar kayda alınmalı
from database.models.satis_siparisi import SatisSiparisi  # noqa: F401
from database.models.satis_irsaliyesi import SatisIrsaliyesi  # noqa: F401
from database.models.satis_faturasi import SatisFaturasi
from database.turkce_normalize import turkce_normalize


class CariService:
    @staticmethod
    def _grup_anahtari(ad: str) -> str:
        """Ad tekilliği anahtarı: Türkçe büyük/küçük harf (İ/I/ı/i), baş-son ve çoklu boşluk duyarsız."""
        normal = unicodedata.normalize("NFKD", turkce_normalize((ad or "").strip()))
        sade = "".join(karakter for karakter in normal if not unicodedata.combining(karakter))
        return " ".join(sade.split())

    @staticmethod
    def gruplari_listele() -> list[str]:
        from database.models.cari import MusteriGrubu

        with get_session() as session:
            return list(session.scalars(select(MusteriGrubu.ad).order_by(MusteriGrubu.ad)).all())

    @staticmethod
    def grup_ekle(ad: str) -> str:
        from database.models.cari import MusteriGrubu

        ad = (ad or "").strip()
        if not ad:
            raise ValueError("Müşteri grup adı boş olamaz.")
        anahtar = CariService._grup_anahtari(ad)
        with get_session() as session:
            mevcut = next(
                (g for g in session.scalars(select(MusteriGrubu)) if CariService._grup_anahtari(g.ad) == anahtar),
                None,
            )
            if mevcut:
                raise ValueError(f"Bu müşteri grubu zaten mevcut: «{mevcut.ad}».")
            session.add(MusteriGrubu(ad=ad))
            session.flush()
            return ad

    ADAY_MUSTERI_GRUP = "ADAY MÜŞTERİ"
    PERAKENDE_MUSTERI_GRUP = "PERAKENDE MÜŞTERİ"

    # Sistem akışlarının grup bağlantısı: rol → (varsayılan ad, açıklama). Grup silinirken hedefe taşınır.
    GRUP_ROLLERI = {
        "ADAY_MUSTERI": (ADAY_MUSTERI_GRUP, "Teklif ekranındaki aday müşteri grubu"),
        "PERAKENDE_MUSTERI": (PERAKENDE_MUSTERI_GRUP, "Hızlı Satış varsayılan perakende müşteri grubu"),
    }

    @staticmethod
    def _rol_tablosu_hazirla(session) -> None:
        from sqlalchemy import inspect as sa_inspect

        from database.models.cari import MusteriGrubuAyari

        if not sa_inspect(session.connection()).has_table(MusteriGrubuAyari.__tablename__):
            MusteriGrubuAyari.__table__.create(session.connection(), checkfirst=True)

    @staticmethod
    def _rol_ayarlari(session) -> dict[str, str]:
        from sqlalchemy import inspect as sa_inspect

        from database.models.cari import MusteriGrubuAyari

        ayarlar = {rol: varsayilan for rol, (varsayilan, _a) in CariService.GRUP_ROLLERI.items()}
        if sa_inspect(session.connection()).has_table(MusteriGrubuAyari.__tablename__):
            for k in session.scalars(select(MusteriGrubuAyari)).all():
                if k.anahtar in ayarlar and (k.deger or "").strip():
                    ayarlar[k.anahtar] = k.deger.strip()
        return ayarlar

    @staticmethod
    def rol_grubu(rol: str, session=None) -> str:
        """Rol için geçerli grup adı (ayar yoksa varsayılan ad)."""
        if session is not None:
            return CariService._rol_ayarlari(session)[rol]
        with get_session() as s:
            return CariService._rol_ayarlari(s)[rol]

    @staticmethod
    def aday_musteri_grubunu_garanti() -> str:
        """Aday müşteri rolündeki grup yoksa oluşturur; varsa mevcut adı döner."""
        from database.models.cari import MusteriGrubu

        with get_session() as session:
            hedef = CariService.rol_grubu("ADAY_MUSTERI", session)
            mevcut = CariService._grup_bul(session, hedef)
            if mevcut:
                return mevcut.ad
            session.add(MusteriGrubu(ad=hedef))
            session.flush()
            return hedef

    @staticmethod
    def _grup_bul(session, ad: str):
        """Grup satırı: önce birebir ad (baş-son boşluk hariç), yoksa tek anahtar eşleşmesi."""
        from database.models.cari import MusteriGrubu

        gruplar = list(session.scalars(select(MusteriGrubu)).all())
        ad = (ad or "").strip()
        birebir = next((g for g in gruplar if (g.ad or "").strip() == ad), None)
        if birebir is not None:
            return birebir
        anahtar = CariService._grup_anahtari(ad)
        eslesen = [g for g in gruplar if CariService._grup_anahtari(g.ad) == anahtar]
        return eslesen[0] if len(eslesen) == 1 else None

    @staticmethod
    def _grup_kartlari(session, ad: str, *, silinenler_dahil: bool = True) -> list[Cari]:
        """Gruba bağlı kartlar: birebir aynı ad; yazımı farklı ad yalnız başka grup satırına ait değilse."""
        from database.models.cari import MusteriGrubu

        ad = (ad or "").strip()
        anahtar = CariService._grup_anahtari(ad)
        diger_adlar = {
            (g or "").strip() for g in session.scalars(select(MusteriGrubu.ad)).all() if (g or "").strip() != ad
        }
        sorgu = select(Cari).where(Cari.musteri_grubu.is_not(None))
        if not silinenler_dahil:
            sorgu = sorgu.where(or_(Cari.is_deleted.is_(False), Cari.is_deleted.is_(None)))
        sonuc = []
        for c in session.scalars(sorgu).all():
            kart_ad = (c.musteri_grubu or "").strip()
            if kart_ad == ad or (
                kart_ad not in diger_adlar and CariService._grup_anahtari(kart_ad) == anahtar
            ):
                sonuc.append(c)
        return sonuc

    @staticmethod
    def _grup_rolleri(session, ad: str) -> list[str]:
        ad = (ad or "").strip()
        return [rol for rol, deger in CariService._rol_ayarlari(session).items() if deger.strip() == ad]

    @staticmethod
    def grup_kullanimi(ad: str) -> dict[str, Any]:
        """Grubu kullanan kart sayısı, taşınabilecek hedef gruplar ve gruba bağlı sistem rolleri."""
        from database.models.cari import MusteriGrubu

        with get_session() as session:
            grup = CariService._grup_bul(session, ad)
            gercek = grup.ad if grup is not None else (ad or "").strip()
            kartlar = CariService._grup_kartlari(session, gercek, silinenler_dahil=True)
            hedefler = [
                g for g in session.scalars(select(MusteriGrubu.ad).order_by(MusteriGrubu.ad)).all()
                if (g or "").strip() != gercek.strip()
            ]
            roller = CariService._grup_rolleri(session, gercek)
        silinmemis = [c for c in kartlar if not c.is_deleted]
        return {
            "ad": gercek,
            "cari_sayisi": len(silinmemis),
            "silinmis_sayisi": len(kartlar) - len(silinmemis),
            "aktif_sayisi": sum(1 for c in silinmemis if c.aktif),
            "hedefler": hedefler,
            "roller": [CariService.GRUP_ROLLERI[r][1] for r in roller],
        }

    @staticmethod
    def grup_sil(ad: str, hedef: str | None = None) -> dict[str, Any]:
        """Grubu siler; bağlı kartlar (silinmiş kartlar dahil) ve rol ayarları önce ``hedef`` gruba taşınır.

        Taşıma, ayar güncellemesi ve silme tek veritabanı işlemidir; hata olursa hepsi geri alınır,
        hiçbir kart grupsuz kalmaz.
        """
        yazma_zorunlu("cari_duzenleme")
        from database.models.cari import MusteriGrubuAyari

        with get_session() as session:
            grup = CariService._grup_bul(session, ad)
            if grup is None:
                raise ValueError("Müşteri grubu bulunamadı.")
            kartlar = CariService._grup_kartlari(session, grup.ad)
            roller = CariService._grup_rolleri(session, grup.ad)
            hedef_grup = None
            if kartlar or roller:
                if not (hedef or "").strip():
                    neden = (f"{len(kartlar)} kart kullanıyor" if kartlar else "") + (
                        ("; " if kartlar else "") + "sistem bağlantısı var" if roller else "")
                    raise ValueError(f"«{grup.ad}» grubunu {neden}; önce taşınacak grubu seçin.")
                hedef_grup = CariService._grup_bul(session, hedef)
                if hedef_grup is None:
                    raise ValueError("Hedef müşteri grubu bulunamadı.")
                if hedef_grup.id == grup.id:
                    raise ValueError("Kartlar silinecek grubun kendisine taşınamaz.")
                for c in kartlar:
                    c.musteri_grubu = hedef_grup.ad
                if roller:
                    CariService._rol_tablosu_hazirla(session)
                    for rol in roller:
                        kayit = session.get(MusteriGrubuAyari, rol)
                        if kayit is None:
                            session.add(MusteriGrubuAyari(anahtar=rol, deger=hedef_grup.ad))
                        else:
                            kayit.deger = hedef_grup.ad
            session.delete(grup)
            session.flush()
            return {
                "silinen": grup.ad,
                "tasinan": len(kartlar),
                "hedef": hedef_grup.ad if hedef_grup is not None else None,
                "tasinan_roller": [CariService.GRUP_ROLLERI[r][1] for r in roller],
            }

    @staticmethod
    def _arama_kontrol(arama: str) -> str:
        arama = arama.strip()
        if arama and len(arama) < 3:
            raise ValueError("Arama için en az 3 karakter girin.")
        return arama

    _DEFTER_ATLA_ONEK = (
        "ODM-", "VRM-", "KKC-", "THS-", "AHV-", "GHV-", "POS-", "BNC-", "KBY-", "KKO-",
        "IPT-", "FZO-",
    )

    # Satış/alış evrak seçicilerinde stok-ürün kartı yoktur (ayrı tablo).
    # Cari tablosunda parti/finans dışı tutulacak türler (yoksa hepsi seçilebilir).
    EVRAK_CARI_HARIC = frozenset(
        {
            "stok",
            "ürün",
            "urun",
            "hizmet ürün",
            "hizmet urun",
        }
    )

    @staticmethod
    def _cari_turu_norm(tur: str | None) -> str:
        return (tur or "").strip().casefold().replace("ı", "i")

    @classmethod
    def evrak_cari_mi(cls, cari_turu: str | None) -> bool:
        """Belge cari seçicisine uygun gerçek cari kartı mı (stok/ürün değil)."""
        n = cls._cari_turu_norm(cari_turu)
        if not n:
            return True
        return n not in cls.EVRAK_CARI_HARIC and not n.startswith("stok")

    @staticmethod
    def _cari_turu_filtresi(statement, cari_turu: str | None):
        if not cari_turu:
            return statement
        tur = (cari_turu or "").strip()
        # Satış + alış evrak: tüm gerçek cari türleri (müşteri/tedarikçi kısıtı yok).
        if tur in {"*", "EVRAK", "EVRAK_CARI", "__EVRAK__", "Tümü", "Tumu", "GENEL"}:
            return statement
        # Liste ekranları: güncel Ana Cari Kart Türü (beşli) — karma tür dahil edilmez
        try:
            from database.kart_turu_service import KartTuruService

            return KartTuruService.cari_filtre_uygula(statement, ana_rol=tur)
        except Exception:
            if tur.casefold().startswith("muster") or tur.casefold().startswith("müşter"):
                return statement.where(Cari.cari_turu == "Müşteri")
            if tur.casefold().startswith("tedarik"):
                return statement.where(Cari.cari_turu == "Tedarikçi")
            return statement.where(Cari.cari_turu == tur)

    @staticmethod
    def _toplu_liste_ozet(
        session,
        cariler: list[Cari],
        *,
        valor: bool = True,
    ) -> list[dict[str, Any]]:
        """Liste ekranı: toplu bakiye; valor=True ise açık bakiyelerde FIFO valör."""
        from database.cari_bakiye_service import liste_bakiyeleri_detay
        from database.cari_ortalama_valor_service import (
            calculate_accounts_average_value_date_bulk,
        )

        if not cariler:
            return []
        ids = [c.id for c in cariler]

        # Önce toplu bakiye (hızlı); valör yalnızca açık bakiyeli cariler için yüklenir
        detay = liste_bakiyeleri_detay(ids)
        bakiyeler: dict[int, Decimal] = {
            cid: detay.get(cid, {}).get("bakiye", Decimal("0")) for cid in ids
        }
        borc_alacak: dict[int, tuple[Decimal, Decimal]] = {
            cid: (
                detay.get(cid, {}).get("toplam_borc", Decimal("0")),
                detay.get(cid, {}).get("toplam_alacak", Decimal("0")),
            )
            for cid in ids
        }

        valor_by: dict[int, dict[str, Any]] = {}
        if valor:
            # hareket_by/islem_by toplu fonksiyonda kullanılmıyor; her açık cari
            # fifo_valor_paketi_oturumdan ile çözülür. Önceden tüm hareketleri
            # belleğe çekmek listeyi ~10× yavaşlatıyordu — kaldırıldı.
            valor_by = calculate_accounts_average_value_date_bulk(
                cariler,
                session,
                bakiyeler=bakiyeler,
            )

        sonuclar: list[dict[str, Any]] = []
        for cari in cariler:
            cid = cari.id
            bakiye = bakiyeler[cid]
            toplam_borc, toplam_alacak = borc_alacak[cid]
            voz = valor_by.get(cid) or {}
            if valor and voz:
                raw_g = voz.get("ortalama_valor_gun")
                gun: float | None = float(raw_g) if raw_g is not None else None
                yukleniyor = False
            elif valor:
                gun = None if bakiye != 0 else 0.0
                yukleniyor = False
            else:
                # İki aşamalı UI: bakiyeler hemen; açık bakiyede valör «Yükleniyor…»
                if bakiye != 0:
                    gun = None
                    yukleniyor = True
                else:
                    gun = 0.0
                    yukleniyor = False
            acik_sayisi = len(voz.get("acik_kalemler") or [])

            sonuclar.append(
                {
                    "cari": cari,
                    "bakiye": bakiye,
                    "bakiye_durumu": voz.get("bakiye_durumu")
                    or ("Borçlu" if bakiye > 0 else ("Alacaklı" if bakiye < 0 else "Kapalı")),
                    "bakiye_yonu": voz.get("bakiye_yonu"),
                    "valor_turu": voz.get("valor_turu"),
                    "valor_turu_etiket": voz.get("valor_turu_etiket"),
                    "ortalama_valor_tarihi": voz.get("ortalama_valor_tarihi"),
                    "ortalama_valor_uyari": voz.get("uyari"),
                    "ortalama_valor_sebep": voz.get("hesaplama_sebep"),
                    "ortalama_yas_gun": voz.get("ortalama_yas_gun"),
                    "toplam_borc": toplam_borc,
                    "toplam_alacak": toplam_alacak,
                    # Hızlı listede kapatılan valör hesaplanmaz (None → kolon boş)
                    "odenen_ortalama_valor_gun": None,
                    "odenen_ortalama_valor_basit_gun": None,
                    "bakiye_ortalama_valor_gun": gun,
                    "borc_tutar": Decimal("0"),
                    "alacak_tutar": Decimal("0"),
                    "borc_valor_gun": gun if bakiye > 0 else None,
                    "alacak_valor_gun": gun if bakiye < 0 else None,
                    "ortalama_gun": gun if gun is not None else 0.0,
                    "agirlikli_ortalama_gun": gun,
                    "valor_yukleniyor": yukleniyor,
                    "acik_hareket_sayisi": acik_sayisi,
                    "ana_yetkili": "",
                    "yetkili_telefon": "",
                    "yaklasan_dogum": "",
                }
            )
        CariService._yetkili_ozetlerini_ekle(session, sonuclar, ids)
        CariService._ust_hesap_ozetlerini_ekle(session, sonuclar, ids)
        for ozet in sonuclar:
            session.expunge(ozet["cari"])
        return sonuclar

    @staticmethod
    def _ust_hesap_ozetlerini_ekle(session, sonuclar: list[dict], ids: list[int]) -> None:
        """Liste kolonu: bağlı üst hesap kod + unvan (toplu)."""
        if not ids or not sonuclar:
            return
        ust_idler = {
            int(o["cari"].ust_cari_id)
            for o in sonuclar
            if getattr(o.get("cari"), "ust_cari_id", None)
        }
        if not ust_idler:
            for ozet in sonuclar:
                ozet.setdefault("ust_hesap", "")
            return
        try:
            ustlar = {
                int(c.id): c
                for c in session.scalars(select(Cari).where(Cari.id.in_(list(ust_idler)))).all()
            }
        except Exception:
            for ozet in sonuclar:
                ozet.setdefault("ust_hesap", "")
            return
        for ozet in sonuclar:
            cid = getattr(ozet.get("cari"), "ust_cari_id", None)
            if not cid:
                ozet["ust_hesap"] = ""
                continue
            ust = ustlar.get(int(cid))
            if not ust:
                ozet["ust_hesap"] = f"#{int(cid)}"
            else:
                ozet["ust_hesap"] = f"{ust.cari_kodu or ''} {ust.unvan or ''}".strip()

    @staticmethod
    def _yetkili_ozetlerini_ekle(session, sonuclar: list[dict], ids: list[int]) -> None:
        """Liste kolonları için ana yetkili / telefon / yaklaşan doğum (toplu)."""
        if not ids or not sonuclar:
            return
        try:
            from database.models.cari import CariYetkili
            from database.cari_yetkili_service import _sonraki_dogum
        except Exception:
            return
        try:
            kayitlar = list(
                session.scalars(
                    select(CariYetkili).where(
                        CariYetkili.cari_id.in_(ids),
                        CariYetkili.aktif.is_(True),
                        or_(CariYetkili.is_deleted.is_(False), CariYetkili.is_deleted.is_(None)),
                    )
                ).all()
            )
        except Exception:
            return
        by_cari: dict[int, list] = {i: [] for i in ids}
        for y in kayitlar:
            by_cari.setdefault(int(y.cari_id), []).append(y)
        bugun = date.today()
        for ozet in sonuclar:
            cid = int(ozet["cari"].id)
            adaylar = by_cari.get(cid) or []
            if not adaylar:
                continue
            ana = next((y for y in adaylar if y.ana_yetkili), adaylar[0])
            ozet["ana_yetkili"] = f"{ana.ad} {ana.soyad}".strip()
            ozet["yetkili_telefon"] = ana.cep_telefonu or ana.is_telefonu or ""
            en_yakin = None
            for y in adaylar:
                if not y.dogum_tarihi or not y.dogum_gunu_hatirlat:
                    continue
                sonraki = _sonraki_dogum(y.dogum_tarihi, bugun)
                if sonraki is None:
                    continue
                kalan = (sonraki - bugun).days
                if kalan > 30:
                    continue
                if en_yakin is None or kalan < en_yakin[0]:
                    en_yakin = (kalan, sonraki)
            if en_yakin is not None:
                kalan, sonraki = en_yakin
                ozet["yaklasan_dogum"] = (
                    "Bugün" if kalan == 0 else f"{kalan} gün ({sonraki.strftime('%d.%m')})"
                )

    @staticmethod
    def _durum_filtre_norm(durum_filtre: str | None) -> str:
        """Aktif | Pasif | Tümü — tanımsız/boş → Tümü (geriye uyum)."""
        d = (durum_filtre or "").strip().casefold()
        if d in {"aktif", "active"}:
            return "Aktif"
        if d in {"pasif", "passive"}:
            return "Pasif"
        return "Tümü"

    @staticmethod
    def listele(
        arama: str = "",
        cari_turu: str | None = None,
        hizli: bool = True,
        *,
        valor: bool = False,
        durum_filtre: str | None = None,
    ) -> list[dict[str, Any]]:
        """Cari listesi. Varsayılan hizli=True (toplu bakiye; UI donmasını önler).

        durum_filtre: Aktif | Pasif | Tümü — sayfalama/sayım öncesi SQL'de uygulanır.
        valor=False (varsayılan): yalnızca bakiye/özet — liste ilk boyama.
        valor=True: açık bakiyelerde FIFO Kalan Bakiye Gün (ağır; arka plan
        ``liste_valor_guncelle`` tercih edilir).
        Tam defter + odenen valör için hizli=False kullanın.
        """
        from sqlalchemy.orm import selectinload

        from database.search_service import SearchService, tokenize_query

        arama = CariService._arama_kontrol(arama)
        durum = CariService._durum_filtre_norm(durum_filtre)
        sadece_aktif = durum == "Aktif"
        # Çoklu blok / sıra bağımsız arama
        if arama and tokenize_query(arama):
            hits = SearchService.search_customers(
                arama,
                limit=200 if hizli else 500,
                cari_turu=cari_turu,
                sadece_aktif=sadece_aktif,
            )
            ids = [int(h["cari"].id) for h in hits if getattr(h["cari"], "id", None)]
            if not ids:
                return []
            with get_session() as session:
                # Arama sonuçları başka oturumdan gelir; bu oturumda yeniden yüklenmeli
                statement = select(Cari).where(Cari.id.in_(ids))
                if durum == "Pasif":
                    statement = statement.where(Cari.aktif.is_(False))
                elif durum == "Aktif":
                    statement = statement.where(Cari.aktif.is_(True))
                if not hizli:
                    statement = statement.options(selectinload(Cari.satis_hareketleri))
                yuklenen = {c.id: c for c in session.scalars(statement).all()}
                sirali = [yuklenen[i] for i in ids if i in yuklenen]
                if hizli:
                    return CariService._toplu_liste_ozet(session, sirali, valor=valor)
                return [CariService._ozet(cari, session=session) for cari in sirali]

        with get_session() as session:
            statement = select(Cari).order_by(Cari.cari_kodu)
            if not hizli:
                statement = statement.options(selectinload(Cari.satis_hareketleri))
            statement = statement.where(
                or_(Cari.is_deleted.is_(False), Cari.is_deleted.is_(None))
            )
            if durum == "Aktif":
                statement = statement.where(Cari.aktif.is_(True))
            elif durum == "Pasif":
                statement = statement.where(Cari.aktif.is_(False))
            statement = CariService._cari_turu_filtresi(statement, cari_turu)
            cariler = list(session.scalars(statement).all())
            if hizli:
                return CariService._toplu_liste_ozet(session, cariler, valor=valor)
            return [CariService._ozet(cari, session=session) for cari in cariler]

    @staticmethod
    def liste_valor_guncelle(ozetler: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Mevcut liste özetlerine FIFO valör alanlarını yazar (arka plan ikinci aşama)."""
        if not ozetler:
            return ozetler
        cariler = [o["cari"] for o in ozetler if o.get("cari") is not None]
        if not cariler:
            return ozetler
        bakiyeler = {
            int(o["cari"].id): o.get("bakiye", Decimal("0"))
            for o in ozetler
            if o.get("cari") is not None
        }
        with get_session() as session:
            from database.cari_ortalama_valor_service import (
                calculate_accounts_average_value_date_bulk,
            )

            # Toplu valör oturumdan paket çeker; önceden tüm hareket yüklemek gereksiz.
            valor_by = calculate_accounts_average_value_date_bulk(
                cariler,
                session,
                bakiyeler=bakiyeler,
            )
        for ozet in ozetler:
            cari = ozet.get("cari")
            if cari is None:
                continue
            cid = int(cari.id)
            bakiye = ozet.get("bakiye", Decimal("0"))
            voz = valor_by.get(cid) or {}
            raw_g = voz.get("ortalama_valor_gun")
            gun = float(raw_g) if raw_g is not None else None
            ozet["bakiye_durumu"] = voz.get("bakiye_durumu") or ozet.get("bakiye_durumu")
            ozet["bakiye_yonu"] = voz.get("bakiye_yonu")
            ozet["valor_turu"] = voz.get("valor_turu")
            ozet["valor_turu_etiket"] = voz.get("valor_turu_etiket")
            ozet["ortalama_valor_tarihi"] = voz.get("ortalama_valor_tarihi")
            ozet["ortalama_valor_uyari"] = voz.get("uyari")
            ozet["ortalama_valor_sebep"] = voz.get("hesaplama_sebep")
            ozet["ortalama_yas_gun"] = voz.get("ortalama_yas_gun")
            ozet["bakiye_ortalama_valor_gun"] = gun
            ozet["borc_valor_gun"] = gun if bakiye > 0 else None
            ozet["alacak_valor_gun"] = gun if bakiye < 0 else None
            ozet["ortalama_gun"] = gun if gun is not None else 0.0
            ozet["agirlikli_ortalama_gun"] = gun
            ozet["valor_yukleniyor"] = False
            ozet["acik_hareket_sayisi"] = len(voz.get("acik_kalemler") or [])
        return ozetler

    @staticmethod
    def getir(cari_id: int) -> Cari | None:
        with get_session() as session:
            return session.get(Cari, cari_id)

    @staticmethod
    def uyari_notu_oku(cari_id: int | None) -> str:
        """Cariye tanımlı uyarı notunu döner (yoksa boş)."""
        if not cari_id:
            return ""
        with get_session() as session:
            cari = session.get(Cari, int(cari_id))
            if cari is None:
                return ""
            return (getattr(cari, "uyari_notu", None) or "").strip()

    @staticmethod
    def kod_ile_getir(cari_kodu: str) -> Cari | None:
        kod = (cari_kodu or "").strip()
        if not kod:
            return None
        with get_session() as session:
            return session.scalar(select(Cari).where(Cari.cari_kodu == kod))

    @staticmethod
    def detay(cari_id: int) -> dict[str, Any] | None:
        from sqlalchemy.orm import selectinload

        with get_session() as session:
            cari = session.scalar(
                select(Cari)
                .where(Cari.id == int(cari_id))
                .options(selectinload(Cari.satis_hareketleri))
            )
            if cari is None:
                return None
            return {
                "cari": cari,
                "hareketler": CariService._defter(session, cari_id),
                "acik_hareketler": sorted(
                    [h for h in cari.satis_hareketleri if h.kalan_acik_tutar > 0],
                    key=lambda item: item.satis_tarihi,
                ),
            }

    @staticmethod
    def _defter_belge_tur_haritasi(session, belge_nolari: set[str]) -> dict[str, str]:
        """Kaynak belge tablolarından tur etiketi (ön ek / işaret varsayımı yok)."""
        nolar = {((b or "").strip()) for b in belge_nolari if (b or "").strip()}
        if not nolar:
            return {}
        sonuc: dict[str, str] = {}
        # Sıra: iade > fatura (çakışmada daha spesifik)
        sorgular = (
            ("alis_iade_faturalari", "iade_no", "Alış İadesi"),
            ("satis_iade_faturalari", "iade_no", "Satış İadesi"),
            ("alis_faturalari", "fatura_no", "Alış"),
            ("satis_faturalari", "fatura_no", "Satış"),
        )
        from sqlalchemy import bindparam, inspect as sa_inspect, text as sa_text

        insp = sa_inspect(session.connection())
        liste = list(nolar)
        for tablo, kolon, tur in sorgular:
            if not insp.has_table(tablo):
                continue
            # SQLite/PG ortak: expanding IN
            for bas in range(0, len(liste), 400):
                parca = liste[bas : bas + 400]
                stmt = sa_text(
                    f'SELECT "{kolon}" FROM "{tablo}" WHERE "{kolon}" IN :nolar'
                ).bindparams(bindparam("nolar", expanding=True))
                bulundu = session.execute(stmt, {"nolar": parca}).scalars().all()
                for bn in bulundu:
                    anahtar = (bn or "").strip()
                    if anahtar and anahtar not in sonuc:
                        sonuc[anahtar] = tur
        return sonuc
    @staticmethod
    def _defter_sh_turu(belge_no: str, tur_map: dict[str, str]) -> str:
        """SH satırı için tur: önce kaynak belge; yoksa güvenli önek yedekleri."""
        bn = (belge_no or "").strip()
        if bn in tur_map:
            return tur_map[bn]
        # Eski Cin önekleri (kaynak satırı henüz bağlanmamış olabilir)
        if bn.startswith("AIAD-"):
            return "Alış İadesi"
        if bn.startswith("IAD-"):
            return "Satış İadesi"
        if bn.startswith(("AFAT-", "ARAY")):
            return "Alış"
        # Evo alış faturası öneki — tabloda yoksa bile alış (import kanıtı)
        if bn.upper().startswith("EVB-AF-"):
            return "Alış"
        return "Satış"

    @staticmethod
    def _defter(session, cari_id: int) -> list[dict[str, Any]]:
        from database.cari_bakiye_service import (
            _defterde_kapanan_toplamlari,
            _satis_hareketi_borc_alacak,
        )

        kayitlar: list[dict[str, Any]] = []
        islemler = list(
            session.scalars(select(CariIslem).where(CariIslem.cari_id == cari_id)).all()
        )
        islem_belgeleri = {i.belge_no for i in islemler}
        hareketler = list(
            session.scalars(select(SatisHareketi).where(SatisHareketi.cari_id == cari_id)).all()
        )
        sh_aday: list[SatisHareketi] = []
        for h in hareketler:
            # Aynı belge CariIslem'de varsa çift kayıt olmasın (GHV/KKC/ODM vb.)
            if h.belge_no in islem_belgeleri:
                continue
            if (h.belge_no or "").startswith(
                ("ODM-", "VRM-", "KKC-", "THS-", "AHV-", "GHV-", "POS-", "BNC-", "KBY-", "KKO-", "IPT-", "FZO-", "OMK-", "TMK-")
            ):
                continue
            sh_aday.append(h)

        tur_map = CariService._defter_belge_tur_haritasi(
            session, {(h.belge_no or "").strip() for h in sh_aday}
        )
        defterde = _defterde_kapanan_toplamlari(
            session,
            [int(h.id) for h in sh_aday if getattr(h, "id", None)],
            islem_belgeleri,
        )

        for h in sh_aday:
            borc, alacak = _satis_hareketi_borc_alacak(
                h.satis_tutari,
                getattr(h, "kalan_acik_tutar", None),
                defterde_kapanan=defterde.get(int(h.id), Decimal("0")),
            )
            kayitlar.append({
                "tarih": h.satis_tarihi,
                "tur": CariService._defter_sh_turu(h.belge_no or "", tur_map),
                "belge_no": h.belge_no,
                "aciklama": "",
                "borc": borc,
                "alacak": alacak,
                "kalan": None,
                "para_birimi": getattr(h, "para_birimi", None) or "TRY",
                "doviz_tutari": getattr(h, "doviz_tutari", None) or Decimal("0"),
                "kur": getattr(h, "kur", None) or Decimal("1"),
                "cari_id": cari_id,
                "hareket_kaynak": "satis_hareketi",
                "hareket_id": int(h.id),
            })
        karsi_idler = {
            int(i.karsi_cari_id) for i in islemler if getattr(i, "karsi_cari_id", None)
        }
        karsi_map: dict[int, Cari] = {}
        if karsi_idler:
            for k in session.scalars(select(Cari).where(Cari.id.in_(karsi_idler))).all():
                karsi_map[int(k.id)] = k
        for islem in islemler:
            aciklama = islem.aciklama or ""
            if islem.karsi_cari_id:
                karsi = karsi_map.get(int(islem.karsi_cari_id))
                if karsi is not None:
                    if islem.alacak > 0:
                        ek = f"Karşı cariye borç: {karsi.cari_kodu}"
                    elif islem.borc > 0:
                        ek = f"Karşı cariden alacak: {karsi.cari_kodu}"
                    else:
                        ek = f"Karşı: {karsi.cari_kodu}"
                    if ek not in aciklama:
                        aciklama = f"{aciklama} | {ek}".strip(" |")
            doviz_tutar = Decimal(str(getattr(islem, "doviz_borc", 0) or 0)) or Decimal(
                str(getattr(islem, "doviz_alacak", 0) or 0)
            )
            kayitlar.append({
                "tarih": islem.tarih,
                "tur": islem.islem_turu,
                "belge_no": islem.belge_no,
                "aciklama": aciklama,
                "borc": islem.borc,
                "alacak": islem.alacak,
                "kalan": None,
                "para_birimi": getattr(islem, "para_birimi", None) or "TRY",
                "doviz_tutari": doviz_tutar,
                "kur": getattr(islem, "kur", None) or Decimal("1"),
                "cari_id": cari_id,
                "hareket_kaynak": "cari_islem",
                "hareket_id": int(islem.id),
            })
        # Kronolojik çalışan bakiye → Kalan Bakiye kolonu
        kayitlar.sort(key=lambda item: (item["tarih"], item["belge_no"], item["tur"]))
        calisan = Decimal("0")
        for kayit in kayitlar:
            calisan += Decimal(str(kayit["borc"] or 0)) - Decimal(str(kayit["alacak"] or 0))
            kayit["kalan"] = calisan
        kayitlar.reverse()  # ekranda yeniden eskiye
        try:
            from database.cari_fatura_detay_service import CariFaturaDetayService

            CariFaturaDetayService.hareketlere_meta_ekle(kayitlar)
        except Exception:
            for kayit in kayitlar:
                kayit.setdefault("genisletilebilir", False)
        return kayitlar

    @staticmethod
    def _belge_no(session, on_ek: str) -> str:
        yil = date.today().year
        like = f"{on_ek}-{yil}-%"
        mevcut = session.scalars(select(CariIslem.belge_no).where(CariIslem.belge_no.like(like))).all()
        sira = 1
        for no in mevcut:
            try:
                sira = max(sira, int(no.rsplit("-", 1)[-1]) + 1)
            except ValueError:
                pass
        return f"{on_ek}-{yil}-{sira:04d}"

    @staticmethod
    def _aciklara_uygula(
        session,
        cari_id: int,
        tutar: Decimal,
        belge_no: str = "",
        *,
        kaynak_tur: str = "TAHSILAT",
        tarih: date | None = None,
        dagitim=None,
    ) -> Decimal:
        """Açık kalemlere uygular (merkez: AcikKalemService.kapat); eşleşmeyen tutarı döner."""
        from database.acik_kalem_service import AcikKalemService

        return AcikKalemService.kapat(
            session,
            cari_id,
            tutar,
            belge_no=belge_no,
            kaynak_tur=kaynak_tur,
            tarih=tarih,
            dagitim=dagitim,
        ).kalan

    @staticmethod
    def _alacak_uygula(
        session,
        cari_id: int,
        tutar,
        belge_no: str,
        tarih: date,
        *,
        kaynak_tur: str = "TAHSILAT",
        dagitim=None,
        fazla: str = "FIFO",
    ) -> dict:
        """Cariye alacak etkisi: açık kalemleri kapatır, artanı avans (açık kredi) olarak saklar."""
        from database.acik_kalem_service import AcikKalemService

        return AcikKalemService.alacak_etkisi(
            session,
            cari_id,
            tutar,
            belge_no=belge_no,
            tarih=tarih,
            kaynak_tur=kaynak_tur,
            dagitim=dagitim,
            fazla=fazla,
        )

    @staticmethod
    def tahsilat_yap(
        cari_id: int,
        tarih: date,
        tutar,
        odeme_sekli: str,
        hesap_adi: str,
        aciklama: str | None = None,
        *,
        dagitim=None,
        fazla: str = "FIFO",
        beklenen: dict | None = None,
    ) -> CariIslem:
        """dagitim: [(hareket_id, tutar)] kullanıcı seçimi; yoksa FIFO. fazla: dağıtım dışı kalan FIFO/AVANS.

        beklenen: {hareket_id: ekranda görülen açık tutar} — değiştiyse AcikKalemDegisti (kayıt yok).
        """
        tutar = CariService._tutar(tutar)
        if tutar <= 0:
            raise ValueError("Tahsilat tutarı pozitif olmalıdır.")
        if tarih > date.today():
            raise ValueError("Tahsilat tarihi gelecek bir tarih olamaz.")
        with get_session() as session:
            cari = session.get(Cari, cari_id)
            if cari is None:
                raise ValueError("Cari bulunamadı.")
            from database.acik_kalem_service import AcikKalemService

            AcikKalemService.beklenen_dogrula(session, cari_id, beklenen)
            belge_no = CariService._belge_no(session, "THS")
            CariService._alacak_uygula(
                session, cari_id, tutar, belge_no, tarih, kaynak_tur="TAHSILAT", dagitim=dagitim, fazla=fazla
            )
            islem = CariIslem(
                cari_id=cari_id, tarih=tarih, islem_turu="Tahsilat", belge_no=belge_no,
                aciklama=aciklama or odeme_sekli, borc=Decimal("0"), alacak=tutar, hesap_adi=hesap_adi,
            )
            session.add(islem)
            FinansService.hareket_ekle(session, belge_no, tarih, tutar, "CARİ TAHSİLAT", hesap_adi, odeme_sekli)
            session.flush()
            iid = int(islem.id)
            from database.finans_evrak_kimligi import EVRAK_CARI_TAHSILAT, kimlik_al
            from database.muhasebe_entegrasyon import muhasebe_hook

            kimlik = kimlik_al(session, EVRAK_CARI_TAHSILAT, belge_no, cari_islem_id=iid)
            muhasebe_hook("cari_tahsilat_fisi", kimlik, session=session)
        with get_session() as session:
            return session.get(CariIslem, iid)

    @staticmethod
    def odeme_yap(
        cari_id: int,
        tarih: date,
        tutar,
        odeme_sekli: str,
        hesap_adi: str,
        aciklama: str | None = None,
        *,
        dagitim=None,
        fazla: str = "FIFO",
        beklenen: dict | None = None,
    ) -> CariIslem:
        tutar = CariService._tutar(tutar)
        if tutar <= 0:
            raise ValueError("Ödeme tutarı pozitif olmalıdır.")
        if tarih > date.today():
            raise ValueError("Ödeme tarihi gelecek bir tarih olamaz.")
        with get_session() as session:
            cari = session.get(Cari, cari_id)
            if cari is None:
                raise ValueError("Cari bulunamadı.")
            from database.acik_kalem_service import AcikKalemService

            AcikKalemService.beklenen_dogrula(session, cari_id, beklenen)
            belge_no = CariService._belge_no(session, "ODM")
            # Tedarikçi: ödeme BORÇ yazar (Evo BNC polaritesi; tedarikçiye borcumuz azalır).
            # Müşteri: ödeme müşteriye borç yazar (varsa avansını kapatır).
            # Yön cari_turu ile; kart kodunun T/M ön ekinden çıkarılmaz.
            if (cari.cari_turu or "") == "Tedarikçi":
                CariService._alacak_uygula(
                    session, cari_id, tutar, belge_no, tarih, kaynak_tur="ODEME", dagitim=dagitim, fazla=fazla
                )
                islem = CariIslem(
                    cari_id=cari_id, tarih=tarih, islem_turu="Ödeme", belge_no=belge_no,
                    aciklama=aciklama or odeme_sekli, borc=tutar, alacak=Decimal("0"), hesap_adi=hesap_adi,
                )
            else:
                from database.acik_kalem_service import AcikKalemService

                AcikKalemService.borc_etkisi(session, cari_id, tutar, belge_no=belge_no, tarih=tarih)
                islem = CariIslem(
                    cari_id=cari_id, tarih=tarih, islem_turu="Ödeme", belge_no=belge_no,
                    aciklama=aciklama or odeme_sekli, borc=tutar, alacak=Decimal("0"), hesap_adi=hesap_adi,
                )
            session.add(islem)
            FinansService.hareket_ekle(session, belge_no, tarih, tutar, "CARİ ÖDEME", hesap_adi, odeme_sekli)
            session.flush()
            iid = int(islem.id)
            from database.finans_evrak_kimligi import EVRAK_CARI_ODEME, kimlik_al
            from database.muhasebe_entegrasyon import muhasebe_hook

            kimlik = kimlik_al(session, EVRAK_CARI_ODEME, belge_no, cari_islem_id=iid)
            muhasebe_hook("cari_odeme_fisi", kimlik, session=session)
        with get_session() as session:
            return session.get(CariIslem, iid)

    @staticmethod
    def tahsilat_odeme_evraki(islem_id: int) -> dict | None:
        """Cari hareket, cari kartından yapılmış bir tahsilat/ödeme evrakı mı (kalıcı kimlikle)."""
        from database.finans_evrak_kimligi import EVRAK_CARI_ODEME, EVRAK_CARI_TAHSILAT, cari_islem_kimligi

        with get_session() as session:
            for evrak in (EVRAK_CARI_TAHSILAT, EVRAK_CARI_ODEME):
                kimlik = cari_islem_kimligi(session, evrak, int(islem_id))
                if kimlik is not None:
                    return {"evrak_turu": evrak, "kaynak_id": int(kimlik.id), "belge_no": kimlik.belge_no}
        return None

    @staticmethod
    def _eski_tahsilat_odeme_kimligi(session, islem: CariIslem):
        """Kalıcı kimlik öncesi cari kartı tahsilat/ödemesi: yapı kesinse (THS/ODM, tek cari hareket,
        aynı tutarda tek kasa/banka hareketi) kimlik oluşturulur; değilse None."""
        from database.finans_evrak_kimligi import EVRAK_CARI_ODEME, EVRAK_CARI_TAHSILAT, kimlik_al, kimlik_getir
        from database.models.finans import FinansHareketi

        no = islem.belge_no or ""
        tur = (islem.islem_turu or "")
        if tur == "Tahsilat" and no.startswith("THS-"):
            evrak, hareket_turu = EVRAK_CARI_TAHSILAT, "CARİ TAHSİLAT"
        elif tur == "Ödeme" and no.startswith("ODM-"):
            evrak, hareket_turu = EVRAK_CARI_ODEME, "CARİ ÖDEME"
        else:
            return None
        if session.scalar(select(func.count()).select_from(CariIslem).where(CariIslem.belge_no == no)) != 1:
            return None
        hareketler = session.scalars(select(FinansHareketi).where(FinansHareketi.belge_no == no)).all()
        tutar = Decimal(str(islem.alacak or 0)) + Decimal(str(islem.borc or 0))
        if len(hareketler) != 1 or hareketler[0].hareket_turu != hareket_turu or \
                Decimal(str(hareketler[0].tutar)) != tutar:
            return None
        return kimlik_getir(session, kimlik_al(session, evrak, no, cari_islem_id=islem.id, kaynak="gecmis"), evrak)

    @staticmethod
    def _eski_tahsilat_fisini_kapat(session, islem: CariIslem, neden: str) -> None:
        """Eski sürümün cari hareket id'sine bağlı fişi (aynı belge numarasıyla) bir kez ters kayıtla kapatır."""
        from database.models.genel_muhasebe import MuhasebeFisi
        from database.muhasebe_entegrasyon import (
            ESKI_KAYNAK_CARI_ODEME,
            ESKI_KAYNAK_CARI_TAHSILAT,
            MuhasebeEntegrasyonService,
        )

        kaynak = ESKI_KAYNAK_CARI_TAHSILAT if (islem.islem_turu or "") == "Tahsilat" else ESKI_KAYNAK_CARI_ODEME
        bagli = session.scalar(select(MuhasebeFisi.id).where(
            MuhasebeFisi.kaynak_turu == kaynak, MuhasebeFisi.kaynak_id == int(islem.id),
            MuhasebeFisi.durum != "İptal", MuhasebeFisi.belge_no == islem.belge_no).limit(1))
        if bagli is not None:  # id yeniden kullanılmış olabilir: belge numarası da aynı olmalı
            MuhasebeEntegrasyonService.iptal_kaynak(kaynak, int(islem.id), f"İptal: {neden}", session=session)

    @staticmethod
    def tahsilat_odeme_iptal(islem_id: int, neden: str) -> None:
        """Cari kartından yapılan tahsilat/ödemeyi bütün etkileriyle tek transaction'da iptal eder.

        Kasa/banka hareketi silinir, kapattığı borçlar (tahsis kayıtlarıyla) yeniden açılır, cari
        hareket kaldırılır; muhasebeleştirilmişse fiş bir kez ters kayıtla kapanır, değilse ters fiş
        oluşmaz. İptal günlüğüne anlık görüntü yazılır. İkinci istek (çift tıklama / eş zamanlı)
        kaydı bulamaz ve hiçbir etki üretmez.
        """
        from database.finans_evrak_kimligi import EVRAK_CARI_ODEME, EVRAK_CARI_TAHSILAT, cari_islem_kimligi
        from database.muhasebe_entegrasyon import muhasebe_hook
        from database.muhasebe_service import kapali_donem_zorunlu_degil
        from database.models.finans import FinansHareketi

        yazma_zorunlu("cari_duzenleme", "finans_duzenleme",
                      mesaj="Tahsilat/ödeme iptali için cari veya finans düzenleme yetkisi gerekir.")
        neden = (neden or "").strip()
        if not neden:
            raise ValueError("İptal nedeni yazın.")
        from database.deleted_record_service import AuditDeleteService

        AuditDeleteService.schema_hazirla()
        with get_session() as session:
            # Önce satırı yazma kilidiyle sahiplen: eş zamanlı ikinci iptal burada bekler, sonra boş döner
            sahip = session.execute(
                update(CariIslem).where(CariIslem.id == int(islem_id)).values(aciklama=CariIslem.aciklama)
                .execution_options(synchronize_session=False)
            ).rowcount
            islem = session.get(CariIslem, int(islem_id)) if sahip else None
            if islem is None:
                raise ValueError("Tahsilat/ödeme bulunamadı; zaten iptal edilmiş olabilir.")
            kimlik = None
            for evrak in (EVRAK_CARI_TAHSILAT, EVRAK_CARI_ODEME):
                kimlik = cari_islem_kimligi(session, evrak, islem.id)
                if kimlik is not None:
                    break
            if kimlik is None:
                kimlik = CariService._eski_tahsilat_odeme_kimligi(session, islem)
            if kimlik is None:
                raise ValueError(
                    "Bu hareket cari kartından yapılmış bir tahsilat/ödeme evrakı değil "
                    "(makbuz, havale, fatura veya aktarım hareketi); kendi evrakından iptal edin."
                )
            kapali_donem_zorunlu_degil(session, islem.tarih, "Tahsilat/ödeme")
            belge_no = islem.belge_no
            CariService._eski_tahsilat_fisini_kapat(session, islem, neden)
            tutar = Decimal(str(islem.alacak or 0)) + Decimal(str(islem.borc or 0))
            hareketler = session.scalars(select(FinansHareketi).where(FinansHareketi.belge_no == belge_no)).all()
            snap = {
                "entity": {"belge_no": belge_no, "evrak_turu": kimlik.evrak_turu, "kimlik_id": kimlik.id,
                           "cari_id": islem.cari_id, "tarih": str(islem.tarih), "borc": str(islem.borc),
                           "alacak": str(islem.alacak), "hesap_adi": islem.hesap_adi},
                "related": [{"type": "finans_hareketi", "id": h.id, "hesap_id": h.hesap_id,
                             "tutar": str(h.tutar), "hareket_turu": h.hareket_turu} for h in hareketler],
            }
            muhasebe_hook(f"{kimlik.evrak_turu}_iptal", int(kimlik.id), f"İptal: {neden}", session=session)
            kimlik.cari_islem_id = None  # cari hareket silinir; id SQLite'ta yeniden kullanılabilir
            FinansService._havale_cari_geri_al(session, belge_no)
            FinansService._finans_hareketlerini_sil(session, belge_no)
            session.flush()
            AuditDeleteService.log_cancel_snapshot(
                "cari_tahsilat_odeme", belge_no, reason=neden,
                note=f"{'Tahsilat' if kimlik.evrak_turu == EVRAK_CARI_TAHSILAT else 'Ödeme'} iptal",
                snapshot=snap, record_code=belge_no, amount=tutar, module="cari", session=session,
            )

    @staticmethod
    def acilis_fisi_ekle(
        cari_id: int,
        tarih: date,
        *,
        borc=0,
        alacak=0,
        belge_no: str,
        aciklama: str | None = None,
    ) -> CariIslem:
        """Cari açılış / devir fişi (borç veya alacak; ikisi birden olmaz).

        Borç satırında SatisHareketi de yazılır ki FIFO açık borç kuyruğuna girsin.
        """
        borc_t = borc if isinstance(borc, Decimal) else CariService._tutar(borc)
        alacak_t = alacak if isinstance(alacak, Decimal) else CariService._tutar(alacak)
        if not isinstance(borc_t, Decimal):
            borc_t = Decimal(str(borc_t))
        if not isinstance(alacak_t, Decimal):
            alacak_t = Decimal(str(alacak_t))
        borc_t = borc_t.quantize(Decimal("0.01"))
        alacak_t = alacak_t.quantize(Decimal("0.01"))
        if borc_t < 0 or alacak_t < 0:
            raise ValueError("Açılış tutarları negatif olamaz.")
        if (borc_t > 0) == (alacak_t > 0):
            raise ValueError("Açılış fişinde yalnızca borç veya yalnızca alacak olmalıdır.")
        belge = (belge_no or "").strip()
        if not belge:
            raise ValueError("Belge numarası zorunludur.")
        if len(belge) > 50:
            raise ValueError("Belge numarası 50 karakteri aşamaz.")
        if tarih > date.today():
            raise ValueError("Açılış tarihi gelecek bir tarih olamaz.")
        with get_session() as session:
            cari = session.get(Cari, cari_id)
            if cari is None:
                raise ValueError("Cari bulunamadı.")
            mevcut = session.scalar(select(CariIslem).where(CariIslem.belge_no == belge))
            if mevcut is not None:
                raise ValueError(f"Belge no zaten var: {belge}")
            from database.acik_kalem_service import AcikKalemService

            if borc_t > 0:
                AcikKalemService.borc_etkisi(session, cari_id, borc_t, belge_no=belge, tarih=tarih)
            else:
                AcikKalemService.alacak_etkisi(
                    session, cari_id, alacak_t, belge_no=belge, tarih=tarih, kaynak_tur="DEVIR"
                )
            islem = CariIslem(
                cari_id=cari_id,
                tarih=tarih,
                islem_turu="Açılış",
                belge_no=belge,
                aciklama=aciklama or "Açılış / dönem devir",
                borc=borc_t,
                alacak=alacak_t,
            )
            session.add(islem)
            session.flush()
            return islem

    @staticmethod
    def acilis_bakiyesi_ekle(
        cari_id: int,
        tarih: date,
        *,
        tutar,
        yon: str,
        belge_no: str,
        aciklama: str | None = None,
        avans_onayli: bool = False,
    ):
        """Açılış bakiyesini anlamıyla yazar. ``yon`` firma defterine göre: B cari borçlu, A cari alacaklı.

        Tedarikçide A (borcumuz) açık borç kalemi olur, ödemeler bunu kapatır; B yalnız ``avans_onayli``
        ise 159 avans sayılır. Dönüş: (cari hareketi, AcilisAnlami).
        """
        from database.cari_acilis_anlam import AVANS_ETIKETI, acilis_anlami

        with get_session() as session:
            cari = session.get(Cari, cari_id)
            if cari is None:
                raise ValueError("Cari bulunamadı.")
            cari_turu = cari.cari_turu
        anlam = acilis_anlami(cari_turu, yon, avans_onayli=avans_onayli)
        tutar_t = CariService._tutar(tutar)
        if not isinstance(tutar_t, Decimal):
            tutar_t = Decimal(str(tutar_t))
        metin = aciklama or "Açılış / dönem devir"
        if anlam.hesap_anahtari == "verilen_siparis_avanslari":
            metin = f"{metin} {AVANS_ETIKETI}"
        islem = CariService.acilis_fisi_ekle(
            cari_id,
            tarih,
            borc=tutar_t if anlam.kalem_borc else Decimal("0"),
            alacak=Decimal("0") if anlam.kalem_borc else tutar_t,
            belge_no=belge_no,
            aciklama=metin,
        )
        return islem, anlam

    @staticmethod
    def _acilis_bagli_odeme_engeli(session, cari_id: int, belge_no: str) -> str | None:
        """Bu açılış/devir kalemine dışarıdan yapılan tahsis varsa önce onları kaldır."""
        from database.models.cari import CariKapatma, SatisHareketi

        hedefler = list(
            session.scalars(
                select(SatisHareketi.id).where(
                    SatisHareketi.cari_id == int(cari_id),
                    SatisHareketi.belge_no == belge_no,
                )
            ).all()
        )
        if not hedefler:
            return None
        kayitlar = list(
            session.scalars(
                select(CariKapatma).where(
                    CariKapatma.cari_id == int(cari_id),
                    CariKapatma.hedef_hareket_id.in_(hedefler),
                    CariKapatma.iptal.is_(False),
                )
            ).all()
        )
        disaridan = []
        for k in kayitlar:
            kaynak = (k.kaynak_belge_no or "").strip()
            if kaynak and kaynak != belge_no:
                disaridan.append(kaynak)
        if not disaridan:
            return None
        benzersiz = sorted(set(disaridan))
        liste = ", ".join(benzersiz[:8])
        fazla = f" (+{len(benzersiz) - 8})" if len(benzersiz) > 8 else ""
        return (
            f"Bu fişe bağlı ödeme/tahsilat var. Önce şu belgeleri iptal veya mahsup geri alın: "
            f"{liste}{fazla}."
        )

    @staticmethod
    def acilis_fisi_getir(belge_no: str | None = None, *, islem_id: int | None = None) -> dict | None:
        """Devir/açılış fişi ekranı için düz kayıt."""
        belge = (belge_no or "").strip()
        with get_session() as session:
            if islem_id is not None:
                islem = session.get(CariIslem, int(islem_id))
            elif belge:
                islem = session.scalar(select(CariIslem).where(CariIslem.belge_no == belge))
            else:
                return None
            if islem is None:
                return None
            tur = (islem.islem_turu or "").strip().casefold()
            if tur not in {"açılış", "acilis", "devir"} and not (islem.belge_no or "").upper().startswith(
                ("EVB-ACL-", "EVB-AK-", "EVB-DEVIR")
            ):
                # Yine de özet bakiye kaydı olabilir
                if tur not in {"açılış", "acilis", "devir"}:
                    pass
            cari = session.get(Cari, int(islem.cari_id)) if islem.cari_id else None
            return {
                "id": int(islem.id),
                "cari_id": int(islem.cari_id),
                "cari_kodu": cari.cari_kodu if cari else "",
                "cari_unvan": cari.unvan if cari else "",
                "tarih": islem.tarih,
                "belge_no": islem.belge_no or "",
                "islem_turu": islem.islem_turu or "Açılış",
                "aciklama": islem.aciklama or "",
                "borc": Decimal(str(islem.borc or 0)),
                "alacak": Decimal(str(islem.alacak or 0)),
                "hesap_adi": islem.hesap_adi or "",
            }

    @staticmethod
    def acilis_fisi_guncelle(
        islem_id: int,
        *,
        tarih: date | None = None,
        borc=None,
        alacak=None,
        aciklama: str | None = None,
        cari_id: int | None = None,
    ) -> dict:
        """Açılış/devir fişini tek transaction'da günceller; açık kalem ve bakiye yenilenir."""
        yazma_zorunlu("cari_duzenleme", mesaj="Açılış fişi güncellemek için cari düzenleme yetkisi gerekir.")
        from database.acik_kalem_service import AcikKalemService
        from database.muhasebe_service import kapali_donem_zorunlu_degil

        with get_session() as session:
            islem = session.get(CariIslem, int(islem_id))
            if islem is None:
                raise ValueError("Açılış fişi bulunamadı.")
            belge = (islem.belge_no or "").strip()
            engel = CariService._acilis_bagli_odeme_engeli(session, int(islem.cari_id), belge)
            if engel:
                raise ValueError(engel)
            yeni_cari = int(cari_id) if cari_id is not None else int(islem.cari_id)
            if session.get(Cari, yeni_cari) is None:
                raise ValueError("Cari bulunamadı.")
            borc_t = CariService._tutar(borc if borc is not None else islem.borc)
            alacak_t = CariService._tutar(alacak if alacak is not None else islem.alacak)
            if not isinstance(borc_t, Decimal):
                borc_t = Decimal(str(borc_t))
            if not isinstance(alacak_t, Decimal):
                alacak_t = Decimal(str(alacak_t))
            borc_t = borc_t.quantize(Decimal("0.01"))
            alacak_t = alacak_t.quantize(Decimal("0.01"))
            if borc_t < 0 or alacak_t < 0:
                raise ValueError("Açılış tutarları negatif olamaz.")
            if (borc_t > 0) == (alacak_t > 0):
                raise ValueError("Açılış fişinde yalnızca borç veya yalnızca alacak olmalıdır.")
            yeni_tarih = tarih or islem.tarih
            if isinstance(yeni_tarih, datetime):
                yeni_tarih = yeni_tarih.date()
            if yeni_tarih > date.today():
                raise ValueError("Açılış tarihi gelecek bir tarih olamaz.")
            kapali_donem_zorunlu_degil(session, islem.tarih, "Açılış fişi")
            kapali_donem_zorunlu_degil(session, yeni_tarih, "Açılış fişi")
            eski_cari = int(islem.cari_id)
            AcikKalemService.belge_kalemlerini_sil(
                session, belge, eski_cari, neden=f"Açılış fişi güncelleme {belge}"
            )
            if borc_t > 0:
                AcikKalemService.borc_etkisi(
                    session, yeni_cari, borc_t, belge_no=belge, tarih=yeni_tarih
                )
            else:
                AcikKalemService.alacak_etkisi(
                    session, yeni_cari, alacak_t, belge_no=belge, tarih=yeni_tarih, kaynak_tur="DEVIR"
                )
            islem.cari_id = yeni_cari
            islem.tarih = yeni_tarih
            islem.borc = borc_t
            islem.alacak = alacak_t
            if aciklama is not None:
                islem.aciklama = (aciklama or "")[:500] or None
            if not (islem.islem_turu or "").strip():
                islem.islem_turu = "Açılış"
            session.flush()
            return {
                "id": int(islem.id),
                "belge_no": belge,
                "cari_id": yeni_cari,
                "borc": borc_t,
                "alacak": alacak_t,
            }

    @staticmethod
    def acilis_fisi_sil(islem_id: int, *, neden: str | None = None) -> None:
        """Açılış/devir fişini ve bağlı açık kalem etkilerini tek transaction'da siler."""
        yazma_zorunlu("cari_duzenleme", "iptal", mesaj="Açılış fişi silmek için cari düzenleme yetkisi gerekir.")
        from database.acik_kalem_service import AcikKalemService
        from database.deleted_record_service import AuditDeleteService
        from database.evo_belge_engel_service import evo_belge_engel_yaz
        from database.muhasebe_service import kapali_donem_zorunlu_degil

        neden_t = (neden or "Açılış fişi silindi").strip() or "Açılış fişi silindi"
        AuditDeleteService.schema_hazirla()
        with get_session() as session:
            islem = session.get(CariIslem, int(islem_id))
            if islem is None:
                raise ValueError("Açılış fişi bulunamadı; zaten silinmiş olabilir.")
            belge = (islem.belge_no or "").strip()
            engel = CariService._acilis_bagli_odeme_engeli(session, int(islem.cari_id), belge)
            if engel:
                raise ValueError(engel)
            kapali_donem_zorunlu_degil(session, islem.tarih, "Açılış fişi")
            cari_id = int(islem.cari_id)
            tutar = Decimal(str(islem.borc or 0)) + Decimal(str(islem.alacak or 0))
            tur_etiket = islem.islem_turu or "Açılış"
            snap = {
                "entity": {
                    "belge_no": belge,
                    "cari_id": cari_id,
                    "tarih": str(islem.tarih),
                    "borc": str(islem.borc),
                    "alacak": str(islem.alacak),
                    "aciklama": islem.aciklama,
                }
            }
            AcikKalemService.belge_kalemlerini_sil(
                session, belge, cari_id, neden=neden_t
            )
            if belge.upper().startswith("EVB-"):
                evo_belge_engel_yaz(
                    session,
                    belge_no=belge,
                    belge_turu=tur_etiket,
                    neden=neden_t,
                )
            session.delete(islem)
            session.flush()
            AuditDeleteService.log_cancel_snapshot(
                "cari_acilis_fisi",
                belge,
                reason=neden_t,
                note="Açılış/devir fişi silindi",
                snapshot=snap,
                record_code=belge,
                amount=tutar,
                module="cari",
                session=session,
            )

    @staticmethod
    def evo_cari_hareket_guncelle(
        islem_id: int,
        *,
        tarih: date | None = None,
        tutar=None,
        aciklama: str | None = None,
    ) -> dict:
        """EVB-BNC / özet tahsilat-ödeme satırını günceller (makbuz kimliği olmayan aktarım)."""
        yazma_zorunlu(
            "cari_duzenleme",
            "finans_duzenleme",
            mesaj="Evrak güncellemek için cari veya finans düzenleme yetkisi gerekir.",
        )
        from database.acik_kalem_service import AcikKalemService
        from database.muhasebe_service import kapali_donem_zorunlu_degil

        with get_session() as session:
            islem = session.get(CariIslem, int(islem_id))
            if islem is None:
                raise ValueError("Hareket bulunamadı.")
            belge = (islem.belge_no or "").strip()
            tur = (islem.islem_turu or "").strip()
            if tur.casefold() not in {"tahsilat", "ödeme", "odeme"} and not belge.upper().startswith(
                ("EVB-BNC-", "EVB-BN-", "THS-", "ODM-")
            ):
                raise ValueError("Bu hareket bu ekrandan güncellenemez.")
            # Kaynak tahsisler belge_kalemlerini_sil ile geri alınır; hedef borçlara yeniden uygulanır.
            yeni_tutar = CariService._tutar(tutar) if tutar is not None else (
                Decimal(str(islem.alacak or 0)) + Decimal(str(islem.borc or 0))
            )
            if not isinstance(yeni_tutar, Decimal):
                yeni_tutar = Decimal(str(yeni_tutar))
            yeni_tutar = yeni_tutar.quantize(Decimal("0.01"))
            if yeni_tutar <= 0:
                raise ValueError("Tutar sıfırdan büyük olmalıdır.")
            yeni_tarih = tarih or islem.tarih
            if isinstance(yeni_tarih, datetime):
                yeni_tarih = yeni_tarih.date()
            kapali_donem_zorunlu_degil(session, islem.tarih, tur or "Hareket")
            kapali_donem_zorunlu_degil(session, yeni_tarih, tur or "Hareket")
            AcikKalemService.belge_kalemlerini_sil(
                session, belge, int(islem.cari_id), neden=f"{tur} güncelleme {belge}"
            )
            tahsilat_mi = float(islem.alacak or 0) > 0 or tur.casefold() == "tahsilat"
            if tahsilat_mi:
                AcikKalemService.alacak_etkisi(
                    session,
                    int(islem.cari_id),
                    yeni_tutar,
                    belge_no=belge,
                    tarih=yeni_tarih,
                    kaynak_tur="TAHSILAT",
                )
                islem.alacak = yeni_tutar
                islem.borc = Decimal("0")
                islem.islem_turu = "Tahsilat"
            else:
                AcikKalemService.borc_etkisi(
                    session, int(islem.cari_id), yeni_tutar, belge_no=belge, tarih=yeni_tarih
                )
                islem.borc = yeni_tutar
                islem.alacak = Decimal("0")
                islem.islem_turu = "Ödeme"
            islem.tarih = yeni_tarih
            if aciklama is not None:
                islem.aciklama = (aciklama or "")[:500] or None
            session.flush()
            return {"id": int(islem.id), "belge_no": belge, "tutar": yeni_tutar}

    @staticmethod
    def evo_cari_hareket_sil(islem_id: int, *, neden: str | None = None) -> None:
        """EVB-BNC tahsilat/ödeme satırını bağlı açık kalemle birlikte siler."""
        yazma_zorunlu(
            "cari_duzenleme",
            "finans_duzenleme",
            "iptal",
            mesaj="Evrak silmek için cari veya finans düzenleme yetkisi gerekir.",
        )
        from database.acik_kalem_service import AcikKalemService
        from database.deleted_record_service import AuditDeleteService
        from database.evo_belge_engel_service import evo_belge_engel_yaz
        from database.models.finans import FinansHareketi
        from database.muhasebe_service import kapali_donem_zorunlu_degil

        neden_t = (neden or "Evo cari hareket silindi").strip() or "Evo cari hareket silindi"
        AuditDeleteService.schema_hazirla()
        with get_session() as session:
            islem = session.get(CariIslem, int(islem_id))
            if islem is None:
                raise ValueError("Hareket bulunamadı; zaten silinmiş olabilir.")
            belge = (islem.belge_no or "").strip()
            kapali_donem_zorunlu_degil(session, islem.tarih, islem.islem_turu or "Hareket")
            # Eş banka hareketi EVB-BN-{aid}
            bn_belge = None
            if belge.upper().startswith("EVB-BNC-"):
                bn_belge = "EVB-BN-" + belge.split("-", 2)[-1]
            snap = {
                "entity": {
                    "belge_no": belge,
                    "cari_id": islem.cari_id,
                    "tarih": str(islem.tarih),
                    "borc": str(islem.borc),
                    "alacak": str(islem.alacak),
                },
                "related": [],
            }
            AcikKalemService.belge_kalemlerini_sil(
                session, belge, int(islem.cari_id), neden=neden_t
            )
            if bn_belge:
                for h in session.scalars(
                    select(FinansHareketi).where(FinansHareketi.belge_no == bn_belge)
                ).all():
                    snap["related"].append(
                        {"type": "finans_hareketi", "id": h.id, "belge_no": bn_belge}
                    )
                    session.delete(h)
                evo_belge_engel_yaz(
                    session, belge_no=bn_belge, belge_turu="Banka", neden=neden_t
                )
            if belge.upper().startswith("EVB-"):
                evo_belge_engel_yaz(
                    session,
                    belge_no=belge,
                    belge_turu=islem.islem_turu or "Tahsilat/Ödeme",
                    neden=neden_t,
                )
            tutar = Decimal(str(islem.borc or 0)) + Decimal(str(islem.alacak or 0))
            session.delete(islem)
            session.flush()
            AuditDeleteService.log_cancel_snapshot(
                "evo_cari_hareket",
                belge,
                reason=neden_t,
                note="Evo tahsilat/ödeme silindi",
                snapshot=snap,
                record_code=belge,
                amount=tutar,
                module="cari",
                session=session,
            )

    @staticmethod
    def acilis_muhasebe_onizleme(cari_id: int | None = None) -> list[dict[str, Any]]:
        """Açılış cari hareketlerinin muhasebe karşılığı. Belirsiz olan 'İnceleme gerekiyor' döner;
        açılış hareketinden otomatik fiş üretilmez."""
        from database.cari_acilis_anlam import kayitli_acilis_anlami

        with get_session() as session:
            q = select(CariIslem, Cari).join(Cari, Cari.id == CariIslem.cari_id).where(
                CariIslem.islem_turu == "Açılış")
            if cari_id is not None:
                q = q.where(CariIslem.cari_id == int(cari_id))
            sonuc = []
            for islem, cari in session.execute(q.order_by(CariIslem.tarih, CariIslem.id)).all():
                anlam = kayitli_acilis_anlami(cari.cari_turu, islem.borc, islem.alacak, islem.aciklama)
                sonuc.append({
                    "islem_id": int(islem.id), "cari_id": int(cari.id), "cari_kodu": cari.cari_kodu,
                    "cari_turu": cari.cari_turu, "belge_no": islem.belge_no, "tarih": islem.tarih,
                    "tutar": Decimal(str(islem.borc or 0)) + Decimal(str(islem.alacak or 0)),
                    "yon": anlam.yon, "hesap_anahtari": anlam.hesap_anahtari, "hesap_kodu": anlam.hesap_kodu,
                    "muhasebe_yonu": anlam.muhasebe_yonu, "durum": anlam.durum, "aciklama": anlam.aciklama,
                })
            return sonuc

    @staticmethod
    def islem_belge_var_mi(belge_no: str) -> bool:
        belge = (belge_no or "").strip()
        if not belge:
            return False
        with get_session() as session:
            return (
                session.scalar(select(CariIslem.id).where(CariIslem.belge_no == belge))
                is not None
            )

    @staticmethod
    def gelir_gider_fisi_ekle(
        cari_id: int,
        tarih: date,
        *,
        tur: str,
        tutar,
        belge_no: str,
        aciklama: str | None = None,
        kalan_acik=None,
        kapatilan=None,
    ) -> CariIslem:
        """EvoBulut Gelir/Gider kaydını cari deftere yazar.

        Gelir (41): cari borçlu → borc + SatisHareketi (açık = kalan_acik).
        Gider (40): cari alacaklı → alacak; kapama borc satırı ile kapatılır.
        """
        tutar_t = tutar if isinstance(tutar, Decimal) else CariService._tutar(tutar)
        if not isinstance(tutar_t, Decimal):
            tutar_t = Decimal(str(tutar_t))
        tutar_t = tutar_t.quantize(Decimal("0.01"))
        if tutar_t <= 0:
            raise ValueError("Gelir/Gider tutarı pozitif olmalıdır.")
        tur_u = (tur or "").strip().upper()
        if tur_u not in {"GELIR", "GIDER"}:
            raise ValueError("Tür GELIR veya GIDER olmalıdır.")
        belge = (belge_no or "").strip()
        if not belge:
            raise ValueError("Belge numarası zorunludur.")
        if len(belge) > 50:
            raise ValueError("Belge numarası 50 karakteri aşamaz.")
        if tarih > date.today():
            raise ValueError("İşlem tarihi gelecek bir tarih olamaz.")

        kalan_t = None
        if kalan_acik is not None:
            kalan_t = (
                kalan_acik
                if isinstance(kalan_acik, Decimal)
                else CariService._tutar(kalan_acik)
            )
            if not isinstance(kalan_t, Decimal):
                kalan_t = Decimal(str(kalan_t))
            kalan_t = max(Decimal("0"), kalan_t.quantize(Decimal("0.01")))

        kapat_t = Decimal("0")
        if kapatilan is not None:
            kapat_t = (
                kapatilan
                if isinstance(kapatilan, Decimal)
                else CariService._tutar(kapatilan)
            )
            if not isinstance(kapat_t, Decimal):
                kapat_t = Decimal(str(kapat_t))
            kapat_t = max(Decimal("0"), kapat_t.quantize(Decimal("0.01")))

        with get_session() as session:
            cari = session.get(Cari, cari_id)
            if cari is None:
                raise ValueError("Cari bulunamadı.")
            mevcut = session.scalar(select(CariIslem).where(CariIslem.belge_no == belge))
            if mevcut is not None:
                raise ValueError(f"Belge no zaten var: {belge}")

            if tur_u == "GELIR":
                acik = kalan_t if kalan_t is not None else tutar_t
                if acik > tutar_t:
                    acik = tutar_t
                session.add(
                    SatisHareketi(
                        cari_id=cari_id,
                        satis_tarihi=tarih,
                        belge_no=belge,
                        satis_tutari=tutar_t,
                        kalan_acik_tutar=acik,
                    )
                )
                from database.acik_kalem_service import AcikKalemService

                AcikKalemService.avanslari_uygula(session, cari_id, para_birimi="TRY")
                islem = CariIslem(
                    cari_id=cari_id,
                    tarih=tarih,
                    islem_turu="Gelir",
                    belge_no=belge,
                    aciklama=aciklama or "Gelir",
                    borc=tutar_t,
                    alacak=Decimal("0"),
                )
                session.add(islem)
                if kapat_t > 0:
                    kap_no = f"EVB-GGK-{belge.split('-')[-1]}"[:50]
                    if kap_no == belge:
                        kap_no = f"{belge}-K"[:50]
                    if session.scalar(select(CariIslem.id).where(CariIslem.belge_no == kap_no)) is None:
                        CariService._alacak_uygula(
                            session, cari_id, kapat_t, kap_no, tarih, kaynak_tur="GELIR_KAPAMA"
                        )
                        session.add(
                            CariIslem(
                                cari_id=cari_id,
                                tarih=tarih,
                                islem_turu="Gelir Kapama",
                                belge_no=kap_no,
                                aciklama=(aciklama or "Gelir") + " (kapama)",
                                borc=Decimal("0"),
                                alacak=kapat_t,
                            )
                        )
            else:
                islem = CariIslem(
                    cari_id=cari_id,
                    tarih=tarih,
                    islem_turu="Gider",
                    belge_no=belge,
                    aciklama=aciklama or "Gider",
                    borc=Decimal("0"),
                    alacak=tutar_t,
                )
                session.add(islem)
                from database.acik_kalem_service import AcikKalemService

                acik_alacak = tutar_t - min(kapat_t, tutar_t)
                if acik_alacak > 0:
                    AcikKalemService.alacak_etkisi(
                        session, cari_id, acik_alacak, belge_no=belge, tarih=tarih, kaynak_tur="GIDER"
                    )
                if kapat_t > 0:
                    kap_no = f"EVB-GGK-{belge.split('-')[-1]}"[:50]
                    if kap_no == belge:
                        kap_no = f"{belge}-K"[:50]
                    if session.scalar(select(CariIslem.id).where(CariIslem.belge_no == kap_no)) is None:
                        session.add(
                            CariIslem(
                                cari_id=cari_id,
                                tarih=tarih,
                                islem_turu="Gider Kapama",
                                belge_no=kap_no,
                                aciklama=(aciklama or "Gider") + " (kapama)",
                                borc=kapat_t,
                                alacak=Decimal("0"),
                            )
                        )
            session.flush()
            return islem

    @staticmethod
    def virman_yap(
        kaynak_id: int,
        hedef_id: int,
        tarih: date,
        tutar,
        aciklama: str | None = None,
        belge_no: str | None = None,
    ) -> tuple[CariIslem, CariIslem]:
        tutar = CariService._tutar(tutar)
        if tutar <= 0:
            raise ValueError("Virman tutarı pozitif olmalıdır.")
        if kaynak_id == hedef_id:
            raise ValueError("Kaynak ve hedef cari aynı olamaz.")
        if tarih > date.today():
            raise ValueError("Virman tarihi gelecek bir tarih olamaz.")
        with get_session() as session:
            kaynak = session.get(Cari, kaynak_id)
            hedef = session.get(Cari, hedef_id)
            if kaynak is None or hedef is None:
                raise ValueError("Kaynak veya hedef cari bulunamadı.")
            if belge_no:
                belgeno = belge_no.strip()
                if not belgeno:
                    raise ValueError("Belge numarası boş olamaz.")
                if len(belgeno) > 50:
                    raise ValueError("Belge numarası 50 karakteri aşamaz.")
                if session.scalar(select(CariIslem.id).where(CariIslem.belge_no == belgeno)):
                    raise ValueError(f"Belge no zaten var: {belgeno}")
            else:
                belgeno = CariService._belge_no(session, "VRM")
            # Çift kayıt: kaynak ALACAK, karşı cari (hedef) aynı tutarda BORÇ
            # Açık bakiye şartı yok; varsa FIFO uygulanır, yoksa yalnızca cari işlem yazılır.
            from database.acik_kalem_service import AcikKalemService

            CariService._alacak_uygula(session, kaynak_id, tutar, belgeno, tarih, kaynak_tur="VIRMAN")
            AcikKalemService.borc_etkisi(session, hedef_id, tutar, belge_no=belgeno, tarih=tarih)
            kaynak_islem = CariIslem(
                cari_id=kaynak_id, tarih=tarih, islem_turu="Cari Virman", belge_no=belgeno,
                aciklama=aciklama or f"Alacak → borç: {hedef.cari_kodu} {hedef.unvan}",
                borc=Decimal("0"), alacak=tutar,
                karsi_cari_id=hedef_id,
            )
            hedef_islem = CariIslem(
                cari_id=hedef_id, tarih=tarih, islem_turu="Cari Virman", belge_no=belgeno,
                aciklama=aciklama or f"Borç ← alacak: {kaynak.cari_kodu} {kaynak.unvan}",
                borc=tutar, alacak=Decimal("0"),
                karsi_cari_id=kaynak_id,
            )
            session.add(kaynak_islem)
            session.add(hedef_islem)
            session.flush()
            from database.finans_evrak_kimligi import EVRAK_CARI_VIRMAN, kimlik_al
            from database.muhasebe_entegrasyon import muhasebe_hook

            muhasebe_hook("cari_virman_fisi", kimlik_al(session, EVRAK_CARI_VIRMAN, belgeno), session=session)
            return kaynak_islem, hedef_islem

    @staticmethod
    def virman_listele(arama: str = "") -> list[dict[str, Any]]:
        """Cari virman fişlerini belge no bazında listeler (kaynak alacak satırı üzerinden)."""
        arama = arama.strip()
        with get_session() as session:
            islemler = session.scalars(
                select(CariIslem)
                .where(CariIslem.islem_turu == "Cari Virman", CariIslem.alacak > 0)
                .order_by(CariIslem.tarih.desc(), CariIslem.id.desc())
            ).all()
            sonuc = []
            for islem in islemler:
                kaynak = session.get(Cari, islem.cari_id)
                hedef = session.get(Cari, islem.karsi_cari_id) if islem.karsi_cari_id else None
                kayit = {
                    "belge_no": islem.belge_no,
                    "tarih": islem.tarih,
                    "tutar": islem.alacak,
                    "aciklama": islem.aciklama or "",
                    "kaynak_id": islem.cari_id,
                    "hedef_id": islem.karsi_cari_id,
                    "kaynak_kodu": kaynak.cari_kodu if kaynak else "",
                    "kaynak_unvan": kaynak.unvan if kaynak else "",
                    "hedef_kodu": hedef.cari_kodu if hedef else "",
                    "hedef_unvan": hedef.unvan if hedef else "",
                }
                if arama:
                    ifade = turkce_normalize(arama)
                    metin = turkce_normalize(" ".join([
                        kayit["belge_no"], kayit["kaynak_kodu"], kayit["kaynak_unvan"],
                        kayit["hedef_kodu"], kayit["hedef_unvan"], kayit["aciklama"],
                    ]))
                    if ifade not in metin:
                        continue
                sonuc.append(kayit)
            return sonuc

    @staticmethod
    def virman_getir(belge_no: str) -> dict[str, Any]:
        """Cari virman fişini belge no ile getirir (kaynak/hedef cari işlem id'leriyle)."""
        belge_no = (belge_no or "").strip()
        if not belge_no.startswith("VRM-"):
            raise ValueError("Geçersiz virman belge numarası.")
        with get_session() as session:
            islemler = session.scalars(
                select(CariIslem).where(
                    CariIslem.belge_no == belge_no,
                    CariIslem.islem_turu == "Cari Virman",
                )
            ).all()
            if not islemler:
                raise ValueError("Virman fişi bulunamadı.")
            kaynak_islem = next((i for i in islemler if i.alacak > 0), None)
            hedef_islem = next((i for i in islemler if i.borc > 0), None)
            if kaynak_islem is None or hedef_islem is None:
                raise ValueError("Virman fişi eksik kayıtlı.")
            kaynak = session.get(Cari, kaynak_islem.cari_id)
            hedef = session.get(Cari, hedef_islem.cari_id)
            return {
                "belge_no": belge_no,
                "tarih": kaynak_islem.tarih,
                "tutar": kaynak_islem.alacak,
                "aciklama": kaynak_islem.aciklama or "",
                "kaynak_id": int(kaynak_islem.cari_id),
                "hedef_id": int(hedef_islem.cari_id),
                "kaynak_islem_id": int(kaynak_islem.id),
                "hedef_islem_id": int(hedef_islem.id),
                "kaynak_kodu": kaynak.cari_kodu if kaynak else "",
                "kaynak_unvan": kaynak.unvan if kaynak else "",
                "hedef_kodu": hedef.cari_kodu if hedef else "",
                "hedef_unvan": hedef.unvan if hedef else "",
            }

    @staticmethod
    def virman_guncelle(
        belge_no: str,
        kaynak_id: int,
        hedef_id: int,
        tarih: date,
        tutar,
        aciklama: str | None = None,
    ) -> tuple[CariIslem, CariIslem]:
        """Aynı belge no ile cari virmanı tek transaction'da günceller; bakiye ve muhasebe yenilenir."""
        yazma_zorunlu(
            "cari_duzenleme",
            mesaj="Cari virman güncellemek için cari düzenleme yetkisi gerekir.",
        )
        belge_no = (belge_no or "").strip()
        if not belge_no.startswith("VRM-"):
            raise ValueError("Geçersiz virman belge numarası.")
        tutar = CariService._tutar(tutar)
        if tutar <= 0:
            raise ValueError("Virman tutarı pozitif olmalıdır.")
        if kaynak_id == hedef_id:
            raise ValueError("Kaynak ve hedef cari aynı olamaz.")
        if isinstance(tarih, datetime):
            tarih = tarih.date()
        if tarih > date.today():
            raise ValueError("Virman tarihi gelecek bir tarih olamaz.")
        with get_session() as session:
            from database.acik_kalem_service import AcikKalemService
            from database.finans_evrak_kimligi import EVRAK_CARI_VIRMAN, kimlik_al
            from database.muhasebe_entegrasyon import muhasebe_hook
            from database.muhasebe_service import kapali_donem_zorunlu_degil

            session.execute(
                update(CariIslem)
                .where(CariIslem.belge_no == belge_no, CariIslem.islem_turu == "Cari Virman")
                .values(aciklama=CariIslem.aciklama)
                .execution_options(synchronize_session=False)
            )
            islemler = session.scalars(
                select(CariIslem).where(
                    CariIslem.belge_no == belge_no,
                    CariIslem.islem_turu == "Cari Virman",
                )
            ).all()
            if not islemler:
                raise ValueError("Virman fişi bulunamadı.")
            kaynak_islem = next((i for i in islemler if i.alacak > 0), None)
            hedef_islem = next((i for i in islemler if i.borc > 0), None)
            if kaynak_islem is None or hedef_islem is None:
                raise ValueError("Virman fişi eksik kayıtlı; güncellenemez.")

            eski_kaynak_id = int(kaynak_islem.cari_id)
            eski_hedef_id = int(hedef_islem.cari_id)
            eski_tutar = Decimal(str(kaynak_islem.alacak))
            eski_tarih = kaynak_islem.tarih
            if isinstance(eski_tarih, datetime):
                eski_tarih = eski_tarih.date()

            kaynak = session.get(Cari, int(kaynak_id))
            hedef = session.get(Cari, int(hedef_id))
            if kaynak is None or hedef is None:
                raise ValueError("Kaynak veya hedef cari bulunamadı.")

            kapali_donem_zorunlu_degil(session, eski_tarih, "Cari virman")
            kapali_donem_zorunlu_degil(session, tarih, "Cari virman")

            # Eski bakiye etkisini geri al
            hedef_hareket = session.scalar(
                select(SatisHareketi).where(
                    SatisHareketi.belge_no == belge_no,
                    SatisHareketi.cari_id == eski_hedef_id,
                )
            )
            if hedef_hareket is not None:
                AcikKalemService.kalem_kaldir(
                    session, hedef_hareket, neden=f"Virman güncelleme {belge_no}"
                )
                if hedef_hareket.kalan_acik_tutar < hedef_hareket.satis_tutari:
                    raise ValueError(
                        "Hedef caride bu virman tutarının bir kısmı tahsil edilmiş; güncellenemez."
                    )
                session.delete(hedef_hareket)
                session.flush()
            CariService._aciklara_geri_al(session, eski_kaynak_id, eski_tutar, belge_no)
            session.flush()

            # Yeni etkileri uygula
            CariService._alacak_uygula(
                session, int(kaynak_id), tutar, belge_no, tarih, kaynak_tur="VIRMAN"
            )
            AcikKalemService.borc_etkisi(
                session, int(hedef_id), tutar, belge_no=belge_no, tarih=tarih
            )

            kaynak_islem.cari_id = int(kaynak_id)
            kaynak_islem.tarih = tarih
            kaynak_islem.borc = Decimal("0")
            kaynak_islem.alacak = tutar
            kaynak_islem.karsi_cari_id = int(hedef_id)
            kaynak_islem.aciklama = (
                aciklama or f"Alacak → borç: {hedef.cari_kodu} {hedef.unvan}"
            )

            hedef_islem.cari_id = int(hedef_id)
            hedef_islem.tarih = tarih
            hedef_islem.borc = tutar
            hedef_islem.alacak = Decimal("0")
            hedef_islem.karsi_cari_id = int(kaynak_id)
            hedef_islem.aciklama = (
                aciklama or f"Borç ← alacak: {kaynak.cari_kodu} {kaynak.unvan}"
            )
            session.flush()

            kimlik_id = kimlik_al(
                session, EVRAK_CARI_VIRMAN, belge_no, cari_islem_id=int(kaynak_islem.id)
            )
            muhasebe_hook(
                "cari_virman_fisi",
                kimlik_id,
                yeniden=True,
                session=session,
            )
            return kaynak_islem, hedef_islem

    @staticmethod
    def _aciklara_geri_al(
        session, cari_id: int, tutar: Decimal, belge_no: str = "", *, yalniz_borc_satirlari: bool = False
    ) -> None:
        """Belgenin kapattığı açık kalemleri geri açar.

        Önce kayıtlı tahsisler (cari_kapatmalar) ve belgenin avans satırı geri alınır; tahsis kaydı
        olmayan eski belgelerde kalan tutar eski yöntemle (LIFO) açılır.
        yalniz_borc_satirlari: başka belgelerin alacak (satış tutarı 0, eksi kalan) satırlarına dokunmaz.
        """
        from database.acik_kalem_service import AcikKalemService

        kalan = Decimal(str(tutar))
        if belge_no:
            kayitli = AcikKalemService.belge_kayitli_mi(session, cari_id, belge_no)
            kalan -= AcikKalemService.belge_geri_al(session, cari_id, belge_no, kalan)
            if kayitli or kalan <= 0:
                return
        # Eski (tahsis kaydı olmayan) belge: yalnız belge kalemlerinin kayıtsız kapanmış kısmı açılır.
        hareketler = session.scalars(
            select(SatisHareketi)
            .where(
                SatisHareketi.cari_id == cari_id,
                SatisHareketi.satis_tutari > 0,
                SatisHareketi.kalan_acik_tutar < SatisHareketi.satis_tutari,
            )
            .order_by(SatisHareketi.satis_tarihi.desc(), SatisHareketi.id.desc())
        ).all()
        for hareket in hareketler:
            if kalan <= 0:
                break
            if hareket.belge_no.startswith(("ODM-", "VRM-", "KKC-", "THS-")):
                continue
            kapasite = (
                Decimal(str(hareket.satis_tutari))
                - Decimal(str(hareket.kalan_acik_tutar))
                - AcikKalemService.kalem_kapanan(session, hareket.id)
            )
            if kapasite <= 0:
                continue
            eklenecek = min(kapasite, kalan)
            hareket.kalan_acik_tutar = Decimal(str(hareket.kalan_acik_tutar)) + eklenecek
            kalan -= eklenecek
            AcikKalemService.belge_senkron(session, hareket, -eklenecek)
        if kalan > 0:
            session.add(SatisHareketi(
                cari_id=cari_id,
                satis_tarihi=date.today(),
                belge_no=f"IPT-{belge_no}" if belge_no else f"IPT-VRM-{cari_id}",
                satis_tutari=kalan,
                kalan_acik_tutar=kalan,
            ))

    @staticmethod
    def islemler_belge_no_ile(belge_no: str) -> list:
        """Belge numarasına bağlı cari işlem(ler); cari ilişkisi yüklü."""
        belge_no = (belge_no or "").strip()
        if not belge_no:
            return []
        with get_session() as session:
            islemler = list(
                session.scalars(
                    select(CariIslem)
                    .options(selectinload(CariIslem.cari))
                    .where(CariIslem.belge_no == belge_no)
                    .order_by(CariIslem.id)
                ).all()
            )
            return islemler

    @staticmethod
    def virman_iptal(belge_no: str) -> None:
        yazma_zorunlu(
            "cari_duzenleme",
            "iptal",
            mesaj="Cari virman silmek için cari düzenleme ve iptal yetkisi gerekir.",
        )
        belge_no = (belge_no or "").strip()
        if not belge_no.startswith("VRM-"):
            raise ValueError("Geçersiz virman belge numarası.")
        with get_session() as session:
            # Yazma kilidiyle sahiplen: eş zamanlı ikinci iptal bekler, sonra hareket bulamaz
            session.execute(
                update(CariIslem)
                .where(CariIslem.belge_no == belge_no, CariIslem.islem_turu == "Cari Virman")
                .values(aciklama=CariIslem.aciklama).execution_options(synchronize_session=False)
            )
            islemler = session.scalars(
                select(CariIslem).where(
                    CariIslem.belge_no == belge_no,
                    CariIslem.islem_turu == "Cari Virman",
                )
            ).all()
            if not islemler:
                raise ValueError("Virman fişi bulunamadı.")
            kaynak_islem = next((i for i in islemler if i.alacak > 0), None)
            hedef_islem = next((i for i in islemler if i.borc > 0), None)
            if kaynak_islem is None or hedef_islem is None:
                raise ValueError("Virman fişi eksik kayıtlı; iptal edilemez.")
            from database.finans_evrak_kimligi import EVRAK_CARI_VIRMAN, kimlik_bul
            from database.muhasebe_entegrasyon import muhasebe_hook
            from database.muhasebe_service import kapali_donem_zorunlu_degil

            kimlik = kimlik_bul(session, EVRAK_CARI_VIRMAN, belge_no)
            if kimlik is not None:
                kapali_donem_zorunlu_degil(session, kaynak_islem.tarih, "Cari virman")
                muhasebe_hook("cari_virman_iptal", int(kimlik.id), f"Cari virman iptal {belge_no}", session=session)
            tutar = kaynak_islem.alacak
            hedef_hareket = session.scalar(
                select(SatisHareketi).where(
                    SatisHareketi.belge_no == belge_no,
                    SatisHareketi.cari_id == hedef_islem.cari_id,
                )
            )
            if hedef_hareket is not None:
                from database.acik_kalem_service import AcikKalemService

                AcikKalemService.kalem_kaldir(session, hedef_hareket, neden=f"Virman iptal {belge_no}")
                if hedef_hareket.kalan_acik_tutar < hedef_hareket.satis_tutari:
                    raise ValueError(
                        "Hedef caride bu virman tutarının bir kısmı tahsil edilmiş; iptal edilemez."
                    )
                session.delete(hedef_hareket)
                session.flush()
            CariService._aciklara_geri_al(session, kaynak_islem.cari_id, tutar, belge_no)
            snap = {
                "entity": {"belge_no": belge_no, "tutar": str(tutar)},
                "related": [
                    {
                        "type": "cari_islem",
                        "id": i.id,
                        "cari_id": i.cari_id,
                        "borc": str(i.borc),
                        "alacak": str(i.alacak),
                    }
                    for i in islemler
                ],
            }
            for islem in islemler:
                session.delete(islem)
            session.flush()
        from database.deleted_record_service import (
            ENTITY_CARI_VIRMAN,
            safe_log_cancel_snapshot,
        )

        safe_log_cancel_snapshot(
            ENTITY_CARI_VIRMAN,
            belge_no,
            note="Cari virman iptal",
            snapshot=snap,
            record_code=belge_no,
            record_title=f"Cari virman {belge_no}",
            amount=tutar,
            module="cari",
        )

    @staticmethod
    def kk_cekimi_yap(musteri_id: int, tedarikci_id: int, tarih: date, tutar, hesap_adi: str, aciklama: str | None = None) -> tuple[CariIslem, CariIslem]:
        """Geriye dönük uyumluluk: yeni KkCekimiService.kaydet kullanılır."""
        from database.kk_cekimi_service import KkCekimiService
        fis = KkCekimiService.kaydet(
            musteri_id, tedarikci_id, tarih, tutar,
            banka=hesap_adi or "Belirtilmedi",
            taksit_sayisi=1,
            aciklama=aciklama,
        )
        with get_session() as session:
            islemler = session.scalars(
                select(CariIslem).where(CariIslem.belge_no == fis["belge_no"])
            ).all()
            musteri_islem = next(i for i in islemler if i.alacak > 0)
            tedarikci_islem = next(i for i in islemler if i.borc > 0)
            return musteri_islem, tedarikci_islem

    @staticmethod
    def aktif_cariler(cari_turu: str | None = None) -> list[Cari]:
        with get_session() as session:
            statement = select(Cari).where(
                Cari.aktif.is_(True),
                or_(Cari.is_deleted.is_(False), Cari.is_deleted.is_(None)),
            ).order_by(Cari.cari_kodu)
            if cari_turu:
                statement = CariService._cari_turu_filtresi(statement, cari_turu)
            return list(session.scalars(statement).all())

    @staticmethod
    def aktif_evrak_carileri() -> list[Cari]:
        """Satış/alış belge seçici: tüm aktif gerçek cari türleri (tür kısıtı yok)."""
        with get_session() as session:
            statement = select(Cari).where(
                Cari.aktif.is_(True),
                or_(Cari.is_deleted.is_(False), Cari.is_deleted.is_(None)),
            )
            statement = CariService._cari_turu_filtresi(statement, "EVRAK")
            statement = statement.order_by(Cari.unvan, Cari.cari_kodu)
            return list(session.scalars(statement).all())

    @staticmethod
    def aktif_tedarikciler() -> list[Cari]:
        return CariService.aktif_cariler(cari_turu="Tedarikçi")

    @staticmethod
    def aktif_musteriler() -> list[Cari]:
        with get_session() as session:
            statement = select(Cari).where(
                Cari.aktif.is_(True),
                or_(Cari.is_deleted.is_(False), Cari.is_deleted.is_(None)),
            )
            statement = CariService._cari_turu_filtresi(statement, "Müşteri")
            statement = statement.order_by(Cari.unvan, Cari.cari_kodu)
            return list(session.scalars(statement).all())

    @staticmethod
    def musteri_ara_hizli(
        arama: str = "", *, limit: int = 50, sadece_aktif: bool = True
    ) -> list[dict[str, Any]]:
        """Belge cari araması — tüm gerçek cari türleri (çoklu blok, SearchService)."""
        from database.search_service import SearchService, tokenize_query

        ara = (arama or "").strip()
        if not ara:
            return []
        if not tokenize_query(ara):
            return []
        return SearchService.search_customers(
            ara, limit=limit, cari_turu="EVRAK", sadece_aktif=sadece_aktif
        )

    @staticmethod
    def unvan_ara(
        arama: str = "",
        *,
        cari_turu: str | None = None,
        limit: int = 50,
        haric_id: int | None = None,
    ) -> list[Cari]:
        """Ünvanın herhangi bir yerinde geçen cariler (Türkçe / büyük-küçük duyarsız).

        2 karakterden kısa sorguda veritabanına gidilmez.
        """
        from database.sqlite_funcs import tr_icerir

        ara = (arama or "").strip()
        if len(ara) < 2:
            return []
        limit = max(1, min(int(limit or 50), 200))
        with get_session() as session:
            statement = select(Cari).where(
                tr_icerir(Cari.unvan, ara),
                or_(Cari.is_deleted.is_(False), Cari.is_deleted.is_(None)),
            )
            statement = CariService._cari_turu_filtresi(statement, cari_turu)
            if haric_id:
                statement = statement.where(Cari.id != int(haric_id))
            statement = statement.order_by(Cari.unvan).limit(limit)
            return list(session.scalars(statement).all())

    @staticmethod
    def tedarikci_ara_hizli(arama: str = "", *, limit: int = 50) -> list[dict[str, Any]]:
        """Satın alma tedarikçi araması — çoklu blok, sıra bağımsız."""
        from database.search_service import SearchService, tokenize_query

        ara = (arama or "").strip()
        if not ara:
            return []
        if not tokenize_query(ara):
            return []
        return SearchService.search_suppliers(ara, limit=limit)

    @staticmethod
    def musteri_bakiyeleri_toplu(cari_idler: list[int]) -> dict[int, Decimal]:
        """Seçilen cari id'leri için liste ile aynı net bakiye."""
        from database.cari_bakiye_service import liste_bakiyeleri

        return liste_bakiyeleri(cari_idler)

    @staticmethod
    def satis_raporu() -> dict[str, Any]:
        from database.models.satis_faturasi import SatisFaturasi
        from database.satis_faturasi_service import SatisFaturasiService
        from sqlalchemy.orm import selectinload

        with get_session() as session:
            faturalar = session.scalars(
                select(SatisFaturasi)
                .where(SatisFaturasi.durum != "İPTAL")
                .options(selectinload(SatisFaturasi.cari), selectinload(SatisFaturasi.satirlar))
                .order_by(SatisFaturasi.fatura_tarihi.desc())
            ).all()
            toplam_ciro = Decimal("0")
            toplam_tahsilat = Decimal("0")
            musteri_cirasi: dict[str, Decimal] = {}
            aylik: dict[str, Decimal] = {}
            satirlar = []
            for fatura in faturalar:
                genel = SatisFaturasiService.net_toplam(fatura)
                toplam_ciro += genel
                toplam_tahsilat += fatura.tahsilat_tutari or Decimal("0")
                unvan = fatura.cari.unvan if fatura.cari else "-"
                musteri_cirasi[unvan] = musteri_cirasi.get(unvan, Decimal("0")) + genel
                ay = fatura.fatura_tarihi.strftime("%Y-%m")
                aylik[ay] = aylik.get(ay, Decimal("0")) + genel
                satirlar.append({
                    "fatura_no": fatura.fatura_no,
                    "tarih": fatura.fatura_tarihi,
                    "musteri": unvan,
                    "toplam": genel,
                    "tahsilat": fatura.tahsilat_tutari or Decimal("0"),
                    "kalan": genel - (fatura.tahsilat_tutari or Decimal("0")),
                    "durum": fatura.durum,
                })
            acik_bakiye = sum(
                (h.kalan_acik_tutar for h in session.scalars(select(SatisHareketi)).all()),
                Decimal("0"),
            )
            top_musteriler = sorted(musteri_cirasi.items(), key=lambda x: x[1], reverse=True)[:10]
            return {
                "toplam_ciro": toplam_ciro,
                "toplam_tahsilat": toplam_tahsilat,
                "acik_bakiye": acik_bakiye,
                "fatura_sayisi": len(faturalar),
                "aylik": sorted(aylik.items()),
                "top_musteriler": top_musteriler,
                "satirlar": satirlar,
            }

    @staticmethod
    def tahsilat_odeme_raporu() -> dict[str, Any]:
        """Cari hareketlerden tahsilat (alacak) ve ödeme (borç) raporları."""
        with get_session() as session:
            islemler = session.scalars(
                select(CariIslem).order_by(CariIslem.tarih.desc(), CariIslem.id.desc())
            ).all()
            tahsilatlar = []
            odemeler = []
            toplam_tahsilat = Decimal("0")
            toplam_odeme = Decimal("0")
            for islem in islemler:
                cari = session.get(Cari, islem.cari_id)
                karsi = session.get(Cari, islem.karsi_cari_id) if islem.karsi_cari_id else None
                kayit = {
                    "tarih": islem.tarih,
                    "tur": islem.islem_turu,
                    "belge_no": islem.belge_no,
                    "cari_kodu": cari.cari_kodu if cari else "",
                    "cari_unvan": cari.unvan if cari else "",
                    "karsi_kodu": karsi.cari_kodu if karsi else "",
                    "karsi_unvan": karsi.unvan if karsi else "",
                    "hesap": islem.hesap_adi or "",
                    "aciklama": islem.aciklama or "",
                    "borc": islem.borc or Decimal("0"),
                    "alacak": islem.alacak or Decimal("0"),
                }
                if kayit["alacak"] > 0:
                    tahsilatlar.append(kayit)
                    toplam_tahsilat += kayit["alacak"]
                if kayit["borc"] > 0:
                    odemeler.append(kayit)
                    toplam_odeme += kayit["borc"]
            return {
                "tahsilatlar": tahsilatlar,
                "odemeler": odemeler,
                "toplam_tahsilat": toplam_tahsilat,
                "toplam_odeme": toplam_odeme,
                "tahsilat_sayisi": len(tahsilatlar),
                "odeme_sayisi": len(odemeler),
            }

    @staticmethod
    def sonraki_kod(cari_turu: str = "Müşteri") -> str:
        """Tür önekleri: Müşteri M, Tedarikçi T, Personel P, Resmi R, Düzenleyici D."""
        tur = (cari_turu or "").strip()
        onek_map = {
            "Tedarikçi": "T",
            "Personel": "P",
            "Resmi Kurumlar": "R",
            "Düzenleyici Hesaplar": "D",
            "Müşteri": "M",
        }
        onek = onek_map.get(tur, "M")
        with get_session() as session:
            kodlar = session.scalars(
                select(Cari.cari_kodu).where(Cari.cari_kodu.like(f"{onek}%"))
            ).all()
            max_no = 0
            for kod in kodlar:
                if not kod:
                    continue
                kuyruk = kod[1:]
                if len(kod) >= 2 and kod[0].upper() == onek and kuyruk.isdigit():
                    max_no = max(max_no, int(kuyruk))
            return f"{onek}{max_no + 1:05d}"

    @staticmethod
    def dogal_kod_anahtari(kod: str | None) -> tuple:
        """Doğal sıra: M10 > M9, M00010 > M00009; harf ve sayı parçaları ayrı karşılaştırılır."""
        import re

        parcalar = re.findall(r"\d+|\D+", (kod or "").strip().casefold())
        return tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in parcalar)

    @staticmethod
    def son_kodlar(cari_turu: str = "Müşteri", limit: int = 10) -> list[dict[str, Any]]:
        """Kod sırasının sonundaki en fazla ``limit`` cari (en büyük kod ilk); bakiyeleriyle."""
        from database.cari_bakiye_service import bakiye_bilgisi, liste_bakiyeleri

        with get_session() as session:
            sorgu = select(Cari.id, Cari.cari_kodu, Cari.unvan, Cari.aktif, Cari.cari_turu).where(
                or_(Cari.is_deleted.is_(False), Cari.is_deleted.is_(None))
            )
            sorgu = CariService._cari_turu_filtresi(sorgu, cari_turu)
            satirlar = list(session.execute(sorgu).all())
        satirlar.sort(key=lambda s: CariService.dogal_kod_anahtari(s.cari_kodu), reverse=True)
        satirlar = satirlar[: max(1, int(limit))]
        bakiyeler = liste_bakiyeleri([s.id for s in satirlar])
        return [
            {
                "id": int(s.id), "cari_kodu": s.cari_kodu or "", "unvan": s.unvan or "",
                "aktif": bool(s.aktif),
                **bakiye_bilgisi(bakiyeler.get(int(s.id), 0),
                                 tedarikci_modu=(s.cari_turu or "") == "Tedarikçi"),
            }
            for s in satirlar
        ]

    @staticmethod
    def secim_etiketleri(cari_turu: str | None = None) -> list[dict[str, Any]]:
        """Seçim kutuları için hafif liste (id, kod, ünvan, tür); bakiye/özet hesaplamaz."""
        with get_session() as session:
            sorgu = select(Cari.id, Cari.cari_kodu, Cari.unvan, Cari.cari_turu, Cari.aktif).where(
                or_(Cari.is_deleted.is_(False), Cari.is_deleted.is_(None))
            )
            if cari_turu:
                sorgu = CariService._cari_turu_filtresi(sorgu, cari_turu)
            return [
                {"id": int(s.id), "cari_kodu": s.cari_kodu or "", "unvan": s.unvan or "",
                 "cari_turu": s.cari_turu or "", "aktif": bool(s.aktif)}
                for s in session.execute(sorgu.order_by(Cari.cari_kodu)).all()
            ]

    @staticmethod
    def ekle(
        veriler: dict[str, object],
        *,
        devir_is_id: int | None = None,
        plan_acilis=None,
        kart_acilis_dayanak: str | None = None,
    ) -> Cari:
        yazma_zorunlu("cari_duzenleme", "yeni_kayit")
        from database import cari_risk_service
        from database.kart_acilis import (
            DAYANAK_DEVIR,
            devir_yeni_kart_tarihleri,
            kart_acilis_koru,
            kart_acilis_uygula,
            yeni_kart_tarihleri,
        )

        veriler = kart_acilis_koru(dict(veriler))
        cari_turu = str(veriler.get("cari_turu") or "Müşteri")
        veriler["cari_turu"] = cari_turu
        risk_alanlari = {a: veriler.pop(a) for a in list(veriler) if a in cari_risk_service.KART_ALANLARI}
        # Kredi notu Cari() öncesi ayrılır; flush sonrası risk ile birlikte uygulanır
        kredi_notu_alanlari = {
            a: veriler.pop(a)
            for a in list(veriler)
            if a in ("kredi_notu", "kredi_notu_manuel_limit")
        }
        cari_risk_service.kart_alanlarini_dogrula(dict(risk_alanlari))
        if kart_acilis_dayanak == DAYANAK_DEVIR or devir_is_id is not None or plan_acilis is not None:
            tarihler = devir_yeni_kart_tarihleri(
                devir_is_id=devir_is_id, plan_acilis=plan_acilis
            )
        else:
            tarihler = yeni_kart_tarihleri()
        son_hata: Exception | None = None
        for _ in range(25):
            if not (str(veriler.get("cari_kodu") or "").strip()):
                veriler["cari_kodu"] = CariService.sonraki_kod(cari_turu)
            try:
                with get_session() as session:
                    cari = Cari(**veriler)
                    kart_acilis_uygula(cari, tarihler)
                    session.add(cari)
                    session.flush()
                    uygula = dict(risk_alanlari)
                    uygula.update(kredi_notu_alanlari)
                    cari_risk_service.kart_degisikligini_uygula(
                        session, cari, uygula, yeni_kart=True
                    )
                    session.flush()
                    return cari
            except IntegrityError as hata:
                son_hata = hata
                veriler["cari_kodu"] = CariService.sonraki_kod(cari_turu)
        raise ValueError("Cari kodu üretilemedi.") from son_hata

    @staticmethod
    def guncelle(cari_id: int, veriler: dict[str, object]) -> Cari:
        yazma_zorunlu("cari_duzenleme")
        from database import cari_risk_service
        from database.kart_acilis import kart_acilis_koru

        veriler = kart_acilis_koru(dict(veriler))
        with get_session() as session:
            cari = session.get(Cari, cari_id)
            if cari is None:
                raise ValueError("Cari bulunamadı.")
            eski_ana = getattr(cari, "ana_kart_turu_id", None)
            eski_tur = (cari.cari_turu or "").strip()
            yeni_ana = veriler.get("ana_kart_turu_id", eski_ana)
            yeni_tur = (veriler.get("cari_turu") or eski_tur or "").strip()
            tur_degisti = (
                "ana_kart_turu_id" in veriler or "cari_turu" in veriler
            ) and (
                (eski_ana != yeni_ana)
                or (eski_tur != yeni_tur)
            )
            cari_risk_service.kart_degisikligini_uygula(session, cari, veriler)
            for alan, deger in veriler.items():
                setattr(cari, alan, deger)
            if tur_degisti:
                CariService._tur_degisiklik_kaydet(
                    session,
                    cari_id=int(cari.id),
                    eski_ana_tur_id=eski_ana,
                    yeni_ana_tur_id=getattr(cari, "ana_kart_turu_id", None),
                    eski_cari_turu=eski_tur,
                    yeni_cari_turu=(cari.cari_turu or "").strip(),
                )
                # Bağlı alt hesapların ana türünü tutarlı güncelle (hareket/bakiye yok)
                altlar = session.scalars(
                    select(Cari).where(
                        Cari.ust_cari_id == int(cari.id),
                        or_(Cari.is_deleted.is_(False), Cari.is_deleted.is_(None)),
                    )
                ).all()
                for alt in altlar:
                    alt_eski_ana = getattr(alt, "ana_kart_turu_id", None)
                    alt_eski_tur = (alt.cari_turu or "").strip()
                    alt.ana_kart_turu_id = getattr(cari, "ana_kart_turu_id", None)
                    alt.cari_turu = cari.cari_turu
                    CariService._tur_degisiklik_kaydet(
                        session,
                        cari_id=int(alt.id),
                        eski_ana_tur_id=alt_eski_ana,
                        yeni_ana_tur_id=alt.ana_kart_turu_id,
                        eski_cari_turu=alt_eski_tur,
                        yeni_cari_turu=(alt.cari_turu or "").strip(),
                        notu=f"Üst hesap {cari.cari_kodu} tür değişikliğinden",
                    )
            try:
                session.flush()
            except IntegrityError as hata:
                raise ValueError("Cari kodu zaten kullanılıyor.") from hata
            return cari

    @staticmethod
    def _tur_degisiklik_kaydet(
        session,
        *,
        cari_id: int,
        eski_ana_tur_id,
        yeni_ana_tur_id,
        eski_cari_turu: str | None,
        yeni_cari_turu: str | None,
        notu: str | None = None,
    ) -> None:
        from database.models.cari import CariTurDegisiklik

        CariService._tur_degisiklik_tablosu_ensure(session)
        kullanici_id = None
        kullanici_adi = None
        try:
            from database.session_manager import oturum

            kullanici_id = getattr(oturum, "user_id", None) or getattr(oturum, "kullanici_id", None)
            kullanici_adi = (
                getattr(oturum, "username", None)
                or getattr(oturum, "kullanici_adi", None)
                or getattr(oturum, "ad", None)
            )
        except Exception:
            pass
        session.add(
            CariTurDegisiklik(
                cari_id=int(cari_id),
                eski_ana_tur_id=int(eski_ana_tur_id) if eski_ana_tur_id else None,
                yeni_ana_tur_id=int(yeni_ana_tur_id) if yeni_ana_tur_id else None,
                eski_cari_turu=(eski_cari_turu or None),
                yeni_cari_turu=(yeni_cari_turu or None),
                degisiklik_tarihi=datetime.now(),
                kullanici_id=kullanici_id,
                kullanici_adi=(str(kullanici_adi)[:80] if kullanici_adi else None),
                notu=(notu[:500] if notu else None),
            )
        )

    @staticmethod
    def _tur_degisiklik_tablosu_ensure(session) -> None:
        from sqlalchemy import inspect

        from database.database import engine
        from database.models.cari import CariTurDegisiklik

        del session  # tablo motor üzerinden kurulur
        if engine is None:
            return
        insp = inspect(engine)
        if not insp.has_table("cari_tur_degisiklikleri"):
            CariTurDegisiklik.__table__.create(bind=engine, checkfirst=True)

    @staticmethod
    def alt_hesaplari_listele(ust_cari_id: int) -> list[Cari]:
        """Üst cariye bağlı alt hesaplar (hareket izlenen kartlar)."""
        with get_session() as session:
            kayitlar = list(
                session.scalars(
                    select(Cari)
                    .where(
                        Cari.ust_cari_id == int(ust_cari_id),
                        or_(Cari.is_deleted.is_(False), Cari.is_deleted.is_(None)),
                    )
                    .order_by(Cari.cari_kodu)
                ).all()
            )
            for k in kayitlar:
                session.expunge(k)
            return kayitlar

    @staticmethod
    def alt_hesap_dongu_var_mi(ust_cari_id: int, aday_ust_id: int | None = None) -> bool:
        """Aday üst, mevcut kartın alt ağacında mı (döngü engeli)."""
        hedef = int(aday_ust_id) if aday_ust_id else int(ust_cari_id)
        with get_session() as session:
            gorulen: set[int] = set()
            mevcut = hedef
            while mevcut:
                if mevcut in gorulen:
                    return True
                gorulen.add(mevcut)
                ust = session.scalar(select(Cari.ust_cari_id).where(Cari.id == mevcut))
                if ust is None:
                    break
                mevcut = int(ust)
            return False

    @staticmethod
    def alt_hesap_ekle(
        ust_cari_id: int,
        *,
        unvan: str,
        cari_kodu: str | None = None,
    ) -> Cari:
        """Üst cariye bağlı alt hesap açar; ana tür üstten miras alınır."""
        yazma_zorunlu("cari_duzenleme", "yeni_kayit")
        unvan = " ".join((unvan or "").split())
        if not unvan:
            raise ValueError("Alt hesap ünvanı zorunlu.")
        ust = CariService.getir(int(ust_cari_id))
        if ust is None:
            raise ValueError("Üst cari bulunamadı.")
        if getattr(ust, "ust_cari_id", None):
            # İkinci seviye: üstün üstü üzerinden bağlanabilir; döngü kontrolü yeterli
            pass
        tur = (ust.cari_turu or "Müşteri").strip()
        kod = (cari_kodu or "").strip() or CariService.sonraki_kod(tur)
        veriler = {
            "cari_kodu": kod,
            "unvan": unvan,
            "cari_turu": tur,
            "ana_kart_turu_id": getattr(ust, "ana_kart_turu_id", None),
            "musteri_alt_tur_id": getattr(ust, "musteri_alt_tur_id", None),
            "tedarikci_alt_tur_id": getattr(ust, "tedarikci_alt_tur_id", None),
            "ust_cari_id": int(ust.id),
            "aktif": True,
        }
        # Döngü: yeni kart henüz yok; üst zinciri kendine dönmesin
        if CariService.alt_hesap_dongu_var_mi(int(ust.id)):
            raise ValueError("Döngüsel üst–alt hesap bağlantısı oluşamaz.")
        return CariService.ekle(veriler)

    @staticmethod
    def ust_alt_bakiye_ozeti(cari_id: int) -> dict[str, Any]:
        """Üst hesabın kendi bakiyesi + alt hesap bakiyeleri (mükerrer yok).

        Genel toplam = üst kendi hareketleri + her altın kendi hareketleri.
        Alt hesaplar üstün hareketlerine yazılmaz; iki kez sayılmaz.
        """
        from database.cari_bakiye_service import liste_bakiyeleri_detay

        ana = CariService.getir(int(cari_id))
        if ana is None:
            raise ValueError("Cari bulunamadı.")
        altlar = CariService.alt_hesaplari_listele(int(cari_id))
        ids = [int(ana.id)] + [int(a.id) for a in altlar]
        detay = liste_bakiyeleri_detay(ids)
        kendi = detay.get(int(ana.id), {})
        alt_satirlar = []
        alt_toplam = Decimal("0")
        for a in altlar:
            d = detay.get(int(a.id), {})
            net = Decimal(str(d.get("bakiye") or 0))
            alt_toplam += net
            alt_satirlar.append(
                {
                    "id": int(a.id),
                    "cari_kodu": a.cari_kodu,
                    "unvan": a.unvan,
                    "bakiye": net,
                    "toplam_borc": d.get("toplam_borc"),
                    "toplam_alacak": d.get("toplam_alacak"),
                }
            )
        kendi_net = Decimal(str(kendi.get("bakiye") or 0))
        return {
            "ust_id": int(ana.id),
            "ust_bakiye": kendi_net,
            "alt_hesaplar": alt_satirlar,
            "alt_toplam": alt_toplam,
            "genel_toplam": kendi_net + alt_toplam,
        }

    @staticmethod
    def toplu_sektor_grubu_ata(
        cari_idler: list[int],
        hedef_grup: str,
        *,
        mevcut_grubu_degistir: bool = False,
    ) -> dict[str, Any]:
        """Seçili carilere sektör grubu (musteri_grubu) atar; ana/alt türlere dokunmaz.

        Varsayılan: yalnız grubu boş olanlara yazar.
        ``mevcut_grubu_degistir=True`` ise farklı grubu olanları da hedefe çeker.
        Tek transaction; hata olursa geri alınır.
        """
        yazma_zorunlu("cari_duzenleme")
        hedef = (hedef_grup or "").strip()
        if not hedef:
            raise ValueError("Hedef sektör grubu seçin.")
        ids = []
        gorulen: set[int] = set()
        for ham in cari_idler or []:
            try:
                cid = int(ham)
            except (TypeError, ValueError):
                continue
            if cid in gorulen:
                continue
            gorulen.add(cid)
            ids.append(cid)
        if not ids:
            raise ValueError("Atanacak cari seçilmedi.")

        from database.kart_turu_service import KartTuruService

        # Aktif sektör doğrula (firma kapsamı)
        sektorler = {
            (s.get("ad") or "").strip()
            for s in KartTuruService.sektor_listele(sadece_aktif=True)
        }
        if hedef not in sektorler:
            raise ValueError(
                f"Hedef sektör grubu aktif listede yok: «{hedef}». "
                "Önce Tanımlar → Kart Türleri / Gruplar’dan ekleyin veya pencereden Yeni Grup kullanın."
            )

        atanan = 0
        zaten = 0
        atlanan_farkli = 0
        bulunamayan = 0
        with get_session() as session:
            for cid in ids:
                cari = session.get(Cari, cid)
                if cari is None or getattr(cari, "is_deleted", False):
                    bulunamayan += 1
                    continue
                mevcut = (cari.musteri_grubu or "").strip()
                if mevcut == hedef:
                    zaten += 1
                    continue
                if mevcut and not mevcut_grubu_degistir:
                    atlanan_farkli += 1
                    continue
                cari.musteri_grubu = hedef
                atanan += 1
            session.flush()
        return {
            "hedef": hedef,
            "atanan": atanan,
            "zaten_grupta": zaten,
            "atlanan_farkli_grup": atlanan_farkli,
            "bulunamayan": bulunamayan,
            "toplam_secim": len(ids),
            "mevcut_grubu_degistir": bool(mevcut_grubu_degistir),
        }

    ADRES_SLOTLARI = (
        (1, "adres", "il", "ilce", "adres_tipi"),
        (2, "adres2", "il2", "ilce2", "adres_tipi2"),
        (3, "adres3", "il3", "ilce3", "adres_tipi3"),
    )
    ADRES_TIPLERI = ("Merkez", "Fatura", "Sevk", "Depo", "Şube", "Diğer")

    @staticmethod
    def bos_adres_slotu(cari_id: int) -> int | None:
        cari = CariService.getir(cari_id)
        if cari is None:
            return None
        for no, adres_alan, il_alan, ilce_alan, _tip in CariService.ADRES_SLOTLARI:
            if not any(
                (getattr(cari, alan, None) or "").strip()
                for alan in (adres_alan, il_alan, ilce_alan)
            ):
                return no
        return None

    @staticmethod
    def adres_ekle(cari_id: int, tip: str, adres: str, il: str = "", ilce: str = "") -> int:
        """Carinin ilk boş adres yuvasına adres ekler; eklenen adres numarasını döner."""
        yazma_zorunlu("cari_duzenleme")
        tip = (tip or "").strip()
        adres = (adres or "").strip()
        il = (il or "").strip()
        ilce = (ilce or "").strip()
        if tip not in CariService.ADRES_TIPLERI:
            raise ValueError("Adres türü seçin.")
        if not adres:
            raise ValueError("Açık adres boş olamaz.")
        if len(adres) > 500:
            raise ValueError("Açık adres en fazla 500 karakter olabilir.")
        if len(il) > 50 or len(ilce) > 50:
            raise ValueError("İl / ilçe en fazla 50 karakter olabilir.")
        with get_session() as session:
            cari = session.get(Cari, cari_id)
            if cari is None:
                raise ValueError("Cari bulunamadı.")
            for no, adres_alan, il_alan, ilce_alan, tip_alan in CariService.ADRES_SLOTLARI:
                if any(
                    (getattr(cari, alan, None) or "").strip()
                    for alan in (adres_alan, il_alan, ilce_alan)
                ):
                    continue
                setattr(cari, adres_alan, adres)
                setattr(cari, il_alan, il or None)
                setattr(cari, ilce_alan, ilce or None)
                setattr(cari, tip_alan, tip)
                session.flush()
                return no
        raise ValueError(
            "Bu carinin 3 adres alanı da dolu. Yeni adres için Cari Hesap Kartı'ndan "
            "mevcut bir adresi düzenleyin."
        )

    @staticmethod
    def pasife_al(cari_id: int) -> None:
        yazma_zorunlu("cari_duzenleme")
        with get_session() as session:
            cari = session.get(Cari, cari_id)
            if cari is None:
                raise ValueError("Cari bulunamadı.")
            cari.aktif = False
            session.flush()

    @staticmethod
    def satis_ekle(cari_id: int, veriler: dict[str, object]) -> SatisHareketi:
        satis_tarihi = veriler.get("satis_tarihi")
        satis_tutari = CariService._tutar(veriler.get("satis_tutari"))
        kalan = CariService._tutar(veriler.get("kalan_acik_tutar"))
        if not isinstance(satis_tarihi, date) or satis_tarihi > date.today():
            raise ValueError("Satış tarihi gelecek bir tarih olamaz.")
        if satis_tutari <= 0 or kalan < 0:
            raise ValueError("Satış tutarı pozitif, kalan tutar sıfır veya daha büyük olmalıdır.")
        if kalan > satis_tutari:
            raise ValueError("Kalan açık tutar satış tutarından büyük olamaz.")
        with get_session() as session:
            if session.get(Cari, cari_id) is None:
                raise ValueError("Cari bulunamadı.")
            hareket = SatisHareketi(
                cari_id=cari_id,
                satis_tarihi=satis_tarihi,
                belge_no=str(veriler.get("belge_no", "")).strip(),
                satis_tutari=satis_tutari,
                kalan_acik_tutar=kalan,
            )
            if not hareket.belge_no:
                raise ValueError("Belge/fatura numarası zorunludur.")
            session.add(hareket)
            session.flush()
            return hareket

    @staticmethod
    def vergi_no_dogrula(deger: object) -> None:
        """Boş serbest; doluysa 10 haneli VKN algoritması."""
        ham = str(deger or "").strip().replace(" ", "")
        if not ham:
            return
        if not ham.isdigit():
            raise ValueError("Vergi numarası yalnızca rakam olmalıdır.")
        if len(ham) != 10:
            raise ValueError("Vergi kimlik numarası (VKN) 10 hane olmalıdır.")
        CariService._vkn_dogrula(ham)

    @staticmethod
    def tc_kimlik_dogrula(deger: object) -> None:
        """Boş serbest; doluysa 11 haneli TCKN algoritması."""
        ham = str(deger or "").strip().replace(" ", "")
        if not ham:
            return
        if not ham.isdigit():
            raise ValueError("TC kimlik numarası yalnızca rakam olmalıdır.")
        if len(ham) != 11:
            raise ValueError("TC kimlik numarası 11 hane olmalıdır.")
        CariService._tc_kimlik_dogrula(ham)

    @staticmethod
    def vergi_veya_tc_dogrula(deger: object) -> None:
        """Geriye dönük: boş serbest; 10 hane VKN, 11 hane TCKN."""
        ham = str(deger or "").strip().replace(" ", "")
        if not ham:
            return
        if not ham.isdigit():
            raise ValueError("Vergi / TC kimlik numarası yalnızca rakam olmalıdır.")
        if len(ham) == 11:
            CariService._tc_kimlik_dogrula(ham)
        elif len(ham) == 10:
            CariService._vkn_dogrula(ham)
        else:
            raise ValueError(
                "Vergi kimlik no 10 hane (VKN) veya TC kimlik no 11 hane olmalıdır."
            )

    @staticmethod
    def _tc_kimlik_dogrula(no: str) -> None:
        if len(no) != 11 or not no.isdigit() or no[0] == "0":
            raise ValueError("Geçersiz TC kimlik numarası.")
        d = [int(c) for c in no]
        # 10. hane: ((1+3+5+7+9)*7 - (2+4+6+8)) mod 10
        o1 = sum(d[i] for i in range(0, 9, 2))
        o2 = sum(d[i] for i in range(1, 8, 2))
        if ((o1 * 7) - o2) % 10 != d[9]:
            raise ValueError("TC kimlik numarası algoritma kontrolünden geçemedi.")
        if (sum(d[:10]) % 10) != d[10]:
            raise ValueError("TC kimlik numarası algoritma kontrolünden geçemedi.")

    @staticmethod
    def _vkn_dogrula(no: str) -> None:
        if len(no) != 10 or not no.isdigit():
            raise ValueError("Geçersiz vergi kimlik numarası (VKN).")
        d = [int(c) for c in no]
        toplam = 0
        for i in range(9):
            tmp = (d[i] + 9 - i) % 10
            if tmp == 0:
                continue
            contrib = (tmp * (2 ** (9 - i))) % 9
            toplam += 9 if contrib == 0 else contrib
        check = (10 - (toplam % 10)) % 10
        if check != d[9]:
            raise ValueError("Vergi kimlik numarası (VKN) algoritma kontrolünden geçemedi.")

    @staticmethod
    def _tutar(deger: object) -> Decimal:
        if isinstance(deger, Decimal):
            return deger
        if isinstance(deger, int) and not isinstance(deger, bool):
            return Decimal(deger)
        try:
            return Decimal(str(deger).replace(".", "").replace(",", "."))
        except (InvalidOperation, ValueError):
            raise ValueError("Tutar geçerli bir sayı olmalıdır.") from None

    @staticmethod
    def _borc_vade_haritasi(session, belge_nolari: list[str] | set[str]) -> dict[str, date]:
        """Belge no → borç vade tarihi (Satış/Alış faturası.vade_tarihi).

        SatisHareketi'nde vade kolonu yok; fatura_no ile eşleşen faturadan alınır.
        """
        nos = [n for n in {str(n or "").strip() for n in belge_nolari} if n]
        if not nos:
            return {}
        harita: dict[str, date] = {}
        for fatura_no, vade in session.execute(
            select(SatisFaturasi.fatura_no, SatisFaturasi.vade_tarihi).where(
                SatisFaturasi.fatura_no.in_(nos)
            )
        ):
            if fatura_no and vade:
                harita[str(fatura_no)] = vade
        from database.models.alis_faturasi import AlisFaturasi

        eksik = [n for n in nos if n not in harita]
        if eksik:
            for fatura_no, vade in session.execute(
                select(AlisFaturasi.fatura_no, AlisFaturasi.vade_tarihi).where(
                    AlisFaturasi.fatura_no.in_(eksik)
                )
            ):
                if fatura_no and vade:
                    harita[str(fatura_no)] = vade
        return harita

    @staticmethod
    def _hareket_vade(h: SatisHareketi, vade_harita: dict[str, date] | None = None) -> date:
        """Borç vadesi: fatura vade_tarihi, yoksa belge tarihi (satis_tarihi)."""
        if vade_harita:
            vade = vade_harita.get(h.belge_no or "")
            if vade:
                return vade
        return h.satis_tarihi

    @staticmethod
    def _agirlikli_gun_ortalama(dilimler: list[dict[str, Any]]) -> float:
        """Σ(tutar × gün) / Σ(tutar); gün None olanlar dışarıda, boşsa 0."""
        toplam = Decimal("0")
        agirlik = 0.0
        for d in dilimler:
            tutar = Decimal(str(d.get("tutar") or 0))
            if tutar <= 0:
                continue
            g = d.get("gun")
            if g is None:
                continue
            toplam += tutar
            agirlik += float(tutar) * float(g)
        return agirlik / float(toplam) if toplam else 0.0

    @staticmethod
    def _basit_gun_ortalama(dilimler: list[dict[str, Any]]) -> float:
        """Σ(gün) / adet; gün None olanlar dışarıda, boşsa 0."""
        degerler = []
        for d in dilimler:
            g = d.get("gun")
            if g is None:
                continue
            degerler.append(float(g))
        if not degerler:
            return 0.0
        return sum(degerler) / len(degerler)

    # Borç kuyruğuna alınmayan belgeler (kredi/tahsilat/ödeme fişleri).
    # Valör borçları = satış/alış faturaları (ve benzeri belge borçları);
    # ODM/THS vb. cari fişleri fatura borcu sayılmaz.
    _VALOR_BORC_HARIC_ONEK = (
        "VRM-", "KKC-", "THS-", "AHV-", "POS-", "BNC-", "KBY-", "KKO-", "IPT-", "FZO-",
        "ODM-", "GHV-",
    )

    @staticmethod
    def _odeme_borc_dusurur_mu(islem: CariIslem, tedarikci: bool) -> Decimal:
        """FIFO eşleştirmede ödemenin bakiyeyi düşüren tutarı.

        Müşteri: Tahsilat / virman / KK çekimi → alacak.
        Tedarikçi: Ödeme, Virman Ödeme, KK Çekimi (müşteriden tedarikçiye) ve iade
        kapamaları → borc (yoksa alacak); açılış/fatura alacağı ödeme sayılmaz.
        """
        tur = (getattr(islem, "islem_turu", None) or "").strip()
        if tedarikci:
            if (
                tur in ("Ödeme", "Virman Ödeme", "KK Çekimi")
                or tur.casefold().startswith("iade")
            ):
                dusen = Decimal(str(islem.borc or 0))
                if dusen <= 0:
                    dusen = Decimal(str(islem.alacak or 0))
                return dusen if dusen > 0 else Decimal("0")
            return Decimal("0")
        dusen = Decimal(str(islem.alacak or 0))
        return dusen if dusen > 0 else Decimal("0")

    @staticmethod
    def _fifo_valor_dilimleri(
        session,
        cari_id: int,
        cari_turu: str | None = None,
        referans: date | None = None,
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        """FIFO valör: (tam_kapanan, açık_borç, kapanan_dilimler, açık_alacak).

        MANUEL kullanıcı kapatmaları korunur; serbest kalan tutarlara işlem tarihi →
        belge_no → id FIFO uygulanır. Hesap tarihinden sonraki hareketler hariç.
        """
        from database.cari_ortalama_valor_service import fifo_valor_paketi_oturumdan

        return fifo_valor_paketi_oturumdan(
            session,
            int(cari_id),
            cari_turu=cari_turu,
            referans=referans,
        )

    @staticmethod
    def _fifo_odeme_borc_eslesmeleri(
        session, cari_id: int, cari_turu: str | None = None
    ) -> list[dict[str, Any]]:
        """FIFO kapanış dilimleri (geriye dönük API)."""
        _tam, _acik, dilimler, _alacak = CariService._fifo_valor_dilimleri(
            session, cari_id, cari_turu
        )
        return dilimler

    @staticmethod
    def _odenen_ortalama_valor_fifo(session, cari_id: int, cari_turu: str | None = None) -> float | None:
        """Kapanan borcun tutar-ağırlıklı ortalama valörü (P − I).

        Her ödeme dilimi kendi tarihi ve tutarıyla girer; tam/kısmi ayrımı yok.
        """
        from database.cari_ortalama_valor_service import kapanan_valor_ortalama

        _tam, _acik, dilimler, _alacak = CariService._fifo_valor_dilimleri(
            session, cari_id, cari_turu
        )
        return kapanan_valor_ortalama(dilimler).get("odenen_ortalama_valor_gun")

    @staticmethod
    def _acik_ortalama_valor_fifo(
        session, cari_id: int, cari_turu: str | None = None, referans: date | None = None
    ) -> float | None:
        """Açık bakiyenin tutar-ağırlıklı ortalama valörü (T − V)."""
        from database.cari_ortalama_valor_service import _sonuc_olustur

        bugun = referans or date.today()
        _tam, acik, _dilimler, acik_alacak = CariService._fifo_valor_dilimleri(
            session, cari_id, cari_turu, referans=bugun
        )
        # Yönü net bakiyeden almak için kısa yol: yalnız açık borç dilimleri
        if acik:
            gecerli = [d for d in acik if d.get("gun") is not None]
            return CariService._agirlikli_gun_ortalama(gecerli) if gecerli else None
        if acik_alacak:
            sonuc = _sonuc_olustur(Decimal("-1"), [], acik_alacak, bugun)
            return sonuc.get("ortalama_valor_gun")
        return None

    @staticmethod
    def _ozet(
        cari: Cari,
        session=None,
        *,
        defter: list[dict[str, Any]] | None = None,
        fifo_sonuc: tuple | None = None,
        rapor_tarihi: date | None = None,
    ) -> dict[str, Any]:
        """Cari hesap özeti.

        Toplam borç/alacak: defter sütun toplamları (hareket genel toplam ile aynı).
        Bakiye: toplam_borç − toplam_alacak (defter kalan konvansiyonu).
        Bakiye durumu: Borçlu / Alacaklı / Kapalı.

        Bakiyenin ort. valörü (çift yönlü — ``cari_ortalama_valor_service``):
          Borçlu → açık borç FIFO; Alacaklı → açık alacak FIFO;
          açık valör gün = T − I (belge yaşı); kapanan valör = P − I.

        ``defter`` / ``fifo_sonuc`` verilirse tekrar hesaplanmaz (kart özeti performansı).
        """
        from database.cari_ortalama_valor_service import (
            calculate_account_average_value_date,
            kapanan_valor_ortalama,
        )

        bugun = rapor_tarihi or date.today()
        hareketler = list(cari.satis_hareketleri or [])
        borclar = [h for h in hareketler if Decimal(str(h.kalan_acik_tutar or 0)) > 0]
        alacaklar = [h for h in hareketler if Decimal(str(h.kalan_acik_tutar or 0)) < 0]
        acik_borc = sum((Decimal(str(h.kalan_acik_tutar)) for h in borclar), Decimal("0"))
        acik_alacak = sum((-Decimal(str(h.kalan_acik_tutar)) for h in alacaklar), Decimal("0"))

        odenen_valor = None
        odenen_valor_basit = None
        bakiye_valor = None
        bakiye_yas = None
        valor_meta: dict[str, Any] = {}
        kap_ozet: dict[str, Any] = {}
        acik_dilimler: list[dict[str, Any]] = []
        if session is not None:
            if defter is None:
                defter = CariService._defter(session, cari.id)
            toplam_borc = sum((Decimal(str(k.get("borc") or 0)) for k in defter), Decimal("0"))
            toplam_alacak = sum((Decimal(str(k.get("alacak") or 0)) for k in defter), Decimal("0"))
            bakiye = toplam_borc - toplam_alacak
            if fifo_sonuc is None:
                fifo_sonuc = CariService._fifo_valor_dilimleri(
                    session, cari.id, cari_turu=cari.cari_turu, referans=bugun
                )
            if len(fifo_sonuc) >= 4:
                _kapanan_tam, acik_dilimler, kapanan_dilimler, _acik_alacak = (
                    fifo_sonuc[0],
                    fifo_sonuc[1],
                    fifo_sonuc[2],
                    fifo_sonuc[3],
                )
            else:
                _kapanan_tam, acik_dilimler, kapanan_dilimler = (
                    fifo_sonuc[0],
                    fifo_sonuc[1],
                    fifo_sonuc[2],
                )
            # Kapanan valör: her ödeme dilimi (P−I); tam kapanan tek tarih tuzağı yok
            kap_ozet = kapanan_valor_ortalama(kapanan_dilimler)
            odenen_valor = kap_ozet.get("odenen_ortalama_valor_gun")
            odenen_valor_basit = CariService._basit_gun_ortalama(
                [d for d in kapanan_dilimler if d.get("kapanan_valor_gun") is not None or d.get("gun") is not None]
            )
            valor_meta = calculate_account_average_value_date(
                cari.id,
                rapor_tarihi=bugun,
                session=session,
                cari_turu=cari.cari_turu,
                bakiye=bakiye,
                fifo_paketi=fifo_sonuc,
            )
            raw_valor = valor_meta.get("ortalama_valor_gun")
            bakiye_valor = float(raw_valor) if raw_valor is not None else None
            raw_yas = valor_meta.get("ortalama_yas_gun")
            bakiye_yas = float(raw_yas) if raw_yas is not None else None
        else:
            toplam_borc = sum(
                (Decimal(str(h.satis_tutari or 0)) for h in hareketler if Decimal(str(h.satis_tutari or 0)) > 0),
                Decimal("0"),
            )
            toplam_alacak = Decimal("0")
            bakiye = sum((Decimal(str(h.kalan_acik_tutar or 0)) for h in hareketler), Decimal("0"))
            acik_dilimler = []
            defter = []
            from database.cari_ortalama_valor_service import _yon_etiket, _valor_turu_etiket

            yon, tur, durum = _yon_etiket(bakiye)
            valor_meta = {
                "bakiye_yonu": yon,
                "valor_turu": tur,
                "valor_turu_etiket": _valor_turu_etiket(tur),
                "ortalama_valor_tarihi": None,
                "ortalama_valor_gun": None,
                "ortalama_yas_gun": None,
                "uyari": None,
                "hesaplama_sebep": "Oturum yok",
                "bakiye_durumu": durum,
            }

        bakiye_durumu = valor_meta.get("bakiye_durumu") or (
            "Borçlu" if bakiye > 0 else ("Alacaklı" if bakiye < 0 else "Kapalı")
        )

        # Açık borç valörü: yalnız vadesi bilinen dilimler (gun = T−V)
        borc_valor_kaynak = [d for d in acik_dilimler if d.get("gun") is not None]
        borc_valor = (
            CariService._agirlikli_gun_ortalama(borc_valor_kaynak) if borc_valor_kaynak else None
        )
        alacak_valor = bakiye_valor if bakiye < 0 else None

        vade_harita: dict[str, date] | None = None
        if session is not None:
            vade_harita = CariService._borc_vade_haritasi(
                session, [h.belge_no for h in hareketler]
            )

        # Liste «Ort. Gün»: yalnız gerçek vadeli açık borçların basit T−V ortalaması
        vade_gunleri = []
        for h in borclar:
            vade = None
            if vade_harita:
                vade = vade_harita.get(h.belge_no or "")
            if vade is None:
                continue
            vade_gunleri.append((bugun - vade).days)
        ortalama = (sum(vade_gunleri) / len(vade_gunleri)) if vade_gunleri else None
        return {
            "cari": cari,
            "bakiye": bakiye,
            "bakiye_durumu": bakiye_durumu,
            "bakiye_yonu": valor_meta.get("bakiye_yonu"),
            "valor_turu": valor_meta.get("valor_turu"),
            "valor_turu_etiket": valor_meta.get("valor_turu_etiket"),
            "ortalama_valor_tarihi": valor_meta.get("ortalama_valor_tarihi"),
            "ortalama_valor_uyari": valor_meta.get("uyari"),
            "ortalama_valor_sebep": valor_meta.get("hesaplama_sebep"),
            "ortalama_yas_gun": bakiye_yas,
            "ortalama_yas_tarihi": valor_meta.get("ortalama_yas_tarihi"),
            "toplam_borc": toplam_borc,
            "toplam_alacak": toplam_alacak,
            "odenen_ortalama_valor_gun": odenen_valor,
            "odenen_ortalama_valor_basit_gun": odenen_valor_basit,
            "bakiye_ortalama_valor_gun": bakiye_valor,
            "borc_tutar": acik_borc,
            "alacak_tutar": acik_alacak,
            "borc_valor_gun": borc_valor,
            "alacak_valor_gun": alacak_valor,
            "ortalama_gun": ortalama if ortalama is not None else 0.0,
            "agirlikli_ortalama_gun": bakiye_valor if bakiye_valor is not None else 0.0,
            "acik_hareket_sayisi": len(borclar) + len(alacaklar),
            "olcu_acik": valor_meta.get("olcu") or "acik_valor_T_eksi_I",
            "olcu_kapanan": kap_ozet.get("olcu") or "kapanan_valor_P_eksi_I",
        }

    @staticmethod
    def kart_ozet_metrikleri(
        cari_id: int, *, rapor_tarihi: date | None = None
    ) -> dict[str, Any] | None:
        """Cari kart üst özeti — mevcut bakiye/valör/FIFO ve risk mantığını yeniden kullanır.

        Yeni formül icat etmez:
        - bakiye / açık valör (T−I) → ``_ozet``
        - kapanan valör (P−I) → FIFO / doğrulanmış belge bağlantıları
        - vadesi geçmiş → FIFO ``vade_farki_gun > 0`` tutar toplamı
        - kullanılabilir risk → ``acik_hesap_risk_degerlendir(...).kalan_limit``
        - son işlem → defterin en yeni satırı

        Performans: defter + FIFO bir kez hesaplanır, ``_ozet`` ile paylaşılır.
        """
        from hizli_satis_musteri import acik_hesap_risk_degerlendir

        from sqlalchemy.orm import selectinload

        referans = rapor_tarihi or date.today()
        with get_session() as session:
            cari = session.scalar(
                select(Cari)
                .where(Cari.id == int(cari_id))
                .options(selectinload(Cari.satis_hareketleri))
            )
            if cari is None:
                return None
            defter = CariService._defter(session, cari.id)
            fifo_sonuc = CariService._fifo_valor_dilimleri(
                session, cari.id, cari_turu=cari.cari_turu, referans=referans
            )
            ozet = CariService._ozet(
                cari,
                session=session,
                defter=defter,
                fifo_sonuc=fifo_sonuc,
                rapor_tarihi=referans,
            )
            acik_dilimler = fifo_sonuc[1]
            # Vadesi geçmiş: açık valör T−V > 0 (işlem yaşı ile karıştırma)
            def _vadesi_gecmis_mi(d: dict) -> bool:
                vf = d.get("vade_farki_gun")
                if vf is None:
                    vf = d.get("gun")
                try:
                    return vf is not None and int(vf) > 0
                except (TypeError, ValueError):
                    return False

            vadesi_gecmis = sum(
                (Decimal(str(d.get("tutar") or 0)) for d in acik_dilimler if _vadesi_gecmis_mi(d)),
                Decimal("0"),
            )
            son = defter[0] if defter else None
            bakiye = Decimal(str(ozet.get("bakiye") or 0))
            from database import cari_risk_service

            risk = acik_hesap_risk_degerlendir(
                bakiye=bakiye if bakiye > 0 else Decimal("0"),
                risk_limiti=cari_risk_service.etkin_limit(cari, cari_risk_service.TUR_ACIK),
                ek_tutar=0,
                acik_hesap_yetkisi=True,
            )
            try:
                risk_ozeti = cari_risk_service.risk_hesapla(session, cari.id)
            except Exception:
                risk_ozeti = None

            def _opt_float(v):
                return float(v) if v is not None else None

            session.expunge(cari)
            return {
                "cari": cari,
                "bakiye": bakiye,
                "bakiye_durumu": ozet.get("bakiye_durumu") or "Kapalı",
                "bakiye_yonu": ozet.get("bakiye_yonu"),
                "valor_turu": ozet.get("valor_turu"),
                "valor_turu_etiket": ozet.get("valor_turu_etiket"),
                "ortalama_valor_tarihi": ozet.get("ortalama_valor_tarihi"),
                "ortalama_valor_uyari": ozet.get("ortalama_valor_uyari"),
                "ortalama_valor_sebep": ozet.get("ortalama_valor_sebep"),
                "ortalama_yas_gun": ozet.get("ortalama_yas_gun"),
                "ortalama_yas_tarihi": ozet.get("ortalama_yas_tarihi"),
                "toplam_borc": ozet.get("toplam_borc", Decimal("0")),
                "toplam_alacak": ozet.get("toplam_alacak", Decimal("0")),
                "odenen_ortalama_valor_gun": _opt_float(ozet.get("odenen_ortalama_valor_gun")),
                "bakiye_ortalama_valor_gun": _opt_float(ozet.get("bakiye_ortalama_valor_gun")),
                "agirlikli_ortalama_gun": _opt_float(ozet.get("bakiye_ortalama_valor_gun")),
                "olcu_acik": ozet.get("olcu_acik"),
                "olcu_kapanan": ozet.get("olcu_kapanan"),
                "vadesi_gecmis": vadesi_gecmis,
                "kullanilabilir_risk": risk.get("kalan_limit"),
                "risk_durum": risk.get("durum") or "ok",
                "risk_mesaj": risk.get("mesaj") or "",
                "risk_ozeti": risk_ozeti,
                "son_islem_tarih": (son or {}).get("tarih"),
                "son_islem_tutar": (
                    Decimal(str((son or {}).get("borc") or 0))
                    - Decimal(str((son or {}).get("alacak") or 0))
                    if son
                    else None
                ),
                "son_islem_tur": (son or {}).get("tur"),
                "son_islem_belge": (son or {}).get("belge_no"),
                "hareketler": defter,
            }
