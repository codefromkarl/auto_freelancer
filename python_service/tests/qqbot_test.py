import asyncio
import json
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from services.qqbot_service import QQBotClient, QQBotConfig, QQBotError
from services.qqbot_store import QQBotStore
from services.qqbot_events import QQEventHandler, signing_key, verify_callback, verification_response, notify_snapshot


@pytest.fixture
def qq(tmp_path):
    config = QQBotConfig(app_id='test-app', app_secret='test-qq-secret', target_id='operator',
                         approvers=frozenset({'operator'}), state_path=str(tmp_path/'qq.db'))
    store = QQBotStore(config.state_path)
    class Client:
        def __init__(self):
            self.config = config
            self.sent = []
        def send_text(self, text, **kwargs):
            self.sent.append((text, kwargs))
            return 'message-id'
    client = Client()
    return config, store, client


def snapshot(store, review=True):
    return store.create({'project_id':123, 'title':'Python API', 'amount':500.0, 'currency':'USD',
        'period':7, 'description':'The exact approved full proposal.', 'review_required':review,
        'qq_target_type':'c2c', 'qq_target_id':'operator', 'qq_app_id':'test-app'})


def event(record, *, actor='operator', target=None, kind='C2C_MESSAGE_CREATE', action='批准风险', suffix='one'):
    data = {'id':'msg-'+suffix, 'content':f"{action} {record['id']} {record['digest'][:16]}",
            'author':{'user_openid':actor, 'member_openid':actor}}
    if kind == 'GROUP_AT_MESSAGE_CREATE':
        data['group_openid'] = target or 'wrong-group'
    return {'op':0, 't':kind, 'id':'event-'+suffix, 'd':data}


@pytest.mark.parametrize('actor,kind', [('intruder','C2C_MESSAGE_CREATE'), ('operator','GROUP_AT_MESSAGE_CREATE')])
def test_wrong_actor_or_chat_cannot_approve(qq, actor, kind):
    config, store, client = qq
    record = snapshot(store)
    response = asyncio.run(QQEventHandler(config,store,client).handle(event(record,actor=actor,kind=kind)))
    assert response['status'].startswith('unauthorized')
    assert store.get(record['id'])['state']=='pending'
    assert client.sent==[]


def test_exact_approval_and_replay_are_separate_from_submission(qq):
    config, store, client = qq
    record = snapshot(store)
    handler = QQEventHandler(config,store,client)
    assert asyncio.run(handler.handle(event(record)))['status']=='approved'
    assert store.get(record['id'])['state']=='approved'
    assert asyncio.run(handler.handle(event(record)))['status']=='duplicate'
    assert len(client.sent)==1
    assert '尚未提交' in client.sent[0][0]


def test_identity_does_not_grant_access_even_when_reply_permission_is_missing(qq):
    config,store,client=qq
    config=replace(config,target_id='',approvers=frozenset())
    identity=event(snapshot(store),actor='new-user')
    identity['d']['content']='身份'
    def rejected(*_args,**_kwargs):raise QQBotError('Missing reply permission')
    client.send_text=rejected
    result=asyncio.run(QQEventHandler(config,store,client).handle(identity))
    assert result['status']=='identity' and result['actor']=='new-user'
    assert result['reply_confirmed'] is False
    assert config.approvers==frozenset() and config.target_id==''


def test_unknown_risk_and_bad_digest_do_not_approve(qq):
    config, store, client = qq
    record = snapshot(store)
    handler = QQEventHandler(config,store,client)
    assert asyncio.run(handler.handle(event(record,action='批准')))['status']=='blocked'
    modified = event(record,suffix='two')
    modified['d']['content'] = f"批准风险 {record['id']} 0000000000000000"
    assert asyncio.run(handler.handle(modified))['status']=='blocked'
    assert store.get(record['id'])['state']=='pending'


