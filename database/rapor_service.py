from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.cari_service import CariService
from database.database import get_session
from database.models.cari import Cari, CariIslem
from database.models.satis_faturasi import SatisFaturasi
from database.models.satis_iade_faturasi import SatisIadeFaturasi
from database.models.alis_faturasi import AlisFaturasi
from database.models.alis_iade_faturasi import AlisIadeFaturasi
from database.models.stok import Depo, StokHareketi, StokKarti, StokLotu
from database.stok_service import CIKIS_HAREKETLERI, GIRIS_HAREKETLERI, StokService
from database.satis_faturasi_service import SatisFaturasiService
from database.satis_iade_faturasi_service import SatisIadeFaturasiService
from database.alis_faturasi_service import AlisFaturasiService
from database.alis_iade_faturasi_service import AlisIadeFaturasiService

MALIYET_YONTEMLERI_RAPOR = (
    "FIFO",
    "SON ALIŞ FİYATI",
    "ORTALAMA ALIŞ FİYATI",
    "AĞIRLIKLI ORTALAMA ALIŞ FİYATI",
)

_MALIYET_ALAN = {
    "FIFO": "fifo_birim_maliyeti",
    "SON ALIŞ FİYATI": "son_alis_birim_maliyeti",
    "ORTALAMA ALIŞ FİYATI": "ortalama_birim_maliyeti",
    "AĞIRLIKLI ORTALAMA ALIŞ FİYATI": "agirlikli_ortalama_birim_maliyeti",
}
_MALIYET_ANAHTAR = {
    "FIFO": "fifo",
    "SON ALIŞ FİYATI": "son_alis",
    "ORTALAMA ALIŞ FİYATI": "ortalama",
    "AĞIRLIKLI ORTALAMA ALIŞ FİYATI": "agirlikli",
}


