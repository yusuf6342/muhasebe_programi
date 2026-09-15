# Silinen Kayıtlar ve Geri Yükleme Merkezi — Plan

## Yaklaşım
- Soft delete öncelikli: `is_deleted` + log; muhasebe belgelerinde rastgele fiziksel DELETE yok.
- Servis: `deleted_record_service.py` (`AuditDeleteService`, `RestoreService`, `safe_log_cancel`, `safe_log_cancel_snapshot`).
- UI: Sistem Yönetimi → Silinen Kayıtlar (+ yönetici: Eski Log Temizle).

## Phase A — tamam
Soft-delete cari/stok/taslak fatura + merkez UI + testler.

## Phase B — tamam
Belge iptal logları: satış/alış sipariş·irsaliye·fatura·iade, hizmet, çek/senet, KK.

## Phase C — tamam (bu oturum)
| Kaynak | Log |
|--------|-----|
| Cari virman iptal | `cari_virman` snapshot |
| Muhasebe fiş iptal | `muhasebe_fisi` (otomatik iptalde log yok) |
| Stok birleştir (kaynak silme) | `stok_birlestir` snapshot |
| Kapalı dönem | restore preview/validate engeli |
| Fiziksel purge | yalnızca yönetici; restored + cancel(can_restore=False); aktif soft-delete korunur; purge audit logu yazılır |

## Bilinçli olarak bağlanmayanlar
- Finans iç rewrite `session.delete` (makbuz yeniden yazımı)
- System DB kullanıcı/firma pasife
- İptal belgelerinin otomatik muhasebe reverse restore (`can_restore=False`)
