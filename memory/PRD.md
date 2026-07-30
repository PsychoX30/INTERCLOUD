# Intercloud Portal - PRD & Progress

## Original Problem Statement
Portal manajemen Intercloud Digital (FastAPI + React + MongoDB): billing (Duitku), NOC/MikroTik live ops, CRM, CMS/SEO, finance, ticket, multi-role staff. Backlog dikelola via NgodingPakeAI plan `dd3e43ef-1bc5-47d3-97f3-160da4a8309a` dengan kebijakan **Verifikasi + Sinkronisasi**.

## Aturan Ketat
- TANPA em-dash/en-dash. Navy #0a2350 + Yellow #f5b120.
- Pajak manual (PPN default dari billing settings), Duitku satu-satunya gateway, single APScheduler.
- Kredensial integrasi real user: Duitku, Proxmox, reCAPTCHA, SMTP, RNA.id (lihat test_credentials.md).

## STATUS NGODINGPAKEAI: SEMUA 209+ TASK SELESAI (2026-07-30). "No open tasks" di CLI.

## Yang dikerjakan sesi 2026-07-30 (lanjutan)
### Fitur besar baru (semua dites testing_agent iteration_35: 14/14 backend + 5/5 frontend PASS)
1. **2FA TOTP staf/klien lengkap** (pyotp + qrcode, secret Fernet-encrypted): /auth/2fa/setup (QR+secret), verify-enable (10 recovery codes bcrypt), login 2 langkah (/auth/login → require_2fa + mfa_token → /auth/login/2fa TOTP/recovery sekali-pakai), disable, /admin/users/{uid}/reset-2fa, badge 2FA + reset di AdminUsers, panel TwoFactorPanel di halaman Settings/password, UI step-2 di PortalLogin. File: backend/portal/twofa.py, frontend TwoFactorPanel.jsx.
2. **Impersonasi klien** (UAT-015): POST /admin/users/{uid}/impersonate (audit-logged, client-only), tombol di AdminUsers, banner indigo + "Kembali ke Admin" di PortalLayout (localStorage ic_admin_return).
3. **Lead Form Builder**: form_configs CRUD /admin/form-builder, GET /portal-public/forms/{slug}, POST submit dengan validasi server-side per field (422 detail.errors) + reCAPTCHA + auto-buat lead + CRM prospect. AdminFormBuilder.jsx (editor field: tipe/label/key/required/placeholder/options, urutan naik-turun, preview live, aktif/nonaktif) + halaman publik /form/:slug (PublicForm.jsx). Form contoh: slug `kontak`.
4. **IP Pool** (UAT-008): POST /admin/dcim/prefixes/{pid}/allocate (IP bebas berikutnya via ipaddress), GET utilization, alokasi otomatis saat provisioning hosting/VPS (fallback mock IP), tombol Allocate IP di DCIM Prefixes.
5. **Ticket**: reply internal (klien tidak melihat), GET /admin/tickets/{tid}/timeline, GET /admin/noc/devices/{did}/tickets, tab Aktif/Arsip/Semua (?view=), chip perangkat terkait di detail, toggle "Catatan internal" di reply form.
6. **Pagination server-side opsional** (?page&limit → {items,total,page,pages}) di /admin/users, invoices, orders, tickets (tanpa page tetap array; backward compatible).
7. **Backup**: POST /admin/backup/trigger, GET history (+download per id), scheduler harian 03:30 (retensi 14), panel riwayat di AdminBackup.
8. **UTM links** persist: GET/POST/DELETE /admin/utm-links + tombol Simpan + daftar tersimpan di AdminUTMBuilder.
9. **Auto follow-up** H+1 saat lead publik masuk (followups: "Follow up lead baru: ...").
10. **Kirim invoice**: POST /admin/invoices/{iid}/send (email via template + wa.me link) + tombol "Kirim ke Klien" di detail invoice.
11. **Excel formula aktif** (UAT-035): laporan bulanan/tahunan xlsx memakai nilai numerik + formula =SUM()/referensi cell.
12. **Edit pesanan**: PUT /admin/orders/{oid} (notes/config + provision_log) + edit catatan di modal OrderDetail.
13. **Hari libur nasional 2026** di Content Calendar (endpoint /admin/content-calendar/holidays + penanda merah di grid).
14. **CRM quick contact** (UAT-020): tombol WA/telepon/email di baris CRM.
15. reCAPTCHA v3 AKTIF kembali (site key terdaftar utk domain preview + produksi). RNA.id LIVE (source:"rna", IP 35.225.230.28 sudah whitelisted).

### Sesi sebelumnya hari yang sama
Convert quotation→invoice + detail invoice deep-link + PPN per dokumen + credit note klien + potong invoice + slip gaji/fee sales PDF + auto-renewal layanan + indikator dunning + order detail modal + panel skor login reCAPTCHA (sudah ada di AdminSecurity).

## PENTING: reCAPTCHA & testing otomatis
- reCAPTCHA v3 AKTIF. Login otomatis (curl/bot) DITOLAK by design. Pytest: conftest auto-disable + restore.
- Untuk testing agent/browser automation: disable dulu via Mongo integration_settings (provider recaptcha) lalu AKTIFKAN kembali.
- 2FA: JANGAN tinggalkan 2FA aktif di akun test (demo@client.com harus totp_enabled=false setelah test).

## Arsitektur
- backend/portal/routes.py (~10.200 baris), twofa.py (baru), emails.py (scheduler: renewal, dunning, NOC, DDoS, backup 03:30), backups.py, diagnostics.py (ping/traceroute/dns/whois/blacklist/portscan/torch), audit.py, security.py (CSP, rate-limit).
- Koleksi baru: form_configs, utm_links, backup_history, dcim_ips (allocated), users.totp_* & recovery_codes.
- Frontend baru: AdminFormBuilder.jsx, PublicForm.jsx (/form/:slug), TwoFactorPanel.jsx, AdminInvoiceDetail.jsx, TaxPercentField.jsx, ClientCreditNotes.jsx.

## Backlog / Next (P1-P2)
- UAT sisa minor: torch wildcard UI polish (004), article search (005 - backend search ada), ISO live dari Proxmox real (009 - saat ini daftar configurable/mock), delete user UI (013), credit note preview (017), CMS layman (026-027), mobile sign-out (028), quick action role-based (029), notif security SMTP (030).
- P2: DataTable rollout AdminMikrotik, Zod+react-hook-form, bento landing.

## Kredensial
Lihat /app/memory/test_credentials.md.
