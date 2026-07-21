# AGENTS.md — Ryukomik Discord Bot

## Ringkasan
Bot Discord untuk Ryukomik Scanlation Group. Fitur utama:
1. **Recruitment Ticket System** — User apply jadi staff, buat tiket privat
2. **Staff Payment System** — Assign, claim, submit, review, bayar
3. **RAW Chapter Downloader** — Download RAW dari Asura Scans

## Struktur Project
```
RyukomikBot/
├── bot.py              ← Main entry, setup semua
├── config.py           ← IDs (guild, channel, role)
├── database.py         ← SQLite (assignments, payments)
├── panels/
│   ├── admin_panel.py  ← Admin Panel (di #・staff-mod)
│   ├── staff_panel.py  ← Staff Panel (di tiket staff)
│   └── claim_view.py   ← Claim button (di #・staff-tasks)
├── views/
│   ├── ticket_views.py ← Submit, Review, Revisi buttons
│   └── select_views.py ← Dropdown selects
├── modals/
│   ├── assign_modal.py ← Form assign tugas
│   ├── submit_modal.py ← Form submit GDrive
│   ├── revisi_modal.py ← Form revisi
│   └── rekap_modal.py  ← Form rekap gaji
├── helpers/
│   └── utils.py        ← is_admin, is_staff, calculate_rate
├── raw_downloader/
│   └── asura.py        ← Download RAW chapter
└── recruitment/
    └── ticket.py       ← Ticket system rekrutmen
```

## Channel & Role IDs
```
GUILD_ID = 1524448659951849666

Channels:
- #・staff-tasks   = 1529129826558939268  (task announcements)
- #・staff-mod     = 1524468717591859234  (admin panel + logs)
- #・staff-payrate = 1524467683054325870  (payrate info)
- Rekrut Category  = 1524467626665836615  (tiket rekrutmen)

Roles:
- Staff = 1524458627124166696
- Admin = 1524457168072343762
```

---

## ALUR SISTEM PENGGAJIAN STAFF

### Flow Utama
```
1. ADMIN ASSIGN
   Admin klik [📋 Assign Tugas] di #・staff-mod
   → Isi form: manga, chapter, role, rate
   → Task muncul di #・staff-tasks dengan tombol [✋ Claim]

2. STAFF CLAIM
   Staff klik [✋ Claim Tugas] di #・staff-tasks
   → Bot cek: ada role Staff? ✓
   → Status: open → claimed
   → Notif ke #・staff-mod
   → Task detail dikirim ke tiket staff

3. STAFF SUBMIT
   Staff klik [📤 Submit Hasil] di tiket
   → Isi link Google Drive
   → Status: claimed → submitted
   → Notif ke #・staff-mod

4. ADMIN REVIEW
   Admin klik [✅ Approve] atau [🔄 Revisi] di tiket
   → Approve: auto hitung gaji, status → approved
   → Revisi: staff perbaiki, submit ulang

5. ADMIN PAY
   Admin klik [💰 Rekap Gaji] di #・staff-mod
   → Pilih staff & bulan
   → Klik [✅ Confirm Bayar]
   → Status: approved → paid
```

### Status Flow
```
open → claimed → submitted → approved → paid
            ↑           │
            └── revision ←┘
```

---

## PANEL LAYOUT

### #・staff-mod (Admin Only)
```
🛠️ ADMIN PANEL
[📋 Assign Tugas]  [📝 Review]
[💰 Rekap Gaji]    [📊 Stats]
```

### #・staff-tasks (Public)
```
📋 {Manga} Ch {Chapter}
📌 Role | 💰 Rate | 📊 Status: 🔓 Available
[✋ Claim Tugas]
```

### 🔒・tiket-{staff} (Private)
```
👤 STAFF PANEL
[📋 Tugas Saya]  [📤 Submit Hasil]  [💰 Penghasilan]
```

---

## PAYRATE
```
TL (Translator): Rp 3.000 - 8.000 / chapter
TS (Typesetter): Rp 3.000 - 12.000 / chapter
TL+TS (Keduanya): Rp 5.000 - 15.000 / chapter

Multiplier:
- Series populer: +30%
- Chapter >20 halaman: +20%
- Deadline ketat: +10%
```

---

## COMMANDS
```
/panels admin    → Kirim Admin Panel ke #・staff-mod
/panels staff    → Kirim Staff Panel ke tiket (harus di tiket)
/update-payrate  → Update embed payrate
```

---

## DATABASE SCHEMA
```sql
assignments (
  id INTEGER PRIMARY KEY,
  manga TEXT,
  chapter TEXT,
  staff_id INTEGER DEFAULT NULL,  -- NULL = open (belum di-claim)
  role TEXT,                       -- TL / TS / TL+TS
  base_rate INTEGER DEFAULT 3000,
  final_rate INTEGER,
  status TEXT DEFAULT 'open',     -- open/claimed/submitted/revision/approved/paid
  gdrive_link TEXT,
  message_id INTEGER,             -- message ID di #・staff-tasks
  ticket_channel_id INTEGER,      -- channel ID tiket staff
  paid_period TEXT                -- "YYYY-MM"
)

payments (
  id INTEGER PRIMARY KEY,
  staff_id INTEGER,
  period TEXT,                    -- "YYYY-MM"
  total_amount INTEGER,
  chapter_count INTEGER,
  status TEXT DEFAULT 'pending'  -- pending/paid
)
```

---

## PERATURAN
1. **Jangan pernah share identitas user** (username, foto profil) ke partner
2. **CopyMessage, bukan ForwardMessage** untuk relay anonim
3. **Staff role = filter** → hanya user dengan role Staff yang bisa claim/submit
4. **All responses visible** → di tiket private, semua response kelihatan (bukan ephemeral)
5. **Persistent views** → semua button views harus registered di setup_hook

---

## DEPLOY
```bash
cd /home/ryukomik/RyukomikBot
cp .env.example .env  # isi DISCORD_TOKEN
pip install -r requirements.txt
python bot.py
```

Atau pakai PM2:
```bash
pm2 start bot.py --name ryukomik-bot
```

---

## NOTES
- Bot file: `/home/ryukomik/RyukomikBot/bot.py`
- Database: `/home/ryukomik/RyukomikBot/data/staff_pay.db`
- GitHub: https://github.com/bagusdanur/RyukomikBot
- Stack: Python 3, discord.py, SQLite (aiosqlite)
