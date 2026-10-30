"""DENEME AKTARIM'da doğrulanmış eski ödemeleri bilgi bağlantısıyla tamamlar.
Finans/cari/stok hareketi veya uygulamanın tahsilat tablosuna satır eklemez.
"""
from __future__ import annotations
import json
import sqlite3
from contextlib import closing
from datetime import datetime
from decimal import Decimal
from pathlib import Path

UID = 'f6e88cd0-1a48-4a85-80b7-ca2fc5949738'
LABELS = {'10': 'NAKİT / KASA', '20': 'GELEN HAVALE', '25': 'KREDİ KARTIYLA TAHSİLAT'}
# Yalnız ayrıntılı incelemede toplamı eşleşen 64 belge; yeni kayıtlar bu araçla tahmin edilmez.
CANDIDATES = ('10095', '10123', '10147', '10334', '10452', '10509', '10523', '11845', '11926', '11995', '12150', '12326', '12699', '12867', '12998', '13082', '13148', '13283', '13645', '13772', '13775', '1393', '13936', '14173', '14273', '14277', '1434', '14415', '14493', '14528', '14556', '1929', '2232', '2270', '2422', '2587', '2737', '4182', '4241', '4298', '4434', '4744', '4964', '4993', '5506', '5653', '6150', '6234', '6489', '6838', '7020', '7496', '7710', '8373', '8463', '8673', '8682', '8717', '9281', '9282', '9551', '9729', '9794', '9894')


def money(v):
    d = Decimal(str(v or 0))
    if not d.is_finite():
        raise ValueError('Geçersiz tutar')
    return d.quantize(Decimal('.01'))


def iso(v):
    return datetime.strptime(str(v)[:10], '%d.%m.%Y').date().isoformat()


def connect(path, write=False):
    return sqlite3.connect(Path(path).resolve().as_uri() + ('?mode=rw' if write else '?mode=ro'), uri=True, timeout=10)


def identity(c):
    if c.execute('SELECT firma_kodu,unvan FROM firmalar').fetchall() != [('001', 'DENEME AKTARIM')]:
        raise ValueError('Yalnız 001 DENEME AKTARIM firmasına uygulanabilir.')
    meta = dict(c.execute('SELECT key,value FROM evo_import_metadata'))
    if meta.get('source_company') != '42178' or meta.get('target_company_uid') != UID:
        raise ValueError('Kaynak/hedef kimliği uyuşmuyor.')