def test_expired_or_mutated_payload_is_not_approved(qq):
    _, store, _ = qq
    record = snapshot(store)
    with store.connect() as db:
        payload = dict(record['payload'],amount=700)
        db.execute('UPDATE approvals SET payload=? WHERE id=?',(json.dumps(payload),record['id']))
    with pytest.raises(ValueError,match='modified'):
        store.decide(record['id'],record['digest'][:16],actor='operator',scope='c2c',target='operator',approve=True,risk_reviewed=True)
    with pytest.raises(ValueError,match='modified'):
        store.get(record['id'])


def test_daily_claim_and_duplicate_submission_limit(qq):
    _, store, _ = qq
    first = snapshot(store)
    store.decide(first['id'],first['digest'][:16],actor='operator',scope='c2c',target='operator',approve=True,risk_reviewed=True)
    store.claim(first['id'],1)
    with pytest.raises(ValueError,match='approved'):
        store.claim(first['id'],1)
    second = store.create(dict(first['payload'],project_id=124))
    store.decide(second['id'],second['digest'][:16],actor='operator',scope='c2c',target='operator',approve=True,risk_reviewed=True)
    with pytest.raises(ValueError,match='Daily'):
        store.claim(second['id'],1)
    assert store.score_allowance(8,10)==8
    assert store.score_allowance(8,10)==2


def test_unlimited_scoring_keeps_usage_after_previous_daily_cap(qq):
    _,store,_=qq
    assert store.score_allowance(20,20)==20
    assert store.score_allowance(5,20)==0
    assert store.score_allowance(7,0)==7
    assert store.score_allowance(4,0)==4
    with store.connect() as db:
        assert db.execute("SELECT count FROM usage WHERE kind='scores'").fetchone()['count']==31
    with pytest.raises(ValueError):store.score_allowance(1,-1)


def test_notification_success_is_confirmed_and_unknown_delivery_is_not_retried(qq):
    _, store, client = qq
    record = snapshot(store)
    assert notify_snapshot(client,store,record) is True
    assert notify_snapshot(client,store,record) is False
    other = store.create(dict(record['payload'],project_id=124))
    def lost(*_args,**_kwargs):raise QQBotError('outcome unknown')
    client.send_text=lost
    with pytest.raises(QQBotError):notify_snapshot(client,store,other)
    assert notify_snapshot(client,store,other) is False


def test_unlimited_daily_cap_keeps_counting_and_blocks_duplicate_claims(qq):
    _,store,_=qq
    first=snapshot(store)
    store.decide(first['id'],first['digest'][:16],actor='operator',scope='c2c',target='operator',approve=True,risk_reviewed=True)
    store.claim(first['id'],1)
    second=store.create(dict(first['payload'],project_id=124))
    store.decide(second['id'],second['digest'][:16],actor='operator',scope='c2c',target='operator',approve=True,risk_reviewed=True)
    with pytest.raises(ValueError,match='Daily'):
        store.claim(second['id'],1)
    store.claim(second['id'],0)
    third=store.create(dict(first['payload'],project_id=125))
    store.decide(third['id'],third['digest'][:16],actor='operator',scope='c2c',target='operator',approve=True,risk_reviewed=True)
    store.claim(third['id'],0)
    with store.connect() as db:
        assert db.execute("SELECT count FROM usage WHERE kind='bids'").fetchone()[0]==3
    with pytest.raises(ValueError,match='approved'):
        store.claim(second['id'],0)


def test_unlimited_mode_still_requires_approval_and_valid_configuration(qq):
    _,store,_=qq
    record=snapshot(store)
    with pytest.raises(ValueError,match='approved'):
        store.claim(record['id'],0)
    with pytest.raises(ValueError,match='zero'):
        store.claim(record['id'],-1)
    store.decide(record['id'],record['digest'][:16],actor='operator',scope='c2c',target='operator',approve=True,risk_reviewed=True)
    with store.connect() as db:
        db.execute('UPDATE approvals SET expires_at=? WHERE id=?',(time.time()-1,record['id']))
    with pytest.raises(ValueError,match='approved'):
        store.claim(record['id'],0)


