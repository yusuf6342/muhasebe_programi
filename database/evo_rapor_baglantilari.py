"""Evo aktarım izlerini raporda okur; hiçbir mali kayıt oluşturmaz."""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

from sqlalchemy import inspect, text


def _date(value):
    return datetime.strptime(str(value)[:10], "%d.%m.%Y").date()


def _amount(value):
    result = Decimal(str(value or 0))
    if not result.is_finite():
        raise ValueError("Geçersiz tutar")
    return result.quantize(Decimal("0.01"))


class EvoRaporBaglantilari:
    """Kaynak kimliği, cari, tarih, yön, tutar ve hedef hesap birlikte doğrulanır."""

    def __init__(self, session, bas, bit):
        self.finans = {}
        self.iadeler = {}
        self.uyarilar = []
        if not inspect(session.connection()).has_table("evo_import_records"):
            return
        parties = {}
        for cid, code in session.execute(text("SELECT id,cari_kodu FROM cari_kartlar")):
            if code and code.startswith("EVB-"):
                parties.setdefault(code[4:], set()).add(int(cid))
        records = session.execute(text(
            "SELECT entity,source_id,target_id,status,target_table,source_json "
            "FROM evo_import_records WHERE entity IN "
            "('cari','banka_hareket','kasa_hareket','33','37')"
        )).all()
        for entity, sid, tid, status, table, raw in records:
            if entity == "cari" and status == "imported" and tid is not None:
                parties.setdefault(str(sid), set()).add(int(tid))

        def party(sid):
            ids = parties.get(str(sid), set())
            return next(iter(ids)) if len(ids) == 1 else None

        movements = {int(r["id"]): r for r in session.execute(text(
            "SELECT f.id,f.hesap_id,f.tarih,f.hareket_turu,f.belge_no,f.tutar,"
            "h.hesap_adi,h.hesap_turu,h.alt_hesap_turu FROM finans_hareketleri f "
            "JOIN finans_hesaplari h ON h.id=f.hesap_id "
            "WHERE f.tarih BETWEEN :bas AND :bit"
        ), {"bas": bas.isoformat(), "bit": bit.isoformat()}).mappings()}
        return_columns = {col["name"] for col in inspect(session.connection()).get_columns("satis_iade_faturalari")}
        return_total = "tl_genel_toplam" if "tl_genel_toplam" in return_columns else "NULL AS tl_genel_toplam"
        returns = {int(r["id"]): r for r in session.execute(text(
            "SELECT id,iade_no,iade_tarihi,cari_id," + return_total + " FROM satis_iade_faturalari "
            "WHERE iade_tarihi BETWEEN :bas AND :bit"
        ), {"bas": bas.isoformat(), "bit": bit.isoformat()}).mappings()}
        seen = set()
        for entity, sid, tid, status, table, raw in records:
            if entity == "cari" or tid is None:
                continue
            tid = int(tid)
            if entity in ("33", "37"):
                if table != "satis_iade_faturalari" or tid not in returns:
                    continue
                f = returns[tid]
                # Bilinen kaynak belge doğrulanamazsa tutar rapora sessizce katılmaz.
                self.iadeler[tid] = {"onay": False, "cari_tutar": None, "hata": "Kaynak iade bağlantısı doğrulanamadı"}
                try:
                    doc = json.loads(raw)
                    h = doc["Ana"][0] if isinstance(doc["Ana"], list) else doc["Ana"]
                    if (status != "imported" or str(h.get("a_id")) != str(sid)
                            or str(h.get("a_tur")) != entity
                            or party(h.get("a_cari_id")) != f["cari_id"]
                            or _date(h.get("a_tarih")).isoformat() != f["iade_tarihi"]
                            or f["tl_genel_toplam"] is None
                            or _amount(h.get("a_tutar")) != _amount(f["tl_genel_toplam"])):
                        raise ValueError("Kaynak iade kimliği/cari/tarih/tutar farklı")
                    approved = str(h.get("a_onay")) == "1"
                    amount = None
                    if approved:
                        candidates = session.execute(text(
                            "SELECT alacak,borc FROM cari_islemleri WHERE belge_no=:no "
                            "AND cari_id=:cid AND tarih=:tarih AND islem_turu='İade'"
                        ), {"no": f["iade_no"], "cid": f["cari_id"], "tarih": f["iade_tarihi"]}).all()
                        if (len(candidates) == 1 and _amount(candidates[0][1]) == 0
                                and _amount(candidates[0][0]) == _amount(h.get("a_tutar"))):
                            amount = _amount(candidates[0][0])
                    self.iadeler[tid] = {"onay": approved, "cari_tutar": amount, "hata": ""}
                except (ValueError, KeyError, TypeError, IndexError, ArithmeticError) as exc:
                    self.iadeler[tid]["hata"] = str(exc)
                continue
            if status != "imported" or table != "finans_hareketleri" or tid not in movements:
                continue
            try:
                s = json.loads(raw)
                typ = str(s.get("a_tur_id"))
                # Firma kartı ödemeleri (24) müşteri tahsilatı/iadesi diye varsayılmaz.
                kinds = {"10": ("Nakit", 1, "KASA GİRİŞ"), "11": ("Nakit", -1, "KASA ÇIKIŞ"),
                         "20": ("Alınan havale", 1, "BANKA GİRİŞ"),
                         "21": ("Alınan havale", -1, "BANKA ÇIKIŞ"),
                         "25": ("Kredi kartı", 1, "BANKA GİRİŞ")}
                if typ not in kinds:
                    continue
                method, sign, movement_type = kinds[typ]
                if (entity == "kasa_hareket") != (typ in ("10", "11")):
                    continue
                m = movements[tid]
                source_in, source_out = _amount(s.get("a_giren")), _amount(s.get("a_cikan"))
                value, other = (source_in, source_out) if sign > 0 else (source_out, source_in)
                prefix = "EVB-KS-" if entity == "kasa_hareket" else "EVB-BN-"
                cid = party(s.get("a_ref_id"))
                if (str(s.get("a_id")) != str(sid) or not cid or value <= 0 or other != 0
                        or m["belge_no"] != prefix + str(sid) or m["hareket_turu"] != movement_type
                        or _date(s.get("a_tarih")).isoformat() != m["tarih"]
                        or _amount(m["tutar"]) != value
                        or str(s.get("DOV_KOD", s.get("Doviz_Kodu", ""))) not in ("TL", "TRY")
                        or Decimal(str(s.get("a_dov_kur", "0"))) != 1):
                    continue
                if entity == "kasa_hareket":
                    if m["hesap_turu"] != "KASA" or m["hesap_adi"] != s.get("a_kasa_ad"):
                        continue
                else:
                    if (m["hesap_turu"] != "BANKA" or m["alt_hesap_turu"] not in ("POS", "KMH", "MEVDUAT")
                            or m["hesap_adi"] not in (s.get("a_banka_ad"), str(s.get("a_banka_ad")) + " · POS")):
                        continue
                # Aynı finans hedefi iki kaynak izine bağlanmışsa belirsiz bırak.
                if tid in seen:
                    self.finans.pop(tid, None)
                    continue
                seen.add(tid)
                self.finans[tid] = {"yontem": method, "isaret": sign, "cari_id": cid,
                                    "tutar": value, "belge_no": m["belge_no"]}
            except (ValueError, KeyError, TypeError, ArithmeticError):
                continue

    def cari_bacagi(self, hareket, cid, toplam, sign):
        r = self.finans.get(int(hareket.id))
        if (r and r["cari_id"] == cid and r["isaret"] == sign
                and r["belge_no"] == hareket.belge_no):
            return r
        return None
