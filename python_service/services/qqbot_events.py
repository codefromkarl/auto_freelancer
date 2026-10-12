"""Verified QQ events: explicit identities, immutable previews, no trading side effect."""
from __future__ import annotations

import asyncio
import json
import re
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.exceptions import InvalidSignature

from services.qqbot_service import QQBotClient, QQBotConfig, QQBotError
from services.qqbot_store import QQBotStore


def signing_key(secret: str):
    if not secret:
        raise ValueError('QQ Bot secret is missing')
    seed = secret
    while len(seed) < 32:
        seed += seed
    return Ed25519PrivateKey.from_private_bytes(seed[:32].encode())


def verify_callback(secret, timestamp, signature, body: bytes) -> None:
    if not timestamp or not str(timestamp).isdigit():
        raise ValueError('QQ callback timestamp is missing or expired')
    stamp = int(timestamp)
    if stamp > 100_000_000_000:
        stamp /= 1000
    if abs(time.time()-stamp) > 300:
        raise ValueError('QQ callback timestamp is missing or expired')
    try:
        signing_key(secret).public_key().verify(bytes.fromhex(signature), timestamp.encode()+body)
    except (InvalidSignature, TypeError, ValueError):
        raise ValueError('QQ callback signature is invalid') from None


def verification_response(secret: str, data: dict) -> dict:
    plain = data.get('plain_token', '')
    timestamp = str(data.get('event_ts', ''))
    # An unsigned challenge must not become an arbitrary-message signing oracle.
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', plain) or not timestamp.isdigit():
        raise ValueError('Invalid QQ callback verification challenge')
    stamp = int(timestamp)
    if stamp > 100_000_000_000_000:
        raise ValueError('Invalid QQ callback verification timestamp')
    if stamp > 100_000_000_000:
        stamp /= 1000
    if abs(time.time()-stamp) > 300:
        raise ValueError('Expired QQ callback verification challenge')
    return {'plain_token': plain, 'signature': signing_key(secret).sign((timestamp+plain).encode()).hex()}


def parse_message(event: dict) -> dict | None:
    data = event.get('d') or {}
    kind = event.get('t')
    author = data.get('author') or {}
    if kind == 'C2C_MESSAGE_CREATE':
        actor = author.get('user_openid')
        scope, target = 'c2c', actor
    elif kind == 'GROUP_AT_MESSAGE_CREATE':
        actor = author.get('member_openid')
        scope, target = 'group', data.get('group_openid')
    else:
        return None
    if not all(isinstance(x, str) and x for x in (actor, target, data.get('id'))):
        return None
    content = re.sub(r'<@!?[^>]+>', '', str(data.get('content') or '')).strip().lstrip('/')
    return {'actor': actor, 'scope': scope, 'target': target, 'message_id': data['id'], 'content': content,
            'event_id': str(event.get('id') or f"{kind}:{data['id']}")}


def preview_text(snapshot: dict) -> str:
    payload = snapshot['payload']
    risk = '需人工风险复核' if payload.get('review_required') else '基础检查已通过'
    command = '批准风险' if payload.get('review_required') else '批准'
    comparison = ''
    review = payload.get('competition_review')
    if review:
        from services.proposal_review_display import review_summary
        comparison = review_summary(review)+'\n'
        if review.get('feature_gap_labels'):
            comparison += '建议补充：'+'、'.join(review['feature_gap_labels'][:2])+'\n'
    text = (
        f"投标候选（未提交）\n项目 {payload['project_id']}：{payload['title']}\n"
        f"报价 {payload['amount']:.2f} {payload['currency']}；工期 {payload['period']} 天\n"
        f"状态：{risk}；有效期截至 {time.strftime('%H:%M', time.localtime(snapshot['expires_at']))}\n"
        f"复核事项：{'；'.join(payload.get('review_notes') or [])}\n"
        f"{comparison}"
        f"完整提案：\n{payload['description']}\n\n"
        f"审批内容版本 {snapshot['digest'][:16]}\n"
        f"{command} {snapshot['id']} {snapshot['digest'][:16]}\n"
        f"拒绝 {snapshot['id']} {snapshot['digest'][:16]}"
    )
    return text


