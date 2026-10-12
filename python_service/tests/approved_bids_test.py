import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from config import settings
from database.connection import Base
from database.models import Project
from services import approved_bids
from services.qqbot_service import QQBotConfig
from services.qqbot_store import QQBotStore


@pytest.fixture
def prepared(tmp_path,monkeypatch):
    config=QQBotConfig(app_id='test-app',app_secret='test-secret',target_id='operator',
        approvers=frozenset({'operator'}),state_path=str(tmp_path/'qq.db'))
    monkeypatch.setattr(QQBotConfig,'from_env',lambda:config)
    monkeypatch.setattr(approved_bids.bid_service,'check_content_risk',lambda *_:(True,'ok'))
    engine=create_engine('sqlite:///:memory:', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db=Session(engine)
    project=Project(freelancer_id=123,title='Python API',description='Build the exact approved API',
        full_description='Build the exact approved API',currency_code='USD',type_id=1,
        skills='["Python"]',budget_minimum=100,budget_maximum=700,estimated_hours=20,status='active')
    db.add(project);db.commit()
    store=QQBotStore(config.state_path)
    record=asyncio.run(approved_bids.prepare_bid(db,123,500,7,'The immutable approved proposal',store=store))
    yield db,store,record,project
    db.close();engine.dispose()


def approve(store,record):
    store.decide(record['id'],record['digest'][:16],actor='operator',scope='c2c',target='operator',approve=True,risk_reviewed=True)


def test_disabled_switch_never_submits_even_with_valid_approval(prepared,monkeypatch):
    db,store,record,_=prepared;approve(store,record)
    monkeypatch.setattr(settings,'BID_SUBMISSION_ENABLED',False)
    post=AsyncMock();monkeypatch.setattr(approved_bids.bid_service,'create_bid',post)
    with pytest.raises(ValueError,match='开关'):
        asyncio.run(approved_bids.submit_approved_bid(db,record['id'],store))
    post.assert_not_called()


def test_unapproved_or_changed_snapshot_never_submits(prepared,monkeypatch):
    db,store,record,project=prepared
    monkeypatch.setattr(settings,'BID_SUBMISSION_ENABLED',True)
    post=AsyncMock();monkeypatch.setattr(approved_bids.bid_service,'create_bid',post)
    with pytest.raises(ValueError):asyncio.run(approved_bids.submit_approved_bid(db,record['id'],store))
    approve(store,record)
    project.description='A changed project';project.full_description='A changed project';db.commit()
    with pytest.raises(ValueError,match='变化'):
        asyncio.run(approved_bids.submit_approved_bid(db,record['id'],store))
    post.assert_not_called()


def test_execution_uses_exact_approved_payload_once(prepared,monkeypatch):
    db,store,record,_=prepared;approve(store,record)
    monkeypatch.setattr(settings,'BID_SUBMISSION_ENABLED',True)
    remote={'id':123,'title':'Python API','description':'Build the exact approved API',
        'currency':{'code':'USD'},'type':'fixed','status':'active','jobs':[{'id':13,'name':'Python'}],
        'budget':{'minimum':100,'maximum':700}}
    client=SimpleNamespace(session=object(),get_project=AsyncMock(return_value=remote))
    monkeypatch.setattr(approved_bids,'get_freelancer_client',lambda:client)
    import freelancersdk.resources.users.users as users
    monkeypatch.setattr(users,'get_self',lambda *_:{'id':999,'jobs':[{'id':13}],'status':{'email_verified':True}})
    post=AsyncMock(return_value={'bid_id':456,'status':'submitted'})
    monkeypatch.setattr(approved_bids.bid_service,'create_bid',post)
    assert asyncio.run(approved_bids.submit_approved_bid(db,record['id'],store))['bid_id']==456
    assert post.call_args.args[2:]==(500.0,7,'The immutable approved proposal')
    assert store.get(record['id'])['state']=='submitted'
    with pytest.raises(ValueError):asyncio.run(approved_bids.submit_approved_bid(db,record['id'],store))
    assert post.await_count==1


def test_pending_or_approved_preview_is_reused_without_generation(prepared,monkeypatch):
    db,store,record,_=prepared;approve(store,record)
    generator=AsyncMock()
    monkeypatch.setattr(approved_bids,'get_proposal_service',lambda:SimpleNamespace(generate_proposal=generator))
    again=asyncio.run(approved_bids.prepare_bid(db,123,500,7,store=store))
    assert again['id']==record['id']
    generator.assert_not_called()


def test_limits_and_unknown_review_are_explicit(prepared):
    db,store,record,project=prepared
    assert record['payload']['review_required'] is True
    with pytest.raises(ValueError,match='金额'):
        asyncio.run(approved_bids.prepare_bid(db,123,2000,7,'Proposal',store=store))
    project.estimated_hours=50
    with pytest.raises(ValueError,match='工时'):
        asyncio.run(approved_bids.prepare_bid(db,123,500,10,'Proposal',store=store))


def test_http_prepare_qq_approve_and_disabled_submit_boundary(prepared,monkeypatch):
    from database.connection import get_db
    from main import app
    import qqbot_main
    from services.qqbot_events import signing_key
    import time
    db,store,record,_=prepared
    config=QQBotConfig.from_env()
    class Client:
        def __init__(self):self.sent=[]
        def send_text(self,text,**kwargs):self.sent.append(text);return 'mock-message'
    client=Client()
    monkeypatch.setattr(qqbot_main,'QQBotClient',lambda _:client)
    monkeypatch.setattr(settings,'BID_SUBMISSION_ENABLED',False)
    post=AsyncMock();monkeypatch.setattr(approved_bids.bid_service,'create_bid',post)
    app.dependency_overrides[get_db]=lambda:db
    try:
        api=TestClient(app);headers={'X-API-Key':'test-api-key'}
        request={'project_id':123,'amount':500,'amount_currency':'USD','period':7,
                 'description':'The immutable approved proposal'}
        assert api.post('/api/v1/approvals/prepare',json=request).status_code==401
        preview=api.post('/api/v1/approvals/prepare',json=request,headers=headers)
        assert preview.status_code==200
        assert preview.json()['data']['id']==record['id']
        assert api.post('/api/v1/bids',json=request,headers=headers).status_code==400
        event={'op':0,'t':'C2C_MESSAGE_CREATE','id':'integration-event','d':{
            'id':'integration-msg','author':{'user_openid':'operator'},
            'content':f"批准风险 {record['id']} {record['digest'][:16]}"}}
        body=json.dumps(event).encode();timestamp=str(int(time.time()))
        signature=signing_key(config.app_secret).sign(timestamp.encode()+body).hex()
        qq=TestClient(qqbot_main.app)
        response=qq.post('/qqbot/callback',content=body,headers={
            'X-Signature-Timestamp':timestamp,'X-Signature-Ed25519':signature})
        assert response.status_code==200
        read=api.get('/api/v1/approvals/'+record['id'],headers=headers)
        assert read.json()['data']['state']=='approved'
        assert read.json()['data']['submission_enabled'] is False
        request['approval_id']=record['id']
        disabled=api.post('/api/v1/bids',json=request,headers=headers)
        assert disabled.status_code==400 and '开关' in disabled.json()['detail']
        request['amount']=600
        changed=api.post('/api/v1/bids',json=request,headers=headers)
        assert changed.status_code==400 and '金额' in changed.json()['detail']
        post.assert_not_called()
    finally:
        app.dependency_overrides.clear()