class RaporService:
    @staticmethod
    def musteri_bakiye_durum(cari_turu: str | None = None) -> list[dict[str, Any]]:
        """Cari bakiye durumu. cari_turu verilirse sadece o tür (Müşteri/Tedarikçi)."""
        bugun = date.today()
        sonuc = []
        for ozet in CariService.listele(cari_turu=cari_turu):
            cari = ozet["cari"]
            if (cari.cari_turu or "") == "Tedarikçi":
                vade_ozet = AlisFaturasiService.bakiye_ozeti(cari.id)
            else:
                vade_ozet = SatisFaturasiService.bakiye_ozeti(cari.id)
            ortalama_vade = vade_ozet.get("ortalama_vade")
            if ortalama_vade and ortalama_vade < bugun and (ozet["bakiye"] or 0) > 0:
                geciken_gun = (bugun - ortalama_vade).days
            else:
                geciken_gun = 0
            sonuc.append({
                "cari_id": cari.id,
                "cari_kodu": cari.cari_kodu,
                "unvan": cari.unvan,
                "cari_turu": cari.cari_turu,
                "aktif": cari.aktif,
                "bakiye": ozet["bakiye"],
                "ortalama_gun": ozet["ortalama_gun"],
                "agirlikli_ortalama_gun": ozet["agirlikli_ortalama_gun"],
                "ortalama_vade": ortalama_vade,
                "vade_bakiyesi": vade_ozet.get("bakiye") or Decimal("0"),
                "geciken_gun": geciken_gun,
            })
        sonuc.sort(key=lambda x: x["bakiye"], reverse=True)
        return sonuc

    @staticmethod
    def musteri_ekstresi(cari_id: int) -> dict[str, Any]:
        """Müşteri ekstresi: hareketler + çalışan bakiye + ağırlıklı valör."""
        detay = CariService.detay(cari_id)
        if not detay:
            raise ValueError("Cari bulunamadı.")
        cari = detay["cari"]
        ozet = next((o for o in CariService.listele() if o["cari"].id == cari_id), None)
        vade_ozet = SatisFaturasiService.bakiye_ozeti(cari_id)

        # Kronolojik sırada çalışan bakiye
        hareketler = sorted(detay["hareketler"], key=lambda h: (h["tarih"], h["belge_no"]))
        calisan = Decimal("0")
        satirlar = []
        for h in hareketler:
            borc = h["borc"] or Decimal("0")
            alacak = h["alacak"] or Decimal("0")
            calisan += borc - alacak
            gun = (date.today() - h["tarih"]).days
            satirlar.append({
                "tarih": h["tarih"],
                "tur": h["tur"],
                "belge_no": h["belge_no"],
                "aciklama": h.get("aciklama") or "",
                "borc": borc,
                "alacak": alacak,
                "bakiye": calisan,
                "gun": gun,
                "kalan": h.get("kalan"),
            })
        return {
            "cari": cari,
            "bakiye": ozet["bakiye"] if ozet else calisan,
            "ortalama_gun": ozet["ortalama_gun"] if ozet else 0,
            "agirlikli_ortalama_gun": ozet["agirlikli_ortalama_gun"] if ozet else 0,
            "ortalama_vade": vade_ozet.get("ortalama_vade"),
            "satirlar": list(reversed(satirlar)),  # yeni üstte
        }

    @staticmethod
    def stok_detayli_ekstre(cari_id: int) -> dict[str, Any]:
        """Fatura bazlı toplam + stok satır ayrıntısı + cari işlemler; çalışan bakiye."""
        with get_session() as session:
            cari = session.get(Cari, cari_id)
            if cari is None:
                raise ValueError("Cari bulunamadı.")

            belgeler: list[dict[str, Any]] = []

            faturalar = session.scalars(
                select(SatisFaturasi)
                .where(SatisFaturasi.cari_id == cari_id, SatisFaturasi.durum != "İPTAL")
                .options(selectinload(SatisFaturasi.satirlar))
                .order_by(SatisFaturasi.fatura_tarihi, SatisFaturasi.id)
            ).all()
            for fatura in faturalar:
                toplam = SatisFaturasiService.toplam(fatura.satirlar)
                stok_satirlari = []
                for satir in fatura.satirlar:
                    net = satir.miktar * satir.birim_fiyat * (
                        Decimal("1") - (satir.iskonto_orani or 0) / Decimal("100")
                    )
                    kdv = net * (satir.kdv_orani or 0) / Decimal("100")
                    genel = net + kdv
                    stok = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == satir.urun_kodu))
                    lot_ozet = satir.lot_cikisi or ""
                    if not lot_ozet and stok:
                        hareketler = session.scalars(
                            select(StokHareketi).where(
                                StokHareketi.belge_no == fatura.fatura_no,
                                StokHareketi.stok_id == stok.id,
                                StokHareketi.hareket_turu == "FATURA ÇIKIŞ",
                            )
                        ).all()
                        parcalar = []
                        for hrk in hareketler:
                            lot = session.get(StokLotu, hrk.lot_id) if hrk.lot_id else None
                            if lot:
                                parcalar.append(f"{lot.lot_no}:{hrk.miktar}")
                        lot_ozet = ", ".join(parcalar)
                    stok_satirlari.append({
                        "urun_kodu": satir.urun_kodu,
                        "urun_adi": satir.urun_adi,
                        "miktar": satir.miktar,
                        "birim": satir.birim,
                        "birim_fiyat": satir.birim_fiyat,
                        "iskonto_orani": satir.iskonto_orani or Decimal("0"),
                        "kdv_orani": satir.kdv_orani or Decimal("0"),
                        "net": net,
                        "kdv": kdv,
                        "genel": genel,
                        "fifo_birim_maliyeti": satir.fifo_birim_maliyeti or Decimal("0"),
                        "lot_cikisi": lot_ozet,
                        "depo": fatura.depo,
                    })
                belgeler.append({
                    "tarih": fatura.fatura_tarihi,
                    "tur": "Satış Faturası",
                    "belge_no": fatura.fatura_no,
                    "aciklama": fatura.aciklama or f"Vade: {fatura.vade_tarihi:%d.%m.%Y}",
                    "borc": toplam["genel_toplam"],
                    "alacak": Decimal("0"),
                    "stok_satirlari": stok_satirlari,
                    "sira": fatura.id,
                })

            iade_belge_nolari: set[str] = set()
            iadeler = session.scalars(
                select(SatisIadeFaturasi)
                .where(SatisIadeFaturasi.cari_id == cari_id, SatisIadeFaturasi.durum != "İPTAL")
                .options(selectinload(SatisIadeFaturasi.satirlar))
                .order_by(SatisIadeFaturasi.iade_tarihi, SatisIadeFaturasi.id)
            ).all()
            for iade in iadeler:
                iade_belge_nolari.add(iade.iade_no)
                toplam = SatisIadeFaturasiService.toplam(iade.satirlar)
                stok_satirlari = []
                for satir in iade.satirlar:
                    net = satir.miktar * satir.birim_fiyat * (
                        Decimal("1") - (satir.iskonto_orani or 0) / Decimal("100")
                    )
                    kdv = net * (satir.kdv_orani or 0) / Decimal("100")
                    genel = net + kdv
                    stok_satirlari.append({
                        "urun_kodu": satir.urun_kodu,
                        "urun_adi": satir.urun_adi,
                        "miktar": satir.miktar,
                        "birim": satir.birim,
                        "birim_fiyat": satir.birim_fiyat,
                        "iskonto_orani": satir.iskonto_orani or Decimal("0"),
                        "kdv_orani": satir.kdv_orani or Decimal("0"),
                        "net": net,
                        "kdv": kdv,
                        "genel": genel,
                        "fifo_birim_maliyeti": satir.fifo_birim_maliyeti or Decimal("0"),
                        "lot_cikisi": satir.lot_no or "",
                        "depo": iade.depo,
                    })
                belgeler.append({
                    "tarih": iade.iade_tarihi,
                    "tur": "Satış İadesi",
                    "belge_no": iade.iade_no,
                    "aciklama": iade.aciklama or "Satış iade faturası",
                    "borc": Decimal("0"),
                    "alacak": toplam["genel_toplam"],
                    "stok_satirlari": stok_satirlari,
                    "sira": iade.id,
                })

            # Alış faturaları (stok girişi)
            alis_faturalar = session.scalars(
                select(AlisFaturasi)
                .where(AlisFaturasi.cari_id == cari_id, AlisFaturasi.durum != "İPTAL")
                .options(selectinload(AlisFaturasi.satirlar))
                .order_by(AlisFaturasi.fatura_tarihi, AlisFaturasi.id)
            ).all()
            for fatura in alis_faturalar:
                toplam = AlisFaturasiService.toplam(fatura.satirlar)
                stok_satirlari = []
                for satir in fatura.satirlar:
                    net = satir.miktar * satir.birim_fiyat * (
                        Decimal("1") - (satir.iskonto_orani or 0) / Decimal("100")
                    )
                    kdv = net * (satir.kdv_orani or 0) / Decimal("100")
                    genel = net + kdv
                    stok_satirlari.append({
                        "urun_kodu": satir.urun_kodu,
                        "urun_adi": satir.urun_adi,
                        "miktar": satir.miktar,
                        "birim": satir.birim,
                        "birim_fiyat": satir.birim_fiyat,
                        "iskonto_orani": satir.iskonto_orani or Decimal("0"),
                        "kdv_orani": satir.kdv_orani or Decimal("0"),
                        "net": net,
                        "kdv": kdv,
                        "genel": genel,
                        "fifo_birim_maliyeti": satir.fifo_birim_maliyeti or Decimal("0"),
                        "lot_cikisi": satir.lot_girisi or "",
                        "depo": fatura.depo,
                    })
                belgeler.append({
                    "tarih": fatura.fatura_tarihi,
                    "tur": "Alış Faturası",
                    "belge_no": fatura.fatura_no,
                    "aciklama": fatura.aciklama or f"Vade: {fatura.vade_tarihi:%d.%m.%Y}",
                    "borc": toplam["genel_toplam"],
                    "alacak": Decimal("0"),
                    "stok_satirlari": stok_satirlari,
                    "sira": fatura.id,
                })

            alis_iade_nolari: set[str] = set()
            alis_iadeler = session.scalars(
                select(AlisIadeFaturasi)
                .where(AlisIadeFaturasi.cari_id == cari_id, AlisIadeFaturasi.durum != "İPTAL")
                .options(selectinload(AlisIadeFaturasi.satirlar))
                .order_by(AlisIadeFaturasi.iade_tarihi, AlisIadeFaturasi.id)
            ).all()
            for iade in alis_iadeler:
                alis_iade_nolari.add(iade.iade_no)
                toplam = AlisIadeFaturasiService.toplam(iade.satirlar)
                stok_satirlari = []
                for satir in iade.satirlar:
                    net = satir.miktar * satir.birim_fiyat * (
                        Decimal("1") - (satir.iskonto_orani or 0) / Decimal("100")
                    )
                    kdv = net * (satir.kdv_orani or 0) / Decimal("100")
                    genel = net + kdv
                    stok_satirlari.append({
                        "urun_kodu": satir.urun_kodu,
                        "urun_adi": satir.urun_adi,
                        "miktar": satir.miktar,
                        "birim": satir.birim,
                        "birim_fiyat": satir.birim_fiyat,
                        "iskonto_orani": satir.iskonto_orani or Decimal("0"),
                        "kdv_orani": satir.kdv_orani or Decimal("0"),
                        "net": net,
                        "kdv": kdv,
                        "genel": genel,
                        "fifo_birim_maliyeti": satir.fifo_birim_maliyeti or Decimal("0"),
                        "lot_cikisi": satir.lot_cikisi or satir.lot_no or "",
                        "depo": iade.depo,
                    })
                belgeler.append({
                    "tarih": iade.iade_tarihi,
                    "tur": "Alış İadesi",
                    "belge_no": iade.iade_no,
                    "aciklama": iade.aciklama or "Satın alma iade faturası",
                    "borc": Decimal("0"),
                    "alacak": toplam["genel_toplam"],
                    "stok_satirlari": stok_satirlari,
                    "sira": iade.id,
                })

            for islem in session.scalars(
                select(CariIslem)
                .where(CariIslem.cari_id == cari_id)
                .order_by(CariIslem.tarih, CariIslem.id)
            ).all():
                # İade faturaları stok satırlarıyla eklendi; CariIslem çift sayılmasın.
                if islem.islem_turu == "Satış İadesi" and islem.belge_no in iade_belge_nolari:
                    continue
                if islem.islem_turu == "Alış İadesi" and islem.belge_no in alis_iade_nolari:
                    continue
                belgeler.append({
                    "tarih": islem.tarih,
                    "tur": islem.islem_turu,
                    "belge_no": islem.belge_no,
                    "aciklama": islem.aciklama or "",
                    "borc": islem.borc or Decimal("0"),
                    "alacak": islem.alacak or Decimal("0"),
                    "stok_satirlari": [],
                    "sira": islem.id,
                })

            def _sira_tur(tur: str) -> int:
                if tur in ("Satış Faturası", "Alış Faturası"):
                    return 0
                if tur in ("Satış İadesi", "Alış İadesi"):
                    return 1
                return 2

            belgeler.sort(key=lambda b: (b["tarih"], _sira_tur(b["tur"]), b["sira"]))
            calisan = Decimal("0")
            for belge in belgeler:
                calisan += (belge["borc"] or Decimal("0")) - (belge["alacak"] or Decimal("0"))
                belge["bakiye"] = calisan

            ozet = next((o for o in CariService.listele() if o["cari"].id == cari_id), None)
            return {
                "cari": cari,
                "bakiye": ozet["bakiye"] if ozet else calisan,
                "belgeler": list(reversed(belgeler)),
                "fatura_sayisi": sum(1 for b in belgeler if b["tur"] in ("Satış Faturası", "Alış Faturası")),
                "iade_sayisi": sum(1 for b in belgeler if b["tur"] in ("Satış İadesi", "Alış İadesi")),
                "belge_sayisi": len(belgeler),
                "belge_turleri": sorted({b["tur"] for b in belgeler}),
            }


    @staticmethod
    def tarih_aralikli_tahsilat_odeme(
        baslangic: date | None = None,
        bitis: date | None = None,
        tur: str = "hepsi",
    ) -> dict[str, Any]:
        """Tarih aralıklı tahsilat / ödeme (cari hareketler). tur: tahsilat|odeme|hepsi."""
        with get_session() as session:
            islemler = session.scalars(
                select(CariIslem).order_by(CariIslem.tarih.desc(), CariIslem.id.desc())
            ).all()
            satirlar = []
            toplam_tahsilat = Decimal("0")
            toplam_odeme = Decimal("0")
            for islem in islemler:
                if baslangic and islem.tarih < baslangic:
                    continue
                if bitis and islem.tarih > bitis:
                    continue
                alacak = islem.alacak or Decimal("0")
                borc = islem.borc or Decimal("0")
                if tur == "tahsilat" and alacak <= 0:
                    continue
                if tur == "odeme" and borc <= 0:
                    continue
                if tur == "hepsi" and alacak <= 0 and borc <= 0:
                    continue
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
                    "borc": borc,
                    "alacak": alacak,
                }
                if alacak > 0:
                    toplam_tahsilat += alacak
                if borc > 0:
                    toplam_odeme += borc
                if tur == "tahsilat" and alacak > 0:
                    satirlar.append(kayit)
                elif tur == "odeme" and borc > 0:
                    satirlar.append(kayit)
                elif tur == "hepsi":
                    satirlar.append(kayit)
            return {
                "satirlar": satirlar,
                "toplam_tahsilat": toplam_tahsilat,
                "toplam_odeme": toplam_odeme,
                "baslangic": baslangic,
                "bitis": bitis,
            }

    @staticmethod
    def musteri_kar_zarar(
        cari_id: int,
        baslangic: date | None = None,
        bitis: date | None = None,
        stok: str | None = None,
    ) -> dict[str, Any]:
        """Müşteri bazlı kar/zarar (FIFO maliyet). Tarih ve stok (kod/ad) filtresi destekler."""
        stok_filtre = (stok or "").strip().casefold()
        with get_session() as session:
            cari = session.get(Cari, cari_id)
            if cari is None:
                raise ValueError("Cari bulunamadı.")
            faturalar = session.scalars(
                select(SatisFaturasi)
                .where(SatisFaturasi.cari_id == cari_id, SatisFaturasi.durum != "İPTAL")
                .options(selectinload(SatisFaturasi.satirlar))
                .order_by(SatisFaturasi.fatura_tarihi.desc())
            ).all()
            satirlar = []
            toplam_satis = Decimal("0")
            toplam_maliyet = Decimal("0")
            for fatura in faturalar:
                if baslangic and fatura.fatura_tarihi < baslangic:
                    continue
                if bitis and fatura.fatura_tarihi > bitis:
                    continue
                for satir in fatura.satirlar:
                    if stok_filtre and (
                        stok_filtre not in (satir.urun_kodu or "").casefold()
                        and stok_filtre not in (satir.urun_adi or "").casefold()
                    ):
                        continue
                    net = satir.miktar * satir.birim_fiyat * (
                        Decimal("1") - (satir.iskonto_orani or 0) / Decimal("100")
                    )
                    birim_maliyet = satir.fifo_birim_maliyeti or Decimal("0")
                    maliyet = satir.miktar * birim_maliyet
                    kar = net - maliyet
                    marj = (kar / net * Decimal("100")) if net else Decimal("0")
                    toplam_satis += net
                    toplam_maliyet += maliyet
                    satirlar.append({
                        "fatura_no": fatura.fatura_no,
                        "tarih": fatura.fatura_tarihi,
                        "urun_kodu": satir.urun_kodu,
                        "urun_adi": satir.urun_adi,
                        "miktar": satir.miktar,
                        "birim_fiyat": satir.birim_fiyat,
                        "net_satis": net,
                        "fifo_birim_maliyeti": birim_maliyet,
                        "toplam_maliyet": maliyet,
                        "kar": kar,
                        "marj": marj,
                    })
            toplam_kar = toplam_satis - toplam_maliyet
            toplam_marj = (toplam_kar / toplam_satis * Decimal("100")) if toplam_satis else Decimal("0")
            return {
                "cari": cari,
                "satirlar": satirlar,
                "toplam_satis": toplam_satis,
                "toplam_maliyet": toplam_maliyet,
                "toplam_kar": toplam_kar,
                "toplam_marj": toplam_marj,
            }

    # --- Stok raporları ---

    @staticmethod
    def stok_rapor_filtre_secenekleri(stok_kodu: str | None = None) -> dict[str, list[str]]:
        """Kar/zarar vb. raporlar için lot ve tedarikçi seçim listeleri."""
        stok_kodu = (stok_kodu or "").strip()
        with get_session() as session:
            q = select(StokLotu).order_by(StokLotu.lot_no)
            if stok_kodu:
                stok = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == stok_kodu))
                if stok:
                    q = q.where(StokLotu.stok_id == stok.id)
            lotlar = list(session.scalars(q).all())
            lot_nos = sorted({(l.lot_no or "").strip() for l in lotlar if (l.lot_no or "").strip()})
            tedarikciler = sorted(
                {(l.tedarikci or "").strip() for l in lotlar if (l.tedarikci or "").strip()},
                key=str.casefold,
            )
            # Cari kartındaki tedarikçileri de ekle
            for ozet in CariService.listele(cari_turu="Tedarikçi"):
                ad = (ozet["cari"].unvan or "").strip()
                if ad and ad not in tedarikciler:
                    tedarikciler.append(ad)
            tedarikciler = sorted(set(tedarikciler), key=str.casefold)
            return {"lotlar": lot_nos, "tedarikciler": tedarikciler}

    @staticmethod
    def _depo_adi(session, depo_id):
        depo = session.get(Depo, depo_id)
        return depo.ad if depo else ""

    @staticmethod
    def stok_envanter(
        tarih: date | None = None,
        maliyet_yontemi: str = "FIFO",
        depo_adi: str | None = None,
        stok_filtre: str | None = None,
        sadece_pozitif: bool = True,
    ) -> dict[str, Any]:
        """
        Belirli tarihteki stok envanteri.
        Miktar: hareket bakiyesi (tarih ≤ seçilen gün).
        Birim maliyet: seçilen yönteme göre (güncel lot / kart maliyetleri).
        """
        as_of = tarih or date.today()
        yontem = maliyet_yontemi if maliyet_yontemi in _MALIYET_ANAHTAR else "FIFO"
        anahtar = _MALIYET_ANAHTAR[yontem]
        filtre = (stok_filtre or "").strip().casefold()
        depo_filtre = (depo_adi or "").strip()

        with get_session() as session:
            depolar = {d.id: d.ad for d in session.scalars(select(Depo)).all()}
            stoklar = list(
                session.scalars(
                    select(StokKarti).where(StokKarti.aktif.is_(True)).order_by(StokKarti.stok_kodu)
                ).all()
            )
            hareketler = list(
                session.scalars(
                    select(StokHareketi).where(StokHareketi.tarih <= as_of)
                ).all()
            )

            bakiye: dict[tuple[int, int], Decimal] = {}
            for h in hareketler:
                key = (h.stok_id, h.depo_id)
                isaret = Decimal("1") if h.hareket_turu in GIRIS_HAREKETLERI else Decimal("-1")
                if h.hareket_turu not in GIRIS_HAREKETLERI and h.hareket_turu not in CIKIS_HAREKETLERI:
                    continue
                bakiye[key] = bakiye.get(key, Decimal("0")) + isaret * (h.miktar or Decimal("0"))

            satirlar = []
            toplam_miktar = Decimal("0")
            toplam_tutar = Decimal("0")
            for stok in stoklar:
                if filtre and (
                    filtre not in (stok.stok_kodu or "").casefold()
                    and filtre not in (stok.stok_adi or "").casefold()
                ):
                    continue
                for depo_id, ad in depolar.items():
                    if depo_filtre and ad != depo_filtre:
                        continue
                    miktar = bakiye.get((stok.id, depo_id), Decimal("0"))
                    if sadece_pozitif and miktar <= 0:
                        continue
                    if miktar == 0 and not sadece_pozitif:
                        continue
                    maliyetler = StokService.maliyetler(stok.stok_kodu, ad)
                    birim = Decimal(str(maliyetler.get(anahtar) or 0))
                    tutar = miktar * birim
                    toplam_miktar += miktar
                    toplam_tutar += tutar
                    satirlar.append({
                        "stok_kodu": stok.stok_kodu,
                        "stok_adi": stok.stok_adi,
                        "kart_turu": stok.kart_turu or "",
                        "birim": stok.birim or "Adet",
                        "depo": ad,
                        "miktar": miktar,
                        "birim_maliyet": birim,
                        "tutar": tutar,
                        "maliyet_yontemi": yontem,
                    })
            satirlar.sort(key=lambda s: (s["stok_kodu"], s["depo"]))
            return {
                "tarih": as_of,
                "maliyet_yontemi": yontem,
                "satirlar": satirlar,
                "toplam_miktar": toplam_miktar,
                "toplam_tutar": toplam_tutar,
            }

    @staticmethod
    def stok_kar_zarar(
        baslangic: date | None = None,
        bitis: date | None = None,
        stok: str | None = None,
        cari_id: int | None = None,
        lot: str | None = None,
        tedarikci: str | None = None,
        maliyet_yontemi: str = "FIFO",
    ) -> dict[str, Any]:
        """Satış faturalarından stok kar/zarar; çoklu filtre."""
        stok_f = (stok or "").strip().casefold()
        lot_f = (lot or "").strip().casefold()
        tedarikci_f = (tedarikci or "").strip().casefold()
        alan = _MALIYET_ALAN.get(maliyet_yontemi, "fifo_birim_maliyeti")

        with get_session() as session:
            q = (
                select(SatisFaturasi)
                .where(SatisFaturasi.durum != "İPTAL")
                .options(
                    selectinload(SatisFaturasi.satirlar),
                    selectinload(SatisFaturasi.cari),
                )
                .order_by(SatisFaturasi.fatura_tarihi.desc())
            )
            if cari_id:
                q = q.where(SatisFaturasi.cari_id == int(cari_id))
            faturalar = list(session.scalars(q).all())

            # Lot → tedarikçi eşlemesi
            lot_tedarikci = {}
            if tedarikci_f:
                for l in session.scalars(select(StokLotu)).all():
                    lot_tedarikci[(l.stok_id, (l.lot_no or "").casefold())] = (l.tedarikci or "").casefold()

            satirlar = []
            toplam_satis = toplam_maliyet = Decimal("0")
            for fatura in faturalar:
                if baslangic and fatura.fatura_tarihi < baslangic:
                    continue
                if bitis and fatura.fatura_tarihi > bitis:
                    continue
                cari = fatura.cari
                for satir in fatura.satirlar:
                    if stok_f and (
                        stok_f not in (satir.urun_kodu or "").casefold()
                        and stok_f not in (satir.urun_adi or "").casefold()
                    ):
                        continue
                    lot_metin = f"{satir.lot_no or ''} {satir.lot_cikisi or ''}".casefold()
                    if lot_f and lot_f not in lot_metin:
                        continue
                    if tedarikci_f:
                        stok_kart = session.scalar(
                            select(StokKarti).where(StokKarti.stok_kodu == satir.urun_kodu)
                        )
                        ok = False
                        if stok_kart:
                            for parca in (satir.lot_cikisi or satir.lot_no or "").split(","):
                                lot_no = parca.split(":")[0].strip().casefold()
                                if lot_tedarikci.get((stok_kart.id, lot_no), "").find(tedarikci_f) >= 0:
                                    ok = True
                                    break
                                if tedarikci_f in lot_tedarikci.get((stok_kart.id, lot_no), ""):
                                    ok = True
                                    break
                        if not ok:
                            # lot'ta tedarikçi yoksa satırı atla
                            continue

                    net = satir.miktar * satir.birim_fiyat * (
                        Decimal("1") - (satir.iskonto_orani or 0) / Decimal("100")
                    )
                    birim_maliyet = getattr(satir, alan, None) or satir.fifo_birim_maliyeti or Decimal("0")
                    maliyet = satir.miktar * birim_maliyet
                    kar = net - maliyet
                    marj = (kar / net * Decimal("100")) if net else Decimal("0")
                    toplam_satis += net
                    toplam_maliyet += maliyet
                    satirlar.append({
                        "fatura_no": fatura.fatura_no,
                        "tarih": fatura.fatura_tarihi,
                        "cari_kodu": cari.cari_kodu if cari else "",
                        "cari_unvan": cari.unvan if cari else "",
                        "urun_kodu": satir.urun_kodu,
                        "urun_adi": satir.urun_adi,
                        "lot": satir.lot_cikisi or satir.lot_no or "",
                        "miktar": satir.miktar,
                        "birim_fiyat": satir.birim_fiyat,
                        "net_satis": net,
                        "birim_maliyet": birim_maliyet,
                        "toplam_maliyet": maliyet,
                        "kar": kar,
                        "marj": marj,
                        "depo": fatura.depo,
                    })
            toplam_kar = toplam_satis - toplam_maliyet
            return {
                "satirlar": satirlar,
                "toplam_satis": toplam_satis,
                "toplam_maliyet": toplam_maliyet,
                "toplam_kar": toplam_kar,
                "toplam_marj": (toplam_kar / toplam_satis * 100) if toplam_satis else Decimal("0"),
                "maliyet_yontemi": maliyet_yontemi,
            }

    @staticmethod
    def satilmayan_urunler(min_gun: int = 30, stok_filtre: str | None = None) -> dict[str, Any]:
        """Son satış (FATURA ÇIKIŞ) üzerinden X gündür satılmayan ürünler."""
        bugun = date.today()
        min_gun = max(0, int(min_gun))
        filtre = (stok_filtre or "").strip().casefold()
        with get_session() as session:
            stoklar = list(
                session.scalars(
                    select(StokKarti)
                    .where(StokKarti.aktif.is_(True))
                    .options(selectinload(StokKarti.lotlar))
                    .order_by(StokKarti.stok_adi)
                ).all()
            )
            son_satis: dict[int, date] = {}
            for h in session.scalars(
                select(StokHareketi).where(StokHareketi.hareket_turu == "FATURA ÇIKIŞ")
            ).all():
                onceki = son_satis.get(h.stok_id)
                if onceki is None or h.tarih > onceki:
                    son_satis[h.stok_id] = h.tarih

            satirlar = []
            for stok in stoklar:
                if filtre and (
                    filtre not in (stok.stok_kodu or "").casefold()
                    and filtre not in (stok.stok_adi or "").casefold()
                ):
                    continue
                mevcut = sum((lot.kalan_miktar for lot in stok.lotlar), Decimal("0"))
                son = son_satis.get(stok.id)
                if son is None:
                    # Hiç satılmamış — kart oluşturma yerine en eski lot / bugün
                    gun = 9999
                    son_metin = None
                else:
                    gun = (bugun - son).days
                    son_metin = son
                if gun < min_gun:
                    continue
                satirlar.append({
                    "stok_kodu": stok.stok_kodu,
                    "stok_adi": stok.stok_adi,
                    "birim": stok.birim,
                    "mevcut": mevcut,
                    "son_satis": son_metin,
                    "gun": gun if gun < 9999 else None,
                    "hic_satilmadi": son is None,
                })
            satirlar.sort(key=lambda s: (-(s["gun"] or 9999), s["stok_adi"]))
            return {"min_gun": min_gun, "satirlar": satirlar, "tarih": bugun}

    @staticmethod
    def stok_devir_hizi(
        baslangic: date,
        bitis: date,
        stok_filtre: str | None = None,
        maliyet_yontemi: str = "FIFO",
    ) -> dict[str, Any]:
        """
        Stok devir hızı (ürün bazlı):
          Devir Hızı = Dönem Satış Maliyeti (COGS) / Ortalama Stok Değeri
          Ortalama Stok = (Dönem Başı Envanter + Dönem Sonu Envanter) / 2
          Stokta Kalma Süresi (gün) = Dönem Gün Sayısı / Devir Hızı
        """
        if bitis < baslangic:
            raise ValueError("Bitiş, başlangıçtan önce olamaz.")
        gun_sayisi = (bitis - baslangic).days + 1
        onceki_gun = date.fromordinal(baslangic.toordinal() - 1)

        bas_env = RaporService.stok_envanter(
            tarih=onceki_gun, maliyet_yontemi=maliyet_yontemi,
            stok_filtre=stok_filtre, sadece_pozitif=False,
        )
        son_env = RaporService.stok_envanter(
            tarih=bitis, maliyet_yontemi=maliyet_yontemi,
            stok_filtre=stok_filtre, sadece_pozitif=False,
        )

        def _topla(envanter):
            mp: dict[str, dict] = {}
            for s in envanter["satirlar"]:
                kod = s["stok_kodu"]
                if kod not in mp:
                    mp[kod] = {
                        "stok_kodu": kod,
                        "stok_adi": s["stok_adi"],
                        "birim": s["birim"],
                        "miktar": Decimal("0"),
                        "tutar": Decimal("0"),
                    }
                mp[kod]["miktar"] += s["miktar"]
                mp[kod]["tutar"] += s["tutar"]
            return mp

        bas_map = _topla(bas_env)
        son_map = _topla(son_env)
        kodlar = set(bas_map) | set(son_map)

        # Dönem COGS: FATURA ÇIKIŞ maliyetleri
        filtre = (stok_filtre or "").strip().casefold()
        cogs: dict[str, Decimal] = {}
        cogs_miktar: dict[str, Decimal] = {}
        with get_session() as session:
            stok_by_id = {s.id: s for s in session.scalars(select(StokKarti)).all()}
            for h in session.scalars(
                select(StokHareketi).where(
                    StokHareketi.hareket_turu == "FATURA ÇIKIŞ",
                    StokHareketi.tarih >= baslangic,
                    StokHareketi.tarih <= bitis,
                )
            ).all():
                stok = stok_by_id.get(h.stok_id)
                if not stok:
                    continue
                if filtre and (
                    filtre not in (stok.stok_kodu or "").casefold()
                    and filtre not in (stok.stok_adi or "").casefold()
                ):
                    continue
                kod = stok.stok_kodu
                cogs[kod] = cogs.get(kod, Decimal("0")) + (h.miktar or 0) * (h.birim_maliyet or 0)
                cogs_miktar[kod] = cogs_miktar.get(kod, Decimal("0")) + (h.miktar or 0)
                kodlar.add(kod)

        satirlar = []
        for kod in sorted(kodlar):
            b = bas_map.get(kod, {"miktar": Decimal("0"), "tutar": Decimal("0"), "stok_adi": "", "birim": "Adet"})
            s = son_map.get(kod, {"miktar": Decimal("0"), "tutar": Decimal("0"), "stok_adi": "", "birim": "Adet"})
            adi = s.get("stok_adi") or b.get("stok_adi") or kod
            birim = s.get("birim") or b.get("birim") or "Adet"
            ort_miktar = (b["miktar"] + s["miktar"]) / Decimal("2")
            ort_deger = (b["tutar"] + s["tutar"]) / Decimal("2")
            satis_mal = cogs.get(kod, Decimal("0"))
            satis_mik = cogs_miktar.get(kod, Decimal("0"))
            # Devir hızı (değer): COGS / ortalama stok değeri
            if ort_deger > 0:
                devir = satis_mal / ort_deger
            elif ort_miktar > 0 and satis_mik > 0:
                devir = satis_mik / ort_miktar
            else:
                devir = Decimal("0")
            gun_stokta = (Decimal(gun_sayisi) / devir) if devir > 0 else None
            satirlar.append({
                "stok_kodu": kod,
                "stok_adi": adi,
                "birim": birim,
                "bas_miktar": b["miktar"],
                "son_miktar": s["miktar"],
                "ort_miktar": ort_miktar,
                "bas_deger": b["tutar"],
                "son_deger": s["tutar"],
                "ort_deger": ort_deger,
                "cogs": satis_mal,
                "satis_miktar": satis_mik,
                "devir_hizi": devir,
                "gun_stokta": gun_stokta,
            })
        satirlar.sort(key=lambda x: x["devir_hizi"], reverse=True)
        return {
            "baslangic": baslangic,
            "bitis": bitis,
            "gun_sayisi": gun_sayisi,
            "maliyet_yontemi": maliyet_yontemi,
            "satirlar": satirlar,
            "formul": (
                "Devir Hızı = Dönem Satış Maliyeti (COGS) / Ortalama Stok Değeri; "
                "Ortalama Stok = (Dönem Başı + Dönem Sonu) / 2; "
                "Stokta Kalma (gün) = Dönem Gün / Devir Hızı"
            ),
        }

    @staticmethod
    def stok_hareket_raporu(
        baslangic: date | None = None,
        bitis: date | None = None,
        stok: str | None = None,
        depo_adi: str | None = None,
        hareket_turu: str | None = None,
        belge_no: str | None = None,
        lot: str | None = None,
    ) -> dict[str, Any]:
        """Stok hareketleri — çoklu filtre."""
        stok_f = (stok or "").strip().casefold()
        depo_f = (depo_adi or "").strip()
        tur_f = (hareket_turu or "").strip()
        belge_f = (belge_no or "").strip().casefold()
        lot_f = (lot or "").strip().casefold()

        with get_session() as session:
            depolar = {d.id: d.ad for d in session.scalars(select(Depo)).all()}
            stoklar = {s.id: s for s in session.scalars(select(StokKarti)).all()}
            lotlar = {l.id: l for l in session.scalars(select(StokLotu)).all()}
            q = select(StokHareketi).order_by(StokHareketi.tarih.desc(), StokHareketi.id.desc())
            if baslangic:
                q = q.where(StokHareketi.tarih >= baslangic)
            if bitis:
                q = q.where(StokHareketi.tarih <= bitis)
            if tur_f:
                q = q.where(StokHareketi.hareket_turu == tur_f)
            hareketler = list(session.scalars(q).all())

            satirlar = []
            for h in hareketler:
                stok_k = stoklar.get(h.stok_id)
                if not stok_k:
                    continue
                if stok_f and (
                    stok_f not in (stok_k.stok_kodu or "").casefold()
                    and stok_f not in (stok_k.stok_adi or "").casefold()
                ):
                    continue
                depo = depolar.get(h.depo_id, "")
                if depo_f and depo != depo_f:
                    continue
                if belge_f and belge_f not in (h.belge_no or "").casefold():
                    continue
                lot_obj = lotlar.get(h.lot_id) if h.lot_id else None
                lot_no = lot_obj.lot_no if lot_obj else ""
                if lot_f and lot_f not in lot_no.casefold():
                    continue
                yon = "+" if h.hareket_turu in GIRIS_HAREKETLERI else "−"
                satirlar.append({
                    "tarih": h.tarih,
                    "hareket_turu": h.hareket_turu,
                    "belge_no": h.belge_no,
                    "stok_kodu": stok_k.stok_kodu,
                    "stok_adi": stok_k.stok_adi,
                    "depo": depo,
                    "lot_no": lot_no,
                    "yon": yon,
                    "miktar": h.miktar,
                    "birim_maliyet": h.birim_maliyet,
                    "tutar": (h.miktar or 0) * (h.birim_maliyet or 0),
                })
            return {"satirlar": satirlar}

    @staticmethod
    def bilanco_ozeti(maliyet_yontemi: str = "FIFO") -> dict[str, Any]:
        """
        Bilanço benzeri özet tablo verisi (canlı bakiyeler).

        Aktif: kasa, mevduat, POS, pozitif KMH, cari alacaklar, stok.
        Pasif: negatif KMH (kullanım), krediler, kredi kartı, tedarikçi/müşteri borçları.
        Özkaynak (hesaplanan) = Toplam Aktif − Toplam Borçlar (iki taraf dengelenir).
        """
        from database.finans_service import FinansService

        yontem = maliyet_yontemi if maliyet_yontemi in _MALIYET_ANAHTAR else "FIFO"
        sifir = Decimal("0")

        def _satir(etiket: str, tutar, *, seviye: str = "kalem", kaynak: str = "") -> dict[str, Any]:
            return {
                "etiket": etiket,
                "tutar": Decimal(str(tutar or 0)),
                "seviye": seviye,  # baslik | kalem | ara_toplam | toplam
                "kaynak": kaynak,
            }

        # --- Kasa ---
        kasa_kalemleri = []
        kasa_toplam = sifir
        for hesap in FinansService.kasa_hesaplari(aktif_only=True):
            bak = FinansService.bakiye(hesap)
            kasa_kalemleri.append(_satir(hesap.hesap_adi, bak, kaynak="kasa"))
            kasa_toplam += bak

        # --- Banka alt hesapları ---
        mevduat_kalemleri = []
        pos_kalemleri = []
        kmh_varlik = []
        kmh_borc = []
        kredi_kalemleri = []
        kk_kalemleri = []
        mevduat_toplam = sifir
        pos_toplam = sifir
        kmh_varlik_toplam = sifir
        kmh_borc_toplam = sifir
        kredi_toplam = sifir
        kk_toplam = sifir

        for kart in FinansService.banka_kartlari(aktif_only=True):
            banka = (kart.banka_adi or "Banka").strip()
            bak = FinansService.banka_bakiyeler(kart)

            mev = bak.get("MEVDUAT") or sifir
            if mev != 0:
                mevduat_kalemleri.append(_satir(f"{banka} — Mevduat", mev, kaynak="mevduat"))
                mevduat_toplam += mev

            pos = bak.get("POS") or sifir
            if pos != 0:
                pos_kalemleri.append(_satir(f"{banka} — POS", pos, kaynak="pos"))
                pos_toplam += pos

            kmh = bak.get("KMH") or sifir
            if kmh > 0:
                kmh_varlik.append(_satir(f"{banka} — KMH", kmh, kaynak="kmh"))
                kmh_varlik_toplam += kmh
            elif kmh < 0:
                # Kullanılan KMH → pasif (pozitif borç tutarı)
                tutar = abs(kmh)
                kmh_borc.append(_satir(f"{banka} — KMH kullanımı", tutar, kaynak="kmh"))
                kmh_borc_toplam += tutar

            kred = bak.get("KREDILER") or sifir
            if kred != 0:
                tutar = abs(kred)
                kredi_kalemleri.append(_satir(f"{banka} — Kredi", tutar, kaynak="kredi"))
                kredi_toplam += tutar

            kk = bak.get("KREDI_KARTI") or sifir
            if kk != 0:
                tutar = abs(kk)
                kk_kalemleri.append(_satir(f"{banka} — Kredi kartı", tutar, kaynak="kk"))
                kk_toplam += tutar

        # --- Cari ---
        cari_alacak_kalemleri = []
        cari_borc_kalemleri = []
        cari_alacak_toplam = sifir
        cari_borc_toplam = sifir
        for ozet in CariService.listele():
            cari = ozet["cari"]
            if not getattr(cari, "aktif", True):
                continue
            bak = Decimal(str(ozet.get("bakiye") or 0))
            if bak == 0:
                continue
            etiket = f"{cari.cari_kodu} — {cari.unvan}"
            # bakiye > 0 → Borçlu (bize borçlu) = alacak / varlık
            # bakiye < 0 → Alacaklı (biz borçluyuz) = borç / pasif
            if bak > 0:
                cari_alacak_kalemleri.append(_satir(etiket, bak, kaynak="cari_alacak"))
                cari_alacak_toplam += bak
            else:
                cari_borc_kalemleri.append(_satir(etiket, abs(bak), kaynak="cari_borc"))
                cari_borc_toplam += abs(bak)

        cari_alacak_kalemleri.sort(key=lambda s: s["tutar"], reverse=True)
        cari_borc_kalemleri.sort(key=lambda s: s["tutar"], reverse=True)

        # --- Stok ---
        envanter = RaporService.stok_envanter(maliyet_yontemi=yontem, sadece_pozitif=True)
        stok_toplam = Decimal(str(envanter.get("toplam_tutar") or 0))
        stok_kalemleri = [
            _satir(f"Stoklar ({yontem})", stok_toplam, kaynak="stok"),
        ]

        # --- Aktif ağacı ---
        aktif: list[dict[str, Any]] = []
        aktif.append(_satir("DÖNEN VARLIKLAR", sifir, seviye="baslik"))

        def _bolum(hedef, baslik, toplam, kalemler, kaynak):
            if toplam == 0 and not kalemler:
                return
            hedef.append(_satir(baslik, toplam, seviye="ara_toplam", kaynak=kaynak))
            hedef.extend(kalemler)

        _bolum(aktif, "Kasa yekünü", kasa_toplam, kasa_kalemleri, "kasa")
        _bolum(aktif, "Banka mevduat yekünü", mevduat_toplam, mevduat_kalemleri, "mevduat")
        _bolum(aktif, "POS bakiyeleri", pos_toplam, pos_kalemleri, "pos")
        _bolum(aktif, "KMH (pozitif bakiye)", kmh_varlik_toplam, kmh_varlik, "kmh")

        _bolum(aktif, "Cari alacaklar toplamı", cari_alacak_toplam, [], "cari_alacak")
        for s in cari_alacak_kalemleri[:15]:
            aktif.append(s)
        if len(cari_alacak_kalemleri) > 15:
            kalan = sum((s["tutar"] for s in cari_alacak_kalemleri[15:]), sifir)
            aktif.append(
                _satir(f"… ve {len(cari_alacak_kalemleri) - 15} cari daha", kalan, kaynak="cari_alacak")
            )

        _bolum(aktif, "Stoklar toplamı", stok_toplam, stok_kalemleri, "stok")

        toplam_aktif = (
            kasa_toplam
            + mevduat_toplam
            + pos_toplam
            + kmh_varlik_toplam
            + cari_alacak_toplam
            + stok_toplam
        )
        aktif.append(_satir("TOPLAM VARLIKLAR (AKTİF)", toplam_aktif, seviye="toplam"))

        # --- Pasif ağacı ---
        pasif: list[dict[str, Any]] = []
        pasif.append(_satir("KISA / UZUN VADELİ BORÇLAR", sifir, seviye="baslik"))

        _bolum(pasif, "Toplam KMH kullanımı", kmh_borc_toplam, kmh_borc, "kmh")
        _bolum(pasif, "Toplam kredi borcu", kredi_toplam, kredi_kalemleri, "kredi")
        _bolum(pasif, "Toplam kredi kartı borcu", kk_toplam, kk_kalemleri, "kk")

        _bolum(pasif, "Cari borçlar toplamı", cari_borc_toplam, [], "cari_borc")
        for s in cari_borc_kalemleri[:15]:
            pasif.append(s)
        if len(cari_borc_kalemleri) > 15:
            kalan = sum((s["tutar"] for s in cari_borc_kalemleri[15:]), sifir)
            pasif.append(
                _satir(f"… ve {len(cari_borc_kalemleri) - 15} cari daha", kalan, kaynak="cari_borc")
            )

        toplam_borclar = kmh_borc_toplam + kredi_toplam + kk_toplam + cari_borc_toplam
        ozkaynak = toplam_aktif - toplam_borclar

        pasif.append(_satir("TOPLAM BORÇLAR", toplam_borclar, seviye="ara_toplam"))
        pasif.append(
            _satir(
                "Özkaynak / net varlık (hesaplanan)",
                ozkaynak,
                seviye="ara_toplam",
                kaynak="ozkaynak",
            )
        )
        toplam_pasif = toplam_borclar + ozkaynak  # = toplam_aktif
        pasif.append(_satir("TOPLAM KAYNAKLAR (PASİF)", toplam_pasif, seviye="toplam"))

        return {
            "tarih": date.today(),
            "maliyet_yontemi": yontem,
            "aktif": aktif,
            "pasif": pasif,
            "ozet": {
                "kasa": kasa_toplam,
                "mevduat": mevduat_toplam,
                "pos": pos_toplam,
                "kmh_varlik": kmh_varlik_toplam,
                "cari_alacak": cari_alacak_toplam,
                "stok": stok_toplam,
                "toplam_aktif": toplam_aktif,
                "kmh_borc": kmh_borc_toplam,
                "kredi": kredi_toplam,
                "kk": kk_toplam,
                "cari_borc": cari_borc_toplam,
                "toplam_borclar": toplam_borclar,
                "ozkaynak": ozkaynak,
                "toplam_pasif": toplam_pasif,
                "denge": toplam_aktif - toplam_pasif,
            },
        }

    @staticmethod
    def gelir_tablosu(
        baslangic: date,
        bitis: date,
        maliyet_yontemi: str = "FIFO",
    ) -> dict[str, Any]:
        """
        Klasik gelir tablosu (P&L) — tarih aralığı.

        Net satış = brüt satışlar − satış iskontoları − satıştan iadeler (KDV hariç).
        SMM = dönem başı emtia + net alışlar − dönem sonu emtia
          net alışlar = dönem içi alışlar − alış iskontoları − satınalma iadeleri (KDV hariç).
        Dönem başı emtia: stok_envanter(başlangıç − 1 gün); dönem sonu: bitiş günü.
        Stok miktarı hareket bakiyesine göredir; birim maliyet seçilen yöntemin *güncel*
        kart/lot maliyetidir (tarihsel maliyet katmanı yok).
        """
        from database.models.finans import GiderFisi
        from database.models.hizmet_faturasi import HizmetFaturasi
        from database.hizmet_faturasi_service import HizmetFaturasiService

        if bitis < baslangic:
            raise ValueError("Bitiş, başlangıçtan önce olamaz.")

        yontem = maliyet_yontemi if maliyet_yontemi in _MALIYET_ANAHTAR else "FIFO"
        sifir = Decimal("0")

        def _satir(etiket: str, tutar, *, seviye: str = "kalem", kaynak: str = "") -> dict[str, Any]:
            return {
                "etiket": etiket,
                "tutar": Decimal(str(tutar or 0)),
                "seviye": seviye,
                "kaynak": kaynak,
            }

        def _net_kdvsiz(toplam: dict) -> Decimal:
            return Decimal(str(toplam.get("ara_toplam") or 0)) - Decimal(str(toplam.get("iskonto") or 0))

        onceki_gun = date.fromordinal(baslangic.toordinal() - 1)
        bas_env = RaporService.stok_envanter(
            tarih=onceki_gun, maliyet_yontemi=yontem, sadece_pozitif=True
        )
        son_env = RaporService.stok_envanter(
            tarih=bitis, maliyet_yontemi=yontem, sadece_pozitif=True
        )
        donem_basi_emtia = Decimal(str(bas_env.get("toplam_tutar") or 0))
        donem_sonu_emtia = Decimal(str(son_env.get("toplam_tutar") or 0))

        brut_satis = satis_iskonto = sifir
        satis_iade_brut = satis_iade_iskonto = sifir
        alis_brut = alis_iskonto = sifir
        alis_iade_brut = alis_iade_iskonto = sifir
        hizmet_gider = hizmet_gelir = sifir
        gider_fis_hizmet = gider_fis_faiz = gider_fis_masraf = gider_fis_diger = sifir

        with get_session() as session:
            for fatura in session.scalars(
                select(SatisFaturasi)
                .where(SatisFaturasi.durum != "İPTAL")
                .options(selectinload(SatisFaturasi.satirlar))
            ).all():
                if fatura.fatura_tarihi < baslangic or fatura.fatura_tarihi > bitis:
                    continue
                t = SatisFaturasiService.toplam(fatura.satirlar)
                brut_satis += Decimal(str(t["ara_toplam"]))
                satis_iskonto += Decimal(str(t["iskonto"]))

            for iade in session.scalars(
                select(SatisIadeFaturasi)
                .where(SatisIadeFaturasi.durum != "İPTAL")
                .options(selectinload(SatisIadeFaturasi.satirlar))
            ).all():
                if iade.iade_tarihi < baslangic or iade.iade_tarihi > bitis:
                    continue
                t = SatisIadeFaturasiService.toplam(iade.satirlar)
                satis_iade_brut += Decimal(str(t["ara_toplam"]))
                satis_iade_iskonto += Decimal(str(t["iskonto"]))

            for fatura in session.scalars(
                select(AlisFaturasi)
                .where(AlisFaturasi.durum != "İPTAL")
                .options(selectinload(AlisFaturasi.satirlar))
            ).all():
                if fatura.fatura_tarihi < baslangic or fatura.fatura_tarihi > bitis:
                    continue
                t = AlisFaturasiService.toplam(fatura.satirlar)
                alis_brut += Decimal(str(t["ara_toplam"]))
                alis_iskonto += Decimal(str(t["iskonto"]))

            for iade in session.scalars(
                select(AlisIadeFaturasi)
                .where(AlisIadeFaturasi.durum != "İPTAL")
                .options(selectinload(AlisIadeFaturasi.satirlar))
            ).all():
                if iade.iade_tarihi < baslangic or iade.iade_tarihi > bitis:
                    continue
                t = AlisIadeFaturasiService.toplam(iade.satirlar)
                alis_iade_brut += Decimal(str(t["ara_toplam"]))
                alis_iade_iskonto += Decimal(str(t["iskonto"]))

            for fatura in session.scalars(
                select(HizmetFaturasi)
                .where(HizmetFaturasi.durum != "İPTAL")
                .options(selectinload(HizmetFaturasi.satirlar))
            ).all():
                if fatura.fatura_tarihi < baslangic or fatura.fatura_tarihi > bitis:
                    continue
                net = _net_kdvsiz(HizmetFaturasiService.toplam(fatura.satirlar))
                tur = (fatura.fatura_turu or "").upper()
                if tur == "GIDER":
                    hizmet_gider += net
                elif tur == "GELIR":
                    hizmet_gelir += net

            for fis in session.scalars(
                select(GiderFisi).where(GiderFisi.durum != "IPTAL")
            ).all():
                if fis.tarih < baslangic or fis.tarih > bitis:
                    continue
                tutar = Decimal(str(fis.tutar or 0))
                tur = (fis.gider_turu or "").upper()
                if tur == "HIZMET":
                    gider_fis_hizmet += tutar
                elif tur == "KREDI_FAIZ":
                    gider_fis_faiz += tutar
                elif tur == "KREDI_MASRAF":
                    gider_fis_masraf += tutar
                else:
                    gider_fis_diger += tutar

        satis_iade_net = satis_iade_brut - satis_iade_iskonto
        net_satislar = brut_satis - satis_iskonto - satis_iade_net

        alis_iade_net = alis_iade_brut - alis_iade_iskonto
        net_alislar = alis_brut - alis_iskonto - alis_iade_net

        smm = donem_basi_emtia + net_alislar - donem_sonu_emtia
        brut_kar = net_satislar - smm

        toplam_gider_fis = (
            gider_fis_hizmet + gider_fis_faiz + gider_fis_masraf + gider_fis_diger
        )
        toplam_giderler = toplam_gider_fis + hizmet_gider
        net_kar = brut_kar + hizmet_gelir - toplam_giderler

        satirlar: list[dict[str, Any]] = []
        satirlar.append(_satir("SATIŞLAR", sifir, seviye="baslik"))
        satirlar.append(_satir("Brüt satışlar", brut_satis, kaynak="brut_satis"))
        if satis_iskonto:
            satirlar.append(_satir("Satış iskontoları (−)", -satis_iskonto, kaynak="satis_iskonto"))
        satirlar.append(
            _satir("Satıştan iadeler (−)", -satis_iade_net, kaynak="satis_iade")
        )
        satirlar.append(
            _satir("Net satışlar", net_satislar, seviye="ara_toplam", kaynak="net_satis")
        )

        satirlar.append(_satir("SATILAN MALIN MALİYETİ (SMM)", sifir, seviye="baslik"))
        satirlar.append(
            _satir("Dönem başı emtia", donem_basi_emtia, kaynak="donem_basi")
        )
        satirlar.append(_satir("Dönem içi alışlar", alis_brut - alis_iskonto, kaynak="alis"))
        if alis_iade_net:
            satirlar.append(
                _satir("Satınalma iadeleri (−)", -alis_iade_net, kaynak="alis_iade")
            )
        satirlar.append(
            _satir("Net alışlar", net_alislar, seviye="ara_toplam", kaynak="net_alis")
        )
        satirlar.append(
            _satir("Dönem sonu emtia (−)", -donem_sonu_emtia, kaynak="donem_sonu")
        )
        satirlar.append(_satir("Satılan malın maliyeti", smm, seviye="ara_toplam", kaynak="smm"))

        satirlar.append(_satir("Brüt kâr", brut_kar, seviye="toplam", kaynak="brut_kar"))

        if hizmet_gelir:
            satirlar.append(_satir("DİĞER GELİRLER", sifir, seviye="baslik"))
            satirlar.append(
                _satir("Hizmet satış gelirleri", hizmet_gelir, kaynak="hizmet_gelir")
            )

        satirlar.append(_satir("GİDERLER", sifir, seviye="baslik"))
        if hizmet_gider:
            satirlar.append(
                _satir("Hizmet alış (gider) faturaları", hizmet_gider, kaynak="hizmet_gider")
            )
        if gider_fis_hizmet:
            satirlar.append(
                _satir("Gider fişleri (hizmet)", gider_fis_hizmet, kaynak="gider_fis")
            )
        if gider_fis_faiz:
            satirlar.append(
                _satir("Kredi / KMH faiz giderleri", gider_fis_faiz, kaynak="faiz")
            )
        if gider_fis_masraf:
            satirlar.append(
                _satir("Kredi masraf giderleri", gider_fis_masraf, kaynak="masraf")
            )
        if gider_fis_diger:
            satirlar.append(
                _satir("Diğer gider fişleri", gider_fis_diger, kaynak="gider_diger")
            )
        if toplam_giderler == 0:
            satirlar.append(_satir("Dönem gideri (kayıt yok)", sifir, kaynak="gider"))
        satirlar.append(
            _satir("Toplam giderler", toplam_giderler, seviye="ara_toplam", kaynak="toplam_gider")
        )

        net_etiket = "Net kâr" if net_kar >= 0 else "Net zarar"
        satirlar.append(_satir(net_etiket, net_kar, seviye="toplam", kaynak="net_kar"))

        return {
            "baslangic": baslangic,
            "bitis": bitis,
            "maliyet_yontemi": yontem,
            "donem_basi_tarih": onceki_gun,
            "donem_sonu_tarih": bitis,
            "satirlar": satirlar,
            "ozet": {
                "brut_satislar": brut_satis,
                "satis_iskonto": satis_iskonto,
                "satis_iadeleri": satis_iade_net,
                "net_satislar": net_satislar,
                "donem_basi_emtia": donem_basi_emtia,
                "donem_ici_alislar": alis_brut - alis_iskonto,
                "alis_iadeleri": alis_iade_net,
                "net_alislar": net_alislar,
                "donem_sonu_emtia": donem_sonu_emtia,
                "smm": smm,
                "brut_kar": brut_kar,
                "hizmet_gelir": hizmet_gelir,
                "toplam_giderler": toplam_giderler,
                "net_kar": net_kar,
            },
            "notlar": (
                "Tutarlar KDV hariçtir. Dönem başı emtia = başlangıç gününden bir gün önceki "
                f"envanter ({onceki_gun.strftime('%d.%m.%Y')}); dönem sonu = bitiş günü. "
                "Stok miktarı hareket bakiyesine göredir; birim maliyet seçilen yöntemin güncel "
                "değeridir. Alışlar alış faturalarından (irsaliye henüz faturalanmamışsa SMM sapabilir)."
            ),
        }