def notify_snapshot(client: QQBotClient, store: QQBotStore, snapshot: dict) -> bool:
    client.config.require_target()
    payload = snapshot['payload']
    if (payload.get('qq_app_id') != client.config.app_id
            or payload.get('qq_target_type') != client.config.target_type
            or payload.get('qq_target_id') != client.config.target_id):
        raise ValueError('QQ notification destination differs from the prepared snapshot')
    text = preview_text(snapshot)
    if len(text) > 1800:
        raise ValueError('Prepared proposal exceeds QQ message limit; do not approve a truncated preview')
    key = f"{client.config.app_id}:{client.config.target_type}:{client.config.target_id}:{snapshot['id']}:{snapshot['digest']}"
    if not store.reserve_notification(key):
        return False
    try:
        message_id = client.send_text(text)
    except Exception:
        store.finish_notification(key)
        raise
    store.finish_notification(key, message_id)
    return True


class QQEventHandler:
    def __init__(self, config: QQBotConfig, store: QQBotStore, client: QQBotClient):
        self.config, self.store, self.client = config, store, client

    async def handle(self, event: dict) -> dict:
        message = parse_message(event)
        if message is None:
            return {'status': 'ignored'}
        if not self.store.receive_event(message['event_id']):
            return {'status': 'duplicate'}
        if message['content'] == '身份':
            # Only reveal the requesting user's own context; never self-enroll an approver.
            text = f"场景 {message['scope']}\n接收 OpenID {message['target']}\n审批者 OpenID {message['actor']}\n请由管理员在本地配置，机器人不会自动授权。"
            replied = True
            try:
                await self.reply(message, text)
            except QQBotError:
                # Receiving an identity is still useful when QQ reply permission is missing.
                replied = False
            return {'status': 'identity', 'scope': message['scope'], 'target': message['target'],
                    'actor': message['actor'], 'reply_confirmed': replied}
        if message['scope'] != self.config.target_type or message['target'] != self.config.target_id:
            return {'status': 'unauthorized_target'}
        if message['actor'] not in self.config.approvers:
            return {'status': 'unauthorized_actor'}
        if message['content'] == '候选':
            snapshots = [s for s in self.store.list_pending(limit=100)
                if s['payload'].get('qq_app_id') == self.config.app_id
                and s['payload'].get('qq_target_type') == message['scope']
                and s['payload'].get('qq_target_id') == message['target']][:5]
            if not snapshots:
                await self.reply(message, '当前没有待审批候选。')
            for seq, snapshot in enumerate(snapshots, 1):
                text = preview_text(snapshot)
                if len(text) > 1800:
                    text = '候选文本超过消息长度限制，暂不支持审批，请由管理员处理。'
                await self.reply(message, text, seq)
            return {'status': 'listed', 'count': len(snapshots)}
        parts = message['content'].split()
        if len(parts) != 3 or parts[0] not in {'批准', '批准风险', '拒绝'}:
            return {'status': 'ignored_command'}
        action, identity, digest = parts
        try:
            if self.store.get(identity)['payload'].get('qq_app_id') != self.config.app_id:
                raise ValueError('机器人已改变，需要重新准备候选')
            self.store.decide(identity, digest, actor=message['actor'], scope=message['scope'], target=message['target'],
                              approve=action != '拒绝', risk_reviewed=action == '批准风险')
            status = 'approved' if action != '拒绝' else 'rejected'
            await self.reply(message, '已记录批准，尚未提交；真实投标仍由启用后的执行器处理。' if status == 'approved' else '已拒绝该候选。')
            return {'status': status, 'approval_id': identity}
        except ValueError as exc:
            await self.reply(message, str(exc))
            return {'status': 'blocked'}

    async def reply(self, message: dict, text: str, seq=1):
        return await asyncio.to_thread(self.client.send_text, text,
            target_type=message['scope'], target_id=message['target'], msg_id=message['message_id'], msg_seq=seq)
