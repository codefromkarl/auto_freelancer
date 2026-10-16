"""Signed release verification and integrity-checked downloads; no silent installation."""

import base64
import hashlib
import os
from pathlib import Path
import platform
import re
import sys
import tempfile
from urllib.parse import urlsplit
from datetime import datetime, timezone

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature
from desktop import __version__
from desktop.licensing import canonical, utc_stamp


class ReleaseError(ValueError):
    pass


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise ReleaseError("Invalid release version")
    return tuple(int(x) for x in value.split("."))


class ReleaseManager:
    def __init__(self, directory, public_key, system=None, architecture=None):
        self.directory = Path(directory)
        self.public_key = public_key
        self.system = system or {"win32": "windows", "darwin": "macos"}.get(
            sys.platform, "linux"
        )
        self.architecture = architecture or {
            "AMD64": "x64",
            "x86_64": "x64",
            "arm64": "arm64",
            "aarch64": "arm64",
        }.get(platform.machine())

    def verify(self, document, allow_current=False):
        try:
            if not self.public_key:
                raise ValueError("No trusted publisher key")
            if set(document) != {"payload", "signature"}:
                raise ValueError("Invalid envelope")
            p = document["payload"]
            serialization.load_pem_public_key(self.public_key).verify(
                base64.b64decode(document["signature"], validate=True), canonical(p)
            )
            if p["kind"] != "release" or p["version_schema"] != 1:
                raise ValueError("Invalid kind")
            if p["platform"] != self.system or p["architecture"] != self.architecture:
                raise ValueError("Wrong target")
            if version_tuple(p["version"]) < version_tuple(__version__) or (
                not allow_current
                and version_tuple(p["version"]) == version_tuple(__version__)
            ):
                raise ValueError("Not a newer release")
            if (
                not utc_stamp(p["issued_at"])
                <= datetime.now(timezone.utc)
                < utc_stamp(p["expires_at"])
            ):
                raise ValueError("Expired release")
            if (
                p.get("native_verified") is not True
                or p.get("code_signed") is not True
                or (self.system == "macos" and p.get("notarized") is not True)
            ):
                raise ValueError("Release signing is incomplete")
            url = urlsplit(p["url"])
            suffix = {"windows": ".exe", "macos": ".dmg"}.get(self.system)
            if (
                not suffix
                or url.scheme != "https"
                or not url.hostname
                or url.username
                or url.password
                or url.fragment
                or not url.path.endswith(suffix)
            ):
                raise ValueError("Invalid installer URL")
            if not re.fullmatch(r"[a-f0-9]{64}", p["sha256"]):
                raise ValueError("Invalid digest")
            if (
                isinstance(p["bytes"], bool)
                or not isinstance(p["bytes"], int)
                or not 1 <= p["bytes"] <= 1024**3
            ):
                raise ValueError("Invalid size")
            return p
        except (ValueError, KeyError, TypeError, InvalidSignature, AttributeError):
            raise ReleaseError(
                "Release is untrusted, expired, not newer, or not verified for this operating system."
            ) from None

    async def download(self, document):
        p = self.verify(document)
        target = self.directory / "updates"
        target.mkdir(exist_ok=True, mode=0o700)
        fd, temp = tempfile.mkstemp(prefix="download-", dir=target)
        digest = hashlib.sha256()
        count = 0
        try:
            with os.fdopen(fd, "wb") as output:
                async with httpx.AsyncClient(
                    trust_env=False, follow_redirects=False, timeout=30
                ) as client:
                    async with client.stream("GET", p["url"]) as response:
                        if response.status_code != 200:
                            raise ReleaseError(
                                "Installer download failed; no update was installed."
                            )
                        async for chunk in response.aiter_bytes():
                            count += len(chunk)
                            if count > p["bytes"]:
                                raise ReleaseError(
                                    "Installer size exceeds signed release metadata."
                                )
                            digest.update(chunk)
                            output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if count != p["bytes"] or digest.hexdigest() != p["sha256"]:
                raise ReleaseError(
                    "Installer integrity check failed; no update was installed."
                )
            name = f"BidMaster-{p['version']}-{self.system}-{self.architecture}" + (
                ".exe" if self.system == "windows" else ".dmg"
            )
            os.replace(temp, target / name)
            return {
                "file": str(target / name),
                "installed": False,
                "next_step": "Pause work and quit safely before opening this verified installer. User data is kept separately.",
            }
        except httpx.HTTPError:
            raise ReleaseError(
                "Installer could not be downloaded; no update was installed."
            ) from None
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
