#!/usr/bin/env python3
"""
兼容旧入口：转发到 02_fetch.py。
"""
import importlib.util
import sys
from pathlib import Path

script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))

_target = script_dir / "02_fetch.py"
_spec = importlib.util.spec_from_file_location("manual_fetch", _target)
_fetch_module = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_fetch_module)


def main(argv=None) -> int:
    return _fetch_module.main(argv)


if __name__ == "__main__":
    sys.exit(main())
