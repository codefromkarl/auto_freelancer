import asyncio
import json
import logging
import time
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

import scheduler
from config import settings
from database.connection import Base, get_db
from database.models import Project, CandidateWorkflow, WorkflowEvent, BidSubmission, Bid
from services import approved_bids, automatic_bid_policy, workflow_service as workflow
from services.scoring_policy import SCORING_VERSION, digest, policy_signature, scoring_inputs
from services.qqbot_service import QQBotConfig
from services.qqbot_store import QQBotStore, canonical_hash

TEXT = 'I will implement the API, test acceptance with the sample data, and deliver the agreed scope after credentials are supplied. Public code: https://example.com/portfolio.'


def stamp(db, project):
    project.ai_score = 8
    project.scored_at = workflow.now()
    project.score_metadata = json.dumps({'source': 'llm', 'version': SCORING_VERSION,
        'policy_hash': policy_signature(db), 'input_hash': digest(scoring_inputs(project)),
        'total': project.ai_score, 'estimated_hours': project.estimated_hours,
        'quote_usd': float(project.suggested_bid), 'clarification_questions': [],
        'model_dimensions': {'budget_efficiency':8,'competition':8,'clarity':8,'customer':8,'tech':9,'risk':7}})
    db.commit()


@pytest.fixture
def auto_bid(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'BID_APPROVAL_MODE', 'automatic')
    monkeypatch.setattr(settings, 'BID_SUBMISSION_ENABLED', True)
    config = QQBotConfig(state_path=str(tmp_path / 'snapshots.db'))
    monkeypatch.setattr(QQBotConfig, 'from_env', lambda: config)
    engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = Session(engine)
    project = Project(freelancer_id=123, title='Python API integration', type_id=1,
        description='Implement one Python API integration', full_description='Implement one Python API integration',
        skills='["Python"]', currency_code='USD', budget_minimum=100, budget_maximum=700,
        status='active', estimated_hours=10, suggested_bid=300, submitdate=str(int(time.time())),
        owner_id=111, owner_info=json.dumps({'id':111, 'status':{'payment_verified':True}}),
        bid_stats=json.dumps({'bid_count':3, 'bid_avg':300}))
    db.add(project); db.commit(); stamp(db, project)
    context = {'status':'ready', 'currency':'USD', 'total_bids':3, 'visible_count':3,
        'price_count':3, 'complete':True, 'fetched_at':None, 'valid_until':time.time()+1800,
        'price':{'median':300}, 'period':{'median':7}, 'feature_mentions':{}, 'examples':[],
        'digest':'fixture-market', '_corpus':[]}
    monkeypatch.setattr(approved_bids, 'ensure_competitor_context', AsyncMock(return_value=context))
    monkeypatch.setattr(approved_bids, 'load_competitor_context', lambda *_: context)
    monkeypatch.setattr(approved_bids.bid_service, 'check_content_risk', lambda *_:(True, 'ok'))
    remote = {'id':123, 'title':project.title, 'description':project.full_description,
        'type':'fixed', 'currency':{'code':'USD'}, 'budget':{'minimum':100, 'maximum':700},
        'status':'active', 'submitdate':project.submitdate, 'jobs':[{'id':13, 'name':'Python'}],
        'owner_id':111, 'owner_info':{'id':111, 'status':{'payment_verified':True}},
        'bid_stats':{'bid_count':3, 'bid_avg':300}}
    client = SimpleNamespace(session=object(), get_project=AsyncMock(return_value=remote),
                             get_project_bids=AsyncMock(return_value=[]))
    monkeypatch.setattr(approved_bids, 'get_freelancer_client', lambda:client)
    account = {'id':999, 'jobs':[{'id':13}], 'status':{'email_verified':True,
        'phone_verified':True, 'profile_complete':True}, 'primary_currency':{'code':'USD'},
        'account_balances':{'bids_remaining':48, 'equivalent_amount':200}}
    import freelancersdk.resources.users.users as users
    monkeypatch.setattr(users, 'get_self', lambda *_:account)
    real_create_bid = approved_bids.bid_service.create_bid
    post = AsyncMock(return_value={'bid_id':456, 'status':'submitted'})
    monkeypatch.setattr(approved_bids.bid_service, 'create_bid', post)
    store = QQBotStore(config.state_path)
    yield SimpleNamespace(db=db, project=project, store=store, context=context, client=client,
                          account=account, post=post, remote=remote, config=config, real_create_bid=real_create_bid)
    db.close(); engine.dispose()


