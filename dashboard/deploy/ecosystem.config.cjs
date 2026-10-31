const { readFileSync } = require('node:fs');
const translatorToken = readFileSync('/home/ryukomik/ryukomik-auto-comic-translator/.api-token', 'utf8').trim();
const rawApiKey = readFileSync('/home/ryukomik/RyukomikBot/dashboard/.raw-api-key', 'utf8').trim();

module.exports = {
  apps: [{
    name: 'ryukomik-dashboard-api',
    cwd: '/home/ryukomik/RyukomikBot',
    script: '/home/ryukomik/RyukomikBot/dashboard/.venv/bin/uvicorn',
    args: 'dashboard.backend.app:app --host 127.0.0.1 --port 8000 --proxy-headers',
    interpreter: 'none',
    autorestart: true,
    max_memory_restart: '300M',
    env: {
      TRANSLATOR_API_URL: 'http://127.0.0.1:3210',
      TRANSLATOR_API_TOKEN: translatorToken,
      RAW_API_KEY: rawApiKey,
    },
  }],
}
