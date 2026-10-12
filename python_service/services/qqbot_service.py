"""QQ Bot official API adapter. Credentials are private; failures never mean delivery."""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import threading
import time
from typing import Any
from urllib.parse import quote

from dotenv import dotenv_values
import requests

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class QQBotConfig:
    app_id: str = ''
    app_secret: str = field(default='', repr=False)
    api_base: str = 'https://api.bot.qq.com'
    target_type: str = 'c2c'
    target_id: str = ''
    approvers: frozenset[str] = field(default_factory=frozenset)
    state_path: str = str(ROOT / 'python_service/data/qqbot.db')

    @classmethod
    def from_env(cls) -> 'QQBotConfig':
        values = {**dotenv_values(ROOT / '.env'), **dotenv_values(ROOT / '.env.qqbot'), **os.environ}
        return cls(
            app_id=values.get('QQ_BOT_APP_ID') or '',
            app_secret=values.get('QQ_BOT_APP_SECRET') or '',
            api_base=(values.get('QQ_BOT_API_BASE') or cls.api_base).rstrip('/'),
            target_type=values.get('QQ_BOT_TARGET_TYPE') or 'c2c',
            target_id=values.get('QQ_BOT_TARGET_ID') or '',
            approvers=frozenset(x.strip() for x in (values.get('QQ_BOT_APPROVER_OPENIDS') or '').split(',') if x.strip()),
            state_path=values.get('QQ_BOT_STATE_PATH') or cls.state_path,
        )

    def require_target(self) -> None:
        if self.target_type not in {'c2c', 'group'} or not self.target_id:
            raise ValueError('QQ Bot requires a configured target type and target OpenID')


class QQBotError(RuntimeError):
    pass


class QQBotClient:
    def __init__(self, config: QQBotConfig, session=None):
        self.config = config
        self.session = session or requests.Session()
        self.session.trust_env = False
        self._token = ''
        self._expires_at = 0.0
        self._lock = threading.RLock()

    def get_token(self) -> str:
        with self._lock:
            if self._token and time.monotonic() < self._expires_at:
                return self._token
            if not self.config.app_id or not self.config.app_secret:
                raise QQBotError('QQ Bot credentials are missing')
            data = self._request('POST', '/app/getAppAccessToken', authenticated=False,
                json={'appId': self.config.app_id, 'clientSecret': self.config.app_secret})
            token = data.get('access_token')
            expiry = int(data.get('expires_in') or 0)
            if not isinstance(token, str) or not token or expiry <= 0:
                raise QQBotError('QQ Bot token response is incomplete')
            self._token = token
            self._expires_at = time.monotonic() + max(1, expiry - 60)
            return token

    def _request(self, method: str, path: str, authenticated=True, **kwargs) -> dict[str, Any]:
        with self._lock:
            headers = {'Content-Type': 'application/json'}
            if authenticated:
                headers.update(Authorization='QQBot ' + self.get_token(), **{'X-Union-Appid': self.config.app_id})
            try:
                response = self.session.request(method, self.config.api_base + path,
                    headers=headers, timeout=(5, 20), allow_redirects=False, **kwargs)
            except requests.RequestException as exc:
                raise QQBotError(f'QQ Bot request outcome unknown ({type(exc).__name__}); no automatic resend') from None
            try:
                data = response.json()
            except ValueError:
                raise QQBotError('QQ Bot returned a non-JSON response') from None
            if response.status_code not in (200, 201) or not isinstance(data, dict):
                code = data.get('code') if isinstance(data, dict) else None
                raise QQBotError(f'QQ Bot API rejected request (HTTP {response.status_code}, code={code})')
            return data

    def profile(self) -> dict:
        return self._request('GET', '/users/@me')

    def gateway(self) -> dict:
        return self._request('GET', '/gateway/bot')

    def send_text(self, content: str, *, target_type=None, target_id=None, msg_id=None, msg_seq=1) -> str:
        scope = target_type or self.config.target_type
        target = target_id or self.config.target_id
        if scope not in {'c2c', 'group'} or not target:
            raise QQBotError('QQ Bot notification target is not configured')
        if not content or len(content) > 1800:
            raise QQBotError('QQ Bot text must contain 1-1800 characters')
        namespace = 'users' if scope == 'c2c' else 'groups'
        body = {'content': content, 'msg_type': 0}
        if msg_id:
            body.update(msg_id=msg_id, msg_seq=msg_seq)
        data = self._request('POST', f'/v2/{namespace}/{quote(target, safe="")}/messages', json=body)
        message_id = data.get('id')
        if not message_id:
            raise QQBotError('QQ Bot delivery response missing message ID; outcome unknown')
        return str(message_id)
