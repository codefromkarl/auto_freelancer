"""Generate a public download inventory from trusted, verified release documents."""

import argparse
import json
from pathlib import Path
from desktop.updates import ReleaseManager
from desktop.paths import atomic_json


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--issuer-public-key", type=Path, required=True)
    p.add_argument("--release", type=Path, action="append", required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args(argv)
    public = a.issuer_public_key.read_bytes()
    items = []
    targets = set()
    for file in a.release:
        doc = json.loads(file.read_text())
        body = doc["payload"]
        item = ReleaseManager(
            a.output.parent, public, body["platform"], body["architecture"]
        ).verify(doc, allow_current=True)
        target = (item["platform"], item["architecture"])
        if target in targets:
            p.error("Include only the selected release for each OS/architecture")
        targets.add(target)
        items.append(
            {
                key: item[key]
                for key in [
                    "version",
                    "platform",
                    "architecture",
                    "url",
                    "bytes",
                    "sha256",
                    "code_signed",
                    "notarized",
                    "native_verified",
                ]
                if key in item
            }
        )
    atomic_json(a.output, {"releases": items})
    print("Verified public download inventory written.")


if __name__ == "__main__":
    main()
