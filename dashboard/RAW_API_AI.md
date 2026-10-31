# RAW API — Panduan untuk AI Agent di VPS Lain

Dokumen ini untuk **agent/AI di server lain** yang perlu mengunduh RAW komik
tanpa mengakses server Ryukomik lewat SSH. Semua akses lewat HTTP + API key.

---

## 1. Fakta dasar

| Item | Nilai |
|---|---|
| Base URL | `https://staff.ryukomik.web.id` |
| Prefix API | `/api/v1/raw` |
| Auth | header `X-API-Key: <RAW_API_KEY>` (alternatif: `Authorization: Bearer <key>`) |
| Format hasil | ZIP (isi: `001.webp`, `002.webp`, … atau `001.png`, … sesuai source) |
| Bahasa | `id` untuk pesan error, `en` untuk nama field |

`RAW_API_KEY` **tidak boleh** ditulis di kode, repo, log, atau pesan chat.
Simpan sebagai environment variable di VPS kamu:

```bash
echo 'export RAW_API_URL="https://staff.ryukomik.web.id"' >> ~/.bashrc
echo 'export RAW_API_KEY="<tempel-key-di-sini>"' >> ~/.bashrc
source ~/.bashrc
```

Tanpa key: `401 {"detail":"API key salah."}`. Kalau server belum menyetel key:
`503 {"detail":"RAW_API_KEY belum diset di server."}`.

---

## 2. Tiga cara pakai (pilih satu)

### A. Satu langkah, hanya judul — paling gampang

```bash
curl -sS -H "X-API-Key: $RAW_API_KEY" -o raw.zip \
  "$RAW_API_URL/api/v1/raw/get?title=Koshaku%20no%20Tsukibito%20Ossan&chapter=1"
```

Parameter:

- `title` — judul (boleh sebagian; dicocokkan fuzzy)
- `chapter` — nomor chapter, mis. `1`. **Tanpa ini diambil chapter terbaru.**
- `source` — `mangadex` (default), `asura`, `thunder`, `evascan`, `mist`, `lua`,
  `vortex`, `qimanga`, `demon`, `kagane`, `mgread`
- `mode` — **`original` (default, file sumber apa adanya)**, atau `joined` (gabungan WebP lossless, lebih lambat)
- `wait_seconds` — default 600, maksimum 1800

Balasan sukses: **HTTP 200 + body ZIP**. Tidak ada JSON.
Kalau gagal: JSON `{"detail": "..."}` dengan kode 4xx/5xx.

> Endpoint ini menahan koneksi sampai paket siap. Nginx server memakai
> `proxy_read_timeout 300s`, jadi chapter yang butuh >5 menit bisa terputus.
> Untuk itu pakai cara B.

### B. Bertahap (disarankan untuk otomasi)

```bash
# 1) buat paket
curl -sS -H "X-API-Key: $RAW_API_KEY" -H 'Content-Type: application/json' \
  -d '{"title":"Koshaku no Tsukibito Ossan","chapter":"1"}' \
  "$RAW_API_URL/api/v1/raw/fetch"
```

Contoh balasan:

```json
{
  "token": "0534f576186956a1cacefe46631da702",
  "state": "QUEUED",
  "source": "mangadex",
  "manga_id": "9a0ebc7d-a90a-423c-8b30-4b7fae988b42",
  "chapter_id": "b1f0…",
  "chapter": "Chapter 1 [es-la]",
  "status_url": "/api/v1/raw/status/0534f576…",
  "download_url": "/api/v1/raw/download/0534f576…?mode=original"
}
```

```bash
# 2) polling tiap 3–5 detik sampai state=READY
curl -sS -H "X-API-Key: $RAW_API_KEY" "$RAW_API_URL/api/v1/raw/status/<TOKEN>"
```

Urutan state: `QUEUED` → `DOWNLOADING` → `JOINING` → `READY` (atau `FAILED`).

Saat `READY`, balasan berisi ringkasan dan URL unduh:

```json
{
  "token": "0534f576…",
  "state": "READY",
  "original": {"count": 42, "min_height": 354, "max_height": 2150, "bytes": 51436852},
  "download": {"original": "/api/v1/raw/download/0534f576…?mode=original"}
}
```

```bash
# 3) unduh
curl -sS -H "X-API-Key: $RAW_API_KEY" -o raw.zip \
  "$RAW_API_URL/api/v1/raw/download/<TOKEN>?mode=original"
```

### C. Cari dulu, baru pilih (kalau judul ambigu)

