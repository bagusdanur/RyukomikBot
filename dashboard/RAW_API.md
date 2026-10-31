# RAW API (dipakai dari VPS lain)

Server: `https://staff.ryukomik.web.id`
Base path: `/api/v1/raw`
Auth: header `X-API-Key: <RAW_API_KEY>` (atau `Authorization: Bearer <key>`)

Kunci disimpan di server: `/home/ryukomik/RyukomikBot/dashboard/.raw-api-key`
(ikut dimuat PM2 lewat `deploy/ecosystem.config.cjs` sebagai `RAW_API_KEY`).
Tanpa kunci → `401`. Kalau `RAW_API_KEY` belum diset di proses → `503`.

## Satu langkah (paling simpel)

```bash
curl -H "X-API-Key: $RAW_API_KEY" \
  -o raw.zip \
  "https://staff.ryukomik.web.id/api/v1/raw/get?title=Koshaku%20no%20Tsukibito%20Ossan&chapter=1"
```

- `title` = judul (boleh sebagian, dicocokkan fuzzy; default source `mangadex`)
- `chapter` = angka chapter (opsional; tanpa ini diambil chapter terbaru)
- `source` = `mangadex|asura|thunder|evascan|mist|lua|vortex|qimanga|demon|kagane|mgread` (opsional)
- `mode` = `original` (default, file asli) atau `joined` (gabungan WebP lossless)
- `wait_seconds` = default 600, maksimum 1800

Catatan: endpoint ini menahan koneksi sampai paket siap. Nginx memakai
`proxy_read_timeout 300s`, jadi untuk chapter sangat besar pakai alur bertahap.

## Alur bertahap (aman untuk chapter besar)

```bash
# 1. buat paket
TOKEN=$(curl -s -H "X-API-Key: $RAW_API_KEY" -H 'Content-Type: application/json' \
  -d '{"title":"Koshaku no Tsukibito Ossan","chapter":"1"}' \
  https://staff.ryukomik.web.id/api/v1/raw/fetch | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')

# 2. cek status (QUEUED -> DOWNLOADING -> JOINING -> READY)
curl -s -H "X-API-Key: $RAW_API_KEY" https://staff.ryukomik.web.id/api/v1/raw/status/$TOKEN

# 3. unduh
curl -H "X-API-Key: $RAW_API_KEY" -o raw.zip \
  "https://staff.ryukomik.web.id/api/v1/raw/download/$TOKEN?mode=original"
```

## Endpoint lain

| Method | Path | Fungsi |
|---|---|---|
| GET | `/sources` | daftar source + default |
| GET | `/search?q=&source=` | cari judul, balikan `{source,id,title}` |
| GET | `/chapters?source=&manga_id=` | daftar chapter (id + label + bahasa) |
| POST | `/fetch` | buat paket (`title` atau `manga_id`, `chapter`, `source`, `mode`) |
| GET | `/status/{token}` | progres + `download` URL per mode |
| GET | `/download/{token}?mode=` | kirim ZIP |

## Klien siap pakai

`dashboard/deploy/raw_api_client.py` (butuh `httpx`):

```bash
export RAW_API_URL=https://staff.ryukomik.web.id
export RAW_API_KEY=<isi file .raw-api-key>
python raw_api_client.py "Koshaku no Tsukibito Ossan" --chapter 1 --out raw.zip
```

## Batas & perilaku

- Paket disimpan **30 menit**, lalu dibersihkan otomatis.
- Maksimal **2 paket** disiapkan bersamaan (lebih dari itu → `429`).
- Maksimal **300 gambar** per chapter.
- Gabungan (`joined`) memakai batas `min(15000, 24_000_000 ÷ lebar)` px per halaman.
- Proses join berjalan di proses terpisah (CPU/RAM berat tidak mematikan API).
- Source tanpa judul yang cocok → `404` dengan daftar source yang dicoba; judul yang
  ditemukan tetapi chapter-nya tidak ada → juga `404`.
