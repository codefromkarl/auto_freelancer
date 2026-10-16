import asyncio
import hashlib
import json
import os
import subprocess
import sys
import importlib.util
from contextlib import nullcontext
from pathlib import Path
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from config import settings
from database.connection import Base, get_db
from database.models import Project, AuditLog, CompetitorBidContent
from services import competitor_bid_service, approved_bids
from services.proposal_competition import (load_competitor_context, ensure_competitor_context,
    evaluate_proposal_competition, competition_prompt)
from services.proposal_service import ProposalService, ProposalConfig
from services.qqbot_service import QQBotConfig
from services.qqbot_store import QQBotStore
from services.qqbot_events import preview_text

PEER = ('Your numerical database validation should preserve source tables with read-only SQL access. '
        'I will reconcile record counts and transaction totals before checking duplicate keys and missing values. '
        'Each anomaly will be linked to its source table and primary key. Original values, proposed corrections, '
        'timestamps and rule identifiers will form a structured audit trail. My delivery includes CSV exports, '
        'a quality report and reusable validation scripts. A sample checkpoint will establish agreed thresholds '
        'before the complete batch is processed. The first batch is delivered within seven days after access '
        'and scope are confirmed. Which database engine and data dictionary will you provide?')
OURS = ('The Python implementation will process the agreed numerical batch using read-only SQL and pandas. '
        'My delivery plan starts by agreeing business rules with your team, then validates the export and '
        'reconciles the source row counts. I will record flagged rows in a timestamped audit log and keep '
        'all live tables untouched. The fixed budget is 500 USD and the period is 7 days after access is ready. '
        'The first sample is a checkpoint for your approval. Which database engine and table volumes apply?')


@pytest.fixture
def market(tmp_path, monkeypatch):
    engine=create_engine('sqlite:///:memory:',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine);db=Session(engine)
    project=Project(freelancer_id=123,title='Database Numerical Data Validation',
        description='Read-only numerical database validation with CSV exports and an audit log.',
        full_description='Read-only numerical database validation with CSV exports and an audit log.',
        currency_code='USD',type_id=1,status='active',estimated_hours=20,
        skills='["Python"]',budget_minimum=100,budget_maximum=700)
    db.add(project);db.commit()
    rows=[{'id':1,'bidder_id':101,'amount':400,'period':7,'description':PEER},
          {'id':2,'bidder_id':102,'amount':0,'period':5,'description':'SEALED_PRIVATE_TEXT','sealed':True},
          {'id':3,'bidder_id':103,'amount':1,'period':1,'description':'WITHDRAWN','retracted':True},
          {'id':4,'bidder_id':104,'amount':350,'period':6,'description':'A read-only sample with a timestamped audit report.'},
          {'id':5,'bidder_id':999,'amount':900,'period':9,'description':'OUR_ACCOUNT_TEXT'},
          {'id':6,'bidder_id':106,'amount':450,'period':8,'description':'A paid pilot with a mock outbound adapter; no live provider connection.'}]
    fetch=AsyncMock(return_value=rows)
    monkeypatch.setattr(competitor_bid_service,'get_freelancer_client',lambda:SimpleNamespace(get_project_bids=fetch))
    config=QQBotConfig(app_id='test-app',app_secret='test-secret',target_id='operator',
        approvers=frozenset({'operator'}),state_path=str(tmp_path/'qq.db'))
    monkeypatch.setattr(QQBotConfig,'from_env',lambda:config)
    yield db,project,rows,fetch,QQBotStore(config.state_path)
    db.close();engine.dispose()


def test_public_prices_privacy_and_cache_are_grounded(market):
    db,project,_,fetch,_=market
    context=asyncio.run(ensure_competitor_context(db,project))
    assert context['price']=={'min':350,'median':400,'max':450}
    assert context['visible_count']==3 and context['sealed_bids']==1
    assert context['status']=='ready'
    prompt=competition_prompt(context)
    assert 'SEALED_PRIVATE_TEXT' not in prompt and 'OUR_ACCOUNT_TEXT' not in prompt
    assert 'partial_or_mock' in prompt and 'untrusted' in prompt
    assert db.query(CompetitorBidContent).filter_by(bid_id=2).first() is None
    again=asyncio.run(ensure_competitor_context(db,project))
    assert again['digest']==context['digest'] and fetch.await_count==1