def prepare(f):
    return asyncio.run(approved_bids.prepare_bid(f.db, 123, 300, 7, TEXT, store=f.store))


def test_automatic_exact_submission_without_qq_identity_or_approval(auto_bid):
    f=auto_bid; snapshot=prepare(f)
    assert snapshot['state']=='auto_pending' and snapshot['actor'] is None
    assert f.db.query(CandidateWorkflow).one().state=='awaiting_submission'
    assert f.store.list_pending()==[]
    with pytest.raises(ValueError):
        f.store.decide(snapshot['id'],snapshot['digest'][:16],actor='operator',scope='c2c',target='',approve=True)
    result=asyncio.run(approved_bids.submit_approved_bid(f.db,snapshot['id'],f.store))
    assert result['bid_id']==456 and f.post.call_args.args[2:]==(300.0,7,TEXT)
    saved=f.store.get(snapshot['id'])
    assert saved['state']=='submitted' and saved['actor']=='automatic_policy'
    assert saved['scope']=='automatic' and saved['risk_reviewed']==0
    assert f.db.query(WorkflowEvent).filter_by(stage='authorization',outcome='automatic').count()==1
    assert f.db.query(WorkflowEvent).filter_by(stage='approval',outcome='approved').count()==0
    with pytest.raises(ValueError):
        asyncio.run(approved_bids.submit_approved_bid(f.db,snapshot['id'],f.store))
    assert f.post.await_count==1


@pytest.mark.parametrize('change,match',[
    ('unknown_payment','付款验证未知'), ('unverified_payment','付款验证'),
    ('premium','中位数'), ('stale_market','竞标资料'),
    ('incomplete_market','竞标资料'), ('stale_score','评分'), ('missing_hours','评分'),
    ('clarifications','未解决'), ('copy_risk','竞标评估')])
def test_automatic_policy_rejects_unresolved_evidence(auto_bid, change, match, monkeypatch):
    f=auto_bid
    if change=='unknown_payment':f.project.owner_info=None;stamp(f.db,f.project)
    elif change=='unverified_payment':f.project.owner_info=json.dumps({'status':{'payment_verified':False}});stamp(f.db,f.project)
    elif change=='premium':f.context['price']['median']=155
    elif change=='partial':f.context['examples']=[{'scope':'partial_or_mock'}]
    elif change=='stale_market':f.context['status']='stale'
    elif change=='incomplete_market':f.context['complete']=False
    elif change=='stale_score':f.project.ai_score=9;f.db.commit()
    elif change=='missing_hours':f.project.estimated_hours=None;f.db.commit()
    elif change=='clarifications':
        m=json.loads(f.project.score_metadata);m['clarification_questions']=['Which domain?'];f.project.score_metadata=json.dumps(m);f.db.commit()
    elif change=='copy_risk':f.context['_corpus']=[{'bid_id':9,'text':TEXT*8}]
    with pytest.raises(ValueError,match=match):prepare(f)
    f.post.assert_not_called()


@pytest.mark.parametrize('change,match',[
    ('mode','模式'),('policy','策略'),('score','评分'),('description','content'),
    ('expired','过期'),('disabled','开关')])
def test_frozen_automatic_decision_cannot_survive_changes(auto_bid,change,match,monkeypatch):
    f=auto_bid;s=prepare(f)
    if change=='mode':monkeypatch.setattr(settings,'BID_APPROVAL_MODE','qq')
    elif change=='policy':monkeypatch.setattr(settings,'BID_MAX_ESTIMATED_HOURS',30)
    elif change=='score':f.project.ai_score=9;f.db.commit()
    elif change=='description':
        with f.store.connect() as db:db.execute('UPDATE approvals SET payload=? WHERE id=?',(json.dumps(dict(s['payload'],description='changed')),s['id']))
    elif change=='expired':s['payload']['competition_review']['benchmark']['valid_until']=time.time()-1
    elif change=='disabled':monkeypatch.setattr(settings,'BID_SUBMISSION_ENABLED',False)
    if change=='expired':
        with f.store.connect() as db:db.execute('UPDATE approvals SET payload=?,digest=? WHERE id=?',
            (json.dumps(s['payload']),canonical_hash(s['payload']),s['id']))
    with pytest.raises(ValueError,match=match):asyncio.run(approved_bids.submit_approved_bid(f.db,s['id'],f.store))
    f.post.assert_not_called()


