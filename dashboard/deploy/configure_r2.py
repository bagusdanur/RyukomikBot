"""Securely configure the private R2 bucket and browser upload CORS."""

from getpass import getpass
from pathlib import Path

import boto3
from botocore.exceptions import ClientError


ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
BUCKET = "ryukomik-staff-submissions"


def upsert(values):
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    output, seen = [], set()
    for line in lines:
        key = line.split("=", 1)[0] if "=" in line else None
        if key in values:
            if key not in seen:
                output.append(f"{key}={values[key]}"); seen.add(key)
        else:
            output.append(line)
    if output and output[-1]:
        output.append("")
    output.extend(f"{key}={value}" for key, value in values.items() if key not in seen)
    ENV_PATH.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def main():
    account_id = input("R2 Account ID: ").strip()
    access_key = getpass("R2 Access Key ID baru: ").strip()
    secret_key = getpass("R2 Secret Access Key baru: ").strip()
    if min(len(account_id), len(access_key), len(secret_key)) < 20:
        raise SystemExit("Kredensial terlihat tidak valid; tidak ada perubahan disimpan.")
    endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
    client = boto3.client("s3", endpoint_url=endpoint, aws_access_key_id=access_key,
                          aws_secret_access_key=secret_key, region_name="auto")
    client.head_bucket(Bucket=BUCKET)
    upsert({"R2_ACCOUNT_ID": account_id, "R2_ACCESS_KEY_ID": access_key,
            "R2_SECRET_ACCESS_KEY": secret_key, "R2_BUCKET_NAME": BUCKET,
            "R2_ENDPOINT": endpoint})
    try:
        client.put_bucket_cors(Bucket=BUCKET, CORSConfiguration={"CORSRules": [{
            "AllowedOrigins": ["https://staff.ryukomik.web.id"],
            "AllowedMethods": ["GET", "PUT", "HEAD"],
            "AllowedHeaders": ["Content-Type"],
            "ExposeHeaders": ["ETag"],
            "MaxAgeSeconds": 3600,
        }]})
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") != "AccessDenied":
            raise
        print("R2 terverifikasi dan kredensial tersimpan. Token tidak memiliki izin pengaturan bucket; pasang CORS manual di Cloudflare.")
    else:
        print("R2 terverifikasi, CORS terpasang, dan kredensial tersimpan tanpa ditampilkan.")


if __name__ == "__main__":
    main()
