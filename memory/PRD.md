# Intercloud Portal - PRD & Progress

## Original Problem Statement
Portal manajemen Intercloud Digital (FastAPI + React + MongoDB): billing (Duitku), NOC/MikroTik live ops, CRM, CMS/SEO, finance, ticket, multi-role staff. Mengerjakan backlog NgodingPakeAI plan `dd3e43ef-1bc5-47d3-97f3-160da4a8309a` dengan kebijakan **Verifikasi + Sinkronisasi** (fitur existing diverifikasi, fitur baru diimplementasikan; stack tetap React+FastAPI). UAT.xlsx user dilacak di `/app/memory/UAT_issues.md`.

## Aturan Ketat
- TANPA em-dash/en-dash di seluruh aplikasi. Navy #0a2350 + Yellow #f5b120.
- Pajak manual (PPN default), Duitku satu-satunya gateway, single APScheduler.
- Loop task NgodingPakeAI: SATU task per satu (start → kerjakan → complete → next).
- Kredensial integrasi real user di /app/memory/test_credentials.md (Duitku, Proxmox, reCAPTCHA, SMTP, RNA.id).

## Status Loop NgodingPakeAI (update 2026-07-30 sesi ini)
- ✅ FASE 1 FRONTEND + ~20 task backend fase 1 selesai (sesi sebelumnya).
- ✅ Sesi ini: 10 task selesai (8 Billing & Invoice + 2 Provisioning). Sisa 17 task di plan.
- Task berikutnya di loop: lanjut `task next -p dd3e43ef-...` (fitur Provisioning Server & Hosting dst).

## Yang dikerjakan SESI INI (2026-07-30)
1. **FIX KRITIS**: backend crash karena `m.QuotationConvertIn` tidak ada (sisa pekerjaan agent sebelumnya). Model dibuat, backend pulih.
2. Convert quotation → invoice: tombol "Buat Invoice" + modal di AdminQuotations (idempoten, badge nomor invoice bila sudah dikonversi).
3. Halaman detail invoice deep-link `/portal/admin/invoices/:id` (AdminInvoiceDetail.jsx) + endpoint `GET /admin/invoices/{iid}` + row click dari daftar invoice + salin tautan.
4. Komponen PPN per dokumen (TaxPercentField.jsx): default dari `/admin/billing/settings`, override per dokumen, tombol reset ke default. Dipakai di form invoice & quotation.
5. Halaman Credit Notes klien `/portal/client/credit-notes` (ClientCreditNotes.jsx) + nav + total kredit diterapkan + unduh PDF.
6. Komponen potong invoice dengan credit note (CreditDeduction di AdminInvoiceDetail): daftar CN per invoice, tombol Terapkan, kredit diterapkan + sisa tagihan.
7. Slip fee sales PDF: endpoint `GET /documents/sales-fee-slip/{sid}` (WeasyPrint) + tombol Slip di tab Sales Fees AdminFinance.
8. Laporan keuangan Excel (bulanan/tahunan) + ekspor Proyeksi Kas PDF/XLSX: DIVERIFIKASI berfungsi (endpoint /admin/finance/report/*, /admin/finance/cashflow-forecast/export).
9. Auto-renewal per layanan: field `auto_renew` + `PUT /client/services/{sid}/auto-renew` + toggle di ClientServices; sweep renewal skip layanan dengan auto_renew=false.
10. Indikator dunning & suspensi di Client Profile 360 (AdminUsers): level clear/reminder/urgent/suspended, invoice overdue + hari lewat tempo, layanan suspended + alasan.
11. Order detail modal di AdminOrders (config, invoice link, provision log lengkap).
12. **reCAPTCHA v3 AKTIF** (permintaan eksplisit user): enabled=true di integration_settings. User sudah menambahkan domain preview ke key Google. Diverifikasi end-to-end: token diterbitkan, verifikasi Google jalan, bot ditolak (skor 0.1 < min 0.5). Login manusia normal lolos. Lead form juga terlindungi.
13. Pytest conftest: auto-disable reCAPTCHA saat suite berjalan, restore setelah selesai (sessionstart/sessionfinish snapshot). Fix test reset-password yang flaky karena SMTP real aktif (token tak lagi dicetak ke log → skip).
14. Regresi: pytest 422 passed, 33 skipped, 1 flaky fixed.

## PENTING: reCAPTCHA & testing otomatis
- reCAPTCHA v3 AKTIF di login/register/forgot/lead. Login otomatis (curl tanpa token, browser bot) DITOLAK by design.
- Pytest aman: conftest menonaktifkan sementara lalu memulihkan.
- Untuk testing agent/browser automation: nonaktifkan dulu via Mongo `integration_settings.update_one({provider:'recaptcha'},{$set:{enabled:false}})`, lalu AKTIFKAN KEMBALI setelah selesai.

## Whitelist IP RDASH/RNA.id (manual oleh user)
- IP egress server preview: **35.225.230.28** → daftarkan di dashboard RDASH (menu API/IP Whitelist).
- Jika deploy produksi, IP bisa berbeda; tambahkan IP produksi juga.

## Backlog / Next
- P0: Lanjut loop NgodingPakeAI (17 task tersisa; berikutnya fitur Provisioning Server & Hosting, lalu Monitoring Jaringan, CRM, dsb).
- P1: Item UAT.xlsx belum tersentuh (lihat /app/memory/UAT_issues.md): torch wildcard (004), article search (005), IP Pool (008), ISO live (009), delete user UI (013), impersonate (015), credit note preview (017), CRM quick contact/prospect sync (020-022), content planner sync + libur nasional (023-024), follow-up dari CRM (025), CMS layman (026-027), mobile sign-out (028), quick action role-based (029), notif security SMTP (030), Excel formula (035).
- P2: DataTable rollout (AdminMikrotik), Zod+react-hook-form, asymmetric bento landing.

## Arsitektur
- backend/portal/routes.py (~9500 baris, semua route /api/portal/*), models.py, emails.py (renewal sweep + dunning), integrations_v2.py (Recaptcha verifier, RNA, Proxmox, dll).
- frontend/src/pages/portal/{admin,client}/*; komponen baru sesi ini: AdminInvoiceDetail.jsx, TaxPercentField.jsx, ClientCreditNotes.jsx.
- Koleksi berubah: services.auto_renew, quotations.converted_invoice_*, invoices.source_quotation_*.

## Kredensial
Lihat /app/memory/test_credentials.md (admin + demo client; catatan reCAPTCHA).
