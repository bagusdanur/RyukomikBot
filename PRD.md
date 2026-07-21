# PRD — Ryukomik Discord Bot

## 1. Ringkasan
Bot Discord untuk mengelola staff Ryukomik Scanlation Group. Fitur utama: sistem penggajian berbasis claim, tiket rekrutmen, dan downloader RAW chapter.

## 2. Fitur

### 2.1 Staff Payment System
**Tujuan:** Mengelola tugas dan pembayaran staff secara transparan.

**Flow:**
1. Admin assign tugas → post di #・staff-tasks
2. Staff claim tugas → notif ke #・staff-mod + kirim ke tiket
3. Staff submit hasil (link GDrive) → di tiket
4. Admin review → approve/revisi → di tiket
5. Admin rekap gaji → confirm bayar

**Rules:**
- Hanya user dengan role Staff yang bisa claim
- Hanya admin yang bisa assign, approve, dan bayar
- Semua response visible di channel (bukan ephemeral)
- Task announcements di #・staff-tasks (public)
- Review/submit di tiket staff (private)

### 2.2 Recruitment Ticket System
**Tujuan:** Proses rekrutmen staff baru secara privat.

**Flow:**
1. User klik tombol "Buat Tiket" di #・staff-rekrutmen
2. Bot buat channel privat: 🔒・tiket-{username}
3. User pilih posisi (TL/TS/TL+TS)
4. Bot kirim bahan tes
5. User submit hasil tes
6. Admin review → approve → kasih role Staff

### 2.3 RAW Chapter Downloader
**Tujuan:** Download RAW chapter dari Asura Scans untuk kebutuhan scanlation.

**Commands:**
- `/raw-update` — Cek update RAW terbaru
- `/raw-search` — Cari komik
- `/raw-chapters` — Lihat daftar chapter
- `/raw-download` — Download chapter
- `/raw-download-batch` — Batch download

---

## 3. Database

### assignments
| Kolom | Tipe | Default | Keterangan |
|-------|------|---------|------------|
| id | INTEGER | AUTO | Primary key |
| manga | TEXT | - | Judul manga |
| chapter | TEXT | - | Nomor chapter |
| staff_id | INTEGER | NULL | NULL = open (belum di-claim) |
| role | TEXT | - | TL / TS / TL+TS |
| base_rate | INTEGER | 3000 | Rate dasar |
| final_rate | INTEGER | - | Rate setelah multiplier |
| status | TEXT | 'open' | open/claimed/submitted/revision/approved/paid |
| gdrive_link | TEXT | NULL | Link Google Drive hasil kerja |
| message_id | INTEGER | NULL | Message ID di #・staff-tasks |
| ticket_channel_id | INTEGER | NULL | Channel ID tiket staff |
| paid_period | TEXT | NULL | Periode pembayaran (YYYY-MM) |

### payments
| Kolom | Tipe | Default | Keterangan |
|-------|------|---------|------------|
| id | INTEGER | AUTO | Primary key |
| staff_id | INTEGER | - | ID staff |
| period | TEXT | - | Periode (YYYY-MM) |
| total_amount | INTEGER | 0 | Total gaji |
| chapter_count | INTEGER | 0 | Jumlah chapter |
| status | TEXT | 'pending' | pending/paid |

---

## 4. Panel Layout

### Admin Panel (#・staff-mod only)
```
📋 Assign Tugas → Modal: manga, chapter, role, rate_override
📝 Review → Dropdown → Approve/Revisi
💰 Rekap Gaji → Modal: staff_id, period
📊 Stats → Embed statistik
```

### Staff Panel (tiket staff only)
```
📋 Tugas Saya → Embed daftar tugas aktif
📤 Submit Hasil → Dropdown → Modal: gdrive_link
💰 Penghasilan → Embed penghasilan bulanan
```

### Task Announcement (#・staff-tasks)
```
📋 {Manga} Ch {Chapter}
📌 Role | 💰 Rate | 📊 Status
[✋ Claim Tugas]
```

---

## 5. Payrate

| Role | Rate/Chapter |
|------|-------------|
| TL (Translator) | Rp 3.000 - 8.000 |
| TS (Typesetter) | Rp 3.000 - 12.000 |
| TL+TS | Rp 5.000 - 15.000 |

**Multiplier:**
- Series populer: +30%
- Chapter >20 halaman: +20%
- Deadline ketat: +10%

---

## 6. Permission

| Action | Siapa |
|--------|-------|
| Assign tugas | Admin |
| Claim tugas | Staff |
| Submit hasil | Staff (yang claim) |
| Approve/Revisi | Admin |
| Rekap gaji | Admin |
| Confirm bayar | Admin |
| Lihat stats | Admin |
| Lihat tugas | Staff |
| Lihat penghasilan | Staff |

---

## 7. Deploy

```bash
# Clone
git clone https://github.com/bagusdanur/RyukomikBot.git
cd RyukomikBot

# Setup
cp .env.example .env
# Edit .env → isi DISCORD_TOKEN
pip install -r requirements.txt

# Run
python bot.py

# Atau PM2
pm2 start bot.py --name ryukomik-bot
```

---

## 8. Tech Stack
- Python 3.11+
- discord.py 2.x
- SQLite (aiosqlite)
- Persistent Views (button/select)
- Modals (form input)
