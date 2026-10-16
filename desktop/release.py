"""Publishable release metadata, issued only after native/signing verification."""

import argparse
import base64
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
from urllib.parse import urlsplit
from cryptography.hazmat.primitives import serialization
from desktop.licensing import canonical
from desktop.paths import atomic_json


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", required=True, type=Path)
    p.add_argument("--artifact", required=True)
    p.add_argument("--url", required=True)
    p.add_argument("--key", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--native-verification", required=True, type=Path)
    a = p.parse_args(argv)
    m = json.loads(a.manifest.read_text())
    e = json.loads(a.native_verification.read_text())
    if (
        m.get("development_build")
        or not m.get("code_signed")
        or (m["platform"] == "macos" and not m.get("notarized"))
    ):
        p.error("Only verified production-signed builds may be published")
    if (
        e.get("version") != m["version"]
        or e.get("platform") != m["platform"]
        or e.get("architecture") != m["architecture"]
        or not all(
            e.get(k)
            for k in ["packaged_launch", "restart_preserves_data", "native_vault"]
        )
    ):
        p.error("Matching successful native verification is required")
    url = urlsplit(a.url)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.fragment
    ):
        p.error("A direct HTTPS installer URL without credentials is required")
    expected_suffix = ".exe" if m["platform"] == "windows" else ".dmg"
    if not a.artifact.endswith(expected_suffix):
        p.error("Select the native installer, not a portable preview archive")
    artifact = next((x for x in m["artifacts"] if x["file"] == a.artifact), None)
    if not artifact or Path(urlsplit(a.url).path).name != a.artifact:
        p.error("URL must identify the verified installer artifact")
    now = datetime.now(timezone.utc)
    body = {
        "kind": "release",
        "version_schema": 1,
        "version": m["version"],
        "platform": m["platform"],
        "architecture": m["architecture"],
        "native_verified": True,
        "code_signed": True,
        "notarized": m.get("notarized", False),
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(days=30)).isoformat(),
        "url": a.url,
        "sha256": artifact["sha256"],
        "bytes": artifact["bytes"],
    }
    key = serialization.load_pem_private_key(a.key.read_bytes(), password=None)
    atomic_json(
        a.output,
        {
            "payload": body,
            "signature": base64.b64encode(key.sign(canonical(body))).decode(),
        },
    )
    print(
        "Signed release metadata written. Upload only the installer and public metadata, never issuer keys."
    )


if __name__ == "__main__":
    main()
