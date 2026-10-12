#!/usr/bin/env python3
"""Send already-prepared, immutable candidates to the configured QQ recipient."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'python_service'))
from services.qqbot_service import QQBotConfig, QQBotClient
from services.qqbot_store import QQBotStore
from services.qqbot_events import notify_snapshot


def main():
    parser = argparse.ArgumentParser(description='Notify prepared QQ candidates, never submit bids')
    parser.add_argument('--limit', type=int, default=5)
    args = parser.parse_args()
    config = QQBotConfig.from_env()
    try:
        config.require_target()
        client = QQBotClient(config)
        store = QQBotStore(config.state_path)
        sent = sum(notify_snapshot(client, store, record) for record in store.list_pending(args.limit))
        print(f'QQ candidate notifications confirmed: {sent}')
    except Exception as exc:
        print(f'QQ notification failed: {type(exc).__name__}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
