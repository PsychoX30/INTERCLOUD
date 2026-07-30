# Intercloud Portal - PRD & Progress

## Original Problem Statement
Portal manajemen Intercloud Digital (FastAPI + React + MongoDB): billing (Duitku), NOC/MikroTik live ops, CRM, CMS/SEO, finance, ticket, multi-role staff. Backlog dikelola via NgodingPakeAI plan `dd3e43ef-1bc5-47d3-97f3-160da4a8309a` dengan kebijakan **Verifikasi + Sinkronisasi**.

## Aturan Ketat
- TANPA em-dash/en-dash. Navy #0a2350 + Yellow #f5b120.
- Pajak manual (PPN default dari billing settings), Duitku satu-satunya gateway, single APScheduler.
- Kredensial integrasi real user: Duitku, Proxmox, reCAPTCHA, SMTP, RNA.id (lihat test_credentials.md).
- Bahasa respons ke user: INDONESIA.

## STATUS NGODINGPAKEAI: SEMUA 209+ TASK SELESAI (2026-07-30). "No open tasks" di CLI.

## Sesi 2026-07-30 (lanjutan 2): PRODUCTION READINESS - SELESAI & DITES (iteration_36: 11/11 backend + 14/15 frontend PASS, 1 miss hanya heuristik helper Playwright)
1. **UAT minor selesai**:
   - Article search: sudah ada di admin (articles-search) & publik (/articles?q=) - diverifikasi berfungsi.
   - Delete user dari UI: tombol Delete merah per baris di AdminUsers (data-testid delete-user-{email}), confirm dialog, tidak muncul untuk akun sendiri. Endpoint DELETE /admin/users/{uid} (audit-logged).
   - Mobile sign-out: tombol logout di header (data-testid mobile-logout-btn, lg:hidden) - klik -> redirect /portal/login.
2. **Sinkronisasi hak akses**: ADMIN_MENU_CATALOG (+form_builder, +status_page, -user_settings), fix key frontend site-content -> site_content (PortalLayout). Role menus diverifikasi: sales, support, ticket_only, override menu_keys via Manage Access modal.
3. **HAPUS SEMUA MOCK (production ready)**:
   - `mock_test_connection` DIHAPUS dari integrations_registry.py. Test koneksi module-hub kini REAL via `_live_test_connection` (routes.py ~3567) memakai klien iv2 (cPanel/Plesk/DirectAdmin/Proxmox/MikroTik/SMTP/Duitku/Midtrans/Xendit; whois/blacklist = HTTP reachability). Tetap mengembalikan {ok, message, latency_ms}.
   - `_auto_provision`: TANPA fake success. Hosting tanpa panel aktif / Proxmox tanpa integrasi -> provision_status "pending", service status "pending", log jelas + follow-up admin otomatis (`_notify_admin_manual_provision` -> koleksi followups). VPS live path: iv2.ProxmoxClient.clone_vm bila proxmox enabled. Fake IP 103.28.14.x dihapus (hanya IP pool DCIM real).
   - Traffic report klien: tidak ada data mock. Membaca koleksi `traffic_samples` (siap untuk kolektor real); kosong -> {available:false, message} + kartu "Data trafik belum tersedia" (traffic-unavailable) di ClientTraffic.jsx.
   - Halaman Admin Provisioning (AdminMockedScreens.jsx): tombol kini memanggil endpoint REAL `POST /admin/provisioning/proxmox/create` & `/admin/provisioning/hosting/create` (400 + pesan Indonesia bila integrasi belum aktif; 400 juga utk error live spt "clone requires template_vmid"). Konsol noVNC mock dihapus. Import mati AdminSubscriptions dihapus dari App.js.
4. **Keamanan kredensial**: git TIDAK melacak .env / test_credentials.md (dicek git ls-files + check-ignore). Tidak ada secret hardcoded di file tracked (hanya FAKE keys di tests). seed.py: default password dev "AdminIntercloud2026!" hanya dipakai bila /app/memory ada (env dev); di production tanpa ADMIN_PASSWORD -> generate acak + must_change_password + log sekali. _write_credentials_file hanya menulis di env dev (skip di production).
5. **Installer (scripts/install.sh)**: sudah production-grade (Mongo 8 + auth, nginx+CSP, certbot, fail2ban, ufw, supervisor, backup cron, WeasyPrint check, seed HANYA 1 admin dgn password acak + must-change). Ditambah PUBLIC_URL=/ di frontend .env build & komentar seeder diperbaiki. requirements.txt sudah memuat pyotp+qrcode (dipasang via pip -r).
6. Test: pytest full 434 passed (2 flake paralel xdist terverifikasi pass saat isolasi: race 2FA di demo@client.com & timeout beban); test_portal traffic & integration-test assertions diupdate ke perilaku produksi.

## PENTING: reCAPTCHA & testing otomatis
- reCAPTCHA v3 AKTIF KEMBALI (di-disable sementara saat testing, sudah di-enable lagi). Login otomatis (curl/bot) DITOLAK by design.
- Untuk testing agent/browser automation: disable dulu via Mongo integration_settings (provider recaptcha) lalu AKTIFKAN kembali.
- 2FA: demo@client.com totp_enabled=false (diverifikasi).
- Proxmox integration_settings enabled dgn kredensial REAL (157.20.32.249) tapi tanpa clone_template_vmid -> clone gagal jujur. Untuk auto-provision VPS live, set options.clone_template_vmid.

## LEARNING (untuk agent berikutnya)
- JANGAN paralel search_replace pada FILE YANG SAMA - saling menimpa (edit menu catalog sempat hilang). Serialisasi edit pada file yang sama.
- Cloudflare menyamarkan respons 502 backend dgn halaman HTML-nya - pakai 400 utk error detail yang harus terlihat client.

## Arsitektur
- backend/portal/routes.py (~10.300 baris), twofa.py, emails.py (scheduler), backups.py, diagnostics.py, audit.py, security.py, seed.py (admin-only, production-safe), integrations_v2.py (klien real), integrations_registry.py (schema module hub, tanpa mock).
- Endpoint baru: POST /admin/provisioning/proxmox/create, POST /admin/provisioning/hosting/create.
- Koleksi: traffic_samples (sumber traffic report real, kosong secara default), followups (dipakai notifikasi provisioning manual).
- Frontend: PortalLayout.jsx (mobile-logout-btn, site_content), AdminUsers.jsx (delete + confirm), ClientTraffic.jsx (empty state), AdminMockedScreens.jsx (provisioning real).

## Backlog / Next (P1-P2)
- P1: Set clone_template_vmid Proxmox agar auto-provision VPS live end-to-end; kolektor traffic_samples (SNMP/MikroTik) utk Traffic Report live.
- P2 UAT sisa: torch wildcard UI polish (004), ISO live dari Proxmox real (009), credit note preview (017), CMS layman (026-027), quick action role-based (029), notif security SMTP (030).
- P2: DataTable rollout AdminMikrotik, Zod+react-hook-form, bento landing.

## Kredensial
Lihat /app/memory/test_credentials.md (dev only; production: installer generate acak / operator-set).
