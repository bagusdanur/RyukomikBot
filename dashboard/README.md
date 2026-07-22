# Ryukomik Staff Dashboard

Dashboard ringan dengan Vue 3 + Vite + PrimeVue dan backend FastAPI.

## Struktur

```text
dashboard/
├── frontend/  # SPA statis, build ke dist/
└── backend/   # OAuth Discord dan API database
```

## Development

Terminal backend dari root repository:

```bash
pip install -r dashboard/backend/requirements.txt
DASHBOARD_DEV_BYPASS=true uvicorn dashboard.backend.app:app --reload --port 8000
```

Terminal frontend:

```bash
cd dashboard/frontend
npm install
npm run dev
```

Buka `http://127.0.0.1:5173`.

`DASHBOARD_DEV_BYPASS` hanya untuk pengembangan lokal. Production wajib memakai Discord OAuth2.

## Production

1. Isi environment OAuth dan session secret pada VPS.
2. Jalankan FastAPI hanya di `127.0.0.1:8000`.
3. Jalankan `npm run build`.
4. Sajikan `dashboard/frontend/dist` melalui Nginx.
5. Proxy `/api`, `/auth`, dan `/health` ke FastAPI.

Database production masih memakai SQLite WAL pada MVP agar bot tetap kompatibel. Migrasi PostgreSQL dilakukan setelah dashboard read-only dan OAuth lolos staging.
