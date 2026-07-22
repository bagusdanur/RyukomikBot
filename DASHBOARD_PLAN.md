# Rencana Ryukomik Staff Dashboard

## 1. Tujuan

Membuat dashboard web yang mempermudah administrator dan staff mengelola tugas, deadline, hasil kerja, RAW, serta pembayaran tanpa harus mengingat banyak command Discord.

Dashboard tidak menggantikan bot. Bot dan dashboard memakai backend serta database yang sama agar status selalu konsisten.

## 2. Biaya dan Teknologi

Komponen inti dapat digunakan gratis dan bersifat open-source:

| Komponen | Pilihan | Biaya software |
|---|---|---:|
| Frontend | Next.js + TypeScript | Gratis |
| Tampilan | Tailwind CSS + shadcn/ui | Gratis |
| Backend | FastAPI (Python) | Gratis |
| Database | PostgreSQL | Gratis |
| Login | Discord OAuth2 | Gratis |
| Grafik | Recharts | Gratis |
| Reverse proxy | Nginx | Gratis |
| Process manager | PM2 atau systemd | Gratis |
| Hosting | VPS Ryukomik yang sudah ada | Tidak ada biaya baru jika kapasitas cukup |

Biaya tambahan hanya diperlukan jika:

- membeli domain baru;
- menaikkan spesifikasi VPS;
- menggunakan storage, email, monitoring, atau backup berbayar;
- trafik dan data sudah melebihi kapasitas VPS.

Subdomain seperti `staff.ryukomik.web.id` dapat memakai domain yang sudah ada.

## 3. Arsitektur

```text
Browser
   |
   v
Nginx + HTTPS
   |
   +--> Next.js Dashboard
   |         |
   |         v
   +--> FastAPI Internal API
             |
             v
         PostgreSQL
          ^       ^
          |       |
     Discord Bot  Dashboard
```

Aturan penting:

- Bot dan dashboard tidak menulis langsung ke SQLite dari dua proses berbeda.
- Semua operasi tugas/gaji melewati service/API yang sama.
- Bot token hanya berada di server dan tidak pernah dikirim ke browser.
- Semua perubahan penting disimpan di audit log.

## 4. Hak Akses

### Administrator

- Melihat seluruh tugas dan staff.
- Membuat, mengedit, assign, dan membatalkan tugas.
- Mengubah payrate dan bayaran khusus tugas.
- Review, revisi, approve, dan menandai pembayaran.
- Melihat deadline serta laporan kendala.
- Export rekap pembayaran.
- Melihat audit log.

### Staff

- Hanya melihat tugas dan pendapatan miliknya.
- Membuka detail tugas dan deadline.
- Submit atau submit ulang hasil.
- Download RAW berdasarkan proyek aktif.
- Mengirim kendala atau permintaan perpanjangan.
- Melihat status review dan pembayaran.

### Pengunjung

- Tidak memiliki akses dashboard.
- Harus login dengan Discord dan menjadi member server Ryukomik.

## 5. Login dan Keamanan

1. Pengguna menekan **Masuk dengan Discord**.
2. Discord OAuth2 mengembalikan identitas pengguna.
3. Backend memeriksa membership guild Ryukomik.
4. Backend membaca role Administrator atau Staff.
5. Backend membuat session cookie `HttpOnly`, `Secure`, dan `SameSite=Lax`.
6. Akses ditolak jika member keluar dari server atau kehilangan role.

Keamanan minimum:

- HTTPS wajib.
- CSRF protection untuk operasi perubahan data.
- Rate limiting untuk login dan API sensitif.
- Validasi role dilakukan di backend, bukan hanya menyembunyikan tombol frontend.
- Secret OAuth, bot token, dan database URL disimpan dalam environment VPS.
- Audit log tidak dapat diedit dari dashboard biasa.
- Backup PostgreSQL otomatis setiap hari.

## 6. Halaman Administrator

### 6.1 Overview

- Jumlah tugas open, dikerjakan, review, revisi, approved, dan paid.
- Total pengeluaran bulan berjalan.
- Tugas melewati atau mendekati deadline.
- Hasil yang menunggu review.
- Kendala dan permintaan perpanjangan terbaru.

### 6.2 Tugas

