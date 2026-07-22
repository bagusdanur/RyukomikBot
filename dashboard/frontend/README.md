# Dashboard Frontend

Vue 3 + Vite + PrimeVue dashboard untuk Ryukomik.

```bash
npm install
npm run dev
npm run build
```

Development server mem-proxy `/api`, `/auth`, dan `/health` ke FastAPI pada `127.0.0.1:8000`. Production build berada di `dist/` dan dapat disajikan langsung oleh Nginx.
