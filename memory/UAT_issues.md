# UAT Checklist (dari UAT.xlsx user, versi sebelumnya) - wajib diperbaiki

Status: OPEN = belum diperbaiki, FIXED-VERIFY = diperbaiki tapi butuh verifikasi, DONE = fixed + verified di sesi ini.

| ID | Modul | Masalah | Status |
|----|-------|---------|--------|
| 002 | Duitku | Payment gateway 400 Bad Request | FIXED-VERIFY (Batch 6 live-verified, retest) |
| 003 | Documents | Drag & drop upload lokal belum ada (hanya URL) | OPEN |
| 004 | Torch | Error jika src/dst 0.0.0.0/0 (wildcard) | OPEN (verify) |
| 005 | Article Search | Search tidak menampilkan hasil | OPEN (verify) |
| 006 | Proxmox | Provisioning masih mock | IN PROGRESS (client VM control real, sesi ini) |
| 007 | Proxmox | Service sisi klien masih mock + assign IP | IN PROGRESS |
| 008 | IP Pool | Fitur add IP pool belum ada | OPEN |
| 009 | ISO | ISO list belum live dari server | OPEN |
| 010 | reCAPTCHA | Missing recaptcha token / lambat | OPEN (keys tersedia dari user) |
| 011 | Ticket | Tidak ada opsi close ticket | OPEN (verify) |
| 012 | Email Invoice | Tombol Open Invoice ke 404 | FIXED-VERIFY (Batch 6 deep-link) |
| 013 | UAC | Tidak ada menu hapus user | OPEN (verify) |
| 014 | Dashboard | System health tidak live | DONE (sesi ini, health real dari integrations) |
| 015 | Impersonate | Belum ada fitur | OPEN |
| 016 | User 360 | Detail order/invoice/outstanding per user | OPEN |
| 017 | Credit Note | Hanya download, tidak bisa preview | OPEN (verify) |
| 018 | Credit Saldo | Potong invoice & alokasi saldo | FIXED-VERIFY (Batch 7 apply) |
| 019 | Credit Note | Cancel belum ada | FIXED-VERIFY (Batch 7 cancel) |
| 020 | CRM | Prospect tidak auto jadi existing setelah order | OPEN (verify) |
| 021 | CRM | Button quick contact WA/webmail belum ada | OPEN (verify) |
| 022 | Email Blast | Belum terhubung CRM | OPEN (verify) |
| 023 | Content Planner | Tidak sinkron ke calendar | OPEN (verify) |
| 024 | Calendar | Hari libur Indonesia belum muncul | OPEN |
| 025 | Follow-up | List customer tidak dari CRM (ketik manual) | OPEN (verify) |
| 026 | Landing CMS | Bahasa teknis, sulit untuk tim awam | OPEN |
| 027 | Landing CMS | Tidak 100% editable | OPEN |
| 028 | Mobile | Sign out menu terpotong | OPEN (verify) |
| 029 | Quick Action | Tidak sesuai role (invoice ke non-finance) | IN PROGRESS (role-gate quick actions) |
| 030 | Notif Security | Baca SMTP belum di-setting padahal sudah | OPEN (verify) |
| 031 | Finance | Depresiasi mengurangi revenue | OPEN (verify) |
| 032 | Sales Fee | Input manual, harus dropdown user/invoice | OPEN (verify) |
| 033 | Salary | Employee harus pilih dari list | OPEN (verify) |
| 034 | Salary | Slip gaji PDF belum ada | OPEN (verify) |
| 035 | Report | Excel tanpa rumus/format angka | OPEN (verify) |

Kredensial integrasi real dari user tersimpan di memory/test_credentials.md (JANGAN hardcode di kode; simpan di DB `integrations`).
