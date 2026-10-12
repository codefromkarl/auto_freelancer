"""Optional signed webhook receiver, independent of Freelancer credentials."""
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks

from services.qqbot_service import QQBotConfig, QQBotClient
from services.qqbot_store import QQBotStore
from services.qqbot_events import QQEventHandler, verification_response, verify_callback

app = FastAPI(title='BidMaster QQ Bot receiver')


@app.get('/health')
async def health():
    return {'status': 'healthy', 'service': 'qqbot-receiver'}


@app.post('/qqbot/callback')
async def callback(request: Request, background_tasks: BackgroundTasks):
    config = QQBotConfig.from_env()
    if not config.app_secret:
        raise HTTPException(503, 'QQ Bot is not configured')
    body = await request.body()
    if len(body) > 65536:
        raise HTTPException(413, 'QQ callback exceeds size limit')
    import json
    try:
        event = json.loads(body)
        if not isinstance(event, dict):
            raise ValueError('Invalid event')
        if event.get('op') == 13:
            return verification_response(config.app_secret, event.get('d') or {})
        verify_callback(config.app_secret, request.headers.get('X-Signature-Timestamp'),
                        request.headers.get('X-Signature-Ed25519', ''), body)
    except (ValueError, TypeError):
        raise HTTPException(401, 'Invalid QQ callback') from None
    if event.get('op') == 0:
        handler = QQEventHandler(config, QQBotStore(config.state_path), QQBotClient(config))
        background_tasks.add_task(handler.handle, event)
    return {'op': 12, 'd': 0}
