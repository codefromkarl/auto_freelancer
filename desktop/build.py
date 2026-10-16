"""Build a native distribution with no developer data or private issuer key."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from desktop import __version__


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Build on the actual target OS and architecture."
    )
    parser.add_argument("--issuer-public-key", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=Path("dist/local"))
    parser.add_argument("--installer", action="store_true")
    parser.add_argument(
        "--sign",
        action="store_true",
        help="Use a pre-authorized native code signing identity",
    )
    parser.add_argument(
        "--notarize-profile",
        help="Existing Apple notarytool keychain profile; requires --sign and --installer",
    )
    args = parser.parse_args(argv)
    key = serialization.load_pem_public_key(args.issuer_public_key.read_bytes())
    if not isinstance(key, Ed25519PublicKey):
        parser.error("An Ed25519 public key is required, never a private key")
    root = Path(__file__).resolve().parent.parent
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    system = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    arch = {"AMD64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(
        platform.machine()
    )
    if arch is None:
        parser.error("Unsupported architecture")
    if system == "windows" and arch != "x64":
        parser.error("Windows V1 currently targets x64 only")
    with tempfile.TemporaryDirectory(prefix="bidmaster-build-") as temporary:
        stage = Path(temporary)
        public = stage / "issuer-public.pem"
        public.write_bytes(args.issuer_public_key.read_bytes())
        from desktop.notices import write_notices

        notices = stage / "THIRD_PARTY_NOTICES.txt"
        write_notices(root / "desktop/requirements-lock.txt", notices)
        env = os.environ.copy()
        env["BIDMASTER_BUILD_NOTICES"] = str(notices)
        env["BIDMASTER_BUILD_PUBLIC_KEY"] = str(public)
        if not args.sign:
            env.pop("BIDMASTER_MAC_SIGN_IDENTITY", None)
        if (
            args.sign
            and sys.platform == "darwin"
            and not env.get("BIDMASTER_MAC_SIGN_IDENTITY")
        ):
            parser.error(
                "BIDMASTER_MAC_SIGN_IDENTITY is required for a signed macOS build"
            )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--distpath",
                str(output),
                "--workpath",
                str(stage / "work"),
                str(root / "desktop/packaging/BidMaster.spec"),
            ],
            cwd=root,
            env=env,
            check=True,
        )
    package = output / ("BidMaster.app" if system == "macos" else "BidMaster")
    code_signed = False
    notarized = False
    if args.sign:
        if system == "windows":
            thumbprint = os.environ.get("BIDMASTER_WINDOWS_CERT_SHA1")
            if not thumbprint:
                parser.error(
                    "BIDMASTER_WINDOWS_CERT_SHA1 must reference an authorized certificate in the Windows store"
                )
            subprocess.run(
                [
                    "signtool",
                    "sign",
                    "/sha1",
                    thumbprint,
                    "/fd",
                    "SHA256",
                    "/tr",
                    "http://timestamp.digicert.com",
                    "/td",
                    "SHA256",
                    str(package / "BidMaster.exe"),
                ],
                check=True,
            )
            subprocess.run(
                ["signtool", "verify", "/pa", str(package / "BidMaster.exe")],
                check=True,
            )
            code_signed = True
        elif system == "macos":
            subprocess.run(
                ["codesign", "--verify", "--deep", "--strict", str(package)], check=True
            )
            code_signed = True
        else:
            parser.error("Code signing requires a native Windows/macOS build")
    if args.notarize_profile and not (
        args.sign and args.installer and system == "macos"
    ):
        parser.error("Notarization requires a signed native macOS installer")
    # Explicit integrity requirement: generated package manifests identify update payloads.
    archive_base = output / f"BidMaster-{__version__}-{system}-{arch}"
    archive = Path(
        shutil.make_archive(str(archive_base), "zip", package.parent, package.name)
    )
    artifacts = [archive]
    if args.installer:
        if system == "windows":
            compiler = (
                shutil.which("iscc") or r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
            )
            if not Path(compiler).exists() and not shutil.which(compiler):
                raise RuntimeError("Inno Setup is required for the Windows installer")
            subprocess.run(
                [
                    compiler,
                    f"/DSourceDir={package}",
                    f"/DOutputDir={output}",
                    str(root / "desktop/packaging/windows.iss"),
                ],
                check=True,
            )
            installer = output / f"BidMaster-{__version__}-windows-x64-setup.exe"
            if args.sign:
                subprocess.run(
                    [
                        "signtool",
                        "sign",
                        "/sha1",
                        thumbprint,
                        "/fd",
                        "SHA256",
                        "/tr",
                        "http://timestamp.digicert.com",
                        "/td",
                        "SHA256",
                        str(installer),
                    ],
                    check=True,
                )
                subprocess.run(
                    ["signtool", "verify", "/pa", str(installer)], check=True
                )
            artifacts.append(installer)
        elif system == "macos":
            dmg = output / f"BidMaster-{__version__}-macos-{arch}.dmg"
            with tempfile.TemporaryDirectory(prefix="bidmaster-dmg-") as temporary:
                stage = Path(temporary)
                shutil.copytree(package, stage / package.name, symlinks=True)
                (stage / "Applications").symlink_to("/Applications")
                subprocess.run(
                    [
                        "hdiutil",
                        "create",
                        "-volname",
                        "BidMaster Local",
                        "-srcfolder",
                        str(stage),
                        "-ov",
                        "-format",
                        "UDZO",
                        str(dmg),
                    ],
                    check=True,
                )
            if args.notarize_profile:
                subprocess.run(
                    [
                        "xcrun",
                        "notarytool",
                        "submit",
                        str(dmg),
                        "--keychain-profile",
                        args.notarize_profile,
                        "--wait",
                    ],
                    check=True,
                )
                subprocess.run(["xcrun", "stapler", "staple", str(dmg)], check=True)
                subprocess.run(["xcrun", "stapler", "validate", str(dmg)], check=True)
                notarized = True
            artifacts.append(dmg)
        else:
            raise RuntimeError(
                "Installer creation requires Windows or macOS; a Linux archive is not a substitute"
            )
    manifest = {
        "version": __version__,
        "platform": system,
        "architecture": arch,
        "development_build": not (code_signed and (system != "macos" or notarized)),
        "code_signed": code_signed,
        "notarized": notarized,
        "artifacts": [
            {
                "file": p.name,
                "bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
            for p in artifacts
        ],
    }
    (output / f"manifest-{system}-{arch}.json").write_text(
        json.dumps(manifest, indent=2)
    )
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