def test_visibility_changes_erase_old_prose_and_absent_bids(market):
    db,project,rows,fetch,_=market
    asyncio.run(ensure_competitor_context(db,project))
    changed=dict(rows[0],sealed=True,amount=0,description='now hidden')
    fetch.return_value=[changed]
    asyncio.run(competitor_bid_service.fetch_and_save_bids(db,123))
    assert db.query(CompetitorBidContent).filter_by(bid_id=1).first() is None
    assert db.query(CompetitorBidContent).count()==0
    assert load_competitor_context(db,project)['price']=={}


def test_stale_failed_and_changed_currency_never_look_fresh(market):
    db,project,_,fetch,_=market
    asyncio.run(ensure_competitor_context(db,project))
    audit=db.query(AuditLog).filter_by(action='competitor_snapshot').one()
    meta=json.loads(audit.response_data);meta['fetched_at']=(datetime.utcnow()-timedelta(hours=2)).isoformat()
    audit.response_data=json.dumps(meta);db.commit()
    assert load_competitor_context(db,project)['status']=='stale'
    fetch.side_effect=RuntimeError('network unavailable')
    context=asyncio.run(ensure_competitor_context(db,project))
    assert context['status']=='unavailable'
    assert evaluate_proposal_competition(project.to_dict(),OURS,500,7,context)['review_required']
    project.currency_code='EUR';db.commit()
    assert load_competitor_context(db,project)['status']=='unavailable'


def test_price_features_and_scope_gaps_do_not_silently_change_terms(market):
    db,project,_,_,_=market
    context=asyncio.run(ensure_competitor_context(db,project))
    review=evaluate_proposal_competition(project.to_dict(),OURS,500,7,context)
    assert review['premium_pct']==25 and review['amount']==500 and review['period']==7
    assert 'reusable' in review['feature_gaps']
    assert review['blocking_issues']==[] and review['review_required']
    assert any('模拟原型' in note for note in review['findings'])


def test_copy_block_is_based_on_non_requirement_prose(market):
    db,project,_,_,_=market
    context=asyncio.run(ensure_competitor_context(db,project))
    copied=evaluate_proposal_competition(project.to_dict(),PEER,500,7,context)
    assert copied['status']=='blocked' and copied['copy_matches'][0]['bid_id']==1
    original=evaluate_proposal_competition(project.to_dict(),OURS,500,7,context)
    assert original['blocking_issues']==[]


def test_invalid_snapshot_and_account_switch_do_not_create_green_context(market,monkeypatch):
    db,project,_,fetch,_=market
    fetch.return_value=[{'id':'malformed'}]
    assert asyncio.run(ensure_competitor_context(db,project))['status']=='unavailable'
    assert db.query(AuditLog).filter_by(action='competitor_snapshot',status='success').count()==0
    fetch.return_value=[]
    asyncio.run(ensure_competitor_context(db,project))
    monkeypatch.setattr(settings,'FREELANCER_USER_ID','another-account')
    assert load_competitor_context(db,project)['status']=='unavailable'


def test_competition_expiry_and_changed_market_invalidate_approved_snapshot(market,monkeypatch):
    db,project,rows,fetch,store=market
    record=asyncio.run(approved_bids.prepare_bid(db,123,500,7,OURS,store=store))
    store.decide(record['id'],record['digest'][:16],actor='operator',scope='c2c',target='operator',approve=True,risk_reviewed=True)
    monkeypatch.setattr(settings,'BID_SUBMISSION_ENABLED',True)
    post=AsyncMock();monkeypatch.setattr(approved_bids.bid_service,'create_bid',post)
    fetch.return_value=[dict(row,amount=300) if row['id']==1 else row for row in rows]
    asyncio.run(competitor_bid_service.fetch_and_save_bids(db,123))
    with pytest.raises(ValueError,match='竞标对比数据已变化'):
        asyncio.run(approved_bids.submit_approved_bid(db,record['id'],store))
    assert store.get(record['id'])['state']=='approved'
    post.assert_not_called()