def plan(c):
    identity(c)
    parties = {}
    for sid, tid in c.execute("SELECT source_id,target_id FROM evo_import_records WHERE entity='cari' AND status='imported'"):
        parties.setdefault(str(sid), set()).add(int(tid))
    for tid, code in c.execute("SELECT id,cari_kodu FROM cari_kartlar WHERE cari_kodu LIKE 'EVB-%' AND NOT is_deleted"):
        parties.setdefault(code[4:], set()).add(int(tid))
    groups = {}
    for ent, sid, tid, status, table, raw in c.execute("SELECT entity,source_id,target_id,status,target_table,source_json FROM evo_import_records WHERE entity IN ('banka_hareket','kasa_hareket')"):
        s = json.loads(raw)
        if str(s.get('a_modul_id')) == '1054':
            groups.setdefault(str(s.get('a_mudul_ref_id')), []).append((ent, sid, tid, status, table, s))
    ready, skipped = [], []
    linked = c.execute("SELECT 1 FROM sqlite_master WHERE name='evo_invoice_payment_links'").fetchone()
    for sid in CANDIDATES:
        try:
            tr = c.execute("SELECT target_id,status,target_table,source_json FROM evo_import_records WHERE entity='31' AND source_id=?", (sid,)).fetchone()
            if not tr or tr[1:3] != ('imported', 'satis_faturalari'):
                raise ValueError('Fatura aktarım izi eksik')
            fid = tr[0]; h = json.loads(tr[3])['Ana'][0]
            f = c.execute('SELECT fatura_no,cari_id,fatura_tarihi,tahsilat_tutari,tahsilat_sekli,tahsilat_hesabi,is_deleted,onaylandi,para_birimi,kur FROM satis_faturalari WHERE id=?', (fid,)).fetchone()
            if not f:raise ValueError('Fatura yok')
            no, cid, date, total, method, account, deleted, approved, pb, rate = f
            party = str(h.get('a_cari_id'))
            if (str(h.get('a_id')) != sid or str(h.get('a_tur')) != '31'
                    or parties.get(party) != {cid} or iso(h.get('a_tarih')) != date
                    or deleted or not approved or str(h.get('a_onay')) != '1'
                    or pb not in ('TRY','TL') or Decimal(str(rate)) != 1
                    or h.get('Doviz_Kodu') not in ('TL','TRY') or Decimal(str(h.get('a_dov_kur'))) != 1):
                raise ValueError('Fatura kimlik/cari/tarih/onay/döviz kontrolü başarısız')
            if c.execute('SELECT 1 FROM satis_faturasi_tahsilatlari WHERE fatura_id=?', (fid,)).fetchone():
                raise ValueError('Ayrıntılı tahsilat tablosunda kayıt mevcut')
            legs = []; used = set()
            for ent, psid, tid, status, table, s in groups.get(sid, []):
                typ = str(s.get('a_tur_id'))
                if (typ not in LABELS or status != 'imported' or table != 'finans_hareketleri'
                        or str(s.get('a_id')) != psid or str(s.get('a_ref_id')) != party
                        or (ent == 'kasa_hareket') != (typ == '10') or tid in used):
                    raise ValueError('Kaynak ödeme kimliği/türü/cari farklı')
                used.add(tid)
                value = money(s.get('a_giren')); pdate = iso(s.get('a_tarih'))
                if (value <= 0 or money(s.get('a_cikan')) != 0 or money(s.get('a_ref_giren')) != 0
                        or money(s.get('a_ref_cikan')) != value
                        or str(s.get('DOV_KOD',s.get('Doviz_Kodu'))) not in ('TL','TRY')
                        or Decimal(str(s.get('a_dov_kur'))) != 1):raise ValueError('Ödeme tutar/yön/döviz farklı')
                doc = ('EVB-KS-' if ent == 'kasa_hareket' else 'EVB-BN-') + psid
                m = c.execute('SELECT f.hesap_id,f.tarih,f.belge_no,f.tutar,h.hesap_adi,h.hesap_turu,h.alt_hesap_turu,f.hareket_turu FROM finans_hareketleri f JOIN finans_hesaplari h ON h.id=f.hesap_id WHERE f.id=?', (tid,)).fetchone()
                if (not m or m[1] != pdate or m[2] != doc or money(m[3]) != value
                        or m[7] != ('KASA GİRİŞ' if typ == '10' else 'BANKA GİRİŞ')):raise ValueError('Hedef finans farklı')
                if c.execute('SELECT count(*) FROM finans_hareketleri WHERE belge_no=?', (doc,)).fetchone()[0] != 1:raise ValueError('Mükerrer belge numarası')
                if typ == '10':
                    if m[5] != 'KASA' or m[4] != s.get('a_kasa_ad'):raise ValueError('Kasa farklı')
                elif (m[5] != 'BANKA' or m[6] not in ('POS','KMH','MEVDUAT')
                        or m[4] not in (s.get('a_banka_ad'),str(s.get('a_banka_ad'))+' · POS')):raise ValueError('Banka hesabı farklı')
                ls = c.execute('SELECT id,cari_id,tarih,borc,alacak FROM cari_islemleri WHERE belge_no=?', (doc,)).fetchall()
                if (len(ls) != 1 or ls[0][1] != cid or ls[0][2] != pdate
                        or money(ls[0][3]) != 0 or money(ls[0][4]) != value):raise ValueError('Hedef cari hareketi farklı')
                legs.append({'entity':ent,'source_id':psid,'finance_id':tid,'ledger_id':ls[0][0],
                             'date':pdate,'amount':str(value),'method':LABELS[typ],'account':m[4]})
            if not legs or money(sum((Decimal(x['amount']) for x in legs),Decimal(0))) != money(total) or money(h.get('a_tutar_kapanan')) != money(total):raise ValueError('Fatura toplamı ile bağlı tahsilat farklı')
            methods = {x['method'] for x in legs}; accounts = {x['account'] for x in legs}
            new_method = next(iter(methods)) if len(methods) == 1 else None
            new_account = next(iter(accounts)) if len(accounts) == 1 else None
            if linked and c.execute('SELECT 1 FROM evo_invoice_payment_links WHERE invoice_id=?',(fid,)).fetchone():
                old=c.execute('SELECT entity,source_id,finance_id,ledger_id,method,account,amount FROM evo_invoice_payment_links WHERE invoice_id=? ORDER BY entity,source_id',(fid,)).fetchall()
                desired=sorted((x['entity'],x['source_id'],x['finance_id'],x['ledger_id'],x['method'],x['account'],x['amount']) for x in legs)
                if old!=desired:raise ValueError('Önceki bağlantı değişmiş')
                if new_method is not None and (method!=new_method or account!=new_account):raise ValueError('Önceki başlık düzeltmesi değişmiş')
                skipped.append({'source_id':sid,'reason':'Zaten tamamlandı'});continue
            if method not in (None,'') or account not in (None,''):raise ValueError('Başlık ödeme alanı dolu; değiştirilmedi')
            ready.append({'source_id':sid,'invoice_id':fid,'invoice':no,'party_source':party,'party_id':cid,
                          'method':new_method,'account':new_account,'legs':legs})
        except (ValueError,KeyError,TypeError,IndexError,ArithmeticError) as exc:
            skipped.append({'source_id':sid,'reason':str(exc)})
    return ready, skipped


