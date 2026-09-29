"""Bukti kausal: guard-lah yang menghentikan notifikasi, bukan kebetulan.

Dijalankan dengan jaringan diblokir, jadi tidak ada pesan asli yang terkirim
walau guard-nya sengaja dimatikan.
"""
import asyncio
import os
import socket
import sys

sys.path.insert(0, "/home/ryukomik/RyukomikBot")

BLOCKED = []


def _no_conn(*a, **k):
    BLOCKED.append(a[:1])
    raise OSError("jaringan diblokir")


socket.create_connection = _no_conn
_real_socket = socket.socket


class _BlockedSocket(_real_socket):
    def connect(self, *a, **k):
        BLOCKED.append(a[:1])
        raise OSError("jaringan diblokir")


socket.socket = _BlockedSocket

# Simulasikan kondisi suite berjalan: hanya penanda mode-uji yang disetel,
# persis seperti tests/test_dashboard_api.py sekarang.
os.environ["DASHBOARD_DEV_BYPASS"] = "true"
os.environ["DASHBOARD_NO_DISCORD"] = "true"

from dashboard.backend import helpers
from dashboard.backend.routers import payrate
from config import GUILD_ID


async def main():
    # --- KONDISI SEKARANG (guard aktif) ---
    n_before = len(BLOCKED)
    sent = await payrate.broadcast_payrate_to_staff("TL", 4000, 8000)
    now_attempts = len(BLOCKED) - n_before
    print(f"1) MODE UJI (guard) -> broadcast mengembalikan {sent}, percobaan jaringan = {now_attempts}")

    # --- SIMULASI KODE LAMA (guard dimatikan) ---
    payrate._live_discord_allowed = lambda: True
    helpers._live_discord_allowed = lambda: True
    n_before = len(BLOCKED)
    try:
        sent2 = await payrate.broadcast_payrate_to_staff("TL", 4000, 8000)
    except Exception as e:
        sent2 = f"exception {type(e).__name__}"
    old_attempts = len(BLOCKED) - n_before
    print(f"2) PRODUKSI (tanpa guard) -> broadcast mengembalikan {sent2}, percobaan jaringan = {old_attempts}")

    print()
    if now_attempts == 0 and old_attempts > 0:
        print("KESIMPULAN: guard inilah yang menghentikan notifikasi.")
        print(f"  tanpa guard ada {old_attempts} percobaan koneksi keluar (inilah yang mengirim pesan asli)")
    else:
        print(f"KESIMPULAN: tidak konklusif (guard={now_attempts}, tanpa guard={old_attempts})")


asyncio.run(main())
