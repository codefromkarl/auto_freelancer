"""QQ outbound Gateway receiver: one event loop, bounded reconnect, no bid execution."""
import asyncio
import json
import logging
from urllib.parse import urlparse

import aiohttp

from services.qqbot_service import QQBotClient, QQBotConfig, QQBotError
from services.qqbot_store import QQBotStore
from services.qqbot_events import QQEventHandler

logger = logging.getLogger(__name__)


async def run_gateway(config: QQBotConfig, *, once_ready=False, max_reconnects=10):
    client = QQBotClient(config)
    store = QQBotStore(config.state_path)
    for attempt in range(max_reconnects + 1):
        heartbeat_task = None
        dispatch_tasks = set()
        try:
            token = await asyncio.to_thread(client.get_token)
            gateway = await asyncio.to_thread(client.gateway)
            url = gateway.get('url') or ''
            parsed = urlparse(url)
            if parsed.scheme != 'wss' or parsed.hostname not in {'api.bot.qq.com', 'api.sgroup.qq.com'}:
                raise QQBotError('QQ returned an unexpected gateway address')
            async with aiohttp.ClientSession(trust_env=False) as session:
                async with session.ws_connect(url, timeout=20, max_msg_size=65536) as ws:
                    hello = await ws.receive_json(timeout=20)
                    if hello.get('op') != 10:
                        raise QQBotError('QQ Gateway did not return Hello')
                    interval = float(hello['d']['heartbeat_interval']) / 1000
                    if not 1 <= interval <= 3600:
                        raise QQBotError('QQ heartbeat interval is invalid')
                    await ws.send_json({'op': 2, 'd': {'token': 'QQBot ' + token,
                        'intents': 1 << 25, 'shard': [0, 1]}})
                    state = {'seq': None, 'ack': True}

                    async def heartbeat():
                        while not ws.closed:
                            await asyncio.sleep(interval)
                            if not state['ack']:
                                await ws.close()
                                return
                            state['ack'] = False
                            await ws.send_json({'op': 1, 'd': state['seq']})

                    heartbeat_task = asyncio.create_task(heartbeat())
                    async for frame in ws:
                        if frame.type != aiohttp.WSMsgType.TEXT:
                            if frame.type in {aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                                break
                            continue
                        event = json.loads(frame.data)
                        if event.get('s') is not None:
                            state['seq'] = event['s']
                        op = event.get('op')
                        if op == 11:
                            state['ack'] = True
                        elif op in {7, 9}:
                            await ws.close()
                        elif op == 0:
                            if event.get('t') == 'READY':
                                print('QQ Gateway READY (authenticated; real bidding remains disabled).', flush=True)
                                if once_ready:
                                    return
                            # Keep receiving heartbeat acknowledgements while replies are in flight.
                            if len(dispatch_tasks) >= 20:
                                logger.error('QQ event queue is full; no approval or trading action taken')
                                continue
                            async def dispatch(payload):
                                fresh = QQBotConfig.from_env()
                                if fresh.app_id != config.app_id or fresh.app_secret != config.app_secret:
                                    logger.error('QQ credentials changed; restart the receiver')
                                    return
                                handler = QQEventHandler(fresh, store, client)
                                try:
                                    result = await handler.handle(payload)
                                    if result.get('status') == 'identity':
                                        print('QQ identity context:', json.dumps(result, ensure_ascii=False), flush=True)
                                except Exception as exc:
                                    logger.error('QQ event handling failed (%s); no trading action taken', type(exc).__name__)
                            task = asyncio.create_task(dispatch(event))
                            dispatch_tasks.add(task)
                            task.add_done_callback(dispatch_tasks.discard)
            raise QQBotError('QQ Gateway connection ended')
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if attempt >= max_reconnects:
                raise QQBotError(f'QQ receiver stopped after bounded reconnects ({type(exc).__name__})') from None
            logger.warning('QQ receiver reconnecting (%s), attempt %d', type(exc).__name__, attempt+1)
            await asyncio.sleep(min(30, 2 ** attempt))
        finally:
            if dispatch_tasks:
                await asyncio.gather(*dispatch_tasks, return_exceptions=True)
            if heartbeat_task:
                heartbeat_task.cancel()
                await asyncio.gather(heartbeat_task, return_exceptions=True)
