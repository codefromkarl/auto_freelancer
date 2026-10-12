#!/usr/bin/env python3
"""Run the QQ receiver independently of trading credentials and the scheduler."""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'python_service'))
from services.qqbot_gateway import run_gateway
from services.qqbot_service import QQBotConfig


def main():
    parser = argparse.ArgumentParser(description='Receive QQ Bot private/group events; never submits bids')
    parser.add_argument('--once-ready', action='store_true', help='Verify authenticated Gateway readiness and exit')
    parser.add_argument('--max-reconnects', type=int, default=10)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run_gateway(QQBotConfig.from_env(), once_ready=args.once_ready, max_reconnects=args.max_reconnects))
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f'QQ receiver failed: {type(exc).__name__}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