@pytest.mark.parametrize('change', ['quota','balance','profile','skills','existing_remote','remote_scope','remote_customer'])
def test_remote_preflight_blocks_without_post(auto_bid,change):
    f=auto_bid;s=prepare(f)
    if change=='quota':f.account['account_balances']['bids_remaining']=0
    elif change=='balance':f.account['account_balances']['equivalent_amount']=0
    elif change=='profile':f.account['status']['profile_complete']=False
    elif change=='skills':f.account['jobs']=[]
    elif change=='existing_remote':f.client.get_project_bids.return_value=[{'bidder_id':999,'retracted':False}]
    elif change=='remote_scope':f.remote['description']='A different entire project'
    elif change=='remote_customer':f.remote['owner_info']=None
    with pytest.raises(ValueError):asyncio.run(approved_bids.submit_approved_bid(f.db,s['id'],f.store))
    assert f.store.get(s['id'])['state']=='blocked'
    f.post.assert_not_called()


def test_unknown_submission_is_terminal(auto_bid):
    from services.freelancer_client import FreelancerAPIError
    f=auto_bid;s=prepare(f);f.post.side_effect=FreelancerAPIError('outcome unknown',status_code=409)
    with pytest.raises(FreelancerAPIError):asyncio.run(approved_bids.submit_approved_bid(f.db,s['id'],f.store))
    assert f.store.get(s['id'])['state']=='outcome_unknown'
    with pytest.raises(ValueError):asyncio.run(approved_bids.submit_approved_bid(f.db,s['id'],f.store))
    assert f.post.await_count==1


def test_unknown_client_is_recorded_not_falsely_verified(auto_bid,monkeypatch):
    f=auto_bid
    monkeypatch.setattr(settings,'BID_AUTO_REQUIRE_VERIFIED_CLIENT_PAYMENT',False)
    f.project.owner_info=None;f.remote['owner_info']=None
    f.project.suggested_bid=200;stamp(f.db,f.project)
    s=asyncio.run(approved_bids.prepare_bid(f.db,123,200,7,TEXT,store=f.store))
    assert s['payload']['authorization']['client_payment']=='unknown'
    assert asyncio.run(approved_bids.submit_approved_bid(f.db,s['id'],f.store))['bid_id']==456
    assert f.project.owner_info is None and f.store.get(s['id'])['risk_reviewed']==0


@pytest.mark.parametrize('change',['amount','hours','unverified'])
def test_unknown_client_caps_and_explicit_negative_remain_blocking(auto_bid,monkeypatch,change):
    f=auto_bid;monkeypatch.setattr(settings,'BID_AUTO_REQUIRE_VERIFIED_CLIENT_PAYMENT',False)
    f.project.owner_info=None
    if change=='hours':f.project.estimated_hours=21
    if change=='unverified':f.project.owner_info=json.dumps({'status':{'payment_verified':False}})
    stamp(f.db,f.project)
    with pytest.raises(ValueError):prepare(f)
    f.post.assert_not_called()


def test_no_case_link_and_zero_real_competitors_do_not_require_human_approval(auto_bid):
    f=auto_bid;f.context.update(total_bids=0,visible_count=0,price_count=0,price={})
    text='I will implement the API, test acceptance with the sample data, and deliver the agreed scope after credentials are supplied.'
    s=asyncio.run(approved_bids.prepare_bid(f.db,123,300,7,text,store=f.store))
    assert s['payload']['competition_review']['review_required'] is True
    assert s['payload']['authorization']['market_sample']=='insufficient_sample'
    assert asyncio.run(approved_bids.submit_approved_bid(f.db,s['id'],f.store))['bid_id']==456


