"""Stok sayım fişi servisi — sistem/sayılan farkını GİRİŞ/ÇIKIŞ hareketiyle düzeltir."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from database.access import yazma_zorunlu
from database.database import Base, company_db, get_session
from database.models.stok import Depo, StokHareketi, StokKarti, StokLotu
from database.models.stok_sayim import StokSayimFisi, StokSayimSatiri
from database.satis_siparisi_service import decimal

MALIYET_FIFO_SON_LOT = "FIFO son lot"
MALIYET_SON_ALIS = "Son geçerli alış"
MALIYET_KULLANICI = "Kullanıcı"
MALIYET_KAYNAKLARI = (MALIYET_FIFO_SON_LOT, MALIYET_SON_ALIS, MALIYET_KULLANICI)


class StokSayimService:
    @staticmethod
    def schema_hazirla() -> None:
        import database.models.stok_sayim  # noqa: F401
        from database.modul_sema import eksik_kolonlari_ekle

        if company_db.engine is None:
            return
        Base.metadata.create_all(company_db.engine)
        eksik_kolonlari_ekle(
            company_db.engine,
            "stok_sayim_satirlari",
            {"birim_maliyet": "NUMERIC(18, 4)", "maliyet_kaynagi": "VARCHAR(30)"},
        )

    @staticmethod
    def _maliyet_onerisi(session, stok_id: int, depo_id: int | None) -> dict[str, Any] | None:
        """Sayım fazlası için geçerli birim maliyet önerisi (temel birim başına).

        Sıra: depodaki (yoksa tüm depolardaki) en son girişli maliyetli lot → son maliyetli
        FATURA GİRİŞ hareketi. Sayım lotları (tedarikçi=SAYIM) kaynak sayılmaz. Bulunamazsa None.
        """
        sifirdan_buyuk = StokLotu.birim_maliyet > 0
        sayim_degil = func.coalesce(StokLotu.tedarikci, "") != "SAYIM"
        kosullar: list[tuple] = [(StokLotu.depo_id == int(depo_id),)] if depo_id else []
        kosullar.append(())
        for depo_kosulu in kosullar:
            lot = session.scalar(
                select(StokLotu)
                .where(StokLotu.stok_id == int(stok_id), sifirdan_buyuk, sayim_degil, *depo_kosulu)
                .order_by(StokLotu.giris_tarihi.desc(), StokLotu.id.desc())
                .limit(1)
            )
            if lot is not None:
                return {
                    "birim_maliyet": Decimal(str(lot.birim_maliyet)),
                    "kaynak": MALIYET_FIFO_SON_LOT,
                    "aciklama": f"Lot {lot.lot_no or lot.id} ({lot.giris_tarihi:%d.%m.%Y})",
                }
        hareket = session.scalar(
            select(StokHareketi)
            .where(
                StokHareketi.stok_id == int(stok_id),
                StokHareketi.hareket_turu == "FATURA GİRİŞ",
                StokHareketi.birim_maliyet > 0,
            )
            .order_by(StokHareketi.tarih.desc(), StokHareketi.id.desc())
            .limit(1)
        )
        if hareket is not None:
            return {
                "birim_maliyet": Decimal(str(hareket.birim_maliyet)),
                "kaynak": MALIYET_SON_ALIS,
                "aciklama": f"{hareket.belge_no or ''} ({hareket.tarih:%d.%m.%Y})".strip(),
            }
        return None

    @staticmethod
    def maliyet_onerisi(stok_id: int, depo_id: int | None) -> dict[str, Any] | None:
        with get_session() as session:
            return StokSayimService._maliyet_onerisi(session, stok_id, depo_id)

    @staticmethod
    def _fazla_maliyeti(session, veri: dict[str, Any], stok: StokKarti, depo_id: int) -> tuple[Decimal, str]:
        """Sayım fazlası satırının maliyeti; 0 / belirsiz maliyetle giriş yapılmaz."""
        girilen = veri.get("birim_maliyet")
        oneri = StokSayimService._maliyet_onerisi(session, stok.id, depo_id)
        if girilen not in (None, ""):
            maliyet = decimal(girilen, f"{stok.stok_kodu} birim maliyet", Decimal("0"))
            if maliyet <= 0:
                raise ValueError(
                    f"{stok.stok_kodu} — {stok.stok_adi}: sayım fazlası 0 maliyetle stoğa alınamaz; "
                    "geçerli bir birim maliyet girin."
                )
            kaynak = (veri.get("maliyet_kaynagi") or "").strip()
            if kaynak not in MALIYET_KAYNAKLARI or (
                kaynak != MALIYET_KULLANICI and (oneri is None or oneri["birim_maliyet"] != maliyet)
            ):
                kaynak = MALIYET_KULLANICI
            return maliyet, kaynak
        if oneri is None:
            raise ValueError(
                f"{stok.stok_kodu} — {stok.stok_adi}: sayım fazlası için geçerli maliyet bulunamadı "
                "(lot / alış yok). Sayım ekranında birim maliyeti girin."
            )
        return oneri["birim_maliyet"], oneri["kaynak"]

    @staticmethod
    def fis_no() -> str:
        StokSayimService.schema_hazirla()
        onek = "SYM"
        with get_session() as session:
            son = session.scalar(
                select(StokSayimFisi.fis_no)
                .where(StokSayimFisi.fis_no.like(f"{onek}%"))
                .order_by(StokSayimFisi.fis_no.desc())
            )
        if not son:
            return f"{onek}000001"
        try:
            sira = int(str(son)[len(onek) :]) + 1
        except ValueError:
            sira = 1
        return f"{onek}{sira:06d}"

    @staticmethod
    def listele() -> list[dict[str, Any]]:
        StokSayimService.schema_hazirla()
        with get_session() as session:
            kayitlar = list(
                session.scalars(
                    select(StokSayimFisi)
                    .options(
                        selectinload(StokSayimFisi.depo),
                        selectinload(StokSayimFisi.satirlar),
                    )
                    .order_by(StokSayimFisi.id.desc())
                ).all()
            )
            return [
                {
                    "id": f.id,
                    "fis_no": f.fis_no,
                    "tarih": f.fis_tarihi,
                    "depo": f.depo.ad if f.depo else "",
                    "durum": f.durum,
                    "satir": len(f.satirlar or []),
                    "aciklama": f.aciklama or "",
                }
                for f in kayitlar
            ]

    @staticmethod
    def depo_stok_listesi(depo_id: int) -> list[dict[str, Any]]:
        """Depodaki stoklar ve sistem miktarları."""
        with get_session() as session:
            satirlar = list(
                session.execute(
                    select(
                        StokLotu.stok_id,
                        func.coalesce(func.sum(StokLotu.kalan_miktar), 0),
                    )
                    .where(StokLotu.depo_id == int(depo_id))
                    .group_by(StokLotu.stok_id)
                ).all()
            )
            sonuc = []
            for stok_id, miktar in satirlar:
                stok = session.get(StokKarti, int(stok_id))
                if not stok or not stok.aktif or getattr(stok, "is_deleted", False):
                    continue
                sonuc.append(
                    {
                        "stok_id": int(stok_id),
                        "urun_kodu": stok.stok_kodu,
                        "urun_adi": stok.stok_adi,
                        "birim": stok.birim,
                        "sistem_miktar": Decimal(str(miktar or 0)),
                    }
                )
            sonuc.sort(key=lambda x: x["urun_kodu"])
            return sonuc

    @staticmethod
    def _referans_sistem_miktari(session, stok_id: int, depo_id: int, sayim_zamani: datetime | None) -> Decimal:
        """Depodaki güncel lot bakiyesi; referans zamandan sonra oluşan hareketler geri alınmış hâli."""
        from database.stok_service import CIKIS_HAREKETLERI, GIRIS_HAREKETLERI

        mevcut = Decimal(str(session.scalar(
            select(func.coalesce(func.sum(StokLotu.kalan_miktar), 0)).where(
                StokLotu.stok_id == stok_id, StokLotu.depo_id == depo_id
            )
        ) or 0))
        if sayim_zamani is None:
            return mevcut
        sonraki = session.execute(
            select(StokHareketi.hareket_turu, StokHareketi.miktar).where(
                StokHareketi.stok_id == stok_id,
                StokHareketi.depo_id == depo_id,
                StokHareketi.olusturma_tarihi > sayim_zamani,
            )
        ).all()
        for tur, miktar in sonraki:
            m = Decimal(str(miktar or 0))
            if tur in GIRIS_HAREKETLERI:
                mevcut -= m
            elif tur in CIKIS_HAREKETLERI:
                mevcut += m
        return mevcut

    @staticmethod
    def kaydet_ve_onayla(
        depo_id: int,
        fis_tarihi: date,
        satirlar: list[dict[str, Any]],
        aciklama: str | None = None,
        sube_id: int | None = None,
        sayim_zamani: datetime | None = None,
    ) -> int:
        """
        Sayım satırlarını kaydeder ve farkları tek transaction içinde stoğa yansıtır.
        Pozitif fark → SAYIM GİRİŞ, negatif → SAYIM ÇIKIŞ (FIFO).

        Referans zaman: ``sayim_zamani`` (sayılan miktarın geçerli olduğu an; verilmezse kayıt anı).
        Sistem miktarı ekrandan alınmaz; kayıt anında depodaki lot bakiyesinden, referans zamandan
        sonra oluşturulmuş hareketler geri alınarak yeniden okunur. Fark = sayılan − referans
        sistem miktarı; referanstan sonraki hareketler stokta kalır (aynı satış iki kez düşülmez).
        """
        yazma_zorunlu("stok_duzenleme", "yeni_kayit")
        StokSayimService.schema_hazirla()
        if not satirlar:
            raise ValueError("Sayım satırı yok.")

        with get_session() as session:
            from database.sube_service import SubeService

            sube_id = SubeService.transaction_subesi(session, sube_id)
            depo = session.get(Depo, int(depo_id))
            if not depo:
                raise ValueError("Depo bulunamadı.")

            fis = StokSayimFisi(
                fis_no=StokSayimService.fis_no(),
                sube_id=sube_id,
                fis_tarihi=fis_tarihi,
                depo_id=depo.id,
                durum="TASLAK",
                aciklama=aciklama,
            )
            session.add(fis)
            session.flush()

            fark_var = False
            satir_maliyetleri: list[tuple[Decimal | None, str | None]] = []
            for veri in satirlar:
                ekran = decimal(veri.get("sistem_miktar", 0), "Sistem", Decimal("0"))
                sayilan = decimal(veri["sayilan_miktar"], "Sayılan", Decimal("0"))
                sistem = StokSayimService._referans_sistem_miktari(
                    session, int(veri["stok_id"]), depo.id, sayim_zamani
                )
                fark = sayilan - sistem
                if fark != 0:
                    fark_var = True
                neden = veri.get("fark_nedeni")
                if ekran != sistem:
                    not_ = f"Ekranda {ekran.normalize():f} görünüyordu; sayım anı sistem miktarı {sistem.normalize():f}."
                    neden = f"{neden} — {not_}" if neden else not_
                maliyet = kaynak = None
                if fark > 0:
                    stok = session.get(StokKarti, int(veri["stok_id"]))
                    if not stok:
                        raise ValueError("Stok kartı bulunamadı.")
                    maliyet, kaynak = StokSayimService._fazla_maliyeti(session, veri, stok, depo.id)
                fis.satirlar.append(
                    StokSayimSatiri(
                        stok_id=int(veri["stok_id"]),
                        sistem_miktar=sistem,
                        sayilan_miktar=sayilan,
                        fark=fark,
                        fark_nedeni=(neden or None) and str(neden)[:200],
                        birim_maliyet=maliyet,
                        maliyet_kaynagi=kaynak,
                    )
                )
            session.flush()

            # Stok düzeltmeleri
            for satir in fis.satirlar:
                if satir.fark == 0:
                    continue
                stok = session.get(StokKarti, satir.stok_id)
                if not stok:
                    raise ValueError("Stok kartı bulunamadı.")
                if satir.fark > 0:
                    # Giriş
                    lot = StokLotu(
                        stok_id=stok.id,
                        depo_id=depo.id,
                        lot_no=f"SAYIM-{fis.fis_no}-{stok.id}",
                        tedarikci="SAYIM",
                        giris_tarihi=fis_tarihi,
                        kalan_miktar=satir.fark,
                        birim_maliyet=satir.birim_maliyet,
                    )
                    session.add(lot)
                    session.flush()
                    session.add(
                        StokHareketi(
                            sube_id=sube_id,
                            tarih=fis_tarihi,
                            hareket_turu="SAYIM GİRİŞ",
                            belge_no=fis.fis_no,
                            stok_id=stok.id,
                            depo_id=depo.id,
                            lot_id=lot.id,
                            miktar=satir.fark,
                            birim_maliyet=satir.birim_maliyet,
                        )
                    )
                else:
                    # FIFO çıkış
                    gereken = abs(satir.fark)
                    lotlar = list(
                        session.scalars(
                            select(StokLotu)
                            .where(
                                StokLotu.stok_id == stok.id,
                                StokLotu.depo_id == depo.id,
                                StokLotu.kalan_miktar > 0,
                            )
                            .order_by(StokLotu.giris_tarihi, StokLotu.id)
                        ).all()
                    )
                    mevcut = sum((l.kalan_miktar for l in lotlar), Decimal("0"))
                    if mevcut < gereken:
                        raise ValueError(
                            f"{stok.stok_kodu}: sayım çıkışı için stok yetersiz "
                            f"(mevcut {mevcut}, fark {gereken})."
                        )
                    kalan = gereken
                    for lot in lotlar:
                        if kalan <= 0:
                            break
                        cikan = min(kalan, lot.kalan_miktar)
                        lot.kalan_miktar -= cikan
                        kalan -= cikan
                        session.add(
                            StokHareketi(
                                sube_id=sube_id,
                                tarih=fis_tarihi,
                                hareket_turu="SAYIM ÇIKIŞ",
                                belge_no=fis.fis_no,
                                stok_id=stok.id,
                                depo_id=depo.id,
                                lot_id=lot.id,
                                miktar=cikan,
                                birim_maliyet=lot.birim_maliyet,
                            )
                        )

            fis.durum = "FARK VAR" if fark_var else "TAMAM"
            session.flush()
            return int(fis.id)
