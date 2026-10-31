#!/usr/bin/env python3
"""Klien RAW API: tinggal pasang judul, server yang mengunduh.

Contoh:
    export RAW_API_URL=https://staff.ryukomik.web.id
    export RAW_API_KEY=<isi dari dashboard/.raw-api-key di server>
    python raw_api_client.py "Koshaku no Tsukibito Ossan, Yonaoshi Tabi de Harem to Naru" --chapter 1 --out raw.zip

Default `original` (file sumber apa adanya); `joined` hanya bila diminta eksplisit.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description="Unduh RAW lewat RAW API (by title).")
    parser.add_argument("title", help="judul manga/komik")
    parser.add_argument("--chapter", default=None, help="nomor chapter, mis. 1")
    parser.add_argument("--source", default=None, help="mangadex/asura/thunder/...")
    parser.add_argument("--mode", choices=("original", "joined"), default="original")
    parser.add_argument("--out", default="raw.zip")
    parser.add_argument("--wait", type=int, default=900, help="detik menunggu (polling)")
    args = parser.parse_args()

    base = os.getenv("RAW_API_URL", "https://staff.ryukomik.web.id").rstrip("/")
    key = os.getenv("RAW_API_KEY", "").strip()
    if not key:
        print("RAW_API_KEY belum di-set.", file=sys.stderr)
        return 2
    headers = {"X-API-Key": key}
    payload = {"title": args.title, "chapter": args.chapter, "source": args.source, "mode": args.mode}

    with httpx.Client(base_url=base, headers=headers, timeout=httpx.Timeout(60, read=600)) as client:
        created = client.post("/api/v1/raw/fetch", json=payload)
        if created.status_code >= 400:
            print(f"gagal: {created.status_code} {created.text[:300]}", file=sys.stderr)
            return 1
        job = created.json()
        token = job["token"]
        print(f"chapter: {job.get('chapter')} | source: {job.get('source')} | token: {token[:8]}", flush=True)
        deadline = time.time() + args.wait
        while time.time() < deadline:
            state = client.get(f"/api/v1/raw/status/{token}").json()
            print(f"  {state['state']}", flush=True)
            if state["state"] == "READY":
                url = state.get("download", {}).get(args.mode) or state.get("download", {}).get("original")
                response = client.get(url)
                response.raise_for_status()
                with open(args.out, "wb") as handle:
                    handle.write(response.content)
                print(f"tersimpan: {args.out} ({len(response.content)/1e6:.1f} MB)")
                return 0
            if state["state"] == "FAILED":
                print(f"gagal: {state.get('error')}", file=sys.stderr)
                return 1
            time.sleep(3)
    print("waktu habis; paket RAW tersimpan 30 menit, cek /status/{token} lagi.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
