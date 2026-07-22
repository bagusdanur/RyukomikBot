"""Safely upsert non-secret production dashboard settings in the project .env."""

from pathlib import Path
import secrets


ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
SETTINGS = {
    "DISCORD_CLIENT_ID": "1524449203944816680",
    "DASHBOARD_ORIGIN": "https://staff.ryukomik.web.id",
    "DASHBOARD_API_ORIGIN": "https://staff.ryukomik.web.id",
    "DASHBOARD_DEV_BYPASS": "false",
}


def main():
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    values = dict(SETTINGS)
    if not any(line.startswith("DASHBOARD_SESSION_SECRET=") and line.split("=", 1)[1] for line in lines):
        values["DASHBOARD_SESSION_SECRET"] = secrets.token_hex(32)

    replaced = set()
    output = []
    for line in lines:
        key = line.split("=", 1)[0] if "=" in line else None
        if key in values:
            output.append(f"{key}={values[key]}")
            replaced.add(key)
        else:
            output.append(line)
    if output and output[-1]:
        output.append("")
    for key, value in values.items():
        if key not in replaced:
            output.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    print("Dashboard environment configured (secret values hidden).")


if __name__ == "__main__":
    main()
