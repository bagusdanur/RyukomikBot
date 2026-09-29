"""Jalankan SELURUH suite dengan semua koneksi keluar diblokir.

Kalau ada tes yang mencoba menembak Discord, ia gagal di sini alih-alih
mengirim pesan asli ke staff. Jalankan dari root repo:
    dashboard/.venv/bin/python tools/audit_suite_nonet.py
"""
import os
import socket
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

BLOCKED = []


class _BlockedSocket(socket.socket):
    def connect(self, *a, **k):
        BLOCKED.append(("socket.connect", a[:1]))
        raise OSError("jaringan keluar diblokir (audit suite)")


def _no_create_connection(*a, **k):
    BLOCKED.append(("create_connection", a[:1]))
    raise OSError("jaringan keluar diblokir (audit suite)")


socket.socket = _BlockedSocket
socket.create_connection = _no_create_connection

suite = unittest.TestLoader().discover("tests")
result = unittest.TextTestRunner(verbosity=1).run(suite)

print("\n=== AUDIT JARINGAN ===")
print("percobaan koneksi keluar:", len(BLOCKED))
for kind, addr in BLOCKED[:10]:
    print(f"   {kind} {addr}")
if BLOCKED:
    print("  !! MASIH ADA tes yang menembak jaringan luar")
else:
    print("  AMAN: tidak ada tes yang menghubungi jaringan luar")

sys.exit(0 if (not BLOCKED and result.wasSuccessful()) else 1)