def test_new_evidence_requires_new_approval_after_unknown_review(market,monkeypatch):
    from services.freelancer_client import FreelancerAPIError
    db,project,rows,fetch,store=market
    fetch.side_effect=FreelancerAPIError('Unavailable',503)
    record=asyncio.run(approved_bids.prepare_bid(db,123,500,7,OURS,store=store))
    assert record['payload']['competition_review']['benchmark']['status']=='unavailable'
    store.decide(record['id'],record['digest'][:16],actor='operator',scope='c2c',target='operator',approve=True,risk_reviewed=True)
    fetch.side_effect=None;fetch.return_value=rows
    asyncio.run(competitor_bid_service.fetch_and_save_bids(db,123))
    monkeypatch.setattr(settings,'BID_SUBMISSION_ENABLED',True)
    post=AsyncMock();monkeypatch.setattr(approved_bids.bid_service,'create_bid',post)
    with pytest.raises(ValueError,match='竞标对比数据已变化'):
        asyncio.run(approved_bids.submit_approved_bid(db,record['id'],store))
    post.assert_not_called()


def test_page_cap_is_explicitly_partial(market):
    db,project,_,fetch,_=market
    fetch.return_value=[{'id':i+1,'bidder_id':1000+i,'amount':400,'period':7,'description':'Documented delivery and acceptance tests.'} for i in range(400)]
    context=asyncio.run(ensure_competitor_context(db,project))
    assert context['total_bids']==400 and context['complete'] is False
    review=evaluate_proposal_competition(project.to_dict(),OURS,500,7,context)
    assert any('不完整' in note for note in review['findings'])


def test_http_pagination_stops_at_configured_bound(monkeypatch):
    import services.freelancer_client as client_module
    calls=[]
    class HTTP:
        def get(self,_url,**kwargs):
            calls.append(kwargs['params']['offset'])
            offset=kwargs['params']['offset']
            return SimpleNamespace(status_code=200,json=lambda:{'result':{'bids':[{'id':offset+i+1} for i in range(50)]}})
    client=client_module.FreelancerClient()
    monkeypatch.setattr(client_module._requests,'Session',lambda:HTTP())
    client._rate_limiter.acquire=AsyncMock()
    bids=asyncio.run(client.get_project_bids(123,max_pages=2))
    assert len(bids)==100 and calls==[0,50]
    with pytest.raises(ValueError):asyncio.run(client.get_project_bids(123,max_pages=0))
    assert calls==[0,50]


def test_generation_receives_reference_and_returns_matching_evaluation(market):
    db,project,_,_,_=market
    llm=SimpleNamespace(generate_proposal=AsyncMock(return_value=OURS))
    service=ProposalService(llm_client=llm,config=ProposalConfig(max_retries=1,min_length=280,max_length=1800))
    result=asyncio.run(service.generate_proposal(project,{'suggested_bid':500,'period':7},db=db))
    assert result['success'] and result['validation_passed']
    prompt=llm.generate_proposal.call_args.kwargs['user_prompt']
    assert 'COMPETITOR_REFERENCE_DATA' in prompt and '"median": 400.0' in prompt
    assert 'offered delivery period is 7' in prompt
    assert 'Do not claim the client has agreed' in prompt
    assert 'do not offer text-layer-only delivery' in prompt
    assert result['competition_review']['text_digest']==hashlib.sha256(result['proposal'].encode()).hexdigest()
    llm.generate_proposal.return_value=PEER
    blocked=asyncio.run(service.generate_proposal(project,{'suggested_bid':500,'period':7},db=db))
    assert blocked['success'] is False and blocked['proposal']==''
    assert blocked['competition_review']['blocking_issues']