def test_competitive_quote_recalculates_economics_without_inventing_model_call(auto_bid):
    f=auto_bid;f.project.suggested_bid=400;stamp(f.db,f.project)
    s=asyncio.run(approved_bids.prepare_bid(f.db,123,400,7,TEXT,store=f.store,competitive_quote=True))
    assert s['payload']['amount']==300
    m=json.loads(f.project.score_metadata)
    assert m['pricing_adjustment']['model_quote_usd']==400
    assert m['quote_usd']==300 and m['net_hourly_usd']==27
    assert f.db.query(WorkflowEvent).filter_by(stage='score',outcome='scored').count()==0


def test_market_price_cannot_pay_whole_scope_is_rejected(auto_bid):
    f=auto_bid;f.context['price']['median']=100
    with pytest.raises(ValueError,match='最低净收益'):
        asyncio.run(approved_bids.prepare_bid(f.db,123,300,7,TEXT,store=f.store,competitive_quote=True))
    f.post.assert_not_called()


def test_low_technical_match_cannot_pass_by_quote_or_soft_score(auto_bid):
    f=auto_bid;m=json.loads(f.project.score_metadata);m['model_dimensions']['tech']=4
    f.project.score_metadata=json.dumps(m);f.db.commit()
    with pytest.raises(ValueError,match='技术匹配'):prepare(f)
    f.post.assert_not_called()


def test_invalid_terms_are_not_reassessed_until_material_or_policy_changes(auto_bid):
    f=auto_bid
    workflow.defer_evaluation(f.db,f.project,policy_signature(f.db),'Quote cannot cover the requested scope')
    f.db.commit()
    assert workflow.evaluation_allowed(f.db,f.project) is False
    f.project.bid_stats='{"bid_count":40}';f.db.commit()
    assert workflow.evaluation_allowed(f.db,f.project) is False
    f.project.budget_maximum=900;f.db.commit()
    assert workflow.evaluation_allowed(f.db,f.project) is True


def test_market_change_during_remote_checks_blocks_frozen_submission(auto_bid):
    f=auto_bid;s=prepare(f)
    async def changes_during_read(_):
        f.context['digest']='a-new-market-snapshot'
        return []
    f.client.get_project_bids.side_effect=changes_during_read
    with pytest.raises(ValueError,match='竞标对比数据已变化'):
        asyncio.run(approved_bids.submit_approved_bid(f.db,s['id'],f.store))
    f.post.assert_not_called()
    assert f.store.get(s['id'])['state']=='blocked'


def test_bid_count_change_refreshes_market_math_without_new_model_or_new_text(auto_bid):
    f=auto_bid;s=prepare(f);original_time=f.project.scored_at
    async def posted(*args,**kwargs):
        assert json.loads(f.project.score_metadata)['market_refresh']['model_calls']==0
        assert f.project.scored_at==original_time
        return {'bid_id':456,'status':'submitted'}
    f.post.side_effect=posted
    f.remote['bid_stats']={'bid_count':4,'bid_avg':300}
    assert asyncio.run(approved_bids.submit_approved_bid(f.db,s['id'],f.store))['bid_id']==456
    assert f.post.call_args.args[4]==TEXT
    assert f.project.scored_at==original_time


def test_preview_never_authorizes_or_submits_without_qq_config(auto_bid,monkeypatch):
    f=auto_bid
    @contextmanager
    def scope():yield f.db
    monkeypatch.setattr(scheduler.common,'get_db_context',scope)
    monkeypatch.setattr(approved_bids,'get_proposal_service',lambda:SimpleNamespace(
        generate_proposal=AsyncMock(return_value={'success':True,'validation_passed':True,'proposal':TEXT})))
    result=asyncio.run(scheduler._step_auto_bid([{'freelancer_id':123,'suggested_bid':300,'estimated_hours':10}],True,logging.getLogger('auto-test')))
    assert result[0]['status']=='dry_run'
    assert f.store.get(result[0]['snapshot_id'])['state']=='auto_pending'
    assert f.db.query(WorkflowEvent).filter_by(stage='authorization').count()==0
    f.post.assert_not_called()


