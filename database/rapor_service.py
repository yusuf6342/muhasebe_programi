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
from database.models.stok import Depo, StokHareketi, StokKarti, StokLotu
from database.satis_faturasi_service import SatisFaturasiService
from database.satis_iade_faturasi_service import SatisIadeFaturasiService


class RaporService:
    @staticmethod
    def musteri_bakiye_durum() -> list[dict[str, Any]]:
        """Müşteri bakiye durumu: bakiye + ortalama vade + ağırlıklı gün + geciken gün."""
        bugun = date.today()
        sonuc = []
        for ozet in CariService.listele():
            cari = ozet["cari"]
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

            for islem in session.scalars(
                select(CariIslem)
                .where(CariIslem.cari_id == cari_id)
                .order_by(CariIslem.tarih, CariIslem.id)
            ).all():
                # İade faturası zaten stok satırlarıyla eklendi; CariIslem çift sayılmasın.
                if islem.islem_turu == "Satış İadesi" and islem.belge_no in iade_belge_nolari:
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

            belgeler.sort(
                key=lambda b: (
                    b["tarih"],
                    0 if b["tur"] == "Satış Faturası" else (1 if b["tur"] == "Satış İadesi" else 2),
                    b["sira"],
                )
            )
            calisan = Decimal("0")
            for belge in belgeler:
                calisan += (belge["borc"] or Decimal("0")) - (belge["alacak"] or Decimal("0"))
                belge["bakiye"] = calisan

            ozet = next((o for o in CariService.listele() if o["cari"].id == cari_id), None)
            return {
                "cari": cari,
                "bakiye": ozet["bakiye"] if ozet else calisan,
                "belgeler": list(reversed(belgeler)),
                "fatura_sayisi": sum(1 for b in belgeler if b["tur"] == "Satış Faturası"),
                "iade_sayisi": sum(1 for b in belgeler if b["tur"] == "Satış İadesi"),
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