def test_manual_prepare_freezes_comparison_and_unknown_legacy_is_rejected(market,monkeypatch):
    db,project,_,_,store=market
    record=asyncio.run(approved_bids.prepare_bid(db,123,500,7,OURS,store=store))
    review=record['payload']['competition_review']
    assert review['benchmark']['price']['median']==400
    assert '中位价 400 USD' in preview_text(record)
    assert '完整提案' in preview_text(record) and OURS in preview_text(record)
    with pytest.raises(ValueError,match='重合'):
        asyncio.run(approved_bids.prepare_bid(db,123,500,7,PEER,store=store))
    legacy=dict(record['payload']);legacy.pop('competition_review')
    old=store.create(legacy)
    store.decide(old['id'],old['digest'][:16],actor='operator',scope='c2c',target='operator',approve=True,risk_reviewed=True)
    monkeypatch.setattr(settings,'BID_SUBMISSION_ENABLED',True)
    post=AsyncMock();monkeypatch.setattr(approved_bids.bid_service,'create_bid',post)
    with pytest.raises(ValueError,match='评估'):
        asyncio.run(approved_bids.submit_approved_bid(db,old['id'],store))
    post.assert_not_called()


def test_evaluation_api_is_authenticated_and_does_not_create_approval(market):
    from main import app
    db,project,_,_,store=market
    app.dependency_overrides[get_db]=lambda:db
    try:
        client=TestClient(app)
        request={'project_id':123,'amount':500,'amount_currency':'USD','period':7,'description':OURS}
        assert client.post('/api/v1/proposals/evaluate',json=request).status_code==401
        response=client.post('/api/v1/proposals/evaluate',json=request,headers={'X-API-Key':'test-api-key'})
        assert response.status_code==200
        assert response.json()['data']['benchmark']['price']['median']==400
        assert response.json()['data']['content_validation_passed'] is True
        assert store.list_active()==[]
    finally:
        app.dependency_overrides.clear()


def test_qq_preview_remains_independent_of_trading_configuration(market):
    db,project,_,_,store=market
    record=asyncio.run(approved_bids.prepare_bid(db,123,500,7,OURS,store=store))
    env=dict(os.environ)
    env['PYTHONPATH']=str(Path(__file__).resolve().parents[1])
    for name in ('FREELANCER_OAUTH_TOKEN','FREELANCER_USER_ID','PYTHON_API_KEY'):
        env.pop(name,None)
    code=('import json,sys; from services.qqbot_events import preview_text; '
          'text=preview_text(json.load(sys.stdin)); assert "中位价" in text; print("preview-ok")')
    result=subprocess.run([sys.executable,'-c',code],input=json.dumps(record),text=True,
                          capture_output=True,env=env,timeout=10)
    assert result.returncode==0,result.stderr
    assert result.stdout.strip()=='preview-ok'


def test_cli_review_uses_frozen_evaluation_and_never_prints_stale_as_zero(market,monkeypatch,tmp_path):
    db,project,_,_,store=market
    asyncio.run(approved_bids.prepare_bid(db,123,500,7,OURS,store=store))
    project.ai_score=8;project.submitdate=str(datetime.now().timestamp());db.commit()
    script=Path(__file__).resolve().parents[2]/'scripts/manual_pipeline/04_review.py'
    spec=importlib.util.spec_from_file_location('competition_cli_review',script)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(module.common,'get_db_context',lambda:nullcontext(db))
    monkeypatch.setattr(module.common,'file_lock',lambda *_args,**_kwargs:nullcontext(True))
    monkeypatch.setattr(module,'policy_signature',lambda _:None)
    monkeypatch.setattr(module,'score_is_current',lambda *_:True)
    monkeypatch.setattr(module,'_refresh_remote_status_and_filter',AsyncMock(return_value=([project],0)))
    report=tmp_path/'review.md'
    assert module.main(['--threshold','7','--output',str(report)])==0
    assert '中位价 400 USD' in report.read_text()
    audit=db.query(AuditLog).filter_by(action='competitor_snapshot').one()
    meta=json.loads(audit.response_data);meta['fetched_at']=(datetime.utcnow()-timedelta(hours=2)).isoformat()
    audit.response_data=json.dumps(meta);db.commit()
    assert module.main(['--threshold','7','--output',str(report)])==0
    text=report.read_text()
    assert 'N/A (stale)' in text and 'median=unknown' in text
