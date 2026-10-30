"""Aktivite Yönetimi servisi — türler, liste, kayıt (sprint 1)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import select

from database.access import yazma_zorunlu
from database.database import Base, engine, get_session
from database.models.aktivite import (
    SEFER_DURUMLARI,
    TESLIMAT_TURLERI,
    Aktivite,
    AktiviteSefer,
    AktiviteSeferDurak,
    AktiviteTekillik,
    AktiviteTuru,
)

# Talimat § sabit test yol süreleri (ardışık duraklar arası) — gerçek sağlayıcı değil
_TEST_YOL_DK = (15, 10, 25, 20, 15, 20)
_VARSAYILAN_BASLANGIC = "Ray Mobilya — mağaza (varsayılan başlangıç/dönüş)"

VARSAYILAN_TURLER: tuple[tuple[str, str, int, bool, bool], ...] = (
    ("MUSTERI_ARAMASI", "Müşteri araması", 15, False, False),
    ("TEKLIF_TAKIBI", "Teklif takibi", 20, False, False),
    ("MUSTERI_ZIYARETI", "Müşteri ziyareti", 45, False, True),
    ("SIPARIS_HAZIRLAMA", "Sipariş hazırlama", 30, False, False),
    ("PAKETLEME", "Paketleme", 20, False, False),
    ("SEVKIYAT", "Sevkiyat", 60, True, True),
    ("MAL_ALMA", "Mal alma", 40, False, True),
    ("TAHSILAT", "Tahsilat", 20, False, True),
    ("BANKA_ISI", "Banka işi", 30, False, True),
    ("KARGO_TESLIMI", "Kargo teslimi", 30, True, True),
    ("SERVIS", "Servis", 60, False, True),
    ("ETIKETLEME", "Etiketleme", 15, False, False),
    ("RAF_DUZENLEME", "Raf düzenleme", 30, False, False),
    ("STOK_SAYIMI", "Stok sayımı", 60, False, False),
)


class AktiviteService:
    _schema_hazir = False

    @classmethod
    def ensure_schema(cls, eng=None) -> None:
        bag = eng if eng is not None else engine
        if bag is None:
            return
        import database.models.aktivite  # noqa: F401

        Base.metadata.create_all(
            bind=bag,
            tables=[
                AktiviteTuru.__table__,
                Aktivite.__table__,
                AktiviteTekillik.__table__,
                AktiviteSefer.__table__,
                AktiviteSeferDurak.__table__,
            ],
        )
        cls._varsayilan_turleri_doldur()
        cls._schema_hazir = True

    @classmethod
    def _varsayilan_turleri_doldur(cls) -> None:
        with get_session() as session:
            mevcut = {t.kod for t in session.scalars(select(AktiviteTuru)).all()}
            for i, (kod, ad, sure, sevk, dis) in enumerate(VARSAYILAN_TURLER):
                if kod in mevcut:
                    continue
                session.add(
                    AktiviteTuru(
                        kod=kod,
                        ad=ad,
                        varsayilan_sure_dk=sure,
                        sevkiyat_mi=sevk,
                        dis_is_mi=dis,
                        sira=(i + 1) * 10,
                    )
                )
            session.flush()

    @staticmethod
    def tur_listesi(*, yalniz_aktif: bool = True) -> list[dict[str, Any]]:
        AktiviteService.ensure_schema()
        with get_session() as session:
            q = select(AktiviteTuru).order_by(AktiviteTuru.sira, AktiviteTuru.ad)
            if yalniz_aktif:
                q = q.where(AktiviteTuru.aktif.is_(True))
            return [
                {
                    "id": int(t.id),
                    "kod": t.kod,
                    "ad": t.ad,
                    "varsayilan_sure_dk": int(t.varsayilan_sure_dk),
                    "sevkiyat_mi": bool(t.sevkiyat_mi),
                    "dis_is_mi": bool(t.dis_is_mi),
                    "aktif": bool(t.aktif),
                }
                for t in session.scalars(q).all()
            ]

    @staticmethod
    def listele(
        *,
        filtre: str = "acik",
        sorumlu_id: int | None = None,
        bugun: bool = False,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        AktiviteService.ensure_schema()
        with get_session() as session:
            q = (
                select(Aktivite, AktiviteTuru)
                .join(AktiviteTuru, AktiviteTuru.id == Aktivite.tur_id)
                .where(Aktivite.is_deleted.is_(False))
                .order_by(Aktivite.plan_tarih.asc(), Aktivite.id.desc())
                .limit(limit)
            )
            if filtre == "acik":
                q = q.where(Aktivite.durum.in_(("ACIK", "DEVAM", "BEKLEMEDE")))
            elif filtre == "geciken":
                q = q.where(
                    Aktivite.durum.in_(("ACIK", "DEVAM", "BEKLEMEDE")),
                    Aktivite.son_tarih.is_not(None),
                    Aktivite.son_tarih < date.today(),
                )
            elif filtre == "tamamlanan":
                q = q.where(Aktivite.durum == "TAMAMLANDI")
            if sorumlu_id:
                q = q.where(Aktivite.sorumlu_personel_id == int(sorumlu_id))
            if bugun:
                q = q.where(Aktivite.plan_tarih == date.today())

            sonuc = []
            for a, t in session.execute(q).all():
                sonuc.append(
                    {
                        "id": int(a.id),
                        "konu": a.konu,
                        "tur_kod": t.kod,
                        "tur_ad": t.ad,
                        "durum": a.durum,
                        "oncelik": a.oncelik,
                        "plan_tarih": a.plan_tarih,
                        "plan_saat": a.plan_saat,
                        "son_tarih": a.son_tarih,
                        "cari_id": a.cari_id,
                        "sorumlu_personel_id": a.sorumlu_personel_id,
                        "kaynak_belge_tur": a.kaynak_belge_tur,
                        "kaynak_belge_no": a.kaynak_belge_no,
                        "teslimat_turu": a.teslimat_turu,
                        "sevkiyat_durum": a.sevkiyat_durum,
                        "dis_is_mi": bool(t.dis_is_mi),
                        "adres_metin": a.adres_metin,
                    }
                )
            return sonuc

    @staticmethod
    def dis_isler(*, limit: int = 100) -> list[dict[str, Any]]:
        tum = AktiviteService.listele(filtre="acik", limit=limit * 2)
        return [a for a in tum if a.get("dis_is_mi")][:limit]

    @staticmethod
    def kaydet(veriler: dict[str, Any]) -> dict[str, Any]:
        yazma_zorunlu("yeni_kayit", "satis_duzenleme", "stok_duzenleme")
        AktiviteService.ensure_schema()
        konu = (veriler.get("konu") or "").strip()
        if not konu:
            raise ValueError("Konu zorunludur.")
        tur_kod = (veriler.get("tur_kod") or "").strip()
        with get_session() as session:
            tur = session.scalar(select(AktiviteTuru).where(AktiviteTuru.kod == tur_kod))
            if tur is None and veriler.get("tur_id"):
                tur = session.get(AktiviteTuru, int(veriler["tur_id"]))
            if tur is None:
                raise ValueError("Aktivite türü seçin.")

            aid = veriler.get("id")
            if aid:
                a = session.get(Aktivite, int(aid))
                if a is None or a.is_deleted:
                    raise ValueError("Aktivite bulunamadı.")
            else:
                a = Aktivite()
                session.add(a)

            a.konu = konu
            a.tur_id = int(tur.id)
            a.durum = (veriler.get("durum") or a.durum or "ACIK").upper()
            a.oncelik = (veriler.get("oncelik") or "NORMAL").upper()
            a.plan_tarih = veriler.get("plan_tarih") or a.plan_tarih
            a.plan_saat = (veriler.get("plan_saat") or "").strip() or None
            a.son_tarih = veriler.get("son_tarih")
            a.tahmini_sure_dk = veriler.get("tahmini_sure_dk") or tur.varsayilan_sure_dk
            a.cari_id = veriler.get("cari_id")
            a.sorumlu_personel_id = veriler.get("sorumlu_personel_id")
            a.kaynak_belge_tur = veriler.get("kaynak_belge_tur")
            a.kaynak_belge_id = veriler.get("kaynak_belge_id")
            a.kaynak_belge_no = (veriler.get("kaynak_belge_no") or "").strip() or None
            a.teslim_partisi = (veriler.get("teslim_partisi") or "").strip() or None
            tt = (veriler.get("teslimat_turu") or "").strip().upper() or None
            if tt and tt not in TESLIMAT_TURLERI:
                raise ValueError(f"Geçersiz teslimat türü: {tt}")
            a.teslimat_turu = tt
            a.sevkiyat_durum = veriler.get("sevkiyat_durum")
            a.adres_metin = (veriler.get("adres_metin") or "").strip() or None
            a.aciklama = (veriler.get("aciklama") or "").strip() or None
            a.updated_at = datetime.now()
            session.flush()

            # Tekillik (kaynak belge varsa)
            if a.kaynak_belge_tur and a.kaynak_belge_id:
                parti = a.teslim_partisi or ""
                mevcut = session.scalar(
                    select(AktiviteTekillik).where(
                        AktiviteTekillik.kaynak_belge_tur == a.kaynak_belge_tur,
                        AktiviteTekillik.kaynak_belge_id == int(a.kaynak_belge_id),
                        AktiviteTekillik.tur_kod == tur.kod,
                        AktiviteTekillik.teslim_partisi == parti,
                    )
                )
                if mevcut and int(mevcut.aktivite_id) != int(a.id):
                    raise ValueError(
                        f"Aynı belge/tür/parti için aktivite zaten var (#{mevcut.aktivite_id})."
                    )
                if mevcut is None and not aid:
                    session.add(
                        AktiviteTekillik(
                            kaynak_belge_tur=a.kaynak_belge_tur,
                            kaynak_belge_id=int(a.kaynak_belge_id),
                            tur_kod=tur.kod,
                            teslim_partisi=parti,
                            aktivite_id=int(a.id),
                        )
                    )
            session.flush()
            return {"id": int(a.id), "konu": a.konu, "durum": a.durum}

    @staticmethod
    def tamamla(aktivite_id: int, *, sonuc_kod: str | None = None) -> dict[str, Any]:
        yazma_zorunlu("yeni_kayit", "satis_duzenleme")
        AktiviteService.ensure_schema()
        with get_session() as session:
            a = session.get(Aktivite, int(aktivite_id))
            if a is None or a.is_deleted:
                raise ValueError("Aktivite bulunamadı.")
            if a.durum == "TAMAMLANDI":
                raise ValueError("Bu aktivite zaten tamamlanmış.")
            if a.durum == "IPTAL":
                raise ValueError("İptal edilmiş aktivite tamamlanamaz.")
            a.durum = "TAMAMLANDI"
            a.tamamlanma_tarihi = datetime.now()
            a.sonuc_kod = (sonuc_kod or "OK").strip()
            a.updated_at = datetime.now()
            # Stok/finans üretmez — yalnızca durum
            session.flush()
            return {"id": int(a.id), "durum": a.durum}

    @staticmethod
    def kaynak_ile_bul(
        *,
        kaynak_belge_tur: str,
        kaynak_belge_id: int,
        tur_kod: str,
        teslim_partisi: str = "",
    ) -> dict[str, Any] | None:
        """Tekillik anahtarıyla mevcut aktiviteyi döndürür."""
        AktiviteService.ensure_schema()
        parti = teslim_partisi or ""
        with get_session() as session:
            tek = session.scalar(
                select(AktiviteTekillik).where(
                    AktiviteTekillik.kaynak_belge_tur == kaynak_belge_tur,
                    AktiviteTekillik.kaynak_belge_id == int(kaynak_belge_id),
                    AktiviteTekillik.tur_kod == tur_kod,
                    AktiviteTekillik.teslim_partisi == parti,
                )
            )
            if tek is None:
                return None
            a = session.get(Aktivite, int(tek.aktivite_id))
            if a is None or a.is_deleted:
                return None
            return {
                "id": int(a.id),
                "konu": a.konu,
                "durum": a.durum,
                "aciklama": a.aciklama,
            }

    @staticmethod
    def kaynak_ile_kaydet_veya_guncelle(veriler: dict[str, Any]) -> dict[str, Any]:
        """Kaynak belge tekilliği: varsa açık kaydı güncelle, yoksa oluştur.

        Tamamlanmış/iptal kayıt üzerine yeni açık görev açılmaz; mevcut kimlik korunur
        ve durum yeniden ACIK yapılmaz (yeniden açma ayrı yetkili işlemdir).
        """
        yazma_zorunlu("yeni_kayit", "satis_duzenleme", "stok_duzenleme")
        kaynak_tur = (veriler.get("kaynak_belge_tur") or "").strip()
        kaynak_id = veriler.get("kaynak_belge_id")
        tur_kod = (veriler.get("tur_kod") or "").strip()
        if not kaynak_tur or not kaynak_id or not tur_kod:
            raise ValueError("Kaynak belge ve tür zorunlu.")
        parti = (veriler.get("teslim_partisi") or "").strip()
        mevcut = AktiviteService.kaynak_ile_bul(
            kaynak_belge_tur=kaynak_tur,
            kaynak_belge_id=int(kaynak_id),
            tur_kod=tur_kod,
            teslim_partisi=parti,
        )
        payload = dict(veriler)
        if mevcut:
            payload["id"] = mevcut["id"]
            # Kapalı işi sessizce çoğaltma / yeniden açma
            if mevcut["durum"] in ("TAMAMLANDI", "IPTAL"):
                return {"id": mevcut["id"], "konu": mevcut["konu"], "durum": mevcut["durum"], "guncellendi": False}
            payload.setdefault("durum", mevcut["durum"])
        return {**AktiviteService.kaydet(payload), "guncellendi": bool(mevcut)}

    @staticmethod
    def ertele(
        aktivite_id: int,
        *,
        yeni_tarih: date,
        gerekce: str = "",
        yeni_saat: str | None = None,
    ) -> dict[str, Any]:
        """Plan tarihini erteler; ilk son_tarih korunur (gecikme raporu için)."""
        yazma_zorunlu("yeni_kayit", "satis_duzenleme")
        AktiviteService.ensure_schema()
        with get_session() as session:
            a = session.get(Aktivite, int(aktivite_id))
            if a is None or a.is_deleted:
                raise ValueError("Aktivite bulunamadı.")
            if a.durum in ("TAMAMLANDI", "IPTAL"):
                raise ValueError("Kapalı aktivite ertelenemez.")
            eski = a.plan_tarih
            if a.son_tarih is None and eski is not None:
                a.son_tarih = eski
            a.plan_tarih = yeni_tarih
            if yeni_saat is not None:
                a.plan_saat = (yeni_saat or "").strip() or None
            not_satir = f"Erteleme: {eski} → {yeni_tarih}"
            if gerekce:
                not_satir += f" ({gerekce.strip()})"
            onceki = (a.aciklama or "").rstrip()
            a.aciklama = f"{onceki}\n{not_satir}".strip() if onceki else not_satir
            a.updated_at = datetime.now()
            session.flush()
            return {"id": int(a.id), "plan_tarih": a.plan_tarih, "son_tarih": a.son_tarih}

    @staticmethod
    def ata(
        aktivite_id: int,
        *,
        yeni_sorumlu_id: int | None,
        gerekce: str = "",
    ) -> dict[str, Any]:
        """Sorumluyu değiştirir; görev numarası (id) aynı kalır."""
        yazma_zorunlu("yeni_kayit", "satis_duzenleme")
        AktiviteService.ensure_schema()
        with get_session() as session:
            a = session.get(Aktivite, int(aktivite_id))
            if a is None or a.is_deleted:
                raise ValueError("Aktivite bulunamadı.")
            if a.durum in ("TAMAMLANDI", "IPTAL"):
                raise ValueError("Kapalı aktivite atanamaz.")
            eski = a.sorumlu_personel_id
            a.sorumlu_personel_id = int(yeni_sorumlu_id) if yeni_sorumlu_id else None
            not_satir = f"Devir: sorumlu {eski} → {a.sorumlu_personel_id}"
            if gerekce:
                not_satir += f" ({gerekce.strip()})"
            onceki = (a.aciklama or "").rstrip()
            a.aciklama = f"{onceki}\n{not_satir}".strip() if onceki else not_satir
            a.updated_at = datetime.now()
            session.flush()
            return {"id": int(a.id), "sorumlu_personel_id": a.sorumlu_personel_id}

    SEVKIYAT_DURUMLARI = (
        "HAZIRLANIYOR",
        "HAZIR",
        "YUKLENDI",
        "YOLDA",
        "KISMI",
        "TESLIM",
        "TESLIM_EDILEMEDI",
    )

    @staticmethod
    def sevkiyat_durum_guncelle(
        aktivite_id: int,
        *,
        sevkiyat_durum: str,
    ) -> dict[str, Any]:
        """Sevkiyat alt durumu; stok/finans üretmez. Genel durumla tutarlı tutulur."""
        yazma_zorunlu("yeni_kayit", "satis_duzenleme")
        kod = (sevkiyat_durum or "").strip().upper()
        if kod not in AktiviteService.SEVKIYAT_DURUMLARI:
            raise ValueError(f"Geçersiz sevkiyat durumu: {sevkiyat_durum}")
        AktiviteService.ensure_schema()
        with get_session() as session:
            a = session.get(Aktivite, int(aktivite_id))
            if a is None or a.is_deleted:
                raise ValueError("Aktivite bulunamadı.")
            if a.durum in ("TAMAMLANDI", "IPTAL"):
                raise ValueError("Kapalı aktivitede sevkiyat durumu değişmez.")
            a.sevkiyat_durum = kod
            # Genel durum eşlemesi (talimat §5)
            if kod in ("YUKLENDI", "YOLDA"):
                a.durum = "DEVAM"
            elif kod == "KISMI":
                a.durum = "BEKLEMEDE"
            elif kod == "TESLIM":
                # Kalan miktar kontrolü yoksa tamamlandı sayma — yalnız alt durum
                a.durum = "DEVAM"
            elif kod == "TESLIM_EDILEMEDI":
                a.durum = "BEKLEMEDE"
            a.updated_at = datetime.now()
            session.flush()
            return {
                "id": int(a.id),
                "sevkiyat_durum": a.sevkiyat_durum,
                "durum": a.durum,
            }

    @staticmethod
    def teslimat_turleri() -> tuple[str, ...]:
        return TESLIMAT_TURLERI

    # ------------------------------------------------------------------ Sefer / rota

    @staticmethod
    def harita_saglayici_durumu() -> dict[str, Any]:
        """Harita anahtarı yoksa sahte mesafe üretilmez; durum açık döner."""
        import os

        anahtar = (os.environ.get("CIN_HARITA_API_KEY") or "").strip()
        if anahtar:
            return {
                "bagli": True,
                "saglayici": (os.environ.get("CIN_HARITA_SAGLAYICI") or "ozel").strip(),
                "uyari": None,
            }
        return {
            "bagli": False,
            "saglayici": None,
            "uyari": (
                "Harita sağlayıcı anahtarı yok (CIN_HARITA_API_KEY). "
                "Liste ve elle planlama kullanılabilir; gerçek yol ağı hesabı çalışmaz. "
                "Sahte mesafe üretilmez."
            ),
        }

    @staticmethod
    def sefer_olustur(veriler: dict[str, Any]) -> dict[str, Any]:
        yazma_zorunlu("yeni_kayit", "satis_duzenleme")
        AktiviteService.ensure_schema()
        tarih = veriler.get("sefer_tarih") or date.today()
        if not isinstance(tarih, date):
            raise ValueError("Sefer tarihi geçersiz.")
        sefer_no = int(veriler.get("sefer_no") or 1)
        if sefer_no < 1:
            raise ValueError("Sefer numarası 1 veya daha büyük olmalı.")
        arac = (veriler.get("arac_kod") or "").strip() or None
        gorevli = veriler.get("gorevli_personel_id")
        with get_session() as session:
            # Aynı gün/araç veya görevli çakışan aktif sefer
            if arac or gorevli:
                q = select(AktiviteSefer).where(
                    AktiviteSefer.sefer_tarih == tarih,
                    AktiviteSefer.is_deleted.is_(False),
                    AktiviteSefer.durum.in_(
                        ("TASLAK", "PLANLANDI", "KESINLESTI", "YOLDA")
                    ),
                )
                for s in session.scalars(q).all():
                    if arac and s.arac_kod == arac and int(s.sefer_no) != sefer_no:
                        # Aynı araç aynı gün farklı sefer OK if sequential; block only overlap flag
                        pass
                    if gorevli and s.gorevli_personel_id == int(gorevli):
                        if int(s.sefer_no) == sefer_no:
                            raise ValueError(
                                f"Görevli zaten bu gün sefer #{s.sefer_no} içinde (#{s.id})."
                            )
            mevcut = session.scalar(
                select(AktiviteSefer).where(
                    AktiviteSefer.sefer_tarih == tarih,
                    AktiviteSefer.sefer_no == sefer_no,
                    AktiviteSefer.is_deleted.is_(False),
                )
            )
            if mevcut is not None:
                raise ValueError(f"{tarih} için sefer #{sefer_no} zaten var (#{mevcut.id}).")
            harita = AktiviteService.harita_saglayici_durumu()
            s = AktiviteSefer(
                sefer_tarih=tarih,
                sefer_no=sefer_no,
                durum="TASLAK",
                arac_kod=arac,
                arac_adi=(veriler.get("arac_adi") or "").strip() or None,
                gorevli_personel_id=int(gorevli) if gorevli else None,
                baslangic_adres=(veriler.get("baslangic_adres") or _VARSAYILAN_BASLANGIC).strip(),
                donus_adres=(veriler.get("donus_adres") or _VARSAYILAN_BASLANGIC).strip(),
                cikis_saat=(veriler.get("cikis_saat") or "09:00").strip(),
                en_gec_donus_saat=(veriler.get("en_gec_donus_saat") or "").strip() or None,
                rota_modu="ELLE",
                harita_saglayici=harita.get("saglayici"),
                harita_uyari=harita.get("uyari"),
            )
            session.add(s)
            session.flush()
            return AktiviteService._sefer_dict(session, s)

    @staticmethod
    def _sefer_dict(session, s: AktiviteSefer) -> dict[str, Any]:
        duraklar = list(
            session.scalars(
                select(AktiviteSeferDurak)
                .where(AktiviteSeferDurak.sefer_id == int(s.id))
                .order_by(AktiviteSeferDurak.sira)
            ).all()
        )
        detay = []
        for d in duraklar:
            a = session.get(Aktivite, int(d.aktivite_id))
            detay.append(
                {
                    "durak_id": int(d.id),
                    "sira": int(d.sira),
                    "aktivite_id": int(d.aktivite_id),
                    "konu": a.konu if a else "?",
                    "adres_metin": (a.adres_metin if a else None),
                    "yol_dk_onceki": d.yol_dk_onceki,
                    "is_dk": d.is_dk,
                    "tahmini_varis": d.tahmini_varis,
                    "planlanamadi_neden": d.planlanamadi_neden,
                }
            )
        return {
            "id": int(s.id),
            "sefer_tarih": s.sefer_tarih,
            "sefer_no": int(s.sefer_no),
            "durum": s.durum,
            "arac_kod": s.arac_kod,
            "arac_adi": s.arac_adi,
            "gorevli_personel_id": s.gorevli_personel_id,
            "baslangic_adres": s.baslangic_adres,
            "donus_adres": s.donus_adres,
            "cikis_saat": s.cikis_saat,
            "en_gec_donus_saat": s.en_gec_donus_saat,
            "rota_modu": s.rota_modu,
            "rota_ozet": s.rota_ozet,
            "tahmini_yol_dk": s.tahmini_yol_dk,
            "tahmini_is_dk": s.tahmini_is_dk,
            "tahmini_toplam_dk": s.tahmini_toplam_dk,
            "tahmini_donus_saat": s.tahmini_donus_saat,
            "harita_saglayici": s.harita_saglayici,
            "harita_uyari": s.harita_uyari,
            "duraklar": detay,
        }

    @staticmethod
    def sefer_getir(sefer_id: int) -> dict[str, Any] | None:
        AktiviteService.ensure_schema()
        with get_session() as session:
            s = session.get(AktiviteSefer, int(sefer_id))
            if s is None or s.is_deleted:
                return None
            return AktiviteService._sefer_dict(session, s)

    @staticmethod
    def sefer_listele(*, sefer_tarih: date | None = None, limit: int = 50) -> list[dict[str, Any]]:
        AktiviteService.ensure_schema()
        gun = sefer_tarih or date.today()
        with get_session() as session:
            q = (
                select(AktiviteSefer)
                .where(
                    AktiviteSefer.sefer_tarih == gun,
                    AktiviteSefer.is_deleted.is_(False),
                )
                .order_by(AktiviteSefer.sefer_no)
                .limit(limit)
            )
            return [AktiviteService._sefer_dict(session, s) for s in session.scalars(q).all()]

    @staticmethod
    def sefer_durak_ekle(sefer_id: int, aktivite_id: int) -> dict[str, Any]:
        """Dış işi sefere ekler. Aynı açık aktivite iki aktif seferde olamaz."""
        yazma_zorunlu("yeni_kayit", "satis_duzenleme")
        AktiviteService.ensure_schema()
        with get_session() as session:
            s = session.get(AktiviteSefer, int(sefer_id))
            if s is None or s.is_deleted:
                raise ValueError("Sefer bulunamadı.")
            if s.durum in ("TAMAMLANDI", "IPTAL", "YOLDA"):
                raise ValueError(f"«{s.durum}» sefere durak eklenemez.")
            a = session.get(Aktivite, int(aktivite_id))
            if a is None or a.is_deleted:
                raise ValueError("Aktivite bulunamadı.")
            if a.durum in ("TAMAMLANDI", "IPTAL"):
                raise ValueError("Kapalı aktivite sefere alınamaz.")
            # Eksik adres → durak eklenebilir ama kesinleştirme engeli
            baska = session.execute(
                select(AktiviteSeferDurak.id)
                .join(AktiviteSefer, AktiviteSefer.id == AktiviteSeferDurak.sefer_id)
                .where(
                    AktiviteSeferDurak.aktivite_id == int(aktivite_id),
                    AktiviteSefer.is_deleted.is_(False),
                    AktiviteSefer.durum.in_(
                        ("TASLAK", "PLANLANDI", "KESINLESTI", "YOLDA")
                    ),
                    AktiviteSefer.id != int(sefer_id),
                )
                .limit(1)
            ).first()
            if baska is not None:
                raise ValueError(
                    f"Aktivite #{aktivite_id} başka aktif seferde (çift yükleme engellendi)."
                )
            mevcut = session.scalar(
                select(AktiviteSeferDurak).where(
                    AktiviteSeferDurak.sefer_id == int(sefer_id),
                    AktiviteSeferDurak.aktivite_id == int(aktivite_id),
                )
            )
            if mevcut is not None:
                return AktiviteService._sefer_dict(session, s)
            max_sira = session.scalar(
                select(AktiviteSeferDurak.sira)
                .where(AktiviteSeferDurak.sefer_id == int(sefer_id))
                .order_by(AktiviteSeferDurak.sira.desc())
                .limit(1)
            )
            sira = int(max_sira or 0) + 1
            neden = None
            if not (a.adres_metin or "").strip():
                neden = "Adres eksik — rota kesinleştirilemez"
            session.add(
                AktiviteSeferDurak(
                    sefer_id=int(sefer_id),
                    aktivite_id=int(aktivite_id),
                    sira=sira,
                    is_dk=int(a.tahmini_sure_dk or 30),
                    planlanamadi_neden=neden,
                )
            )
            s.updated_at = datetime.now()
            session.flush()
            return AktiviteService._sefer_dict(session, s)

    @staticmethod
    def sefer_durak_cikar(sefer_id: int, aktivite_id: int) -> dict[str, Any]:
        yazma_zorunlu("yeni_kayit", "satis_duzenleme")
        AktiviteService.ensure_schema()
        with get_session() as session:
            s = session.get(AktiviteSefer, int(sefer_id))
            if s is None or s.is_deleted:
                raise ValueError("Sefer bulunamadı.")
            if s.durum in ("YOLDA", "TAMAMLANDI"):
                raise ValueError("Yoldaki / tamamlanan seferden durak çıkarılamaz.")
            d = session.scalar(
                select(AktiviteSeferDurak).where(
                    AktiviteSeferDurak.sefer_id == int(sefer_id),
                    AktiviteSeferDurak.aktivite_id == int(aktivite_id),
                )
            )
            if d is not None:
                session.delete(d)
                session.flush()
                # Sıraları sıkıştır
                kalan = list(
                    session.scalars(
                        select(AktiviteSeferDurak)
                        .where(AktiviteSeferDurak.sefer_id == int(sefer_id))
                        .order_by(AktiviteSeferDurak.sira)
                    ).all()
                )
                for i, k in enumerate(kalan, start=1):
                    k.sira = i
            s.updated_at = datetime.now()
            session.flush()
            return AktiviteService._sefer_dict(session, s)

    @staticmethod
    def sefer_durak_sirala(sefer_id: int, aktivite_idleri: list[int]) -> dict[str, Any]:
        """Elle sıra — aktivite_id listesi yeni sıra."""
        yazma_zorunlu("yeni_kayit", "satis_duzenleme")
        AktiviteService.ensure_schema()
        with get_session() as session:
            s = session.get(AktiviteSefer, int(sefer_id))
            if s is None or s.is_deleted:
                raise ValueError("Sefer bulunamadı.")
            duraklar = {
                int(d.aktivite_id): d
                for d in session.scalars(
                    select(AktiviteSeferDurak).where(
                        AktiviteSeferDurak.sefer_id == int(sefer_id)
                    )
                ).all()
            }
            if set(int(x) for x in aktivite_idleri) != set(duraklar.keys()):
                raise ValueError("Sıra listesi sefer duraklarıyla eşleşmiyor.")
            # Geçici sıra çakışması olmasın
            for i, d in enumerate(duraklar.values(), start=1000):
                d.sira = i
            session.flush()
            for i, aid in enumerate(aktivite_idleri, start=1):
                duraklar[int(aid)].sira = i
            s.rota_modu = "ELLE"
            s.updated_at = datetime.now()
            session.flush()
            return AktiviteService._sefer_dict(session, s)

    @staticmethod
    def _saat_ekle(saat: str, dakika: int) -> str:
        h, m = (saat or "09:00").split(":")[:2]
        toplam = int(h) * 60 + int(m) + int(dakika)
        return f"{(toplam // 60) % 24:02d}:{toplam % 60:02d}"

    @staticmethod
    def sefer_rota_hesapla(
        sefer_id: int, *, mod: str = "TEST_VERISI"
    ) -> dict[str, Any]:
        """Rota süresi hesabı.

        TEST_VERISI: talimat sabit yol dakikaları (kabul senaryosu).
        ELLE: yalnız iş süreleri; yol 0 (mesafe uydurulmaz).
        SAGLAYICI: anahtar yoksa hata; sahte yol üretilmez.
        """
        yazma_zorunlu("yeni_kayit", "satis_duzenleme")
        kod = (mod or "TEST_VERISI").strip().upper()
        if kod not in ("ELLE", "TEST_VERISI", "SAGLAYICI"):
            raise ValueError("rota modu ELLE | TEST_VERISI | SAGLAYICI olmalı.")
        AktiviteService.ensure_schema()
        harita = AktiviteService.harita_saglayici_durumu()
        if kod == "SAGLAYICI" and not harita["bagli"]:
            raise ValueError(harita["uyari"] or "Harita sağlayıcı bağlı değil.")

        with get_session() as session:
            s = session.get(AktiviteSefer, int(sefer_id))
            if s is None or s.is_deleted:
                raise ValueError("Sefer bulunamadı.")
            duraklar = list(
                session.scalars(
                    select(AktiviteSeferDurak)
                    .where(AktiviteSeferDurak.sefer_id == int(sefer_id))
                    .order_by(AktiviteSeferDurak.sira)
                ).all()
            )
            if not duraklar:
                raise ValueError("Seferde durak yok.")
            eksik = [d for d in duraklar if d.planlanamadi_neden]
            if eksik and kod != "ELLE":
                raise ValueError(
                    "Eksik bilgili duraklar var; önce adresleri tamamlayın veya ELLE modunu kullanın."
                )

            yol_toplam = 0
            is_toplam = 0
            cikis = s.cikis_saat or "09:00"
            simdi_dk = 0
            n = len(duraklar)
            for i, d in enumerate(duraklar):
                a = session.get(Aktivite, int(d.aktivite_id))
                is_dk = int(d.is_dk or (a.tahmini_sure_dk if a else 30) or 30)
                d.is_dk = is_dk
                if kod == "TEST_VERISI":
                    # Ardışık: çıkış→1, 1→2, ... son→dönüş ayrı
                    yol = _TEST_YOL_DK[i] if i < len(_TEST_YOL_DK) else 15
                elif kod == "SAGLAYICI":
                    raise ValueError(
                        "Sağlayıcı yol hesabı henüz bağlı değil; anahtar tanımlı olsa da "
                        "bu sürümde TEST_VERISI veya ELLE kullanın."
                    )
                else:
                    yol = 0
                d.yol_dk_onceki = yol
                simdi_dk += yol
                d.tahmini_varis = AktiviteService._saat_ekle(cikis, simdi_dk)
                simdi_dk += is_dk
                yol_toplam += yol
                is_toplam += is_dk

            # Dönüş: test dizisinde durak sayısından sonraki değer (6 durak → dizi tükenir, dönüş 0;
            # 5 durak → 6. değer dönüş: 15+10+25+20+15+20=105)
            if kod == "TEST_VERISI" and n < len(_TEST_YOL_DK):
                donus_yol = _TEST_YOL_DK[n]
            else:
                donus_yol = 0
            yol_toplam += donus_yol
            simdi_dk += donus_yol
            toplam = yol_toplam + is_toplam
            s.rota_modu = kod
            s.tahmini_yol_dk = yol_toplam
            s.tahmini_is_dk = is_toplam
            s.tahmini_toplam_dk = toplam
            s.tahmini_donus_saat = AktiviteService._saat_ekle(cikis, simdi_dk)
            s.harita_uyari = harita.get("uyari")
            s.rota_ozet = (
                f"mod={kod}; yol={yol_toplam} dk; iş={is_toplam} dk; "
                f"toplam={toplam} dk; dönüş≈{s.tahmini_donus_saat}"
            )
            if kod == "TEST_VERISI":
                s.rota_ozet += " (sabit test yol verisi — gerçek sağlayıcı değil)"
            s.updated_at = datetime.now()
            session.flush()
            return AktiviteService._sefer_dict(session, s)

    @staticmethod
    def sefer_kesinlestir(sefer_id: int) -> dict[str, Any]:
        yazma_zorunlu("yeni_kayit", "satis_duzenleme")
        AktiviteService.ensure_schema()
        with get_session() as session:
            s = session.get(AktiviteSefer, int(sefer_id))
            if s is None or s.is_deleted:
                raise ValueError("Sefer bulunamadı.")
            duraklar = list(
                session.scalars(
                    select(AktiviteSeferDurak).where(
                        AktiviteSeferDurak.sefer_id == int(sefer_id)
                    )
                ).all()
            )
            if not duraklar:
                raise ValueError("Duraksız sefer kesinleştirilemez.")
            for d in duraklar:
                if d.planlanamadi_neden:
                    raise ValueError(
                        f"Durak #{d.sira}: {d.planlanamadi_neden}. "
                        "Eksik bilgi tamamlanmadan kesinleştirilemez."
                    )
            s.durum = "KESINLESTI"
            s.updated_at = datetime.now()
            session.flush()
            return AktiviteService._sefer_dict(session, s)
