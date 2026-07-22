"""Replace duplicate Discord bot-token entries without exposing the token."""

from getpass import getpass
from pathlib import Path


ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


def main():
    token = getpass("Discord Bot Token baru: ").strip()
    if len(token) < 40:
        raise SystemExit("Token terlihat tidak valid; tidak ada perubahan yang disimpan.")
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    output, inserted = [], False
    for line in lines:
        if line.startswith("DISCORD_TOKEN="):
            if not inserted:
                output.append(f"DISCORD_TOKEN={token}")
                inserted = True
            continue
        output.append(line)
    if not inserted:
        output.extend(["", f"DISCORD_TOKEN={token}"])
    ENV_PATH.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    print("Bot token tersimpan dan entri duplikat dibersihkan. Nilai tidak ditampilkan.")


if __name__ == "__main__":
    main()