def test_expired_candidate_requires_new_approval_and_can_notify_again(qq):
    _, store, client = qq
    record = snapshot(store)
    assert notify_snapshot(client,store,record)
    with store.connect() as db:
        db.execute('UPDATE approvals SET expires_at=? WHERE id=?',(time.time()-1,record['id']))
    with pytest.raises(ValueError,match='expired'):
        store.decide(record['id'],record['digest'][:16],actor='operator',scope='c2c',target='operator',approve=True,risk_reviewed=True)
    new = snapshot(store)
    assert new['id'] != record['id']
    assert new['digest'] == record['digest']
    assert notify_snapshot(client,store,new)


def test_changed_bot_or_destination_never_exposes_old_candidate(qq):
    config, store, client = qq
    old = snapshot(store)
    with store.connect() as db:
        db.execute('DELETE FROM approvals WHERE id=?',(old['id'],))
    old = store.create(dict(old['payload'],qq_app_id='old-app'))
    with pytest.raises(ValueError,match='destination'):
        notify_snapshot(client,store,old)
    assert client.sent==[]
    handler = QQEventHandler(config,store,client)
    listed = event(old,suffix='list')
    listed['d']['content']='候选'
    assert asyncio.run(handler.handle(listed))['count']==0
    assert 'full proposal' not in client.sent[0][0]
    assert asyncio.run(handler.handle(event(old)))['status']=='blocked'
    assert store.get(old['id'])['state']=='pending'


def test_signed_callbacks_require_original_body_and_fresh_timestamp():
    secret='test-qq-secret';timestamp=str(int(time.time()));body=b'{"op":0,"d":{}}'
    signature=signing_key(secret).sign(timestamp.encode()+body).hex()
    verify_callback(secret,timestamp,signature,body)
    with pytest.raises(ValueError):verify_callback(secret,timestamp,signature,body+b' ')
    with pytest.raises(ValueError):verify_callback(secret,str(int(time.time())-301),signature,body)
    with pytest.raises(ValueError):verification_response(secret,{'plain_token':'{"op":0}', 'event_ts':timestamp})
    answer=verification_response(secret,{'plain_token':'challenge-token','event_ts':timestamp})
    signing_key(secret).public_key().verify(bytes.fromhex(answer['signature']),(timestamp+'challenge-token').encode())


def test_webhook_rejects_unsigned_approval_without_api_key_bypass(monkeypatch,qq):
    import qqbot_main
    config, store, client = qq
    monkeypatch.setattr(qqbot_main.QQBotConfig,'from_env',lambda:config)
    monkeypatch.setattr(qqbot_main,'QQBotClient',lambda _:client)
    record=snapshot(store)
    testclient=TestClient(qqbot_main.app)
    body=json.dumps(event(record)).encode()
    assert testclient.post('/qqbot/callback',content=body).status_code==401
    timestamp=str(int(time.time()));signature=signing_key(config.app_secret).sign(timestamp.encode()+body).hex()
    response=testclient.post('/qqbot/callback',content=body,headers={'X-Signature-Timestamp':timestamp,'X-Signature-Ed25519':signature})
    assert response.status_code==200
    assert store.get(record['id'])['state']=='approved'


def test_token_cache_and_api_contract_do_not_expose_secret():
    class Response:
        status_code=200
        def __init__(self,data):self.data=data
        def json(self):return self.data
    class Session:
        def __init__(self):self.calls=[]
        def request(self,method,url,**kwargs):
            self.calls.append((method,url,kwargs))
            return Response({'access_token':'test-access','expires_in':7200}) if url.endswith('getAppAccessToken') else Response({'id':'message'})
    session=Session();config=QQBotConfig(app_id='test-app',app_secret='test-secret',target_id='operator')
    client=QQBotClient(config,session)
    assert client.get_token()=='test-access'
    assert client.get_token()=='test-access'
    assert len(session.calls)==1
    assert client.send_text('Test',msg_id='inbound')=='message'
    call=session.calls[-1]
    assert '/v2/users/operator/messages' in call[1]
    assert call[2]['headers']['Authorization']=='QQBot test-access'
    assert call[2]['json']['msg_id']=='inbound'
    assert 'test-secret' not in repr(config)
