# Dashboard Backend

FastAPI API untuk dashboard Ryukomik. Jalankan dari root repository agar modul bot dapat diimpor.

Environment yang diperlukan:

```text
DISCORD_TOKEN=token bot
DISCORD_CLIENT_ID=application id Discord
DISCORD_CLIENT_SECRET=OAuth client secret
DASHBOARD_SESSION_SECRET=random minimal 32 karakter
DASHBOARD_ORIGIN=https://staff.ryukomik.web.id
DASHBOARD_API_ORIGIN=https://staff.ryukomik.web.id
```

Untuk development lokal saja dapat memakai `DASHBOARD_DEV_BYPASS=true`. Jangan aktifkan bypass di production.

```bash
pip install -r dashboard/backend/requirements.txt
uvicorn dashboard.backend.app:app --host 127.0.0.1 --port 8000
```

## RAW gabungan (Gabungan WebP) — catatan 502

Gejala: pilih **Gabungan WebP** lalu muncul `502`; log nginx menunjukkan
`connect() failed (111) ... /api/tools/translator/raw/prepare`, dan PM2
mencatat `ryukomik-dashboard-api` restart berkali-kali.

Penyebab: proses join dulu berjalan di dalam uvicorn dan `raw_join.prepare_inputs`
memakai `np.concatenate()` per halaman, sehingga kanvas 15k baris disalin 2–3x
plus encoder WebP lossless. Puncak RSS melewati `max_memory_restart` PM2
(300 MB) → proses dimatikan → nginx 502.

Perbaikan:

- `raw_join.prepare_inputs` memakai **satu buffer RGB yang dialokasikan sekali**
  dan diisi baris per baris (tanpa concatenate).
- `backend/join_worker.py` menjalankan join di **proses terpisah** dengan
  `RLIMIT_AS` 1,6 GB dan timeout 1800 s; `raw_exports.join_package` memanggilnya
  lewat `python -m backend.join_worker`. Kalau join gagal, paket RAW berstatus
  `FAILED` dengan pesan yang bisa dibaca, dan API tetap hidup (Original tetap
  bisa diunduh).

Batas tinggi gabungan = `min(15000, 24_000_000 // lebar_halaman)`. Untuk RAW
selebar 3556 px batasnya ~6749 px; RAW 800 px bisa sampai 15.000 px.
