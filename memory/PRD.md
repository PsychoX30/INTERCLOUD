# Intercloud Portal - PRD & Progress

## Original Problem Statement
Portal manajemen Intercloud Digital (FastAPI + React + MongoDB): billing (Duitku), NOC/MikroTik live ops, CRM, CMS/SEO, finance, ticket, multi-role staff. Round 3 (sesi ini): mengerjakan backlog NgodingPakeAI plan `dd3e43ef-1bc5-47d3-97f3-160da4a8309a` (PRD v10) dengan kebijakan **Verifikasi + Sinkronisasi** (fitur yang sudah ada diverifikasi, fitur baru diimplementasikan; tetap di stack existing React+FastAPI, TANPA migrasi Remix). Hasil UAT.xlsx user (35 item, 34 FAIL versi lama) dilacak di `/app/memory/UAT_issues.md`.

## Aturan Ketat
- TANPA em-dash/en-dash di seluruh aplikasi. Navy #0a2350 + Yellow #f5b120.
- Pajak manual (PPN default), Duitku satu-satunya gateway, single APScheduler.
- Loop task NgodingPakeAI: SATU task per satu; BERHENTI tiap ganti layer/fase (checkpoint user).
- Kredensial integrasi real user ada di /app/memory/test_credentials.md (Duitku, Proxmox, reCAPTCHA, SMTP, RNA.id).

## Status Loop NgodingPakeAI (2026-07-29)
- ✅ FASE 1 LAYER FRONTEND SELESAI (semua 30 task frontend done)
- ⛔ CHECKPOINT: task berikutnya = layer BACKEND ("Buat skema database MongoDB untuk dashboard dan notifikasi", Dashboard Utama, remainingInLayer 52). MENUNGGU user bilang "lanjut".

## Yang dikerjakan sesi ini (2026-07-29, fase 1 frontend)
1. **Dashboard admin**: Pusat Notifikasi (invoice overdue + device down, auto-refresh 60s), Tagihan Terbaru, System Health REAL dari registry integrations (UAT-014 DONE), responsif mobile (fix min-w-0 overflow).
2. **Self-service klien (ClientServices)**: kontrol VM start/stop/reboot LIVE via Proxmox (endpoint client-scoped + audit + self_service_log), reset password guest via QEMU agent (fail-fast 15s), panel Upgrade resource (quote prorata + PPN + invoice selisih otomatis + pending_upgrade guard).
3. **Proxmox integration**: DIKONFIGURASI LIVE (https://157.20.32.249:8006, node1, PVE 8.4.0) via integrations-v2; test connection OK; VM start/stop diuji live pada VM 108 (NOCS, dikembalikan ke stopped).
4. **AdminServices**: DataTable + modal detail provisioning (config, provision log, self-service log, pending upgrade).
5. **AdminUsers**: modal Client Profile 360 (stats, outstanding, Akun Hosting, layanan, invoice terakhir) - endpoint GET /admin/users/{uid}/profile (parsial UAT-016).
6. **ClientDomains (BARU, /portal/client/domains + nav)**: cek ketersediaan (mock), WHOIS lookup (mock), Domain Suggestion (mock), status order + tombol perpanjang, notifikasi sukses + pengingat kedaluwarsa. INTEGRASI RNA.id LIVE MENYUSUL DI FASE BACKEND (MOCKED).
7. **AdminAssets**: field status active/disposed (backend+form+kolom), depresiasi bulanan+tahunan di tabel, progress bar nilai buku/umur pakai.
8. **AdminFinance**: Summary jadi Laporan Laba Rugi dengan baris "Beban depresiasi aset" terpisah (UAT-031 semantik benar; revenue utuh).
9. **ClientOrder**: LiveTotalBar estimasi harga real-time di step Configure & Add-ons (opsi & addon sudah ada sebelumnya).
10. **Landing**: LeadForm (lead capture, MOCK submit - CRM+reCAPTCHA menyusul backend), Testimonials (mock), responsif mobile OK.
11. **AdminNOC**: NetflowSankey (diagram Sankey interaktif + tooltip bantuan, data MOCK), DDoSPanel (insiden mock + tombol Blackhole IP memanggil API MikroTik REAL), ThresholdRules (CRUD lokal mock), DDoSHistory (mock + filter), NotifChannels (CRUD lokal mock), BlackholeLog (mock + search).
12. Regresi: pytest 422 passed, 34 skipped (hijau penuh).

## Catatan MOCKED (menunggu fase backend dari task loop)
- Domain page (cek/WHOIS/suggestion/order) = MOCK → RNA.id API.
- Lead form submit = MOCK → CRM + reCAPTCHA v3.
- Netflow Sankey, insiden DDoS, threshold rules, notif channels, blackhole log = data MOCK (blackhole button = API real).
- Testimoni landing = data MOCK.

## Backlog / Next
- P0: LANJUTKAN loop backend fase 1 setelah user konfirmasi ("Buat skema database MongoDB untuk dashboard dan notifikasi", dst; 52 task backend).
- P1: Item UAT.xlsx yang belum tersentuh (lihat /app/memory/UAT_issues.md): drag-drop upload Documents (003), torch wildcard (004), article search (005), IP Pool (008), ISO live (009), reCAPTCHA (010), close ticket (011), delete user UI (013), impersonate (015), credit note preview (017), CRM quick contact/prospect sync (020-022), content planner sync + libur nasional (023-024), follow-up dari CRM (025), CMS layman + 100% editable (026-027), mobile sign-out (028), quick action role-based (029), notif security SMTP (030), sales fee/slip gaji dropdown+PDF (032-034), Excel formula (035).
- P1 (dari fork sebelumnya): Cash-flow Forecast 30/60/90 hari di AdminFinance.
- P2: DataTable rollout (AdminOrders, AdminMikrotik), Zod+react-hook-form, Email test button, asymmetric bento landing.

## Arsitektur
- backend/portal/routes.py (~8000 baris, semua route /api/portal/*), integrations_v2.py (ProxmoxClient + vm_status + set_user_password), audit.py.
- frontend/src/pages/portal/{admin,client}/*, components/* (LeadForm, Testimonials baru), App.js routes.
- Koleksi baru/berubah: services.pending_upgrade + self_service_log, invoices.upgrade, assets.status/disposed_at, integration_settings.proxmox (enabled, live).

## Kredensial
Lihat /app/memory/test_credentials.md (admin, demo client, integrasi real).
