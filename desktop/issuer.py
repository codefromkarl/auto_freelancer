"""Publisher-only CLI; never include private keys in the distributed client."""

import argparse
import base64
import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from desktop.licensing import canonical
from desktop.paths import atomic_json


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Issue BidMaster local licenses after verifying an order or trial."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("keygen")
    gen.add_argument("--directory", required=True)
    issue = sub.add_parser("issue")
    issue.add_argument("--key", required=True)
    issue.add_argument("--installation", required=True)
    issue.add_argument("--days", type=int, default=14)
    issue.add_argument("--output", required=True)
    issue.add_argument(
        "--kind",
        choices=["license", "platform_authorization", "revocations"],
        default="license",
    )
    issue.add_argument("--capability", action="append", default=[])
    issue.add_argument("--authorization-reference")
    issue.add_argument("--revoked-id", action="append", default=[])
    args = parser.parse_args(argv)
    os.umask(0o077)
    if args.command == "keygen":
        directory = Path(args.directory)
        directory.mkdir(parents=True, exist_ok=True)
        private = directory / "issuer-private.pem"
        public = directory / "issuer-public.pem"
        if private.exists() or public.exists():
            parser.error(
                "Key files already exist; do not replace an active publisher identity"
            )
        key = Ed25519PrivateKey.generate()
        private.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        public.write_bytes(
            key.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        print(
            "Created publisher keys. Protect the private key; distribute only the public key."
        )
        return 0
    if not 1 <= args.days <= 366:
        parser.error("days must be 1–366")
    if len(args.installation) != 32 or any(
        c not in "0123456789abcdef" for c in args.installation
    ):
        parser.error("Invalid installation ID")
    if args.kind == "platform_authorization" and not args.authorization_reference:
        parser.error(
            "Supply a reference to verified written platform permission; a software purchase is not permission"
        )
    now = datetime.now(timezone.utc)
    payload = {
        "version": 1,
        "kind": args.kind,
        "id": str(uuid.uuid4()),
        "installation_id": args.installation,
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(days=args.days)).isoformat(),
        "capabilities": args.capability
        or (["assistant"] if args.kind == "license" else []),
    }
    if args.kind == "platform_authorization":
        payload.update(
            platform="freelancer", authorization_reference=args.authorization_reference
        )
    if args.kind == "revocations":
        payload["revoked_ids"] = args.revoked_id
    key = serialization.load_pem_private_key(Path(args.key).read_bytes(), password=None)
    document = {
        "payload": payload,
        "signature": base64.b64encode(key.sign(canonical(payload))).decode(),
    }
    atomic_json(Path(args.output), document)
    print("Signed document written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