- Tampilan tabel dan Kanban.
- Filter manga, staff, role, status, dan bulan.
- Buat tugas dengan wizard:
  - judul manga;
  - chapter;
  - TL/TS/TL+TS;
  - open claim atau assign langsung;
  - staff tujuan;
  - jumlah halaman;
  - deadline;
  - rate default atau bayaran manual;
  - preview sebelum diterbitkan.
- Edit tugas yang belum dibayar.
- Buka tiket atau pesan tugas di Discord.

### 6.3 Review

- Daftar hasil berstatus `submitted`.
- Link Google Drive dapat dibuka langsung.
- Tombol approve atau revisi.
- Catatan revisi wajib diisi.
- Tindakan dashboard menghasilkan notifikasi Discord.

### 6.4 Staff

- Daftar member ber-role Staff.
- Tugas aktif dan riwayat tugas.
- Total approved dan paid.
- Persentase selesai tepat waktu.
- Tombol membuka tiket Discord.

### 6.5 Gaji

- Atur rate default TL, TS, dan TL+TS.
- Atur bayaran manual per tugas.
- Filter staff dan periode.
- Preview tugas approved yang belum dibayar.
- Pilih beberapa tugas dan konfirmasi pembayaran.
- Export CSV dan Excel.
- Riwayat pembayaran tidak boleh dihapus.

### 6.6 Deadline dan Kendala

- Urutan deadline paling dekat.
- Penanda terlambat, kurang dari 24 jam, dan aman.
- Laporan kendala staff.
- Permintaan perpanjangan.
- Admin dapat menyetujui deadline baru dengan catatan.

### 6.7 RAW

- Pilih assignment aktif, bukan mengetik judul.
- Cari otomatis Asura dan Doujiva.
- Pilih chapter.
- Tampilkan progres.
- Hasil berupa link Filebin.
- Riwayat hanya menyimpan metadata/link, bukan file gambar lokal.

### 6.8 Audit Log

Mencatat:

- siapa melakukan tindakan;
- waktu tindakan;
- data sebelum dan sesudah;
- tugas/staff terkait;
- IP dan user agent untuk operasi sensitif.

Tindakan yang wajib dicatat: perubahan rate, perubahan nominal tugas, approve, revisi, pembayaran, pembatalan, dan perubahan role dashboard.

## 7. Halaman Staff

### 7.1 Beranda

- Satu card **Tindakan Berikutnya**.
- Tugas paling dekat deadline.
- Tugas revisi ditempatkan paling atas.
- Ringkasan penghasilan bulan berjalan.

### 7.2 Tugas Saya

- Tugas aktif dan selesai.
- Detail role, bayaran, deadline, serta status dalam Bahasa Indonesia.
- Submit link Google Drive.
- Submit ulang tugas revisi.

### 7.3 RAW Proyek

- Pilih tugas aktif.
- Judul diambil otomatis dari assignment.
- Pilih hasil komik dan chapter.
- Link Filebin ditampilkan setelah selesai.

### 7.4 Penghasilan

- Nominal menunggu review.
- Nominal approved.
- Nominal sudah dibayar.
- Riwayat pembayaran per periode.

### 7.5 Bantuan

- Pilih tugas aktif.
- Laporkan kendala.
- Minta perpanjangan.
- Lihat status tanggapan admin.

## 8. Skema Database Awal

Tabel utama:

```text
users
guild_members
assignments
assignment_events
payrates
payments
payment_items
support_requests
raw_jobs
audit_logs
web_sessions
```

Perubahan penting dari SQLite saat ini:

- `payments` dipisahkan dari item tugas yang dibayar.
- Semua perubahan status disimpan di `assignment_events`.
- Permintaan bantuan memiliki status `open/resolved/rejected`.
- `audit_logs` menyimpan perubahan administratif.
- Discord snowflake disimpan sebagai `BIGINT` atau string aman.

## 9. Integrasi Bot

- Bot tetap menangani tombol, tiket, notifikasi, dan slash command.
- FastAPI menyediakan service yang digunakan bot dan dashboard.
- Perubahan dashboard mengirim notifikasi melalui bot.
- Interaksi bot memperbarui data yang langsung terlihat di dashboard.
- Setiap operasi menggunakan idempotency key untuk mencegah pembayaran atau assignment ganda.

## 10. Tahapan Implementasi

### Tahap 0 — Persiapan dan Backup

