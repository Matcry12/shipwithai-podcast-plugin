#!/usr/bin/env python3
# r2_upload.py — Upload a rendered .mp3 to Cloudflare R2 and print the public URL.
# stdlib only — no install required (hashlib, hmac, datetime, urllib.request, os, sys, argparse, pathlib)
#
# Usage:
#   python r2_upload.py <mp3-path> [--key <object-key>]
#
# Arguments:
#   mp3-path   Path to the local .mp3 file to upload (required).
#   --key      R2 object key (default: basename of mp3-path, e.g. my-episode.mp3).
#
# Required env vars:
#   PODCAST_R2_ACCOUNT_ID    Cloudflare account ID (the hex string in the R2 dashboard URL).
#   PODCAST_R2_ACCESS_KEY    R2 API token Access Key ID.
#   PODCAST_R2_SECRET_KEY    R2 API token Secret Access Key.
#   PODCAST_R2_BUCKET        R2 bucket name.
#   PODCAST_R2_PUBLIC_BASE   Public base URL for the bucket, e.g. https://assets.example.com.
#
# On success, prints the public URL on its own line so callers can grep/parse it.

from __future__ import annotations

import argparse
import datetime
import hashlib
import hmac
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


# ── Arg parsing (before any heavy work so --help works instantly) ────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="r2_upload.py",
        description=(
            "Upload a rendered .mp3 to Cloudflare R2 and print the public URL. "
            "Reads credentials from PODCAST_R2_* env vars."
        ),
    )
    parser.add_argument(
        "mp3_path",
        metavar="mp3-path",
        help="Path to the local .mp3 file to upload.",
    )
    parser.add_argument(
        "--key",
        default=None,
        help="R2 object key (default: basename of mp3-path, e.g. my-episode.mp3).",
    )
    return parser


def parse_args() -> argparse.Namespace:
    return build_parser().parse_args()


# ── AWS Signature Version 4 helpers ─────────────────────────────────────────

def quote_path(path: str) -> str:
    """Percent-encode a URL path per AWS SigV4 rules: each '/'-separated
    segment is percent-encoded individually (unreserved chars preserved),
    and the '/' separators themselves are left intact. This is the single
    source of truth for path encoding — call it once and reuse the result
    for both the signed canonical URI and the actual request URL so they
    can never drift apart."""
    return "/".join(urllib.parse.quote(segment, safe="") for segment in path.split("/"))


def _sign(key: bytes, msg: str) -> bytes:
    """HMAC-SHA256: key is already bytes, msg is a str."""
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _derive_signing_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    k_date    = _sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region  = _sign(k_date, region)
    k_service = _sign(k_region, service)
    k_signing = _sign(k_service, "aws4_request")
    return k_signing


