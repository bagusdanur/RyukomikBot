"""Verify private R2 read/write and browser CORS without exposing credentials."""

import os
import secrets
from urllib.request import Request, urlopen

import boto3
from dotenv import load_dotenv


load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"))


def main():
    bucket = os.environ["R2_BUCKET_NAME"]
    client = boto3.client(
        "s3", endpoint_url=os.environ["R2_ENDPOINT"], region_name="auto",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    )
    key = f"system-check/{secrets.token_hex(8)}.txt"
    body = b"Ryukomik R2 verification"
    try:
        client.put_object(Bucket=bucket, Key=key, Body=body, ContentType="text/plain")
        metadata = client.head_object(Bucket=bucket, Key=key)
        if metadata["ContentLength"] != len(body):
            raise RuntimeError("Ukuran object hasil tes tidak sesuai.")
        upload_url = client.generate_presigned_url(
            "put_object", Params={"Bucket": bucket, "Key": key, "ContentType": "text/plain"}, ExpiresIn=300
        )
        request = Request(upload_url, method="OPTIONS", headers={
            "Origin": "https://staff.ryukomik.web.id",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type",
        })
        with urlopen(request, timeout=20) as response:
            allowed = response.headers.get("Access-Control-Allow-Origin")
        if allowed not in ("*", "https://staff.ryukomik.web.id"):
            raise RuntimeError("CORS belum mengizinkan origin dashboard.")
        print("R2 read/write, private object, presigned URL, dan browser CORS: OK")
    finally:
        client.delete_object(Bucket=bucket, Key=key)


if __name__ == "__main__":
    main()
