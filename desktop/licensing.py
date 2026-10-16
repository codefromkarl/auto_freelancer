"""Offline verifiable publisher licenses. Platform permission is a separate attestation."""

import base64
import json
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature
from desktop.paths import atomic_json


class EntitlementError(ValueError):
    pass


def canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def utc_stamp(value):
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError("Timestamp must contain a timezone")
    return stamp.astimezone(timezone.utc)


class LicenseManager:
    def __init__(self, directory, installation_id, public_key=None, clock=None):
        self.directory = Path(directory)
        self.installation_id = installation_id
        self.public_key = public_key
        if self.public_key is None:
            path = Path(__file__).parent / "assets" / "issuer-public.pem"
            if path.exists():
                self.public_key = path.read_bytes()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def verify(self, document, kind):
        try:
            if not self.public_key:
                raise ValueError("Publisher key is not configured")
            if not isinstance(document, dict) or set(document) != {
                "payload",
                "signature",
            }:
                raise ValueError("Invalid envelope")
            payload = document["payload"]
            if payload["kind"] != kind or payload["version"] != 1:
                raise ValueError("Wrong document kind")
            key = serialization.load_pem_public_key(self.public_key)
            key.verify(
                base64.b64decode(document["signature"], validate=True),
                canonical(payload),
            )
            if (
                kind != "revocations"
                and payload["installation_id"] != self.installation_id
            ):
                raise ValueError("Wrong installation")
            now = self.clock()
            if (
                not utc_stamp(payload["issued_at"])
                <= now
                < utc_stamp(payload["expires_at"])
            ):
                raise ValueError("Document is not current")
            if not isinstance(payload["id"], str) or not 1 <= len(payload["id"]) <= 100:
                raise ValueError("Invalid document ID")
            return payload
        except (ValueError, KeyError, TypeError, InvalidSignature, AttributeError):
            raise EntitlementError(
                "This document is invalid, expired, or issued for another installation."
            ) from None

    def load(self, kind):
        path = self.directory / (kind + ".json")
        try:
            return self.verify(json.loads(path.read_text(encoding="utf-8")), kind)
        except (OSError, json.JSONDecodeError):
            raise EntitlementError(
                "Import a valid signed "
                + kind.replace("_", " ")
                + " document to enable this feature."
            ) from None

    def install(self, document):
        if len(canonical(document)) > 32768:
            raise EntitlementError("Document is too large")
        kind = document.get("payload", {}).get("kind")
        if kind not in {"license", "platform_authorization", "revocations"}:
            raise EntitlementError("Unsupported document")
        payload = self.verify(document, kind)
        if kind == "license" and (
            not isinstance(payload.get("capabilities"), list)
            or any(
                c not in {"assistant", "platform_execution"}
                for c in payload["capabilities"]
            )
        ):
            raise EntitlementError("Invalid license capabilities")
        if kind == "platform_authorization":
            if (
                payload.get("platform") != "freelancer"
                or not str(payload.get("authorization_reference") or "").strip()
            ):
                raise EntitlementError(
                    "A verified written platform permission reference is required"
                )
            if not isinstance(payload.get("capabilities"), list) or any(
                c not in {"platform_read", "platform_bid"}
                for c in payload["capabilities"]
            ):
                raise EntitlementError("Invalid platform capabilities")
        if kind == "revocations" and not isinstance(payload.get("revoked_ids"), list):
            raise EntitlementError("Invalid revocations")
        atomic_json(self.directory / (kind + ".json"), document)
        return self.status()

    def require(self, capability):
        payload = self.load("license")
        revoked = self.directory / "revocations.json"
        if revoked.exists():
            revocations = self.load("revocations")
            if payload["id"] in revocations["revoked_ids"]:
                raise EntitlementError("This license was revoked.")
        if capability not in payload.get("capabilities", []):
            raise EntitlementError("Your license does not include this feature.")
        return payload

    def require_platform(self, capability):
        self.require("platform_execution")
        payload = self.load("platform_authorization")
        if payload.get("platform") != "freelancer" or not payload.get(
            "authorization_reference"
        ):
            raise EntitlementError("Verified written platform permission is required.")
        if capability not in payload.get("capabilities", []):
            raise EntitlementError("Platform action has not been authorized.")
        return payload

    def status(self):
        try:
            payload = self.require("assistant")
            return {
                "active": True,
                "id": payload["id"],
                "expires_at": payload["expires_at"],
                "capabilities": payload.get("capabilities", []),
            }
        except EntitlementError as exc:
            return {
                "active": False,
                "message": str(exc),
                "publisher_configured": bool(self.public_key),
            }


def require_platform_access(directory, installation_id, capability):
    return LicenseManager(directory, installation_id).require_platform(capability)
