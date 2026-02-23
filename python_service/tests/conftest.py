"""
Shared test configuration.

Sets DATABASE_PATH to a local temp directory before any test module imports
the config singleton, preventing PermissionError on /app/data.
"""

import os
from pathlib import Path

# Must run before any import of config.settings
_test_db_dir = Path(__file__).resolve().parents[1] / "data"
os.environ.setdefault(
    "DATABASE_PATH",
    str(_test_db_dir / "test_freelancer.db"),
)