def apply(path, output):
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    with closing(connect(path,True)) as c:
        c.execute('BEGIN IMMEDIATE')
        try:
            ready,skipped=plan(c)
            backup=None
            if ready:
                if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or c.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('Bütünlük hatası')
                backup=out/'BAGLANTI_ONCESI.sqlite'
                if backup.exists():raise ValueError('Yedek mevcut; yeni çıktı klasörü gerekli')
                with closing(connect(path)) as src,closing(sqlite3.connect(backup)) as dst:
                    src.backup(dst)
                    if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Yedek hatası')
                c.execute('CREATE TABLE IF NOT EXISTS evo_invoice_payment_links(invoice_id INTEGER NOT NULL,entity TEXT NOT NULL,source_id TEXT NOT NULL,finance_id INTEGER NOT NULL,ledger_id INTEGER NOT NULL,method TEXT NOT NULL,account TEXT NOT NULL,amount TEXT NOT NULL,linked_at TEXT NOT NULL,PRIMARY KEY(entity,source_id),UNIQUE(invoice_id,finance_id))')
                c.execute('CREATE TABLE IF NOT EXISTS evo_payment_links_audit(invoice_id INTEGER PRIMARY KEY,source_id TEXT NOT NULL,old_method TEXT,old_account TEXT,new_method TEXT,new_account TEXT,backup_path TEXT,changed_at TEXT)')
                for r in ready:
                    now=datetime.now().isoformat()
                    for x in r['legs']:
                        c.execute('INSERT INTO evo_invoice_payment_links VALUES (?,?,?,?,?,?,?,?,?)',(r['invoice_id'],x['entity'],x['source_id'],x['finance_id'],x['ledger_id'],x['method'],x['account'],x['amount'],now))
                    if r['method'] is not None:
                        c.execute('UPDATE satis_faturalari SET tahsilat_sekli=?,tahsilat_hesabi=? WHERE id=?',(r['method'],r['account'],r['invoice_id']))
                    c.execute('INSERT INTO evo_payment_links_audit VALUES (?,?,?,?,?,?,?,?)',(r['invoice_id'],r['source_id'],None,None,r['method'],r['account'],str(backup),now))
                if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or c.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('Son bütünlük hatası')
            c.commit()
        except Exception:c.rollback();raise
    result={'linked_invoices':len(ready),'header_updates':sum(x['method'] is not None for x in ready),'rows':ready,'skipped':skipped,'backup':str(backup) if backup else None}
    (out/'SONUC.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
