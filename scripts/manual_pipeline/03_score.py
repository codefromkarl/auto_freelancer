#!/usr/bin/env python3
"""
Compatibility wrapper for concurrent scoring script.
"""
import importlib.util
import sys
from pathlib import Path

script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))

_target = script_dir / "03_score_concurrent.py"
_spec = importlib.util.spec_from_file_location("score_concurrent", _target)
_score_module = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_score_module)

common = _score_module.common


def main(argv=None) -> int:
    return _score_module.main(argv)


if __name__ == "__main__":
    sys.exit(main())