def test_notification_failure_does_not_change_submission(auto_bid,monkeypatch):
    f=auto_bid
    @contextmanager
    def scope():yield f.db
    monkeypatch.setattr(scheduler.common,'get_db_context',scope)
    monkeypatch.setattr(approved_bids,'get_proposal_service',lambda:SimpleNamespace(
        generate_proposal=AsyncMock(return_value={'success':True,'validation_passed':True,'proposal':TEXT})))
    from services import qqbot_events
    def fail(*_):raise RuntimeError('QQ unavailable')
    monkeypatch.setattr(qqbot_events,'notify_bid_result',fail)
    result=asyncio.run(scheduler._step_auto_bid([{'freelancer_id':123,'suggested_bid':300,'estimated_hours':10}],False,logging.getLogger('auto-test')))
    assert result[0]['status']=='submitted' and f.post.await_count==1
    assert f.store.get(result[0]['snapshot_id'])['state']=='submitted'


def test_api_automatic_submission_requires_no_approval_id(auto_bid,monkeypatch):
    from main import app
    f=auto_bid
    monkeypatch.setattr(approved_bids,'get_proposal_service',lambda:SimpleNamespace(
        generate_proposal=AsyncMock(return_value={'success':True,'validation_passed':True,'proposal':TEXT})))
    app.dependency_overrides[get_db]=lambda:f.db
    try:
        api=TestClient(app);data={'project_id':123,'amount':300,'period':7,'description':TEXT}
        assert api.post('/api/v1/bids',json=data).status_code==401
        result=api.post('/api/v1/bids',json=data,headers={'X-API-Key':'test-api-key'})
        assert result.status_code==200 and result.json()['data']['bid_id']==456
    finally:app.dependency_overrides.pop(get_db,None)


def test_cli_real_automatic_mode_has_no_qq_prerequisite(auto_bid,monkeypatch):
    monkeypatch.setattr(scheduler.common,'load_env',lambda:None)
    monkeypatch.setattr(scheduler.common,'get_settings',lambda:settings)
    monkeypatch.setattr(scheduler,'_shutdown',False)
    run=AsyncMock(return_value={});monkeypatch.setattr(scheduler,'run_cycle',run)
    assert scheduler.main(['--once','--submit','--no-night-mode'])==0
    assert run.call_args.kwargs['dry_run'] is False


@pytest.mark.parametrize('outcome', ['success', 'timeout', 'incomplete_receipt'])
def test_automatic_execution_uses_real_submission_ledger(auto_bid,monkeypatch,outcome):
    f=auto_bid
    monkeypatch.setattr(approved_bids.bid_service,'create_bid',f.real_create_bid)
    monkeypatch.setattr(approved_bids.bid_service,'get_freelancer_client',lambda:f.client)
    async def platform_post(**kwargs):
        # Durable reservation is present before the simulated external side effect.
        assert f.db.query(BidSubmission).filter_by(project_freelancer_id=123).one().status=='submitting'
        assert kwargs['description']==TEXT and kwargs['amount']==300
        if outcome=='timeout':raise TimeoutError('No receipt')
        return {'id':456,'bidder_id':999} if outcome=='success' else {}
    f.client.create_bid=AsyncMock(side_effect=platform_post)
    snapshot=prepare(f)
    if outcome=='success':
        assert asyncio.run(approved_bids.submit_approved_bid(f.db,snapshot['id'],f.store))['bid_id']==456
        assert f.db.query(BidSubmission).one().status=='submitted'
        assert f.db.query(Bid).one().description==TEXT
        assert f.db.query(CandidateWorkflow).one().state=='submitted'
    else:
        from services.freelancer_client import FreelancerAPIError
        with pytest.raises(FreelancerAPIError):asyncio.run(approved_bids.submit_approved_bid(f.db,snapshot['id'],f.store))
        assert f.db.query(BidSubmission).one().status=='outcome_unknown'
        assert f.db.query(CandidateWorkflow).one().state=='outcome_unknown'
    with pytest.raises(ValueError):asyncio.run(approved_bids.submit_approved_bid(f.db,snapshot['id'],f.store))
    assert f.client.create_bid.await_count==1
