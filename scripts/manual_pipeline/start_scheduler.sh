#!/bin/bash
# Launcher script: clears proxy env vars before starting scheduler

# Global proxy handling is task-local; QQ connects directly to official APIs.
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

set -e
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
PYTHON_BIN="${PYTHON_BIN:-../../.venv/bin/python}"
if [ ! -x "$PYTHON_BIN" ]; then PYTHON_BIN=python3; fi

exec "$PYTHON_BIN" scheduler.py \
  --interval 30 \
  --since-days 3 \
  --bid-threshold 7.0 \
  --max-bids-per-cycle 2 \
  --limit 20 \
  --keywords "python automation,fastapi,web scraping,api integration" "$@"
