"""EvoBulut stok satırlarını yerel StokKarti / StokService'e aktarma."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from database.database import get_session
from database.models.stok import StokKarti
from database.stok_service import StokService

# CLI yolu main.py bootstrap'ını atlar; ilişkili modeller için
from database.models.satis_siparisi import SatisSiparisi  # noqa: F401
from database.models.satis_irsaliyesi import SatisIrsaliyesi  # noqa: F401
from database.models.satis_faturasi import SatisFaturasi  # noqa: F401

# EvoBulut a_kart_tur → yerel kart_turu
_KART_TUR_HARITASI = {
    "1": "Ticari Mal",  # MALZEME
    "2": "Mamul",
    "3": "Yarı Mamul",
    "4": "Hammadde",
    "5": "Demirbaş",
    "10": "Paket",
}


@dataclass
class ImportSonuc:
    eklenen: int = 0
    guncellenen: int = 0
    atlanan: int = 0
    cekilen: int = 0
    hatalar: list[str] = field(default_factory=list)


def _temiz(deger: Any) -> str:
    if deger is None:
        return ""
    return str(deger).strip()


def _para(deger: Any) -> Decimal | None:
    metin = _temiz(deger).replace(",", ".")
    if not metin or metin in {"-", "—"}:
        return None
    try:
        tutar = Decimal(metin)
    except (InvalidOperation, ValueError):
        return None
    return tutar


def _aktif_mi(ham: str) -> bool:
    t = _temiz(ham).casefold()
    if not t:
        return True
    if t in {"0", "pasif", "p", "hayir", "hayır", "false", "no"}:
        return False
    if "pasif" in t:
        return False
    return True


def _kart_turu(ham: str) -> str:
    kod = _temiz(ham)
    if kod in _KART_TUR_HARITASI:
        return _KART_TUR_HARITASI[kod]
    ust = kod.upper()
    if "HAMMAD" in ust:
        return "Hammadde"
    if "Y.MAMUL" in ust or "YARI" in ust:
        return "Yarı Mamul"
    if "MAMUL" in ust:
        return "Mamul"
    if "DEMIR" in ust or "DEMİR" in ust:
        return "Demirbaş"
    if "PAKET" in ust:
        return "Paket"
    if "SARF" in ust:
        return "Sarf Malzeme"
    if "HIZMET" in ust:
        return "Hizmet"
    return "Ticari Mal"


def _barkod_aday(kod: str) -> str | None:
    """Stok kodu barkod gibi görünüyorsa ana barkod adayı."""
    k = _temiz(kod)
    if k.isdigit() and 8 <= len(k) <= 14:
        return k
    return None


def map_evobulut_api_satir(satir: dict[str, Any]) -> dict[str, Any]:
    """Stok Liste (jq_list) satırını StokService.stok_kaydi alanlarına çevirir."""

    def al(*anahtarlar: str) -> str:
        for a in anahtarlar:
            if a in satir and _temiz(satir[a]):
                return _temiz(satir[a])
        return ""

    kod = al("a_kod", "stok_kodu")
    ad = al("a_adi", "stok_adi", "a_alt_adi")
    if not ad:
        ad = al("a_alt_adi")
    birim = al("ana_birim_adi", "ANA_BRM_ADI", "birim") or "Adet"
    marka = al("marka_adi", "a_marka_adi")
    model = al("model_adi", "a_model_adi")
    aciklama = al("a_aciklama", "aciklama")
    rapor = al("a_rapor_grup_adi", "rapor_grubu")
    agirlik = al("a_agirlik")
    if agirlik in {"0", "0.0", "0.00"}:
        agirlik = ""

    isk = _para(al("a_isk", "iskonto_1")) or Decimal("0")

    fiyatlar: list[tuple[str, str]] = []
    alis = _para(al("a_fiyat_al"))
    satis = _para(al("a_fiyat_sat"))
    ozel1 = _para(al("a_ozel_fiy1"))
    ozel2 = _para(al("a_ozel_fiy2"))
    ozel3 = _para(al("a_ozel_fiy3"))
    if alis is not None and alis > 0:
        fiyatlar.append(("ALIŞ FİYATI", str(alis)))
    if satis is not None and satis > 0:
        fiyatlar.append(("SATIŞ FİYATI 1", str(satis)))
    if ozel1 is not None and ozel1 > 0:
        fiyatlar.append(("SATIŞ FİYATI 2", str(ozel1)))
    if ozel2 is not None and ozel2 > 0:
        fiyatlar.append(("SATIŞ FİYATI 3", str(ozel2)))
    if ozel3 is not None and ozel3 > 0:
        fiyatlar.append(("SATIŞ FİYATI 4", str(ozel3)))

    barkod = _barkod_aday(kod)
    # Liste yanıtında ayrı barkod alanı yok; detay çağrısı isteğe bağlı

    kdv_al = al("a_kdv_al")
    kdv_sat = al("a_kdv_sat")
    # Yerel modelde KDV oranı alanı yok; not olarak açıklamaya ekleme (yalnızca boşsa)
    if not aciklama and (kdv_al or kdv_sat):
        parcalar = []
        if kdv_al:
            parcalar.append(f"KDV Alış %{kdv_al}")
        if kdv_sat:
            parcalar.append(f"KDV Satış %{kdv_sat}")
        aciklama = " | ".join(parcalar)

    veriler: dict[str, Any] = {
        "stok_kodu": kod[:50] if kod else "",
        "stok_adi": ad[:200] if ad else "",
        "birim": birim[:20] or "Adet",
        "kart_turu": _kart_turu(al("a_kart_tur", "kart_turu")),
        "aciklama": aciklama[:2000] if aciklama else None,
        "marka": marka[:100] if marka else None,
        "model": model[:100] if model else None,
        "agirlik": agirlik[:50] if agirlik else None,
        "rapor_grubu": rapor[:100] if rapor else None,
        "iskonto_1": str(isk) if isk else "0",
        "barkod": barkod,
        "aktif": _aktif_mi(al("aktif_pasif", "a_pasif_adi", "a_pasif")),
        "_evobulut_id": al("a_id"),
        "_fiyatlar": fiyatlar,
    }
    return veriler


def _mevcut_stok(stok_kodu: str) -> StokKarti | None:
    with get_session() as session:
        return StokService._stok_yukle(session, stok_kodu=stok_kodu)


def _aktif_guncelle(stok_id: int, aktif: bool) -> None:
    with get_session() as session:
        stok = session.get(StokKarti, int(stok_id))
        if stok is not None and stok.aktif != aktif:
            stok.aktif = aktif


def _barkod_baska_kullaniyor_mu(barkod: str, haric_stok_id: int | None = None) -> bool:
    if not barkod:
        return False
    with get_session() as session:
        return StokService._barkod_kullaniliyor_mu(session, barkod, haric_stok_id=haric_stok_id)


def kaydet_veya_guncelle(veriler: dict[str, Any]) -> str:
    """Returns: 'eklendi' | 'guncellendi' | 'atlandi'."""
    kod = _temiz(veriler.get("stok_kodu"))
    ad = _temiz(veriler.get("stok_adi"))
    if not kod or not ad:
        return "atlandi"

    fiyatlar: list[tuple[str, str]] = list(veriler.pop("_fiyatlar", []) or [])
    veriler.pop("_evobulut_id", None)
    aktif = bool(veriler.pop("aktif", True))
    barkod = veriler.get("barkod") or None

    mevcut = _mevcut_stok(kod)
    if mevcut:
        # Güncellemede mevcut fiyatları koru, API fiyatlarıyla üzerine yaz
        mevcut_fiyat = {f.fiyat_adi: str(f.tutar) for f in (mevcut.fiyatlar or [])}
        for ad_f, tutar in fiyatlar:
            mevcut_fiyat[ad_f] = tutar
        birlesik = list(mevcut_fiyat.items())
        if barkod and _barkod_baska_kullaniyor_mu(barkod, haric_stok_id=mevcut.id):
            veriler["barkod"] = mevcut.barkod  # çakışmada eskiyi bırak
        kayit = {**veriler, "stok_id": mevcut.id}
        try:
            StokService.stok_kaydi(kayit, birlesik)
        except ValueError as exc:
            if "barkod" in str(exc).casefold():
                kayit["barkod"] = mevcut.barkod
                StokService.stok_kaydi(kayit, birlesik)
            else:
                raise
        _aktif_guncelle(mevcut.id, aktif)
        return "guncellendi"

    if barkod and _barkod_baska_kullaniyor_mu(barkod):
        veriler["barkod"] = None
    try:
        kaydedilen = StokService.stok_kaydi(veriler, fiyatlar)
    except ValueError as exc:
        if "barkod" in str(exc).casefold():
            veriler["barkod"] = None
            kaydedilen = StokService.stok_kaydi(veriler, fiyatlar)
        else:
            raise
    if kaydedilen is not None:
        _aktif_guncelle(kaydedilen.id, aktif)
    return "eklendi"


def aktar_satirlari(satirlar: Iterable[dict[str, Any]]) -> ImportSonuc:
    sonuc = ImportSonuc()
    for i, satir in enumerate(satirlar, start=1):
        try:
            veriler = map_evobulut_api_satir(satir)
            durum = kaydet_veya_guncelle(veriler)
            if durum == "eklendi":
                sonuc.eklenen += 1
            elif durum == "guncellendi":
                sonuc.guncellenen += 1
            else:
                sonuc.atlanan += 1
        except Exception as exc:  # noqa: BLE001 — satır bazlı hata topla
            kod = _temiz(satir.get("a_kod") if isinstance(satir, dict) else "")
            etiket = f"Satır {i}" + (f" ({kod})" if kod else "")
            sonuc.hatalar.append(f"{etiket}: {exc}")
            sonuc.atlanan += 1
    return sonuc


def aktar_api_den(*, ara: str = "") -> ImportSonuc:
    from entegrasyon.evobulut_client import EvobulutClient, load_credentials

    # İlk kullanımda tablolar/varsayılanlar hazır olsun
    StokService.varsayilanlari_hazirla()

    client = EvobulutClient(load_credentials())
    client.login()
    satirlar = client.tum_stoklari_cek(ara=ara)
    sonuc = aktar_satirlari(satirlar)
    sonuc.cekilen = len(satirlar)
    return sonuc
