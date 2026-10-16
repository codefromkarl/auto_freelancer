"""Include upstream license texts from the resolved dependency distributions."""

import importlib.metadata
import re
from pathlib import Path
import sys


def write_notices(lockfile, output):
    names = {
        m.group(1)
        for line in Path(lockfile).read_text().splitlines()
        if (m := re.match(r"^([A-Za-z0-9_.-]+)==", line))
    }
    names.add("pyinstaller")
    parts = [
        "BidMaster Local — Third-party notices",
        "Python " + sys.version.split()[0],
    ]
    for name in sorted(names):
        try:
            distribution = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            continue  # Platform-specific dependencies need not exist on every builder.
        parts.append("\n## " + name + " " + distribution.version)
        expression = distribution.metadata.get(
            "License-Expression"
        ) or distribution.metadata.get("License")
        if expression:
            parts.append(expression)
        for file in distribution.files or []:
            path = Path(str(file))
            if ".dist-info" not in str(file) or path.suffix.lower() not in {
                "",
                ".txt",
                ".md",
                ".rst",
            }:
                continue
            if not path.name.lower().startswith(("license", "copying", "notice")):
                continue
            try:
                parts.append(distribution.locate_file(file).read_text(encoding="utf-8"))
            except (OSError, UnicodeError):
                continue
    Path(output).write_text("\n\n".join(parts), encoding="utf-8")
