module.exports = {
  apps: [{
    name: 'ryukomik-dashboard-api',
    cwd: '/home/ryukomik/RyukomikBot',
    script: '/home/ryukomik/hermes-agent/venv/bin/uvicorn',
    args: 'dashboard.backend.app:app --host 127.0.0.1 --port 8000 --proxy-headers',
    interpreter: 'none',
    autorestart: true,
    max_memory_restart: '300M',
  }],
}
