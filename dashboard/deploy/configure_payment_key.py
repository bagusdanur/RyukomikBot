"""Create the payout-data encryption key once without printing the secret."""

from pathlib import Path

from cryptography.fernet import Fernet

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
KEY = "PAYMENT_DATA_ENCRYPTION_KEY"


def main():
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    existing = next((line.split("=", 1)[1] for line in lines if line.startswith(f"{KEY}=")), "")
    if existing:
        Fernet(existing.encode())
        print("Payment encryption key already configured and valid.")
        return
    lines.extend(["", f"{KEY}={Fernet.generate_key().decode()}"])
    ENV_PATH.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print("Payment encryption key created (value hidden).")


if __name__ == "__main__":
    main()