```bash
curl -sS -H "X-API-Key: $RAW_API_KEY" \
  "$RAW_API_URL/api/v1/raw/search?q=Koshaku%20no%20Tsukibito&source=mangadex"
# -> {"query":"...","results":[{"source":"mangadex","id":"9a0ebc7d-...","title":"Koshaku no Tsukibito Ossan, Yonaoshi Tabi de Harem to Naru"}]}

curl -sS -H "X-API-Key: $RAW_API_KEY" \
  "$RAW_API_URL/api/v1/raw/chapters?source=mangadex&manga_id=9a0ebc7d-a90a-423c-8b30-4b7fae988b42"
# -> {"count":N,"chapters":[{"id":"...","title":"Chapter 1 [es-la]","language":"es-la"},...]}
```

Lalu `POST /fetch` dengan `{"manga_id": "...", "chapter_id": "..."}`.

---

## 3. Contoh kode Python (agent-friendly)

```python
import os, time, httpx

BASE = os.environ["RAW_API_URL"].rstrip("/")
HEADERS = {"X-API-Key": os.environ["RAW_API_KEY"]}

def download_raw(title: str, chapter: str, mode: str = "original", out: str = "raw.zip",
                 timeout: int = 900) -> str:
    with httpx.Client(base_url=BASE, headers=HEADERS, timeout=httpx.Timeout(60, read=600)) as c:
        r = c.post("/api/v1/raw/fetch", json={"title": title, "chapter": chapter, "mode": mode})
        r.raise_for_status()
        token = r.json()["token"]
        deadline = time.time() + timeout
        while time.time() < deadline:
            st = c.get(f"/api/v1/raw/status/{token}").json()
            if st["state"] == "READY":
                url = st["download"].get(mode) or st["download"]["original"]
                data = c.get(url).content
                with open(out, "wb") as f:
                    f.write(data)
                return out
            if st["state"] == "FAILED":
                raise RuntimeError(st.get("error"))
            time.sleep(4)
    raise TimeoutError("RAW belum siap; token masih valid 30 menit")

if __name__ == "__main__":
    print(download_raw("Koshaku no Tsukibito Ossan", "1"))
```

Aturan untuk agent:

1. **Jangan retry** `401`/`404` — key salah atau judul/chapter tidak ada.
2. `429` = sudah 2 paket berjalan; tunggu minimal 30 detik lalu coba lagi.
3. `504` di `/get` = pakai alur `/fetch` + `/status`.
4. Token berlaku **30 menit**; simpan token, jangan buat paket baru untuk chapter yang sama.
5. Jangan paralel lebih dari 2 paket.
6. Jangan mencetak API key ke log/stdout.

---

## 4. Batas & angka nyata

| Hal | Nilai |
|---|---|
| Maks gambar per chapter | 300 |
| Paket bersamaan | 2 (lebih → `429`) |
| Umur paket | 30 menit |
| Batas tinggi gabungan | `min(15000, 24_000_000 ÷ lebar_maksimum)` px (halaman spread bisa lebih lebar) |
| Ukuran contoh | 42 halaman → original 51,4 MB (joined 55,5 MB bila diminta) |
| Waktu contoh | `original` ≈ **4 detik** (cache source) sampai ±1 menit; `joined` ≈ **3 menit** |

Arti `mode`:

- `original` — **default API**. File sumber, tanpa diubah, dikirim apa adanya
  (`001.jpg`, `002.png`, …). Paling cepat karena tidak ada penggabungan.
- `joined` — opsional. Halaman digabung jadi beberapa strip panjang (lossless,
  tanpa resize). Harus diminta eksplisit dan butuh waktu/RAM lebih besar.

`joined` bisa lebih kecil jumlah halamannya daripada `original` (contoh 42 → 18), dan potongannya mengikuti sela panel aman, jadi tinggi tiap strip bisa < batas (contoh batas 6749 px, hasil 2768–6622 px).

---

## 5. Kode status

| Kode | Arti | Tindakan |
|---|---|---|
| 200 | sukses (ZIP) | simpan file |
| 400 | parameter kurang/salah | perbaiki request |
| 401 | API key salah/kosong | cek environment, jangan retry |
| 404 | judul/chapter tidak ditemukan | cek `/search`, coba `source` lain |
| 409 | paket belum siap | tunggu, ulangi `/status` |
| 413 | paket terlalu besar | pakai `original` |
| 429 | 2 paket sedang berjalan | tunggu 30 s |
| 502 | source menolak / gagal unduh | coba lagi / ganti source |
| 503 | server belum punya key | hubungi admin Ryukomik |
| 504 | waktu tunggu habis | pakai alur bertahap |

---

## 6. Cek cepat setelah setup

```bash
curl -sS -H "X-API-Key: $RAW_API_KEY" "$RAW_API_URL/api/v1/raw/sources"
# {"sources":["mangadex","asura","thunder",...],"default":"mangadex"}
```

Kalau ini balas 200, key dan jaringan sudah benar. Lanjut uji satu chapter kecil
dengan `mode=original` sebelum memakai `joined`.