def _sigv4_auth_header(
    method: str,
    host: str,
    canonical_uri: str,
    body: bytes,
    access_key: str,
    secret_key: str,
    region: str,
    service: str,
    amz_date: str,
    date_stamp: str,
) -> str:
    """Return the Authorization header value for an S3 PutObject request.

    canonical_uri must already be percent-encoded (via quote_path) and must
    be the exact same string used to build the request URL, or the
    signature will not match what R2 receives."""

    payload_hash       = hashlib.sha256(body).hexdigest()
    canonical_qs       = ""
    canonical_headers  = (
        f"host:{host}\n"
        f"x-amz-content-sha256:{payload_hash}\n"
        f"x-amz-date:{amz_date}\n"
    )
    signed_headers = "host;x-amz-content-sha256;x-amz-date"

    canonical_request = "\n".join([
        method,
        canonical_uri,
        canonical_qs,
        canonical_headers,
        signed_headers,
        payload_hash,
    ])

    algorithm        = "AWS4-HMAC-SHA256"
    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    cr_hash          = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    string_to_sign   = "\n".join([algorithm, amz_date, credential_scope, cr_hash])

    signing_key = _derive_signing_key(secret_key, date_stamp, region, service)
    signature   = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    return (
        f"{algorithm} "
        f"Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )


# ── Upload ───────────────────────────────────────────────────────────────────

def upload_to_r2(
    mp3_path: Path,
    key: str,
    account_id: str,
    access_key: str,
    secret_key: str,
    bucket: str,
) -> None:
    """Sign and PUT the mp3 file to Cloudflare R2 via S3-compatible API."""

    region  = "auto"
    service = "s3"
    host    = f"{account_id}.r2.cloudflarestorage.com"
    # Encode once; reuse for both the request URL and the signed canonical
    # URI so they cannot drift apart (the SigV4 bug this fixes).
    canonical_uri = "/" + quote_path(f"{bucket}/{key}")
    url           = f"https://{host}{canonical_uri}"

    body = mp3_path.read_bytes()
    print(f"[upload] PUT  {url}")
    print(f"[upload] File: {mp3_path}  ({len(body):,} bytes)")

    now        = datetime.datetime.now(datetime.timezone.utc)
    amz_date   = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    payload_hash = hashlib.sha256(body).hexdigest()

    auth_header = _sigv4_auth_header(
        method="PUT",
        host=host,
        canonical_uri=canonical_uri,
        body=body,
        access_key=access_key,
        secret_key=secret_key,
        region=region,
        service=service,
        amz_date=amz_date,
        date_stamp=date_stamp,
    )

    req = urllib.request.Request(url, data=body, method="PUT")
    req.add_header("Authorization",         auth_header)
    req.add_header("x-amz-date",            amz_date)
    req.add_header("x-amz-content-sha256",  payload_hash)
    req.add_header("Content-Type",          "audio/mpeg")
    req.add_header("Content-Length",        str(len(body)))

    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            etag = resp.headers.get("ETag", "")
            print(f"[upload] ✅  Uploaded {len(body):,} bytes → {key}")
            if etag:
                print(f"[upload] ETag: {etag}")
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")[:500]
        sys.exit(
            f"ERROR [upload]: R2 returned HTTP {e.code}\n"
            f"{error_body}\n"
            "Check your credentials, bucket name, and object key."
        )
    except urllib.error.URLError as e:
        sys.exit(
            f"ERROR [upload]: Could not connect to R2 endpoint {host}\n{e.reason}\n"
            "Check that PODCAST_R2_ACCOUNT_ID is correct and you have network access."
        )


# ── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()

    mp3_path = Path(args.mp3_path)
    if not mp3_path.exists():
        sys.exit(f"ERROR: MP3 file not found: {mp3_path}")

    object_key = args.key if args.key else mp3_path.name

    env_vars = {
        "PODCAST_R2_ACCOUNT_ID":  os.environ.get("PODCAST_R2_ACCOUNT_ID", ""),
        "PODCAST_R2_ACCESS_KEY":  os.environ.get("PODCAST_R2_ACCESS_KEY", ""),
        "PODCAST_R2_SECRET_KEY":  os.environ.get("PODCAST_R2_SECRET_KEY", ""),
        "PODCAST_R2_BUCKET":      os.environ.get("PODCAST_R2_BUCKET", ""),
        "PODCAST_R2_PUBLIC_BASE": os.environ.get("PODCAST_R2_PUBLIC_BASE", ""),
    }

    missing = [k for k, v in env_vars.items() if not v]
    if missing:
        sys.exit(
            "ERROR: The following required env vars are unset or empty:\n"
            + "".join(f"  {k}\n" for k in missing)
            + "Export them in your shell before invoking r2_upload.py."
        )

    account_id  = env_vars["PODCAST_R2_ACCOUNT_ID"]
    access_key  = env_vars["PODCAST_R2_ACCESS_KEY"]
    secret_key  = env_vars["PODCAST_R2_SECRET_KEY"]
    bucket      = env_vars["PODCAST_R2_BUCKET"]
    public_base = env_vars["PODCAST_R2_PUBLIC_BASE"]

    upload_to_r2(
        mp3_path=mp3_path,
        key=object_key,
        account_id=account_id,
        access_key=access_key,
        secret_key=secret_key,
        bucket=bucket,
    )

    public_url = public_base.rstrip("/") + "/" + quote_path(object_key)
    print(f"[upload] PUBLIC_URL {public_url}")
    # Plain line so callers can grep unambiguously:
    print(public_url)


if __name__ == "__main__":
    main()
