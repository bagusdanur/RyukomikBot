"""Prompt for a Discord OAuth secret without exposing it in shell history."""

from getpass import getpass
from pathlib import Path


ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


def main():
    secret = getpass("Discord OAuth Client Secret baru: ").strip()
    if len(secret) < 20:
        raise SystemExit("Secret terlihat tidak valid; tidak ada perubahan yang disimpan.")

    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    output = []
    replaced = False
    for line in lines:
        if line.startswith("DISCORD_CLIENT_SECRET="):
            output.append(f"DISCORD_CLIENT_SECRET={secret}")
            replaced = True
        else:
            output.append(line)
    if not replaced:
        output.extend(["", f"DISCORD_CLIENT_SECRET={secret}"])
    ENV_PATH.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    print("Discord OAuth secret tersimpan. Nilainya tidak ditampilkan.")


if __name__ == "__main__":
    main()
