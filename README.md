# Ryukomik Bot

Discord bot untuk Ryukomik Scanlation Group dengan fitur:
- 📋 Sistem tugas staff (assign, claim, submit, review)
- 💰 Sistem pembayaran staff
- 📩 Sistem rekrutmen tiket
- 📥 RAW chapter downloader (Asura Scans)

## Struktur Project

```
RyukomikBot/
├── bot.py                 # Main entry point
├── config.py              # Configuration
├── database.py            # Database setup & helpers
├── panels/
│   ├── admin_panel.py     # Admin panel view
│   ├── staff_panel.py     # Staff panel view
│   └── claim_view.py      # Claim assignment view
├── views/
│   ├── ticket_views.py    # Ticket submit/review views
│   └── select_views.py    # Dropdown selections
├── modals/
│   ├── assign_modal.py    # Assign task modal
│   ├── submit_modal.py    # Submit work modal
│   ├── revisi_modal.py    # Revision modal
│   └── rekap_modal.py     # Payment recap modal
├── helpers/
│   └── utils.py           # Utility functions
├── raw_downloader/
│   └── asura.py           # Asura Scans downloader
├── recruitment/
│   └── ticket.py          # Recruitment ticket system
├── data/                  # Database & downloads
├── .env.example           # Environment template
├── .gitignore
├── requirements.txt
└── README.md
```

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Setup Environment

```bash
cp .env.example .env
# Edit .env and add your DISCORD_TOKEN
```

### 3. Run Bot

```bash
python bot.py
```

## Commands

### Slash Commands

| Command | Description | Permission |
|---------|-------------|------------|
| `/panels` | Tampilkan panel admin/staff | Admin/Staff |
| `/update-payrate` | Update base rate | Admin |
| `/search-manga` | Cari manga | Everyone |
| `/download-raw` | Download chapter RAW | Staff |

### Prefix Commands

| Command | Description | Permission |
|---------|-------------|------------|
| `!panel` | Tampilkan panel | Admin/Staff |
| `!rekrut` | Kirim embed rekrutmen | Admin |
| `!close` | Tutup tiket | Admin/Ticket Owner |
| `!help-ryukomik` | Tampilkan help | Everyone |

## Sistem Tugas

### Flow Tugas

1. **Admin Assign** → Tugas dibuat dengan status `open`
2. **Staff Claim** → Tugas di-claim, status `claimed`
3. **Staff Submit** → Hasil di-submit, status `submitted`
4. **Admin Review** → Tugas di-approve atau di-revise
5. **Admin Rekap** → Tugas ditandai `approved`
6. **Admin Bayar** → Tugas ditandai `paid`

### Status

- 🔓 `open` - Tersedia untuk di-claim
- ⏳ `claimed` - Sedang dikerjakan
- 🟡 `submitted` - Menunggu review
- 🔴 `revision` - Perlu revisi
- ✅ `approved` - Disetujui
- 💰 `paid` - Sudah dibayar

## Rate System

| Role | Base Rate | Max Rate |
|------|-----------|----------|
| TL (Translator) | Rp 3.000 | Rp 15.000 |
| PR (Proofreader) | Rp 3.000 | Rp 12.000 |
| CL (Cleaner) | Rp 3.000 | Rp 8.000 |

**Bonus Popular Series (+30%):**
- Solo Leveling
- Nano Machine
- Martial Peak
- Tomb Raider King
- Leveling with the Gods
- Dan lainnya...

## Database

Bot menggunakan SQLite dengan 2 tabel:

### assignments
- id, manga, chapter, staff_id, role
- base_rate, final_rate, multiplier
- status, gdrive_link, admin_notes
- message_id, ticket_channel_id
- claimed_at, assigned_at, submitted_at, approved_at
- paid_period

### payments
- id, staff_id, period
- total_amount, chapter_count
- status, paid_at

## License

MIT License
