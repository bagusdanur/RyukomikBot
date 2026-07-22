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