- Audit SQLite dan schema aktif.
- Backup database serta `.env` VPS.
- Buat environment staging.
- Tentukan subdomain dashboard.

### Tahap 1 — Dashboard Read-only

- Scaffold Next.js dan FastAPI.
- Login Discord.
- Pemeriksaan guild dan role.
- Overview, daftar tugas, staff, dan gaji read-only.

Kriteria selesai:

- Admin dapat login dan melihat seluruh data.
- Staff hanya melihat data miliknya.
- User tanpa role ditolak.
- Belum ada operasi yang mengubah data produksi.

### Tahap 2 — PostgreSQL dan Migrasi

- Buat schema PostgreSQL.
- Migrasikan salinan SQLite ke staging.
- Bandingkan jumlah assignment, status, dan total pembayaran.
- Uji bot menggunakan PostgreSQL di staging.
- Jadwalkan cutover dengan backup dan rollback plan.

Kriteria selesai:

- Tidak ada data hilang.
- Total nominal sebelum dan sesudah migrasi sama.
- Bot lolos seluruh alur tugas di staging.

### Tahap 3 — Pengelolaan Tugas

- Wizard assignment.
- Direct assign/open claim.
- Edit deadline dan bayaran.
- Review, revisi, dan approve.
- Sinkronisasi notifikasi Discord.

### Tahap 4 — Gaji dan Pembayaran

- Pengaturan payrate.
- Rekap periode.
- Bulk confirm pembayaran.
- Export CSV/Excel.
- Audit log penuh.

### Tahap 5 — Portal Staff

- Tugas aktif.
- Submit/revisi.
- Penghasilan.
- Bantuan tugas.
- RAW berdasarkan assignment.

### Tahap 6 — Operasional

- Backup otomatis.
- Monitoring API/database.
- Error tracking.
- Rate limiting.
- Dokumentasi admin dan staff.

## 11. Pengujian Wajib

- Login Discord valid, role hilang, member keluar guild, dan session kedaluwarsa.
- Staff tidak dapat membaca assignment atau gaji staff lain.
- Staff tidak dapat memanggil endpoint admin secara manual.
- Dua admin tidak dapat membayar assignment yang sama dua kali.
- Bot dan dashboard memperbarui assignment bersamaan tanpa kehilangan data.
- Perubahan rate tidak mengubah assignment lama.
- Semua nominal pembayaran cocok dengan item approved.
- Audit log tercatat untuk semua tindakan sensitif.
- Notifikasi Discord gagal tidak membatalkan transaksi database, tetapi masuk retry queue.
- Backup dapat direstore di staging.

## 12. Deployment VPS

Rencana service:

```text
ryukomik-bot        -> Python bot
ryukomik-api        -> FastAPI/Uvicorn
ryukomik-dashboard  -> Next.js
postgresql          -> database
nginx               -> HTTPS dan reverse proxy
```

Nginx hanya mengekspos dashboard/API yang diperlukan. PostgreSQL tidak dibuka ke internet.

## 13. MVP yang Disarankan

Versi pertama cukup berisi:

1. Login Discord dan validasi role.
2. Overview.
3. Daftar/filter tugas.
4. Daftar staff.
5. Pengaturan payrate.
6. Rekap gaji bulanan.
7. Konfirmasi pembayaran.
8. Deadline dan kendala.
9. Audit log.

RAW dan submit staff dari web dikerjakan setelah MVP stabil karena fitur tersebut melibatkan pekerjaan background, upload eksternal, dan sinkronisasi Discord yang lebih kompleks.

## 14. Keputusan Sebelum Implementasi

- Subdomain yang akan digunakan.
- Dashboard diletakkan dalam repository ini atau repository terpisah.
- Waktu migrasi SQLite ke PostgreSQL.
- Lama penyimpanan audit log dan backup.
- Apakah staff portal langsung masuk MVP atau fase berikutnya.

## 15. Definisi Selesai

Dashboard dianggap siap produksi jika:

- role dan privasi sudah diuji;
- data SQLite berhasil dimigrasikan dan direkonsiliasi;
- bot dan dashboard menggunakan sumber data yang sama;
- pembayaran memiliki proteksi duplikasi dan audit log;
- backup serta rollback sudah diuji;
- tampilan nyaman digunakan dari HP;
- tidak ada token atau secret di frontend/repository;
- seluruh layanan stabil setelah restart VPS.
